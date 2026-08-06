from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

from context_engine import ContextBuilder, ContextItemType
from memory.facts import InMemoryMemoryFactStore, LongTermMemoryRuntime


def test_support_workflow_node_persists_working_memory(monkeypatch):
    langchain = types.ModuleType("langchain"); langchain.__path__ = []
    chat_models = types.ModuleType("langchain.chat_models"); chat_models.init_chat_model = lambda *args, **kwargs: object()
    langchain_community = types.ModuleType("langchain_community"); langchain_community.__path__ = []
    utilities = types.ModuleType("langchain_community.utilities"); utilities.SQLDatabase = object
    langchain_core = types.ModuleType("langchain_core"); langchain_core.__path__ = []
    messages_mod = types.ModuleType("langchain_core.messages")

    class FakeMessage:
        def __init__(self, content: str):
            self.content = content
            self.type = "human"

    messages_mod.AIMessage = FakeMessage; messages_mod.HumanMessage = FakeMessage
    langgraph = types.ModuleType("langgraph"); langgraph.__path__ = []
    checkpoint = types.ModuleType("langgraph.checkpoint"); checkpoint.__path__ = []
    checkpoint_memory = types.ModuleType("langgraph.checkpoint.memory"); checkpoint_memory.MemorySaver = object
    graph_mod = types.ModuleType("langgraph.graph"); graph_mod.START = "START"; graph_mod.MessagesState = dict; graph_mod.StateGraph = object
    runtime_mod = types.ModuleType("langgraph.runtime")

    class FakeRuntimeType:
        @classmethod
        def __class_getitem__(cls, item): return cls

    runtime_mod.Runtime = FakeRuntimeType
    types_mod = types.ModuleType("langgraph.types")

    class FakeCommand:
        @classmethod
        def __class_getitem__(cls, item): return cls
        def __init__(self, *, update=None, goto=None): self.update = update or {}; self.goto = goto

    types_mod.Command = FakeCommand; types_mod.interrupt = lambda value: value
    supervisor_mod = types.ModuleType("agents.conversation_supervisor"); supervisor_mod.create_supervisor_agent = lambda **kwargs: object()
    knowledge_mod = types.ModuleType("agents.knowledge_agent"); knowledge_mod.create_knowledge_agent = lambda **kwargs: object()
    order_mod = types.ModuleType("agents.order_agent"); order_mod.create_order_agent = lambda **kwargs: object()
    database_mod = types.ModuleType("tools.database"); database_mod.get_database = lambda: object()

    for name, module in {
        "langchain": langchain, "langchain.chat_models": chat_models,
        "langchain_community": langchain_community, "langchain_community.utilities": utilities,
        "langchain_core": langchain_core, "langchain_core.messages": messages_mod,
        "langgraph": langgraph, "langgraph.checkpoint": checkpoint,
        "langgraph.checkpoint.memory": checkpoint_memory, "langgraph.graph": graph_mod,
        "langgraph.runtime": runtime_mod, "langgraph.types": types_mod,
        "agents.conversation_supervisor": supervisor_mod, "agents.knowledge_agent": knowledge_mod,
        "agents.order_agent": order_mod, "tools.database": database_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location("phase2_support_workflow_under_test", Path("agents/support_workflow.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, "classify_query_intent", lambda query, model: {"requires_verification": False, "reasoning": "通用故障排查"})
    monkeypatch.setattr(
        module,
        "_LONG_TERM_MEMORY_RUNTIME",
        LongTermMemoryRuntime(store=InMemoryMemoryFactStore()),
    )

    runtime = types.SimpleNamespace(
        context=types.SimpleNamespace(model="fake:model", tenant_id="tenant-test"),
        execution_info=types.SimpleNamespace(thread_id="thread-test-1"),
        server_info=types.SimpleNamespace(
            user=types.SimpleNamespace(identity="user-test-1")
        ),
    )
    command = module.query_router(
        {
            "messages": [FakeMessage("我确认设备型号是 LF-900，请排查冰箱异常噪音")],
        },
        runtime,
    )
    assert command.goto == "supervisor_agent"
    assert command.update["session_id"]
    identity = command.update["identity_context"]
    assert identity["tenant_id"] == "tenant-test"
    assert identity["user_id"] == "user-test-1"
    assert identity["thread_id"] == "thread-test-1"
    assert identity["session_id"] == command.update["session_id"]
    assert len(set(identity.values())) == 5
    assert command.update["working_memory"]["task_goal"] == "我确认设备型号是 LF-900，请排查冰箱异常噪音"
    assert command.update["working_memory"]["current_intent"] == "general_support"
    persisted_record = command.update["working_memory_lifecycle_records"][-1]
    assert persisted_record["memory"]["lifecycle_state"] == "PERSISTED"
    assert persisted_record["identity_context"] == identity
    assert "task_goal" in persisted_record["attributes"]["changed_fields"]
    assert persisted_record["attributes"]["previous_fingerprint"] != persisted_record["attributes"]["candidate_fingerprint"]
    long_term_records = command.update["long_term_memory_lifecycle_records"]
    assert long_term_records[-1]["memory"]["lifecycle_state"] == "PERSISTED"
    assert long_term_records[-1]["attributes"]["fact_key"] == "product_model"

    repeated_state = {
        "messages": [FakeMessage("我确认设备型号是 LF-900，请排查冰箱异常噪音")],
        **command.update,
    }
    repeated = module.query_router(repeated_state, runtime)
    assert repeated.goto == "supervisor_agent"
    assert "working_memory" not in repeated.update
    assert "working_memory_lifecycle_records" not in repeated.update
    assert "long_term_memory_lifecycle_records" not in repeated.update

    items = ContextBuilder(
        long_term_memory_runtime=module._LONG_TERM_MEMORY_RUNTIME
    ).build(
        messages_state={
            "messages": [FakeMessage("我确认设备型号是 LF-900，请排查冰箱异常噪音")],
            **command.update,
        }
    )
    assert any(item.type is ContextItemType.MEMORY for item in items)
    assert any(
        item.metadata.get("memory_kind") == "long_term_fact"
        and item.metadata.get("fact_key") == "product_model"
        for item in items
    )
    assert all(item.metadata["identity_context"] == identity for item in items)
