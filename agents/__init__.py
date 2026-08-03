"""Shared agent factories for the Liorin support system."""

from agents.conversation_supervisor import (
    SUPERVISOR_AGENT_SYSTEM_PROMPT,
    create_supervisor_agent,
)
from agents.knowledge_agent import (
    KNOWLEDGE_AGENT_BASE_TOOLS,
    KNOWLEDGE_AGENT_SYSTEM_PROMPT,
    create_knowledge_agent,
)
from agents.order_agent import (
    ORDER_AGENT_BASE_TOOLS,
    create_order_agent,
)
from agents.support_workflow import create_support_agent

__all__ = [
    "create_knowledge_agent",
    "KNOWLEDGE_AGENT_SYSTEM_PROMPT",
    "KNOWLEDGE_AGENT_BASE_TOOLS",
    "create_order_agent",
    "ORDER_AGENT_BASE_TOOLS",
    "create_supervisor_agent",
    "SUPERVISOR_AGENT_SYSTEM_PROMPT",
    "create_support_agent",
]
