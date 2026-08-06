"""Bounded retry primitives for transient infrastructure failures."""
from __future__ import annotations

from dataclasses import dataclass
import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: float = 0.05
    max_delay_seconds: float = 1.0
    multiplier: float = 2.0
    jitter_ratio: float = 0.1
    retryable_exceptions: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError, OSError)

    def __post_init__(self) -> None:
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be greater than zero")
        if self.initial_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays must not be negative")
        if self.multiplier < 1:
            raise ValueError("retry multiplier must be at least 1")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")

    def execute(
        self,
        operation: Callable[[], T],
        *,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
        on_retry: Callable[[BaseException, int, float], None] | None = None,
    ) -> T:
        delay = self.initial_delay_seconds
        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except self.retryable_exceptions as exc:
                if attempt >= self.max_attempts:
                    raise
                jitter = delay * self.jitter_ratio * ((random_value() * 2) - 1)
                wait = max(0.0, min(self.max_delay_seconds, delay + jitter))
                if on_retry is not None:
                    on_retry(exc, attempt, wait)
                sleep(wait)
                delay = min(self.max_delay_seconds, max(delay, 0.001) * self.multiplier)
        raise RuntimeError("retry policy exhausted without result")
