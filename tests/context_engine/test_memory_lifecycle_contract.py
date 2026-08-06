from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from context_engine import (
    ContextItem,
    ContextItemType,
    MemoryLifecycleEvent,
    MemoryLifecycleHook,
    MemoryLifecycleRecord,
    MemoryLifecycleState,
    MemoryMetadata,
)


def _metadata(*, state: MemoryLifecycleState | str = MemoryLifecycleState.CANDIDATE):
    created_at = datetime(2026, 8, 6, 3, 0, tzinfo=timezone.utc)
    return MemoryMetadata(
        id="memory-1",
        created_at=created_at,
        updated_at=created_at,
        source="conversation-memory-extractor",
        confidence=0.91,
        lifecycle_state=state,
    )


def test_memory_lifecycle_event_contract_is_stable():
    assert [event.value for event in MemoryLifecycleEvent] == [
        "CREATED",
        "UPDATED",
        "RETRIEVED",
        "EXPIRED",
        "DELETED",
    ]
    assert MemoryLifecycleState("CANDIDATE") is MemoryLifecycleState.CANDIDATE
    assert _metadata(state="persisted").lifecycle_state is MemoryLifecycleState.PERSISTED


def test_memory_metadata_roundtrip_is_checkpoint_safe():
    metadata = _metadata(state=MemoryLifecycleState.POLICY_APPROVED)

    restored = MemoryMetadata.from_state(metadata.to_state())

    assert restored == metadata
    assert restored.to_state()["lifecycle_state"] == "POLICY_APPROVED"


def test_memory_metadata_rejects_invalid_audit_values():
    created_at = datetime.now(timezone.utc)

    with pytest.raises(ValueError, match="updated_at must not precede"):
        MemoryMetadata(
            id="memory-1",
            created_at=created_at,
            updated_at=created_at - timedelta(seconds=1),
            source="extractor",
            confidence=0.8,
            lifecycle_state=MemoryLifecycleState.CANDIDATE,
        )

    with pytest.raises(ValueError, match="between 0 and 1"):
        MemoryMetadata(
            id="memory-1",
            created_at=created_at,
            updated_at=created_at,
            source="extractor",
            confidence=1.01,
            lifecycle_state=MemoryLifecycleState.CANDIDATE,
        )


def test_lifecycle_record_captures_writer_or_reader_and_reason():
    metadata = _metadata(state=MemoryLifecycleState.PERSISTED)
    record = MemoryLifecycleRecord(
        event=MemoryLifecycleEvent.RETRIEVED,
        memory=metadata,
        occurred_at=metadata.updated_at + timedelta(minutes=2),
        actor="context_engine.builder",
        reason="Inject relevant user preference into current model context",
        attributes={"request_id": "req-7", "policy": "tenant-safe"},
    )

    restored = MemoryLifecycleRecord.from_state(record.to_state())

    assert restored.event is MemoryLifecycleEvent.RETRIEVED
    assert restored.memory.id == "memory-1"
    assert restored.actor == "context_engine.builder"
    assert restored.reason.startswith("Inject relevant")
    assert restored.attributes["request_id"] == "req-7"


def test_lifecycle_hook_is_a_contract_only_and_metadata_can_travel_by_reference():
    observed: list[MemoryLifecycleRecord] = []

    class Collector:
        def __call__(self, record: MemoryLifecycleRecord) -> None:
            observed.append(record)

    hook = Collector()
    assert isinstance(hook, MemoryLifecycleHook)

    metadata = _metadata(state=MemoryLifecycleState.PERSISTED)
    record = MemoryLifecycleRecord(
        event="retrieved",
        memory=metadata,
        occurred_at=metadata.updated_at,
        actor="test-reader",
        reason="Verify hook contract",
    )
    hook(record)

    item = ContextItem(
        id="memory-ref-1",
        type=ContextItemType.MEMORY,
        content="memory_id=memory-1",
        source="future-memory-runtime",
        priority=70,
        metadata={"memory_metadata": metadata},
    )

    assert observed == [record]
    assert item.metadata["memory_metadata"]["id"] == "memory-1"
    assert item.metadata["memory_metadata"]["lifecycle_state"] == "PERSISTED"
