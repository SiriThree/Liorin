from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from evals.benchmark.expansion.e1_runner import run_mixed_gold_preparation
from evals.benchmark.expansion.mixed_gold_alignment import validate_mixed_gold

ROOT = Path(__file__).resolve().parents[2]
E0 = ROOT / "artifacts/evaluation/dataset-expansion-e0-mixed"
E1 = ROOT / "artifacts/evaluation/dataset-expansion-e1-mixed-gold"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _by_id(rows):
    return {x["candidate_id"]: x for x in rows}


def test_e1_frozen_input_and_e0_reject_isolation():
    candidates = _jsonl(E0 / "mixed_source_validated.jsonl")
    rejected = _jsonl(E0 / "mixed_rejected.jsonl")
    assert len(candidates) == 58
    assert len(rejected) == 10
    assert not ({x["candidate_id"] for x in candidates} & {x["candidate_id"] for x in rejected})
    assert {x["mixed_family_id"] for x in rejected} == {"MIXED_ORDER_RETURN_POLICY"}
    assert "MIXED_ORDER_RETURN_POLICY" not in {x["mixed_family_id"] for x in candidates}


def test_e1_draft_statuses_are_explicit_and_not_formal():
    drafts = _jsonl(E1 / "mixed_gold_drafts.jsonl")
    assert len(drafts) == 58
    counts = {}
    for d in drafts:
        counts[d["annotation_status"]] = counts.get(d["annotation_status"], 0) + 1
        assert d["human_reviewed"] is False
        assert d["formal_eligible"] is False
    assert counts == {"READY_FOR_DUAL_ANNOTATION": 16, "NEEDS_MANUAL_PRECHECK": 42}


def test_manual_routing_fact_is_intermediate_and_manual_fact_is_answer_required():
    candidates = _by_id(_jsonl(E0 / "mixed_source_validated.jsonl"))
    drafts = _by_id(_jsonl(E1 / "mixed_gold_drafts.jsonl"))
    cid = next(k for k, c in candidates.items() if c["mixed_mode"] == "ENTITY_TO_KNOWLEDGE_ROUTING")
    d = drafts[cid]
    assert d["structured_facts"][0]["role"] == "TASK_REQUIRED_INTERMEDIATE"
    assert d["structured_facts"][0]["answer_required"] is False
    assert d["document_facts"][0]["role"] == "ANSWER_REQUIRED"
    assert d["document_facts"][0]["answer_required"] is True
    assert d["derived_facts"][0]["role"] == "TASK_REQUIRED_INTERMEDIATE"


def test_manual_broad_section_scope_is_precheck_not_silently_incomplete_gold():
    drafts = _jsonl(E1 / "mixed_gold_drafts.jsonl")
    manual = [d for d in drafts if d["mixed_mode"] == "ENTITY_TO_KNOWLEDGE_ROUTING"]
    assert len(manual) == 42
    assert all(d["annotation_status"] == "NEEDS_MANUAL_PRECHECK" for d in manual)
    assert all("BROAD_MANUAL_SECTION_SCOPE" in d["review_requirements"] for d in manual)
    report = _json(E1 / "mixed_gold_minimality_report.json")
    assert report["minimality_issue_count"] == 42
    assert report["completeness_issue_count"] == 42


def test_order_policy_derived_decision_and_qualification_are_source_preserving():
    candidates = _by_id(_jsonl(E0 / "mixed_source_validated.jsonl"))
    drafts = _by_id(_jsonl(E1 / "mixed_gold_drafts.jsonl"))
    policy_rules = _jsonl(E1 / "mixed_policy_rule_drafts.jsonl")
    shipped = next(c for c in candidates.values() if c["mixed_family_id"] == "MIXED_ORDER_STATUS_POLICY" and c["source_entity_state"] == "Shipped")
    d = drafts[shipped["candidate_id"]]
    assert d["annotation_status"] == "READY_FOR_DUAL_ANNOTATION"
    assert d["structured_facts"][0]["role"] == "TASK_REQUIRED_INTERMEDIATE"
    assert d["document_facts"][0]["role"] == "TASK_REQUIRED_INTERMEDIATE"
    assert d["derived_facts"][0]["role"] == "ANSWER_REQUIRED"
    assert "USUALLY_DIRECT_CANCEL_NOT_ALLOWED" in d["derived_facts"][0]["normalized_result"]
    matching = [r for r in policy_rules if "Shipped" in r["applicable_values"]]
    assert len(matching) == 1
    assert matching[0]["ambiguity_status"] == "QUALIFIED_BUT_USABLE"
    assert matching[0]["qualification_preserved"] is True


def test_processing_and_cancelled_policy_rules_are_deterministic():
    rules = _jsonl(E1 / "mixed_policy_rule_drafts.jsonl")
    deterministic = [r for r in rules if r["ambiguity_status"] == "DETERMINISTIC"]
    assert len(deterministic) == 2
    assert {tuple(r["applicable_values"]) for r in deterministic} == {("Processing",), ("Cancelled",)}


def test_warranty_policy_gold_requires_current_state_and_qualified_policy_facts():
    candidates = _by_id(_jsonl(E0 / "mixed_source_validated.jsonl"))
    drafts = _by_id(_jsonl(E1 / "mixed_gold_drafts.jsonl"))
    c = next(x for x in candidates.values() if x["mixed_family_id"] == "MIXED_WARRANTY_STATUS_POLICY")
    d = drafts[c["candidate_id"]]
    assert d["annotation_status"] == "READY_FOR_DUAL_ANNOTATION"
    assert d["structured_facts"][0]["role"] == "ANSWER_REQUIRED"
    assert len(d["document_facts"]) == 2
    assert all(f["role"] == "ANSWER_REQUIRED" for f in d["document_facts"])
    assert d["derived_facts"][0]["role"] == "SUPPORTING_ONLY"


def test_every_draft_preserves_dual_source_evidence_and_stable_document_identity():
    drafts = _jsonl(E1 / "mixed_gold_drafts.jsonl")
    for d in drafts:
        types = {e["source_type"] for e in d["gold_evidence"]}
        assert {"STRUCTURED_DATA", "DOCUMENT"}.issubset(types)
        for e in d["gold_evidence"]:
            if e["source_type"] == "STRUCTURED_DATA":
                assert "#" in e["evidence_id"]
                assert ":hash:" in e["evidence_id"]
            else:
                assert ":sec:" in e["section_id"]
                assert "-H" not in e["section_id"]


def test_derived_provenance_has_valid_inputs_and_validator_fails_closed_when_missing():
    candidates = _by_id(_jsonl(E0 / "mixed_source_validated.jsonl"))
    drafts = _by_id(_jsonl(E1 / "mixed_gold_drafts.jsonl"))
    cid = next(k for k, c in candidates.items() if c["mixed_family_id"] == "MIXED_ORDER_STATUS_POLICY")
    c = candidates[cid]
    d = drafts[cid]
    diag = {"runtime_leakage": [], "manual_scope_issue": False}
    assert validate_mixed_gold(c, d, diag)["status"] == "aligned"
    broken = copy.deepcopy(d)
    broken["derived_facts"][0]["input_fact_ids"].append("missing-fact")
    result = validate_mixed_gold(c, broken, diag)
    assert "DERIVED_INPUT_REFERENCE_INVALID" in result["issues"]


def test_validator_rejects_missing_either_source_evidence():
    candidates = _by_id(_jsonl(E0 / "mixed_source_validated.jsonl"))
    drafts = _by_id(_jsonl(E1 / "mixed_gold_drafts.jsonl"))
    cid = next(iter(candidates))
    c = candidates[cid]
    d = copy.deepcopy(drafts[cid])
    d["gold_evidence"] = [e for e in d["gold_evidence"] if e["source_type"] != "DOCUMENT"]
    result = validate_mixed_gold(c, d, {"runtime_leakage": [], "manual_scope_issue": False})
    assert "MISSING_DOCUMENT_EVIDENCE" in result["issues"]


def test_runtime_materialization_is_complete_and_leakage_free():
    runtime = _json(E1 / "mixed_runtime_materialization.json")
    leakage = _json(E1 / "mixed_query_leakage_report.json")
    assert runtime["count"] == 58
    assert runtime["materializable"] == 58
    assert leakage["clean"] == 58
    assert leakage["leaked"] == 0
    assert all("<ORDER_REF:" not in r["runtime_query_redacted"] and "<TICKET_REF:" not in r["runtime_query_redacted"] and "<WARRANTY_REF:" not in r["runtime_query_redacted"] for r in runtime["rows"])


def test_ready_packet_freeze_contains_only_ready_gold_and_no_runtime_outputs():
    drafts = _by_id(_jsonl(E1 / "mixed_gold_drafts.jsonl"))
    packets = _jsonl(E1 / "mixed_annotation_packets.jsonl")
    assert len(packets) == 16
    assert len({p["annotation_packet_hash"] for p in packets}) == 16
    for p in packets:
        assert drafts[p["candidate_id"]]["annotation_status"] == "READY_FOR_DUAL_ANNOTATION"
        text = json.dumps(p, ensure_ascii=False)
        for forbidden in ("Production Prediction", "Agent Trace", "Judge Result", "Other Annotator Decision"):
            assert forbidden in p["excluded_information"]
        assert "FORMAL_ELIGIBLE" not in text
        assert "section_text" not in text


def test_batch_hash_is_reproducible_when_timestamp_changes(tmp_path: Path):
    out1 = tmp_path / "one"
    out2 = tmp_path / "two"
    s1 = run_mixed_gold_preparation(ROOT, E0, out1)
    s2 = run_mixed_gold_preparation(ROOT, E0, out2)
    assert s1["annotation_batch_hash"] == s2["annotation_batch_hash"]
    assert _json(out1 / "mixed_annotation_batch_manifest.json")["batch_hash"] == _json(out2 / "mixed_annotation_batch_manifest.json")["batch_hash"]


def test_gold_level_dedup_rechecks_existing_formal_and_reports_effective_signatures():
    report = _json(E1 / "mixed_gold_level_dedup.json")
    assert report["existing_formal_mixed_count"] == 10
    assert report["existing_formal_gold_collision_count"] == 0
    assert report["unique_gold_information_signatures"] == 48
    assert report["low_information_entity_variation_count"] == 16


def test_ready_policy_concentration_is_recomputed_not_hidden():
    ready = _json(E1 / "mixed_ready_distribution.json")
    assert ready["ready"] == 16
    assert ready["policy_candidate_count"] == 16
    assert ready["max_cases_per_policy_fact"] == 8
    assert ready["max_policy_fact_ratio_over_ready"] == pytest.approx(0.5)


def test_e1_public_artifacts_do_not_leak_private_business_ids_or_email():
    for path in E1.iterdir():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "ORD-2026-" not in text
        assert "TCK-2026-" not in text
        assert "WAR-2026-" not in text
        assert "CUST-" not in text
        assert "@liorin" not in text.lower()


def test_existing_formal_canonical_count_is_still_39_and_no_new_formal_files():
    canonical = ROOT / "evals/benchmark/data/canonical"
    total = 0
    for name in ("dev_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.json"):
        total += len(_json(canonical / name))
    assert total == 39


def test_annotation_and_production_are_not_run_and_d3r_stays_deferred():
    summary = _json(E1 / "phase_e1_summary.json")
    assert summary["annotation_runs"] == 0
    assert summary["production_agent_execution"] == "NOT RUN"
    assert summary["d3r_status"] == "DEFERRED_BY_ENVIRONMENT"
    assert summary["agreement"] == "NOT_RUN"
