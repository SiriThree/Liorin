"""Thread-safe metrics emitted by the real Memory Runtime."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Mapping


_COUNTER_NAMES = (
    "memory_retrieval_count",
    "memory_retrieval_hit_count",
    "memory_retrieved_fact_count",
    "wrong_injection_count",
    "stale_memory_block_count",
    "memory_candidate_count",
    "memory_policy_accept_count",
    "memory_policy_reject_count",
    "memory_noop_count",
    "memory_update_count",
    "memory_context_tokens",
    "artifact_reference_count",
    "context_selection_count",
    "compaction_count",
    "backend_failure_count",
    "policy_failure_count",
    "audit_failure_count",
    "acl_denied_count",
)


@dataclass(slots=True)
class MemoryMetricsRegistry:
    _counters: dict[str, float] = field(
        default_factory=lambda: {name: 0.0 for name in _COUNTER_NAMES}
    )
    _lock: RLock = field(default_factory=RLock, repr=False)

    def increment(self, name: str, value: float = 1.0) -> None:
        if value < 0:
            raise ValueError("metrics increments must not be negative")
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + float(value)

    def set_value(self, name: str, value: float) -> None:
        with self._lock:
            self._counters[name] = float(value)

    def value(self, name: str) -> float:
        with self._lock:
            return float(self._counters.get(name, 0.0))

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            raw = dict(self._counters)
        retrievals = raw.get("memory_retrieval_count", 0.0)
        decisions = raw.get("memory_policy_accept_count", 0.0) + raw.get("memory_policy_reject_count", 0.0)
        candidates = raw.get("memory_candidate_count", 0.0)
        selections = raw.get("context_selection_count", 0.0)
        raw["memory_hit_rate"] = (
            raw.get("memory_retrieval_hit_count", 0.0) / retrievals if retrievals else 0.0
        )
        raw["memory_policy_accept_rate"] = (
            raw.get("memory_policy_accept_count", 0.0) / decisions if decisions else 0.0
        )
        raw["memory_noop_rate"] = (
            raw.get("memory_noop_count", 0.0) / candidates if candidates else 0.0
        )
        raw["compaction_rate"] = (
            raw.get("compaction_count", 0.0) / selections if selections else 0.0
        )
        return raw

    def reset(self) -> None:
        with self._lock:
            self._counters = {name: 0.0 for name in _COUNTER_NAMES}


class RuntimeMetricsCollector:
    """Derive cross-cutting metrics from actual Runtime artifacts/selections."""

    def __init__(self, registry: MemoryMetricsRegistry | None = None) -> None:
        self.registry = registry or get_default_memory_metrics()
        self._seen_artifact_records: set[tuple[str, str, str]] = set()

    def observe_artifact_registry(self, artifact_registry: Any) -> None:
        for record in artifact_registry.lifecycle_records():
            event = getattr(getattr(record, "event", None), "value", "")
            if event != "REFERENCED":
                continue
            marker = (
                str(getattr(record, "artifact_id", "")),
                str(getattr(record, "timestamp", "")),
                str(getattr(record, "reason", "")),
            )
            if marker in self._seen_artifact_records:
                continue
            self._seen_artifact_records.add(marker)
            self.registry.increment("artifact_reference_count")

    def observe_context_selection(self, selection: Any) -> None:
        self.registry.increment("context_selection_count")
        metadata: Mapping[str, Any] = getattr(selection, "runtime_metadata", {}) or {}
        compaction = metadata.get("compaction") if isinstance(metadata, Mapping) else None
        if isinstance(compaction, Mapping) and bool(compaction.get("applied")):
            self.registry.increment("compaction_count")
        items = getattr(selection, "items", ()) or ()
        memory_tokens = sum(
            int(getattr(item, "token_cost", 0) or 0)
            for item in items
            if getattr(getattr(item, "type", None), "value", "") == "MEMORY"
        )
        if memory_tokens:
            self.registry.increment("memory_context_tokens", memory_tokens)


_DEFAULT_METRICS = MemoryMetricsRegistry()


def get_default_memory_metrics() -> MemoryMetricsRegistry:
    return _DEFAULT_METRICS


def reset_default_memory_metrics() -> MemoryMetricsRegistry:
    _DEFAULT_METRICS.reset()
    return _DEFAULT_METRICS


__all__ = [
    "MemoryMetricsRegistry",
    "RuntimeMetricsCollector",
    "get_default_memory_metrics",
    "reset_default_memory_metrics",
]
