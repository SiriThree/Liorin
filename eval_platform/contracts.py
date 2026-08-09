"""Strongly typed canonical Evaluation contracts for Liorin Phase 1.

These contracts describe Gold and dataset semantics only.  They do not execute
an evaluator and they never cross the production runtime boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


CANONICAL_SCHEMA_VERSION = "1.0"


class TaskCategory(StrEnum):
    KNOWLEDGE_QA = "KNOWLEDGE_QA"
    TROUBLESHOOTING = "TROUBLESHOOTING"
    PRIVATE_BUSINESS_QUERY = "PRIVATE_BUSINESS_QUERY"
    MIXED_KNOWLEDGE_STRUCTURED = "MIXED_KNOWLEDGE_STRUCTURED"
    SAFETY_GOVERNANCE = "SAFETY_GOVERNANCE"


class Difficulty(StrEnum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class DatasetSplit(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class ResponseType(StrEnum):
    ANSWER = "ANSWER"
    CLARIFICATION = "CLARIFICATION"
    HANDOFF = "HANDOFF"
    REFUSAL = "REFUSAL"
    ERROR = "ERROR"


class SuccessCriterion(StrEnum):
    RESPONSE_TYPE_CORRECT = "RESPONSE_TYPE_CORRECT"
    REQUIRED_AGENTS_CORRECT = "REQUIRED_AGENTS_CORRECT"
    REQUIRED_TOOLS_CORRECT = "REQUIRED_TOOLS_CORRECT"
    FORBIDDEN_TOOLS_NOT_CALLED = "FORBIDDEN_TOOLS_NOT_CALLED"
    CRITICAL_FACTS_CORRECT = "CRITICAL_FACTS_CORRECT"
    CRITICAL_FACTS_GROUNDED = "CRITICAL_FACTS_GROUNDED"
    CLARIFICATION_CORRECT = "CLARIFICATION_CORRECT"
    HANDOFF_CORRECT = "HANDOFF_CORRECT"
    AUTHORIZATION_CORRECT = "AUTHORIZATION_CORRECT"
    NO_UNAUTHORIZED_ACCESS = "NO_UNAUTHORIZED_ACCESS"
    NO_SENSITIVE_DATA_LEAK = "NO_SENSITIVE_DATA_LEAK"
    NO_CRITICAL_HALLUCINATION = "NO_CRITICAL_HALLUCINATION"
    # Phase 5 trace-level safety criteria. These extend the one canonical Task
    # Success criterion system; they do not create a parallel safety score.
    NO_UNAUTHORIZED_RETRIEVAL = "NO_UNAUTHORIZED_RETRIEVAL"
    NO_UNAUTHORIZED_TOOL_EXECUTION = "NO_UNAUTHORIZED_TOOL_EXECUTION"
    NO_UNAUTHORIZED_SIDE_EFFECT = "NO_UNAUTHORIZED_SIDE_EFFECT"
    NO_CROSS_TENANT_DATA = "NO_CROSS_TENANT_DATA"
    NO_CROSS_USER_DATA = "NO_CROSS_USER_DATA"
    NO_CROSS_SESSION_STATE_WHEN_FORBIDDEN = "NO_CROSS_SESSION_STATE_WHEN_FORBIDDEN"
    NO_UNAUTHORIZED_ARTIFACT_ACCESS = "NO_UNAUTHORIZED_ARTIFACT_ACCESS"
    NO_UNAUTHORIZED_MEMORY_ACCESS = "NO_UNAUTHORIZED_MEMORY_ACCESS"
    PROMPT_INJECTION_NOT_FOLLOWED = "PROMPT_INJECTION_NOT_FOLLOWED"
    CORRECT_REFUSAL_OR_HANDOFF = "CORRECT_REFUSAL_OR_HANDOFF"


class EvidenceSourceType(StrEnum):
    DOCUMENT = "DOCUMENT"
    STRUCTURED_DATA = "STRUCTURED_DATA"
    TOOL_RESULT = "TOOL_RESULT"


class FactValueType(StrEnum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"
    ENUM = "ENUM"
    JSON = "JSON"


class ComparisonMode(StrEnum):
    EXACT = "EXACT"
    NORMALIZED_EXACT = "NORMALIZED_EXACT"
    NUMERIC = "NUMERIC"
    DATE = "DATE"
    SEMANTIC = "SEMANTIC"


class SplitTrustLevel(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    TEST = "TEST"
    HISTORICAL_UNVERIFIED = "HISTORICAL_UNVERIFIED"
    CONTAMINATED = "CONTAMINATED"


class AnnotationStatus(StrEnum):
    MIGRATED_LEGACY = "MIGRATED_LEGACY"
    MODEL_GENERATED_UNREVIEWED = "MODEL_GENERATED_UNREVIEWED"
    HUMAN_REVIEWED = "HUMAN_REVIEWED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class MigrationStatus(StrEnum):
    MIGRATED = "MIGRATED"
    PARTIALLY_MIGRATED = "PARTIALLY_MIGRATED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class IdentitySpec:
    """Dataset representation compatible with production ``IdentityContext``.

    The first five identifiers map one-to-one to ``identity.IdentityContext``.
    Region/roles/permissions are runtime-visible request metadata, not Gold.
    """

    tenant_id: str
    user_id: str
    conversation_id: str
    thread_id: str
    session_id: str
    region: str | None = None
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("tenant_id", "user_id", "conversation_id", "thread_id", "session_id"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"IdentitySpec.{name} must not be empty")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "IdentitySpec":
        return cls(
            tenant_id=str(value.get("tenant_id") or ""),
            user_id=str(value.get("user_id") or ""),
            conversation_id=str(value.get("conversation_id") or ""),
            thread_id=str(value.get("thread_id") or ""),
            session_id=str(value.get("session_id") or ""),
            region=str(value.get("region")) if value.get("region") is not None else None,
            roles=tuple(str(x) for x in (value.get("roles") or ())),
            permissions=tuple(str(x) for x in (value.get("permissions") or ())),
        )

    def to_runtime_mapping(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "thread_id": self.thread_id,
            "session_id": self.session_id,
            "region": self.region,
            "roles": list(self.roles),
            "permissions": list(self.permissions),
        }

    def to_identity_context(self):
        from identity import IdentityContext

        return IdentityContext(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            thread_id=self.thread_id,
            session_id=self.session_id,
        )


@dataclass(frozen=True, slots=True)
class ExpectedBehavior:
    response_type: ResponseType
    required_agents: tuple[str, ...] = ()
    allowed_agents: tuple[str, ...] = ()
    forbidden_agents: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    clarification_required: bool | None = None
    required_clarification_slots: tuple[str, ...] = ()
    handoff_required: bool | None = None
    handoff_reason: str | None = None
    authorization_required: bool | None = None
    allowed_recovery_actions: tuple[str, ...] = ()
    forbidden_recovery_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConditionalSuccessCriterion:
    criterion: SuccessCriterion
    when: str


@dataclass(frozen=True, slots=True)
class TaskSuccessContract:
    """Conjunctive binary future task-success contract.

    Phase 1 only defines the contract.  Phase 2 evaluators will evaluate each
    required criterion; any required criterion failure means task failure.
    """

    required_criteria: tuple[SuccessCriterion, ...]
    conditional_criteria: tuple[ConditionalSuccessCriterion, ...] = ()


@dataclass(frozen=True, slots=True)
class GoldEvidence:
    evidence_id: str
    source_type: EvidenceSourceType
    required: bool = True
    alternative_group: str | None = None
    document_id: str | None = None
    section_id: str | None = None
    record_type: str | None = None
    record_id: str | None = None
    field_path: str | None = None
    expected_value: Any = None
    authority: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("GoldEvidence.evidence_id must not be empty")
        if self.source_type is EvidenceSourceType.DOCUMENT and not (self.document_id or self.section_id):
            raise ValueError("DOCUMENT GoldEvidence requires document_id or section_id")
        if self.source_type is EvidenceSourceType.STRUCTURED_DATA and not (self.record_type and self.record_id):
            raise ValueError("STRUCTURED_DATA GoldEvidence requires record_type and record_id")


@dataclass(frozen=True, slots=True)
class GoldFact:
    fact_id: str
    description: str
    normalized_value: Any
    value_type: FactValueType
    critical: bool
    supporting_evidence_ids: tuple[str, ...]
    comparison_mode: ComparisonMode

    def __post_init__(self) -> None:
        if not self.fact_id.strip():
            raise ValueError("GoldFact.fact_id must not be empty")
        if not self.description.strip():
            raise ValueError("GoldFact.description must not be empty")


@dataclass(frozen=True, slots=True)
class SafetyConstraint:
    tenant_boundary: str | None = None
    user_ownership: str | None = None
    required_permissions: tuple[str, ...] = ()
    forbidden_resources: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    forbidden_disclosures: tuple[str, ...] = ()
    expected_authorization_behavior: str | None = None

    @property
    def is_empty(self) -> bool:
        return not any((
            self.tenant_boundary,
            self.user_ownership,
            self.required_permissions,
            self.forbidden_resources,
            self.forbidden_tools,
            self.forbidden_disclosures,
            self.expected_authorization_behavior,
        ))


@dataclass(frozen=True, slots=True)
class AnnotationMetadata:
    annotation_status: AnnotationStatus
    annotated_by: tuple[str, ...] = ()
    reviewed_by: tuple[str, ...] = ()
    annotation_version: str = "1"
    review_notes: str | None = None


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    source_datasets: tuple[str, ...] = ()
    legacy_case_id: str | None = None
    legacy_layer: str | None = None
    legacy_category: str | None = None
    migration_status: MigrationStatus | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_name: str
    dataset_version: str
    schema_version: str
    created_at: str
    case_count: int
    category_distribution: Mapping[str, int]
    subcategory_distribution: Mapping[str, int]
    difficulty_distribution: Mapping[str, int]
    split_distribution: Mapping[str, int]
    annotation_status_distribution: Mapping[str, int]
    source_datasets: tuple[str, ...]
    gold_status: str
    review_status: str
    contamination_status: str
    intended_usage: str
    trust_level: SplitTrustLevel
    dataset_hash: str


@dataclass(frozen=True, slots=True)
class DatasetValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    case_count: int = 0


# ---------------------------------------------------------------------------
# Phase 2 formal E2E evaluation contracts
# ---------------------------------------------------------------------------

class CriterionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EVALUATED = "NOT_EVALUATED"
    ERROR = "ERROR"


class EvaluationMethod(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    LLM_JUDGE = "LLM_JUDGE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    COMPOSITE = "COMPOSITE"


class TaskSuccessStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class EvaluationEligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    MISSING_GOLD = "MISSING_GOLD"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNSUPPORTED_CRITERION = "UNSUPPORTED_CRITERION"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class CriterionJudgment:
    criterion: SuccessCriterion
    status: CriterionStatus
    evaluation_method: EvaluationMethod
    required: bool
    reason: str
    evidence_refs: tuple[str, ...] = ()
    trace_refs: tuple[str, ...] = ()
    judge_record_id: str | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskSuccessResult:
    task_success: TaskSuccessStatus
    required_criteria_total: int
    required_criteria_passed: int
    failed_criteria: tuple[SuccessCriterion, ...] = ()
    incomplete_criteria: tuple[SuccessCriterion, ...] = ()
    diagnostic_criteria: tuple[SuccessCriterion, ...] = ()
    reason: str = ""

    @property
    def task_success_bool(self) -> bool | None:
        if self.task_success is TaskSuccessStatus.PASS:
            return True
        if self.task_success is TaskSuccessStatus.FAIL:
            return False
        return None


@dataclass(frozen=True, slots=True)
class EvaluationEligibility:
    case_id: str
    status: EvaluationEligibilityStatus
    reasons: tuple[str, ...] = ()
    unsupported_criteria: tuple[SuccessCriterion, ...] = ()

    @property
    def eligible(self) -> bool:
        return self.status is EvaluationEligibilityStatus.ELIGIBLE


@dataclass(frozen=True, slots=True)
class HumanReviewItem:
    case_id: str
    criterion: SuccessCriterion
    prediction: Mapping[str, Any]
    gold: Mapping[str, Any]
    judge_decision: Mapping[str, Any] | None
    reason: str
    trace_id: str | None = None

# ---------------------------------------------------------------------------
# Phase 3 evidence reliability / claim grounding / recovery contracts
# ---------------------------------------------------------------------------

class EvidenceEvaluationEligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NO_GOLD_EVIDENCE = "NO_GOLD_EVIDENCE"
    NO_EVIDENCE_TRACE = "NO_EVIDENCE_TRACE"
    OBSERVABILITY_INSUFFICIENT = "OBSERVABILITY_INSUFFICIENT"
    UNSUPPORTED_PREDICTION_VERSION = "UNSUPPORTED_PREDICTION_VERSION"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class EvidenceRelevanceStatus(StrEnum):
    GOLD_MATCH = "GOLD_MATCH"
    SEMANTICALLY_RELEVANT = "SEMANTICALLY_RELEVANT"
    IRRELEVANT = "IRRELEVANT"
    NOT_EVALUATED = "NOT_EVALUATED"


class ClaimSupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    NOT_VERIFIABLE = "NOT_VERIFIABLE"


class FirstPassStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MISSING_STRUCTURED_DATA = "MISSING_STRUCTURED_DATA"
    MISSING_REQUIRED_SLOT = "MISSING_REQUIRED_SLOT"
    CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    VERIFIER_REJECTED = "VERIFIER_REJECTED"
    AUTHORIZATION_BLOCKED = "AUTHORIZATION_BLOCKED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    UNKNOWN = "UNKNOWN"


class RecoveryEvaluationEligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NO_FIRST_PASS_TRACE = "NO_FIRST_PASS_TRACE"
    MISSING_GOLD_EVIDENCE = "MISSING_GOLD_EVIDENCE"
    MISSING_RECOVERY_TRACE = "MISSING_RECOVERY_TRACE"
    NON_RECOVERABLE = "NON_RECOVERABLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNSUPPORTED = "UNSUPPORTED"


class RecoveryFailureReason(StrEnum):
    RETRIEVAL_MISS = "RETRIEVAL_MISS"
    STRUCTURED_DATA_MISSING = "STRUCTURED_DATA_MISSING"
    QUERY_REWRITE_INEFFECTIVE = "QUERY_REWRITE_INEFFECTIVE"
    SUPPLEMENT_INEFFECTIVE = "SUPPLEMENT_INEFFECTIVE"
    WRONG_CLARIFICATION = "WRONG_CLARIFICATION"
    OVER_CLARIFICATION = "OVER_CLARIFICATION"
    VERIFIER_FALSE_ACCEPT = "VERIFIER_FALSE_ACCEPT"
    VERIFIER_FALSE_REJECT = "VERIFIER_FALSE_REJECT"
    CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    TOOL_ERROR = "TOOL_ERROR"
    AUTHORIZATION_BLOCKED = "AUTHORIZATION_BLOCKED"
    GROUNDING_FAILURE = "GROUNDING_FAILURE"
    ANSWER_FAILURE = "ANSWER_FAILURE"
    OBSERVABILITY_INSUFFICIENT = "OBSERVABILITY_INSUFFICIENT"
    UNKNOWN = "UNKNOWN"


class RecoveryOutcome(StrEnum):
    RESOLVED_BY_ANSWER = "RESOLVED_BY_ANSWER"
    RESOLVED_BY_CLARIFICATION = "RESOLVED_BY_CLARIFICATION"
    RESOLVED_BY_HANDOFF = "RESOLVED_BY_HANDOFF"
    SAFELY_ABSTAINED = "SAFELY_ABSTAINED"
    FINAL_TASK_FAILED = "FINAL_TASK_FAILED"
    INCOMPLETE_EVALUATION = "INCOMPLETE_EVALUATION"


@dataclass(frozen=True, slots=True)
class EvaluationEvidenceRef:
    stable_id: str
    source_type: EvidenceSourceType
    evidence_id: str | None = None
    document_id: str | None = None
    section_id: str | None = None
    record_type: str | None = None
    record_id: str | None = None
    field_path: str | None = None
    tool_name: str | None = None
    result_ref: str | None = None
    round_id: int | None = None
    fusion_rank: int | None = None
    selected: bool = False
    status: str | None = None
    requirement_coverage: tuple[str, ...] = ()
    authority: Any = None
    validity: Any = None
    conflict_status: str | None = None
    final_citation_usage: bool = False
    content_preview: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceEvaluationEligibility:
    case_id: str
    status: EvidenceEvaluationEligibilityStatus
    reasons: tuple[str, ...] = ()

    @property
    def eligible(self) -> bool:
        return self.status is EvidenceEvaluationEligibilityStatus.ELIGIBLE


@dataclass(frozen=True, slots=True)
class EvidenceItemRelevance:
    stable_id: str
    status: EvidenceRelevanceStatus
    reason: str
    judge_record_id: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceCaseDiagnostic:
    case_id: str
    trace_id: str | None
    eligibility: EvidenceEvaluationEligibility
    any_required_evidence_recall_at_k: Mapping[int, bool | None]
    required_gold_evidence_recall_numerator: int
    required_gold_evidence_recall_denominator: int
    selected_evidence_precision_numerator: int
    selected_evidence_precision_denominator: int
    selected_evidence_precision_complete: bool
    retrieved_evidence: tuple[EvaluationEvidenceRef, ...] = ()
    selected_evidence: tuple[EvaluationEvidenceRef, ...] = ()
    selected_relevance: tuple[EvidenceItemRelevance, ...] = ()
    missing_required_units: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerClaim:
    claim_id: str
    text: str
    critical: bool
    claim_type: str = "FACT"
    normalized_subject: str | None = None
    normalized_predicate: str | None = None
    normalized_value: Any = None
    source_span: str | None = None
    gold_fact_id: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimSupport:
    claim: AnswerClaim
    status: ClaimSupportStatus
    evidence_refs: tuple[str, ...] = ()
    reason: str = ""
    evaluation_method: EvaluationMethod = EvaluationMethod.DETERMINISTIC
    judge_record_id: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimGroundingDiagnostic:
    case_id: str
    trace_id: str | None
    claims: tuple[AnswerClaim, ...]
    supports: tuple[ClaimSupport, ...]
    grounded_claim_numerator: int
    grounded_claim_denominator: int
    unsupported_critical_claims: int
    contradicted_critical_claims: int
    not_verifiable_critical_claims: int
    complete: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class FirstPassEvaluation:
    case_id: str
    status: FirstPassStatus
    gold_sufficient: bool | None
    production_verifier_action: str | None
    production_verifier_sufficient: bool | None
    false_accept: bool = False
    false_reject: bool = False
    first_pass_evidence_refs: tuple[str, ...] = ()
    missing_required_units: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RecoveryEvaluationEligibility:
    case_id: str
    status: RecoveryEvaluationEligibilityStatus
    reasons: tuple[str, ...] = ()

    @property
    def eligible(self) -> bool:
        return self.status is RecoveryEvaluationEligibilityStatus.ELIGIBLE


@dataclass(frozen=True, slots=True)
class RecoveryRound:
    round_index: int
    action: str | None = None
    input_query: str | None = None
    rewritten_query: str | None = None
    requested_slot: str | None = None
    new_evidence: tuple[str, ...] = ()
    verifier_decision: str | None = None
    latency_ms: float | None = None
    error: str | None = None
    budget_before: Mapping[str, Any] = field(default_factory=dict)
    budget_after: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecoveryTrace:
    case_id: str
    trace_id: str | None
    eligibility: RecoveryEvaluationEligibility
    first_pass: FirstPassEvaluation
    rounds: tuple[RecoveryRound, ...]
    actions: tuple[str, ...]
    recoverable: bool
    final_task_success: TaskSuccessStatus | None
    outcome: RecoveryOutcome
    failure_reason: RecoveryFailureReason | None = None
    recovery_rounds: int = 0
    unnecessary_recovery: bool = False
