"""Deployment configuration for the TechHub customer support agent."""

from agents.docs_agent import create_docs_agent
from agents.sql_agent import create_sql_agent
from agents.supervisor_hitl_agent import create_supervisor_hitl_agent

sql_agent = create_sql_agent(use_checkpointer=False)
docs_agent = create_docs_agent(use_checkpointer=False)

graph = create_supervisor_hitl_agent(
    database_agent=sql_agent,
    docs_agent=docs_agent,
    use_checkpointer=False,
)
