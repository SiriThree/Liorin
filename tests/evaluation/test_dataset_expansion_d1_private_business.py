from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

from evals.benchmark.expansion.candidate_contracts import CandidateStatus
from evals.benchmark.expansion.candidate_dedup import deduplicate_candidates
from evals.benchmark.expansion.candidate_generator import generate_private_business_candidates
from evals.benchmark.expansion.candidate_validation import validate_candidate
from evals.benchmark.expansion.d1_runner import run_private_business_expansion
from evals.benchmark.expansion.legacy_evidence_alias import build_legacy_section_alias_map

ROOT = Path(__file__).resolve().parents[2]
D0 = ROOT / "artifacts/evaluation/dataset-expansion-d0"


def test_d1_legacy_alias_bridge_is_40_of_40_deterministic():
    payload = build_legacy_section_alias_map(ROOT, D0)
    assert payload["total_legacy_document_refs"] == 40
    assert payload["resolved"] == 40
    assert payload["ambiguous"] == 0
    assert payload["missing"] == 0
    assert payload["all_deterministically_resolved"] is True
    assert all(x["current_stable_hash"] for x in payload["aliases"])


def test_private_candidate_generation_is_deterministic_and_capacity_driven():
    a = generate_private_business_candidates(ROOT)
    b = generate_private_business_candidates(ROOT)
    assert len(a) == len(b) == 84
    assert [x.candidate_id for x in a] == [x.candidate_id for x in b]
    assert [x.source_entity_ref for x in a] == [x.source_entity_ref for x in b]
    assert {x.record_type for x in a} == {"order", "ticket", "warranty"}
    assert all(x.category == "PRIVATE_BUSINESS_QUERY" for x in a)


def test_all_generated_candidates_source_validate_and_map_to_real_read_capability():
    rows = generate_private_business_candidates(ROOT)
    for row in rows:
        validate_candidate(ROOT, D0, row)
    assert len(rows) == 84
    assert all(x.status is CandidateStatus.SOURCE_VALIDATED for x in rows)
    assert all(x.query_plan.operation_semantics == "READ_LOOKUP" for x in rows)
    assert all(x.production_capability_ref == "private_structured_read" for x in rows)


def test_source_validation_fails_closed_for_missing_entity_wrong_field_and_owner():
    base = generate_private_business_candidates(ROOT)[0]

    missing = copy.deepcopy(base)
    missing.source_entity_ref = "order:hash:00000000000000000000"
    validate_candidate(ROOT, D0, missing)
    assert missing.status is CandidateStatus.REJECTED
    assert "SOURCE_ENTITY_MISSING_OR_NONUNIQUE" in missing.rejection_reasons

    wrong_field = copy.deepcopy(base)
    wrong_field.required_structured_fields = ("tracking_number",)
    wrong_field.source_field_paths = ("tracking_number",)
    wrong_field.query_plan = replace(wrong_field.query_plan, required_fields=("tracking_number",))
    validate_candidate(ROOT, D0, wrong_field)
    assert wrong_field.status is CandidateStatus.REJECTED
    assert any("UNSUPPORTED_FIELD" in x for x in wrong_field.rejection_reasons)

    wrong_owner = copy.deepcopy(base)
    wrong_owner.customer_group_ref = "customer:hash:00000000000000000000"
    validate_candidate(ROOT, D0, wrong_owner)
    assert "CUSTOMER_GROUP_MISMATCH" in wrong_owner.rejection_reasons


def test_source_validation_rejects_event_write_mixed_and_safety_leakage():
    base = generate_private_business_candidates(ROOT)[0]

    event = copy.deepcopy(base)
    event.required_structured_fields = ("happened_at",)
    event.source_field_paths = ("happened_at",)
    event.query_plan = replace(event.query_plan, template_id="order_events", required_fields=("happened_at",))
    validate_candidate(ROOT, D0, event)
    assert event.status is CandidateStatus.REJECTED

    write = copy.deepcopy(base)
    write.query_plan = replace(write.query_plan, operation_semantics="UPDATE")
    validate_candidate(ROOT, D0, write)
    assert "UNSUPPORTED_OPERATION" in write.rejection_reasons

    mixed = copy.deepcopy(base)
    mixed.candidate_query += " 另外按退货政策我还能退吗？"
    validate_candidate(ROOT, D0, mixed)
    assert "MIXED_TASK_LEAKAGE" in mixed.rejection_reasons

    safety = copy.deepcopy(base)
    safety.candidate_query += " 顺便查一下别人的订单。"
    validate_candidate(ROOT, D0, safety)
    assert "SAFETY_TASK_LEAKAGE" in safety.rejection_reasons


def test_answer_and_metadata_leakage_are_rejected():
    base = next(x for x in generate_private_business_candidates(ROOT) if x.semantic_family_id == "ORDER_STATUS_LOOKUP")
    leaked = copy.deepcopy(base)
    leaked.candidate_query += f" 我记得好像是 {leaked.expected_value_draft['status']}。"
    validate_candidate(ROOT, D0, leaked)
    assert "ANSWER_LEAKAGE" in leaked.rejection_reasons

    raw_identifier = copy.deepcopy(base)
    raw_identifier.candidate_query = "请查询订单 ORD-2025-00001 的状态。"
    validate_candidate(ROOT, D0, raw_identifier)
    assert "METADATA_OR_IDENTIFIER_LEAKAGE" in raw_identifier.rejection_reasons


def test_semantic_dedup_rejects_same_entity_same_field_but_retains_meaningful_field_change():
    first = generate_private_business_candidates(ROOT)[0]
    first.status = CandidateStatus.SOURCE_VALIDATED
    duplicate = copy.deepcopy(first)
    duplicate.candidate_id = first.candidate_id + "-SURFACE"
    duplicate.candidate_query = first.candidate_query.replace("现在是什么状态", "当前状态是什么")
    report = deduplicate_candidates([first, duplicate])
    assert duplicate.status is CandidateStatus.REJECTED
    assert duplicate.duplicate_of == first.candidate_id
    assert report["rejected_duplicates"] == 1

    other = copy.deepcopy(first)
    other.candidate_id = first.candidate_id + "-DATE"
    other.required_structured_fields = ("order_date",)
    other.source_field_paths = ("order_date",)
    other.duplicate_keys = dict(other.duplicate_keys)
    other.duplicate_keys["semantic_entity_field"] = "different-field-key"
    other.status = CandidateStatus.SOURCE_VALIDATED
    report = deduplicate_candidates([first, other])
    assert other.status is CandidateStatus.SOURCE_VALIDATED
    assert report["rejected_duplicates"] == 0


def test_d1_artifacts_meet_diversity_and_concentration_contract(tmp_path):
    summary = run_private_business_expansion(ROOT, D0, tmp_path / "d1")
    dist = json.loads((tmp_path / "d1/private_business_distribution.json").read_text(encoding="utf-8"))
    assert summary["raw_candidates"] == 84
    assert summary["source_validated"] >= 60
    assert summary["semantic_families"] == 25
    assert dist["domain_distribution"] == {"order": 36, "ticket": 26, "warranty": 22}
    assert dist["unique_entity_ratio"] == 1.0
    assert dist["unique_customer_ratio"] >= 0.80
    assert dist["unique_products"] == 20
    assert dist["unique_tenants"] == 19
    assert dist["max_per_entity"] == 1
    assert dist["tenant_concentration_ratio"] <= 0.10
    assert dist["product_concentration_ratio"] <= 0.10


def test_d1_state_coverage_includes_real_minority_states(tmp_path):
    run_private_business_expansion(ROOT, D0, tmp_path / "d1")
    states = json.loads((tmp_path / "d1/private_business_state_coverage.json").read_text(encoding="utf-8"))
    assert {"Delivered", "Cancelled", "Processing", "Shipped"} <= set(states["order_status"])
    assert {"resolved", "pending_customer", "in_progress", "open"} <= set(states["ticket_status"])
    assert {"in_warranty", "expired"} <= set(states["warranty_coverage_status"])
    assert {"active", "under_review", "denied", "expired"} <= set(states["warranty_status"])


def test_d1_field_coverage_is_real_and_does_not_force_identifier_or_customer_profile_targets(tmp_path):
    run_private_business_expansion(ROOT, D0, tmp_path / "d1")
    coverage = json.loads((tmp_path / "d1/private_business_field_coverage.json").read_text(encoding="utf-8"))
    assert coverage["production_ordinary_gold_usable_types"] == 28
    assert coverage["covered_types"] == 23
    assert set(coverage["not_covered"]) == {
        "customer.customer_id", "customer.segment", "order.order_id", "ticket.ticket_id", "warranty.case_id"
    }


def test_public_candidate_artifacts_do_not_expose_raw_private_business_ids(tmp_path):
    run_private_business_expansion(ROOT, D0, tmp_path / "d1")
    for name in ["private_business_raw_candidates.jsonl", "private_business_source_validated.jsonl", "phase_d1_summary.json"]:
        text = (tmp_path / "d1" / name).read_text(encoding="utf-8")
        assert "ORD-2025-" not in text and "ORD-2026-" not in text
        assert "TCK-2026-" not in text and "WAR-2026-" not in text
        assert "CUST-" not in text and "@example.com" not in text
    assert "<ORDER_REF:" in (tmp_path / "d1/private_business_source_validated.jsonl").read_text(encoding="utf-8")


def test_existing_formal_dataset_is_unchanged_and_no_formal_or_reviewed_rows_are_created(tmp_path):
    base = ROOT / "evals/benchmark/data/canonical"
    before = len(json.loads((base / "dev_v7_3_canonical_v1.json").read_text(encoding="utf-8"))) + len(json.loads((base / "validation_v7_3_canonical_v1.json").read_text(encoding="utf-8")))
    summary = run_private_business_expansion(ROOT, D0, tmp_path / "d1")
    after = len(json.loads((base / "dev_v7_3_canonical_v1.json").read_text(encoding="utf-8"))) + len(json.loads((base / "validation_v7_3_canonical_v1.json").read_text(encoding="utf-8")))
    assert before == after == 39
    assert summary["new_formal_cases"] == 0
    assert summary["new_human_reviewed_gold"] == 0
    assert summary["production_agent_execution"] == "NOT RUN"
    rows = [json.loads(line) for line in (tmp_path / "d1/private_business_source_validated.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(x["annotation_metadata"]["human_reviewed"] is False for x in rows)
    assert all(x["annotation_metadata"]["formal_metric_eligible"] is False for x in rows)


def test_candidate_manifest_has_reproducibility_fingerprints(tmp_path):
    run_private_business_expansion(ROOT, D0, tmp_path / "d1")
    m = json.loads((tmp_path / "d1/private_business_candidate_manifest.json").read_text(encoding="utf-8"))
    assert len(m["db_sha256"]) == 64
    assert len(m["tool_registry_fingerprint"]) == 64
    assert len(m["raw_candidate_sha256"]) == 64
    assert len(m["source_validated_sha256"]) == 64
    assert m["random_seed"] == 0
    assert m["formal_metric_eligible"] is False

def test_d1_unified_cli_entrypoint(tmp_path):
    from eval_platform.cli import main
    output = tmp_path / "cli-d1"
    rc = main([
        "dataset-expand-private", "--root", str(ROOT), "--d0", str(D0), "--output", str(output)
    ])
    assert rc == 0
    summary = json.loads((output / "phase_d1_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "COMPLETE"
    assert summary["raw_candidates"] == 84
    assert summary["new_formal_cases"] == 0
