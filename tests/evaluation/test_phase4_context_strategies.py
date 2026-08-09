from __future__ import annotations

from context_engine import ContextItemType, ContextRuntime
from context_engine.strategy import ContextEvaluationStrategy, ContextStrategyConfig
from identity import IdentityContext


def _state():
    identity = IdentityContext(
        tenant_id="tenant:t", user_id="user:u", conversation_id="conversation:c",
        thread_id="thread:t", session_id="session:s",
    )
    return {
        "identity_context": identity.to_state(),
        "messages": [
            {"role":"user","content":"first product FR-100"},
            {"role":"assistant","content":"noted"},
            {"role":"user","content":"second product FR-200"},
            {"role":"assistant","content":"updated"},
            {"role":"user","content":"what about this one?"},
        ],
    }


def test_full_history_retains_all_conversation_messages():
    runtime=ContextRuntime(max_tokens=10000,strategy=ContextEvaluationStrategy.FULL_HISTORY)
    selection=runtime.select(_state())
    history=[x for x in selection.items if x.source=="messages_state"]
    assert [x.metadata.get("sequence") for x in history] == [0,1,2,3,4]
    assert selection.runtime_metadata["strategy"]["selector_enabled"] is False
    assert selection.runtime_metadata["strategy"]["compaction_enabled"] is False


def test_sliding_window_retains_last_turn_and_current():
    runtime=ContextRuntime(max_tokens=10000,strategy=ContextEvaluationStrategy.SLIDING_WINDOW,sliding_window_turns=2)
    selection=runtime.select(_state())
    seq=[x.metadata.get("sequence") for x in selection.items if x.source=="messages_state"]
    assert seq == [2,3,4]


def test_summary_only_uses_existing_compactor_and_drops_raw_old_history():
    state=_state()
    state["messages"]=[
        {**msg, "content": msg["content"] + " detail"*120}
        if i < 4 else msg
        for i,msg in enumerate(state["messages"])
    ]
    runtime=ContextRuntime(max_tokens=10000,strategy=ContextEvaluationStrategy.SUMMARY_ONLY)
    selection=runtime.select(state)
    assert selection.runtime_metadata["compaction"]["applied"] is True
    assert any(x.type is ContextItemType.SUMMARY for x in selection.items)
    raw_old=[x for x in selection.items if x.source=="messages_state" and not x.metadata.get("is_current")]
    assert not raw_old


def test_liorin_context_and_full_toggle_real_memory_artifact_switches():
    base=ContextStrategyConfig.for_strategy(ContextEvaluationStrategy.LIORIN_CONTEXT)
    full=ContextStrategyConfig.for_strategy(ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT)
    assert base.working_memory_enabled is True
    assert base.long_term_memory_enabled is False
    assert base.artifact_enabled is False
    assert full.working_memory_enabled is True
    assert full.long_term_memory_enabled is True
    assert full.artifact_enabled is True


def test_artifact_disabled_full_history_does_not_replace_historical_tool_payload_with_placeholder():
    identity=IdentityContext("tenant:t","user:u","conversation:c","thread:t","session:s")
    state={"identity_context":identity.to_state(),"messages":[
        {"role":"user","content":"first"},
        {"role":"tool","content":"X"*5000,"name":"big_tool"},
        {"role":"assistant","content":"ok"},
        {"role":"user","content":"second"},
    ]}
    runtime=ContextRuntime(max_tokens=20000,strategy=ContextEvaluationStrategy.FULL_HISTORY)
    selection=runtime.select(state)
    tool=next(x for x in selection.items if x.metadata.get("role")=="tool")
    assert "identity_missing" not in tool.metadata.get("artifact_reference_status","")
    assert "unbound placeholder" not in tool.content
