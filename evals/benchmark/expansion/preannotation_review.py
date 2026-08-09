"""D2 warranty, order-item and surface-collision pre-annotation audits."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from retrieval.security import hash_identifier, redact_text
from .gold_draft import resolve_candidate_source


def _normalize_surface(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"<(?:order|ticket|warranty)_ref:[0-9a-f]+>", "<entity_ref>", text)
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[，。！？,.!?：:]", "", text)


def audit_warranty_answerability(root: Path, candidate: Mapping[str, Any]) -> dict[str, Any]:
    record = resolve_candidate_source(root, candidate)
    customer_id = str(record["customer_id"])
    target_case = str(record["case_id"])
    conn = sqlite3.connect(root / "data/structured/liorin.db")
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT w.case_id,w.ticket_id,w.order_id,w.product_id,w.coverage_type,w.coverage_status,w.status,w.expires_at "
            "FROM warranty_cases w JOIN customers c ON c.customer_id=w.customer_id "
            "WHERE c.tenant_id=? AND w.customer_id=? ORDER BY w.expires_at DESC LIMIT 50",
            (record["_tenant_id"], customer_id),
        )]
    finally:
        conn.close()
    matches = [x for x in rows if str(x["case_id"]) == target_case]
    required = set(candidate["required_structured_fields"])
    fields_available = all(field in rows[0] for field in required) if rows else False
    query_contains_disambiguator = "<WARRANTY_REF:" in str(candidate["candidate_query"])
    sufficient = len(matches) == 1 and fields_available and query_contains_disambiguator
    return {
        "candidate_id": candidate["candidate_id"],
        "customer_case_count": len(rows),
        "target_uniquely_identifiable": len(matches) == 1,
        "query_contains_disambiguator": query_contains_disambiguator,
        "tool_result_sufficient": sufficient,
        "status": "ANSWERABLE" if sufficient else ("AMBIGUOUS" if len(matches) != 1 else "TOOL_OUTPUT_INSUFFICIENT"),
        "reason": (
            "customer-level warranty list includes exactly one target case_id and all requested fields; runtime case_id can disambiguate"
            if sufficient else "customer-level warranty list cannot deterministically identify/support the target case"
        ),
        "raw_case_id_persisted": False,
    }


def audit_order_item(root: Path, candidate: Mapping[str, Any]) -> dict[str, Any]:
    record = resolve_candidate_source(root, candidate)
    fields = set(candidate["required_structured_fields"])
    item_fields = fields & {"product_id", "product_name", "quantity", "price_per_unit"}
    count = len(record.get("_order_items") or [])
    valid = not item_fields or count == 1
    return {
        "candidate_id": candidate["candidate_id"],
        "item_level_fields": sorted(item_fields),
        "underlying_order_item_count": count,
        "valid": valid,
        "status": "VALID_SINGLE_ITEM" if item_fields and valid else ("NOT_ITEM_LEVEL" if not item_fields else "AMBIGUOUS_MULTI_ITEM"),
    }


def _value_bucket(candidate: Mapping[str, Any]) -> str:
    values = candidate.get("expected_value_draft") or {}
    fields = tuple(candidate["required_structured_fields"])
    if len(fields) == 1:
        value = values.get(fields[0])
        if isinstance(value, dict):
            value = value.get("display") or value.get("value_hash") or "OBJECT"
        if isinstance(value, (int, float)):
            n = float(value)
            if n < 10: return "NUM_LT_10"
            if n < 100: return "NUM_10_99"
            if n < 1000: return "NUM_100_999"
            return "NUM_GE_1000"
        return str(value)
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def review_surface_collisions(candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for c in candidates:
        groups[_normalize_surface(str(c["candidate_query"]))].append(c)
    collision_groups = []
    candidate_priority: dict[str, str] = {}
    candidate_collision_class: dict[str, str] = {}
    for normalized, rows in sorted(groups.items()):
        if len(rows) < 2:
            for c in rows:
                candidate_priority[c["candidate_id"]] = "MEDIUM" if len(c["required_structured_fields"]) > 1 else "LOW"
                candidate_collision_class[c["candidate_id"]] = "NO_COLLISION"
            continue
        states = {str(c.get("entity_state")) for c in rows}
        values = {_value_bucket(c) for c in rows}
        products = {str(c.get("product_ref") or "NONE") for c in rows}
        families = {str(c["semantic_family_id"]) for c in rows}
        rare = any(c.get("sampling_reason") == "RARE_STATE_COVERAGE" for c in rows)
        if len(states) > 1 or (len(values) > 1 and rare) or len(families) > 1:
            info = "HIGH_INFORMATION"
            retention = "distinct business state/value/family gives the shared surface meaningful coverage value"
            priority = "HIGH"
        elif len(values) > 1 or len(products) > 1:
            info = "MEDIUM_INFORMATION"
            retention = "same surface retains source/value/product diversity but needs later annotation-level dedup review"
            priority = "MEDIUM"
        else:
            info = "LOW_INFORMATION"
            retention = "same surface/family/state/value bucket; entity replacement contributes limited incremental information"
            priority = "LOW"
        for c in rows:
            candidate_priority[c["candidate_id"]] = priority
            candidate_collision_class[c["candidate_id"]] = info
        collision_groups.append({
            "surface_signature": hashlib.sha256(normalized.encode()).hexdigest()[:20],
            "candidate_count": len(rows),
            "candidate_ids": [c["candidate_id"] for c in rows],
            "semantic_families": sorted(families),
            "distinct_entities": len({c["source_entity_ref"] for c in rows}),
            "distinct_states": len(states),
            "distinct_value_buckets": len(values),
            "distinct_products": len(products),
            "information_class": info,
            "retention_reason": retention,
        })
    class_counts = {
        name: sum(1 for value in candidate_collision_class.values() if value == name)
        for name in ("HIGH_INFORMATION", "MEDIUM_INFORMATION", "LOW_INFORMATION", "NO_COLLISION")
    }
    return {
        "normalized_duplicate_excess": sum(max(0, len(v) - 1) for v in groups.values()),
        "collision_group_count": len(collision_groups),
        "high_information_groups": sum(1 for x in collision_groups if x["information_class"] == "HIGH_INFORMATION"),
        "medium_information_groups": sum(1 for x in collision_groups if x["information_class"] == "MEDIUM_INFORMATION"),
        "low_information_groups": sum(1 for x in collision_groups if x["information_class"] == "LOW_INFORMATION"),
        "candidate_information_counts": class_counts,
        "groups": collision_groups,
        "candidate_retention_priority": candidate_priority,
        "candidate_collision_class": candidate_collision_class,
    }
