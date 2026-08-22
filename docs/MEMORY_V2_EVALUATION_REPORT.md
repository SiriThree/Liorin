# Memory V2 Evaluation Report

## What Was Validated

- V1 working-memory checkpoints migrate into task-scoped state.
- Same-task corrections supersede stale facts instead of keeping conflicting
  active facts.
- Task switches suspend the old task and activate a new one.
- Long-term memory rejects task-local `product_model` and accepts durable
  `owned_product`.
- Context budgeting preserves active working memory before compactable history.
- Hybrid semantic compaction sees only compactable narrative history.
- Semantic compaction failure falls back to deterministic compaction.
- Artifact references remain rehydratable and artifact payloads are not copied
  into compaction summaries.

## Test Results

Commands run locally:

- `uv run pytest tests/memory tests/context_engine -q`
  - Result: `50 passed`
- `uv run pytest tests/artifact -q`
  - Result: `10 passed`
- `$env:OPENAI_API_KEY='dummy'; uv run pytest tests/governance tests/production -q`
  - Result: `27 passed`
- `uv run python -m compileall context_engine memory tests/context_engine tests/memory`
  - Result: passed

The dummy API key was used only to allow modules with LangChain/OpenAI
initialization to import during local tests. No external LLM behavior is part of
these assertions.

## Residual Risk

The semantic compactor is implemented as an injectable callable. Production
wiring can choose the real model client later, but the safety boundary and
fallback behavior are already covered by deterministic tests.

