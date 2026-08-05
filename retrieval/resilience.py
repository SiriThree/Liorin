"""Bounded retries, circuit breakers, bulkheads and dependency health state."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from random import random
from threading import BoundedSemaphore, Lock
from time import monotonic, sleep
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    pass


class BulkheadRejected(RuntimeError):
    pass


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 3
    recovery_timeout_seconds: float = 30.0
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float | None = None
    last_error: str | None = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def allow_request(self) -> bool:
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self.opened_at is not None and monotonic() - self.opened_at >= self.recovery_timeout_seconds:
                    self.state = CircuitState.HALF_OPEN
                    return True
                return False
            return True

    def before_call(self) -> None:
        if not self.allow_request():
            raise CircuitOpenError(f"circuit {self.name} is open")

    def record_success(self) -> None:
        with self._lock:
            self.state = CircuitState.CLOSED
            self.consecutive_failures = 0
            self.opened_at = None
            self.last_error = None

    def record_failure(self, exc: BaseException) -> None:
        with self._lock:
            self.consecutive_failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            if self.consecutive_failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = monotonic()

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": str(self.state),
            "consecutive_failures": self.consecutive_failures,
            "last_error_type": self.last_error.split(":", 1)[0] if self.last_error else None,
        }


@dataclass
class Bulkhead:
    name: str
    max_concurrency: int
    acquire_timeout_seconds: float = 0.05
    _semaphore: BoundedSemaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._semaphore = BoundedSemaphore(self.max_concurrency)

    def __enter__(self):
        if not self._semaphore.acquire(timeout=self.acquire_timeout_seconds):
            raise BulkheadRejected(f"bulkhead {self.name} is saturated")
        return self

    def __exit__(self, exc_type, exc, tb):
        self._semaphore.release()
        return False


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    base_delay_seconds: float = 0.02
    max_delay_seconds: float = 0.2
    jitter_ratio: float = 0.2

    def delay(self, attempt: int) -> float:
        base = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** max(0, attempt - 1)))
        return max(0.0, base * (1 + (random() * 2 - 1) * self.jitter_ratio))


class DependencyRegistry:
    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._bulkheads: dict[str, Bulkhead] = {}
        self._lock = Lock()

    def breaker(self, name: str, **kwargs: Any) -> CircuitBreaker:
        with self._lock:
            return self._breakers.setdefault(name, CircuitBreaker(name=name, **kwargs))

    def bulkhead(self, name: str, *, max_concurrency: int = 8) -> Bulkhead:
        with self._lock:
            return self._bulkheads.setdefault(name, Bulkhead(name=name, max_concurrency=max_concurrency))

    def health(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: breaker.health() for name, breaker in self._breakers.items()}

    def reset(self) -> None:
        with self._lock:
            self._breakers.clear()
            self._bulkheads.clear()


DEPENDENCIES = DependencyRegistry()


def call_with_resilience(
    dependency: str,
    function: Callable[[], T],
    *,
    retry_policy: RetryPolicy | None = None,
    retry_if: Callable[[BaseException], bool] | None = None,
    max_concurrency: int = 8,
) -> T:
    """Invoke one dependency with bounded retry, circuit breaker and bulkhead."""

    policy = retry_policy or RetryPolicy()
    breaker = DEPENDENCIES.breaker(dependency)
    bulkhead = DEPENDENCIES.bulkhead(dependency, max_concurrency=max_concurrency)
    breaker.before_call()
    last_error: BaseException | None = None
    with bulkhead:
        for attempt in range(1, policy.max_attempts + 1):
            try:
                result = function()
                breaker.record_success()
                return result
            except BaseException as exc:
                last_error = exc
                should_retry = retry_if(exc) if retry_if else True
                if not should_retry or attempt >= policy.max_attempts:
                    breaker.record_failure(exc)
                    raise
                sleep(policy.delay(attempt))
    assert last_error is not None
    raise last_error
