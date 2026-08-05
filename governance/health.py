"""Dependency and index health snapshot without leaking credentials or identities."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from config import DEFAULT_DB_PATH, DEFAULT_INDEX_REGISTRY_PATH
from retrieval.index_lifecycle import IndexLifecycleManager
from retrieval.resilience import DEPENDENCIES


def _database_health(path: Path) -> dict[str, Any]:
    try:
        uri = f"file:{path}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=0.2) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("SELECT 1").fetchone()
        return {"status": "healthy", "read_only_probe": True}
    except sqlite3.Error as exc:
        return {"status": "unhealthy", "read_only_probe": False, "error_type": type(exc).__name__}


def system_health(
    *,
    database_path: Path = DEFAULT_DB_PATH,
    index_registry_path: Path = DEFAULT_INDEX_REGISTRY_PATH,
    extra_checks: dict[str, Callable[[], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    index_manager = IndexLifecycleManager(index_registry_path)
    index_errors = index_manager.check_consistency() if index_registry_path.exists() else ["index registry missing"]
    checks: dict[str, Any] = {
        "database": _database_health(database_path),
        "index": {
            "status": "healthy" if not index_errors else "degraded",
            "consistency_errors": index_errors,
            "active_build_id": getattr(index_manager.active_manifest(), "index_build_id", None),
        },
        "dependency_circuits": DEPENDENCIES.health(),
    }
    for name, callback in (extra_checks or {}).items():
        try:
            checks[name] = callback()
        except Exception as exc:  # health checks must report, not crash the endpoint
            checks[name] = {"status": "unhealthy", "error_type": type(exc).__name__}
    unhealthy = any(
        isinstance(value, dict) and value.get("status") == "unhealthy"
        for value in checks.values()
    )
    degraded = any(
        isinstance(value, dict) and value.get("status") == "degraded"
        for value in checks.values()
    )
    return {"status": "unhealthy" if unhealthy else "degraded" if degraded else "healthy", "checks": checks}
