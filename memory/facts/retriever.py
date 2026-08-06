"""Relevant, ACL-protected retrieval for long-term MemoryFact."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from governance.acl import MemoryAccessAction, MemoryAccessPolicy
from identity import IdentityContext
from memory.facts.models import MemoryFact
from storage.interfaces import MemoryBackend


_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "product_model": ("型号", "model", "device", "设备", "产品"),
    "device_model": ("型号", "model", "device", "设备"),
    "product_name": ("产品", "设备", "product", "device"),
    "preferred_language": ("语言", "language", "中文", "英文"),
    "language_preference": ("语言", "language", "中文", "英文"),
    "region": ("地区", "区域", "region", "country"),
    "timezone": ("时区", "timezone", "时间"),
    "communication_preference": ("沟通", "回复", "communication", "reply"),
    "preferred_contact_channel": ("联系", "渠道", "contact", "channel"),
}


def _message_value(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, Mapping):
        return message.get(key, default)
    return getattr(message, key, default)


def _message_role(message: Any) -> str:
    role = _message_value(message, "role") or _message_value(message, "type")
    role = str(role or "").casefold()
    return {"human": "user", "ai": "assistant"}.get(role, role)


def _latest_user_text(messages: Sequence[Any]) -> str:
    for message in reversed(messages):
        if _message_role(message) != "user":
            continue
        content = _message_value(message, "content", "")
        if isinstance(content, str):
            return content.strip()
    return ""


def _working_memory_query(state: Mapping[str, Any]) -> str:
    memory = state.get("working_memory")
    if not isinstance(memory, Mapping):
        return ""
    parts = [str(memory.get("task_goal") or ""), str(memory.get("current_intent") or "")]
    parts.extend(str(item) for item in (memory.get("open_questions") or ()))
    return " ".join(part for part in parts if part)


@dataclass(frozen=True, slots=True)
class MemoryRetrievalResult:
    facts: tuple[MemoryFact, ...]
    query: str
    requested_keys: tuple[str, ...]
    expired_fact_ids: tuple[str, ...] = ()
    denied_fact_ids: tuple[str, ...] = ()


class MemoryRetriever:
    """Retrieve only relevant facts; never return the user's entire backend."""

    def __init__(
        self,
        store: MemoryBackend,
        *,
        minimum_confidence: float = 0.7,
        access_policy: MemoryAccessPolicy | None = None,
        on_retrieved: Callable[[MemoryFact, IdentityContext, str], None] | None = None,
        on_expired: Callable[[MemoryFact, IdentityContext], None] | None = None,
        on_denied: Callable[[MemoryFact, IdentityContext], None] | None = None,
    ) -> None:
        self.store = store
        self.minimum_confidence = float(minimum_confidence)
        self.access_policy = access_policy or MemoryAccessPolicy()
        self.on_retrieved = on_retrieved
        self.on_expired = on_expired
        self.on_denied = on_denied

    def retrieve(
        self,
        current_context: Mapping[str, Any] | str,
        *,
        identity_context: IdentityContext,
        limit: int = 6,
        now: datetime | None = None,
    ) -> MemoryRetrievalResult:
        now = now or datetime.now(timezone.utc)
        if isinstance(current_context, str):
            query = current_context.strip()
            requested_keys: tuple[str, ...] = ()
        else:
            requested_keys = tuple(
                str(item).strip()
                for item in (current_context.get("required_memory_keys") or ())
                if str(item).strip()
            )
            query = " ".join(
                part
                for part in (
                    str(current_context.get("memory_query") or "").strip(),
                    _latest_user_text(current_context.get("messages", []) or []),
                    _working_memory_query(current_context),
                )
                if part
            )
        if not query and not requested_keys:
            return MemoryRetrievalResult((), query, requested_keys)

        expanded = [query]
        query_folded = query.casefold()
        for key, aliases in _KEY_ALIASES.items():
            if key in requested_keys or any(alias.casefold() in query_folded for alias in aliases):
                expanded.append(key.replace("_", " "))
                expanded.extend(aliases)
        search_query = " ".join(expanded)
        candidates = self.store.search_fact(
            identity_context=identity_context,
            query=search_query,
            keys=requested_keys,
            limit=max(limit * 3, limit),
            now=now,
            include_expired=True,
        )

        selected: list[MemoryFact] = []
        expired: list[str] = []
        denied: list[str] = []
        for fact in candidates:
            decision = self.access_policy.evaluate(
                requester=identity_context,
                action=MemoryAccessAction.READ,
                resource_owner=fact.identity_context,
            )
            if not decision.allowed:
                denied.append(fact.fact_id)
                if self.on_denied is not None:
                    self.on_denied(fact, identity_context)
                continue
            if fact.is_expired(now=now):
                expired.append(fact.fact_id)
                if self.on_expired is not None:
                    self.on_expired(fact, identity_context)
                continue
            if fact.confidence < self.minimum_confidence:
                continue
            selected.append(fact)
            if self.on_retrieved is not None:
                self.on_retrieved(fact, identity_context, query)
            if len(selected) >= limit:
                break
        return MemoryRetrievalResult(
            facts=tuple(selected),
            query=query,
            requested_keys=requested_keys,
            expired_fact_ids=tuple(expired),
            denied_fact_ids=tuple(denied),
        )


__all__ = ["MemoryRetrievalResult", "MemoryRetriever"]
