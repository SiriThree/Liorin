"""Phase-5 Safety and unified failure-attribution artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from eval_platform.failure_attribution import (
    ATTRIBUTION_POLICY_VERSION, FAILURE_TAXONOMY_VERSION, CaseFailureAttribution,
    FailureCode, FailureDomain, FailureStage, aggregate_failure_attribution,
)
from eval_platform.safety import SafetyCaseDiagnostic, aggregate_safety_metrics


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def build_phase5_summary(
    safety: Sequence[SafetyCaseDiagnostic],
    failures: Sequence[CaseFailureAttribution],
    *,
    total_cases: int,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "phase": 5,
        "metric_semantics": {
            "safety": "FAIL ANYWHERE over one frozen Production trace; final refusal cannot erase an earlier prohibited access/side effect",
            "failure_attribution": "deterministic-first causal attribution; zero-tolerance safety can take primary precedence; otherwise earliest causal supported stage",
            "task_success_redefined": False,
            "grounding_redefined": False,
        },
        "safety": aggregate_safety_metrics(safety),
        "failure_attribution": aggregate_failure_attribution(failures, total_cases=total_cases),
        "metadata": dict(metadata or {}),
    }


def _rate_text(metric: Mapping[str, Any]) -> str:
    rate = metric.get("rate")
    return f"{metric.get('numerator', 0)} / {metric.get('denominator', 0)}" + (f" = {float(rate):.2%}" if rate is not None else " = N/A")


def write_phase5_artifacts(
    output_dir: str | Path,
    *,
    safety: Sequence[SafetyCaseDiagnostic],
    failures: Sequence[CaseFailureAttribution],
    total_cases: int,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    safety_states = [x.to_state() for x in safety]
    failure_states = [x.to_state() for x in failures]
    safety_summary = aggregate_safety_metrics(safety)
    failure_summary = aggregate_failure_attribution(failures, total_cases=total_cases)
    phase5_summary = build_phase5_summary(safety, failures, total_cases=total_cases, metadata=metadata)

    paths = {
        "safety_summary": target / "safety_summary.json",
        "safety_summary_md": target / "safety_summary.md",
        "safety_case_diagnostics": target / "safety_case_diagnostics.jsonl",
        "failure_summary": target / "failure_summary.json",
        "failure_summary_md": target / "failure_summary.md",
        "failure_attribution": target / "failure_attribution.jsonl",
        "failure_taxonomy": target / "failure_taxonomy.json",
        "phase5_summary": target / "phase5_summary.json",
    }
    _write_json(paths["safety_summary"], safety_summary)
    _write_jsonl(paths["safety_case_diagnostics"], safety_states)
    _write_json(paths["failure_summary"], failure_summary)
    _write_jsonl(paths["failure_attribution"], failure_states)
    _write_json(paths["failure_taxonomy"], {
        "failure_taxonomy_version": FAILURE_TAXONOMY_VERSION,
        "attribution_policy_version": ATTRIBUTION_POLICY_VERSION,
        "domains": [x.value for x in FailureDomain],
        "codes": [x.value for x in FailureCode],
        "stages": [x.value for x in FailureStage],
    })
    _write_json(paths["phase5_summary"], phase5_summary)

    ss = [
        "# Phase 5 Safety Summary", "",
        f"Safety Pass Rate: {_rate_text(safety_summary['safety_pass_rate'])}",
        f"Critical Safety Violations: {safety_summary['critical_safety_violation_count']}",
        f"Zero-tolerance Violations: {safety_summary['zero_tolerance_violation_count']}",
        f"Prompt Injection Resistance: {_rate_text(safety_summary['prompt_injection_resistance_rate'])}",
        "", "> Safety is trace-level FAIL ANYWHERE. Final refusal does not erase an earlier unauthorized read or side effect.",
    ]
    paths["safety_summary_md"].write_text("\n".join(ss) + "\n", encoding="utf-8")
    fs = [
        "# Phase 5 Failure Attribution Summary", "",
        f"Failed cases: {failure_summary['failed_cases']}",
        f"Attribution Coverage: {_rate_text(failure_summary['attribution_coverage'])}",
        f"Partially attributable: {failure_summary['partially_attributable']}",
        f"Observability insufficient: {failure_summary['observability_insufficient']}",
        "", "## Primary domains", "",
    ]
    for name, value in failure_summary["primary_domains"].items():
        fs.append(f"- {name}: {value['count']} failed cases; share={value['share_of_failures'] if value['share_of_failures'] is not None else 'N/A'}")
    paths["failure_summary_md"].write_text("\n".join(fs) + "\n", encoding="utf-8")
    return paths


__all__ = ["build_phase5_summary", "write_phase5_artifacts"]
