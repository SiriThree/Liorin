from __future__ import annotations

import json

from eval_platform import (
    CriterionStatus,
    JudgeConfig,
    JudgeRequest,
    JudgeRuntime,
    SuccessCriterion,
)


class SequenceProvider:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def invoke(self, request, config):
        self.calls += 1
        value = self.results.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def config(retries=2):
    return JudgeConfig(
        judge_name="phase2-test-judge",
        provider="stub",
        model="stub-model",
        temperature=0.0,
        max_tokens=500,
        timeout=1,
        max_retries=retries,
        prompt_version="answer_correctness_v1",
    )


def fact_request():
    return JudgeRequest.build(
        case_id="judge-case",
        criterion=SuccessCriterion.CRITICAL_FACTS_CORRECT,
        prompt_version="answer_correctness_v1",
        structured_input={
            "user_query": "q",
            "gold_facts": [{"fact_id":"f1","description":"fact"}],
            "assistant_response": "a",
        },
    )


def test_valid_structured_fail_is_not_retried_until_pass():
    provider = SequenceProvider(
        {"status":"FAIL","fact_results":[{"fact_id":"f1","status":"FAIL","reason":"missing"}],"unsupported_critical_claims":[],"rationale":"missing fact"},
        {"status":"PASS","fact_results":[{"fact_id":"f1","status":"PASS","reason":"ok"}],"unsupported_critical_claims":[],"rationale":"ok"},
    )
    runtime = JudgeRuntime(config(), provider)
    response, record = runtime.evaluate(fact_request())
    assert provider.calls == 1
    assert response is not None and response.status is CriterionStatus.FAIL
    assert record.attempt_count == 1
    assert record.error is None
    assert record.prompt_version == "answer_correctness_v1"
    assert record.raw_response is not None


def test_invalid_structured_output_retries_only_as_infrastructure_failure():
    provider = SequenceProvider(
        "not-json",
        {"status":"PASS","fact_results":[{"fact_id":"f1","status":"PASS","reason":"present"}],"unsupported_critical_claims":[],"rationale":"correct"},
    )
    runtime = JudgeRuntime(config(retries=2), provider)
    response, record = runtime.evaluate(fact_request())
    assert provider.calls == 2
    assert response is not None and response.status is CriterionStatus.PASS
    assert record.attempt_count == 2
    assert record.error is None


def test_timeout_provider_error_all_retries_failed_is_recorded_not_passed():
    provider = SequenceProvider(TimeoutError("timeout"), RuntimeError("provider down"))
    runtime = JudgeRuntime(config(retries=1), provider)
    response, record = runtime.evaluate(fact_request())
    assert response is None
    assert provider.calls == 2
    assert record.attempt_count == 2
    assert "provider down" in (record.error or "")
    assert record.structured_result is None


def test_fact_result_ids_must_match_requested_gold():
    provider = SequenceProvider(
        {"status":"PASS","fact_results":[{"fact_id":"wrong","status":"PASS","reason":"x"}],"rationale":"bad schema"},
    )
    runtime = JudgeRuntime(config(retries=0), provider)
    response, record = runtime.evaluate(fact_request())
    assert response is None
    assert "fact_results IDs" in (record.error or "")


def test_request_hash_is_stable_for_same_structured_input():
    a = fact_request()
    b = fact_request()
    assert a.request_hash == b.request_hash


def test_judge_run_metadata_records_versions_and_errors():
    provider = SequenceProvider(
        {"status":"PASS","fact_results":[{"fact_id":"f1","status":"PASS","reason":"present"}],"unsupported_critical_claims":[],"rationale":"ok"},
    )
    runtime = JudgeRuntime(config(retries=0), provider)
    runtime.evaluate(fact_request())
    metadata = runtime.run_metadata()
    assert metadata.records == 1
    assert metadata.errors == 0
    assert metadata.prompt_versions == ("answer_correctness_v1",)
    assert metadata.schema_version == "1.0"
