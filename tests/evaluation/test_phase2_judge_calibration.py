from pathlib import Path

from eval_platform.calibration import REQUIRED_CALIBRATION_KINDS, load_judge_calibration


def test_calibration_set_has_reference_and_required_failure_modes():
    path = Path("evals/benchmark/data/calibration/judge_calibration_v1.json")
    cases = load_judge_calibration(path)
    assert len(cases) >= 12
    assert {c.kind for c in cases} >= REQUIRED_CALIBRATION_KINDS
    assert all(c.reference_source for c in cases)
    assert all(c.reference_reason for c in cases)
    # Calibration fixtures are deliberately synthetic/constructed; they are not a
    # future validation/test split and are safe for prompt calibration.
    assert all("VALIDATION" not in c.reference_source and "TEST" not in c.reference_source for c in cases)
