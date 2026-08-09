from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from evals.benchmark.expansion.g0_2_runner import EXPECTED_SOURCE_SPACE_HASH, run_knowledge_task_planning
from evals.benchmark.expansion.knowledge_plan_validation import validate_plan
from evals.benchmark.expansion.knowledge_selection import effective_representatives


ROOT = Path(__file__).resolve().parents[2]
G01 = ROOT / "artifacts/evaluation/dataset-expansion-g0-1-knowledge-source"
G02 = ROOT / "artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning"


def _json(name: str):
    return json.loads((G02 / name).read_text(encoding="utf-8"))


def _json_g01(name: str):
    return json.loads((G01 / name).read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _plans():
    return _jsonl(G02 / "knowledge_task_plans.jsonl")


def _facts():
    rows = _jsonl(G01 / "knowledge_atomic_fact_audit.jsonl")
    return {r["fact_id"]: r for r in rows}


def _units():
    rows = _jsonl(G01 / "knowledge_source_units.jsonl")
    return {r["source_unit_id"]: r for r in rows}


def _ownership():
    data = _json_g01("knowledge_category_ownership.json")
    return {r["fact_id"]: set(r.get("observed_overlaps", [])) for r in data["facts"]}


def test_g01_source_space_is_frozen():
    manifest = _json_g01("knowledge_source_space_manifest.json")
    assert manifest["knowledge_source_space_hash"] == EXPECTED_SOURCE_SPACE_HASH
    assert manifest["effective_source_units"] == 1195


def test_effective_representative_pool_is_exactly_1195():
    units = _jsonl(G01 / "knowledge_source_units.jsonl")
    bp = _json_g01("knowledge_capacity_blueprint.json")
    previous = _json_g01("knowledge_previous_uncovered_source_audit.json")
    reps, _ = effective_representatives(units, bp, previous)
    assert len(reps) == 1195


def test_g02_generates_plans_only_not_queries_or_candidates():
    summary = _json("phase_g0_2_summary.json")
    manifest = _json("knowledge_task_plan_manifest.json")
    assert summary["new_queries"] == summary["new_candidates"] == 0
    assert manifest["new_queries"] == manifest["new_candidates"] == 0
    forbidden = {"candidate_query", "query", "gold_answer", "gold_facts", "annotation_packet"}
    for row in _plans():
        assert not (forbidden & set(row))


def test_planned_count_status_and_effective_diversity():
    plans = _plans()
    diversity = _json("knowledge_task_plan_effective_diversity.json")
    assert len(plans) == 180
    assert {p["status"] for p in plans} == {"PLANNED"}
    assert diversity["effective_task_plan_semantics"] == 180
    assert diversity["semantic_duplicate_excess"] == 0
    assert diversity["unique_plan_signatures"] == 180


def test_priority_mix_is_balanced_without_p2():
    report = _json("knowledge_selection_priority_report.json")
    assert report["P0"] == {"available": 654, "selected": 135}
    assert report["P1"] == {"available": 532, "selected": 45}
    assert report["P2"] == {"available": 9, "selected": 0}


def test_feature_and_direct_spec_caps_hold():
    summary = _json("phase_g0_2_summary.json")
    assert summary["feature_ratio"] <= 0.25
    assert summary["direct_spec_ratio"] <= 0.20
    guards = summary["balance_guards"]
    assert guards["feature_cap_pass"] is True
    assert guards["direct_spec_cap_pass"] is True


def test_task_type_capability_mix_is_present():
    dist = _json("knowledge_task_type_distribution.json")
    expected = {
        "DIRECT_FACT", "PRODUCT_SPEC", "FEATURE_OR_INSTRUCTION", "COMPATIBILITY",
        "LIMITATION", "POLICY_OR_WARRANTY", "FAQ_PROCESS", "MULTI_FACT_SYNTHESIS",
        "MULTI_SECTION_SYNTHESIS",
    }
    assert set(dist) == expected
    assert dist["COMPATIBILITY"]["count"] == 21
    assert dist["LIMITATION"]["count"] == 12
    assert dist["MULTI_FACT_SYNTHESIS"]["count"] == 42
    assert dist["MULTI_SECTION_SYNTHESIS"]["count"] == 13


def test_difficulty_is_structure_balanced():
    dist = _json("knowledge_difficulty_distribution.json")
    assert dist["EASY"]["ratio"] <= 0.40
    assert 0.35 <= dist["MEDIUM"]["ratio"] <= 0.50
    assert 0.15 <= dist["HARD"]["ratio"] <= 0.25


def test_all_sources_and_products_are_covered():
    summary = _json("phase_g0_2_summary.json")
    assert summary["documents"] == 22
    assert summary["products"] == 20
    docs = _json("knowledge_document_balance.json")
    assert docs["max_ratio"] <= 0.08


def test_all_five_previously_untested_sources_are_selected():
    rows = _json("knowledge_previous_uncovered_source_selection.json")
    assert len(rows) == 5
    assert all(r["selected"] for r in rows)
    assert all(r["planned"] > 0 and r["effective"] > 0 for r in rows)


def test_source_topic_balance_uses_g01_topics_not_composition_labels():
    report = _json("knowledge_semantic_topic_balance.json")
    assert len(report["available"]) == 18
    assert report["covered_source_topics"] == 17
    assert report["max_source_topic_ratio"] <= 0.20
    # The only unused source topic is the one ambiguous warranty-rule unit.
    assert set(report["available"]) - set(report["selected_source_topics"]) == {"warranty_rule"}


def test_multifact_plans_use_minimal_required_fact_sets():
    facts = _facts()
    for p in _plans():
        if p["primary_task_type"] != "MULTI_FACT_SYNTHESIS":
            continue
        assert 2 <= len(p["required_fact_ids"]) <= 3
        assert len(set(p["required_fact_ids"])) == len(p["required_fact_ids"])
        assert all(fid in facts for fid in p["required_fact_ids"])
        assert p["answer_scope"] in {"BOUNDED_FACT_SET", "PROCEDURE_SUBSET"}


def test_multisection_plans_require_strong_relation_evidence():
    for p in _plans():
        if p["primary_task_type"] != "MULTI_SECTION_SYNTHESIS":
            continue
        assert len(set(p["section_ids"])) >= 2
        assert p["composition_validation"] == "EXPLICIT_CROSS_SECTION_REFERENCE"
        assert p["composition_relation_evidence"]
        assert p["semantic_topic"] not in {"same_topic_cross_reference", "explicit_cross_reference"}
        assert len(p["required_evidence_ids"]) >= 2


def test_planned_facts_do_not_have_unresolved_deictic_or_regulatory_blob():
    facts = _facts()
    for p in _plans():
        for fid in p["required_fact_ids"]:
            text = facts[fid]["fact_text"]
            assert not any(x in text for x in ("此功能", "该功能", "本功能"))
            assert "这些限制旨在" not in text
            assert "联邦通信委员会" not in text


def test_active_troubleshooting_overlap_is_not_planned():
    ownership = _ownership()
    for p in _plans():
        assert all("TROUBLESHOOTING" not in ownership.get(fid, set()) for fid in p["required_fact_ids"])


def test_all_plans_pass_current_hard_validator():
    fact_map = _facts()
    unit_map = _units()
    ownership = _ownership()
    for p in _plans():
        assert validate_plan(p, fact_map, unit_map, ownership) == []


def test_rendering_constraints_are_frozen_without_rendering_queries():
    required = {
        "allowed_user_context", "required_user_context", "forbidden_answer_terms",
        "forbidden_internal_terms", "must_not_expand_scope", "must_not_reveal_answer",
        "product_name_allowed", "expected_query_intent",
    }
    for p in _plans():
        assert required <= set(p["rendering_constraints"])
        assert p["rendering_constraints"]["must_not_expand_scope"] is True
        assert p["rendering_constraints"]["must_not_reveal_answer"] is True


def test_future_split_keys_are_complete():
    required = {
        "document_family", "product_family", "section_family", "fact_family",
        "semantic_family_id", "source_unit_ids", "composition_family_id",
    }
    for p in _plans():
        assert required <= set(p["future_split_keys"])
        assert p["future_split_keys"]["source_unit_ids"] == sorted(p["source_unit_ids"])


def test_section_and_source_unit_reuse_is_bounded():
    plans = _plans()
    sec = Counter(s for p in plans for s in set(p["section_ids"]))
    assert max(sec.values()) <= 2
    primary = Counter()
    for p in plans:
        if p["primary_task_type"] != "MULTI_SECTION_SYNTHESIS":
            primary.update(p["source_unit_ids"])
    assert max(primary.values()) <= 1


def test_faq_and_policy_primary_inflation_is_controlled():
    units = _units()
    faq_units = []
    policy_units = []
    for p in _plans():
        if p["primary_task_type"] == "FAQ_PROCESS":
            faq_units.extend(p["source_unit_ids"])
        if p["primary_task_type"] == "POLICY_OR_WARRANTY" and len(p["source_unit_ids"]) == 1:
            policy_units.extend(p["source_unit_ids"])
    assert len(faq_units) == len(set(faq_units))
    assert len(policy_units) == len(set(policy_units))
    assert all(units[u]["source_type"] == "faq" for u in faq_units)


def test_frozen_batches_and_formal_count_are_still_exact():
    private = json.loads((ROOT / "artifacts/evaluation/dataset-expansion-d2/annotation_batch_manifest.json").read_text())
    mixed = json.loads((ROOT / "artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_annotation_batch_manifest_refrozen.json").read_text())
    f0 = json.loads((ROOT / "artifacts/evaluation/dataset-expansion-f0-troubleshooting/phase_f0_summary.json").read_text())
    assert private["packet_count"] == 76
    assert mixed["packet_count"] == 58
    assert f0["source_validated"] == 66
    total = 0
    for name in ("dev_v7_3_canonical_v1.json", "validation_v7_3_canonical_v1.json"):
        data = json.loads((ROOT / "evals/benchmark/data/canonical" / name).read_text())
        rows = data.get("samples", data) if isinstance(data, dict) else data
        total += len(rows)
    assert total == 39


def test_reproducible_rerun_has_same_task_plan_set_hash(tmp_path: Path):
    result = run_knowledge_task_planning(ROOT, G01, tmp_path / "g02")
    assert result["task_plan_set_hash"] == _json("knowledge_task_plan_manifest.json")["task_plan_set_hash"]
    assert result["planned"] == 180
    assert result["effective_task_plan_semantics"] == 180
