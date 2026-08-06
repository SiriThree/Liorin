"""Core context models used by the Liorin runtime context pipeline.

Phase 1 deliberately models context only.  It does not persist conversation or
long-term memory and it does not introduce a separate agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from math import ceil
from typing import Any, Mapping, Protocol, runtime_checkable

from identity.models import IdentityContext


class ContextItemType(StrEnum):
    """Supported context categories at the model-call boundary."""

    SYSTEM = "SYSTEM"
    USER_MESSAGE = "USER_MESSAGE"
    ASSISTANT_MESSAGE = "ASSISTANT_MESSAGE"
    WORKFLOW_STATE = "WORKFLOW_STATE"
    RETRIEVAL_REFERENCE = "RETRIEVAL_REFERENCE"
    EVIDENCE_REFERENCE = "EVIDENCE_REFERENCE"
    ARTIFACT_REFERENCE = "ARTIFACT_REFERENCE"
    SUMMARY = "SUMMARY"
    # Reserved in Phase 1 so later Memory/Artifact phases can extend the
    # runtime without changing the public ContextItem contract.
    MEMORY = "MEMORY"
    MEMORY_SUMMARY = "MEMORY_SUMMARY"
    USER_PROFILE = "USER_PROFILE"


class MemoryLifecycleEvent(StrEnum):
    """Auditable events emitted by a future memory lifecycle pipeline.

    Phase 1 defines the event vocabulary only.  No event dispatcher, memory
    store or persistence side effect is introduced here.
    """

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    RETRIEVED = "RETRIEVED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class MemoryLifecycleState(StrEnum):
    """Reserved states for Candidate -> Policy -> Persist -> Injection."""

    CANDIDATE = "CANDIDATE"
    POLICY_APPROVED = "POLICY_APPROVED"
    POLICY_REJECTED = "POLICY_REJECTED"
    PERSISTED = "PERSISTED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


@dataclass(frozen=True, slots=True)
class MemoryMetadata:
    """Checkpoint/log-safe identity and lifecycle snapshot for memory.

    This contract intentionally contains no content payload and performs no
    persistence.  It can accompany a future memory candidate, policy decision,
    persisted record or context-injection reference without coupling the
    Context Runtime to a concrete store.
    """

    id: str
    created_at: datetime
    updated_at: datetime
    source: str
    confidence: float
    lifecycle_state: MemoryLifecycleState

    def __post_init__(self) -> None:
        memory_id = str(self.id).strip()
        if not memory_id:
            raise ValueError("MemoryMetadata.id must not be empty")
        object.__setattr__(self, "id", memory_id)

        for field_name in ("created_at", "updated_at"):
            value = getattr(self, field_name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise ValueError(f"MemoryMetadata.{field_name} must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("MemoryMetadata.updated_at must not precede created_at")

        source = str(self.source).strip()
        if not source:
            raise ValueError("MemoryMetadata.source must not be empty")
        object.__setattr__(self, "source", source)

        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("MemoryMetadata.confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)

        if not isinstance(self.lifecycle_state, MemoryLifecycleState):
            raw_state = str(self.lifecycle_state)
            try:
                state = MemoryLifecycleState(raw_state)
            except ValueError:
                state = MemoryLifecycleState(raw_state.upper())
            object.__setattr__(self, "lifecycle_state", state)

    def to_state(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "source": self.source,
            "confidence": self.confidence,
            "lifecycle_state": self.lifecycle_state.value,
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "MemoryMetadata":
        def parse_datetime(field_name: str) -> datetime:
            raw = value.get(field_name)
            if isinstance(raw, str):
                raw = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return raw

        return cls(
            id=str(value.get("id") or ""),
            created_at=parse_datetime("created_at"),
            updated_at=parse_datetime("updated_at"),
            source=str(value.get("source") or ""),
            confidence=float(value.get("confidence", 0.0)),
            lifecycle_state=value.get("lifecycle_state") or "",
        )


@dataclass(frozen=True, slots=True)
class MemoryLifecycleRecord:
    """Immutable audit event passed to a future lifecycle hook.

    ``actor`` identifies the writer/reader/system component and ``reason``
    records why the transition or retrieval happened.  The record is merely a
    serializable contract; Phase 1 does not publish or store it.
    """

    event: MemoryLifecycleEvent
    memory: MemoryMetadata
    occurred_at: datetime
    actor: str
    reason: str
    attributes: Mapping[str, Any] = field(default_factory=dict)
    identity_context: IdentityContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event, MemoryLifecycleEvent):
            raw_event = str(self.event)
            try:
                event = MemoryLifecycleEvent(raw_event)
            except ValueError:
                event = MemoryLifecycleEvent(raw_event.upper())
            object.__setattr__(self, "event", event)

        if not isinstance(self.memory, MemoryMetadata):
            if not isinstance(self.memory, Mapping):
                raise TypeError("MemoryLifecycleRecord.memory must be MemoryMetadata or mapping")
            object.__setattr__(self, "memory", MemoryMetadata.from_state(self.memory))

        if not isinstance(self.occurred_at, datetime) or self.occurred_at.tzinfo is None:
            raise ValueError("MemoryLifecycleRecord.occurred_at must be timezone-aware")
        if self.occurred_at < self.memory.created_at:
            raise ValueError("MemoryLifecycleRecord.occurred_at must not precede memory creation")

        actor = str(self.actor).strip()
        reason = str(self.reason).strip()
        if not actor:
            raise ValueError("MemoryLifecycleRecord.actor must not be empty")
        if not reason:
            raise ValueError("MemoryLifecycleRecord.reason must not be empty")
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "attributes", _json_safe(dict(self.attributes)))

        if self.identity_context is not None and not isinstance(
            self.identity_context, IdentityContext
        ):
            if not isinstance(self.identity_context, Mapping):
                raise TypeError(
                    "MemoryLifecycleRecord.identity_context must be IdentityContext or mapping"
                )
            object.__setattr__(
                self,
                "identity_context",
                IdentityContext.from_state(self.identity_context),
            )

    def to_state(self) -> dict[str, Any]:
        state = {
            "event": self.event.value,
            "memory": self.memory.to_state(),
            "occurred_at": self.occurred_at.isoformat(),
            "actor": self.actor,
            "reason": self.reason,
            "attributes": dict(self.attributes),
        }
        if self.identity_context is not None:
            state["identity_context"] = self.identity_context.to_state()
        return state

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "MemoryLifecycleRecord":
        occurred_at = value.get("occurred_at")
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        return cls(
            event=value.get("event") or "",
            memory=MemoryMetadata.from_state(value.get("memory") or {}),
            occurred_at=occurred_at,
            actor=str(value.get("actor") or ""),
            reason=str(value.get("reason") or ""),
            attributes=value.get("attributes") or {},
            identity_context=(
                IdentityContext.from_state(value["identity_context"])
                if isinstance(value.get("identity_context"), Mapping)
                else None
            ),
        )


@runtime_checkable
class MemoryLifecycleHook(Protocol):
    """Callable boundary for future audit/policy lifecycle subscribers."""

    def __call__(self, record: MemoryLifecycleRecord) -> None:
        """Observe one lifecycle record without owning memory persistence."""
        ...


@dataclass(frozen=True, slots=True)
class SummarySourceRange:
    """Auditable source span covered by a generated summary.

    A summary may identify its source either by a conversation turn range,
    by concrete ContextItem ids, or by both.  This keeps the contract usable
    for future conversation compaction and artifact/memory compaction.
    """

    start_turn: int | None = None
    end_turn: int | None = None
    source_item_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.start_turn is None) != (self.end_turn is None):
            raise ValueError("SummarySourceRange requires both start_turn and end_turn")
        if self.start_turn is not None:
            start_turn = int(self.start_turn)
            end_turn = int(self.end_turn)
            if start_turn < 0 or end_turn < start_turn:
                raise ValueError("SummarySourceRange turn range is invalid")
            object.__setattr__(self, "start_turn", start_turn)
            object.__setattr__(self, "end_turn", end_turn)

        normalized_ids = tuple(str(item_id).strip() for item_id in self.source_item_ids)
        if any(not item_id for item_id in normalized_ids):
            raise ValueError("SummarySourceRange.source_item_ids must not contain empty ids")
        object.__setattr__(self, "source_item_ids", normalized_ids)

        if self.start_turn is None and not normalized_ids:
            raise ValueError("SummarySourceRange requires a turn range or source_item_ids")

    def to_state(self) -> dict[str, Any]:
        return {
            "start_turn": self.start_turn,
            "end_turn": self.end_turn,
            "source_item_ids": list(self.source_item_ids),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "SummarySourceRange":
        return cls(
            start_turn=value.get("start_turn"),
            end_turn=value.get("end_turn"),
            source_item_ids=tuple(value.get("source_item_ids") or ()),
        )


@dataclass(frozen=True, slots=True)
class SummaryMetadata:
    """Governance and quality metadata required for generated summaries.

    Phase 1 introduced this contract. Phase 3.2 now uses it for ephemeral,
    identity-bound Context Compaction summaries; durable replacement and
    cross-session storage remain out of scope.
    """

    source_range: SummarySourceRange
    generated_by: str
    confidence: float
    created_at: datetime
    original_token_cost: int
    compressed_token_cost: int
    identity_context: IdentityContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_range, SummarySourceRange):
            if not isinstance(self.source_range, Mapping):
                raise TypeError("SummaryMetadata.source_range must be a mapping or SummarySourceRange")
            object.__setattr__(
                self,
                "source_range",
                SummarySourceRange.from_state(self.source_range),
            )

        generated_by = str(self.generated_by).strip()
        if not generated_by:
            raise ValueError("SummaryMetadata.generated_by must not be empty")
        object.__setattr__(self, "generated_by", generated_by)

        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("SummaryMetadata.confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)

        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise ValueError("SummaryMetadata.created_at must be timezone-aware")

        original_cost = int(self.original_token_cost)
        compressed_cost = int(self.compressed_token_cost)
        if original_cost < 0 or compressed_cost < 0:
            raise ValueError("Summary token costs must not be negative")
        object.__setattr__(self, "original_token_cost", original_cost)
        object.__setattr__(self, "compressed_token_cost", compressed_cost)

        if self.identity_context is not None and not isinstance(
            self.identity_context, IdentityContext
        ):
            if not isinstance(self.identity_context, Mapping):
                raise TypeError(
                    "SummaryMetadata.identity_context must be IdentityContext or mapping"
                )
            object.__setattr__(
                self,
                "identity_context",
                IdentityContext.from_state(self.identity_context),
            )

    @property
    def tokens_saved(self) -> int:
        return self.original_token_cost - self.compressed_token_cost

    @property
    def compression_ratio(self) -> float | None:
        if self.original_token_cost == 0:
            return None
        return self.compressed_token_cost / self.original_token_cost

    def to_state(self) -> dict[str, Any]:
        state = {
            "source_range": self.source_range.to_state(),
            "generated_by": self.generated_by,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "original_token_cost": self.original_token_cost,
            "compressed_token_cost": self.compressed_token_cost,
        }
        if self.identity_context is not None:
            state["identity_context"] = self.identity_context.to_state()
        return state

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "SummaryMetadata":
        created_at = value.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return cls(
            source_range=SummarySourceRange.from_state(value.get("source_range") or {}),
            generated_by=str(value.get("generated_by") or ""),
            confidence=float(value.get("confidence", 0.0)),
            created_at=created_at,
            original_token_cost=int(value.get("original_token_cost", 0)),
            compressed_token_cost=int(value.get("compressed_token_cost", 0)),
            identity_context=(
                IdentityContext.from_state(value["identity_context"])
                if isinstance(value.get("identity_context"), Mapping)
                else None
            ),
        )



def _json_safe(value: Any) -> Any:
    """Convert metadata into a deterministic JSON-safe structure."""

    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
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
    return str(value)


def estimate_token_cost(text: str) -> int:
    """Return a deterministic, provider-neutral token estimate.

    Liorin supports multiple model providers, so Phase 1 avoids binding the
    runtime to a provider tokenizer.  UTF-8 byte length divided by four is a
    conservative approximation for mixed Chinese/English support content.
    Exact provider usage remains observable through the existing trace/cost
    pipeline.
    """

    if not text:
        return 0
    return max(1, ceil(len(text.encode("utf-8")) / 4))


@dataclass(frozen=True, slots=True)
class ContextItem:
    """A single normalized piece of model-visible runtime context."""

    id: str
    type: ContextItemType
    content: str
    source: str
    priority: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    token_cost: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.type, ContextItemType):
            raw_type = str(self.type)
            try:
                normalized_type = ContextItemType(raw_type)
            except ValueError:
                normalized_type = ContextItemType(raw_type.upper())
            object.__setattr__(self, "type", normalized_type)
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("ContextItem.id must not be empty")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("ContextItem.source must not be empty")
        if not isinstance(self.content, str):
            object.__setattr__(self, "content", str(self.content))
        priority = int(self.priority)
        if not 0 <= priority <= 100:
            raise ValueError("ContextItem.priority must be between 0 and 100")
        object.__setattr__(self, "priority", priority)
        if not isinstance(self.timestamp, datetime) or self.timestamp.tzinfo is None:
            raise ValueError("ContextItem.timestamp must be timezone-aware")
        computed_cost = estimate_token_cost(self.content)
        if self.token_cost is None:
            object.__setattr__(self, "token_cost", computed_cost)
        else:
            token_cost = int(self.token_cost)
            if token_cost < 0:
                raise ValueError("ContextItem.token_cost must not be negative")
            object.__setattr__(self, "token_cost", token_cost)
        normalized_metadata = dict(self.metadata)
        identity_value = normalized_metadata.get("identity_context")
        if identity_value is not None:
            if isinstance(identity_value, IdentityContext):
                identity_context = identity_value
            elif isinstance(identity_value, Mapping):
                identity_context = IdentityContext.from_state(identity_value)
            else:
                raise TypeError(
                    "ContextItem.metadata.identity_context must be IdentityContext or mapping"
                )
            normalized_metadata["identity_context"] = identity_context.to_state()
        object.__setattr__(self, "metadata", _json_safe(normalized_metadata))

    @property
    def required(self) -> bool:
        """Whether selection/budgeting must preserve this item."""

        return bool(self.metadata.get("required", False))

    @property
    def identity_context(self) -> IdentityContext | None:
        """Return the canonical identity attached to this context item."""

        value = self.metadata.get("identity_context")
        if not isinstance(value, Mapping):
            return None
        try:
            return IdentityContext.from_state(value)
        except (TypeError, ValueError):
            return None

    def with_metadata(self, **metadata_updates: Any) -> "ContextItem":
        """Return a copy with normalized merged metadata."""

        metadata = dict(self.metadata)
        metadata.update(metadata_updates)
        return replace(self, metadata=metadata)

    @property
    def summary_metadata(self) -> SummaryMetadata | None:
        """Return validated summary metadata when this is an auditable summary."""

        if self.type not in {ContextItemType.SUMMARY, ContextItemType.MEMORY_SUMMARY}:
            return None
        value = self.metadata.get("summary_metadata")
        if not isinstance(value, Mapping):
            return None
        try:
            return SummaryMetadata.from_state(value)
        except (TypeError, ValueError):
            return None

    @property
    def is_auditable_summary(self) -> bool:
        """Whether the item can participate in future compaction evaluation."""

        return self.summary_metadata is not None

    def with_content(self, content: str, **metadata_updates: Any) -> "ContextItem":
        """Return a copy with recalculated cost and merged metadata."""

        metadata = dict(self.metadata)
        metadata.update(metadata_updates)
        return replace(
            self,
            content=content,
            token_cost=estimate_token_cost(content),
            metadata=metadata,
        )

    def to_state(self) -> dict[str, Any]:
        """Return a checkpoint/log-safe representation."""

        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "source": self.source,
            "priority": self.priority,
            "timestamp": self.timestamp.isoformat(),
            "token_cost": self.token_cost,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "ContextItem":
        timestamp = value.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return cls(
            id=str(value.get("id") or ""),
            type=value.get("type") or "",
            content=str(value.get("content") or ""),
            source=str(value.get("source") or ""),
            priority=int(value.get("priority", 0)),
            timestamp=timestamp,
            token_cost=value.get("token_cost"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class ContextSelection:
    """Selected context plus an auditable, non-persistent manifest."""

    items: tuple[ContextItem, ...]
    max_tokens: int
    input_tokens: int
    selected_tokens: int
    dropped_item_ids: tuple[str, ...] = ()
    truncated_item_ids: tuple[str, ...] = ()
    runtime_metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def within_budget(self) -> bool:
        return self.selected_tokens <= self.max_tokens

    def to_manifest(self) -> dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "input_tokens": self.input_tokens,
            "selected_tokens": self.selected_tokens,
            "selected_item_ids": [item.id for item in self.items],
            "dropped_item_ids": list(self.dropped_item_ids),
            "truncated_item_ids": list(self.truncated_item_ids),
            "within_budget": self.within_budget,
            "runtime_metadata": _json_safe(dict(self.runtime_metadata)),
        }

    def to_state(self) -> dict[str, Any]:
        return {
            "items": [item.to_state() for item in self.items],
            "max_tokens": self.max_tokens,
            "input_tokens": self.input_tokens,
            "selected_tokens": self.selected_tokens,
            "dropped_item_ids": list(self.dropped_item_ids),
            "truncated_item_ids": list(self.truncated_item_ids),
            "runtime_metadata": _json_safe(dict(self.runtime_metadata)),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "ContextSelection":
        return cls(
            items=tuple(ContextItem.from_state(item) for item in value.get("items", [])),
            max_tokens=int(value.get("max_tokens", 0)),
            input_tokens=int(value.get("input_tokens", 0)),
            selected_tokens=int(value.get("selected_tokens", 0)),
            dropped_item_ids=tuple(value.get("dropped_item_ids") or ()),
            truncated_item_ids=tuple(value.get("truncated_item_ids") or ()),
            runtime_metadata=value.get("runtime_metadata") or {},
        )
