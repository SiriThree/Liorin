"""Unified, JSON-safe evaluation reports and Phase-2 formal E2E artifacts."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from eval_platform.regression import RunValidity

from eval_platform.contracts import (
    CriterionJudgment,
    CriterionStatus,
    EvaluationEligibility,
    EvaluationEligibilityStatus,
    EvaluationMethod,
    SuccessCriterion,
    TaskSuccessStatus,
)


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


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    """Facts produced by exactly one production execution.

    Gold judgments are deliberately excluded. Diagnostic fields must be derived
    from the execution trace identified by ``trace_id``.
    """

    case_id: str
    trace_id: str
    final_response: str
    response_type: str
    trace_facts: Mapping[str, Any]
    runtime_metrics: Mapping[str, Any]
    execution_status: str = "COMPLETED"
    execution_error: str | None = None
    run_id: str | None = None
    schema_version: str = "3.0"

    def to_state(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "final_response": self.final_response,
            "response_type": self.response_type,
            "trace_facts": dict(self.trace_facts),
            "runtime_metrics": dict(self.runtime_metrics),
            "execution_status": self.execution_status,
            "execution_error": self.execution_error,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "PredictionRecord":
        allowed = {
            "case_id", "run_id", "trace_id", "final_response", "response_type",
            "trace_facts", "runtime_metrics", "execution_status", "execution_error", "schema_version",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown PredictionRecord field(s): {sorted(unknown)}")
        return cls(
            case_id=str(value.get("case_id") or ""),
            run_id=str(value.get("run_id")) if value.get("run_id") is not None else None,
            trace_id=str(value.get("trace_id") or ""),
            final_response=str(value.get("final_response") or ""),
            response_type=str(value.get("response_type") or ""),
            trace_facts=dict(value.get("trace_facts") or {}),
            runtime_metrics=dict(value.get("runtime_metrics") or {}),
            execution_status=str(value.get("execution_status") or "UNKNOWN"),
            execution_error=str(value.get("execution_error")) if value.get("execution_error") else None,
            schema_version=str(value.get("schema_version") or "2.0"),
        )


@dataclass(frozen=True, slots=True)
class CaseJudgment:
    """Evaluator-only comparison between one frozen PredictionRecord and hidden Gold."""

    case_id: str
    run_id: str | None
    execution_status: str
    criterion_judgments: tuple[CriterionJudgment, ...]
    task_success_status: TaskSuccessStatus | None
    task_success_bool: bool | None
    eligibility_status: EvaluationEligibilityStatus = EvaluationEligibilityStatus.ELIGIBLE
    failed_criteria: tuple[SuccessCriterion, ...] = ()
    incomplete_criteria: tuple[SuccessCriterion, ...] = ()
    rationale: str | None = None
    trace_id: str | None = None

    def to_state(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    run_id: str
    predictions: tuple[PredictionRecord, ...]
    judgments: tuple[CaseJudgment, ...] = ()
    eligibilities: tuple[EvaluationEligibility, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "metadata": _jsonable(self.metadata),
            "prediction_count": len(self.predictions),
            "judgment_count": len(self.judgments),
            "eligibilities": _jsonable(self.eligibilities),
        }


@dataclass(frozen=True, slots=True)
class ScenarioEvaluationResult:
    scenario_id: str
    output: Mapping[str, Any]
    scores: Mapping[str, float]
    trace: Mapping[str, Any]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Legacy component report. ``success_rate`` is execution success only."""

    dataset_name: str
    results: tuple[ScenarioEvaluationResult, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def metrics(self) -> dict[str, float]:
        names = {name for result in self.results for name in result.scores}
        return {
            name: sum(result.scores.get(name, 0.0) for result in self.results) / len(self.results)
            for name in sorted(names)
        } if self.results else {}

    @property
    def execution_success_rate(self) -> float:
        return sum(1 for result in self.results if result.error is None) / len(self.results) if self.results else 0.0

    @property
    def success_rate(self) -> float:
        return self.execution_success_rate

    def to_state(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "created_at": self.created_at.isoformat(),
            "scenario_count": len(self.results),
            "success_rate": self.success_rate,
            "execution_success_rate": self.execution_success_rate,
            "success_rate_semantics": "RUNTIME_EXECUTION_SUCCESS_NOT_E2E_TASK_SUCCESS",
            "metrics": self.metrics,
            "results": [
                {
                    "scenario_id": item.scenario_id,
                    "output": dict(item.output),
                    "scores": dict(item.scores),
                    "trace": dict(item.trace),
                    "error": item.error,
                }
                for item in self.results
            ],
        }


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": (numerator / denominator) if denominator else None,
    }


def build_formal_summary(samples: Sequence[Any], judgments: Sequence[CaseJudgment]) -> dict[str, Any]:
    sample_by_id = {sample.sample_id: sample for sample in samples}
    eligible = [j for j in judgments if j.eligibility_status is EvaluationEligibilityStatus.ELIGIBLE]
    ineligible = [j for j in judgments if j.eligibility_status is not EvaluationEligibilityStatus.ELIGIBLE]
    execution_errors = [j for j in eligible if j.task_success_status is TaskSuccessStatus.EXECUTION_ERROR]
    incomplete = [j for j in eligible if j.task_success_status is TaskSuccessStatus.INCOMPLETE]
    passed = [j for j in eligible if j.task_success_status is TaskSuccessStatus.PASS]
    failed = [j for j in eligible if j.task_success_status is TaskSuccessStatus.FAIL]

    # Formal quality denominator excludes evaluation-infrastructure INCOMPLETE,
    # but retains production execution errors as user-visible task failures.
    quality_denominator = len(passed) + len(failed) + len(execution_errors)
    attempted_denominator = len(eligible)
    if not eligible:
        run_validity = RunValidity.INSUFFICIENT_DATA
    elif incomplete:
        run_validity = RunValidity.JUDGE_INCOMPLETE
    else:
        run_validity = RunValidity.VALID

    def dimensions(attr: str) -> dict[str, Any]:
        grouped: dict[str, list[CaseJudgment]] = defaultdict(list)
        for judgment in eligible:
            sample = sample_by_id.get(judgment.case_id)
            if sample is None:
                continue
            value = getattr(sample, attr)
            key = value.value if isinstance(value, Enum) else str(value)
            grouped[key].append(judgment)
        result: dict[str, Any] = {}
        for key, rows in sorted(grouped.items()):
            p = sum(1 for j in rows if j.task_success_status is TaskSuccessStatus.PASS)
            denominator = sum(
                1 for j in rows
                if j.task_success_status in {TaskSuccessStatus.PASS, TaskSuccessStatus.FAIL, TaskSuccessStatus.EXECUTION_ERROR}
            )
            result[key] = _rate(p, denominator)
        return result

    coverage: dict[str, dict[str, int]] = {}
    for judgment in eligible:
        for item in judgment.criterion_judgments:
            bucket = coverage.setdefault(item.criterion.value, {
                "required_cases": 0,
                "deterministic": 0,
                "llm_judge": 0,
                "composite": 0,
                "human_review": 0,
                "not_evaluable": 0,
            })
            if item.required:
                bucket["required_cases"] += 1
            if item.evaluation_method is EvaluationMethod.DETERMINISTIC:
                bucket["deterministic"] += 1
            elif item.evaluation_method is EvaluationMethod.LLM_JUDGE:
                bucket["llm_judge"] += 1
            elif item.evaluation_method is EvaluationMethod.COMPOSITE:
                bucket["composite"] += 1
            elif item.evaluation_method is EvaluationMethod.HUMAN_REVIEW:
                bucket["human_review"] += 1
            if item.status in {CriterionStatus.NOT_EVALUATED, CriterionStatus.ERROR}:
                bucket["not_evaluable"] += 1

    return {
        "run_validity": run_validity.value,
        "metric_semantics": {
            "north_star": "End-to-End Task Success = PASS / evaluable eligible attempted cases; production execution errors count as failure; evaluation-infrastructure INCOMPLETE is excluded and separately reported",
            "legacy_component_scores_included": False,
        },
        "cases": {
            "dataset_cases": len(samples),
            "eligible_cases": len(eligible),
            "ineligible_cases": len(ineligible),
            "execution_errors": len(execution_errors),
            "incomplete_evaluations": len(incomplete),
            "task_pass": len(passed),
            "task_fail": len(failed),
        },
        "overall_end_to_end_task_success": _rate(len(passed), quality_denominator),
        "attempted_task_success_diagnostic": _rate(len(passed), attempted_denominator),
        "execution_error_rate": _rate(len(execution_errors), attempted_denominator),
        "incomplete_evaluation_rate": _rate(len(incomplete), attempted_denominator),
        "by_category": dimensions("category"),
        "by_subcategory": dimensions("subcategory"),
        "by_difficulty": dimensions("difficulty"),
        "criterion_coverage": dict(sorted(coverage.items())),
        "eligibility_status": dict(sorted(Counter(j.eligibility_status.value for j in judgments).items())),
    }


def write_formal_artifacts(
    output_dir: str | Path,
    *,
    run: EvaluationRun,
    samples: Sequence[Any],
    judge_records: Sequence[Any] = (),
    human_review_items: Sequence[Any] = (),
) -> dict[str, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    predictions_path = target / "predictions.jsonl"
    judgments_path = target / "judgments.jsonl"
    run_path = target / "evaluation_run.json"
    summary_path = target / "summary.json"
    summary_md_path = target / "summary.md"
    judge_path = target / "judge_records.jsonl"
    review_path = target / "human_review_queue.jsonl"

    predictions_path.write_text("".join(json.dumps(p.to_state(), ensure_ascii=False, sort_keys=True) + "\n" for p in run.predictions), encoding="utf-8")
    judgments_path.write_text("".join(json.dumps(j.to_state(), ensure_ascii=False, sort_keys=True) + "\n" for j in run.judgments), encoding="utf-8")
    run_path.write_text(json.dumps(run.to_state(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    judge_path.write_text("".join(json.dumps(_jsonable(r), ensure_ascii=False, sort_keys=True) + "\n" for r in judge_records), encoding="utf-8")
    review_path.write_text("".join(json.dumps(_jsonable(r), ensure_ascii=False, sort_keys=True) + "\n" for r in human_review_items), encoding="utf-8")

    summary = build_formal_summary(samples, run.judgments)
    summary["run"] = {
        "run_id": run.run_id,
        "dataset_name": run.metadata.get("dataset_name"),
        "dataset_version": run.metadata.get("dataset_version"),
        "dataset_hash": run.metadata.get("dataset_hash"),
        "evaluator_version": run.metadata.get("evaluator_version"),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    overall = summary["overall_end_to_end_task_success"]
    cases = summary["cases"]
    lines = [
        "# Liorin Formal Evaluation Summary",
        "",
        f"- Dataset: {summary['run']['dataset_name']} ({summary['run']['dataset_version']})",
        f"- Dataset hash: {summary['run']['dataset_hash']}",
        f"- Eligible cases: {cases['eligible_cases']}",
        f"- Executed/predicted cases: {len(run.predictions)}",
        f"- Ineligible cases: {cases['ineligible_cases']}",
        f"- Execution errors: {cases['execution_errors']}",
        f"- Incomplete evaluations: {cases['incomplete_evaluations']}",
        f"- End-to-End Task Success: {overall['numerator']} / {overall['denominator']}" + (f" = {overall['rate']:.2%}" if overall['rate'] is not None else " = N/A"),
        "",
        "## By category",
        "",
    ]
    for category, metric in summary["by_category"].items():
        rate_text = f"{metric['rate']:.2%}" if metric["rate"] is not None else "N/A"
        lines.append(f"- {category}: {metric['numerator']} / {metric['denominator']} = {rate_text}")
    lines.extend([
        "",
        "> Production execution errors count as task failures. Judge/evaluation infrastructure failures are INCOMPLETE and excluded from the quality denominator.",
    ])
    summary_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "evaluation_run": run_path,
        "predictions": predictions_path,
        "judgments": judgments_path,
        "summary": summary_path,
        "summary_md": summary_md_path,
        "judge_records": judge_path,
        "human_review_queue": review_path,
    }


__all__ = [
    "PredictionRecord", "CaseJudgment", "EvaluationRun", "ScenarioEvaluationResult", "EvaluationReport",
    "build_formal_summary", "write_formal_artifacts",
]
