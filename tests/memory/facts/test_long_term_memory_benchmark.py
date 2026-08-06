from evals.long_term_memory_benchmark import run_benchmark


def test_long_term_memory_benchmark():
    result = run_benchmark(case_count=30)
    assert result.session_a_persisted_fact_count == 90
    assert result.after_memory_precision == 1.0
    assert result.after_memory_recall == 1.0
    assert result.after_wrong_injection_rate == 0.0
    assert result.cross_identity_injection_count == 0
    assert result.expired_injection_count == 0
    assert result.average_context_token_increase > 0
