"""MemoryUpdate-compatible Delta detection for long-term MemoryFact."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

from memory.delta import MemoryUpdate
from memory.facts.models import MemoryFact, canonical_value


_FACT_FIELDS = (
    "key",
    "value",
    "source",
    "confidence",
    "verified",
    "verified_by",
    "expires_at",
)


def semantic_fact_state(fact: MemoryFact | Mapping[str, Any] | None) -> dict[str, Any]:
    if fact is None:
        return {}
    if isinstance(fact, Mapping):
        fact = MemoryFact.from_state(fact)
    return {
        "key": fact.key,
        "value": fact.value,
        "source": fact.source,
        "confidence": round(float(fact.confidence), 6),
        "verified": bool(fact.verified),
        "verified_by": fact.verified_by,
        "expires_at": fact.expires_at.isoformat() if fact.expires_at else None,
    }


def memory_fact_fingerprint(fact: MemoryFact | Mapping[str, Any] | None) -> str:
    payload = semantic_fact_state(fact)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _change_value(value: Any) -> tuple[str, ...]:
    if value in (None, "", [], {}):
        return ()
    if isinstance(value, str):
        return (value,)
    return (canonical_value(value),)


class MemoryFactDeltaDetector:
    """Return the shared Phase 3.1 MemoryUpdate contract for one fact."""

    def detect(
        self,
        previous: MemoryFact | Mapping[str, Any] | None,
        candidate: MemoryFact | Mapping[str, Any],
        *,
        reason: str,
    ) -> MemoryUpdate:
        old = semantic_fact_state(previous)
        new = semantic_fact_state(candidate)
        old_fp = memory_fact_fingerprint(previous)
        new_fp = memory_fact_fingerprint(candidate)
        if old_fp == new_fp:
            return MemoryUpdate(
                changed_fields=(),
                reason=reason,
                previous_fingerprint=old_fp,
                candidate_fingerprint=new_fp,
                additions={},
                removals={},
            )

        changed: list[str] = []
        additions: dict[str, tuple[str, ...]] = {}
        removals: dict[str, tuple[str, ...]] = {}
        for field_name in _FACT_FIELDS:
            old_value = old.get(field_name)
            new_value = new.get(field_name)
            if old_value == new_value:
                continue
            changed.append(field_name)
            added = _change_value(new_value)
            removed = _change_value(old_value)
            if added:
                additions[field_name] = added
            if removed:
                removals[field_name] = removed
        return MemoryUpdate(
            changed_fields=tuple(changed),
            reason=reason,
            previous_fingerprint=old_fp,
            candidate_fingerprint=new_fp,
            additions=additions,
            removals=removals,
        )


__all__ = [
    "MemoryFactDeltaDetector",
    "memory_fact_fingerprint",
    "semantic_fact_state",
]
