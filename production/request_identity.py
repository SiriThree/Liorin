"""Trusted request identity binding for the production HTTP boundary.

Authentication remains the responsibility of an upstream identity-aware
proxy. This module ensures untrusted request bodies cannot override the
identity asserted by that proxy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from identity import IdentityContext


class RequestIdentityMismatch(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class TrustedRequestIdentity:
    tenant_id: str
    user_id: str
    conversation_id: str
    thread_id: str
    session_id: str

    def to_context(self) -> IdentityContext:
        return IdentityContext(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            thread_id=self.thread_id,
            session_id=self.session_id,
        )


def bind_trusted_identity(
    state: Mapping[str, Any],
    config: Mapping[str, Any] | None,
    trusted: TrustedRequestIdentity,
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = trusted.to_context()
    existing_raw = state.get("identity_context")
    if existing_raw:
        existing = IdentityContext.from_state(existing_raw)
        if existing != identity:
            raise RequestIdentityMismatch("request body identity conflicts with trusted gateway identity")

    bound_state = dict(state)
    bound_state["identity_context"] = identity.to_state()
    bound_state["tenant_id"] = identity.tenant_id
    bound_state["user_id"] = identity.user_id
    bound_state["conversation_id"] = identity.conversation_id
    bound_state["thread_id"] = identity.thread_id
    bound_state["session_id"] = identity.session_id

    bound_config = dict(config or {})
    configurable = dict(bound_config.get("configurable") or {})
    configured_thread = configurable.get("thread_id")
    if configured_thread is not None and str(configured_thread) != identity.thread_id:
        raise RequestIdentityMismatch("LangGraph configurable.thread_id conflicts with trusted identity")
    configurable["thread_id"] = identity.thread_id
    bound_config["configurable"] = configurable
    return bound_state, bound_config


__all__ = ["RequestIdentityMismatch", "TrustedRequestIdentity", "bind_trusted_identity"]
