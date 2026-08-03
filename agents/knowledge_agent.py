"""Knowledge retrieval agent for Liorin support."""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import MessagesState

from config import DEFAULT_MODEL, Context
from tools import search_manuals, search_support_policies


KNOWLEDGE_AGENT_SYSTEM_PROMPT = """You are the Knowledge Agent for Liorin, a trusted enterprise customer support platform for technical products and post-sales service.

Your role is to answer queries from a conversation supervisor about product manuals, troubleshooting, operating instructions, safety notes, warranty policy, returns, repair intake, refunds, and shipping.
You do NOT interact directly with customers; you only interact with the supervisor agent.

Instructions:
- Always search the TraceMind-derived manuals or Liorin policies before answering.
- If information is missing or not found, say so clearly.
- Do not provide information that is not supported by the retrieved documentation.
- Be accurate, concise, and specific.
"""

KNOWLEDGE_AGENT_BASE_TOOLS = [
    search_manuals,
    search_support_policies,
]


def create_knowledge_agent(
    state_schema=None,
    use_checkpointer=True,
    model=None,
    system_prompt=None,
):
    """Create a product knowledge and policy specialist agent."""
    llm = init_chat_model(model or DEFAULT_MODEL, configurable_fields=["model"])

    agent_kwargs = {
        "model": llm,
        "tools": KNOWLEDGE_AGENT_BASE_TOOLS.copy(),
        "name": "knowledge_agent",
        "system_prompt": system_prompt or KNOWLEDGE_AGENT_SYSTEM_PROMPT,
        "state_schema": state_schema or MessagesState,
        "context_schema": Context,
    }

    if use_checkpointer:
        agent_kwargs["checkpointer"] = MemorySaver()

    return create_agent(**agent_kwargs)
