"""Structured, identity-bound long-term memory facts for Liorin.

Long-term memory stores stable facts, not chat transcripts, agent messages, tool
outputs, retrieval chunks, or compaction summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
import json
from typing import Any, Mapping

from identity import IdentityContext


class MemoryFactSource(StrEnum):
    USER_CONFIRMATION = "user_confirmation"
    BUSINESS_SYSTEM = "business_system"
    WORKFLOW_STATE = "workflow_state"
    AGENT_INFERENCE = "agent_inference"
    LEGACY_CHECKPOINT = "legacy_checkpoint"


def _normalize_text(value: Any, *, field_name: str, max_chars: int = 512) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    if len(text) > max_chars:
        raise ValueError(f"{field_name} must not exceed {max_chars} characters")
    return text


def _parse_datetime(value: Any, *, field_name: str, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if hasattr(value, "to_state"):
        return _json_safe(value.to_state())
    return str(value)


def canonical_value(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def display_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """One stable fact owned by a tenant/user and observed in a runtime scope.

    The full ``identity_context`` records the origin observation. Access control
    for cross-session retrieval uses the durable owner boundary
    ``tenant_id + user_id``; conversation/thread/session remain provenance.
    """

    fact_id: str
    identity_context: IdentityContext
    key: str
    value: Any
    source: str
    confidence: float
    verified: bool
    observed_at: datetime
    verified_at: datetime | None
    verified_by: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_id", _normalize_text(self.fact_id, field_name="MemoryFact.fact_id"))
        if not isinstance(self.identity_context, IdentityContext):
            if not isinstance(self.identity_context, Mapping):
                raise TypeError("MemoryFact.identity_context must be IdentityContext or mapping")
            object.__setattr__(
                self,
                "identity_context",
                IdentityContext.from_state(self.identity_context),
            )
        object.__setattr__(self, "key", _normalize_text(self.key, field_name="MemoryFact.key", max_chars=160))
        safe_value = _json_safe(self.value)
        if safe_value in (None, "", [], {}):
            raise ValueError("MemoryFact.value must not be empty")
        if len(canonical_value(safe_value)) > 4096:
            raise ValueError("MemoryFact.value is too large for a fact")
        object.__setattr__(self, "value", safe_value)
        object.__setattr__(self, "source", _normalize_text(self.source, field_name="MemoryFact.source", max_chars=160))

        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("MemoryFact.confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "verified", bool(self.verified))

        observed_at = _parse_datetime(self.observed_at, field_name="MemoryFact.observed_at")
        created_at = _parse_datetime(self.created_at, field_name="MemoryFact.created_at")
        updated_at = _parse_datetime(self.updated_at, field_name="MemoryFact.updated_at")
        verified_at = _parse_datetime(
            self.verified_at,
            field_name="MemoryFact.verified_at",
            optional=True,
        )
        expires_at = _parse_datetime(
            self.expires_at,
            field_name="MemoryFact.expires_at",
            optional=True,
        )
        if updated_at < created_at:
            raise ValueError("MemoryFact.updated_at must not precede created_at")
        if observed_at > updated_at:
            raise ValueError("MemoryFact.observed_at must not follow updated_at")
        if expires_at is not None and expires_at <= observed_at:
            raise ValueError("MemoryFact.expires_at must follow observed_at")

        verified_by = (
            _normalize_text(self.verified_by, field_name="MemoryFact.verified_by", max_chars=160)
            if self.verified_by not in (None, "")
            else None
        )
        if self.verified and (verified_at is None or verified_by is None):
            raise ValueError("Verified MemoryFact requires verified_at and verified_by")
        if not self.verified:
            verified_at = None
            verified_by = None

        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "verified_at", verified_at)
        object.__setattr__(self, "verified_by", verified_by)
        object.__setattr__(self, "expires_at", expires_at)

    @property
    def owner_key(self) -> tuple[str, str]:
        return (self.identity_context.tenant_id, self.identity_context.user_id)

    def is_owned_by(self, identity_context: IdentityContext) -> bool:
        return self.owner_key == (
            identity_context.tenant_id,
            identity_context.user_id,
        )

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("MemoryFact expiry check requires timezone-aware now")
        return self.expires_at <= now

    def with_update(
        self,
        *,
        value: Any,
        source: str,
        confidence: float,
        verified: bool,
        observed_at: datetime,
        verified_at: datetime | None,
        verified_by: str | None,
        expires_at: datetime | None,
        updated_at: datetime,
    ) -> "MemoryFact":
        return replace(
            self,
            value=value,
            source=source,
            confidence=confidence,
            verified=verified,
            observed_at=observed_at,
            verified_at=verified_at,
            verified_by=verified_by,
            expires_at=expires_at,
            updated_at=updated_at,
        )

    def to_state(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "identity_context": self.identity_context.to_state(),
            "key": self.key,
            "value": _json_safe(self.value),
            "source": self.source,
            "confidence": self.confidence,
            "verified": self.verified,
            "observed_at": self.observed_at.isoformat(),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "verified_by": self.verified_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "MemoryFact":
        return cls(
            fact_id=value.get("fact_id") or "",
            identity_context=value.get("identity_context") or {},
            key=value.get("key") or "",
            value=value.get("value"),
            source=value.get("source") or "",
            confidence=value.get("confidence", 0.0),
            verified=value.get("verified", False),
            observed_at=value.get("observed_at"),
            verified_at=value.get("verified_at"),
            verified_by=value.get("verified_by"),
            created_at=value.get("created_at"),
            updated_at=value.get("updated_at"),
            expires_at=value.get("expires_at"),
        )


@dataclass(frozen=True, slots=True)
class MemoryFactCandidate:
    """Structured candidate that must pass Delta and Promotion Policy."""

    identity_context: IdentityContext
    key: str
    value: Any
    source: str
    confidence: float
    verified: bool
    observed_at: datetime
    verified_at: datetime | None = None
    verified_by: str | None = None
    expires_at: datetime | None = None
    reason: str = "structured memory fact candidate"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.identity_context, IdentityContext):
            if not isinstance(self.identity_context, Mapping):
                raise TypeError("MemoryFactCandidate.identity_context must be IdentityContext or mapping")
            object.__setattr__(
                self,
                "identity_context",
                IdentityContext.from_state(self.identity_context),
            )
        object.__setattr__(self, "key", _normalize_text(self.key, field_name="MemoryFactCandidate.key", max_chars=160))
        safe_value = _json_safe(self.value)
        if safe_value in (None, "", [], {}):
            raise ValueError("MemoryFactCandidate.value must not be empty")
        object.__setattr__(self, "value", safe_value)
        object.__setattr__(self, "source", _normalize_text(self.source, field_name="MemoryFactCandidate.source", max_chars=160))
        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("MemoryFactCandidate.confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "verified", bool(self.verified))
        observed_at = _parse_datetime(self.observed_at, field_name="MemoryFactCandidate.observed_at")
        verified_at = _parse_datetime(
            self.verified_at,
            field_name="MemoryFactCandidate.verified_at",
            optional=True,
        )
        expires_at = _parse_datetime(
            self.expires_at,
            field_name="MemoryFactCandidate.expires_at",
            optional=True,
        )
        verified_by = (
            _normalize_text(self.verified_by, field_name="MemoryFactCandidate.verified_by", max_chars=160)
            if self.verified_by not in (None, "")
            else None
        )
        if self.verified and (verified_at is None or verified_by is None):
            raise ValueError("Verified MemoryFactCandidate requires verified_at and verified_by")
        if not self.verified:
            verified_at = None
            verified_by = None
        if expires_at is not None and expires_at <= observed_at:
            raise ValueError("MemoryFactCandidate.expires_at must follow observed_at")
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "verified_at", verified_at)
        object.__setattr__(self, "verified_by", verified_by)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "reason", _normalize_text(self.reason, field_name="MemoryFactCandidate.reason"))
        object.__setattr__(self, "metadata", _json_safe(dict(self.metadata)))

    def to_fact(
        self,
        *,
        fact_id: str,
        previous: MemoryFact | None = None,
        now: datetime | None = None,
    ) -> MemoryFact:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("MemoryFactCandidate.to_fact requires timezone-aware now")
        if previous is None:
            return MemoryFact(
                fact_id=fact_id,
                identity_context=self.identity_context,
                key=self.key,
                value=self.value,
                source=self.source,
                confidence=self.confidence,
                verified=self.verified,
                observed_at=self.observed_at,
                verified_at=self.verified_at,
                verified_by=self.verified_by,
                created_at=now,
                updated_at=now,
                expires_at=self.expires_at,
            )
        if previous.key != self.key or not previous.is_owned_by(self.identity_context):
            raise ValueError("MemoryFactCandidate cannot update a different fact owner/key")
        return previous.with_update(
            value=self.value,
            source=self.source,
            confidence=self.confidence,
            verified=self.verified,
            observed_at=min(self.observed_at, now),
            verified_at=self.verified_at,
            verified_by=self.verified_by,
            expires_at=self.expires_at,
            updated_at=now,
        )

    def to_state(self) -> dict[str, Any]:
        return {
            "identity_context": self.identity_context.to_state(),
            "key": self.key,
            "value": _json_safe(self.value),
            "source": self.source,
            "confidence": self.confidence,
            "verified": self.verified,
            "observed_at": self.observed_at.isoformat(),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "verified_by": self.verified_by,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


__all__ = [
    "MemoryFact",
    "MemoryFactCandidate",
    "MemoryFactSource",
    "canonical_value",
    "display_value",
]
