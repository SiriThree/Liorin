from evals.production_benchmark import run_benchmark


def test_production_benchmark_1000_requests():
    report = run_benchmark()
    assert report["scope"]["requests"] == 1000
    results = report["results"]
    assert results["request_success_rate"] == 1.0
    assert results["memory_hit_rate"] >= 0.98
    assert results["artifact_retrieval_success_rate"] == 1.0
    assert results["failure_recovery_rate"] == 1.0
    assert results["token_reduction_rate"] > 0.80
    assert results["artifact_saved_tokens"] > 0
    assert results["backend_failure_count"] == results["injected_backend_failures"]
    assert results["latency_ms_p95"] > 0
