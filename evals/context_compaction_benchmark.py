"""Deterministic Phase 3.2 benchmark for long-trajectory context compaction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from context_engine import ContextBuilder, ContextItemType, ContextRuntime
from identity import IdentityContext
from memory.working import WorkingMemory


@dataclass(frozen=True, slots=True)
class ContextCompactionBenchmarkResult:
    case_count: int
    trajectory_steps: tuple[int, ...]
    context_budget_tokens: int
    before_context_tokens: int
    after_compacted_context_tokens: int
    after_budgeted_context_tokens: int
    token_reduction_ratio: float
    state_preservation_rate: float
    summary_metadata_validity_rate: float
    compaction_success_rate: float
    original_history_retention_rate: float
    summaries_generated: int
    methodology: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["trajectory_steps"] = list(self.trajectory_steps)
        return result


def _identity(case_index: int) -> IdentityContext:
    return IdentityContext(
        tenant_id="tenant-compaction-benchmark",
        user_id=f"user-{case_index}",
        conversation_id=f"conversation-{case_index}",
        thread_id=f"thread-{case_index}",
        session_id=f"session-{case_index}",
    )


def _state(case_index: int, steps: int) -> dict[str, Any]:
    identity = _identity(case_index)
    memory = WorkingMemory(
        session_id=identity.session_id,
        task_goal="定位 LF-900 冰箱间歇性噪音并给出安全处理方案",
        current_intent="troubleshooting",
        confirmed_facts=(
            "product_model=LF-900",
            "error_code=E17",
            "noise_area=compressor",
            "warranty_status=active",
        ),
        open_questions=("噪音是否只在制冷启动时出现",),
        constraints=("不拆机", "不声称已经完成维修"),
        decisions=("先检查放置水平与风扇区域",),
        failed_attempts=("断电重启未解决",),
        next_actions=("确认噪音出现时机", "必要时建议授权维修"),
        last_updated=datetime(2026, 8, 6, 5, 45, tzinfo=timezone.utc),
    )
    messages: list[dict[str, Any]] = []
    for step in range(steps):
        phase = step % 3
        if phase == 0:
            role = "user"
            content = (
                f"第 {step} 步：确认型号 LF-900，E17 偶发，噪音来自压缩机附近。"
                "下一步应该检查什么？" + "历史用户描述" * 22
            )
        elif phase == 1:
            role = "assistant"
            content = (
                f"第 {step} 步：决定先核对放置水平和风扇区域；失败后再升级人工维修。"
                + "历史处理说明" * 22
            )
        else:
            role = "tool"
            content = (
                f"tool observation {step}: retrieved diagnostic payload "
                + "large tool output " * 80
            )
        messages.append(
            {
                "role": role,
                "content": content,
                "id": f"case-{case_index}-message-{step}",
                "name": "knowledge_agent" if role == "tool" else None,
            }
        )
    # Ensure a native current user turn exists after the historical trajectory.
    messages.append(
        {
            "role": "user",
            "content": "请基于已经确认的状态继续给出下一步。",
            "id": f"case-{case_index}-current-user",
        }
    )
    return {
        "messages": messages,
        "identity_context": identity.to_state(),
        "session_id": identity.session_id,
        "working_memory": memory.to_state(),
        "workflow_state": {
            "stage": "troubleshooting",
            "status": "in_progress",
        },
        "unresolved_slots": ["noise_timing"],
        "evidence_refs": [
            {
                "id": "manual-noise-diagnosis",
                "source": "fridge_manual.md",
                "required": True,
            }
        ],
    }


def run_benchmark(
    *,
    trajectory_steps: tuple[int, ...] = (120, 140, 160, 180, 200),
    context_budget_tokens: int = 1024,
) -> ContextCompactionBenchmarkResult:
    if not trajectory_steps or any(step < 100 or step > 200 for step in trajectory_steps):
        raise ValueError("Phase 3.2 trajectories must contain 100-200 steps")

    before_tokens = 0
    after_compacted_tokens = 0
    after_budgeted_tokens = 0
    preserved = 0
    metadata_valid = 0
    successful = 0
    history_retained = 0
    summaries_generated = 0
    builder = ContextBuilder()

    for case_index, steps in enumerate(trajectory_steps, start=1):
        state = _state(case_index, steps)
        original_messages_json = json.dumps(
            state["messages"], ensure_ascii=False, sort_keys=True
        )
        built = builder.build(messages_state=state)
        before_tokens += sum(int(item.token_cost or 0) for item in built)

        selection = ContextRuntime(
            max_tokens=context_budget_tokens,
            compaction_item_threshold=24,
            compaction_recent_messages=8,
            compaction_summary_max_tokens=300,
        ).select(state)
        compaction = selection.runtime_metadata["compaction"]
        after_compacted_tokens += selection.input_tokens
        after_budgeted_tokens += selection.selected_tokens

        if compaction.get("applied"):
            successful += 1
            summaries_generated += sum(
                item.type is ContextItemType.SUMMARY
                and bool(item.metadata.get("compaction_summary"))
                for item in selection.items
            )
        validation = compaction.get("validation") or {}
        if validation.get("working_memory_preserved"):
            preserved += 1
        if validation.get("summary_metadata_valid"):
            metadata_valid += 1
        if json.dumps(state["messages"], ensure_ascii=False, sort_keys=True) == original_messages_json:
            history_retained += 1

    case_count = len(trajectory_steps)
    reduction = (
        0.0
        if before_tokens == 0
        else 1 - after_compacted_tokens / before_tokens
    )
    return ContextCompactionBenchmarkResult(
        case_count=case_count,
        trajectory_steps=trajectory_steps,
        context_budget_tokens=context_budget_tokens,
        before_context_tokens=before_tokens,
        after_compacted_context_tokens=after_compacted_tokens,
        after_budgeted_context_tokens=after_budgeted_tokens,
        token_reduction_ratio=round(reduction, 6),
        state_preservation_rate=round(preserved / case_count, 6),
        summary_metadata_validity_rate=round(metadata_valid / case_count, 6),
        compaction_success_rate=round(successful / case_count, 6),
        original_history_retention_rate=round(history_retained / case_count, 6),
        summaries_generated=summaries_generated,
        methodology=(
            "Deterministic 120-200 step trajectories. Before tokens are all ContextItems "
            "built from unchanged state. After-compacted tokens are the ContextSelector input "
            "after old messages/tool observations are replaced by an identity-bound structured "
            "summary. State preservation is CompactionValidator's exact Working Memory check; "
            "this benchmark does not claim live-LLM answer accuracy."
        ),
    )


def main() -> None:
    result = run_benchmark()
    output = Path("evals/benchmark/reports/context_compaction_phase3_2_report.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
