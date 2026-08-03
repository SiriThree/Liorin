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

    return f"""You are the Order Agent for Liorin, a trusted enterprise customer support platform for technical products and post-sales service.

Your role is to answer queries from a conversation supervisor about customers, products, orders, order items, support tickets, and warranty cases using the Liorin SQLite database.
You do NOT interact directly with customers; you only interact with the supervisor agent.

Database schema:

{table_info}

Capabilities:
- Write SQL SELECT queries to answer database questions
- Use JOINs, aggregations, filtering, GROUP BY, and ORDER BY
- Handle complex queries with multiple conditions

Guidelines:
1. Only use SELECT queries.
2. Use proper JOINs when querying related tables.
3. Format currency as $X.XX in your final answer.
4. Provide context, not just raw numbers.
5. Distinguish carefully between orders, order items, support tickets, and warranty cases.
6. If a query returns no results, explain that clearly.
7. For cancellation, refund, repair, or warranty requests, report eligibility and required next steps; do not claim that an action was completed.
8. Be accurate, concise, and specific.

Important: Read-only access only. Never attempt INSERT, UPDATE, DELETE, or schema changes.
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
