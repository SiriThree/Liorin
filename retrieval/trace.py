"""Central JSON-safe request/stage/evidence trace event construction."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import uuid4

from retrieval.security import hash_identifier, sanitize_for_log


class TraceSink:
    """Bounded centralized trace sink with optional JSONL export.

    LangSmith/LangGraph tracing remains untouched; this sink supplies a stable,
    dependency-free stream for metric aggregation and incident audit.  Set
    ``LIORIN_TRACE_JSONL`` to persist the same sanitized events.
    """

    def __init__(self, *, max_events: int = 20_000, jsonl_path: str | None = None):
        self._events = deque(maxlen=max_events)
        self._lock = Lock()
        configured = jsonl_path if jsonl_path is not None else os.getenv("LIORIN_TRACE_JSONL")
        self.jsonl_path = Path(configured) if configured else None

    def emit(self, event: dict[str, Any]) -> None:
        safe = sanitize_for_log(event)
        with self._lock:
            self._events.append(safe)
            if self.jsonl_path:
                self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
                with self.jsonl_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(safe, ensure_ascii=False, sort_keys=True) + "\n")

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


TRACE_SINK = TraceSink()


def trace_event(
    step: str,
    event: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    subquery_id: str | None = None,
    status: str | None = None,
    source: str | None = None,
    trace_level: str = "stage",
    **data: Any,
) -> dict[str, Any]:
    """Create a structured event without raw PII or identity values.

    Existing ``step/event/data`` keys are retained for checkpoint and benchmark
    compatibility while Stage 4 adds stable event IDs, session/source and level.
    """

    safe_data = sanitize_for_log(data)
    payload = {
        "event_id": uuid4().hex,
        "trace_level": trace_level,
        "step": step,
        "stage": step,
        "event": event,
        "status": status or event,
        "request_id": request_id,
        "session_id": f"hash:{hash_identifier(session_id, namespace='session')}" if session_id else None,
        "source": source,
        "subquery_id": subquery_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "monotonic": perf_counter(),
        "data": safe_data,
    }
    TRACE_SINK.emit(payload)
    return payload
