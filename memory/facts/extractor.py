"""Structured candidate extraction for long-term MemoryFact promotion."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import re
from typing import Any

from identity import IdentityContext
from memory.facts.models import MemoryFactCandidate, MemoryFactSource


_DIRECT_STABLE_FIELDS = (
    "product_model",
    "product_name",
    "device_model",
    "preferred_language",
    "language_preference",
    "communication_preference",
    "accessibility_preference",
    "region",
    "timezone",
    "preferred_contact_channel",
)


_EXPLICIT_MODEL_PATTERNS = (
    re.compile(
        r"(?:我(?:确认)?(?:的)?(?:设备|产品|冰箱)?|设备|产品|冰箱)?\s*型号\s*(?:是|为|[:：])\s*([A-Za-z0-9][A-Za-z0-9._-]{1,63})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:device|product)?\s*model\s*(?:is|[:：])\s*([A-Za-z0-9][A-Za-z0-9._-]{1,63})",
        re.IGNORECASE,
    ),
)


def _message_value(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, Mapping):
        return message.get(key, default)
    return getattr(message, key, default)


def _message_role(message: Any) -> str:
    role = _message_value(message, "role") or _message_value(message, "type")
    role = str(role or "").casefold()
    return {"human": "user", "ai": "assistant"}.get(role, role)


def _latest_user_text(messages: Any) -> str:
    try:
        materialized = list(messages or ())
    except TypeError:
        return ""
    for message in reversed(materialized):
        if _message_role(message) != "user":
            continue
        content = _message_value(message, "content", "")
        return content.strip() if isinstance(content, str) else ""
    return ""


def _explicit_current_turn_facts(state: Mapping[str, Any]) -> dict[str, str]:
    """Extract only strongly phrased current-turn confirmations.

    This does not summarize or scan the full conversation. It inspects the most
    recent user message for a narrow, deterministic confirmation grammar.
    """

    text = _latest_user_text(state.get("messages", ()))
    if not text:
        return {}
    for pattern in _EXPLICIT_MODEL_PATTERNS:
        match = pattern.search(text)
        if match:
            return {"product_model": match.group(1)}
    return {}


def _parse_fact_text(value: Any) -> tuple[str, Any] | None:
    text = " ".join(str(value or "").split()).strip()
    if not text or "=" not in text:
        return None
    key, raw_value = text.split("=", 1)
    key = key.strip()
    raw_value = raw_value.strip()
    if not key or not raw_value:
        return None
    return key, raw_value


def _entries(value: Any) -> list[dict[str, Any]]:
    if value in (None, "", [], {}):
        return []
    result: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        if "key" in value and "value" in value:
            return [dict(value)]
        for key, item in value.items():
            if isinstance(item, Mapping) and "value" in item:
                result.append({"key": key, **dict(item)})
            else:
                result.append({"key": key, "value": item})
        return result
    if isinstance(value, str):
        parsed = _parse_fact_text(value)
        return [{"key": parsed[0], "value": parsed[1]}] if parsed else []
    try:
        iterable: Iterable[Any] = value
    except TypeError:
        return []
    for item in iterable:
        if isinstance(item, Mapping):
            if "key" in item and "value" in item:
                result.append(dict(item))
        else:
            parsed = _parse_fact_text(item)
            if parsed:
                result.append({"key": parsed[0], "value": parsed[1]})
    return result


class MemoryCandidateExtractor:
    """Extract candidates from structured state only, never full chat history."""

    def extract(
        self,
        state: Mapping[str, Any],
        *,
        identity_context: IdentityContext,
        working_memory: Any = None,
        now: datetime | None = None,
    ) -> tuple[MemoryFactCandidate, ...]:
        now = now or datetime.now(timezone.utc)
        if working_memory is None:
            working_memory = state.get("working_memory")
        if isinstance(working_memory, Mapping):
            try:
                from memory.working.models import WorkingMemory
                working_memory = WorkingMemory.from_state(working_memory)
            except (TypeError, ValueError):
                working_memory = None

        candidates: dict[str, MemoryFactCandidate] = {}

        # Fully structured candidates are the preferred integration contract.
        for entry in _entries(state.get("memory_fact_candidates")):
            candidate = self._candidate_from_entry(
                entry,
                identity_context=identity_context,
                default_source=entry.get("source") or MemoryFactSource.WORKFLOW_STATE.value,
                default_confidence=float(entry.get("confidence", 0.8)),
                default_verified=bool(entry.get("verified", False)),
                default_verified_by=entry.get("verified_by"),
                now=now,
                reason=str(entry.get("reason") or "explicit structured memory candidate"),
            )
            if candidate:
                candidates[candidate.key] = candidate

        for entry in _entries(state.get("user_confirmed_facts")):
            candidate = self._candidate_from_entry(
                entry,
                identity_context=identity_context,
                default_source=MemoryFactSource.USER_CONFIRMATION.value,
                default_confidence=1.0,
                default_verified=True,
                default_verified_by="user",
                now=now,
                reason="user explicitly confirmed stable fact",
            )
            if candidate:
                candidates[candidate.key] = candidate

        for entry in _entries(_explicit_current_turn_facts(state)):
            candidate = self._candidate_from_entry(
                entry,
                identity_context=identity_context,
                default_source=MemoryFactSource.USER_CONFIRMATION.value,
                default_confidence=1.0,
                default_verified=True,
                default_verified_by="user_explicit_statement",
                now=now,
                reason="current user explicitly confirmed stable fact",
            )
            if candidate:
                candidates.setdefault(candidate.key, candidate)

        for entry in _entries(state.get("business_system_facts")):
            candidate = self._candidate_from_entry(
                entry,
                identity_context=identity_context,
                default_source=MemoryFactSource.BUSINESS_SYSTEM.value,
                default_confidence=1.0,
                default_verified=True,
                default_verified_by="business_system",
                now=now,
                reason="business system returned stable fact",
            )
            if candidate:
                candidates[candidate.key] = candidate

        workflow = state.get("workflow_state")
        if isinstance(workflow, Mapping):
            for entry in _entries(workflow.get("stable_facts")):
                candidate = self._candidate_from_entry(
                    entry,
                    identity_context=identity_context,
                    default_source=MemoryFactSource.WORKFLOW_STATE.value,
                    default_confidence=0.85,
                    default_verified=False,
                    default_verified_by=None,
                    now=now,
                    reason="workflow state exposed stable reusable fact",
                )
                if candidate:
                    candidates.setdefault(candidate.key, candidate)

        # Existing structured top-level fields are safe to inspect and avoid an
        # LLM/history scan. They remain unverified unless a stronger source above
        # supplied the same key.
        for key in _DIRECT_STABLE_FIELDS:
            value = state.get(key)
            if value in (None, "", [], {}):
                continue
            candidates.setdefault(
                key,
                MemoryFactCandidate(
                    identity_context=identity_context,
                    key=key,
                    value=value,
                    source=MemoryFactSource.WORKFLOW_STATE.value,
                    confidence=0.85,
                    verified=False,
                    observed_at=now,
                    reason="structured runtime field candidate",
                    metadata={"stable": True, "future_reuse": True},
                ),
            )

        # Legacy WorkingMemory confirmed_facts remain readable but are migrated
        # conservatively: no verification and low confidence. Policy will not
        # silently promote them unless a stronger structured candidate exists.
        if working_memory is not None and hasattr(working_memory, "confirmed_facts"):
            for fact_text in working_memory.confirmed_facts:
                parsed = _parse_fact_text(fact_text)
                if parsed is None:
                    continue
                key, value = parsed
                candidates.setdefault(
                    key,
                    MemoryFactCandidate(
                        identity_context=identity_context,
                        key=key,
                        value=value,
                        source=MemoryFactSource.LEGACY_CHECKPOINT.value,
                        confidence=0.5,
                        verified=False,
                        observed_at=working_memory.last_updated,
                        reason="legacy WorkingMemory confirmed_facts migration",
                        metadata={"legacy_checkpoint": True},
                    ),
                )

        return tuple(candidates[key] for key in sorted(candidates))

    @staticmethod
    def _candidate_from_entry(
        entry: Mapping[str, Any],
        *,
        identity_context: IdentityContext,
        default_source: str,
        default_confidence: float,
        default_verified: bool,
        default_verified_by: str | None,
        now: datetime,
        reason: str,
    ) -> MemoryFactCandidate | None:
        key = str(entry.get("key") or "").strip()
        value = entry.get("value")
        if not key or value in (None, "", [], {}):
            return None
        verified = bool(entry.get("verified", default_verified))
        verified_by = entry.get("verified_by", default_verified_by) if verified else None
        observed_at = entry.get("observed_at") or now
        verified_at = entry.get("verified_at") or (now if verified else None)
        return MemoryFactCandidate(
            identity_context=identity_context,
            key=key,
            value=value,
            source=str(entry.get("source") or default_source),
            confidence=float(entry.get("confidence", default_confidence)),
            verified=verified,
            observed_at=observed_at,
            verified_at=verified_at,
            verified_by=verified_by,
            expires_at=entry.get("expires_at"),
            reason=str(entry.get("reason") or reason),
            metadata=entry.get("metadata") or {
                "stable": True,
                "future_reuse": True,
            },
        )


__all__ = ["MemoryCandidateExtractor"]
