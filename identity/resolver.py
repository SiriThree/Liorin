"""Resolve one canonical IdentityContext from Liorin runtime state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import uuid4

from identity.models import IdentityContext


class IdentityResolutionError(ValueError):
    """Raised when a checkpoint identity conflicts with the active runtime."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _attribute(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _first_text(*values: Any) -> str:
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if text:
            return text
    return ""


def _derived_id(prefix: str, seed: str) -> str:
    readable = seed.strip()
    if len(readable) <= 180:
        return f"{prefix}:{readable}"
    digest = sha256(readable.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _runtime_thread_id(runtime: Any) -> str:
    execution_info = _attribute(runtime, "execution_info")
    return _first_text(_attribute(execution_info, "thread_id"))


def _runtime_user_id(runtime: Any) -> str:
    server_info = _attribute(runtime, "server_info")
    server_user = _attribute(server_info, "user")
    return _first_text(
        _attribute(server_user, "identity"),
        _attribute(server_user, "user_id"),
        _attribute(server_user, "id"),
    )


def _runtime_context_value(runtime: Any, name: str) -> Any:
    return _attribute(_attribute(runtime, "context"), name)


def _principal_value(state: Mapping[str, Any], name: str) -> Any:
    principal = state.get("principal") or state.get("retrieval_principal")
    return _attribute(principal, name)


def _working_memory_session(state: Mapping[str, Any]) -> str:
    memory = _mapping(state.get("working_memory"))
    return _first_text(memory.get("session_id"))


def _active_langgraph_config() -> Mapping[str, Any]:
    """Best-effort access to RunnableConfig without coupling the model layer."""

    try:
        from langgraph.config import get_config

        value = get_config()
    except (ImportError, LookupError, RuntimeError):
        return {}
    return _mapping(value)


@dataclass(slots=True)
class IdentityResolver:
    """Centralize identity extraction and compatibility migration.

    Existing checkpoint identity is preserved.  Explicit runtime identity may
    upgrade anonymous/default ownership, but conflicting tenant, conversation,
    thread, or established user identity is rejected to avoid cross-boundary
    memory injection.
    """

    default_tenant_id: str = "tenant:public"
    default_user_id: str = "user:anonymous"

    def restore(self, state: Mapping[str, Any] | None) -> IdentityContext | None:
        """Restore identity only when it already exists in state."""

        if not state:
            return None
        raw = state.get("identity_context")
        if isinstance(raw, IdentityContext):
            return raw
        if isinstance(raw, Mapping):
            return IdentityContext.from_state(raw)
        return None

    def resolve(
        self,
        state: Mapping[str, Any] | None,
        *,
        runtime: Any = None,
        configurable: Mapping[str, Any] | None = None,
    ) -> IdentityContext:
        """Resolve one checkpoint-safe identity for the active graph execution."""

        state = state or {}
        existing = self.restore(state)
        configurable = _mapping(configurable) or _active_langgraph_config()
        nested_configurable = _mapping(configurable.get("configurable"))

        runtime_thread = _runtime_thread_id(runtime)
        explicit_thread = _first_text(
            runtime_thread,
            nested_configurable.get("thread_id"),
            configurable.get("thread_id"),
            state.get("thread_id"),
        )
        thread_id = explicit_thread or (existing.thread_id if existing else "")
        if not thread_id:
            thread_id = f"thread:{uuid4().hex}"
        self._reject_conflict("thread_id", existing, explicit_thread)

        explicit_tenant = _first_text(
            _principal_value(state, "tenant_id"),
            _runtime_context_value(runtime, "tenant_id"),
            nested_configurable.get("tenant_id"),
            configurable.get("tenant_id"),
            state.get("tenant_id"),
        )
        tenant_id = explicit_tenant or (existing.tenant_id if existing else "") or self.default_tenant_id
        if existing and explicit_tenant and explicit_tenant != existing.tenant_id:
            if existing.tenant_id != self.default_tenant_id:
                raise IdentityResolutionError(
                    "IdentityContext tenant_id conflicts with active runtime tenant"
                )

        explicit_user = _first_text(
            _principal_value(state, "user_id"),
            _runtime_context_value(runtime, "user_id"),
            _runtime_user_id(runtime),
            nested_configurable.get("user_id"),
            configurable.get("user_id"),
            state.get("user_id"),
            state.get("customer_id"),
        )
        user_id = explicit_user or (existing.user_id if existing else "") or self.default_user_id
        if existing and explicit_user and explicit_user != existing.user_id:
            if not existing.is_anonymous:
                raise IdentityResolutionError(
                    "IdentityContext user_id conflicts with established runtime user"
                )

        explicit_conversation = _first_text(
            state.get("conversation_id"),
            nested_configurable.get("conversation_id"),
            configurable.get("conversation_id"),
            _runtime_context_value(runtime, "conversation_id"),
        )
        conversation_id = (
            explicit_conversation
            or (existing.conversation_id if existing else "")
            or _derived_id("conversation", thread_id)
        )
        self._reject_conflict("conversation_id", existing, explicit_conversation)

        explicit_session = _first_text(
            state.get("session_id"),
            _working_memory_session(state),
            nested_configurable.get("session_id"),
            configurable.get("session_id"),
            _runtime_context_value(runtime, "session_id"),
        )
        session_id = (
            explicit_session
            or (existing.session_id if existing else "")
            or _derived_id("session", thread_id)
        )
        self._reject_conflict("session_id", existing, explicit_session)

        return IdentityContext(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            session_id=session_id,
        )

    @staticmethod
    def _reject_conflict(
        field_name: str,
        existing: IdentityContext | None,
        explicit_value: str,
    ) -> None:
        if not existing or not explicit_value:
            return
        if explicit_value != getattr(existing, field_name):
            raise IdentityResolutionError(
                f"IdentityContext {field_name} conflicts with active runtime"
            )
