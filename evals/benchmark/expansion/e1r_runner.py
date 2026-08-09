"""Phase E1-R Manual-routing query scope repair and Mixed Gold re-freeze."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .gold_draft import canonical_hash
from .manual_scope import build_fact_scope, FactGranularity
from .manual_scope_repair import (
    E1R_REPAIR_VERSION,
    build_repaired_candidate,
    build_refrozen_manual_snapshot,
    refreeze_manual_draft,
    semantic_repair_signature,
)
from .manual_scope_validation import existing_formal_gold_collisions, validate_scope_repair
from .mixed_annotation_packet import build_mixed_annotation_packet
from .mixed_gold_draft import _document_indexes


POLICY_FAMILIES = {"MIXED_ORDER_STATUS_POLICY", "MIXED_WARRANTY_STATUS_POLICY"}
MANUAL_FAMILIES = {"MIXED_ORDER_PRODUCT_MANUAL", "MIXED_TICKET_TROUBLESHOOTING", "MIXED_WARRANTY_PRODUCT_MANUAL"}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(dict(x), ensure_ascii=False, sort_keys=True) + "\n" for x in rows), encoding="utf-8")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _formal_count(root: Path) -> int:
    return sum(len(_read_json(root / "evals/benchmark/data/canonical" / name)) for name in ("dev_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.json"))


def _batch_manifest(packets: list[Mapping[str, Any]], snapshots_by_id: Mapping[str, Mapping[str, Any]], construction_hash: str) -> dict[str, Any]:
    candidate_semantics = [
        {
            "candidate_id": p["candidate_id"],
            "packet_hash": p["annotation_packet_hash"],
            "snapshot_hash": snapshots_by_id[p["candidate_id"]]["snapshot_hash"],
        }
        for p in packets
    ]
    candidate_set_hash = canonical_hash(candidate_semantics)
    semantic = {
        "batch_version": "mixed-annotation-batch-e1r-v1",
        "candidate_set_hash": candidate_set_hash,
        "packet_count": len(packets),
        "packet_hashes": [str(x["annotation_packet_hash"]) for x in packets],
        "source_snapshot_hashes": [str(snapshots_by_id[x["candidate_id"]]["snapshot_hash"]) for x in packets],
        "gold_draft_schema": "mixed-gold-draft-v1",
        "repair_version": E1R_REPAIR_VERSION,
        "construction_hash": construction_hash,
        "annotation_runs": 0,
        "human_review_runs": 0,
        "formal_eligible_count": 0,
    }
    batch_hash = canonical_hash(semantic)
    return {**semantic, "batch_id": f"MIX-E1R-{batch_hash[:12].upper()}", "batch_hash": batch_hash, "created_at": datetime.now(timezone.utc).isoformat()}


def run_manual_scope_repair(root: str | Path, e1_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    root = Path(root).resolve()
    e1 = Path(e1_dir)
    if not e1.is_absolute():
        e1 = root / e1
    out = Path(output_dir)
    if not out.is_absolute():
        out = root / out
    out.mkdir(parents=True, exist_ok=True)

    e0 = root / "artifacts/evaluation/dataset-expansion-e0-mixed"
    e1_drafts = _read_jsonl(e1 / "mixed_gold_drafts.jsonl")
    e1_pre = _read_jsonl(e1 / "mixed_preannotation_review_queue.jsonl")
    e1_packets = _read_jsonl(e1 / "mixed_annotation_packets.jsonl")
    e1_snapshots = _read_jsonl(e1 / "mixed_source_snapshots.jsonl")
    e1_batch = _read_json(e1 / "mixed_annotation_batch_manifest.json")
    e1_summary = _read_json(e1 / "phase_e1_summary.json")
    e0_candidates = _read_jsonl(e0 / "mixed_source_validated.jsonl")
    e0_rejected = _read_jsonl(e0 / "mixed_rejected.jsonl")

    # Hard input gate: exactly the previously reported 58/16/42/0 split.
    if len(e1_drafts) != 58 or e1_summary.get("ready_for_dual_annotation") != 16 or e1_summary.get("needs_manual_precheck") != 42 or e1_summary.get("rejected_before_annotation") != 0:
        raise ValueError("INPUT_DRIFT:E1_STATUS_COUNTS")
    if len(e1_pre) != 42 or Counter(x["mixed_family_id"] for x in e1_pre) != Counter({"MIXED_ORDER_PRODUCT_MANUAL": 18, "MIXED_TICKET_TROUBLESHOOTING": 8, "MIXED_WARRANTY_PRODUCT_MANUAL": 16}):
        raise ValueError("INPUT_DRIFT:E1_PRECHECK_SCOPE")
    e1_by_id = {x["candidate_id"]: x for x in e1_drafts}
    candidates = {x["candidate_id"]: x for x in e0_candidates}
    pre_ids = [x["candidate_id"] for x in e1_pre]
    policy_ids = [x["candidate_id"] for x in e1_drafts if x["annotation_status"] == "READY_FOR_DUAL_ANNOTATION"]
    if set(policy_ids) & set(pre_ids) or {e1_by_id[x]["mixed_family_id"] for x in policy_ids} != POLICY_FAMILIES:
        raise ValueError("INPUT_DRIFT:POLICY_READY")
    rejected_e0_ids = {x["candidate_id"] for x in e0_rejected}
    if rejected_e0_ids & set(pre_ids):
        raise ValueError("INPUT_DRIFT:E0_REJECTED_ENTERED_REPAIR")
    if len(e0_rejected) != 10 or {x["mixed_family_id"] for x in e0_rejected} != {"MIXED_ORDER_RETURN_POLICY"}:
        raise ValueError("INPUT_DRIFT:E0_REJECTED_SET")

    facts_index, section_index, by_section = _document_indexes(root)
    old_packets = {x["candidate_id"]: x for x in e1_packets}
    old_snapshots = {x["candidate_id"]: x for x in e1_snapshots}

    # Freeze evidence/query/draft/packet hashes for the 16 already-ready policy units.
    policy_freeze = []
    for cid in policy_ids:
        d = e1_by_id[cid]
        c = candidates[cid]
        p = old_packets[cid]
        policy_freeze.append({
            "candidate_id": cid,
            "query_hash": canonical_hash(c["candidate_query"]),
            "gold_draft_hash": canonical_hash(d),
            "evidence_hash": canonical_hash(d["gold_evidence"]),
            "packet_hash": p["annotation_packet_hash"],
        })

    repair_input: list[dict[str, Any]] = []
    scope_rows: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    repaired_candidates: list[dict[str, Any]] = []
    scopes_by_id: dict[str, dict[str, Any]] = {}

    for cid in pre_ids:
        c = candidates[cid]
        d = e1_by_id[cid]
        selected_ref = str(d["document_facts"][0]["source_fact_ref"])
        fact = facts_index[selected_ref]
        scope = build_fact_scope(cid, fact, document_id=str(fact["document_id"]), section_id=str(fact["section_id"]))
        s = scope.to_state()
        scopes_by_id[cid] = s
        repair_input.append({
            "candidate_id": cid, "mixed_family_id": c["mixed_family_id"], "original_query": c["candidate_query"],
            "document_id": c["document_source_id"], "section_id": fact["section_id"],
            "selected_fact_id": selected_ref, "selected_fact_text": fact["normalized_value"],
            "old_issues": list(d["review_requirements"]),
        })
        scope_rows.append({**s, "mixed_family_id": c["mixed_family_id"], "section_usable_fact_count": len(by_section.get(scope.section_id, []))})
        if scope.repairable:
            rc = build_repaired_candidate(c, scope)
            repaired_candidates.append(rc)
            proposals.append({
                "candidate_id": cid, "repair_id": rc["repair_id"], "mixed_family_id": c["mixed_family_id"],
                "original_query": c["candidate_query"], "repaired_query": rc["candidate_query"],
                "repair_type": scope.repair_type, "intent_id": scope.intent_id,
                "selected_fact_id": scope.selected_fact_id, "coherent_group_fact_ids": list(scope.coherent_group_fact_ids),
                "source_preserving": True,
            })
        else:
            proposals.append({
                "candidate_id": cid, "repair_id": None, "mixed_family_id": c["mixed_family_id"],
                "original_query": c["candidate_query"], "repaired_query": None,
                "repair_type": scope.repair_type, "intent_id": scope.intent_id,
                "selected_fact_id": scope.selected_fact_id, "coherent_group_fact_ids": [],
                "source_preserving": True,
            })

    repaired_by_id = {x["candidate_id"]: x for x in repaired_candidates}
    validations: dict[str, dict[str, Any]] = {}
    for cid in pre_ids:
        scope = scopes_by_id[cid]
        if cid not in repaired_by_id:
            validations[cid] = {
                "candidate_id": cid, "original_query": candidates[cid]["candidate_query"], "repaired_query": None,
                "repair_type": scope["repair_type"], "intent_id": scope["intent_id"], "selected_fact_id": scope["selected_fact_id"],
                "selected_fact_scope": [scope["selected_fact_id"]], "source_preserved": True,
                "structured_source_required": True, "document_source_required": True,
                "gold_complete": False, "gold_minimal": False, "query_leakage_clean": True,
                "issues": ["NOT_REPAIRABLE_DETERMINISTICALLY"], "status": "STILL_NEEDS_MANUAL_PRECHECK",
                "validation_signature": canonical_hash({"candidate_id": cid, "status": "STILL_NEEDS_MANUAL_PRECHECK"}),
            }
            continue
        validations[cid] = validate_scope_repair(root, candidates[cid], repaired_by_id[cid], scope, facts_index=facts_index)

    # Existing Formal Gold collision is checked after semantic narrowing.
    collisions = existing_formal_gold_collisions(root, repaired_candidates, scopes_by_id)
    collision_by_id = {x["candidate_id"]: x for x in collisions}
    for cid, row in validations.items():
        if collision_by_id.get(cid, {}).get("exact_existing_formal_gold_collision"):
            row["issues"] = sorted(set(list(row["issues"]) + ["DUPLICATE_EXISTING_FORMAL"]))
            row["status"] = "REJECTED_AFTER_SCOPE_REPAIR"

    # Re-freeze drafts/snapshots.  Policy units are byte-semantic copies of E1.
    refrozen_drafts: list[dict[str, Any]] = []
    refrozen_snapshots: list[dict[str, Any]] = []
    active_candidates: dict[str, dict[str, Any]] = {}
    result_rows: list[dict[str, Any]] = []

    for cid in [x["candidate_id"] for x in e1_drafts]:
        if cid in policy_ids:
            refrozen_drafts.append(copy.deepcopy(e1_by_id[cid]))
            refrozen_snapshots.append(copy.deepcopy(old_snapshots[cid]))
            active_candidates[cid] = candidates[cid]
            continue
        scope_state = scopes_by_id[cid]
        val = validations[cid]
        if cid not in repaired_by_id:
            d = copy.deepcopy(e1_by_id[cid])
            d["review_requirements"] = sorted(set(list(d.get("review_requirements") or []) + list(val["issues"])))
            refrozen_drafts.append(d)
            refrozen_snapshots.append(copy.deepcopy(old_snapshots[cid]))
            result_rows.append({
                **val, "mixed_family_id": candidates[cid]["mixed_family_id"], "repair_status": val["status"],
                "repair_id": None, "manual_fact_scope": scope_state,
            })
            continue
        final_status = {
            "REPAIRED_READY": "READY_FOR_DUAL_ANNOTATION",
            "STILL_NEEDS_MANUAL_PRECHECK": "NEEDS_MANUAL_PRECHECK",
            "REJECTED_AFTER_SCOPE_REPAIR": "REJECTED_BEFORE_ANNOTATION",
        }[val["status"]]
        rc, new_draft = refreeze_manual_draft(
            root, candidates[cid], e1_by_id[cid], build_fact_scope(
                cid, facts_index[scope_state["selected_fact_id"]], document_id=scope_state["document_id"], section_id=scope_state["section_id"]
            ), facts_index, final_status=final_status, validation_issues=list(val["issues"]),
        )
        # Gold alignment after repair: specific query => selected answer fact only; context facts are SUPPORTING_ONLY.
        answer_facts = set(new_draft["answer_required_facts"])
        selected_draft_id = next(
            f["fact_id"] for f in new_draft["document_facts"] if f.get("source_fact_ref") == scope_state["selected_fact_id"]
        )
        if answer_facts != {selected_draft_id}:
            val["issues"] = sorted(set(list(val["issues"]) + ["ANSWER_REQUIRED_SCOPE_MISMATCH"]))
            val["status"] = "STILL_NEEDS_MANUAL_PRECHECK"
            new_draft["annotation_status"] = "NEEDS_MANUAL_PRECHECK"
            new_draft["review_requirements"] = val["issues"]
        active_candidates[cid] = rc
        refrozen_drafts.append(new_draft)
        if new_draft["annotation_status"] == "READY_FOR_DUAL_ANNOTATION":
            snap = build_refrozen_manual_snapshot(rc, new_draft, build_fact_scope(
                cid, facts_index[scope_state["selected_fact_id"]], document_id=scope_state["document_id"], section_id=scope_state["section_id"]
            ), facts_index=facts_index, section_index=section_index)
        else:
            snap = copy.deepcopy(old_snapshots[cid])
        refrozen_snapshots.append(snap)
        result_rows.append({
            **val, "mixed_family_id": candidates[cid]["mixed_family_id"], "repair_status": val["status"],
            "repair_id": rc["repair_id"], "manual_fact_scope": scope_state,
            "semantic_signature": semantic_repair_signature(candidates[cid], build_fact_scope(
                cid, facts_index[scope_state["selected_fact_id"]], document_id=scope_state["document_id"], section_id=scope_state["section_id"]
            )),
        })

    drafts_by_id = {x["candidate_id"]: x for x in refrozen_drafts}
    snapshots_by_id = {x["candidate_id"]: x for x in refrozen_snapshots}

    # Freeze packets: reuse the original 16 policy packets exactly; rebuild only repaired Manual READY packets.
    refrozen_packets: list[dict[str, Any]] = []
    for cid in policy_ids:
        refrozen_packets.append(copy.deepcopy(old_packets[cid]))
    for row in result_rows:
        if row["repair_status"] != "REPAIRED_READY":
            continue
        cid = row["candidate_id"]
        p = build_mixed_annotation_packet(active_candidates[cid], drafts_by_id[cid], snapshots_by_id[cid])
        refrozen_packets.append(p)

    # Re-check policy units truly stayed frozen in all requested dimensions.
    policy_freeze_after = []
    packet_by_id = {p["candidate_id"]: p for p in refrozen_packets}
    for before in policy_freeze:
        cid = before["candidate_id"]
        after = {
            "candidate_id": cid,
            "query_hash": canonical_hash(candidates[cid]["candidate_query"]),
            "gold_draft_hash": canonical_hash(drafts_by_id[cid]),
            "evidence_hash": canonical_hash(drafts_by_id[cid]["gold_evidence"]),
            "packet_hash": packet_by_id[cid]["annotation_packet_hash"],
        }
        after["unchanged"] = all(after[k] == before[k] for k in ("query_hash", "gold_draft_hash", "evidence_hash", "packet_hash"))
        policy_freeze_after.append({"before": before, "after": after})
    if not all(x["after"]["unchanged"] for x in policy_freeze_after):
        raise ValueError("POLICY_READY_FREEZE_VIOLATION")

    # Reports.
    status_counts = Counter(r["repair_status"] for r in result_rows)
    family_results = defaultdict(Counter)
    for r in result_rows:
        family_results[r["mixed_family_id"]][r["repair_status"]] += 1
    granularity = Counter(r["manual_fact_scope"]["fact_granularity"] for r in result_rows)
    repair_types = Counter(r["manual_fact_scope"]["repair_type"] for r in result_rows)
    minimal_groups = [r for r in result_rows if r["manual_fact_scope"]["coherent_group_required"]]
    group_sizes = [1 + len(r["manual_fact_scope"]["coherent_group_fact_ids"]) for r in minimal_groups]

    # Dedup / effective diversity across final 58 Gold units.  Policy signatures remain E1's;
    # Manual signatures are scope-repaired and include routing source type.
    all_signatures = [d["gold_information_signature"] for d in refrozen_drafts]
    signature_counts = Counter(all_signatures)
    manual_ready = [r for r in result_rows if r["repair_status"] == "REPAIRED_READY"]
    manual_sig_counts = Counter(r.get("semantic_signature") for r in manual_ready)
    low_info = sum(v - 1 for v in manual_sig_counts.values() if v > 1)

    ready_ids = [d["candidate_id"] for d in refrozen_drafts if d["annotation_status"] == "READY_FOR_DUAL_ANNOTATION"]
    ready_candidates = [active_candidates.get(cid, candidates[cid]) for cid in ready_ids]
    ready_products = {str(c.get("product_ref")) for c in ready_candidates if c.get("product_ref")}
    ready_docs = {str(c.get("document_source_id")) for c in ready_candidates}
    ready_sections = {str(sec) for c in ready_candidates for sec in c.get("document_section_refs") or []}
    final_family_count = len({str(c["mixed_family_id"]) for c in ready_candidates})

    construction_hash = canonical_hash({
        "e1_batch": e1_batch["batch_hash"], "repair_version": E1R_REPAIR_VERSION,
        "results": [{"candidate_id": r["candidate_id"], "status": r["repair_status"], "signature": r.get("semantic_signature")} for r in result_rows],
        "policy_packet_hashes": [old_packets[cid]["annotation_packet_hash"] for cid in policy_ids],
    })
    batch = _batch_manifest(refrozen_packets, snapshots_by_id, construction_hash)

    # Persist requested artifacts.
    _write_jsonl(out / "manual_scope_repair_input.jsonl", repair_input)
    _write_jsonl(out / "manual_fact_scope_audit.jsonl", scope_rows)
    _write_jsonl(out / "manual_scope_repair_proposals.jsonl", proposals)
    _write_jsonl(out / "manual_scope_repair_results.jsonl", result_rows)
    _write_jsonl(out / "manual_scope_repair_ready.jsonl", [r for r in result_rows if r["repair_status"] == "REPAIRED_READY"])
    _write_jsonl(out / "manual_scope_repair_precheck.jsonl", [r for r in result_rows if r["repair_status"] == "STILL_NEEDS_MANUAL_PRECHECK"])
    _write_jsonl(out / "manual_scope_repair_rejected.jsonl", [r for r in result_rows if r["repair_status"] == "REJECTED_AFTER_SCOPE_REPAIR"])
    _write_json(out / "manual_scope_fact_type_distribution.json", {
        "source_fact_type": dict(Counter(r["manual_fact_scope"]["source_fact_type"] for r in result_rows)),
        "fact_granularity": dict(granularity), "repair_type": dict(repair_types),
    })
    _write_json(out / "manual_scope_gold_completeness.json", {
        "before_issue_count": 42, "after_issue_count": sum(1 for r in result_rows if not r["gold_complete"]),
        "resolved_count": sum(1 for r in result_rows if r["gold_complete"]),
        "remaining_candidate_ids": [r["candidate_id"] for r in result_rows if not r["gold_complete"]],
    })
    _write_json(out / "manual_scope_gold_minimality.json", {
        "before_issue_count": 42, "after_issue_count": sum(1 for r in result_rows if not r["gold_minimal"]),
        "resolved_count": sum(1 for r in result_rows if r["gold_minimal"]),
        "minimal_fact_group_cases": len(minimal_groups),
        "average_fact_group_size": (sum(group_sizes) / len(group_sizes) if group_sizes else 1.0),
        "max_fact_group_size": max(group_sizes, default=1),
    })
    _write_json(out / "manual_scope_mixed_necessity.json", {
        "structured_required": sum(1 for r in result_rows if r["structured_source_required"]),
        "document_required": sum(1 for r in result_rows if r["document_source_required"]),
        "repair_invalidated_mixed_cases": sum(1 for r in result_rows if not (r["structured_source_required"] and r["document_source_required"])),
    })
    _write_json(out / "manual_scope_query_leakage.json", {
        "clean": sum(1 for r in result_rows if r["query_leakage_clean"]),
        "leaked": sum(1 for r in result_rows if not r["query_leakage_clean"]),
        "product_identity": sum(1 for r in result_rows if "PRODUCT_ROUTING_FACT_LEAKED" in r["issues"]),
        "document_answer": sum(1 for r in result_rows if "DOCUMENT_ANSWER_LEAKED" in r["issues"]),
        "raw_private_id": sum(1 for r in result_rows if "RAW_PRIVATE_ID_LEAKAGE" in r["issues"]),
    })
    _write_json(out / "manual_scope_existing_formal_collision.json", {
        "existing_formal_mixed_count": 10,
        "exact_gold_collision_count": sum(1 for x in collisions if x["exact_existing_formal_gold_collision"]),
        "rows": collisions,
    })
    _write_json(out / "manual_scope_gold_level_dedup.json", {
        "manual_ready_count": len(manual_ready), "unique_manual_repaired_signatures": len(manual_sig_counts),
        "low_information_entity_variation_count": low_info,
        "final_gold_unique_information_signatures": len(signature_counts),
        "final_gold_duplicate_excess": sum(v - 1 for v in signature_counts.values() if v > 1),
    })
    _write_json(out / "manual_scope_effective_diversity.json", {
        "e0_effective_before": 48,
        "e1_gold_effective_before_repair": int(_read_json(e1 / "mixed_gold_level_dedup.json")["unique_gold_information_signatures"]),
        "manual_repaired_effective_units": len(manual_sig_counts),
        "final_effective_gold_units": len(signature_counts),
        "final_ready_count": len(ready_ids), "final_ready_families": final_family_count,
    })
    _write_json(out / "manual_scope_repair_manifest.json", {
        "input_e1_hash": _file_hash(e1 / "phase_e1_summary.json"),
        "input_e1_batch_id": e1_batch["batch_id"], "input_e1_batch_hash": e1_batch["batch_hash"],
        "precheck_input_ids": pre_ids, "policy_frozen_ids": policy_ids, "repair_version": E1R_REPAIR_VERSION,
        "renderer_version": "deterministic-corpus-bound-renderer-v1", "fact_scope_rules": "manual-fact-scope-registry-v1",
        "repair_ready_count": status_counts["REPAIRED_READY"], "still_precheck_count": status_counts["STILL_NEEDS_MANUAL_PRECHECK"],
        "repair_reject_count": status_counts["REJECTED_AFTER_SCOPE_REPAIR"],
        "policy_freeze_verified": all(x["after"]["unchanged"] for x in policy_freeze_after),
        "policy_freeze_rows": policy_freeze_after,
        "new_batch_id": batch["batch_id"], "new_batch_hash": batch["batch_hash"],
        "generation_method": "DETERMINISTIC_SOURCE_PRESERVING_SCOPE_REPAIR", "llm_used": False,
    })

    _write_jsonl(out / "mixed_gold_drafts_refrozen.jsonl", refrozen_drafts)
    _write_jsonl(out / "mixed_source_snapshots_refrozen.jsonl", refrozen_snapshots)
    _write_jsonl(out / "mixed_annotation_packets_refrozen.jsonl", refrozen_packets)
    _write_json(out / "mixed_annotation_batch_manifest_refrozen.json", batch)
    _write_json(out / "mixed_ready_distribution_refrozen.json", {
        "policy_ready": len(policy_ids), "manual_ready": status_counts["REPAIRED_READY"],
        "precheck": status_counts["STILL_NEEDS_MANUAL_PRECHECK"], "rejected": status_counts["REJECTED_AFTER_SCOPE_REPAIR"],
        "total_ready": len(ready_ids), "ready_families": final_family_count,
        "products": len(ready_products), "documents": len(ready_docs), "sections": len(ready_sections),
        "by_family": dict(Counter(c["mixed_family_id"] for c in ready_candidates)),
    })

    summary = {
        "phase": "E1R_MANUAL_SCOPE_REPAIR",
        "status": "COMPLETE" if len(result_rows) == 42 and all(x["after"]["unchanged"] for x in policy_freeze_after) else "PARTIAL",
        "policy_ready_frozen": 16,
        "manual_precheck_input": 42,
        "repaired_ready": status_counts["REPAIRED_READY"],
        "still_needs_manual_precheck": status_counts["STILL_NEEDS_MANUAL_PRECHECK"],
        "rejected_after_scope_repair": status_counts["REJECTED_AFTER_SCOPE_REPAIR"],
        "family_results": {k: dict(v) for k, v in sorted(family_results.items())},
        "fact_granularity": dict(granularity), "repair_types": dict(repair_types),
        "source_changes": {"entity": 0, "product_relation": 0, "manual": 0, "section": 0, "selected_source_fact": 0},
        "gold_completeness_before_issues": 42,
        "gold_completeness_after_issues": sum(1 for r in result_rows if not r["gold_complete"]),
        "gold_minimality_before_issues": 42,
        "gold_minimality_after_issues": sum(1 for r in result_rows if not r["gold_minimal"]),
        "mixed_necessity_invalidated": sum(1 for r in result_rows if not (r["structured_source_required"] and r["document_source_required"])),
        "query_leakage_count": sum(1 for r in result_rows if not r["query_leakage_clean"]),
        "existing_formal_gold_collision_count": sum(1 for x in collisions if x["exact_existing_formal_gold_collision"]),
        "minimal_fact_group_cases": len(minimal_groups),
        "effective_before": 48, "effective_after": len(signature_counts),
        "final_policy_ready": 16, "final_manual_ready": status_counts["REPAIRED_READY"],
        "final_precheck": status_counts["STILL_NEEDS_MANUAL_PRECHECK"], "final_reject": status_counts["REJECTED_AFTER_SCOPE_REPAIR"],
        "final_total_ready": len(ready_ids), "final_ready_families": final_family_count,
        "final_ready_products": len(ready_products), "final_ready_documents": len(ready_docs), "final_ready_sections": len(ready_sections),
        "new_annotation_batch_id": batch["batch_id"], "new_annotation_batch_hash": batch["batch_hash"], "new_packet_count": len(refrozen_packets),
        "old_e1_batch_id": e1_batch["batch_id"], "old_e1_batch_hash": e1_batch["batch_hash"], "old_e1_batch_unchanged": True,
        "existing_formal_canonical_cases": _formal_count(root), "new_formal_cases": 0,
        "annotation_runs": 0, "production_agent_execution": "NOT RUN", "d3r_status": "DEFERRED_BY_ENVIRONMENT",
        "e0_rejected_touched": 0, "llm_used": False,
    }
    _write_json(out / "phase_e1r_summary.json", summary)
    return summary
