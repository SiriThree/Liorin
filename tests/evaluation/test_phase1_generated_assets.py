from __future__ import annotations

import json
from pathlib import Path

from eval_platform import canonical_dataset_hash, read_canonical_dataset, validate_dataset


CANONICAL = Path("evals/benchmark/data/canonical")


def test_checked_in_phase1_canonical_assets_validate_and_match_manifests():
    pairs = (
        ("dev_v7_3_canonical_v1.json", "dev_v7_3_canonical_v1.manifest.json", 34),
        ("validation_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.manifest.json", 5),
        ("representative_seed_v1.json", "representative_seed_v1.manifest.json", 15),
    )
    for dataset_name, manifest_name, count in pairs:
        samples = read_canonical_dataset(CANONICAL / dataset_name)
        manifest = json.loads((CANONICAL / manifest_name).read_text(encoding="utf-8"))
        assert len(samples) == count
        assert validate_dataset(samples).valid
        assert manifest["case_count"] == count
        assert manifest["dataset_hash"] == canonical_dataset_hash(samples)


def test_split_trust_is_explicit_and_no_trusted_test_is_claimed():
    trust = json.loads((CANONICAL / "split_trust_v1.json").read_text(encoding="utf-8"))
    by_dataset = {item["dataset"]: item["trust_level"] for item in trust["splits"]}
    assert by_dataset == {
        "dev_v7_3.json": "DEVELOPMENT",
        "validation_v7_3.json": "VALIDATION",
        "blind_test_inputs_v7_3.json": "HISTORICAL_UNVERIFIED",
    }
    assert trust["trusted_test_split"] is None
    assert trust["trusted_test_status"] == "NO_TRUSTED_TEST_SPLIT_YET"


def test_migration_report_preserves_real_counts_and_review_debt():
    report = json.loads((CANONICAL / "phase1_legacy_migration_report.json").read_text(encoding="utf-8"))
    by_source = {item["source_dataset"]: item for item in report}
    assert (by_source["dev_v7_3.json"]["total_cases"], by_source["dev_v7_3.json"]["fully_migrated"]) == (368, 34)
    assert (by_source["validation_v7_3.json"]["total_cases"], by_source["validation_v7_3.json"]["fully_migrated"]) == (119, 5)
    assert (by_source["blind_test_inputs_v7_3.json"]["total_cases"], by_source["blind_test_inputs_v7_3.json"]["needs_review"]) == (125, 125)

    summary = json.loads((CANONICAL / "phase1_asset_summary.json").read_text(encoding="utf-8"))
    assert summary["fully_migrated_legacy_total"] == 39
    assert summary["needs_review_source_rows_total"] == 1252
    assert summary["non_v73_retired_source_rows"] == 400
