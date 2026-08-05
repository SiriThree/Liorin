# Migration State Mapping

## Production Knowledge Agent

The migrated production path keeps `agents.knowledge_agent.create_knowledge_agent()` as the single graph constructor. Benchmark adapters call the same graph path instead of invoking isolated node copies.

| Target state field | Stage 4 role | Notes |
| --- | --- | --- |
| `messages` | user/agent conversation | Preserved as LangChain messages. |
| `original_question` | query source | Used by Query Understanding and benchmark adapters. |
| `principal` | server-side retrieval identity | Benchmark default is public-only unless a sample explicitly provides a principal. |
| `query_understanding` | structured understanding | `retrieval.protocols.QueryUnderstanding`; checkpoint-safe pydantic state. |
| `retrieval_plan` | planned subqueries | `RetrievalPlan` with per-source subqueries. |
| `retrieval_responses` | structured retrieval results | `RetrievalResponse` objects; avoids interpreting empty lexical output as success. |
| `evidences` | fused/cited evidence | `RetrievedEvidence` with `chunk_id`/`citation_id` and provenance. |
| `verification_decision` | evidence gate | `VerificationDecision` drives answer/supplement/handoff. |
| `trace_events` | sanitized observability | PII/tenant secrets are redacted by retrieval/security helpers. |

## Benchmark Mapping

`evals/benchmark/corpus_registry.py` maps production evidence to benchmark chunks by exact `chunk_id`. If the production `chunk_id` is not in the benchmark manifest, it may use exact `source_file + heading + text containment`; ambiguous matches are reported as unmapped. No fuzzy title guessing is used.

## Annotation State

The multi-agent annotation pipeline writes:

- `source_packets.jsonl`: A/B request packets with recursive `gold`, `split`, and `annotation` removal.
- `annotator_a.jsonl` / `annotator_b.jsonl`: independent first-pass records.
- `adjudicator_c.jsonl`: only disagreement samples.
- `adjudicated.jsonl`: consensus or C-resolved final annotation.
- `human_review_queue.json`: all disagreements, all high-risk samples, and deterministic random consensus samples.
- `final_annotations_after_human_review.json`: approved/modified/rejected review result.
- `reviewed_gold_export.json`: reviewed gold export without replacing old gold by default.

## Resume / Fingerprint

Annotation runs fingerprint dataset, corpus, model/provider/prompt config, schema source, and code source. A changed config/model/prompt/schema/data/code fingerprint rejects reuse of an old output directory. Targeted tests cover config drift and C-only disagreement resume behavior.
