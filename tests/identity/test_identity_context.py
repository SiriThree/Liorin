from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from context_engine import (
    ContextBuilder,
    ContextItem,
    ContextItemType,
    MemoryLifecycleEvent,
    MemoryLifecycleRecord,
    MemoryLifecycleState,
    MemoryMetadata,
    SummaryMetadata,
    SummarySourceRange,
)
from identity import IdentityContext, IdentityResolutionError, IdentityResolver
from memory.working import WorkingMemory, WorkingMemorySerializer


def _identity() -> IdentityContext:
    return IdentityContext(
        tenant_id="tenant-acme",
        user_id="user-42",
        conversation_id="conversation-900",
        thread_id="langgraph-thread-77",
        session_id="runtime-session-12",
    )


def test_identity_context_roundtrip():
    identity = _identity()

    restored = IdentityContext.from_state(
        json.loads(json.dumps(identity.to_state(), ensure_ascii=False))
    )

    assert restored == identity
    assert restored.to_state() == {
        "tenant_id": "tenant-acme",
        "user_id": "user-42",
        "conversation_id": "conversation-900",
        "thread_id": "langgraph-thread-77",
        "session_id": "runtime-session-12",
    }

    with pytest.raises(ValueError, match="distinct identity semantics"):
        IdentityContext(
            tenant_id="same",
            user_id="same",
            conversation_id="same",
            thread_id="same",
            session_id="same",
        )


def test_identity_resolver_uses_runtime_thread_and_preserves_semantics():
    runtime = SimpleNamespace(
        execution_info=SimpleNamespace(thread_id="thread-from-langgraph"),
        server_info=SimpleNamespace(
            user=SimpleNamespace(identity="authenticated-user")
        ),
        context=SimpleNamespace(tenant_id="tenant-runtime"),
    )

    identity = IdentityResolver().resolve({}, runtime=runtime)

    assert identity.thread_id == "thread-from-langgraph"
    assert identity.tenant_id == "tenant-runtime"
    assert identity.user_id == "authenticated-user"
    assert identity.conversation_id.startswith("conversation:")
    assert identity.session_id.startswith("session:")
    assert len(set(identity.to_state().values())) == 5


def test_identity_resolver_migrates_phase2_session_and_upgrades_anonymous_user():
    resolver = IdentityResolver()
    migrated = resolver.resolve(
        {
            "session_id": "phase2-session",
            "working_memory": {"session_id": "phase2-session"},
        },
        configurable={"configurable": {"thread_id": "thread-migration"}},
    )

    assert migrated.thread_id == "thread-migration"
    assert migrated.session_id == "phase2-session"
    assert migrated.user_id == "user:anonymous"

    upgraded = resolver.resolve(
        {
            "identity_context": migrated.to_state(),
            "session_id": "phase2-session",
            "customer_id": "customer-88",
        },
        configurable={"configurable": {"thread_id": "thread-migration"}},
    )

    assert upgraded.user_id == "customer-88"
    assert upgraded.thread_id == migrated.thread_id
    assert upgraded.session_id == migrated.session_id


def test_identity_resolver_rejects_cross_thread_checkpoint_reuse():
    resolver = IdentityResolver()
    state = {"identity_context": _identity().to_state()}
    runtime = SimpleNamespace(
        execution_info=SimpleNamespace(thread_id="different-thread"),
        server_info=None,
        context=None,
    )

    with pytest.raises(IdentityResolutionError, match="thread_id conflicts"):
        resolver.resolve(state, runtime=runtime)


def test_identity_checkpoint_restore():
    identity = _identity()
    memory = WorkingMemory(
        session_id=identity.session_id,
        task_goal="排查冰箱异常噪音",
        current_intent="troubleshooting",
        confirmed_facts=("product_model=LF-900",),
        open_questions=("需要补充：错误代码",),
        last_updated=datetime(2026, 8, 6, 4, 0, tzinfo=timezone.utc),
    )
    payload = WorkingMemorySerializer.checkpoint_payload(
        memory,
        lifecycle_records=(),
        identity_context=identity,
    )

    restored_payload = WorkingMemorySerializer.json_round_trip(payload)
    restored_identity = IdentityContext.from_state(
        restored_payload["identity_context"]
    )
    restored_memory = WorkingMemory.from_state(restored_payload["working_memory"])

    assert restored_identity == identity
    assert restored_memory.session_id == restored_identity.session_id
    assert restored_memory.task_goal == "排查冰箱异常噪音"
    assert restored_memory.confirmed_facts == ("product_model=LF-900",)


def test_context_item_and_builder_attach_identity_metadata():
    identity = _identity()
    direct_item = ContextItem(
        id="memory-1",
        type=ContextItemType.MEMORY,
        content="当前任务状态",
        source="memory.working",
        priority=99,
        metadata={"identity_context": identity},
    )

    assert direct_item.identity_context == identity
    assert direct_item.to_state()["metadata"]["identity_context"]["tenant_id"] == "tenant-acme"

    built = ContextBuilder().build(
        messages_state={
            "messages": [{"role": "user", "content": "继续排查"}],
            "identity_context": identity.to_state(),
            "workflow_state": {"stage": "ready_for_supervisor"},
        }
    )

    assert built
    assert all(item.identity_context == identity for item in built)


def test_summary_and_lifecycle_identity_are_backward_compatible():
    identity = _identity()
    created_at = datetime(2026, 8, 6, 4, 0, tzinfo=timezone.utc)
    summary = SummaryMetadata(
        source_range=SummarySourceRange(start_turn=1, end_turn=20),
        generated_by="context_compactor",
        confidence=0.9,
        created_at=created_at,
        original_token_cost=4_000,
        compressed_token_cost=500,
        identity_context=identity,
    )
    old_summary_state = summary.to_state()
    old_summary_state.pop("identity_context")

    assert SummaryMetadata.from_state(summary.to_state()).identity_context == identity
    assert SummaryMetadata.from_state(old_summary_state).identity_context is None

    metadata = MemoryMetadata(
        id="working-memory:runtime-session-12",
        created_at=created_at,
        updated_at=created_at,
        source="memory.working.lifecycle_adapter",
        confidence=1.0,
        lifecycle_state=MemoryLifecycleState.PERSISTED,
    )
    record = MemoryLifecycleRecord(
        event=MemoryLifecycleEvent.RETRIEVED,
        memory=metadata,
        occurred_at=created_at,
        actor="context_engine.builder",
        reason="Inject working memory",
        identity_context=identity,
    )
    legacy_record = record.to_state()
    legacy_record.pop("identity_context")

    assert MemoryLifecycleRecord.from_state(record.to_state()).identity_context == identity
    assert MemoryLifecycleRecord.from_state(legacy_record).identity_context is None
