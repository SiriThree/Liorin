"""Deployment health/readiness probes independent of the HTTP framework."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class HealthStatus:
    status: str
    timestamp: str
    checks: dict[str, str]

    def to_state(self) -> dict[str, Any]:
        return {"status": self.status, "timestamp": self.timestamp, "checks": dict(self.checks)}


def health_check(*, memory_backend: Any = None, artifact_backend: Any = None, cache: Any = None) -> HealthStatus:
    checks = {
        "runtime": "ok",
        "memory_backend": "configured" if memory_backend is not None else "not_configured",
        "artifact_backend": "configured" if artifact_backend is not None else "not_configured",
        "cache": "configured" if cache is not None else "disabled",
    }
    status = "ok" if memory_backend is not None and artifact_backend is not None else "degraded"
    return HealthStatus(status, datetime.now(timezone.utc).isoformat(), checks)
