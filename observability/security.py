"""Read-only security observability helpers.

These helpers never make authorization decisions.  They only project decisions
already made by production components into the active AgentExecutionTrace using
hashed identity/resource references suitable for evaluation and operations.
"""
from __future__ import annotations

from typing import Any, Mapping

from observability.events import RuntimeEventType
from observability.trace import get_default_trace_recorder
from retrieval.security import hash_identifier


def hashed_ref(value: Any, *, namespace: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return f"hash:{hash_identifier(text, namespace=namespace)}"


def identity_refs(identity: Any = None, *, tenant_id: Any = None, user_id: Any = None, session_id: Any = None) -> dict[str, str | None]:
    def read(name: str) -> Any:
        if isinstance(identity, Mapping):
            return identity.get(name)
        return getattr(identity, name, None)
    return {
        "tenant_ref": hashed_ref(tenant_id if tenant_id is not None else read("tenant_id"), namespace="tenant"),
        "user_ref": hashed_ref(user_id if user_id is not None else read("user_id"), namespace="user"),
        "session_ref": hashed_ref(session_id if session_id is not None else read("session_id"), namespace="session"),
    }


def emit_identity_resolved(identity: Any, *, source: str, stage: str = "identity") -> None:
    refs = identity_refs(identity)
    try:
        get_default_trace_recorder().emit(
            RuntimeEventType.IDENTITY_RESOLVED,
            attributes={
                "stage": stage,
                "source": source,
                **refs,
                "conversation_ref": hashed_ref(getattr(identity, "conversation_id", None), namespace="conversation"),
                "thread_ref": hashed_ref(getattr(identity, "thread_id", None), namespace="thread"),
            },
        )
    except Exception:
        pass


def emit_security_decision(
    *,
    kind: str,
    stage: str,
    allowed: bool | None,
    decision: str,
    reason: str,
    actor_identity: Any = None,
    actor_tenant_id: Any = None,
    actor_user_id: Any = None,
    actor_session_id: Any = None,
    resource_identity: Any = None,
    resource_tenant_id: Any = None,
    resource_user_id: Any = None,
    resource_session_id: Any = None,
    resource_type: str | None = None,
    resource_ref: str | None = None,
    tool_name: str | None = None,
    side_effect: str = "NONE",
    policy: str | None = None,
    event_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    actor = identity_refs(
        actor_identity,
        tenant_id=actor_tenant_id,
        user_id=actor_user_id,
        session_id=actor_session_id,
    )
    resource = identity_refs(
        resource_identity,
        tenant_id=resource_tenant_id,
        user_id=resource_user_id,
        session_id=resource_session_id,
    )
    attrs = {
        "security_kind": str(kind),
        "stage": str(stage),
        "allowed": allowed,
        "decision": str(decision),
        "reason": str(reason)[:500],
        "actor_identity": actor,
        "resource_identity": resource,
        "resource_type": resource_type,
        "resource_ref": resource_ref,
        "tool_name": tool_name,
        "side_effect": str(side_effect),
        "policy": policy,
        "source_event_id": event_id,
        "metadata": dict(metadata or {}),
    }
    try:
        get_default_trace_recorder().emit(RuntimeEventType.SECURITY_DECISION, attributes=attrs)
    except Exception:
        pass


__all__ = ["emit_identity_resolved", "emit_security_decision", "hashed_ref", "identity_refs"]
