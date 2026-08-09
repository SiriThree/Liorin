from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evals.benchmark.expansion.g0_4_runner import EXPECTED_G03_CANDIDATE_SET_HASH, run_knowledge_gold_preparation

ROOT = Path(__file__).resolve().parents[2]
G01 = ROOT / "artifacts/evaluation/dataset-expansion-g0-1-knowledge-source"
G02 = ROOT / "artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning"
G03 = ROOT / "artifacts/evaluation/dataset-expansion-g0-3-knowledge-rendering"
G04 = ROOT / "artifacts/evaluation/dataset-expansion-g0-4-knowledge-gold"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _drafts(): return _jsonl(G04 / "knowledge_gold_drafts.jsonl")
def _ready(): return [x for x in _drafts() if x["annotation_status"] == "READY_FOR_DUAL_ANNOTATION"]
def _pre(): return _jsonl(G04 / "knowledge_preannotation_review_queue.jsonl")
def _reject(): return _jsonl(G04 / "knowledge_preannotation_rejected.jsonl")


def test_input_is_exactly_171_validated_and_review_reject_are_isolated():
    valid = _jsonl(G03 / "knowledge_source_validated.jsonl")
    review = _jsonl(G03 / "knowledge_query_review_queue.jsonl")
    rejected = _jsonl(G03 / "knowledge_render_rejected.jsonl")
    assert (len(valid), len(review), len(rejected)) == (171, 8, 1)
    vids = {x["candidate_id"] for x in valid}
    assert vids.isdisjoint({x["candidate_id"] for x in review})
    assert vids.isdisjoint({x["candidate_id"] for x in rejected})
    assert {x["candidate_id"] for x in _drafts()} == vids


def test_g03_candidate_set_hash_is_frozen():
    manifest = _json(G03 / "knowledge_candidate_manifest.json")
    assert manifest["candidate_set_hash"] == EXPECTED_G03_CANDIDATE_SET_HASH


def test_candidate_query_and_query_hash_are_immutable():
    candidates = {x["candidate_id"]: x for x in _jsonl(G03 / "knowledge_source_validated.jsonl")}
    for draft in _drafts():
        c = candidates[draft["candidate_id"]]
        assert draft["candidate_query"] == c["candidate_query"]
        assert draft["query_sha256"] == c["query_sha256"]
        assert hashlib.sha256(draft["candidate_query"].encode()).hexdigest() == draft["query_sha256"]


def test_gold_terminal_partition_is_complete_and_truthful():
    report = _json(G04 / "knowledge_gold_draft_report.json")
    assert report["input"] == report["drafted"] == 171
    assert report["ready_for_dual_annotation"] == 146
    assert report["needs_manual_precheck"] == 25
    assert report["rejected_before_annotation"] == 0
    assert 146 + 25 + 0 == 171


def test_effective_gold_units_equal_ready_and_have_no_duplicate_excess():
    report = _json(G04 / "knowledge_gold_dedup_report.json")
    assert report["ready"] == 146
    assert report["effective_gold_units"] == 146
    assert report["semantic_duplicate_excess"] == 0
    assert report["duplicate_groups"] == {}


def test_fact_roles_are_explicit_and_role_correction_exists():
    report = _json(G04 / "knowledge_gold_fact_roles.json")
    assert report["counts"]["ANSWER_REQUIRED"] == 252
    assert report["counts"]["SUPPORTING_ONLY"] == 8
    assert report["total"] == 260
    assert all(g["fact_role"] in {"ANSWER_REQUIRED", "REASONING_REQUIRED", "SUPPORTING_ONLY", "OPTIONAL_OUTPUT"} for d in _drafts() for g in d["gold_facts"])


def test_heading_or_intro_scaffolding_can_be_demoted_not_required():
    drafts = _drafts()
    corrected = [d for d in drafts if d["alignment_audit"]["resolved_through_role_correction"]]
    assert len(corrected) >= 1
    assert any(any(g["fact_role"] == "SUPPORTING_ONLY" for g in d["gold_facts"]) for d in corrected)


def test_broad_multifact_scope_is_precheck_not_silently_expanded():
    pre = _pre()
    broad = [d for d in pre if "BROAD_GROUP_SCOPE_COMPLETENESS_UNCERTAIN" in d["review_requirements"]]
    assert len(broad) == 24
    assert all(d["primary_task_type"] == "MULTI_FACT_SYNTHESIS" for d in broad)
    assert all(d["annotation_status"] == "NEEDS_MANUAL_PRECHECK" for d in broad)


def test_multifact_gold_audit_is_all_42_with_real_precheck():
    audit = _json(G04 / "knowledge_gold_multi_fact_audit.json")
    assert audit["input"] == 42
    assert audit["ready"] == 17
    assert audit["precheck"] == 25
    assert audit["rejected"] == 0
    assert audit["necessity_failures"] == 3
    assert audit["facts_demoted_from_required"] == 5


def test_multisection_all_13_preserve_two_section_necessity():
    audit = _json(G04 / "knowledge_gold_multi_section_audit.json")
    assert len(audit) == 13
    assert all(x["status"] == "READY_FOR_DUAL_ANNOTATION" for x in audit)
    assert all(x["two_section_necessity"] is True for x in audit)
    assert all(len(x["required_sections"]) >= 2 for x in audit)


def test_policy_gold_preserves_qualification_without_region_or_time_hallucination():
    audit = _json(G04 / "knowledge_gold_policy_audit.json")
    assert audit["input"] == 11
    assert audit["qualification_preserved"] == 11
    assert audit["exception_preserved"] == 11
    assert audit["absolute_conversion"] == 0
    assert audit["region_hallucination"] == 0
    assert audit["effective_time_hallucination"] == 0


def test_evidence_is_stable_section_level_not_whole_document():
    report = _json(G04 / "knowledge_gold_evidence.json")
    assert report["gold_evidence_rows"] == 184
    assert report["documents"] == 22
    assert report["whole_document_evidence_violations"] == 0
    assert report["unstable_section_violations"] == 0
    for d in _drafts():
        assert d["gold_evidence"]
        assert all(e["section_id"] and ":sec:" in e["section_id"] for e in d["gold_evidence"])


def test_comparison_contract_has_no_unjustified_numeric_tolerance():
    for d in _drafts():
        assert d["comparison_contract"]["all_required_facts_must_pass"] is True
        assert d["comparison_contract"]["no_unjustified_numeric_tolerance"] is True
        for g in d["gold_facts"]:
            if g["comparison_mode"] == "NUMERIC":
                assert g["value_metadata"].get("tolerance") is None


def test_task_success_contract_reuses_existing_binary_criteria():
    expected = {"RESPONSE_TYPE_CORRECT", "CRITICAL_FACTS_CORRECT", "CRITICAL_FACTS_GROUNDED", "NO_CRITICAL_HALLUCINATION"}
    for d in _drafts():
        contract = d["task_success_contract_draft"]
        assert set(contract["required_criteria"]) == expected
        assert contract["success_rule"] == "ALL_REQUIRED_CRITERIA_MUST_PASS"


def test_gold_level_cross_stage_collisions_are_explicitly_reported():
    report = _json(G04 / "knowledge_gold_cross_stage_collision.json")
    assert report["formal_exact_gold_fact_set"] == []
    assert report["troubleshooting_source_fact_overlap"] == []
    assert len(report["mixed_source_fact_overlap"]) == 1
    assert "semantic duplicate" in report["note"].lower()


def test_annotation_packets_exist_only_for_ready_cases():
    packets = _jsonl(G04 / "knowledge_annotation_packets.jsonl")
    ready = _ready()
    assert len(packets) == len(ready) == 146
    assert {x["candidate_id"] for x in packets} == {x["candidate_id"] for x in ready}


def test_annotation_packet_isolation_excludes_predictions_traces_and_other_annotations():
    packets = _jsonl(G04 / "knowledge_annotation_packets.jsonl")
    forbidden_keys = {"production_prediction", "agent_answer", "agent_trace", "judge_result", "annotator_a", "annotator_b", "adjudication", "formal_split"}
    for p in packets:
        assert forbidden_keys.isdisjoint(p.keys())
        excluded = set(p["excluded_information"])
        assert {"Production Prediction", "Agent Answer", "Agent Trace", "Judge Result", "Other Annotator Decision", "Adjudication", "Formal Split", "Future Test Membership"} <= excluded


def test_batch_manifest_matches_ready_and_has_zero_runs():
    manifest = _json(G04 / "knowledge_annotation_batch_manifest.json")
    assert manifest["ready_candidate_count"] == 146
    assert manifest["packet_count"] == 146
    assert len(manifest["packet_hashes"]) == 146
    assert len(set(manifest["packet_hashes"])) == 146
    assert manifest["annotation_runs"] == 0
    assert manifest["human_review_runs"] == 0
    assert manifest["formal_eligible_count"] == 0
    assert manifest["batch_id"].startswith("KNOW-G0.4-")


def test_ready_pool_retains_full_document_and_product_coverage():
    summary = _json(G04 / "phase_g0_4_summary.json")
    assert summary["document_coverage_ready"] == 22
    assert summary["product_coverage_ready"] == 20


def test_previously_untested_sources_are_reported_without_forced_full_ready():
    report = _json(G04 / "knowledge_gold_ready_distribution.json")
    rows = {x["name"]: x for x in report["previously_untested_sources"]}
    assert len(rows) == 5
    assert rows["Air Purifier"]["ready"] == 5
    assert rows["Air Conditioner"]["ready"] == 5
    assert rows["Steam Cleaner"]["ready"] == 8
    assert rows["Bluetooth Laser Mouse"]["ready"] == 4
    assert rows["Support FAQ"]["ready"] == 8


def test_query_review_8_and_g03_rejected_1_remain_excluded():
    summary = _json(G04 / "phase_g0_4_summary.json")
    assert summary["query_review_excluded"] == 8
    assert summary["g0_3_rejected_excluded"] == 1
    draft_ids = {x["candidate_id"] for x in _drafts()}
    assert draft_ids.isdisjoint({x["candidate_id"] for x in _jsonl(G03 / "knowledge_query_review_queue.jsonl")})
    assert draft_ids.isdisjoint({x["candidate_id"] for x in _jsonl(G03 / "knowledge_render_rejected.jsonl")})


def test_no_new_formal_annotation_or_production_claims():
    summary = _json(G04 / "phase_g0_4_summary.json")
    assert summary["new_formal_cases"] == 0
    assert summary["annotation_runs"] == 0
    assert summary["production_agent"] == "NOT RUN"
    assert summary["d3r"] == "DEFERRED_BY_ENVIRONMENT"


def test_formal_canonical_stays_39():
    total = 0
    for name in ("dev_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.json"):
        data = _json(ROOT / "evals/benchmark/data/canonical" / name)
        rows = data.get("samples", data) if isinstance(data, dict) else data
        total += len(rows)
    assert total == 39


def test_previous_frozen_asset_counts_are_unchanged():
    private = _json(ROOT / "artifacts/evaluation/dataset-expansion-d2/annotation_batch_manifest.json")
    mixed = _json(ROOT / "artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_annotation_batch_manifest_refrozen.json")
    f0 = _json(ROOT / "artifacts/evaluation/dataset-expansion-f0-troubleshooting/troubleshooting_candidate_manifest.json")
    g02 = _json(G02 / "knowledge_task_plan_manifest.json")
    g03 = _json(G03 / "knowledge_candidate_manifest.json")
    assert private["packet_count"] == 76
    assert mixed["packet_count"] == 58
    assert f0["source_validated_count"] == 66
    assert g02["planned_count"] == 180
    assert g03["source_validated_count"] == 171


def test_reproducible_rerun_has_same_gold_and_packet_batch_hash(tmp_path: Path):
    result = run_knowledge_gold_preparation(ROOT, G03, G02, G01, tmp_path / "g04")
    baseline = _json(G04 / "phase_g0_4_summary.json")
    assert result["gold_set_hash"] == baseline["gold_set_hash"]
    assert result["annotation_batch_hash"] == baseline["annotation_batch_hash"]
    assert result["annotation_batch_id"] == baseline["annotation_batch_id"]
    assert result["ready_for_dual_annotation"] == 146
    assert result["needs_manual_precheck"] == 25
    assert result["rejected_before_annotation"] == 0
