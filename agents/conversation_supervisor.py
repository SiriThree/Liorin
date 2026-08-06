"""Conversation supervisor for Liorin support."""

from __future__ import annotations

from collections.abc import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRequest,
    ModelResponse,
    dynamic_prompt,
    wrap_model_call,
)
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState

from config import (
    DEFAULT_CONTEXT_COMPACTION_ENABLED,
    DEFAULT_CONTEXT_COMPACTION_ITEM_THRESHOLD,
    DEFAULT_CONTEXT_COMPACTION_RECENT_MESSAGES,
    DEFAULT_CONTEXT_COMPACTION_SUMMARY_MAX_TOKENS,
    DEFAULT_CONTEXT_MAX_TOKENS,
    DEFAULT_LONG_TERM_MEMORY_ENABLED,
    DEFAULT_LONG_TERM_MEMORY_RETRIEVAL_LIMIT,
    DEFAULT_MODEL,
    DEFAULT_TOOL_RETRY_ATTEMPTS,
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    Context,
)
from context_engine import ContextRuntime
from identity import IdentityResolver
from observability import RuntimeEventType, get_default_metrics, get_default_trace_recorder, invoke_observed_tool
from reliability import RetryPolicy


SUPERVISOR_AGENT_SYSTEM_PROMPT = """你是 Liorin 的会话主管。Liorin 是一个面向企业技术产品与售后服务的可信客服 Agent 平台。

你的职责是直接与客户沟通，判断问题类型，向专业 Agent 获取必要信息，并给客户提供清楚、有帮助的最终答复。

可调用能力：
- 向 order_agent 查询客户、订单、订单明细、售后工单、工单事件、质保案例、商品价格、库存和购买历史。
- 向 knowledge_agent 查询产品手册、故障排查、规格、兼容性、质保、退换货、物流、售后政策和安装/设置说明。

重要规则：
- 不要凭记忆回答数据库或文档问题，必须先调用相应专业 Agent。
- 涉及具体客户的问题，向 order_agent 查询时必须带上客户邮箱或 customer_id。
- 向专业 Agent 提问时，要用主管视角描述任务，不要直接照抄客户口吻。
- 如果客户要求取消订单、申请退款、创建维修工单或修改账户/订单状态，只能检查资格并说明下一步，不要声称已经完成真实业务动作。
- 一个问题需要多类信息时，应同时或依次调用多个专业 Agent。
- 默认使用中文回复客户；只有客户明确要求英文时才使用英文。

最终回复必须有帮助、准确、简洁、具体。
"""


def _request_context_budget(request: ModelRequest, fallback: int) -> int:
    runtime = getattr(request, "runtime", None)
    runtime_context = getattr(runtime, "context", None)
    configured = getattr(runtime_context, "context_max_tokens", fallback)
    try:
        value = int(configured)
    except (TypeError, ValueError):
        value = fallback
    return max(1, value)


def _request_compaction_options(request: ModelRequest) -> dict[str, object]:
    runtime = getattr(request, "runtime", None)
    runtime_context = getattr(runtime, "context", None)
    return {
        "compaction_enabled": getattr(
            runtime_context,
            "context_compaction_enabled",
            DEFAULT_CONTEXT_COMPACTION_ENABLED,
        ),
        "compaction_item_threshold": getattr(
            runtime_context,
            "context_compaction_item_threshold",
            DEFAULT_CONTEXT_COMPACTION_ITEM_THRESHOLD,
        ),
        "compaction_recent_messages": getattr(
            runtime_context,
            "context_compaction_recent_messages",
            DEFAULT_CONTEXT_COMPACTION_RECENT_MESSAGES,
        ),
        "compaction_summary_max_tokens": getattr(
            runtime_context,
            "context_compaction_summary_max_tokens",
            DEFAULT_CONTEXT_COMPACTION_SUMMARY_MAX_TOKENS,
        ),
    }


def _request_long_term_memory_options(request: ModelRequest) -> dict[str, object]:
    runtime = getattr(request, "runtime", None)
    runtime_context = getattr(runtime, "context", None)
    return {
        "long_term_memory_enabled": getattr(
            runtime_context,
            "long_term_memory_enabled",
            DEFAULT_LONG_TERM_MEMORY_ENABLED,
        ),
        "long_term_memory_limit": getattr(
            runtime_context,
            "long_term_memory_retrieval_limit",
            DEFAULT_LONG_TERM_MEMORY_RETRIEVAL_LIMIT,
        ),
    }


def build_supervisor_context_prompt(
    base_prompt: str,
    state: dict,
    *,
    max_tokens: int = DEFAULT_CONTEXT_MAX_TOKENS,
    compaction_enabled: bool = DEFAULT_CONTEXT_COMPACTION_ENABLED,
    compaction_item_threshold: int = DEFAULT_CONTEXT_COMPACTION_ITEM_THRESHOLD,
    compaction_recent_messages: int = DEFAULT_CONTEXT_COMPACTION_RECENT_MESSAGES,
    compaction_summary_max_tokens: int = DEFAULT_CONTEXT_COMPACTION_SUMMARY_MAX_TOKENS,
    long_term_memory_enabled: bool = DEFAULT_LONG_TERM_MEMORY_ENABLED,
    long_term_memory_limit: int = DEFAULT_LONG_TERM_MEMORY_RETRIEVAL_LIMIT,
) -> str:
    """Build the supervisor prompt through the shared Context Runtime.

    This helper is intentionally pure enough for unit tests and evaluation
    adapters.  It does not persist memory or mutate graph state.
    """

    return ContextRuntime(
        max_tokens=max_tokens,
        compaction_enabled=compaction_enabled,
        compaction_item_threshold=compaction_item_threshold,
        compaction_recent_messages=compaction_recent_messages,
        compaction_summary_max_tokens=compaction_summary_max_tokens,
        long_term_memory_enabled=long_term_memory_enabled,
        long_term_memory_limit=long_term_memory_limit,
    ).build_prompt(base_prompt, state)


def create_supervisor_agent(
    order_agent,
    knowledge_agent,
    state_schema=None,
    use_checkpointer=True,
    model=None,
    system_prompt=None,
    context_max_tokens: int = DEFAULT_CONTEXT_MAX_TOKENS,
):
    """Create the supervisor that routes work to order and knowledge specialists."""
    llm = init_chat_model(model or DEFAULT_MODEL, configurable_fields=["model"])
    prompt = system_prompt or SUPERVISOR_AGENT_SYSTEM_PROMPT

    @dynamic_prompt
    def supervisor_prompt(request: ModelRequest) -> str:
        budget = _request_context_budget(request, context_max_tokens)
        return build_supervisor_context_prompt(
            prompt,
            request.state,
            max_tokens=budget,
            **_request_compaction_options(request),
            **_request_long_term_memory_options(request),
        )

    @wrap_model_call
    def bounded_model_context(
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Expose only the active trajectory as raw model messages.

        Full MessagesState remains in the graph checkpoint for recovery and
        audit.  Relevant history is represented by ContextItems in the dynamic
        system prompt, so the supervisor no longer sends the entire thread to
        the model on every ReAct step.
        """

        recorder = get_default_trace_recorder()
        identity = IdentityResolver().restore(request.state)
        conversation_id = identity.conversation_id if identity else str(request.state.get("conversation_id") or "conversation:unknown")
        thread_id = identity.thread_id if identity else str(request.state.get("thread_id") or "thread:unknown")
        request_id = str(request.state.get("request_id") or f"{thread_id}:model:{len(request.messages)}")

        def invoke_model() -> ModelResponse:
            budget = _request_context_budget(request, context_max_tokens)
            context_runtime = ContextRuntime(
                max_tokens=budget,
                **_request_compaction_options(request),
                **_request_long_term_memory_options(request),
            )
            selection = context_runtime.select(request.state)
            bounded_messages = context_runtime.bounded_model_messages(
                request.messages,
                selection=selection,
            )
            get_default_metrics().increment("prompt_tokens", selection.selected_tokens)
            response = handler(request.override(messages=bounded_messages))
            usage = getattr(response, "usage_metadata", None) or getattr(response, "response_metadata", None) or {}
            completion_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0) if isinstance(usage, dict) else 0
            if completion_tokens:
                get_default_metrics().increment("completion_tokens", completion_tokens)
            recorder.emit(
                RuntimeEventType.MODEL_CALL,
                attributes={
                    "prompt_tokens": selection.selected_tokens,
                    "completion_tokens": completion_tokens,
                    "message_count": len(bounded_messages),
                    "context_manifest": selection.to_manifest(),
                },
            )
            return response

        if recorder.current() is not None:
            return invoke_model()
        with recorder.trace(
            request_id=request_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            agent_name="conversation_supervisor",
        ):
            return invoke_model()

    @tool(
        "order_agent",
        description="查询 Liorin 订单与结构化数据专员，获取客户、订单状态、订单明细、工单、质保案例、商品价格、库存和购买历史。",
    )
    def call_order_agent(query: str) -> str:
        result = invoke_observed_tool(
            "order_agent",
            lambda: order_agent.invoke({"messages": [{"role": "user", "content": query}]}),
            timeout_seconds=DEFAULT_TOOL_TIMEOUT_SECONDS,
            retry_policy=RetryPolicy(max_attempts=DEFAULT_TOOL_RETRY_ATTEMPTS),
            input_preview=query,
        )
        return result["messages"][-1].content

    @tool(
        "knowledge_agent",
        description="查询 Liorin 知识检索专员，获取产品手册、故障排查、售后政策、质保、物流、退换货、兼容性和设置说明。",
    )
    def call_knowledge_agent(query: str) -> str:
        result = invoke_observed_tool(
            "knowledge_agent",
            lambda: knowledge_agent.invoke({"messages": [{"role": "user", "content": query}]}),
            timeout_seconds=DEFAULT_TOOL_TIMEOUT_SECONDS,
            retry_policy=RetryPolicy(max_attempts=DEFAULT_TOOL_RETRY_ATTEMPTS),
            input_preview=query,
        )
        return result["messages"][-1].content

    agent_kwargs = {
        "model": llm,
        "tools": [call_order_agent, call_knowledge_agent],
        "name": "conversation_supervisor",
        "state_schema": state_schema or MessagesState,
        "middleware": [supervisor_prompt, bounded_model_context],
        "context_schema": Context,
    }

    if use_checkpointer:
        agent_kwargs["checkpointer"] = MemorySaver()

    return create_agent(**agent_kwargs)
