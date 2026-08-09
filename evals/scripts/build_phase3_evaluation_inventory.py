"""Build reproducible Phase-3 evidence/recovery data-readiness inventory.

This script reads Canonical Gold only.  It never invokes Production, Retriever,
Judge, Tool, or DB, and therefore emits no Evidence/Recovery quality metric.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from eval_platform import EvidenceSourceType, read_canonical_dataset

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "evals" / "benchmark" / "data" / "canonical"
DATASETS = {
    "legacy_dev": CANONICAL / "dev_v7_3_canonical_v1.json",
    "legacy_validation": CANONICAL / "validation_v7_3_canonical_v1.json",
    "representative_seed": CANONICAL / "representative_seed_v1.json",
}
OUT = CANONICAL / "phase3_evaluation_inventory.json"


def analyze(path: Path) -> dict:
    rows = read_canonical_dataset(path)
    source_counts = Counter(e.source_type.value for s in rows for e in s.gold_evidence if e.required)
    cases_with_source = Counter()
    alternative_groups = 0
    recovery_declared = 0
    clarification = 0
    for sample in rows:
        types = {e.source_type for e in sample.gold_evidence if e.required}
        for source_type in types:
            cases_with_source[source_type.value] += 1
        alternative_groups += len({e.alternative_group for e in sample.gold_evidence if e.required and e.alternative_group})
        if sample.expected_behavior.allowed_recovery_actions:
            recovery_declared += 1
        if sample.expected_behavior.clarification_required is True:
            clarification += 1
    return {
        "path": str(path.relative_to(ROOT)),
        "cases": len(rows),
        "required_gold_evidence": dict(sorted(source_counts.items())),
        "cases_with_required_source": dict(sorted(cases_with_source.items())),
        "cases_with_gold_evidence": sum(bool(s.gold_evidence) for s in rows),
        "alternative_groups": alternative_groups,
        "cases_declaring_allowed_recovery_actions": recovery_declared,
        "clarification_required_cases": clarification,
        "annotation_status": dict(sorted(Counter(s.annotation_metadata.annotation_status.value for s in rows).items())),
    }


def main() -> int:
    datasets = {name: analyze(path) for name, path in DATASETS.items()}
    formal = [*read_canonical_dataset(DATASETS["legacy_dev"]), *read_canonical_dataset(DATASETS["legacy_validation"])]
    report = {
        "semantics": "Phase-3 data-readiness inventory only; no Production/Judge execution and no quality metric",
        "datasets": datasets,
        "formal_legacy_canonical_cases": len(formal),
        "formal_cases_with_gold_evidence": sum(bool(s.gold_evidence) for s in formal),
        "formal_cases_with_required_structured_evidence": sum(any(e.required and e.source_type is EvidenceSourceType.STRUCTURED_DATA for e in s.gold_evidence) for s in formal),
        "recovery_challenge_dataset_status": "COVERAGE_INSUFFICIENT_NEEDS_REVIEW",
        "recovery_challenge_reason": "Canonical Gold does not yet carry an independently reviewed first-pass insufficiency condition for a formal recovery challenge subset; runtime recovery diagnostics can be computed after a real trace, but no challenge score is pre-certified from Gold alone.",
        "trusted_test_split": False,
        "formal_metric_generated": False,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
