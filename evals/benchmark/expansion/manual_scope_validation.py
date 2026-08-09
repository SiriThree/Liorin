"""Validation gates for E1-R repaired Manual-routing Mixed cases."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .gold_draft import canonical_hash

BROAD_TERMS = ("相关要点", "介绍一下", "说明一下", "怎么排查", "有哪些功能", "有什么需要注意的")
_RAW_ID_RE = re.compile(r"\b(?:ORD|TCK|WAR|CUST)-\d", re.I)


def _norm(text: str) -> str:
    return "".join(str(text).casefold().split())


def validate_scope_repair(
    root: Path,
    original_candidate: Mapping[str, Any],
    repaired_candidate: Mapping[str, Any],
    scope: Mapping[str, Any],
    *,
    facts_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    issues: list[str] = []
    query = str(repaired_candidate["candidate_query"])
    original = str(original_candidate["candidate_query"])

    # Source-preservation invariants.
    for field in ("structured_entity_ref", "structured_record_type", "product_ref", "document_source_id"):
        if repaired_candidate.get(field) != original_candidate.get(field):
            issues.append(f"SOURCE_CHANGED:{field}")
    if list(repaired_candidate.get("document_section_refs") or []) != list(original_candidate.get("document_section_refs") or []):
        issues.append("SOURCE_CHANGED:document_section_refs")
    if list(repaired_candidate.get("document_fact_refs") or []) != list(original_candidate.get("document_fact_refs") or []):
        issues.append("SOURCE_CHANGED:selected_source_fact")

    selected_id = str(scope["selected_fact_id"])
    selected = facts_index.get(selected_id)
    if not selected:
        issues.append("SELECTED_FACT_MISSING")
    else:
        if str(selected["section_id"]) != str(scope["section_id"]):
            issues.append("SELECTED_FACT_SECTION_MISMATCH")
    for fid in scope.get("coherent_group_fact_ids") or []:
        f = facts_index.get(str(fid))
        if not f or str(f["section_id"]) != str(scope["section_id"]):
            issues.append("COHERENT_GROUP_LEFT_SECTION")

    if any(term in query for term in BROAD_TERMS):
        issues.append("BROAD_SCOPE_REMAINS")
    if not str(scope.get("intent_id") or "").strip() or not str(scope.get("question_body") or "").strip():
        issues.append("INTENT_NOT_FROZEN")

    # Source necessity / leakage.  Product identity is the hidden Structured routing fact.
    product_ref = str(original_candidate.get("product_ref") or "")
    if product_ref and product_ref.casefold() in query.casefold():
        issues.append("PRODUCT_ROUTING_FACT_LEAKED")
    # Retrieve product name directly from the checked-in fixture and ensure the renderer did not inject it.
    import sqlite3
    with sqlite3.connect(root / "data/structured/liorin.db") as con:
        prow = con.execute("select name from products where product_id=?", (product_ref,)).fetchone() if product_ref else None
    if prow and str(prow[0]).strip() and str(prow[0]).casefold() in query.casefold():
        issues.append("PRODUCT_ROUTING_FACT_LEAKED")
    if _RAW_ID_RE.search(query):
        issues.append("RAW_PRIVATE_ID_LEAKAGE")
    if selected and _norm(str(selected["normalized_value"])) in _norm(query):
        issues.append("DOCUMENT_ANSWER_LEAKED")

    # Repair must remain a true dual-source routing task.
    structured_required = not any(x in issues for x in ("PRODUCT_ROUTING_FACT_LEAKED",))
    document_required = not any(x in issues for x in ("DOCUMENT_ANSWER_LEAKED",))
    if not structured_required:
        issues.append("MIXED_NECESSITY_STRUCTURED_FAILED")
    if not document_required:
        issues.append("MIXED_NECESSITY_DOCUMENT_FAILED")

    status = "REPAIRED_READY" if not issues else "STILL_NEEDS_MANUAL_PRECHECK"
    if any(x.startswith("SOURCE_CHANGED") or x in {"SELECTED_FACT_MISSING", "SELECTED_FACT_SECTION_MISMATCH", "COHERENT_GROUP_LEFT_SECTION"} for x in issues):
        status = "REJECTED_AFTER_SCOPE_REPAIR"
    return {
        "candidate_id": original_candidate["candidate_id"],
        "original_query": original,
        "repaired_query": query,
        "repair_type": scope.get("repair_type"),
        "intent_id": scope.get("intent_id"),
        "selected_fact_id": selected_id,
        "selected_fact_scope": [selected_id, *(scope.get("coherent_group_fact_ids") or [])],
        "source_preserved": not any(str(x).startswith("SOURCE_CHANGED") for x in issues),
        "structured_source_required": structured_required,
        "document_source_required": document_required,
        "gold_complete": "BROAD_SCOPE_REMAINS" not in issues and "INTENT_NOT_FROZEN" not in issues,
        "gold_minimal": "BROAD_SCOPE_REMAINS" not in issues,
        "query_leakage_clean": not any("LEAK" in x for x in issues),
        "issues": sorted(set(issues)),
        "status": status,
        "validation_signature": canonical_hash({"candidate": original_candidate["candidate_id"], "query": query, "issues": sorted(set(issues))}),
    }


def existing_formal_gold_collisions(root: Path, repaired_rows: list[Mapping[str, Any]], scopes: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Conservative Gold-level collision audit against the 10 current Formal Mixed cases.

    A collision requires the same structured entry type plus an exact current selected
    manual fact value already required by an existing Formal Mixed case.  Same document
    topic alone is reported as overlap, not automatically rejected.
    """
    formal: list[dict[str, Any]] = []
    for name in ("dev_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.json"):
        rows = json.loads((root / "evals/benchmark/data/canonical" / name).read_text(encoding="utf-8"))
        formal.extend(x for x in rows if x.get("category") == "MIXED_KNOWLEDGE_STRUCTURED")
    collisions: list[dict[str, Any]] = []
    for row in repaired_rows:
        scope = scopes[str(row["candidate_id"])]
        selected = _norm(str(scope["selected_fact_text"]))
        hits = []
        for case in formal:
            if str(row["structured_record_type"]) != "ticket":
                continue
            vals = [_norm(str(f.get("normalized_value") or f.get("description") or "")) for f in case.get("gold_facts") or []]
            if selected and selected in vals:
                hits.append(str(case.get("case_id")))
        collisions.append({
            "candidate_id": row["candidate_id"],
            "exact_existing_formal_gold_collision": bool(hits),
            "colliding_case_ids": hits,
        })
    return collisions
