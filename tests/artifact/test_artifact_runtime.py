from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from artifact import (
    Artifact,
    ArtifactIdentityError,
    ArtifactLifecycleEvent,
    ArtifactLifecycleState,
    ArtifactRegistry,
    ArtifactResolver,
    ArtifactType,
    InMemoryArtifactStore,
)
from context_engine import ContextBuilder, ContextItemType, ContextRuntime, ContextCompressor
from identity import IdentityContext


def _identity(*, user_id: str = "user-42") -> IdentityContext:
    return IdentityContext(
        tenant_id="tenant-acme",
        user_id=user_id,
        conversation_id="conversation-artifact-1",
        thread_id="thread-artifact-1",
        session_id="session-artifact-1",
    )


def _registry() -> ArtifactRegistry:
    return ArtifactRegistry(store=InMemoryArtifactStore())


def test_artifact_model():
    identity = _identity()
    artifact = Artifact(
        artifact_id="artifact-report-1",
        artifact_type=ArtifactType.REPORT,
        identity_context=identity,
        source="report_generator",
        created_at=datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc),
        created_by="report_service",
        summary="客户售后处理报告",
        metadata={"format": "markdown"},
        location="memory://artifact-report-1",
        size=128,
        status=ArtifactLifecycleState.AVAILABLE,
        payload={"content": "报告正文"},
    )

    encoded = json.loads(json.dumps(artifact.to_state(), ensure_ascii=False))
    restored = Artifact.from_state(encoded)

    assert restored == artifact
    assert restored.identity_context == identity
    assert artifact.to_reference()["artifact_id"] == "artifact-report-1"
    assert "payload" not in artifact.to_reference()


def test_artifact_store():
    identity = _identity()
    registry = _registry()
    artifact = registry.create_artifact(
        artifact_type=ArtifactType.DOCUMENT,
        identity_context=identity,
        source="upload",
        created_by="tests",
        summary="uploaded document",
        payload={"content": "document payload"},
    )

    assert registry.get_artifact(
        artifact.artifact_id,
        identity_context=identity,
    ).payload["content"] == "document payload"
    assert registry.list_artifacts(identity_context=identity) == [artifact]

    deleted = registry.delete_artifact(
        artifact.artifact_id,
        identity_context=identity,
        actor="tests",
        reason="test deletion",
    )
    assert deleted.status is ArtifactLifecycleState.DELETED
    assert deleted.payload is None
    assert registry.list_artifacts(identity_context=identity) == []


def test_identity_bound_artifact():
    identity = _identity()
    other = _identity(user_id="user-99")
    registry = _registry()
    artifact = registry.create_artifact(
        artifact_type=ArtifactType.TRACE,
        identity_context=identity,
        source="trace",
        created_by="tests",
        summary="execution trace",
        payload={"events": [1, 2, 3]},
    )

    with pytest.raises(ArtifactIdentityError):
        registry.get_artifact(
            artifact.artifact_id,
            identity_context=other,
        )

    with pytest.raises((TypeError, ValueError)):
        Artifact(
            artifact_id="identity-missing",
            artifact_type=ArtifactType.TRACE,
            identity_context={},
            source="trace",
            created_at=datetime.now(timezone.utc),
            created_by="tests",
            summary="invalid",
            metadata={},
            location="memory://identity-missing",
            size=1,
            status=ArtifactLifecycleState.AVAILABLE,
            payload="x",
        )


def test_context_artifact_reference():
    identity = _identity()
    registry = _registry()
    large_payload = "TOOL_SECRET_PAYLOAD:" + ("诊断结果" * 2_000)
    state = {
        "identity_context": identity.to_state(),
        "messages": [
            {"role": "user", "content": "排查冰箱噪音", "id": "user-1"},
            {
                "role": "assistant",
                "content": "",
                "id": "assistant-1",
                "tool_calls": [{"id": "call-1", "name": "knowledge_agent"}],
            },
            {
                "role": "tool",
                "name": "knowledge_agent",
                "tool_call_id": "call-1",
                "content": large_payload,
                "id": "tool-1",
            },
        ],
    }
    runtime = ContextRuntime(
        max_tokens=512,
        compaction_enabled=False,
        artifact_registry=registry,
    )

    selection = runtime.select(state)
    artifact_item = next(
        item for item in selection.items if item.type is ContextItemType.ARTIFACT_REFERENCE
    )
    bounded = runtime.bounded_model_messages(
        state["messages"],
        selection=selection,
    )

    assert artifact_item.metadata["artifact_type"] == "TOOL_RESULT"
    assert artifact_item.metadata["artifact_id"] in artifact_item.content
    assert "TOOL_SECRET_PAYLOAD" not in artifact_item.content
    assert "TOOL_SECRET_PAYLOAD" not in bounded[-1]["content"]
    assert artifact_item.metadata["artifact_id"] in bounded[-1]["content"]
    assert state["messages"][-1]["content"] == large_payload

    stored = registry.get_artifact(
        artifact_item.metadata["artifact_id"],
        identity_context=identity,
    )
    assert stored.payload["content"] == large_payload


def test_retrieval_evidence_becomes_artifact_reference():
    identity = _identity()
    registry = _registry()
    evidence_payload = "EVIDENCE_FULL_PAYLOAD:" + ("手册正文" * 1_500)
    evidence = {
        "citation_id": "E1",
        "source_type": "manual",
        "document": {
            "page_content": evidence_payload,
            "metadata": {
                "document_id": "manual-1",
                "source_file": "fridge_manual.md",
                "section": "异常噪音",
                "security_status": "safe",
            },
        },
        "trace": [{"stage": "dense"}, {"stage": "rerank"}],
    }
    state = {
        "identity_context": identity.to_state(),
        "messages": [{"role": "user", "content": "如何排查噪音"}],
        "verified_evidences": [evidence],
    }

    item = next(
        item
        for item in ContextBuilder(artifact_registry=registry).build(knowledge_state=state)
        if item.type is ContextItemType.EVIDENCE_REFERENCE
    )

    assert item.metadata["artifact_type"] == "RETRIEVAL_EVIDENCE"
    assert item.metadata["artifact_id"] in item.content
    assert "EVIDENCE_FULL_PAYLOAD" not in item.content
    stored = registry.get_artifact(
        item.metadata["artifact_id"],
        identity_context=identity,
    )
    assert stored.payload["document"]["page_content"] == evidence_payload


def test_lazy_loading():
    identity = _identity()
    registry = _registry()
    artifact = registry.create_artifact(
        artifact_type=ArtifactType.TOOL_RESULT,
        identity_context=identity,
        source="knowledge_agent",
        created_by="tests",
        summary="large tool output",
        payload={"content": "recover-me"},
    )
    resolver = ArtifactResolver(registry)

    payload = resolver.resolve(
        artifact.artifact_id,
        identity_context=identity,
        actor="tests",
        reason="verify lazy loading",
    )
    events = [
        record.event
        for record in registry.lifecycle_records(artifact_id=artifact.artifact_id)
    ]

    assert payload == {"content": "recover-me"}
    assert events[:2] == [
        ArtifactLifecycleEvent.CREATED,
        ArtifactLifecycleEvent.AVAILABLE,
    ]
    assert events[-1] is ArtifactLifecycleEvent.RESOLVED


def test_compaction_artifact_integration():
    identity = _identity()
    registry = _registry()
    marker = "DO_NOT_COPY_ARTIFACT_PAYLOAD"
    messages: list[dict] = [{"role": "user", "content": "开始长任务", "id": "u-0"}]
    for index in range(30):
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "id": f"a-{index}",
                    "tool_calls": [{"id": f"call-{index}", "name": "knowledge_agent"}],
                },
                {
                    "role": "tool",
                    "name": "knowledge_agent",
                    "tool_call_id": f"call-{index}",
                    "id": f"t-{index}",
                    "content": marker + (f"-{index}-" + "payload" * 500),
                },
            ]
        )
    messages.append({"role": "user", "content": "汇总下一步", "id": "u-final"})
    state = {
        "identity_context": identity.to_state(),
        "messages": messages,
    }

    built = ContextBuilder(artifact_registry=registry).build(messages_state=state)
    result = ContextCompressor(recent_message_count=2, summary_max_tokens=256).compact(built)
    summary_state = json.dumps(result.summary.to_state(), ensure_ascii=False)
    artifact_ids = {
        item.metadata["artifact_id"]
        for item in built
        if item.type is ContextItemType.ARTIFACT_REFERENCE
        and item.metadata.get("artifact_id")
    }

    assert len(artifact_ids) == 30
    assert marker not in summary_state
    assert result.attributes["tool_output_content_retained"] is False
    assert result.attributes["artifact_reference_count"] == 30
    assert any(artifact_id in summary_state for artifact_id in artifact_ids)


def test_artifact_lifecycle_audits_reference_resolve_delete():
    identity = _identity()
    registry = _registry()
    artifact = registry.create_artifact(
        artifact_type=ArtifactType.SUMMARY,
        identity_context=identity,
        source="compaction",
        created_by="tests",
        summary="compaction summary artifact",
        payload={"summary": "state"},
    )
    registry.reference_artifact(
        artifact.artifact_id,
        identity_context=identity,
        actor="context_builder",
        reason="inject summary reference",
    )
    ArtifactResolver(registry).resolve(
        artifact.artifact_id,
        identity_context=identity,
        actor="tests",
        reason="read summary",
    )
    registry.delete_artifact(
        artifact.artifact_id,
        identity_context=identity,
        actor="tests",
        reason="cleanup",
    )

    events = [
        record.event.value
        for record in registry.lifecycle_records(artifact_id=artifact.artifact_id)
    ]
    assert events == ["CREATED", "AVAILABLE", "REFERENCED", "RESOLVED", "DELETED"]


def test_supervisor_tool_result_artifact_integration(monkeypatch):
    import importlib.util
    from pathlib import Path
    import sys
    import types

    from artifact import get_default_artifact_registry, reset_default_artifact_registry

    registry = reset_default_artifact_registry()
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
    chat_models_mod.init_chat_model = lambda *args, **kwargs: object()
    tools_mod.tool = fake_tool
    memory_mod.MemorySaver = object
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

    spec = importlib.util.spec_from_file_location(
        "phase4_supervisor_under_test",
        Path("agents/conversation_supervisor.py"),
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.create_supervisor_agent(
        order_agent=object(),
        knowledge_agent=object(),
        use_checkpointer=False,
        context_max_tokens=512,
    )

    prompt_middleware, bounded_middleware = captured["middleware"]
    identity = _identity()
    full_payload = "SUPERVISOR_TOOL_FULL_PAYLOAD" + ("证据" * 3_000)
    messages = [
        {"role": "user", "content": "查手册", "id": "u-runtime"},
        {
            "role": "assistant",
            "content": "",
            "id": "a-runtime",
            "tool_calls": [{"id": "call-runtime", "name": "knowledge_agent"}],
        },
        {
            "role": "tool",
            "name": "knowledge_agent",
            "tool_call_id": "call-runtime",
            "content": full_payload,
            "id": "t-runtime",
        },
    ]
    state = {
        "identity_context": identity.to_state(),
        "messages": messages,
    }
    request = FakeRequest(state=state, messages=messages)

    prompt = prompt_middleware(request)
    forwarded: dict = {}

    def handler(bounded_request):
        forwarded["request"] = bounded_request
        return FakeModelResponse()

    bounded_middleware(request, handler)
    bounded_tool_content = forwarded["request"].messages[-1]["content"]
    reference = json.loads(bounded_tool_content)

    assert "SUPERVISOR_TOOL_FULL_PAYLOAD" not in prompt
    assert "SUPERVISOR_TOOL_FULL_PAYLOAD" not in bounded_tool_content
    assert reference["artifact_type"] == "TOOL_RESULT"
    artifact = get_default_artifact_registry().get_artifact(
        reference["artifact_id"],
        identity_context=identity,
    )
    assert artifact.payload["content"] == full_payload
    assert registry is get_default_artifact_registry()
