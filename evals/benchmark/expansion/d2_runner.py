"""Phase D2 Gold Draft + frozen annotation packet preparation runner."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .annotation_packet import build_annotation_packet, build_batch_manifest, build_source_snapshot
from .field_semantics import build_field_semantics_registry, registry_index
from .gold_alignment import validate_gold_alignment
from .gold_draft import GoldDraftStatus, materialize_gold_draft
from .preannotation_review import audit_order_item, audit_warranty_answerability, review_surface_collisions
from .runtime_materialization import build_runtime_materialization

D2_VERSION = "private-business-d2-v1"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows), encoding="utf-8")


def _sha_rows(rows: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return h.hexdigest()


def run_private_gold_preparation(root: str | Path, d1_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    root = Path(root)
    d1 = Path(d1_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    required = [
        "legacy_section_alias_map.json", "private_business_source_validated.jsonl",
        "private_business_candidate_manifest.json", "private_business_dedup_report.json", "phase_d1_summary.json",
    ]
    missing = [name for name in required if not (d1 / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing D1 artifacts: {missing}")

    candidates = _read_jsonl(d1 / "private_business_source_validated.jsonl")
    if len(candidates) != 84:
        raise ValueError(f"D2 expects frozen D1 candidate set of 84, got {len(candidates)}")
    manifest = json.loads((d1 / "private_business_candidate_manifest.json").read_text(encoding="utf-8"))
    expected_hash = manifest.get("source_validated_sha256")
    actual_hash = _sha_rows(candidates)
    if expected_hash != actual_hash:
        raise ValueError("D1 source-validated candidate set hash mismatch")

    field_payload = build_field_semantics_registry(candidates)
    field_index = registry_index(field_payload)
    _write_json(out / "private_business_field_semantics.json", field_payload)

    runtime_rows = [build_runtime_materialization(root, c) for c in candidates]
    runtime_map = {x["candidate_id"]: x for x in runtime_rows}
    _write_json(out / "private_business_runtime_materialization.json", {
        "materialization_version": "private-business-runtime-materialization-v1",
        "synthetic_fixture_source": True,
        "raw_fixture_ids_persisted": False,
        "count": len(runtime_rows),
        "rows": runtime_rows,
    })

    warranty_rows = []
    warranty_map = {}
    order_item_rows = []
    for c in candidates:
        if c["record_type"] == "warranty":
            audit = audit_warranty_answerability(root, c)
            warranty_rows.append(audit)
            warranty_map[c["candidate_id"]] = audit
        if c["record_type"] == "order":
            order_item_rows.append(audit_order_item(root, c))
    _write_json(out / "private_business_warranty_answerability.json", {
        "candidate_count": len(warranty_rows),
        "answerable": sum(1 for x in warranty_rows if x["status"] == "ANSWERABLE"),
        "ambiguous": sum(1 for x in warranty_rows if x["status"] == "AMBIGUOUS"),
        "tool_output_insufficient": sum(1 for x in warranty_rows if x["status"] == "TOOL_OUTPUT_INSUFFICIENT"),
        "rows": warranty_rows,
    })

    collision = review_surface_collisions(candidates)
    _write_json(out / "private_business_surface_collision_review.json", collision)

    drafts = []
    alignment_rows = []
    for c in candidates:
        draft_obj = materialize_gold_draft(
            root, c, field_index, runtime_map[c["candidate_id"]],
            warranty_answerability=warranty_map.get(c["candidate_id"]),
        )
        draft = draft_obj.to_state()
        # Collision information changes retention/review priority only; D2 does
        # not silently delete candidates before dual annotation.
        collision_class = collision["candidate_collision_class"].get(c["candidate_id"], "NO_COLLISION")
        draft["semantic_information_signature"] = {
            "semantic_family": c["semantic_family_id"],
            "field_set": sorted(c["required_structured_fields"]),
            "entity_state": c["entity_state"],
            "response_type": c["expected_response_type_draft"],
            "collision_class": collision_class,
            "product_family": c.get("product_ref") or "NONE",
        }
        collision_priority = collision["candidate_retention_priority"].get(c["candidate_id"], "LOW")
        draft["retention_priority"] = collision_priority
        if collision_class == "LOW_INFORMATION":
            draft["quality_flags"] = sorted(set(draft["quality_flags"] + ["LOW_INFORMATION_DUPLICATE_CANDIDATE"]))
            draft["review_requirements"] = sorted(set(draft["review_requirements"] + ["FUTURE_DEDUP_REVIEW"]))
        alignment = validate_gold_alignment(c, draft)
        if alignment["status"] != "aligned":
            draft["annotation_status"] = GoldDraftStatus.REJECTED_BEFORE_ANNOTATION.value
            draft["review_requirements"] = sorted(set(draft["review_requirements"] + alignment["issues"]))
        drafts.append(draft)
        alignment_rows.append(alignment)

    # Order item ambiguity is a hard D2 construction defect if discovered.
    order_item_map = {x["candidate_id"]: x for x in order_item_rows}
    for draft in drafts:
        audit = order_item_map.get(draft["candidate_id"])
        if audit and not audit["valid"]:
            draft["annotation_status"] = GoldDraftStatus.REJECTED_BEFORE_ANNOTATION.value
            draft["review_requirements"] = sorted(set(draft["review_requirements"] + ["AMBIGUOUS_MULTI_ITEM_ORDER"]))

    _write_jsonl(out / "private_business_gold_drafts.jsonl", drafts)
    _write_json(out / "private_business_gold_alignment_report.json", {
        "candidate_count": len(alignment_rows),
        "aligned": sum(1 for x in alignment_rows if x["status"] == "aligned"),
        "misaligned": sum(1 for x in alignment_rows if x["status"] != "aligned"),
        "multi_field_count": sum(1 for x in alignment_rows if x["multi_field"]),
        "multi_field_aligned": sum(1 for x in alignment_rows if x["multi_field"] and x["status"] == "aligned"),
        "rows": alignment_rows,
        "order_item_audit": order_item_rows,
    })

    snapshots = [build_source_snapshot(c, d) for c, d in zip(candidates, drafts)]
    _write_jsonl(out / "private_business_source_snapshots.jsonl", snapshots)

    packets = []
    for c, d, s in zip(candidates, drafts, snapshots):
        if d["annotation_status"] == GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value:
            packets.append(build_annotation_packet(c, d, s))
    _write_jsonl(out / "private_business_annotation_packets.jsonl", packets)
    value_types = Counter(f["value_type"] for d in drafts for f in d["gold_facts_draft"])
    comparison_modes = Counter(f["comparison_mode"] for d in drafts for f in d["gold_facts_draft"])
    _write_json(out / "private_business_gold_draft_report.json", {
        "draft_count": len(drafts),
        "gold_fact_count": sum(len(d["gold_facts_draft"]) for d in drafts),
        "critical_gold_fact_count": sum(sum(1 for f in d["gold_facts_draft"] if f["critical"]) for d in drafts),
        "optional_gold_fact_count": sum(sum(1 for f in d["gold_facts_draft"] if not f["critical"]) for d in drafts),
        "gold_evidence_count": sum(len(d["gold_evidence_draft"]) for d in drafts),
        "value_type_distribution": dict(value_types),
        "comparison_mode_distribution": dict(comparison_modes),
        "raw_private_id_persisted": False,
    })
    packet_domains = Counter(c["record_type"] for c, d in zip(candidates, drafts) if d["annotation_status"] == GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value)
    packet_families = Counter(c["semantic_family_id"] for c, d in zip(candidates, drafts) if d["annotation_status"] == GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value)
    packet_fields = Counter(f for c, d in zip(candidates, drafts) if d["annotation_status"] == GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value for f in c["required_structured_fields"])
    packet_risks = Counter(r for d in drafts if d["annotation_status"] == GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value for r in d["review_requirements"])
    _write_json(out / "private_business_annotation_packet_report.json", {
        "packet_count": len(packets),
        "ready_by_domain": dict(packet_domains),
        "ready_by_family": dict(packet_families),
        "ready_by_field": dict(packet_fields),
        "ready_review_requirements": dict(packet_risks),
        "packet_hash_unique_count": len({p["annotation_packet_hash"] for p in packets}),
        "source_snapshot_hash_unique_count": len({p["source_snapshot"]["snapshot_hash"] for p in packets}),
    })

    precheck = [d for d in drafts if d["annotation_status"] == GoldDraftStatus.NEEDS_MANUAL_PRECHECK.value]
    rejected = [d for d in drafts if d["annotation_status"] == GoldDraftStatus.REJECTED_BEFORE_ANNOTATION.value]
    _write_jsonl(out / "private_business_preannotation_review_queue.jsonl", precheck)
    _write_jsonl(out / "private_business_preannotation_rejected.jsonl", rejected)

    batch = build_batch_manifest(packets, expected_hash)
    batch["created_at"] = datetime.now(timezone.utc).isoformat()
    # created_at is intentionally not part of batch_hash (built before insertion).
    _write_json(out / "annotation_batch_manifest.json", batch)

    status_counts = Counter(d["annotation_status"] for d in drafts)
    domain_status: dict[str, dict[str, int]] = {}
    for domain in ("order", "ticket", "warranty"):
        subset = [d for d in drafts if d["record_type"] == domain]
        domain_status[domain] = dict(Counter(x["annotation_status"] for x in subset))

    risk_counts = Counter(r for d in drafts for r in d["review_requirements"])
    canonical = root / "evals/benchmark/data/canonical"
    formal_count = 0
    for name in ("dev_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.json"):
        formal_count += len(json.loads((canonical / name).read_text(encoding="utf-8")))
    summary = {
        "phase": "D2_PRIVATE_GOLD_PREPARATION",
        "status": "COMPLETE" if len(drafts) == 84 and sum(status_counts.values()) == 84 else "PARTIAL",
        "input_candidates": len(candidates),
        "gold_drafts_attempted": len(drafts),
        "deterministically_classified": len(drafts),
        "ready_for_dual_annotation": status_counts[GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value],
        "needs_manual_precheck": status_counts[GoldDraftStatus.NEEDS_MANUAL_PRECHECK.value],
        "rejected_before_annotation": status_counts[GoldDraftStatus.REJECTED_BEFORE_ANNOTATION.value],
        "domain_status": domain_status,
        "field_semantics": field_payload["classification_counts"],
        "semantic_judge_required_fields": field_payload["semantic_judge_required_count"],
        "gold_fact_count": sum(len(d["gold_facts_draft"]) for d in drafts),
        "critical_gold_fact_count": sum(sum(1 for f in d["gold_facts_draft"] if f["critical"]) for d in drafts),
        "gold_evidence_count": sum(len(d["gold_evidence_draft"]) for d in drafts),
        "alignment": {
            "aligned": sum(1 for x in alignment_rows if x["status"] == "aligned"),
            "misaligned": sum(1 for x in alignment_rows if x["status"] != "aligned"),
            "multi_field_count": sum(1 for x in alignment_rows if x["multi_field"]),
            "multi_field_aligned": sum(1 for x in alignment_rows if x["multi_field"] and x["status"] == "aligned"),
        },
        "warranty_answerability": {
            "total": len(warranty_rows),
            "answerable": sum(1 for x in warranty_rows if x["status"] == "ANSWERABLE"),
            "ambiguous": sum(1 for x in warranty_rows if x["status"] == "AMBIGUOUS"),
            "tool_output_insufficient": sum(1 for x in warranty_rows if x["status"] == "TOOL_OUTPUT_INSUFFICIENT"),
        },
        "order_item_ambiguity": {
            "audited_order_candidates": len(order_item_rows),
            "item_level_candidates": sum(1 for x in order_item_rows if x["item_level_fields"]),
            "ambiguous": sum(1 for x in order_item_rows if not x["valid"]),
        },
        "runtime_materialization": {"materializable": sum(1 for x in runtime_rows if x["status"] == "MATERIALIZABLE"), "not_materializable": sum(1 for x in runtime_rows if x["status"] != "MATERIALIZABLE")},
        "surface_collision": {
            "normalized_duplicate_excess": collision["normalized_duplicate_excess"],
            "collision_group_count": collision["collision_group_count"],
            "high_information_groups": collision["high_information_groups"],
            "medium_information_groups": collision["medium_information_groups"],
            "low_information_groups": collision["low_information_groups"],
            "candidate_information_counts": collision["candidate_information_counts"],
        },
        "ticket_summary_audit": {
            "candidate_count": sum(1 for c in candidates if c["semantic_family_id"] == "TICKET_SUMMARY_LOOKUP"),
            "semantic_judge_required": sum(1 for d in drafts for f in d["gold_facts_draft"] if f["source_field_path"] == "summary" and f["judge_required"]),
            "sensitive_redaction_rejections": sum(1 for d in drafts if "TICKET_SUMMARY_CONTAINS_REDACTABLE_SENSITIVE_DATA" in d["review_requirements"]),
        },
        "annotation_packets": len(packets),
        "annotation_batch_id": batch["batch_id"],
        "annotation_batch_hash": batch["batch_hash"],
        "review_requirement_distribution": dict(risk_counts),
        "existing_formal_canonical_cases": formal_count,
        "new_formal_cases": 0,
        "dual_annotation_runs": 0,
        "human_reviewed_gold": 0,
        "production_agent_execution": "NOT RUN",
        "judge_execution": "NOT RUN",
    }
    _write_json(out / "phase_d2_summary.json", summary)
    return summary
