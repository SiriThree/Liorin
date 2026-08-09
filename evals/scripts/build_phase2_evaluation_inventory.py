"""Build reproducible Phase-2 eligibility/criterion inventory from Canonical assets.

This is a data-contract inventory only. It never invokes Production or a Judge
and therefore never emits Task Success or model-quality metrics.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path

from eval_platform import (
    ComparisonMode,
    EvaluationEligibilityStatus,
    SuccessCriterion,
    evaluate_eligibility,
    read_canonical_dataset,
)

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "evals" / "benchmark" / "data" / "canonical"
DATASETS = {
    "legacy_dev": CANONICAL / "dev_v7_3_canonical_v1.json",
    "legacy_validation": CANONICAL / "validation_v7_3_canonical_v1.json",
    "representative_seed": CANONICAL / "representative_seed_v1.json",
}
OUT = CANONICAL / "phase2_evaluation_inventory.json"


def analyze(path: Path) -> dict:
    rows = read_canonical_dataset(path)
    eligibility = Counter(evaluate_eligibility(sample).status.value for sample in rows)
    required = Counter(c.value for sample in rows for c in sample.task_success_contract.required_criteria)
    fact_modes = Counter(f.comparison_mode.value for sample in rows for f in sample.gold_facts)
    annotations = Counter(sample.annotation_metadata.annotation_status.value for sample in rows)
    categories = Counter(sample.category.value for sample in rows)

    judge_required_cases = 0
    for sample in rows:
        criteria = set(sample.task_success_contract.required_criteria)
        has_semantic_fact = any(f.comparison_mode is ComparisonMode.SEMANTIC and f.critical for f in sample.gold_facts)
        if has_semantic_fact or SuccessCriterion.NO_CRITICAL_HALLUCINATION in criteria:
            judge_required_cases += 1

    return {
        "path": str(path.relative_to(ROOT)),
        "cases": len(rows),
        "eligibility": dict(sorted(eligibility.items())),
        "annotation_status": dict(sorted(annotations.items())),
        "category": dict(sorted(categories.items())),
        "required_criteria": dict(sorted(required.items())),
        "gold_fact_comparison_modes": dict(sorted(fact_modes.items())),
        "cases_requiring_llm_judge_for_full_required_contract": judge_required_cases,
    }


def main() -> int:
    report = {
        "semantics": "Phase-2 contract inventory only; no Production execution and no Task Success metric",
        "datasets": {name: analyze(path) for name, path in DATASETS.items()},
        "trusted_test_split": False,
        "formal_metric_generated": False,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
