from __future__ import annotations

from pathlib import Path

from eval_platform.context_memory import (
    SessionEligibilityStatus, canonical_session_dataset_hash, read_canonical_sessions,
    session_dataset_inventory, write_canonical_sessions,
)
from eval_platform.multi_turn_seed import build_phase4_candidate_sessions


def test_phase4_candidate_sessions_are_explicitly_unreviewed_and_ineligible():
    sessions=build_phase4_candidate_sessions()
    inventory=session_dataset_inventory(sessions)
    assert inventory["candidate_sessions"] == 12
    assert inventory["turn_count"] == 29
    assert inventory["eligible_sessions"] == 0
    assert inventory["needs_review_sessions"] == 9
    assert inventory["eligibility_statuses"][SessionEligibilityStatus.MISSING_CONTEXT_GOLD.value] == 3


def test_session_json_roundtrip_and_hash_stable(tmp_path: Path):
    sessions=build_phase4_candidate_sessions()
    path=write_canonical_sessions(tmp_path/"sessions.json",sessions)
    loaded=read_canonical_sessions(path)
    assert [x.to_state() for x in loaded] == [x.to_state() for x in sessions]
    assert canonical_session_dataset_hash(loaded) == canonical_session_dataset_hash(sessions)
