"""Agentic RAG retrieval components.

Production entry points are loaded lazily so protocol and budget models remain
importable in lightweight checkpoint/test environments.
"""
from __future__ import annotations

__all__ = ["hybrid_retrieve", "hybrid_search"]


def __getattr__(name: str):
    if name in {"hybrid_retrieve", "hybrid_search"}:
        from retrieval.hybrid_retriever import hybrid_retrieve, hybrid_search
        return {"hybrid_retrieve": hybrid_retrieve, "hybrid_search": hybrid_search}[name]
    raise AttributeError(name)
