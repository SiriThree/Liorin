"""Identity-aware TTL cache for completed ContextSelection objects."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from context_engine.models import ContextSelection


def _safe_state(state: Mapping[str, Any]) -> dict[str, Any]:
    identity = state.get("identity_context") or {}
    messages = []
    for message in state.get("messages", []) or []:
        if isinstance(message, Mapping):
            messages.append({key: message.get(key) for key in ("id", "role", "type", "name", "content", "tool_call_id")})
        else:
            messages.append({
                "id": getattr(message, "id", None),
                "role": getattr(message, "role", getattr(message, "type", None)),
                "name": getattr(message, "name", None),
                "content": getattr(message, "content", None),
                "tool_call_id": getattr(message, "tool_call_id", None),
            })
    return {
        "identity_context": identity,
        "messages": messages,
        "working_memory": state.get("working_memory"),
        "workflow": {key: state.get(key) for key in (
            "customer_id", "customer_email", "current_intent", "task_goal",
            "open_questions", "unresolved_slots", "confirmed_facts", "constraints",
            "decisions", "failed_attempts", "next_actions", "artifact_refs",
            "retrieval_refs", "evidence_refs", "context_summary",
            "context_summary_metadata", "conversation_summary",
            "conversation_summary_metadata",
        ) if key in state},
        "knowledge": {key: state.get(key) for key in (
            "original_question", "rewritten_question", "task_type", "product_name",
            "product_id", "product_model", "product_version", "error_code",
            "order_id", "ticket_id", "requirements", "covered_requirements",
            "missing_requirements", "verification_action",
            "answer_verification_action", "handoff_reason", "verified_evidences",
            "evidences", "retrieval_response",
        ) if key in state},
    }


@dataclass(slots=True)
class ContextAssemblyCache:
    cache: Any
    ttl_seconds: int = 15

    @staticmethod
    def _owner(identity: Any) -> str:
        if isinstance(identity, Mapping):
            tenant_id = identity.get("tenant_id", "tenant:unknown")
            user_id = identity.get("user_id", "user:unknown")
        else:
            tenant_id = getattr(identity, "tenant_id", "tenant:unknown")
            user_id = getattr(identity, "user_id", "user:unknown")
        return f"{tenant_id}:{user_id}"

    def key(self, state: Mapping[str, Any], *, max_tokens: int, options: Mapping[str, Any]) -> str:
        payload = {"state": _safe_state(state), "max_tokens": max_tokens, "options": dict(options)}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        owner = self._owner(state.get("identity_context") or {})
        return f"context:selection:{owner}:" + sha256(raw.encode("utf-8")).hexdigest()

    def invalidate_identity(self, identity: Any) -> int:
        return int(self.cache.invalidate_prefix(f"context:selection:{self._owner(identity)}:"))

    def get(self, key: str) -> "ContextSelection | None":
        state = self.cache.get(key)
        if state is None:
            return None
        from context_engine.models import ContextSelection
        return ContextSelection.from_state(state)

    def set(self, key: str, selection: "ContextSelection") -> None:
        self.cache.set(key, selection.to_state(), ttl_seconds=self.ttl_seconds)


_DEFAULT_CONTEXT_CACHE: ContextAssemblyCache | None = None
_LOCK = RLock()


def set_default_context_cache(cache: ContextAssemblyCache | None) -> ContextAssemblyCache | None:
    global _DEFAULT_CONTEXT_CACHE
    with _LOCK:
        _DEFAULT_CONTEXT_CACHE = cache
        return _DEFAULT_CONTEXT_CACHE


def get_default_context_cache() -> ContextAssemblyCache | None:
    with _LOCK:
        return _DEFAULT_CONTEXT_CACHE
