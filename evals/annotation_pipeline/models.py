from __future__ import annotations

from typing import Any, Literal, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, model_validator

Layer = Literal[
    "query_understanding",
    "routing",
    "retrieval",
    "answer_generation",
    "agent_behavior",
    "end_to_end",
]
QualityStatus = Literal["valid", "needs_correction", "ambiguous", "unanswerable"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(StrictModel):
    source_type: Literal["manual", "policy", "faq", "ticket_history", "database"]
    chunk_id: str | None = None
    source_file: str | None = None
    heading: str | None = None
    record_id: str | None = None

    @model_validator(mode="after")
    def require_locator(self):
        if not self.chunk_id and not self.record_id:
            raise ValueError("source reference requires chunk_id or record_id")
        return self


class EntityLabels(StrictModel):
    product_name: str | None = None
    product_id: str | None = None
    product_model: str | None = None
    product_alias: str | None = None
    accessory_model: str | None = None
    error_code: str | None = None


class RequirementLabel(StrictModel):
    concept_id: str
    description: str
    source_refs: list[SourceRef] = Field(default_factory=list)


class AtomicFactLabel(StrictModel):
    fact_text: str
    source_refs: list[SourceRef] = Field(min_length=1)
    necessity: Literal["required", "optional"] = "required"
    support_label: Literal[
        "fully_supported", "partially_supported", "unsupported", "contradicted"
    ] = "fully_supported"
    exact_numbers: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)


class BaseAnnotation(StrictModel):
    sample_id: str
    layer: Layer
    quality_status: QualityStatus
    confidence: float = Field(ge=0.0, le=1.0)
    quality_issues: list[str] = Field(default_factory=list)
    rationale: str


class QueryUnderstandingAnnotation(BaseAnnotation):
    layer: Literal["query_understanding"]
    entities: EntityLabels
    task_type: str
    requirements: list[RequirementLabel]
    needs_clarification: bool
    clarification_slots: list[str] = Field(default_factory=list)
    rewritten_question: str
    must_not_invent: list[str] = Field(default_factory=list)


class RoutingAnnotation(BaseAnnotation):
    layer: Literal["routing"]
    required_sources: list[str]
    conditional_sources: list[str] = Field(default_factory=list)
    optional_sources: list[str] = Field(default_factory=list)
    forbidden_sources: list[str] = Field(default_factory=list)
    min_queries: int = Field(ge=0)
    parallelizable: bool

    @model_validator(mode="after")
    def source_partitions_are_disjoint(self):
        groups = [
            set(self.required_sources),
            set(self.conditional_sources),
            set(self.optional_sources),
            set(self.forbidden_sources),
        ]
        for i, left in enumerate(groups):
            for right in groups[i + 1 :]:
                if left & right:
                    raise ValueError(f"source groups overlap: {sorted(left & right)}")
        allowed = {"manual", "policy", "faq", "ticket_history", "database"}
        union = set().union(*groups)
        invalid = union - allowed
        if invalid:
            raise ValueError(f"unsupported sources: {sorted(invalid)}")
        return self


class RetrievalAnnotation(BaseAnnotation):
    layer: Literal["retrieval"]
    qrels: dict[str, int]
    atomic_facts: list[AtomicFactLabel] = Field(default_factory=list)
    missing_relevant_evidence: bool = False
    omitted_relevant_descriptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_qrels(self):
        if not self.qrels:
            raise ValueError("qrels cannot be empty")
        invalid = {key: value for key, value in self.qrels.items() if value not in {0, 1, 2, 3}}
        if invalid:
            raise ValueError(f"qrel values must be 0..3: {invalid}")
        return self


class AnswerGenerationAnnotation(BaseAnnotation):
    layer: Literal["answer_generation"]
    expected_response_type: str
    atomic_facts: list[AtomicFactLabel]
    forbidden_claims: list[str] = Field(default_factory=list)
    citation_required: bool = True


class AgentBehaviorAnnotation(BaseAnnotation):
    layer: Literal["agent_behavior"]
    expected_action: str
    allowed_actions: list[str]
    reason_codes: list[str]
    clarification_slots: list[str] = Field(default_factory=list)
    supplemental_sources: list[str] = Field(default_factory=list)
    max_retrieval_rounds: int = Field(ge=0)
    must_not_claim_completed_action: bool = False

    @model_validator(mode="after")
    def expected_is_allowed(self):
        if self.expected_action not in self.allowed_actions:
            raise ValueError("expected_action must appear in allowed_actions")
        return self


class EndToEndAnnotation(BaseAnnotation):
    layer: Literal["end_to_end"]
    expected_response_type: str
    decision_code: str
    required_sources: list[str]
    conditional_sources: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    atomic_facts: list[AtomicFactLabel] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    max_retrieval_rounds: int = Field(ge=0)


Annotation = Annotated[
    Union[
        QueryUnderstandingAnnotation,
        RoutingAnnotation,
        RetrievalAnnotation,
        AnswerGenerationAnnotation,
        AgentBehaviorAnnotation,
        EndToEndAnnotation,
    ],
    Field(discriminator="layer"),
]


class AnnotationEnvelope(StrictModel):
    annotation: Annotation


class ConflictItem(StrictModel):
    path: str
    value_a: Any
    value_b: Any


class Resolution(StrictModel):
    path: str
    value: Any
    reason: str
    source_refs: list[SourceRef] = Field(default_factory=list)


class AdjudicationResponse(StrictModel):
    sample_id: str
    resolutions: list[Resolution]
    quality_status: QualityStatus
    quality_issues: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class AgentRecord(StrictModel):
    sample_id: str
    layer: Layer
    annotator_id: str
    provider: str
    model: str
    prompt_profile: str
    request_hash: str
    source_packet_hash: str
    annotation: Annotation
    raw_response_sha256: str
    attempt_count: int = Field(ge=1)
    validation_errors: list[str] = Field(default_factory=list)
    created_at: str


class AdjudicatedRecord(StrictModel):
    sample_id: str
    layer: Layer
    had_disagreement: bool
    conflict_paths: list[str]
    annotation_a: Annotation
    annotation_b: Annotation
    adjudicator_response: AdjudicationResponse | None = None
    final_annotation: Annotation
    created_at: str


class HumanReviewRecord(StrictModel):
    sample_id: str
    layer: Layer
    mandatory_reasons: list[str]
    source_packet: dict[str, Any]
    adjudicated_record: dict[str, Any]
    human_review: dict[str, Any] = Field(
        default_factory=lambda: {
            "reviewer_id": "",
            "status": "pending",
            "final_annotation": None,
            "notes": "",
        }
    )
