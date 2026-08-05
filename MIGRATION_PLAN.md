# Migration Plan

This plan is written before code migration. The target repository remains `D:\找实习\Liorin`; the source ZIP is only a read-only reference.

## Guardrails

- Do not overwrite the target repository with the source ZIP.
- Do not replace target production API, supervisor, database schema, data files, benchmark, or annotation pipeline wholesale.
- Do not create a parallel Knowledge Agent, retrieval pipeline, or benchmark.
- Do not migrate private/custodian benchmark zips or source PASS reports as evidence.
- Preserve target dirty-worktree changes unless a file is intentionally merged.
- Fix blocking source-test incompatibilities as part of migration, not by weakening tests.

## Batch 1: Protocols And Compatibility

Actions:

- Add source `retrieval/protocols.py` to target.
- Export protocol models from `retrieval/__init__.py`.
- Keep existing legacy retrieval outputs supported with explicit conversion helpers.
- Add tests for checkpoint-safe serialization and legacy compatibility.

Validation:

- `pytest -q tests/test_agentic_rag_protocols.py`
- current `evals/tests` remain passing.

## Batch 2: Retrieval Execution

Actions:

- Merge source retrieval additions:
  - `filters.py`
  - `metadata_lookup.py`
  - `security.py`
  - `observability.py`
  - `resilience.py`
  - `index_lifecycle.py`
  - `verification_policy.json`
- Function-level merge same-name retrieval modules, especially:
  - `hybrid_retriever.py`
  - `database_retriever.py`
  - `document_corpus.py`
  - `trace.py`
  - `budget.py`
  - `context_expander.py`
- Preserve default Dense + BM25 main recall.
- Trigger metadata and database retrieval only from query plan/entity evidence.
- Ensure unified ACL filtering applies to dense, BM25, metadata lookup, database retrieval, and parent expansion.

Validation:

- `pytest -q tests/test_retrieval_execution_stage2.py`
- SQL safety tests from Stage 4.
- Existing benchmark smoke.

## Batch 3: Fusion, Verification, And Decisions

Actions:

- Add `retrieval/evidence_verifier.py`.
- Wire `EvidenceAudit` and `VerificationDecision`.
- Fix LangChain `Document` construction assumptions for current dependency versions.
- Ensure verifier failures route to handoff or safe exit, not normal answer.
- Ensure targeted supplement and max-round deterministic exits.

Validation:

- `pytest -q tests/test_evidence_verifier_stage3.py`
- targeted supplemental retrieval tests.

## Batch 4: Production Knowledge Agent Graph

Actions:

- Merge source `agents/knowledge_agent.py` into target function-by-function.
- Preserve current `KnowledgeState`, `create_knowledge_agent()`, supervisor and support graph entrypoints.
- Add principal derivation from server-side state only.
- Add query understanding, retrieval planning, execute, verify, supplement, rewrite, replan, clarify, handoff, answer gate.
- Add state restoration for checkpoint-safe evidence.

Validation:

- Knowledge Agent graph tests.
- checkpoint/resume test.
- current API/supervisor smoke.
- benchmark adapter consistency test against the same graph.

## Batch 5: Enterprise Governance

Actions:

- Add `governance/` modules and configs:
  - degradation
  - health
  - feedback
  - release gate
- Ensure PII redaction for traces and feedback.
- Ensure prompt-injection findings are data attributes, not executable instructions.
- Add release gate framework without claiming real Milvus/model/blind-test completion.

Validation:

- `pytest -q tests/test_enterprise_governance_stage4.py`
- release gate dry run.

## Batch 6: Evaluation And Benchmark

Actions:

- Add Stage 4 evaluation helpers only where they call target production retrieval/agent code:
  - `evals/retrieval_evaluation.py`
  - `evals/ablation.py`
  - `evals/run_ablations.py`
  - `evals/run_stage4_local_retrieval_eval.py`
  - `evals/gold_isolation.py`
- Keep current benchmark runner and scoring as canonical.
- Ensure no private gold or source custodian zips are migrated.

Validation:

- `python -m evals.benchmark.cli smoke`
- `python -m evals.benchmark.cli run --dataset validation --limit 6 --allow-partial`
- annotation mock/audit/gate remain passing.

## Documentation And Artifacts

Generate at completion:

- `MIGRATION_CHANGED_FILES.txt`
- `MIGRATION_STATE_MAPPING.md`
- `MIGRATION_DEPENDENCY_REPORT.md`
- `MIGRATION_TEST_OUTPUT.txt`
- `MIGRATION_REMAINING_GAPS.md`
- `MIGRATION_HANDOFF.md`
- `artifacts/migration/file_mapping.json`
- `artifacts/migration/state_mapping.json`
- `artifacts/migration/test_summary.json`
- `artifacts/migration/unresolved_conflicts.json`

## Completion Criteria

Migration can be called complete only when:

- Target remains the sole final repository.
- Production API/supervisor/Knowledge Agent/benchmark share the same graph path.
- No duplicate retrieval or Knowledge Agent implementation remains.
- ACL and principal filtering run through every retrieval path.
- Stage 4 governance tests are adapted and passing or explicitly documented as blocked by unavailable real dependencies.
- Current target tests remain passing.

