from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from context_engine import ContextBuilder, ContextItemType, ContextRuntime
from memory.working import WorkingMemory, WorkingMemoryExtractor, WorkingMemorySerializer, WorkingMemoryUpdater


def test_working_memory_model():
    memory = WorkingMemory(
        session_id="session-1", task_goal="排查冰箱异常噪音", current_intent="troubleshooting",
        confirmed_facts=("product_model=LF-900", "error_code=E17"),
        open_questions=("需要补充：noise_timing",), constraints=("不拆机",),
        decisions=("先检查水平状态",), failed_attempts=("重启未解决",),
        next_actions=("检查风扇区域",),
        last_updated=datetime(2026, 8, 6, 4, 0, tzinfo=timezone.utc),
    )
    state = memory.to_state()
    restored = WorkingMemory.from_state(json.loads(json.dumps(state)))
    assert restored == memory
    assert state["last_updated"].endswith("+00:00")
    assert isinstance(state["confirmed_facts"], list)


def test_working_memory_builder():
    memory = WorkingMemoryExtractor().extract(
        {
            "messages": [{"role": "user", "content": "我的 LF-900 冰箱出现 E17 异响"}],
            "workflow_state": {"stage": "identity_verification", "identity_status": "verified"},
            "task_goal": "排查冰箱异常噪音", "task_type": "troubleshooting",
            "product_model": "LF-900", "error_code": "E17", "customer_id": "C-101",
            "unresolved_slots": ["noise_timing"], "requirements": ["不得拆机"],
            "verification_action": "retrieve_more",
        },
        session_id="session-2", now=datetime(2026, 8, 6, 4, 1, tzinfo=timezone.utc),
    )
    assert memory.task_goal == "排查冰箱异常噪音"
    assert memory.current_intent == "troubleshooting"
    assert "product_model=LF-900" in memory.confirmed_facts
    assert "error_code=E17" in memory.confirmed_facts
    assert "customer_id=C-101" in memory.confirmed_facts
    assert "需要补充：noise_timing" in memory.open_questions
    assert "requirement=不得拆机" in memory.constraints
    assert "verification_action=retrieve_more" in memory.decisions
    assert "执行补充检索" in memory.next_actions


def test_working_memory_context_injection():
    memory = WorkingMemory(
        session_id="session-context", task_goal="核对退货资格", current_intent="return_policy",
        confirmed_facts=("product_model=LF-900",), open_questions=("需要补充：purchase_region",),
        next_actions=("收集购买地区",),
        last_updated=datetime(2026, 8, 6, 4, 2, tzinfo=timezone.utc),
    )
    result = WorkingMemoryUpdater().update(
        {**memory.to_state(), "task_goal": memory.task_goal}, actor="test",
        reason="prepare context injection", previous=memory, session_id=memory.session_id,
        now=memory.last_updated,
    )
    state = {
        "messages": [{"role": "user", "content": "我是在中国大陆买的"}],
        "working_memory": result.memory.to_state(),
        "working_memory_lifecycle_records": result.records_to_state(),
        "workflow_state": {"stage": "ready_for_supervisor"},
    }
    items = ContextBuilder().build(messages_state=state)
    [memory_item] = [item for item in items if item.type is ContextItemType.MEMORY]
    prompt = ContextRuntime(max_tokens=512).build_prompt("system", state)
    assert memory_item.priority == 99
    assert memory_item.required is True
    assert memory_item.metadata["memory_kind"] == "working"
    assert memory_item.metadata["lifecycle_event"]["event"] == "RETRIEVED"
    assert "当前目标：核对退货资格" in prompt
    assert "product_model=LF-900" in prompt


def test_checkpoint_recovery():
    updater = WorkingMemoryUpdater()
    serializer = WorkingMemorySerializer()
    state: dict = {
        "messages": [], "workflow_state": {"stage": "ready_for_supervisor"},
        "unresolved_slots": ["product_model"], "task_goal": "完成 20 轮冰箱故障排查",
        "current_intent": "troubleshooting",
    }
    memory = None
    records: list[dict] = []
    start = datetime(2026, 8, 6, 4, 10, tzinfo=timezone.utc)
    for turn in range(20):
        state["messages"].extend([
            {"role": "user", "content": f"第 {turn + 1} 轮补充信息"},
            {"role": "assistant", "content": f"第 {turn + 1} 轮处理结果"},
        ])
        state["confirmed_facts"] = ["product_model=LF-900", f"completed_turn={turn + 1}"]
        state["unresolved_slots"] = ["noise_timing"] if turn < 12 else ["fan_status"]
        result = updater.update(
            state, actor="checkpoint-test", reason=f"turn {turn + 1}", previous=memory,
            existing_records=records, session_id="checkpoint-session",
            now=start + timedelta(minutes=turn),
        )
        if result.delta.is_noop:
            assert result.persisted is False
            assert result.lifecycle_records == ()
        else:
            assert result.persisted is True
        memory = result.memory
        records.extend(result.records_to_state())
    assert memory is not None
    checkpoint = serializer.checkpoint_payload(memory, lifecycle_records=records)
    restored_payload = serializer.json_round_trip(checkpoint)
    restored_memory = WorkingMemory.from_state(restored_payload["working_memory"])
    resumed = WorkingMemoryUpdater().update(
        {**state, **restored_payload}, actor="checkpoint-test-resume",
        reason="resume after checkpoint reload", previous=restored_memory,
        existing_records=restored_payload["working_memory_lifecycle_records"],
        session_id=restored_payload["session_id"], now=start + timedelta(minutes=21),
    )
    assert resumed.memory.session_id == "checkpoint-session"
    assert resumed.memory.task_goal == "完成 20 轮冰箱故障排查"
    assert "product_model=LF-900" in resumed.memory.confirmed_facts
    assert "需要补充：fan_status" in resumed.memory.open_questions


def test_memory_not_duplicate_messages():
    old_secret = "OLD_HISTORY_ONLY_7f4a"
    tool_payload = "TOOL_OUTPUT_ONLY_913b"
    evidence_payload = "RETRIEVAL_CHUNK_ONLY_451c"
    state = {
        "messages": [
            {"role": "user", "content": old_secret},
            {"role": "assistant", "content": "历史回答"},
            {"role": "tool", "content": tool_payload},
            {"role": "user", "content": "当前目标是排查 E17"},
        ],
        "task_goal": "排查 E17", "workflow_state": {"stage": "ready_for_supervisor"},
        "product_model": "LF-900", "error_code": "E17",
        "evidences": [{"document": {"page_content": evidence_payload}, "trace": [{"raw": tool_payload}]}],
        "trace_events": [{"content": old_secret}],
    }
    memory = WorkingMemoryExtractor().extract(state, session_id="no-dup")
    rendered = WorkingMemorySerializer().to_context_content(memory)
    serialized = json.dumps(memory.to_state(), ensure_ascii=False)
    assert memory.task_goal == "排查 E17"
    assert "product_model=LF-900" in memory.confirmed_facts
    assert old_secret not in rendered
    assert tool_payload not in rendered
    assert evidence_payload not in rendered
    assert "messages" not in serialized
    assert "trace" not in serialized
    assert "evidences" not in serialized
