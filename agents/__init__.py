"""Shared agent factories for the Liorin support system.

The package exposes the same public names as before, but imports factories
only when requested. This keeps isolated Knowledge Agent and benchmark tests
from importing unrelated supervisor/order dependencies.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

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

_EXPORTS = {
    "create_knowledge_agent": ("agents.knowledge_agent", "create_knowledge_agent"),
    "KNOWLEDGE_AGENT_SYSTEM_PROMPT": ("agents.knowledge_agent", "KNOWLEDGE_AGENT_SYSTEM_PROMPT"),
    "KNOWLEDGE_AGENT_BASE_TOOLS": ("agents.knowledge_agent", "KNOWLEDGE_AGENT_BASE_TOOLS"),
    "create_order_agent": ("agents.order_agent", "create_order_agent"),
    "ORDER_AGENT_BASE_TOOLS": ("agents.order_agent", "ORDER_AGENT_BASE_TOOLS"),
    "create_supervisor_agent": ("agents.conversation_supervisor", "create_supervisor_agent"),
    "SUPERVISOR_AGENT_SYSTEM_PROMPT": ("agents.conversation_supervisor", "SUPERVISOR_AGENT_SYSTEM_PROMPT"),
    "create_support_agent": ("agents.support_workflow", "create_support_agent"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr = _EXPORTS[name]
    value = getattr(import_module(module_name), attr)
    globals()[name] = value
    return value
