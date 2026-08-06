from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from context_engine import ContextBuilder, ContextItemType, ContextRuntime
from identity import IdentityContext
from memory.facts import (
    InMemoryMemoryFactStore,
    LongTermMemoryRuntime,
    MemoryCandidateExtractor,
    MemoryFact,
    MemoryFactCandidate,
    MemoryFactPolicy,
    MemoryFactSource,
)
from memory.working import WorkingMemory


def _identity(
    user: str = "user:u1",
    *,
    tenant: str = "tenant:t1",
    conversation: str = "conversation:c1",
    thread: str = "thread:t1",
    session: str = "session:s1",
) -> IdentityContext:
    return IdentityContext(tenant, user, conversation, thread, session)


def _runtime() -> LongTermMemoryRuntime:
    return LongTermMemoryRuntime(store=InMemoryMemoryFactStore())


def test_memory_fact_model():
    now = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    fact = MemoryFact(
        fact_id="memory-fact:1",
        identity_context=_identity(),
        key="product_model",
        value="LF-900",
        source=MemoryFactSource.USER_CONFIRMATION.value,
        confidence=1.0,
        verified=True,
        observed_at=now,
        verified_at=now,
        verified_by="user",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(days=365),
    )

    state = fact.to_state()
    restored = MemoryFact.from_state(json.loads(json.dumps(state)))

    assert restored == fact
    assert restored.is_owned_by(_identity(conversation="conversation:c2", thread="thread:t2", session="session:s2"))
    assert restored.is_expired(now=now + timedelta(days=366))


def test_legacy_working_memory_fact_is_conservative():
    now = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    working = WorkingMemory(
        session_id="session:s1",
        confirmed_facts=("product_model=LF-900",),
        last_updated=now,
    )
    [candidate] = MemoryCandidateExtractor().extract(
        {"working_memory": working.to_state()},
        identity_context=_identity(),
        working_memory=working,
        now=now,
    )

    assert candidate.source == "legacy_checkpoint"
    assert candidate.confidence == 0.5
    assert candidate.verified is False
    assert MemoryFactPolicy().evaluate(candidate, now=now).approved is False


def test_memory_fact_identity_isolation():
    now = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    runtime = _runtime()
    result = runtime.promote_from_state(
        {"user_confirmed_facts": {"product_model": "LF-900"}},
        identity_context=_identity("user:u1"),
        actor="test",
        reason="user confirmed model",
        now=now,
    )
    fact = result.persisted_facts[0]

    with pytest.raises(PermissionError):
        runtime.get(fact.fact_id, identity_context=_identity("user:u2"))

    other_results = runtime.retrieve_for_context(
        "我的设备型号是什么？",
        identity_context=_identity("user:u2"),
        now=now,
    )
    assert other_results.facts == ()


def test_memory_candidate_policy():
    now = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    policy = MemoryFactPolicy()
    approved = MemoryFactCandidate(
        identity_context=_identity(),
        key="product_model",
        value="LF-900",
        source="user_confirmation",
        confidence=1.0,
        verified=True,
        observed_at=now,
        verified_at=now,
        verified_by="user",
        reason="explicit confirmation",
        metadata={"stable": True, "future_reuse": True},
    )
    rejected = MemoryFactCandidate(
        identity_context=_identity(),
        key="product_model",
        value="maybe LF-900",
        source="agent_inference",
        confidence=0.6,
        verified=False,
        observed_at=now,
        reason="agent guessed",
        metadata={"stable": True, "future_reuse": True},
    )

    assert policy.evaluate(approved, now=now).approved is True
    decision = policy.evaluate(rejected, now=now)
    assert decision.approved is False
    assert "source/confidence" in decision.reason or "inference" in decision.reason


def test_memory_delta_integration():
    t0 = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    runtime = _runtime()
    state = {"user_confirmed_facts": {"product_model": "LF-900"}}

    first = runtime.promote_from_state(
        state,
        identity_context=_identity(),
        actor="test",
        reason="user confirmed model",
        now=t0,
    )
    second = runtime.promote_from_state(
        state,
        identity_context=_identity(),
        actor="test",
        reason="same structured state processed again",
        now=t0 + timedelta(minutes=1),
    )

    assert len(first.persisted_facts) == 1
    assert len(first.lifecycle_records) == 3
    assert second.noop_count == 1
    assert second.persisted_facts == ()
    assert second.lifecycle_records == ()
    assert runtime.store.count() == 1


def test_memory_retrieval_returns_only_relevant_fact():
    now = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    runtime = _runtime()
    runtime.promote_from_state(
        {
            "user_confirmed_facts": {
                "product_model": "LF-900",
                "preferred_language": "中文",
                "region": "中国大陆",
            }
        },
        identity_context=_identity(),
        actor="test",
        reason="user confirmed stable profile facts",
        now=now,
    )

    result = runtime.retrieve_for_context(
        {"messages": [{"role": "user", "content": "我的设备型号是什么？"}]},
        identity_context=_identity(conversation="conversation:c2", thread="thread:t2", session="session:s2"),
        limit=3,
        now=now,
    )

    assert [fact.key for fact in result.facts] == ["product_model"]
    assert result.facts[0].value == "LF-900"


def test_memory_context_injection():
    now = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    runtime = _runtime()
    origin = _identity()
    current = _identity(
        conversation="conversation:c2",
        thread="thread:t2",
        session="session:s2",
    )
    runtime.promote_from_state(
        {"user_confirmed_facts": {"product_model": "LF-900"}},
        identity_context=origin,
        actor="test",
        reason="session A confirmation",
        now=now,
    )
    state = {
        "identity_context": current.to_state(),
        "messages": [{"role": "user", "content": "请按我的设备型号继续排查"}],
    }
    builder = ContextBuilder(long_term_memory_runtime=runtime)
    items = builder.build(messages_state=state)
    memory_items = [
        item
        for item in items
        if item.type is ContextItemType.MEMORY
        and item.metadata.get("memory_kind") == "long_term_fact"
    ]

    assert len(memory_items) == 1
    item = memory_items[0]
    assert item.content == "LF-900"
    assert item.metadata["fact_key"] == "product_model"
    assert item.metadata["verified"] is True
    assert item.metadata["identity_context"] == current.to_state()
    assert item.metadata["origin_identity_context"] == origin.to_state()

    selection = ContextRuntime(
        max_tokens=512,
        builder=builder,
        long_term_memory_runtime=runtime,
    ).select(state)
    assert selection.runtime_metadata["long_term_memory"]["fact_count"] == 1


def test_expired_memory_not_injected():
    t0 = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    runtime = _runtime()
    runtime.promote_from_state(
        {
            "memory_fact_candidates": [
                {
                    "key": "product_model",
                    "value": "LF-OLD",
                    "source": "user_confirmation",
                    "confidence": 1.0,
                    "verified": True,
                    "verified_by": "user",
                    "verified_at": t0,
                    "expires_at": t0 + timedelta(hours=1),
                    "metadata": {"stable": True, "future_reuse": True},
                }
            ]
        },
        identity_context=_identity(),
        actor="test",
        reason="temporary confirmed model",
        now=t0,
    )
    later = t0 + timedelta(hours=2)
    result = runtime.retrieve_for_context(
        "我的设备型号是什么？",
        identity_context=_identity(
            conversation="conversation:c2",
            thread="thread:t2",
            session="session:s2",
        ),
        now=later,
    )

    assert result.facts == ()
    assert len(result.expired_fact_ids) == 1
    assert any(record.event.value == "EXPIRED" for record in runtime.lifecycle_records())


def test_memory_fact_update_delete_lifecycle():
    t0 = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)
    runtime = _runtime()
    first = runtime.promote_from_state(
        {"user_confirmed_facts": {"product_model": "LF-900"}},
        identity_context=_identity(),
        actor="test",
        reason="initial model",
        now=t0,
    )
    fact_id = first.persisted_facts[0].fact_id
    updated = runtime.promote_from_state(
        {"user_confirmed_facts": {"product_model": "LF-901"}},
        identity_context=_identity(
            conversation="conversation:c2",
            thread="thread:t2",
            session="session:s2",
        ),
        actor="test",
        reason="user corrected model",
        now=t0 + timedelta(minutes=5),
    )

    assert updated.persisted_facts[0].fact_id == fact_id
    assert updated.persisted_facts[0].value == "LF-901"
    assert "value" in updated.items[0].delta.changed_fields

    current_identity = _identity(
        conversation="conversation:c3",
        thread="thread:t3",
        session="session:s3",
    )
    deleted = runtime.delete(
        fact_id,
        identity_context=current_identity,
        actor="test",
        reason="user requested memory deletion",
        now=t0 + timedelta(minutes=10),
    )
    assert deleted.value == "LF-901"
    with pytest.raises(KeyError):
        runtime.get(fact_id, identity_context=current_identity)
    assert runtime.lifecycle_records(fact_id=fact_id)[-1].event.value == "DELETED"
