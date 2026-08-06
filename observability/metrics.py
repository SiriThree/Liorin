"""Unified metrics registry and exporter contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class MetricsExporter(Protocol):
    def export(self, snapshot: Mapping[str, float]) -> None: ...


@dataclass(slots=True)
class UnifiedMetricsRegistry:
    _values: dict[str, float] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)
    exporters: list[MetricsExporter] = field(default_factory=list)

    def increment(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self._values[name] = self._values.get(name, 0.0) + float(value)

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._values[f"{name}_sum"] = self._values.get(f"{name}_sum", 0.0) + float(value)
            self._counts[name] = self._counts.get(name, 0) + 1
            self._values[f"{name}_count"] = float(self._counts[name])
            self._values[f"{name}_avg"] = self._values[f"{name}_sum"] / self._counts[name]

    def set_value(self, name: str, value: float) -> None:
        with self._lock:
            self._values[name] = float(value)

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            values = dict(self._values)

        def ratio(numerator: str, denominator: str) -> float:
            return values.get(numerator, 0.0) / values.get(denominator, 0.0) if values.get(denominator, 0.0) else 0.0

        values.setdefault("memory_hit_rate", ratio("memory_hit", "memory_read"))
        values.setdefault("answer_success_rate", ratio("agent_success_count", "agent_request_count"))
        values.setdefault("fallback_rate", ratio("fallback_count", "agent_request_count"))
        values.setdefault("error_rate", ratio("agent_error_count", "agent_request_count"))
        tool_total = values.get("tool_success_count", 0.0) + values.get("tool_failure_count", 0.0)
        values.setdefault("tool_failure_rate", values.get("tool_failure_count", 0.0) / tool_total if tool_total else 0.0)
        values.setdefault("backend_failure_rate", ratio("backend_failure_count", "backend_operation_count"))
        return values

    def flush(self) -> None:
        snapshot = self.snapshot()
        for exporter in tuple(self.exporters):
            try:
                exporter.export(snapshot)
            except Exception:
                self.increment("metrics_export_failure_count")

    def reset(self) -> None:
        with self._lock:
            self._values.clear()
            self._counts.clear()


@dataclass(slots=True)
class InMemoryMetricsExporter:
    snapshots: list[dict[str, float]] = field(default_factory=list)

    def export(self, snapshot: Mapping[str, float]) -> None:
        self.snapshots.append(dict(snapshot))


@dataclass(slots=True)
class PrometheusTextExporter:
    """Dependency-free Prometheus text exporter for pull-based HTTP endpoints."""
    latest_text: str = ""

    def export(self, snapshot: Mapping[str, float]) -> None:
        lines = []
        for raw_name, value in sorted(snapshot.items()):
            name = "liorin_" + "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw_name)
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {float(value)}")
        self.latest_text = "\n".join(lines) + ("\n" if lines else "")


@dataclass(slots=True)
class OpenTelemetryMetricsExporter:
    """Optional adapter; imports OpenTelemetry only when export is requested."""
    meter_name: str = "liorin"

    def export(self, snapshot: Mapping[str, float]) -> None:
        try:
            from opentelemetry import metrics as otel_metrics
        except ImportError as exc:
            raise RuntimeError("opentelemetry-api is required for OpenTelemetry export") from exc
        meter = otel_metrics.get_meter(self.meter_name)
        for name, value in snapshot.items():
            meter.create_histogram(name).record(float(value))


_DEFAULT_METRICS = UnifiedMetricsRegistry()


def get_default_metrics() -> UnifiedMetricsRegistry:
    return _DEFAULT_METRICS
