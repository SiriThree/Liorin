from __future__ import annotations

import json
from pathlib import Path

from eval_platform.cli import main

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "evals" / "benchmark" / "data" / "canonical"


def test_cli_validate_canonical_dataset(capsys):
    rc = main(["validate", "--dataset", str(CANONICAL / "validation_v7_3_canonical_v1.json")])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["case_count"] == 5


def test_phase2_inventory_is_explicitly_not_a_formal_metric():
    payload = json.loads((CANONICAL / "phase2_evaluation_inventory.json").read_text(encoding="utf-8"))
    assert payload["formal_metric_generated"] is False
    assert payload["trusted_test_split"] is False
    assert payload["datasets"]["legacy_dev"]["eligibility"] == {"ELIGIBLE": 34}
    assert payload["datasets"]["legacy_validation"]["eligibility"] == {"ELIGIBLE": 5}
    assert payload["datasets"]["representative_seed"]["eligibility"] == {"NEEDS_REVIEW": 15}
    assert payload["datasets"]["legacy_dev"]["cases_requiring_llm_judge_for_full_required_contract"] == 34
    assert payload["datasets"]["legacy_validation"]["cases_requiring_llm_judge_for_full_required_contract"] == 5


def test_phase2_example_config_keeps_real_judge_disabled_until_configured():
    payload = json.loads((ROOT / "evals" / "benchmark" / "configs" / "phase2_evaluation.example.json").read_text(encoding="utf-8"))
    assert payload["judge"]["enabled"] is False
    assert payload["judge"]["model"] == "REPLACE_WITH_REAL_MODEL"
