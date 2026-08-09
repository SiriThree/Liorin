"""Phase E0 construction-only contracts for source-grounded Mixed candidates."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any
from .candidate_contracts import CandidateStatus, ConstructionMethod

@dataclass(frozen=True)
class MixedNecessity:
    structured_source_required: bool
    document_source_required: bool
    structured_necessity_reason: str
    document_necessity_reason: str
    without_structured_complete: bool = False
    without_document_complete: bool = False

@dataclass(frozen=True)
class MixedTaskPlan:
    mixed_family_id: str
    mixed_mode: str
    structured_record_type: str
    structured_entity_ref: str
    structured_fact_paths: tuple[str, ...]
    structured_fact_values: tuple[Any, ...]
    document_id: str
    document_section_ids: tuple[str, ...]
    document_fact_ids: tuple[str, ...]
    relation_path: str
    required_structured_evidence: tuple[str, ...]
    required_document_evidence: tuple[str, ...]
    derived_reasoning_contract: dict[str, Any]
    expected_response_type_draft: str
    source_necessity: MixedNecessity
    production_capability_mapping: dict[str, Any]
    split_group_keys: dict[str, str]

    def to_state(self) -> dict[str, Any]:
        out=asdict(self)
        return out

@dataclass
class MixedCandidate:
    candidate_id: str
    status: CandidateStatus
    construction_schema_version: str
    mixed_family_id: str
    mixed_mode: str
    semantic_family_id: str
    structured_record_type: str
    structured_entity_ref: str
    structured_fact_refs: tuple[str, ...]
    document_source_id: str
    document_section_refs: tuple[str, ...]
    document_fact_refs: tuple[str, ...]
    relation_path: str
    mixed_necessity: MixedNecessity
    reasoning_type: tuple[str, ...]
    derived_fact_draft: dict[str, Any] | None
    expected_response_type_draft: str
    candidate_query: str
    candidate_evidence_refs: tuple[str, ...]
    production_capability_refs: tuple[str, ...]
    split_group_keys: dict[str, str]
    dedup_signature: str
    source_entity_state: str | None
    product_ref: str | None
    customer_group_ref: str
    tenant_group_ref: str
    document_fact_type: str | None
    construction_method: ConstructionMethod = ConstructionMethod.DETERMINISTIC_SOURCE_PLAN
    quality_flags: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    annotation_metadata: dict[str, Any] = field(default_factory=lambda:{"annotation_status":"SOURCE_DERIVED_DRAFT","human_reviewed":False,"formal_metric_eligible":False})

    def to_state(self) -> dict[str, Any]:
        out=asdict(self)
        out['status']=self.status.value
        out['construction_method']=self.construction_method.value
        return out
