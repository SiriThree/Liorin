"""Deployment configuration for the Liorin support agent."""

from production import bootstrap_production_runtime

production_runtime = bootstrap_production_runtime()

from agents.knowledge_agent import create_knowledge_agent
from agents.order_agent import create_order_agent
from agents.support_workflow import create_support_agent

order_agent = create_order_agent(use_checkpointer=False)
knowledge_agent = create_knowledge_agent(use_checkpointer=False)

graph = create_support_agent(
    order_agent=order_agent,
    knowledge_agent=knowledge_agent,
    use_checkpointer=False,
)
