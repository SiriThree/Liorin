"""Environment-driven production platform configuration."""
from __future__ import annotations

from dataclasses import dataclass
import os


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class ProductionSettings:
    storage_backend: str = "memory"
    postgres_dsn: str = "postgresql://liorin:liorin@postgres:5432/liorin"
    postgres_schema: str = "liorin"
    redis_enabled: bool = False
    redis_url: str = "redis://redis:6379/0"
    cache_ttl_seconds: int = 60
    retry_attempts: int = 3
    backend_timeout_seconds: float = 3.0
    circuit_failure_threshold: int = 5
    circuit_recovery_seconds: float = 30.0
    observability_enabled: bool = True
    metrics_exporter: str = "prometheus"
    tool_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "ProductionSettings":
        return cls(
            storage_backend=os.getenv("LIORIN_STORAGE_BACKEND", "memory").strip().casefold(),
            postgres_dsn=os.getenv("LIORIN_POSTGRES_DSN", "postgresql://liorin:liorin@postgres:5432/liorin"),
            postgres_schema=os.getenv("LIORIN_POSTGRES_SCHEMA", "liorin"),
            redis_enabled=_bool("LIORIN_REDIS_ENABLED", False),
            redis_url=os.getenv("LIORIN_REDIS_URL", "redis://redis:6379/0"),
            cache_ttl_seconds=int(os.getenv("LIORIN_CACHE_TTL_SECONDS", "60")),
            retry_attempts=int(os.getenv("LIORIN_BACKEND_RETRY_ATTEMPTS", "3")),
            backend_timeout_seconds=float(os.getenv("LIORIN_BACKEND_TIMEOUT_SECONDS", "3")),
            circuit_failure_threshold=int(os.getenv("LIORIN_CIRCUIT_FAILURE_THRESHOLD", "5")),
            circuit_recovery_seconds=float(os.getenv("LIORIN_CIRCUIT_RECOVERY_SECONDS", "30")),
            observability_enabled=_bool("LIORIN_OBSERVABILITY_ENABLED", True),
            metrics_exporter=os.getenv("LIORIN_METRICS_EXPORTER", "prometheus").strip().casefold(),
            tool_timeout_seconds=float(os.getenv("LIORIN_TOOL_TIMEOUT_SECONDS", "30")),
        )

    def __post_init__(self) -> None:
        if self.storage_backend not in {"memory", "postgres"}:
            raise ValueError("LIORIN_STORAGE_BACKEND must be memory or postgres")
        if self.cache_ttl_seconds <= 0 or self.retry_attempts <= 0:
            raise ValueError("cache TTL and retry attempts must be positive")
        if self.backend_timeout_seconds <= 0 or self.tool_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")
        if self.metrics_exporter not in {"prometheus", "opentelemetry", "none"}:
            raise ValueError("LIORIN_METRICS_EXPORTER must be prometheus, opentelemetry, or none")
