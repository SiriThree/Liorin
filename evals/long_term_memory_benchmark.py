"""Deterministic Phase 5 multi-session long-term MemoryFact benchmark."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from context_engine import ContextBuilder, ContextRuntime
from identity import IdentityContext
from memory.facts import InMemoryMemoryFactStore, LongTermMemoryRuntime


@dataclass(frozen=True, slots=True)
class LongTermMemoryBenchmarkResult:
    case_count: int
    session_a_persisted_fact_count: int
    session_b_expected_fact_count: int
    before_memory_precision: float
    before_memory_recall: float
    before_wrong_injection_rate: float
    after_memory_precision: float
    after_memory_recall: float
    after_wrong_injection_rate: float
    cross_identity_injection_count: int
    cumulative_context_token_increase: int
    average_context_token_increase: float
    lifecycle_created_updated_count: int
    lifecycle_retrieved_count: int
    expired_injection_count: int
    methodology: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _identity(user_index: int, session: str) -> IdentityContext:
    return IdentityContext(
        tenant_id="tenant-memory-benchmark",
        user_id=f"user-{user_index}",
        conversation_id=f"conversation-{user_index}-{session}",
        thread_id=f"thread-{user_index}-{session}",
        session_id=f"session-{user_index}-{session}",
    )


def run_benchmark(*, case_count: int = 100) -> LongTermMemoryBenchmarkResult:
    if case_count <= 0:
        raise ValueError("case_count must be greater than zero")
    now = datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)
    runtime = LongTermMemoryRuntime(store=InMemoryMemoryFactStore())

    persisted = 0
    expected = case_count
    true_positive = 0
    retrieved_total = 0
    wrong = 0
    cross_identity = 0
    context_token_increase = 0

    # Session A: each authenticated user explicitly confirms stable facts.
    for index in range(case_count):
        model = f"LF-{900 + index}"
        result = runtime.promote_from_state(
            {
                "user_confirmed_facts": {
                    "product_model": model,
                    "preferred_language": "中文",
                    "region": "中国大陆" if index % 2 == 0 else "美国",
                }
            },
            identity_context=_identity(index, "A"),
            actor="evals.long_term_memory_benchmark",
            reason="Session A explicit stable fact confirmation",
            now=now,
        )
        persisted += len(result.persisted_facts)

    # Session B: a new conversation/thread/session retrieves only product_model.
    for index in range(case_count):
        current_identity = _identity(index, "B")
        state = {
            "identity_context": current_identity.to_state(),
            "messages": [
                {
                    "role": "user",
                    "content": "我之前确认的设备型号是什么？请按这个型号继续排查。",
                    "id": f"query-{index}",
                }
            ],
        }
        result = runtime.retrieve_for_context(
            state,
            identity_context=current_identity,
            limit=4,
            now=now,
        )
        retrieved_total += len(result.facts)
        expected_model = f"LF-{900 + index}"
        for fact in result.facts:
            if not fact.is_owned_by(current_identity):
                cross_identity += 1
            if fact.key == "product_model" and fact.value == expected_model:
                true_positive += 1
            else:
                wrong += 1

        before = ContextRuntime(
            max_tokens=512,
            builder=ContextBuilder(
                long_term_memory_runtime=runtime,
                long_term_memory_enabled=False,
            ),
            long_term_memory_runtime=runtime,
            long_term_memory_enabled=False,
            compaction_enabled=False,
        ).select(state)
        after = ContextRuntime(
            max_tokens=512,
            builder=ContextBuilder(long_term_memory_runtime=runtime),
            long_term_memory_runtime=runtime,
            compaction_enabled=False,
        ).select(state)
        context_token_increase += max(0, after.selected_tokens - before.selected_tokens)

    records = runtime.lifecycle_records()
    created_updated = sum(
        record.event.value in {"CREATED", "UPDATED"} for record in records
    )
    retrieved_events = sum(record.event.value == "RETRIEVED" for record in records)
    expired_injections = sum(
        record.event.value == "RETRIEVED"
        and record.memory.lifecycle_state.value == "EXPIRED"
        for record in records
    )
    precision = true_positive / retrieved_total if retrieved_total else 0.0
    recall = true_positive / expected if expected else 0.0
    wrong_rate = wrong / retrieved_total if retrieved_total else 0.0

    return LongTermMemoryBenchmarkResult(
        case_count=case_count,
        session_a_persisted_fact_count=persisted,
        session_b_expected_fact_count=expected,
        before_memory_precision=0.0,
        before_memory_recall=0.0,
        before_wrong_injection_rate=0.0,
        after_memory_precision=round(precision, 6),
        after_memory_recall=round(recall, 6),
        after_wrong_injection_rate=round(wrong_rate, 6),
        cross_identity_injection_count=cross_identity,
        cumulative_context_token_increase=context_token_increase,
        average_context_token_increase=round(context_token_increase / case_count, 4),
        lifecycle_created_updated_count=created_updated,
        lifecycle_retrieved_count=retrieved_events,
        expired_injection_count=expired_injections,
        methodology=(
            "Deterministic 100-user Session A/Session B evaluation. Session A promotes "
            "three structured, explicitly confirmed facts per user through Candidate -> "
            "MemoryUpdate -> Policy -> Store. Session B uses a different conversation, "
            "thread and session for the same tenant/user and asks only for product_model. "
            "Precision/recall compare exact fact key/value; wrong injection includes irrelevant "
            "or cross-owner facts. Token increase is the bounded Context Runtime delta and is "
            "not a live-LLM answer-quality score."
        ),
    )


def main() -> None:
    result = run_benchmark()
    outputs = (
        Path("evals/benchmark/reports/long_term_memory_phase5_report.json"),
        Path("artifacts/evals/LONG_TERM_MEMORY_PHASE5_BENCHMARK.json"),
    )
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
