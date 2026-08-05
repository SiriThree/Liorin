"""Central request/stage/evidence observability and in-process metrics aggregation."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from retrieval.security import hash_identifier, sanitize_for_log


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RequestTrace:
    request_id: str
    session_id: str | None
    principal_hash: str
    tenant_hash: str
    query_type: str | None = None
    plan_version: str | None = None
    started_at: str = field(default_factory=utc_now)
    total_latency_ms: float | None = None
    final_status: str | None = None
    degraded_reasons: list[str] = field(default_factory=list)
    retry_rounds: int = 0
    final_action: str | None = None

    def to_state(self) -> dict[str, Any]:
        return sanitize_for_log(self.__dict__)


@dataclass
class StageTrace:
    request_id: str | None
    stage: str
    source: str | None = None
    subquery_id: str | None = None
    filters_summary: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now)
    elapsed_ms: float | None = None
    candidate_count: int = 0
    result_count: int = 0
    error: dict[str, Any] | None = None
    budget_before: dict[str, Any] = field(default_factory=dict)
    budget_after: dict[str, Any] = field(default_factory=dict)
    status: str = "unknown"

    def to_state(self) -> dict[str, Any]:
        return sanitize_for_log(self.__dict__)


@dataclass
class EvidenceTrace:
    request_id: str | None
    evidence_id: str
    document_id: str | None
    section_id: str | None
    retrieval_contributions: list[dict[str, Any]] = field(default_factory=list)
    fusion_rank: int | None = None
    rerank_score: float | None = None
    authority: Any = None
    validity: Any = None
    requirement_coverage: list[str] = field(default_factory=list)
    conflict_status: str | None = None
    final_citation_usage: bool = False

    def to_state(self) -> dict[str, Any]:
        return sanitize_for_log(self.__dict__)


class MetricsRegistry:
    """Thread-safe bounded in-process metrics store.

    Production deployments should export snapshots to their metrics backend.  The
    implementation remains dependency-free so local tests and offline benchmarks use
    exactly the same aggregation semantics.
    """

    def __init__(self, max_samples_per_metric: int = 20_000):
        self.max_samples_per_metric = max_samples_per_metric
        self._samples: dict[str, list[float]] = defaultdict(list)
        self._counters: dict[str, float] = defaultdict(float)
        self._lock = Lock()

    def observe(self, name: str, value: float) -> None:
        numeric = float(value)
        if not math.isfinite(numeric):
            return
        with self._lock:
            bucket = self._samples[name]
            bucket.append(numeric)
            if len(bucket) > self.max_samples_per_metric:
                del bucket[: len(bucket) - self.max_samples_per_metric]

    def increment(self, name: str, amount: float = 1.0) -> None:
        with self._lock:
            self._counters[name] += float(amount)

    def ratio(self, numerator: str, denominator: str) -> float:
        with self._lock:
            total = self._counters.get(denominator, 0.0)
            return self._counters.get(numerator, 0.0) / total if total else 0.0

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * percentile
        lower = int(position)
        upper = min(len(ordered) - 1, lower + 1)
        fraction = position - lower
        return ordered[lower] * (1 - fraction) + ordered[upper] * fraction

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            samples = {key: list(value) for key, value in self._samples.items()}
            counters = dict(self._counters)
        distributions = {
            key: {
                "count": len(values),
                "average": sum(values) / len(values) if values else 0.0,
                "p50": self._percentile(values, 0.50),
                "p95": self._percentile(values, 0.95),
                "p99": self._percentile(values, 0.99),
            }
            for key, values in samples.items()
        }
        return {"counters": counters, "distributions": distributions}

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._counters.clear()


METRICS = MetricsRegistry()


def record_retrieval_outcome(
    *,
    latency_ms: float,
    status: str,
    candidate_count: int,
    context_chars: int = 0,
    degraded_reasons: Iterable[str] = (),
    final_action: str | None = None,
    rounds: int | None = None,
) -> None:
    METRICS.increment("retrieval_requests_total")
    METRICS.observe("retrieval_latency_ms", latency_ms)
    METRICS.observe("candidate_count", candidate_count)
    METRICS.observe("context_chars", context_chars)
    if rounds is not None:
        METRICS.observe("retrieval_rounds", rounds)
    normalized = str(status)
    if normalized.endswith("no_results"):
        METRICS.increment("empty_results_total")
    if "dependency_error" in normalized:
        METRICS.increment("dependency_errors_total")
    if "timeout" in normalized:
        METRICS.increment("timeouts_total")
    if "budget_exhausted" in normalized:
        METRICS.increment("budget_exhaustions_total")
    if list(degraded_reasons):
        METRICS.increment("degraded_requests_total")
    if final_action:
        METRICS.increment(f"verification_action_{final_action}_total")


def record_reranker_request(*, use_cross_encoder: bool) -> None:
    """Record one rerank invocation and whether CrossEncoder was requested."""
    METRICS.increment("reranker_requests_total")
    if use_cross_encoder:
        METRICS.increment("cross_encoder_requests_total")


def record_reranker_fallback() -> None:
    METRICS.increment("cross_encoder_fallback_total")


def record_citation_verification(*, errors: int) -> None:
    METRICS.increment("citation_verification_total")
    if errors:
        METRICS.increment("citation_error_requests_total")
        METRICS.increment("citation_errors_total", errors)


def enterprise_metrics_snapshot(registry: MetricsRegistry | None = None) -> dict[str, float]:
    """Return the stable enterprise metric names consumed by dashboards/release gates."""
    source = registry or METRICS
    snapshot = source.snapshot()
    counters = snapshot["counters"]
    distributions = snapshot["distributions"]

    def average(name: str) -> float:
        return float(distributions.get(name, {}).get("average", 0.0))

    latency = distributions.get("retrieval_latency_ms", {})
    requests = float(counters.get("retrieval_requests_total", 0.0))
    verification = float(counters.get("verification_requests_total", 0.0))
    citation_checks = float(counters.get("citation_verification_total", 0.0))
    cross_encoder = float(counters.get("cross_encoder_requests_total", 0.0))

    def rate(name: str, denominator: float) -> float:
        return float(counters.get(name, 0.0)) / denominator if denominator else 0.0

    return {
        "retrieval_latency_p50": float(latency.get("p50", 0.0)),
        "retrieval_latency_p95": float(latency.get("p95", 0.0)),
        "retrieval_latency_p99": float(latency.get("p99", 0.0)),
        "empty_result_rate": rate("empty_results_total", requests),
        "dependency_error_rate": rate("dependency_errors_total", requests),
        "timeout_rate": rate("timeouts_total", requests),
        "budget_exhaustion_rate": rate("budget_exhaustions_total", requests),
        "degraded_rate": rate("degraded_requests_total", requests),
        "verification_pass_rate": rate("verification_pass_total", verification),
        "supplement_rate": rate("verification_action_supplement_total", verification),
        "clarification_rate": rate("verification_action_clarify_total", verification),
        "handoff_rate": rate("verification_action_handoff_total", verification),
        "citation_error_rate": rate("citation_error_requests_total", citation_checks),
        "average_retrieval_rounds": average("retrieval_rounds"),
        "average_candidate_count": average("candidate_count"),
        "average_context_chars": average("context_chars"),
        "cross_encoder_fallback_rate": rate("cross_encoder_fallback_total", cross_encoder),
    }


def build_evidence_trace(
    evidence: Any,
    *,
    request_id: str | None = None,
    fusion_rank: int | None = None,
    authority: Any = None,
    validity: Any = None,
    requirement_coverage: Iterable[str] = (),
    conflict_status: str | None = None,
    final_citation_usage: bool = False,
) -> EvidenceTrace:
    """Build one JSON-safe evidence trace from the production evidence object/state."""
    if isinstance(evidence, dict):
        document = evidence.get("document")
        metadata = getattr(document, "metadata", None) or (document.get("metadata", {}) if isinstance(document, dict) else {})
        contributions = evidence.get("contributions") or []
        evidence_id = evidence.get("citation_id") or metadata.get("chunk_id") or metadata.get("section_id") or "unknown"
        rerank_score = evidence.get("rerank_score")
    else:
        document = getattr(evidence, "document", None)
        metadata = getattr(document, "metadata", {}) or {}
        contributions = [item.to_state() if hasattr(item, "to_state") else item for item in getattr(evidence, "contributions", [])]
        evidence_id = getattr(evidence, "citation_id", None) or metadata.get("chunk_id") or metadata.get("section_id") or "unknown"
        rerank_score = getattr(evidence, "rerank_score", None)
    normalized = [item.to_state() if hasattr(item, "to_state") else dict(item) for item in contributions]
    return EvidenceTrace(
        request_id=request_id,
        evidence_id=str(evidence_id),
        document_id=str(metadata.get("document_id")) if metadata.get("document_id") is not None else None,
        section_id=str(metadata.get("section_id")) if metadata.get("section_id") is not None else None,
        retrieval_contributions=normalized,
        fusion_rank=fusion_rank,
        rerank_score=float(rerank_score) if rerank_score is not None else None,
        authority=authority,
        validity=validity,
        requirement_coverage=list(requirement_coverage),
        conflict_status=conflict_status,
        final_citation_usage=final_citation_usage,
    )


def principal_trace_fields(principal: Any) -> dict[str, str]:
    return {
        "principal_hash": hash_identifier(getattr(principal, "user_id", ""), namespace="principal"),
        "tenant_hash": hash_identifier(getattr(principal, "tenant_id", ""), namespace="tenant"),
    }


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sanitize_for_log(payload), ensure_ascii=False, sort_keys=True) + "\n")
