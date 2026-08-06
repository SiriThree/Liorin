"""Deterministic 50-turn Phase 2 Working Memory benchmark."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from context_engine import ContextRuntime, estimate_token_cost
from memory.working import WorkingMemory, WorkingMemoryUpdater


@dataclass(frozen=True, slots=True)
class WorkingMemoryBenchmarkResult:
    turns: int
    context_budget_tokens: int
    before_final_prompt_tokens: int
    after_final_prompt_tokens: int
    before_cumulative_prompt_tokens: int
    after_cumulative_prompt_tokens: int
    cumulative_token_reduction_ratio: float
    before_task_completion_rate: float
    after_task_completion_rate: float
    before_information_loss_count: int
    after_information_loss_count: int
    final_confirmed_fact_count: int
    final_open_question_count: int
    methodology: str

    def to_dict(self) -> dict[str, Any]: return asdict(self)


def run_benchmark(*, turns: int = 50, context_budget_tokens: int = 768) -> WorkingMemoryBenchmarkResult:
    if turns != 50: raise ValueError("Phase 2 benchmark is defined for exactly 50 turns")
    runtime = ContextRuntime(max_tokens=context_budget_tokens)
    updater = WorkingMemoryUpdater()
    memory: WorkingMemory | None = None
    lifecycle_records: list[dict[str, Any]] = []
    messages: list[dict[str, str]] = []
    expected_facts: list[str] = []
    expected_constraints: list[str] = []
    expected_decisions: list[str] = []
    task_goal = "定位 LF-900 冰箱间歇性异常噪音并给出安全的下一步处理方案"
    start = datetime(2026, 8, 6, 4, 30, tzinfo=timezone.utc)
    fact_schedule = {
        1: ("product_model=LF-900", "产品型号是 LF-900"),
        5: ("error_code=E17", "面板偶尔出现 E17"),
        10: ("region=CN", "购买和使用地区是中国大陆"),
        15: ("noise_timing=night", "异常噪音主要在夜间出现"),
        20: ("warranty_status=active", "设备仍在质保期"),
        25: ("floor_status=level", "已经确认冰箱放置水平"),
        30: ("restart_result=not_resolved", "断电重启后问题仍然存在"),
        35: ("fan_area_checked=true", "已检查风扇区域但没有发现异物"),
        40: ("door_seal_status=normal", "门封条状态正常"),
        45: ("compressor_noise_suspected=true", "噪音更接近压缩机区域"),
    }
    before_successes = after_successes = before_loss = after_loss = 0
    before_cumulative = after_cumulative = before_final = after_final = 0

    for turn in range(1, turns + 1):
        fact_entry = fact_schedule.get(turn)
        user_detail = "继续按照安全流程排查，不要让我拆机。"
        if fact_entry:
            fact, user_detail = fact_entry; expected_facts.append(fact)
        if turn == 2: expected_constraints.append("不拆机")
        if turn == 26: expected_decisions.append("先排除放置与风扇问题")
        unresolved_slots = ["noise_timing"] if turn < 15 else ["fan_status"] if turn < 35 else ["compressor_status"]
        messages.append({"role": "user", "content": f"第 {turn} 轮：{user_detail} " + "请结合之前已经确认的信息继续处理。" * 12})
        messages.append({"role": "assistant", "content": f"第 {turn} 轮处理记录：已接收新状态，继续执行分步诊断。" + "本轮不执行真实维修动作。" * 8})
        structured_state = {
            "messages": messages, "task_goal": task_goal, "current_intent": "troubleshooting",
            "workflow_state": {"stage": "ready_for_supervisor", "requires_verification": False},
            "confirmed_facts": expected_facts, "constraints": expected_constraints,
            "decisions": expected_decisions, "unresolved_slots": unresolved_slots,
            "next_actions": ["在不拆机前提下继续诊断", "证据不足时建议人工维修检查"],
        }
        update = updater.update(
            structured_state, actor="evals.working_memory_benchmark",
            reason=f"Update synthetic task state at turn {turn}", previous=memory,
            existing_records=lifecycle_records, session_id="phase2-benchmark-session",
            now=start + timedelta(minutes=turn),
        )
        if update.policy is not None and not update.policy.approved:
            raise RuntimeError(f"policy rejected turn {turn}: {update.policy.reason}")
        memory = update.memory; lifecycle_records.extend(update.records_to_state())
        before_tokens = sum(estimate_token_cost(message["content"]) for message in messages)
        selection = runtime.select({
            "messages": messages, "working_memory": memory.to_state(),
            "working_memory_lifecycle_records": lifecycle_records,
            "workflow_state": structured_state["workflow_state"], "unresolved_slots": unresolved_slots,
        })
        after_tokens = selection.selected_tokens
        before_cumulative += before_tokens; after_cumulative += after_tokens
        before_final = before_tokens; after_final = after_tokens
        before_text = "\n".join(message["content"] for message in messages)
        introduced_phrases = [entry[1] for key, entry in fact_schedule.items() if key <= turn]
        before_missing = sum(1 for phrase in introduced_phrases if phrase not in before_text)
        after_missing = sum(1 for fact in expected_facts if fact not in memory.confirmed_facts)
        after_missing += sum(1 for slot in unresolved_slots if f"需要补充：{slot}" not in memory.open_questions)
        before_loss += before_missing; after_loss += after_missing
        if before_missing == 0 and task_goal: before_successes += 1
        if after_missing == 0 and memory.task_goal == task_goal: after_successes += 1

    assert memory is not None
    reduction = 0.0 if before_cumulative == 0 else 1 - after_cumulative / before_cumulative
    return WorkingMemoryBenchmarkResult(
        turns=turns, context_budget_tokens=context_budget_tokens,
        before_final_prompt_tokens=before_final, after_final_prompt_tokens=after_final,
        before_cumulative_prompt_tokens=before_cumulative, after_cumulative_prompt_tokens=after_cumulative,
        cumulative_token_reduction_ratio=round(reduction, 6),
        before_task_completion_rate=round(before_successes / turns, 6),
        after_task_completion_rate=round(after_successes / turns, 6),
        before_information_loss_count=before_loss, after_information_loss_count=after_loss,
        final_confirmed_fact_count=len(memory.confirmed_facts), final_open_question_count=len(memory.open_questions),
        methodology="Deterministic structured-state benchmark. Completion measures task-state availability, not semantic answer correctness or live LLM quality.",
    )


def main() -> None:
    result = run_benchmark()
    output = Path("evals/benchmark/reports/working_memory_phase2_report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
