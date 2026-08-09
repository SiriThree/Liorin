"""Judge calibration fixtures kept separate from formal validation/test data."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from eval_platform.contracts import CriterionStatus, SuccessCriterion


REQUIRED_CALIBRATION_KINDS = frozenset({
    "obvious_correct",
    "obvious_wrong",
    "correct_paraphrase",
    "partial_missing_critical_fact",
    "extra_harmless_detail",
    "unsupported_critical_claim",
    "contradiction",
    "correct_clarification",
    "wrong_clarification",
    "unnecessary_clarification",
    "correct_handoff",
    "incorrect_refusal",
})


@dataclass(frozen=True, slots=True)
class JudgeCalibrationCase:
    case_id: str
    kind: str
    criterion: SuccessCriterion
    payload: Mapping[str, Any]
    expected_status: CriterionStatus
    reference_source: str
    reference_reason: str


def load_judge_calibration(path: str | Path) -> tuple[JudgeCalibrationCase, ...]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("judge calibration dataset must be a non-empty JSON list")
    cases: list[JudgeCalibrationCase] = []
    ids: set[str] = set()
    for row in rows:
        case_id = str(row.get("id") or "")
        if not case_id or case_id in ids:
            raise ValueError(f"invalid/duplicate calibration id: {case_id!r}")
        ids.add(case_id)
        expected = CriterionStatus(str(row.get("expected_status") or ""))
        if expected not in {CriterionStatus.PASS, CriterionStatus.FAIL}:
            raise ValueError("calibration reference must be PASS or FAIL")
        source = str(row.get("reference_source") or "")
        reason = str(row.get("reference_reason") or "")
        if not source or not reason:
            raise ValueError(f"calibration case {case_id} lacks reference provenance")
        payload = {k: v for k, v in row.items() if k not in {"id", "kind", "criterion", "expected_status", "reference_source", "reference_reason"}}
        cases.append(JudgeCalibrationCase(
            case_id=case_id,
            kind=str(row.get("kind") or ""),
            criterion=SuccessCriterion(str(row.get("criterion") or "")),
            payload=payload,
            expected_status=expected,
            reference_source=source,
            reference_reason=reason,
        ))
    kinds = {case.kind for case in cases}
    missing = REQUIRED_CALIBRATION_KINDS - kinds
    if missing:
        raise ValueError(f"judge calibration missing required fixture kinds: {sorted(missing)}")
    return tuple(cases)


__all__ = ["JudgeCalibrationCase", "REQUIRED_CALIBRATION_KINDS", "load_judge_calibration"]

PHASE3_REQUIRED_CALIBRATION_KINDS = frozenset({
    "exact_support", "paraphrase_support", "partial_support", "unsupported",
    "contradicted", "structured_fact_support", "multiple_evidence_synthesis",
    "irrelevant_evidence",
})


def load_phase3_claim_calibration(path: str | Path) -> tuple[Mapping[str, Any], ...]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("Phase-3 claim calibration must be a non-empty JSON list")
    ids: set[str] = set()
    kinds: set[str] = set()
    allowed = {"SUPPORTED", "UNSUPPORTED", "CONTRADICTED", "NOT_VERIFIABLE", "IRRELEVANT", "SEMANTICALLY_RELEVANT", "GOLD_MATCH"}
    normalized: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Phase-3 calibration rows must be objects")
        case_id = str(row.get("id") or "")
        kind = str(row.get("kind") or "")
        expected = str(row.get("expected") or "")
        if not case_id or case_id in ids:
            raise ValueError(f"invalid/duplicate Phase-3 calibration id: {case_id!r}")
        if not kind or expected not in allowed:
            raise ValueError(f"invalid Phase-3 calibration row: {case_id}")
        if not row.get("reference_source") or not row.get("reference_reason"):
            raise ValueError(f"Phase-3 calibration row lacks reference provenance: {case_id}")
        ids.add(case_id)
        kinds.add(kind)
        normalized.append(dict(row))
    missing = PHASE3_REQUIRED_CALIBRATION_KINDS - kinds
    if missing:
        raise ValueError(f"Phase-3 calibration missing fixture kinds: {sorted(missing)}")
    return tuple(normalized)


__all__ += ["PHASE3_REQUIRED_CALIBRATION_KINDS", "load_phase3_claim_calibration"]
