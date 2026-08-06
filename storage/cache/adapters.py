"""Read-through cache decorators over backend-neutral interfaces."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from artifact import Artifact
from memory.facts.models import MemoryFact


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class CachedMemoryBackend:
    backend: Any
    cache: Any
    ttl_seconds: int = 60
    on_invalidate: Any = None

    @staticmethod
    def _owner(identity: Any) -> str:
        return f"{identity.tenant_id}:{identity.user_id}"

    def _fact_key(self, fact_id: str, identity: Any) -> str:
        return f"memory:fact:{self._owner(identity)}:{fact_id}"

    def _invalidate_owner(self, identity: Any) -> None:
        self.cache.invalidate_prefix(f"memory:search:{self._owner(identity)}:")
        if callable(self.on_invalidate):
            self.on_invalidate(identity)

    def save_fact(self, fact: MemoryFact) -> MemoryFact:
        result = self.backend.save_fact(fact)
        self.cache.set(self._fact_key(fact.fact_id, fact.identity_context), fact.to_state(), ttl_seconds=self.ttl_seconds)
        self._invalidate_owner(fact.identity_context)
        return result

    def save_fact_with_audit(self, fact: MemoryFact, audit_record: Any) -> MemoryFact:
        method = getattr(self.backend, "save_fact_with_audit", None)
        result = method(fact, audit_record) if callable(method) else self.backend.save_fact(fact)
        self.cache.set(self._fact_key(fact.fact_id, fact.identity_context), fact.to_state(), ttl_seconds=self.ttl_seconds)
        self._invalidate_owner(fact.identity_context)
        return result

    def update_fact(self, fact: MemoryFact) -> MemoryFact:
        result = self.backend.update_fact(fact)
        self.cache.set(self._fact_key(fact.fact_id, fact.identity_context), fact.to_state(), ttl_seconds=self.ttl_seconds)
        self._invalidate_owner(fact.identity_context)
        return result

    def update_fact_with_audit(self, fact: MemoryFact, audit_record: Any) -> MemoryFact:
        method = getattr(self.backend, "update_fact_with_audit", None)
        result = method(fact, audit_record) if callable(method) else self.backend.update_fact(fact)
        self.cache.set(self._fact_key(fact.fact_id, fact.identity_context), fact.to_state(), ttl_seconds=self.ttl_seconds)
        self._invalidate_owner(fact.identity_context)
        return result

    def get_fact(self, fact_id: str, *, identity_context: Any) -> MemoryFact:
        key = self._fact_key(fact_id, identity_context)
        cached = self.cache.get(key)
        if cached is not None:
            return MemoryFact.from_state(cached)
        fact = self.backend.get_fact(fact_id, identity_context=identity_context)
        self.cache.set(key, fact.to_state(), ttl_seconds=self.ttl_seconds)
        return fact

    def delete_fact(self, fact_id: str, *, identity_context: Any) -> MemoryFact:
        fact = self.backend.delete_fact(fact_id, identity_context=identity_context)
        self.cache.delete(self._fact_key(fact_id, identity_context))
        self._invalidate_owner(identity_context)
        return fact

    def delete_fact_with_audit(self, fact_id: str, *, identity_context: Any, audit_record: Any) -> MemoryFact:
        method = getattr(self.backend, "delete_fact_with_audit", None)
        fact = (
            method(fact_id, identity_context=identity_context, audit_record=audit_record)
            if callable(method)
            else self.backend.delete_fact(fact_id, identity_context=identity_context)
        )
        self.cache.delete(self._fact_key(fact_id, identity_context))
        self._invalidate_owner(identity_context)
        return fact

    def search_fact(self, **kwargs: Any) -> list[MemoryFact]:
        identity = kwargs["identity_context"]
        cache_material = {key: value for key, value in kwargs.items() if key != "now"}
        cache_key = f"memory:search:{self._owner(identity)}:{_digest(cache_material)}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return [MemoryFact.from_state(item) for item in cached]
        facts = self.backend.search_fact(**kwargs)
        self.cache.set(cache_key, [fact.to_state() for fact in facts], ttl_seconds=self.ttl_seconds)
        return facts

    def list_facts(self, **kwargs: Any) -> list[MemoryFact]:
        return self.backend.list_facts(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)


@dataclass(slots=True)
class CachedArtifactBackend:
    backend: Any
    cache: Any
    ttl_seconds: int = 120
    on_invalidate: Any = None

    @staticmethod
    def _key(artifact_id: str, identity: Any) -> str:
        return f"artifact:metadata:{identity.tenant_id}:{identity.user_id}:{identity.conversation_id}:{identity.thread_id}:{identity.session_id}:{artifact_id}"

    def save_artifact(self, artifact: Artifact) -> Artifact:
        result = self.backend.save_artifact(artifact)
        self.cache.set(self._key(artifact.artifact_id, artifact.identity_context), artifact.to_state(), ttl_seconds=self.ttl_seconds)
        if callable(self.on_invalidate):
            self.on_invalidate(artifact.identity_context)
        return result

    def get_artifact(self, artifact_id: str, *, identity_context: Any, include_deleted: bool = False) -> Artifact:
        key = self._key(artifact_id, identity_context)
        cached = self.cache.get(key)
        if cached is not None:
            artifact = Artifact.from_state(cached)
            if include_deleted or artifact.status.value != "DELETED":
                return artifact
        artifact = self.backend.get_artifact(artifact_id, identity_context=identity_context, include_deleted=include_deleted)
        self.cache.set(key, artifact.to_state(), ttl_seconds=self.ttl_seconds)
        return artifact

    def delete_artifact(self, artifact_id: str, *, identity_context: Any) -> Artifact:
        artifact = self.backend.delete_artifact(artifact_id, identity_context=identity_context)
        self.cache.delete(self._key(artifact_id, identity_context))
        if callable(self.on_invalidate):
            self.on_invalidate(identity_context)
        return artifact

    def list_artifacts(self, **kwargs: Any) -> list[Artifact]:
        return self.backend.list_artifacts(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)
