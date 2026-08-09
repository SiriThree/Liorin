from __future__ import annotations

from pathlib import Path

import pytest

from eval_platform import RuntimeCaseInput, build_representative_seed_cases
from evals.gold_isolation import assert_no_gold_leak


@pytest.mark.parametrize("key", [
    "expected_behavior",
    "task_success_contract",
    "gold_evidence",
    "gold_facts",
    "safety_constraints",
])
def test_all_phase1_gold_fields_are_rejected_from_runtime_packet(key: str):
    with pytest.raises(ValueError, match="gold fields entered runtime packet"):
        RuntimeCaseInput(
            case_id=f"leak-{key}",
            messages=({"role": "user", "content": "q"},),
            metadata={key: {"secret": True}},
        )


def test_canonical_samples_only_export_runtime_visible_input():
    for sample in build_representative_seed_cases(Path.cwd()):
        packet = sample.to_runtime_input().runtime_packet()
        assert_no_gold_leak(packet)
        serialized = sample.to_dict()
        for key in ("expected_behavior", "task_success_contract", "gold_evidence", "gold_facts", "safety_constraints"):
            assert key in serialized
            assert key not in packet
