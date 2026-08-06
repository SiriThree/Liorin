"""Canonical identity contract for Liorin runtime state.

Phase 3.0 defines identity ownership and checkpoint serialization only.  It does
not implement authentication, authorization, a user profile, or a memory store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


_MAX_ID_LENGTH = 512


def _normalize_identifier(value: Any, *, field_name: str) -> str:
    identifier = " ".join(str(value or "").split()).strip()
    if not identifier:
        raise ValueError(f"IdentityContext.{field_name} must not be empty")
    if len(identifier) > _MAX_ID_LENGTH:
        raise ValueError(
            f"IdentityContext.{field_name} must not exceed {_MAX_ID_LENGTH} characters"
        )
    return identifier


@dataclass(frozen=True, slots=True)
class IdentityContext:
    """Checkpoint-safe mapping between business and runtime identity scopes.

    ``tenant_id`` is the isolation boundary, ``user_id`` owns user-scoped
    memory, ``conversation_id`` identifies the business conversation,
    ``thread_id`` identifies the LangGraph checkpoint thread, and ``session_id``
    identifies the runtime Working Memory lifecycle.
    """

    tenant_id: str
    user_id: str
    conversation_id: str
    thread_id: str
    session_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "user_id",
            "conversation_id",
            "thread_id",
            "session_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_identifier(getattr(self, field_name), field_name=field_name),
            )

        values = {
            self.tenant_id,
            self.user_id,
            self.conversation_id,
            self.thread_id,
            self.session_id,
        }
        if len(values) == 1:
            raise ValueError(
                "IdentityContext fields must preserve distinct identity semantics"
            )

    @property
    def is_anonymous(self) -> bool:
        return self.user_id.casefold() in {
            "anonymous",
            "user:anonymous",
            "public:anonymous",
        }

    def to_state(self) -> dict[str, str]:
        """Return a deterministic JSON-safe checkpoint representation."""

        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "thread_id": self.thread_id,
            "session_id": self.session_id,
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "IdentityContext":
        if not isinstance(value, Mapping):
            raise TypeError("IdentityContext state must be a mapping")
        return cls(
            tenant_id=value.get("tenant_id") or "",
            user_id=value.get("user_id") or "",
            conversation_id=value.get("conversation_id") or "",
            thread_id=value.get("thread_id") or "",
            session_id=value.get("session_id") or "",
        )
