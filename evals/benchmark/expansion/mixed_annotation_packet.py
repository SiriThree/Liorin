"""Frozen E1 Mixed Gold source snapshots and future dual-annotation packets."""
from __future__ import annotations

from typing import Any, Mapping

from .gold_draft import canonical_hash
from .mixed_gold_draft import MIXED_PACKET_VERSION

MIXED_ANNOTATION_DECISION_SCHEMA_VERSION = "mixed-gold-review-decision-v1"


def mixed_annotation_decision_contract() -> dict[str, Any]:
    return {
        "schema_version": MIXED_ANNOTATION_DECISION_SCHEMA_VERSION,
        "candidate_id": "<required>",
        "overall_decision": ["ACCEPT", "ACCEPT_WITH_EDITS", "REJECT", "NEEDS_HUMAN_REVIEW"],
        "query_quality": "PASS|FAIL|UNCERTAIN",
        "answerability": "PASS|FAIL|UNCERTAIN",
        "gold_fact_correct": "PASS|FAIL|UNCERTAIN",
        "gold_fact_complete": "PASS|FAIL|UNCERTAIN",
        "gold_minimality": "PASS|FAIL|UNCERTAIN",
        "gold_evidence_correct": "PASS|FAIL|UNCERTAIN",
        "task_contract_correct": "PASS|FAIL|UNCERTAIN",
        "source_support": "PASS|FAIL|UNCERTAIN",
        "ambiguity": "NONE|PRESENT|UNCERTAIN",
        "privacy_safe": "PASS|FAIL|UNCERTAIN",
        "structured_source_required_correct": "PASS|FAIL|UNCERTAIN",
        "document_source_required_correct": "PASS|FAIL|UNCERTAIN",
        "fact_role_assignment_correct": "PASS|FAIL|UNCERTAIN",
        "derived_reasoning_correct": "PASS|FAIL|UNCERTAIN",
        "suggested_edits": [],
        "risk_flags": [],
        "rationale": "<brief source-grounded rationale>",
    }


def build_mixed_annotation_packet(candidate: Mapping[str, Any], draft: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    semantic = {
        "packet_version": MIXED_PACKET_VERSION,
        "candidate_id": candidate["candidate_id"],
        "annotation_task_type": "MIXED_GOLD_DRAFT_QUALITY_REVIEW",
        "candidate_query": candidate["candidate_query"],
        "runtime_query_preview": draft["runtime_query_materialization"]["runtime_query_redacted"],
        "task_category": "MIXED_KNOWLEDGE_STRUCTURED",
        "mixed_family_id": candidate["mixed_family_id"],
        "mixed_mode": candidate["mixed_mode"],
        "source_snapshot": {
            "source_snapshot_version": snapshot["source_snapshot_version"],
            "candidate_id": snapshot["candidate_id"],
            "snapshot_hash": snapshot["snapshot_hash"],
            "structured_source": snapshot["structured_source"],
            "document_source": [
                {
                    "document_id": row["document_id"],
                    "section_id": row["section_id"],
                    "section_title": row["section_title"],
                    "source_type": row["source_type"],
                    "relevant_fact_texts": row["relevant_fact_texts"],
                }
                for row in snapshot["document_source"]
            ],
            "source_necessity": snapshot["source_necessity"],
        },
        "gold_draft_to_review": {
            "structured_facts": draft["structured_facts"],
            "document_facts": draft["document_facts"],
            "derived_facts": draft["derived_facts"],
            "answer_required_facts": draft["answer_required_facts"],
            "intermediate_required_facts": draft["intermediate_required_facts"],
            "optional_facts": draft["optional_facts"],
            "gold_evidence": draft["gold_evidence"],
            "reasoning_contract": draft["reasoning_contract"],
            "task_success_contract_draft": draft["task_success_contract_draft"],
            "source_necessity_contract": draft["source_necessity_contract"],
        },
        "production_capability_summary": {
            "structured": "private_structured_read",
            "knowledge": "knowledge_retrieval",
            "mixed_orchestration": "ARCHITECTURALLY_SUPPORTED_NOT_LIVE_VERIFIED",
        },
        "review_requirements": draft["review_requirements"],
        "annotation_decision_contract": mixed_annotation_decision_contract(),
        "excluded_information": [
            "Production Prediction", "Agent Trace", "Agent Answer", "Judge Result",
            "Other Annotator Decision", "Adjudication", "Formal Split", "Future Test Membership",
        ],
    }
    return {**semantic, "annotation_packet_hash": canonical_hash(semantic)}


def build_mixed_batch_manifest(packets: list[Mapping[str, Any]], candidate_set_hash: str, construction_hash: str) -> dict[str, Any]:
    semantic = {
        "batch_version": "mixed-annotation-batch-v1",
        "candidate_set_hash": candidate_set_hash,
        "packet_count": len(packets),
        "packet_hashes": [str(x["annotation_packet_hash"]) for x in packets],
        "source_snapshot_hashes": [str(x["source_snapshot"]["snapshot_hash"]) for x in packets],
        "gold_draft_version": "mixed-gold-draft-v1",
        "source_snapshot_version": "mixed-source-snapshot-v1",
        "construction_hash": construction_hash,
        "annotation_runs": 0,
        "human_review_runs": 0,
        "formal_eligible_count": 0,
    }
    batch_hash = canonical_hash(semantic)
    return {**semantic, "batch_id": f"MIX-E1-{batch_hash[:12].upper()}", "batch_hash": batch_hash}
