"""Best-effort, queryable audit sink for Memory lifecycle records."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class MemoryAuditSink(Protocol):
    def record(self, record: Any) -> None: ...


@dataclass(slots=True)
class InMemoryMemoryAuditLog:
    _records: list[Any] = field(default_factory=list)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def record(self, record: Any) -> None:
        with self._lock:
            self._records.append(record)

    def records(
        self,
        *,
        fact_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        event: str | None = None,
    ) -> tuple[Any, ...]:
        with self._lock:
            result = []
            for record in self._records:
                if fact_id is not None and getattr(getattr(record, "memory", None), "id", None) != fact_id:
                    continue
                identity = getattr(record, "identity_context", None)
                if tenant_id is not None and getattr(identity, "tenant_id", None) != tenant_id:
                    continue
                if user_id is not None and getattr(identity, "user_id", None) != user_id:
                    continue
                actual_event = getattr(getattr(record, "event", None), "value", getattr(record, "event", None))
                if event is not None and actual_event != event:
                    continue
                result.append(record)
            return tuple(result)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


@dataclass(slots=True)
class SafeMemoryAuditHook:
    """Never let an audit backend outage block the customer workflow."""

    sink: MemoryAuditSink
    on_failure: Callable[[Exception], None] | None = None

    def __call__(self, record: Any) -> None:
        try:
            self.sink.record(record)
        except Exception as exc:  # audit is explicitly best effort
            if self.on_failure is not None:
                self.on_failure(exc)


_DEFAULT_AUDIT_LOG = InMemoryMemoryAuditLog()


def get_default_memory_audit_log() -> InMemoryMemoryAuditLog:
    return _DEFAULT_AUDIT_LOG


def reset_default_memory_audit_log() -> InMemoryMemoryAuditLog:
    _DEFAULT_AUDIT_LOG.clear()
    return _DEFAULT_AUDIT_LOG


__all__ = [
    "InMemoryMemoryAuditLog",
    "MemoryAuditSink",
    "SafeMemoryAuditHook",
    "get_default_memory_audit_log",
    "reset_default_memory_audit_log",
]
