from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.annotation_pipeline.backends import BackendError, JSONBackend
from evals.annotation_pipeline.config import AgentConfig
from evals.benchmark.expansion.d3_agreement import analyze_agreement, classify_pair
from evals.benchmark.expansion.d3_annotation import (
    PROMPT_SCHEMA_VERSION, PROMPT_VERSION, PrivateGoldAnnotationAgent,
    PrivateGoldAnnotationDecision, build_annotation_request,
)
from evals.benchmark.expansion.d3_runner import run_private_dual_annotation, validate_batch_integrity

ROOT = Path(__file__).resolve().parents[2]
D2 = ROOT / "artifacts/evaluation/dataset-expansion-d2"


def _packets():
    return [json.loads(x) for x in (D2 / "private_business_annotation_packets.jsonl").read_text().splitlines() if x.strip()]


def _config(agent_id="a", provider="p", model="m"):
    return AgentConfig(
        agent_id=agent_id, role="annotator", backend="openai_compatible", provider=provider,
        model=model, base_url="https://example.invalid/v1", api_key_env="NEVER_SET_D3_TEST_KEY",
        prompt_profile="private_gold_review_v1", temperature=0.0, max_tokens=2000, timeout_seconds=1,
    )


def _decision(packet, *, agent_id="a", provider="p", model="m", run_id="run-a", overall="ACCEPT"):
    edits=[]
    if overall == "ACCEPT_WITH_EDITS":
        edits=[{"target":"gold_fact.x","operation":"MAKE_OPTIONAL","old_value":True,"proposed_value":False,"reason":"query does not require it"}]
    return {
        "schema_version": PROMPT_SCHEMA_VERSION,
        "candidate_id": packet["candidate_id"], "packet_hash": packet["annotation_packet_hash"],
        "annotator_id": agent_id, "annotation_run_id": run_id, "overall_decision": overall,
        "query_quality":"PASS", "answerability":"PASS", "response_type_correct":"PASS",
        "gold_fact_correct":"PASS", "gold_fact_complete":"PASS", "gold_fact_minimal":"PASS",
        "gold_evidence_correct":"PASS", "task_contract_correct":"PASS", "source_support":"PASS",
        "ambiguity":"NONE", "privacy_safe":"PASS",
        "gold_fact_reviews":[{
            "fact_id":f["fact_id"], "source_supported":"PASS", "criticality_correct":"PASS",
            "value_correct":"PASS", "comparison_mode_correct":"PASS", "disposition":"KEEP",
        } for f in packet["gold_draft"]["gold_facts_draft"]],
        "gold_evidence_reviews":[{
            "evidence_id":e["evidence_id"], "entity_correct":"PASS", "field_correct":"PASS",
            "required_correct":"PASS", "supporting_relation_correct":"PASS",
        } for e in packet["gold_draft"]["gold_evidence_draft"]],
        "task_contract_review":{
            "required_criteria_correct":"PASS", "required_agents_correct":"PASS", "required_tools_correct":"PASS",
            "authorization_criteria_correct":"PASS", "grounding_requirements_correct":"PASS",
        },
        "suggested_edits":edits, "risk_flags":[], "rationale":"Source snapshot supports the minimal field-level Gold draft.",
        "confidence":"HIGH",
        "annotator_metadata":{
            "annotator_id":agent_id, "provider":provider, "model":model, "packet_hash":packet["annotation_packet_hash"],
            "prompt_version":PROMPT_VERSION, "structured_output_version":PROMPT_SCHEMA_VERSION,
        },
    }


class SequenceBackend(JSONBackend):
    def __init__(self, config, values):
        super().__init__(config); self.values=list(values)
    def complete_json(self, system, user, schema):
        self.last_http_attempt_count=1
        value=self.values.pop(0)
        if isinstance(value, Exception): raise value
        return value, json.dumps(value)


def test_batch_integrity_is_exactly_76_and_excludes_all_8_precheck():
    result=validate_batch_integrity(D2)
    assert result["packet_count"] == 76
    assert result["precheck_count"] == 8
    assert result["batch_id"] == "PBQ-D2-C3B3AA7C6549"
    packet_ids={p["candidate_id"] for p in result["packets"]}
    precheck_ids={p["candidate_id"] for p in result["precheck"]}
    assert not packet_ids & precheck_ids


def test_batch_integrity_fails_closed_on_wrong_packet_hash(tmp_path):
    import shutil
    shutil.copytree(D2, tmp_path / "d2")
    path=tmp_path/"d2"/"private_business_annotation_packets.jsonl"
    rows=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    rows[0]["candidate_query"] += " changed"
    path.write_text("".join(json.dumps(x)+"\n" for x in rows))
    with pytest.raises(ValueError, match="packet hash mismatch"):
        validate_batch_integrity(tmp_path/"d2")


def test_annotation_prompt_is_neutral_and_source_precedes_gold():
    p=_packets()[0]
    system,user,_=build_annotation_request(p, annotator_id="a", provider="p", model="m", run_id="r")
    assert "不是回答用户问题" in system
    assert "另一个 Annotator" in system
    assert user.index('"source_snapshot"') < user.index('"gold_draft_to_review"')
    assert "Production Prediction" not in user
    assert "READY_FOR_DUAL_ANNOTATION" not in user


def test_annotation_decision_accept_requires_all_critical_dimensions_pass():
    p=_packets()[0]
    good=_decision(p)
    PrivateGoldAnnotationDecision.model_validate(good)
    bad=dict(good); bad["source_support"]="FAIL"
    with pytest.raises(Exception): PrivateGoldAnnotationDecision.model_validate(bad)


def test_annotation_decision_invalid_enum_rejected():
    p=_packets()[0]; bad=_decision(p); bad["overall_decision"]="MAYBE"
    with pytest.raises(Exception): PrivateGoldAnnotationDecision.model_validate(bad)


def test_agent_retries_parse_validation_but_not_valid_reject():
    p=_packets()[0]; cfg=_config()
    valid=_decision(p)
    backend=SequenceBackend(cfg,[{"candidate_id":"wrong"}, valid])
    result=PrivateGoldAnnotationAgent(cfg, backend, max_validation_attempts=3).annotate(p,run_id="run-a")
    assert result.status == "VALID"
    reject=_decision(p,overall="REJECT")
    # REJECT can carry PASS dimensions; it is a valid semantic result and must not be retried.
    backend2=SequenceBackend(cfg,[reject])
    result2=PrivateGoldAnnotationAgent(cfg,backend2).annotate(p,run_id="run-a")
    assert result2.status == "VALID"
    assert result2.decision["overall_decision"] == "REJECT"
    assert not backend2.values


def test_backend_error_is_infra_error_not_reject():
    p=_packets()[0]; cfg=_config(); backend=SequenceBackend(cfg,[BackendError("timeout")])
    result=PrivateGoldAnnotationAgent(cfg,backend).annotate(p,run_id="run-a")
    assert result.status == "ANNOTATOR_INFRA_ERROR"
    assert result.decision is None


def test_pair_exact_agreement_and_identical_edits():
    p=_packets()[0]
    a=_decision(p,overall="ACCEPT_WITH_EDITS"); b=json.loads(json.dumps(a))
    result=classify_pair(a,b)
    assert result["exact_case_agreement"]
    assert result["category"] == "AGREED_ACCEPT_WITH_IDENTICAL_EDITS"


def test_pair_accept_vs_reject_is_major_high_disagreement():
    p=_packets()[0]
    a=_decision(p); b=_decision(p,overall="REJECT")
    result=classify_pair(a,b)
    assert result["category"] == "MAJOR_DISAGREEMENT"
    assert result["severity"] == "HIGH"


def test_same_overall_but_dimension_difference_not_exact():
    p=_packets()[0]
    a=_decision(p,overall="REJECT"); b=_decision(p,overall="REJECT")
    b["gold_fact_minimal"]="UNCERTAIN"
    result=classify_pair(a,b)
    assert result["overall_same"]
    assert not result["exact_case_agreement"]
    assert "gold_fact_minimal" in result["dimension_disagreements"]


def test_agreement_denominator_only_both_valid_same_packet():
    packets=_packets()[:2]
    a=[]; b=[]
    for p in packets:
        a.append({"candidate_id":p["candidate_id"],"packet_hash":p["annotation_packet_hash"],"status":"VALID","decision":_decision(p,agent_id="a",run_id="ra")})
    p=packets[0]
    b.append({"candidate_id":p["candidate_id"],"packet_hash":p["annotation_packet_hash"],"status":"VALID","decision":_decision(p,agent_id="b",run_id="rb")})
    result=analyze_agreement(packets,a,b)
    assert result["summary"]["valid_pairs"] == 1
    assert result["summary"]["overall_decision_agreement"]["denominator"] == 1


def test_blocked_runner_never_creates_fake_agreement(tmp_path, monkeypatch):
    cfg=tmp_path/"cfg.yaml"
    cfg.write_text('''annotator_a:\n  agent_id: a\n  role: annotator\n  backend: openai_compatible\n  provider: p1\n  model: m1\n  base_url: https://example.invalid/v1\n  api_key_env: D3_A_MISSING\n  prompt_profile: private_gold_review_v1\nannotator_b:\n  agent_id: b\n  role: annotator\n  backend: openai_compatible\n  provider: p2\n  model: m2\n  base_url: https://example.invalid/v1\n  api_key_env: D3_B_MISSING\n  prompt_profile: private_gold_review_v1\n''')
    monkeypatch.delenv("D3_A_MISSING",raising=False); monkeypatch.delenv("D3_B_MISSING",raising=False)
    out=tmp_path/"out"
    summary=run_private_dual_annotation(ROOT,D2,out,cfg)
    assert summary["status"] == "PARTIAL"
    assert summary["annotation_execution"] == "BLOCKED"
    agreement=json.loads((out/"annotation_agreement_summary.json").read_text())
    assert agreement["status"] == "NOT RUN"
    assert agreement["overall_decision_agreement"]["denominator"] == 0
    assert (out/"annotator_a_decisions.jsonl").read_text() == ""
    assert (out/"annotator_b_decisions.jsonl").read_text() == ""


def test_formal_canonical_still_39():
    canonical=ROOT/"evals/benchmark/data/canonical"
    total=sum(len(json.loads((canonical/name).read_text())) for name in ("dev_v7_3_canonical_v1.json","validation_v7_3_canonical_v1.json"))
    assert total == 39


def test_d3_does_not_require_or_reference_production_predictions():
    p=_packets()[0]
    _,user,_=build_annotation_request(p,annotator_id="a",provider="p",model="m",run_id="r")
    lowered=user.lower()
    assert "agent trace" not in lowered
    assert "agent answer" not in lowered
    assert "judge answer" not in lowered
    assert "production prediction" not in lowered
