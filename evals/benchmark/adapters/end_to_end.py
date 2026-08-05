"""Answer-generation and end-to-end benchmark adapters."""

from __future__ import annotations

from typing import Any

from agents.knowledge_agent import (
    create_knowledge_agent,
    execute_retrieval,
    finalize_answer,
    generate_answer,
    grade_evidence,
    plan_retrieval,
    understand_query,
    verify_answer,
)
from evals.benchmark.corpus_registry import BenchmarkCorpusRegistry

from .common import base_state, public_sources, timed


def create_support_agent(*args, **kwargs):
    from agents.support_workflow import create_support_agent as _create_support_agent

    return _create_support_agent(*args, **kwargs)


def predict(
    sample: dict[str, Any],
    *,
    model: str | None = None,
    registry: BenchmarkCorpusRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or BenchmarkCorpusRegistry()
    state = base_state(sample)
    support_graph_answer = None
    support_graph_error = None

    if sample.get("layer") == "end_to_end":
        try:
            support_graph = create_support_agent(use_checkpointer=False)
            support_result = support_graph.invoke(
                {"messages": [{"role": "user", "content": state["original_question"]}]},
                context={"model": model} if model else None,
            )
            support_graph_answer = support_result["messages"][-1].content
        except Exception as exc:
            support_graph_error = str(exc)[:500]

    def run_chain() -> dict[str, Any]:
        try:
            return create_knowledge_agent(use_checkpointer=False).invoke(state)
        except Exception:
            state.update(understand_query(state, model=model))
            if state.get("needs_clarification"):
                return state
            state.update(plan_retrieval(state, model=model))
            state.update(execute_retrieval(state))
            state.update(grade_evidence(state, model=model))
            state.update(generate_answer(state, model=model))
            state.update(verify_answer(state, model=model))
            state.update(finalize_answer(state))
            return state

    update, latency_ms = timed(run_chain)
    cited = []
    used_source_types = []
    unmapped = []
    for evidence in update.get("evidences", []):
        mapped = registry.map_document(evidence["document"])
        used_source_types.append(mapped.source_type or evidence.get("source_type") or "unknown")
        if mapped.benchmark_chunk_id:
            cited.append(mapped.benchmark_chunk_id)
        else:
            unmapped.append(mapped.__dict__)
    answer = support_graph_answer or update.get("answer") or update.get("clarification_question") or ""
    decision = update.get("verification_action") or ("clarify" if update.get("needs_clarification") else "answer")
    return {
        "id": sample["id"],
        "prediction": {
            "answer": answer,
            "response_type": "clarification" if update.get("needs_clarification") else "answer",
            "cited_chunk_ids": cited,
            "used_sources": public_sources(used_source_types),
            "decision_code": decision,
            "actions": [decision] if decision else [],
            "retrieval_rounds": int(update.get("retry_count", 0)) + (1 if update.get("evidences") else 0),
            "latency_ms": latency_ms,
            "cost_metadata": update.get("estimated_cost", {}),
        },
        "diagnostics": {
            "latency_ms": latency_ms,
            "unmapped_chunk_ids": unmapped,
            "trace_events": update.get("trace_events", []),
            "support_graph_called": sample.get("layer") == "end_to_end",
            "support_graph_fallback_reason": support_graph_error,
        },
    }
