"""Routing benchmark adapter."""

from __future__ import annotations

from typing import Any

from agents.knowledge_agent import plan_retrieval, understand_query

from .common import base_state, public_sources, timed


def predict(sample: dict[str, Any], *, model: str | None = None) -> dict[str, Any]:
    state = base_state(sample)
    understood = understand_query(state, model=model)
    state.update(understood)
    plan_update, latency_ms = timed(lambda: plan_retrieval(state, model=model))
    plan = plan_update.get("retrieval_plan", [])
    sources = public_sources([item.get("source", "all") for item in plan])
    if any(item.get("source") == "all" for item in plan):
        sources = ["database", "faq", "manual", "policy", "ticket_history"]
    return {
        "id": sample["id"],
        "prediction": {
            "selected_sources": sources,
            "planned_query_count": len(plan),
            "plan_details": plan,
        },
        "diagnostics": {
            "latency_ms": latency_ms,
            "trace_events": plan_update.get("trace_events", []),
            "estimated_cost": plan_update.get("estimated_cost", {}),
        },
    }
