"""Frozen D2 source snapshots and annotation packets for future independent annotation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .gold_draft import canonical_hash

PACKET_VERSION = "private-business-annotation-packet-v1"
SOURCE_SNAPSHOT_VERSION = "private-business-source-snapshot-v1"
ANNOTATION_DECISION_SCHEMA_VERSION = "private-business-gold-review-decision-v1"


def build_source_snapshot(candidate: Mapping[str, Any], draft: Mapping[str, Any]) -> dict[str, Any]:
    fields = []
    for fact in draft["gold_facts_draft"]:
        fields.append({
            "field_path": fact["source_field_path"],
            "value": fact["normalized_value"],
            "value_type": fact["value_type"],
        })
    semantic = {
        "source_snapshot_version": SOURCE_SNAPSHOT_VERSION,
        "candidate_id": candidate["candidate_id"],
        "record_type": candidate["record_type"],
        "entity_alias": candidate["source_entity_ref"],
        "fields": fields,
        "ownership_valid": True,
        "tenant_valid": True,
        "source_record_hash": draft["source_provenance"]["source_record_hash"],
    }
    snapshot_hash = canonical_hash(semantic)
    return {**semantic, "field_paths": [x["field_path"] for x in fields], "snapshot_hash": snapshot_hash}


def annotation_decision_contract() -> dict[str, Any]:
    return {
        "schema_version": ANNOTATION_DECISION_SCHEMA_VERSION,
        "candidate_id": "<required>",
        "overall_decision": ["ACCEPT", "ACCEPT_WITH_EDITS", "REJECT", "NEEDS_HUMAN_REVIEW"],
        "query_quality": "PASS|FAIL|UNCERTAIN",
        "answerability": "PASS|FAIL|UNCERTAIN",
        "response_type_correct": "PASS|FAIL|UNCERTAIN",
        "gold_fact_correct": "PASS|FAIL|UNCERTAIN",
        "gold_fact_complete": "PASS|FAIL|UNCERTAIN",
        "gold_evidence_correct": "PASS|FAIL|UNCERTAIN",
        "task_contract_correct": "PASS|FAIL|UNCERTAIN",
        "source_support": "PASS|FAIL|UNCERTAIN",
        "ambiguity": "NONE|PRESENT|UNCERTAIN",
        "suggested_edits": [],
        "risk_flags": [],
        "rationale": "<required>",
        "annotator_metadata": {"annotator_id": "<runtime>", "model": "<runtime>", "packet_hash": "<must-match>"},
    }


def build_annotation_packet(candidate: Mapping[str, Any], draft: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    # Annotators review Gold construction. They never see Production predictions,
    # traces, Judge outputs, split assignment or another annotator's decision.
    semantic = {
        "packet_version": PACKET_VERSION,
        "gold_draft_version": draft["gold_draft_version"],
        "source_snapshot_version": snapshot["source_snapshot_version"],
        "candidate_version": candidate["construction_schema_version"],
        "candidate_id": candidate["candidate_id"],
        "annotation_task_type": "GOLD_DRAFT_QUALITY_REVIEW",
        "candidate_query": candidate["candidate_query"],
        "runtime_query_preview": draft["runtime_query_materialization"]["runtime_query_redacted"],
        "task_category": candidate["category"],
        "semantic_family_id": candidate["semantic_family_id"],
        "source_snapshot": {
            "snapshot_hash": snapshot["snapshot_hash"],
            "record_type": snapshot["record_type"],
            "entity_alias": snapshot["entity_alias"],
            "fields": snapshot["fields"],
            "ownership_valid": snapshot["ownership_valid"],
            "tenant_valid": snapshot["tenant_valid"],
        },
        "gold_draft": {
            "expected_response_type": draft["expected_response_type"],
            "gold_facts_draft": draft["gold_facts_draft"],
            "gold_evidence_draft": draft["gold_evidence_draft"],
            "task_success_contract_draft": draft["task_success_contract_draft"],
            "answerability": draft["answerability"],
            "required_facts": draft["required_facts"],
            "optional_facts": draft["optional_facts"],
            "forbidden_extra_disclosure": draft["forbidden_extra_disclosure"],
        },
        "production_capability_summary": {
            "capability_ref": candidate["production_capability_ref"],
            "required_tool": draft["tool_expectation"]["required_tool"],
            "required_template_id": draft["tool_expectation"]["required_template_id"],
            "operation": "READ_LOOKUP",
            "identity_scope": draft["identity_expectation"]["scope"],
        },
        "review_priority": draft["review_priority"],
        "review_requirements": draft["review_requirements"],
        "annotation_decision_contract": annotation_decision_contract(),
        "excluded_information": [
            "Production Prediction", "Agent Trace", "Agent Answer", "Judge Answer",
            "Other Annotator Decision", "Adjudication", "Formal Split Assignment", "Future Test Membership",
        ],
    }
    packet_hash = canonical_hash(semantic)
    semantic["annotation_packet_hash"] = packet_hash
    return semantic


def build_batch_manifest(packets: list[Mapping[str, Any]], candidate_set_hash: str) -> dict[str, Any]:
    packet_hashes = [str(x["annotation_packet_hash"]) for x in packets]
    source_hashes = [str(x["source_snapshot"]["snapshot_hash"]) for x in packets]
    semantic = {
        "batch_version": "private-business-annotation-batch-v1",
        "candidate_set_hash": candidate_set_hash,
        "packet_count": len(packets),
        "packet_hashes": packet_hashes,
        "source_snapshot_hashes": source_hashes,
        "gold_draft_version": "private-business-gold-draft-v1",
        "annotation_runs": 0,
        "human_review_runs": 0,
        "formal_eligible_count": 0,
    }
    batch_hash = canonical_hash(semantic)
    return {**semantic, "batch_id": f"PBQ-D2-{batch_hash[:12].upper()}", "batch_hash": batch_hash}
