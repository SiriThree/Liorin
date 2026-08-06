"""Backend-neutral persistence contracts for Liorin Memory and Artifact data."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from artifact import Artifact, ArtifactType
    from identity import IdentityContext
    from memory.facts.models import MemoryFact


@runtime_checkable
class MemoryBackend(Protocol):
    """Persistence contract for long-term MemoryFact records."""

    def save_fact(self, fact: "MemoryFact") -> "MemoryFact": ...

    def get_fact(
        self,
        fact_id: str,
        *,
        identity_context: "IdentityContext",
    ) -> "MemoryFact": ...

    def update_fact(self, fact: "MemoryFact") -> "MemoryFact": ...

    def delete_fact(
        self,
        fact_id: str,
        *,
        identity_context: "IdentityContext",
    ) -> "MemoryFact": ...

    def search_fact(
        self,
        *,
        identity_context: "IdentityContext",
        query: str,
        keys: Iterable[str] = (),
        limit: int = 8,
        now: datetime | None = None,
        include_expired: bool = False,
    ) -> list["MemoryFact"]: ...

    def list_facts(
        self,
        *,
        identity_context: "IdentityContext | None" = None,
        tenant_id: str | None = None,
        include_expired: bool = True,
        now: datetime | None = None,
    ) -> list["MemoryFact"]: ...


@runtime_checkable
class ArtifactBackend(Protocol):
    """Persistence contract for Artifact metadata and payloads."""

    def save_artifact(self, artifact: "Artifact") -> "Artifact": ...

    def get_artifact(
        self,
        artifact_id: str,
        *,
        identity_context: "IdentityContext",
        include_deleted: bool = False,
    ) -> "Artifact": ...

    def delete_artifact(
        self,
        artifact_id: str,
        *,
        identity_context: "IdentityContext",
    ) -> "Artifact": ...

    def list_artifacts(
        self,
        *,
        identity_context: "IdentityContext",
        artifact_type: "ArtifactType | None" = None,
        include_deleted: bool = False,
    ) -> list["Artifact"]: ...
