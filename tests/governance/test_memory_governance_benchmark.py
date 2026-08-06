from evals.memory_governance_benchmark import run_benchmark


def test_memory_governance_benchmark():
    report = run_benchmark()
    assert report["tenants"] == 100
    assert report["facts_seeded"] == 1000
    assert report["isolation_accuracy"] == 1.0
    assert report["retrieval_precision"] == 1.0
    assert report["retrieval_recall"] == 1.0
    assert report["wrong_injection_rate"] == 0.0
    assert report["stale_memory_rate"] == 0.0
    assert report["forgetting_accuracy"] == 1.0
    assert report["deletion_correctness"] == 1.0
    assert report["expiration_correctness"] == 1.0
    assert report["policy_accuracy"] == 1.0
