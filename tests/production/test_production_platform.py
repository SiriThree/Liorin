from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml

from artifact import (
    ArtifactRegistry,
    ArtifactResolver,
    ArtifactType,
    reset_default_artifact_registry,
)
from context_engine import ContextBuilder, ContextRuntime
from eval_platform import EvaluationDataset, EvaluationRunner, EvaluationScenario
from identity import IdentityContext
from memory.facts import (
    InMemoryMemoryFactStore,
    LongTermMemoryRuntime,
    reset_default_long_term_memory_runtime,
)
from observability import (
    RuntimeEventType,
    get_default_metrics,
    get_default_trace_recorder,
)
from production import ProductionSettings, bootstrap_production_runtime
from reliability import CircuitBreaker, CircuitOpenError, RetryPolicy
from storage.artifact_backend import BackendArtifactStoreAdapter
from storage.backends import (
    PostgresArtifactBackend,
    PostgresMemoryBackend,
    sqlite_connection_factory,
)
from storage.cache.adapters import CachedMemoryBackend
from storage.cache.memory import InMemoryTTLCache


def identity(*, session: str = "session:s1") -> IdentityContext:
    return IdentityContext(
        "tenant:t1",
        "user:u1",
        "conversation:c1",
        "thread:t1",
        session,
    )


def test_backend_switch_preserves_runtime_behavior(tmp_path: Path):
    now = datetime(2026, 8, 6, 7, 0, tzinfo=timezone.utc)
    state = {"user_confirmed_facts": {"product_model": "LF-900"}}

    in_memory = LongTermMemoryRuntime(store=InMemoryMemoryFactStore())
    memory_result = in_memory.promote_from_state(
        state,
        identity_context=identity(),
        actor="test",
        reason="backend switch baseline",
        now=now,
    )

    database_path = tmp_path / "liorin.sqlite"
    factory = sqlite_connection_factory(database_path)
    postgres = PostgresMemoryBackend(
        connection_factory=factory,
        dialect="sqlite",
        schema="liorin",
    )
    production = LongTermMemoryRuntime(store=postgres)
    production_result = production.promote_from_state(
        state,
        identity_context=identity(),
        actor="test",
        reason="backend switch production",
        now=now,
    )

    assert [fact.to_state() | {"created_at": None, "updated_at": None} for fact in memory_result.persisted_facts] == [
        fact.to_state() | {"created_at": None, "updated_at": None}
        for fact in production_result.persisted_facts
    ]
    retrieved = production.retrieve_for_context(
        "我的设备型号是什么？",
        identity_context=identity(session="session:s2"),
        now=now,
    )
    assert [fact.value for fact in retrieved.facts] == ["LF-900"]
    assert len(postgres.pending_audit_records()) == 1


def test_postgres_artifact_backend_switch(tmp_path: Path):
    factory = sqlite_connection_factory(tmp_path / "artifacts.sqlite")
    backend = PostgresArtifactBackend(
        connection_factory=factory,
        dialect="sqlite",
        schema="liorin",
    )
    registry = ArtifactRegistry(store=BackendArtifactStoreAdapter(backend))
    artifact = registry.create_artifact(
        artifact_type=ArtifactType.TOOL_RESULT,
        identity_context=identity(),
        source="test.tool",
        created_by="test",
        summary="tool result",
        payload={"rows": [1, 2, 3]},
    )
    registry.reference_artifact(
        artifact.artifact_id,
        identity_context=identity(),
        actor="test",
        reason="context reference",
    )

    restored = backend.get_artifact(artifact.artifact_id, identity_context=identity())
    assert restored.payload == {"rows": [1, 2, 3]}
    assert restored.status.value == "REFERENCED"


def test_cache_hit_miss_and_invalidation():
    class CountingBackend(InMemoryMemoryFactStore):
        def __init__(self):
            super().__init__()
            self.get_count = 0

        def get_fact(self, fact_id, *, identity_context):
            self.get_count += 1
            return super().get_fact(fact_id, identity_context=identity_context)

    now = datetime(2026, 8, 6, 7, 0, tzinfo=timezone.utc)
    backend = CountingBackend()
    cached = CachedMemoryBackend(backend, InMemoryTTLCache(default_ttl_seconds=60))
    runtime = LongTermMemoryRuntime(store=cached)
    [fact] = runtime.promote_from_state(
        {"user_confirmed_facts": {"product_model": "LF-900"}},
        identity_context=identity(),
        actor="test",
        reason="cache test",
        now=now,
    ).persisted_facts

    cached.get_fact(fact.fact_id, identity_context=identity())
    cached.get_fact(fact.fact_id, identity_context=identity())
    assert backend.get_count == 1  # promotion read misses once; both reads hit cached write

    updated = fact.with_update(
        value="LF-901",
        source=fact.source,
        confidence=fact.confidence,
        verified=fact.verified,
        observed_at=now,
        verified_at=fact.verified_at,
        verified_by=fact.verified_by,
        expires_at=fact.expires_at,
        updated_at=now,
    )
    cached.update_fact(updated)
    assert cached.get_fact(fact.fact_id, identity_context=identity()).value == "LF-901"


def test_trace_complete_for_context_memory_and_artifact():
    recorder = get_default_trace_recorder()
    recorder.clear()
    get_default_metrics().reset()
    now = datetime(2026, 8, 6, 7, 0, tzinfo=timezone.utc)
    memory_runtime = LongTermMemoryRuntime(store=InMemoryMemoryFactStore())
    registry = ArtifactRegistry()

    with recorder.trace(
        request_id="request:trace-complete",
        conversation_id=identity().conversation_id,
        thread_id=identity().thread_id,
        agent_name="conversation_supervisor",
    ) as trace:
        memory_runtime.promote_from_state(
            {"user_confirmed_facts": {"product_model": "LF-900"}},
            identity_context=identity(),
            actor="test",
            reason="trace memory write",
            now=now,
        )
        artifact = registry.create_artifact(
            artifact_type=ArtifactType.TOOL_RESULT,
            identity_context=identity(),
            source="test.tool",
            created_by="test",
            summary="large result",
            payload="x" * 4000,
        )
        ArtifactResolver(registry).resolve(
            artifact.artifact_id,
            identity_context=identity(),
        )
        state = {
            "identity_context": identity().to_state(),
            "messages": [{"role": "user", "content": "请按设备型号继续排查"}],
            "artifact_refs": [{"artifact_id": artifact.artifact_id, "required": True}],
        }
        ContextRuntime(
            max_tokens=512,
            builder=ContextBuilder(
                artifact_registry=registry,
                long_term_memory_runtime=memory_runtime,
            ),
            artifact_registry=registry,
            long_term_memory_runtime=memory_runtime,
        ).select(state)

    event_types = {event.event_type for event in trace.events}
    assert RuntimeEventType.AGENT_STARTED in event_types
    assert RuntimeEventType.MEMORY_WRITE in event_types
    assert RuntimeEventType.ARTIFACT_CREATED in event_types
    assert RuntimeEventType.ARTIFACT_RESOLVED in event_types
    assert RuntimeEventType.CONTEXT_ASSEMBLED in event_types
    assert RuntimeEventType.AGENT_COMPLETED in event_types
    context_event = next(event for event in trace.events if event.event_type is RuntimeEventType.CONTEXT_ASSEMBLED)
    assert context_event.attributes["token_count"] > 0
    assert context_event.attributes["artifact_reference_count"] >= 1
    assert context_event.attributes["memory_hits"] == 1
    assert trace.replay() == tuple(sorted(trace.replay(), key=lambda item: item["timestamp"]))


def test_metric_collection_from_real_runtime():
    get_default_metrics().reset()
    now = datetime(2026, 8, 6, 7, 0, tzinfo=timezone.utc)
    runtime = LongTermMemoryRuntime(store=InMemoryMemoryFactStore())
    runtime.promote_from_state(
        {"user_confirmed_facts": {"product_model": "LF-900"}},
        identity_context=identity(),
        actor="test",
        reason="metrics write",
        now=now,
    )
    ContextRuntime(
        max_tokens=256,
        builder=ContextBuilder(long_term_memory_runtime=runtime),
        long_term_memory_runtime=runtime,
    ).select({
        "identity_context": identity(session="session:s2").to_state(),
        "messages": [{"role": "user", "content": "设备型号是什么"}],
    })
    snapshot = get_default_metrics().snapshot()
    assert snapshot["memory_write"] == 1
    assert snapshot["memory_read"] >= 1
    assert snapshot["context_selection_count"] >= 1
    assert snapshot["context_tokens"] > 0
    assert snapshot["memory_latency_ms_count"] >= 1


def test_failure_recovery_and_circuit_breaker():
    class FailedBackend:
        def get_fact(self, *args, **kwargs):
            raise ConnectionError("database unavailable")

        def search_fact(self, *args, **kwargs):
            raise ConnectionError("database unavailable")

        def save_fact(self, *args, **kwargs):
            raise ConnectionError("database unavailable")

        update_fact = save_fact
        delete_fact = save_fact
        list_facts = search_fact

    runtime = LongTermMemoryRuntime(store=FailedBackend())
    retrieval = runtime.retrieve_for_context(
        "设备型号",
        identity_context=identity(),
    )
    promotion = runtime.promote_from_state(
        {"user_confirmed_facts": {"product_model": "LF-900"}},
        identity_context=identity(),
        actor="test",
        reason="backend failure",
    )
    assert retrieval.facts == ()
    assert promotion.persisted_facts == ()
    assert promotion.failure_count == 1

    clock = [0.0]
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=10, clock=lambda: clock[0])
    for _ in range(2):
        with pytest.raises(ConnectionError):
            breaker.execute(lambda: (_ for _ in ()).throw(ConnectionError("x")))
    with pytest.raises(CircuitOpenError):
        breaker.execute(lambda: "blocked")
    clock[0] = 11.0
    assert breaker.execute(lambda: "recovered") == "recovered"


def test_unified_evaluation_platform_uses_runtime_trace():
    recorder = get_default_trace_recorder()
    recorder.clear()
    dataset = EvaluationDataset.from_iterable(
        "production-smoke",
        [EvaluationScenario("case-1", {"value": 2}, {"value": 4})],
    )
    runner = EvaluationRunner(
        lambda inputs: {"value": inputs["value"] * 2},
        evaluators={
            "task_success": lambda scenario, output, trace: {
                "task_success": float(output == scenario.expected),
                "trace_complete": float(len(trace["events"]) >= 1),
            }
        },
        trace_recorder=recorder,
    )
    report = runner.run(dataset)
    assert report.success_rate == 1.0
    assert report.metrics["task_success"] == 1.0
    assert report.results[0].trace["request_id"].startswith("eval:")


def test_deployment_config_contains_required_services():
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "deploy" / "docker-compose.yml").read_text())
    services = config["services"]
    assert {"agent-api", "postgres", "redis", "otel-collector", "prometheus"} <= set(services)
    assert services["agent-api"]["healthcheck"]
    env_text = (root / "deploy" / ".env.example").read_text()
    assert "LIORIN_STORAGE_BACKEND=postgres" in env_text
    assert "LIORIN_REDIS_ENABLED=true" in env_text


def test_production_bootstrap_switches_existing_defaults():
    runtime = bootstrap_production_runtime(
        ProductionSettings(storage_backend="memory", redis_enabled=False)
    )
    assert runtime.memory_backend is not None
    assert runtime.artifact_backend is not None
    assert runtime.cache is not None
    reset_default_long_term_memory_runtime()
    reset_default_artifact_registry()


def test_builtin_evaluators_cover_context_memory_artifact_and_agent():
    from eval_platform import BUILTIN_EVALUATORS

    scenario = EvaluationScenario(
        "builtin-case",
        {"value": 1},
        {
            "context_tokens_before": 1000,
            "state_preserved": True,
            "memory_fact_ids": ["fact:1"],
            "artifact_ids": ["artifact:1"],
            "artifact_recovery": True,
            "task_success": True,
            "tool_names": ["knowledge_agent"],
            "fallback": False,
        },
    )
    output = {
        "context_tokens_after": 250,
        "state_preserved": True,
        "memory_fact_ids": ["fact:1"],
        "artifact_ids": ["artifact:1"],
        "artifact_recovery": True,
        "task_success": True,
        "tool_names": ["knowledge_agent"],
        "fallback": False,
    }
    scores = {}
    for evaluator in BUILTIN_EVALUATORS.values():
        scores.update(evaluator(scenario, output, {}))
    assert scores["context_token_reduction"] == 0.75
    assert scores["memory_precision"] == 1.0
    assert scores["artifact_recovery_success"] == 1.0
    assert scores["tool_correctness"] == 1.0


def test_memory_mutation_invalidates_identity_context_cache():
    from storage.cache.context import ContextAssemblyCache

    cache = InMemoryTTLCache(default_ttl_seconds=60)
    context_cache = ContextAssemblyCache(cache, ttl_seconds=60)
    backend = CachedMemoryBackend(
        InMemoryMemoryFactStore(),
        cache,
        on_invalidate=context_cache.invalidate_identity,
    )
    runtime = LongTermMemoryRuntime(store=backend)
    state = {
        "identity_context": identity().to_state(),
        "messages": [{"role": "user", "content": "设备型号是什么"}],
    }
    key = context_cache.key(state, max_tokens=256, options={})
    cache.set(key, {"sentinel": True})
    assert cache.get(key) == {"sentinel": True}

    runtime.promote_from_state(
        {"user_confirmed_facts": {"product_model": "LF-900"}},
        identity_context=identity(),
        actor="test",
        reason="invalidate stale context",
        now=datetime(2026, 8, 6, 7, 0, tzinfo=timezone.utc),
    )
    assert cache.get(key) is None


def test_context_cache_hit_preserves_runtime_metrics():
    from storage.cache.context import ContextAssemblyCache

    get_default_metrics().reset()
    cache = InMemoryTTLCache(default_ttl_seconds=60)
    runtime = ContextRuntime(
        max_tokens=256,
        context_cache=ContextAssemblyCache(cache, ttl_seconds=60),
        long_term_memory_enabled=False,
    )
    state = {
        "identity_context": identity().to_state(),
        "messages": [{"role": "user", "content": "测试缓存指标"}],
    }
    first = runtime.select(state)
    second = runtime.select(state)
    snapshot = get_default_metrics().snapshot()
    assert first.to_state() == second.to_state()
    assert snapshot["context_selection_count"] == 2
    assert snapshot["context_cache_hit"] == 1
    assert snapshot["context_tokens"] == first.selected_tokens * 2


def test_postgres_artifact_backend_rejects_owner_collision(tmp_path: Path):
    factory = sqlite_connection_factory(tmp_path / "artifact-owner.sqlite")
    backend = PostgresArtifactBackend(
        connection_factory=factory,
        dialect="sqlite",
        schema="liorin",
    )
    registry = ArtifactRegistry(store=BackendArtifactStoreAdapter(backend))
    artifact = registry.create_artifact(
        artifact_id="artifact:fixed-id",
        artifact_type=ArtifactType.TOOL_RESULT,
        identity_context=identity(),
        source="test.tool",
        created_by="test",
        summary="owner-bound artifact",
        payload={"ok": True},
    )
    other_identity = IdentityContext(
        "tenant:t1", "user:u2", "conversation:c2", "thread:t2", "session:s2"
    )
    with pytest.raises(PermissionError):
        backend.save_artifact(replace(artifact, identity_context=other_identity))


def test_trusted_request_identity_cannot_be_overridden():
    from production.request_identity import (
        RequestIdentityMismatch,
        TrustedRequestIdentity,
        bind_trusted_identity,
    )

    trusted = TrustedRequestIdentity(
        "tenant:t1", "user:u1", "conversation:c1", "thread:t1", "session:s1"
    )
    state, config = bind_trusted_identity(
        {"messages": [{"role": "user", "content": "hello"}]},
        {},
        trusted,
    )
    assert state["identity_context"] == identity().to_state()
    assert config["configurable"]["thread_id"] == "thread:t1"

    with pytest.raises(RequestIdentityMismatch):
        bind_trusted_identity(
            {"identity_context": IdentityContext(
                "tenant:t1", "user:attacker", "conversation:c1", "thread:t1", "session:s1"
            ).to_state()},
            {},
            trusted,
        )
    with pytest.raises(RequestIdentityMismatch):
        bind_trusted_identity({}, {"configurable": {"thread_id": "thread:other"}}, trusted)
