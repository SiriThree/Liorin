from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from context_engine import MemoryLifecycleState
from memory.delta import MemoryDeltaDetector, MemoryUpdate, memory_fingerprint
from memory.working import WorkingMemory, WorkingMemoryUpdater


def _memory(*, facts=(), questions=(), updated_minute=0) -> WorkingMemory:
    return WorkingMemory(
        session_id="delta-session",
        task_goal="排查冰箱 E17 异响",
        current_intent="troubleshooting",
        confirmed_facts=facts,
        open_questions=questions,
        next_actions=("继续安全排查",),
        last_updated=datetime(2026, 8, 6, 5, updated_minute, tzinfo=timezone.utc),
    )


def test_memory_delta_detection():
    previous = _memory(facts=("product_model=LF-900",), questions=("需要补充：error_code",))
    candidate = _memory(
        facts=("product_model=LF-900", "error_code=E17"),
        questions=("需要补充：noise_timing",),
        updated_minute=1,
    )

    delta = MemoryDeltaDetector().detect(
        previous,
        candidate,
        reason="customer provided error code and next missing slot changed",
    )

    assert delta.is_noop is False
    assert delta.changed_fields == ("confirmed_facts", "open_questions")
    assert delta.additions["confirmed_facts"] == ("error_code=E17",)
    assert delta.removals["open_questions"] == ("需要补充：error_code",)
    assert delta.additions["open_questions"] == ("需要补充：noise_timing",)
    assert delta.previous_fingerprint != delta.candidate_fingerprint


def test_memory_delta_noop():
    previous = _memory(facts=("product_model=LF-900",), updated_minute=0)
    # A newer timestamp is not a semantic state change.
    candidate = _memory(facts=("product_model=LF-900",), updated_minute=1)
    updater = WorkingMemoryUpdater()

    result = updater.update(
        candidate.to_state(),
        actor="test.memory_delta",
        reason="repeat identical structured state",
        previous=previous,
        session_id=previous.session_id,
        now=candidate.last_updated,
    )

    assert result.delta.is_noop is True
    assert result.persisted is False
    assert result.policy is None
    assert result.lifecycle_records == ()
    assert result.memory == previous
    assert result.memory.last_updated == previous.last_updated


def test_memory_delta_checkpoint():
    # Represents a Phase 2 checkpoint: no delta fields are required.
    legacy_checkpoint = {
        "session_id": "delta-session",
        "working_memory": _memory(
            facts=("product_model=LF-900",),
            questions=("需要补充：error_code",),
        ).to_state(),
        "working_memory_lifecycle_records": [],
    }
    restored = json.loads(json.dumps(legacy_checkpoint, ensure_ascii=False))
    previous = WorkingMemory.from_state(restored["working_memory"])

    result = WorkingMemoryUpdater().update(
        {
            **restored,
            "confirmed_facts": ["product_model=LF-900", "error_code=E17"],
            "unresolved_slots": ["noise_timing"],
        },
        actor="test.memory_delta.checkpoint",
        reason="resume legacy checkpoint with a real state change",
        previous=previous,
        existing_records=restored["working_memory_lifecycle_records"],
        session_id=restored["session_id"],
        now=previous.last_updated + timedelta(minutes=1),
    )

    assert result.persisted is True
    assert "confirmed_facts" in result.delta.changed_fields
    assert "error_code=E17" in result.memory.confirmed_facts
    persisted = result.lifecycle_records[-1]
    assert persisted.memory.lifecycle_state is MemoryLifecycleState.PERSISTED
    assert set(persisted.attributes["changed_fields"]) == {
        "confirmed_facts", "open_questions", "next_actions"
    }
    assert persisted.attributes["reason"] == "resume legacy checkpoint with a real state change"


def test_memory_delta_serialization():
    previous = _memory(facts=("product_model=LF-900",))
    candidate = _memory(
        facts=("product_model=LF-900", "error_code=E17"),
        updated_minute=1,
    )
    delta = MemoryDeltaDetector().detect(previous, candidate, reason="customer provided E17")

    serialized = json.loads(json.dumps(delta.to_state(), ensure_ascii=False))
    restored = MemoryUpdate.from_state(serialized)

    assert restored == delta
    assert restored.to_state() == serialized
    assert memory_fingerprint(previous) == memory_fingerprint(
        WorkingMemory.from_state(previous.to_state())
    )
