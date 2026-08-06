"""Thread-safe TTL cache used for tests and local fallback."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
import time
from typing import Any, Callable


@dataclass(slots=True)
class InMemoryTTLCache:
    default_ttl_seconds: int = 60
    clock: Callable[[], float] = time.monotonic
    _values: dict[str, tuple[float | None, Any]] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)
    hits: int = 0
    misses: int = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._values.get(key)
            if row is None:
                self.misses += 1
                return None
            expires_at, value = row
            if expires_at is not None and expires_at <= self.clock():
                self._values.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        ttl = self.default_ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl is not None and ttl < 0:
            raise ValueError("cache ttl must not be negative")
        expires_at = None if ttl in (None, 0) else self.clock() + ttl
        with self._lock:
            self._values[key] = (expires_at, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [key for key in self._values if key.startswith(prefix)]
            for key in keys:
                self._values.pop(key, None)
            return len(keys)
