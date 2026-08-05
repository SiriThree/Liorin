"""Security controls shared by ingestion, retrieval, prompts and observability.

This module intentionally contains no model or vector-store dependency.  It is the
single implementation for PII redaction, stable identity hashing, document safety
scanning and evidence-as-data isolation used by production and benchmark code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import html
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

ALLOWED_DOCUMENT_EXTENSIONS = frozenset({".md", ".txt", ".pdf"})
DEFAULT_MAX_DOCUMENT_BYTES = int(os.getenv("LIORIN_MAX_DOCUMENT_BYTES", str(8 * 1024 * 1024)))
SECURITY_HASH_SALT = os.getenv("LIORIN_SECURITY_HASH_SALT", "liorin-local-dev-salt")

_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_ADDRESS = re.compile(
    r"(?i)(?:地址|address)\s*[：:]?\s*[^\n,，;；]{6,120}|"
    r"\b\d{1,6}\s+[A-Za-z0-9 .'-]+\s(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln)\b"
)
_CUSTOMER_ID = re.compile(r"(?i)\bCUST-\d{3,}\b")
_ORDER_ID = re.compile(r"(?i)\bORD-\d{4}-\d{5,}\b")
_TICKET_ID = re.compile(r"(?i)\bTCK-\d{4}-\d{5,}\b")
_CREDENTIAL = re.compile(
    r"(?i)\b(?:api[_ -]?key|access[_ -]?token|secret|password|passwd|身份证|identity credential)\b"
    r"\s*[=:：]\s*[^\s,，;；]{6,}"
)

PII_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("email", _EMAIL, "[REDACTED_EMAIL]"),
    ("phone", _PHONE, "[REDACTED_PHONE]"),
    ("address", _ADDRESS, "[REDACTED_ADDRESS]"),
    ("customer_id", _CUSTOMER_ID, "[REDACTED_CUSTOMER_ID]"),
    ("order_id", _ORDER_ID, "[REDACTED_ORDER_ID]"),
    ("ticket_id", _TICKET_ID, "[REDACTED_TICKET_ID]"),
    ("credential", _CREDENTIAL, "[REDACTED_CREDENTIAL]"),
)

# Rules deliberately cover different attack surfaces.  A prompt sentence alone is
# not considered a security boundary; high-risk findings quarantine the document.
INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("instruction_override", re.compile(r"(?i)(ignore|disregard|forget).{0,40}(system|previous|developer).{0,40}(prompt|instruction)"), 4),
    ("chinese_instruction_override", re.compile(r"(?:忽略|无视|绕过).{0,30}(?:系统|开发者|之前).{0,20}(?:提示|指令)"), 4),
    ("data_exfiltration", re.compile(r"(?i)(send|export|reveal|print|泄露|发送|导出).{0,50}(all|所有).{0,30}(customer|tenant|客户|租户|secret|密钥|数据)"), 5),
    ("tool_impersonation", re.compile(r"(?i)(call_tool|tool_call|function_call|execute\s+sql|运行工具|调用工具)\s*[:=(]"), 4),
    ("system_role_forgery", re.compile(r"(?im)^\s*(system|developer|assistant)\s*[:：]|<\|(?:system|assistant)\|>"), 3),
    ("hidden_html", re.compile(r"(?is)<(?:script|iframe|object|embed)\b|style\s*=\s*['\"][^'\"]*(?:display\s*:\s*none|font-size\s*:\s*0|opacity\s*:\s*0)"), 5),
    ("markdown_hidden_link", re.compile(r"(?is)\[[^\]]{0,40}\]\((?:javascript|data):"), 5),
)


@dataclass(frozen=True)
class SecurityFinding:
    finding_type: str
    severity: str
    rule_id: str
    excerpt_hash: str


@dataclass
class DocumentSecurityAssessment:
    status: str = "safe"  # safe | review | quarantined | parse_failed
    risk_score: int = 0
    source_trust: str = "unverified"
    findings: list[SecurityFinding] = field(default_factory=list)
    pii_types: list[str] = field(default_factory=list)

    @property
    def is_retrievable(self) -> bool:
        return self.status in {"safe", "review"}

    def to_metadata(self) -> dict[str, Any]:
        return {
            "security_status": self.status,
            "prompt_injection_risk": self.risk_score,
            "source_trust": self.source_trust,
            "security_finding_types": [item.finding_type for item in self.findings],
            "contains_pii_types": list(self.pii_types),
        }


def hash_identifier(value: Any, *, namespace: str = "identity") -> str:
    """Return a deterministic, non-reversible identifier suitable for logs."""

    text = str(value or "")
    material = f"{SECURITY_HASH_SALT}|{namespace}|{text}".encode("utf-8")
    return sha256(material).hexdigest()[:20]


def redact_text(value: Any, *, keep_business_ids: bool = False, limit: int | None = None) -> str:
    """Redact supported PII categories from arbitrary free text.

    Business identifiers may remain in LLM evidence when the authorized user asked
    for them, but they are always redacted from trace/log payloads.
    """

    text = str(value or "")
    for pii_type, pattern, replacement in PII_PATTERNS:
        if keep_business_ids and pii_type in {"customer_id", "order_id", "ticket_id"}:
            continue
        text = pattern.sub(replacement, text)
    return text[:limit] if limit is not None else text


def pii_types(value: Any) -> list[str]:
    text = str(value or "")
    return [name for name, pattern, _replacement in PII_PATTERNS if pattern.search(text)]


def sanitize_for_log(value: Any, *, key: str | None = None) -> Any:
    """Recursively remove PII and raw identities from structured trace payloads."""

    sensitive_keys = {
        "user_id", "tenant_id", "owner", "principal", "principal_id", "customer_id", "order_id", "ticket_id",
        "email", "phone", "address", "tracking_number", "credential", "token", "api_key",
        "query", "original_query", "normalized_query", "page_content", "parent_context",
        "filter_expression", "filters", "allowed_user_ids", "allowed_groups",
    }
    if key and key.casefold() in sensitive_keys:
        if key.casefold() in {"query", "original_query", "normalized_query", "page_content", "parent_context"}:
            return redact_text(value, limit=240)
        return f"hash:{hash_identifier(value, namespace=key.casefold())}"
    if isinstance(value, dict):
        return {str(k): sanitize_for_log(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_log(item, key=key) for item in value]
    if isinstance(value, str):
        return redact_text(value, limit=500)
    return value


def scan_document_content(text: str, *, source_trust: str = "unverified") -> DocumentSecurityAssessment:
    findings: list[SecurityFinding] = []
    score = 0
    for rule_id, pattern, weight in INJECTION_PATTERNS:
        for match in pattern.finditer(text):
            excerpt = match.group(0)[:240]
            score += weight
            findings.append(
                SecurityFinding(
                    finding_type="prompt_injection",
                    severity="high" if weight >= 4 else "medium",
                    rule_id=rule_id,
                    excerpt_hash=hash_identifier(excerpt, namespace="security_excerpt"),
                )
            )
    detected_pii = pii_types(text)
    status = "safe"
    if score >= 5 or any(item.rule_id in {"data_exfiltration", "hidden_html", "markdown_hidden_link"} for item in findings):
        status = "quarantined"
    elif score > 0:
        status = "review"
    return DocumentSecurityAssessment(
        status=status,
        risk_score=score,
        source_trust=source_trust,
        findings=findings,
        pii_types=detected_pii,
    )


def validate_document_file(path: Path, *, max_bytes: int = DEFAULT_MAX_DOCUMENT_BYTES) -> None:
    suffix = path.suffix.casefold()
    if suffix not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValueError(f"unsupported document type: {suffix or '<none>'}")
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"document exceeds maximum size: {size} > {max_bytes}")


def mark_document_security(metadata: dict[str, Any], text: str) -> DocumentSecurityAssessment:
    source_trust = str(metadata.get("source_trust") or "unverified")
    assessment = scan_document_content(text, source_trust=source_trust)
    metadata.update(assessment.to_metadata())
    if assessment.status == "quarantined":
        metadata["active"] = False
    return assessment


def evidence_data_block(text: str, *, evidence_id: str, max_chars: int = 4000) -> str:
    """Wrap evidence as inert data and neutralize active markup.

    This does not replace ACL/tool enforcement.  It prevents accidental role/HTML
    interpretation and gives the answer prompt an explicit data boundary.
    """

    safe = redact_text(text, keep_business_ids=True, limit=max_chars)
    safe = html.escape(safe, quote=False)
    return f'<retrieved_evidence id="{html.escape(evidence_id)}">\n{safe}\n</retrieved_evidence>'


def write_quarantine_record(path: Path, assessment: DocumentSecurityAssessment, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "document_hash": hash_identifier(str(path.resolve()), namespace="document_path"),
        "file_name": path.name,
        "status": assessment.status,
        "risk_score": assessment.risk_score,
        "source_trust": assessment.source_trust,
        "finding_rules": [item.rule_id for item in assessment.findings],
    }
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
