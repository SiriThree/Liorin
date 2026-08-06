"""Deterministic semantic fingerprinting and delta detection."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import TYPE_CHECKING, Any, Mapping

from memory.delta.models import MemoryUpdate

if TYPE_CHECKING:
    from memory.working.models import WorkingMemory


_SCALAR_FIELDS = ("session_id", "task_goal", "current_intent")
_COLLECTION_FIELDS = (
    "confirmed_facts",
    "open_questions",
    "constraints",
    "decisions",
    "failed_attempts",
    "next_actions",
)
_SEMANTIC_FIELDS = _SCALAR_FIELDS + _COLLECTION_FIELDS
_EMPTY_PAYLOAD: dict[str, Any] = {}


def semantic_memory_state(memory: "WorkingMemory" | Mapping[str, Any] | None) -> dict[str, Any]:
    """Return canonical semantic state, excluding volatile timestamps."""

    if memory is None:
        return dict(_EMPTY_PAYLOAD)
    if isinstance(memory, Mapping):
        from memory.working.models import WorkingMemory
        restored = WorkingMemory.from_state(memory)
    else:
        restored = memory
    payload: dict[str, Any] = {}
    for field_name in _SCALAR_FIELDS:
        payload[field_name] = str(getattr(restored, field_name) or "")
    for field_name in _COLLECTION_FIELDS:
        # These fields are set-like task state. Sorting prevents order-only
        # changes from producing lifecycle noise.
        payload[field_name] = sorted(set(getattr(restored, field_name)))
    return payload


def memory_fingerprint(memory: "WorkingMemory" | Mapping[str, Any] | None) -> str:
    payload = semantic_memory_state(memory)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class MemoryDeltaDetector:
    """Compare previous and candidate WorkingMemory semantic state."""

    def detect(
        self,
        previous: "WorkingMemory" | Mapping[str, Any] | None,
        candidate: "WorkingMemory" | Mapping[str, Any],
        *,
        reason: str,
    ) -> MemoryUpdate:
        previous_payload = semantic_memory_state(previous)
        candidate_payload = semantic_memory_state(candidate)
        previous_fingerprint = memory_fingerprint(previous)
        candidate_fingerprint = memory_fingerprint(candidate)

        if previous_fingerprint == candidate_fingerprint:
            return MemoryUpdate(
                changed_fields=(),
                reason=reason,
                previous_fingerprint=previous_fingerprint,
                candidate_fingerprint=candidate_fingerprint,
                additions={},
                removals={},
            )

        changed_fields: list[str] = []
        additions: dict[str, tuple[str, ...]] = {}
        removals: dict[str, tuple[str, ...]] = {}
        for field_name in _SEMANTIC_FIELDS:
            old_value = previous_payload.get(field_name, [] if field_name in _COLLECTION_FIELDS else "")
            new_value = candidate_payload.get(field_name, [] if field_name in _COLLECTION_FIELDS else "")
            if old_value == new_value:
                continue
            changed_fields.append(field_name)
            if field_name in _COLLECTION_FIELDS:
                old_items = set(old_value)
                new_items = set(new_value)
                added = tuple(item for item in new_value if item not in old_items)
                removed = tuple(item for item in old_value if item not in new_items)
            else:
                added = (str(new_value),) if new_value not in (None, "") else ()
                removed = (str(old_value),) if old_value not in (None, "") else ()
            if added:
                additions[field_name] = added
            if removed:
                removals[field_name] = removed

        return MemoryUpdate(
            changed_fields=tuple(changed_fields),
            reason=reason,
            previous_fingerprint=previous_fingerprint,
            candidate_fingerprint=candidate_fingerprint,
            additions=additions,
            removals=removals,
        )
