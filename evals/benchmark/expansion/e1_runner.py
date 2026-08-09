"""Phase E1 Mixed Gold preparation + annotation-packet freeze runner."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .gold_draft import GoldDraftStatus, canonical_hash
from .mixed_annotation_packet import build_mixed_annotation_packet, build_mixed_batch_manifest
from .mixed_gold_alignment import gold_level_dedup, validate_mixed_gold
from .mixed_gold_draft import FactRole, build_source_snapshot, materialize_mixed_gold_draft, _document_indexes


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in rows), encoding="utf-8")


def _sha_rows(rows: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return h.hexdigest()


def _formal_mixed(root: Path) -> list[dict[str, Any]]:
    rows = []
    for name in ("dev_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.json"):
        data = _read_json(root / "evals/benchmark/data/canonical" / name)
        rows.extend([x for x in data if x.get("category") == "MIXED_KNOWLEDGE_STRUCTURED"])
    return rows


def run_mixed_gold_preparation(root: str | Path, e0_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    root = Path(root)
    e0 = Path(e0_dir)
    out = Path(output_dir)
    if not e0.is_absolute():
        e0 = root / e0
    if not out.is_absolute():
        out = root / out
    out.mkdir(parents=True, exist_ok=True)

    required = [
        "mixed_source_validated.jsonl", "mixed_rejected.jsonl", "mixed_candidate_manifest.json",
        "mixed_source_necessity_report.json", "mixed_derived_outcome_report.json", "phase_e0_summary.json",
    ]
    missing = [x for x in required if not (e0 / x).exists()]
    if missing:
        raise FileNotFoundError(f"missing E0 artifacts: {missing}")

    candidates = _read_jsonl(e0 / "mixed_source_validated.jsonl")
    rejected_e0 = _read_jsonl(e0 / "mixed_rejected.jsonl")
    manifest = _read_json(e0 / "mixed_candidate_manifest.json")
    if len(candidates) != 58:
        raise ValueError(f"E1 expects frozen E0 SOURCE_VALIDATED=58, got {len(candidates)}")
    if len(rejected_e0) != 10:
        raise ValueError(f"E1 expects frozen E0 rejected=10, got {len(rejected_e0)}")
    actual_candidate_hash = hashlib.sha256(json.dumps(candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if actual_candidate_hash != manifest.get("candidate_set_sha256"):
        raise ValueError("E0 source-validated candidate hash drift")
    rejected_ids = {x["candidate_id"] for x in rejected_e0}
    candidate_ids = {x["candidate_id"] for x in candidates}
    if rejected_ids & candidate_ids:
        raise ValueError("E0 rejected set leaked into E1 Gold preparation input")
    if any(x["mixed_family_id"] == "MIXED_ORDER_RETURN_POLICY" for x in candidates):
        raise ValueError("E0 rejected return-policy family leaked into E1 input")

    facts_index, section_index, by_section = _document_indexes(root)
    drafts: list[dict[str, Any]] = []
    policies = {}
    diagnostics = []
    alignment_rows = []
    provenance_rows = []
    runtime_rows = []
    leakage_rows = []

    for candidate in candidates:
        draft_obj, policy, diag = materialize_mixed_gold_draft(root, candidate, facts_index=facts_index, section_index=section_index, by_section=by_section)
        draft = draft_obj.to_state()
        alignment = validate_mixed_gold(candidate, draft, diag)
        # Alignment issues that are exactly the already-exposed broad manual scope
        # remain PRECHECK, not hard-reject.  Other structural issues fail closed.
        structural = [x for x in alignment["issues"] if x not in {"DOCUMENT_SCOPE_NOT_DETERMINISTICALLY_COMPLETE"}]
        if structural:
            draft["annotation_status"] = GoldDraftStatus.REJECTED_BEFORE_ANNOTATION.value
            draft["review_requirements"] = sorted(set(draft["review_requirements"] + structural))
        drafts.append(draft)
        diagnostics.append(diag)
        alignment_rows.append(alignment)
        runtime_rows.append({"candidate_id": candidate["candidate_id"], **draft["runtime_query_materialization"]})
        leakage_rows.append({"candidate_id": candidate["candidate_id"], "leakage_flags": diag.get("runtime_leakage") or [], "clean": not bool(diag.get("runtime_leakage"))})
        if policy:
            policies[policy.rule_id] = policy.to_state()
        provenance_rows.append({
            "candidate_id": candidate["candidate_id"],
            "structured_fact_ids": [x["fact_id"] for x in draft["structured_facts"]],
            "document_fact_ids": [x["fact_id"] for x in draft["document_facts"]],
            "derived_nodes": [{"derived_fact_id": x["derived_fact_id"], "input_fact_ids": x["input_fact_ids"], "rule_reference": x["rule_reference"]} for x in draft["derived_facts"]],
            "answer_required_fact_ids": draft["answer_required_facts"],
            "intermediate_fact_ids": draft["intermediate_required_facts"],
            "dual_source_provenance_complete": all(
                bool(set(x["input_fact_ids"]) & {f["fact_id"] for f in draft["structured_facts"]}) and bool(set(x["input_fact_ids"]) & {f["fact_id"] for f in draft["document_facts"]})
                for x in draft["derived_facts"] if x["rule_type"] in {"POLICY_APPLICATION", "MULTI_SOURCE_SYNTHESIS"}
            ),
        })

    # Re-check status invariant after alignment.
    valid_statuses = {
        GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value,
        GoldDraftStatus.NEEDS_MANUAL_PRECHECK.value,
        GoldDraftStatus.REJECTED_BEFORE_ANNOTATION.value,
    }
    if any(d["annotation_status"] not in valid_statuses for d in drafts):
        raise ValueError("E1 left an unresolved Gold Draft status")

    snapshots = [build_source_snapshot(c, d, section_index=section_index) for c, d in zip(candidates, drafts)]
    ready_pairs = [(c, d, s) for c, d, s in zip(candidates, drafts, snapshots) if d["annotation_status"] == GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value]
    packets = [build_mixed_annotation_packet(c, d, s) for c, d, s in ready_pairs]

    candidate_set_hash = _sha_rows([c for c, _, _ in ready_pairs])
    construction_hash = canonical_hash({"e0_candidate_set": manifest["candidate_set_sha256"], "drafts": [d["gold_information_signature"] for d in drafts]})
    batch = build_mixed_batch_manifest(packets, candidate_set_hash, construction_hash)
    batch["created_at"] = datetime.now(timezone.utc).isoformat()

    existing = _formal_mixed(root)
    dedup = gold_level_dedup(drafts, existing)
    existing_inventory = _read_json(e0 / "existing_mixed_inventory.json")
    existing_current_sections = {sec for row in existing_inventory.get("cases", []) for sec in row.get("current_document_sections", []) if sec}
    candidate_sections = {c["candidate_id"]: set(c.get("document_section_refs") or []) for c in candidates}
    existing_collisions = [
        {"candidate_id": d["candidate_id"], "sections": sorted(candidate_sections[d["candidate_id"]] & existing_current_sections)}
        for d in drafts if candidate_sections[d["candidate_id"]] & existing_current_sections
    ]
    dedup["existing_formal_gold_collision_count"] = len(existing_collisions)
    dedup["existing_formal_gold_collisions"] = existing_collisions

    # Reports and artifacts.
    _write_jsonl(out / "mixed_gold_drafts.jsonl", drafts)
    _write_jsonl(out / "mixed_gold_provenance_graph.jsonl", provenance_rows)
    _write_jsonl(out / "mixed_policy_rule_drafts.jsonl", list(sorted(policies.values(), key=lambda x: x["rule_id"])))
    _write_json(out / "mixed_runtime_materialization.json", {"count": len(runtime_rows), "materializable": sum(1 for x in runtime_rows if x["status"] == "MATERIALIZABLE"), "rows": runtime_rows})
    _write_json(out / "mixed_query_leakage_report.json", {"count": len(leakage_rows), "clean": sum(1 for x in leakage_rows if x["clean"]), "leaked": sum(1 for x in leakage_rows if not x["clean"]), "rows": leakage_rows})
    _write_jsonl(out / "mixed_source_snapshots.jsonl", snapshots)
    _write_jsonl(out / "mixed_annotation_packets.jsonl", packets)
    _write_json(out / "mixed_annotation_batch_manifest.json", batch)

    fact_roles = Counter()
    structured_types = Counter()
    document_types = Counter()
    derived_types = Counter()
    evidence_types = Counter()
    for d in drafts:
        for key in ("structured_facts", "document_facts"):
            for f in d[key]:
                fact_roles[f["role"]] += 1
                if key == "structured_facts": structured_types[f["source_field_path"]] += 1
                else: document_types[f["metadata"].get("fact_type") or "UNKNOWN"] += 1
        for f in d["derived_facts"]:
            fact_roles[f["role"]] += 1
            derived_types[f["rule_type"]] += 1
        for e in d["gold_evidence"]:
            evidence_types[e["source_type"]] += 1
    _write_json(out / "mixed_gold_fact_roles.json", {"role_counts": dict(fact_roles), "structured_fact_types": dict(structured_types), "document_fact_types": dict(document_types)})
    _write_json(out / "mixed_derived_fact_report.json", {
        "derived_fact_count": sum(len(d["derived_facts"]) for d in drafts),
        "reasoning_type_distribution": dict(derived_types),
        "complete_dual_source_policy_or_synthesis": sum(r["dual_source_provenance_complete"] for r in provenance_rows),
        "unsupported_derivation": sum(1 for d in drafts for f in d["derived_facts"] if not f["e0_result_compatible"] and f["normalized_result"] == "UNSUPPORTED"),
    })
    _write_json(out / "mixed_gold_alignment_report.json", {
        "candidate_count": len(alignment_rows),
        "fully_aligned": sum(1 for x in alignment_rows if x["status"] == "aligned"),
        "with_issues": sum(1 for x in alignment_rows if x["status"] != "aligned"),
        "dual_source_evidence_complete": sum(1 for x in alignment_rows if x["dual_source_evidence_complete"]),
        "rows": alignment_rows,
    })
    manual_scope = [x for x in diagnostics if x.get("manual_scope_issue")]
    _write_json(out / "mixed_gold_minimality_report.json", {
        "minimality_issue_count": len(manual_scope),
        "completeness_issue_count": len(manual_scope),
        "corrected_count": 0,
        "issue": "BROAD_MANUAL_SECTION_SCOPE prevents deterministic complete/minimal answer Gold without changing the E0 candidate query",
        "candidate_ids": [x["candidate_id"] for x in manual_scope],
    })
    _write_json(out / "mixed_source_necessity_validation.json", {
        "candidate_count": len(drafts),
        "both_sources_required": sum(1 for d in drafts if d["source_necessity_contract"]["structured_source_required"] and d["source_necessity_contract"]["document_source_required"]),
        "gold_preserves_both_sources": sum(1 for d in drafts if d["source_necessity_contract"]["gold_preserves_both_sources"]),
        "cases_missing_either_source": sum(1 for x in alignment_rows if not x["dual_source_evidence_complete"]),
    })
    _write_json(out / "mixed_gold_level_dedup.json", dedup)

    policy_rules = list(policies.values())
    policy_counts = Counter(x["ambiguity_status"] for x in policy_rules)
    candidate_policy_audit = []
    policy_by_rule = {x["rule_id"]: x for x in policy_rules}
    for candidate, draft in zip(candidates, drafts):
        refs = [d["rule_reference"] for d in draft["derived_facts"] if d["rule_reference"] in policy_by_rule]
        if not refs and not candidate["document_source_id"].startswith("source:policy:"):
            continue
        rule = policy_by_rule.get(refs[0]) if refs else None
        candidate_policy_audit.append({
            "candidate_id": candidate["candidate_id"],
            "mixed_family_id": candidate["mixed_family_id"],
            "rule_id": rule["rule_id"] if rule else None,
            "ambiguity_status": rule["ambiguity_status"] if rule else "UNRESOLVED",
            "qualification_preserved": bool(rule and rule["qualification_preserved"]),
            "annotation_status": draft["annotation_status"],
        })
    _write_json(out / "mixed_policy_rule_audit.json", {
        "policy_candidate_count": len(candidate_policy_audit),
        "unique_rule_count": len(policy_rules),
        "unique_rule_distribution": dict(policy_counts),
        "candidate_usage_distribution": dict(Counter(x["ambiguity_status"] for x in candidate_policy_audit)),
        "ambiguous_candidate_count": sum(1 for x in candidate_policy_audit if x["ambiguity_status"] == "AMBIGUOUS"),
        "unsupported_candidate_count": sum(1 for x in candidate_policy_audit if x["ambiguity_status"] in {"UNSUPPORTED", "UNRESOLVED"}),
        "rows": candidate_policy_audit,
    })
    _write_json(out / "mixed_gold_completeness_report.json", {
        "issue_count": len(manual_scope),
        "corrected_count": 0,
        "issue": "The E0 manual-routing query asks for section/topic-level points while E0 binds only one AtomicFact; complete answer Gold cannot be deterministically frozen without changing the candidate query or defining a section-summary contract.",
        "candidate_ids": [x["candidate_id"] for x in manual_scope],
    })
    _write_json(out / "mixed_gold_draft_report.json", {
        "input_count": len(candidates),
        "drafted": len(drafts),
        "status_distribution": dict(Counter(d["annotation_status"] for d in drafts)),
        "by_family": {fam: dict(Counter(d["annotation_status"] for d in drafts if d["mixed_family_id"] == fam)) for fam in sorted({d["mixed_family_id"] for d in drafts})},
        "fact_role_distribution": dict(fact_roles),
        "structured_evidence_count": evidence_types["STRUCTURED_DATA"],
        "document_evidence_count": evidence_types["DOCUMENT"],
        "policy_rule_distribution": dict(policy_counts),
    })
    _write_json(out / "mixed_annotation_packet_report.json", {
        "packet_count": len(packets),
        "packet_hash_unique_count": len({x["annotation_packet_hash"] for x in packets}),
        "ready_by_family": dict(Counter(c["mixed_family_id"] for c, _, _ in ready_pairs)),
        "source_snapshot_hash_unique_count": len({x["snapshot_hash"] for _, _, x in ready_pairs}),
        "annotation_runs": 0,
    })
    precheck = [d for d in drafts if d["annotation_status"] == GoldDraftStatus.NEEDS_MANUAL_PRECHECK.value]
    rejected = [d for d in drafts if d["annotation_status"] == GoldDraftStatus.REJECTED_BEFORE_ANNOTATION.value]
    _write_jsonl(out / "mixed_preannotation_review_queue.jsonl", precheck)
    _write_jsonl(out / "mixed_preannotation_rejected.jsonl", rejected)

    ready = [d for d in drafts if d["annotation_status"] == GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value]
    ready_candidates = [c for c, d in zip(candidates, drafts) if d["annotation_status"] == GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value]
    ready_policy = [c for c in ready_candidates if c["document_source_id"].startswith("source:policy:")]
    policy_fact_counts = Counter(fid for c in ready_policy for fid in c["document_fact_refs"])
    policy_section_counts = Counter(sec for c in ready_policy for sec in c["document_section_refs"])
    ready_docs = Counter(c["document_source_id"] for c in ready_candidates)
    ready_products = {c["product_ref"] for c in ready_candidates if c.get("product_ref")}
    _write_json(out / "mixed_ready_distribution.json", {
        "ready": len(ready),
        "precheck": len(precheck),
        "rejected": len(rejected),
        "ready_by_family": dict(Counter(d["mixed_family_id"] for d in ready)),
        "ready_products": len(ready_products),
        "ready_documents": len(ready_docs),
        "ready_document_counts": dict(ready_docs),
        "policy_candidate_count": len(ready_policy),
        "max_cases_per_policy_fact": max(policy_fact_counts.values(), default=0),
        "max_cases_per_policy_section": max(policy_section_counts.values(), default=0),
        "max_policy_fact_ratio_over_ready": (max(policy_fact_counts.values(), default=0) / len(ready) if ready else None),
    })

    # Formal dataset invariance is factual count only here; tests also compare hashes.
    formal_count = 0
    for name in ("dev_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.json"):
        formal_count += len(_read_json(root / "evals/benchmark/data/canonical" / name))
    status_counts = Counter(d["annotation_status"] for d in drafts)
    summary = {
        "phase": "E1_MIXED_GOLD_PREPARATION",
        "status": "COMPLETE" if len(drafts) == 58 and sum(status_counts.values()) == 58 else "PARTIAL",
        "e0_source_validated": len(candidates),
        "e0_effective": int(_read_json(e0 / "phase_e0_summary.json")["effective_candidates"]),
        "e0_rejected_isolated": len(rejected_ids),
        "e0_rejected_overlap": len(rejected_ids & candidate_ids),
        "drafted": len(drafts),
        "ready_for_dual_annotation": status_counts[GoldDraftStatus.READY_FOR_DUAL_ANNOTATION.value],
        "needs_manual_precheck": status_counts[GoldDraftStatus.NEEDS_MANUAL_PRECHECK.value],
        "rejected_before_annotation": status_counts[GoldDraftStatus.REJECTED_BEFORE_ANNOTATION.value],
        "fact_role_distribution": dict(fact_roles),
        "structured_evidence_count": evidence_types["STRUCTURED_DATA"],
        "document_evidence_count": evidence_types["DOCUMENT"],
        "derived_fact_count": sum(len(d["derived_facts"]) for d in drafts),
        "dual_source_evidence_complete": sum(1 for x in alignment_rows if x["dual_source_evidence_complete"]),
        "policy_rules": len(policy_rules),
        "policy_rule_distribution": dict(policy_counts),
        "gold_minimality_issue_count": len(manual_scope),
        "runtime_materializable": sum(1 for x in runtime_rows if x["status"] == "MATERIALIZABLE"),
        "runtime_query_leakage_count": sum(1 for x in leakage_rows if not x["clean"]),
        "annotation_packets": len(packets),
        "annotation_batch_id": batch["batch_id"],
        "annotation_batch_hash": batch["batch_hash"],
        "existing_formal_mixed": len(existing),
        "existing_formal_canonical_cases": formal_count,
        "new_formal_cases": 0,
        "annotation_runs": 0,
        "human_review_runs": 0,
        "production_agent_execution": "NOT RUN",
        "d3r_status": "DEFERRED_BY_ENVIRONMENT",
        "agreement": "NOT_RUN",
    }
    _write_json(out / "phase_e1_summary.json", summary)
    return summary
