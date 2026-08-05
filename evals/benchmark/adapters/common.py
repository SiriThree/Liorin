"""Common helpers for benchmark adapters."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from langchain_core.messages import HumanMessage


def question_from_sample(sample: dict[str, Any]) -> str:
    inputs = sample.get("input", {})
    if inputs.get("question"):
        return str(inputs["question"])
    conversation = inputs.get("conversation") or []
    for message in reversed(conversation):
        if message.get("role") == "user" and message.get("content"):
            return str(message["content"])
    return str(inputs.get("query") or "")


def base_state(sample: dict[str, Any]) -> dict[str, Any]:
    question = question_from_sample(sample)
    state = {
        "messages": [HumanMessage(content=question)],
        "original_question": question,
        "trace_events": [],
        "estimated_cost": {},
        "use_cross_encoder": False,
        "max_dense_queries": 0,
        "max_sparse_queries": 8,
    }
    principal = sample.get("input", {}).get("principal")
    state["principal"] = principal or {
        "user_id": "benchmark-public",
        "tenant_id": "public",
        "roles": [],
        "groups": [],
        "permissions": [],
        "region": "CN",
    }
    return state


def timed(call):
    started = perf_counter()
    value = call()
    return value, round((perf_counter() - started) * 1000, 2)


def public_sources(values: list[str]) -> list[str]:
    normalized = []
    for value in values:
        if value in {"structured_db", "database"}:
            normalized.append("database")
        elif value in {"manual", "policy", "faq", "ticket_history"}:
            normalized.append(value)
    return sorted(set(normalized))
