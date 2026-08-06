"""Reference persistence backends for long-term MemoryFact records."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from threading import RLock

from identity import IdentityContext
from memory.facts.models import MemoryFact, canonical_value
from storage.interfaces import MemoryBackend


def _owner(identity: IdentityContext) -> tuple[str, str]:
    return identity.tenant_id, identity.user_id


def _terms(value: str) -> set[str]:
    normalized = "".join(char.casefold() if char.isalnum() else " " for char in value)
    tokens = {token for token in normalized.split() if token}
    tokens.update(char for char in value if "\u4e00" <= char <= "\u9fff")
    return tokens


class InMemoryMemoryBackend:
    """Thread-safe process-local backend implementing the production contract."""

    def __init__(self) -> None:
        self._facts: dict[str, MemoryFact] = {}
        self._lock = RLock()

    def save_fact(self, fact: MemoryFact) -> MemoryFact:
        with self._lock:
            if fact.fact_id in self._facts:
                raise KeyError(f"MemoryFact already exists: {fact.fact_id}")
            self._facts[fact.fact_id] = fact
            return fact

    def get_fact(self, fact_id: str, *, identity_context: IdentityContext) -> MemoryFact:
        with self._lock:
            try:
                fact = self._facts[str(fact_id)]
            except KeyError as exc:
                raise KeyError(f"MemoryFact not found: {fact_id}") from exc
            self._assert_owner(fact, identity_context)
            return fact

    def update_fact(self, fact: MemoryFact) -> MemoryFact:
        with self._lock:
            existing = self._facts.get(fact.fact_id)
            if existing is None:
                raise KeyError(f"MemoryFact not found: {fact.fact_id}")
            if existing.owner_key != fact.owner_key:
                raise PermissionError("MemoryFact owner cannot be changed")
            if existing.key != fact.key:
                raise ValueError("MemoryFact key cannot be changed")
            self._facts[fact.fact_id] = fact
            return fact

    def delete_fact(self, fact_id: str, *, identity_context: IdentityContext) -> MemoryFact:
        with self._lock:
            fact = self.get_fact(fact_id, identity_context=identity_context)
            del self._facts[fact.fact_id]
            return fact

    def search_fact(
        self,
        *,
        identity_context: IdentityContext,
        query: str,
        keys: Iterable[str] = (),
        limit: int = 8,
        now: datetime | None = None,
        include_expired: bool = False,
    ) -> list[MemoryFact]:
        if limit <= 0:
            return []
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("MemoryBackend.search_fact requires timezone-aware now")
        requested_keys = {str(key).strip().casefold() for key in keys if str(key).strip()}
        query_terms = _terms(str(query or ""))
        if not query_terms and not requested_keys:
            return []

        ranked: list[tuple[float, MemoryFact]] = []
        with self._lock:
            for fact in self._facts.values():
                if fact.owner_key != _owner(identity_context):
                    continue
                if fact.is_expired(now=now) and not include_expired:
                    continue
                key = fact.key.casefold()
                key_terms = _terms(fact.key.replace("_", " "))
                value_terms = _terms(canonical_value(fact.value))
                score = 0.0
                if key in requested_keys:
                    score += 20.0
                score += 4.0 * len(query_terms & key_terms)
                score += 1.5 * len(query_terms & value_terms)
                if not score:
                    continue
                score += float(fact.confidence)
                if fact.verified:
                    score += 1.0
                ranked.append((score, fact))
        ranked.sort(
            key=lambda item: (
                -item[0],
                -int(item[1].verified),
                -item[1].confidence,
                -item[1].updated_at.timestamp(),
                item[1].fact_id,
            )
        )
        return [fact for _, fact in ranked[:limit]]

    def list_facts(
        self,
        *,
        identity_context: IdentityContext | None = None,
        tenant_id: str | None = None,
        include_expired: bool = True,
        now: datetime | None = None,
    ) -> list[MemoryFact]:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            result = []
            for fact in self._facts.values():
                if identity_context is not None and fact.owner_key != _owner(identity_context):
                    continue
                if tenant_id is not None and fact.identity_context.tenant_id != tenant_id:
                    continue
                if not include_expired and fact.is_expired(now=now):
                    continue
                result.append(fact)
            return sorted(result, key=lambda item: (item.identity_context.tenant_id, item.identity_context.user_id, item.key, item.fact_id))

    # Phase 5 compatibility surface. Business Runtime uses the canonical
    # save_fact/get_fact/update_fact/delete_fact/search_fact methods.
    def save(self, fact: MemoryFact) -> MemoryFact:
        return self.save_fact(fact)

    def get(self, fact_id: str, *, identity_context: IdentityContext) -> MemoryFact:
        return self.get_fact(fact_id, identity_context=identity_context)

    def update(self, fact: MemoryFact) -> MemoryFact:
        return self.update_fact(fact)

    def delete(self, fact_id: str, *, identity_context: IdentityContext) -> MemoryFact:
        return self.delete_fact(fact_id, identity_context=identity_context)

    def search(self, **kwargs) -> list[MemoryFact]:
        return self.search_fact(**kwargs)

    def all_for_owner(self, *, identity_context: IdentityContext) -> list[MemoryFact]:
        return self.list_facts(identity_context=identity_context)

    def count(self) -> int:
        with self._lock:
            return len(self._facts)

    @staticmethod
    def _assert_owner(fact: MemoryFact, identity_context: IdentityContext) -> None:
        if not fact.is_owned_by(identity_context):
            raise PermissionError("MemoryFact belongs to a different tenant/user")


assert isinstance(InMemoryMemoryBackend(), MemoryBackend)

__all__ = ["InMemoryMemoryBackend", "MemoryBackend"]
