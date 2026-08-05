"""Thread-safe latency and resource budgets for Agentic RAG retrieval."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import perf_counter
from typing import Any


@dataclass
class RetrievalBudget:
    """Mutable request budget persisted through ``to_state``/``from_state``.

    Created by Knowledge Agent execution, shared by retrievers and rerankers, and
    consumed by observability/benchmark code.  The lock is intentionally excluded
    from serialization.
    """

    max_dense_queries: int = 6
    max_sparse_queries: int = 8
    max_metadata_queries: int = 4
    max_database_queries: int = 4
    max_candidates: int = 40
    max_final_evidences: int = 8
    max_context_chars: int = 12_000
    max_latency_ms: int = 25_000

    started_at: float | None = None
    elapsed_before_restore_ms: float = 0.0
    dense_queries_used: int = 0
    sparse_queries_used: int = 0
    metadata_queries_used: int = 0
    database_queries_used: int = 0
    candidates_seen: int = 0
    final_evidences_used: int = 0
    context_chars_used: int = 0

    _lock: Any = field(default_factory=Lock, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in (
            "max_dense_queries",
            "max_sparse_queries",
            "max_metadata_queries",
            "max_database_queries",
            "max_candidates",
            "max_final_evidences",
            "max_context_chars",
            "max_latency_ms",
            "elapsed_before_restore_ms",
            "dense_queries_used",
            "sparse_queries_used",
            "metadata_queries_used",
            "database_queries_used",
            "candidates_seen",
            "final_evidences_used",
            "context_chars_used",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.max_final_evidences > self.max_candidates:
            raise ValueError("max_final_evidences cannot exceed max_candidates")

    def start(self) -> "RetrievalBudget":
        with self._lock:
            if self.started_at is None:
                self.started_at = perf_counter()
        return self

    @property
    def elapsed_ms(self) -> float:
        current = 0.0
        if self.started_at is not None:
            current = (perf_counter() - self.started_at) * 1000
        return self.elapsed_before_restore_ms + current

    @property
    def remaining_timeout_ms(self) -> int:
        return max(0, int(self.max_latency_ms - self.elapsed_ms))

    @property
    def remaining_context_chars(self) -> int:
        return max(0, self.max_context_chars - self.context_chars_used)

    @property
    def remaining_candidates(self) -> int:
        return max(0, self.max_candidates - self.candidates_seen)

    @property
    def latency_exceeded(self) -> bool:
        return self.remaining_timeout_ms <= 0

    def _reserve_counter(self, used_name: str, max_name: str) -> bool:
        with self._lock:
            if self.latency_exceeded:
                return False
            if getattr(self, used_name) >= getattr(self, max_name):
                return False
            setattr(self, used_name, getattr(self, used_name) + 1)
            return True

    def reserve_dense(self) -> bool:
        return self._reserve_counter("dense_queries_used", "max_dense_queries")

    def reserve_sparse(self) -> bool:
        return self._reserve_counter("sparse_queries_used", "max_sparse_queries")

    def reserve_metadata(self) -> bool:
        return self._reserve_counter("metadata_queries_used", "max_metadata_queries")

    def reserve_database(self) -> bool:
        return self._reserve_counter("database_queries_used", "max_database_queries")

    def record_candidates(self, count: int) -> int:
        """Account candidates and return how many may enter the shared pipeline."""

        if count < 0:
            raise ValueError("count must be non-negative")
        with self._lock:
            accepted = min(count, max(0, self.max_candidates - self.candidates_seen))
            self.candidates_seen += accepted
            return accepted

    def record_final_evidences(self, count: int) -> int:
        if count < 0:
            raise ValueError("count must be non-negative")
        with self._lock:
            accepted = min(count, self.max_final_evidences)
            self.final_evidences_used = max(self.final_evidences_used, accepted)
            return accepted

    def reserve_context(self, chars: int) -> bool:
        if chars < 0:
            raise ValueError("chars must be non-negative")
        with self._lock:
            if chars > max(0, self.max_context_chars - self.context_chars_used):
                return False
            self.context_chars_used += chars
            return True

    def to_state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "max_dense_queries": self.max_dense_queries,
                "max_sparse_queries": self.max_sparse_queries,
                "max_metadata_queries": self.max_metadata_queries,
                "max_database_queries": self.max_database_queries,
                "max_candidates": self.max_candidates,
                "max_final_evidences": self.max_final_evidences,
                "max_context_chars": self.max_context_chars,
                "max_latency_ms": self.max_latency_ms,
                "elapsed_ms": self.elapsed_ms,
                "remaining_timeout_ms": self.remaining_timeout_ms,
                "dense_queries_used": self.dense_queries_used,
                "sparse_queries_used": self.sparse_queries_used,
                "metadata_queries_used": self.metadata_queries_used,
                "database_queries_used": self.database_queries_used,
                "candidates_seen": self.candidates_seen,
                "final_evidences_used": self.final_evidences_used,
                "context_chars_used": self.context_chars_used,
                "remaining_context_chars": self.remaining_context_chars,
            }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "RetrievalBudget":
        budget = cls(
            max_dense_queries=int(state.get("max_dense_queries", 6)),
            max_sparse_queries=int(state.get("max_sparse_queries", 8)),
            max_metadata_queries=int(state.get("max_metadata_queries", 4)),
            max_database_queries=int(state.get("max_database_queries", 4)),
            max_candidates=int(state.get("max_candidates", 40)),
            max_final_evidences=int(state.get("max_final_evidences", 8)),
            max_context_chars=int(state.get("max_context_chars", 12_000)),
            max_latency_ms=int(state.get("max_latency_ms", 25_000)),
            elapsed_before_restore_ms=float(
                state.get("elapsed_ms", state.get("latency_ms", 0.0))
            ),
            dense_queries_used=int(state.get("dense_queries_used", 0)),
            sparse_queries_used=int(state.get("sparse_queries_used", 0)),
            metadata_queries_used=int(state.get("metadata_queries_used", 0)),
            database_queries_used=int(state.get("database_queries_used", 0)),
            candidates_seen=int(state.get("candidates_seen", 0)),
            final_evidences_used=int(state.get("final_evidences_used", 0)),
            context_chars_used=int(state.get("context_chars_used", 0)),
        )
        budget.started_at = perf_counter()
        return budget
