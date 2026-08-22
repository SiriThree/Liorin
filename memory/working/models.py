"""Data model for Liorin short-term Working Memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from typing import Any, Mapping


def _normalize_text(value: Any, *, max_chars: int = 600) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _normalize_values(values: Any, *, max_items: int = 16, max_chars: int = 240) -> tuple[str, ...]:
    if values in (None, ""):
        return ()
    if isinstance(values, str):
        candidates = [values]
    else:
        try:
            candidates = list(values)
        except TypeError:
            candidates = [values]

    normalized: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        text = _normalize_text(value, max_chars=max_chars)
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
        if len(normalized) >= max_items:
            break
    return tuple(normalized)


class MemoryScope(StrEnum):
    TASK = "TASK"
    CONVERSATION = "CONVERSATION"
    USER = "USER"


class TaskStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RESOLVED = "RESOLVED"


class FactStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


class MemoryAuthority(StrEnum):
    AUTHENTICATED_IDENTITY = "AUTHENTICATED_IDENTITY"
    BUSINESS_SYSTEM = "BUSINESS_SYSTEM"
    USER_CONFIRMED = "USER_CONFIRMED"
    STRUCTURED_QUERY_UNDERSTANDING = "STRUCTURED_QUERY_UNDERSTANDING"
    AGENT_INFERENCE = "AGENT_INFERENCE"
    LEGACY_CHECKPOINT = "LEGACY_CHECKPOINT"


def _parse_datetime(value: Any, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value is None:
        value = fallback or datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("memory timestamps must be timezone-aware")
    return value


def _enum_value(enum_type, value: Any, default: Any):
    if isinstance(value, enum_type):
        return value
    raw = str(value or default).strip()
    try:
        return enum_type(raw)
    except ValueError:
        return enum_type(raw.upper())


def _stable_task_id(*parts: Any) -> str:
    payload = "|".join(str(part or "") for part in parts)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"task-{digest}"


def _parse_fact_string(value: str) -> tuple[str, str] | None:
    text = _normalize_text(value, max_chars=240)
    if not text or "=" not in text:
        return None
    key, raw_value = text.split("=", 1)
    key = key.strip()
    raw_value = raw_value.strip()
    if not key or not raw_value:
        return None
    return key, raw_value


@dataclass(frozen=True, slots=True)
class ScopedMemoryFact:
    """Structured task/conversation/user fact with lifecycle and provenance."""

    key: str
    value: str
    scope: MemoryScope = MemoryScope.TASK
    task_id: str | None = None
    status: FactStatus = FactStatus.ACTIVE
    authority: MemoryAuthority = MemoryAuthority.STRUCTURED_QUERY_UNDERSTANDING
    confidence: float = 0.8
    source: str = "memory.working.extractor"
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    supersedes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _normalize_text(self.key, max_chars=120))
        object.__setattr__(self, "value", _normalize_text(self.value, max_chars=240))
        if not self.key or not self.value:
            raise ValueError("ScopedMemoryFact.key/value must not be empty")
        object.__setattr__(self, "scope", _enum_value(MemoryScope, self.scope, MemoryScope.TASK.value))
        object.__setattr__(self, "status", _enum_value(FactStatus, self.status, FactStatus.ACTIVE.value))
        object.__setattr__(
            self,
            "authority",
            _enum_value(MemoryAuthority, self.authority, MemoryAuthority.STRUCTURED_QUERY_UNDERSTANDING.value),
        )
        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("ScopedMemoryFact.confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "source", _normalize_text(self.source, max_chars=160) or "unknown")
        observed_at = _parse_datetime(self.observed_at)
        updated_at = _parse_datetime(self.updated_at, fallback=observed_at)
        if updated_at < observed_at:
            updated_at = observed_at
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "updated_at", updated_at)
        task_id = _normalize_text(self.task_id, max_chars=160) if self.task_id else None
        if self.scope == MemoryScope.TASK and not task_id:
            raise ValueError("TASK scoped facts require task_id")
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "supersedes", _normalize_text(self.supersedes, max_chars=240) if self.supersedes else None)

    @property
    def fact_ref(self) -> str:
        raw = f"{self.scope.value}:{self.task_id or ''}:{self.key}:{self.value}:{self.observed_at.isoformat()}"
        return "wmfact:" + sha256(raw.encode("utf-8")).hexdigest()[:16]

    def superseded(self, *, by_value: str, now: datetime) -> "ScopedMemoryFact":
        return ScopedMemoryFact(
            key=self.key,
            value=self.value,
            scope=self.scope,
            task_id=self.task_id,
            status=FactStatus.SUPERSEDED,
            authority=self.authority,
            confidence=self.confidence,
            source=self.source,
            observed_at=self.observed_at,
            updated_at=now,
            supersedes=by_value,
        )

    def to_state(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "scope": self.scope.value,
            "task_id": self.task_id,
            "status": self.status.value,
            "authority": self.authority.value,
            "confidence": self.confidence,
            "source": self.source,
            "observed_at": self.observed_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "supersedes": self.supersedes,
            "fact_ref": self.fact_ref,
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "ScopedMemoryFact":
        return cls(
            key=value.get("key") or "",
            value=value.get("value") or "",
            scope=value.get("scope") or MemoryScope.TASK.value,
            task_id=value.get("task_id"),
            status=value.get("status") or FactStatus.ACTIVE.value,
            authority=value.get("authority") or MemoryAuthority.LEGACY_CHECKPOINT.value,
            confidence=float(value.get("confidence", 0.5)),
            source=value.get("source") or "legacy_checkpoint",
            observed_at=value.get("observed_at"),
            updated_at=value.get("updated_at"),
            supersedes=value.get("supersedes"),
        )


@dataclass(frozen=True, slots=True)
class TaskMemory:
    """One task-scoped working-memory segment."""

    task_id: str
    task_goal: str = ""
    intent: str = ""
    status: TaskStatus = TaskStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    structured_facts: tuple[ScopedMemoryFact, ...] = field(default_factory=tuple)
    confirmed_facts: tuple[str, ...] = field(default_factory=tuple)
    open_questions: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    decisions: tuple[str, ...] = field(default_factory=tuple)
    failed_attempts: tuple[str, ...] = field(default_factory=tuple)
    next_actions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        task_id = _normalize_text(self.task_id, max_chars=160)
        if not task_id:
            raise ValueError("TaskMemory.task_id must not be empty")
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "task_goal", _normalize_text(self.task_goal))
        object.__setattr__(self, "intent", _normalize_text(self.intent, max_chars=160))
        object.__setattr__(self, "status", _enum_value(TaskStatus, self.status, TaskStatus.ACTIVE.value))
        created_at = _parse_datetime(self.created_at)
        updated_at = _parse_datetime(self.updated_at, fallback=created_at)
        if updated_at < created_at:
            updated_at = created_at
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        facts = tuple(
            item if isinstance(item, ScopedMemoryFact) else ScopedMemoryFact.from_state(item)
            for item in self.structured_facts
        )
        object.__setattr__(self, "structured_facts", facts)
        for field_name in (
            "confirmed_facts",
            "open_questions",
            "constraints",
            "decisions",
            "failed_attempts",
            "next_actions",
        ):
            object.__setattr__(self, field_name, _normalize_values(getattr(self, field_name)))

    @property
    def active_structured_facts(self) -> tuple[ScopedMemoryFact, ...]:
        return tuple(fact for fact in self.structured_facts if fact.status == FactStatus.ACTIVE)

    def to_state(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_goal": self.task_goal,
            "intent": self.intent,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "structured_facts": [fact.to_state() for fact in self.structured_facts],
            "confirmed_facts": list(self.confirmed_facts),
            "open_questions": list(self.open_questions),
            "constraints": list(self.constraints),
            "decisions": list(self.decisions),
            "failed_attempts": list(self.failed_attempts),
            "next_actions": list(self.next_actions),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "TaskMemory":
        return cls(
            task_id=value.get("task_id") or "",
            task_goal=value.get("task_goal") or "",
            intent=value.get("intent") or value.get("current_intent") or "",
            status=value.get("status") or TaskStatus.ACTIVE.value,
            created_at=value.get("created_at"),
            updated_at=value.get("updated_at"),
            structured_facts=tuple(value.get("structured_facts") or ()),
            confirmed_facts=tuple(value.get("confirmed_facts") or ()),
            open_questions=tuple(value.get("open_questions") or ()),
            constraints=tuple(value.get("constraints") or ()),
            decisions=tuple(value.get("decisions") or ()),
            failed_attempts=tuple(value.get("failed_attempts") or ()),
            next_actions=tuple(value.get("next_actions") or ()),
        )


@dataclass(frozen=True, slots=True)
class WorkingMemory:
    """Small, structured task state persisted with the LangGraph checkpoint."""

    session_id: str
    schema_version: int = 2
    active_task_id: str | None = None
    tasks: tuple[TaskMemory, ...] = field(default_factory=tuple)
    task_goal: str = ""
    current_intent: str = ""
    confirmed_facts: tuple[str, ...] = field(default_factory=tuple)
    open_questions: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    decisions: tuple[str, ...] = field(default_factory=tuple)
    failed_attempts: tuple[str, ...] = field(default_factory=tuple)
    next_actions: tuple[str, ...] = field(default_factory=tuple)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        session_id = _normalize_text(self.session_id, max_chars=160)
        if not session_id:
            raise ValueError("WorkingMemory.session_id must not be empty")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "schema_version", int(self.schema_version or 2))
        object.__setattr__(self, "task_goal", _normalize_text(self.task_goal))
        object.__setattr__(self, "current_intent", _normalize_text(self.current_intent, max_chars=160))
        for field_name in (
            "confirmed_facts",
            "open_questions",
            "constraints",
            "decisions",
            "failed_attempts",
            "next_actions",
        ):
            object.__setattr__(self, field_name, _normalize_values(getattr(self, field_name)))
        if not isinstance(self.last_updated, datetime) or self.last_updated.tzinfo is None:
            raise ValueError("WorkingMemory.last_updated must be timezone-aware")
        tasks = tuple(item if isinstance(item, TaskMemory) else TaskMemory.from_state(item) for item in self.tasks)
        if not tasks:
            task_id = self.active_task_id or _stable_task_id(session_id, self.task_goal, self.current_intent)
            tasks = (
                TaskMemory(
                    task_id=task_id,
                    task_goal=self.task_goal,
                    intent=self.current_intent,
                    status=TaskStatus.ACTIVE,
                    created_at=self.last_updated,
                    updated_at=self.last_updated,
                    structured_facts=_legacy_scoped_facts(
                        self.confirmed_facts,
                        task_id=task_id,
                        now=self.last_updated,
                    ),
                    confirmed_facts=self.confirmed_facts,
                    open_questions=self.open_questions,
                    constraints=self.constraints,
                    decisions=self.decisions,
                    failed_attempts=self.failed_attempts,
                    next_actions=self.next_actions,
                ),
            )
        active_task_id = _normalize_text(self.active_task_id, max_chars=160) if self.active_task_id else None
        if not active_task_id or active_task_id not in {task.task_id for task in tasks}:
            active = next((task for task in tasks if task.status == TaskStatus.ACTIVE), tasks[0])
            active_task_id = active.task_id
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "active_task_id", active_task_id)

    @property
    def active_task(self) -> TaskMemory:
        return next((task for task in self.tasks if task.task_id == self.active_task_id), self.tasks[0])

    @property
    def active_structured_facts(self) -> tuple[ScopedMemoryFact, ...]:
        return self.active_task.active_structured_facts

    def to_state(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "active_task_id": self.active_task_id,
            "tasks": [task.to_state() for task in self.tasks],
            "task_goal": self.task_goal,
            "current_intent": self.current_intent,
            "confirmed_facts": list(self.confirmed_facts),
            "open_questions": list(self.open_questions),
            "constraints": list(self.constraints),
            "decisions": list(self.decisions),
            "failed_attempts": list(self.failed_attempts),
            "next_actions": list(self.next_actions),
            "last_updated": self.last_updated.isoformat(),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "WorkingMemory":
        last_updated = value.get("last_updated")
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
        if last_updated is None:
            last_updated = datetime.now(timezone.utc)
        tasks = tuple(value.get("tasks") or ())
        active_task_id = value.get("active_task_id")
        return cls(
            session_id=str(value.get("session_id") or ""),
            schema_version=int(value.get("schema_version") or (2 if tasks else 1)),
            active_task_id=str(active_task_id) if active_task_id else None,
            tasks=tasks,
            task_goal=str(value.get("task_goal") or ""),
            current_intent=str(value.get("current_intent") or ""),
            confirmed_facts=tuple(value.get("confirmed_facts") or ()),
            open_questions=tuple(value.get("open_questions") or ()),
            constraints=tuple(value.get("constraints") or ()),
            decisions=tuple(value.get("decisions") or ()),
            failed_attempts=tuple(value.get("failed_attempts") or ()),
            next_actions=tuple(value.get("next_actions") or ()),
            last_updated=last_updated,
        )

    @property
    def has_task_state(self) -> bool:
        return bool(
            self.task_goal
            or self.current_intent
            or self.confirmed_facts
            or self.open_questions
            or self.decisions
            or self.next_actions
        )

    def task_state_fingerprint(self) -> str:
        active = self.active_task
        payload = {
            "active_task_id": self.active_task_id,
            "task_status": active.status.value,
            "facts": [
                {
                    "key": fact.key,
                    "value": fact.value,
                    "scope": fact.scope.value,
                    "status": fact.status.value,
                    "authority": fact.authority.value,
                }
                for fact in active.structured_facts
            ],
            "open_questions": list(active.open_questions),
            "constraints": list(active.constraints),
            "decisions": list(active.decisions),
            "next_actions": list(active.next_actions),
        }
        import json
        return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _legacy_scoped_facts(
    values: tuple[str, ...],
    *,
    task_id: str,
    now: datetime,
) -> tuple[ScopedMemoryFact, ...]:
    facts: list[ScopedMemoryFact] = []
    for value in values:
        parsed = _parse_fact_string(value)
        if parsed is None:
            continue
        key, raw_value = parsed
        facts.append(
            ScopedMemoryFact(
                key=key,
                value=raw_value,
                scope=MemoryScope.TASK,
                task_id=task_id,
                status=FactStatus.ACTIVE,
                authority=MemoryAuthority.LEGACY_CHECKPOINT,
                confidence=0.5,
                source="legacy_confirmed_facts",
                observed_at=now,
                updated_at=now,
            )
        )
    return tuple(facts)
