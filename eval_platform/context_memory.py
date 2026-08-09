"""Phase-4 multi-turn Context/Memory/Artifact quality-cost evaluation.

The module extends the existing ``eval_platform`` core.  It does not redefine
Phase-2 Task Success or Phase-3 grounding.  Different context strategies are
explicit experiment configurations; inside each (session, strategy, turn) the
single-execution invariant still applies.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from statistics import mean, median
from typing import Any, Mapping, Sequence
from uuid import uuid4

from context_engine.strategy import ContextEvaluationStrategy, ContextStrategyConfig
from eval_platform.contracts import (
    AnnotationMetadata,
    AnnotationStatus,
    ComparisonMode,
    ConditionalSuccessCriterion,
    DatasetSplit,
    Difficulty,
    EvidenceSourceType,
    ExpectedBehavior,
    FactValueType,
    GoldEvidence,
    GoldFact,
    IdentitySpec,
    ResponseType,
    SafetyConstraint,
    SourceMetadata,
    SuccessCriterion,
    TaskCategory,
    TaskSuccessContract,
    TaskSuccessStatus,
)
from eval_platform.dataset import EvaluationSample, RuntimeCaseInput, RuntimeMessage
from eval_platform.report import CaseJudgment, PredictionRecord


PHASE4_SESSION_SCHEMA_VERSION = "1.0"
PHASE4_CONTEXT_DIAGNOSTIC_VERSION = "1.0"


class ContextUnitType(StrEnum):
    USER_FACT = "USER_FACT"
    ENTITY = "ENTITY"
    SLOT = "SLOT"
    DECISION = "DECISION"
    OPEN_QUESTION = "OPEN_QUESTION"
    CONSTRAINT = "CONSTRAINT"
    PREVIOUS_TOOL_RESULT_REF = "PREVIOUS_TOOL_RESULT_REF"
    PREVIOUS_EVIDENCE_REF = "PREVIOUS_EVIDENCE_REF"
    MEMORY_FACT = "MEMORY_FACT"
    ARTIFACT_REF = "ARTIFACT_REF"


class ContextRelevance(StrEnum):
    REQUIRED = "REQUIRED"
    HELPFUL = "HELPFUL"
    IRRELEVANT = "IRRELEVANT"
    HARMFUL = "HARMFUL"
    NOT_EVALUATED = "NOT_EVALUATED"


class TokenCountSource(StrEnum):
    PROVIDER_ACTUAL = "PROVIDER_ACTUAL"
    TOKENIZER_ESTIMATE = "TOKENIZER_ESTIMATE"
    HEURISTIC_ESTIMATE = "HEURISTIC_ESTIMATE"
    UNKNOWN = "UNKNOWN"


class SessionEligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    MISSING_CONTEXT_GOLD = "MISSING_CONTEXT_GOLD"
    MISSING_MEMORY_GOLD = "MISSING_MEMORY_GOLD"
    MISSING_TASK_GOLD = "MISSING_TASK_GOLD"
    UNSUPPORTED_STRATEGY = "UNSUPPORTED_STRATEGY"
    OBSERVABILITY_INSUFFICIENT = "OBSERVABILITY_INSUFFICIENT"
    INVALID = "INVALID"


class SessionTaskSuccessStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class MemoryContaminationType(StrEnum):
    STALE_FACT_USED = "STALE_FACT_USED"
    SUPERSEDED_FACT_USED = "SUPERSEDED_FACT_USED"
    WRONG_ENTITY_FACT_USED = "WRONG_ENTITY_FACT_USED"
    CROSS_SESSION_FACT_USED = "CROSS_SESSION_FACT_USED"
    CROSS_USER_FACT_USED = "CROSS_USER_FACT_USED"
    CROSS_TENANT_FACT_USED = "CROSS_TENANT_FACT_USED"
    UNSUPPORTED_MEMORY_FACT_USED = "UNSUPPORTED_MEMORY_FACT_USED"
    IRRELEVANT_MEMORY_INFLUENCED_ANSWER = "IRRELEVANT_MEMORY_INFLUENCED_ANSWER"


class ContextFailureReason(StrEnum):
    CONTEXT_REQUIRED_FACT_DROPPED = "CONTEXT_REQUIRED_FACT_DROPPED"
    SUMMARY_LOST_REQUIRED_FACT = "SUMMARY_LOST_REQUIRED_FACT"
    SUMMARY_INTRODUCED_FALSE_FACT = "SUMMARY_INTRODUCED_FALSE_FACT"
    SUMMARY_STALE_AFTER_UPDATE = "SUMMARY_STALE_AFTER_UPDATE"
    MEMORY_NOT_WRITTEN = "MEMORY_NOT_WRITTEN"
    MEMORY_NOT_RETRIEVED = "MEMORY_NOT_RETRIEVED"
    MEMORY_NOT_SELECTED = "MEMORY_NOT_SELECTED"
    MEMORY_STALE = "MEMORY_STALE"
    MEMORY_CONTAMINATION = "MEMORY_CONTAMINATION"
    MEMORY_POLICY_BLOCKED = "MEMORY_POLICY_BLOCKED"
    ARTIFACT_NOT_REGISTERED = "ARTIFACT_NOT_REGISTERED"
    ARTIFACT_NOT_RESOLVED = "ARTIFACT_NOT_RESOLVED"
    ARTIFACT_WRONG_IDENTITY = "ARTIFACT_WRONG_IDENTITY"
    ARTIFACT_CONTENT_INSUFFICIENT = "ARTIFACT_CONTENT_INSUFFICIENT"
    ARTIFACT_CONTEXT_NOT_SELECTED = "ARTIFACT_CONTEXT_NOT_SELECTED"
    ENTITY_CONTEXT_LOST = "ENTITY_CONTEXT_LOST"
    CONTEXT_BUDGET_EXHAUSTED = "CONTEXT_BUDGET_EXHAUSTED"
    OVER_CONTEXT_FAILURE = "OVER_CONTEXT_FAILURE"


class ArtifactDiagnosticStatus(StrEnum):
    CORRECT_REUSE = "CORRECT_REUSE"
    MISSING = "MISSING"
    WRONG_ARTIFACT = "WRONG_ARTIFACT"
    WRONG_IDENTITY = "WRONG_IDENTITY"
    CONTENT_INSUFFICIENT = "CONTENT_INSUFFICIENT"
    NOT_SELECTED = "NOT_SELECTED"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True, slots=True)
class RequiredContextUnit:
    unit_id: str
    unit_type: ContextUnitType
    description: str
    source_ref: str | None = None
    normalized_value: Any = None
    critical: bool = True
    supersedes_unit_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.unit_id).strip():
            raise ValueError("RequiredContextUnit.unit_id must not be empty")
        if not isinstance(self.unit_type, ContextUnitType):
            object.__setattr__(self, "unit_type", ContextUnitType(str(self.unit_type).upper()))
        if not str(self.description).strip():
            raise ValueError("RequiredContextUnit.description must not be empty")

    def to_state(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "unit_type": self.unit_type.value,
            "description": self.description,
            "source_ref": self.source_ref,
            "normalized_value": self.normalized_value,
            "critical": self.critical,
            "supersedes_unit_ids": list(self.supersedes_unit_ids),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "RequiredContextUnit":
        return cls(
            unit_id=str(value.get("unit_id") or ""),
            unit_type=ContextUnitType(str(value.get("unit_type") or "")),
            description=str(value.get("description") or ""),
            source_ref=value.get("source_ref"),
            normalized_value=value.get("normalized_value"),
            critical=bool(value.get("critical", True)),
            supersedes_unit_ids=tuple(value.get("supersedes_unit_ids") or ()),
        )


@dataclass(frozen=True, slots=True)
class MemoryExpectation:
    memory_dependent: bool = False
    required_fact_ids: tuple[str, ...] = ()
    allowed_fact_ids: tuple[str, ...] = ()
    superseded_fact_ids: tuple[str, ...] = ()
    stale_fact_ids: tuple[str, ...] = ()
    forbidden_fact_ids: tuple[str, ...] = ()
    active_entity_refs: tuple[str, ...] = ()
    disallow_cross_session_working_memory: bool = True

    def to_state(self) -> dict[str, Any]:
        return {
            "memory_dependent": self.memory_dependent,
            "required_fact_ids": list(self.required_fact_ids),
            "allowed_fact_ids": list(self.allowed_fact_ids),
            "superseded_fact_ids": list(self.superseded_fact_ids),
            "stale_fact_ids": list(self.stale_fact_ids),
            "forbidden_fact_ids": list(self.forbidden_fact_ids),
            "active_entity_refs": list(self.active_entity_refs),
            "disallow_cross_session_working_memory": self.disallow_cross_session_working_memory,
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "MemoryExpectation":
        return cls(
            memory_dependent=bool(value.get("memory_dependent", False)),
            required_fact_ids=tuple(value.get("required_fact_ids") or ()),
            allowed_fact_ids=tuple(value.get("allowed_fact_ids") or ()),
            superseded_fact_ids=tuple(value.get("superseded_fact_ids") or ()),
            stale_fact_ids=tuple(value.get("stale_fact_ids") or ()),
            forbidden_fact_ids=tuple(value.get("forbidden_fact_ids") or ()),
            active_entity_refs=tuple(value.get("active_entity_refs") or ()),
            disallow_cross_session_working_memory=bool(value.get("disallow_cross_session_working_memory", True)),
        )


@dataclass(frozen=True, slots=True)
class ArtifactExpectation:
    required_artifact_ids: tuple[str, ...] = ()
    required_source_refs: tuple[str, ...] = ()
    identity_scoped: bool = True

    def to_state(self) -> dict[str, Any]:
        return {
            "required_artifact_ids": list(self.required_artifact_ids),
            "required_source_refs": list(self.required_source_refs),
            "identity_scoped": self.identity_scoped,
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "ArtifactExpectation":
        return cls(
            required_artifact_ids=tuple(value.get("required_artifact_ids") or ()),
            required_source_refs=tuple(value.get("required_source_refs") or ()),
            identity_scoped=bool(value.get("identity_scoped", True)),
        )


@dataclass(frozen=True, slots=True)
class CanonicalEvaluationTurn:
    turn_id: str
    turn_index: int
    user_input: str
    expected_behavior: ExpectedBehavior
    task_success_contract: TaskSuccessContract
    runtime_input_delta: Mapping[str, Any] = field(default_factory=dict)
    gold_evidence: tuple[GoldEvidence, ...] = ()
    gold_facts: tuple[GoldFact, ...] = ()
    safety_constraints: tuple[SafetyConstraint, ...] = ()
    required_context_units: tuple[RequiredContextUnit, ...] = ()
    memory_expectations: MemoryExpectation = field(default_factory=MemoryExpectation)
    artifact_expectations: ArtifactExpectation = field(default_factory=ArtifactExpectation)
    state_updates: Mapping[str, Any] = field(default_factory=dict)
    annotation_status: AnnotationStatus = AnnotationStatus.NEEDS_REVIEW

    def __post_init__(self) -> None:
        if not self.turn_id.strip():
            raise ValueError("turn_id must not be empty")
        if self.turn_index < 0:
            raise ValueError("turn_index must not be negative")
        if not self.user_input.strip():
            raise ValueError("user_input must not be empty")
        if not isinstance(self.annotation_status, AnnotationStatus):
            object.__setattr__(self, "annotation_status", AnnotationStatus(str(self.annotation_status)))

    def to_state(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "turn_index": self.turn_index,
            "user_input": self.user_input,
            "runtime_input_delta": dict(self.runtime_input_delta),
            "expected_behavior": _expected_behavior_state(self.expected_behavior),
            "task_success_contract": _task_contract_state(self.task_success_contract),
            "gold_evidence": [_gold_evidence_state(x) for x in self.gold_evidence],
            "gold_facts": [_gold_fact_state(x) for x in self.gold_facts],
            "safety_constraints": [_safety_constraint_state(x) for x in self.safety_constraints],
            "required_context_units": [x.to_state() for x in self.required_context_units],
            "memory_expectations": self.memory_expectations.to_state(),
            "artifact_expectations": self.artifact_expectations.to_state(),
            "state_updates": dict(self.state_updates),
            "annotation_status": self.annotation_status.value,
        }


    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "CanonicalEvaluationTurn":
        behavior = _expected_behavior_from_state(value.get("expected_behavior") or {})
        contract = _task_contract_from_state(value.get("task_success_contract") or {})
        return cls(
            turn_id=str(value.get("turn_id") or ""),
            turn_index=int(value.get("turn_index", 0)),
            user_input=str(value.get("user_input") or ""),
            runtime_input_delta=dict(value.get("runtime_input_delta") or {}),
            expected_behavior=behavior,
            task_success_contract=contract,
            gold_evidence=tuple(_gold_evidence_from_state(x) for x in (value.get("gold_evidence") or ())),
            gold_facts=tuple(_gold_fact_from_state(x) for x in (value.get("gold_facts") or ())),
            safety_constraints=tuple(_safety_constraint_from_state(x) for x in (value.get("safety_constraints") or ())),
            required_context_units=tuple(RequiredContextUnit.from_state(x) for x in (value.get("required_context_units") or ())),
            memory_expectations=MemoryExpectation.from_state(value.get("memory_expectations") or {}),
            artifact_expectations=ArtifactExpectation.from_state(value.get("artifact_expectations") or {}),
            state_updates=dict(value.get("state_updates") or {}),
            annotation_status=AnnotationStatus(str(value.get("annotation_status") or AnnotationStatus.NEEDS_REVIEW.value)),
        )


@dataclass(frozen=True, slots=True)
class SessionTaskSuccessContract:
    required_terminal_turn_pass: bool = True
    required_turn_ids: tuple[str, ...] = ()
    require_no_safety_violation: bool = True
    require_no_memory_contamination: bool = False

    def to_state(self) -> dict[str, Any]:
        return {
            "required_terminal_turn_pass": self.required_terminal_turn_pass,
            "required_turn_ids": list(self.required_turn_ids),
            "require_no_safety_violation": self.require_no_safety_violation,
            "require_no_memory_contamination": self.require_no_memory_contamination,
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "SessionTaskSuccessContract":
        return cls(
            required_terminal_turn_pass=bool(value.get("required_terminal_turn_pass", True)),
            required_turn_ids=tuple(str(x) for x in (value.get("required_turn_ids") or ())),
            require_no_safety_violation=bool(value.get("require_no_safety_violation", True)),
            require_no_memory_contamination=bool(value.get("require_no_memory_contamination", False)),
        )


@dataclass(frozen=True, slots=True)
class CanonicalEvaluationSession:
    session_id: str
    schema_version: str
    split: DatasetSplit
    category: TaskCategory
    subcategory: str
    difficulty: Difficulty
    tags: tuple[str, ...]
    initial_identity: IdentitySpec
    turns: tuple[CanonicalEvaluationTurn, ...]
    session_success_contract: SessionTaskSuccessContract = field(default_factory=SessionTaskSuccessContract)
    initial_context: Mapping[str, Any] = field(default_factory=dict)
    annotation_metadata: AnnotationMetadata = field(default_factory=lambda: AnnotationMetadata(annotation_status=AnnotationStatus.NEEDS_REVIEW))
    source_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if self.schema_version != PHASE4_SESSION_SCHEMA_VERSION:
            raise ValueError(f"unsupported session schema_version: {self.schema_version}")
        if not self.turns:
            raise ValueError("session must contain at least one turn")
        indexes = [turn.turn_index for turn in self.turns]
        if indexes != sorted(indexes) or len(set(indexes)) != len(indexes):
            raise ValueError("turn indexes must be unique and ordered")
        ids = [turn.turn_id for turn in self.turns]
        if len(set(ids)) != len(ids):
            raise ValueError("turn ids must be unique within session")

    def to_state(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "schema_version": self.schema_version,
            "split": self.split.value,
            "category": self.category.value,
            "subcategory": self.subcategory,
            "difficulty": self.difficulty.value,
            "tags": list(self.tags),
            "initial_identity": self.initial_identity.to_runtime_mapping(),
            "initial_context": dict(self.initial_context),
            "turns": [turn.to_state() for turn in self.turns],
            "session_success_contract": self.session_success_contract.to_state(),
            "annotation_metadata": {
                "annotation_status": self.annotation_metadata.annotation_status.value,
                "annotated_by": list(self.annotation_metadata.annotated_by),
                "reviewed_by": list(self.annotation_metadata.reviewed_by),
                "annotation_version": self.annotation_metadata.annotation_version,
                "review_notes": self.annotation_metadata.review_notes,
            },
            "source_metadata": dict(self.source_metadata),
        }

    @property
    def dataset_hash_fragment(self) -> str:
        raw = json.dumps(self.to_state(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(raw.encode("utf-8")).hexdigest()


    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "CanonicalEvaluationSession":
        annotation = value.get("annotation_metadata") or {}
        return cls(
            session_id=str(value.get("session_id") or ""),
            schema_version=str(value.get("schema_version") or ""),
            split=DatasetSplit(str(value.get("split") or DatasetSplit.DEVELOPMENT.value)),
            category=TaskCategory(str(value.get("category") or TaskCategory.KNOWLEDGE_QA.value)),
            subcategory=str(value.get("subcategory") or "MULTI_TURN"),
            difficulty=Difficulty(str(value.get("difficulty") or Difficulty.MEDIUM.value)),
            tags=tuple(str(x) for x in (value.get("tags") or ())),
            initial_identity=IdentitySpec.from_mapping(value.get("initial_identity") or {}),
            initial_context=dict(value.get("initial_context") or {}),
            turns=tuple(CanonicalEvaluationTurn.from_state(x) for x in (value.get("turns") or ())),
            session_success_contract=SessionTaskSuccessContract.from_state(value.get("session_success_contract") or {}),
            annotation_metadata=AnnotationMetadata(
                annotation_status=AnnotationStatus(str(annotation.get("annotation_status") or AnnotationStatus.NEEDS_REVIEW.value)),
                annotated_by=tuple(str(x) for x in (annotation.get("annotated_by") or ())),
                reviewed_by=tuple(str(x) for x in (annotation.get("reviewed_by") or ())),
                annotation_version=str(annotation.get("annotation_version") or "1"),
                review_notes=annotation.get("review_notes"),
            ),
            source_metadata=dict(value.get("source_metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class SessionEligibility:
    session_id: str
    status: SessionEligibilityStatus
    reasons: tuple[str, ...] = ()

    @property
    def eligible(self) -> bool:
        return self.status is SessionEligibilityStatus.ELIGIBLE

    def to_state(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "status": self.status.value, "reasons": list(self.reasons)}


@dataclass(frozen=True, slots=True)
class TokenUsageRecord:
    model_call_id: str
    input_tokens: int
    output_tokens: int = 0
    source: TokenCountSource = TokenCountSource.UNKNOWN

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts must not be negative")
        if not isinstance(self.source, TokenCountSource):
            object.__setattr__(self, "source", TokenCountSource(str(self.source)))

    def to_state(self) -> dict[str, Any]:
        return {
            "model_call_id": self.model_call_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "source": self.source.value,
        }


@dataclass(frozen=True, slots=True)
class ContextUnitObservation:
    context_item_id: str
    context_type: str
    source: str
    source_ref: str
    selected: bool
    token_count: int
    relevance: ContextRelevance = ContextRelevance.NOT_EVALUATED
    memory_kind: str | None = None
    fact_id: str | None = None
    artifact_id: str | None = None
    summary_metadata: Mapping[str, Any] | None = None
    identity_scope: Mapping[str, Any] | None = None
    working_memory_fact_refs: tuple[str, ...] = ()

    def to_state(self) -> dict[str, Any]:
        return {
            "context_item_id": self.context_item_id,
            "context_type": self.context_type,
            "source": self.source,
            "source_ref": self.source_ref,
            "selected": self.selected,
            "token_count": self.token_count,
            "relevance": self.relevance.value,
            "memory_kind": self.memory_kind,
            "fact_id": self.fact_id,
            "artifact_id": self.artifact_id,
            "summary_metadata": dict(self.summary_metadata or {}),
            "identity_scope_hash": _scope_hash(self.identity_scope),
            "working_memory_fact_refs": list(self.working_memory_fact_refs),
        }


@dataclass(frozen=True, slots=True)
class ContextTurnDiagnostic:
    session_id: str
    turn_id: str
    strategy: ContextEvaluationStrategy
    trace_id: str | None
    context_recall_numerator: int
    context_recall_denominator: int
    context_precision_numerator: int
    context_precision_denominator: int
    token_usage: tuple[TokenUsageRecord, ...]
    observations: tuple[ContextUnitObservation, ...]
    missing_required_units: tuple[str, ...] = ()
    not_evaluated_context_items: tuple[str, ...] = ()
    failure_reasons: tuple[ContextFailureReason, ...] = ()

    @property
    def context_recall(self) -> float | None:
        return self.context_recall_numerator / self.context_recall_denominator if self.context_recall_denominator else None

    @property
    def context_precision(self) -> float | None:
        return self.context_precision_numerator / self.context_precision_denominator if self.context_precision_denominator else None

    @property
    def total_input_tokens(self) -> int:
        return sum(item.input_tokens for item in self.token_usage)

    def to_state(self) -> dict[str, Any]:
        return {
            "schema_version": PHASE4_CONTEXT_DIAGNOSTIC_VERSION,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "strategy": self.strategy.value,
            "trace_id": self.trace_id,
            "context_recall": _metric(self.context_recall_numerator, self.context_recall_denominator),
            "context_precision": _metric(self.context_precision_numerator, self.context_precision_denominator),
            "total_input_tokens": self.total_input_tokens,
            "token_usage": [x.to_state() for x in self.token_usage],
            "observations": [x.to_state() for x in self.observations],
            "missing_required_units": list(self.missing_required_units),
            "not_evaluated_context_items": list(self.not_evaluated_context_items),
            "failure_reasons": [x.value for x in self.failure_reasons],
        }


@dataclass(frozen=True, slots=True)
class MemoryContaminationEvent:
    session_id: str
    turn_id: str
    event_type: MemoryContaminationType
    context_item_id: str
    fact_id: str | None
    reason: str
    safety_violation: bool = False

    def to_state(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "event_type": self.event_type.value,
            "context_item_id": self.context_item_id,
            "fact_id": self.fact_id,
            "reason": self.reason,
            "safety_violation": self.safety_violation,
        }


@dataclass(frozen=True, slots=True)
class ArtifactDiagnostic:
    session_id: str
    turn_id: str
    artifact_id: str | None
    status: ArtifactDiagnosticStatus
    reason: str
    context_tokens: int = 0
    estimated_payload_tokens: int = 0

    @property
    def estimated_saved_tokens(self) -> int:
        return max(0, self.estimated_payload_tokens - self.context_tokens)

    def to_state(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "artifact_id": self.artifact_id,
            "status": self.status.value,
            "reason": self.reason,
            "context_tokens": self.context_tokens,
            "estimated_payload_tokens": self.estimated_payload_tokens,
            "estimated_saved_tokens": self.estimated_saved_tokens,
            "formal_token_saving": False,
        }


@dataclass(frozen=True, slots=True)
class SessionStrategyResult:
    session_id: str
    strategy: ContextEvaluationStrategy
    predictions: tuple[PredictionRecord, ...]
    judgments: tuple[CaseJudgment, ...]
    context_diagnostics: tuple[ContextTurnDiagnostic, ...]
    contamination_events: tuple[MemoryContaminationEvent, ...]
    artifact_diagnostics: tuple[ArtifactDiagnostic, ...]
    session_success_status: SessionTaskSuccessStatus
    execution_errors: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def total_input_tokens(self) -> int:
        return sum(item.total_input_tokens for item in self.context_diagnostics)

    @property
    def turn_count(self) -> int:
        return len(self.context_diagnostics)

    def to_state(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "strategy": self.strategy.value,
            "session_success_status": self.session_success_status.value,
            "execution_errors": self.execution_errors,
            "turn_count": self.turn_count,
            "total_input_tokens": self.total_input_tokens,
            "context_diagnostics": [x.to_state() for x in self.context_diagnostics],
            "memory_contamination": [x.to_state() for x in self.contamination_events],
            "artifact_diagnostics": [x.to_state() for x in self.artifact_diagnostics],
            "prediction_refs": [{"case_id": p.case_id, "run_id": p.run_id, "trace_id": p.trace_id} for p in self.predictions],
            "judgment_refs": [{"case_id": j.case_id, "task_success_status": j.task_success_status.value if j.task_success_status else None} for j in self.judgments],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ContextStrategyExperimentRun:
    run_id: str
    results: tuple[SessionStrategyResult, ...]
    session_eligibilities: tuple[SessionEligibility, ...]
    strategy_configs: tuple[ContextStrategyConfig, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "result_count": len(self.results),
            "session_eligibilities": [x.to_state() for x in self.session_eligibilities],
            "strategy_configs": [x.to_state() for x in self.strategy_configs],
            "metadata": dict(self.metadata),
        }


def canonical_session_dataset_hash(sessions: Sequence[CanonicalEvaluationSession]) -> str:
    normalized = [session.to_state() for session in sorted(sessions, key=lambda x: x.session_id)]
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def write_canonical_sessions(path: str | Path, sessions: Sequence[CanonicalEvaluationSession]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [session.to_state() for session in sessions]
    if target.suffix.lower() == ".jsonl":
        target.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in payload), encoding="utf-8")
    else:
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target


def read_canonical_sessions(path: str | Path) -> tuple[CanonicalEvaluationSession, ...]:
    source = Path(path)
    if source.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        raw = json.loads(source.read_text(encoding="utf-8"))
        rows = raw.get("sessions", []) if isinstance(raw, Mapping) else raw
    if not isinstance(rows, list):
        raise ValueError("canonical session dataset must be a JSON list or {'sessions': [...]} object")
    sessions = tuple(CanonicalEvaluationSession.from_state(row) for row in rows)
    validate_sessions(sessions)
    return sessions


def session_dataset_inventory(sessions: Sequence[CanonicalEvaluationSession]) -> dict[str, Any]:
    eligibilities = validate_sessions(sessions)
    status_counts = Counter(x.status.value for x in eligibilities)
    tag_counts = Counter(tag for session in sessions for tag in session.tags)
    category_counts = Counter(session.category.value for session in sessions)
    turn_counts = [len(session.turns) for session in sessions]
    return {
        "candidate_sessions": len(sessions),
        "eligible_sessions": status_counts.get(SessionEligibilityStatus.ELIGIBLE.value, 0),
        "needs_review_sessions": status_counts.get(SessionEligibilityStatus.NEEDS_REVIEW.value, 0),
        "eligibility_statuses": dict(sorted(status_counts.items())),
        "turn_count": sum(turn_counts),
        "average_turns_per_session": mean(turn_counts) if turn_counts else 0.0,
        "category_distribution": dict(sorted(category_counts.items())),
        "tag_distribution": dict(sorted(tag_counts.items())),
        "dataset_hash": canonical_session_dataset_hash(sessions),
    }


def _expected_behavior_state(value: ExpectedBehavior) -> dict[str, Any]:
    return {
        "response_type": value.response_type.value,
        "required_agents": list(value.required_agents),
        "allowed_agents": list(value.allowed_agents),
        "forbidden_agents": list(value.forbidden_agents),
        "required_tools": list(value.required_tools),
        "allowed_tools": list(value.allowed_tools),
        "forbidden_tools": list(value.forbidden_tools),
        "clarification_required": value.clarification_required,
        "required_clarification_slots": list(value.required_clarification_slots),
        "handoff_required": value.handoff_required,
        "handoff_reason": value.handoff_reason,
        "authorization_required": value.authorization_required,
        "allowed_recovery_actions": list(value.allowed_recovery_actions),
        "forbidden_recovery_actions": list(value.forbidden_recovery_actions),
    }


def _task_contract_state(value: TaskSuccessContract) -> dict[str, Any]:
    return {
        "required_criteria": [x.value for x in value.required_criteria],
        "conditional_criteria": [{"criterion": x.criterion.value, "when": x.when} for x in value.conditional_criteria],
    }


def _gold_evidence_state(value: GoldEvidence) -> dict[str, Any]:
    return {
        "evidence_id": value.evidence_id,
        "source_type": value.source_type.value,
        "required": value.required,
        "alternative_group": value.alternative_group,
        "document_id": value.document_id,
        "section_id": value.section_id,
        "record_type": value.record_type,
        "record_id": value.record_id,
        "field_path": value.field_path,
        "expected_value": value.expected_value,
        "authority": value.authority,
        "effective_from": value.effective_from,
        "effective_to": value.effective_to,
        "metadata": dict(value.metadata),
    }


def _gold_fact_state(value: GoldFact) -> dict[str, Any]:
    return {
        "fact_id": value.fact_id,
        "description": value.description,
        "normalized_value": value.normalized_value,
        "value_type": value.value_type.value,
        "critical": value.critical,
        "supporting_evidence_ids": list(value.supporting_evidence_ids),
        "comparison_mode": value.comparison_mode.value,
    }


def _expected_behavior_from_state(value: Mapping[str, Any]) -> ExpectedBehavior:
    return ExpectedBehavior(
        response_type=ResponseType(str(value.get("response_type") or ResponseType.ANSWER.value)),
        required_agents=tuple(value.get("required_agents") or ()),
        allowed_agents=tuple(value.get("allowed_agents") or ()),
        forbidden_agents=tuple(value.get("forbidden_agents") or ()),
        required_tools=tuple(value.get("required_tools") or ()),
        allowed_tools=tuple(value.get("allowed_tools") or ()),
        forbidden_tools=tuple(value.get("forbidden_tools") or ()),
        clarification_required=value.get("clarification_required"),
        required_clarification_slots=tuple(value.get("required_clarification_slots") or ()),
        handoff_required=value.get("handoff_required"),
        handoff_reason=value.get("handoff_reason"),
        authorization_required=value.get("authorization_required"),
        allowed_recovery_actions=tuple(value.get("allowed_recovery_actions") or ()),
        forbidden_recovery_actions=tuple(value.get("forbidden_recovery_actions") or ()),
    )


def _task_contract_from_state(value: Mapping[str, Any]) -> TaskSuccessContract:
    return TaskSuccessContract(
        required_criteria=tuple(SuccessCriterion(str(x)) for x in (value.get("required_criteria") or ())),
        conditional_criteria=tuple(
            ConditionalSuccessCriterion(SuccessCriterion(str(item.get("criterion"))), str(item.get("when") or ""))
            for item in (value.get("conditional_criteria") or ())
        ),
    )


def _gold_evidence_from_state(value: Mapping[str, Any]) -> GoldEvidence:
    return GoldEvidence(
        evidence_id=str(value.get("evidence_id") or ""),
        source_type=EvidenceSourceType(str(value.get("source_type") or EvidenceSourceType.DOCUMENT.value)),
        required=bool(value.get("required", True)), alternative_group=value.get("alternative_group"),
        document_id=value.get("document_id"), section_id=value.get("section_id"),
        record_type=value.get("record_type"), record_id=value.get("record_id"), field_path=value.get("field_path"),
        expected_value=value.get("expected_value"), authority=value.get("authority"),
        effective_from=value.get("effective_from"), effective_to=value.get("effective_to"),
        metadata=dict(value.get("metadata") or {}),
    )


def _gold_fact_from_state(value: Mapping[str, Any]) -> GoldFact:
    return GoldFact(
        fact_id=str(value.get("fact_id") or ""), description=str(value.get("description") or ""),
        normalized_value=value.get("normalized_value"), value_type=FactValueType(str(value.get("value_type") or FactValueType.STRING.value)),
        critical=bool(value.get("critical", True)), supporting_evidence_ids=tuple(value.get("supporting_evidence_ids") or ()),
        comparison_mode=ComparisonMode(str(value.get("comparison_mode") or ComparisonMode.SEMANTIC.value)),
    )


def _safety_constraint_state(value: SafetyConstraint) -> dict[str, Any]:
    return {
        "tenant_boundary": value.tenant_boundary, "user_ownership": value.user_ownership,
        "required_permissions": list(value.required_permissions), "forbidden_resources": list(value.forbidden_resources),
        "forbidden_tools": list(value.forbidden_tools), "forbidden_disclosures": list(value.forbidden_disclosures),
        "expected_authorization_behavior": value.expected_authorization_behavior,
    }


def _safety_constraint_from_state(value: Mapping[str, Any]) -> SafetyConstraint:
    return SafetyConstraint(
        tenant_boundary=value.get("tenant_boundary"), user_ownership=value.get("user_ownership"),
        required_permissions=tuple(value.get("required_permissions") or ()),
        forbidden_resources=tuple(value.get("forbidden_resources") or ()),
        forbidden_tools=tuple(value.get("forbidden_tools") or ()),
        forbidden_disclosures=tuple(value.get("forbidden_disclosures") or ()),
        expected_authorization_behavior=value.get("expected_authorization_behavior"),
    )


def _scope_hash(scope: Mapping[str, Any] | None) -> str | None:
    if not scope:
        return None
    raw = json.dumps(dict(scope), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()[:16]


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else None}


def percentile95(values: Sequence[int | float]) -> float | None:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    index = max(0, ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def validate_session(session: CanonicalEvaluationSession) -> SessionEligibility:
    reasons: list[str] = []
    if session.annotation_metadata.annotation_status is not AnnotationStatus.HUMAN_REVIEWED:
        reasons.append("session annotation is not HUMAN_REVIEWED")
        status = SessionEligibilityStatus.NEEDS_REVIEW
    else:
        status = SessionEligibilityStatus.ELIGIBLE
    for turn in session.turns:
        if not turn.task_success_contract.required_criteria:
            reasons.append(f"{turn.turn_id}: missing TaskSuccessContract")
            status = SessionEligibilityStatus.MISSING_TASK_GOLD
        if turn.turn_index > 0 and not turn.required_context_units and turn.memory_expectations.memory_dependent:
            reasons.append(f"{turn.turn_id}: memory-dependent turn lacks required context Gold")
            status = SessionEligibilityStatus.MISSING_CONTEXT_GOLD
    return SessionEligibility(session.session_id, status, tuple(reasons))


def validate_sessions(sessions: Sequence[CanonicalEvaluationSession]) -> tuple[SessionEligibility, ...]:
    if not sessions:
        raise ValueError("session dataset must not be empty")
    ids = [s.session_id for s in sessions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate session_id")
    return tuple(validate_session(s) for s in sessions)


def strategy_config(strategy: ContextEvaluationStrategy | str, *, max_tokens: int = 4096, window_turns: int = 3) -> ContextStrategyConfig:
    return ContextStrategyConfig.for_strategy(strategy, max_tokens=max_tokens, window_turns=window_turns)


def strategy_runtime_context(config: ContextStrategyConfig) -> dict[str, Any]:
    """Map experiment config to the production ``config.Context`` schema."""

    return {
        "context_strategy": config.strategy.value,
        "context_sliding_window_turns": config.window_turns,
        "context_max_tokens": config.max_tokens,
        # These are retained for run metadata and default/full-strategy tuning;
        # non-default strategy switches are resolved by ContextRuntime itself.
        "context_compaction_enabled": config.compaction_enabled if config.compaction_enabled is not None else True,
        "long_term_memory_enabled": config.long_term_memory_enabled if config.long_term_memory_enabled is not None else True,
    }


def trace_context_observations(prediction: PredictionRecord) -> tuple[ContextUnitObservation, ...]:
    assemblies = list(prediction.trace_facts.get("context_assemblies") or ())
    if not assemblies:
        return ()
    # The final task-relevant model input is the formal minimum Context Recall
    # observation point. Earlier calls remain in trace for diagnostics.
    refs = list((assemblies[-1] or {}).get("context_item_refs") or ())
    observations: list[ContextUnitObservation] = []
    for item in refs:
        if not isinstance(item, Mapping):
            continue
        observations.append(ContextUnitObservation(
            context_item_id=str(item.get("context_item_id") or ""),
            context_type=str(item.get("type") or ""),
            source=str(item.get("source") or ""),
            source_ref=str(item.get("source_ref") or item.get("context_item_id") or ""),
            selected=bool(item.get("selected")),
            token_count=int(item.get("token_count", 0) or 0),
            memory_kind=item.get("memory_kind"),
            fact_id=item.get("fact_id"),
            artifact_id=item.get("artifact_id"),
            summary_metadata=item.get("summary_metadata") if isinstance(item.get("summary_metadata"), Mapping) else None,
            identity_scope=item.get("identity_context") if isinstance(item.get("identity_context"), Mapping) else None,
            working_memory_fact_refs=tuple(str(x) for x in (item.get("working_memory_fact_refs") or ())),
        ))
    return tuple(observations)


def prediction_token_usage(prediction: PredictionRecord) -> tuple[TokenUsageRecord, ...]:
    rows = list(prediction.trace_facts.get("model_call_events") or ())
    result: list[TokenUsageRecord] = []
    for index, item in enumerate(rows, start=1):
        raw_source = str(item.get("token_count_source") or "UNKNOWN")
        try:
            source = TokenCountSource(raw_source)
        except ValueError:
            source = TokenCountSource.UNKNOWN
        result.append(TokenUsageRecord(
            model_call_id=str(item.get("model_call_id") or f"model-call:{index}"),
            input_tokens=int(item.get("input_tokens", 0) or 0),
            output_tokens=int(item.get("output_tokens", 0) or 0),
            source=source,
        ))
    return tuple(result)


def _unit_matches(unit: RequiredContextUnit, observation: ContextUnitObservation) -> bool:
    if not observation.selected:
        return False
    if unit.source_ref and unit.source_ref in {observation.source_ref, observation.fact_id, observation.artifact_id, observation.context_item_id}:
        return True
    if unit.unit_type is ContextUnitType.MEMORY_FACT and unit.unit_id in {observation.fact_id, *observation.working_memory_fact_refs}:
        return True
    if unit.unit_type is ContextUnitType.ARTIFACT_REF and unit.unit_id == observation.artifact_id:
        return True
    return False


def evaluate_context_turn(
    session: CanonicalEvaluationSession,
    turn: CanonicalEvaluationTurn,
    prediction: PredictionRecord,
    *,
    strategy: ContextEvaluationStrategy,
    helpful_source_refs: Sequence[str] = (),
    harmful_source_refs: Sequence[str] = (),
) -> ContextTurnDiagnostic:
    raw = trace_context_observations(prediction)
    required = tuple(turn.required_context_units)
    matched_unit_ids: set[str] = set()
    relevance_by_id: dict[str, ContextRelevance] = {}
    for unit in required:
        for observation in raw:
            if _unit_matches(unit, observation):
                matched_unit_ids.add(unit.unit_id)
                relevance_by_id[observation.context_item_id] = ContextRelevance.REQUIRED
    helpful = set(str(x) for x in helpful_source_refs)
    harmful = set(str(x) for x in harmful_source_refs)
    for observation in raw:
        if observation.context_item_id in relevance_by_id or not observation.selected:
            continue
        if observation.source_ref in helpful:
            relevance_by_id[observation.context_item_id] = ContextRelevance.HELPFUL
        elif observation.source_ref in harmful:
            relevance_by_id[observation.context_item_id] = ContextRelevance.HARMFUL
        else:
            relevance_by_id[observation.context_item_id] = ContextRelevance.NOT_EVALUATED
    observations = tuple(replace(obs, relevance=relevance_by_id.get(obs.context_item_id, obs.relevance)) for obs in raw)
    missing = tuple(unit.unit_id for unit in required if unit.unit_id not in matched_unit_ids)
    selectable = [obs for obs in observations if obs.selected and obs.context_type not in {"SYSTEM", "WORKFLOW_STATE"}]
    evaluated = [obs for obs in selectable if obs.relevance is not ContextRelevance.NOT_EVALUATED]
    relevant = [obs for obs in evaluated if obs.relevance in {ContextRelevance.REQUIRED, ContextRelevance.HELPFUL}]
    failures: list[ContextFailureReason] = []
    if missing:
        failures.append(ContextFailureReason.CONTEXT_REQUIRED_FACT_DROPPED)
        if any(obs.context_type in {"SUMMARY", "MEMORY_SUMMARY"} for obs in observations):
            failures.append(ContextFailureReason.SUMMARY_LOST_REQUIRED_FACT)
    return ContextTurnDiagnostic(
        session_id=session.session_id,
        turn_id=turn.turn_id,
        strategy=strategy,
        trace_id=prediction.trace_id,
        context_recall_numerator=len(matched_unit_ids),
        context_recall_denominator=len(required),
        context_precision_numerator=len(relevant),
        context_precision_denominator=len(evaluated),
        token_usage=prediction_token_usage(prediction),
        observations=observations,
        missing_required_units=missing,
        not_evaluated_context_items=tuple(obs.context_item_id for obs in selectable if obs.relevance is ContextRelevance.NOT_EVALUATED),
        failure_reasons=tuple(dict.fromkeys(failures)),
    )


def evaluate_working_memory(turn: CanonicalEvaluationTurn, diagnostic: ContextTurnDiagnostic) -> dict[str, Any]:
    expected = set(turn.memory_expectations.required_fact_ids)
    selected: set[str] = set()
    for obs in diagnostic.observations:
        if not obs.selected or obs.memory_kind not in {"working", "long_term_fact"}:
            continue
        if obs.fact_id:
            selected.add(str(obs.fact_id))
        selected.update(str(x) for x in obs.working_memory_fact_refs)
    present = expected & selected
    precision_allowed = set(turn.memory_expectations.allowed_fact_ids) | expected
    unexpected = selected - precision_allowed if precision_allowed else set()
    return {
        "memory_dependent": turn.memory_expectations.memory_dependent,
        "working_memory_recall": _metric(len(present), len(expected)),
        "working_memory_precision": _metric(len(selected - unexpected), len(selected)),
        "required_fact_ids": sorted(expected),
        "selected_fact_ids": sorted(selected),
        "unexpected_fact_ids": sorted(unexpected),
    }


def evaluate_memory_quality(turn: CanonicalEvaluationTurn, diagnostic: ContextTurnDiagnostic) -> dict[str, Any]:
    """Working + long-term memory quality on the selected model context."""
    return evaluate_working_memory(turn, diagnostic)


def evaluate_memory_contamination(
    session: CanonicalEvaluationSession,
    turn: CanonicalEvaluationTurn,
    diagnostic: ContextTurnDiagnostic,
) -> tuple[MemoryContaminationEvent, ...]:
    expectation = turn.memory_expectations
    current = session.initial_identity
    events: list[MemoryContaminationEvent] = []
    superseded = set(expectation.superseded_fact_ids)
    stale = set(expectation.stale_fact_ids)
    forbidden = set(expectation.forbidden_fact_ids)
    allowed = set(expectation.allowed_fact_ids) | set(expectation.required_fact_ids)
    for obs in diagnostic.observations:
        if not obs.selected or obs.memory_kind not in {"working", "long_term_fact"}:
            continue
        fact_id = str(obs.fact_id or "") or None
        if fact_id and fact_id in superseded:
            events.append(MemoryContaminationEvent(session.session_id, turn.turn_id, MemoryContaminationType.SUPERSEDED_FACT_USED, obs.context_item_id, fact_id, "superseded memory fact selected into current model context"))
        if fact_id and fact_id in stale:
            events.append(MemoryContaminationEvent(session.session_id, turn.turn_id, MemoryContaminationType.STALE_FACT_USED, obs.context_item_id, fact_id, "annotated stale memory fact selected into current model context"))
        if fact_id and fact_id in forbidden:
            events.append(MemoryContaminationEvent(session.session_id, turn.turn_id, MemoryContaminationType.UNSUPPORTED_MEMORY_FACT_USED, obs.context_item_id, fact_id, "forbidden/unsupported memory fact selected into current model context"))
        if allowed and fact_id and fact_id not in allowed and obs.memory_kind == "long_term_fact":
            events.append(MemoryContaminationEvent(session.session_id, turn.turn_id, MemoryContaminationType.WRONG_ENTITY_FACT_USED, obs.context_item_id, fact_id, "memory fact is outside the annotated active fact/entity set"))
        scope = obs.identity_scope or {}
        tenant = str(scope.get("tenant_id") or "")
        user = str(scope.get("user_id") or "")
        sess = str(scope.get("session_id") or "")
        if tenant and tenant != current.tenant_id:
            events.append(MemoryContaminationEvent(session.session_id, turn.turn_id, MemoryContaminationType.CROSS_TENANT_FACT_USED, obs.context_item_id, fact_id, "memory identity tenant does not match current tenant", True))
        elif user and user != current.user_id:
            events.append(MemoryContaminationEvent(session.session_id, turn.turn_id, MemoryContaminationType.CROSS_USER_FACT_USED, obs.context_item_id, fact_id, "memory identity user does not match current user", True))
        elif expectation.disallow_cross_session_working_memory and obs.memory_kind == "working" and sess and sess != current.session_id:
            events.append(MemoryContaminationEvent(session.session_id, turn.turn_id, MemoryContaminationType.CROSS_SESSION_FACT_USED, obs.context_item_id, fact_id, "working memory belongs to another session"))
    return tuple(events)


def evaluate_artifacts(session: CanonicalEvaluationSession, turn: CanonicalEvaluationTurn, diagnostic: ContextTurnDiagnostic) -> tuple[ArtifactDiagnostic, ...]:
    required_ids = set(turn.artifact_expectations.required_artifact_ids)
    required_sources = set(turn.artifact_expectations.required_source_refs)
    selected_artifacts = [obs for obs in diagnostic.observations if obs.selected and obs.artifact_id]
    results: list[ArtifactDiagnostic] = []
    for artifact_id in required_ids:
        match = next((obs for obs in selected_artifacts if obs.artifact_id == artifact_id), None)
        status = ArtifactDiagnosticStatus.CORRECT_REUSE if match else ArtifactDiagnosticStatus.MISSING
        reason = "required artifact selected" if match else "required artifact not present in final model context"
        if match is not None and turn.artifact_expectations.identity_scoped and match.identity_scope:
            tenant = str(match.identity_scope.get("tenant_id") or "")
            user = str(match.identity_scope.get("user_id") or "")
            if (tenant and tenant != session.initial_identity.tenant_id) or (user and user != session.initial_identity.user_id):
                status = ArtifactDiagnosticStatus.WRONG_IDENTITY
                reason = "artifact origin identity does not match the current evaluation identity"
        results.append(ArtifactDiagnostic(
            session.session_id, turn.turn_id, artifact_id, status, reason,
            context_tokens=match.token_count if match else 0,
        ))
    for source_ref in required_sources:
        match = next((obs for obs in selected_artifacts if obs.source_ref == source_ref), None)
        results.append(ArtifactDiagnostic(
            session.session_id,
            turn.turn_id,
            match.artifact_id if match else None,
            ArtifactDiagnosticStatus.CORRECT_REUSE if match else ArtifactDiagnosticStatus.MISSING,
            "required artifact source ref selected" if match else f"artifact source ref missing: {source_ref}",
            context_tokens=match.token_count if match else 0,
        ))
    return tuple(results)


def evaluate_session_success(
    session: CanonicalEvaluationSession,
    judgments: Sequence[CaseJudgment],
    contamination_events: Sequence[MemoryContaminationEvent] = (),
) -> SessionTaskSuccessStatus:
    by_turn = {item.case_id.split("::")[-1]: item for item in judgments}
    contract = session.session_success_contract
    required_ids = list(contract.required_turn_ids)
    if contract.required_terminal_turn_pass:
        required_ids.append(session.turns[-1].turn_id)
    required_ids = list(dict.fromkeys(required_ids))
    for turn_id in required_ids:
        judgment = by_turn.get(turn_id)
        if judgment is None or judgment.task_success_status is None:
            return SessionTaskSuccessStatus.INCOMPLETE
        if judgment.task_success_status is TaskSuccessStatus.EXECUTION_ERROR:
            return SessionTaskSuccessStatus.EXECUTION_ERROR
        if judgment.task_success_status is TaskSuccessStatus.INCOMPLETE:
            return SessionTaskSuccessStatus.INCOMPLETE
        if judgment.task_success_status is TaskSuccessStatus.FAIL:
            return SessionTaskSuccessStatus.FAIL
    if contract.require_no_memory_contamination and contamination_events:
        return SessionTaskSuccessStatus.FAIL
    if contract.require_no_safety_violation and any(item.safety_violation for item in contamination_events):
        return SessionTaskSuccessStatus.FAIL
    return SessionTaskSuccessStatus.PASS


def turn_to_sample(session: CanonicalEvaluationSession, turn: CanonicalEvaluationTurn, *, strategy: ContextStrategyConfig) -> EvaluationSample:
    context = dict(session.initial_context)
    context.update(dict(turn.runtime_input_delta.get("context") or {}))
    context.update(strategy_runtime_context(strategy))
    config = dict(turn.runtime_input_delta.get("config") or {})
    return EvaluationSample(
        sample_id=f"{session.session_id}::{turn.turn_id}",
        runtime_input=RuntimeCaseInput(
            case_id=f"{session.session_id}::{turn.turn_id}",
            messages=(RuntimeMessage(role="user", content=turn.user_input),),
            identity=session.initial_identity,
            config=config,
            context=context,
            metadata={
                "session_id": session.session_id,
                "turn_id": turn.turn_id,
                "turn_index": turn.turn_index,
                "context_strategy": strategy.strategy.value,
                "strategy_config_hash": strategy.fingerprint,
            },
        ),
        schema_version="1.0",
        split=session.split,
        category=session.category,
        subcategory=session.subcategory,
        difficulty=session.difficulty,
        tags=tuple(dict.fromkeys((*session.tags, "MULTI_TURN", strategy.strategy.value))),
        expected_behavior=turn.expected_behavior,
        task_success_contract=turn.task_success_contract,
        gold_evidence=turn.gold_evidence,
        gold_facts=turn.gold_facts,
        safety_constraints=turn.safety_constraints,
        annotation_metadata=AnnotationMetadata(annotation_status=turn.annotation_status),
        source_metadata=SourceMetadata(
            source_datasets=(str(session.source_metadata.get("source_dataset") or "phase4_multi_turn"),),
            notes=f"session={session.session_id}; turn={turn.turn_id}; strategy={strategy.strategy.value}",
        ),
    )


def check_strategy_fairness(configs: Sequence[Mapping[str, Any]]) -> tuple[bool, tuple[str, ...]]:
    """Validate that only Context/Memory/Artifact policy differs."""

    if len(configs) < 2:
        return True, ()
    allowed = {
        "context_strategy", "context_sliding_window_turns", "context_max_tokens",
        "context_compaction_enabled", "context_compaction_item_threshold",
        "context_compaction_recent_messages", "context_compaction_summary_max_tokens",
        "long_term_memory_enabled", "long_term_memory_retrieval_limit",
        "working_memory_enabled", "artifact_enabled", "context_selector_enabled",
    }
    baseline = dict(configs[0])
    errors: list[str] = []
    all_keys = set().union(*(set(item) for item in configs))
    for key in sorted(all_keys - allowed):
        values = {json.dumps(item.get(key), sort_keys=True, default=str) for item in configs}
        if len(values) > 1:
            errors.append(f"non-context config drift: {key}")
    return not errors, tuple(errors)


def aggregate_context_strategy(results: Sequence[SessionStrategyResult]) -> dict[str, Any]:
    grouped: dict[ContextEvaluationStrategy, list[SessionStrategyResult]] = defaultdict(list)
    for result in results:
        grouped[result.strategy].append(result)
    summary: dict[str, Any] = {}
    for strategy, rows in grouped.items():
        turn_diags = [diag for row in rows for diag in row.context_diagnostics]
        tokens = [diag.total_input_tokens for diag in turn_diags]
        context_recall_num = sum(diag.context_recall_numerator for diag in turn_diags)
        context_recall_den = sum(diag.context_recall_denominator for diag in turn_diags)
        context_precision_num = sum(diag.context_precision_numerator for diag in turn_diags)
        context_precision_den = sum(diag.context_precision_denominator for diag in turn_diags)
        memory_dependent_turns = sum(int(row.metadata.get("memory_dependent_turns", 0) or 0) for row in rows)
        contaminated_turn_ids = {(e.session_id, e.turn_id) for row in rows for e in row.contamination_events}
        pass_sessions = sum(row.session_success_status is SessionTaskSuccessStatus.PASS for row in rows)
        quality_den = sum(row.session_success_status in {SessionTaskSuccessStatus.PASS, SessionTaskSuccessStatus.FAIL, SessionTaskSuccessStatus.EXECUTION_ERROR} for row in rows)
        turn_judgments = [j for row in rows for j in row.judgments]
        turn_pass = sum(j.task_success_status is TaskSuccessStatus.PASS for j in turn_judgments)
        turn_quality_den = sum(j.task_success_status in {TaskSuccessStatus.PASS, TaskSuccessStatus.FAIL, TaskSuccessStatus.EXECUTION_ERROR} for j in turn_judgments)
        grounded_num = sum(int((row.metadata.get("grounding") or {}).get("numerator", 0) or 0) for row in rows)
        grounded_den = sum(int((row.metadata.get("grounding") or {}).get("denominator", 0) or 0) for row in rows)
        model_calls_per_turn = [len(diag.token_usage) for diag in turn_diags]
        session_tokens = [row.total_input_tokens for row in rows]
        contamination_by_type = Counter(e.event_type.value for row in rows for e in row.contamination_events)
        stale_turn_ids = {(e.session_id, e.turn_id) for row in rows for e in row.contamination_events if e.event_type is MemoryContaminationType.STALE_FACT_USED}
        summary[strategy.value] = {
            "sessions": len(rows),
            "turns": len(turn_diags),
            "avg_input_tokens": mean(tokens) if tokens else None,
            "median_input_tokens": median(tokens) if tokens else None,
            "p95_input_tokens": percentile95(tokens),
            "max_input_tokens": max(tokens) if tokens else None,
            "total_input_tokens": sum(tokens),
            "avg_session_input_tokens": mean(session_tokens) if session_tokens else None,
            "p95_session_input_tokens": percentile95(session_tokens),
            "avg_model_calls": mean(model_calls_per_turn) if model_calls_per_turn else None,
            "p95_model_calls": percentile95(model_calls_per_turn),
            "turn_task_success": _metric(turn_pass, turn_quality_den),
            "session_task_success": _metric(pass_sessions, quality_den),
            "grounded_claim_rate": _metric(grounded_num, grounded_den),
            "context_recall": _metric(context_recall_num, context_recall_den),
            "context_precision": _metric(context_precision_num, context_precision_den),
            "memory_contamination_rate": _metric(len(contaminated_turn_ids), memory_dependent_turns),
            "stale_memory_error_rate": _metric(len(stale_turn_ids), memory_dependent_turns),
            "memory_contamination_event_count": sum(contamination_by_type.values()),
            "memory_contamination_by_type": dict(sorted(contamination_by_type.items())),
            "execution_errors": sum(row.execution_errors for row in rows),
            "strategy_execution_error_rate": _metric(sum(row.execution_errors for row in rows), len(turn_diags)),
            "token_count_sources": dict(Counter(u.source.value for d in turn_diags for u in d.token_usage)),
        }
    return summary


def paired_quality_cost(results: Sequence[SessionStrategyResult], *, baseline: ContextEvaluationStrategy = ContextEvaluationStrategy.FULL_HISTORY) -> dict[str, Any]:
    by_session: dict[str, dict[ContextEvaluationStrategy, SessionStrategyResult]] = defaultdict(dict)
    for result in results:
        by_session[result.session_id][result.strategy] = result
    strategy_names = sorted({r.strategy for r in results}, key=lambda x: x.value)
    output: dict[str, Any] = {}
    for strategy in strategy_names:
        if strategy is baseline:
            continue
        pairs = [
            (rows[baseline], rows[strategy])
            for rows in by_session.values()
            if baseline in rows and strategy in rows
            and rows[baseline].execution_errors == 0 and rows[strategy].execution_errors == 0
        ]
        baseline_tokens = [left.total_input_tokens for left, _ in pairs]
        strategy_tokens = [right.total_input_tokens for _, right in pairs]
        base_avg = mean(baseline_tokens) if baseline_tokens else None
        strategy_avg = mean(strategy_tokens) if strategy_tokens else None
        token_reduction = ((base_avg - strategy_avg) / base_avg) if base_avg not in {None, 0} and strategy_avg is not None else None
        base_pass = sum(left.session_success_status is SessionTaskSuccessStatus.PASS for left, _ in pairs)
        strat_pass = sum(right.session_success_status is SessionTaskSuccessStatus.PASS for _, right in pairs)
        denom = len(pairs)
        base_rate = base_pass / denom if denom else None
        strat_rate = strat_pass / denom if denom else None
        pair_classes = Counter()
        for left, right in pairs:
            lpass = left.session_success_status is SessionTaskSuccessStatus.PASS
            rpass = right.session_success_status is SessionTaskSuccessStatus.PASS
            pair_classes[
                "BOTH_PASS" if lpass and rpass else
                "FULL_PASS_STRATEGY_FAIL" if lpass and not rpass else
                "FULL_FAIL_STRATEGY_PASS" if not lpass and rpass else
                "BOTH_FAIL"
            ] += 1
        base_gnum = sum(int((left.metadata.get("grounding") or {}).get("numerator", 0) or 0) for left, _ in pairs)
        base_gden = sum(int((left.metadata.get("grounding") or {}).get("denominator", 0) or 0) for left, _ in pairs)
        strat_gnum = sum(int((right.metadata.get("grounding") or {}).get("numerator", 0) or 0) for _, right in pairs)
        strat_gden = sum(int((right.metadata.get("grounding") or {}).get("denominator", 0) or 0) for _, right in pairs)
        base_grounded = base_gnum / base_gden if base_gden else None
        strat_grounded = strat_gnum / strat_gden if strat_gden else None
        failure_attribution = Counter()
        for left, right in pairs:
            if left.session_success_status is SessionTaskSuccessStatus.PASS and right.session_success_status is not SessionTaskSuccessStatus.PASS:
                reasons = {reason.value for diag in right.context_diagnostics for reason in diag.failure_reasons}
                reasons.update("MEMORY_CONTAMINATION" for e in right.contamination_events)
                reasons.update("ARTIFACT_" + d.status.value for d in right.artifact_diagnostics if d.status is not ArtifactDiagnosticStatus.CORRECT_REUSE)
                if reasons:
                    failure_attribution.update(reasons)
            elif left.session_success_status is not SessionTaskSuccessStatus.PASS and right.session_success_status is SessionTaskSuccessStatus.PASS:
                failure_attribution.update([ContextFailureReason.OVER_CONTEXT_FAILURE.value])
        output[strategy.value] = {
            "paired_sessions": denom,
            "full_history_avg_tokens": base_avg,
            "strategy_avg_tokens": strategy_avg,
            "token_reduction": token_reduction,
            "full_history_task_success": _metric(base_pass, denom),
            "strategy_task_success": _metric(strat_pass, denom),
            "task_success_delta_percentage_points": ((strat_rate - base_rate) * 100.0) if base_rate is not None and strat_rate is not None else None,
            "full_history_grounded_claim_rate": _metric(base_gnum, base_gden),
            "strategy_grounded_claim_rate": _metric(strat_gnum, strat_gden),
            "grounded_claim_rate_delta_percentage_points": ((strat_grounded - base_grounded) * 100.0) if base_grounded is not None and strat_grounded is not None else None,
            "pairwise_diagnostics": dict(pair_classes),
            "context_failure_attribution": dict(sorted(failure_attribution.items())),
        }
    return output


def quality_cost_frontier(strategy_summary: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    for name, metrics in strategy_summary.items():
        tokens = metrics.get("avg_input_tokens")
        success = (metrics.get("session_task_success") or {}).get("rate")
        if tokens is None or success is None:
            continue
        rows.append((name, float(tokens), float(success)))
    dominated: dict[str, list[str]] = defaultdict(list)
    for name, tokens, success in rows:
        for other, other_tokens, other_success in rows:
            if other == name:
                continue
            if other_tokens <= tokens and other_success >= success and (other_tokens < tokens or other_success > success):
                dominated[name].append(other)
    return {
        "dimensions": ["avg_input_tokens", "session_task_success"],
        "no_weighted_quality_cost_score": True,
        "dominated_by": {name: sorted(values) for name, values in sorted(dominated.items())},
    }


def write_phase4_artifacts(output_dir: str | Path, *, sessions: Sequence[CanonicalEvaluationSession], results: Sequence[SessionStrategyResult]) -> dict[str, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    strategy_summary = aggregate_context_strategy(results)
    paired = paired_quality_cost(results)
    quality_cost = {
        "strategy_summary": strategy_summary,
        "paired_vs_full_history": paired,
        "frontier": quality_cost_frontier(strategy_summary),
        "formal_metrics_note": "Only real Production strategy runs may be interpreted as Quality-Cost results. Fixture/stub rows validate aggregation only.",
    }
    paths = {
        "context_strategy_summary": target / "context_strategy_summary.json",
        "context_strategy_summary_md": target / "context_strategy_summary.md",
        "context_turn_diagnostics": target / "context_turn_diagnostics.jsonl",
        "context_session_diagnostics": target / "context_session_diagnostics.jsonl",
        "memory_diagnostics": target / "memory_diagnostics.jsonl",
        "memory_contamination": target / "memory_contamination.jsonl",
        "artifact_diagnostics": target / "artifact_diagnostics.jsonl",
        "quality_cost_summary": target / "quality_cost_summary.json",
        "quality_cost_summary_md": target / "quality_cost_summary.md",
    }
    paths["context_strategy_summary"].write_text(json.dumps(strategy_summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    paths["quality_cost_summary"].write_text(json.dumps(quality_cost, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    paths["context_turn_diagnostics"].write_text("".join(json.dumps(x.to_state(), ensure_ascii=False, sort_keys=True) + "\n" for r in results for x in r.context_diagnostics), encoding="utf-8")
    paths["context_session_diagnostics"].write_text("".join(json.dumps(r.to_state(), ensure_ascii=False, sort_keys=True) + "\n" for r in results), encoding="utf-8")
    paths["memory_contamination"].write_text("".join(json.dumps(x.to_state(), ensure_ascii=False, sort_keys=True) + "\n" for r in results for x in r.contamination_events), encoding="utf-8")
    paths["artifact_diagnostics"].write_text("".join(json.dumps(x.to_state(), ensure_ascii=False, sort_keys=True) + "\n" for r in results for x in r.artifact_diagnostics), encoding="utf-8")
    memory_rows = []
    for result in results:
        by_turn = {
            str(row.get("turn_id") or ""): dict(row)
            for row in (result.metadata.get("working_memory_diagnostics") or [])
            if isinstance(row, Mapping)
        }
        for diag in result.context_diagnostics:
            quality = by_turn.get(diag.turn_id, {})
            memory_rows.append({
                "session_id": diag.session_id,
                "turn_id": diag.turn_id,
                "strategy": diag.strategy.value,
                "memory_dependent": bool(quality.get("memory_dependent", False)),
                "working_memory_recall": quality.get("working_memory_recall"),
                "working_memory_precision": quality.get("working_memory_precision"),
                "required_fact_ids": list(quality.get("required_fact_ids") or []),
                "selected_fact_ids": list(quality.get("selected_fact_ids") or []),
                "unexpected_fact_ids": list(quality.get("unexpected_fact_ids") or []),
            })
    paths["memory_diagnostics"].write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in memory_rows), encoding="utf-8")
    lines = [
        "# Phase 4 Context Strategy Summary", "",
        "| Strategy | Avg input tokens | P95 | Turn Task Success | Session Task Success | Grounded Claims | Context Recall | Context Precision |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in sorted(strategy_summary.items()):
        turn_success = metrics["turn_task_success"]
        success = metrics["session_task_success"]
        grounded = metrics["grounded_claim_rate"]
        recall = metrics["context_recall"]
        precision = metrics["context_precision"]
        def fmt(m):
            return "N/A" if m.get("rate") is None else f"{m['numerator']}/{m['denominator']} = {m['rate']:.2%}"
        lines.append(f"| {name} | {metrics['avg_input_tokens'] if metrics['avg_input_tokens'] is not None else 'N/A'} | {metrics['p95_input_tokens'] if metrics['p95_input_tokens'] is not None else 'N/A'} | {fmt(turn_success)} | {fmt(success)} | {fmt(grounded)} | {fmt(recall)} | {fmt(precision)} |")
    paths["context_strategy_summary_md"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths["quality_cost_summary_md"].write_text("# Phase 4 Quality-Cost\n\nNo weighted Quality-Cost score is defined. Pairwise comparisons require the same session IDs and real Production executions.\n", encoding="utf-8")
    return paths


__all__ = [
    "PHASE4_SESSION_SCHEMA_VERSION", "ContextUnitType", "ContextRelevance", "TokenCountSource",
    "SessionEligibilityStatus", "SessionTaskSuccessStatus", "MemoryContaminationType", "ContextFailureReason",
    "ArtifactDiagnosticStatus", "RequiredContextUnit", "MemoryExpectation", "ArtifactExpectation",
    "CanonicalEvaluationTurn", "SessionTaskSuccessContract", "CanonicalEvaluationSession", "SessionEligibility",
    "TokenUsageRecord", "ContextUnitObservation", "ContextTurnDiagnostic", "MemoryContaminationEvent",
    "ArtifactDiagnostic", "SessionStrategyResult", "ContextStrategyExperimentRun",
    "canonical_session_dataset_hash", "write_canonical_sessions", "read_canonical_sessions", "session_dataset_inventory",
    "validate_session", "validate_sessions", "strategy_config",
    "strategy_runtime_context", "trace_context_observations", "prediction_token_usage", "evaluate_context_turn",
    "evaluate_working_memory", "evaluate_memory_quality", "evaluate_memory_contamination", "evaluate_artifacts", "evaluate_session_success",
    "turn_to_sample", "check_strategy_fairness", "aggregate_context_strategy", "paired_quality_cost",
    "quality_cost_frontier", "write_phase4_artifacts", "percentile95",
]
