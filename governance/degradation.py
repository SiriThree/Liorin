"""Config-backed failure/degradation policy shared by runtime and release tests."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_MATRIX_PATH = Path(__file__).with_name("degradation_matrix.json")


@lru_cache(maxsize=4)
def load_degradation_matrix(path: str | Path = DEFAULT_MATRIX_PATH) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload.get("policies"), dict):
        raise ValueError("degradation matrix requires policies")
    return payload


def degradation_policy(dependency: str, *, path: str | Path = DEFAULT_MATRIX_PATH) -> dict[str, Any]:
    policies = load_degradation_matrix(path).get("policies", {})
    if dependency not in policies:
        raise KeyError(f"unknown degradation dependency: {dependency}")
    return dict(policies[dependency])


def resolve_dependency_failure(
    dependency: str,
    *,
    alternative_available: bool = False,
    current_business_data_required: bool = False,
    high_risk: bool = False,
) -> dict[str, Any]:
    """Resolve a failure without hiding its degraded/error semantics."""
    policy = degradation_policy(dependency)
    action = policy["when_failed"]
    status = policy["status"]
    if dependency in {"dense", "bm25"} and not alternative_available:
        action = "handoff_or_safe_no_results"
        status = "dependency_error"
    elif dependency == "database" and current_business_data_required:
        action = "handoff"
    elif dependency == "verifier" and high_risk:
        action = "handoff"
    return {**policy, "dependency": dependency, "action": action, "status": status}
