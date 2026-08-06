"""Identity-bound artifact contracts for Liorin runtime products.

Artifacts are produced intermediate results (tool outputs, evidence payloads,
documents, reports, traces, summaries).  They are deliberately separate from
Working/Long-term Memory, which models facts and task state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
import json
from typing import Any, Mapping

from identity import IdentityContext


class ArtifactType(StrEnum):
    RETRIEVAL_EVIDENCE = "RETRIEVAL_EVIDENCE"
    TOOL_RESULT = "TOOL_RESULT"
    DOCUMENT = "DOCUMENT"
    REPORT = "REPORT"
    TRACE = "TRACE"
    SUMMARY = "SUMMARY"


class ArtifactLifecycleState(StrEnum):
    CREATED = "CREATED"
    AVAILABLE = "AVAILABLE"
    REFERENCED = "REFERENCED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class ArtifactLifecycleEvent(StrEnum):
    CREATED = "CREATED"
    AVAILABLE = "AVAILABLE"
    REFERENCED = "REFERENCED"
    RESOLVED = "RESOLVED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


def _json_safe(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if hasattr(value, "to_state"):
        try:
            return _json_safe(value.to_state())
        except Exception:
            pass
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump(mode="json"))
        except Exception:
            pass
    if hasattr(value, "page_content") and hasattr(value, "metadata"):
        return {
            "page_content": str(getattr(value, "page_content", "")),
            "metadata": _json_safe(getattr(value, "metadata", {}) or {}),
        }
    return str(value)


def payload_size(value: Any) -> int:
    """Return deterministic UTF-8 serialized size for in-memory payloads."""

    rendered = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return len(rendered.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class Artifact:
    """One identity-bound intermediate product and its in-memory payload.

    ``payload`` is owned by the Artifact Store and is never emitted by
    ``to_reference``.  Context Runtime only uses the compact reference view.
    """

    artifact_id: str
    artifact_type: ArtifactType
    identity_context: IdentityContext
    source: str
    created_at: datetime
    created_by: str
    summary: str
    metadata: Mapping[str, Any]
    location: str
    size: int
    status: ArtifactLifecycleState
    payload: Any = None

    def __post_init__(self) -> None:
        artifact_id = str(self.artifact_id).strip()
        if not artifact_id:
            raise ValueError("Artifact.artifact_id must not be empty")
        object.__setattr__(self, "artifact_id", artifact_id)

        if not isinstance(self.artifact_type, ArtifactType):
            raw = str(self.artifact_type)
            try:
                normalized = ArtifactType(raw)
            except ValueError:
                normalized = ArtifactType(raw.upper())
            object.__setattr__(self, "artifact_type", normalized)

        if not isinstance(self.identity_context, IdentityContext):
            if not isinstance(self.identity_context, Mapping):
                raise TypeError("Artifact.identity_context must be IdentityContext or mapping")
            object.__setattr__(
                self,
                "identity_context",
                IdentityContext.from_state(self.identity_context),
            )

        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise ValueError("Artifact.created_at must be timezone-aware")

        source = str(self.source).strip()
        actor = str(self.created_by).strip()
        summary = " ".join(str(self.summary or "").split()).strip()
        location = str(self.location).strip()
        if not source:
            raise ValueError("Artifact.source must not be empty")
        if not actor:
            raise ValueError("Artifact.created_by must not be empty")
        if not summary:
            raise ValueError("Artifact.summary must not be empty")
        if not location:
            raise ValueError("Artifact.location must not be empty")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "created_by", actor)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "location", location)
        object.__setattr__(self, "metadata", _json_safe(dict(self.metadata)))
        object.__setattr__(self, "payload", _json_safe(self.payload))

        size = int(self.size)
        if size < 0:
            raise ValueError("Artifact.size must not be negative")
        object.__setattr__(self, "size", size)

        if not isinstance(self.status, ArtifactLifecycleState):
            raw = str(self.status)
            try:
                status = ArtifactLifecycleState(raw)
            except ValueError:
                status = ArtifactLifecycleState(raw.upper())
            object.__setattr__(self, "status", status)

    def with_status(
        self,
        status: ArtifactLifecycleState,
        *,
        payload: Any = ...,  # preserve unless explicitly replaced
        size: int | None = None,
    ) -> "Artifact":
        updates: dict[str, Any] = {"status": status}
        if payload is not ...:
            updates["payload"] = payload
        if size is not None:
            updates["size"] = size
        return replace(self, **updates)

    def to_state(self, *, include_payload: bool = True) -> dict[str, Any]:
        state = {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "identity_context": self.identity_context.to_state(),
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "summary": self.summary,
            "metadata": dict(self.metadata),
            "location": self.location,
            "size": self.size,
            "status": self.status.value,
        }
        if include_payload:
            state["payload"] = _json_safe(self.payload)
        return state

    def to_reference(self) -> dict[str, Any]:
        """Return the only representation allowed into model context."""

        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "summary": self.summary,
            "source": self.source,
            "location": self.location,
            "size": self.size,
            "status": self.status.value,
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "Artifact":
        created_at = value.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return cls(
            artifact_id=str(value.get("artifact_id") or ""),
            artifact_type=value.get("artifact_type") or "",
            identity_context=IdentityContext.from_state(value.get("identity_context") or {}),
            source=str(value.get("source") or ""),
            created_at=created_at,
            created_by=str(value.get("created_by") or ""),
            summary=str(value.get("summary") or ""),
            metadata=value.get("metadata") or {},
            location=str(value.get("location") or ""),
            size=int(value.get("size", 0)),
            status=value.get("status") or "",
            payload=value.get("payload"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactLifecycleRecord:
    artifact_id: str
    event: ArtifactLifecycleEvent
    identity_context: IdentityContext
    actor: str
    reason: str
    timestamp: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        artifact_id = str(self.artifact_id).strip()
        if not artifact_id:
            raise ValueError("ArtifactLifecycleRecord.artifact_id must not be empty")
        object.__setattr__(self, "artifact_id", artifact_id)

        if not isinstance(self.event, ArtifactLifecycleEvent):
            raw = str(self.event)
            try:
                event = ArtifactLifecycleEvent(raw)
            except ValueError:
                event = ArtifactLifecycleEvent(raw.upper())
            object.__setattr__(self, "event", event)

        if not isinstance(self.identity_context, IdentityContext):
            if not isinstance(self.identity_context, Mapping):
                raise TypeError(
                    "ArtifactLifecycleRecord.identity_context must be IdentityContext or mapping"
                )
            object.__setattr__(
                self,
                "identity_context",
                IdentityContext.from_state(self.identity_context),
            )

        actor = str(self.actor).strip()
        reason = str(self.reason).strip()
        if not actor:
            raise ValueError("ArtifactLifecycleRecord.actor must not be empty")
        if not reason:
            raise ValueError("ArtifactLifecycleRecord.reason must not be empty")
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None:
            raise ValueError("ArtifactLifecycleRecord.timestamp must be timezone-aware")
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "metadata", _json_safe(dict(self.metadata)))

    def to_state(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "event": self.event.value,
            "identity_context": self.identity_context.to_state(),
            "actor": self.actor,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "ArtifactLifecycleRecord":
        timestamp = value.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return cls(
            artifact_id=str(value.get("artifact_id") or ""),
            event=value.get("event") or "",
            identity_context=IdentityContext.from_state(value.get("identity_context") or {}),
            actor=str(value.get("actor") or ""),
            reason=str(value.get("reason") or ""),
            timestamp=timestamp,
            metadata=value.get("metadata") or {},
        )


__all__ = [
    "Artifact",
    "ArtifactLifecycleEvent",
    "ArtifactLifecycleRecord",
    "ArtifactLifecycleState",
    "ArtifactType",
    "payload_size",
]
