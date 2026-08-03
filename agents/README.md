# Agents

Reusable agent factories for the TechHub support system.

| Agent | Purpose |
|---|---|
| `sql_agent.py` | Answers database questions with read-only SQL queries. |
| `docs_agent.py` | Retrieves product documentation and policy information. |
| `supervisor_agent.py` | Routes customer questions to the right specialist. |
| `supervisor_hitl_agent.py` | Adds customer verification before account-specific work. |

The production graph is created by `create_supervisor_hitl_agent()`, which
defaults to the SQL database specialist and documentation specialist.
