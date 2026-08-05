"""Agent-behavior benchmark adapter."""

from __future__ import annotations

from typing import Any

from agents.knowledge_agent import create_knowledge_agent

from .common import base_state, public_sources, timed


def predict(sample: dict[str, Any], *, model: str | None = None) -> dict[str, Any]:
    state = base_state(sample)
    graph = create_knowledge_agent(use_checkpointer=False)
    state, latency_ms = timed(lambda: graph.invoke(state))
    if state.get("needs_clarification"):
        action = "clarify"
        reason_codes = ["needs_clarification"]
        supplemental_sources: list[str] = []
        retrieval_rounds = 0
    else:
        action = "answer"
        reason_codes = []
        decision = state.get("verification_decision") or {}
        verification_action = decision.get("action") or state.get("answer_verification_action")
        if verification_action in {"supplement", "rewrite", "decompose"}:
            action = "retrieve_more"
            reason_codes.append(str(decision.get("reason") or verification_action))
        if verification_action == "clarify":
            action = "clarify"
            reason_codes.append(str(decision.get("reason") or "needs_clarification"))
        if verification_action == "handoff":
            action = "handoff"
            reason_codes.append(str(decision.get("reason") or "verification_handoff"))
        if not state.get("relevance_passed", True):
            action = "retrieve_more"
            reason_codes.append("low_relevance")
        if state.get("coverage_score", 0.0) < 0.66:
            action = "retrieve_more"
            reason_codes.append("insufficient_coverage")
        if state.get("evidence_conflict"):
            action = "handoff"
            reason_codes.append("evidence_conflict")
        supplemental_sources = public_sources([item.get("source", "") for item in state.get("retrieval_plan", [])])
        retrieval_rounds = int(state.get("retry_count", 0)) + (1 if state.get("evidences") else 0)
    return {
        "id": sample["id"],
        "prediction": {
            "action": action,
            "reason_codes": reason_codes,
            "clarification_slots": [state["clarification_question"]] if state.get("clarification_question") else [],
            "supplemental_sources": supplemental_sources,
            "retrieval_rounds": retrieval_rounds,
            "verification_action": (state.get("verification_decision") or {}).get("action"),
        },
        "diagnostics": {
            "latency_ms": latency_ms,
            "trace_events": state.get("trace_events", []),
            "coverage_score": state.get("coverage_score"),
        },
    }
