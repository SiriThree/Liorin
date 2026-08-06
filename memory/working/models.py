"""Data model for Liorin short-term Working Memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
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


@dataclass(frozen=True, slots=True)
class WorkingMemory:
    """Small, structured task state persisted with the LangGraph checkpoint."""

    session_id: str
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

    def to_state(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
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
        return cls(
            session_id=str(value.get("session_id") or ""),
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
