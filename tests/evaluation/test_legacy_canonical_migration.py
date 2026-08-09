from __future__ import annotations

import json
from pathlib import Path

from eval_platform import MigrationStatus, migrate_legacy_dataset, migrate_legacy_row


def test_dev_validation_and_historical_blind_migration_counts_are_real():
    expected = {
        "dev_v7_3.json": (368, 34, 334, 0),
        "validation_v7_3.json": (119, 5, 114, 0),
        "blind_test_inputs_v7_3.json": (125, 0, 0, 125),
    }
    for filename, counts in expected.items():
        _, report = migrate_legacy_dataset(Path("evals/benchmark/data") / filename)
        assert (report.total_cases, report.fully_migrated, report.partial, report.needs_review) == counts


def test_required_keywords_are_not_auto_promoted_to_gold_facts():
    row = {
        "id": "legacy-keywords-only",
        "layer": "answer_generation",
        "category": "legacy",
        "difficulty": "easy",
        "input": {"question": "q", "conversation": [{"role": "user", "content": "q"}]},
        "gold": {"required_keywords": ["secret-proxy"], "expected_response_type": "answer"},
        "split": "dev",
    }
    record = migrate_legacy_row(row, source_dataset="synthetic-legacy-shape")
    assert record.status is MigrationStatus.PARTIALLY_MIGRATED
    assert record.canonical_sample is None
    assert "gold_facts" in record.missing


def test_expected_source_alone_is_not_promoted_to_complete_gold():
    row = {
        "id": "legacy-source-only",
        "layer": "end_to_end",
        "category": "manual_support",
        "difficulty": "easy",
        "input": {"conversation": [{"role": "user", "content": "q"}], "identity_verified": False},
        "gold": {"expected_source": "manual", "expected_response_type": "answer", "required_atomic_facts": []},
        "split": "dev",
    }
    record = migrate_legacy_row(row, source_dataset="synthetic-legacy-shape")
    assert record.status is MigrationStatus.PARTIALLY_MIGRATED
    assert "gold_facts" in record.missing


def test_historical_blind_input_remains_unverified_and_has_no_canonical_gold():
    row = json.loads(Path("evals/benchmark/data/blind_test_inputs_v7_3.json").read_text(encoding="utf-8"))[0]
    record = migrate_legacy_row(row, source_dataset="blind_test_inputs_v7_3.json")
    assert record.status is MigrationStatus.NEEDS_REVIEW
    assert record.canonical_sample is None
    assert record.missing == ("gold",)
