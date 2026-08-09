"""Order and structured-data agent for Liorin support.

Production hardening note (Phase 7): the specialist no longer accepts or
constructs arbitrary SQL.  It selects one allow-listed, principal-bound read
operation exposed by :func:`tools.database.execute_sql_template`.
"""

from __future__ import annotations

from langchain.agents import AgentState, create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import MemorySaver

from config import DEFAULT_MODEL, Context
from tools.database import SQL_TEMPLATES, execute_sql_template


class OrderAgentState(AgentState, total=False):
    """Internal specialist state carrying trusted support-workflow identity.

    These fields are injected by the supervisor from its runtime state; they are
    not model-visible tool arguments.  ``structured_permissions`` is an
    internal capability minted only after successful customer verification.
    """

    customer_id: str
    tenant_id: str
    identity_context: dict[str, str]
    structured_permissions: list[str]


def _template_catalog() -> str:
    rows = []
    for template_id, template in SQL_TEMPLATES.items():
        entity_requirement = "需要 entity_id" if "entity_id" in template.parameter_order else "不需要 entity_id"
        rows.append(f"- {template_id}: {template.description}（{entity_requirement}）")
    return "\n".join(rows)


def _create_order_system_prompt() -> str:
    """Generate the specialist prompt from the live safe-template registry."""

    return f"""你是 Liorin 的订单与结构化数据专员。Liorin 是一个面向企业技术产品与售后服务的可信客服 Agent 平台。

你的职责是使用**固定、只读、已授权的结构化查询模板**回答会话主管转来的客户、订单、订单明细、售后工单、工单事件和质保案例问题。
你不直接面对客户，只与会话主管 Agent 交互。

允许的结构化查询模板：
{_template_catalog()}

工作方式：
1. 只调用 execute_sql_template；不要生成、拼接或输出 SQL。
2. 根据问题选择 template_id；只有模板明确要求时才传 entity_id（例如订单号或工单号）。
3. 租户、客户身份和读取权限由运行时可信状态注入，严禁要求模型填写 tenant_id、customer_id 或权限字段。
4. 如果工具返回“被拒绝”“未找到”或失败信息，必须如实说明，不要绕过权限或改用自由 SQL。
5. 最终回答中的金额使用“¥X.XX”格式。
6. 回答要提供上下文，不要只给原始数字。
7. 必须仔细区分订单、订单明细、售后工单、工单事件和质保案例。
8. 涉及取消订单、退款、维修或质保请求时，只能说明资格和下一步，不要声称已经完成真实业务动作。
9. 默认使用中文回答；只有主管明确要求英文时才使用英文。

重要限制：数据库只读；任意 SQL 入口已经停用。你只能选择上述 allow-listed template。
"""


ORDER_AGENT_BASE_TOOLS = [execute_sql_template]


def create_order_agent(
    state_schema=None,
    additional_tools=None,
    use_checkpointer=True,
    model=None,
    system_prompt=None,
):
    """Create the principal-bound order and structured-data specialist agent."""
    llm = init_chat_model(model or DEFAULT_MODEL, configurable_fields=["model"])
    tools = ORDER_AGENT_BASE_TOOLS.copy()
    if additional_tools:
        tools.extend(additional_tools)

    agent_kwargs = {
        "model": llm,
        "tools": tools,
        "name": "order_agent",
        "system_prompt": system_prompt or _create_order_system_prompt(),
        "state_schema": state_schema or OrderAgentState,
        "context_schema": Context,
    }

    if use_checkpointer:
        agent_kwargs["checkpointer"] = MemorySaver()

    return create_agent(**agent_kwargs)
