from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from evals.benchmark.expansion.troubleshooting_plan import build_candidates
from evals.benchmark.expansion.troubleshooting_recovery import recovery_action_matrix
from evals.benchmark.expansion.troubleshooting_source import build_troubleshooting_source_units
from evals.benchmark.expansion.troubleshooting_validation import validate_candidate, validate_candidates

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/"artifacts/evaluation/dataset-expansion-f0-troubleshooting"

def load_json(name): return json.loads((OUT/name).read_text(encoding="utf-8"))
def load_jsonl(name): return [json.loads(x) for x in (OUT/name).read_text(encoding="utf-8").splitlines() if x.strip()]


def test_source_units_are_section_grouped_and_real():
    units,report=build_troubleshooting_source_units(ROOT)
    assert len(units)==137
    assert report["benchmark_usable"]>=25
    usable=[u for u in units if u.benchmark_usable]
    assert report["benchmark_usable"]==len(usable)
    assert all(u.diagnostic_steps for u in usable)
    assert all("NON_TROUBLESHOOTING_CONTEXT" not in u.quality_flags for u in usable)
    assert all("PREVENTIVE_ONLY_CONTEXT" not in u.quality_flags for u in usable)
    assert report["with_multi_step"]>=20
    assert report["with_conditional_branch"]>=20
    assert report["with_safety_condition"]>=15
    assert report["with_escalation"]>=20


def test_source_unit_steps_preserve_source_fact_ids():
    units,_=build_troubleshooting_source_units(ROOT)
    for u in units:
        facts=set(u.manual_fact_ids)
        assert all((s.source_fact_id in facts) for s in u.diagnostic_steps if s.source_fact_id)


def test_raw_candidate_target_is_real_and_not_formal_gold():
    rows=load_jsonl("troubleshooting_raw_candidates.jsonl")
    assert len(rows)==100
    assert {r["status"] for r in rows}=={"CANDIDATE"}
    assert all("FORMAL_ELIGIBLE" not in json.dumps(r) and "RECOVERED" not in json.dumps(r) for r in rows)


def test_validated_scale_and_effective_diversity():
    s=load_json("phase_f0_summary.json")
    assert s["source_validated"]>=65
    assert s["effective_semantic_units"]>=55
    assert s["scenario_families"]>=50
    assert s["status"]=="COMPLETE"


def test_clarification_required_is_source_context_bound():
    rows=load_jsonl("troubleshooting_clarification_candidates.jsonl")
    assert len(rows)>=12
    for r in rows:
        assert r["expected_behavior_draft"]["response_type"]=="CLARIFICATION"
        assert r["hidden_required_context"]
        assert r["expected_behavior_draft"]["acceptable_clarification_slots"]==r["hidden_required_context"]
        assert r["expected_behavior_draft"]["forbidden_assumptions"]==["do_not_guess_missing_context"]


def test_false_clarification_controls_are_answer_cases():
    rows=load_jsonl("troubleshooting_false_clarification_controls.jsonl")
    assert len(rows)>=10
    assert all(r["expected_behavior_draft"]["response_type"]=="ANSWER" for r in rows)
    assert all(not r["hidden_required_context"] for r in rows)


def test_clarification_and_control_share_scenario_families():
    groups=load_json("troubleshooting_scenario_families.json")
    paired=[g for g in groups if g["clarification_variant_ids"] and g["full_context_candidate_ids"]]
    assert len(paired)>=10


def test_handoff_candidates_are_source_grounded():
    units={u.source_unit_id:u for u in build_troubleshooting_source_units(ROOT)[0]}
    rows=load_jsonl("troubleshooting_handoff_candidates.jsonl")
    assert len(rows)>=8
    for r in rows:
        assert units[r["source_unit_id"]].escalation_conditions
        assert r["expected_behavior_draft"]["response_type"]=="HANDOFF"
        assert r["expected_behavior_draft"]["handoff_reason"]


def test_recovery_is_candidate_only_never_observed():
    rows=load_jsonl("troubleshooting_source_validated.jsonl")
    assert sum("RECOVERY_ORIENTED" in r["behavior_labels"] for r in rows)>=15
    for r in rows:
        rec=r["recovery_eligibility"]
        assert rec["observed_first_pass_failure"] is False
        assert rec["formal_recovery_eligible"] is False
    s=load_json("phase_f0_summary.json")
    assert s["observed_production_first_pass_failures"]==0
    assert s["real_recovery_runs"]==0
    assert s["recovered_cases"]==0


def test_recovery_action_matrix_matches_current_supported_action_names():
    m=recovery_action_matrix()
    assert set(m["actions"])=={"CLARIFY","REWRITE","SUPPLEMENT","DECOMPOSE","RELAX_FILTERS","HANDOFF"}
    assert m["triggers"]["MISSING_REQUIRED_CONTEXT"]["CLARIFY"]=="ALLOWED"
    assert m["triggers"]["MISSING_REQUIRED_CONTEXT"]["SUPPLEMENT"]=="FORBIDDEN"
    assert m["triggers"]["CONFLICTING_EVIDENCE"]["HANDOFF"]=="ALLOWED"


def test_mixed_private_leakage_guard_fails_closed():
    units,_=build_troubleshooting_source_units(ROOT); um={u.source_unit_id:u for u in units}
    c=next(c for c in build_candidates(units) if c.product_id and c.required_steps)
    bad=replace(c,candidate_query=c.candidate_query+" <TICKET_REF:abc123>")
    ok,reasons=validate_candidate(bad,um[bad.source_unit_id],source_unit_map=um)
    assert not ok and "MIXED_OR_PRIVATE_SOURCE_REQUIRED" in reasons


def test_answer_leakage_guard_fails_closed():
    units,_=build_troubleshooting_source_units(ROOT); um={u.source_unit_id:u for u in units}
    chosen=None
    for c in build_candidates(units):
        if not c.required_steps:
            continue
        u=um[c.source_unit_id]
        step_by_id={s.step_id:s for s in u.diagnostic_steps}
        for sid in c.required_steps:
            step=step_by_id.get(sid)
            if step and len("".join(step.action.split()))>=12:
                chosen=(c,u,step.action); break
        if chosen:
            break
    assert chosen is not None
    c,u,action=chosen
    bad=replace(c,candidate_query=c.candidate_query+" "+action)
    ok,reasons=validate_candidate(bad,u,source_unit_map=um)
    assert not ok and "ANSWER_LEAKAGE" in reasons


def test_existing_formal_and_mixed_collisions_are_excluded_from_validated():
    report=load_json("troubleshooting_existing_collision_report.json")
    valid={x["candidate_id"] for x in load_jsonl("troubleshooting_source_validated.jsonl")}
    collided=set(report["formal_section_collisions"])|set(report["mixed_gold_fact_collisions"])
    assert collided
    assert not (valid & collided)


def test_no_exact_or_normalized_query_duplicates():
    d=load_json("troubleshooting_dedup_report.json")
    assert d["exact_query_duplicates"]==0
    assert d["normalized_query_duplicates"]==0


def test_reproducible_source_units_and_candidate_ids():
    u1,_=build_troubleshooting_source_units(ROOT); u2,_=build_troubleshooting_source_units(ROOT)
    assert [u.source_unit_id for u in u1]==[u.source_unit_id for u in u2]
    assert [c.candidate_id for c in build_candidates(u1)]==[c.candidate_id for c in build_candidates(u2)]


def test_previous_frozen_batches_are_unchanged_counts():
    private=json.loads((ROOT/"artifacts/evaluation/dataset-expansion-d2/annotation_batch_manifest.json").read_text())
    mixed=json.loads((ROOT/"artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_annotation_batch_manifest_refrozen.json").read_text())
    assert private["packet_count"]==76
    assert mixed["packet_count"]==58


def test_formal_canonical_remains_39():
    total=0
    for name in ("dev_v7_3_canonical_v1.json","validation_v7_3_canonical_v1.json"):
        x=json.loads((ROOT/"evals/benchmark/data/canonical"/name).read_text())
        total+=len(x.get("samples") if isinstance(x,dict) else x)
    assert total==39


def test_phase_boundaries_are_explicit():
    s=load_json("phase_f0_summary.json")
    assert s["new_formal_cases"]==0
    assert s["production_agent"]=="NOT RUN"
    assert s["annotation_runs"]==0
    assert s["d3r"]=="DEFERRED_BY_ENVIRONMENT"
