"""Answer-generation diagnostic adapter and production end-to-end adapter.

Phase 0 deliberately separates two responsibilities:

* ``answer_generation`` remains a legacy Knowledge-Agent component diagnostic.
* ``end_to_end`` is routed through ``ProductionEvaluationAdapter`` and therefore
  obeys ONE CASE -> ONE PRODUCTION EXECUTION -> ONE TRACE.

No specialist/retrieval fallback is allowed after a production E2E execution.
"""

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
from eval_platform import ProductionEvaluationAdapter, RuntimeCaseInput
from evals.benchmark.corpus_registry import BenchmarkCorpusRegistry

from .common import base_state, public_sources, timed


def _runtime_case_from_sample(sample: dict[str, Any], *, model: str | None) -> RuntimeCaseInput:
    """Project only runtime-visible fields from a legacy benchmark sample."""

    inputs = sample.get("input") or {}
    conversation = tuple(
        {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")}
        for item in (inputs.get("conversation") or [])
        if isinstance(item, dict) and item.get("content") is not None
    )
    if not conversation:
        question = str(inputs.get("question") or inputs.get("query") or "")
        conversation = ({"role": "user", "content": question},)

    identity_source = inputs.get("identity_context") or inputs.get("identity") or inputs.get("principal") or {}
    identity = {
        key: identity_source[key]
        for key in ("tenant_id", "user_id", "conversation_id", "thread_id", "session_id")
        if isinstance(identity_source, dict) and identity_source.get(key)
    }
    context = {"model": model} if model else {}
    return RuntimeCaseInput(
        case_id=str(sample["id"]),
        messages=conversation,
        identity=identity,
        context=context,
        metadata={"legacy_layer": "end_to_end"},
    )


def _predict_production_e2e(
    sample: dict[str, Any],
    *,
    model: str | None,
    registry: BenchmarkCorpusRegistry,
) -> dict[str, Any]:
    record = ProductionEvaluationAdapter().run(_runtime_case_from_sample(sample, model=model))
    facts = dict(record.trace_facts)
    selected_ids = [str(item) for item in facts.get("selected_evidence_ids", [])]
    cited: list[str] = []
    unmapped: list[dict[str, Any]] = []
    for evidence_id in selected_ids:
        if evidence_id in registry.by_chunk_id:
            cited.append(evidence_id)
        else:
            unmapped.append({
                "production_evidence_id": evidence_id,
                "reason": "trace evidence id is absent from benchmark corpus manifest",
            })

    used_sources = public_sources(list(facts.get("used_sources", [])))
    if not used_sources:
        used_sources = public_sources(
            [registry.source_type_for(chunk_id) or "unknown" for chunk_id in cited]
        )
    verifier_actions = [str(item) for item in facts.get("verifier_actions", []) if item]
    recovery_actions = [str(item) for item in facts.get("recovery_actions", []) if item]
    workflow_decisions = list(facts.get("workflow_decisions", []))
    latest_workflow_action = (
        str(workflow_decisions[-1].get("action") or "")
        if workflow_decisions and isinstance(workflow_decisions[-1], dict)
        else ""
    )
    decision = verifier_actions[-1] if verifier_actions else latest_workflow_action or record.response_type

    return {
        "id": sample["id"],
        "prediction": {
            "answer": record.final_response,
            "response_type": record.response_type,
            "cited_chunk_ids": cited,
            "used_sources": used_sources,
            "decision_code": decision,
            "actions": recovery_actions,
            "retrieval_rounds": int(facts.get("retrieval_rounds", 0) or 0),
            "latency_ms": record.runtime_metrics.get("latency_ms"),
            "cost_metadata": {
                "model_calls": record.runtime_metrics.get("model_calls", 0),
                "tool_calls": record.runtime_metrics.get("tool_calls", 0),
            },
        },
        "diagnostics": {
            "latency_ms": record.runtime_metrics.get("latency_ms"),
            "unmapped_chunk_ids": unmapped,
            "trace_id": record.trace_id,
            "trace_facts": facts,
            "support_graph_called": True,
            "single_execution": True,
            "execution_status": record.execution_status,
            "execution_error": record.execution_error,
            "support_graph_fallback_reason": None,
        },
    }


def predict(
    sample: dict[str, Any],
    *,
    model: str | None = None,
    registry: BenchmarkCorpusRegistry | None = None,
) -> dict[str, Any]:
    registry = registry or BenchmarkCorpusRegistry()

    if sample.get("layer") == "end_to_end":
        return _predict_production_e2e(sample, model=model, registry=registry)

    # Legacy answer-generation diagnostic. It intentionally exercises the
    # Knowledge Agent directly and must not be reported as formal E2E success.
    state = base_state(sample)

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
    answer = update.get("answer") or update.get("clarification_question") or ""
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
            "support_graph_called": False,
            "single_execution": True,
            "component_diagnostic": "answer_generation",
        },
    }
