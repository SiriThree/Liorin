"""Lifecycle governance operations over the existing LongTermMemoryRuntime."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from governance.acl import MemoryAccessAction, MemoryAccessPolicy
from identity import IdentityContext
from memory.facts.models import MemoryFactCandidate
from memory.facts.runtime import LongTermMemoryRuntime, MemoryPromotionItemResult


class MemoryGovernanceService:
    def __init__(
        self,
        runtime: LongTermMemoryRuntime,
        *,
        access_policy: MemoryAccessPolicy | None = None,
    ) -> None:
        self.runtime = runtime
        self.access_policy = access_policy or runtime.access_policy

    def delete_fact(
        self,
        fact_id: str,
        *,
        requester: IdentityContext,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ):
        return self.runtime.delete(
            fact_id,
            identity_context=requester,
            actor=actor,
            reason=reason,
            now=now,
        )

    def delete_by_user(
        self,
        *,
        requester: IdentityContext,
        target_owner: IdentityContext,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        self.access_policy.assert_allowed(
            requester=requester,
            action=MemoryAccessAction.DELETE_USER,
            resource_owner=target_owner,
        )
        fact_ids = [
            fact.fact_id
            for fact in self.runtime.store.list_facts(identity_context=target_owner)
        ]
        for fact_id in fact_ids:
            self.runtime.delete(
                fact_id,
                identity_context=requester,
                actor=actor,
                reason=reason,
                now=now,
            )
        return tuple(fact_ids)

    def delete_by_tenant(
        self,
        *,
        requester: IdentityContext,
        tenant_id: str,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        self.access_policy.assert_allowed(
            requester=requester,
            action=MemoryAccessAction.DELETE_TENANT,
            tenant_id=tenant_id,
        )
        facts = self.runtime.store.list_facts(tenant_id=tenant_id)
        deleted: list[str] = []
        for fact in facts:
            self.runtime._delete_owned_fact(
                fact,
                requester=requester,
                actor=actor,
                reason=reason,
                now=now,
                tenant_admin=True,
            )
            deleted.append(fact.fact_id)
        return tuple(deleted)

    def correct_fact(
        self,
        fact_id: str,
        *,
        requester: IdentityContext,
        value: Any,
        actor: str,
        reason: str,
        confidence: float = 1.0,
        verified: bool = True,
        now: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryPromotionItemResult:
        now = now or datetime.now(timezone.utc)
        existing = self.runtime.get(fact_id, identity_context=requester)
        self.access_policy.assert_allowed(
            requester=requester,
            action=MemoryAccessAction.UPDATE,
            resource_owner=existing.identity_context,
        )
        candidate = MemoryFactCandidate(
            identity_context=existing.identity_context,
            key=existing.key,
            value=value,
            source="user_confirmation",
            confidence=confidence,
            verified=verified,
            observed_at=now,
            verified_at=now if verified else None,
            verified_by=actor if verified else None,
            expires_at=expires_at,
            reason=reason,
            metadata={"stable": True, "future_reuse": True, "correction": True},
        )
        return self.runtime.promote_candidate(
            candidate,
            actor=actor,
            reason=reason,
            now=now,
        )


__all__ = ["MemoryGovernanceService"]
