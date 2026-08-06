"""Unified, replay-safe runtime event contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


class RuntimeEventType(StrEnum):
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    AGENT_FAILED = "AGENT_FAILED"
    MODEL_CALL = "MODEL_CALL"
    CONTEXT_ASSEMBLED = "CONTEXT_ASSEMBLED"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"
    MEMORY_READ = "MEMORY_READ"
    MEMORY_WRITE = "MEMORY_WRITE"
    MEMORY_UPDATE = "MEMORY_UPDATE"
    MEMORY_BLOCK = "MEMORY_BLOCK"
    ARTIFACT_CREATED = "ARTIFACT_CREATED"
    ARTIFACT_REFERENCED = "ARTIFACT_REFERENCED"
    ARTIFACT_RESOLVED = "ARTIFACT_RESOLVED"
    ARTIFACT_DELETED = "ARTIFACT_DELETED"
    BACKEND_RETRY = "BACKEND_RETRY"
    BACKEND_FAILURE = "BACKEND_FAILURE"
    DEGRADATION = "DEGRADATION"


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe(item) for item in value]
    if hasattr(value, "to_state"):
        return _safe(value.to_state())
    return str(value)


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    event_type: RuntimeEventType
    timestamp: datetime
    request_id: str
    conversation_id: str
    thread_id: str
    agent_name: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, RuntimeEventType):
            object.__setattr__(self, "event_type", RuntimeEventType(str(self.event_type).upper()))
        if self.timestamp.tzinfo is None:
            raise ValueError("RuntimeEvent.timestamp must be timezone-aware")
        for field_name in ("request_id", "conversation_id", "thread_id", "agent_name"):
            value = str(getattr(self, field_name) or "").strip()
            if not value:
                raise ValueError(f"RuntimeEvent.{field_name} must not be empty")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "attributes", _safe(dict(self.attributes)))

    @classmethod
    def create(cls, event_type: RuntimeEventType, **kwargs: Any) -> "RuntimeEvent":
        return cls(event_type=event_type, timestamp=datetime.now(timezone.utc), **kwargs)

    def to_state(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "thread_id": self.thread_id,
            "agent_name": self.agent_name,
            "attributes": dict(self.attributes),
        }
