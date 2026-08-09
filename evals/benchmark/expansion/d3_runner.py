"""Phase D3 frozen dual independent annotation runner.

Real agreement metrics are produced only from two valid real annotator runs.
Mock/stub backends are rejected for formal D3 execution.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from .annotation_packet import build_batch_manifest
from .d3_agreement import analyze_agreement
from .d3_annotation import (
    D3AnnotationConfig, PrivateGoldAnnotationAgent, credential_status, load_d3_config,
    new_run_id, prompt_metadata,
)
from .gold_draft import canonical_hash

D3_VERSION = "private-business-d3-v1"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.write_text("".join(json.dumps(dict(r), ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def _empty_jsonl(path: Path) -> None:
    if path.exists() and path.stat().st_size:
        raise RuntimeError(f"refusing to overwrite immutable annotation output: {path}")
    path.touch()


def validate_batch_integrity(d2: Path) -> dict[str, Any]:
    required = [
        "private_business_annotation_packets.jsonl", "annotation_batch_manifest.json",
        "private_business_preannotation_review_queue.jsonl", "private_business_source_snapshots.jsonl",
    ]
    missing = [name for name in required if not (d2 / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing D2 artifacts: {missing}")
    packets = _read_jsonl(d2 / "private_business_annotation_packets.jsonl")
    precheck = _read_jsonl(d2 / "private_business_preannotation_review_queue.jsonl")
    manifest = _read_json(d2 / "annotation_batch_manifest.json")
    if len(packets) != manifest.get("packet_count"):
        raise ValueError("D2 packet_count mismatch")
    if len(packets) != 76:
        raise ValueError(f"D3 frozen READY batch must contain 76 packets, got {len(packets)}")
    if len(precheck) != 8:
        raise ValueError(f"D3 must exclude exactly the 8 frozen PRECHECK drafts, got {len(precheck)}")
    packet_ids = [p["candidate_id"] for p in packets]
    if len(packet_ids) != len(set(packet_ids)):
        raise ValueError("duplicate candidate_id in D2 annotation batch")
    precheck_ids = {p["candidate_id"] for p in precheck}
    if precheck_ids & set(packet_ids):
        raise ValueError("PRECHECK packet leaked into D3 READY batch")
    recomputed_hashes = []
    for packet in packets:
        semantic = dict(packet)
        claimed = semantic.pop("annotation_packet_hash")
        actual = canonical_hash(semantic)
        if claimed != actual:
            raise ValueError(f"packet hash mismatch: {packet['candidate_id']}")
        recomputed_hashes.append(actual)
    if recomputed_hashes != manifest.get("packet_hashes"):
        raise ValueError("annotation_batch_manifest packet hashes/order mismatch")
    rebuilt = build_batch_manifest(packets, manifest["candidate_set_hash"])
    if rebuilt["batch_hash"] != manifest.get("batch_hash") or rebuilt["batch_id"] != manifest.get("batch_id"):
        raise ValueError("annotation batch hash/id mismatch")
    return {
        "packets": packets, "precheck": precheck, "manifest": manifest,
        "packet_count": len(packets), "precheck_count": len(precheck),
        "batch_id": manifest["batch_id"], "batch_hash": manifest["batch_hash"],
        "candidate_set_hash": manifest["candidate_set_hash"], "integrity_status": "VALID",
    }


def _decision_record(packet: Mapping[str, Any], result, annotator, run_id: str, batch_id: str) -> dict[str, Any]:
    return {
        "candidate_id": packet["candidate_id"], "packet_hash": packet["annotation_packet_hash"],
        "batch_id": batch_id, "annotator_id": annotator.agent_id, "provider": annotator.provider,
        "model": annotator.model, "annotation_run_id": run_id, "status": result.status,
        "decision": result.decision, "error": result.error, "retry_count": result.retry_count,
        "request_sha256": result.request_sha256, "request_semantic_sha256": result.request_semantic_sha256,
        "raw_response_sha256": result.raw_response_sha256,
        "request_started_at": result.request_started_at, "latency_ms": result.latency_ms,
        "provider_attempt_count": result.provider_attempt_count,
        "prompt_version": prompt_metadata()["prompt_version"], "structured_output_version": prompt_metadata()["structured_output_version"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _run_side(packets: list[Mapping[str, Any]], cfg, *, output_path: Path, run_id: str, batch_id: str, max_concurrency: int, max_validation_attempts: int) -> list[dict[str, Any]]:
    if output_path.exists() and output_path.stat().st_size:
        raise RuntimeError(f"refusing to overwrite immutable annotation run: {output_path}")
    results: dict[str, dict[str, Any]] = {}
    def annotate_one(packet):
        # One backend instance per packet keeps retry/attempt telemetry isolated across threads.
        agent = PrivateGoldAnnotationAgent(cfg, max_validation_attempts=max_validation_attempts)
        return agent.annotate(packet, run_id=run_id)
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures = {pool.submit(annotate_one, packet): packet for packet in packets}
        for future in as_completed(futures):
            packet = futures[future]
            result = future.result()
            results[packet["candidate_id"]] = _decision_record(packet, result, cfg, run_id, batch_id)
    rows = [results[p["candidate_id"]] for p in packets]
    _write_jsonl(output_path, rows)
    return rows


def _manifest(config, *, side: str, run_id: str, batch: Mapping[str, Any], readiness: Mapping[str, Any], rows: list[Mapping[str, Any]] | None = None, status: str) -> dict[str, Any]:
    agent = config.annotator_a if side == "A" else config.annotator_b
    rows = rows or []
    return {
        "manifest_version": "private-business-annotator-run-manifest-v1", "side": side,
        "status": status, "annotation_run_id": run_id, "batch_id": batch["batch_id"], "batch_hash": batch["batch_hash"],
        "packet_count": batch["packet_count"], "annotator_id": agent.agent_id, "provider": agent.provider, "model": agent.model,
        "base_url": agent.base_url, **prompt_metadata(), "temperature": agent.temperature, "seed": agent.seed,
        "timeout_seconds": agent.timeout_seconds, "max_retries": agent.max_retries,
        "structured_output_config": "json_object+pydantic_validation", "requested_annotations": len(rows) if rows else 0,
        "successful_annotations": sum(r.get("status") == "VALID" for r in rows),
        "infra_failures": sum(r.get("status") != "VALID" for r in rows),
        "provider_call_count": sum(int(r.get("provider_attempt_count") or 0) for r in rows),
        "credential_configured": readiness["configured"],
        "api_key_env": readiness["api_key_env"], "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _blocked_artifacts(out: Path, integrity: Mapping[str, Any], config: D3AnnotationConfig, ready_a: Mapping[str, Any], ready_b: Mapping[str, Any]) -> dict[str, Any]:
    for name in ("annotator_a_decisions.jsonl", "annotator_b_decisions.jsonl", "annotation_disagreement_queue.jsonl", "consensus_annotation_candidates.jsonl"):
        _empty_jsonl(out / name)
    pairing = []
    incomplete = []
    for packet in integrity["packets"]:
        cid = packet["candidate_id"]
        ph = packet["annotation_packet_hash"]
        pairing.append({"candidate_id": cid, "packet_hash": ph, "annotator_a_decision_ref": None, "annotator_b_decision_ref": None, "pair_status": "ANNOTATION_BLOCKED"})
        incomplete.append({"candidate_id": cid, "packet_hash": ph, "annotator_a_status": "BLOCKED", "annotator_b_status": "BLOCKED", "status": "INCOMPLETE_DUAL_ANNOTATION", "reason": "REAL_ANNOTATOR_ENVIRONMENT_UNAVAILABLE"})
    _write_jsonl(out / "dual_annotation_pairing.jsonl", pairing)
    _write_jsonl(out / "annotation_incomplete.jsonl", incomplete)
    run_a = new_run_id("PBQ-D3-A-BLOCKED", integrity["batch_hash"])
    run_b = new_run_id("PBQ-D3-B-BLOCKED", integrity["batch_hash"])
    _write_json(out / "annotator_a_run_manifest.json", _manifest(config, side="A", run_id=run_a, batch=integrity["manifest"], readiness=ready_a, status="BLOCKED"))
    _write_json(out / "annotator_b_run_manifest.json", _manifest(config, side="B", run_id=run_b, batch=integrity["manifest"], readiness=ready_b, status="BLOCKED"))
    reason = {"annotator_a": ready_a, "annotator_b": ready_b}
    summary = {
        "phase": "D3_PRIVATE_DUAL_ANNOTATION", "status": "PARTIAL", "annotation_execution": "BLOCKED",
        "blocker": "REAL_ANNOTATOR_ENVIRONMENT_UNAVAILABLE", "readiness": reason,
        "frozen_packets": integrity["packet_count"], "excluded_precheck": integrity["precheck_count"],
        "annotator_a_completed": 0, "annotator_b_completed": 0, "valid_pairs": 0, "incomplete_pairs": integrity["packet_count"],
        "agreement_metrics_status": "NOT RUN", "new_formal_cases": 0, "human_reviewed_gold": 0,
        "adjudication_runs": 0, "production_agent_execution": "NOT RUN",
    }
    blocked_agreement = {
        "status": "NOT RUN", "reason": summary["blocker"], "valid_pairs": 0,
        "overall_decision_agreement": {"numerator": 0, "denominator": 0, "rate": None},
        "exact_case_agreement": {"numerator": 0, "denominator": 0, "rate": None},
    }
    _write_json(out / "annotation_agreement_summary.json", blocked_agreement)
    (out / "annotation_agreement_summary.md").write_text("# D3 Annotation Agreement\n\n**NOT RUN** — real independent annotator environment is unavailable. No stub/mock decisions were used.\n", encoding="utf-8")
    for name in ("annotation_dimension_agreement.json", "annotation_family_agreement.json", "annotation_domain_agreement.json", "annotation_goldfact_agreement.json", "annotation_evidence_agreement.json", "annotation_contract_agreement.json"):
        _write_json(out / name, {"status": "NOT RUN", "reason": summary["blocker"], "denominator": 0})
    _write_json(out / "phase_d3_summary.json", summary)
    return summary


def run_private_dual_annotation(root: str | Path, d2_dir: str | Path, output_dir: str | Path, config_path: str | Path) -> dict[str, Any]:
    root = Path(root); d2 = Path(d2_dir); out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    integrity = validate_batch_integrity(d2)
    config = load_d3_config(config_path)
    ready_a, ready_b = credential_status(config.annotator_a), credential_status(config.annotator_b)
    if not ready_a["ready"] or not ready_b["ready"]:
        return _blocked_artifacts(out, integrity, config, ready_a, ready_b)

    run_a = new_run_id("PBQ-D3-A", integrity["batch_hash"])
    run_b = new_run_id("PBQ-D3-B", integrity["batch_hash"])
    rows_a = _run_side(integrity["packets"], config.annotator_a, output_path=out / "annotator_a_decisions.jsonl", run_id=run_a, batch_id=integrity["batch_id"], max_concurrency=config.max_concurrency, max_validation_attempts=config.max_validation_attempts)
    rows_b = _run_side(integrity["packets"], config.annotator_b, output_path=out / "annotator_b_decisions.jsonl", run_id=run_b, batch_id=integrity["batch_id"], max_concurrency=config.max_concurrency, max_validation_attempts=config.max_validation_attempts)
    _write_json(out / "annotator_a_run_manifest.json", _manifest(config, side="A", run_id=run_a, batch=integrity["manifest"], readiness=ready_a, rows=rows_a, status="COMPLETE"))
    _write_json(out / "annotator_b_run_manifest.json", _manifest(config, side="B", run_id=run_b, batch=integrity["manifest"], readiness=ready_b, rows=rows_b, status="COMPLETE"))

    analysis = analyze_agreement(integrity["packets"], rows_a, rows_b)
    valid_ids = set(analysis["valid_pair_ids"])
    pairing = []
    incomplete = []
    a_by, b_by = {r["candidate_id"]: r for r in rows_a}, {r["candidate_id"]: r for r in rows_b}
    for packet in integrity["packets"]:
        cid = packet["candidate_id"]
        if cid in valid_ids:
            pairing.append({"candidate_id": cid, "packet_hash": packet["annotation_packet_hash"], "annotator_a_decision_ref": f"annotator_a_decisions.jsonl#{cid}", "annotator_b_decision_ref": f"annotator_b_decisions.jsonl#{cid}", "pair_status": "VALID"})
        else:
            incomplete.append({"candidate_id": cid, "packet_hash": packet["annotation_packet_hash"], "annotator_a_status": a_by.get(cid, {}).get("status", "MISSING"), "annotator_b_status": b_by.get(cid, {}).get("status", "MISSING"), "status": "INCOMPLETE_DUAL_ANNOTATION"})
    _write_jsonl(out / "dual_annotation_pairing.jsonl", pairing)
    _write_jsonl(out / "annotation_incomplete.jsonl", incomplete)
    _write_jsonl(out / "annotation_disagreement_queue.jsonl", analysis["disagreements"])
    consensus = []
    for row in analysis["pair_rows"]:
        if row["exact_case_agreement"]:
            consensus.append({"candidate_id": row["candidate_id"], "packet_hash": row["packet_hash"], "consensus_status": row["category"], "gold_mutated": False, "adjudicated": False})
    _write_jsonl(out / "consensus_annotation_candidates.jsonl", consensus)
    _write_json(out / "annotation_agreement_summary.json", analysis["summary"])
    _write_json(out / "annotation_dimension_agreement.json", analysis["dimension"])
    _write_json(out / "annotation_family_agreement.json", analysis["family"])
    _write_json(out / "annotation_domain_agreement.json", analysis["domain"])
    _write_json(out / "annotation_goldfact_agreement.json", analysis["gold_fact"])
    _write_json(out / "annotation_evidence_agreement.json", analysis["gold_evidence"])
    _write_json(out / "annotation_contract_agreement.json", analysis["task_contract"])
    s = analysis["summary"]
    md = ["# D3 Annotation Agreement", "", f"Valid pairs: {s['valid_pairs']} / {integrity['packet_count']}", ""]
    for key in ("overall_decision_agreement", "exact_case_agreement"):
        x=s[key]; md.append(f"- {key}: {x['numerator']} / {x['denominator']} = {x['rate'] if x['rate'] is not None else 'NOT RUN'}")
    (out / "annotation_agreement_summary.md").write_text("\n".join(md)+"\n", encoding="utf-8")
    summary = {
        "phase": "D3_PRIVATE_DUAL_ANNOTATION", "status": "COMPLETE" if len(valid_ids) == integrity["packet_count"] else "PARTIAL",
        "annotation_execution": "RUN", "annotation_diversity": config.annotation_diversity,
        "frozen_packets": integrity["packet_count"], "excluded_precheck": integrity["precheck_count"],
        "annotator_a_valid": sum(r["status"] == "VALID" for r in rows_a), "annotator_b_valid": sum(r["status"] == "VALID" for r in rows_b),
        "valid_pairs": len(valid_ids), "incomplete_pairs": len(incomplete), "overall_decision_agreement": s["overall_decision_agreement"],
        "exact_case_agreement": s["exact_case_agreement"], "disagreement_count": len(analysis["disagreements"]),
        "new_formal_cases": 0, "human_reviewed_gold": 0, "adjudication_runs": 0, "production_agent_execution": "NOT RUN",
    }
    _write_json(out / "phase_d3_summary.json", summary)
    return summary
