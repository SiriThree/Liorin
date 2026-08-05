"""Order and structured-data agent for Liorin support."""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState

from config import DEFAULT_MODEL, Context
from tools.database import execute_sql, get_database


def _create_order_system_prompt() -> str:
    """Generate an order specialist prompt with the live table schema."""
    db = get_database()
    table_info = db.get_table_info()

    return f"""你是 Liorin 的订单与结构化数据专员。Liorin 是一个面向企业技术产品与售后服务的可信客服 Agent 平台。

你的职责是使用 Liorin SQLite 数据库，回答会话主管转来的客户、产品、订单、订单明细、售后工单、质保案例和生命周期事件相关问题。
你不直接面对客户，只与会话主管 Agent 交互。

数据库表结构：

{table_info}

能力边界：
- 编写 SQL SELECT 查询来回答数据库问题。
- 可以使用 JOIN、聚合、过滤、GROUP BY 和 ORDER BY。
- 可以处理包含多个条件的复杂查询。

工作规则：
1. 只能使用 SELECT 查询。
2. 查询关联表时必须使用正确的 JOIN。
3. 最终回答中的金额使用“¥X.XX”格式。
4. 回答要提供上下文，不要只给原始数字。
5. 必须仔细区分订单、订单明细、售后工单、工单事件、质保案例和订单状态事件。
6. 如果查询没有结果，要明确说明未找到。
7. 涉及取消订单、退款、维修或质保请求时，只能说明资格和下一步，不要声称已经完成真实业务动作。
8. 回答要准确、简洁、具体。
9. 默认使用中文回答；只有主管明确要求英文时才使用英文。

重要限制：数据库只读。严禁尝试 INSERT、UPDATE、DELETE 或修改表结构。
"""


ORDER_AGENT_BASE_TOOLS = [execute_sql]


def create_order_agent(
    state_schema=None,
    additional_tools=None,
    use_checkpointer=True,
    model=None,
    system_prompt=None,
):
    """Create an order and structured-data specialist agent."""
    llm = init_chat_model(model or DEFAULT_MODEL, configurable_fields=["model"])
    tools = ORDER_AGENT_BASE_TOOLS.copy()
    if additional_tools:
        tools.extend(additional_tools)

    agent_kwargs = {
        "model": llm,
        "tools": tools,
        "name": "order_agent",
        "system_prompt": system_prompt or _create_order_system_prompt(),
        "state_schema": state_schema or MessagesState,
        "context_schema": Context,
    }

    if use_checkpointer:
        agent_kwargs["checkpointer"] = MemorySaver()

    return create_agent(**agent_kwargs)
