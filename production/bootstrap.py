"""Wire production infrastructure into existing runtime interfaces."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from artifact import ArtifactRegistry, set_default_artifact_registry
from memory.facts.runtime import LongTermMemoryRuntime, set_default_long_term_memory_runtime
from memory.facts.store import set_default_memory_fact_store
from observability import OpenTelemetryMetricsExporter, PrometheusTextExporter, get_default_metrics
from reliability import CircuitBreaker, ResilientBackend, RetryPolicy
from storage.artifact_backend import ArtifactStoreBackendAdapter, BackendArtifactStoreAdapter
from storage.backends import PostgresArtifactBackend, PostgresMemoryBackend, RedisCacheAdapter
from storage.cache.adapters import CachedArtifactBackend, CachedMemoryBackend
from storage.cache.context import ContextAssemblyCache, set_default_context_cache
from storage.cache.memory import InMemoryTTLCache
from storage.memory_backend import InMemoryMemoryBackend
from artifact.store import InMemoryArtifactStore
from production.config import ProductionSettings


@dataclass(frozen=True, slots=True)
class ProductionRuntime:
    settings: ProductionSettings
    memory_backend: Any
    artifact_backend: Any
    cache: Any | None
    metrics_exporter: Any | None


def _resilient(backend: Any, settings: ProductionSettings) -> Any:
    return ResilientBackend(
        backend,
        retry_policy=RetryPolicy(max_attempts=settings.retry_attempts),
        circuit_breaker=CircuitBreaker(
            failure_threshold=settings.circuit_failure_threshold,
            recovery_timeout_seconds=settings.circuit_recovery_seconds,
        ),
        on_retry=lambda _exc, _attempt, _delay: get_default_metrics().increment("retry_count"),
        timeout_seconds=settings.backend_timeout_seconds,
    )


def bootstrap_production_runtime(settings: ProductionSettings | None = None) -> ProductionRuntime:
    settings = settings or ProductionSettings.from_env()
    if settings.storage_backend == "postgres":
        memory_backend: Any = PostgresMemoryBackend(dsn=settings.postgres_dsn, schema=settings.postgres_schema)
        artifact_backend: Any = PostgresArtifactBackend(dsn=settings.postgres_dsn, schema=settings.postgres_schema)
    else:
        memory_backend = InMemoryMemoryBackend()
        artifact_backend = ArtifactStoreBackendAdapter(InMemoryArtifactStore())

    cache = None
    if settings.redis_enabled:
        cache = RedisCacheAdapter(url=settings.redis_url, default_ttl_seconds=settings.cache_ttl_seconds)
    elif settings.storage_backend == "memory":
        # Local reference cache exercises the same adapters without becoming a source of truth.
        cache = InMemoryTTLCache(default_ttl_seconds=settings.cache_ttl_seconds)

    if cache is not None:
        context_cache = ContextAssemblyCache(cache, ttl_seconds=min(30, settings.cache_ttl_seconds))
        memory_backend = CachedMemoryBackend(
            memory_backend,
            cache,
            ttl_seconds=settings.cache_ttl_seconds,
            on_invalidate=context_cache.invalidate_identity,
        )
        artifact_backend = CachedArtifactBackend(
            artifact_backend,
            cache,
            ttl_seconds=settings.cache_ttl_seconds,
            on_invalidate=context_cache.invalidate_identity,
        )
        set_default_context_cache(context_cache)
    else:
        set_default_context_cache(None)

    memory_backend = _resilient(memory_backend, settings)
    artifact_backend = _resilient(artifact_backend, settings)

    set_default_memory_fact_store(memory_backend)
    set_default_long_term_memory_runtime(LongTermMemoryRuntime(store=memory_backend))
    registry = ArtifactRegistry(store=BackendArtifactStoreAdapter(artifact_backend))
    set_default_artifact_registry(registry)

    exporter = None
    if settings.observability_enabled and settings.metrics_exporter == "prometheus":
        exporter = PrometheusTextExporter()
        get_default_metrics().exporters.append(exporter)
    elif settings.observability_enabled and settings.metrics_exporter == "opentelemetry":
        exporter = OpenTelemetryMetricsExporter()
        get_default_metrics().exporters.append(exporter)

    return ProductionRuntime(settings, memory_backend, artifact_backend, cache, exporter)
