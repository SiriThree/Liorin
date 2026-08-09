from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from retrieval.security import hash_identifier
from evals.benchmark.expansion.annotation_packet import build_annotation_packet, build_source_snapshot
from evals.benchmark.expansion.d2_runner import run_private_gold_preparation
from evals.benchmark.expansion.field_semantics import build_field_semantics_registry, registry_index
from evals.benchmark.expansion.gold_alignment import validate_gold_alignment
from evals.benchmark.expansion.gold_draft import materialize_gold_draft
from evals.benchmark.expansion.preannotation_review import audit_order_item, audit_warranty_answerability, review_surface_collisions
from evals.benchmark.expansion.runtime_materialization import build_runtime_materialization, materialize_runtime_query

ROOT = Path(__file__).resolve().parents[2]
D1 = ROOT / "artifacts/evaluation/dataset-expansion-d1"


def _rows():
    return [json.loads(x) for x in (D1 / "private_business_source_validated.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def _run(tmp_path):
    out = tmp_path / "d2"
    summary = run_private_gold_preparation(ROOT, D1, out)
    return out, summary


def test_d2_consumes_frozen_d1_84_without_generating_candidates(tmp_path):
    out, summary = _run(tmp_path)
    assert len(_rows()) == 84
    assert summary["input_candidates"] == 84
    assert summary["gold_drafts_attempted"] == 84
    assert summary["ready_for_dual_annotation"] == 76
    assert summary["needs_manual_precheck"] == 8
    assert summary["rejected_before_annotation"] == 0
    assert summary["new_formal_cases"] == 0
    assert summary["dual_annotation_runs"] == 0
    assert summary["human_reviewed_gold"] == 0
    assert summary["production_agent_execution"] == "NOT RUN"


def test_field_semantics_separates_exposure_from_benchmark_worthiness():
    payload = build_field_semantics_registry(_rows())
    idx = registry_index(payload)
    assert payload["covered_field_count"] == 23
    assert payload["classification_counts"]["USER_FACING"] == 21
    assert payload["classification_counts"]["BUSINESS_VALID_BUT_REVIEW"] == 2
    assert idx[("ticket", "priority")]["classification"] == "BUSINESS_VALID_BUT_REVIEW"
    assert idx[("ticket", "assigned_team")]["classification"] == "BUSINESS_VALID_BUT_REVIEW"
    assert idx[("ticket", "summary")]["comparison_mode"] == "SEMANTIC"
    assert idx[("ticket", "summary")]["judge_required"] is True


def test_gold_alignment_single_and_multi_field_are_exactly_field_level(tmp_path):
    out, summary = _run(tmp_path)
    report = json.loads((out / "private_business_gold_alignment_report.json").read_text(encoding="utf-8"))
    assert report["aligned"] == 84
    assert report["misaligned"] == 0
    assert report["multi_field_count"] == 15
    assert report["multi_field_aligned"] == 15
    drafts = [json.loads(x) for x in (out / "private_business_gold_drafts.jsonl").read_text(encoding="utf-8").splitlines()]
    one = next(x for x in drafts if x["semantic_family_id"] == "ORDER_MULTI_FIELD_SUMMARY")
    assert {f["source_field_path"] for f in one["gold_facts_draft"]} == {"status", "order_date"}
    assert {e["field_path"] for e in one["gold_evidence_draft"]} == {"status", "order_date"}


def test_alignment_validator_detects_missing_extra_and_wrong_field(tmp_path):
    out, _ = _run(tmp_path)
    candidate = next(c for c in _rows() if c["semantic_family_id"] == "ORDER_MULTI_FIELD_SUMMARY")
    draft = next(json.loads(x) for x in (out / "private_business_gold_drafts.jsonl").read_text(encoding="utf-8").splitlines() if candidate["candidate_id"] in x)
    bad = copy.deepcopy(draft)
    bad["gold_facts_draft"] = bad["gold_facts_draft"][:-1]
    result = validate_gold_alignment(candidate, bad)
    assert result["status"] == "misaligned"
    assert "MISSING_OR_EXTRA_GOLD_FACT" in result["issues"]


def test_gold_evidence_is_field_level_stable_and_never_persists_raw_business_id(tmp_path):
    out, _ = _run(tmp_path)
    text = (out / "private_business_gold_drafts.jsonl").read_text(encoding="utf-8")
    assert not re.search(r"\b(?:ORD|TCK|WAR)-20\d{2}-\d+\b", text)
    drafts = [json.loads(x) for x in text.splitlines()]
    assert all(e["source_type"] == "STRUCTURED_DATA" for d in drafts for e in d["gold_evidence_draft"])
    assert all(re.match(r"record:(?:order|ticket|warranty):hash:[0-9a-f]+#[a-z_]+$", e["evidence_id"]) for d in drafts for e in d["gold_evidence_draft"])


def test_order_product_gold_does_not_overconstrain_id_and_name(tmp_path):
    out, _ = _run(tmp_path)
    draft = next(json.loads(x) for x in (out / "private_business_gold_drafts.jsonl").read_text(encoding="utf-8").splitlines() if 'ORDER_PRODUCT_LOOKUP' in x)
    by_field = {f["source_field_path"]: f for f in draft["gold_facts_draft"]}
    assert by_field["product_name"]["critical"] is True
    assert by_field["product_id"]["critical"] is False
    assert len(draft["required_facts"]) == 1
    assert len(draft["optional_facts"]) == 1


def test_order_item_reaudit_all_generated_item_level_cases_are_single_item():
    item_fields = {"product_id", "product_name", "quantity", "price_per_unit"}
    audits = [audit_order_item(ROOT, c) for c in _rows() if c["record_type"] == "order" and item_fields & set(c["required_structured_fields"])]
    assert len(audits) == 13
    assert all(x["valid"] for x in audits)
    assert all(x["underlying_order_item_count"] == 1 for x in audits)


def test_order_item_audit_fails_closed_for_real_multi_item_order():
    base = next(c for c in _rows() if c["semantic_family_id"] == "ORDER_QUANTITY_LOOKUP")
    conn = sqlite3.connect(ROOT / "data/structured/liorin.db")
    row = conn.execute("SELECT order_id FROM order_items GROUP BY order_id HAVING COUNT(*) > 1 LIMIT 1").fetchone()
    conn.close()
    assert row is not None
    raw = row[0]
    mutated = copy.deepcopy(base)
    mutated["source_entity_ref"] = f"order:hash:{hash_identifier(raw, namespace='structured:order')}"
    audit = audit_order_item(ROOT, mutated)
    assert audit["valid"] is False
    assert audit["status"] == "AMBIGUOUS_MULTI_ITEM"


def test_all_22_warranty_candidates_are_answerable_through_customer_list_semantics():
    audits = [audit_warranty_answerability(ROOT, c) for c in _rows() if c["record_type"] == "warranty"]
    assert len(audits) == 22
    assert all(x["target_uniquely_identifiable"] for x in audits)
    assert all(x["query_contains_disambiguator"] for x in audits)
    assert all(x["tool_result_sufficient"] for x in audits)
    assert max(x["customer_case_count"] for x in audits) == 3


def test_runtime_materialization_is_deterministic_natural_and_public_artifact_redacted(tmp_path):
    candidate = _rows()[0]
    a = materialize_runtime_query(ROOT, candidate)
    b = materialize_runtime_query(ROOT, candidate)
    assert a == b
    assert "<ORDER_REF:" not in a
    assert re.search(r"ORD-20\d{2}-\d+", a)
    public = build_runtime_materialization(ROOT, candidate)
    serialized = json.dumps(public, ensure_ascii=False)
    assert "[ORDER_FIXTURE_ID]" in public["runtime_query_redacted"]
    assert not re.search(r"ORD-20\d{2}-\d+", serialized)
    assert public["raw_identifier_persisted"] is False


def test_ticket_summary_is_semantic_judge_required_but_not_sensitive_in_selected_d1_pool(tmp_path):
    out, summary = _run(tmp_path)
    assert summary["ticket_summary_audit"] == {"candidate_count": 3, "semantic_judge_required": 3, "sensitive_redaction_rejections": 0}
    drafts = [json.loads(x) for x in (out / "private_business_gold_drafts.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = [d for d in drafts if d["semantic_family_id"] == "TICKET_SUMMARY_LOOKUP"]
    assert len(rows) == 3
    assert all(d["annotation_status"] == "READY_FOR_DUAL_ANNOTATION" for d in rows)
    assert all(d["gold_facts_draft"][0]["comparison_mode"] == "SEMANTIC" for d in rows)
    assert all(d["gold_facts_draft"][0]["judge_required"] for d in rows)


def test_ticket_business_visibility_uncertainty_is_precheck_not_silent_ready(tmp_path):
    out, summary = _run(tmp_path)
    rows = [json.loads(x) for x in (out / "private_business_preannotation_review_queue.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 8
    families = {x["semantic_family_id"] for x in rows}
    assert families == {"TICKET_PRIORITY_LOOKUP", "TICKET_ASSIGNED_TEAM_LOOKUP", "TICKET_MULTI_FIELD_SUMMARY"}
    assert summary["domain_status"]["ticket"]["NEEDS_MANUAL_PRECHECK"] == 8


def test_surface_collision_review_flags_low_information_instead_of_auto_deleting():
    report = review_surface_collisions(_rows())
    assert report["normalized_duplicate_excess"] == 59
    assert report["collision_group_count"] == 25
    assert report["high_information_groups"] == 10
    assert report["medium_information_groups"] == 14
    assert report["low_information_groups"] == 1
    assert report["candidate_information_counts"]["LOW_INFORMATION"] == 5
    low = next(x for x in report["groups"] if x["information_class"] == "LOW_INFORMATION")
    assert low["candidate_count"] == 5
    assert low["distinct_entities"] == 5
    assert low["distinct_states"] == 1


def test_source_snapshot_is_minimal_and_packet_hash_is_stable_without_predictions(tmp_path):
    out1, summary1 = _run(tmp_path / "a")
    out2, summary2 = _run(tmp_path / "b")
    assert summary1["annotation_batch_hash"] == summary2["annotation_batch_hash"]
    assert summary1["annotation_batch_id"] == summary2["annotation_batch_id"]
    packet1 = json.loads((out1 / "private_business_annotation_packets.jsonl").read_text(encoding="utf-8").splitlines()[0])
    packet2 = json.loads((out2 / "private_business_annotation_packets.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert packet1["annotation_packet_hash"] == packet2["annotation_packet_hash"]
    assert set(packet1["source_snapshot"]) == {"snapshot_hash", "record_type", "entity_alias", "fields", "ownership_valid", "tenant_valid"}
    text = json.dumps(packet1, ensure_ascii=False).casefold()
    for forbidden in ("production prediction", "agent trace", "agent answer", "judge answer"):
        # Forbidden names are listed only under excluded_information, never as payload fields.
        assert forbidden not in {str(k).casefold() for k in packet1.keys()}
    assert "formal split assignment" in json.dumps(packet1["excluded_information"], ensure_ascii=False).casefold()


def test_annotation_packet_count_only_includes_ready_rows_and_freezes_zero_runs(tmp_path):
    out, summary = _run(tmp_path)
    packets = (out / "private_business_annotation_packets.jsonl").read_text(encoding="utf-8").splitlines()
    manifest = json.loads((out / "annotation_batch_manifest.json").read_text(encoding="utf-8"))
    assert len(packets) == 76
    assert manifest["packet_count"] == 76
    assert manifest["annotation_runs"] == 0
    assert manifest["human_review_runs"] == 0
    assert manifest["formal_eligible_count"] == 0
    assert len(manifest["batch_hash"]) == 64


def test_existing_formal_dataset_remains_39_and_d2_public_artifacts_do_not_leak_raw_ids(tmp_path):
    out, summary = _run(tmp_path)
    assert summary["existing_formal_canonical_cases"] == 39
    assert summary["new_formal_cases"] == 0
    for path in out.iterdir():
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"\b(?:ORD|TCK|WAR)-20\d{2}-\d+\b", text), path.name
            assert "CUST-" not in text
            assert "@example.com" not in text


def test_d2_unified_cli_entrypoint(tmp_path):
    from eval_platform.cli import main
    out = tmp_path / "cli-d2"
    rc = main(["dataset-prepare-private-annotation", "--root", str(ROOT), "--d1", str(D1), "--output", str(out)])
    assert rc == 0
    summary = json.loads((out / "phase_d2_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "COMPLETE"
    assert summary["ready_for_dual_annotation"] == 76
    assert summary["dual_annotation_runs"] == 0
