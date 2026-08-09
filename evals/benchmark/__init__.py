"""Versioned Liorin Agentic RAG benchmark integration.

Runner imports are lazy so offline scoring/schema utilities do not bootstrap the
production Agent dependency graph merely by importing ``evals.benchmark``.
"""

from __future__ import annotations

from typing import Any

__all__ = ["BenchmarkRunner", "BenchmarkRunConfig"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .runner import BenchmarkRunConfig, BenchmarkRunner

        return {"BenchmarkRunner": BenchmarkRunner, "BenchmarkRunConfig": BenchmarkRunConfig}[name]
    raise AttributeError(name)
