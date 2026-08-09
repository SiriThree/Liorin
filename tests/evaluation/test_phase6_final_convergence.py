from __future__ import annotations

from pathlib import Path

from eval_platform.cli import build_parser
from eval_platform.final_report import MetricProvenanceStatus, assess_resume_metric, build_final_report, write_resume_safe_metrics
from eval_platform.readiness import EvaluationReadiness, EvaluationSystemStatus, ReadinessItem, ReadinessStatus
from eval_platform.regression import RunValidity


def _blocked_readiness():
    return EvaluationReadiness((
        ReadinessItem("production_runtime",ReadinessStatus.BLOCKED,"missing langchain"),
        ReadinessItem("judge_provider",ReadinessStatus.BLOCKED,"missing provider"),
        ReadinessItem("validation_split",ReadinessStatus.READY,"5 cases",{"case_count":5}),
        ReadinessItem("trusted_test_split",ReadinessStatus.NOT_READY,"none"),
        ReadinessItem("multi_turn_subset",ReadinessStatus.NOT_READY,"0"),
        ReadinessItem("safety_subset",ReadinessStatus.READY,"3"),
        ReadinessItem("recovery_subset",ReadinessStatus.NOT_READY,"review debt"),
    ),EvaluationSystemStatus.PRODUCTION_BLOCKED)


def test_final_report_shows_not_run_instead_of_hiding_blocked_metrics():
    report=build_final_report(readiness=_blocked_readiness())
    assert report["formal_validation"] == "NOT RUN"
    assert report["core_metrics"]["end_to_end_task_success"] == "NOT RUN"
    assert report["dataset_scope"]["trusted_test"] is False


def test_fixture_stub_legacy_and_blocked_metrics_are_never_resume_safe(tmp_path):
    metadata={"dataset_name":"validation","dataset_hash":"d","run_id":"r","production_config_hash":"c","dataset_version":"1"}
    fixture=assess_resume_metric(metric_name="Task Success",value=.9,numerator=9,denominator=10,metadata=metadata,run_validity=RunValidity.VALID,formal_eligible=True,real_production=True,real_judge_when_required=True,is_fixture=True)
    legacy=assess_resume_metric(metric_name="legacy -95.2% token reduction",value=.952,numerator=None,denominator=1,metadata=metadata,run_validity=RunValidity.VALID,formal_eligible=True,real_production=True,real_judge_when_required=True,is_legacy=True)
    blocked=assess_resume_metric(metric_name="Grounded Claim Rate",value=None,numerator=None,denominator=None,metadata=metadata,run_validity=RunValidity.DEPENDENCY_BLOCKED,formal_eligible=True,real_production=False,real_judge_when_required=False,judge_required=True)
    assert fixture.status is MetricProvenanceStatus.NOT_SAFE_TO_USE
    assert legacy.status is MetricProvenanceStatus.LEGACY_DO_NOT_USE
    assert blocked.status is MetricProvenanceStatus.NOT_SAFE_TO_USE
    path=write_resume_safe_metrics(tmp_path/"RESUME_SAFE_METRICS.md",(fixture,legacy,blocked),engineering={"tests":"fixture"},legacy={"legacy_token_reduction":"95.2%"})
    text=path.read_text(encoding="utf-8")
    assert "**NONE**" in text
    assert "DO_NOT_USE_AS_FORMAL_QUALITY_METRIC" in text


def test_unified_cli_contains_phase6_commands():
    parser=build_parser()
    text=parser.format_help()
    for name in ("doctor","ablation","gate","promote-baseline","final-report"):
        assert name in text


def test_ci_no_longer_runs_legacy_fixed_threshold_gate_and_has_three_layers():
    root=Path(__file__).resolve().parents[2]
    pr=(root/".github/workflows/eval-regression.yml").read_text(encoding="utf-8")
    scheduled=(root/".github/workflows/formal-evaluation.yml").read_text(encoding="utf-8")
    release=(root/".github/workflows/release-evaluation.yml").read_text(encoding="utf-8")
    assert "run_ci_eval.py --threshold 0.8" not in pr
    assert "tests/evaluation" in pr
    assert "schedule:" in scheduled
    assert "workflow_dispatch:" in release


def test_legacy_eval_dependencies_are_optional_not_production_dependencies():
    root=Path(__file__).resolve().parents[2]
    pyproject=(root/"pyproject.toml").read_text(encoding="utf-8")
    main=pyproject.split("[project.optional-dependencies]")[0]
    assert "agentevals" not in main and "openevals" not in main
    assert "legacy-evaluation" in pyproject
