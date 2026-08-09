"""Deterministic E1-R query-scope repair and Gold re-freeze helpers."""
from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from .gold_draft import canonical_hash
from .manual_scope import ManualFactScope
from .mixed_gold_draft import FactRole, build_source_snapshot
from .runtime_materialization import build_runtime_materialization

_TOKEN_RE = re.compile(r"<(ORDER|TICKET|WARRANTY)_REF:[0-9a-f]+>", re.I)
E1R_REPAIR_VERSION = "manual-scope-repair-v1"
E1R_QUERY_VERSION = "mixed-query-e1r-v1"
E1R_SOURCE_SNAPSHOT_VERSION = "mixed-source-snapshot-e1r-v1"
E1R_PACKET_VERSION = "mixed-annotation-packet-e1r-v1"


def _entity_prefix(candidate: Mapping[str, Any]) -> str:
    query = str(candidate["candidate_query"])
    m = _TOKEN_RE.search(query)
    if not m:
        raise ValueError(f"{candidate['candidate_id']} missing construction entity token")
    token = m.group(0)
    kind = str(candidate["structured_record_type"])
    if kind == "order":
        return f"订单 {token} 里的设备具体型号我不记得了。请先从订单确认对应产品，再根据该产品手册，"
    if kind == "ticket":
        return f"工单 {token} 里没有写产品型号。请先根据工单关联的产品确认对应手册。然后根据手册，"
    if kind == "warranty":
        return f"我只记得保修案例 {token}，不清楚对应设备型号。请先从该保修案例确认产品，再根据对应手册，"
    raise ValueError(kind)


def build_repaired_query(candidate: Mapping[str, Any], scope: ManualFactScope) -> str:
    if not scope.repairable or not scope.question_body:
        raise ValueError("scope is not deterministically repairable")
    return _entity_prefix(candidate) + scope.question_body


def repair_id(candidate_id: str, scope: ManualFactScope, repaired_query: str) -> str:
    payload = f"{candidate_id}|{scope.selected_fact_id}|{scope.intent_id}|{repaired_query}|{E1R_REPAIR_VERSION}"
    return "MIX-REPAIR-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16].upper()


def build_repaired_candidate(candidate: Mapping[str, Any], scope: ManualFactScope) -> dict[str, Any]:
    row = copy.deepcopy(dict(candidate))
    query = build_repaired_query(candidate, scope)
    row["candidate_query"] = query
    row["query_version"] = E1R_QUERY_VERSION
    row["repair_id"] = repair_id(str(candidate["candidate_id"]), scope, query)
    row["scope_repair"] = {
        "repair_version": E1R_REPAIR_VERSION,
        "repair_type": scope.repair_type,
        "intent_id": scope.intent_id,
        "selected_fact_id": scope.selected_fact_id,
        "coherent_group_fact_ids": list(scope.coherent_group_fact_ids),
        "original_query": candidate["candidate_query"],
        "repaired_query": query,
        "source_preserving": True,
    }
    return row


def _supporting_fact_state(fact: Mapping[str, Any], evidence_id: str) -> dict[str, Any]:
    fid = "mixed-fact-context:" + hashlib.sha256(str(fact["fact_id"]).encode()).hexdigest()[:20]
    return {
        "fact_id": fid,
        "fact_origin": "DOCUMENT",
        "role": FactRole.SUPPORTING_ONLY.value,
        "description": str(fact["normalized_value"]),
        "normalized_value": str(fact["normalized_value"]),
        "value_type": "STRING",
        "comparison_mode": "SEMANTIC",
        "critical_for_task": False,
        "answer_required": False,
        "supporting_evidence_ids": [evidence_id],
        "source_field_path": None,
        "source_fact_ref": str(fact["fact_id"]),
        "metadata": {
            "fact_type": str(fact.get("fact_type") or "UNKNOWN"),
            "section_id": str(fact["section_id"]),
            "scope_context_only": True,
        },
    }


def refreeze_manual_draft(
    root: Path,
    candidate: Mapping[str, Any],
    e1_draft: Mapping[str, Any],
    scope: ManualFactScope,
    facts_index: Mapping[str, Mapping[str, Any]],
    *,
    final_status: str,
    validation_issues: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    repaired = build_repaired_candidate(candidate, scope)
    draft = copy.deepcopy(dict(e1_draft))
    doc_evidence = next(e for e in draft["gold_evidence"] if e["source_type"] == "DOCUMENT")

    # Keep the E0-selected answer fact unchanged.  Add only the minimal same-section
    # context facts needed to make a fragment/condition natural; they are SUPPORTING_ONLY.
    existing_refs = {f.get("source_fact_ref") for f in draft["document_facts"]}
    added_supporting: list[dict[str, Any]] = []
    for fid in scope.coherent_group_fact_ids:
        if fid in existing_refs:
            continue
        fact = facts_index[fid]
        if str(fact["section_id"]) != scope.section_id:
            raise ValueError("coherent context fact left original section")
        added_supporting.append(_supporting_fact_state(fact, str(doc_evidence["evidence_id"])))
    draft["document_facts"] = list(draft["document_facts"]) + added_supporting
    if added_supporting:
        doc_evidence["source_fact_ids"] = list(dict.fromkeys(list(doc_evidence.get("source_fact_ids") or []) + [str(f["source_fact_ref"]) for f in added_supporting]))

    draft["runtime_query_materialization"] = build_runtime_materialization(root, {
        "candidate_id": repaired["candidate_id"],
        "record_type": repaired["structured_record_type"],
        "source_entity_ref": repaired["structured_entity_ref"],
        "candidate_query": repaired["candidate_query"],
    })
    draft["annotation_status"] = final_status
    draft["ambiguity_status"] = "NONE" if final_status == "READY_FOR_DUAL_ANNOTATION" else "PRESENT"
    draft["review_requirements"] = sorted(set(validation_issues))
    qf = set(draft.get("quality_flags") or [])
    qf.discard("MANUAL_SECTION_HAS_MULTIPLE_USABLE_FACTS")
    qf.add("E1R_SOURCE_PRESERVING_SCOPE_REPAIR")
    if scope.coherent_group_required:
        qf.add("MINIMAL_COHERENT_CONTEXT_GROUP")
    draft["quality_flags"] = sorted(qf)
    draft["scope_repair"] = {
        "repair_id": repaired["repair_id"],
        "repair_version": E1R_REPAIR_VERSION,
        "query_version": E1R_QUERY_VERSION,
        "original_query": candidate["candidate_query"],
        "repaired_query": repaired["candidate_query"],
        "repair_type": scope.repair_type,
        "intent_id": scope.intent_id,
        "selected_fact_id": scope.selected_fact_id,
        "selected_fact_text": scope.selected_fact_text,
        "coherent_group_fact_ids": list(scope.coherent_group_fact_ids),
        "source_preserving": True,
    }
    draft["gold_information_signature"] = canonical_hash({
        "family": candidate["mixed_family_id"],
        "routing_source_type": candidate["structured_record_type"],
        "product": candidate.get("product_ref"),
        "selected_fact": scope.selected_fact_id,
        "coherent_group": list(scope.coherent_group_fact_ids),
        "intent": scope.intent_id,
        "answer_facts": list(draft["answer_required_facts"]),
        "section": scope.section_id,
    })
    return repaired, draft


def build_refrozen_manual_snapshot(
    candidate: Mapping[str, Any], draft: Mapping[str, Any], scope: ManualFactScope,
    *, facts_index: Mapping[str, Mapping[str, Any]], section_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    structured = []
    for fact in draft["structured_facts"]:
        structured.append({
            "fact_id": fact["fact_id"], "role": fact["role"], "field_path": fact["source_field_path"],
            "value": fact["normalized_value"], "entity_alias": candidate["structured_entity_ref"],
            "ownership_valid": True, "tenant_valid": True,
        })
    row = section_index[scope.section_id]
    fact_ids = [scope.selected_fact_id, *scope.coherent_group_fact_ids]
    texts = [str(facts_index[fid]["normalized_value"]) for fid in fact_ids]
    semantic = {
        "source_snapshot_version": E1R_SOURCE_SNAPSHOT_VERSION,
        "candidate_id": candidate["candidate_id"],
        "structured_source": structured,
        "document_source": [{
            "document_id": row["document_id"], "section_id": row["section_id"], "section_title": row["title"],
            "source_type": row["source_type"], "relevant_fact_texts": texts,
            "selected_fact_id": scope.selected_fact_id, "necessary_local_context_fact_ids": list(scope.coherent_group_fact_ids),
        }],
        "source_necessity": draft["source_necessity_contract"],
        "scope_repair": {
            "intent_id": scope.intent_id, "repair_type": scope.repair_type,
            "answer_scope_fact_ids": [scope.selected_fact_id],
            "context_fact_ids": list(scope.coherent_group_fact_ids),
        },
    }
    semantic["snapshot_hash"] = canonical_hash(semantic)
    semantic["source_record_hash"] = canonical_hash({"candidate_id": candidate["candidate_id"], "structured_source": structured})
    return semantic


def semantic_repair_signature(candidate: Mapping[str, Any], scope: ManualFactScope) -> str:
    return canonical_hash({
        "family": candidate["mixed_family_id"], "manual_fact": scope.selected_fact_id,
        "fact_group": list(scope.coherent_group_fact_ids), "intent": scope.intent_id,
        "condition": scope.condition, "action": scope.action, "product": candidate.get("product_ref"),
        "routing_source_type": candidate["structured_record_type"],
    })
