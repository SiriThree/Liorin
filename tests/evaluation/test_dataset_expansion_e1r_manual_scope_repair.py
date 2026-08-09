from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from evals.benchmark.expansion.e1r_runner import run_manual_scope_repair
from evals.benchmark.expansion.manual_scope_validation import validate_scope_repair

ROOT = Path(__file__).resolve().parents[2]
E0 = ROOT / "artifacts/evaluation/dataset-expansion-e0-mixed"
E1 = ROOT / "artifacts/evaluation/dataset-expansion-e1-mixed-gold"
E1R = ROOT / "artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _by_id(rows):
    return {x["candidate_id"]: x for x in rows}


def test_input_gate_is_exactly_16_policy_plus_42_manual_precheck():
    summary = _json(E1R / "phase_e1r_summary.json")
    assert summary["policy_ready_frozen"] == 16
    assert summary["manual_precheck_input"] == 42
    rows = _jsonl(E1R / "manual_scope_repair_input.jsonl")
    assert len(rows) == 42
    assert {x["mixed_family_id"] for x in rows} == {
        "MIXED_ORDER_PRODUCT_MANUAL", "MIXED_TICKET_TROUBLESHOOTING", "MIXED_WARRANTY_PRODUCT_MANUAL"
    }


def test_e0_rejected_return_policy_never_enters_repair():
    rejected = {x["candidate_id"] for x in _jsonl(E0 / "mixed_rejected.jsonl")}
    repair = {x["candidate_id"] for x in _jsonl(E1R / "manual_scope_repair_input.jsonl")}
    assert len(rejected) == 10
    assert rejected.isdisjoint(repair)


def test_all_16_policy_units_are_byte_semantically_frozen():
    manifest = _json(E1R / "manual_scope_repair_manifest.json")
    assert manifest["policy_freeze_verified"] is True
    assert len(manifest["policy_freeze_rows"]) == 16
    assert all(x["after"]["unchanged"] for x in manifest["policy_freeze_rows"])
    assert manifest["input_e1_batch_id"] == "MIX-E1-1FECB833D0B9"


def test_all_42_manual_scope_units_have_lineage_and_source_fact_is_unchanged():
    inputs = _by_id(_jsonl(E1R / "manual_scope_repair_input.jsonl"))
    results = _by_id(_jsonl(E1R / "manual_scope_repair_results.jsonl"))
    assert set(inputs) == set(results)
    for cid, row in results.items():
        assert row["manual_fact_scope"]["selected_fact_id"] == inputs[cid]["selected_fact_id"]
        assert row["source_preserved"] is True
        assert row["repair_id"].startswith("MIX-REPAIR-")
        assert row["original_query"] != row["repaired_query"]


def test_source_preservation_zero_changes():
    summary = _json(E1R / "phase_e1r_summary.json")
    assert summary["source_changes"] == {
        "entity": 0, "product_relation": 0, "manual": 0, "section": 0, "selected_source_fact": 0
    }


def test_broad_scope_is_eliminated_and_gold_is_complete_minimal():
    comp = _json(E1R / "manual_scope_gold_completeness.json")
    mini = _json(E1R / "manual_scope_gold_minimality.json")
    assert comp["before_issue_count"] == 42 and comp["after_issue_count"] == 0
    assert mini["before_issue_count"] == 42 and mini["after_issue_count"] == 0
    assert all(x["repair_status"] == "REPAIRED_READY" for x in _jsonl(E1R / "manual_scope_repair_results.jsonl"))


def test_minimal_coherent_groups_never_expand_to_whole_section():
    mini = _json(E1R / "manual_scope_gold_minimality.json")
    assert mini["minimal_fact_group_cases"] == 12
    assert mini["max_fact_group_size"] == 2
    assert mini["average_fact_group_size"] == 2


def test_fragment_fact_uses_minimal_context_group_not_section_dump():
    rows = _jsonl(E1R / "manual_fact_scope_audit.jsonl")
    vr = next(x for x in rows if x["selected_fact_id"] == "af:4df72d7f8b0bbd0c")
    assert vr["fact_granularity"] == "FRAGMENT_ONLY"
    assert vr["repair_type"] == "MINIMAL_FACT_GROUP"
    assert vr["coherent_group_fact_ids"] == ["af:03dd5fba6e61d2f3"]
    assert vr["section_usable_fact_count"] == 4


def test_conditional_fact_query_preserves_condition_without_answer_leakage():
    rows = _jsonl(E1R / "manual_scope_repair_results.jsonl")
    bike = next(x for x in rows if x["manual_fact_scope"]["selected_fact_id"] == "af:871807f11ccf667a")
    assert "腿伸得太直" in bike["repaired_query"]
    assert "座椅调低" not in bike["repaired_query"]
    assert bike["query_leakage_clean"] is True


def test_mixed_necessity_survives_all_repairs():
    report = _json(E1R / "manual_scope_mixed_necessity.json")
    assert report == {"structured_required": 42, "document_required": 42, "repair_invalidated_mixed_cases": 0}


def test_query_leakage_is_zero_and_product_identity_remains_hidden():
    report = _json(E1R / "manual_scope_query_leakage.json")
    assert report["clean"] == 42
    assert report["leaked"] == 0
    assert report["product_identity"] == 0
    text = (E1R / "manual_scope_repair_proposals.jsonl").read_text(encoding="utf-8")
    assert "LIO-PROD-" not in "\n".join(json.dumps(x.get("repaired_query"), ensure_ascii=False) for x in _jsonl(E1R / "manual_scope_repair_proposals.jsonl"))


def test_validator_flags_product_identity_injected_into_repaired_query():
    candidates = _by_id(_jsonl(E0 / "mixed_source_validated.jsonl"))
    result = next(x for x in _jsonl(E1R / "manual_scope_repair_results.jsonl") if x["mixed_family_id"] == "MIXED_ORDER_PRODUCT_MANUAL")
    c = candidates[result["candidate_id"]]
    repaired = copy.deepcopy(c)
    repaired["candidate_query"] = result["repaired_query"] + f" 产品型号是 {c['product_ref']}。"
    facts = {}
    for line in (ROOT / "artifacts/evaluation/dataset-expansion-d0/atomic_fact_inventory.jsonl").read_text(encoding="utf-8").splitlines():
        x = json.loads(line); facts[x["fact_id"]] = x
    v = validate_scope_repair(ROOT, c, repaired, result["manual_fact_scope"], facts_index=facts)
    assert "PRODUCT_ROUTING_FACT_LEAKED" in v["issues"]
    assert "MIXED_NECESSITY_STRUCTURED_FAILED" in v["issues"]


def test_existing_formal_gold_collision_rechecked_and_zero():
    report = _json(E1R / "manual_scope_existing_formal_collision.json")
    assert report["existing_formal_mixed_count"] == 10
    assert report["exact_gold_collision_count"] == 0


def test_effective_diversity_is_recomputed_not_inflated_by_42_repairs():
    report = _json(E1R / "manual_scope_effective_diversity.json")
    assert report["e0_effective_before"] == 48
    assert report["manual_repaired_effective_units"] == 42
    assert report["final_effective_gold_units"] == 48
    assert report["final_ready_count"] == 58
    assert report["final_ready_families"] == 5


def test_refrozen_gold_has_58_ready_and_no_new_formal_flags():
    drafts = _jsonl(E1R / "mixed_gold_drafts_refrozen.jsonl")
    assert len(drafts) == 58
    assert all(d["annotation_status"] == "READY_FOR_DUAL_ANNOTATION" for d in drafts)
    assert all(d["human_reviewed"] is False and d["formal_eligible"] is False for d in drafts)


def test_refrozen_packet_batch_has_policy_plus_manual_and_old_batch_is_unchanged():
    packets = _jsonl(E1R / "mixed_annotation_packets_refrozen.jsonl")
    batch = _json(E1R / "mixed_annotation_batch_manifest_refrozen.json")
    old = _json(E1 / "mixed_annotation_batch_manifest.json")
    assert len(packets) == 58
    assert batch["packet_count"] == 58
    assert batch["batch_id"].startswith("MIX-E1R-")
    assert old["batch_id"] == "MIX-E1-1FECB833D0B9"
    assert old["batch_hash"] == "1fecb833d0b96ce695343df4543c27b6a50e98657c41ecc95a8068c3088d2861"


def test_refrozen_packets_do_not_contain_whole_manual_sections_or_runtime_outputs():
    packets = _jsonl(E1R / "mixed_annotation_packets_refrozen.jsonl")
    assert len({x["annotation_packet_hash"] for x in packets}) == 58
    for p in packets:
        text = json.dumps(p, ensure_ascii=False)
        assert "section_text" not in text
        assert "Production Prediction" in p["excluded_information"]
        assert "Agent Trace" in p["excluded_information"]
        assert "Judge Result" in p["excluded_information"]


def test_repair_reproducibility_preserves_queries_packets_and_batch_hash(tmp_path: Path):
    out1 = tmp_path / "a"
    out2 = tmp_path / "b"
    s1 = run_manual_scope_repair(ROOT, E1, out1)
    s2 = run_manual_scope_repair(ROOT, E1, out2)
    assert s1["new_annotation_batch_hash"] == s2["new_annotation_batch_hash"]
    assert (out1 / "manual_scope_repair_proposals.jsonl").read_bytes() == (out2 / "manual_scope_repair_proposals.jsonl").read_bytes()
    assert (out1 / "mixed_annotation_packets_refrozen.jsonl").read_bytes() == (out2 / "mixed_annotation_packets_refrozen.jsonl").read_bytes()


def test_existing_formal_dataset_still_39_and_runs_remain_zero():
    summary = _json(E1R / "phase_e1r_summary.json")
    assert summary["existing_formal_canonical_cases"] == 39
    assert summary["new_formal_cases"] == 0
    assert summary["annotation_runs"] == 0
    assert summary["production_agent_execution"] == "NOT RUN"
    assert summary["d3r_status"] == "DEFERRED_BY_ENVIRONMENT"


def test_public_e1r_artifacts_do_not_leak_raw_private_fixture_ids_or_emails():
    for path in E1R.iterdir():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "ORD-2026-" not in text
        assert "TCK-2026-" not in text
        assert "WAR-2026-" not in text
        assert "CUST-" not in text
        assert "@liorin" not in text.lower()
