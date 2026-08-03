"""Documentation retrieval agent for TechHub customer support."""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState

from config import DEFAULT_MODEL, Context
from tools import search_policy_docs, search_product_docs


DOCS_AGENT_SYSTEM_PROMPT = """You are the company policy and product information specialist for TechHub customer support.

Your role is to answer queries from a supervisor agent about product specifications, features, compatibility, policies, warranties, shipping, returns, and setup instructions.
You do NOT interact directly with customers; you only interact with the supervisor agent.

Instructions:
- Always search the documentation before answering.
- If information is missing or not found, say so clearly.
- Do not provide information that is not supported by the retrieved documentation.
- Be accurate, concise, and specific.
"""

DOCS_AGENT_BASE_TOOLS = [
    search_product_docs,
    search_policy_docs,
]


def create_docs_agent(
    state_schema=None,
    use_checkpointer=True,
    model=None,
    system_prompt=None,
):
    """Create a documentation specialist agent."""
    llm = init_chat_model(model or DEFAULT_MODEL, configurable_fields=["model"])

    agent_kwargs = {
        "model": llm,
        "tools": DOCS_AGENT_BASE_TOOLS.copy(),
        "name": "docs_agent",
        "system_prompt": system_prompt or DOCS_AGENT_SYSTEM_PROMPT,
        "state_schema": state_schema or MessagesState,
        "context_schema": Context,
    }

    if use_checkpointer:
        agent_kwargs["checkpointer"] = MemorySaver()

    return create_agent(**agent_kwargs)
