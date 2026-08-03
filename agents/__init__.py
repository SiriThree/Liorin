"""Shared agent factories for the TechHub customer support system."""

from agents.docs_agent import (
    DOCS_AGENT_BASE_TOOLS,
    DOCS_AGENT_SYSTEM_PROMPT,
    create_docs_agent,
)
from agents.sql_agent import SQL_AGENT_BASE_TOOLS, create_sql_agent
from agents.supervisor_agent import (
    SUPERVISOR_AGENT_SYSTEM_PROMPT,
    create_supervisor_agent,
)
from agents.supervisor_hitl_agent import create_supervisor_hitl_agent

__all__ = [
    "create_docs_agent",
    "DOCS_AGENT_SYSTEM_PROMPT",
    "DOCS_AGENT_BASE_TOOLS",
    "create_sql_agent",
    "SQL_AGENT_BASE_TOOLS",
    "create_supervisor_agent",
    "SUPERVISOR_AGENT_SYSTEM_PROMPT",
    "create_supervisor_hitl_agent",
]
