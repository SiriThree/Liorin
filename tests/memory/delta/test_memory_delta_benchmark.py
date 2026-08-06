from evals.memory_delta_benchmark import run_benchmark


def test_memory_delta_benchmark_eliminates_repeated_lifecycle_noise():
    result = run_benchmark()

    assert result.repeated_update_calls == 100
    assert result.legacy_estimated_lifecycle_records == 300
    assert result.delta_lifecycle_records == 0
    assert result.delta_persisted_updates == 0
    assert result.delta_noop_count == 100
    assert result.lifecycle_record_reduction_ratio == 1.0
    assert result.final_real_change_persisted is True
    assert result.final_real_change_lifecycle_records == 3
    assert "confirmed_facts" in result.final_real_change_changed_fields
