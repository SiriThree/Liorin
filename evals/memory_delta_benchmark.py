"""Deterministic Phase 3.1 benchmark for repeated Working Memory updates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

# Import Context Runtime first to preserve the repository's existing module
# initialization order in dependency-light test environments.
from context_engine import MemoryLifecycleState
from memory.working import WorkingMemory, WorkingMemoryUpdater


@dataclass(frozen=True, slots=True)
class MemoryDeltaBenchmarkResult:
    repeated_update_calls: int
    legacy_estimated_lifecycle_records: int
    delta_lifecycle_records: int
    legacy_estimated_persisted_updates: int
    delta_persisted_updates: int
    delta_noop_count: int
    lifecycle_record_reduction_ratio: float
    final_real_change_persisted: bool
    final_real_change_lifecycle_records: int
    final_real_change_changed_fields: tuple[str, ...]
    methodology: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["final_real_change_changed_fields"] = list(
            self.final_real_change_changed_fields
        )
        return result


def run_benchmark(*, repeated_updates: int = 100) -> MemoryDeltaBenchmarkResult:
    if repeated_updates != 100:
        raise ValueError("Phase 3.1 benchmark is defined for exactly 100 repeated updates")

    start = datetime(2026, 8, 6, 5, 30, tzinfo=timezone.utc)
    state = {
        "task_goal": "排查 LF-900 冰箱 E17 异响",
        "current_intent": "troubleshooting",
        "confirmed_facts": ["product_model=LF-900", "error_code=E17"],
        "unresolved_slots": ["noise_timing"],
        "next_actions": ["继续安全排查"],
        "workflow_state": {"stage": "ready_for_supervisor"},
        "messages": [{"role": "user", "content": "继续排查"}],
    }
    updater = WorkingMemoryUpdater()
    seed = updater.update(
        state,
        actor="evals.memory_delta_benchmark",
        reason="seed benchmark working memory",
        session_id="phase3-1-delta-benchmark",
        now=start,
    )
    if not seed.persisted:
        raise RuntimeError("benchmark seed Working Memory was not persisted")

    memory: WorkingMemory = seed.memory
    lifecycle_records = seed.records_to_state()
    baseline_record_count = len(lifecycle_records)
    persisted_updates = 0
    noop_count = 0

    for index in range(repeated_updates):
        result = updater.update(
            state,
            actor="evals.memory_delta_benchmark",
            reason="repeat identical structured state",
            previous=memory,
            existing_records=lifecycle_records,
            session_id=memory.session_id,
            now=start + timedelta(seconds=index + 1),
        )
        if result.persisted:
            persisted_updates += 1
        if result.delta.is_noop:
            noop_count += 1
        lifecycle_records.extend(result.records_to_state())
        memory = result.memory

    repeated_record_count = len(lifecycle_records) - baseline_record_count

    changed_state = {
        **state,
        "confirmed_facts": [
            "product_model=LF-900",
            "error_code=E17",
            "noise_timing=night",
        ],
        "unresolved_slots": ["fan_status"],
    }
    changed = updater.update(
        changed_state,
        actor="evals.memory_delta_benchmark",
        reason="customer confirmed noise timing",
        previous=memory,
        existing_records=lifecycle_records,
        session_id=memory.session_id,
        now=start + timedelta(minutes=2),
    )
    if changed.persisted:
        assert changed.lifecycle_records[-1].memory.lifecycle_state is MemoryLifecycleState.PERSISTED

    legacy_records = repeated_updates * 3
    reduction = 0.0 if legacy_records == 0 else 1 - repeated_record_count / legacy_records
    return MemoryDeltaBenchmarkResult(
        repeated_update_calls=repeated_updates,
        legacy_estimated_lifecycle_records=legacy_records,
        delta_lifecycle_records=repeated_record_count,
        legacy_estimated_persisted_updates=repeated_updates,
        delta_persisted_updates=persisted_updates,
        delta_noop_count=noop_count,
        lifecycle_record_reduction_ratio=round(reduction, 6),
        final_real_change_persisted=changed.persisted,
        final_real_change_lifecycle_records=len(changed.lifecycle_records),
        final_real_change_changed_fields=changed.delta.changed_fields,
        methodology=(
            "Deterministic runtime benchmark. Legacy estimate uses the Phase 2 "
            "Candidate + Policy + Persist records for every updater call. Phase 3.1 "
            "counts records actually emitted after semantic fingerprint no-op detection."
        ),
    )


def main() -> None:
    result = run_benchmark()
    output = Path("evals/benchmark/reports/memory_delta_phase3_1_report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
