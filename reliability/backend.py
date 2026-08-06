"""Retry and circuit-breaker decorators over existing storage interfaces."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reliability.circuit_breaker import CircuitBreaker
from reliability.retry import RetryPolicy
from reliability.timeout import execute_with_timeout


@dataclass(slots=True)
class ResilientBackend:
    backend: Any
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    on_retry: Any = None
    timeout_seconds: float | None = None

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        raw_operation = lambda: getattr(self.backend, name)(*args, **kwargs)
        operation = (
            (lambda: execute_with_timeout(raw_operation, self.timeout_seconds))
            if self.timeout_seconds is not None
            else raw_operation
        )
        return self.circuit_breaker.execute(
            lambda: self.retry_policy.execute(operation, on_retry=self.on_retry)
        )

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self.backend, name)
        if not callable(attribute):
            return attribute
        return lambda *args, **kwargs: self._call(name, *args, **kwargs)
