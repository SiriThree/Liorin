"""Thread-safe circuit breaker with CLOSED/OPEN/HALF_OPEN states."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(ConnectionError):
    pass


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0
    clock: Callable[[], float] = time.monotonic
    _state: CircuitState = CircuitState.CLOSED
    _failures: int = 0
    _opened_at: float | None = None
    _lock: RLock = field(default_factory=RLock, repr=False)

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be greater than zero")
        if self.recovery_timeout_seconds < 0:
            raise ValueError("recovery_timeout_seconds must not be negative")

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._refresh()
            return self._state

    def execute(self, operation: Callable[[], T]) -> T:
        with self._lock:
            self._refresh()
            if self._state is CircuitState.OPEN:
                raise CircuitOpenError("circuit breaker is open")
        try:
            result = operation()
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    def record_success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state is CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = self.clock()

    def _refresh(self) -> None:
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and self.clock() - self._opened_at >= self.recovery_timeout_seconds
        ):
            self._state = CircuitState.HALF_OPEN
