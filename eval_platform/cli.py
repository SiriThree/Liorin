"""Unified Phase-2 Canonical Evaluation CLI.

Examples:
  python -m eval_platform.cli validate --dataset path.json
  python -m eval_platform.cli run --dataset path.json --split VALIDATION --output artifacts/eval/run-1
  python -m eval_platform.cli score-existing-predictions --dataset path.json --predictions predictions.jsonl --output artifacts/eval/rescore

The CLI never upgrades historical blind inputs into TEST and never uses legacy
``macro_objective_score`` as formal Task Success.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Sequence

from eval_platform.contracts import DatasetSplit, TaskCategory
from agents.feature_flags import AgentFeatureConfig
from eval_platform.ablation import ControlledAblationRunner, ablation_config_from_state, removal_config, AblationFeature
from eval_platform.readiness import build_evaluation_readiness
from eval_platform.regression import BaselineRegistry, GateStatus, RegressionRule, RunValidity, ThresholdType, evaluate_rule, write_gate_artifacts
from eval_platform.final_report import build_final_report, write_final_report
from eval_platform.dataset import EvaluationSample, read_canonical_dataset
from eval_platform.judge import JudgeConfig, JudgeRuntime
from eval_platform.production_adapter import ProductionEvaluationAdapter
from context_engine.strategy import ContextEvaluationStrategy
from eval_platform.context_memory import read_canonical_sessions
from eval_platform.runner import ContextStrategyExperimentRunner, FormalEvaluationRunner, read_prediction_jsonl
from eval_platform.validation import validate_dataset


def _load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("evaluation config must be a JSON object")
    return raw


def _judge_runtime(config: dict[str, Any]) -> JudgeRuntime | None:
    raw = config.get("judge")
    if not raw or raw.get("enabled") is False:
        return None
    model = raw.get("model")
    model_env = raw.get("model_env")
    if not model and model_env:
        model = os.getenv(str(model_env))
    missing = [name for name in ("judge_name", "provider") if not raw.get(name)]
    if not model:
        missing.append("model/model_env")
    if missing:
        raise ValueError(f"judge config missing fields: {missing}")
    return JudgeRuntime(JudgeConfig(
        judge_name=str(raw["judge_name"]),
        provider=str(raw["provider"]),
        model=str(model),
        temperature=float(raw.get("temperature", 0.0)),
        max_tokens=int(raw.get("max_tokens", 1200)),
        timeout=float(raw.get("timeout", 30.0)),
        max_retries=int(raw.get("max_retries", 2)),
        prompt_version=str(raw.get("prompt_version", "answer_correctness_v1")),
        schema_version=str(raw.get("schema_version", "1.0")),
    ))


def _filter(samples: Sequence[EvaluationSample], args: argparse.Namespace) -> tuple[EvaluationSample, ...]:
    rows = list(samples)
    if getattr(args, "split", None):
        split = DatasetSplit(str(args.split).upper())
        rows = [s for s in rows if s.split is split]
    if getattr(args, "category", None):
        category = TaskCategory(str(args.category).upper())
        rows = [s for s in rows if s.category is category]
    if getattr(args, "case_id", None):
        ids = set(args.case_id)
        rows = [s for s in rows if s.sample_id in ids]
    if getattr(args, "limit", None) is not None:
        rows = rows[: int(args.limit)]
    if not rows:
        raise ValueError("no canonical cases selected")
    return tuple(rows)


def _add_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--split", choices=[x.value for x in DatasetSplit])
    parser.add_argument("--category", choices=[x.value for x in TaskCategory])
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--config")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="liorin-eval", description="Liorin Canonical Evaluation CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate")
    _add_selection(validate)

    run = sub.add_parser("run")
    _add_selection(run)
    run.add_argument("--output", required=True)

    score = sub.add_parser("score-existing-predictions")
    _add_selection(score)
    score.add_argument("--predictions", required=True)
    score.add_argument("--output", required=True)

    judge = sub.add_parser("judge")
    _add_selection(judge)
    judge.add_argument("--predictions", required=True)
    judge.add_argument("--output", required=True)

    report = sub.add_parser("report")
    report.add_argument("--output", required=True, help="existing evaluation artifact directory")

    safety = sub.add_parser("safety")
    _add_selection(safety)
    safety.add_argument("--predictions", required=True)
    safety.add_argument("--attack-type")
    safety.add_argument("--output", required=True)

    attribute = sub.add_parser("attribute-failures")
    _add_selection(attribute)
    attribute.add_argument("--predictions", required=True)
    attribute.add_argument("--failure-domain")
    attribute.add_argument("--failure-code")
    attribute.add_argument("--primary-only", action="store_true")
    attribute.add_argument("--output", required=True)

    experiment = sub.add_parser("experiment")
    experiment_sub = experiment.add_subparsers(dest="experiment_type", required=True)
    context = experiment_sub.add_parser("context")
    context.add_argument("--dataset", required=True)
    context.add_argument("--strategies", required=True, help="comma-separated ContextEvaluationStrategy values")
    context.add_argument("--strategy", choices=[x.value for x in ContextEvaluationStrategy])
    context.add_argument("--session-id", action="append")
    context.add_argument("--split", choices=[x.value for x in DatasetSplit])
    context.add_argument("--category", choices=[x.value for x in TaskCategory])
    context.add_argument("--limit", type=int)
    context.add_argument("--max-tokens", type=int, default=4096)
    context.add_argument("--window-turns", type=int, default=3)
    context.add_argument("--config")
    context.add_argument("--output", required=True)

    recovery = experiment_sub.add_parser("recovery")
    _add_selection(recovery)
    recovery.add_argument("--output", required=True)

    ablation = sub.add_parser("ablation")
    _add_selection(ablation)
    ablation.add_argument("--ablation-config", required=True)
    ablation.add_argument("--output", required=True)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--root", default=".")
    doctor.add_argument("--live", action="store_true", help="perform real provider/Milvus connectivity probes; never falls back to mocks")
    doctor.add_argument("--output")

    gate = sub.add_parser("gate")
    gate.add_argument("--current", required=True, help="JSON with metrics/run metadata")
    gate.add_argument("--registry", default="artifacts/evaluation/baseline_registry.json")
    gate.add_argument("--baseline-name", default="formal_validation")
    gate.add_argument("--output", required=True)

    promote = sub.add_parser("promote-baseline")
    promote.add_argument("--run", required=True, help="validated run descriptor JSON")
    promote.add_argument("--registry", default="artifacts/evaluation/baseline_registry.json")
    promote.add_argument("--baseline-name", default="formal_validation")

    final_report = sub.add_parser("final-report")
    final_report.add_argument("--root", default=".")
    final_report.add_argument("--output", required=True)

    dataset_audit = sub.add_parser("dataset-audit", help="Phase D0 source/fact/relation/coverage audit; never runs Production")
    dataset_audit.add_argument("--root", default=".")
    dataset_audit.add_argument("--output", default="artifacts/evaluation/dataset-expansion-d0")

    dataset_expand_private = sub.add_parser("dataset-expand-private", help="Phase D1 source-grounded PRIVATE_BUSINESS_QUERY candidate construction; never runs Production")
    dataset_expand_private.add_argument("--root", default=".")
    dataset_expand_private.add_argument("--d0", default="artifacts/evaluation/dataset-expansion-d0")
    dataset_expand_private.add_argument("--output", default="artifacts/evaluation/dataset-expansion-d1")

    dataset_prepare_private = sub.add_parser("dataset-prepare-private-annotation", help="Phase D2 deterministic Private Business Gold Draft + annotation packet freeze; never runs Production/Judge")
    dataset_prepare_private.add_argument("--root", default=".")
    dataset_prepare_private.add_argument("--d1", default="artifacts/evaluation/dataset-expansion-d1")
    dataset_prepare_private.add_argument("--output", default="artifacts/evaluation/dataset-expansion-d2")

    dataset_annotate_private = sub.add_parser("dataset-annotate-private", help="Phase D3/D3-R dual independent Gold Draft annotation; never runs Production Agent or adjudication")
    dataset_annotate_private.add_argument("--root", default=".")
    dataset_annotate_private.add_argument("--d2", default="artifacts/evaluation/dataset-expansion-d2")
    dataset_annotate_private.add_argument("--d3", default="artifacts/evaluation/dataset-expansion-d3", help="historical blocked D3 artifact directory used by D3-R integrity checks")
    dataset_annotate_private.add_argument("--config", required=True)
    dataset_annotate_private.add_argument("--output", default="artifacts/evaluation/dataset-expansion-d3")
    dataset_annotate_private.add_argument("--runtime-recovery", action="store_true", help="Phase D3-R: readiness -> provider smoke -> 5-8 packet pilot -> real formal A/B run")
    dataset_annotate_private.add_argument("--check-only", action="store_true", help="D3-R readiness only; makes zero provider calls")
    dataset_annotate_private.add_argument("--pilot-count", type=int, default=6, help="D3-R infrastructure pilot size; must be 5-8")
    dataset_expand_mixed = sub.add_parser("dataset-expand-mixed", help="Phase E0 source-grounded MIXED_KNOWLEDGE_STRUCTURED candidate construction; never runs Production/Annotators")
    dataset_expand_mixed.add_argument("--root", default=".")
    dataset_expand_mixed.add_argument("--d0", default="artifacts/evaluation/dataset-expansion-d0")
    dataset_expand_mixed.add_argument("--output", default="artifacts/evaluation/dataset-expansion-e0-mixed")

    dataset_prepare_mixed = sub.add_parser("dataset-prepare-mixed-annotation", help="Phase E1 deterministic Mixed Gold preparation + annotation packet freeze; never runs Annotators/Production")
    dataset_prepare_mixed.add_argument("--root", default=".")
    dataset_prepare_mixed.add_argument("--e0", default="artifacts/evaluation/dataset-expansion-e0-mixed")
    dataset_prepare_mixed.add_argument("--output", default="artifacts/evaluation/dataset-expansion-e1-mixed-gold")

    dataset_repair_mixed = sub.add_parser("dataset-repair-mixed-manual-scope", help="Phase E1-R source-preserving Manual-routing query scope repair + Mixed Gold re-freeze; never runs Annotators/Production")
    dataset_repair_mixed.add_argument("--root", default=".")
    dataset_repair_mixed.add_argument("--e1", default="artifacts/evaluation/dataset-expansion-e1-mixed-gold")
    dataset_repair_mixed.add_argument("--output", default="artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair")

    dataset_expand_troubleshooting = sub.add_parser("dataset-expand-troubleshooting", help="Phase F0 source-grounded Troubleshooting/Clarification/Recovery-oriented candidate construction; never runs Production/Annotators")
    dataset_expand_troubleshooting.add_argument("--root", default=".")
    dataset_expand_troubleshooting.add_argument("--d0", default="artifacts/evaluation/dataset-expansion-d0")
    dataset_expand_troubleshooting.add_argument("--output", default="artifacts/evaluation/dataset-expansion-f0-troubleshooting")

    dataset_audit_knowledge = sub.add_parser("dataset-audit-knowledge-source", help="Phase G0.1 Knowledge source-space audit + KnowledgeSourceUnit construction; generates no queries/candidates")
    dataset_audit_knowledge.add_argument("--root", default=".")
    dataset_audit_knowledge.add_argument("--d0", default="artifacts/evaluation/dataset-expansion-d0")
    dataset_audit_knowledge.add_argument("--output", default="artifacts/evaluation/dataset-expansion-g0-1-knowledge-source")

    dataset_plan_knowledge = sub.add_parser("dataset-plan-knowledge", help="Phase G0.2 balanced KnowledgeTaskPlan selection; generates no queries/candidates")
    dataset_plan_knowledge.add_argument("--root", default=".")
    dataset_plan_knowledge.add_argument("--g0-1", dest="g0_1", default="artifacts/evaluation/dataset-expansion-g0-1-knowledge-source")
    dataset_plan_knowledge.add_argument("--output", default="artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning")

    dataset_render_knowledge = sub.add_parser("dataset-render-knowledge", help="Phase G0.3 controlled Knowledge query rendering + candidate validation; never runs Production/Annotation")
    dataset_render_knowledge.add_argument("--root", default=".")
    dataset_render_knowledge.add_argument("--g0-2", dest="g0_2", default="artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning")
    dataset_render_knowledge.add_argument("--g0-1", dest="g0_1", default="artifacts/evaluation/dataset-expansion-g0-1-knowledge-source")
    dataset_render_knowledge.add_argument("--output", default="artifacts/evaluation/dataset-expansion-g0-3-knowledge-rendering")

    dataset_prepare_knowledge = sub.add_parser("dataset-prepare-knowledge-annotation", help="Phase G0.4 Knowledge Gold preparation + annotation packet freeze; never runs Production/Annotation")
    dataset_prepare_knowledge.add_argument("--root", default=".")
    dataset_prepare_knowledge.add_argument("--g0-3", dest="g0_3", default="artifacts/evaluation/dataset-expansion-g0-3-knowledge-rendering")
    dataset_prepare_knowledge.add_argument("--g0-2", dest="g0_2", default="artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning")
    dataset_prepare_knowledge.add_argument("--g0-1", dest="g0_1", default="artifacts/evaluation/dataset-expansion-g0-1-knowledge-source")
    dataset_prepare_knowledge.add_argument("--output", default="artifacts/evaluation/dataset-expansion-g0-4-knowledge-gold")

    dataset_expand_safety = sub.add_parser("dataset-expand-safety", help="Phase H0 Safety/Governance surface revalidation + static candidate expansion; never runs Production/Annotation")
    dataset_expand_safety.add_argument("--root", default=".")
    dataset_expand_safety.add_argument("--output", default="artifacts/evaluation/dataset-expansion-h0-safety")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "dataset-expand-safety":
        from evals.benchmark.expansion import run_safety_expansion
        payload = run_safety_expansion(args.root, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "dataset-prepare-knowledge-annotation":
        from evals.benchmark.expansion import run_knowledge_gold_preparation
        payload = run_knowledge_gold_preparation(args.root, args.g0_3, args.g0_2, args.g0_1, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "dataset-render-knowledge":
        from evals.benchmark.expansion import run_knowledge_query_rendering
        payload = run_knowledge_query_rendering(args.root, args.g0_2, args.g0_1, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "dataset-audit-knowledge-source":
        from evals.benchmark.expansion import run_knowledge_source_audit
        payload = run_knowledge_source_audit(args.root, args.d0, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    elif args.command == "dataset-plan-knowledge":
        from evals.benchmark.expansion import run_knowledge_task_planning
        payload = run_knowledge_task_planning(args.root, args.g0_1, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "dataset-expand-troubleshooting":
        from evals.benchmark.expansion import run_troubleshooting_expansion
        payload = run_troubleshooting_expansion(args.root, args.d0, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "dataset-repair-mixed-manual-scope":
        from evals.benchmark.expansion import run_manual_scope_repair
        payload = run_manual_scope_repair(args.root, args.e1, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "dataset-prepare-mixed-annotation":
        from evals.benchmark.expansion import run_mixed_gold_preparation
        payload = run_mixed_gold_preparation(args.root, args.e0, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "dataset-expand-mixed":
        from evals.benchmark.expansion import run_mixed_expansion
        payload = run_mixed_expansion(args.root, args.d0, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "dataset-audit":
        from evals.benchmark.expansion import run_dataset_expansion_audit
        payload = run_dataset_expansion_audit(args.root, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "dataset-expand-private":
        from evals.benchmark.expansion import run_private_business_expansion
        payload = run_private_business_expansion(args.root, args.d0, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "dataset-prepare-private-annotation":
        from evals.benchmark.expansion import run_private_gold_preparation
        payload = run_private_gold_preparation(args.root, args.d1, args.output)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "dataset-annotate-private":
        if args.check_only and not args.runtime_recovery:
            raise SystemExit("--check-only requires --runtime-recovery")
        if args.runtime_recovery:
            from evals.benchmark.expansion import run_d3r_runtime_recovery
            payload = run_d3r_runtime_recovery(
                args.root, args.d2, args.d3, args.output, args.config,
                check_only=bool(args.check_only), pilot_count=int(args.pilot_count),
            )
        else:
            from evals.benchmark.expansion import run_private_dual_annotation
            payload = run_private_dual_annotation(args.root, args.d2, args.output, args.config)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "doctor":
        readiness = build_evaluation_readiness(args.root, live_checks=bool(args.live))
        payload = readiness.to_state()
        if args.output:
            Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "gate":
        current = json.loads(Path(args.current).read_text(encoding="utf-8"))
        registry = BaselineRegistry(args.registry)
        baseline = registry.get(args.baseline_name)
        metrics = dict(current.get("metrics") or {})
        results = []
        # Zero tolerance can operate without a promoted quality baseline.
        results.append(evaluate_rule(RegressionRule("zero_tolerance_safety", "critical_safety_violations", ThresholdType.ZERO_TOLERANCE, 0.0), current=metrics.get("critical_safety_violations"), baseline=0.0, run_id=current.get("run_id")))
        for metric in ("task_success", "grounded_claim_rate", "first_pass_failure_recovery_rate"):
            base_value = baseline.metrics.get(metric) if baseline else None
            # No tolerance is invented here. Until a real baseline + explicit tolerance exists this gate is BLOCKED.
            results.append(evaluate_rule(RegressionRule(f"quality_{metric}", metric, ThresholdType.MAX_REGRESSION_PP, None), current=metrics.get(metric), baseline=base_value, run_id=current.get("run_id")))
        write_gate_artifacts(args.output, results, metadata={"baseline_name": args.baseline_name, "baseline_established": baseline is not None})
        print(json.dumps({"results": [x.to_state() for x in results]}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "promote-baseline":
        raw = json.loads(Path(args.run).read_text(encoding="utf-8"))
        registry = BaselineRegistry(args.registry)
        record = registry.promote(
            baseline_name=args.baseline_name, run_validity=RunValidity(str(raw.get("run_validity") or "PARTIAL")),
            dataset_formal_eligible=bool(raw.get("dataset_formal_eligible")),
            critical_safety_violations=int(raw.get("critical_safety_violations", 0) or 0),
            required_metrics=dict(raw.get("metrics") or {}), dataset_hash=raw.get("dataset_hash"),
            config_hash=raw.get("config_hash"), run_id=raw.get("run_id"), git_commit=raw.get("git_commit"),
        )
        print(json.dumps(record.to_state(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "final-report":
        readiness = build_evaluation_readiness(args.root)
        report = build_final_report(readiness=readiness, metadata={"generated_by": "eval_platform.cli final-report"})
        paths = write_final_report(args.output, report)
        print(json.dumps({k: str(v) for k, v in paths.items()}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "report":
        summary = Path(args.output) / "summary.json"
        if not summary.exists():
            raise FileNotFoundError(summary)
        print(summary.read_text(encoding="utf-8"))
        return 0

    if args.command == "experiment" and args.experiment_type == "recovery":
        config = _load_config(args.config)
        samples = _filter(read_canonical_dataset(args.dataset), args)
        cfg = removal_config(AblationFeature.AGENTIC_RECOVERY)
        result = ControlledAblationRunner(judge_runtime=_judge_runtime(config)).run(samples, cfg, output_dir=args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "ablation":
        config = _load_config(args.config)
        samples = _filter(read_canonical_dataset(args.dataset), args)
        raw = json.loads(Path(args.ablation_config).read_text(encoding="utf-8"))
        result = ControlledAblationRunner(judge_runtime=_judge_runtime(config)).run(samples, ablation_config_from_state(raw), output_dir=args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "experiment" and args.experiment_type == "context":
        config = _load_config(args.config)
        sessions = list(read_canonical_sessions(args.dataset))
        if args.split:
            sessions = [s for s in sessions if s.split is DatasetSplit(str(args.split).upper())]
        if args.category:
            sessions = [s for s in sessions if s.category is TaskCategory(str(args.category).upper())]
        if args.session_id:
            wanted = set(args.session_id)
            sessions = [s for s in sessions if s.session_id in wanted]
        if args.limit is not None:
            sessions = sessions[:args.limit]
        if not sessions:
            raise ValueError("no canonical multi-turn sessions selected")
        raw_strategies = [args.strategy] if args.strategy else [x.strip() for x in args.strategies.split(",") if x.strip()]
        strategies = [ContextEvaluationStrategy(str(x).upper()) for x in raw_strategies]
        runner = ContextStrategyExperimentRunner(judge_runtime=_judge_runtime(config))
        result = runner.run(
            sessions, strategies=strategies, output_dir=args.output, max_tokens=args.max_tokens,
            window_turns=args.window_turns, common_production_config=config.get("production") or {}, root=Path.cwd(),
        )
        print(json.dumps(result.to_state(), ensure_ascii=False, indent=2))
        return 0

    config = _load_config(args.config)
    samples = _filter(read_canonical_dataset(args.dataset), args)
    if args.command == "safety":
        if not args.category:
            samples = tuple(s for s in samples if s.category is TaskCategory.SAFETY_GOVERNANCE)
        if args.attack_type:
            attack = str(args.attack_type).upper()
            samples = tuple(s for s in samples if attack in s.subcategory.upper() or any(attack in tag.upper() for tag in s.tags))
        if not samples:
            raise ValueError("no safety cases selected")
    if args.command == "validate":
        result = validate_dataset(samples)
        print(json.dumps({"valid": result.valid, "case_count": result.case_count, "errors": list(result.errors)}, ensure_ascii=False, indent=2))
        return 0

    judge_runtime = _judge_runtime(config)
    production_config = config.get("production") or {}
    raw_features = production_config.get("features")
    if isinstance(raw_features, dict):
        feature_config = AgentFeatureConfig.from_mapping(raw_features)
        production_adapter = ProductionEvaluationAdapter.for_feature_config(feature_config)
    else:
        recovery_enabled = bool(production_config.get("agentic_recovery_enabled", True))
        production_adapter = ProductionEvaluationAdapter.for_agentic_recovery(enabled=recovery_enabled)
    runner = FormalEvaluationRunner(
        production_adapter=production_adapter,
        judge_runtime=judge_runtime,
    )
    dataset_name = str(config.get("dataset_name") or Path(args.dataset).stem)
    dataset_version = str(config.get("dataset_version") or "1")
    if args.command == "run":
        run = runner.run(
            samples,
            output_dir=args.output,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            production_config=production_config,
            model=config.get("model"),
            embedding=config.get("embedding"),
            root=Path.cwd(),
        )
    else:
        predictions = read_prediction_jsonl(args.predictions)
        if args.command == "judge" and judge_runtime is None:
            raise ValueError("judge command requires an enabled judge config")
        run = runner.score_existing_predictions(
            samples,
            predictions,
            output_dir=args.output,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            root=Path.cwd(),
        )
        if args.command == "safety":
            summary_path = Path(args.output) / "safety_summary.json"
            print(summary_path.read_text(encoding="utf-8"))
            return 0
        if args.command == "attribute-failures":
            source = Path(args.output) / "failure_attribution.jsonl"
            rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
            if args.failure_domain:
                target = str(args.failure_domain).upper()
                rows = [row for row in rows if (row.get("primary_failure") or {}).get("domain") == target]
            if args.failure_code:
                target = str(args.failure_code).upper()
                if args.primary_only:
                    rows = [row for row in rows if (row.get("primary_failure") or {}).get("failure_code") == target]
                else:
                    rows = [row for row in rows if (row.get("primary_failure") or {}).get("failure_code") == target or any(x.get("failure_code") == target for x in row.get("secondary_failures") or [])]
            filtered = Path(args.output) / "failure_attribution.filtered.jsonl"
            filtered.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
            print(json.dumps({"count": len(rows), "artifact": str(filtered)}, ensure_ascii=False, indent=2))
            return 0
    print(json.dumps(run.to_state(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
