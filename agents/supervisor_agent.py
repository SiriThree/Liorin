"""Supervisor agent for TechHub customer support."""

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState

from config import DEFAULT_MODEL, Context


SUPERVISOR_AGENT_SYSTEM_PROMPT = """You are a supervisor agent for TechHub customer support.

Your role is to interact with customers, gather the information needed from specialist agents, and provide helpful final answers.

Capabilities:
- Ask the database_specialist about orders, order items, product prices, inventory, customers, and purchase history.
- Ask the documentation_specialist about product specs, compatibility, warranties, returns, shipping, support policies, and setup instructions.

Important:
- Do not answer database or documentation questions from memory. Use the specialist tools first.
- For customer-specific questions, include the customer's email or customer_id in your database_specialist query.
- Phrase specialist queries from your perspective as the supervisor, not as the customer.
- If the customer asks to cancel an order, check eligibility and then explain the next step; do not claim an order was actually cancelled.
- Use multiple specialists when needed to answer a question fully.

Always provide helpful, accurate, concise, and specific responses.
"""


def create_supervisor_agent(
    database_agent,
    docs_agent,
    state_schema=None,
    use_checkpointer=True,
    model=None,
    system_prompt=None,
):
    """Create the supervisor that routes work to database and docs specialists."""
    llm = init_chat_model(model or DEFAULT_MODEL, configurable_fields=["model"])
    prompt = system_prompt or SUPERVISOR_AGENT_SYSTEM_PROMPT

    @dynamic_prompt
    def supervisor_prompt(request: ModelRequest) -> str:
        customer_id = request.state.get("customer_id", None)
        if customer_id:
            return f"{prompt}\n\nThe customer's ID in this conversation is: {customer_id}"
        return prompt

    @tool(
        "database_specialist",
        description="Query TechHub database specialist for order status, order details, product prices, product availability, customers, and purchase history.",
    )
    def call_database_specialist(query: str) -> str:
        result = database_agent.invoke(
            {"messages": [{"role": "user", "content": query}]}
        )
        return result["messages"][-1].content

    @tool(
        "documentation_specialist",
        description="Query TechHub documentation specialist for product specs, policies, warranties, shipping, returns, compatibility, and setup instructions.",
    )
    def call_documentation_specialist(query: str) -> str:
        result = docs_agent.invoke({"messages": [{"role": "user", "content": query}]})
        return result["messages"][-1].content

    agent_kwargs = {
        "model": llm,
        "tools": [call_database_specialist, call_documentation_specialist],
        "name": "supervisor_agent",
        "state_schema": state_schema or MessagesState,
        "middleware": [supervisor_prompt],
        "context_schema": Context,
    }

    if use_checkpointer:
        agent_kwargs["checkpointer"] = MemorySaver()

    return create_agent(**agent_kwargs)
