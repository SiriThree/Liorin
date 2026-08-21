# Entity-Scoped Retrieval Refactor

## 1. Before

The audited production entry point was `retrieval.hybrid_retriever.hybrid_retrieve`.
Before this refactor, one subquery could invoke:

```text
Dense Milvus
+ Sparse BM25
+ Structured Database when business entities exist
-> weighted Reciprocal Rank Fusion
-> coarse rerank
-> parent expansion
-> final rerank
```

`_query_aware_weights()` increased metadata weight for product model/error-code
queries and database weight for order/ticket/customer entities. Metadata is no
longer used this way after the latest change.

## 2. Problems

- Route leakage: `source=manual` could still invoke structured database when
  `QueryUnderstanding` contained an order, ticket, or customer entity.
- Metadata responsibility confusion: metadata lookup was both an exact locator
  and a third ranked list in normal document RRF.
- Structured/unstructured score mixing: authoritative database state entered the
  same RRF as document relevance rankings.
- BM25 full-corpus scan: metadata filters were applied before scoring, but BM25
  still iterated every corpus document to reach that check.
- Global query-aware weights: metadata/database importance was hard-coded into
  fusion rather than expressed by explicit routing.

## 3. After

The new mode is behind `AgentFeatureConfig.entity_scoped_routing_enabled`, which
defaults to `False`.

When enabled, one subquery is resolved into exactly one route:

```text
STRUCTURED_DATABASE:
  source=database/structured_db or retrieval_mode=database
  -> database_search only

METADATA_EXACT:
  source=metadata or retrieval_mode=metadata
  -> metadata_direct_lookup only

DOCUMENT_HYBRID:
  manual/policy/faq/ticket_history/all
  -> deterministic search scope
  -> Dense || BM25
  -> Dense/BM25-only RRF
  -> rerank
  -> parent expansion
  -> final rerank
```

Dense and BM25 use the same effective scoped filters. Metadata and structured
database no longer enter document-route RRF in the new mode.

In the default path, `metadata_direct_lookup` has also been removed as an
automatic recall lane. It remains available only when the planner explicitly
requests `source=metadata` or `retrieval_mode=metadata`, where it acts as an
exact locator instead of a competing ranked-list retriever.

## 4. File Changes

- `agents/feature_flags.py`: added `entity_scoped_routing_enabled=False`.
- `agents/knowledge_agent.py`: passes the feature flag into production retrieval
  execution.
- `retrieval/router.py`: new deterministic route resolver and search-scope
  derivation.
- `retrieval/hybrid_retriever.py`: added the routed entity-scoped path and
  removed automatic metadata recall from the default path. Explicit metadata
  requests still run as exact locator lookups.
- `retrieval/sparse_retriever.py`: added metadata postings and scoped candidate
  indices for BM25, with trace counters for corpus, scoped candidates, and scored
  docs.
- `retrieval/reranker.py`: made heuristic reranking use lightweight local term
  extraction so a simple rerank does not cold-load BM25/Jieba.
- `eval_platform/ablation.py`: registered the new feature flag for fairness
  accounting.
- `tests/test_retrieval_execution_stage2.py`: added route isolation, entity
  scope, RRF contribution, and BM25 scoped-candidate regression tests.

## 5. Backward Compatibility

The entity-scoped route resolver is still disabled by default:

```python
AgentFeatureConfig().entity_scoped_routing_enabled is False
```

When the flag is off, `hybrid_retrieve()` keeps the existing Dense/BM25 and
structured database behavior, but no longer calls `metadata_direct_lookup` as an
automatic third document recall list.

## 6. Tests

```text
uv run pytest tests/test_retrieval_execution_stage2.py -q
44 passed, 1 warning

uv run pytest tests/test_evidence_verifier_stage3.py -q
37 passed

$env:OPENAI_API_KEY='dummy'; uv run pytest tests/evaluation/test_phase6_ablation.py -q
7 passed
```

Without `OPENAI_API_KEY`, `tests/evaluation/test_phase6_ablation.py` fails during
collection because the evaluation package initializes a LangChain OpenAI client.
No network/model call was needed for the passing run; the dummy key only allowed
client construction.

## 7. Ablation

Controlled production ablations were not run in this implementation pass.

```text
Previous Four-Way Baseline: NOT_RUN
Dense+BM25: NOT_RUN
Entity-Scoped Dense+BM25: NOT_RUN
Routed Entity-Scoped: NOT_RUN
```

Reason: this pass added the production switch, route/scope implementation, BM25
scope counters, and regression tests. A paired evaluation still needs the same
dataset, case IDs, model, embedding, reranker, verifier, corpus/index version,
budget, and ACL context.

## 8. Interpretation

- Four-way retrieval remains available as the baseline; this change does not
  prove it should be removed.
- Metadata Direct Lookup still has value as an explicit exact locator route, not
  as a default hybrid recall channel.
- Entity scope is now measurable for BM25 through `scope_candidate_count` and
  `scored_doc_count`, but latency impact is `NOT_RUN`.
- Structured DB now has independent routing semantics in the new mode; Private
  Business improvement is `NOT_RUN` until paired evaluation runs.
- Known open risk: mixed-query quality still depends on the planner creating
  explicit source-specific subqueries. The executor now enforces route
  responsibility for each subquery, but it does not rewrite a bad mixed plan by
  itself.

## 9. Decision

Do not switch the production default yet.

Recommendation: keep `entity_scoped_routing_enabled=False` until paired ablation
results show no material recall/task-success regression and demonstrate useful
BM25 scoring reduction or route-accuracy gains.
