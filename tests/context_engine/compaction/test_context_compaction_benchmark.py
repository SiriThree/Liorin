from evals.context_compaction_benchmark import run_benchmark


def test_context_compaction_benchmark():
    result = run_benchmark()

    assert min(result.trajectory_steps) >= 100
    assert max(result.trajectory_steps) <= 200
    assert result.token_reduction_ratio > 0.70
    assert result.state_preservation_rate == 1.0
    assert result.summary_metadata_validity_rate == 1.0
    assert result.compaction_success_rate == 1.0
    assert result.original_history_retention_rate == 1.0
    assert result.summaries_generated == result.case_count
