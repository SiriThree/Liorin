"""Deterministic real-record -> task-plan -> surface generation for Phase D1."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from retrieval.security import hash_identifier, redact_text
from .candidate_contracts import CandidateStatus, ConstructionMethod, PrivateBusinessCandidate, StructuredTaskPlan
from .private_business import ALL_FAMILIES, FamilySpec

GENERATION_VERSION = "private-business-d1-v1"


def _ref(kind: str, raw: str, *, namespace: str | None = None) -> str:
    ns = namespace or (f"structured:{kind}" if kind in {"order","ticket","warranty"} else kind)
    return f"{kind}:hash:{hash_identifier(raw, namespace=ns)}"


def _public_entity_token(record_type: str, source_ref: str) -> str:
    digest = source_ref.rsplit(":", 1)[-1][:8]
    return f"<{record_type.upper()}_REF:{digest}>"


def _safe_value(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in {"order_id", "ticket_id", "case_id", "customer_id"}:
        kind = "warranty" if field == "case_id" else field.removesuffix("_id")
        return _ref(kind, str(value))
    if field == "summary":
        text = str(value)
        return {"display": redact_text(text, limit=500), "value_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]}
    return value


def _candidate_id(family: str, source_ref: str, fields: tuple[str,...]) -> str:
    material = json.dumps({"family":family,"source":source_ref,"fields":list(fields)},sort_keys=True,separators=(",",":"))
    return "PBQ-" + hashlib.sha256(material.encode()).hexdigest()[:16].upper()


def _load_rows(root: Path, record_type: str) -> list[dict[str, Any]]:
    conn=sqlite3.connect(root/'data/structured/liorin.db'); conn.row_factory=sqlite3.Row
    try:
        if record_type == "order":
            sql='''
            SELECT o.order_id,o.customer_id,c.tenant_id,o.order_date,o.status,o.total_amount,o.channel,
                   x.item_count,i.product_id,p.name AS product_name,i.quantity,i.price_per_unit
            FROM orders o JOIN customers c ON c.customer_id=o.customer_id
            JOIN (SELECT order_id,COUNT(*) AS item_count FROM order_items GROUP BY order_id) x ON x.order_id=o.order_id
            LEFT JOIN order_items i ON i.order_id=o.order_id AND x.item_count=1
            LEFT JOIN products p ON p.product_id=i.product_id
            ORDER BY o.order_id'''
        elif record_type == "ticket":
            sql='''SELECT t.ticket_id,t.customer_id,c.tenant_id,t.order_id,t.product_id,t.status,t.priority,
                          t.issue_type,t.summary,t.created_at,t.assigned_team
                   FROM tickets t JOIN customers c ON c.customer_id=t.customer_id ORDER BY t.ticket_id'''
        elif record_type == "warranty":
            sql='''SELECT w.case_id,w.customer_id,c.tenant_id,w.ticket_id,w.order_id,w.product_id,w.status,
                          w.coverage_type,w.coverage_status,w.expires_at
                   FROM warranty_cases w JOIN customers c ON c.customer_id=w.customer_id ORDER BY w.case_id'''
        else:
            raise ValueError(record_type)
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def _entity_raw_id(row: dict[str,Any], record_type: str) -> str:
    return str(row[{"order":"order_id","ticket":"ticket_id","warranty":"case_id"}[record_type]])


def _state(row: dict[str,Any], record_type: str) -> str:
    return str(row["coverage_status"] if record_type == "warranty" else row["status"])


def _desired_states(record_type: str, total: int) -> list[str]:
    if record_type == "order":
        base=["Processing"]*7+["Shipped"]*7+["Cancelled"]*8+["Delivered"]*14
    elif record_type == "ticket":
        base=["open"]*6+["in_progress"]*6+["pending_customer"]*6+["resolved"]*8
    else:
        base=["expired"]*10+["in_warranty"]*12
    assert len(base)==total
    return base


def _field_non_null(row: dict[str,Any], fields: tuple[str,...]) -> bool:
    return all(row.get(f) is not None and str(row.get(f)).strip() != "" for f in fields)


def _pick_row(rows: list[dict[str,Any]], spec: FamilySpec, desired_state: str, used_entities: set[str], used_customers: set[str], tenant_counts: Counter, product_counts: Counter) -> dict[str,Any]:
    eligible=[]
    for row in rows:
        raw=_entity_raw_id(row,spec.record_type)
        if raw in used_entities or not _field_non_null(row,spec.fields): continue
        if spec.requires_single_item_order and int(row.get("item_count") or 0) != 1: continue
        # Product may be unavailable on a multi-item order; only product/item families require it.
        actual_state=_state(row,spec.record_type)
        product=str(row.get("product_id") or "")
        customer=str(row["customer_id"]); tenant=str(row["tenant_id"])
        score=(
            0 if actual_state==desired_state else 5,
            1 if tenant_counts[tenant] >= 6 else 0,
            0 if customer not in used_customers else 1,
            tenant_counts[tenant],
            product_counts[product] if product else 0,
            hashlib.sha256(raw.encode()).hexdigest(),
        )
        eligible.append((score,row))
    if not eligible:
        raise RuntimeError(f"no source row for {spec.family_id} desired_state={desired_state}")
    return min(eligible,key=lambda x:x[0])[1]


def generate_private_business_candidates(root: str | Path) -> list[PrivateBusinessCandidate]:
    root=Path(root)
    by_type={kind:_load_rows(root,kind) for kind in ("order","ticket","warranty")}
    family_by_type=defaultdict(list)
    for spec in ALL_FAMILIES: family_by_type[spec.record_type].append(spec)
    total_by_type={k:sum(x.count for x in v) for k,v in family_by_type.items()}
    desired={k:iter(_desired_states(k,n)) for k,n in total_by_type.items()}
    used_entities={k:set() for k in by_type}; used_customers=set(); tenant_counts=Counter(); product_counts=Counter(); out=[]
    for record_type in ("order","ticket","warranty"):
        for spec in family_by_type[record_type]:
            for _ in range(spec.count):
                target_state=next(desired[record_type])
                row=_pick_row(by_type[record_type],spec,target_state,used_entities[record_type],used_customers,tenant_counts,product_counts)
                raw_id=_entity_raw_id(row,record_type); source_ref=_ref(record_type,raw_id)
                customer=str(row["customer_id"]); tenant=str(row["tenant_id"]); product=str(row.get("product_id") or "") or None
                used_entities[record_type].add(raw_id); used_customers.add(customer); tenant_counts[tenant]+=1
                if product: product_counts[product]+=1
                ref_token=_public_entity_token(record_type,source_ref)
                query=spec.query_template.format(ref=ref_token)
                evidence=tuple(f"record:{record_type}:hash:{hash_identifier(raw_id, namespace=f'structured:{record_type}')}#{f}" for f in spec.fields)
                expected={f:_safe_value(f,row.get(f)) for f in spec.fields}
                plan=StructuredTaskPlan(record_type,source_ref,spec.fields,"READ_LOOKUP","ANSWER","SAME_TENANT_VERIFIED_CUSTOMER",spec.reasoning_type,spec.family_id,spec.template_id)
                cid=_candidate_id(spec.family_id,source_ref,spec.fields)
                state=_state(row,record_type)
                rare = (record_type=="order" and state in {"Cancelled","Processing","Shipped"}) or (record_type=="ticket" and state in {"open","in_progress","pending_customer"}) or (record_type=="warranty" and state=="expired")
                cand=PrivateBusinessCandidate(
                    candidate_id=cid,construction_schema_version="1.0",status=CandidateStatus.CANDIDATE,
                    category="PRIVATE_BUSINESS_QUERY",subcategory=record_type.upper(),semantic_family_id=spec.family_id,
                    record_type=record_type,source_entity_ref=source_ref,source_field_paths=spec.fields,
                    source_fact_refs=tuple(f"structured-fact:{record_type}.{f}:{source_ref.rsplit(':',1)[-1]}" for f in spec.fields),
                    entity_state=state,
                    state_attributes={
                        "status": str(row.get("status") or ""),
                        **({"coverage_status": str(row.get("coverage_status") or "")} if record_type == "warranty" else {}),
                    },
                    difficulty=("MEDIUM" if len(spec.fields) > 1 or spec.reasoning_type == "MULTI_FIELD_STRUCTURED" or spec.family_id == "TICKET_SUMMARY_LOOKUP" else "EASY"),
                    product_ref=product,tenant_group_ref=_ref("tenant",tenant,namespace="tenant"),customer_group_ref=_ref("customer",customer,namespace="customer"),
                    query_plan=plan,candidate_query=query,expected_response_type_draft="ANSWER",required_structured_fields=spec.fields,candidate_evidence_refs=evidence,
                    production_capability_ref="private_structured_read",surface_template_id=spec.surface_template_id,construction_method=ConstructionMethod.DETERMINISTIC_SOURCE_PLAN,
                    duplicate_keys={
                        "semantic_entity_field": hashlib.sha256(f"{record_type}|{source_ref}|{','.join(sorted(spec.fields))}|ANSWER".encode()).hexdigest(),
                        "family_state": hashlib.sha256(f"{spec.family_id}|{','.join(sorted(spec.fields))}|{state}".encode()).hexdigest(),
                        "gold_fact_candidate_set": hashlib.sha256("|".join(sorted(evidence)).encode()).hexdigest(),
                        "candidate_evidence_set": hashlib.sha256("|".join(sorted(evidence)).encode()).hexdigest(),
                    },
                    split_group_keys={
                        "semantic_family_group": spec.family_id,
                        "customer_group": _ref("customer",customer,namespace="customer"),
                        "entity_group": source_ref,
                        "product_group": product or "NONE",
                        "tenant_group": _ref("tenant",tenant,namespace="tenant"),
                        "structured_record_family": record_type,
                    },
                    expected_value_draft=expected,expected_value_source="data/structured/liorin.db",
                    internal_source_locator={"table":{"order":"orders","ticket":"tickets","warranty":"warranty_cases"}[record_type],"identifier_field":{"order":"order_id","ticket":"ticket_id","warranty":"case_id"}[record_type],"identifier_hash":source_ref.rsplit(':',1)[-1],"hash_namespace":f"structured:{record_type}","resolution":"scan-and-hash construction source; raw identifier not stored in public artifact"},
                    sampling_reason="RARE_STATE_COVERAGE" if rare else "BALANCED_FAMILY_STATE_COVERAGE",
                )
                out.append(cand)
    return out
