"""Lazy-loading interface for artifact references."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from time import perf_counter

from artifact.models import Artifact
from artifact.registry import ArtifactRegistry, get_default_artifact_registry
from identity import IdentityContext
from observability import get_default_metrics


@dataclass(slots=True)
class ArtifactResolver:
    registry: ArtifactRegistry | None = None

    def __post_init__(self) -> None:
        if self.registry is None:
            self.registry = get_default_artifact_registry()

    def resolve_artifact(
        self,
        artifact_id: str,
        *,
        identity_context: IdentityContext,
        actor: str = "artifact.resolver",
        reason: str = "lazy load artifact",
        metadata: Mapping[str, Any] | None = None,
    ) -> Artifact:
        assert self.registry is not None
        started = perf_counter()
        artifact = self.registry.get_artifact(
            artifact_id,
            identity_context=identity_context,
        )
        self.registry.record_resolved(
            artifact,
            actor=actor,
            reason=reason,
            metadata=metadata,
        )
        get_default_metrics().observe("artifact_latency_ms", (perf_counter() - started) * 1000)
        return artifact

    def resolve(
        self,
        artifact_id: str,
        *,
        identity_context: IdentityContext,
        actor: str = "artifact.resolver",
        reason: str = "lazy load artifact payload",
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        return self.resolve_artifact(
            artifact_id,
            identity_context=identity_context,
            actor=actor,
            reason=reason,
            metadata=metadata,
        ).payload

    def resolve_reference(
        self,
        reference: Mapping[str, Any],
        *,
        identity_context: IdentityContext,
        actor: str = "artifact.resolver",
        reason: str = "lazy load artifact reference",
    ) -> Any:
        artifact_id = str(reference.get("artifact_id") or "").strip()
        if not artifact_id:
            raise ValueError("Artifact reference requires artifact_id")
        return self.resolve(
            artifact_id,
            identity_context=identity_context,
            actor=actor,
            reason=reason,
            metadata={"reference_source": reference.get("source")},
        )


__all__ = ["ArtifactResolver"]
