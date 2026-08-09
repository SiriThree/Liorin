"""Canonical Evaluation dataset contracts and deterministic JSON/JSONL I/O."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from eval_platform.contracts import (
    CANONICAL_SCHEMA_VERSION,
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
    MigrationStatus,
    ResponseType,
    SafetyConstraint,
    SourceMetadata,
    SuccessCriterion,
    TaskCategory,
    TaskSuccessContract,
)
from evals.gold_isolation import assert_no_gold_leak


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], *, scope: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown {scope} field(s): {sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class EvaluationScenario:
    """Legacy component-evaluation scenario; not a formal canonical E2E sample."""

    scenario_id: str
    inputs: Mapping[str, Any]
    expected: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.scenario_id).strip():
            raise ValueError("scenario_id must not be empty")


@dataclass(frozen=True, slots=True)
class RuntimeMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"unsupported message role: {self.role!r}")
        if not isinstance(self.content, str):
            raise TypeError("RuntimeMessage.content must be str")

    @classmethod
    def from_value(cls, value: "RuntimeMessage | Mapping[str, Any]") -> "RuntimeMessage":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("runtime messages must be RuntimeMessage or mapping")
        _reject_unknown(value, {"role", "content"}, scope="RuntimeMessage")
        return cls(role=str(value.get("role") or ""), content=str(value.get("content") or ""))

    def to_state(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class RuntimeCaseInput:
    """Gold-free input allowed to cross the production runtime boundary."""

    case_id: str
    messages: tuple[RuntimeMessage | Mapping[str, Any], ...]
    query: str | None = None
    identity: IdentitySpec | Mapping[str, Any] | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    context: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise ValueError("RuntimeCaseInput.case_id must not be empty")
        if not self.messages:
            raise ValueError("RuntimeCaseInput.messages must not be empty")
        object.__setattr__(self, "messages", tuple(RuntimeMessage.from_value(item) for item in self.messages))
        if isinstance(self.identity, Mapping):
            raw_identity = dict(self.identity)
            # A supplied identity must identify a real production principal.
            # Conversation/thread/session identifiers are execution identifiers and
            # may be deterministically allocated by the evaluation adapter, but we
            # never invent tenant_id/user_id to make a benchmark row validate.
            if not raw_identity.get("tenant_id") or not raw_identity.get("user_id"):
                raise ValueError("runtime identity mapping requires tenant_id and user_id")
            raw_identity.setdefault("conversation_id", f"conversation:eval:{self.case_id}")
            raw_identity.setdefault("thread_id", f"thread:eval:{self.case_id}")
            raw_identity.setdefault("session_id", f"session:eval:{self.case_id}")
            object.__setattr__(self, "identity", IdentitySpec.from_mapping(raw_identity))
        if self.query is None:
            last_user = next((m.content for m in reversed(self.messages) if m.role == "user"), None)
            object.__setattr__(self, "query", last_user)
        assert_no_gold_leak(self.runtime_packet())

    def runtime_packet(self) -> dict[str, Any]:
        identity = self.identity.to_runtime_mapping() if isinstance(self.identity, IdentitySpec) else {}
        packet = {
            "case_id": self.case_id,
            "query": self.query,
            "messages": [item.to_state() for item in self.messages],
            "identity": identity,
            "config": dict(self.config),
            "context": dict(self.context),
            "metadata": dict(self.metadata),
        }
        assert_no_gold_leak(packet)
        return packet


@dataclass(frozen=True, slots=True)
class EvaluationSample:
    """The one formal canonical sample type, refined from the Phase-0 skeleton."""

    sample_id: str
    runtime_input: RuntimeCaseInput
    schema_version: str = CANONICAL_SCHEMA_VERSION
    split: DatasetSplit = DatasetSplit.DEVELOPMENT
    category: TaskCategory = TaskCategory.KNOWLEDGE_QA
    subcategory: str = "FAQ"
    difficulty: Difficulty = Difficulty.MEDIUM
    tags: tuple[str, ...] = ()
    expected_behavior: ExpectedBehavior = field(default_factory=lambda: ExpectedBehavior(ResponseType.ANSWER))
    task_success_contract: TaskSuccessContract = field(default_factory=lambda: TaskSuccessContract(()))
    gold_evidence: tuple[GoldEvidence, ...] = ()
    gold_facts: tuple[GoldFact, ...] = ()
    safety_constraints: tuple[SafetyConstraint, ...] = ()
    annotation_metadata: AnnotationMetadata = field(
        default_factory=lambda: AnnotationMetadata(AnnotationStatus.NEEDS_REVIEW)
    )
    source_metadata: SourceMetadata = field(default_factory=SourceMetadata)

    def __post_init__(self) -> None:
        if not str(self.sample_id).strip():
            raise ValueError("EvaluationSample.sample_id must not be empty")
        if self.runtime_input.case_id != self.sample_id:
            raise ValueError("EvaluationSample.sample_id must match RuntimeCaseInput.case_id")
        if self.schema_version != CANONICAL_SCHEMA_VERSION:
            raise ValueError(f"unsupported canonical schema version: {self.schema_version}")
        if not isinstance(self.split, DatasetSplit):
            object.__setattr__(self, "split", DatasetSplit(str(self.split).upper()))
        if not isinstance(self.category, TaskCategory):
            object.__setattr__(self, "category", TaskCategory(str(self.category)))
        if not isinstance(self.difficulty, Difficulty):
            object.__setattr__(self, "difficulty", Difficulty(str(self.difficulty).upper()))

    def to_runtime_input(self) -> RuntimeCaseInput:
        return self.runtime_input

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.sample_id,
            "schema_version": self.schema_version,
            "split": self.split.value,
            "category": self.category.value,
            "subcategory": self.subcategory,
            "difficulty": self.difficulty.value,
            "tags": list(self.tags),
            "input": self.runtime_input.runtime_packet(),
            "expected_behavior": _jsonable(self.expected_behavior),
            "task_success_contract": _jsonable(self.task_success_contract),
            "gold_evidence": _jsonable(self.gold_evidence),
            "gold_facts": _jsonable(self.gold_facts),
            "safety_constraints": _jsonable(self.safety_constraints),
            "annotation_metadata": _jsonable(self.annotation_metadata),
            "source_metadata": _jsonable(self.source_metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvaluationSample":
        allowed_top = {
            "case_id", "schema_version", "split", "category", "subcategory", "difficulty", "tags",
            "input", "expected_behavior", "task_success_contract", "gold_evidence", "gold_facts",
            "safety_constraints", "annotation_metadata", "source_metadata",
        }
        _reject_unknown(value, allowed_top, scope="canonical sample")
        inp = value.get("input") or {}
        allowed_input = {"case_id", "query", "messages", "identity", "config", "context", "metadata"}
        _reject_unknown(inp, allowed_input, scope="RuntimeCaseInput")
        identity_value = inp.get("identity") or None
        if identity_value:
            _reject_unknown(identity_value, {"tenant_id", "user_id", "conversation_id", "thread_id", "session_id", "region", "roles", "permissions"}, scope="IdentitySpec")
        runtime = RuntimeCaseInput(
            case_id=str(value.get("case_id") or ""),
            query=inp.get("query"),
            messages=tuple(inp.get("messages") or ()),
            identity=IdentitySpec.from_mapping(identity_value) if identity_value else None,
            config=inp.get("config") or {},
            context=inp.get("context") or {},
            metadata=inp.get("metadata") or {},
        )
        behavior_raw = value.get("expected_behavior") or {}
        _reject_unknown(behavior_raw, {
            "response_type", "required_agents", "allowed_agents", "forbidden_agents",
            "required_tools", "allowed_tools", "forbidden_tools", "clarification_required",
            "required_clarification_slots", "handoff_required", "handoff_reason",
            "authorization_required", "allowed_recovery_actions", "forbidden_recovery_actions",
        }, scope="ExpectedBehavior")
        behavior = ExpectedBehavior(
            response_type=ResponseType(str(behavior_raw.get("response_type") or "ANSWER")),
            required_agents=tuple(behavior_raw.get("required_agents") or ()),
            allowed_agents=tuple(behavior_raw.get("allowed_agents") or ()),
            forbidden_agents=tuple(behavior_raw.get("forbidden_agents") or ()),
            required_tools=tuple(behavior_raw.get("required_tools") or ()),
            allowed_tools=tuple(behavior_raw.get("allowed_tools") or ()),
            forbidden_tools=tuple(behavior_raw.get("forbidden_tools") or ()),
            clarification_required=behavior_raw.get("clarification_required"),
            required_clarification_slots=tuple(behavior_raw.get("required_clarification_slots") or ()),
            handoff_required=behavior_raw.get("handoff_required"),
            handoff_reason=behavior_raw.get("handoff_reason"),
            authorization_required=behavior_raw.get("authorization_required"),
            allowed_recovery_actions=tuple(behavior_raw.get("allowed_recovery_actions") or ()),
            forbidden_recovery_actions=tuple(behavior_raw.get("forbidden_recovery_actions") or ()),
        )
        contract_raw = value.get("task_success_contract") or {}
        _reject_unknown(contract_raw, {"required_criteria", "conditional_criteria"}, scope="TaskSuccessContract")
        for item in (contract_raw.get("conditional_criteria") or ()):
            _reject_unknown(item, {"criterion", "when"}, scope="ConditionalSuccessCriterion")
        contract = TaskSuccessContract(
            required_criteria=tuple(SuccessCriterion(str(x)) for x in (contract_raw.get("required_criteria") or ())),
            conditional_criteria=tuple(
                ConditionalSuccessCriterion(
                    criterion=SuccessCriterion(str(item["criterion"])),
                    when=str(item["when"]),
                ) for item in (contract_raw.get("conditional_criteria") or ())
            ),
        )
        for item in (value.get("gold_evidence") or ()):
            _reject_unknown(item, {
                "evidence_id", "source_type", "required", "alternative_group", "document_id",
                "section_id", "record_type", "record_id", "field_path", "expected_value",
                "authority", "effective_from", "effective_to", "metadata",
            }, scope="GoldEvidence")
        evidence = tuple(
            GoldEvidence(
                evidence_id=str(item.get("evidence_id") or ""),
                source_type=EvidenceSourceType(str(item.get("source_type") or "")),
                required=bool(item.get("required", True)),
                alternative_group=item.get("alternative_group"),
                document_id=item.get("document_id"),
                section_id=item.get("section_id"),
                record_type=item.get("record_type"),
                record_id=item.get("record_id"),
                field_path=item.get("field_path"),
                expected_value=item.get("expected_value"),
                authority=item.get("authority"),
                effective_from=item.get("effective_from"),
                effective_to=item.get("effective_to"),
                metadata=item.get("metadata") or {},
            ) for item in (value.get("gold_evidence") or ())
        )
        for item in (value.get("gold_facts") or ()):
            _reject_unknown(item, {
                "fact_id", "description", "normalized_value", "value_type", "critical",
                "supporting_evidence_ids", "comparison_mode",
            }, scope="GoldFact")
        facts = tuple(
            GoldFact(
                fact_id=str(item.get("fact_id") or ""),
                description=str(item.get("description") or ""),
                normalized_value=item.get("normalized_value"),
                value_type=FactValueType(str(item.get("value_type") or "STRING")),
                critical=bool(item.get("critical", True)),
                supporting_evidence_ids=tuple(item.get("supporting_evidence_ids") or ()),
                comparison_mode=ComparisonMode(str(item.get("comparison_mode") or "SEMANTIC")),
            ) for item in (value.get("gold_facts") or ())
        )
        for item in (value.get("safety_constraints") or ()):
            _reject_unknown(item, {
                "tenant_boundary", "user_ownership", "required_permissions", "forbidden_resources",
                "forbidden_tools", "forbidden_disclosures", "expected_authorization_behavior",
            }, scope="SafetyConstraint")
        constraints = tuple(SafetyConstraint(
            tenant_boundary=item.get("tenant_boundary"),
            user_ownership=item.get("user_ownership"),
            required_permissions=tuple(item.get("required_permissions") or ()),
            forbidden_resources=tuple(item.get("forbidden_resources") or ()),
            forbidden_tools=tuple(item.get("forbidden_tools") or ()),
            forbidden_disclosures=tuple(item.get("forbidden_disclosures") or ()),
            expected_authorization_behavior=item.get("expected_authorization_behavior"),
        ) for item in (value.get("safety_constraints") or ()))
        annotation_raw = value.get("annotation_metadata") or {}
        _reject_unknown(annotation_raw, {"annotation_status", "annotated_by", "reviewed_by", "annotation_version", "review_notes"}, scope="AnnotationMetadata")
        annotation = AnnotationMetadata(
            annotation_status=AnnotationStatus(str(annotation_raw.get("annotation_status") or "NEEDS_REVIEW")),
            annotated_by=tuple(annotation_raw.get("annotated_by") or ()),
            reviewed_by=tuple(annotation_raw.get("reviewed_by") or ()),
            annotation_version=str(annotation_raw.get("annotation_version") or "1"),
            review_notes=annotation_raw.get("review_notes"),
        )
        source_raw = value.get("source_metadata") or {}
        _reject_unknown(source_raw, {"source_datasets", "legacy_case_id", "legacy_layer", "legacy_category", "migration_status", "notes"}, scope="SourceMetadata")
        migration = source_raw.get("migration_status")
        source = SourceMetadata(
            source_datasets=tuple(source_raw.get("source_datasets") or ()),
            legacy_case_id=source_raw.get("legacy_case_id"),
            legacy_layer=source_raw.get("legacy_layer"),
            legacy_category=source_raw.get("legacy_category"),
            migration_status=MigrationStatus(str(migration)) if migration else None,
            notes=source_raw.get("notes"),
        )
        return cls(
            sample_id=str(value.get("case_id") or ""),
            runtime_input=runtime,
            schema_version=str(value.get("schema_version") or ""),
            split=DatasetSplit(str(value.get("split") or "").upper()),
            category=TaskCategory(str(value.get("category") or "")),
            subcategory=str(value.get("subcategory") or ""),
            difficulty=Difficulty(str(value.get("difficulty") or "").upper()),
            tags=tuple(value.get("tags") or ()),
            expected_behavior=behavior,
            task_success_contract=contract,
            gold_evidence=evidence,
            gold_facts=facts,
            safety_constraints=constraints,
            annotation_metadata=annotation,
            source_metadata=source,
        )


# Semantic alias only: there is exactly one canonical sample class.
CanonicalEvaluationSample = EvaluationSample


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    name: str
    scenarios: tuple[EvaluationScenario, ...]

    @classmethod
    def from_iterable(cls, name: str, scenarios: Iterable[EvaluationScenario]) -> "EvaluationDataset":
        materialized = tuple(scenarios)
        if not materialized:
            raise ValueError("evaluation dataset must contain scenarios")
        return cls(name=name, scenarios=materialized)


def normalized_dataset_bytes(samples: Sequence[EvaluationSample]) -> bytes:
    rows = [sample.to_dict() for sample in sorted(samples, key=lambda item: item.sample_id)]
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_dataset_hash(samples: Sequence[EvaluationSample]) -> str:
    return sha256(normalized_dataset_bytes(samples)).hexdigest()


def write_canonical_dataset(path: str | Path, samples: Sequence[EvaluationSample]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".jsonl":
        target.write_text(
            "\n".join(json.dumps(sample.to_dict(), ensure_ascii=False, sort_keys=True) for sample in samples) + "\n",
            encoding="utf-8",
        )
    else:
        target.write_text(json.dumps([s.to_dict() for s in samples], ensure_ascii=False, indent=2), encoding="utf-8")


def read_canonical_dataset(path: str | Path) -> tuple[EvaluationSample, ...]:
    source = Path(path)
    if source.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("canonical dataset JSON must contain a list")
        rows = raw
    return tuple(EvaluationSample.from_dict(row) for row in rows)


def build_dataset_manifest(
    *,
    dataset_name: str,
    dataset_version: str,
    samples: Sequence[EvaluationSample],
    created_at: str,
    source_datasets: Sequence[str],
    gold_status: str,
    review_status: str,
    contamination_status: str,
    intended_usage: str,
    trust_level,
):
    from collections import Counter
    from eval_platform.contracts import DatasetManifest, SplitTrustLevel

    if not isinstance(trust_level, SplitTrustLevel):
        trust_level = SplitTrustLevel(str(trust_level))
    return DatasetManifest(
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        schema_version=CANONICAL_SCHEMA_VERSION,
        created_at=created_at,
        case_count=len(samples),
        category_distribution=dict(sorted(Counter(s.category.value for s in samples).items())),
        subcategory_distribution=dict(sorted(Counter(s.subcategory for s in samples).items())),
        difficulty_distribution=dict(sorted(Counter(s.difficulty.value for s in samples).items())),
        split_distribution=dict(sorted(Counter(s.split.value for s in samples).items())),
        annotation_status_distribution=dict(sorted(Counter(s.annotation_metadata.annotation_status.value for s in samples).items())),
        source_datasets=tuple(source_datasets),
        gold_status=gold_status,
        review_status=review_status,
        contamination_status=contamination_status,
        intended_usage=intended_usage,
        trust_level=trust_level,
        dataset_hash=canonical_dataset_hash(samples),
    )


def write_dataset_manifest(path: str | Path, manifest) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_jsonable(manifest), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
