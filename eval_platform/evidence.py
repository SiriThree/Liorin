"""Phase-3 Evidence Reliability evaluation over frozen PredictionRecord artifacts.

No function in this module calls Production, Retriever, Tool, Verifier, or DB.
All metrics are derived from one frozen PredictionRecord + Canonical Gold.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from typing import Any, Iterable, Mapping, Sequence

from eval_platform.contracts import (
    AnswerClaim,
    ClaimGroundingDiagnostic,
    ClaimSupport,
    ClaimSupportStatus,
    CriterionStatus,
    EvaluationEvidenceRef,
    EvaluationMethod,
    EvidenceCaseDiagnostic,
    EvidenceEvaluationEligibility,
    EvidenceEvaluationEligibilityStatus,
    EvidenceItemRelevance,
    EvidenceRelevanceStatus,
    EvidenceSourceType,
    GoldEvidence,
)
from eval_platform.dataset import EvaluationSample
from eval_platform.judge import JudgeRequest, JudgeRuntime
from eval_platform.report import PredictionRecord
from retrieval.security import hash_identifier


DEFAULT_RECALL_KS = (1, 3, 5, 10)


def _norm(value: Any) -> str:
    return "".join(str(value or "").strip().casefold().split())




def _structured_record_ref(record_type: str, record_id: str) -> str:
    return f"hash:{hash_identifier(str(record_id), namespace=f'structured:{record_type}')}"


def _structured_record_id_matches(record_type: str, gold_record_id: str, actual_record_id: str) -> bool:
    if _norm(gold_record_id) == _norm(actual_record_id):
        return True
    return _norm(_structured_record_ref(record_type, gold_record_id)) == _norm(actual_record_id)


def _gold_aliases(item: GoldEvidence) -> set[str]:
    aliases = {_norm(item.evidence_id)} if item.evidence_id else set()
    if item.document_id:
        aliases.add(_norm(f"doc:{item.document_id}"))
        aliases.add(_norm(item.document_id))
    if item.section_id:
        aliases.add(_norm(f"section:{item.section_id}"))
        aliases.add(_norm(item.section_id))
    if item.document_id and item.section_id:
        aliases.add(_norm(f"doc:{item.document_id}#{item.section_id}"))
    if item.record_type and item.record_id:
        for record_id in (item.record_id, _structured_record_ref(item.record_type, item.record_id)):
            base = f"record:{item.record_type}:{record_id}"
            aliases.add(_norm(base))
            if item.field_path:
                aliases.add(_norm(f"{base}#{item.field_path}"))
                aliases.add(_norm(f"{base}:{item.field_path}"))
    for alias in item.metadata.get("stable_aliases", ()) if isinstance(item.metadata, Mapping) else ():
        aliases.add(_norm(alias))
    return {x for x in aliases if x}


def _ref_aliases(ref: EvaluationEvidenceRef) -> set[str]:
    values = {
        ref.stable_id,
        ref.evidence_id,
        ref.document_id,
        ref.section_id,
        ref.result_ref,
    }
    if ref.document_id:
        values.add(f"doc:{ref.document_id}")
    if ref.section_id:
        values.add(f"section:{ref.section_id}")
    if ref.document_id and ref.section_id:
        values.add(f"doc:{ref.document_id}#{ref.section_id}")
    if ref.record_type and ref.record_id:
        base = f"record:{ref.record_type}:{ref.record_id}"
        values.add(base)
        if ref.field_path:
            values.add(f"{base}#{ref.field_path}")
            values.add(f"{base}:{ref.field_path}")
    return {_norm(x) for x in values if x}


def _parent_match(gold: GoldEvidence, actual: EvaluationEvidenceRef) -> bool:
    """Deterministic parent-child match only when hierarchy metadata is explicit."""
    metadata = gold.metadata if isinstance(gold.metadata, Mapping) else {}
    allowed_parents = {_norm(x) for x in metadata.get("allowed_parent_refs", ())}
    if allowed_parents and _norm(actual.stable_id) in allowed_parents:
        return True
    child_sections = {_norm(x) for x in actual.metadata.get("child_section_ids", ())} if isinstance(actual.metadata, Mapping) else set()
    return bool(gold.section_id and _norm(gold.section_id) in child_sections)


def evidence_matches(gold: GoldEvidence, actual: EvaluationEvidenceRef) -> bool:
    """Match evidence using the strongest stable identity available.

    A section-scoped Gold document must not match merely because the runtime
    evidence came from the same document.  That looser alias rule inflated
    recall for multi-section tasks, so typed identities are evaluated before
    generic aliases.
    """
    if gold.source_type is EvidenceSourceType.DOCUMENT:
        if actual.source_type is not EvidenceSourceType.DOCUMENT:
            return False
        if gold.document_id:
            if not actual.document_id or _norm(gold.document_id) != _norm(actual.document_id):
                # A reviewed explicit alias may still identify an equivalent
                # runtime evidence item, but same-document similarity is not enough.
                reviewed = {_norm(x) for x in (gold.metadata.get("stable_aliases", ()) if isinstance(gold.metadata, Mapping) else ())}
                return bool(reviewed & _ref_aliases(actual))
        if gold.section_id:
            if actual.section_id and _norm(gold.section_id) == _norm(actual.section_id):
                return True
            if _parent_match(gold, actual):
                return True
            # Exact evidence ids remain valid stable aliases, but a bare
            # document id cannot satisfy a section-level Gold requirement.
            if gold.evidence_id and _norm(gold.evidence_id) in _ref_aliases(actual):
                return True
            reviewed = {_norm(x) for x in (gold.metadata.get("stable_aliases", ()) if isinstance(gold.metadata, Mapping) else ())}
            return bool(reviewed & _ref_aliases(actual))
        if gold.document_id and actual.document_id:
            return _norm(gold.document_id) == _norm(actual.document_id)
        if gold.evidence_id:
            return _norm(gold.evidence_id) in _ref_aliases(actual)
        return bool(_gold_aliases(gold) & _ref_aliases(actual))

    if gold.source_type is EvidenceSourceType.STRUCTURED_DATA:
        if actual.source_type is not EvidenceSourceType.STRUCTURED_DATA:
            return False
        if not (gold.record_type and gold.record_id and actual.record_type and actual.record_id):
            return False
        if _norm(gold.record_type) != _norm(actual.record_type) or not _structured_record_id_matches(gold.record_type, gold.record_id, actual.record_id):
            return False
        # A field-scoped Gold requirement may only be satisfied by the same
        # field (or an explicitly reviewed alias), never by another field from
        # the same record.
        if gold.field_path:
            if actual.field_path and _norm(gold.field_path) == _norm(actual.field_path):
                return True
            reviewed = {_norm(x) for x in (gold.metadata.get("stable_aliases", ()) if isinstance(gold.metadata, Mapping) else ())}
            return bool(reviewed & _ref_aliases(actual))
        return True

    if gold.source_type is EvidenceSourceType.TOOL_RESULT:
        if actual.source_type is not EvidenceSourceType.TOOL_RESULT:
            return False
        return bool(_gold_aliases(gold) & _ref_aliases(actual))

    return False


def _source_type(event: Mapping[str, Any]) -> EvidenceSourceType:
    if event.get("record_type") and event.get("record_id"):
        return EvidenceSourceType.STRUCTURED_DATA
    stable = str(event.get("stable_ref") or "")
    if stable.startswith("record:"):
        return EvidenceSourceType.STRUCTURED_DATA
    if event.get("tool_name") or event.get("result_ref"):
        return EvidenceSourceType.TOOL_RESULT
    return EvidenceSourceType.DOCUMENT


def _parse_record_ref(stable: str) -> tuple[str | None, str | None, str | None]:
    if not stable.startswith("record:"):
        return None, None, None
    body = stable[len("record:"):]
    main, _, field = body.partition("#")
    parts = main.split(":", 1)
    if len(parts) != 2:
        return None, None, field or None
    return parts[0] or None, parts[1] or None, field or None


def prediction_evidence_refs(prediction: PredictionRecord) -> tuple[EvaluationEvidenceRef, ...]:
    events = prediction.trace_facts.get("evidence_events") or ()
    rows: list[EvaluationEvidenceRef] = []
    if events:
        selected_ids = {_norm(x) for x in (prediction.trace_facts.get("selected_evidence_ids") or ())}
        for event in events:
            if not isinstance(event, Mapping) or str(event.get("event") or "") == "cited":
                continue
            stable = str(event.get("stable_ref") or event.get("evidence_id") or "")
            rtype, rid, field = _parse_record_ref(stable)
            eid = str(event.get("evidence_id") or "") or None
            rows.append(EvaluationEvidenceRef(
                stable_id=stable or eid or "unknown",
                source_type=_source_type(event),
                evidence_id=eid,
                document_id=str(event.get("document_id") or "") or None,
                section_id=str(event.get("section_id") or "") or None,
                record_type=str(event.get("record_type") or rtype or "") or None,
                record_id=str(event.get("record_id") or rid or "") or None,
                field_path=str(event.get("field_path") or field or "") or None,
                tool_name=str(event.get("tool_name") or "") or None,
                result_ref=str(event.get("result_ref") or "") or None,
                round_id=event.get("round_id") if isinstance(event.get("round_id"), int) else None,
                fusion_rank=event.get("fusion_rank") if isinstance(event.get("fusion_rank"), int) else None,
                selected=bool(
                    (eid and _norm(eid) in selected_ids)
                    or (stable and _norm(stable) in selected_ids)
                    or bool(event.get("selected_for_answer"))
                ),
                status=str(event.get("status") or "") or None,
                requirement_coverage=tuple(str(x) for x in (event.get("requirement_coverage") or ())),
                authority=event.get("authority"),
                validity=event.get("validity"),
                conflict_status=str(event.get("conflict_status") or "") or None,
                final_citation_usage=bool(event.get("final_citation_usage")),
                content_preview=str(event.get("content_preview") or "") or None,
                metadata={
                    "aliases": list(event.get("aliases") or ()),
                    "observed_value": event.get("observed_value"),
                    "selected_for_answer": bool(event.get("selected_for_answer")),
                },
            ))
        return tuple(rows)

    # Backward-compatible projection for Phase-2 predictions. This is enough for
    # minimum exact matching, but round-aware metrics remain unsupported.
    for raw in prediction.trace_facts.get("evidence_refs") or ():
        value = str(raw)
        if not value:
            continue
        rtype, rid, field = _parse_record_ref(value)
        rows.append(EvaluationEvidenceRef(
            stable_id=value,
            source_type=EvidenceSourceType.STRUCTURED_DATA if rtype else EvidenceSourceType.DOCUMENT,
            record_type=rtype,
            record_id=rid,
            field_path=field,
            selected=_norm(value) in {_norm(x) for x in (prediction.trace_facts.get("selected_evidence_ids") or ())},
        ))
    return tuple(rows)


def _required_units(gold: Sequence[GoldEvidence]) -> list[tuple[str, tuple[GoldEvidence, ...]]]:
    grouped: dict[str, list[GoldEvidence]] = defaultdict(list)
    units: list[tuple[str, tuple[GoldEvidence, ...]]] = []
    for item in gold:
        if not item.required:
            continue
        if item.alternative_group:
            grouped[item.alternative_group].append(item)
        else:
            units.append((item.evidence_id, (item,)))
    for group, items in sorted(grouped.items()):
        units.append((f"alternative:{group}", tuple(items)))
    return units


def _unit_matches(unit: tuple[GoldEvidence, ...], refs: Sequence[EvaluationEvidenceRef]) -> bool:
    return any(evidence_matches(gold, actual) for gold in unit for actual in refs)


def evidence_eligibility(sample: EvaluationSample, prediction: PredictionRecord) -> EvidenceEvaluationEligibility:
    if not sample.gold_evidence:
        return EvidenceEvaluationEligibility(sample.sample_id, EvidenceEvaluationEligibilityStatus.NO_GOLD_EVIDENCE, ("case has no GoldEvidence",))
    refs = prediction_evidence_refs(prediction)
    if not refs:
        if prediction.execution_status.upper() not in {"COMPLETED", "SUCCESS", "OK"}:
            return EvidenceEvaluationEligibility(sample.sample_id, EvidenceEvaluationEligibilityStatus.NO_EVIDENCE_TRACE, ("production execution did not complete",))
        return EvidenceEvaluationEligibility(sample.sample_id, EvidenceEvaluationEligibilityStatus.NO_EVIDENCE_TRACE, ("PredictionRecord has no observable evidence trace",))
    gold_structured = any(x.source_type is EvidenceSourceType.STRUCTURED_DATA for x in sample.gold_evidence if x.required)
    observable_structured = any(x.source_type is EvidenceSourceType.STRUCTURED_DATA for x in refs)
    if gold_structured and not observable_structured:
        return EvidenceEvaluationEligibility(
            sample.sample_id,
            EvidenceEvaluationEligibilityStatus.OBSERVABILITY_INSUFFICIENT,
            ("required structured evidence exists in Gold but the production trace exposes no structured evidence result",),
        )
    return EvidenceEvaluationEligibility(sample.sample_id, EvidenceEvaluationEligibilityStatus.ELIGIBLE)


def evaluate_selected_precision(
    sample: EvaluationSample,
    selected: Sequence[EvaluationEvidenceRef],
    *,
    judge: JudgeRuntime | None = None,
) -> tuple[tuple[EvidenceItemRelevance, ...], int, int, bool]:
    rows: list[EvidenceItemRelevance] = []
    relevant = 0
    complete = True
    for ref in selected:
        if any(evidence_matches(g, ref) for g in sample.gold_evidence):
            rows.append(EvidenceItemRelevance(ref.stable_id, EvidenceRelevanceStatus.GOLD_MATCH, "selected evidence matches annotated Gold"))
            relevant += 1
            continue
        if judge is None:
            rows.append(EvidenceItemRelevance(ref.stable_id, EvidenceRelevanceStatus.NOT_EVALUATED, "non-Gold selected evidence requires semantic relevance Judge"))
            complete = False
            continue
        req = JudgeRequest.build(
            case_id=sample.sample_id,
            criterion="SELECTED_EVIDENCE_RELEVANCE",
            prompt_version="selected_evidence_relevance_v1",
            structured_input={
                "user_query": sample.runtime_input.query,
                "selected_evidence": asdict(ref),
            },
        )
        response, record = judge.evaluate(req)
        if response is None:
            rows.append(EvidenceItemRelevance(ref.stable_id, EvidenceRelevanceStatus.NOT_EVALUATED, "relevance Judge failed", record.judge_record_id))
            complete = False
        elif response.status is CriterionStatus.PASS:
            rows.append(EvidenceItemRelevance(ref.stable_id, EvidenceRelevanceStatus.SEMANTICALLY_RELEVANT, response.rationale, record.judge_record_id))
            relevant += 1
        else:
            rows.append(EvidenceItemRelevance(ref.stable_id, EvidenceRelevanceStatus.IRRELEVANT, response.rationale, record.judge_record_id))
    return tuple(rows), relevant, len(selected), complete


def evaluate_evidence_case(
    sample: EvaluationSample,
    prediction: PredictionRecord,
    *,
    ks: Sequence[int] = DEFAULT_RECALL_KS,
    judge: JudgeRuntime | None = None,
) -> EvidenceCaseDiagnostic:
    eligibility = evidence_eligibility(sample, prediction)
    refs = prediction_evidence_refs(prediction)
    selected_ids = {_norm(x) for x in (prediction.trace_facts.get("selected_evidence_ids") or ())}
    selected = tuple(ref for ref in refs if ref.selected or _norm(ref.evidence_id) in selected_ids or _norm(ref.stable_id) in selected_ids)
    # Deduplicate selected by stable identity while preserving final trace order.
    selected = tuple({ref.stable_id: ref for ref in selected}.values())
    units = _required_units(sample.gold_evidence)

    ranked = sorted(
        refs,
        key=lambda x: (
            x.round_id if x.round_id is not None else 10**6,
            x.fusion_rank if x.fusion_rank is not None else 10**6,
        ),
    )
    any_at_k: dict[int, bool | None] = {}
    for k in ks:
        if not units or not ranked:
            any_at_k[int(k)] = None
        else:
            any_at_k[int(k)] = any(_unit_matches(unit, ranked[: int(k)]) for _, unit in units)

    found_units = [name for name, unit in units if _unit_matches(unit, refs)]
    missing = tuple(name for name, unit in units if not _unit_matches(unit, refs))
    relevance, precision_num, precision_den, precision_complete = evaluate_selected_precision(sample, selected, judge=judge)
    if not eligibility.eligible:
        precision_complete = False

    return EvidenceCaseDiagnostic(
        case_id=sample.sample_id,
        trace_id=prediction.trace_id,
        eligibility=eligibility,
        any_required_evidence_recall_at_k=any_at_k,
        required_gold_evidence_recall_numerator=len(found_units),
        required_gold_evidence_recall_denominator=len(units),
        selected_evidence_precision_numerator=precision_num,
        selected_evidence_precision_denominator=precision_den,
        selected_evidence_precision_complete=precision_complete,
        retrieved_evidence=refs,
        selected_evidence=selected,
        selected_relevance=relevance,
        missing_required_units=missing,
    )


def extract_claims(sample: EvaluationSample, prediction: PredictionRecord, judge: JudgeRuntime | None) -> tuple[tuple[AnswerClaim, ...], str | None]:
    if judge is None:
        return (), "claim extraction requires configured JudgeRuntime"
    request = JudgeRequest.build(
        case_id=sample.sample_id,
        criterion="CLAIM_EXTRACTION",
        prompt_version="claim_extraction_v1",
        structured_input={
            "user_query": sample.runtime_input.query,
            "assistant_response": prediction.final_response,
        },
    )
    response, record = judge.evaluate(request)
    if response is None:
        return (), f"claim extraction Judge failed: {record.error}"
    claims = tuple(AnswerClaim(
        claim_id=str(item.get("claim_id")),
        text=str(item.get("text")),
        critical=bool(item.get("critical")),
        claim_type=str(item.get("claim_type") or "FACT"),
        normalized_subject=str(item.get("normalized_subject")) if item.get("normalized_subject") is not None else None,
        normalized_predicate=str(item.get("normalized_predicate")) if item.get("normalized_predicate") is not None else None,
        normalized_value=item.get("normalized_value"),
        source_span=str(item.get("source_span")) if item.get("source_span") is not None else None,
        gold_fact_id=str(item.get("gold_fact_id")) if item.get("gold_fact_id") else None,
    ) for item in response.claims)
    return claims, None


def _evidence_payload(ref: EvaluationEvidenceRef) -> Mapping[str, Any]:
    return {
        "stable_id": ref.stable_id,
        "source_type": ref.source_type.value,
        "document_id": ref.document_id,
        "section_id": ref.section_id,
        "record_type": ref.record_type,
        "record_id": ref.record_id,
        "field_path": ref.field_path,
        "content_preview": ref.content_preview,
        "authority": ref.authority,
        "validity": ref.validity,
    }


def evaluate_claim_grounding(
    sample: EvaluationSample,
    prediction: PredictionRecord,
    evidence: EvidenceCaseDiagnostic,
    *,
    judge: JudgeRuntime | None,
) -> ClaimGroundingDiagnostic:
    claims, error = extract_claims(sample, prediction, judge)
    if error:
        return ClaimGroundingDiagnostic(
            sample.sample_id, prediction.trace_id, (), (), 0, 0, 0, 0, 0, False, error
        )
    selected = evidence.selected_evidence or evidence.retrieved_evidence
    supports: list[ClaimSupport] = []
    gold_fact_map = {fact.fact_id: fact for fact in sample.gold_facts}
    for claim in claims:
        # Structured claims tied to a GoldFact can be grounded deterministically
        # when the exact supporting structured evidence is observable.
        fact = gold_fact_map.get(claim.gold_fact_id or "")
        if fact:
            supporting_gold = [g for g in sample.gold_evidence if g.evidence_id in set(fact.supporting_evidence_ids)]
            matching_refs = [ref for ref in selected if any(evidence_matches(g, ref) for g in supporting_gold)]
            if matching_refs and any(ref.source_type is EvidenceSourceType.STRUCTURED_DATA for ref in matching_refs):
                supports.append(ClaimSupport(
                    claim,
                    ClaimSupportStatus.SUPPORTED,
                    tuple(ref.stable_id for ref in matching_refs),
                    "structured claim has observable supporting structured evidence",
                    EvaluationMethod.DETERMINISTIC,
                ))
                continue
        if not selected:
            supports.append(ClaimSupport(claim, ClaimSupportStatus.NOT_VERIFIABLE, (), "no selected/observable evidence available", EvaluationMethod.DETERMINISTIC))
            continue
        if judge is None:
            supports.append(ClaimSupport(claim, ClaimSupportStatus.NOT_VERIFIABLE, (), "claim-evidence entailment requires JudgeRuntime", EvaluationMethod.LLM_JUDGE))
            continue
        request = JudgeRequest.build(
            case_id=sample.sample_id,
            criterion="CLAIM_EVIDENCE_ENTAILMENT",
            prompt_version="claim_evidence_entailment_v1",
            structured_input={
                "user_query": sample.runtime_input.query,
                "claim": asdict(claim),
                "evidence": [_evidence_payload(ref) for ref in selected],
            },
        )
        response, record = judge.evaluate(request)
        if response is None or response.entailment_status is None:
            supports.append(ClaimSupport(claim, ClaimSupportStatus.NOT_VERIFIABLE, (), f"entailment Judge failed: {record.error}", EvaluationMethod.LLM_JUDGE, record.judge_record_id))
            continue
        status = ClaimSupportStatus(response.entailment_status)
        supports.append(ClaimSupport(claim, status, tuple(ref.stable_id for ref in selected), response.rationale, EvaluationMethod.LLM_JUDGE, record.judge_record_id))

    critical = [row for row in supports if row.claim.critical]
    verifiable = [row for row in critical if row.status is not ClaimSupportStatus.NOT_VERIFIABLE]
    supported = [row for row in verifiable if row.status is ClaimSupportStatus.SUPPORTED]
    unsupported = [row for row in critical if row.status is ClaimSupportStatus.UNSUPPORTED]
    contradicted = [row for row in critical if row.status is ClaimSupportStatus.CONTRADICTED]
    not_verifiable = [row for row in critical if row.status is ClaimSupportStatus.NOT_VERIFIABLE]
    return ClaimGroundingDiagnostic(
        case_id=sample.sample_id,
        trace_id=prediction.trace_id,
        claims=claims,
        supports=tuple(supports),
        grounded_claim_numerator=len(supported),
        grounded_claim_denominator=len(verifiable),
        unsupported_critical_claims=len(unsupported),
        contradicted_critical_claims=len(contradicted),
        not_verifiable_critical_claims=len(not_verifiable),
        complete=not not_verifiable,
        reason="NOT_VERIFIABLE critical claims are excluded from Grounded Claim Rate denominator and reported separately",
    )


def aggregate_evidence_metrics(diags: Sequence[EvidenceCaseDiagnostic]) -> dict[str, Any]:
    eligible = [d for d in diags if d.eligibility.eligible]
    out: dict[str, Any] = {
        "eligible_cases": len(eligible),
        "observability_insufficient_cases": sum(d.eligibility.status is EvidenceEvaluationEligibilityStatus.OBSERVABILITY_INSUFFICIENT for d in diags),
    }
    for k in DEFAULT_RECALL_KS:
        vals = [d.any_required_evidence_recall_at_k.get(k) for d in eligible]
        vals = [x for x in vals if x is not None]
        out[f"any_required_evidence_recall_at_{k}"] = {
            "numerator": sum(bool(x) for x in vals),
            "denominator": len(vals),
            "rate": (sum(bool(x) for x in vals) / len(vals)) if vals else None,
        }
    req_num = sum(d.required_gold_evidence_recall_numerator for d in eligible)
    req_den = sum(d.required_gold_evidence_recall_denominator for d in eligible)
    out["required_gold_evidence_recall"] = {"numerator": req_num, "denominator": req_den, "rate": req_num / req_den if req_den else None}
    precision_rows = [d for d in eligible if d.selected_evidence_precision_complete]
    pnum = sum(d.selected_evidence_precision_numerator for d in precision_rows)
    pden = sum(d.selected_evidence_precision_denominator for d in precision_rows)
    out["selected_evidence_precision"] = {"numerator": pnum, "denominator": pden, "rate": pnum / pden if pden else None}
    out["selected_precision_incomplete_cases"] = sum(not d.selected_evidence_precision_complete for d in eligible)
    return out


def aggregate_grounding_metrics(diags: Sequence[ClaimGroundingDiagnostic]) -> dict[str, Any]:
    complete = [d for d in diags if d.complete]
    num = sum(d.grounded_claim_numerator for d in complete)
    den = sum(d.grounded_claim_denominator for d in complete)
    unsupported = sum(d.unsupported_critical_claims for d in complete)
    contradicted = sum(d.contradicted_critical_claims for d in complete)
    all_verifiable_critical = den
    return {
        "grounded_claim_rate": {"numerator": num, "denominator": den, "rate": num / den if den else None},
        "unsupported_critical_claim_rate": {
            "numerator": unsupported,
            "denominator": all_verifiable_critical,
            "rate": unsupported / all_verifiable_critical if all_verifiable_critical else None,
        },
        "contradicted_critical_claim_count": contradicted,
        "not_verifiable_critical_claim_count": sum(d.not_verifiable_critical_claims for d in diags),
        "complete_cases": len(complete),
        "incomplete_cases": len(diags) - len(complete),
    }
