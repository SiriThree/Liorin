# Liorin Data Utilities

Utilities for rebuilding local development artifacts from the committed Liorin
dataset.

## Data Sources

- `data/knowledge/manuals`: TraceMind product manuals converted to Markdown.
- `data/knowledge/policies`: Liorin after-sales policy documents.
- `data/structured/*.json`: sample enterprise support data aligned with the
  manuals.
- `evals/tracemind`: copied TraceMind benchmark and public question datasets.

## Commands

```bash
uv run python data/data_generation/create_database.py
uv run python data/data_generation/validate_database.py
uv run python data/data_generation/build_vectorstore.py
```

## Outputs

| Script | Output | Purpose |
|---|---|---|
| `create_database.py` | `data/structured/liorin.db` | SQLite database for Order Agent queries |
| `validate_database.py` | validation report | Integrity checks for the structured dataset |
| `build_vectorstore.py` | `data/vector_stores/liorin_vectorstore_{provider}.pkl` | RAG index for manuals and policies |

The default embedding provider is HuggingFace. Set `EMBEDDING_PROVIDER=openai`
to build the vectorstore with OpenAI embeddings.
