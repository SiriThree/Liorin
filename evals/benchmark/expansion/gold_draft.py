"""Phase D2 deterministic Private Business Gold Draft construction.

These contracts are dataset-construction intermediates only. They intentionally
reuse Phase-1/2 semantics without becoming CanonicalEvaluationSample or formal
Gold until dual annotation, adjudication and human review occur.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from eval_platform.contracts import ComparisonMode, EvidenceSourceType, FactValueType, ResponseType, SuccessCriterion
from retrieval.security import hash_identifier, redact_text


GOLD_DRAFT_VERSION = "private-business-gold-draft-v1"


class GoldDraftStatus(StrEnum):
    SOURCE_DERIVED_DRAFT = "SOURCE_DERIVED_DRAFT"
    DETERMINISTICALLY_VALIDATED = "DETERMINISTICALLY_VALIDATED"
    READY_FOR_DUAL_ANNOTATION = "READY_FOR_DUAL_ANNOTATION"
    NEEDS_MANUAL_PRECHECK = "NEEDS_MANUAL_PRECHECK"
    REJECTED_BEFORE_ANNOTATION = "REJECTED_BEFORE_ANNOTATION"


class AnswerabilityStatus(StrEnum):
    CLEARLY_ANSWERABLE = "CLEARLY_ANSWERABLE"
    ANSWERABLE_WITH_RUNTIME_MATERIALIZATION = "ANSWERABLE_WITH_RUNTIME_MATERIALIZATION"
    AMBIGUOUS = "AMBIGUOUS"
    TOOL_OUTPUT_INSUFFICIENT = "TOOL_OUTPUT_INSUFFICIENT"
    SOURCE_INSUFFICIENT = "SOURCE_INSUFFICIENT"
    POLICY_UNCLEAR = "POLICY_UNCLEAR"


class ReviewPriority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class GoldFactDraft:
    fact_id: str
    description: str
    normalized_value: Any
    value_type: str
    critical: bool
    supporting_evidence_ids: tuple[str, ...]
    comparison_mode: str
    source_field_path: str
    judge_required: bool = False
    value_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["supporting_evidence_ids"] = list(self.supporting_evidence_ids)
        state["value_metadata"] = dict(self.value_metadata)
        return state


@dataclass(frozen=True)
class GoldEvidenceDraft:
    evidence_id: str
    source_type: str
    required: bool
    record_type: str
    record_id: str
    field_path: str
    expected_value: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["metadata"] = dict(self.metadata)
        return state


@dataclass(frozen=True)
class TaskSuccessContractDraft:
    required_criteria: tuple[str, ...]
    required_agents: tuple[str, ...]
    required_tools: tuple[str, ...]
    required_template_ids: tuple[str, ...]
    authorization_expected: str

    def to_state(self) -> dict[str, Any]:
        return {
            "required_criteria": list(self.required_criteria),
            "required_agents": list(self.required_agents),
            "required_tools": list(self.required_tools),
            "required_template_ids": list(self.required_template_ids),
            "authorization_expected": self.authorization_expected,
        }


@dataclass
class PrivateBusinessGoldDraft:
    candidate_id: str
    gold_draft_version: str
    record_type: str
    semantic_family_id: str
    expected_response_type: str
    task_success_contract_draft: TaskSuccessContractDraft
    gold_facts_draft: tuple[GoldFactDraft, ...]
    gold_evidence_draft: tuple[GoldEvidenceDraft, ...]
    identity_expectation: Mapping[str, Any]
    tool_expectation: Mapping[str, Any]
    answerability: str
    ambiguity_status: str
    runtime_query_materialization: Mapping[str, Any]
    source_provenance: Mapping[str, Any]
    annotation_status: str
    quality_flags: list[str]
    review_requirements: list[str]
    review_priority: str
    required_facts: tuple[str, ...]
    optional_facts: tuple[str, ...]
    forbidden_extra_disclosure: tuple[str, ...]

    def to_state(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "gold_draft_version": self.gold_draft_version,
            "record_type": self.record_type,
            "semantic_family_id": self.semantic_family_id,
            "expected_response_type": self.expected_response_type,
            "task_success_contract_draft": self.task_success_contract_draft.to_state(),
            "gold_facts_draft": [x.to_state() for x in self.gold_facts_draft],
            "gold_evidence_draft": [x.to_state() for x in self.gold_evidence_draft],
            "identity_expectation": dict(self.identity_expectation),
            "tool_expectation": dict(self.tool_expectation),
            "answerability": self.answerability,
            "ambiguity_status": self.ambiguity_status,
            "runtime_query_materialization": dict(self.runtime_query_materialization),
            "source_provenance": dict(self.source_provenance),
            "annotation_status": self.annotation_status,
            "quality_flags": sorted(set(self.quality_flags)),
            "review_requirements": sorted(set(self.review_requirements)),
            "review_priority": self.review_priority,
            "required_facts": list(self.required_facts),
            "optional_facts": list(self.optional_facts),
            "forbidden_extra_disclosure": list(self.forbidden_extra_disclosure),
        }


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_fact_id(candidate_id: str, field_path: str) -> str:
    return f"pbq-fact:{hashlib.sha256(f'{candidate_id}|{field_path}'.encode()).hexdigest()[:20]}"


def _safe_ref(kind: str, raw: str) -> str:
    ns = f"structured:{kind}" if kind in {"order", "ticket", "warranty"} else kind
    return f"{kind}:hash:{hash_identifier(str(raw), namespace=ns)}"


def resolve_candidate_source(root: Path, candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the unique raw source record from the construction-only hash locator."""
    record_type = str(candidate["record_type"])
    table, key = {
        "order": ("orders", "order_id"),
        "ticket": ("tickets", "ticket_id"),
        "warranty": ("warranty_cases", "case_id"),
    }[record_type]
    source_ref = str(candidate["source_entity_ref"])
    conn = sqlite3.connect(root / "data/structured/liorin.db")
    conn.row_factory = sqlite3.Row
    try:
        matches = []
        for row in conn.execute(f"SELECT * FROM {table}"):
            raw = str(row[key])
            if _safe_ref(record_type, raw) == source_ref:
                matches.append(dict(row))
        if len(matches) != 1:
            raise ValueError(f"candidate {candidate['candidate_id']} source resolution expected 1 row, found {len(matches)}")
        record = matches[0]
        customer = conn.execute("SELECT tenant_id FROM customers WHERE customer_id=?", (record["customer_id"],)).fetchone()
        if customer is None:
            raise ValueError(f"candidate {candidate['candidate_id']} owner customer missing")
        record["_tenant_id"] = str(customer["tenant_id"])
        if record_type == "order":
            items = [dict(r) for r in conn.execute(
                "SELECT i.order_item_id,i.product_id,p.name AS product_name,i.quantity,i.price_per_unit "
                "FROM order_items i JOIN products p ON p.product_id=i.product_id WHERE i.order_id=? ORDER BY i.order_item_id",
                (record["order_id"],),
            )]
            record["_order_items"] = items
        return record
    finally:
        conn.close()


def safe_source_value(record_type: str, field_path: str, value: Any, *, product_name: str | None = None) -> Any:
    if value is None:
        return None
    if field_path == "order_id":
        return _safe_ref("order", str(value))
    if field_path == "ticket_id":
        return _safe_ref("ticket", str(value))
    if field_path == "case_id":
        return _safe_ref("warranty", str(value))
    if field_path == "customer_id":
        return f"customer:hash:{hash_identifier(str(value), namespace='customer')}"
    if field_path == "summary":
        text = str(value)
        return {
            "display": redact_text(text, limit=500),
            "value_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:20],
        }
    if field_path == "product_id" and product_name:
        return {"product_id": str(value), "product_name": product_name}
    return value


def evidence_id_for(candidate: Mapping[str, Any], field_path: str) -> str:
    source = str(candidate["source_entity_ref"])
    digest = source.rsplit(":", 1)[-1]
    return f"record:{candidate['record_type']}:hash:{digest}#{field_path}"


def base_required_criteria() -> tuple[str, ...]:
    return tuple(x.value for x in (
        SuccessCriterion.RESPONSE_TYPE_CORRECT,
        SuccessCriterion.REQUIRED_AGENTS_CORRECT,
        SuccessCriterion.REQUIRED_TOOLS_CORRECT,
        SuccessCriterion.CRITICAL_FACTS_CORRECT,
        SuccessCriterion.CRITICAL_FACTS_GROUNDED,
        SuccessCriterion.AUTHORIZATION_CORRECT,
        SuccessCriterion.NO_UNAUTHORIZED_ACCESS,
        SuccessCriterion.NO_SENSITIVE_DATA_LEAK,
        SuccessCriterion.NO_CRITICAL_HALLUCINATION,
    ))


def build_task_contract(candidate: Mapping[str, Any]) -> TaskSuccessContractDraft:
    return TaskSuccessContractDraft(
        required_criteria=base_required_criteria(),
        required_agents=("order_agent",),
        required_tools=("execute_sql_template",),
        required_template_ids=(str(candidate["query_plan"]["template_id"]),),
        authorization_expected="ALLOW_SAME_TENANT_VERIFIED_CUSTOMER",
    )


def _record_value(root: Path, candidate: Mapping[str, Any], record: Mapping[str, Any], field_path: str) -> tuple[Any, dict[str, Any]]:
    metadata: dict[str, Any] = {}
    if candidate["record_type"] == "order" and field_path in {"product_id", "product_name", "quantity", "price_per_unit"}:
        items = list(record.get("_order_items") or [])
        if len(items) != 1:
            raise ValueError("AMBIGUOUS_MULTI_ITEM_ORDER")
        value = items[0][field_path]
        if field_path == "product_id":
            metadata["companion_product_name"] = items[0]["product_name"]
        return value, metadata
    return record.get(field_path), metadata


def materialize_gold_draft(
    root: Path,
    candidate: Mapping[str, Any],
    field_registry: Mapping[tuple[str, str], Mapping[str, Any]],
    runtime_materialization: Mapping[str, Any],
    *,
    warranty_answerability: Mapping[str, Any] | None = None,
) -> PrivateBusinessGoldDraft:
    record = resolve_candidate_source(root, candidate)
    facts: list[GoldFactDraft] = []
    evidence: list[GoldEvidenceDraft] = []
    review_requirements: list[str] = []
    quality_flags = ["SOURCE_TRUTH_RESOLVED", "FIELD_LEVEL_GOLD", "AUTHORIZATION_ALLOW_DRAFT"]
    required_fact_ids: list[str] = []
    optional_fact_ids: list[str] = []
    policy_unclear = False
    sensitive = False

    fields = tuple(candidate["required_structured_fields"])
    # Product-name order lookup: product_name is the user-facing critical fact;
    # product_id remains a non-critical identity companion so D2 does not force
    # an Agent to emit both code and name when the query simply asks "which product".
    product_name_compound = candidate["semantic_family_id"] == "ORDER_PRODUCT_LOOKUP" and set(fields) == {"product_id", "product_name"}

    for field_path in fields:
        semantics = field_registry[(str(candidate["record_type"]), str(field_path))]
        value, value_meta = _record_value(root, candidate, record, field_path)
        if value is None:
            review_requirements.append(f"SOURCE_VALUE_NULL:{field_path}")
        safe_value = safe_source_value(str(candidate["record_type"]), field_path, value, product_name=value_meta.get("companion_product_name"))
        if field_path == "summary":
            raw_summary = str(value or "")
            redacted_summary = redact_text(raw_summary, limit=500)
            safe_value = redacted_summary
            value_meta["source_value_hash"] = hashlib.sha256(raw_summary.encode("utf-8")).hexdigest()[:20]
            value_meta["redaction_changed_source"] = redacted_summary != raw_summary
            if redacted_summary != raw_summary:
                sensitive = True
                review_requirements.append("TICKET_SUMMARY_CONTAINS_REDACTABLE_SENSITIVE_DATA")
        eid = evidence_id_for(candidate, field_path)
        fact_id = stable_fact_id(str(candidate["candidate_id"]), field_path)
        critical = not (product_name_compound and field_path == "product_id")
        if critical:
            required_fact_ids.append(fact_id)
        else:
            optional_fact_ids.append(fact_id)
        judge_required = bool(semantics.get("judge_required"))
        value_metadata = {
            "field_classification": semantics["classification"],
            "natural_language_label": semantics["natural_language_label"],
            "source_literal_preserved": True,
            **value_meta,
        }
        if field_path in {"price_per_unit", "total_amount"}:
            value_metadata.update({
                "currency": "CNY",
                "display_contract": "Order Agent production prompt requires ¥X.XX",
                "rounding": "source numeric value; no construction-time rounding",
            })
        if field_path in {"order_id", "ticket_id", "case_id"} or field_path.endswith("_id"):
            if field_path in {"order_id", "ticket_id", "case_id"}:
                value_metadata["runtime_identifier_materialization_required"] = True
        facts.append(GoldFactDraft(
            fact_id=fact_id,
            description=str(semantics["gold_description"]),
            normalized_value=safe_value,
            value_type=str(semantics["value_type"]),
            critical=critical,
            supporting_evidence_ids=(eid,),
            comparison_mode=str(semantics["comparison_mode"]),
            source_field_path=field_path,
            judge_required=judge_required,
            value_metadata=value_metadata,
        ))
        evidence.append(GoldEvidenceDraft(
            evidence_id=eid,
            source_type=EvidenceSourceType.STRUCTURED_DATA.value,
            required=critical,
            record_type=str(candidate["record_type"]),
            record_id=str(candidate["source_entity_ref"]),
            field_path=field_path,
            expected_value=safe_value,
            metadata={
                "privacy_preserving_record_identity": True,
                "construction_status": "SOURCE_DERIVED_DRAFT",
            },
        ))
        if semantics["classification"] == "BUSINESS_VALID_BUT_REVIEW":
            policy_unclear = True
            review_requirements.append(f"BUSINESS_VISIBILITY_PRECHECK:{field_path}")
        elif semantics["classification"] in {"INTERNAL_ONLY", "SENSITIVE", "UNSUPPORTED"}:
            sensitive = True
            review_requirements.append(f"FIELD_NOT_NORMAL_PRIVATE_GOLD:{field_path}:{semantics['classification']}")
        if semantics.get("annotation_risk") == "HIGH":
            review_requirements.append(f"HIGH_FIELD_REVIEW:{field_path}")

    answerability = AnswerabilityStatus.ANSWERABLE_WITH_RUNTIME_MATERIALIZATION
    ambiguity_status = "NONE"
    annotation_status = GoldDraftStatus.DETERMINISTICALLY_VALIDATED
    if warranty_answerability is not None:
        if not warranty_answerability.get("tool_result_sufficient"):
            answerability = AnswerabilityStatus.TOOL_OUTPUT_INSUFFICIENT
        elif not warranty_answerability.get("target_uniquely_identifiable"):
            answerability = AnswerabilityStatus.AMBIGUOUS
            ambiguity_status = "WARRANTY_TARGET_NOT_UNIQUE"
    if policy_unclear:
        answerability = AnswerabilityStatus.POLICY_UNCLEAR
        ambiguity_status = "BUSINESS_VISIBILITY_REQUIRES_MANUAL_PRECHECK"
    if sensitive:
        annotation_status = GoldDraftStatus.REJECTED_BEFORE_ANNOTATION
    elif answerability in {AnswerabilityStatus.AMBIGUOUS, AnswerabilityStatus.TOOL_OUTPUT_INSUFFICIENT, AnswerabilityStatus.SOURCE_INSUFFICIENT}:
        annotation_status = GoldDraftStatus.REJECTED_BEFORE_ANNOTATION
    elif answerability is AnswerabilityStatus.POLICY_UNCLEAR:
        annotation_status = GoldDraftStatus.NEEDS_MANUAL_PRECHECK
    elif runtime_materialization.get("status") == "MATERIALIZABLE":
        annotation_status = GoldDraftStatus.READY_FOR_DUAL_ANNOTATION
        quality_flags.append("RUNTIME_QUERY_DETERMINISTIC")
    else:
        annotation_status = GoldDraftStatus.NEEDS_MANUAL_PRECHECK
        review_requirements.append("RUNTIME_QUERY_NOT_MATERIALIZABLE")

    if any(f.judge_required for f in facts):
        quality_flags.append("SEMANTIC_JUDGE_REQUIRED_FOR_FUTURE_SCORING")
    if len(fields) > 1:
        quality_flags.append("MULTI_FIELD_ALIGNMENT_REQUIRED")

    priority = ReviewPriority.LOW
    if annotation_status != GoldDraftStatus.READY_FOR_DUAL_ANNOTATION or any(f.judge_required for f in facts) or len(fields) > 1:
        priority = ReviewPriority.HIGH
    elif any(field_registry[(candidate["record_type"], f)].get("annotation_risk") == "MEDIUM" for f in fields):
        priority = ReviewPriority.MEDIUM

    return PrivateBusinessGoldDraft(
        candidate_id=str(candidate["candidate_id"]),
        gold_draft_version=GOLD_DRAFT_VERSION,
        record_type=str(candidate["record_type"]),
        semantic_family_id=str(candidate["semantic_family_id"]),
        expected_response_type=ResponseType.ANSWER.value,
        task_success_contract_draft=build_task_contract(candidate),
        gold_facts_draft=tuple(facts),
        gold_evidence_draft=tuple(evidence),
        identity_expectation={
            "scope": "SAME_TENANT_VERIFIED_CUSTOMER",
            "tenant_group_ref": candidate["tenant_group_ref"],
            "customer_group_ref": candidate["customer_group_ref"],
            "authorization_expected": "ALLOW",
        },
        tool_expectation={
            "required_tool": "execute_sql_template",
            "required_template_id": candidate["query_plan"]["template_id"],
            "operation": "READ_LOOKUP",
            "acceptable_tool_set": ["execute_sql_template"],
        },
        answerability=answerability.value,
        ambiguity_status=ambiguity_status,
        runtime_query_materialization=dict(runtime_materialization),
        source_provenance={
            "source_entity_ref": candidate["source_entity_ref"],
            "source_field_paths": list(fields),
            "source_fact_refs": list(candidate["source_fact_refs"]),
            "source_record_hash": canonical_hash({
                "record_type": candidate["record_type"],
                "source_entity_ref": candidate["source_entity_ref"],
                "fields": {f: safe_source_value(str(candidate["record_type"]), f, _record_value(root, candidate, record, f)[0]) for f in fields},
                "tenant_group_ref": candidate["tenant_group_ref"],
                "customer_group_ref": candidate["customer_group_ref"],
            }),
        },
        annotation_status=annotation_status.value,
        quality_flags=quality_flags,
        review_requirements=review_requirements,
        review_priority=priority.value,
        required_facts=tuple(required_fact_ids),
        optional_facts=tuple(optional_fact_ids),
        forbidden_extra_disclosure=("OTHER_USER_PRIVATE_DATA", "INTERNAL_UNREQUESTED_FIELDS"),
    )
