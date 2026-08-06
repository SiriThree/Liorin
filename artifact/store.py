"""Artifact Store interface and minimum in-memory implementation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, runtime_checkable

from artifact.models import Artifact, ArtifactLifecycleState, ArtifactType
from identity import IdentityContext


class ArtifactNotFoundError(KeyError):
    pass


class ArtifactIdentityError(PermissionError):
    pass


class ArtifactConflictError(ValueError):
    pass


def _assert_identity(owner: IdentityContext, requester: IdentityContext) -> None:
    if owner != requester:
        raise ArtifactIdentityError(
            "Artifact identity mismatch: artifact access requires the exact "
            "tenant/user/conversation/thread/session ownership context"
        )


@runtime_checkable
class ArtifactStore(Protocol):
    def create_artifact(self, artifact: Artifact) -> Artifact: ...

    def get_artifact(
        self,
        artifact_id: str,
        *,
        identity_context: IdentityContext,
        include_deleted: bool = False,
    ) -> Artifact: ...

    def delete_artifact(
        self,
        artifact_id: str,
        *,
        identity_context: IdentityContext,
    ) -> Artifact: ...

    def list_artifacts(
        self,
        *,
        identity_context: IdentityContext,
        artifact_type: ArtifactType | None = None,
        include_deleted: bool = False,
    ) -> list[Artifact]: ...

    def update_artifact(self, artifact: Artifact) -> Artifact: ...


@dataclass(slots=True)
class InMemoryArtifactStore:
    """Thread-safe minimum store.

    Deletion removes the payload while retaining a tombstone metadata record so
    lifecycle audit can still identify what was deleted.
    """

    _artifacts: dict[str, Artifact] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def create_artifact(self, artifact: Artifact) -> Artifact:
        with self._lock:
            existing = self._artifacts.get(artifact.artifact_id)
            if existing is not None:
                raise ArtifactConflictError(
                    f"Artifact already exists: {artifact.artifact_id}"
                )
            self._artifacts[artifact.artifact_id] = artifact
            return artifact

    def update_artifact(self, artifact: Artifact) -> Artifact:
        with self._lock:
            existing = self._artifacts.get(artifact.artifact_id)
            if existing is None:
                raise ArtifactNotFoundError(artifact.artifact_id)
            _assert_identity(existing.identity_context, artifact.identity_context)
            self._artifacts[artifact.artifact_id] = artifact
            return artifact

    def get_artifact(
        self,
        artifact_id: str,
        *,
        identity_context: IdentityContext,
        include_deleted: bool = False,
    ) -> Artifact:
        with self._lock:
            artifact = self._artifacts.get(str(artifact_id))
            if artifact is None:
                raise ArtifactNotFoundError(str(artifact_id))
            _assert_identity(artifact.identity_context, identity_context)
            if artifact.status is ArtifactLifecycleState.DELETED and not include_deleted:
                raise ArtifactNotFoundError(str(artifact_id))
            return artifact

    def delete_artifact(
        self,
        artifact_id: str,
        *,
        identity_context: IdentityContext,
    ) -> Artifact:
        with self._lock:
            artifact = self.get_artifact(
                artifact_id,
                identity_context=identity_context,
                include_deleted=True,
            )
            if artifact.status is ArtifactLifecycleState.DELETED:
                return artifact
            deleted = artifact.with_status(
                ArtifactLifecycleState.DELETED,
                payload=None,
                size=0,
            )
            self._artifacts[artifact.artifact_id] = deleted
            return deleted

    def list_artifacts(
        self,
        *,
        identity_context: IdentityContext,
        artifact_type: ArtifactType | None = None,
        include_deleted: bool = False,
    ) -> list[Artifact]:
        with self._lock:
            result = []
            for artifact in self._artifacts.values():
                if artifact.identity_context != identity_context:
                    continue
                if artifact_type is not None and artifact.artifact_type is not artifact_type:
                    continue
                if not include_deleted and artifact.status is ArtifactLifecycleState.DELETED:
                    continue
                result.append(artifact)
            return sorted(result, key=lambda item: (item.created_at, item.artifact_id))


__all__ = [
    "ArtifactConflictError",
    "ArtifactIdentityError",
    "ArtifactNotFoundError",
    "ArtifactStore",
    "InMemoryArtifactStore",
]
