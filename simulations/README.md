# Simulations

Automated conversation simulation for the deployed `customer_support_agent`.

The simulator can generate dynamic, data-grounded customer conversations or run
fixed scenarios from `scenarios.json`. It is useful for smoke testing, LangSmith
trace generation, and monitoring dashboards.

## Usage

```bash
uv run python simulations/run_simulation.py
uv run python simulations/run_simulation.py --count 5
uv run python simulations/run_simulation.py --count 3 --mode static
uv run python simulations/run_simulation.py --url https://custom-deployment.langgraph.app
```

## Required Environment

- `LANGSMITH_API_KEY`
- `ANTHROPIC_API_KEY` or another key for `LIORIN_MODEL`
- `LANGGRAPH_DEPLOYMENT_URL`

## Modes

- `dynamic`: query the local TechHub database, choose a customer and archetype,
  then generate a grounded opening query.
- `static`: run hand-authored scenarios from `scenarios.json`.
- `mixed`: combine static and dynamic scenarios.

## Notes

The simulator handles HITL email verification by detecting graph interrupts and
resuming the run with the scenario customer's email address.
