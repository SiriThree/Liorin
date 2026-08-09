"""Phase G0.2 Knowledge task-planning contracts.

Dataset-construction only: these plans intentionally contain no natural-language
query, candidate answer, Gold, annotation decision, or Production prediction.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class KnowledgeTaskPlan:
    task_plan_id: str
    plan_version: str
    primary_task_type: str
    semantic_family_id: str
    reasoning_type: str
    difficulty: str
    priority: str
    source_unit_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    section_ids: tuple[str, ...]
    product_ids: tuple[str, ...]
    primary_fact_ids: tuple[str, ...]
    required_fact_ids: tuple[str, ...]
    supporting_fact_ids: tuple[str, ...]
    required_evidence_ids: tuple[str, ...]
    answer_scope: str
    fact_relationship: str
    source_necessity: tuple[dict[str, Any], ...]
    multi_fact: bool
    multi_section: bool
    procedure_family_id: str | None
    composition_family_id: str | None
    source_priority: str
    selection_rationale: tuple[str, ...]
    quality_flags: tuple[str, ...]
    future_split_keys: dict[str, Any]
    rendering_constraints: dict[str, Any]
    status: str

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        for key in (
            "source_unit_ids", "document_ids", "section_ids", "product_ids",
            "primary_fact_ids", "required_fact_ids", "supporting_fact_ids",
            "required_evidence_ids", "source_necessity", "selection_rationale",
            "quality_flags",
        ):
            state[key] = list(state[key])
        return state
