# Migration Handoff

## Status

The Stage 4 Agentic RAG and enterprise governance migration has been applied to the target repository without replacing the repository wholesale. The source ZIP was used as read-only input.

## What Is Complete

- Unified retrieval protocol models.
- Production retrieval stack with ACL filters, metadata lookup, DB retrieval, BM25/dense routing, parent expansion, evidence verifier, observability, resilience, and index lifecycle helpers.
- Knowledge Agent graph integration through `create_knowledge_agent()`.
- Benchmark adapters use the production graph/retrieval path and produce schema-valid predictions for the six layers covered by tests.
- Multi-agent annotation mock flow, audit, C-only disagreement behavior, human review application, and reviewed Gold export.
- Security scans for forbidden blind/gold names, private key patterns, OpenAI-style keys, caches, and large files.

## What Is Not Complete

- Real three-model annotation.
- Blind Test formal evaluation.
- Real Milvus production validation.
- Real production LLM evaluation.
- Release gate PASS.

## README Commands

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m evals.benchmark.cli smoke
.venv\Scripts\python.exe -m evals.benchmark.cli run --dataset validation --limit 6 --allow-partial --predictions evals\reports\migration_validation_predictions.json --report evals\reports\migration_validation_report.json
.venv\Scripts\python.exe -m evals.benchmark.cli score evals\reports\migration_validation_predictions.json --dataset-path evals\benchmark\data\validation_v7_3.json --allow-partial --report evals\reports\migration_validation_rescore.json
.venv\Scripts\python.exe evals\run_ci_eval.py
.venv\Scripts\python.exe evals\run_stage4_local_retrieval_eval.py --predictions evals\reports\stage4_local_bm25_predictions.json --report evals\reports\stage4_local_bm25_report.json
.venv\Scripts\python.exe evals\run_ablations.py --local-bm25-report evals\reports\stage4_local_bm25_report.json --output evals\reports\stage4_ablation_report.json --repetitions 1
.venv\Scripts\python.exe governance\release_gate.py --report evals\reports\stage4_local_bm25_report.json --output evals\reports\stage4_release_gate_result.json
```

Annotation mock flow requires a run config equivalent to `evals/configs/mock_flow_test.yaml` with absolute `dataset_path`, `corpus_path`, and an ignored output directory under `evals/annotation_runs/`.

## Next Recommended Gate

Run real dependency validation in this order:

1. Build/validate real Milvus index manifest.
2. Run full production graph with real model credentials in a non-blind validation split.
3. Run real independent A/B/C annotation.
4. Run agreement gate on real run.
5. Prepare aggregate release report with approved thresholds.
6. Run release gate and only then consider formal Blind Test.
