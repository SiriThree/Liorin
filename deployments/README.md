# Deployments

This directory contains the production LangGraph entrypoint for Liorin.

`support_agent_graph.py` exports `graph`, which is referenced by
`langgraph.json` as `support_agent`.

The graph disables local checkpointers because LangGraph deployment provides
managed persistence.
