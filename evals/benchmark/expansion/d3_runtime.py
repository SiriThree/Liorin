"""Phase D3-R real annotator runtime recovery orchestration.

This module does not alter D2 packets or Gold. It only verifies runtime
readiness, performs infrastructure-only provider smoke/pilot checks, and then
reuses the Phase D3 formal independent annotation runner when both real
annotators are available.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from evals.annotation_pipeline.backends import BackendError, JSONBackend, make_backend
from evals.annotation_pipeline.config import AgentConfig

from .d3_annotation import (
    D3AnnotationConfig,
    annotation_request_semantic_hash,
    build_annotation_request,
    load_d3_config,
    prompt_metadata,
)
from .d3_runner import (
    _run_side,
    run_private_dual_annotation,
    validate_batch_integrity,
)

D3R_VERSION = "private-business-d3r-v1"
RUNTIME_MANIFEST_VERSION = "private-business-annotation-runtime-v1"
PROVIDER_SMOKE_VERSION = "private-business-annotator-provider-smoke-v1"
DEFAULT_PILOT_COUNT = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(dict(r), ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _placeholder_config(config: AgentConfig) -> list[str]:
    issues: list[str] = []
    provider = config.provider.strip().lower()
    model = config.model.strip().lower()
    host = (urlparse(config.base_url).hostname or "").lower()
    if provider in {"provider-a", "provider-b", "provider", "example"}:
        issues.append("PLACEHOLDER_PROVIDER")
    if model in {"model-a", "model-b", "model", "example-model"}:
        issues.append("PLACEHOLDER_MODEL")
    if host.endswith(".example") or host.endswith(".invalid") or host in {"example.com", "localhost.invalid"}:
        issues.append("PLACEHOLDER_BASE_URL")
    return issues


def _backend_instantiable(config: AgentConfig) -> tuple[bool, str | None]:
    try:
        backend = make_backend(config)
        client = getattr(backend, "client", None)
        if client is not None and hasattr(client, "close"):
            client.close()
        return True, None
    except Exception as exc:  # readiness must report, not raise on provider config
        return False, f"{type(exc).__name__}: {str(exc)[:500]}"


def _side_readiness(config: AgentConfig) -> dict[str, Any]:
    placeholder_issues = _placeholder_config(config)
    credential = bool(os.getenv(config.api_key_env, ""))
    backend_allowed = config.backend == "openai_compatible"
    parsed = urlparse(config.base_url)
    base_url_valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    instantiable, backend_error = _backend_instantiable(config) if backend_allowed else (False, "formal D3-R forbids mock backend")
    checks = {
        "provider_configured": bool(config.provider.strip()) and "PLACEHOLDER_PROVIDER" not in placeholder_issues,
        "model_configured": bool(config.model.strip()) and "PLACEHOLDER_MODEL" not in placeholder_issues,
        "base_url_valid": base_url_valid and "PLACEHOLDER_BASE_URL" not in placeholder_issues,
        "credential_configured": credential,
        "backend_allowed": backend_allowed,
        "backend_instantiable": instantiable,
    }
    ready = all(checks.values())
    if ready:
        status = "READY"
        reason = "READY"
    elif any(checks[k] for k in ("provider_configured", "model_configured", "credential_configured")):
        status = "PARTIAL"
        failed = [k for k, v in checks.items() if not v]
        reason = ",".join(failed)
    else:
        status = "BLOCKED"
        failed = [k for k, v in checks.items() if not v]
        reason = ",".join(failed)
    return {
        "status": status,
        "ready": ready,
        "reason": reason,
        "annotator_id": config.agent_id,
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "backend": config.backend,
        "api_key_env": config.api_key_env,
        "credential_configured": credential,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "timeout_seconds": config.timeout_seconds,
        "max_retries": config.max_retries,
        "checks": checks,
        "placeholder_issues": placeholder_issues,
        "backend_error": backend_error,
    }


def _output_writable(path: Path) -> tuple[bool, str | None]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".d3r_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:500]}"


def annotation_runtime_readiness(
    d2_dir: str | Path,
    output_dir: str | Path,
    config_path: str | Path,
) -> dict[str, Any]:
    d2 = Path(d2_dir)
    out = Path(output_dir)
    integrity = validate_batch_integrity(d2)
    config = load_d3_config(config_path)
    writable, write_error = _output_writable(out)
    a = _side_readiness(config.annotator_a)
    b = _side_readiness(config.annotator_b)
    prompt = prompt_metadata()
    prompt_available = bool(prompt.get("prompt_hash") and prompt.get("prompt_version"))
    schema_available = bool(prompt.get("structured_output_version"))
    batch_ready = integrity["packet_count"] == 76 and integrity["precheck_count"] == 8
    if a["ready"] and b["ready"] and writable and prompt_available and schema_available and batch_ready:
        status = "READY"
    elif (a["ready"] or b["ready"]) and writable and batch_ready:
        status = "PARTIAL"
    else:
        status = "BLOCKED"
    configured_diversity = "SAME_MODEL_INDEPENDENT" if config.annotation_diversity.startswith("SAME_MODEL") else "MODEL_DIVERSE"
    diversity = configured_diversity if a["ready"] and b["ready"] else "NOT_ESTABLISHED"
    return {
        "readiness_version": "private-business-d3r-readiness-v1",
        "status": status,
        "checked_at": _now(),
        "batch": {
            "status": "READY" if batch_ready else "BLOCKED",
            "packet_count": integrity["packet_count"],
            "excluded_precheck": integrity["precheck_count"],
            "batch_id": integrity["batch_id"],
            "batch_hash": integrity["batch_hash"],
            "candidate_set_hash": integrity["candidate_set_hash"],
            "packet_hashes_valid": integrity["integrity_status"] == "VALID",
        },
        "annotator_a": a,
        "annotator_b": b,
        "annotation_diversity": diversity,
        "configured_annotation_diversity": configured_diversity,
        "prompt": prompt,
        "prompt_available": prompt_available,
        "structured_schema_available": schema_available,
        "output_writable": writable,
        "output_write_error": write_error,
    }


def provider_smoke(config: AgentConfig, *, backend: JSONBackend | None = None) -> dict[str, Any]:
    """Perform one non-benchmark structured-output call for infrastructure only."""
    started_at = _now()
    started = time.perf_counter()
    system = (
        "You are an infrastructure probe. Do not answer any benchmark task. "
        "Return exactly one JSON object with status='OK' and probe_version as requested."
    )
    user_obj = {"task": "structured_output_provider_smoke", "probe_version": PROVIDER_SMOKE_VERSION}
    user = json.dumps(user_obj, separators=(",", ":"), sort_keys=True)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "probe_version"],
        "properties": {
            "status": {"const": "OK"},
            "probe_version": {"const": PROVIDER_SMOKE_VERSION},
        },
    }
    request_hash = hashlib.sha256((system + "\n" + user).encode("utf-8")).hexdigest()
    be = backend or make_backend(config)
    raw_hash = None
    try:
        parsed, raw = be.complete_json(system, user, schema)
        raw_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        valid = parsed.get("status") == "OK" and parsed.get("probe_version") == PROVIDER_SMOKE_VERSION
        return {
            "status": "PASS" if valid else "FAIL",
            "provider": config.provider,
            "model": config.model,
            "credential_configured": bool(os.getenv(config.api_key_env, "")),
            "request_hash": request_hash,
            "raw_response_sha256": raw_hash,
            "provider_attempt_count": max(1, getattr(be, "last_http_attempt_count", 1)),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "started_at": started_at,
            "error": None if valid else "STRUCTURED_SMOKE_RESPONSE_INVALID",
            "annotation_quality_result": "NOT_APPLICABLE",
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "provider": config.provider,
            "model": config.model,
            "credential_configured": bool(os.getenv(config.api_key_env, "")),
            "request_hash": request_hash,
            "raw_response_sha256": raw_hash,
            "provider_attempt_count": max(0, getattr(be, "last_http_attempt_count", 0)),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "started_at": started_at,
            "error": f"{type(exc).__name__}: {str(exc)[:1000]}",
            "annotation_quality_result": "NOT_APPLICABLE",
        }
    finally:
        client = getattr(be, "client", None)
        if backend is None and client is not None and hasattr(client, "close"):
            client.close()


def select_pilot_packets(packets: list[Mapping[str, Any]], count: int = DEFAULT_PILOT_COUNT) -> list[Mapping[str, Any]]:
    if count < 5 or count > 8:
        raise ValueError("D3-R infrastructure pilot must contain 5-8 frozen packets")
    selected: list[Mapping[str, Any]] = []
    used: set[str] = set()

    def choose(predicate) -> None:
        for packet in packets:
            if packet["candidate_id"] in used:
                continue
            if predicate(packet):
                selected.append(packet)
                used.add(packet["candidate_id"])
                return

    def record_type(packet: Mapping[str, Any]) -> str:
        return str((packet.get("source_snapshot") or {}).get("record_type") or "").upper()

    def multi(packet: Mapping[str, Any]) -> bool:
        return len((packet.get("gold_draft") or {}).get("gold_facts_draft") or []) > 1

    choose(lambda p: record_type(p) == "ORDER" and not multi(p))
    choose(lambda p: record_type(p) == "ORDER" and multi(p))
    choose(lambda p: p.get("semantic_family_id") == "TICKET_SUMMARY_LOOKUP")
    choose(lambda p: record_type(p) == "TICKET" and p.get("semantic_family_id") != "TICKET_SUMMARY_LOOKUP" and not multi(p))
    choose(lambda p: record_type(p) == "WARRANTY" and not multi(p))
    choose(lambda p: record_type(p) == "WARRANTY" and multi(p))
    for packet in packets:
        if len(selected) >= count:
            break
        if packet["candidate_id"] not in used:
            selected.append(packet)
            used.add(packet["candidate_id"])
    if len(selected) != count:
        raise ValueError(f"could not select {count} deterministic pilot packets")
    return selected


def _decision_file_stats(path: Path) -> dict[str, Any]:
    rows = _read_jsonl(path) if path.exists() else []
    return {
        "requested": len(rows),
        "valid": sum(r.get("status") == "VALID" for r in rows),
        "infra_error": sum(r.get("status") == "ANNOTATOR_INFRA_ERROR" for r in rows),
        "provider_call_count": sum(int(r.get("provider_attempt_count") or 0) for r in rows),
        "mean_latency_ms": (
            round(sum(float(r.get("latency_ms") or 0) for r in rows) / len(rows), 3) if rows else None
        ),
        "decisions_sha256": _sha256_file(path) if path.exists() else None,
    }


def _write_blocked_real_run(out: Path, readiness: Mapping[str, Any]) -> dict[str, Any]:
    batch = readiness["batch"]
    for name in (
        "annotator_a_decisions.jsonl", "annotator_b_decisions.jsonl",
        "annotation_disagreement_queue.jsonl", "consensus_annotation_candidates.jsonl",
    ):
        _write_jsonl(out / name, [])
    pairing = []
    incomplete = []
    d2 = out.parent.parent / "dataset-expansion-d2"
    # The orchestrator writes pairing from the frozen packet list separately if D2 is elsewhere.
    summary = {
        "phase": "D3R_REAL_DUAL_ANNOTATION",
        "version": D3R_VERSION,
        "status": "PARTIAL",
        "annotation_runtime": readiness["status"],
        "actual_dual_annotation": "BLOCKED",
        "agreement": "NOT RUN",
        "blocker": "REAL_ANNOTATOR_RUNTIME_NOT_READY",
        "frozen_packets": batch["packet_count"],
        "excluded_precheck": batch["excluded_precheck"],
        "annotator_a_real_calls": 0,
        "annotator_b_real_calls": 0,
        "valid_pairs": 0,
        "incomplete_pairs": batch["packet_count"],
        "new_formal_cases": 0,
        "human_review_runs": 0,
        "adjudication_runs": 0,
        "production_agent_execution": "NOT RUN",
    }
    return summary


def _runtime_manifest_base(readiness: Mapping[str, Any], *, config_path: str | Path) -> dict[str, Any]:
    return {
        "manifest_version": RUNTIME_MANIFEST_VERSION,
        "phase": "D3-R",
        "status": readiness["status"],
        "batch_id": readiness["batch"]["batch_id"],
        "batch_hash": readiness["batch"]["batch_hash"],
        "candidate_set_hash": readiness["batch"]["candidate_set_hash"],
        "packet_count": readiness["batch"]["packet_count"],
        "excluded_precheck": readiness["batch"]["excluded_precheck"],
        "annotation_diversity": readiness["annotation_diversity"],
        "prompt_version": readiness["prompt"]["prompt_version"],
        "prompt_hash": readiness["prompt"]["prompt_hash"],
        "schema_version": readiness["prompt"]["structured_output_version"],
        "config_path": str(config_path),
        "annotator_a": readiness["annotator_a"],
        "annotator_b": readiness["annotator_b"],
        "provider_smoke": {"annotator_a": "NOT_RUN", "annotator_b": "NOT_RUN"},
        "pilot": {"status": "NOT_RUN", "packet_count": 0},
        "formal_run": {"status": "NOT_RUN"},
        "credential_values_persisted": False,
        "provider_call_count_a": 0,
        "provider_call_count_b": 0,
        "created_at": _now(),
    }


def run_d3r_runtime_recovery(
    root: str | Path,
    d2_dir: str | Path,
    d3_dir: str | Path,
    output_dir: str | Path,
    config_path: str | Path,
    *,
    check_only: bool = False,
    pilot_count: int = DEFAULT_PILOT_COUNT,
) -> dict[str, Any]:
    """Recover real A/B runtime and, only if ready, run smoke → pilot → formal D3."""
    root = Path(root)
    d2 = Path(d2_dir)
    d3 = Path(d3_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    readiness = annotation_runtime_readiness(d2, out, config_path)
    integrity = validate_batch_integrity(d2)
    # Preserve and verify the historical blocked D3 state; never overwrite it.
    historical = _read_json(d3 / "phase_d3_summary.json") if (d3 / "phase_d3_summary.json").exists() else None
    if historical is not None:
        if historical.get("frozen_packets") != 76 or historical.get("valid_pairs") != 0:
            raise ValueError("historical D3 blocked artifact is not the expected frozen baseline")

    runtime_manifest = _runtime_manifest_base(readiness, config_path=config_path)
    runtime_manifest["historical_d3_preserved"] = bool(historical is not None)
    runtime_manifest["historical_d3_status"] = historical.get("status") if historical else "MISSING"
    _write_json(out / "annotation_runtime_manifest.json", runtime_manifest)

    if check_only:
        summary = {
            "phase": "D3R_REAL_DUAL_ANNOTATION", "version": D3R_VERSION,
            "status": readiness["status"], "mode": "CHECK_ONLY",
            "annotation_runtime": readiness["status"], "actual_dual_annotation": "NOT RUN",
            "agreement": "NOT RUN", "frozen_packets": 76, "excluded_precheck": 8,
            "provider_call_count_a": 0, "provider_call_count_b": 0,
            "new_formal_cases": 0, "human_review_runs": 0, "adjudication_runs": 0,
            "production_agent_execution": "NOT RUN",
        }
        _write_json(out / "phase_d3r_summary.json", summary)
        return summary

    if readiness["status"] != "READY":
        summary = _write_blocked_real_run(out, readiness)
        packets = integrity["packets"]
        pairing = [{
            "candidate_id": p["candidate_id"], "packet_hash": p["annotation_packet_hash"],
            "annotator_a_decision_ref": None, "annotator_b_decision_ref": None,
            "pair_status": "ANNOTATION_BLOCKED",
        } for p in packets]
        incomplete = [{
            "candidate_id": p["candidate_id"], "packet_hash": p["annotation_packet_hash"],
            "annotator_a_status": "BLOCKED", "annotator_b_status": "BLOCKED",
            "status": "INCOMPLETE_DUAL_ANNOTATION", "reason": "REAL_ANNOTATOR_RUNTIME_NOT_READY",
        } for p in packets]
        _write_jsonl(out / "dual_annotation_pairing.jsonl", pairing)
        _write_jsonl(out / "annotation_incomplete.jsonl", incomplete)
        not_run = {
            "status": "NOT RUN", "reason": "REAL_ANNOTATOR_RUNTIME_NOT_READY", "valid_pairs": 0,
            "overall_decision_agreement": {"numerator": 0, "denominator": 0, "rate": None},
            "exact_case_agreement": {"numerator": 0, "denominator": 0, "rate": None},
        }
        _write_json(out / "annotation_agreement_summary.json", not_run)
        (out / "annotation_agreement_summary.md").write_text(
            "# D3-R Annotation Agreement\n\n**NOT RUN** — both real annotator runtimes are not READY. No stub/fixture decisions were used.\n",
            encoding="utf-8",
        )
        for name in (
            "annotation_dimension_agreement.json", "annotation_goldfact_agreement.json",
            "annotation_evidence_agreement.json", "annotation_contract_agreement.json",
            "annotation_domain_agreement.json", "annotation_family_agreement.json",
        ):
            _write_json(out / name, {"status": "NOT RUN", "reason": "REAL_ANNOTATOR_RUNTIME_NOT_READY", "denominator": 0})
        for side in ("a", "b"):
            side_cfg = load_d3_config(config_path).annotator_a if side == "a" else load_d3_config(config_path).annotator_b
            side_ready = readiness[f"annotator_{side}"]
            _write_json(out / f"annotator_{side}_run_manifest.json", {
                "manifest_version": "private-business-annotator-run-manifest-v1",
                "side": side.upper(), "status": "BLOCKED", "annotation_run_id": None,
                "batch_id": readiness["batch"]["batch_id"], "batch_hash": readiness["batch"]["batch_hash"],
                "packet_count": 76, "annotator_id": side_cfg.agent_id, "provider": side_cfg.provider,
                "model": side_cfg.model, "credential_configured": side_ready["credential_configured"],
                "provider_call_count": 0, "successful_annotations": 0, "infra_failures": 0,
                **prompt_metadata(), "created_at": _now(),
            })
        runtime_manifest["status"] = readiness["status"]
        runtime_manifest["blocker"] = "REAL_ANNOTATOR_RUNTIME_NOT_READY"
        _write_json(out / "annotation_runtime_manifest.json", runtime_manifest)
        _write_json(out / "phase_d3r_summary.json", summary)
        return summary

    config: D3AnnotationConfig = load_d3_config(config_path)
    # Step 1: provider smoke on independent, non-benchmark infrastructure fixture.
    smoke_a = provider_smoke(config.annotator_a)
    smoke_b = provider_smoke(config.annotator_b)
    runtime_manifest["provider_smoke"] = {"annotator_a": smoke_a, "annotator_b": smoke_b}
    runtime_manifest["provider_call_count_a"] += int(smoke_a.get("provider_attempt_count") or 0)
    runtime_manifest["provider_call_count_b"] += int(smoke_b.get("provider_attempt_count") or 0)
    if smoke_a["status"] != "PASS" or smoke_b["status"] != "PASS":
        runtime_manifest["status"] = "PARTIAL"
        runtime_manifest["blocker"] = "PROVIDER_SMOKE_FAILED"
        _write_json(out / "annotation_runtime_manifest.json", runtime_manifest)
        summary = {
            "phase": "D3R_REAL_DUAL_ANNOTATION", "version": D3R_VERSION, "status": "PARTIAL",
            "annotation_runtime": "PARTIAL", "actual_dual_annotation": "BLOCKED", "agreement": "NOT RUN",
            "blocker": "PROVIDER_SMOKE_FAILED", "frozen_packets": 76, "excluded_precheck": 8,
            "annotator_a_real_calls": runtime_manifest["provider_call_count_a"],
            "annotator_b_real_calls": runtime_manifest["provider_call_count_b"],
            "valid_pairs": 0, "new_formal_cases": 0, "human_review_runs": 0, "adjudication_runs": 0,
            "production_agent_execution": "NOT RUN",
        }
        _write_json(out / "phase_d3r_summary.json", summary)
        return summary

    # Step 2: infrastructure pilot over a deterministic 5-8 packet subset.
    frozen_prompt = prompt_metadata()
    pilot_packets = select_pilot_packets(integrity["packets"], pilot_count)
    pilot_dir = out / "pilot"
    pilot_dir.mkdir(exist_ok=True)
    pilot_a_id = f"PBQ-D3R-PILOT-A-{readiness['batch']['batch_hash'][:10]}"
    pilot_b_id = f"PBQ-D3R-PILOT-B-{readiness['batch']['batch_hash'][:10]}"
    rows_pa = _run_side(
        pilot_packets, config.annotator_a, output_path=pilot_dir / "annotator_a_pilot_decisions.jsonl",
        run_id=pilot_a_id, batch_id=integrity["batch_id"], max_concurrency=config.max_concurrency,
        max_validation_attempts=config.max_validation_attempts,
    )
    rows_pb = _run_side(
        pilot_packets, config.annotator_b, output_path=pilot_dir / "annotator_b_pilot_decisions.jsonl",
        run_id=pilot_b_id, batch_id=integrity["batch_id"], max_concurrency=config.max_concurrency,
        max_validation_attempts=config.max_validation_attempts,
    )
    pilot_valid = (
        all(r.get("status") == "VALID" for r in rows_pa)
        and all(r.get("status") == "VALID" for r in rows_pb)
        and [r["packet_hash"] for r in rows_pa] == [r["packet_hash"] for r in rows_pb]
        and frozen_prompt == prompt_metadata()
    )
    runtime_manifest["provider_call_count_a"] += sum(int(r.get("provider_attempt_count") or 0) for r in rows_pa)
    runtime_manifest["provider_call_count_b"] += sum(int(r.get("provider_attempt_count") or 0) for r in rows_pb)
    runtime_manifest["pilot"] = {
        "status": "PASS" if pilot_valid else "FAIL", "packet_count": len(pilot_packets),
        "candidate_ids": [p["candidate_id"] for p in pilot_packets], "annotation_quality_result": "NOT_APPLICABLE",
        "annotator_a_valid": sum(r.get("status") == "VALID" for r in rows_pa),
        "annotator_b_valid": sum(r.get("status") == "VALID" for r in rows_pb),
        "prompt_modified": False, "prompt_hash_before": frozen_prompt["prompt_hash"],
        "prompt_hash_after": prompt_metadata()["prompt_hash"],
    }
    _write_json(pilot_dir / "pilot_summary.json", runtime_manifest["pilot"])
    if not pilot_valid:
        runtime_manifest["status"] = "PARTIAL"
        runtime_manifest["blocker"] = "INFRASTRUCTURE_PILOT_FAILED"
        _write_json(out / "annotation_runtime_manifest.json", runtime_manifest)
        summary = {
            "phase": "D3R_REAL_DUAL_ANNOTATION", "version": D3R_VERSION, "status": "PARTIAL",
            "annotation_runtime": "PARTIAL", "actual_dual_annotation": "NOT RUN", "agreement": "NOT RUN",
            "blocker": "INFRASTRUCTURE_PILOT_FAILED", "frozen_packets": 76, "excluded_precheck": 8,
            "valid_pairs": 0, "new_formal_cases": 0, "human_review_runs": 0, "adjudication_runs": 0,
            "production_agent_execution": "NOT RUN",
        }
        _write_json(out / "phase_d3r_summary.json", summary)
        return summary

    # Step 3: formal independent A then B over the exact frozen batch.
    formal_summary = run_private_dual_annotation(root, d2, out, config_path)
    a_stats = _decision_file_stats(out / "annotator_a_decisions.jsonl")
    b_stats = _decision_file_stats(out / "annotator_b_decisions.jsonl")
    runtime_manifest["provider_call_count_a"] += a_stats["provider_call_count"]
    runtime_manifest["provider_call_count_b"] += b_stats["provider_call_count"]
    runtime_manifest["formal_run"] = {
        "status": formal_summary.get("status"), "annotator_a": a_stats, "annotator_b": b_stats,
        "valid_pairs": formal_summary.get("valid_pairs"), "incomplete_pairs": formal_summary.get("incomplete_pairs"),
    }
    runtime_manifest["status"] = "READY"
    runtime_manifest["completed_at"] = _now()
    _write_json(out / "annotation_runtime_manifest.json", runtime_manifest)

    agreement = _read_json(out / "annotation_agreement_summary.json")
    valid_pairs = int(formal_summary.get("valid_pairs") or 0)
    status = "COMPLETE" if valid_pairs == 76 else "PARTIAL"
    summary = {
        "phase": "D3R_REAL_DUAL_ANNOTATION", "version": D3R_VERSION, "status": status,
        "annotation_runtime": "READY", "actual_dual_annotation": "RUN",
        "agreement": "RUN" if valid_pairs > 0 else "NOT RUN",
        "annotation_diversity": readiness["annotation_diversity"],
        "frozen_packets": 76, "excluded_precheck": 8,
        "annotator_a_real_calls": runtime_manifest["provider_call_count_a"],
        "annotator_b_real_calls": runtime_manifest["provider_call_count_b"],
        "annotator_a_valid": formal_summary.get("annotator_a_valid", 0),
        "annotator_b_valid": formal_summary.get("annotator_b_valid", 0),
        "valid_pairs": valid_pairs, "incomplete_pairs": formal_summary.get("incomplete_pairs", 76 - valid_pairs),
        "overall_decision_agreement": agreement.get("overall_decision_agreement"),
        "exact_case_agreement": agreement.get("exact_case_agreement"),
        "disagreement_count": formal_summary.get("disagreement_count", 0),
        "new_formal_cases": 0, "human_review_runs": 0, "adjudication_runs": 0,
        "production_agent_execution": "NOT RUN",
    }
    _write_json(out / "phase_d3r_summary.json", summary)
    return summary
