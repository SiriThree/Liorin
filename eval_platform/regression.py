"""Phase-6 regression gate and explicit baseline registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REGRESSION_GATE_VERSION = "1.0"


class RunValidity(StrEnum):
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    INVALID_CONFIG = "INVALID_CONFIG"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    JUDGE_INCOMPLETE = "JUDGE_INCOMPLETE"
    OBSERVABILITY_INSUFFICIENT = "OBSERVABILITY_INSUFFICIENT"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ThresholdType(StrEnum):
    ABSOLUTE_FLOOR = "ABSOLUTE_FLOOR"
    MAX_REGRESSION_PP = "MAX_REGRESSION_PP"
    ZERO_TOLERANCE = "ZERO_TOLERANCE"
    WARNING_ONLY = "WARNING_ONLY"


@dataclass(frozen=True, slots=True)
class RegressionRule:
    gate_name: str
    metric: str
    threshold_type: ThresholdType
    threshold: float | None = None
    required: bool = True


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_name: str
    status: GateStatus
    metric: str | None = None
    baseline: float | None = None
    current: float | None = None
    threshold: float | None = None
    reason: str = ""
    run_id: str | None = None

    def to_state(self) -> dict[str, Any]:
        return {
            "gate_name": self.gate_name, "status": self.status.value, "metric": self.metric,
            "baseline": self.baseline, "current": self.current, "threshold": self.threshold,
            "reason": self.reason, "run_id": self.run_id,
        }


@dataclass(frozen=True, slots=True)
class BaselineRecord:
    baseline_name: str
    dataset_hash: str
    config_hash: str
    run_id: str
    metrics: Mapping[str, float]
    promoted_at: str
    git_commit: str | None = None

    def to_state(self) -> dict[str, Any]:
        return {
            "baseline_name": self.baseline_name, "dataset_hash": self.dataset_hash,
            "config_hash": self.config_hash, "run_id": self.run_id, "metrics": dict(self.metrics),
            "promoted_at": self.promoted_at, "git_commit": self.git_commit,
        }


class BaselineRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.records: dict[str, BaselineRecord] = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for row in raw.get("baselines", []):
                record = BaselineRecord(
                    baseline_name=str(row["baseline_name"]), dataset_hash=str(row["dataset_hash"]),
                    config_hash=str(row["config_hash"]), run_id=str(row["run_id"]),
                    metrics={str(k): float(v) for k, v in dict(row.get("metrics") or {}).items()},
                    promoted_at=str(row["promoted_at"]), git_commit=row.get("git_commit"),
                )
                self.records[record.baseline_name] = record

    def get(self, name: str) -> BaselineRecord | None:
        return self.records.get(name)

    def promote(
        self, *, baseline_name: str, run_validity: RunValidity, dataset_formal_eligible: bool,
        critical_safety_violations: int, required_metrics: Mapping[str, float | None],
        dataset_hash: str | None, config_hash: str | None, run_id: str | None, git_commit: str | None = None,
    ) -> BaselineRecord:
        if run_validity is not RunValidity.VALID:
            raise ValueError("only VALID formal runs can be promoted")
        if not dataset_formal_eligible:
            raise ValueError("baseline dataset must be formal eligible")
        if int(critical_safety_violations) != 0:
            raise ValueError("baseline promotion requires zero critical safety violations")
        if not dataset_hash or not config_hash or not run_id:
            raise ValueError("dataset_hash, config_hash and run_id are required")
        missing = [name for name, value in required_metrics.items() if value is None]
        if missing:
            raise ValueError(f"required baseline metrics unavailable: {missing}")
        record = BaselineRecord(
            baseline_name=baseline_name, dataset_hash=dataset_hash, config_hash=config_hash,
            run_id=run_id, metrics={k: float(v) for k, v in required_metrics.items() if v is not None},
            promoted_at=datetime.now(timezone.utc).isoformat(), git_commit=git_commit,
        )
        self.records[baseline_name] = record
        self.save()
        return record

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "schema_version": "1.0", "baselines": [r.to_state() for r in sorted(self.records.values(), key=lambda x: x.baseline_name)]
        }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def evaluate_rule(rule: RegressionRule, *, current: float | None, baseline: float | None, run_id: str | None = None) -> GateResult:
    if current is None:
        return GateResult(rule.gate_name, GateStatus.BLOCKED if rule.required else GateStatus.NOT_APPLICABLE, rule.metric, baseline, current, rule.threshold, "CURRENT_METRIC_NOT_AVAILABLE", run_id)
    if rule.threshold_type is ThresholdType.ZERO_TOLERANCE:
        return GateResult(rule.gate_name, GateStatus.PASS if current <= 0 else GateStatus.FAIL, rule.metric, baseline, current, 0.0, "zero-tolerance metric must equal zero", run_id)
    if rule.threshold_type is ThresholdType.WARNING_ONLY:
        return GateResult(rule.gate_name, GateStatus.PASS, rule.metric, baseline, current, rule.threshold, "warning-only gate does not hard block", run_id)
    if rule.threshold_type is ThresholdType.ABSOLUTE_FLOOR:
        if rule.threshold is None:
            return GateResult(rule.gate_name, GateStatus.BLOCKED, rule.metric, baseline, current, None, "THRESHOLD_NOT_ESTABLISHED", run_id)
        return GateResult(rule.gate_name, GateStatus.PASS if current >= rule.threshold else GateStatus.FAIL, rule.metric, baseline, current, rule.threshold, "absolute floor", run_id)
    if baseline is None:
        return GateResult(rule.gate_name, GateStatus.BLOCKED, rule.metric, None, current, rule.threshold, "BASELINE_NOT_ESTABLISHED", run_id)
    if rule.threshold is None:
        return GateResult(rule.gate_name, GateStatus.BLOCKED, rule.metric, baseline, current, None, "REGRESSION_TOLERANCE_NOT_ESTABLISHED", run_id)
    floor = baseline - rule.threshold / 100.0
    return GateResult(rule.gate_name, GateStatus.PASS if current >= floor else GateStatus.FAIL, rule.metric, baseline, current, rule.threshold, f"current must be >= baseline - {rule.threshold} percentage points", run_id)


def evaluate_contract_gate(contract_checks: Mapping[str, bool]) -> GateResult:
    failed = sorted(name for name, ok in contract_checks.items() if not ok)
    return GateResult("contract_gate", GateStatus.PASS if not failed else GateStatus.FAIL, reason="all contract checks passed" if not failed else f"failed contract checks: {failed}")


def write_gate_artifacts(output_dir: str | Path, results: Sequence[GateResult], *, metadata: Mapping[str, Any] | None = None) -> dict[str, Path]:
    target = Path(output_dir); target.mkdir(parents=True, exist_ok=True)
    payload = {"gate_version": REGRESSION_GATE_VERSION, "results": [x.to_state() for x in results], "metadata": dict(metadata or {})}
    json_path = target / "regression_gate.json"
    md_path = target / "regression_gate.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    lines = ["# Evaluation Regression Gate", ""]
    for item in results:
        lines.append(f"- **{item.gate_name}**: {item.status.value} — {item.reason}")
    md_path.write_text("\n".join(lines)+"\n", encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


__all__ = ["REGRESSION_GATE_VERSION", "RunValidity", "GateStatus", "ThresholdType", "RegressionRule", "GateResult", "BaselineRecord", "BaselineRegistry", "evaluate_rule", "evaluate_contract_gate", "write_gate_artifacts"]
