"""Liorin Working, Delta and long-term structured memory primitives.

Exports are resolved lazily to keep the Memory package independent from the
Context Runtime during module initialization.
"""

from __future__ import annotations

from importlib import import_module


_EXPORT_MODULES = {
    "MemoryDeltaDetector": "memory.delta",
    "MemoryUpdate": "memory.delta",
    "memory_fingerprint": "memory.delta",
    "semantic_memory_state": "memory.delta",
    "InMemoryWorkingMemoryLifecycleAdapter": "memory.working",
    "WorkingMemory": "memory.working",
    "WorkingMemoryExtractor": "memory.working",
    "WorkingMemoryPolicy": "memory.working",
    "WorkingMemoryPolicyDecision": "memory.working",
    "WorkingMemorySerializer": "memory.working",
    "WorkingMemoryUpdate": "memory.working",
    "WorkingMemoryUpdater": "memory.working",
    "InMemoryMemoryFactStore": "memory.facts",
    "LongTermMemoryRuntime": "memory.facts",
    "MemoryCandidateExtractor": "memory.facts",
    "MemoryFact": "memory.facts",
    "MemoryFactCandidate": "memory.facts",
    "MemoryFactDeltaDetector": "memory.facts",
    "MemoryFactPolicy": "memory.facts",
    "MemoryFactSource": "memory.facts",
    "MemoryFactStore": "memory.facts",
    "MemoryPolicy": "memory.facts",
    "MemoryPolicyDecision": "memory.facts",
    "MemoryPromotionResult": "memory.facts",
    "MemoryRetrievalResult": "memory.facts",
    "MemoryRetriever": "memory.facts",
    "deterministic_memory_fact_id": "memory.facts",
    "get_default_long_term_memory_runtime": "memory.facts",
    "reset_default_long_term_memory_runtime": "memory.facts",
}


def __getattr__(name: str):
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


__all__ = sorted(_EXPORT_MODULES)
