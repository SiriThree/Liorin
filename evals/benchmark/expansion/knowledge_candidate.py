"""Phase G0.3 Knowledge candidate contracts.

These candidates are source-grounded rendered surfaces of frozen G0.2 task plans.
They are not Formal Gold and carry no Production/annotation result.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class KnowledgeCandidate:
    candidate_id: str
    task_plan_id: str
    render_version: str
    candidate_query: str
    language: str
    primary_task_type: str
    semantic_family_id: str
    reasoning_type: str
    difficulty: str
    answer_scope: str
    source_unit_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    section_ids: tuple[str, ...]
    product_ids: tuple[str, ...]
    required_fact_ids: tuple[str, ...]
    required_evidence_ids: tuple[str, ...]
    rendering_constraints: dict[str, Any]
    render_pattern: str
    render_metadata: dict[str, Any]
    query_validation: dict[str, Any]
    source_validation: dict[str, Any]
    scope_validation: dict[str, Any]
    leakage_validation: dict[str, Any]
    collision_validation: dict[str, Any]
    dedup_signature: str
    query_sha256: str
    status: str
    quality_flags: tuple[str, ...]
    rejection_reasons: tuple[str, ...]

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        for key in (
            "source_unit_ids", "document_ids", "section_ids", "product_ids", "required_fact_ids", "required_evidence_ids",
            "quality_flags", "rejection_reasons",
        ):
            state[key] = list(state[key])
        return state
