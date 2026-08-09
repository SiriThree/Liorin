from __future__ import annotations

import json
from pathlib import Path

from evals.benchmark.expansion.g0_1_runner import run_knowledge_source_audit
from evals.benchmark.expansion.knowledge_source import audit_knowledge_source_space

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/evaluation/dataset-expansion-g0-1-knowledge-source"


def load_json(name: str):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def load_jsonl(name: str):
    return [json.loads(x) for x in (OUT / name).read_text(encoding="utf-8").splitlines() if x.strip()]


def test_current_corpus_matches_d0_source_truth_exactly():
    s = load_json("phase_g0_1_summary.json")
    m = load_json("knowledge_source_space_manifest.json")
    assert s["sources"] == 22
    assert s["manuals"] == 20 and s["policies"] == 1 and s["faq"] == 1
    assert s["stable_sections"] == 1216
    assert s["atomic_facts"] == 4913
    assert s["heuristic_usable"] == 4907
    assert m["source_drift"]["status"] == "NO_SOURCE_DRIFT"
    assert m["source_drift"]["document_hashes_equal"] is True
    assert m["source_drift"]["atomic_fact_inventory_equal"] is True


def test_fact_audit_has_one_stricter_task_usability_status_per_fact():
    rows = load_jsonl("knowledge_atomic_fact_audit.jsonl")
    assert len(rows) == 4913
    allowed = {"TASK_USABLE","GROUP_ONLY","CONTEXT_DEPENDENT","FRAGMENT","DUPLICATE_SEMANTIC_FACT","NON_TASK_INFORMATION","CATEGORY_OWNERSHIP_EXCLUDED","UNSUPPORTED"}
    assert all(r["task_usability"] in allowed for r in rows)
    assert sum(r["task_usability"] == "TASK_USABLE" for r in rows) < 4907


def test_active_troubleshooting_facts_are_excluded_from_knowledge_ownership():
    ownership = load_json("knowledge_category_ownership.json")
    f0 = load_jsonl("../dataset-expansion-f0-troubleshooting/troubleshooting_source_units.jsonl") if False else None
    trouble_ids = set()
    for row in [json.loads(x) for x in (ROOT/"artifacts/evaluation/dataset-expansion-f0-troubleshooting/troubleshooting_source_units.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]:
        if row["benchmark_usable"]:
            trouble_ids.update(row["manual_fact_ids"])
    owner_map = {r["fact_id"]: r["current_owner"] for r in ownership["facts"]}
    assert trouble_ids
    assert all(owner_map[fid] == "TROUBLESHOOTING" for fid in trouble_ids)


def test_source_unit_trace_is_complete_and_not_fact_equal_case_generation():
    facts = {r["fact_id"]: r for r in load_jsonl("knowledge_atomic_fact_audit.jsonl")}
    units = load_jsonl("knowledge_source_units.jsonl")
    docs = {r["document_id"] for r in load_json("knowledge_document_inventory.json")}
    assert 500 < len(units) < 4913
    for u in units:
        assert u["document_id"] in docs
        assert u["fact_ids"]
        assert all(fid in facts for fid in u["fact_ids"])
        assert all(facts[fid]["document_id"] == u["document_id"] for fid in u["fact_ids"])


def test_independent_askability_and_coherent_groups_are_separate_capacity():
    independent = load_jsonl("knowledge_independent_askable_facts.jsonl")
    groups = load_jsonl("knowledge_coherent_fact_groups.jsonl")
    assert len(independent) == load_json("knowledge_capacity_funnel.json")["independent_askable_facts"]
    assert groups
    assert all(1 <= len(g["fact_ids"]) <= 3 for g in groups)
    assert all(g["minimal"] for g in groups)


def test_procedure_inflation_is_prevented():
    x = load_json("knowledge_inflation_audit.json")
    assert x["procedure_source_units"] > 0
    assert x["procedure_fact_or_step_count_if_mechanically_inflated"] > x["procedure_source_units"]
    assert x["procedure_inflation_prevented"] > 500


def test_faq_and_policy_are_not_sentence_inflated():
    x = load_json("knowledge_inflation_audit.json")
    assert x["faq_source_units"] < x["faq_fact_count"]
    assert x["policy_source_units"] < x["policy_fact_count"]
    assert x["faq_inflation_prevented"] > 0
    assert x["policy_inflation_prevented"] > 0


def test_table_context_is_preserved_for_attribute_facts():
    rows = load_jsonl("knowledge_atomic_fact_audit.jsonl")
    specs = [r for r in rows if r["relationship"] == "ATTRIBUTE_VALUE" and r["task_usability"] == "TASK_USABLE"]
    assert specs
    assert all("attribute_label_or_table_header" in r["required_local_context"] for r in specs)


def test_condition_action_relationship_preserves_condition_context():
    rows = load_jsonl("knowledge_atomic_fact_audit.jsonl")
    cond = [r for r in rows if r["relationship"] == "CONDITION_ACTION" and r["task_usability"] == "TASK_USABLE"]
    assert cond
    assert any("condition_clause" in r["required_local_context"] for r in cond)


def test_cross_product_duplicate_audit_finds_real_repeated_semantics():
    x = load_json("knowledge_cross_product_semantic_duplicates.json")
    assert x["fact_level_duplicate_groups"] >= 10
    assert x["fact_level_semantic_duplicate_excess"] > 0
    assert any("加油时务必关闭发动机" in r["example"] for r in x["fact_groups"])


def test_all_knowledge_sources_and_products_have_usable_units():
    s = load_json("knowledge_source_coverage.json")
    p = load_json("knowledge_product_coverage.json")
    assert s["total_sources"] == 22 and s["sources_with_usable_units"] == 22
    assert p["total_products"] == 20 and p["products_with_usable_units"] == 20


def test_previous_uncovered_sources_now_have_real_source_capacity():
    rows = load_json("knowledge_previous_uncovered_source_audit.json")
    assert {r["name"] for r in rows} == {"Air Purifier","Air Conditioner","Steam Cleaner","Bluetooth Laser Mouse","Support FAQ"}
    assert all(r["source_still_exists"] for r in rows)
    assert all(r["knowledge_source_units"] > 0 for r in rows)
    assert all(r["effective_units"] > 0 for r in rows)
    assert all(r["previous_formal_coverage"] is False for r in rows)


def test_capacity_funnel_compresses_atomic_facts_and_does_not_equal_question_count():
    f = load_json("knowledge_capacity_funnel.json")
    assert f["atomic_fact_candidates"] == 4913
    assert f["task_usable_facts"] < f["heuristic_usable"]
    assert f["knowledge_source_units"] < f["atomic_fact_candidates"]
    assert f["effective_source_units"] <= f["benchmark_usable_source_units"]


def test_capacity_blueprint_is_planning_only_and_not_candidate_output():
    b = load_json("knowledge_capacity_blueprint.json")
    assert 90 <= b["minimum_high_quality_candidate_capacity"] <= b["recommended_first_wave_capacity"] <= b["upper_reasonable_capacity"] <= 240
    assert b["confidence"] in {"HIGH","MEDIUM","LOW"}
    s = load_json("phase_g0_1_summary.json")
    assert s["new_queries"] == 0 and s["new_candidates"] == 0


def test_no_query_candidate_gold_or_annotation_packet_artifacts_are_created():
    names = {p.name for p in OUT.iterdir() if p.is_file()}
    assert not any("raw_candidates" in n or "source_validated" in n or "annotation_packet" in n or "gold_draft" in n for n in names)
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in OUT.iterdir() if p.is_file() and p.suffix in {".json",".jsonl"})
    assert '"candidate_query"' not in text


def test_stable_source_unit_and_group_ids_are_reproducible():
    a = audit_knowledge_source_space(ROOT)
    b = audit_knowledge_source_space(ROOT)
    assert [u.source_unit_id for u in a["source_units"]] == [u.source_unit_id for u in b["source_units"]]
    assert [g.group_id for g in a["coherent_groups"]] == [g.group_id for g in b["coherent_groups"]]


def test_runner_rerun_produces_same_semantic_manifest_hash(tmp_path):
    out = tmp_path / "g01"
    x = run_knowledge_source_audit(ROOT, ROOT/"artifacts/evaluation/dataset-expansion-d0", out)
    m1 = json.loads((out/"knowledge_source_space_manifest.json").read_text(encoding="utf-8"))
    x = run_knowledge_source_audit(ROOT, ROOT/"artifacts/evaluation/dataset-expansion-d0", out)
    m2 = json.loads((out/"knowledge_source_space_manifest.json").read_text(encoding="utf-8"))
    assert m1["knowledge_source_space_hash"] == m2["knowledge_source_space_hash"]
    assert m1["source_unit_count"] == m2["source_unit_count"]


def test_previous_frozen_assets_and_formal_counts_remain_expected():
    private=json.loads((ROOT/"artifacts/evaluation/dataset-expansion-d2/annotation_batch_manifest.json").read_text())
    mixed=json.loads((ROOT/"artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_annotation_batch_manifest_refrozen.json").read_text())
    f0=json.loads((ROOT/"artifacts/evaluation/dataset-expansion-f0-troubleshooting/phase_f0_summary.json").read_text())
    assert private["packet_count"] == 76
    assert mixed["packet_count"] == 58
    assert f0["source_validated"] == 66
    assert load_json("phase_g0_1_summary.json")["formal_canonical"] == 39


def test_phase_boundaries_are_explicit():
    s = load_json("phase_g0_1_summary.json")
    assert s["status"] == "COMPLETE"
    assert s["new_queries"] == 0
    assert s["new_candidates"] == 0
    assert s["new_formal_cases"] == 0
    assert s["annotation_runs"] == 0
    assert s["production_agent"] == "NOT RUN"
    assert s["d3r"] == "DEFERRED_BY_ENVIRONMENT"
