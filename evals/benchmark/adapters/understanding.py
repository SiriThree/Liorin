"""Query-understanding benchmark adapter."""

from __future__ import annotations

from typing import Any

from agents.knowledge_agent import understand_query

from .common import base_state, timed


def predict(sample: dict[str, Any], *, model: str | None = None) -> dict[str, Any]:
    state = base_state(sample)
    update, latency_ms = timed(lambda: understand_query(state, model=model))
    entities = {
        "product_name": update.get("product_name"),
        "product_id": update.get("product_id"),
        "product_model": update.get("product_model"),
        "product_alias": None,
        "accessory_model": None,
        "error_code": update.get("error_code"),
    }
    requirements = update.get("requirements") or []
    return {
        "id": sample["id"],
        "prediction": {
            "entities": entities,
            "task_type": update.get("task_type") or "unknown",
            "requirement_concept_ids": [
                req if str(req).startswith(("manual:", "policy:", "faq:", "ticket:", "database:")) else f"free_text:{idx}"
                for idx, req in enumerate(requirements)
            ],
            "needs_clarification": bool(update.get("needs_clarification")),
            "clarification_slots": [update["clarification_question"]] if update.get("clarification_question") else [],
            "rewritten_question": update.get("rewritten_question"),
        },
        "diagnostics": {
            "latency_ms": latency_ms,
            "trace_events": update.get("trace_events", []),
            "estimated_cost": update.get("estimated_cost", {}),
        },
    }
