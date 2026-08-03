"""Conversation supervisor for Liorin support."""

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, dynamic_prompt
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState

from config import DEFAULT_MODEL, Context


SUPERVISOR_AGENT_SYSTEM_PROMPT = """You are the Conversation Supervisor for Liorin, a trusted enterprise customer support platform for technical products and post-sales service.

Your role is to interact with customers, gather the information needed from specialist agents, and provide helpful final answers.

Capabilities:
- Ask the order_agent about customers, orders, order items, support tickets, warranty cases, product prices, inventory, and purchase history.
- Ask the knowledge_agent about product manuals, troubleshooting, specs, compatibility, warranties, returns, shipping, support policies, and setup instructions.

Important:
- Do not answer database or documentation questions from memory. Use the specialist tools first.
- For customer-specific questions, include the customer's email or customer_id in your order_agent query.
- Phrase specialist queries from your perspective as the supervisor, not as the customer.
- If the customer asks to cancel an order, request a refund, create a repair ticket, or change account/order state, check eligibility and explain the next step; do not claim the action was actually completed.
- Use multiple specialists when needed to answer a question fully.

Always provide helpful, accurate, concise, and specific responses.
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
            return f"{prompt}\n\nThe customer's ID in this conversation is: {customer_id}"
        return prompt

    @tool(
        "order_agent",
        description="Query Liorin order specialist for customers, order status, order details, tickets, warranty cases, product prices, inventory, and purchase history.",
    )
    def call_order_agent(query: str) -> str:
        result = order_agent.invoke(
            {"messages": [{"role": "user", "content": query}]}
        )
        return result["messages"][-1].content

    @tool(
        "knowledge_agent",
        description="Query Liorin knowledge specialist for manuals, troubleshooting, policies, warranties, shipping, returns, compatibility, and setup instructions.",
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
