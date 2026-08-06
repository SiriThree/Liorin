"""Identity-bound ACL policy for long-term memory resources."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from identity import IdentityContext


class MemoryAccessAction(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    DELETE_USER = "DELETE_USER"
    DELETE_TENANT = "DELETE_TENANT"


@dataclass(frozen=True, slots=True)
class MemoryAccessDecision:
    allowed: bool
    action: MemoryAccessAction
    reason: str


class MemoryAccessDenied(PermissionError):
    pass


@dataclass(slots=True)
class MemoryAccessPolicy:
    """Fail-closed ownership policy.

    Ordinary fact access requires exact ``tenant_id + user_id`` ownership.
    Tenant-wide deletion requires an explicitly configured tenant admin owner;
    Phase 6 does not invent a role/permission system inside IdentityContext.
    """

    tenant_admin_owners: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    def evaluate(
        self,
        *,
        requester: IdentityContext,
        action: MemoryAccessAction,
        resource_owner: IdentityContext | None = None,
        tenant_id: str | None = None,
    ) -> MemoryAccessDecision:
        if not isinstance(requester, IdentityContext):
            return MemoryAccessDecision(False, action, "missing authenticated identity context")
        if requester.is_anonymous:
            return MemoryAccessDecision(False, action, "anonymous identity cannot access long-term memory")

        if action is MemoryAccessAction.DELETE_TENANT:
            target_tenant = str(tenant_id or "").strip()
            allowed = (
                bool(target_tenant)
                and requester.tenant_id == target_tenant
                and (requester.tenant_id, requester.user_id) in self.tenant_admin_owners
            )
            return MemoryAccessDecision(
                allowed,
                action,
                "configured tenant administrator" if allowed else "tenant-wide delete requires configured tenant administrator",
            )

        if resource_owner is None:
            resource_owner = requester
        same_owner = (
            requester.tenant_id == resource_owner.tenant_id
            and requester.user_id == resource_owner.user_id
        )
        return MemoryAccessDecision(
            same_owner,
            action,
            "tenant/user owner match" if same_owner else "tenant/user ownership mismatch",
        )

    def assert_allowed(self, **kwargs) -> MemoryAccessDecision:
        decision = self.evaluate(**kwargs)
        if not decision.allowed:
            raise MemoryAccessDenied(decision.reason)
        return decision


__all__ = [
    "MemoryAccessAction",
    "MemoryAccessDecision",
    "MemoryAccessDenied",
    "MemoryAccessPolicy",
]
