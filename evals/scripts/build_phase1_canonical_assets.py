"""Build Phase-1 canonical dataset assets from the checked-in Liorin repository.

This script is deliberately conservative:
- it emits only fully migrated legacy cases as canonical legacy datasets;
- partial/unknown legacy cases go to a review queue;
- historical blind inputs remain HISTORICAL_UNVERIFIED and receive no Gold;
- representative seed cases are a separate schema-coverage asset, not a benchmark score set.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from eval_platform import (
    MigrationStatus,
    SplitTrustLevel,
    build_dataset_manifest,
    build_representative_seed_cases,
    migrate_legacy_dataset,
    validate_dataset,
    write_canonical_dataset,
    write_dataset_manifest,
    write_migration_report,
)


DEFAULT_CREATED_AT = "2026-08-08T08:06:08Z"


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")



def _audit_non_v73_legacy_assets(root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return per-source-row migration status plus an asset-level inventory.

    These older TraceMind/baseline assets lack the strong Gold required by the
    canonical contract.  We preserve them as review/migration inputs rather
    than synthesizing GoldFact/GoldEvidence from keywords or expected_source.
    """
    records: list[dict[str, object]] = []
    inventory: list[dict[str, object]] = []

    baseline = root / "evals/baseline_dataset.json"
    rows = json.loads(baseline.read_text(encoding="utf-8"))
    inventory.append({
        "path": str(baseline.relative_to(root)),
        "type": "legacy_dataset",
        "row_count": len(rows),
        "decision": "MIGRATE_WITH_REVIEW",
        "reason": "expected_source/required_keywords are legacy annotations, not canonical GoldEvidence/GoldFact",
    })
    for index, row in enumerate(rows):
        metadata = row.get("metadata") or {}
        records.append({
            "source_dataset": str(baseline.relative_to(root)),
            "legacy_case_id": str(metadata.get("id") or f"baseline:{index}"),
            "migration_status": "NEEDS_REVIEW",
            "missing": ["task_success_contract", "gold_evidence", "gold_facts"],
            "notes": ["required_keywords and expected_source were intentionally not auto-promoted"],
        })

    tracemind_dir = root / "evals/tracemind"
    case_csvs = {
        "multiturn_benchmark_200.csv",
        "multiturn_benchmark_50.csv",
        "multiturn_cases.csv",
        "multiturn_failure_cases.csv",
        "multiturn_transition_cases.csv",
        "question_public.csv",
        "trace_annotation_template.csv",
    }
    for path in sorted(tracemind_dir.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            csv_rows = list(csv.DictReader(handle))
        rel = str(path.relative_to(root))
        if path.name == "submission_example.csv":
            decision = "RETIRED_AS_DATASET_INPUT"
            reason = "submission output example contains predictions, not evaluation Gold"
            status = "RETIRED"
            missing = []
        elif path.name in case_csvs:
            decision = "MIGRATE_WITH_REVIEW"
            reason = "legacy TraceMind schema lacks canonical evidence/fact/success contracts; lexical fields are not promoted"
            status = "NEEDS_REVIEW"
            missing = ["task_success_contract", "gold_evidence", "gold_facts"]
        else:
            decision = "REVIEW_ASSET_ROLE"
            reason = "CSV role is not a canonical Phase-1 dataset source"
            status = "NEEDS_REVIEW"
            missing = ["canonical_contract"]
        inventory.append({
            "path": rel,
            "type": "legacy_csv",
            "row_count": len(csv_rows),
            "decision": decision,
            "reason": reason,
        })
        for index, row in enumerate(csv_rows):
            records.append({
                "source_dataset": rel,
                "legacy_case_id": str(row.get("id") or f"{path.stem}:{index}"),
                "migration_status": status,
                "missing": list(missing),
                "notes": [reason],
            })

    inventory.append({
        "path": "evals/annotation_pipeline/",
        "type": "annotation_pipeline",
        "row_count": 0,
        "decision": "KEEP",
        "reason": "annotation/review capability is retained for future canonical Gold review; no annotation output dataset is checked into this directory",
    })
    inventory.append({
        "path": "evals/agentic_rag_metrics_report.json",
        "type": "legacy_report",
        "row_count": 0,
        "decision": "KEEP_LEGACY_REPORT_NOT_MIGRATION_INPUT",
        "reason": "historical metric artifact is not a source of canonical Gold",
    })
    return records, inventory

def build(root: Path, *, created_at: str) -> dict[str, object]:
    data_dir = root / "evals/benchmark/data"
    out = data_dir / "canonical"
    out.mkdir(parents=True, exist_ok=True)

    legacy_specs = (
        ("dev_v7_3.json", SplitTrustLevel.DEVELOPMENT, "DEVELOPMENT"),
        ("validation_v7_3.json", SplitTrustLevel.VALIDATION, "VALIDATION"),
        ("blind_test_inputs_v7_3.json", SplitTrustLevel.HISTORICAL_UNVERIFIED, "HISTORICAL_UNVERIFIED"),
    )

    reports = []
    review_queue = []
    migrated_by_source: dict[str, tuple] = {}
    for filename, trust, intended_usage in legacy_specs:
        records, report = migrate_legacy_dataset(data_dir / filename)
        reports.append(report)
        fully = tuple(
            record.canonical_sample
            for record in records
            if record.status is MigrationStatus.MIGRATED and record.canonical_sample is not None
        )
        migrated_by_source[filename] = fully
        if fully:
            validate_dataset(fully)
            stem = filename.removesuffix(".json")
            dataset_path = out / f"{stem}_canonical_v1.json"
            write_canonical_dataset(dataset_path, fully)
            manifest = build_dataset_manifest(
                dataset_name=f"liorin_{stem}_canonical",
                dataset_version="1.0",
                samples=fully,
                created_at=created_at,
                source_datasets=(filename,),
                gold_status="LEGACY_GOLD_MIGRATED_CONSERVATIVELY",
                review_status="MIGRATED_LEGACY_NOT_HUMAN_REVIEWED",
                contamination_status=(
                    "DEVELOPMENT_ONLY" if trust is SplitTrustLevel.DEVELOPMENT
                    else "VALIDATION_ONLY_NO_TEST_CLAIM"
                ),
                intended_usage=intended_usage,
                trust_level=trust,
            )
            write_dataset_manifest(out / f"{stem}_canonical_v1.manifest.json", manifest)

        for record in records:
            if record.status is MigrationStatus.MIGRATED:
                continue
            candidate = record.canonical_sample
            review_queue.append({
                "source_dataset": filename,
                "legacy_case_id": record.legacy_case_id,
                "migration_status": record.status.value,
                "candidate_category": candidate.category.value if candidate else None,
                "candidate_subcategory": candidate.subcategory if candidate else None,
                "missing": list(record.missing),
                "notes": list(record.notes),
            })

    write_migration_report(out / "phase1_legacy_migration_report.json", reports)
    _write_json(out / "phase1_legacy_review_queue.json", review_queue)

    non_v73_records, legacy_inventory = _audit_non_v73_legacy_assets(root)
    non_v73_path = out / "phase1_non_v73_migration_status.jsonl"
    non_v73_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in non_v73_records) + "\n",
        encoding="utf-8",
    )
    _write_json(out / "phase1_legacy_asset_inventory.json", legacy_inventory)

    # Separate, source-grounded schema seeds.  They are explicitly NEEDS_REVIEW
    # and never merged into the migrated legacy benchmark count.
    seeds = build_representative_seed_cases(root)
    validate_dataset(seeds)
    write_canonical_dataset(out / "representative_seed_v1.json", seeds)
    write_canonical_dataset(out / "representative_seed_v1.jsonl", seeds)
    seed_manifest = build_dataset_manifest(
        dataset_name="liorin_phase1_representative_seed",
        dataset_version="1.0",
        samples=seeds,
        created_at=created_at,
        source_datasets=(
            "evals/benchmark/corpus/corpus_v7_3.json",
            "evals/benchmark/data/dev_v7_3.json",
            "evals/benchmark/data/validation_v7_3.json",
            "data/structured/customers.json",
            "data/structured/orders.json",
            "data/structured/tickets.json",
            "data/structured/warranty_cases.json",
        ),
        gold_status="SOURCE_GROUNDED_SCHEMA_SEED_NEEDS_REVIEW",
        review_status="NOT_HUMAN_REVIEWED",
        contamination_status="DEVELOPMENT_SCHEMA_COVERAGE_ONLY",
        intended_usage="SCHEMA_VALIDATION_ONLY",
        trust_level=SplitTrustLevel.DEVELOPMENT,
    )
    write_dataset_manifest(out / "representative_seed_v1.manifest.json", seed_manifest)

    # Explicit trust registry.  Trust is assigned here from audit evidence, not
    # inferred from substrings such as 'blind' in a filename.
    split_trust = {
        "schema_version": "1.0",
        "trusted_test_split": None,
        "trusted_test_status": "NO_TRUSTED_TEST_SPLIT_YET",
        "splits": [
            {
                "dataset": "dev_v7_3.json",
                "declared_split": "dev",
                "trust_level": SplitTrustLevel.DEVELOPMENT.value,
                "intended_usage": "DEVELOPMENT",
                "reason": "Legacy development set; tuning exposure is expected.",
            },
            {
                "dataset": "validation_v7_3.json",
                "declared_split": "validation",
                "trust_level": SplitTrustLevel.VALIDATION.value,
                "intended_usage": "VALIDATION",
                "reason": "Legacy validation set; no claim of blind/test independence.",
            },
            {
                "dataset": "blind_test_inputs_v7_3.json",
                "declared_split": "blind_test",
                "trust_level": SplitTrustLevel.HISTORICAL_UNVERIFIED.value,
                "intended_usage": "PREDICTION_INPUTS_ONLY",
                "reason": "No local Gold and no auditable evidence proving no historical tuning exposure or independent Gold custody.",
            },
        ],
    }
    _write_json(out / "split_trust_v1.json", split_trust)

    summary = {
        "created_at": created_at,
        "fully_migrated_legacy_total": sum(len(items) for items in migrated_by_source.values()),
        "fully_migrated_by_source": {name: len(items) for name, items in migrated_by_source.items()},
        "v73_review_queue_count": len(review_queue),
        "non_v73_needs_review_source_rows": sum(1 for item in non_v73_records if item["migration_status"] == "NEEDS_REVIEW"),
        "non_v73_retired_source_rows": sum(1 for item in non_v73_records if item["migration_status"] == "RETIRED"),
        "needs_review_source_rows_total": len(review_queue) + sum(1 for item in non_v73_records if item["migration_status"] == "NEEDS_REVIEW"),
        "representative_seed_count": len(seeds),
        "trusted_test_status": "NO_TRUSTED_TEST_SPLIT_YET",
    }
    _write_json(out / "phase1_asset_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--created-at", default=DEFAULT_CREATED_AT)
    args = parser.parse_args()
    summary = build(args.root.resolve(), created_at=args.created_at)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
