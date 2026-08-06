"""JSON-safe Memory Delta model for explainable Working Memory updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


def _normalize_fields(values: Any) -> tuple[str, ...]:
    if values in (None, ""):
        return ()
    if isinstance(values, str):
        candidates = [values]
    else:
        try:
            candidates = list(values)
        except TypeError:
            candidates = [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


def _normalize_changes(value: Mapping[str, Any] | None) -> Mapping[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for key, raw_values in (value or {}).items():
        field_name = str(key).strip()
        if not field_name:
            raise ValueError("MemoryUpdate change field names must not be empty")
        values = _normalize_fields(raw_values)
        if values:
            normalized[field_name] = values
    return MappingProxyType(normalized)


def _validate_fingerprint(value: str, *, field_name: str) -> str:
    fingerprint = str(value or "").strip().lower()
    if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
        raise ValueError(f"MemoryUpdate.{field_name} must be a SHA-256 hex digest")
    return fingerprint


@dataclass(frozen=True, slots=True)
class MemoryUpdate:
    """Semantic change between a previous and candidate WorkingMemory state.

    ``last_updated`` is deliberately excluded by the detector.  Lifecycle
    persistence is driven by semantic state changes, not by updater calls.
    """

    changed_fields: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""
    previous_fingerprint: str = ""
    candidate_fingerprint: str = ""
    additions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    removals: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        changed_fields = _normalize_fields(self.changed_fields)
        reason = " ".join(str(self.reason or "").split()).strip()
        if not reason:
            raise ValueError("MemoryUpdate.reason must not be empty")
        previous_fingerprint = _validate_fingerprint(
            self.previous_fingerprint, field_name="previous_fingerprint"
        )
        candidate_fingerprint = _validate_fingerprint(
            self.candidate_fingerprint, field_name="candidate_fingerprint"
        )
        additions = _normalize_changes(self.additions)
        removals = _normalize_changes(self.removals)

        changed_set = set(changed_fields)
        unexpected = (set(additions) | set(removals)) - changed_set
        if unexpected:
            raise ValueError(
                "MemoryUpdate additions/removals must reference changed_fields: "
                + ", ".join(sorted(unexpected))
            )
        if previous_fingerprint == candidate_fingerprint and changed_fields:
            raise ValueError("No-op MemoryUpdate must not contain changed_fields")
        if previous_fingerprint != candidate_fingerprint and not changed_fields:
            raise ValueError("Changed MemoryUpdate requires changed_fields")

        object.__setattr__(self, "changed_fields", changed_fields)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "previous_fingerprint", previous_fingerprint)
        object.__setattr__(self, "candidate_fingerprint", candidate_fingerprint)
        object.__setattr__(self, "additions", additions)
        object.__setattr__(self, "removals", removals)

    @property
    def is_noop(self) -> bool:
        return self.previous_fingerprint == self.candidate_fingerprint

    def to_state(self) -> dict[str, Any]:
        return {
            "changed_fields": list(self.changed_fields),
            "reason": self.reason,
            "previous_fingerprint": self.previous_fingerprint,
            "candidate_fingerprint": self.candidate_fingerprint,
            "additions": {key: list(values) for key, values in self.additions.items()},
            "removals": {key: list(values) for key, values in self.removals.items()},
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "MemoryUpdate":
        return cls(
            changed_fields=tuple(value.get("changed_fields") or ()),
            reason=str(value.get("reason") or ""),
            previous_fingerprint=str(value.get("previous_fingerprint") or ""),
            candidate_fingerprint=str(value.get("candidate_fingerprint") or ""),
            additions=value.get("additions") or {},
            removals=value.get("removals") or {},
        )
