from evals.artifact_context_benchmark import run_benchmark


def test_artifact_context_benchmark():
    result = run_benchmark(result_count=100, payload_repeat=100)

    assert result["tool_result_count"] == 100
    assert result["token_reduction_ratio"] > 0.95
    assert result["artifact_retrieval_success_rate"] == 1.0
    assert result["reference_correct_rate"] == 1.0
    assert result["artifact_count"] == 100
    assert result["original_history_preserved"] is True
    assert result["artifact_payload_in_context"] is False
