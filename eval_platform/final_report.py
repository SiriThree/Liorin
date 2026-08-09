"""Final Phase-6 report and resume-safe metric provenance."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from eval_platform.readiness import EvaluationReadiness, ReadinessStatus
from eval_platform.regression import RunValidity


FINAL_REPORT_SCHEMA_VERSION = "1.0"


class MetricProvenanceStatus(StrEnum):
    SAFE_TO_USE = "SAFE_TO_USE"
    NOT_SAFE_TO_USE = "NOT_SAFE_TO_USE"
    ENGINEERING_ONLY = "ENGINEERING_ONLY"
    LEGACY_DO_NOT_USE = "DO_NOT_USE_AS_FORMAL_QUALITY_METRIC"


@dataclass(frozen=True, slots=True)
class ResumeMetric:
    metric_name: str
    value: float | None
    numerator: int | None
    denominator: int | None
    dataset: str | None
    split: str | None
    dataset_version: str | None
    dataset_hash: str | None
    run_id: str | None
    git_commit: str | None
    config_hash: str | None
    model: str | None
    judge: str | None
    report_path: str | None
    limitations: tuple[str, ...]
    status: MetricProvenanceStatus
    reason: str

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["status"] = self.status.value
        state["limitations"] = list(self.limitations)
        return state


def assess_resume_metric(
    *, metric_name: str, value: float | None, numerator: int | None, denominator: int | None,
    metadata: Mapping[str, Any], run_validity: RunValidity, formal_eligible: bool,
    real_production: bool, real_judge_when_required: bool, is_fixture: bool = False,
    is_legacy: bool = False, judge_required: bool = False, report_path: str | None = None,
    limitations: Sequence[str] = (),
) -> ResumeMetric:
    reasons: list[str] = []
    if is_legacy: reasons.append("legacy/proxy metric")
    if is_fixture: reasons.append("fixture/mock/stub result")
    if value is None or denominator in {None, 0}: reasons.append("metric not actually run")
    if run_validity is not RunValidity.VALID: reasons.append(f"run validity={run_validity.value}")
    if not formal_eligible: reasons.append("dataset not formal eligible")
    if not real_production: reasons.append("non-mock Production execution not verified")
    if judge_required and not real_judge_when_required: reasons.append("required real Judge not verified")
    for key in ("dataset_hash", "run_id", "production_config_hash"):
        if not metadata.get(key): reasons.append(f"missing {key}")
    status = MetricProvenanceStatus.SAFE_TO_USE if not reasons else (MetricProvenanceStatus.LEGACY_DO_NOT_USE if is_legacy else MetricProvenanceStatus.NOT_SAFE_TO_USE)
    return ResumeMetric(
        metric_name, value, numerator, denominator, metadata.get("dataset_name"), metadata.get("split"),
        metadata.get("dataset_version"), metadata.get("dataset_hash"), metadata.get("run_id"), metadata.get("git_commit"),
        metadata.get("production_config_hash"), metadata.get("model"), metadata.get("judge_model"), report_path,
        tuple(limitations), status, "; ".join(reasons) if reasons else "provenance chain complete",
    )


def build_final_report(*, readiness: EvaluationReadiness, formal_summary: Mapping[str, Any] | None = None, phase3: Mapping[str, Any] | None = None, phase4: Mapping[str, Any] | None = None, phase5: Mapping[str, Any] | None = None, ablation: Mapping[str, Any] | None = None, gate: Mapping[str, Any] | None = None, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    formal_summary = dict(formal_summary or {})
    by_name = readiness.by_name()
    production_ready = by_name.get("production_runtime") and by_name["production_runtime"].status is ReadinessStatus.READY
    judge_ready = by_name.get("judge_provider") and by_name["judge_provider"].status is ReadinessStatus.READY
    validation = by_name.get("validation_split")
    trusted_test = by_name.get("trusted_test_split")
    formal_blocked = not production_ready or not judge_ready
    return {
        "schema_version": FINAL_REPORT_SCHEMA_VERSION,
        "evaluation_platform": "READY",
        "evaluation_platform_engineering": "COMPLETE",
        "formal_quality_evaluation": "BLOCKED" if formal_blocked else ("RUN" if formal_summary else "READY_TO_RUN"),
        "formal_validation": "NOT RUN" if formal_blocked else ("RUN" if formal_summary else "READY_TO_RUN"),
        "formal_validation_status": "BLOCKED" if formal_blocked else ("VALID" if formal_summary else "READY_TO_RUN"),
        "readiness": readiness.to_state(),
        "dataset_scope": {
            "validation": validation.details if validation else {},
            "trusted_test": bool(trusted_test and trusted_test.status is ReadinessStatus.READY),
            "multi_turn": by_name.get("multi_turn_subset").to_state() if by_name.get("multi_turn_subset") else None,
            "safety": by_name.get("safety_subset").to_state() if by_name.get("safety_subset") else None,
            "recovery": by_name.get("recovery_subset").to_state() if by_name.get("recovery_subset") else None,
        },
        "core_metrics": {
            "end_to_end_task_success": formal_summary.get("overall_end_to_end_task_success") or formal_summary.get("task_success") or "NOT RUN",
            "required_gold_evidence_recall": (phase3 or {}).get("required_gold_evidence_recall", "NOT RUN"),
            "grounded_claim_rate": (phase3 or {}).get("grounded_claim_rate", "NOT RUN"),
            "first_pass_failure_recovery_rate": (phase3 or {}).get("first_pass_failure_recovery_rate", "NOT RUN"),
            "safety_pass_rate": ((phase5 or {}).get("safety") or {}).get("safety_pass_rate", "NOT RUN"),
        },
        "context_quality_cost": phase4 or {"status": "NOT RUN"},
        "failure_attribution": (phase5 or {}).get("failure_attribution") or {"status": "NOT RUN"},
        "ablation": ablation or {"status": "NOT RUN"},
        "regression_gate": gate or {"status": "BASELINE_NOT_ESTABLISHED"},
        "metadata": dict(metadata or {}),
        "limitations": [
            "No trusted TEST split unless readiness explicitly says READY.",
            "Formal metrics are NOT RUN when Production or required Judge is blocked.",
            "Phase-4 multi-turn candidate sessions remain review debt unless formally eligible.",
            "Order Agent structured business-query tool wiring remains a Production gap.",
        ],
    }


def write_final_report(output_dir: str | Path, report: Mapping[str, Any]) -> dict[str, Path]:
    target = Path(output_dir); target.mkdir(parents=True, exist_ok=True)
    json_path = target / "final_evaluation_report.json"
    md_path = target / "FINAL_EVALUATION_REPORT.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    m = report.get("core_metrics") or {}
    lines = [
        "# Liorin Final Evaluation Report", "",
        f"Evaluation Platform Engineering: **{report.get('evaluation_platform_engineering', report.get('evaluation_platform'))}**",
        f"Formal Quality Evaluation: **{report.get('formal_quality_evaluation', report.get('formal_validation'))}**",
        f"Formal Validation Result: **{report.get('formal_validation')}**", "",
        "## Core metrics", "",
        f"- End-to-End Task Success: {m.get('end_to_end_task_success', 'NOT RUN')}",
        f"- Required Gold Evidence Recall: {m.get('required_gold_evidence_recall', 'NOT RUN')}",
        f"- Grounded Claim Rate: {m.get('grounded_claim_rate', 'NOT RUN')}",
        f"- First-pass Failure Recovery Rate: {m.get('first_pass_failure_recovery_rate', 'NOT RUN')}",
        f"- Safety Pass Rate: {m.get('safety_pass_rate', 'NOT RUN')}", "",
        "## Limitations", "",
    ]
    lines.extend(f"- {x}" for x in report.get("limitations", []))
    md_path.write_text("\n".join(lines)+"\n", encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def write_resume_safe_metrics(path: str | Path, metrics: Sequence[ResumeMetric], *, engineering: Mapping[str, Any] | None = None, legacy: Mapping[str, Any] | None = None) -> Path:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    safe = [x for x in metrics if x.status is MetricProvenanceStatus.SAFE_TO_USE]
    lines = ["# Resume-safe Metrics", "", "This file is the only approved source for formal resume quality metrics.", "", "## SAFE_TO_USE QUALITY METRICS", ""]
    if not safe:
        lines.append("**NONE**")
    else:
        for item in safe:
            lines.append(f"- {item.metric_name}: {item.value} ({item.numerator}/{item.denominator}) — run `{item.run_id}`")
    lines += ["", "## NOT_SAFE_TO_USE / BLOCKED", ""]
    unsafe = [x for x in metrics if x.status is not MetricProvenanceStatus.SAFE_TO_USE]
    if not unsafe:
        lines.append("None")
    else:
        for item in unsafe:
            lines.append(f"- {item.metric_name}: **{item.status.value}** — {item.reason}")
    lines += ["", "## ENGINEERING_ONLY", ""]
    for key, value in (engineering or {}).items(): lines.append(f"- {key}: {value}")
    lines += ["", "## Legacy metrics — DO NOT USE AS FORMAL QUALITY", ""]
    for key, value in (legacy or {}).items(): lines.append(f"- {key}: {value} — DO_NOT_USE_AS_FORMAL_QUALITY_METRIC")
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")
    return path


__all__ = ["FINAL_REPORT_SCHEMA_VERSION", "MetricProvenanceStatus", "ResumeMetric", "assess_resume_metric", "build_final_report", "write_final_report", "write_resume_safe_metrics"]
