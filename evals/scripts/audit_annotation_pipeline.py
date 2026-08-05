#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from annotation_pipeline.io_utils import read_json, read_jsonl, sha256_json, write_json_atomic
from annotation_pipeline.models import AgentRecord, AdjudicatedRecord, HumanReviewRecord
from annotation_pipeline.review_queue import risk_tags


def forbidden_key_paths(value, path=""):
    found=[]
    if isinstance(value, dict):
        for key, child in value.items():
            child_path=f"{path}/{key}"
            if key in {"gold", "annotation", "split"}:
                found.append(child_path)
            found.extend(forbidden_key_paths(child, child_path))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found.extend(forbidden_key_paths(child, f"{path}/{i}"))
    return found


def audit(run_dir: Path, config_path: Path | None = None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    packets = read_jsonl(run_dir / "source_packets.jsonl")
    a = read_jsonl(run_dir / "annotator_a.jsonl")
    b = read_jsonl(run_dir / "annotator_b.jsonl")
    c = read_jsonl(run_dir / "adjudicator_c.jsonl")
    adjudicated = read_jsonl(run_dir / "adjudicated.jsonl")
    review_queue = read_json(run_dir / "human_review_queue.json")
    agreement = read_json(run_dir / "agreement_report.json")
    manifest = read_json(run_dir / "run_manifest.json")

    expected = manifest["sample_count"]
    for name, rows in [("packets", packets), ("annotator_a", a), ("annotator_b", b), ("adjudicated", adjudicated)]:
        if len(rows) != expected:
            errors.append(f"{name} count={len(rows)}, expected={expected}")
        ids = [row["sample_id"] for row in rows]
        if len(ids) != len(set(ids)):
            errors.append(f"{name} contains duplicate sample ids")

    for packet in packets:
        leaked = forbidden_key_paths(packet)
        if leaked:
            errors.append(f"gold leakage in packet {packet['sample_id']}: {leaked[:10]}")
        expected_hash = packet.get("packet_sha256")
        clone = dict(packet); clone.pop("packet_sha256", None)
        if expected_hash != sha256_json(clone):
            errors.append(f"packet hash mismatch {packet['sample_id']}")

    for row in a + b:
        try:
            AgentRecord.model_validate(row)
        except Exception as exc:
            errors.append(f"invalid agent record {row.get('sample_id')}: {exc}")
    for row in c:
        if int(row.get("attempt_count", 0)) < 1:
            errors.append(f"invalid adjudicator attempt_count {row.get('sample_id')}")
        if not isinstance(row.get("validation_errors", []), list):
            errors.append(f"invalid adjudicator validation_errors {row.get('sample_id')}")
    for row in adjudicated:
        try:
            AdjudicatedRecord.model_validate(row)
        except Exception as exc:
            errors.append(f"invalid adjudicated record {row.get('sample_id')}: {exc}")

    disagreement_ids = {row["sample_id"] for row in adjudicated if row["had_disagreement"]}
    consensus_ids = {row["sample_id"] for row in adjudicated if not row["had_disagreement"]}
    c_ids = {row["sample_id"] for row in c}
    if c_ids != disagreement_ids:
        errors.append(
            f"C must be called exactly on disagreements: missing={sorted(disagreement_ids-c_ids)[:10]} extra={sorted(c_ids-disagreement_ids)[:10]}"
        )
    if c_ids & consensus_ids:
        errors.append("adjudicator was called for consensus samples")
    for row in adjudicated:
        if row["had_disagreement"] and not row.get("adjudicator_response"):
            errors.append(f"missing adjudicator response: {row['sample_id']}")
        if not row["had_disagreement"] and row.get("adjudicator_response") is not None:
            errors.append(f"unexpected adjudicator response: {row['sample_id']}")

    packet_by_id = {row["sample_id"]: row for row in packets}
    adjudicated_by_id = {row["sample_id"]: row for row in adjudicated}
    queued = {row["sample_id"]: row for row in review_queue}
    missing_disagreement_review = disagreement_ids - set(queued)
    if missing_disagreement_review:
        errors.append(f"human queue misses disagreements: {sorted(missing_disagreement_review)[:20]}")

    # Recompute high-risk tags using packet input because original dataset metadata is not copied to prompts.
    high_risk_ids = set()
    for sid, packet in packet_by_id.items():
        pseudo_sample = {"id": sid, "layer": packet["layer"], "input": packet["input"]}
        if risk_tags(pseudo_sample, adjudicated_by_id[sid]):
            high_risk_ids.add(sid)
    if high_risk_ids - set(queued):
        errors.append(f"human queue misses high-risk samples: {sorted(high_risk_ids-set(queued))[:20]}")

    for row in review_queue:
        try:
            HumanReviewRecord.model_validate(row)
        except Exception as exc:
            errors.append(f"invalid human review row {row.get('sample_id')}: {exc}")

    random_rows = [row for row in review_queue if "random_consensus_sample" in row["mandatory_reasons"]]
    expected_random = round(len(consensus_ids) * manifest["human_review_policy"]["random_consensus_rate"])
    if len(random_rows) < expected_random:
        errors.append(f"random consensus review too small: {len(random_rows)} < {expected_random}")

    signatures = [tuple(x) for x in manifest["independence"]["signatures"]]
    if manifest["independence"]["strict"] and len(set(signatures)) != 3:
        errors.append("strict mode but model/provider signatures are not pairwise distinct")
    if not manifest["independence"]["strict"]:
        warnings.append("correlated-agent mode enabled; disclose that annotators may share model/provider biases")

    required_layers = {"query_understanding","routing","retrieval","answer_generation","agent_behavior","end_to_end"}
    if set(agreement.get("by_layer", {})) != required_layers:
        errors.append("agreement report does not contain all six layers")

    repaired_a = sum(int(row.get("attempt_count", 1)) > 1 for row in a)
    repaired_b = sum(int(row.get("attempt_count", 1)) > 1 for row in b)
    repaired_c = sum(int(row.get("attempt_count", 1)) > 1 for row in c)
    total_agent_calls = max(1, len(a) + len(b) + len(c))
    repair_rate = (repaired_a + repaired_b + repaired_c) / total_agent_calls
    if repair_rate > 0.10:
        warnings.append(f"schema repair rate is high: {repair_rate:.3f}; inspect prompts/models before accepting labels")

    uses_mock = any(manifest.get("annotators", {}).get(role, {}).get("backend") == "mock" for role in ["A", "B", "C"])
    result = {
        "status": ("FAIL" if errors else ("PASS_FLOW_ONLY" if uses_mock else "PASS")),
        "semantic_results_valid": not uses_mock and not errors,
        "sample_count": expected,
        "counts": {
            "packets": len(packets),
            "annotator_a": len(a),
            "annotator_b": len(b),
            "disagreements": len(disagreement_ids),
            "adjudicator_calls": len(c),
            "human_review_queue": len(review_queue),
            "high_risk": len(high_risk_ids),
            "random_consensus_review": len(random_rows),
            "schema_repairs": {"annotator_a": repaired_a, "annotator_b": repaired_b, "adjudicator_c": repaired_c},
            "schema_repair_rate": repair_rate,
        },
        "invariants": {
            "no_gold_in_agent_packets": not any("gold leakage" in x for x in errors),
            "c_called_only_for_disagreements": c_ids == disagreement_ids,
            "all_disagreements_in_human_queue": not missing_disagreement_review,
            "all_high_risk_in_human_queue": not (high_risk_ids - set(queued)),
            "random_consensus_rate_met": len(random_rows) >= expected_random,
            "strict_agent_independence": manifest["independence"]["strict"] and len(set(signatures)) == 3,
        },
        "errors": errors,
        "warnings": warnings,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    result = audit(Path(args.run_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        write_json_atomic(args.output, result)
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
