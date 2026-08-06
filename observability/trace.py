"""In-process trace recorder with deterministic execution replay data."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from time import perf_counter
from typing import Any, Iterator, Mapping
from uuid import uuid4

from observability.events import RuntimeEvent, RuntimeEventType


@dataclass(slots=True)
class AgentExecutionTrace:
    request_id: str
    conversation_id: str
    thread_id: str
    agent_name: str
    start_time: datetime
    end_time: datetime | None = None
    status: str = "RUNNING"
    events: list[RuntimeEvent] = field(default_factory=list)
    error: str | None = None

    def add(self, event: RuntimeEvent) -> None:
        if event.request_id != self.request_id:
            raise ValueError("event request_id does not match trace")
        self.events.append(event)

    def complete(self, *, status: str = "COMPLETED", error: str | None = None) -> None:
        self.end_time = datetime.now(timezone.utc)
        self.status = status
        self.error = error

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return max(0.0, (self.end_time - self.start_time).total_seconds() * 1000)

    def replay(self) -> tuple[dict[str, Any], ...]:
        """Return ordered, JSON-safe events sufficient to replay decisions."""
        return tuple(event.to_state() for event in sorted(self.events, key=lambda item: item.timestamp))

    def to_state(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "thread_id": self.thread_id,
            "agent_name": self.agent_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "events": list(self.replay()),
        }


_CURRENT_TRACE: ContextVar[AgentExecutionTrace | None] = ContextVar("liorin_current_trace", default=None)


@dataclass(slots=True)
class TraceRecorder:
    _traces: dict[str, AgentExecutionTrace] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    @contextmanager
    def trace(
        self,
        *,
        request_id: str | None = None,
        conversation_id: str,
        thread_id: str,
        agent_name: str,
    ) -> Iterator[AgentExecutionTrace]:
        trace = AgentExecutionTrace(
            request_id=request_id or f"request:{uuid4().hex}",
            conversation_id=conversation_id,
            thread_id=thread_id,
            agent_name=agent_name,
            start_time=datetime.now(timezone.utc),
        )
        with self._lock:
            self._traces[trace.request_id] = trace
        token = _CURRENT_TRACE.set(trace)
        from observability.metrics import get_default_metrics
        metrics = get_default_metrics()
        metrics.increment("agent_request_count")
        self.emit(RuntimeEventType.AGENT_STARTED, attributes={})
        try:
            yield trace
        except Exception as exc:
            metrics.increment("agent_error_count")
            self.emit(RuntimeEventType.AGENT_FAILED, attributes={"error": type(exc).__name__, "detail": str(exc)[:500]})
            trace.complete(status="FAILED", error=f"{type(exc).__name__}: {exc}")
            raise
        else:
            metrics.increment("agent_success_count")
            self.emit(RuntimeEventType.AGENT_COMPLETED, attributes={})
            trace.complete()
        finally:
            _CURRENT_TRACE.reset(token)

    @contextmanager
    def span(self, event_prefix: str, *, attributes: Mapping[str, Any] | None = None) -> Iterator[None]:
        started = perf_counter()
        attrs = dict(attributes or {})
        start_type = RuntimeEventType[f"{event_prefix}_STARTED"]
        completed_type = RuntimeEventType[f"{event_prefix}_COMPLETED"]
        failed_type = RuntimeEventType[f"{event_prefix}_FAILED"]
        self.emit(start_type, attributes=attrs)
        try:
            yield
        except Exception as exc:
            self.emit(failed_type, attributes={**attrs, "latency_ms": (perf_counter() - started) * 1000, "error": type(exc).__name__})
            raise
        else:
            self.emit(completed_type, attributes={**attrs, "latency_ms": (perf_counter() - started) * 1000})

    def emit(
        self,
        event_type: RuntimeEventType,
        *,
        attributes: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        conversation_id: str | None = None,
        thread_id: str | None = None,
        agent_name: str | None = None,
    ) -> RuntimeEvent | None:
        trace = _CURRENT_TRACE.get()
        if trace is None and request_id is None:
            return None
        if trace is not None:
            request_id = request_id or trace.request_id
            conversation_id = conversation_id or trace.conversation_id
            thread_id = thread_id or trace.thread_id
            agent_name = agent_name or trace.agent_name
        assert request_id and conversation_id and thread_id and agent_name
        event = RuntimeEvent.create(
            event_type,
            request_id=request_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            agent_name=agent_name,
            attributes=attributes or {},
        )
        target = trace or self.get(request_id)
        if target is not None:
            with self._lock:
                target.add(event)
        return event

    def current(self) -> AgentExecutionTrace | None:
        return _CURRENT_TRACE.get()

    def get(self, request_id: str) -> AgentExecutionTrace | None:
        with self._lock:
            return self._traces.get(request_id)

    def traces(self) -> tuple[AgentExecutionTrace, ...]:
        with self._lock:
            return tuple(self._traces.values())

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()


_DEFAULT_TRACE_RECORDER = TraceRecorder()


def get_default_trace_recorder() -> TraceRecorder:
    return _DEFAULT_TRACE_RECORDER
