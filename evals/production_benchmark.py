"""Deterministic 1,000-request Production Platform benchmark.

This benchmark exercises the real Context/Memory/Artifact runtime without an
external LLM or network database. It measures platform overhead and graceful
degradation, not model answer quality or PostgreSQL throughput.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from math import ceil
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from artifact import ArtifactRegistry, ArtifactResolver, ArtifactType
from context_engine import ContextBuilder, ContextRuntime
from identity import IdentityContext
from memory.facts import InMemoryMemoryFactStore, LongTermMemoryRuntime
from observability import get_default_metrics

REQUEST_COUNT = 1000
USER_COUNT = 100
FAIL_EVERY = 100


def _identity(user_index: int, request_index: int, *, origin: bool = False) -> IdentityContext:
    suffix = "origin" if origin else f"request-{request_index}"
    return IdentityContext(
        tenant_id=f"tenant:{user_index % 10:02d}",
        user_id=f"user:{user_index:03d}",
        conversation_id=f"conversation:{suffix}",
        thread_id=f"thread:{suffix}",
        session_id=f"session:{suffix}",
    )


class FlakySearchBackend:
    def __init__(self, backend: Any, fail_every: int) -> None:
        self.backend = backend
        self.fail_every = fail_every
        self.search_calls = 0
        self.injected_failures = 0

    def search_fact(self, **kwargs: Any):
        self.search_calls += 1
        if self.search_calls % self.fail_every == 0:
            self.injected_failures += 1
            raise ConnectionError("injected temporary memory backend failure")
        return self.backend.search_fact(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def run_benchmark() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    metrics = get_default_metrics()
    metrics.reset()
    base_store = InMemoryMemoryFactStore()
    writer = LongTermMemoryRuntime(store=base_store)
    for user_index in range(USER_COUNT):
        writer.promote_from_state(
            {"user_confirmed_facts": {"product_model": f"LF-{900 + user_index}"}},
            identity_context=_identity(user_index, 0, origin=True),
            actor="evals.production_benchmark",
            reason="seed stable device model",
            now=now,
        )

    flaky_store = FlakySearchBackend(base_store, FAIL_EVERY)
    memory_runtime = LongTermMemoryRuntime(store=flaky_store)
    artifact_registry = ArtifactRegistry()
    artifact_resolver = ArtifactResolver(artifact_registry)
    builder = ContextBuilder(
        artifact_registry=artifact_registry,
        long_term_memory_runtime=memory_runtime,
    )
    context_runtime = ContextRuntime(
        max_tokens=768,
        builder=builder,
        artifact_registry=artifact_registry,
        long_term_memory_runtime=memory_runtime,
    )

    latencies_ms: list[float] = []
    memory_hits = 0
    artifact_retrieval_success = 0
    request_success = 0
    recovered_failures = 0
    before_tokens = 0
    after_tokens = 0

    for request_index in range(1, REQUEST_COUNT + 1):
        user_index = (request_index - 1) % USER_COUNT
        identity = _identity(user_index, request_index)
        payload = {
            "tool": "knowledge_agent",
            "request_index": request_index,
            "content": "diagnostic-observation " * 256,
        }
        artifact = artifact_registry.create_artifact(
            artifact_type=ArtifactType.TOOL_RESULT,
            identity_context=identity,
            source=f"benchmark.tool:{request_index}",
            created_by="evals.production_benchmark",
            summary=f"diagnostic result {request_index}",
            payload=payload,
        )
        state = {
            "identity_context": identity.to_state(),
            "messages": [{"role": "user", "content": "请按我的设备型号继续排查异常噪音"}],
            "artifact_refs": [{"artifact_id": artifact.artifact_id, "required": True}],
        }
        failure_count_before = flaky_store.injected_failures
        started = perf_counter()
        try:
            selection = context_runtime.select(state)
            restored = artifact_resolver.resolve(
                artifact.artifact_id,
                identity_context=identity,
                actor="evals.production_benchmark",
                reason="verify artifact lazy loading",
            )
        except Exception:
            continue
        latency_ms = (perf_counter() - started) * 1000
        latencies_ms.append(latency_ms)
        request_success += 1
        memory_hits += int(selection.runtime_metadata["long_term_memory"]["fact_count"] > 0)
        artifact_retrieval_success += int(restored == payload)
        if flaky_store.injected_failures > failure_count_before:
            recovered_failures += 1
        payload_tokens = max(1, ceil(len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) / 4))
        before_tokens += payload_tokens + 32
        after_tokens += selection.selected_tokens

    snapshot = metrics.snapshot()
    return {
        "benchmark": "Liorin Production Agent Platform Phase 7",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "requests": REQUEST_COUNT,
            "users": USER_COUNT,
            "tenants": 10,
            "memory_backend": "in-memory reference backend with injected failures",
            "artifact_backend": "in-memory reference backend",
            "external_llm": False,
            "external_postgres": False,
            "external_redis": False,
        },
        "results": {
            "request_success_rate": request_success / REQUEST_COUNT,
            "latency_ms_mean": mean(latencies_ms) if latencies_ms else 0.0,
            "latency_ms_p50": _percentile(latencies_ms, 0.50),
            "latency_ms_p95": _percentile(latencies_ms, 0.95),
            "latency_ms_p99": _percentile(latencies_ms, 0.99),
            "memory_hit_rate": memory_hits / REQUEST_COUNT,
            "artifact_retrieval_success_rate": artifact_retrieval_success / REQUEST_COUNT,
            "injected_backend_failures": flaky_store.injected_failures,
            "failure_recovery_rate": (
                recovered_failures / flaky_store.injected_failures
                if flaky_store.injected_failures else 1.0
            ),
            "context_tokens_before": before_tokens,
            "context_tokens_after": after_tokens,
            "token_reduction_rate": 1.0 - (after_tokens / before_tokens),
            "artifact_saved_tokens": snapshot.get("artifact_saved_tokens", 0.0),
            "backend_failure_count": snapshot.get("backend_failure_count", 0.0),
            "backend_failure_rate": snapshot.get("backend_failure_rate", 0.0),
        },
        "limitations": [
            "No external LLM was called, so completion latency and answer quality are not measured.",
            "PostgreSQL/Redis network throughput is not measured; their adapters are covered by contract tests.",
            "Token counts use the existing provider-neutral estimator.",
        ],
    }


def main() -> None:
    report = run_benchmark()
    output = Path("evals/benchmark/reports/production_phase7_report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
