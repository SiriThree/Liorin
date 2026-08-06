"""Production persistence contracts with lazy exports to avoid import cycles."""
from __future__ import annotations

from typing import Any

__all__ = [
    "ArtifactBackend", "ArtifactStoreBackendAdapter", "BackendArtifactStoreAdapter",
    "InMemoryArtifactBackend", "InMemoryMemoryBackend", "MemoryBackend",
]


def __getattr__(name: str) -> Any:
    if name in {"ArtifactBackend", "MemoryBackend"}:
        from storage.interfaces import ArtifactBackend, MemoryBackend
        return {"ArtifactBackend": ArtifactBackend, "MemoryBackend": MemoryBackend}[name]
    if name == "InMemoryMemoryBackend":
        from storage.memory_backend import InMemoryMemoryBackend
        return InMemoryMemoryBackend
    if name in {"ArtifactStoreBackendAdapter", "BackendArtifactStoreAdapter", "InMemoryArtifactBackend"}:
        from storage.artifact_backend import ArtifactStoreBackendAdapter, BackendArtifactStoreAdapter, InMemoryArtifactBackend
        return {
            "ArtifactStoreBackendAdapter": ArtifactStoreBackendAdapter,
            "BackendArtifactStoreAdapter": BackendArtifactStoreAdapter,
            "InMemoryArtifactBackend": InMemoryArtifactBackend,
        }[name]
    raise AttributeError(name)
