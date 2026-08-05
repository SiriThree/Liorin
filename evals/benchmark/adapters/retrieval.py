"""Retrieval benchmark adapter."""

from __future__ import annotations

from typing import Any

from agents.knowledge_agent import execute_retrieval, plan_retrieval, understand_query
from evals.benchmark.corpus_registry import BenchmarkCorpusRegistry

from .common import base_state, public_sources, timed


def predict(
    sample: dict[str, Any],
    *,
    model: str | None = None,
    registry: BenchmarkCorpusRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or BenchmarkCorpusRegistry()
    state = base_state(sample)
    state.update(understand_query(state, model=model))
    state.update(plan_retrieval(state, model=model))
    update, latency_ms = timed(lambda: execute_retrieval(state))
    ranked = []
    source_types = []
    scores = []
    unmapped = []
    for evidence in update.get("evidences", []):
        doc = evidence["document"]
        mapped = registry.map_document(doc)
        source_types.append(mapped.source_type or evidence.get("source_type") or "unknown")
        scores.append(
            {
                "production_chunk_id": mapped.production_chunk_id,
                "retrieval_score": evidence.get("retrieval_score"),
                "rerank_score": evidence.get("rerank_score"),
                "source_type": mapped.source_type,
            }
        )
        if mapped.benchmark_chunk_id:
            ranked.append(mapped.benchmark_chunk_id)
        else:
            unmapped.append(mapped.__dict__)
    return {
        "id": sample["id"],
        "prediction": {
            "ranked_chunk_ids": ranked,
            "source_types": public_sources(source_types),
            "scores": scores,
            "latency_ms": latency_ms,
            "trace_summary": update.get("trace_events", [])[-20:],
        },
        "diagnostics": {
            "latency_ms": latency_ms,
            "unmapped_chunk_ids": unmapped,
            "estimated_cost": update.get("estimated_cost", {}),
        },
    }
