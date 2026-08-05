"""Metadata extraction and document hierarchy helpers for Liorin knowledge data."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retrieval.filters import KNOWN_RETRIEVAL_PERMISSIONS

ERROR_CONTEXT_PATTERN = re.compile(
    r"(?:错误码|故障码|报错|错误|error|err|code)[：:\s]*([A-Z]{1,8}[-_ ]?\d{2,6}[A-Z0-9-]*)",
    re.IGNORECASE,
)
ERROR_PREFIX_PATTERN = re.compile(r"\b(?:ERR|ERROR|E)[-_ ]?\d{2,6}\b", re.IGNORECASE)
PRODUCT_MODEL_CONTEXT_PATTERN = re.compile(
    r"(?:型号|model|设备|产品)[：:\s]*([A-Z]{1,8}[-_ ]?\d{2,6}[A-Z0-9-]*)",
    re.IGNORECASE,
)
PRODUCT_MODEL_PATTERN = re.compile(
    r"\b(?!ERR\b|ERROR\b|E[-_ ]?\d)[A-Z]{2,8}[-_ ]?\d{2,6}[A-Z0-9-]*\b",
    re.IGNORECASE,
)
ORDER_ID_PATTERN = re.compile(r"\bORD-\d{4}-\d{5,}\b", re.IGNORECASE)
TICKET_ID_PATTERN = re.compile(r"\bTCK-\d{4}-\d{5,}\b", re.IGNORECASE)
CUSTOMER_ID_PATTERN = re.compile(r"\bCUST-\d{3,}\b", re.IGNORECASE)
DOCUMENT_ID_PATTERN = re.compile(r"\bDOC-[A-Z0-9-]{3,}\b", re.IGNORECASE)
POLICY_ID_PATTERN = re.compile(r"\bPOL-[A-Z0-9-]{3,}\b", re.IGNORECASE)
PRODUCT_ID_PATTERN = re.compile(r"\b(?:LIO-)?PROD-\d{3,}\b", re.IGNORECASE)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


UNICODE_ESCAPE_PATTERN = re.compile(r"#U([0-9A-Fa-f]{4,6})")


def decode_escaped_filename(value: str) -> str:
    """Decode repository-safe ``#UXXXX`` filename escapes used by the corpus."""
    return UNICODE_ESCAPE_PATTERN.sub(lambda match: chr(int(match.group(1), 16)), value)

SECTION_TYPE_KEYWORDS = {
    "troubleshooting": ["故障", "排查", "错误", "异常", "报错", "问题", "troubleshooting"],
    "maintenance": ["维护", "保养", "清洁", "更换", "复位", "滤芯", "maintenance"],
    "setup": ["安装", "设置", "连接", "配对", "接线", "setup", "install"],
    "spec": ["规格", "参数", "技术", "specification", "spec"],
    "safety": ["安全", "警告", "注意", "危险", "warning", "safety"],
    "warranty": ["质保", "保修", "warranty"],
    "return": ["退货", "退换货", "return"],
    "refund": ["退款", "refund"],
    "shipping": ["物流", "配送", "发货", "shipping"],
    "repair": ["维修", "工单", "repair"],
    "faq": ["常见问题", "FAQ", "faq"],
}


def normalize_entity(value: str) -> str:
    return value.replace(" ", "").replace("_", "-").strip().upper()


def infer_language(text: str) -> str:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    ascii_letters = len(re.findall(r"[A-Za-z]", text))
    if chinese_chars and ascii_letters:
        return "zh-CN" if chinese_chars >= ascii_letters / 2 else "mixed"
    return "zh-CN" if chinese_chars else "en"


def infer_section_type(text: str, section: str | None = None) -> str:
    haystack = f"{section or ''}\n{text[:800]}".lower()
    for section_type, keywords in SECTION_TYPE_KEYWORDS.items():
        if any(keyword.lower() in haystack for keyword in keywords):
            return section_type
    return "general"


def extract_error_codes(text: str) -> list[str]:
    codes: list[str] = []
    for pattern in (ERROR_CONTEXT_PATTERN, ERROR_PREFIX_PATTERN):
        for match in pattern.finditer(text):
            value = match.group(1) if match.lastindex else match.group(0)
            codes.append(normalize_entity(value))
    return list(dict.fromkeys(codes))


def extract_product_models(text: str) -> list[str]:
    error_codes = set(extract_error_codes(text))
    values: list[str] = []
    for pattern in (PRODUCT_MODEL_CONTEXT_PATTERN, PRODUCT_MODEL_PATTERN):
        for match in pattern.finditer(text):
            value = normalize_entity(match.group(1) if match.lastindex else match.group(0))
            if value in error_codes or value.startswith(
                ("LIO-", "PROD-", "ERR-", "ERROR-", "E-", "ORD-", "TCK-", "CUST-", "DOC-", "POL-")
            ):
                continue
            values.append(value)
    return list(dict.fromkeys(values))


def extract_product_model(text: str) -> str | None:
    """Compatibility alias returning the first extracted product model."""

    values = extract_product_models(text)
    return values[0] if values else None


def extract_business_entities(text: str) -> dict[str, list[str]]:
    patterns = {
        "order_id": ORDER_ID_PATTERN,
        "ticket_id": TICKET_ID_PATTERN,
        "customer_id": CUSTOMER_ID_PATTERN,
        "document_id": DOCUMENT_ID_PATTERN,
        "policy_id": POLICY_ID_PATTERN,
        "product_id": PRODUCT_ID_PATTERN,
    }
    entities: dict[str, list[str]] = {
        "product_model": extract_product_models(text),
        "error_code": extract_error_codes(text),
    }
    for field, pattern in patterns.items():
        values = [normalize_entity(match.group(0)) for match in pattern.finditer(text)]
        if values:
            entities[field] = list(dict.fromkeys(values))
    return {field: values for field, values in entities.items() if values}


def nearest_heading(text: str, start_index: int | None) -> str | None:
    if start_index is None:
        match = HEADING_PATTERN.search(text)
        return match.group(2).strip() if match else None
    headings = [match for match in HEADING_PATTERN.finditer(text) if match.start() <= start_index]
    return headings[-1].group(2).strip() if headings else None


def _file_version(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()
    return digest[:12]


def metadata_time_epoch(value: Any) -> int:
    """Convert optional ISO metadata dates to UTC epoch seconds; 0 means unbounded."""

    if value in (None, ""):
        return 0
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text[:10])
            except ValueError:
                return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def base_metadata_for_file(
    path: Path,
    doc_type: str,
    text: str,
    *,
    front_matter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build document-level metadata without fabricating business dates/regions."""

    front_matter = front_matter or {}
    decoded_name = decode_escaped_filename(path.name)
    decoded_stem = Path(decoded_name).stem
    document_id = str(front_matter.get("document_id") or front_matter.get("doc_id") or decoded_stem)
    effective_from = front_matter.get("effective_from") or front_matter.get("effective_date")
    effective_to = front_matter.get("effective_to")
    required_permissions = list(front_matter.get("required_permissions") or [])
    unknown_permissions = set(required_permissions) - KNOWN_RETRIEVAL_PERMISSIONS
    if unknown_permissions:
        raise ValueError(
            f"unknown retrieval permissions in {path.name}: {sorted(unknown_permissions)}"
        )
    classification = str(front_matter.get("classification") or "public")
    tenant_id = str(front_matter.get("tenant_id") or ("public" if classification == "public" else "default"))
    visibility = str(front_matter.get("visibility") or ("public" if tenant_id in {"public", "global"} and classification == "public" else "tenant"))
    metadata: dict[str, Any] = {
        "document_id": document_id,
        "doc_id": document_id,  # compatibility alias
        "doc_type": doc_type,
        "source": doc_type,
        "source_file": decoded_name,
        "language": front_matter.get("language") or infer_language(text),
        "version": str(front_matter.get("version") or _file_version(path)),
        "effective_from": effective_from,
        "effective_to": effective_to,
        "effective_from_ts": metadata_time_epoch(effective_from),
        "effective_to_ts": metadata_time_epoch(effective_to),
        "tenant_id": tenant_id,
        "allowed_user_ids": list(front_matter.get("allowed_user_ids") or []),
        "allowed_groups": list(front_matter.get("allowed_groups") or []),
        "required_permissions": required_permissions,
        "classification": classification,
        "visibility": visibility,
        "owner": front_matter.get("owner"),
        "source_trust": str(front_matter.get("source_trust") or "trusted_repository"),
        "acl_identity_public": not bool(
            front_matter.get("allowed_user_ids") or front_matter.get("allowed_groups")
        ),
        "active": bool(front_matter.get("active", True)),
        "region": front_matter.get("region"),
    }
    if doc_type == "manual":
        product_id, _, manual_name = decoded_stem.partition("_")
        metadata.update(
            {
                "product_id": front_matter.get("product_id") or product_id,
                "product_name": front_matter.get("product_name") or manual_name.removesuffix("手册"),
                "manual_name": front_matter.get("manual_name") or manual_name or decoded_stem,
                "product_models": front_matter.get("product_models") or extract_product_models(text),
            }
        )
        if metadata["product_models"]:
            metadata["product_model"] = metadata["product_models"][0]
    elif doc_type == "policy":
        metadata.update(
            {
                "policy_id": front_matter.get("policy_id") or document_id,
                "policy_name": front_matter.get("policy_name") or decoded_stem,
                "policy_type": front_matter.get("policy_type") or infer_section_type(text),
            }
        )
    elif doc_type == "faq":
        metadata.update(
            {
                "faq_name": front_matter.get("faq_name") or decoded_stem,
                "section_type": "faq",
            }
        )
    return metadata


def section_identifier(document_id: str, section_path: str, start: int) -> str:
    digest = hashlib.sha1(f"{document_id}|{section_path}|{start}".encode("utf-8")).hexdigest()[:12]
    return f"{document_id}:sec:{digest}"


def chunk_identifier(section_id: str, chunk_index: int) -> str:
    return f"{section_id}:chunk:{chunk_index:05d}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
