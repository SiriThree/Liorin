"""Scenario runner connecting Dataset -> Runtime -> Trace -> Evaluator -> Report."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from eval_platform.dataset import EvaluationDataset, EvaluationScenario
from eval_platform.report import EvaluationReport, ScenarioEvaluationResult
from observability import TraceRecorder, get_default_metrics, get_default_trace_recorder

Evaluator = Callable[[EvaluationScenario, Mapping[str, Any], Mapping[str, Any]], Mapping[str, float] | float]


class EvaluationRunner:
    def __init__(
        self,
        runtime: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        *,
        evaluators: Mapping[str, Evaluator],
        trace_recorder: TraceRecorder | None = None,
    ) -> None:
        self.runtime = runtime
        self.evaluators = dict(evaluators)
        self.trace_recorder = trace_recorder or get_default_trace_recorder()

    def run(self, dataset: EvaluationDataset) -> EvaluationReport:
        results = []
        for scenario in dataset.scenarios:
            identity = scenario.inputs.get("identity_context") or {}
            conversation_id = str(identity.get("conversation_id") or scenario.metadata.get("conversation_id") or f"conversation:{scenario.scenario_id}")
            thread_id = str(identity.get("thread_id") or scenario.metadata.get("thread_id") or f"thread:{scenario.scenario_id}")
            request_id = str(scenario.metadata.get("request_id") or f"eval:{dataset.name}:{scenario.scenario_id}")
            output: Mapping[str, Any] = {}
            error = None
            scores: dict[str, float] = {}
            with self.trace_recorder.trace(
                request_id=request_id,
                conversation_id=conversation_id,
                thread_id=thread_id,
                agent_name=str(scenario.metadata.get("agent_name") or "support_agent"),
            ) as trace:
                try:
                    output = self.runtime(scenario.inputs)
                    for name, evaluator in self.evaluators.items():
                        raw = evaluator(scenario, output, trace.to_state())
                        if isinstance(raw, Mapping):
                            scores.update({str(key): float(value) for key, value in raw.items()})
                        else:
                            scores[name] = float(raw)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
            results.append(ScenarioEvaluationResult(
                scenario_id=scenario.scenario_id,
                output=output,
                scores=scores,
                trace=trace.to_state(),
                error=error,
            ))
        report = EvaluationReport(dataset.name, tuple(results))
        metrics = get_default_metrics()
        metrics.set_value("evaluation_execution_success_rate", report.execution_success_rate)
        for name, value in report.metrics.items():
            metrics.set_value(name, value)
        return report


# ---------------------------------------------------------------------------
# Phase 2 formal Canonical E2E runner
# ---------------------------------------------------------------------------

from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from eval_platform.contracts import (
    CriterionStatus,
    EvaluationEligibilityStatus,
    EvaluationMethod,
    HumanReviewItem,
    TaskCategory,
    TaskSuccessStatus,
)
from eval_platform.criteria import evaluate_criteria, evaluate_eligibility, resolve_conditional_criteria
from eval_platform.dataset import EvaluationSample, canonical_dataset_hash, read_canonical_dataset
from eval_platform.judge import JudgeRuntime
from eval_platform.production_adapter import ProductionEvaluationAdapter
from eval_platform.safety import evaluate_safety_case, safety_result_to_judgment, SAFETY_EVALUATOR_VERSION, SAFETY_POLICY_VERSION
from eval_platform.failure_attribution import attribute_failure, FAILURE_TAXONOMY_VERSION, ATTRIBUTION_POLICY_VERSION
from eval_platform.phase5_report import write_phase5_artifacts
from eval_platform.report import CaseJudgment, EvaluationRun, PredictionRecord, write_formal_artifacts
from eval_platform.phase3_report import evaluate_phase3, write_phase3_artifacts
from eval_platform.task_success import TaskSuccessEvaluator
from eval_platform.validation import validate_dataset


FORMAL_EVALUATOR_VERSION = "phase3-evidence-recovery-v1"


def _git_commit(root: str | Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root) if root else None,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        value = result.stdout.strip()
        return value if result.returncode == 0 and value else None
    except Exception:
        return None


def _hash_json(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def _review_items(sample: EvaluationSample, prediction: PredictionRecord, judgment: CaseJudgment) -> list[HumanReviewItem]:
    items: list[HumanReviewItem] = []
    for criterion in judgment.criterion_judgments:
        needs_review = (
            criterion.status in {CriterionStatus.ERROR, CriterionStatus.NOT_EVALUATED}
            or sample.category is TaskCategory.SAFETY_GOVERNANCE
        )
        if not needs_review:
            continue
        items.append(HumanReviewItem(
            case_id=sample.sample_id,
            criterion=criterion.criterion,
            prediction=prediction.to_state(),
            gold={
                "expected_behavior": sample.to_dict()["expected_behavior"],
                "task_success_contract": sample.to_dict()["task_success_contract"],
                "gold_evidence": sample.to_dict()["gold_evidence"],
                "gold_facts": sample.to_dict()["gold_facts"],
                "safety_constraints": sample.to_dict()["safety_constraints"],
            },
            judge_decision={
                "status": criterion.status.value,
                "method": criterion.evaluation_method.value,
                "judge_record_id": criterion.judge_record_id,
            },
            reason=criterion.reason,
            trace_id=prediction.trace_id,
        ))
    return items


class FormalEvaluationRunner:
    """Canonical Dataset -> one Production execution -> independent scoring.

    Ineligible cases are reported explicitly and are not silently executed or
    included in formal Task Success.  ``score_existing_predictions`` never calls
    the production adapter and never mutates the saved predictions.
    """

    def __init__(
        self,
        *,
        production_adapter: ProductionEvaluationAdapter | None = None,
        judge_runtime: JudgeRuntime | None = None,
        task_success_evaluator: TaskSuccessEvaluator | None = None,
    ) -> None:
        self.production_adapter = production_adapter or ProductionEvaluationAdapter()
        self.judge_runtime = judge_runtime
        self.task_success_evaluator = task_success_evaluator or TaskSuccessEvaluator()
        self._safety_cache: dict[str, Any] = {}

    def _score_prediction(
        self,
        sample: EvaluationSample,
        prediction: PredictionRecord,
        *,
        run_id: str,
    ) -> CaseJudgment:
        resolved_required = tuple(dict.fromkeys((
            *sample.task_success_contract.required_criteria,
            *resolve_conditional_criteria(sample),
        )))
        execution_failed = bool(prediction.execution_error) or prediction.execution_status.upper() not in {"COMPLETED", "SUCCESS", "OK"}
        if execution_failed:
            result = self.task_success_evaluator.evaluate(
                sample.task_success_contract,
                (),
                execution_failed=True,
                resolved_required_criteria=resolved_required,
            )
            return CaseJudgment(
                case_id=sample.sample_id,
                run_id=run_id,
                execution_status=prediction.execution_status,
                criterion_judgments=(),
                task_success_status=result.task_success,
                task_success_bool=result.task_success_bool,
                failed_criteria=result.failed_criteria,
                incomplete_criteria=result.incomplete_criteria,
                rationale=result.reason,
                trace_id=prediction.trace_id,
            )
        criteria = list(evaluate_criteria(sample, prediction, judge=self.judge_runtime))
        safety = evaluate_safety_case(sample, prediction, judge_runtime=self.judge_runtime)
        self._safety_cache[sample.sample_id] = safety
        # When a Phase-5 safety criterion is part of the canonical contract, use
        # the trace-level fail-anywhere result as the authoritative criterion
        # judgment. This replaces only that criterion; TaskSuccess semantics stay
        # the Phase-2 required-criteria conjunction.
        by_criterion = {item.criterion: item for item in criteria}
        for safety_result in safety.criterion_results:
            if safety_result.criterion in resolved_required:
                by_criterion[safety_result.criterion] = safety_result_to_judgment(safety_result, required=True)
        criteria = list(by_criterion.values())
        result = self.task_success_evaluator.evaluate(
            sample.task_success_contract,
            criteria,
            resolved_required_criteria=resolved_required,
        )
        task_status = result.task_success
        task_bool = result.task_success_bool
        failed_criteria = tuple(result.failed_criteria)
        rationale = result.reason
        if safety.task_failing_violation and task_status is not TaskSuccessStatus.EXECUTION_ERROR:
            task_status = TaskSuccessStatus.FAIL
            task_bool = False
            safety_failed = tuple(x.criterion for x in safety.violations)
            failed_criteria = tuple(dict.fromkeys((*failed_criteria, *safety_failed)))
            rationale = f"{rationale}; Phase-5 FAIL ANYWHERE safety violation forces Task Success FAIL"
        return CaseJudgment(
            case_id=sample.sample_id,
            run_id=run_id,
            execution_status=prediction.execution_status,
            criterion_judgments=tuple(criteria),
            task_success_status=task_status,
            task_success_bool=task_bool,
            failed_criteria=failed_criteria,
            incomplete_criteria=result.incomplete_criteria,
            rationale=rationale,
            trace_id=prediction.trace_id,
        )

    def score_prediction(self, sample: EvaluationSample, prediction: PredictionRecord, *, run_id: str) -> CaseJudgment:
        """Public frozen-prediction scoring hook reused by Phase-4 sessions."""
        return self._score_prediction(sample, prediction, run_id=run_id)

    def _ineligible_judgment(self, sample: EvaluationSample, eligibility, *, run_id: str) -> CaseJudgment:
        return CaseJudgment(
            case_id=sample.sample_id,
            run_id=run_id,
            execution_status="NOT_EXECUTED_INELIGIBLE",
            criterion_judgments=(),
            task_success_status=None,
            task_success_bool=None,
            eligibility_status=eligibility.status,
            rationale="; ".join(eligibility.reasons),
            trace_id=None,
        )

    def _metadata(
        self,
        samples: Sequence[EvaluationSample],
        *,
        run_id: str,
        dataset_name: str,
        dataset_version: str,
        production_config: Mapping[str, Any] | None = None,
        model: str | None = None,
        embedding: str | None = None,
        root: str | Path | None = None,
    ) -> dict[str, Any]:
        judge_config = self.judge_runtime.config if self.judge_runtime else None
        judge_run_metadata = asdict(self.judge_runtime.run_metadata()) if self.judge_runtime else None
        return {
            "run_id": run_id,
            "git_commit": _git_commit(root),
            "dataset_name": dataset_name,
            "dataset_version": dataset_version,
            "dataset_hash": canonical_dataset_hash(samples),
            "evaluation_schema_version": "2.0",
            "evaluator_version": FORMAL_EVALUATOR_VERSION,
            "production_config_hash": _hash_json(production_config),
            "model": model,
            "embedding": embedding,
            "judge_model": judge_config.model if judge_config else None,
            "judge_provider": judge_config.provider if judge_config else None,
            "judge_prompt_versions": sorted({record.prompt_version for record in self.judge_runtime.records}) if self.judge_runtime else [],
            "judge_run_metadata": judge_run_metadata,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": {
                "pythonpath": os.getenv("PYTHONPATH"),
                "judge_configured": self.judge_runtime is not None,
            },
            "task_success_denominator_policy": (
                "PASS / (PASS + evaluated FAIL + production EXECUTION_ERROR); "
                "evaluation infrastructure INCOMPLETE excluded and separately reported; ineligible cases excluded and explicitly counted"
            ),
            "phase5_policy_versions": {
                "safety_evaluator_version": SAFETY_EVALUATOR_VERSION,
                "fail_anywhere_policy": SAFETY_POLICY_VERSION,
                "failure_taxonomy_version": FAILURE_TAXONOMY_VERSION,
                "attribution_policy_version": ATTRIBUTION_POLICY_VERSION,
                "governance_policy_version": None,
                "identity_policy_version": None,
                "tool_policy_version": None,
                "memory_governance_version": None,
                "artifact_policy_version": None,
            },
        }

    def run(
        self,
        samples: Sequence[EvaluationSample],
        *,
        output_dir: str | Path | None = None,
        dataset_name: str = "canonical",
        dataset_version: str = "1",
        production_config: Mapping[str, Any] | None = None,
        model: str | None = None,
        embedding: str | None = None,
        root: str | Path | None = None,
    ) -> EvaluationRun:
        materialized = tuple(samples)
        validate_dataset(materialized)  # fail closed before any Production execution
        run_id = f"evalrun:{uuid4().hex}"
        self._safety_cache.clear()
        predictions: list[PredictionRecord] = []
        judgments: list[CaseJudgment] = []
        eligibilities = []
        review_items: list[HumanReviewItem] = []

        for sample in materialized:
            eligibility = evaluate_eligibility(sample)
            eligibilities.append(eligibility)
            if not eligibility.eligible:
                judgments.append(self._ineligible_judgment(sample, eligibility, run_id=run_id))
                continue
            prediction = self.production_adapter.run(sample.to_runtime_input())
            prediction = replace(prediction, run_id=run_id)
            predictions.append(prediction)
            judgment = self._score_prediction(sample, prediction, run_id=run_id)
            judgments.append(judgment)
            review_items.extend(_review_items(sample, prediction, judgment))

        phase3_evidence, phase3_grounding, phase3_recovery = evaluate_phase3(
            materialized, predictions, judgments, judge_runtime=self.judge_runtime
        )
        sample_by_id = {item.sample_id: item for item in materialized}
        prediction_by_id = {item.case_id: item for item in predictions}
        safety_diagnostics = tuple(
            self._safety_cache.get(case_id) or evaluate_safety_case(sample_by_id[case_id], prediction, judge_runtime=self.judge_runtime)
            for case_id, prediction in prediction_by_id.items() if case_id in sample_by_id
        )
        safety_by_id = {item.case_id: item for item in safety_diagnostics}
        evidence_by_id = {item.case_id: item for item in phase3_evidence}
        grounding_by_id = {item.case_id: item for item in phase3_grounding}
        recovery_by_id = {item.case_id: item for item in phase3_recovery}
        failure_attributions = tuple(
            attribute_failure(
                judgment, prediction_by_id.get(judgment.case_id),
                evidence=evidence_by_id.get(judgment.case_id), grounding=grounding_by_id.get(judgment.case_id),
                recovery=recovery_by_id.get(judgment.case_id), safety=safety_by_id.get(judgment.case_id),
            )
            for judgment in judgments if judgment.task_success_status is not None
        )
        metadata = self._metadata(
            materialized,
            run_id=run_id,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            production_config=production_config,
            model=model,
            embedding=embedding,
            root=root,
        )
        metadata["phase3"] = {
            "evidence_diagnostics": len(phase3_evidence),
            "grounding_diagnostics": len(phase3_grounding),
            "recovery_diagnostics": len(phase3_recovery),
            "single_execution_only": True,
        }
        metadata["phase5"] = {
            "safety_diagnostics": len(safety_diagnostics),
            "failure_attributions": len(failure_attributions),
            "fail_anywhere": True,
            "single_execution_only": True,
        }
        run = EvaluationRun(run_id, tuple(predictions), tuple(judgments), tuple(eligibilities), metadata)
        if output_dir is not None:
            write_formal_artifacts(
                output_dir,
                run=run,
                samples=materialized,
                judge_records=tuple(self.judge_runtime.records) if self.judge_runtime else (),
                human_review_items=tuple(review_items),
            )
            write_phase3_artifacts(
                output_dir, samples=materialized, evidence=phase3_evidence,
                grounding=phase3_grounding, recovery=phase3_recovery,
            )
            write_phase5_artifacts(
                output_dir, safety=safety_diagnostics, failures=failure_attributions,
                total_cases=len(materialized), metadata=metadata.get("phase5") or {},
            )
        return run

    def score_existing_predictions(
        self,
        samples: Sequence[EvaluationSample],
        predictions: Sequence[PredictionRecord],
        *,
        output_dir: str | Path | None = None,
        dataset_name: str = "canonical",
        dataset_version: str = "1",
        root: str | Path | None = None,
    ) -> EvaluationRun:
        materialized = tuple(samples)
        validate_dataset(materialized)
        prediction_by_id = {item.case_id: item for item in predictions}
        if len(prediction_by_id) != len(predictions):
            raise ValueError("duplicate case_id in PredictionRecord artifact")
        run_id = next((p.run_id for p in predictions if p.run_id), None) or f"rescore:{uuid4().hex}"
        frozen_predictions = tuple(predictions)
        self._safety_cache.clear()
        judgments: list[CaseJudgment] = []
        eligibilities = []
        review_items: list[HumanReviewItem] = []
        for sample in materialized:
            eligibility = evaluate_eligibility(sample)
            eligibilities.append(eligibility)
            if not eligibility.eligible:
                judgments.append(self._ineligible_judgment(sample, eligibility, run_id=run_id))
                continue
            prediction = prediction_by_id.get(sample.sample_id)
            if prediction is None:
                judgments.append(CaseJudgment(
                    case_id=sample.sample_id,
                    run_id=run_id,
                    execution_status="MISSING_PREDICTION",
                    criterion_judgments=(),
                    task_success_status=TaskSuccessStatus.INCOMPLETE,
                    task_success_bool=None,
                    rationale="eligible case has no saved PredictionRecord; rescoring cannot call Production",
                    trace_id=None,
                    incomplete_criteria=sample.task_success_contract.required_criteria,
                ))
                continue
            judgment = self._score_prediction(sample, prediction, run_id=run_id)
            judgments.append(judgment)
            review_items.extend(_review_items(sample, prediction, judgment))

        phase3_evidence, phase3_grounding, phase3_recovery = evaluate_phase3(
            materialized, frozen_predictions, judgments, judge_runtime=self.judge_runtime
        )
        sample_by_id = {item.sample_id: item for item in materialized}
        safety_diagnostics = tuple(
            self._safety_cache.get(case_id) or evaluate_safety_case(sample_by_id[case_id], prediction, judge_runtime=self.judge_runtime)
            for case_id, prediction in prediction_by_id.items() if case_id in sample_by_id
        )
        safety_by_id = {item.case_id: item for item in safety_diagnostics}
        evidence_by_id = {item.case_id: item for item in phase3_evidence}
        grounding_by_id = {item.case_id: item for item in phase3_grounding}
        recovery_by_id = {item.case_id: item for item in phase3_recovery}
        failure_attributions = tuple(
            attribute_failure(
                judgment, prediction_by_id.get(judgment.case_id), evidence=evidence_by_id.get(judgment.case_id),
                grounding=grounding_by_id.get(judgment.case_id), recovery=recovery_by_id.get(judgment.case_id),
                safety=safety_by_id.get(judgment.case_id),
            )
            for judgment in judgments if judgment.task_success_status is not None
        )
        metadata = self._metadata(materialized, run_id=run_id, dataset_name=dataset_name, dataset_version=dataset_version, root=root)
        metadata["scoring_mode"] = "SCORE_EXISTING_PREDICTIONS_NO_PRODUCTION_EXECUTION"
        metadata["phase3"] = {
            "evidence_diagnostics": len(phase3_evidence),
            "grounding_diagnostics": len(phase3_grounding),
            "recovery_diagnostics": len(phase3_recovery),
            "single_execution_only": True,
        }
        metadata["phase5"] = {
            "safety_diagnostics": len(safety_diagnostics),
            "failure_attributions": len(failure_attributions),
            "fail_anywhere": True,
            "single_execution_only": True,
            "scoring_mode": "FROZEN_PREDICTION_RESCORING",
        }
        run = EvaluationRun(run_id, frozen_predictions, tuple(judgments), tuple(eligibilities), metadata)
        if output_dir is not None:
            write_formal_artifacts(
                output_dir,
                run=run,
                samples=materialized,
                judge_records=tuple(self.judge_runtime.records) if self.judge_runtime else (),
                human_review_items=tuple(review_items),
            )
            write_phase3_artifacts(
                output_dir, samples=materialized, evidence=phase3_evidence,
                grounding=phase3_grounding, recovery=phase3_recovery,
            )
            write_phase5_artifacts(
                output_dir, safety=safety_diagnostics, failures=failure_attributions,
                total_cases=len(materialized), metadata=metadata.get("phase5") or {},
            )
        return run


def read_prediction_jsonl(path: str | Path) -> tuple[PredictionRecord, ...]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(PredictionRecord.from_state(json.loads(line)))
    return tuple(rows)


# ---------------------------------------------------------------------------
# Phase 4 multi-turn Context / Memory quality-cost runner
# ---------------------------------------------------------------------------

from eval_platform.context_memory import (
    CanonicalEvaluationSession, ContextStrategyExperimentRun, SessionStrategyResult,
    ContextEvaluationStrategy, ContextStrategyConfig, aggregate_context_strategy,
    check_strategy_fairness, evaluate_artifacts, evaluate_context_turn,
    evaluate_memory_contamination, evaluate_session_success, evaluate_working_memory,
    paired_quality_cost, session_dataset_inventory, strategy_config, strategy_runtime_context,
    validate_sessions, write_phase4_artifacts, turn_to_sample,
)


class ContextStrategyExperimentRunner:
    """Run explicit (session, strategy) streams with one Production invocation per turn."""

    def __init__(self, *, judge_runtime: JudgeRuntime | None = None, adapter_factory=None) -> None:
        self.judge_runtime = judge_runtime
        self.adapter_factory = adapter_factory

    def _adapter(self, config: ContextStrategyConfig) -> ProductionEvaluationAdapter:
        if self.adapter_factory is not None:
            return self.adapter_factory(config)
        return ProductionEvaluationAdapter.for_context_strategy(
            agentic_recovery_enabled=True, use_checkpointer=True
        )

    def run(
        self,
        sessions: Sequence[CanonicalEvaluationSession],
        *,
        strategies: Sequence[ContextEvaluationStrategy | str],
        output_dir: str | Path | None = None,
        max_tokens: int = 4096,
        window_turns: int = 3,
        common_production_config: Mapping[str, Any] | None = None,
        root: str | Path | None = None,
    ) -> ContextStrategyExperimentRun:
        materialized = tuple(sessions)
        eligibilities = validate_sessions(materialized)
        configs = tuple(strategy_config(x, max_tokens=max_tokens, window_turns=window_turns) for x in strategies)
        if len({cfg.strategy for cfg in configs}) != len(configs):
            raise ValueError("duplicate context strategy")
        common = dict(common_production_config or {})
        fairness_rows = [{**common, **strategy_runtime_context(cfg)} for cfg in configs]
        fair, fairness_errors = check_strategy_fairness(fairness_rows)
        if not fair:
            raise ValueError("EXPERIMENT INVALID: " + "; ".join(fairness_errors))
        run_id = f"context-exp:{uuid4().hex}"
        results: list[SessionStrategyResult] = []
        eligibility_by_id = {x.session_id: x for x in eligibilities}
        for cfg in configs:
            adapter = self._adapter(cfg)
            scorer = FormalEvaluationRunner(production_adapter=adapter, judge_runtime=self.judge_runtime)
            for session in materialized:
                if not eligibility_by_id[session.session_id].eligible:
                    continue
                predictions = []
                judgments = []
                context_diags = []
                contamination = []
                artifact_diags = []
                wm_diags = []
                grounding_diags = []
                execution_errors = 0
                for turn in session.turns:
                    sample = turn_to_sample(session, turn, strategy=cfg)
                    prediction = replace(adapter.run(sample.to_runtime_input()), run_id=run_id)
                    predictions.append(prediction)
                    judgment = scorer.score_prediction(sample, prediction, run_id=run_id)
                    judgments.append(judgment)
                    _evidence, grounding, _recovery = evaluate_phase3(
                        (sample,), (prediction,), (judgment,), judge_runtime=self.judge_runtime
                    )
                    grounding_diags.extend(grounding)
                    if prediction.execution_error:
                        execution_errors += 1
                    diag = evaluate_context_turn(session, turn, prediction, strategy=cfg.strategy)
                    context_diags.append(diag)
                    wm_diags.append({"turn_id": turn.turn_id, **evaluate_working_memory(turn, diag)})
                    contamination.extend(evaluate_memory_contamination(session, turn, diag))
                    artifact_diags.extend(evaluate_artifacts(session, turn, diag))
                session_status = evaluate_session_success(session, judgments, contamination)
                results.append(SessionStrategyResult(
                    session_id=session.session_id, strategy=cfg.strategy, predictions=tuple(predictions),
                    judgments=tuple(judgments), context_diagnostics=tuple(context_diags),
                    contamination_events=tuple(contamination), artifact_diagnostics=tuple(artifact_diags),
                    session_success_status=session_status, execution_errors=execution_errors,
                    metadata={
                        "strategy_config": cfg.to_state(), "strategy_config_hash": cfg.fingerprint,
                        "memory_dependent_turns": sum(1 for turn in session.turns if turn.memory_expectations.memory_dependent),
                        "working_memory_diagnostics": wm_diags,
                        "grounding": {
                            "numerator": sum(x.grounded_claim_numerator for x in grounding_diags if x.complete),
                            "denominator": sum(x.grounded_claim_denominator for x in grounding_diags if x.complete),
                            "complete_cases": sum(1 for x in grounding_diags if x.complete),
                            "incomplete_cases": sum(1 for x in grounding_diags if not x.complete),
                        },
                    },
                ))
        metadata = {
            "dataset": session_dataset_inventory(materialized),
            "strategy_fairness": {"valid": fair, "errors": list(fairness_errors)},
            "single_execution_per_session_strategy_turn": True,
            "agentic_recovery_fixed": True,
            "git_commit": _git_commit(root),
            "common_production_config_hash": _hash_json(common),
        }
        experiment = ContextStrategyExperimentRun(run_id, tuple(results), eligibilities, configs, metadata)
        if output_dir is not None:
            write_phase4_artifacts(output_dir, sessions=materialized, results=tuple(results))
            Path(output_dir, "context_experiment_run.json").write_text(
                json.dumps(experiment.to_state(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
            )
        return experiment
