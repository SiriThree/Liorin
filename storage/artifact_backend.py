"""ArtifactBackend adapters over the existing Phase 4 Artifact Store."""
from __future__ import annotations

from dataclasses import dataclass, field

from artifact.models import Artifact, ArtifactLifecycleState, ArtifactType
from artifact.store import (
    ArtifactConflictError,
    ArtifactNotFoundError,
    ArtifactStore,
    InMemoryArtifactStore,
)
from identity import IdentityContext
from storage.interfaces import ArtifactBackend


@dataclass(slots=True)
class ArtifactStoreBackendAdapter:
    """Expose an existing ArtifactStore through the production backend contract."""

    store: ArtifactStore = field(default_factory=InMemoryArtifactStore)

    def save_artifact(self, artifact: Artifact) -> Artifact:
        try:
            existing = self.store.get_artifact(
                artifact.artifact_id,
                identity_context=artifact.identity_context,
                include_deleted=True,
            )
        except ArtifactNotFoundError:
            return self.store.create_artifact(artifact)
        if existing.identity_context != artifact.identity_context:
            raise PermissionError("Artifact owner cannot be changed")
        return self.store.update_artifact(artifact)

    def get_artifact(self, artifact_id: str, *, identity_context: IdentityContext, include_deleted: bool = False) -> Artifact:
        return self.store.get_artifact(
            artifact_id,
            identity_context=identity_context,
            include_deleted=include_deleted,
        )

    def delete_artifact(self, artifact_id: str, *, identity_context: IdentityContext) -> Artifact:
        return self.store.delete_artifact(artifact_id, identity_context=identity_context)

    def list_artifacts(
        self,
        *,
        identity_context: IdentityContext,
        artifact_type: ArtifactType | None = None,
        include_deleted: bool = False,
    ) -> list[Artifact]:
        return self.store.list_artifacts(
            identity_context=identity_context,
            artifact_type=artifact_type,
            include_deleted=include_deleted,
        )


@dataclass(slots=True)
class BackendArtifactStoreAdapter:
    """Let the existing ArtifactRegistry run on any ArtifactBackend."""

    backend: ArtifactBackend

    def create_artifact(self, artifact: Artifact) -> Artifact:
        try:
            self.backend.get_artifact(
                artifact.artifact_id,
                identity_context=artifact.identity_context,
                include_deleted=True,
            )
        except (ArtifactNotFoundError, KeyError):
            return self.backend.save_artifact(artifact)
        raise ArtifactConflictError(f"Artifact already exists: {artifact.artifact_id}")

    def update_artifact(self, artifact: Artifact) -> Artifact:
        return self.backend.save_artifact(artifact)

    def get_artifact(self, artifact_id: str, *, identity_context: IdentityContext, include_deleted: bool = False) -> Artifact:
        try:
            return self.backend.get_artifact(
                artifact_id,
                identity_context=identity_context,
                include_deleted=include_deleted,
            )
        except KeyError as exc:
            raise ArtifactNotFoundError(str(artifact_id)) from exc

    def delete_artifact(self, artifact_id: str, *, identity_context: IdentityContext) -> Artifact:
        return self.backend.delete_artifact(
            artifact_id,
            identity_context=identity_context,
        )

    def list_artifacts(
        self,
        *,
        identity_context: IdentityContext,
        artifact_type: ArtifactType | None = None,
        include_deleted: bool = False,
    ) -> list[Artifact]:
        return self.backend.list_artifacts(
            identity_context=identity_context,
            artifact_type=artifact_type,
            include_deleted=include_deleted,
        )


InMemoryArtifactBackend = ArtifactStoreBackendAdapter

__all__ = [
    "ArtifactStoreBackendAdapter",
    "BackendArtifactStoreAdapter",
    "InMemoryArtifactBackend",
]
