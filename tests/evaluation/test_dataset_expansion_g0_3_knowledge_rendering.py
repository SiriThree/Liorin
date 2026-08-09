from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from evals.benchmark.expansion.g0_3_runner import EXPECTED_TASK_PLAN_HASH, run_knowledge_query_rendering
from evals.benchmark.expansion.knowledge_query_validation import normalize_query

ROOT = Path(__file__).resolve().parents[2]
G01 = ROOT / "artifacts/evaluation/dataset-expansion-g0-1-knowledge-source"
G02 = ROOT / "artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning"
G03 = ROOT / "artifacts/evaluation/dataset-expansion-g0-3-knowledge-rendering"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _plans(): return _jsonl(G02 / "knowledge_task_plans.jsonl")
def _raw(): return _jsonl(G03 / "knowledge_raw_candidates.jsonl")
def _valid(): return _jsonl(G03 / "knowledge_source_validated.jsonl")
def _review(): return _jsonl(G03 / "knowledge_query_review_queue.jsonl")
def _reject(): return _jsonl(G03 / "knowledge_render_rejected.jsonl")


def test_frozen_g02_input_is_exact():
    manifest = _json(G02 / "knowledge_task_plan_manifest.json")
    assert manifest["planned_count"] == 180
    assert manifest["effective_plan_count"] == 180
    assert manifest["task_plan_set_hash"] == EXPECTED_TASK_PLAN_HASH


def test_exactly_one_render_attempt_per_task_plan():
    plans = _plans(); raw = _raw()
    assert len(plans) == len(raw) == 180
    assert len({r["task_plan_id"] for r in raw}) == 180
    assert {p["task_plan_id"] for p in plans} == {r["task_plan_id"] for r in raw}


def test_final_status_partition_is_complete():
    raw = _raw(); valid = _valid(); review = _review(); rejected = _reject()
    assert len(valid) == 171
    assert len(review) == 8
    assert len(rejected) == 1
    assert len(valid) + len(review) + len(rejected) == len(raw) == 180
    assert {r["status"] for r in valid} == {"SOURCE_VALIDATED"}
    assert {r["status"] for r in review} == {"NEEDS_QUERY_REVIEW"}
    assert {r["status"] for r in rejected} == {"REJECTED"}


def test_effective_ratio_is_100_percent_of_validated():
    report = _json(G03 / "knowledge_candidate_effective_diversity.json")
    assert report["source_validated"] == 171
    assert report["effective_semantic_units"] == 171
    assert report["effective_ratio"] == 1.0
    assert report["semantic_duplicate_excess"] == 0


def test_validated_queries_have_no_exact_or_normalized_duplicates():
    rows = _valid()
    assert len({r["candidate_query"] for r in rows}) == len(rows)
    assert len({normalize_query(r["candidate_query"]) for r in rows}) == len(rows)
    report = _json(G03 / "knowledge_candidate_dedup_report.json")
    assert report["exact_query_duplicate_excess"] == 0
    assert report["normalized_query_duplicate_excess"] == 0


def test_no_construction_placeholders_or_internal_ids_in_validated_queries():
    forbidden = ("LIO-PROD-", "KSU-", "KTP-", "af:", "PLACEHOLDER", "FIXTURE", "SOURCE_UNIT", "PRODUCT_X", "section_id", "fact_id", "document_id")
    for row in _valid():
        q = row["candidate_query"]
        assert not any(x.lower() in q.lower() for x in forbidden)


def test_task_plan_lineage_and_immutable_fields_are_preserved():
    plans = {p["task_plan_id"]: p for p in _plans()}
    for row in _raw():
        p = plans[row["task_plan_id"]]
        assert row["primary_task_type"] == p["primary_task_type"]
        assert row["semantic_family_id"] == p["semantic_family_id"]
        assert row["reasoning_type"] == p["reasoning_type"]
        assert row["difficulty"] == p["difficulty"]
        assert row["answer_scope"] == p["answer_scope"]
        assert row["source_unit_ids"] == p["source_unit_ids"]
        assert row["document_ids"] == p["document_ids"]
        assert row["section_ids"] == p["section_ids"]
        assert row["product_ids"] == p["product_ids"]
        assert row["required_fact_ids"] == p["required_fact_ids"]
        assert row["required_evidence_ids"] == p["required_evidence_ids"]


def test_query_hash_and_candidate_id_are_deterministic():
    for row in _raw():
        assert row["query_sha256"] == hashlib.sha256(row["candidate_query"].encode()).hexdigest()
        assert row["candidate_id"].startswith("KQC-")


def test_all_required_fact_and_evidence_alignment_is_complete_for_validated():
    for row in _valid():
        fa = row["scope_validation"]["fact_alignment"]
        ea = row["scope_validation"]["evidence_alignment"]
        assert fa["missing"] == []
        assert fa["extra"] == []
        assert fa["covered"] == fa["required"]
        assert ea["pass"] is True


def test_multifact_all_42_preserve_scope():
    rows = [r for r in _raw() if r["primary_task_type"] == "MULTI_FACT_SYNTHESIS"]
    assert len(rows) == 42
    assert all(r["status"] == "SOURCE_VALIDATED" for r in rows)
    assert all(r["scope_validation"]["scope"]["pass"] for r in rows)
    audit = _json(G03 / "knowledge_query_multi_fact_audit.json")
    assert audit["scope_collapse"] == 0
    assert audit["necessity_preserved"] == 42


def test_multisection_all_13_preserve_relation_and_two_section_evidence():
    rows = _json(G03 / "knowledge_query_multi_section_audit.json")
    assert len(rows) == 13
    assert all(r["status"] == "SOURCE_VALIDATED" for r in rows)
    assert all(r["relation_preserved"] is True for r in rows)
    assert all(r["both_necessary"] is True for r in rows)
    assert all(len(r["sections"]) >= 2 for r in rows)


def test_policy_audit_has_no_absolutization_or_hallucinated_region_time():
    audit = _json(G03 / "knowledge_query_policy_audit.json")
    assert audit["planned"] == 12
    assert audit["source_validated"] == 11
    assert audit["absolute_interpretation_failures"] == 0
    assert audit["region_hallucination"] == 0
    assert audit["effective_time_hallucination"] == 0


def test_compatibility_uncertainty_is_reviewed_not_silently_reclassified():
    review = _review()
    flagged = [r for r in review if "PLANNING_COMPATIBILITY_SEMANTICS_UNCERTAIN" in r["quality_flags"]]
    assert len(flagged) == 3
    assert all(r["primary_task_type"] == "COMPATIBILITY" for r in flagged)


def test_only_hard_reject_is_troubleshooting_category_drift():
    rejected = _reject()
    assert len(rejected) == 1
    assert rejected[0]["task_plan_id"] == "KTP-06321e1fd45f44bd"
    assert rejected[0]["rejection_reasons"] == ["CATEGORY_DRIFT_TROUBLESHOOTING"]


def test_review_queue_is_pre_candidate_review_not_gold_review():
    assert len(_review()) == 8
    for row in _review():
        assert row["status"] == "NEEDS_QUERY_REVIEW"
        assert "gold" not in row


def test_document_and_product_coverage_remain_full_for_validated():
    docs = _json(G03 / "knowledge_candidate_document_balance.json")
    prods = _json(G03 / "knowledge_candidate_product_balance.json")
    assert docs["covered"] == 22
    assert prods["covered"] == 20


def test_render_surface_diversity_is_not_template_dominated():
    report = _json(G03 / "knowledge_rendering_pattern_report.json")
    assert report["pattern_count"] >= 40
    assert report["max_pattern_ratio"] <= 0.40
    assert report["max_prefix_ratio"] < 0.20


def test_validated_difficulty_distribution_remains_balanced():
    dist = _json(G03 / "knowledge_candidate_difficulty_distribution.json")
    assert dist["EASY"]["ratio"] < 0.50
    assert 0.30 <= dist["MEDIUM"]["ratio"] <= 0.50
    assert 0.15 <= dist["HARD"]["ratio"] <= 0.30


def test_no_new_formal_gold_annotation_or_production_claims():
    manifest = _json(G03 / "knowledge_candidate_manifest.json")
    summary = _json(G03 / "phase_g0_3_summary.json")
    assert manifest["new_formal_cases"] == summary["new_formal_cases"] == 0
    assert manifest["gold"] == summary["gold"] == "NOT PREPARED"
    assert manifest["annotation_runs"] == summary["annotation_runs"] == 0
    assert manifest["production_agent"] == summary["production_agent"] == "NOT RUN"


def test_previous_frozen_assets_counts_are_unchanged():
    private = _json(ROOT / "artifacts/evaluation/dataset-expansion-d2/annotation_batch_manifest.json")
    mixed = _json(ROOT / "artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_annotation_batch_manifest_refrozen.json")
    f0 = _json(ROOT / "artifacts/evaluation/dataset-expansion-f0-troubleshooting/troubleshooting_candidate_manifest.json")
    assert private["packet_count"] == 76
    assert mixed["packet_count"] == 58
    assert f0["source_validated_count"] == 66


def test_formal_canonical_stays_39():
    total = 0
    for name in ("dev_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.json"):
        data = _json(ROOT / "evals/benchmark/data/canonical" / name)
        rows = data.get("samples", data) if isinstance(data, dict) else data
        total += len(rows)
    assert total == 39


def test_reproducible_rerun_has_same_candidate_set_hash(tmp_path: Path):
    result = run_knowledge_query_rendering(ROOT, G02, G01, tmp_path / "g03")
    manifest = _json(G03 / "knowledge_candidate_manifest.json")
    assert result["candidate_set_hash"] == manifest["candidate_set_hash"]
    assert result["source_validated"] == 171
    assert result["needs_query_review"] == 8
    assert result["rejected"] == 1
