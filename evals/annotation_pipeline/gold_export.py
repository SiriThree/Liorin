from __future__ import annotations

import hashlib
import re
from typing import Any


def fact_id(fact: dict[str, Any]) -> str:
    locators = sorted(
        str(ref.get("chunk_id") or ref.get("record_id") or "")
        for ref in fact.get("source_refs", [])
    )
    normalized = re.sub(r"\s+", "", str(fact.get("fact_text", ""))).lower()
    digest = hashlib.sha256(("|".join(locators) + "::" + normalized).encode("utf-8")).hexdigest()[:12]
    prefix = locators[0] if locators else "FACT"
    return f"{prefix}-FACT-{digest}"


def convert_fact(fact: dict[str, Any]) -> dict[str, Any]:
    refs = []
    for ref in fact.get("source_refs", []):
        refs.append({k: v for k, v in ref.items() if v is not None})
    return {
        "fact_id": fact_id(fact),
        "text": fact["fact_text"],
        "source_refs": refs,
        "match": {
            "required_anchors": [],
            "min_anchor_hits": 0,
            "exact_numbers": fact.get("exact_numbers", []),
            "conditions": fact.get("conditions", []),
        },
        "support_label": fact.get("support_label", "fully_supported"),
    }


def annotation_to_gold(sample: dict[str, Any], annotation: dict[str, Any]) -> dict[str, Any]:
    layer = annotation["layer"]
    if layer == "query_understanding":
        return {
            "entities": annotation["entities"],
            "task_type": annotation["task_type"],
            "requirements": [
                {
                    "concept_id": item["concept_id"],
                    "description": item["description"],
                    "source_refs": [
                        {k: v for k, v in ref.items() if v is not None}
                        for ref in item.get("source_refs", [])
                    ],
                }
                for item in annotation["requirements"]
            ],
            "needs_clarification": annotation["needs_clarification"],
            "clarification_slots": annotation["clarification_slots"],
            "rewritten_question": annotation["rewritten_question"],
            "rewrite_semantic_contract": {
                "must_preserve": [item["concept_id"] for item in annotation["requirements"]],
                "must_not_invent": annotation["must_not_invent"],
            },
            "required_atomic_facts": [],
        }
    if layer == "routing":
        return {
            "required_sources": annotation["required_sources"],
            "conditional_sources": annotation["conditional_sources"],
            "optional_sources": annotation["optional_sources"],
            "forbidden_sources": annotation["forbidden_sources"],
            "expected_plan": {
                "min_queries": annotation["min_queries"],
                "parallelizable": annotation["parallelizable"],
            },
            "required_atomic_facts": [],
        }
    if layer == "retrieval":
        qrels = annotation["qrels"]
        return {
            "qrels": qrels,
            "primary_chunk_ids": sorted([key for key, value in qrels.items() if value == 3]),
            "acceptable_chunk_ids": sorted([key for key, value in qrels.items() if value == 2]),
            "hard_negative_chunk_ids": sorted([key for key, value in qrels.items() if value == 0]),
            "required_atomic_facts": [
                convert_fact(fact) for fact in annotation.get("atomic_facts", []) if fact.get("necessity") == "required"
            ],
            "annotation_limitations": {
                "missing_relevant_evidence": annotation.get("missing_relevant_evidence", False),
                "omitted_relevant_descriptions": annotation.get("omitted_relevant_descriptions", []),
            },
            "evaluation": {
                "recall_k": [1, 3, 5, 10], "mrr": True, "ndcg_k": 10, "map_k": 10, "full_corpus": True
            },
        }
    if layer == "answer_generation":
        facts = annotation.get("atomic_facts", [])
        evidences = sample.get("input", {}).get("evidences", [])
        citation_by_chunk = {
            str(item.get("chunk_id")): item.get("citation_id")
            for item in evidences if item.get("chunk_id") and item.get("citation_id")
        }
        required = [convert_fact(fact) for fact in facts if fact.get("necessity") == "required"]
        optional = [convert_fact(fact) for fact in facts if fact.get("necessity") == "optional"]
        citation_map = {}
        for source_fact, converted in zip([f for f in facts if f.get("necessity") == "required"], required):
            citations = sorted({
                citation_by_chunk.get(str(ref.get("chunk_id")))
                for ref in source_fact.get("source_refs", [])
                if citation_by_chunk.get(str(ref.get("chunk_id")))
            })
            citation_map[converted["fact_id"]] = citations
        return {
            "required_atomic_facts": required,
            "optional_facts": optional,
            "forbidden_claims": annotation["forbidden_claims"],
            "required_citation_map": citation_map,
            "expected_response_type": annotation["expected_response_type"],
            "max_unsupported_claims": 0,
            "evaluation_mode": "multi_agent_adjudicated_facts_citations_and_safety",
        }
    if layer == "agent_behavior":
        return {
            "expected_action": annotation["expected_action"],
            "allowed_actions": annotation["allowed_actions"],
            "reason_codes": annotation["reason_codes"],
            "required_clarification_slots": annotation["clarification_slots"],
            "required_supplemental_sources": annotation["supplemental_sources"],
            "must_not_claim_completed_action": annotation["must_not_claim_completed_action"],
            "max_retrieval_rounds": annotation["max_retrieval_rounds"],
            "required_atomic_facts": [],
        }
    if layer == "end_to_end":
        facts = annotation.get("atomic_facts", [])
        return {
            "required_sources": annotation["required_sources"],
            "conditional_sources": annotation["conditional_sources"],
            "required_atomic_facts": [convert_fact(f) for f in facts if f.get("necessity") == "required"],
            "optional_facts": [convert_fact(f) for f in facts if f.get("necessity") == "optional"],
            "expected_response_type": annotation["expected_response_type"],
            "decision_code": annotation["decision_code"],
            "forbidden_claims": annotation["forbidden_claims"],
            "required_actions": annotation["required_actions"],
            "allowed_actions": annotation["allowed_actions"],
            "max_retrieval_rounds": annotation["max_retrieval_rounds"],
        }
    raise ValueError(f"unsupported layer: {layer}")
