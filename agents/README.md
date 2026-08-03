# Agents

Reusable agent factories for the Liorin support system.

| Agent | Purpose |
|---|---|
| `order_agent.py` | Answers structured-data questions with read-only SQL queries. |
| `knowledge_agent.py` | Retrieves TraceMind product manuals and Liorin policy information. |
| `conversation_supervisor.py` | Routes customer questions to the right specialist. |
| `support_workflow.py` | Adds customer verification before account-specific work. |

The production graph is created by `create_support_agent()`, which defaults to
the Order Agent and Knowledge Agent behind the Conversation Supervisor.
