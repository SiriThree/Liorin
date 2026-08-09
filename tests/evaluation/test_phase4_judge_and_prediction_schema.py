from __future__ import annotations

from eval_platform.contracts import CriterionStatus
from eval_platform.judge import JudgeConfig, JudgeRequest, JudgeRuntime, PROMPTS
from eval_platform.production_adapter import TraceAdapter


class Stub:
    def invoke(self,request,config):
        return {"relevance_status":"HARMFUL","rationale":"stale wrong-entity history"}


def test_context_relevance_prompt_is_versioned_structured_judge_contract():
    assert "context_relevance_v1" in PROMPTS
    runtime=JudgeRuntime(JudgeConfig("ctx","stub","stub",prompt_version="context_relevance_v1"),provider=Stub())
    request=JudgeRequest.build(case_id="c",criterion="CONTEXT_RELEVANCE",prompt_version="context_relevance_v1",structured_input={"task":"FR-200","context_item":"WM-100"})
    response,record=runtime.evaluate(request)
    assert response is not None and response.relevance_status == "HARMFUL"
    assert response.status is CriterionStatus.PASS
    assert record.prompt_version == "context_relevance_v1"


def test_trace_adapter_projects_context_and_model_token_observability():
    trace={"request_id":"trace","events":[
        {"event_type":"CONTEXT_ASSEMBLED","attributes":{"context_build_id":"ctx1","strategy":{"strategy_id":"FULL_HISTORY"},"context_item_refs":[{"context_item_id":"i","type":"USER_MESSAGE","source":"messages_state","source_ref":"msg1","selected":True,"token_count":20}],"token_count":20,"token_count_source":"HEURISTIC_ESTIMATE"}},
        {"event_type":"MODEL_CALL","attributes":{"model_call_id":"m1","input_tokens":22,"completion_tokens":3,"token_count_source":"PROVIDER_ACTUAL","context_strategy":{"strategy_id":"FULL_HISTORY"}}},
    ]}
    facts=TraceAdapter().adapt(trace)
    assert facts["prediction_schema_version"] == "5.0"
    assert facts["context_assemblies"][0]["context_build_id"] == "ctx1"
    assert facts["model_input_tokens_total"] == 22
    assert facts["model_input_token_sources"] == ["PROVIDER_ACTUAL"]


def test_phase4_context_relevance_calibration_fixture_is_explicitly_non_formal():
    import json
    from pathlib import Path

    payload = json.loads(Path('evals/benchmark/data/calibration/phase4_context_relevance_calibration_v1.json').read_text(encoding='utf-8'))
    assert payload['prompt_version'] == 'context_relevance_v1'
    assert payload['provenance'] == 'carefully_constructed_fixture'
    assert payload['human_reviewed'] is False
    assert {row['reference'] for row in payload['cases']} == {'REQUIRED', 'HELPFUL', 'IRRELEVANT', 'HARMFUL'}
