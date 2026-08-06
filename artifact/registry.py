"""Artifact registration, lifecycle and idempotent creation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Mapping
from time import perf_counter

from artifact.models import (
    Artifact,
    ArtifactLifecycleEvent,
    ArtifactLifecycleRecord,
    ArtifactLifecycleState,
    ArtifactType,
    _json_safe,
    payload_size,
)
from artifact.store import (
    ArtifactConflictError,
    ArtifactNotFoundError,
    ArtifactStore,
    InMemoryArtifactStore,
)
from identity import IdentityContext
from observability import RuntimeEventType, get_default_metrics, get_default_trace_recorder


def payload_fingerprint(payload: Any) -> str:
    normalized = json.dumps(
        _json_safe(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(normalized.encode("utf-8")).hexdigest()


def deterministic_artifact_id(
    *,
    artifact_type: ArtifactType,
    identity_context: IdentityContext,
    source_key: str,
    payload: Any,
) -> str:
    identity = identity_context.to_state()
    raw = json.dumps(
        {
            "type": artifact_type.value,
            "identity": identity,
            "source_key": str(source_key),
            "payload_fingerprint": payload_fingerprint(payload),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"artifact-{sha256(raw.encode('utf-8')).hexdigest()[:24]}"


@dataclass(slots=True)
class ArtifactRegistry:
    store: ArtifactStore = field(default_factory=InMemoryArtifactStore)
    _lifecycle_records: list[ArtifactLifecycleRecord] = field(default_factory=list)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def create_artifact(
        self,
        *,
        artifact_type: ArtifactType,
        identity_context: IdentityContext,
        source: str,
        created_by: str,
        summary: str,
        payload: Any,
        metadata: Mapping[str, Any] | None = None,
        artifact_id: str | None = None,
        created_at: datetime | None = None,
    ) -> Artifact:
        if not isinstance(identity_context, IdentityContext):
            raise TypeError("Artifact creation requires IdentityContext")
        created_at = created_at or datetime.now(timezone.utc)
        fingerprint = payload_fingerprint(payload)
        artifact_id = artifact_id or deterministic_artifact_id(
            artifact_type=artifact_type,
            identity_context=identity_context,
            source_key=source,
            payload=payload,
        )
        full_metadata = {
            **dict(metadata or {}),
            "payload_fingerprint": fingerprint,
        }
        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            identity_context=identity_context,
            source=source,
            created_at=created_at,
            created_by=created_by,
            summary=summary,
            metadata=full_metadata,
            location=f"memory://{artifact_id}",
            size=payload_size(payload),
            status=ArtifactLifecycleState.AVAILABLE,
            payload=payload,
        )

        with self._lock:
            try:
                existing = self.store.get_artifact(
                    artifact_id,
                    identity_context=identity_context,
                    include_deleted=True,
                )
            except ArtifactNotFoundError:
                existing = None
            if existing is not None:
                if existing.metadata.get("payload_fingerprint") != fingerprint:
                    raise ArtifactConflictError(
                        f"Artifact id {artifact_id} already owns a different payload"
                    )
                if existing.status is ArtifactLifecycleState.DELETED:
                    raise ArtifactConflictError(
                        f"Deleted artifact id cannot be reused: {artifact_id}"
                    )
                return existing

            self.store.create_artifact(artifact)
            self._record(
                artifact,
                ArtifactLifecycleEvent.CREATED,
                actor=created_by,
                reason="artifact metadata and payload registered",
                metadata={"status": ArtifactLifecycleState.CREATED.value},
            )
            self._record(
                artifact,
                ArtifactLifecycleEvent.AVAILABLE,
                actor=created_by,
                reason="artifact is available for lazy resolution",
                metadata={"status": ArtifactLifecycleState.AVAILABLE.value},
            )
            get_default_metrics().increment("artifact_created")
            get_default_trace_recorder().emit(
                RuntimeEventType.ARTIFACT_CREATED,
                attributes={"artifact_id": artifact.artifact_id, "artifact_type": artifact.artifact_type.value, "size": artifact.size},
            )
            return artifact

    def get_artifact(
        self,
        artifact_id: str,
        *,
        identity_context: IdentityContext,
        include_deleted: bool = False,
    ) -> Artifact:
        return self.store.get_artifact(
            artifact_id,
            identity_context=identity_context,
            include_deleted=include_deleted,
        )

    def reference_artifact(
        self,
        artifact_id: str,
        *,
        identity_context: IdentityContext,
        actor: str,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Artifact:
        with self._lock:
            artifact = self.store.get_artifact(
                artifact_id,
                identity_context=identity_context,
            )
            if artifact.status is not ArtifactLifecycleState.REFERENCED:
                artifact = artifact.with_status(ArtifactLifecycleState.REFERENCED)
                self.store.update_artifact(artifact)
            self._record(
                artifact,
                ArtifactLifecycleEvent.REFERENCED,
                actor=actor,
                reason=reason,
                metadata=metadata,
            )
            get_default_metrics().increment("artifact_reference_count")
            get_default_trace_recorder().emit(
                RuntimeEventType.ARTIFACT_REFERENCED,
                attributes={"artifact_id": artifact.artifact_id, "artifact_type": artifact.artifact_type.value, "size": artifact.size},
            )
            return artifact

    def record_resolved(
        self,
        artifact: Artifact,
        *,
        actor: str,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._record(
                artifact,
                ArtifactLifecycleEvent.RESOLVED,
                actor=actor,
                reason=reason,
                metadata=metadata,
            )
            get_default_metrics().increment("artifact_retrieval_count")
            get_default_trace_recorder().emit(
                RuntimeEventType.ARTIFACT_RESOLVED,
                attributes={"artifact_id": artifact.artifact_id, "artifact_type": artifact.artifact_type.value, "size": artifact.size},
            )

    def delete_artifact(
        self,
        artifact_id: str,
        *,
        identity_context: IdentityContext,
        actor: str,
        reason: str,
    ) -> Artifact:
        with self._lock:
            deleted = self.store.delete_artifact(
                artifact_id,
                identity_context=identity_context,
            )
            self._record(
                deleted,
                ArtifactLifecycleEvent.DELETED,
                actor=actor,
                reason=reason,
                metadata={"payload_removed": True},
            )
            get_default_metrics().increment("artifact_deleted")
            get_default_trace_recorder().emit(
                RuntimeEventType.ARTIFACT_DELETED,
                attributes={"artifact_id": deleted.artifact_id, "artifact_type": deleted.artifact_type.value},
            )
            return deleted

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

    def lifecycle_records(
        self,
        *,
        artifact_id: str | None = None,
        identity_context: IdentityContext | None = None,
    ) -> list[ArtifactLifecycleRecord]:
        with self._lock:
            return [
                record
                for record in self._lifecycle_records
                if (artifact_id is None or record.artifact_id == artifact_id)
                and (
                    identity_context is None
                    or record.identity_context == identity_context
                )
            ]

    def _record(
        self,
        artifact: Artifact,
        event: ArtifactLifecycleEvent,
        *,
        actor: str,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self._lifecycle_records.append(
            ArtifactLifecycleRecord(
                artifact_id=artifact.artifact_id,
                event=event,
                identity_context=artifact.identity_context,
                actor=actor,
                reason=reason,
                timestamp=datetime.now(timezone.utc),
                metadata={
                    "artifact_type": artifact.artifact_type.value,
                    "artifact_status": artifact.status.value,
                    **dict(metadata or {}),
                },
            )
        )


_DEFAULT_REGISTRY: ArtifactRegistry | None = None
_DEFAULT_LOCK = RLock()


def get_default_artifact_registry() -> ArtifactRegistry:
    global _DEFAULT_REGISTRY
    with _DEFAULT_LOCK:
        if _DEFAULT_REGISTRY is None:
            _DEFAULT_REGISTRY = ArtifactRegistry()
        return _DEFAULT_REGISTRY



def set_default_artifact_registry(registry: ArtifactRegistry) -> ArtifactRegistry:
    global _DEFAULT_REGISTRY
    with _DEFAULT_LOCK:
        _DEFAULT_REGISTRY = registry
        return _DEFAULT_REGISTRY


def reset_default_artifact_registry() -> ArtifactRegistry:
    """Testing/operational reset for the process-local minimum adapter."""

    global _DEFAULT_REGISTRY
    with _DEFAULT_LOCK:
        _DEFAULT_REGISTRY = ArtifactRegistry()
        return _DEFAULT_REGISTRY


__all__ = [
    "ArtifactRegistry",
    "deterministic_artifact_id",
    "get_default_artifact_registry",
    "payload_fingerprint",
    "reset_default_artifact_registry",
    "set_default_artifact_registry",
]
