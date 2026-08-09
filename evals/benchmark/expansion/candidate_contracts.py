"""Dataset-construction contracts for Phase D1 Private Business candidates.

These objects are *not* CanonicalEvaluationSample and are never eligible for
formal metrics without the later annotation/review pipeline.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class CandidateStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    SOURCE_VALIDATED = "SOURCE_VALIDATED"
    REJECTED = "REJECTED"


class ConstructionMethod(str, Enum):
    DETERMINISTIC_SOURCE_PLAN = "DETERMINISTIC_SOURCE_PLAN"
    MODEL_SURFACE_UNREVIEWED = "MODEL_SURFACE_UNREVIEWED"


@dataclass(frozen=True)
class StructuredTaskPlan:
    record_type: str
    target_entity_ref: str
    required_fields: tuple[str, ...]
    operation_semantics: str
    expected_response_type: str
    required_identity_scope: str
    reasoning_type: str
    semantic_family_id: str
    template_id: str

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["required_fields"] = list(self.required_fields)
        return state


@dataclass
class PrivateBusinessCandidate:
    candidate_id: str
    construction_schema_version: str
    status: CandidateStatus
    category: str
    subcategory: str
    semantic_family_id: str
    record_type: str
    source_entity_ref: str
    source_field_paths: tuple[str, ...]
    source_fact_refs: tuple[str, ...]
    entity_state: str
    state_attributes: dict[str, str]
    difficulty: str
    product_ref: str | None
    tenant_group_ref: str
    customer_group_ref: str
    query_plan: StructuredTaskPlan
    candidate_query: str
    expected_response_type_draft: str
    required_structured_fields: tuple[str, ...]
    candidate_evidence_refs: tuple[str, ...]
    production_capability_ref: str
    surface_template_id: str
    construction_method: ConstructionMethod
    duplicate_keys: dict[str, str]
    split_group_keys: dict[str, str]
    expected_value_draft: dict[str, Any]
    expected_value_source: str
    internal_source_locator: dict[str, str]
    sampling_reason: str | None = None
    runtime_materialization_required: bool = True
    quality_flags: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    duplicate_of: str | None = None
    duplicate_type: str | None = None
    annotation_metadata: dict[str, Any] = field(default_factory=lambda: {
        "annotation_status": "SOURCE_DERIVED_DRAFT",
        "human_reviewed": False,
        "formal_metric_eligible": False,
    })

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["status"] = self.status.value
        state["construction_method"] = self.construction_method.value
        state["query_plan"] = self.query_plan.to_state()
        for key in ("source_field_paths", "source_fact_refs", "required_structured_fields", "candidate_evidence_refs"):
            state[key] = list(state[key])
        return state
