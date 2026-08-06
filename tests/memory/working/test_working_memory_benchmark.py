from evals.working_memory_benchmark import run_benchmark


def test_phase2_working_memory_benchmark_is_bounded_and_lossless():
    result = run_benchmark()
    assert result.turns == 50
    assert result.after_final_prompt_tokens <= result.context_budget_tokens
    assert result.after_cumulative_prompt_tokens < result.before_cumulative_prompt_tokens
    assert result.cumulative_token_reduction_ratio > 0.80
    assert result.after_task_completion_rate == 1.0
    assert result.after_information_loss_count == 0
