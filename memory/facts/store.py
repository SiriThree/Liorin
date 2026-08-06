"""Compatibility exports for the Phase 6 MemoryBackend abstraction."""
from __future__ import annotations

from threading import RLock

from storage.interfaces import MemoryBackend
from storage.memory_backend import InMemoryMemoryBackend


class InMemoryMemoryFactStore(InMemoryMemoryBackend):
    """Backward-compatible Phase 5 name for the canonical in-memory backend."""


MemoryFactStore = MemoryBackend

_DEFAULT_STORE: MemoryFactStore | None = None
_DEFAULT_STORE_LOCK = RLock()


def get_default_memory_fact_store() -> MemoryFactStore:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = InMemoryMemoryFactStore()
        return _DEFAULT_STORE


def set_default_memory_fact_store(store: MemoryFactStore) -> MemoryFactStore:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        _DEFAULT_STORE = store
        return _DEFAULT_STORE


def reset_default_memory_fact_store() -> InMemoryMemoryFactStore:
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        _DEFAULT_STORE = InMemoryMemoryFactStore()
        return _DEFAULT_STORE


__all__ = [
    "InMemoryMemoryFactStore",
    "MemoryFactStore",
    "get_default_memory_fact_store",
    "reset_default_memory_fact_store",
    "set_default_memory_fact_store",
]
