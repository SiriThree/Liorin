"""Phase E1 deterministic Mixed Structured + Knowledge Gold preparation.

Construction-only contracts.  These are not CanonicalEvaluationSample objects and
never become HUMAN_REVIEWED / FORMAL_ELIGIBLE in E1.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from eval_platform.contracts import ComparisonMode, EvidenceSourceType, FactValueType, SuccessCriterion
from retrieval.security import hash_identifier

from .gold_draft import GoldDraftStatus, canonical_hash, resolve_candidate_source
from .runtime_materialization import build_runtime_materialization
from .source_inventory import build_document_source_inventory

MIXED_GOLD_DRAFT_VERSION = "mixed-gold-draft-v1"
MIXED_SOURCE_SNAPSHOT_VERSION = "mixed-source-snapshot-v1"
MIXED_PACKET_VERSION = "mixed-annotation-packet-v1"


class FactRole(StrEnum):
    ANSWER_REQUIRED = "ANSWER_REQUIRED"
    TASK_REQUIRED_INTERMEDIATE = "TASK_REQUIRED_INTERMEDIATE"
    SUPPORTING_ONLY = "SUPPORTING_ONLY"
    OPTIONAL_OUTPUT = "OPTIONAL_OUTPUT"


class EvidenceRole(StrEnum):
    ANSWER_SUPPORTING_EVIDENCE = "ANSWER_SUPPORTING_EVIDENCE"
    ROUTING_EVIDENCE = "ROUTING_EVIDENCE"
    DERIVATION_INPUT_EVIDENCE = "DERIVATION_INPUT_EVIDENCE"


class PolicyAmbiguity(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    QUALIFIED_BUT_USABLE = "QUALIFIED_BUT_USABLE"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class MixedFactDraft:
    fact_id: str
    fact_origin: str  # STRUCTURED / DOCUMENT / DERIVED
    role: str
    description: str
    normalized_value: Any
    value_type: str
    comparison_mode: str
    critical_for_task: bool
    answer_required: bool
    supporting_evidence_ids: tuple[str, ...] = ()
    source_field_path: str | None = None
    source_fact_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        x = asdict(self)
        x["supporting_evidence_ids"] = list(self.supporting_evidence_ids)
        x["metadata"] = dict(self.metadata)
        return x


@dataclass(frozen=True)
class MixedEvidenceDraft:
    evidence_id: str
    source_type: str
    evidence_role: str
    required: bool
    record_type: str | None = None
    record_id: str | None = None
    field_path: str | None = None
    document_id: str | None = None
    section_id: str | None = None
    source_fact_ids: tuple[str, ...] = ()
    expected_value: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        x = asdict(self)
        x["source_fact_ids"] = list(self.source_fact_ids)
        x["metadata"] = dict(self.metadata)
        return x


@dataclass(frozen=True)
class PolicyRuleDraft:
    rule_id: str
    document_id: str
    section_id: str
    source_fact_ids: tuple[str, ...]
    condition: str
    applicable_structured_field: str | None
    applicable_values: tuple[str, ...]
    decision: str
    exceptions: tuple[str, ...]
    deterministic: bool
    ambiguity_status: str
    qualification_preserved: bool
    source_text: tuple[str, ...]

    def to_state(self) -> dict[str, Any]:
        x = asdict(self)
        for key in ("source_fact_ids", "applicable_values", "exceptions", "source_text"):
            x[key] = list(x[key])
        return x


@dataclass(frozen=True)
class DerivedFactDraft:
    derived_fact_id: str
    input_fact_ids: tuple[str, ...]
    rule_type: str
    rule_reference: str
    operator: str
    normalized_result: str
    critical: bool
    answer_required: bool
    role: str
    e0_result: str | None
    e0_result_compatible: bool

    def to_state(self) -> dict[str, Any]:
        x = asdict(self)
        x["input_fact_ids"] = list(self.input_fact_ids)
        return x


@dataclass(frozen=True)
class MixedTaskSuccessContractDraft:
    required_criteria: tuple[str, ...]
    required_agents: tuple[str, ...]
    required_tools: tuple[str, ...]
    structured_template_id: str
    authorization_expected: str
    mixed_requirements: Mapping[str, Any]

    def to_state(self) -> dict[str, Any]:
        return {
            "required_criteria": list(self.required_criteria),
            "required_agents": list(self.required_agents),
            "required_tools": list(self.required_tools),
            "structured_template_id": self.structured_template_id,
            "authorization_expected": self.authorization_expected,
            "mixed_requirements": dict(self.mixed_requirements),
        }


@dataclass
class MixedGoldDraft:
    candidate_id: str
    gold_draft_version: str
    mixed_family_id: str
    mixed_mode: str
    expected_response_type: str
    structured_facts: tuple[MixedFactDraft, ...]
    document_facts: tuple[MixedFactDraft, ...]
    derived_facts: tuple[DerivedFactDraft, ...]
    answer_required_facts: tuple[str, ...]
    intermediate_required_facts: tuple[str, ...]
    optional_facts: tuple[str, ...]
    gold_evidence: tuple[MixedEvidenceDraft, ...]
    reasoning_contract: Mapping[str, Any]
    task_success_contract_draft: MixedTaskSuccessContractDraft
    source_necessity_contract: Mapping[str, Any]
    runtime_query_materialization: Mapping[str, Any]
    answerability: str
    ambiguity_status: str
    annotation_status: str
    review_requirements: list[str]
    quality_flags: list[str]
    gold_information_signature: str

    def to_state(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "gold_draft_version": self.gold_draft_version,
            "mixed_family_id": self.mixed_family_id,
            "mixed_mode": self.mixed_mode,
            "expected_response_type": self.expected_response_type,
            "structured_facts": [x.to_state() for x in self.structured_facts],
            "document_facts": [x.to_state() for x in self.document_facts],
            "derived_facts": [x.to_state() for x in self.derived_facts],
            "answer_required_facts": list(self.answer_required_facts),
            "intermediate_required_facts": list(self.intermediate_required_facts),
            "optional_facts": list(self.optional_facts),
            "gold_evidence": [x.to_state() for x in self.gold_evidence],
            "reasoning_contract": dict(self.reasoning_contract),
            "task_success_contract_draft": self.task_success_contract_draft.to_state(),
            "source_necessity_contract": dict(self.source_necessity_contract),
            "runtime_query_materialization": dict(self.runtime_query_materialization),
            "answerability": self.answerability,
            "ambiguity_status": self.ambiguity_status,
            "annotation_status": self.annotation_status,
            "review_requirements": sorted(set(self.review_requirements)),
            "quality_flags": sorted(set(self.quality_flags)),
            "gold_information_signature": self.gold_information_signature,
            "human_reviewed": False,
            "formal_eligible": False,
        }


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}:{hashlib.sha256('|'.join(parts).encode()).hexdigest()[:20]}"


def _e0_adapter(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "record_type": candidate["structured_record_type"],
        "source_entity_ref": candidate["structured_entity_ref"],
        "candidate_query": candidate["candidate_query"],
    }


def _structured_source_value(root: Path, candidate: Mapping[str, Any], field_path: str) -> Any:
    record = resolve_candidate_source(root, _e0_adapter(candidate))
    if candidate["structured_record_type"] == "order" and field_path == "product_id":
        items = list(record.get("_order_items") or [])
        if len(items) != 1:
            raise ValueError("AMBIGUOUS_MULTI_ITEM_ORDER")
        return items[0]["product_id"]
    return record.get(field_path)


def _structured_fact_type(field_path: str) -> tuple[str, str]:
    if field_path in {"status", "coverage_status", "coverage_type"}:
        return FactValueType.ENUM.value, ComparisonMode.NORMALIZED_EXACT.value
    if field_path.endswith("_date") or field_path.endswith("_at") or field_path == "expires_at":
        return FactValueType.DATE.value, ComparisonMode.DATE.value
    return FactValueType.STRING.value, ComparisonMode.NORMALIZED_EXACT.value


def _document_indexes(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    facts: dict[str, dict[str, Any]] = {}
    by_section: dict[str, list[dict[str, Any]]] = {}
    for line in (root / "artifacts/evaluation/dataset-expansion-d0/atomic_fact_inventory.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        f = json.loads(line)
        facts[str(f["fact_id"])] = f
        if f.get("benchmark_usable"):
            by_section.setdefault(str(f["section_id"]), []).append(f)
    _, sections = build_document_source_inventory(root)
    section_index = {str(x["section_id"]): x for x in sections}
    return facts, section_index, by_section


def _document_evidence_id(document_id: str, section_id: str) -> str:
    return f"doc:{document_id}#{section_id}"


def _structured_evidence_id(candidate: Mapping[str, Any], field_path: str) -> str:
    digest = str(candidate["structured_entity_ref"]).rsplit(":", 1)[-1]
    return f"record:{candidate['structured_record_type']}:hash:{digest}#{field_path}"


def _structured_template(candidate: Mapping[str, Any]) -> str:
    return {"order": "order_detail", "ticket": "ticket_detail", "warranty": "warranty_cases"}[str(candidate["structured_record_type"])]


def _knowledge_tool(candidate: Mapping[str, Any]) -> str:
    return "search_support_policies" if str(candidate["document_source_id"]).startswith("source:policy:") else "search_manuals"


def _base_contract(candidate: Mapping[str, Any]) -> MixedTaskSuccessContractDraft:
    criteria = tuple(x.value for x in (
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
    return MixedTaskSuccessContractDraft(
        required_criteria=criteria,
        required_agents=("order_agent", "knowledge_agent"),
        required_tools=("execute_sql_template", _knowledge_tool(candidate)),
        structured_template_id=_structured_template(candidate),
        authorization_expected="ALLOW_SAME_TENANT_VERIFIED_CUSTOMER",
        mixed_requirements={
            "structured_source_required": True,
            "document_source_required": True,
            "routing_evidence_required": candidate["mixed_mode"] == "ENTITY_TO_KNOWLEDGE_ROUTING",
            "derived_reasoning_required": candidate["mixed_mode"] in {"POLICY_APPLICATION", "CROSS_SOURCE_SYNTHESIS"},
            "final_text_alone_is_insufficient_for_mixed_success": True,
        },
    )


def _policy_rule(candidate: Mapping[str, Any], doc_facts: list[dict[str, Any]]) -> PolicyRuleDraft | None:
    fam = str(candidate["mixed_family_id"])
    if fam == "MIXED_ORDER_STATUS_POLICY":
        state = str(candidate["source_entity_state"])
        fact = doc_facts[0]
        if state == "Processing":
            decision = "CANCELLATION_ELIGIBILITY_CHECK_ALLOWED"
            ambiguity = PolicyAmbiguity.DETERMINISTIC
            values = ("Processing",)
            qualified = False
        elif state in {"Shipped", "Delivered"}:
            decision = "STANDARD_POLICY_USUALLY_DIRECT_CANCEL_NOT_ALLOWED_USE_RETURN_REFUND"
            ambiguity = PolicyAmbiguity.QUALIFIED_BUT_USABLE
            values = ("Shipped", "Delivered")
            qualified = True
        elif state == "Cancelled":
            decision = "DO_NOT_REPEAT_CANCELLATION"
            ambiguity = PolicyAmbiguity.DETERMINISTIC
            values = ("Cancelled",)
            qualified = False
        else:
            return None
        return PolicyRuleDraft(
            rule_id=_stable_id("mixed-policy-rule", "order-cancellation", ",".join(values), fact["fact_id"]),
            document_id=str(fact["document_id"]), section_id=str(fact["section_id"]), source_fact_ids=(str(fact["fact_id"]),),
            condition=f"order.status in {list(values)!r}", applicable_structured_field="order.status", applicable_values=values,
            decision=decision, exceptions=("specific contract / regional regulation / enterprise agreement may override the general policy",),
            deterministic=True, ambiguity_status=ambiguity.value, qualification_preserved=qualified,
            source_text=(str(fact["normalized_value"]),),
        )
    if fam == "MIXED_WARRANTY_STATUS_POLICY":
        # Two qualified source statements are requested verbatim at the semantic level;
        # E1 does not turn "usually" into an absolute entitlement decision.
        return PolicyRuleDraft(
            rule_id=_stable_id("mixed-policy-rule", "standard-warranty-scope", *(str(f["fact_id"]) for f in doc_facts)),
            document_id=str(doc_facts[0]["document_id"]), section_id=str(doc_facts[0]["section_id"]),
            source_fact_ids=tuple(str(f["fact_id"]) for f in doc_facts),
            condition="general standard-warranty scope explanation",
            applicable_structured_field="warranty.coverage_status",
            applicable_values=("in_warranty", "expired"),
            decision="REPORT_CURRENT_COVERAGE_STATUS_AND_QUALIFIED_STANDARD_WARRANTY_SCOPE",
            exceptions=("specific contract / regional regulation / enterprise agreement may override the general policy",),
            deterministic=True, ambiguity_status=PolicyAmbiguity.QUALIFIED_BUT_USABLE.value,
            qualification_preserved=True, source_text=tuple(str(f["normalized_value"]) for f in doc_facts),
        )
    return None


def _manual_scope_precheck(candidate: Mapping[str, Any], by_section: Mapping[str, list[dict[str, Any]]]) -> tuple[bool, int]:
    section_ids = list(candidate.get("document_section_refs") or [])
    if not section_ids:
        return True, 0
    section_fact_count = sum(len(by_section.get(str(section_id), [])) for section_id in section_ids)
    # E0 query wording asks for the section/topic's "related usage/handling points"
    # but binds only one AtomicFact.  When the same section contains multiple usable
    # facts there is no deterministic way, without rewriting the candidate, to decide
    # which subset is the complete-but-minimal answer Gold.
    selected_count = len(candidate.get("document_fact_refs") or [])
    return section_fact_count > selected_count, section_fact_count


def materialize_mixed_gold_draft(root: Path, candidate: Mapping[str, Any], *, facts_index: Mapping[str, dict[str, Any]], section_index: Mapping[str, dict[str, Any]], by_section: Mapping[str, list[dict[str, Any]]]) -> tuple[MixedGoldDraft, PolicyRuleDraft | None, dict[str, Any]]:
    doc_facts = [facts_index[str(fid)] for fid in candidate["document_fact_refs"]]
    structured_field = str(candidate["structured_fact_refs"][0]).split("#", 1)[1]
    structured_value = _structured_source_value(root, candidate, structured_field)
    struct_eid = _structured_evidence_id(candidate, structured_field)
    doc_section_ids = tuple(dict.fromkeys(str(x) for x in candidate["document_section_refs"]))
    doc_evidence_ids = tuple(_document_evidence_id(str(doc_facts[0]["document_id"]), sec) for sec in doc_section_ids)

    family = str(candidate["mixed_family_id"])
    mode = str(candidate["mixed_mode"])
    quality = ["E0_SOURCE_VALIDATED", "DUAL_SOURCE_NECESSITY_PRESERVED", "CURRENT_STABLE_DOCUMENT_IDENTITY"]
    review: list[str] = []
    policy = _policy_rule(candidate, doc_facts)

    structured_role = FactRole.TASK_REQUIRED_INTERMEDIATE
    structured_answer_required = False
    structured_evidence_role = EvidenceRole.DERIVATION_INPUT_EVIDENCE
    if family == "MIXED_WARRANTY_STATUS_POLICY":
        structured_role = FactRole.ANSWER_REQUIRED
        structured_answer_required = True
        structured_evidence_role = EvidenceRole.ANSWER_SUPPORTING_EVIDENCE
    elif mode == "ENTITY_TO_KNOWLEDGE_ROUTING":
        structured_evidence_role = EvidenceRole.ROUTING_EVIDENCE

    svt, scm = _structured_fact_type(structured_field)
    structured_fact_id = _stable_id("mixed-fact", str(candidate["candidate_id"]), "structured", structured_field)
    structured_fact = MixedFactDraft(
        fact_id=structured_fact_id,
        fact_origin="STRUCTURED",
        role=structured_role.value,
        description=f"{candidate['structured_record_type']}.{structured_field} from the authorized private record",
        normalized_value=structured_value,
        value_type=svt,
        comparison_mode=scm,
        critical_for_task=True,
        answer_required=structured_answer_required,
        supporting_evidence_ids=(struct_eid,),
        source_field_path=f"{candidate['structured_record_type']}.{structured_field}",
        metadata={"private_entity_ref": candidate["structured_entity_ref"]},
    )
    structured_evidence = MixedEvidenceDraft(
        evidence_id=struct_eid,
        source_type=EvidenceSourceType.STRUCTURED_DATA.value,
        evidence_role=structured_evidence_role.value,
        required=True,
        record_type=str(candidate["structured_record_type"]),
        record_id=str(candidate["structured_entity_ref"]),
        field_path=structured_field,
        expected_value=structured_value,
        metadata={"authorization_expected": "ALLOW_SAME_TENANT_VERIFIED_CUSTOMER"},
    )

    document_fact_drafts: list[MixedFactDraft] = []
    doc_role = FactRole.ANSWER_REQUIRED if family != "MIXED_ORDER_STATUS_POLICY" else FactRole.TASK_REQUIRED_INTERMEDIATE
    doc_evidence_role = EvidenceRole.ANSWER_SUPPORTING_EVIDENCE if doc_role is FactRole.ANSWER_REQUIRED else EvidenceRole.DERIVATION_INPUT_EVIDENCE
    for fact in doc_facts:
        eid = _document_evidence_id(str(fact["document_id"]), str(fact["section_id"]))
        document_fact_drafts.append(MixedFactDraft(
            fact_id=_stable_id("mixed-fact", str(candidate["candidate_id"]), "document", str(fact["fact_id"])),
            fact_origin="DOCUMENT",
            role=doc_role.value,
            description=str(fact["normalized_value"]),
            normalized_value=str(fact["normalized_value"]),
            value_type=FactValueType.STRING.value,
            comparison_mode=ComparisonMode.SEMANTIC.value,
            critical_for_task=True,
            answer_required=doc_role is FactRole.ANSWER_REQUIRED,
            supporting_evidence_ids=(eid,),
            source_fact_ref=str(fact["fact_id"]),
            metadata={"fact_type": fact.get("fact_type"), "section_id": fact["section_id"], "judge_required": True},
        ))

    document_evidence = []
    for section_id in doc_section_ids:
        section_facts = [f for f in doc_facts if str(f["section_id"]) == section_id]
        document_evidence.append(MixedEvidenceDraft(
            evidence_id=_document_evidence_id(str(section_facts[0]["document_id"]), section_id),
            source_type=EvidenceSourceType.DOCUMENT.value,
            evidence_role=doc_evidence_role.value,
            required=True,
            document_id=str(section_facts[0]["document_id"]),
            section_id=section_id,
            source_fact_ids=tuple(str(f["fact_id"]) for f in section_facts),
            metadata={"authority": "policy" if str(candidate["document_source_id"]).startswith("source:policy:") else "manual"},
        ))

    derived: list[DerivedFactDraft] = []
    answer_ids: list[str] = []
    intermediate_ids: list[str] = []
    optional_ids: list[str] = []
    if structured_role is FactRole.ANSWER_REQUIRED:
        answer_ids.append(structured_fact_id)
    else:
        intermediate_ids.append(structured_fact_id)
    for f in document_fact_drafts:
        (answer_ids if f.answer_required else intermediate_ids).append(f.fact_id)

    e0 = dict(candidate.get("derived_fact_draft") or {})
    if family == "MIXED_ORDER_STATUS_POLICY":
        if policy is None:
            review.append("POLICY_RULE_UNRESOLVED")
            recomputed = "UNSUPPORTED"
        else:
            recomputed = policy.decision
            if policy.ambiguity_status == PolicyAmbiguity.QUALIFIED_BUT_USABLE.value:
                quality.append("QUALIFIED_POLICY_LANGUAGE_PRESERVED")
        did = _stable_id("mixed-derived", str(candidate["candidate_id"]), "order-status-policy")
        derived.append(DerivedFactDraft(
            derived_fact_id=did,
            input_fact_ids=(structured_fact_id,) + tuple(f.fact_id for f in document_fact_drafts),
            rule_type="POLICY_APPLICATION",
            rule_reference=policy.rule_id if policy else "UNRESOLVED",
            operator="ENUM_RULE",
            normalized_result=recomputed,
            critical=True,
            answer_required=True,
            role=FactRole.ANSWER_REQUIRED.value,
            e0_result=str(e0.get("result")) if e0 else None,
            e0_result_compatible=(str(e0.get("result")) in {recomputed, "DIRECT_CANCEL_NOT_ALLOWED_USE_RETURN_REFUND" if "USUALLY_DIRECT_CANCEL" in recomputed else recomputed}),
        ))
        answer_ids.append(did)
    elif mode == "ENTITY_TO_KNOWLEDGE_ROUTING":
        did = _stable_id("mixed-derived", str(candidate["candidate_id"]), "route-manual")
        derived.append(DerivedFactDraft(
            derived_fact_id=did,
            input_fact_ids=(structured_fact_id,) + tuple(f.fact_id for f in document_fact_drafts),
            rule_type="SOURCE_ROUTING",
            rule_reference=str(candidate["relation_path"]),
            operator="EXACT_RELATION",
            normalized_result="ROUTE_TO_MATCHED_PRODUCT_MANUAL",
            critical=True,
            answer_required=False,
            role=FactRole.TASK_REQUIRED_INTERMEDIATE.value,
            e0_result=str(e0.get("result")) if e0 else None,
            e0_result_compatible=str(e0.get("result")) == "ROUTE_TO_MATCHED_PRODUCT_MANUAL",
        ))
        intermediate_ids.append(did)
    elif family == "MIXED_WARRANTY_STATUS_POLICY":
        did = _stable_id("mixed-derived", str(candidate["candidate_id"]), "warranty-policy-synthesis")
        result = f"{str(candidate['source_entity_state']).upper()}_PLUS_QUALIFIED_POLICY_SCOPE"
        derived.append(DerivedFactDraft(
            derived_fact_id=did,
            input_fact_ids=(structured_fact_id,) + tuple(f.fact_id for f in document_fact_drafts),
            rule_type="MULTI_SOURCE_SYNTHESIS",
            rule_reference=policy.rule_id if policy else "UNRESOLVED",
            operator="SYNTHESIS",
            normalized_result=result,
            critical=False,
            answer_required=False,
            role=FactRole.SUPPORTING_ONLY.value,
            e0_result=str(e0.get("result")) if e0 else None,
            e0_result_compatible=True,
        ))

    manual_scope_issue = False
    section_fact_count = len(doc_facts)
    if mode == "ENTITY_TO_KNOWLEDGE_ROUTING":
        manual_scope_issue, section_fact_count = _manual_scope_precheck(candidate, by_section)
        if manual_scope_issue:
            review += ["BROAD_MANUAL_SECTION_SCOPE", "DOCUMENT_GOLD_COMPLETENESS_NOT_DETERMINISTIC"]
            quality.append("MANUAL_SECTION_HAS_MULTIPLE_USABLE_FACTS")

    if policy and policy.ambiguity_status == PolicyAmbiguity.AMBIGUOUS.value:
        review.append("POLICY_AMBIGUOUS")
    if policy and policy.ambiguity_status == PolicyAmbiguity.UNSUPPORTED.value:
        review.append("POLICY_UNSUPPORTED")

    runtime = build_runtime_materialization(root, _e0_adapter(candidate))
    query_lower = str(runtime["runtime_query_redacted"]).casefold()
    leakage = []
    if str(structured_value).casefold() in query_lower and structured_field in {"status", "coverage_status", "product_id"}:
        leakage.append("STRUCTURED_FACT_LEAKED_AFTER_MATERIALIZATION")
    if str(candidate.get("product_ref") or "").casefold() and str(candidate.get("product_ref") or "").casefold() in query_lower and mode == "ENTITY_TO_KNOWLEDGE_ROUTING":
        leakage.append("PRODUCT_ROUTING_FACT_LEAKED_AFTER_MATERIALIZATION")
    if leakage:
        review.extend(leakage)

    status = GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value
    answerability = "ANSWERABLE_WITH_RUNTIME_MATERIALIZATION"
    ambiguity_status = "NONE"
    hard_reject = any(x in review for x in ("POLICY_UNSUPPORTED", "STRUCTURED_FACT_LEAKED_AFTER_MATERIALIZATION", "PRODUCT_ROUTING_FACT_LEAKED_AFTER_MATERIALIZATION"))
    if hard_reject:
        status = GoldDraftStatus.REJECTED_BEFORE_ANNOTATION.value
        answerability = "SOURCE_INSUFFICIENT"
        ambiguity_status = "PRESENT"
    elif review:
        status = GoldDraftStatus.NEEDS_MANUAL_PRECHECK.value
        ambiguity_status = "PRESENT"

    reasoning = {
        "mixed_mode": mode,
        "reasoning_types": list(candidate.get("reasoning_type") or []),
        "structured_input_fact_ids": [structured_fact_id],
        "document_input_fact_ids": [f.fact_id for f in document_fact_drafts],
        "derived_fact_ids": [x.derived_fact_id for x in derived],
        "provenance_complete": all(x.input_fact_ids for x in derived),
        "final_answer_requires_internal_routing_fact": False,
    }
    source_necessity = {
        "structured_source_required": True,
        "document_source_required": True,
        "without_structured_complete": False,
        "without_document_complete": False,
        "structured_necessity_reason": candidate["mixed_necessity"]["structured_necessity_reason"],
        "document_necessity_reason": candidate["mixed_necessity"]["document_necessity_reason"],
        "gold_preserves_both_sources": True,
    }
    signature = canonical_hash({
        "family": family,
        "structured_roles": [(structured_field, structured_role.value, str(structured_value))],
        "document_facts": [(str(f["fact_id"]), doc_role.value) for f in doc_facts],
        "derived": [(x.rule_type, x.normalized_result, x.role, x.answer_required) for x in derived],
        "reasoning": list(candidate.get("reasoning_type") or []),
        "sections": list(doc_section_ids),
    })
    draft = MixedGoldDraft(
        candidate_id=str(candidate["candidate_id"]), gold_draft_version=MIXED_GOLD_DRAFT_VERSION,
        mixed_family_id=family, mixed_mode=mode, expected_response_type=str(candidate["expected_response_type_draft"]),
        structured_facts=(structured_fact,), document_facts=tuple(document_fact_drafts), derived_facts=tuple(derived),
        answer_required_facts=tuple(answer_ids), intermediate_required_facts=tuple(intermediate_ids), optional_facts=tuple(optional_ids),
        gold_evidence=(structured_evidence, *tuple(document_evidence)), reasoning_contract=reasoning,
        task_success_contract_draft=_base_contract(candidate), source_necessity_contract=source_necessity,
        runtime_query_materialization=runtime, answerability=answerability, ambiguity_status=ambiguity_status,
        annotation_status=status, review_requirements=review, quality_flags=quality, gold_information_signature=signature,
    )
    diagnostics = {
        "candidate_id": candidate["candidate_id"],
        "manual_section_usable_fact_count": section_fact_count if mode == "ENTITY_TO_KNOWLEDGE_ROUTING" else None,
        "selected_document_fact_count": len(doc_facts),
        "manual_scope_issue": manual_scope_issue,
        "runtime_leakage": leakage,
        "policy_ambiguity": policy.ambiguity_status if policy else "NOT_APPLICABLE",
    }
    return draft, policy, diagnostics


def build_source_snapshot(candidate: Mapping[str, Any], draft: Mapping[str, Any], *, section_index: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    structured = []
    for fact in draft["structured_facts"]:
        structured.append({
            "fact_id": fact["fact_id"], "role": fact["role"], "field_path": fact["source_field_path"],
            "value": fact["normalized_value"], "entity_alias": candidate["structured_entity_ref"],
            "ownership_valid": True, "tenant_valid": True,
        })
    docs = []
    for sec in candidate["document_section_refs"]:
        row = section_index[str(sec)]
        relevant = [
            f["normalized_value"] for f in draft["document_facts"]
            if (f.get("metadata") or {}).get("section_id") == str(sec)
        ]
        docs.append({
            "document_id": row["document_id"], "section_id": row["section_id"], "section_title": row["title"],
            "relevant_fact_texts": relevant,
            "section_text": row["text"], "source_type": row["source_type"],
        })
    semantic = {
        "source_snapshot_version": MIXED_SOURCE_SNAPSHOT_VERSION,
        "candidate_id": candidate["candidate_id"],
        "structured_source": structured,
        "document_source": docs,
        "source_necessity": draft["source_necessity_contract"],
    }
    return {**semantic, "snapshot_hash": canonical_hash(semantic)}
