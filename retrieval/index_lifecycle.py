"""Versioned index manifest, blue/green activation, rollback and consistency checks."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class IndexManifest:
    corpus_version: str
    embedding_model_version: str
    embedding_dimension: int
    tokenizer_version: str
    chunking_version: str
    metadata_schema_version: str
    index_build_id: str = field(default_factory=lambda: uuid4().hex)
    collection_name: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    document_count: int = 0
    chunk_count: int = 0
    status: str = "building"  # building | ready | failed | retired
    checksum: str | None = None
    parent_build_id: str | None = None
    build_mode: str = "full_green"
    changed_document_ids: list[str] = field(default_factory=list)

    def to_state(self) -> dict[str, Any]:
        return asdict(self)

    def compatible_with(self, *, embedding_model_version: str, embedding_dimension: int, metadata_schema_version: str) -> bool:
        return (
            self.embedding_model_version == embedding_model_version
            and self.embedding_dimension == embedding_dimension
            and self.metadata_schema_version == metadata_schema_version
            and self.status == "ready"
        )


class IndexLifecycleManager:
    """Filesystem-backed atomic registry suitable for one deployment control plane."""

    def __init__(self, registry_path: Path):
        self.registry_path = registry_path
        self._lock = Lock()

    def _load(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {
                "active_build_id": None, "previous_build_id": None, "builds": {},
                "tombstones": [], "pending_changes": [], "rebuild_history": [],
            }
        state = json.loads(self.registry_path.read_text(encoding="utf-8"))
        state.setdefault("active_build_id", None)
        state.setdefault("previous_build_id", None)
        state.setdefault("builds", {})
        state.setdefault("tombstones", [])
        state.setdefault("pending_changes", [])
        state.setdefault("rebuild_history", [])
        return state

    def _save(self, state: dict[str, Any]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.registry_path.with_suffix(self.registry_path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self.registry_path)

    def register_build(self, manifest: IndexManifest) -> None:
        with self._lock:
            state = self._load()
            state["builds"][manifest.index_build_id] = manifest.to_state()
            self._save(state)

    def mark_ready(self, build_id: str, *, checksum: str | None = None) -> None:
        with self._lock:
            state = self._load()
            build = state["builds"].get(build_id)
            if not build:
                raise KeyError(f"unknown index build: {build_id}")
            build["status"] = "ready"
            build["checksum"] = checksum or build.get("checksum")
            self._save(state)

    def mark_failed(self, build_id: str) -> None:
        with self._lock:
            state = self._load()
            build = state["builds"].get(build_id)
            if not build:
                raise KeyError(f"unknown index build: {build_id}")
            build["status"] = "failed"
            self._save(state)

    def activate(self, build_id: str) -> None:
        with self._lock:
            state = self._load()
            build = state["builds"].get(build_id)
            if not build or build.get("status") != "ready":
                raise ValueError("only a ready index build can be activated")
            state["previous_build_id"] = state.get("active_build_id")
            state["active_build_id"] = build_id
            state["rebuild_history"].append({
                "event": "activate", "build_id": build_id,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            self._save(state)

    def rollback(self) -> str:
        with self._lock:
            state = self._load()
            previous = state.get("previous_build_id")
            if not previous or state["builds"].get(previous, {}).get("status") != "ready":
                raise ValueError("no ready previous index build is available")
            current = state.get("active_build_id")
            state["active_build_id"] = previous
            state["previous_build_id"] = current
            state["rebuild_history"].append({
                "event": "rollback", "build_id": previous, "from_build_id": current,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            self._save(state)
            return previous

    def record_document_change(
        self,
        operation: str,
        document_id: str,
        *,
        reason: str | None = None,
        requested_by_hash: str | None = None,
    ) -> str:
        """Journal add/update/delete/invalidate before the next green rebuild.

        Liorin intentionally avoids unsafe in-place vector mutation.  Incremental
        source changes are journaled, then applied by a complete green build and
        atomic activation.  Deletes/invalidation take effect immediately through
        tombstones and remain in the next physical rebuild.
        """
        if operation not in {"add", "update", "delete", "invalidate", "restore"}:
            raise ValueError(f"unsupported index change operation: {operation}")
        change_id = uuid4().hex
        with self._lock:
            state = self._load()
            state["pending_changes"].append({
                "change_id": change_id,
                "operation": operation,
                "document_id": document_id,
                "reason": reason,
                "requested_by_hash": requested_by_hash,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            tombstones = set(state.get("tombstones") or [])
            if operation in {"delete", "invalidate"}:
                tombstones.add(document_id)
            elif operation == "restore":
                tombstones.discard(document_id)
            state["tombstones"] = sorted(tombstones)
            self._save(state)
        return change_id

    def pending_changes(self) -> list[dict[str, Any]]:
        return list(self._load().get("pending_changes") or [])

    def mark_changes_applied(self, build_id: str, change_ids: list[str]) -> None:
        with self._lock:
            state = self._load()
            known = {row.get("change_id") for row in state.get("pending_changes", [])}
            unknown = set(change_ids) - known
            if unknown:
                raise KeyError(f"unknown change ids: {sorted(unknown)}")
            state["pending_changes"] = [
                row for row in state.get("pending_changes", []) if row.get("change_id") not in set(change_ids)
            ]
            state["rebuild_history"].append({
                "event": "changes_applied", "build_id": build_id,
                "change_ids": list(change_ids),
                "at": datetime.now(timezone.utc).isoformat(),
            })
            self._save(state)

    def delete_document(self, document_id: str) -> None:
        self.record_document_change("delete", document_id)

    def restore_document(self, document_id: str) -> None:
        self.record_document_change("restore", document_id)

    def is_deleted(self, document_id: str) -> bool:
        return document_id in set(self._load().get("tombstones") or [])

    def active_manifest(self) -> IndexManifest | None:
        state = self._load()
        active = state.get("active_build_id")
        row = state.get("builds", {}).get(active) if active else None
        return IndexManifest(**row) if row else None

    def check_consistency(self) -> list[str]:
        state = self._load()
        errors: list[str] = []
        active = state.get("active_build_id")
        if active and active not in state.get("builds", {}):
            errors.append("active build is missing")
        if active and state["builds"][active].get("status") != "ready":
            errors.append("active build is not ready")
        return errors


def content_checksum(values: list[str]) -> str:
    return sha256("\n".join(values).encode("utf-8")).hexdigest()
