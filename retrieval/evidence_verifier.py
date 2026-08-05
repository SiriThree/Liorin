"""Requirement-, authority-, validity- and conflict-aware Evidence Verifier.

This module is the single production verifier used by ``agents.knowledge_agent``.
It is deterministic and rule-driven by ``verification_policy.json``.  It does not
call an LLM and never relies on benchmark gold labels.  The outputs are protocol
objects that can be checkpointed and evaluated by the benchmark adapter.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from retrieval.filters import document_matches_filters
from retrieval.protocols import (
    DuplicateEvidenceGroup,
    EvidenceAudit,
    EvidenceConflict,
    EvidenceValidity,
    QueryUnderstanding,
    RequirementCoverage,
    RetrievalFilters,
    RetrievalPlan,
    RetrievalPrincipal,
    RetrievalResponse,
    RetrievalStatus,
    RetrievalSubquery,
    SourceAuthorityAssessment,
    VerificationAction,
    VerificationDecision,
)

_POLICY_PATH = Path(__file__).with_name("verification_policy.json")
_TOKEN_PATTERN = re.compile(r"[A-Za-z]+[A-Za-z0-9_-]*|\d+(?:\.\d+)?|[\u4e00-\u9fff]{2,}")
_NUMERIC_FACT_PATTERN = re.compile(
    r"(?P<key>退款到账|检测周期|维修周期|维修时长|保修期限|质保期限|退货期限|换货期限|响应时间|复位时长)"
    r".{0,12}?(?P<value>\d+(?:\.\d+)?\s*(?:秒|分钟|小时|天|日|个?月|年|元|%|工作日))"
)
_BOOLEAN_PATTERNS = {
    "免费维修": (re.compile(r"(?:可以|支持|符合|享受|提供).{0,8}免费维修|免费维修.{0,8}(?:可以|支持|适用)"),
                 re.compile(r"(?:不可以|不支持|不符合|不享受|不可|不能).{0,8}免费维修|免费维修.{0,8}(?:不适用|不支持|不可)")),
    "支持退货": (re.compile(r"(?:支持|可以|允许).{0,8}退货"), re.compile(r"(?:不支持|不可以|不允许|不可).{0,8}退货")),
    "支持退款": (re.compile(r"(?:支持|可以|允许).{0,8}退款"), re.compile(r"(?:不支持|不可以|不允许|不可).{0,8}退款")),
}


@dataclass(frozen=True)
class RequirementRule:
    requirement_type: str
    patterns: tuple[str, ...]
    evidence_patterns: tuple[str, ...]
    preferred_sources: tuple[str, ...]
    acceptable_sources: tuple[str, ...]
    authority_threshold: float
    authority_required: bool
    critical: bool
    needs_product: bool = False
    needs_region: bool = False
    temporal_required: bool = False


@dataclass
class VerificationResult:
    audit: EvidenceAudit
    decision: VerificationDecision
    representative_evidences: list[dict[str, Any]]


@lru_cache(maxsize=1)
def load_verification_policy() -> dict[str, Any]:
    return json.loads(_POLICY_PATH.read_text(encoding="utf-8"))


def clear_verification_policy_cache() -> None:
    load_verification_policy.cache_clear()


def _rules() -> list[RequirementRule]:
    rows = load_verification_policy()["requirement_rules"]
    return [
        RequirementRule(
            requirement_type=row["type"],
            patterns=tuple(row.get("patterns", [])),
            evidence_patterns=tuple(row.get("evidence_patterns", [])),
            preferred_sources=tuple(row.get("preferred_sources", [])),
            acceptable_sources=tuple(row.get("acceptable_sources", [])),
            authority_threshold=float(row.get("authority_threshold", 0.0)),
            authority_required=bool(row.get("authority_required", False)),
            critical=bool(row.get("critical", True)),
            needs_product=bool(row.get("needs_product", False)),
            needs_region=bool(row.get("needs_region", False)),
            temporal_required=bool(row.get("temporal_required", False)),
        )
        for row in rows
    ]


def classify_requirement(requirement: str) -> RequirementRule:
    text = requirement.lower()
    for rule in _rules():
        if rule.requirement_type != "general" and any(pattern.lower() in text for pattern in rule.patterns):
            return rule
    return next(rule for rule in _rules() if rule.requirement_type == "general")


def evidence_id(evidence: dict[str, Any], fallback: int = 0) -> str:
    metadata = evidence["document"].metadata
    return str(
        evidence.get("citation_id")
        or metadata.get("chunk_id")
        or metadata.get("section_id")
        or metadata.get("document_id")
        or f"evidence-{fallback}"
    )


def _source_type(evidence: dict[str, Any]) -> str:
    metadata = evidence["document"].metadata
    value = str(
        evidence.get("source_type")
        or metadata.get("source")
        or metadata.get("doc_type")
        or "unknown"
    ).lower()
    aliases = {
        "database": "structured_db",
        "structured_database": "structured_db",
        "ticket": "ticket_history",
        "historical_ticket": "ticket_history",
    }
    return aliases.get(value, value)


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_values(value: Any) -> set[str]:
    if value in (None, ""):
        return set()
    rows = value if isinstance(value, (list, tuple, set)) else [value]
    return {
        str(row).strip().upper()
        for row in rows
        if row not in (None, "") and str(row).strip()
    }


def assess_validity(
    evidence: dict[str, Any],
    understanding: QueryUnderstanding,
    *,
    now: datetime | None = None,
) -> EvidenceValidity:
    metadata = evidence["document"].metadata
    eid = evidence_id(evidence)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reasons: list[str] = []
    active = bool(metadata.get("is_active", metadata.get("active", True)))
    effective_from = _parse_datetime(metadata.get("effective_from") or metadata.get("effective_date"))
    effective_to = _parse_datetime(metadata.get("effective_to"))
    superseded_by = metadata.get("superseded_by")
    if not active:
        reasons.append("evidence is inactive")
    if effective_from and effective_from > now:
        active = False
        reasons.append("evidence is not yet effective")
    if effective_to and effective_to < now:
        active = False
        reasons.append("evidence has expired")
    if superseded_by:
        active = False
        reasons.append(f"evidence superseded by {superseded_by}")

    requested_region = (understanding.region or "").strip().upper()
    evidence_regions = _as_values(metadata.get("region") or metadata.get("regions"))
    global_regions = {"GLOBAL", "ALL", "*", "通用"}
    region_information_complete = bool(evidence_regions)
    region_compatible = not requested_region or not evidence_regions or bool(
        requested_region in evidence_regions or evidence_regions & global_regions
    )
    if not region_compatible:
        reasons.append("evidence region does not match query region")

    requested_products = _as_values(
        [understanding.product_id, understanding.product_name, *understanding.product_models]
    )
    evidence_products = _as_values(
        [
            metadata.get("product_id"),
            metadata.get("product_name"),
            metadata.get("product_model"),
            *(metadata.get("product_models") or []),
            *(metadata.get("product_ids") or []),
        ]
    )
    product_information_complete = bool(evidence_products)
    product_compatible = not requested_products or not evidence_products or bool(
        requested_products & evidence_products
    )
    if not product_compatible:
        reasons.append("evidence product/model does not match query")

    requested_product_versions = _as_values(understanding.product_version)
    evidence_product_versions = _as_values(
        [
            metadata.get("product_version"),
            metadata.get("firmware_version"),
            *(metadata.get("product_versions") or []),
            *(metadata.get("supported_product_versions") or []),
        ]
    )
    product_version_compatible = not requested_product_versions or bool(
        evidence_product_versions and requested_product_versions & evidence_product_versions
    )
    if not product_version_compatible:
        reasons.append("evidence product/firmware version does not match query")

    # A document version label alone does not prove that a policy is currently
    # effective.  Temporal-sensitive requirements need an effective boundary or
    # an explicit upstream verification marker.
    temporal_complete = bool(
        effective_from
        or effective_to
        or metadata.get("effective_at")
        or metadata.get("temporal_verified") is True
    )
    sufficient = active and region_compatible and product_compatible and product_version_compatible
    return EvidenceValidity(
        evidence_id=eid,
        is_active=active,
        effective_from=effective_from.isoformat() if effective_from else None,
        effective_to=effective_to.isoformat() if effective_to else None,
        version=str(metadata.get("version")) if metadata.get("version") is not None else None,
        superseded_by=str(superseded_by) if superseded_by else None,
        region_compatible=region_compatible,
        region_information_complete=region_information_complete,
        product_compatible=product_compatible,
        product_information_complete=product_information_complete,
        product_version_compatible=product_version_compatible,
        temporal_information_complete=temporal_complete,
        validity_sufficient=sufficient,
        reasons=reasons,
    )


def _normalized_text(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())


def _text_similarity(left: str, right: str) -> float:
    left_norm = _normalized_text(left)
    right_norm = _normalized_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if min(len(left_norm), len(right_norm)) < 40:
        return SequenceMatcher(None, left_norm, right_norm).ratio()
    left_grams = {left_norm[i : i + 5] for i in range(len(left_norm) - 4)}
    right_grams = {right_norm[i : i + 5] for i in range(len(right_norm) - 4)}
    return len(left_grams & right_grams) / max(1, len(left_grams | right_grams))


def detect_duplicates(
    evidences: list[dict[str, Any]],
    validity_by_id: dict[str, EvidenceValidity],
) -> tuple[list[dict[str, Any]], list[DuplicateEvidenceGroup], set[str]]:
    groups: list[DuplicateEvidenceGroup] = []
    excluded: set[str] = set()
    representatives: list[dict[str, Any]] = []
    consumed: set[int] = set()

    def representative_index(indices: list[int]) -> int:
        def score(index: int) -> tuple[int, int, float]:
            item = evidences[index]
            eid = evidence_id(item, index)
            validity = validity_by_id[eid]
            source_score = load_verification_policy()["authority_scores"].get(_source_type(item), 0.0)
            version = str(item["document"].metadata.get("version") or "")
            version_num = max([int(v) for v in re.findall(r"\d+", version)] or [0])
            return (int(validity.validity_sufficient), version_num, float(source_score))
        return max(indices, key=score)

    for i, item in enumerate(evidences):
        if i in consumed:
            continue
        meta = item["document"].metadata
        cluster = [i]
        duplicate_type = ""
        similarity = 1.0
        for j in range(i + 1, len(evidences)):
            if j in consumed:
                continue
            other = evidences[j]
            other_meta = other["document"].metadata
            same_chunk = bool(meta.get("chunk_id") and meta.get("chunk_id") == other_meta.get("chunk_id"))
            same_section = bool(meta.get("section_id") and meta.get("section_id") == other_meta.get("section_id"))
            same_hash = bool(
                meta.get("content_sha256")
                and meta.get("content_sha256") == other_meta.get("content_sha256")
            )
            sim = _text_similarity(item["document"].page_content, other["document"].page_content)
            left_claims = _extract_claims(item)
            right_claims = _extract_claims(other)
            contradictory = any(
                key in right_claims and right_claims[key] != value
                for key, value in left_claims.items()
            )
            if contradictory:
                continue
            # Different chunks in the same section may support different
            # requirements.  Treat section identity as duplicate evidence only
            # when the content is also materially the same (or the executor has
            # already produced a section-level record).
            section_level_duplicate = same_section and (
                sim >= 0.72
                or str(meta.get("evidence_level") or "").lower() == "section"
                or str(other_meta.get("evidence_level") or "").lower() == "section"
            )
            if same_chunk or same_hash or section_level_duplicate or sim >= 0.9:
                cluster.append(j)
                consumed.add(j)
                if same_chunk:
                    duplicate_type = "same_chunk"
                elif same_section:
                    duplicate_type = "same_section"
                elif same_hash:
                    duplicate_type = "same_content_hash"
                else:
                    duplicate_type = "high_text_similarity"
                similarity = min(similarity, sim if sim else 1.0)
        consumed.add(i)
        rep_idx = representative_index(cluster)
        representatives.append(evidences[rep_idx])
        if len(cluster) > 1:
            ids = [evidence_id(evidences[index], index) for index in cluster]
            rep_id = evidence_id(evidences[rep_idx], rep_idx)
            excluded.update(eid for eid in ids if eid != rep_id)
            groups.append(
                DuplicateEvidenceGroup(
                    duplicate_id=f"dup-{len(groups) + 1}",
                    evidence_ids=ids,
                    representative_evidence_id=rep_id,
                    duplicate_type=duplicate_type or "duplicate",
                    similarity=similarity,
                )
            )
    return representatives, groups, excluded


def _requirement_tokens(requirement: str) -> set[str]:
    stop = {"是否", "可以", "大概", "给出", "说明", "判断", "如何", "什么", "用户", "需要", "当前"}
    return {
        token.lower()
        for token in _TOKEN_PATTERN.findall(requirement)
        if len(token) >= 2 and token not in stop
    }


def _lineage_matches(
    evidence: dict[str, Any],
    requirement: str,
    plan: RetrievalPlan,
) -> bool:
    contribution_ids = {
        str(item.get("subquery_id"))
        for item in evidence.get("contributions", [])
        if isinstance(item, dict) and item.get("subquery_id")
    }
    for subquery in plan.subqueries:
        if subquery.subquery_id not in contribution_ids:
            continue
        targets = subquery.required_evidence or [subquery.reason]
        for target in targets:
            if target and (_text_similarity(target, requirement) >= 0.45 or target in requirement or requirement in target):
                return True
    return False


def _semantic_match_score(
    requirement: str,
    rule: RequirementRule,
    evidence: dict[str, Any],
    plan: RetrievalPlan,
) -> float:
    metadata = evidence["document"].metadata
    text = "\n".join(
        [
            evidence["document"].page_content,
            str(evidence.get("parent_context") or ""),
            str(metadata.get("section_path") or metadata.get("section") or ""),
            str(metadata.get("error_codes") or metadata.get("error_code") or ""),
            str(metadata.get("product_models") or metadata.get("product_model") or ""),
        ]
    ).lower()
    lineage = 1.0 if _lineage_matches(evidence, requirement, plan) else 0.0
    indicators = [pattern for pattern in rule.evidence_patterns if pattern.lower() in text]
    indicator_score = 1.0 if indicators else 0.0
    tokens = _requirement_tokens(requirement)
    lexical = sum(token in text for token in tokens) / max(1, len(tokens))
    phrase = _text_similarity(requirement, text[: min(len(text), 3000)])
    return min(1.0, 0.42 * lineage + 0.33 * indicator_score + 0.2 * lexical + 0.05 * phrase)


def _authority_assessment(
    evidence: dict[str, Any],
    requirement_id: str,
    rule: RequirementRule,
) -> SourceAuthorityAssessment:
    source = _source_type(evidence)
    scores = load_verification_policy()["authority_scores"]
    raw_authority = evidence.get("authority") or evidence["document"].metadata.get("authority")
    authority_score = float(scores.get(source, scores.get("unknown", 0.0)))
    if raw_authority in {"transactional_database", "support_case_database"}:
        authority_score = max(authority_score, 0.95)
    accepted = source in rule.acceptable_sources or source in rule.preferred_sources
    passed = accepted and authority_score >= rule.authority_threshold
    reason = (
        f"{source} is an accepted source for {rule.requirement_type}"
        if passed
        else f"{source} does not meet authority policy for {rule.requirement_type}"
    )
    return SourceAuthorityAssessment(
        evidence_id=evidence_id(evidence),
        requirement_id=requirement_id,
        source_type=source,
        source_authority=authority_score,
        authority_reason=reason,
        authority_required=rule.authority_required,
        authority_passed=passed if rule.authority_required else accepted or authority_score >= rule.authority_threshold,
    )


def _extract_claims(evidence: dict[str, Any]) -> dict[str, str]:
    metadata = evidence["document"].metadata
    claims: dict[str, str] = {}
    conflict_group = str(metadata.get("conflict_group") or "").strip()
    conflict_key = metadata.get("conflict_key")
    conflict_value = metadata.get("conflict_value")
    if conflict_value is not None and (conflict_key is not None or conflict_group):
        key = str(conflict_key) if conflict_key is not None else "value"
        scoped_key = f"{conflict_group}::{key}" if conflict_group else key
        claims[scoped_key] = str(conflict_value)
    text = evidence["document"].page_content
    for match in _NUMERIC_FACT_PATTERN.finditer(text):
        claims[match.group("key")] = re.sub(r"\s+", "", match.group("value"))
    for key, (positive, negative) in _BOOLEAN_PATTERNS.items():
        pos = bool(positive.search(text))
        neg = bool(negative.search(text))
        if pos != neg:
            claims[key] = "true" if pos else "false"
    return claims


def _version_key(value: Any) -> tuple[int, ...]:
    numbers = tuple(int(item) for item in re.findall(r"\d+", str(value or "")))
    return numbers or (0,)


def _preferred_conflict_evidence(
    evidence_ids: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
    validity_by_id: dict[str, EvidenceValidity],
    authority_by_pair: dict[tuple[str, str], SourceAuthorityAssessment],
    requirement_id: str,
) -> tuple[str | None, str, bool]:
    """Resolve only when validity, authority or same-policy version is decisive."""
    current_ids = [eid for eid in evidence_ids if validity_by_id[eid].validity_sufficient]
    if not current_ids:
        return None, "all conflicting evidence is invalid/expired and excluded", False
    if len(current_ids) == 1:
        return current_ids[0], "current valid evidence preferred over expired/superseded evidence", False

    sources = {_source_type(evidence_by_id[eid]) for eid in current_ids}
    if "policy" in sources and "ticket_history" in sources:
        policy_ids = [eid for eid in current_ids if _source_type(evidence_by_id[eid]) == "policy"]
        if len(policy_ids) == 1:
            return policy_ids[0], "current policy authority overrides historical ticket experience", False
        # Multiple current policy rows must first agree with each other; historical
        # cases cannot be used to break a policy-policy tie.
        current_ids = policy_ids

    authority_scores = {
        eid: (authority_by_pair.get((requirement_id, eid)).source_authority
              if authority_by_pair.get((requirement_id, eid)) else 0.0)
        for eid in current_ids
    }
    best_authority = max(authority_scores.values(), default=0.0)
    authority_winners = [eid for eid, score in authority_scores.items() if score == best_authority]
    if len(authority_winners) == 1:
        return authority_winners[0], "higher-authority evidence preferred", False
    current_ids = authority_winners

    # A version number is comparable only inside the same logical policy.  It is
    # unsafe to let an unrelated policy v3 automatically overrule policy v1.
    policy_ids = {
        str(evidence_by_id[eid]["document"].metadata.get("policy_id") or "")
        for eid in current_ids
    }
    if len(policy_ids) == 1 and "" not in policy_ids and len(current_ids) > 1:
        versions = {
            eid: _version_key(evidence_by_id[eid]["document"].metadata.get("version"))
            for eid in current_ids
        }
        best_version = max(versions.values())
        version_winners = [eid for eid, version in versions.items() if version == best_version]
        if len(version_winners) == 1:
            return version_winners[0], "newer authoritative version of the same policy preferred", False

    return None, "same-authority current evidence remains mutually inconsistent", True


def detect_conflicts(
    coverages: list[RequirementCoverage],
    evidence_by_id: dict[str, dict[str, Any]],
    validity_by_id: dict[str, EvidenceValidity],
    authority_assessments: list[SourceAuthorityAssessment],
    candidate_ids_by_requirement: dict[str, list[str]] | None = None,
) -> list[EvidenceConflict]:
    conflicts: list[EvidenceConflict] = []
    authority_by_pair = {
        (item.requirement_id, item.evidence_id): item for item in authority_assessments
    }
    candidate_ids_by_requirement = candidate_ids_by_requirement or {}
    for coverage in coverages:
        candidate_ids = [
            eid
            for eid in candidate_ids_by_requirement.get(coverage.requirement_id, coverage.evidence_ids)
            if eid in evidence_by_id
        ]
        claims_by_key: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        policy_versions: dict[str, list[str]] = defaultdict(list)
        for eid in candidate_ids:
            item = evidence_by_id[eid]
            metadata = item["document"].metadata
            for key, value in _extract_claims(item).items():
                claims_by_key[key][value].append(eid)
            policy_id = metadata.get("policy_id")
            if policy_id:
                policy_versions[str(policy_id)].append(eid)
        for key, values in claims_by_key.items():
            if len(values) <= 1:
                continue
            ids = list(dict.fromkeys(eid for rows in values.values() for eid in rows))
            preferred, reason, unresolved = _preferred_conflict_evidence(
                ids, evidence_by_id, validity_by_id, authority_by_pair, coverage.requirement_id
            )
            sources = {_source_type(evidence_by_id[eid]) for eid in ids}
            conflict_type = "historical_vs_current_policy" if {"policy", "ticket_history"} <= sources else "conflict_key_value"
            conflicts.append(
                EvidenceConflict(
                    conflict_id=f"conf-{len(conflicts) + 1}",
                    requirement_id=coverage.requirement_id,
                    evidence_ids=ids,
                    conflict_type=conflict_type,
                    preferred_evidence_id=preferred,
                    resolution_reason=reason,
                    unresolved=unresolved,
                    risk_level="high" if coverage.evidence_type in {"warranty_eligibility", "return_refund_policy"} else "medium",
                )
            )
        for policy_id, ids in policy_versions.items():
            versions = {str(evidence_by_id[eid]["document"].metadata.get("version") or "") for eid in ids}
            if len(ids) < 2 or len(versions) < 2:
                continue
            already = any(set(item.evidence_ids) == set(ids) for item in conflicts)
            if already:
                continue
            preferred, reason, unresolved = _preferred_conflict_evidence(
                ids, evidence_by_id, validity_by_id, authority_by_pair, coverage.requirement_id
            )
            conflicts.append(
                EvidenceConflict(
                    conflict_id=f"conf-{len(conflicts) + 1}",
                    requirement_id=coverage.requirement_id,
                    evidence_ids=ids,
                    conflict_type="policy_version",
                    preferred_evidence_id=preferred,
                    resolution_reason=reason,
                    unresolved=unresolved,
                    risk_level="high",
                )
            )
    return conflicts


def _missing_identity_question(understanding: QueryUnderstanding, rules: Iterable[RequirementRule]) -> str | None:
    rules = list(rules)
    has_product = bool(understanding.product_id or understanding.product_name or understanding.product_models)
    if any(rule.needs_product for rule in rules) and not has_product:
        return "请补充产品名称或具体型号，以便核对适用手册、政策和维修数据。"
    if any(rule.needs_region for rule in rules) and not understanding.region:
        return "请补充购买或使用地区，以便核对当前地区有效的售后政策。"
    return None


def _filters_for_requirement(
    understanding: QueryUnderstanding,
    principal: RetrievalPrincipal,
    source: str,
) -> dict[str, Any]:
    filters: dict[str, Any] = {
        "tenant_id": principal.tenant_id,
        "active_only": True,
    }
    if understanding.product_id:
        filters["product_id"] = understanding.product_id
    elif understanding.product_models:
        filters["product_model"] = understanding.product_models
    elif understanding.product_name:
        filters["product_name"] = understanding.product_name
    if understanding.error_codes:
        filters["error_code"] = understanding.error_codes
    if understanding.region:
        filters["region"] = understanding.region
    if source not in {"all", "structured_db", "database"}:
        filters["source"] = source
    return filters


def subquery_signature(subquery: RetrievalSubquery) -> str:
    payload = {
        "query": re.sub(r"\s+", " ", subquery.query.strip().lower()),
        "source": subquery.source,
        "filters": subquery.filters,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_targeted_subqueries(
    missing: list[RequirementCoverage],
    understanding: QueryUnderstanding,
    principal: RetrievalPrincipal,
    *,
    round_id: int,
    executed_signatures: set[str] | None = None,
) -> list[RetrievalSubquery]:
    executed_signatures = executed_signatures or set()
    entities = " ".join(
        item
        for item in [
            understanding.product_id,
            understanding.product_name,
            *understanding.product_models,
            understanding.product_version,
            *understanding.error_codes,
            understanding.order_id,
            understanding.ticket_id,
            understanding.customer_id,
        ]
        if item
    )
    output: list[RetrievalSubquery] = []
    for coverage in missing:
        rule = classify_requirement(coverage.requirement)
        sources = list(rule.preferred_sources or rule.acceptable_sources or ("all",))
        if rule.requirement_type == "repair_duration" and not (
            understanding.ticket_id or understanding.order_id or understanding.customer_id
        ):
            sources = [source for source in sources if source != "structured_db"] or ["ticket_history"]
        for source in sources[:2]:
            query = " ".join(part for part in [entities, coverage.requirement] if part).strip()
            subquery = RetrievalSubquery(
                subquery_id=f"vr{round_id}-{coverage.requirement_id}-{source}",
                query=query,
                source="database" if source == "structured_db" else source,
                filters=_filters_for_requirement(understanding, principal, source),
                required_evidence=[coverage.requirement],
                priority=95 if coverage.critical else 70,
                retrieval_mode="database" if source == "structured_db" else "hybrid",
                parent_query_id=coverage.requirement_id,
                reason=f"targeted supplement for {coverage.requirement_id}:{coverage.evidence_type}",
            )
            signature = subquery_signature(subquery)
            if signature in executed_signatures:
                continue
            output.append(subquery)
            executed_signatures.add(signature)
            break
    return output


def _safe_filters_to_relax(plan: RetrievalPlan) -> list[str]:
    config = load_verification_policy()
    protected = set(config["protected_filters"])
    safe = set(config["safe_relaxable_filters"])
    present = {
        key
        for subquery in plan.subqueries
        for key in subquery.filters
        if key in safe and key not in protected
    }
    return sorted(present)


def verify_evidence(
    understanding: QueryUnderstanding,
    plan: RetrievalPlan,
    retrieval_response: RetrievalResponse,
    evidences: list[dict[str, Any]],
    principal: RetrievalPrincipal,
    *,
    retry_count: int = 0,
    executed_signatures: set[str] | None = None,
    now: datetime | None = None,
) -> VerificationResult:
    requirements = understanding.requirements or plan.original_requirements or [understanding.normalized_query]
    requirement_rules = [classify_requirement(requirement) for requirement in requirements]
    clarification = understanding.clarification_question if understanding.needs_clarification else None
    clarification = clarification or _missing_identity_question(understanding, requirement_rules)

    validity_rows = [assess_validity(item, understanding, now=now) for item in evidences]
    validity_by_id = {item.evidence_id: item for item in validity_rows}
    acl_filters = RetrievalFilters(
        tenant_id=principal.tenant_id,
        region=understanding.region,
        active_only=False,
    )
    acl_excluded: set[str] = set()
    acl_valid: list[dict[str, Any]] = []
    for index, item in enumerate(evidences):
        eid = evidence_id(item, index)
        if document_matches_filters(item["document"].metadata, acl_filters, principal):
            acl_valid.append(item)
        else:
            acl_excluded.add(eid)
            validity_by_id[eid].validity_sufficient = False
            validity_by_id[eid].reasons.append("evidence is outside current principal ACL")

    representatives, duplicate_groups, duplicate_excluded = detect_duplicates(acl_valid, validity_by_id)
    evidence_by_id = {evidence_id(item, index): item for index, item in enumerate(representatives)}

    coverages: list[RequirementCoverage] = []
    authority_rows: list[SourceAuthorityAssessment] = []
    candidate_ids_by_requirement: dict[str, list[str]] = {}
    for index, (requirement, rule) in enumerate(zip(requirements, requirement_rules), start=1):
        req_id = f"req-{index}"
        candidate_rows: list[tuple[float, str, bool, bool]] = []
        for item in representatives:
            eid = evidence_id(item)
            semantic_score = _semantic_match_score(requirement, rule, item, plan)
            if semantic_score < 0.32:
                continue
            authority = _authority_assessment(item, req_id, rule)
            authority_rows.append(authority)
            validity = validity_by_id[eid]
            temporal_pass = not rule.temporal_required or validity.temporal_information_complete
            region_pass = not rule.needs_region or (
                validity.region_compatible and validity.region_information_complete
            )
            product_pass = not rule.needs_product or (
                validity.product_compatible
                and validity.product_information_complete
                and validity.product_version_compatible
            )
            validity_pass = validity.validity_sufficient and temporal_pass and region_pass and product_pass
            authority_pass = authority.authority_passed or not rule.authority_required
            confidence = min(1.0, semantic_score * 0.65 + authority.source_authority * 0.25 + (0.1 if validity_pass else 0.0))
            candidate_rows.append((confidence, eid, authority_pass, validity_pass))
        candidate_ids_by_requirement[req_id] = [row[1] for row in candidate_rows]
        accepted = [row for row in candidate_rows if row[2] and row[3]]
        accepted.sort(reverse=True)
        evidence_ids = [row[1] for row in accepted]
        best_confidence = accepted[0][0] if accepted else (max((row[0] for row in candidate_rows), default=0.0))
        authority_sufficient = any(row[2] for row in candidate_rows) if candidate_rows else False
        validity_sufficient = any(row[3] for row in candidate_rows) if candidate_rows else False
        covered = bool(accepted)
        if covered:
            reason = f"covered by {len(evidence_ids)} unique valid evidence item(s) with requirement-aware authority"
        elif candidate_rows and not authority_sufficient:
            reason = "related evidence exists, but source authority is insufficient"
        elif candidate_rows and not validity_sufficient:
            reason = "related evidence exists, but version/time/region/product validity is insufficient"
        else:
            reason = "no unique evidence semantically supports this requirement"
        coverages.append(
            RequirementCoverage(
                requirement_id=req_id,
                requirement=requirement,
                covered=covered,
                evidence_ids=evidence_ids,
                confidence=best_confidence,
                reason=reason,
                evidence_type=rule.requirement_type,
                authority_sufficient=authority_sufficient,
                validity_sufficient=validity_sufficient,
                authority_required=rule.authority_required,
                critical=rule.critical,
            )
        )

    conflicts = detect_conflicts(
        coverages,
        evidence_by_id,
        validity_by_id,
        authority_rows,
        candidate_ids_by_requirement,
    )
    unresolved_ids = {
        eid
        for conflict in conflicts
        if conflict.unresolved
        for eid in conflict.evidence_ids
    }
    resolved_losers = {
        eid
        for conflict in conflicts
        if not conflict.unresolved and conflict.preferred_evidence_id
        for eid in conflict.evidence_ids
        if eid != conflict.preferred_evidence_id
    }
    for coverage in coverages:
        if unresolved_ids & set(coverage.evidence_ids):
            coverage.covered = False
            coverage.reason = "coverage blocked by unresolved evidence conflict"
            continue
        if resolved_losers & set(coverage.evidence_ids):
            coverage.evidence_ids = [eid for eid in coverage.evidence_ids if eid not in resolved_losers]
            coverage.covered = bool(coverage.evidence_ids)
            if coverage.covered:
                coverage.reason = "covered by verifier-preferred evidence after conflict resolution"
            else:
                coverage.reason = "all supporting evidence was superseded during conflict resolution"
    critical = [item for item in coverages if item.critical]
    coverage_score = sum(item.covered for item in coverages) / max(1, len(coverages))
    all_critical = all(item.covered for item in critical) if critical else bool(coverages)
    unresolved_high = any(item.unresolved and item.risk_level == "high" for item in conflicts)
    accepted_ids = sorted({eid for item in coverages if item.covered for eid in item.evidence_ids})
    excluded_ids = sorted(acl_excluded | duplicate_excluded | resolved_losers | {
        eid for eid, valid in validity_by_id.items() if not valid.validity_sufficient
    })
    audit = EvidenceAudit(
        requirement_coverages=coverages,
        source_authority=authority_rows,
        evidence_validity=list(validity_by_id.values()),
        duplicate_groups=duplicate_groups,
        conflicts=conflicts,
        accepted_evidence_ids=accepted_ids,
        excluded_evidence_ids=excluded_ids,
        coverage_score=coverage_score,
        all_critical_requirements_covered=all_critical,
        unresolved_high_risk_conflicts=unresolved_high,
        method="rules",
        policy_version=load_verification_policy()["version"],
    )

    max_rounds = max(1, plan.max_rounds)
    at_max_rounds = retry_count >= max_rounds - 1
    missing = [item for item in coverages if not item.covered]
    status = RetrievalStatus(retrieval_response.status)
    hard_failure = status in {
        RetrievalStatus.PERMISSION_DENIED,
        RetrievalStatus.INVALID_FILTER,
        RetrievalStatus.DEPENDENCY_ERROR,
        RetrievalStatus.TIMEOUT,
        RetrievalStatus.BUDGET_EXHAUSTED,
    }
    non_retryable_failure = status in {
        RetrievalStatus.PERMISSION_DENIED,
        RetrievalStatus.INVALID_FILTER,
    } or any(not error.retryable for error in retrieval_response.errors)

    if clarification:
        decision = VerificationDecision(
            action=VerificationAction.CLARIFY,
            reason="required user-provided identity or region is missing",
            missing_requirements=[item.requirement for item in missing] or requirements,
            clarification_question=clarification,
            confidence=0.98,
            decision_source="rule",
        )
    elif unresolved_high:
        conflict_ids = [item.conflict_id for item in conflicts if item.unresolved and item.risk_level == "high"]
        decision = VerificationDecision(
            action=VerificationAction.HANDOFF,
            reason="unresolved high-risk evidence conflict blocks deterministic answer",
            missing_requirements=[item.requirement for item in missing],
            handoff_reason="同等级、当前有效的关键证据相互冲突，需要人工裁决。",
            confidence=0.99,
            unresolved_conflict_ids=conflict_ids,
            partial_answer_allowed=bool(accepted_ids),
            decision_source="rule",
        )
    elif all_critical and not missing:
        decision = VerificationDecision(
            action=VerificationAction.ACCEPT,
            reason="all critical requirements have unique, authoritative and valid evidence",
            confidence=min(0.99, sum(item.confidence for item in coverages) / max(1, len(coverages))),
            decision_source="rule",
        )
    elif at_max_rounds:
        decision = VerificationDecision(
            action=VerificationAction.HANDOFF,
            reason="maximum retrieval rounds reached before verification passed",
            missing_requirements=[item.requirement for item in missing],
            handoff_reason="已达到最大检索轮次，关键需求仍缺少可靠证据。",
            confidence=0.99,
            partial_answer_allowed=bool(accepted_ids),
            decision_source="rule",
        )
    elif status in {RetrievalStatus.BUDGET_EXHAUSTED, RetrievalStatus.TIMEOUT}:
        decision = VerificationDecision(
            action=VerificationAction.HANDOFF,
            reason="retrieval budget or timeout exhausted before coverage completed",
            missing_requirements=[item.requirement for item in missing],
            handoff_reason="检索预算或超时额度已耗尽，无法继续安全补证。",
            confidence=0.98,
            partial_answer_allowed=bool(accepted_ids),
            decision_source="rule",
        )
    elif hard_failure and (not accepted_ids or non_retryable_failure):
        decision = VerificationDecision(
            action=VerificationAction.HANDOFF,
            reason="critical retrieval dependency or permission failure",
            missing_requirements=[item.requirement for item in missing],
            handoff_reason="关键检索依赖或权限校验失败，无法安全回答。",
            confidence=0.98,
            partial_answer_allowed=bool(accepted_ids),
            decision_source="rule",
        )
    else:
        next_round = retry_count + 2
        next_subqueries = build_targeted_subqueries(
            missing,
            understanding,
            principal,
            round_id=next_round,
            executed_signatures=executed_signatures,
        )
        filters_to_relax = _safe_filters_to_relax(plan) if status == RetrievalStatus.NO_RESULTS else []
        if filters_to_relax and next_subqueries:
            for subquery in next_subqueries:
                subquery.filters = {
                    key: value for key, value in subquery.filters.items() if key not in filters_to_relax
                }
            decision = VerificationDecision(
                action=VerificationAction.RELAX_FILTERS,
                reason="no results and non-security metadata filters appear overly restrictive",
                missing_requirements=[item.requirement for item in missing],
                next_subqueries=next_subqueries,
                filters_to_relax=filters_to_relax,
                confidence=0.78,
                decision_source="rule",
            )
        elif accepted_ids and next_subqueries:
            decision = VerificationDecision(
                action=VerificationAction.SUPPLEMENT,
                reason="some requirements are covered; retrieve only the missing requirement evidence",
                missing_requirements=[item.requirement for item in missing],
                next_subqueries=next_subqueries,
                confidence=0.9,
                decision_source="rule",
            )
        elif len(requirements) > 1 and len(plan.subqueries) <= 1 and next_subqueries:
            decision = VerificationDecision(
                action=VerificationAction.DECOMPOSE,
                reason="multi-requirement query was not sufficiently decomposed by the current plan",
                missing_requirements=[item.requirement for item in missing],
                next_subqueries=next_subqueries,
                confidence=0.82,
                decision_source="rule",
            )
        elif next_subqueries:
            decision = VerificationDecision(
                action=VerificationAction.REWRITE,
                reason="entities are clear but current query expression did not retrieve usable evidence",
                missing_requirements=[item.requirement for item in missing],
                next_subqueries=next_subqueries,
                confidence=0.72,
                decision_source="rule",
            )
        else:
            decision = VerificationDecision(
                action=VerificationAction.HANDOFF,
                reason="all safe targeted subqueries were already executed",
                missing_requirements=[item.requirement for item in missing],
                handoff_reason="无法生成新的非重复检索任务，关键需求仍未覆盖。",
                confidence=0.96,
                partial_answer_allowed=bool(accepted_ids),
                decision_source="rule",
            )
    return VerificationResult(audit=audit, decision=decision, representative_evidences=representatives)
