from pathlib import Path

from eval_platform.calibration import PHASE3_REQUIRED_CALIBRATION_KINDS, load_phase3_claim_calibration
from eval_platform.judge import PROMPTS


def test_phase3_claim_grounding_calibration_is_separate_and_referenced():
    path = Path("evals/benchmark/data/calibration/phase3_claim_grounding_calibration_v1.json")
    rows = load_phase3_claim_calibration(path)
    assert {row["kind"] for row in rows} == PHASE3_REQUIRED_CALIBRATION_KINDS
    assert all(row["reference_source"] and row["reference_reason"] for row in rows)
    assert {row["prompt_version"] for row in rows} <= set(PROMPTS)
