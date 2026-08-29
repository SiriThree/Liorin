# Liorin Benchmark 1000 Dataset

This dataset expands Liorin evaluation coverage to 1,000 source-grounded cases.

## Output

- Dataset: `evals/benchmark/data/canonical/liorin_benchmark_1000_v1.jsonl`
- Manifest: `evals/benchmark/data/canonical/liorin_benchmark_1000_v1.manifest.json`
- Builder: `evals/scripts/build_benchmark_1000.py`

## Quotas

The 1,000 cases are a single benchmark made of 500 single-turn cases and
500 multi-turn sessions. A multi-turn session is counted as one case, not one
case per user utterance.

| Category | Total | Single-turn | Multi-turn sessions |
| --- | ---: | ---: | ---: |
| Knowledge requests | 600 | 300 | 300 |
| Private business-data requests | 150 | 75 | 75 |
| Mixed structured + knowledge requests | 150 | 75 | 75 |
| Safety/governance requests | 100 | 50 | 50 |
| Total | 1000 | 500 | 500 |

Product-related requests total 900 cases. They are exactly balanced across the
20 checked-in products: 45 cases per product. Knowledge cases are not forced to
be 30 per product when a raw manual has fewer independent askable semantics;
private and mixed tasks fill the remaining product balance.

## Source Truth

The benchmark is generated only from checked-in source truth:

- Knowledge: raw files under `data/knowledge/manuals/*.md`, plus
  `data/structured/products.json` only when a product manual has fewer
  independent raw manual semantics than the target allocation can use.
- Private business data: `data/structured/orders.json`,
  `data/structured/order_items.json`, `data/structured/tickets.json`, and
  `data/structured/warranty_cases.json`.
- Mixed tasks: private order/item records plus either product manuals or
  `data/knowledge/policies/after_sales_policy.md`.
- Safety: H0 policy-validated security scenarios and safety surface inventory.

## Construction Logic

The builder follows three steps:

1. Identify real data sources with stable source references.
2. Extract independent, verifiable task semantics from raw manual lines,
   structured fields, dual-source mixed requirements, and safety policies.
3. Render each semantic unit into a natural-language user query while keeping
   the source references and gold facts attached to the case.

Each case contains:

- `query` and model-call-style `input.messages`;
- `case_mode`, either `single_turn` or `multi_turn_session`;
- `source_semantic.semantic_id` and `source_semantic.source_refs`;
- `gold_evidence`;
- `gold_facts`;
- category/subcategory/difficulty metadata.

Multi-turn session cases additionally contain `multi_turn_gold`, which marks:

- the active task at the final answer point;
- facts that should be inherited from earlier turns;
- stale facts and facts that must not be inherited;
- clarification-required turns and task-switch turns;
- cross-agent handoffs when the answer depends on state produced by another
  agent;
- session-level success criteria.

The multi-turn set is designed to cover six failure modes:

- clarification then task resume;
- cross-turn entity carryover;
- user correction and fact supersession;
- task switch and context contamination;
- cross-agent state transfer;
- cross-session long-term memory and stale-memory rejection.

## Validation

`tests/evaluation/test_benchmark_1000_dataset.py` validates:

- exactly 1,000 cases;
- exact category quotas;
- exact 500/500 single-turn and multi-turn split;
- exact per-category single-turn and multi-turn quotas;
- exact 45-case product balance for all product-related tasks;
- unique `case_id`, `query`, and source semantic IDs;
- manifest hash consistency;
- required source grounding fields;
- multi-turn sessions have full transcripts and required `multi_turn_gold`
  fields;
- knowledge source references resolve to raw manual files and line numbers,
  or to the checked-in product catalog fallback.
