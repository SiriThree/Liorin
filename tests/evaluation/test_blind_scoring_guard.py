from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.benchmark.scoring.scorer import score_predictions


def test_gold_free_historical_blind_inputs_cannot_be_locally_scored(tmp_path: Path):
    predictions = tmp_path / "predictions.json"
    predictions.write_text(json.dumps([]), encoding="utf-8")

    with pytest.raises(ValueError, match="without local Gold"):
        score_predictions(
            predictions,
            "evals/benchmark/data/blind_test_inputs_v7_3.json",
        )
