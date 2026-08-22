from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from context_engine import (
    CompactionTrigger,
    CompactionValidationError,
    CompactionValidator,
    ContextBuilder,
    ContextCompressor,
    ContextItem,
    ContextItemType,
    ContextRuntime,
    HybridSemanticContextCompressor,
)
from identity import IdentityContext
from memory.working import WorkingMemory


def _identity() -> IdentityContext:
    return IdentityContext(
        tenant_id="tenant-acme",
        user_id="user-42",
        conversation_id="conversation-noise-1",
        thread_id="thread-noise-1",
        session_id="session-noise-1",
    )


def _working_memory() -> WorkingMemory:
    return WorkingMemory(
        session_id="session-noise-1",
        task_goal="排查冰箱异常噪音并给出下一步行动",
        current_intent="product_troubleshooting",
        confirmed_facts=("product_model=LF-900", "noise_from=compressor_area"),
        open_questions=("噪音是否只在制冷启动时出现",),
        constraints=("不能声称已经完成维修",),
        decisions=("先核对安装水平再检查压缩机",),
        failed_attempts=("重新插电未解决",),
        next_actions=("确认噪音出现时机",),
        last_updated=datetime(2026, 8, 6, 4, 0, tzinfo=timezone.utc),
    )


def _state(step_count: int = 120) -> dict:
    messages: list[dict] = []
    for index in range(step_count):
        role = "user" if index % 2 == 0 else "assistant"
        if role == "user":
            content = (
                f"第 {index} 步：确认型号 LF-900，噪音仍在压缩机附近。"
                "这个现象下一步应该检查什么？" + "历史描述" * 18
            )
        else:
            content = (
                f"第 {index} 步：决定先检查安装水平；如果失败再检查压缩机。"
                + "历史处理" * 18
            )
        messages.append({"role": role, "content": content, "id": f"message-{index}"})
    identity = _identity()
    memory = _working_memory()
    return {
        "messages": messages,
        "identity_context": identity.to_state(),
        "session_id": identity.session_id,
        "working_memory": memory.to_state(),
        "workflow_state": {"stage": "troubleshooting", "status": "in_progress"},
        "unresolved_slots": ["noise_timing"],
        "evidence_refs": [
            {
                "id": "evidence-noise-guide",
                "source": "fridge_manual.md",
                "required": True,
            }
        ],
    }


def test_compaction_trigger():
    items = [
        ContextItem(
            id=f"history-{index}",
            type=(
                ContextItemType.USER_MESSAGE
                if index % 2 == 0
                else ContextItemType.ASSISTANT_MESSAGE
            ),
            content="历史上下文" * 80,
            source="messages_state",
            priority=25,
            metadata={"sequence": index, "is_current": False},
        )
        for index in range(12)
    ]
    decision = CompactionTrigger(token_threshold=100, item_threshold=50).evaluate(items)

    assert decision.should_compact is True
    assert decision.reason == "token_threshold_exceeded"
    assert decision.compactable_item_count == 12


def test_summary_metadata():
    built = ContextBuilder().build(messages_state=_state(80))
    result = ContextCompressor(
        recent_message_count=4,
        summary_max_tokens=240,
    ).compact(built)
    metadata = result.summary.summary_metadata
    round_tripped = json.loads(json.dumps(result.summary.to_state(), ensure_ascii=False))

    assert metadata.source_range.source_item_ids
    assert metadata.generated_by.startswith("context_engine.compaction")
    assert 0.0 <= metadata.confidence <= 1.0
    assert metadata.created_at.tzinfo is not None
    assert metadata.original_token_cost > metadata.compressed_token_cost
    assert metadata.identity_context == _identity()
    assert round_tripped["identity_context"]["thread_id"] == "thread-noise-1"
    assert set(result.summary.summary_content) == {
        "task_progress",
        "important_decisions",
        "confirmed_information",
        "corrections",
        "pending_questions",
        "failed_attempts",
        "continuity_notes",
    }


def test_compaction_preserve_working_memory():
    built = ContextBuilder().build(messages_state=_state(120))
    before_memory = [item.to_state() for item in built if item.type is ContextItemType.MEMORY]
    compressor = ContextCompressor(recent_message_count=6, summary_max_tokens=256)
    result = compressor.compact(built)
    validation = CompactionValidator().validate(
        before_items=built,
        after_items=result.items,
        summary=result.summary,
    )
    after_memory = [
        item.to_state() for item in result.items if item.type is ContextItemType.MEMORY
    ]

    assert validation.valid is True
    assert validation.working_memory_preserved is True
    assert before_memory == after_memory
    assert any(item.type is ContextItemType.SUMMARY for item in result.items)


def test_compaction_validation_failure():
    built = ContextBuilder().build(messages_state=_state(100))
    result = ContextCompressor(recent_message_count=4).compact(built)
    without_working_memory = tuple(
        item for item in result.items if item.type is not ContextItemType.MEMORY
    )

    with pytest.raises(CompactionValidationError, match="working_memory_changed_or_missing"):
        CompactionValidator().validate(
            before_items=built,
            after_items=without_working_memory,
            summary=result.summary,
        )


def test_context_builder_integration():
    state = _state(140)
    original_messages = json.loads(json.dumps(state["messages"], ensure_ascii=False))
    runtime = ContextRuntime(
        max_tokens=640,
        compaction_item_threshold=20,
        compaction_recent_messages=6,
        compaction_summary_max_tokens=220,
    )

    selection = runtime.select(state)
    prompt = runtime.build_prompt("system", state)
    manifest = selection.to_manifest()["runtime_metadata"]["compaction"]

    assert manifest["applied"] is True
    assert manifest["validation"]["working_memory_preserved"] is True
    assert manifest["summary"]["identity_context"]["session_id"] == "session-noise-1"
    assert any(item.type is ContextItemType.MEMORY for item in selection.items)
    assert any(
        item.type is ContextItemType.SUMMARY
        and item.metadata.get("compaction_summary")
        for item in selection.items
    )
    assert "context_engine.compaction" in prompt
    assert '"task_progress"' in prompt
    assert state["messages"] == original_messages


def test_supervisor_dynamic_prompt_uses_compaction(monkeypatch):
    import importlib.util
    from pathlib import Path
    import sys
    import types

    captured: dict = {}
    langchain = types.ModuleType("langchain")
    langchain.__path__ = []
    agents_mod = types.ModuleType("langchain.agents")
    middleware_mod = types.ModuleType("langchain.agents.middleware")
    chat_models_mod = types.ModuleType("langchain.chat_models")
    tools_mod = types.ModuleType("langchain.tools")
    langgraph = types.ModuleType("langgraph")
    langgraph.__path__ = []
    checkpoint_mod = types.ModuleType("langgraph.checkpoint")
    checkpoint_mod.__path__ = []
    memory_mod = types.ModuleType("langgraph.checkpoint.memory")
    graph_mod = types.ModuleType("langgraph.graph")

    class FakeRequest:
        def __init__(self, *, state, messages, runtime=None):
            self.state = state
            self.messages = messages
            self.runtime = runtime

        def override(self, **updates):
            return FakeRequest(
                state=updates.get("state", self.state),
                messages=updates.get("messages", self.messages),
                runtime=self.runtime,
            )

    class FakeModelResponse:
        pass

    class FakeMemorySaver:
        pass

    class FakeModel:
        pass

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    def identity_middleware(fn):
        return fn

    def fake_tool(*args, **kwargs):
        del args, kwargs

        def decorator(fn):
            return fn

        return decorator

    agents_mod.create_agent = fake_create_agent
    middleware_mod.ModelRequest = FakeRequest
    middleware_mod.ModelResponse = FakeModelResponse
    middleware_mod.dynamic_prompt = identity_middleware
    middleware_mod.wrap_model_call = identity_middleware
    chat_models_mod.init_chat_model = lambda *args, **kwargs: FakeModel()
    class FakeToolRuntime:
        pass

    tools_mod.ToolRuntime = FakeToolRuntime
    tools_mod.tool = fake_tool
    memory_mod.MemorySaver = FakeMemorySaver
    graph_mod.MessagesState = dict

    for name, module in {
        "langchain": langchain,
        "langchain.agents": agents_mod,
        "langchain.agents.middleware": middleware_mod,
        "langchain.chat_models": chat_models_mod,
        "langchain.tools": tools_mod,
        "langgraph": langgraph,
        "langgraph.checkpoint": checkpoint_mod,
        "langgraph.checkpoint.memory": memory_mod,
        "langgraph.graph": graph_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    module_path = Path("agents/conversation_supervisor.py")
    spec = importlib.util.spec_from_file_location(
        "phase3_2_supervisor_under_test", module_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.create_supervisor_agent(
        order_agent=object(),
        knowledge_agent=object(),
        use_checkpointer=False,
        context_max_tokens=640,
    )
    dynamic_prompt_middleware, bounded_message_middleware = captured["middleware"]
    state = _state(130)
    request = FakeRequest(state=state, messages=state["messages"])

    prompt = dynamic_prompt_middleware(request)
    assert '"task_progress"' in prompt
    assert '"applied": true' in prompt
    assert "context_engine.compaction" in prompt
    assert "当前目标" in prompt

    forwarded: dict = {}

    def handler(bounded_request):
        forwarded["request"] = bounded_request
        return FakeModelResponse()

    bounded_model_context = bounded_message_middleware
    bounded_model_context(request, handler)
    assert forwarded["request"].messages == state["messages"][-2:]
    assert len(request.state["messages"]) == 130


def test_hybrid_semantic_compaction_only_receives_compactable_history():
    built = ContextBuilder().build(messages_state=_state(80))
    captured: dict = {}

    def semantic(payload):
        captured["payload"] = payload
        return {
            "task_progress": ["用户一直在排查 LF-900 的压缩机噪音。"],
            "important_decisions": ["先检查安装水平，再看压缩机。"],
            "confirmed_information": ["型号 LF-900，噪音来自压缩机附近。"],
            "corrections": [],
            "pending_questions": ["仍需确认噪音是否只在制冷启动时出现。"],
            "failed_attempts": ["重新插电未解决。"],
            "continuity_notes": ["继续沿当前噪音排查任务推进。"],
        }

    result = HybridSemanticContextCompressor(
        semantic_compactor=semantic,
        recent_message_count=4,
        summary_max_tokens=256,
    ).compact(built)

    payload_items = captured["payload"]["items"]
    assert payload_items
    assert {item["type"] for item in payload_items} <= {"USER_MESSAGE", "ASSISTANT_MESSAGE"}
    assert not any("Active Task" in item["content"] for item in payload_items)
    assert result.attributes["semantic_compaction_applied"] is True
    assert result.summary.summary_metadata.generated_by.endswith("HybridSemanticContextCompressor/v1")
    assert result.summary.summary_content["continuity_notes"]


def test_hybrid_semantic_compaction_falls_back_on_invalid_output():
    built = ContextBuilder().build(messages_state=_state(80))

    def broken(payload):
        del payload
        return {"unsupported": ["bad schema"]}

    result = HybridSemanticContextCompressor(
        semantic_compactor=broken,
        recent_message_count=4,
        summary_max_tokens=256,
    ).compact(built)

    assert result.attributes["semantic_compaction_applied"] is False
    assert result.attributes["fallback_mode"] == "deterministic"
    assert result.summary.summary_content["task_progress"]


def test_compaction_summary_preserves_corrections():
    identity = _identity()
    items = [
        ContextItem(
            id=f"message-{index}",
            type=ContextItemType.USER_MESSAGE if index % 2 == 0 else ContextItemType.ASSISTANT_MESSAGE,
            content=content,
            source="messages_state",
            priority=20,
            metadata={
                "sequence": index,
                "is_current": False,
                "role": "user" if index % 2 == 0 else "assistant",
                "identity_context": identity.to_state(),
            },
        )
        for index, content in enumerate(
            [
                "我确认型号是 X100，错误码 E17。",
                "已记录 X100 和 E17。",
                "刚才型号说错了，不是 X100，改成 X200。",
                "继续用 X200 做后续排查。",
                "现在下一步怎么做？",
                "下一步先确认购买地区。",
            ]
        )
    ]

    result = ContextCompressor(recent_message_count=0, summary_max_tokens=256).compact(items)

    assert any("X200" in item for item in result.summary.summary_content["corrections"])
