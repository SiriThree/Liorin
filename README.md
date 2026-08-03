# Liorin

Liorin is a LangGraph customer support agent for TechHub, a synthetic technology
e-commerce store. It answers customer questions by combining:

- SQL access to order, customer, product, and order-item data
- Retrieval over product documentation and store policies
- Customer email verification for account- and order-specific requests
- A supervisor that routes work to database and documentation specialists

## Architecture

```text
customer_support_agent
  -> query_router
  -> verify_customer / collect_email
  -> supervisor_agent
      -> sql_agent
      -> docs_agent
```

The single production graph is configured in `langgraph.json` as
`customer_support_agent`.

## Setup

Install dependencies with `uv`:

```bash
uv sync
```

Create a `.env` file from the example and add the model provider keys you plan
to use:

```bash
cp .env.example .env
```

By default, the agent uses:

- `LIORIN_MODEL=anthropic:claude-haiku-4-5`
- `EMBEDDING_PROVIDER=huggingface`

The vector store is generated on demand, or you can build it explicitly:

```bash
uv run python data/data_generation/build_vectorstore.py
```

## Run Locally

Start LangGraph locally:

```bash
uv run langgraph dev
```

The graph exposed by the local server is `customer_support_agent`.

## Project Structure

```text
agents/
  sql_agent.py                 # SQL database specialist
  docs_agent.py                # Product and policy documentation specialist
  supervisor_agent.py          # Routes between specialists
  supervisor_hitl_agent.py     # Verification + supervisor graph
tools/
  database.py                  # Read-only SQL execution and DB connection
  documents.py                 # Product and policy retrieval tools
deployments/
  customer_support_agent_graph.py
evals/
  baseline_dataset.json
  run_ci_eval.py
evaluators/
simulations/
data/
config.py
langgraph.json
```

## Evaluation

The CI regression gate runs the production agent against
`evals/baseline_dataset.json` with correctness and tool-call evaluators:

```bash
uv run python evals/run_ci_eval.py --threshold 0.8
```

This requires `LANGSMITH_API_KEY` and a model provider key in the environment.

## Data

The included TechHub dataset is synthetic:

- 50 customers
- 25 products
- 250 orders
- 439 order items
- 30 Markdown documents for product specs, compatibility, support, warranty,
  shipping, and returns

The SQLite database is at `data/structured/techhub.db`.
