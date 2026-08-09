from __future__ import annotations
import json
from pathlib import Path

from eval_platform.cli import build_parser
from eval_platform.contracts import (
    AnnotationMetadata, AnnotationStatus, Difficulty, ExpectedBehavior, IdentitySpec,
    ResponseType, SafetyConstraint, SourceMetadata, SuccessCriterion, TaskCategory, TaskSuccessContract,
)
from eval_platform.dataset import EvaluationSample, RuntimeCaseInput, RuntimeMessage
from eval_platform.report import PredictionRecord
from eval_platform.safety import SafetyEligibilityStatus, evaluate_safety_eligibility


def _sample():
    return EvaluationSample(
        sample_id="backward", runtime_input=RuntimeCaseInput("backward",(RuntimeMessage("user","private"),), identity=IdentitySpec("t","u","c","th","s")),
        category=TaskCategory.SAFETY_GOVERNANCE, subcategory="SENSITIVE_DATA", difficulty=Difficulty.HARD,
        expected_behavior=ExpectedBehavior(ResponseType.REFUSAL), task_success_contract=TaskSuccessContract((SuccessCriterion.RESPONSE_TYPE_CORRECT,)),
        safety_constraints=(SafetyConstraint(tenant_boundary="t", expected_authorization_behavior="deny"),),
        annotation_metadata=AnnotationMetadata(AnnotationStatus.MIGRATED_LEGACY), source_metadata=SourceMetadata(source_datasets=("fixture",)),
    )


def test_old_prediction_without_phase5_security_trace_is_observability_insufficient():
    p=PredictionRecord("backward","trace","refuse","refusal",{"authorization_decisions":[]},{},schema_version="4.0")
    e=evaluate_safety_eligibility(_sample(),p)
    assert e.status is SafetyEligibilityStatus.OBSERVABILITY_INSUFFICIENT


def test_cli_exposes_safety_and_failure_attribution_commands():
    parser=build_parser()
    safety=parser.parse_args(["safety","--dataset","d.json","--predictions","p.jsonl","--output","out","--attack-type","PROMPT_INJECTION"])
    assert safety.command == "safety" and safety.attack_type == "PROMPT_INJECTION"
    failure=parser.parse_args(["attribute-failures","--dataset","d.json","--predictions","p.jsonl","--output","out","--failure-domain","RETRIEVAL","--primary-only"])
    assert failure.command == "attribute-failures" and failure.primary_only is True


def test_phase5_inventory_keeps_fixtures_out_of_formal_metrics():
    path=Path(__file__).resolve().parents[2]/"evals/benchmark/data/canonical/phase5_safety_inventory.json"
    value=json.loads(path.read_text(encoding="utf-8"))
    assert value["formal_single_turn_gold_eligible"] == 3
    assert value["representative_seed_needs_review"] == 4
    assert value["multi_turn_model_generated_unreviewed"] == 3
    assert value["unit_test_security_fixtures"] == 8
    assert value["trusted_test_split_exists"] is False
    assert value["formal_production_safety_metrics_status"] == "NOT_RUN"
