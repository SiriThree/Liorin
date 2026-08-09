"""Phase-3 evidence/grounding/recovery diagnostics and artifact writers."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from eval_platform.contracts import (
    ClaimGroundingDiagnostic,
    EvidenceCaseDiagnostic,
    EvidenceEvaluationEligibilityStatus,
    RecoveryTrace,
)
from eval_platform.dataset import EvaluationSample
from eval_platform.evidence import (
    aggregate_evidence_metrics,
    aggregate_grounding_metrics,
    evaluate_claim_grounding,
    evaluate_evidence_case,
)
from eval_platform.judge import JudgeRuntime
from eval_platform.recovery import aggregate_recovery_metrics, build_recovery_trace
from eval_platform.report import CaseJudgment, PredictionRecord


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


def evaluate_phase3(
    samples: Sequence[EvaluationSample],
    predictions: Sequence[PredictionRecord],
    judgments: Sequence[CaseJudgment],
    *,
    judge_runtime: JudgeRuntime | None = None,
) -> tuple[tuple[EvidenceCaseDiagnostic, ...], tuple[ClaimGroundingDiagnostic, ...], tuple[RecoveryTrace, ...]]:
    sample_by_id = {s.sample_id: s for s in samples}
    prediction_by_id = {p.case_id: p for p in predictions}
    judgment_by_id = {j.case_id: j for j in judgments}
    evidence_rows: list[EvidenceCaseDiagnostic] = []
    grounding_rows: list[ClaimGroundingDiagnostic] = []
    recovery_rows: list[RecoveryTrace] = []
    for case_id, prediction in prediction_by_id.items():
        sample = sample_by_id.get(case_id)
        judgment = judgment_by_id.get(case_id)
        if sample is None or judgment is None:
            continue
        evidence = evaluate_evidence_case(sample, prediction, judge=judge_runtime)
        evidence_rows.append(evidence)
        grounding_rows.append(evaluate_claim_grounding(sample, prediction, evidence, judge=judge_runtime))
        recovery_rows.append(build_recovery_trace(sample, prediction, judgment))
    return tuple(evidence_rows), tuple(grounding_rows), tuple(recovery_rows)


def _by_category(
    samples: Sequence[EvaluationSample],
    evidence: Sequence[EvidenceCaseDiagnostic],
    grounding: Sequence[ClaimGroundingDiagnostic],
    recovery: Sequence[RecoveryTrace],
) -> dict[str, Any]:
    sample_by_id = {s.sample_id: s for s in samples}
    categories = sorted({s.category.value for s in samples})
    out: dict[str, Any] = {}
    for category in categories:
        ids = {s.sample_id for s in samples if s.category.value == category}
        e = [x for x in evidence if x.case_id in ids]
        g = [x for x in grounding if x.case_id in ids]
        r = [x for x in recovery if x.case_id in ids]
        out[category] = {
            "evidence": aggregate_evidence_metrics(e),
            "grounding": aggregate_grounding_metrics(g),
            "recovery": aggregate_recovery_metrics(r),
        }
    return out


def build_phase3_summary(
    samples: Sequence[EvaluationSample],
    evidence: Sequence[EvidenceCaseDiagnostic],
    grounding: Sequence[ClaimGroundingDiagnostic],
    recovery: Sequence[RecoveryTrace],
) -> dict[str, Any]:
    evidence_summary = aggregate_evidence_metrics(evidence)
    grounding_summary = aggregate_grounding_metrics(grounding)
    recovery_summary = aggregate_recovery_metrics(recovery)
    return {
        "metric_semantics": {
            "required_gold_evidence_recall": "retrieved required Gold evidence units / all required Gold evidence units; alternative groups count once",
            "selected_evidence_precision": "relevant evidence actually passed into the verifier/answer path / all such selected evidence; document evidence uses the final verifier-accepted set and structured tool results use the specialist-context projection; unresolved semantic relevance is not guessed",
            "grounded_claim_rate": "SUPPORTED critical claims / all verifiable critical claims; NOT_VERIFIABLE is excluded and separately reported",
            "first_pass_boundary": "after initial retrieval/tool acquisition and first evidence-verifier decision, before any recovery action",
            "first_pass_failure_recovery_rate": "recoverable Gold-aware first-pass failures ending in formal Task Success PASS / all recoverable Gold-aware first-pass failures",
        },
        "evidence": evidence_summary,
        "grounding": grounding_summary,
        "recovery": recovery_summary,
        "eligibility": {
            "evidence": {status.value: sum(x.eligibility.status is status for x in evidence) for status in EvidenceEvaluationEligibilityStatus},
            "recovery": dict(sorted(__import__('collections').Counter(x.eligibility.status.value for x in recovery).items())),
        },
        "by_category": _by_category(samples, evidence, grounding, recovery),
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, values: Sequence[Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for value in values:
            handle.write(json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True) + "\n")


def _rate_text(row: Mapping[str, Any]) -> str:
    n, d, rate = row.get("numerator"), row.get("denominator"), row.get("rate")
    return f"{n} / {d} = {rate:.3%}" if isinstance(rate, (int, float)) else f"{n} / {d} = NOT EVALUABLE"


def write_phase3_artifacts(
    output_dir: str | Path,
    *,
    samples: Sequence[EvaluationSample],
    evidence: Sequence[EvidenceCaseDiagnostic],
    grounding: Sequence[ClaimGroundingDiagnostic],
    recovery: Sequence[RecoveryTrace],
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary = build_phase3_summary(samples, evidence, grounding, recovery)
    _write_json(root / "evidence_summary.json", summary["evidence"])
    _write_json(root / "recovery_summary.json", summary["recovery"])
    _write_json(root / "phase3_summary.json", summary)
    _write_jsonl(root / "case_evidence_diagnostics.jsonl", evidence)
    _write_jsonl(root / "case_claim_grounding.jsonl", grounding)
    _write_jsonl(root / "case_recovery_diagnostics.jsonl", recovery)

    e = summary["evidence"]
    g = summary["grounding"]
    r = summary["recovery"]
    evidence_md = [
        "# Phase 3 Evidence Reliability Summary",
        "",
        f"- Required Gold Evidence Recall: {_rate_text(e['required_gold_evidence_recall'])}",
        f"- Any Required Evidence Recall@5: {_rate_text(e['any_required_evidence_recall_at_5'])}",
        f"- Selected Evidence Precision: {_rate_text(e['selected_evidence_precision'])}",
        f"- Grounded Claim Rate: {_rate_text(g['grounded_claim_rate'])}",
        f"- Unsupported Critical Claim Rate: {_rate_text(g['unsupported_critical_claim_rate'])}",
        f"- Evidence observability-insufficient cases: {e['observability_insufficient_cases']}",
        "",
        "NOT_VERIFIABLE claims and semantically unresolved selected evidence are not silently treated as PASS or irrelevant.",
    ]
    recovery_md = [
        "# Phase 3 Agentic Recovery Summary",
        "",
        f"- First-pass Failure Rate: {_rate_text(r['first_pass_failure_rate'])}",
        f"- First-pass Failure Recovery Rate: {_rate_text(r['first_pass_failure_recovery_rate'])}",
        f"- Unnecessary Recovery Rate: {_rate_text(r['unnecessary_recovery_rate'])}",
        f"- Average Recovery Rounds: {r['average_recovery_rounds']}",
        f"- Recovery rounds P50/P95/Max: {r['recovery_rounds_p50']} / {r['recovery_rounds_p95']} / {r['recovery_rounds_max']}",
        "",
        "Authorization blocks and observability gaps are not counted as recoverable retrieval failures.",
    ]
    (root / "evidence_summary.md").write_text("\n".join(evidence_md) + "\n", encoding="utf-8")
    (root / "recovery_summary.md").write_text("\n".join(recovery_md) + "\n", encoding="utf-8")

    # Extend the formal Phase-2 summary without changing its Task Success semantics.
    summary_path = root / "summary.json"
    if summary_path.exists():
        formal = json.loads(summary_path.read_text(encoding="utf-8"))
        formal["phase3_evidence_recovery"] = summary
        _write_json(summary_path, formal)
    summary_md = root / "summary.md"
    if summary_md.exists():
        with summary_md.open("a", encoding="utf-8") as handle:
            handle.write("\n## Phase 3 Evidence / Recovery\n\n")
            handle.write(f"- Required Gold Evidence Recall: {_rate_text(e['required_gold_evidence_recall'])}\n")
            handle.write(f"- Selected Evidence Precision: {_rate_text(e['selected_evidence_precision'])}\n")
            handle.write(f"- Grounded Claim Rate: {_rate_text(g['grounded_claim_rate'])}\n")
            handle.write(f"- First-pass Failure Recovery Rate: {_rate_text(r['first_pass_failure_recovery_rate'])}\n")
    return summary
