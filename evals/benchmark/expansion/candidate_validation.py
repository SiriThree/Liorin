"""Source/capability/leakage validation for Phase D1 candidates."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from retrieval.security import hash_identifier
from .candidate_contracts import CandidateStatus, PrivateBusinessCandidate

_WRITE_WORDS = ("退款", "取消订单", "修改订单", "删除", "创建售后", "创建工单")
_MIXED_WORDS = ("退货政策", "售后政策", "说明书", "手册怎么说", "政策是否", "保修政策")
_SAFETY_WORDS = ("别人的", "其他人的", "其他租户", "管理员权限", "绕过权限", "越权")
_ID_FIELDS = {"order_id", "ticket_id", "case_id"}


def _hash_ref(record_type: str, raw_id: str) -> str:
    return f"{record_type}:hash:{hash_identifier(raw_id, namespace=f'structured:{record_type}')}"


def _resolve_hashed_entity(conn: sqlite3.Connection, record_type: str, source_ref: str) -> dict[str, Any] | None:
    mapping = {
        "order": ("orders", "order_id"),
        "ticket": ("tickets", "ticket_id"),
        "warranty": ("warranty_cases", "case_id"),
    }
    table, key = mapping[record_type]
    matches = []
    for row in conn.execute(f"SELECT * FROM {table}"):
        raw = str(row[key])
        if _hash_ref(record_type, raw) == source_ref:
            matches.append(dict(row))
    return matches[0] if len(matches) == 1 else None


def _expected_text_values(candidate: PrivateBusinessCandidate) -> list[str]:
    values = []
    for key, value in candidate.expected_value_draft.items():
        if key in _ID_FIELDS or key.endswith("_id"):
            continue
        if isinstance(value, dict) and "display" in value:
            value = value["display"]
        if isinstance(value, (str, int, float)):
            text = str(value).strip()
            if len(text) >= 3:
                values.append(text.casefold())
    return values


def validate_candidate(root: str | Path, d0_dir: str | Path, candidate: PrivateBusinessCandidate) -> PrivateBusinessCandidate:
    root = Path(root); d0 = Path(d0_dir)
    facts = json.loads((d0 / "structured_fact_inventory.json").read_text(encoding="utf-8"))
    usable = {(x["record_type"], x["field_path"]) for x in facts if x.get("benchmark_usable")}
    templates = json.loads((d0 / "structured_source_inventory.json").read_text(encoding="utf-8"))["sql_templates"]
    template_map = {x["template_id"]: set(x.get("output_fields") or []) for x in templates}
    reasons = []
    flags = []

    if candidate.record_type not in {"order", "ticket", "warranty"}:
        reasons.append("UNSUPPORTED_RECORD_TYPE")
    if candidate.query_plan.operation_semantics != "READ_LOOKUP":
        reasons.append("UNSUPPORTED_OPERATION")
    if candidate.query_plan.template_id not in template_map:
        reasons.append("NO_CAPABILITY_MAPPING")
    for field in candidate.required_structured_fields:
        if (candidate.record_type, field) not in usable:
            reasons.append(f"UNSUPPORTED_FIELD:{field}")
        if field not in template_map.get(candidate.query_plan.template_id, set()):
            reasons.append(f"FIELD_NOT_EXPOSED_BY_TEMPLATE:{field}")
    if any(candidate.record_type + "_event" == rt for rt, _ in usable):
        pass
    if any(word in candidate.candidate_query for word in _WRITE_WORDS):
        reasons.append("WRITE_OPERATION_LEAKAGE")
    if any(word in candidate.candidate_query for word in _MIXED_WORDS):
        reasons.append("MIXED_TASK_LEAKAGE")
    if any(word in candidate.candidate_query for word in _SAFETY_WORDS):
        reasons.append("SAFETY_TASK_LEAKAGE")

    conn = sqlite3.connect(root / "data/structured/liorin.db")
    conn.row_factory = sqlite3.Row
    try:
        row = _resolve_hashed_entity(conn, candidate.record_type, candidate.source_entity_ref)
        if row is None:
            reasons.append("SOURCE_ENTITY_MISSING_OR_NONUNIQUE")
        else:
            customer_id = str(row["customer_id"])
            customer = conn.execute("SELECT tenant_id FROM customers WHERE customer_id=?", (customer_id,)).fetchone()
            if customer is None:
                reasons.append("OWNER_METADATA_MISSING")
            else:
                tenant_ref = f"tenant:hash:{hash_identifier(customer['tenant_id'], namespace='tenant')}"
                customer_ref = f"customer:hash:{hash_identifier(customer_id, namespace='customer')}"
                if tenant_ref != candidate.tenant_group_ref:
                    reasons.append("TENANT_GROUP_MISMATCH")
                if customer_ref != candidate.customer_group_ref:
                    reasons.append("CUSTOMER_GROUP_MISMATCH")
            if candidate.record_type == "order" and any(f in {"product_id","product_name","quantity","price_per_unit"} for f in candidate.required_structured_fields):
                raw_id = str(row["order_id"])
                count = conn.execute("SELECT COUNT(*) FROM order_items WHERE order_id=?", (raw_id,)).fetchone()[0]
                if int(count) != 1:
                    reasons.append("AMBIGUOUS_MULTI_ROW_EVIDENCE")
    finally:
        conn.close()

    query_norm = candidate.candidate_query.casefold()
    for value in _expected_text_values(candidate):
        if value in query_norm:
            reasons.append("ANSWER_LEAKAGE")
            break
    # Public artifacts must not expose raw business identifiers or owner/tenant IDs.
    if re.search(r"\b(?:ORD|TCK|WAR)-\d{4}-\d{5,}\b|\bCUST-\d{3,}\b|\bTENANT-[A-Z0-9-]+\b", candidate.candidate_query, re.I):
        reasons.append("METADATA_OR_IDENTIFIER_LEAKAGE")

    if reasons:
        candidate.status = CandidateStatus.REJECTED
        candidate.rejection_reasons = sorted(set(reasons))
    else:
        candidate.status = CandidateStatus.SOURCE_VALIDATED
        flags.extend(["SOURCE_VALID", "PRODUCTION_SUPPORTED", "IDENTITY_VALID", "FIELD_EXPOSED", "STABLE_EVIDENCE"])
        candidate.quality_flags = sorted(set(candidate.quality_flags + flags))
    return candidate
