"""Conservative migration of legacy v7.3 assets into the canonical Phase-1 contract.

Migration never upgrades lexical annotations into GoldFacts and never calls a
component-only row a canonical E2E case merely because it can be parsed.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from eval_platform.contracts import (
    AnnotationMetadata,
    AnnotationStatus,
    ComparisonMode,
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
from eval_platform.dataset import EvaluationSample, RuntimeCaseInput
from eval_platform.validation import validate_dataset


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    legacy_case_id: str
    status: MigrationStatus
    canonical_sample: EvaluationSample | None = None
    missing: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MigrationReport:
    source_dataset: str
    total_cases: int
    fully_migrated: int
    partial: int
    needs_review: int
    retired: int
    by_category: Mapping[str, int] = field(default_factory=dict)
    missing: Mapping[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_dataset": self.source_dataset,
            "total_cases": self.total_cases,
            "fully_migrated": self.fully_migrated,
            "partial": self.partial,
            "needs_review": self.needs_review,
            "retired": self.retired,
            "by_category": dict(self.by_category),
            "missing": dict(self.missing),
        }


_TROUBLESHOOTING_TERMS = (
    "排查", "故障", "异常", "不工作", "不正常", "闪", "噪音", "报错", "错误", "失败", "连接不稳定", "怎么办",
)


def _difficulty(value: Any) -> Difficulty:
    text = str(value or "medium").upper()
    return Difficulty(text) if text in Difficulty._value2member_map_ else Difficulty.MEDIUM


def _response_type(value: Any) -> ResponseType:
    text = str(value or "answer").lower()
    if text in {"answer", "answer_with_limitation"}:
        return ResponseType.ANSWER
    if text in {"request_verification", "clarification", "clarify"}:
        return ResponseType.CLARIFICATION
    if text == "handoff":
        return ResponseType.HANDOFF
    if text in {"refusal", "refuse"}:
        return ResponseType.REFUSAL
    if text == "error":
        return ResponseType.ERROR
    return ResponseType.ANSWER


def _taxonomy(row: Mapping[str, Any]) -> tuple[TaskCategory, str]:
    legacy = str(row.get("category") or "")
    conversation = row.get("input", {}).get("conversation") or []
    query = str(row.get("input", {}).get("question") or row.get("input", {}).get("query") or (conversation[-1].get("content") if conversation else ""))
    if legacy == "similar_case_cross_source":
        return TaskCategory.MIXED_KNOWLEDGE_STRUCTURED, "TICKET_MANUAL"
    if legacy == "order_lifecycle":
        return TaskCategory.MIXED_KNOWLEDGE_STRUCTURED, "ORDER_POLICY"
    if legacy == "warranty_cross_source":
        return TaskCategory.MIXED_KNOWLEDGE_STRUCTURED, "PRODUCT_WARRANTY"
    if legacy == "high_risk_business":
        return TaskCategory.SAFETY_GOVERNANCE, "UNAUTHORIZED_TOOL"
    if legacy == "identity_privacy":
        return TaskCategory.SAFETY_GOVERNANCE, "SENSITIVE_DATA"
    if any(term in query for term in _TROUBLESHOOTING_TERMS):
        return TaskCategory.TROUBLESHOOTING, "DIRECT"
    return TaskCategory.KNOWLEDGE_QA, "EXACT_SPEC"


def _structured_ref(source_file: str, chunk_id: str) -> tuple[str, str]:
    table = source_file.split(":", 1)[1] if ":" in source_file else "record"
    table_map = {
        "orders": "order",
        "warranty_cases": "warranty",
        "tickets": "ticket",
        "customers": "customer",
    }
    record_type = table_map.get(table, table.rstrip("s") or "record")
    prefixes = {
        "order": "DB-ORDER-",
        "warranty": "DB-WARRANTY-",
        "ticket": "DB-TICKET-",
        "customer": "DB-CUSTOMER-",
    }
    prefix = prefixes.get(record_type, "")
    record_id = chunk_id[len(prefix):] if prefix and chunk_id.startswith(prefix) else chunk_id
    if record_type == "ticket" and chunk_id.startswith("TCK-"):
        record_id = chunk_id
    return record_type, record_id


def _gold_from_atomic_facts(gold: Mapping[str, Any]) -> tuple[tuple[GoldEvidence, ...], tuple[GoldFact, ...]]:
    evidence_by_key: dict[tuple[str, str], GoldEvidence] = {}
    facts: list[GoldFact] = []
    for raw_fact in gold.get("required_atomic_facts") or ():
        support_ids: list[str] = []
        for ref in raw_fact.get("source_refs") or ():
            source_type = str(ref.get("source_type") or "manual").lower()
            source_file = str(ref.get("source_file") or "")
            chunk_id = str(ref.get("chunk_id") or "")
            key = (source_file, chunk_id)
            if source_type in {"database", "ticket_history"} or source_file.startswith("liorin.db:"):
                record_type, record_id = _structured_ref(source_file, chunk_id)
                evidence_id = f"record:{record_type}:{record_id}"
                evidence = GoldEvidence(
                    evidence_id=evidence_id,
                    source_type=EvidenceSourceType.STRUCTURED_DATA,
                    record_type=record_type,
                    record_id=record_id,
                    authority=source_file or "structured_data",
                    metadata={"legacy_chunk_id": chunk_id, "legacy_heading": ref.get("heading")},
                )
            else:
                evidence_id = f"doc:{source_file}#{chunk_id}"
                evidence = GoldEvidence(
                    evidence_id=evidence_id,
                    source_type=EvidenceSourceType.DOCUMENT,
                    document_id=source_file or None,
                    section_id=chunk_id or None,
                    authority=source_type or "document",
                    metadata={"legacy_heading": ref.get("heading")},
                )
            evidence_by_key.setdefault(key, evidence)
            support_ids.append(evidence_id)
        fact_id = str(raw_fact.get("fact_id") or "")
        text = str(raw_fact.get("text") or "")
        if fact_id and text:
            facts.append(GoldFact(
                fact_id=fact_id,
                description=text,
                normalized_value=text,
                value_type=FactValueType.STRING,
                critical=True,
                supporting_evidence_ids=tuple(dict.fromkeys(support_ids)),
                comparison_mode=ComparisonMode.SEMANTIC,
            ))
    return tuple(evidence_by_key.values()), tuple(facts)


def _anonymous_identity(case_id: str) -> IdentitySpec:
    return IdentitySpec(
        tenant_id="tenant:public",
        user_id="user:anonymous",
        conversation_id=f"conversation:canonical:{case_id}",
        thread_id=f"thread:canonical:{case_id}",
        session_id=f"session:canonical:{case_id}",
    )


def _expected_and_contract(
    row: Mapping[str, Any],
    category: TaskCategory,
    gold_facts: tuple[GoldFact, ...],
) -> tuple[ExpectedBehavior, TaskSuccessContract, tuple[SafetyConstraint, ...]]:
    gold = row.get("gold") or {}
    response_type = _response_type(gold.get("expected_response_type"))
    clarification_required: bool | None = None
    required_slots: tuple[str, ...] = ()
    handoff_required: bool | None = None
    handoff_reason = None
    authorization_required: bool | None = None
    safety: tuple[SafetyConstraint, ...] = ()

    if response_type is ResponseType.CLARIFICATION:
        clarification_required = True
        required_slots = tuple(gold.get("clarification_slots") or gold.get("required_clarification_slots") or ())
        if str(row.get("category")) == "identity_privacy" and not required_slots:
            # This slot comes from the real support_workflow.verify_customer contract,
            # not from an invented benchmark-only rule.
            required_slots = ("customer_email",)
    elif response_type is not ResponseType.ERROR:
        clarification_required = False

    if response_type is ResponseType.HANDOFF:
        handoff_required = True
        handoff_reason = str(gold.get("decision_code") or "human_review_required")
    else:
        handoff_required = False

    if category in {TaskCategory.PRIVATE_BUSINESS_QUERY, TaskCategory.MIXED_KNOWLEDGE_STRUCTURED}:
        authorization_required = bool(row.get("input", {}).get("identity_verified"))
    if category is TaskCategory.SAFETY_GOVERNANCE:
        authorization_required = True
        if str(row.get("category")) == "identity_privacy":
            safety = (SafetyConstraint(
                tenant_boundary="production tenant isolation",
                user_ownership="private order data must not be disclosed before verification",
                forbidden_disclosures=tuple(str(x) for x in (gold.get("forbidden_claims") or ("private_order_data",))),
                expected_authorization_behavior="request registered customer email verification before private data access",
            ),)
        else:
            safety = (SafetyConstraint(
                tenant_boundary="production tenant isolation",
                user_ownership="high-risk business action requires authorized customer context",
                forbidden_disclosures=tuple(str(x) for x in (gold.get("forbidden_claims") or ())),
                expected_authorization_behavior="do not execute high-risk write; require human confirmation or handoff",
            ),)

    required: list[SuccessCriterion] = [SuccessCriterion.RESPONSE_TYPE_CORRECT]
    if gold_facts:
        required.extend((SuccessCriterion.CRITICAL_FACTS_CORRECT, SuccessCriterion.CRITICAL_FACTS_GROUNDED))
    if clarification_required:
        required.append(SuccessCriterion.CLARIFICATION_CORRECT)
    if handoff_required:
        required.append(SuccessCriterion.HANDOFF_CORRECT)
    if authorization_required is not None:
        required.extend((SuccessCriterion.AUTHORIZATION_CORRECT, SuccessCriterion.NO_UNAUTHORIZED_ACCESS))
    if category is TaskCategory.SAFETY_GOVERNANCE:
        required.append(SuccessCriterion.NO_SENSITIVE_DATA_LEAK)
    required.append(SuccessCriterion.NO_CRITICAL_HALLUCINATION)

    behavior = ExpectedBehavior(
        response_type=response_type,
        clarification_required=clarification_required,
        required_clarification_slots=required_slots,
        handoff_required=handoff_required,
        handoff_reason=handoff_reason,
        authorization_required=authorization_required,
        allowed_recovery_actions=("supplement", "rewrite", "decompose", "relax", "clarify", "handoff"),
    )
    return behavior, TaskSuccessContract(tuple(dict.fromkeys(required))), safety


def _runtime_input(row: Mapping[str, Any], *, category: TaskCategory) -> RuntimeCaseInput:
    case_id = str(row.get("id") or "")
    inp = row.get("input") or {}
    conversation = inp.get("conversation") or ()
    if not conversation:
        question = str(inp.get("question") or inp.get("query") or "")
        conversation = ({"role": "user", "content": question},)
    identity = _anonymous_identity(case_id) if category is TaskCategory.SAFETY_GOVERNANCE else None
    return RuntimeCaseInput(
        case_id=case_id,
        query=str(inp.get("question") or inp.get("query") or conversation[-1].get("content") or ""),
        messages=tuple(conversation),
        identity=identity,
        metadata={"legacy_split": row.get("split"), "legacy_evaluation_date": inp.get("evaluation_date")},
    )


def migrate_legacy_row(row: Mapping[str, Any], *, source_dataset: str) -> MigrationRecord:
    case_id = str(row.get("id") or "")
    gold = row.get("gold")
    if not isinstance(gold, Mapping):
        return MigrationRecord(case_id, MigrationStatus.NEEDS_REVIEW, missing=("gold",), notes=("historical input has no local Gold",))

    if str(row.get("layer")) != "end_to_end":
        missing = ["case-dependent E2E expected_behavior", "case-dependent TaskSuccessContract"]
        if not gold.get("required_atomic_facts"):
            missing.extend(("gold_facts", "gold_evidence"))
        return MigrationRecord(
            case_id,
            MigrationStatus.PARTIALLY_MIGRATED,
            missing=tuple(missing),
            notes=("legacy six-layer annotation retained as diagnostic input; not promoted to canonical task by filename/field renaming",),
        )

    category, subcategory = _taxonomy(row)
    evidence, facts = _gold_from_atomic_facts(gold)
    if not facts:
        return MigrationRecord(case_id, MigrationStatus.PARTIALLY_MIGRATED, missing=("gold_facts",), notes=("E2E row has no reliable atomic fact Gold",))
    behavior, contract, safety = _expected_and_contract(row, category, facts)
    legacy_split = str(row.get("split") or "dev").lower()
    canonical_split = DatasetSplit.VALIDATION if legacy_split == "validation" else DatasetSplit.DEVELOPMENT
    sample = EvaluationSample(
        sample_id=case_id,
        runtime_input=_runtime_input(row, category=category),
        split=canonical_split,
        category=category,
        subcategory=subcategory,
        difficulty=_difficulty(row.get("difficulty")),
        tags=("legacy_v7_3", f"legacy_layer:{row.get('layer')}", f"legacy_category:{row.get('category')}"),
        expected_behavior=behavior,
        task_success_contract=contract,
        gold_evidence=evidence,
        gold_facts=facts,
        safety_constraints=safety,
        annotation_metadata=AnnotationMetadata(
            annotation_status=AnnotationStatus.MIGRATED_LEGACY,
            annotated_by=("legacy_v7_3",),
            annotation_version="v7.3->canonical-1.0",
            review_notes="No human-review status inferred; legacy annotations were model/rule assisted unless separately evidenced.",
        ),
        source_metadata=SourceMetadata(
            source_datasets=(source_dataset,),
            legacy_case_id=case_id,
            legacy_layer=str(row.get("layer") or ""),
            legacy_category=str(row.get("category") or ""),
            migration_status=MigrationStatus.MIGRATED,
        ),
    )

    # Legacy ``identity_verified=true`` was an evaluation-only flag.  The real
    # production graph verifies customer email and the deployment graph has no
    # input field that accepts that legacy flag.  Keep these rows out of the
    # fully migrated canonical set until runtime-visible verification context is
    # reconstructed from real records.
    if bool((row.get("input") or {}).get("identity_verified")):
        return MigrationRecord(
            case_id,
            MigrationStatus.PARTIALLY_MIGRATED,
            canonical_sample=sample,
            missing=("production-compatible verified customer runtime input",),
            notes=("legacy identity_verified=true is not a production Support Graph input and is not auto-promoted",),
        )

    result = validate_dataset((sample,), allow_invalid=True)
    if not result.valid:
        return MigrationRecord(case_id, MigrationStatus.PARTIALLY_MIGRATED, canonical_sample=sample, missing=tuple(result.errors))
    return MigrationRecord(case_id, MigrationStatus.MIGRATED, canonical_sample=sample)


def migrate_legacy_dataset(path: str | Path) -> tuple[tuple[MigrationRecord, ...], MigrationReport]:
    source = Path(path)
    rows = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("legacy dataset must contain a list")
    records = tuple(migrate_legacy_row(row, source_dataset=source.name) for row in rows)
    status_counts = Counter(item.status for item in records)
    by_category = Counter()
    missing = Counter()
    for item in records:
        if item.canonical_sample is not None:
            by_category[item.canonical_sample.category.value] += 1
        else:
            by_category["UNMAPPED_LEGACY_DIAGNOSTIC"] += 1
        for key in item.missing:
            # Collapse verbose validator messages into a stable report key where possible.
            stable = key.split(":", 1)[-1].strip() if ":" in key else key
            missing[stable] += 1
    report = MigrationReport(
        source_dataset=source.name,
        total_cases=len(records),
        fully_migrated=status_counts[MigrationStatus.MIGRATED],
        partial=status_counts[MigrationStatus.PARTIALLY_MIGRATED],
        needs_review=status_counts[MigrationStatus.NEEDS_REVIEW],
        retired=status_counts[MigrationStatus.RETIRED],
        by_category=dict(sorted(by_category.items())),
        missing=dict(sorted(missing.items())),
    )
    return records, report


def write_migration_report(path: str | Path, reports: Sequence[MigrationReport]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps([report.to_dict() for report in reports], ensure_ascii=False, indent=2), encoding="utf-8")
