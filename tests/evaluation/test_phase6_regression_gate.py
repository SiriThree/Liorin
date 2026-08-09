from __future__ import annotations

import json
from pathlib import Path
import pytest

from eval_platform.regression import (
    BaselineRegistry, GateStatus, RegressionRule, RunValidity, ThresholdType,
    evaluate_contract_gate, evaluate_rule,
)


def test_contract_gate_is_all_or_nothing():
    assert evaluate_contract_gate({"schema":True,"gold":True,"single_execution":True}).status is GateStatus.PASS
    result=evaluate_contract_gate({"schema":True,"gold":False})
    assert result.status is GateStatus.FAIL and "gold" in result.reason


def test_zero_tolerance_gate_fails_on_one_critical_violation():
    rule=RegressionRule("safety","critical",ThresholdType.ZERO_TOLERANCE,0)
    assert evaluate_rule(rule,current=0,baseline=0).status is GateStatus.PASS
    assert evaluate_rule(rule,current=1,baseline=0).status is GateStatus.FAIL


def test_quality_gate_without_baseline_or_tolerance_is_blocked():
    rule=RegressionRule("task","task_success",ThresholdType.MAX_REGRESSION_PP,None)
    assert evaluate_rule(rule,current=.9,baseline=None).reason == "BASELINE_NOT_ESTABLISHED"
    assert evaluate_rule(rule,current=.9,baseline=.91).reason == "REGRESSION_TOLERANCE_NOT_ESTABLISHED"


def test_quality_regression_uses_percentage_point_tolerance_fixture_only():
    rule=RegressionRule("task","task_success",ThresholdType.MAX_REGRESSION_PP,2.0)
    assert evaluate_rule(rule,current=.84,baseline=.85).status is GateStatus.PASS
    assert evaluate_rule(rule,current=.82,baseline=.85).status is GateStatus.FAIL


def test_baseline_promotion_is_explicit_and_rejects_invalid_runs(tmp_path):
    registry=BaselineRegistry(tmp_path/"baseline.json")
    with pytest.raises(ValueError):
        registry.promote(baseline_name="x",run_validity=RunValidity.PARTIAL,dataset_formal_eligible=True,critical_safety_violations=0,required_metrics={"task_success":.8},dataset_hash="d",config_hash="c",run_id="r")
    record=registry.promote(baseline_name="x",run_validity=RunValidity.VALID,dataset_formal_eligible=True,critical_safety_violations=0,required_metrics={"task_success":.8},dataset_hash="d",config_hash="c",run_id="r")
    assert record.run_id == "r"
    assert BaselineRegistry(tmp_path/"baseline.json").get("x").metrics["task_success"] == .8


def test_baseline_promotion_rejects_critical_safety_violation(tmp_path):
    registry=BaselineRegistry(tmp_path/"b.json")
    with pytest.raises(ValueError):
        registry.promote(baseline_name="x",run_validity=RunValidity.VALID,dataset_formal_eligible=True,critical_safety_violations=1,required_metrics={"task_success":.8},dataset_hash="d",config_hash="c",run_id="r")
