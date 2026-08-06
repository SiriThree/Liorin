from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types

from context_engine import (
    ContextBudgetManager,
    ContextBuilder,
    ContextItem,
    ContextItemType,
    ContextRuntime,
    ContextSelector,
)


def test_context_item_creation():
    item = ContextItem(
        id="request-1",
        type=ContextItemType.USER_MESSAGE,
        content="冰箱出现异常噪音，应该如何排查？",
        source="messages_state",
        priority=100,
        timestamp=datetime.now(timezone.utc),
        metadata={"required": True},
    )

    assert item.type is ContextItemType.USER_MESSAGE
    assert item.required is True
    assert item.token_cost > 0
    assert item.to_state()["type"] == "USER_MESSAGE"


def test_context_budget_limit():
    messages = []
    for index in range(100):
        messages.append(
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"第 {index} 轮消息：" + ("历史上下文" * 80),
                "id": f"message-{index}",
            }
        )
    state = {
        "messages": messages,
        "workflow_state": {"stage": "ready_for_supervisor", "task": "noise_diagnosis"},
        "unresolved_slots": ["product_model"],
    }

    selection = ContextRuntime(max_tokens=256).select(state)

    assert selection.within_budget
    assert selection.selected_tokens <= 256
    assert sum(item.token_cost for item in selection.items) <= 256
    assert any(item.metadata.get("is_current") for item in selection.items)
    assert any(item.metadata.get("category") == "unresolved_slots" for item in selection.items)


def test_context_priority_selection():
    items = [
        ContextItem(
            id="old-history",
            type=ContextItemType.ASSISTANT_MESSAGE,
            content="旧历史" * 400,
            source="messages_state",
            priority=10,
        ),
        ContextItem(
            id="current-request",
            type=ContextItemType.USER_MESSAGE,
            content="当前用户请求：排查 E502",
            source="messages_state",
            priority=100,
            metadata={"required": True, "is_current": True},
        ),
        ContextItem(
            id="workflow",
            type=ContextItemType.WORKFLOW_STATE,
            content="当前任务状态：等待确认产品型号",
            source="support_workflow",
            priority=100,
            metadata={"required": True, "category": "unresolved_slots"},
        ),
    ]

    selected = ContextSelector().select(items)
    selection = ContextBudgetManager(max_tokens=40).apply(selected)
    selected_ids = {item.id for item in selection.items}

    assert "current-request" in selected_ids
    assert "workflow" in selected_ids
    assert "old-history" not in selected_ids
    assert selection.within_budget


def test_dynamic_prompt_integration(monkeypatch):
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
    spec = importlib.util.spec_from_file_location("phase1_supervisor_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.create_supervisor_agent(
        order_agent=object(),
        knowledge_agent=object(),
        use_checkpointer=False,
        context_max_tokens=160,
    )

    dynamic_prompt_middleware, bounded_message_middleware = captured["middleware"]
    messages = [
        {"role": "user", "content": "旧问题"},
        {"role": "assistant", "content": "旧答案"},
        {"role": "user", "content": "当前问题：冰箱异常噪音"},
    ]
    request = FakeRequest(
        state={
            "messages": messages,
            "workflow_state": {"stage": "ready_for_supervisor"},
            "unresolved_slots": ["product_model"],
        },
        messages=messages,
    )

    prompt = dynamic_prompt_middleware(request)
    assert "<runtime_context>" in prompt
    assert "未解决槽位" in prompt
    assert "context_manifest" in prompt

    forwarded: dict = {}

    def handler(bounded_request):
        forwarded["request"] = bounded_request
        return FakeModelResponse()

    bounded_message_middleware(request, handler)
    assert forwarded["request"].messages == [messages[-1]]


def test_knowledge_evidence_is_deduplicated_into_reference():
    evidence = {
        "citation_id": "E1",
        "source": "manual",
        "source_type": "manual",
        "document": {
            "page_content": "大体积证据正文" * 500,
            "metadata": {
                "document_id": "manual-1",
                "section": "异常噪音",
                "source_file": "fridge_manual.md",
                "security_status": "safe",
            },
        },
        "trace": [{"stage": "dense"}, {"stage": "rerank"}],
    }
    state = {
        "messages": [{"role": "user", "content": "怎么排查异常噪音？"}],
        "evidences": [evidence],
        "verified_evidences": [evidence],
        "retrieval_response": {"evidences": [evidence]},
    }

    items = ContextBuilder().build(knowledge_state=state)
    evidence_items = [item for item in items if item.type is ContextItemType.EVIDENCE_REFERENCE]

    assert len(evidence_items) == 1
    assert evidence_items[0].metadata["verified"] is True
    assert evidence_items[0].metadata["trace_event_count"] == 2
    assert "大体积证据正文" not in evidence_items[0].content
    assert evidence_items[0].source == "fridge_manual.md"
