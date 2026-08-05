"""Conversation supervisor for Liorin support."""

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState

from config import DEFAULT_MODEL, Context


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


def create_supervisor_agent(
    order_agent,
    knowledge_agent,
    state_schema=None,
    use_checkpointer=True,
    model=None,
    system_prompt=None,
):
    """Create the supervisor that routes work to order and knowledge specialists."""
    llm = init_chat_model(model or DEFAULT_MODEL, configurable_fields=["model"])
    prompt = system_prompt or SUPERVISOR_AGENT_SYSTEM_PROMPT

    @dynamic_prompt
    def supervisor_prompt(request: ModelRequest) -> str:
        customer_id = request.state.get("customer_id", None)
        if customer_id:
            return f"{prompt}\n\n当前会话已验证客户 ID：{customer_id}"
        return prompt

    @tool(
        "order_agent",
        description="查询 Liorin 订单与结构化数据专员，获取客户、订单状态、订单明细、工单、质保案例、商品价格、库存和购买历史。",
    )
    def call_order_agent(query: str) -> str:
        result = order_agent.invoke(
            {"messages": [{"role": "user", "content": query}]}
        )
        return result["messages"][-1].content

    @tool(
        "knowledge_agent",
        description="查询 Liorin 知识检索专员，获取产品手册、故障排查、售后政策、质保、物流、退换货、兼容性和设置说明。",
    )
    def call_knowledge_agent(query: str) -> str:
        result = knowledge_agent.invoke({"messages": [{"role": "user", "content": query}]})
        return result["messages"][-1].content

    agent_kwargs = {
        "model": llm,
        "tools": [call_order_agent, call_knowledge_agent],
        "name": "conversation_supervisor",
        "state_schema": state_schema or MessagesState,
        "middleware": [supervisor_prompt],
        "context_schema": Context,
    }

    if use_checkpointer:
        agent_kwargs["checkpointer"] = MemorySaver()

    return create_agent(**agent_kwargs)
