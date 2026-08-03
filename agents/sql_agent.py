"""SQL agent for TechHub customer support."""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState

from config import DEFAULT_MODEL, Context
from tools.database import execute_sql, get_database


def _create_sql_system_prompt() -> str:
    """Generate a SQL specialist prompt with the live table schema."""
    db = get_database()
    table_info = db.get_table_info()

    return f"""You are a database specialist for TechHub customer support.

Your role is to answer queries from a supervisor agent about orders, products, customers, and purchase history using the TechHub SQLite database.
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
5. Distinguish carefully between orders and order items.
6. If a query returns no results, explain that clearly.
7. Be accurate, concise, and specific.

Important: Read-only access only. Never attempt INSERT, UPDATE, DELETE, or schema changes.
"""


SQL_AGENT_BASE_TOOLS = [execute_sql]


def create_sql_agent(
    state_schema=None,
    additional_tools=None,
    use_checkpointer=True,
    model=None,
    system_prompt=None,
):
    """Create a SQL database specialist agent."""
    llm = init_chat_model(model or DEFAULT_MODEL, configurable_fields=["model"])
    tools = SQL_AGENT_BASE_TOOLS.copy()
    if additional_tools:
        tools.extend(additional_tools)

    agent_kwargs = {
        "model": llm,
        "tools": tools,
        "name": "sql_agent",
        "system_prompt": system_prompt or _create_sql_system_prompt(),
        "state_schema": state_schema or MessagesState,
        "context_schema": Context,
    }

    if use_checkpointer:
        agent_kwargs["checkpointer"] = MemorySaver()

    return create_agent(**agent_kwargs)
