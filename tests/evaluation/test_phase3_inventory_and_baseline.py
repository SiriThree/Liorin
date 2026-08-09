import json
from pathlib import Path


def test_phase3_inventory_is_data_readiness_not_a_quality_score():
    row = json.loads(Path("evals/benchmark/data/canonical/phase3_evaluation_inventory.json").read_text(encoding="utf-8"))
    assert row["formal_legacy_canonical_cases"] == 39
    assert row["formal_cases_with_gold_evidence"] == 39
    assert row["formal_cases_with_required_structured_evidence"] == 10
    assert row["recovery_challenge_dataset_status"] == "COVERAGE_INSUFFICIENT_NEEDS_REVIEW"
    assert row["formal_metric_generated"] is False
    assert row["trusted_test_split"] is False


def test_one_pass_and_full_configs_differ_only_in_recovery_switch_and_protocol_label():
    root = Path("evals/benchmark/configs")
    one = json.loads((root / "phase3_one_pass_baseline.example.json").read_text(encoding="utf-8"))
    full = json.loads((root / "phase3_full_agentic.example.json").read_text(encoding="utf-8"))
    assert one["dataset_name"] == full["dataset_name"]
    assert one["dataset_version"] == full["dataset_version"]
    assert one["judge"] == full["judge"]
    assert one["production"]["agentic_recovery_enabled"] is False
    assert full["production"]["agentic_recovery_enabled"] is True
