# DATA EXPANSION PHASE D3-R — REAL DUAL ANNOTATION RUNTIME RECOVERY

## 1. D3-R Summary

Phase D3-R is a runtime-recovery continuation of Phase D3, not a new dataset expansion phase. The frozen D2 batch remains unchanged. Runtime engineering is complete enough to perform readiness checks, provider smoke, a 5–8 packet infrastructure pilot, and the formal independent A/B run when two real annotator runtimes are configured.

Current environment result:

- Phase status: **PARTIAL**
- Annotation Runtime: **BLOCKED**
- Actual Dual Independent Annotation: **BLOCKED**
- Agreement: **NOT RUN**
- Real provider calls A/B: **0 / 0**
- Valid pairs: **0 / 76**
- New Formal Cases: **0**
- Human Review: **0**
- Adjudication: **0**
- Production Agent: **NOT RUN**

No mock, fixture, stub, copied decision, or deterministic fake decision was used as an annotation result.

## 2. Initial Blocker

Phase D3 had recorded `REAL_ANNOTATOR_ENVIRONMENT_UNAVAILABLE`. D3-R rechecked the environment instead of copying that conclusion.

Observed environment:

- `ANNOTATOR_A_API_KEY`: not configured
- `ANNOTATOR_B_API_KEY`: not configured
- `OPENAI_API_KEY`: not configured
- `DEEPSEEK_API_KEY`: not configured
- `ANTHROPIC_API_KEY`: not configured
- No committed real runtime config exists; only `private_business_dual_annotation.example.yaml` is present.
- The example uses placeholder provider/model/base URLs and is now explicitly rejected as a formal runtime config.
- Expected local model endpoints on `127.0.0.1:11434` and `127.0.0.1:8000` were not reachable during the audit. No configured local annotator runtime was found.

The first real blocker is therefore **missing real annotator runtime configuration/credentials**, not low annotation agreement.

## 3. Frozen Batch Verification

D3-R revalidated the D2 packet manifest before any possible provider call.

- Frozen packets: **76**
- Excluded PRECHECK: **8**
- Batch ID: `PBQ-D2-C3B3AA7C6549`
- Batch hash: `c3b3aa7c65497813a9947e2ee0a8f05bae84958c0f5f09ba1f7bc1f3bc22e01c`
- Candidate set hash: `7885191d82cb97e51e38e000d7a70a77dbea865b2cd61b74256c98ad950855f6`
- Packet hash validation: **76 / 76 PASS**
- `READY packet IDs ∩ PRECHECK IDs`: **empty**

The historical blocked D3 artifact was also checked and preserved. D3-R writes to `artifacts/evaluation/dataset-expansion-d3-real-run/` and does not overwrite `dataset-expansion-d3/`.

## 4. Annotator A Runtime

Actual runtime status: **BLOCKED**.

The repository only contains example values for A:

- example provider: `provider-a`
- example model: `model-a`
- example base URL: `https://api.provider-a.example/v1`
- credential env name: `ANNOTATOR_A_API_KEY`

These values are explicitly classified as placeholders, not as an actual configured provider/model.

Real calls: **0**.

## 5. Annotator B Runtime

Actual runtime status: **BLOCKED**.

The repository only contains example values for B:

- example provider: `provider-b`
- example model: `model-b`
- example base URL: `https://api.provider-b.example/v1`
- credential env name: `ANNOTATOR_B_API_KEY`

These values are explicitly classified as placeholders, not as an actual configured provider/model.

Real calls: **0**.

## 6. Annotation Diversity Mode

Current actual diversity: **NOT_ESTABLISHED**.

D3-R no longer reports `MODEL_DIVERSE` merely because two example config blocks contain different placeholder strings. Only once both real runtimes are READY does the runtime freeze one of:

- `MODEL_DIVERSE`
- `SAME_MODEL_INDEPENDENT`

The configured example would conceptually be diverse, but this is not an actual runtime fact.

## 7. Provider Smoke

Annotator A provider smoke: **NOT RUN**.

Annotator B provider smoke: **NOT RUN**.

Reason: runtime readiness must be READY before any provider call. Smoke uses a separate infrastructure-only structured-output fixture and never consumes one of the 76 formal annotation packets.

Smoke output is explicitly `annotation_quality_result = NOT_APPLICABLE`.

## 8. Infrastructure Pilot

Pilot: **NOT RUN**.

D3-R implements a deterministic 5–8 packet pilot selector that covers ORDER, TICKET, WARRANTY, single-field, multi-field, and Ticket Summary when available. The default pilot size is 6.

The pilot only validates prompt rendering, SourceSnapshot rendering, structured output, packet/candidate binding, and provider stability. Pilot decisions never enter the 76-packet agreement denominator.

## 9. Prompt Freeze

Prompt version: `private_gold_review_v1`.

Prompt hash in the final blocked real-run manifest:

`319996558482ca2b5d0b2c3b1cfb4d9c713800bb2a7afbde7173d5fbb7535064`

Structured decision schema: `private-business-dual-annotation-output-v1`.

The prompt was not modified to improve agreement. D3-R only adds runtime checks and telemetry.

## 10. Annotator A Formal Run

Formal A run: **NOT RUN**.

- requested formal annotations: 0 provider calls
- valid decisions: 0
- infra failures observed from provider: 0
- run ID: not created because runtime readiness failed before formal execution

The blocked run manifest records the configuration state without storing secret values.

## 11. Annotator B Formal Run

Formal B run: **NOT RUN**.

- requested formal annotations: 0 provider calls
- valid decisions: 0
- infra failures observed from provider: 0
- run ID: not created because runtime readiness failed before formal execution

## 12. Annotation Completion

- Frozen packets: 76
- A valid: 0
- B valid: 0
- Valid pairs: 0
- Incomplete pairs: 76

All 76 are recorded as `INCOMPLETE_DUAL_ANNOTATION` with reason `REAL_ANNOTATOR_RUNTIME_NOT_READY`.

This is not a 0% annotation quality result.

## 13. Pairing

Formal pairing requires:

`A valid AND B valid AND same candidate_id AND same packet_hash`.

Current valid pairs: **0 / 76**.

Each blocked pairing record retains the candidate ID and frozen packet hash but contains no decision reference.

## 14. Overall Agreement

**NOT RUN**.

- numerator: N/A
- denominator: 0
- rate: N/A

A 0/0 artifact must never be interpreted as 0% agreement.

## 15. Exact Case Agreement

**NOT RUN**.

The D3 agreement engine remains unchanged. Exact agreement requires identical overall decision, all critical dimensions, GoldFact/GoldEvidence/TaskContract reviews, and structured edits.

## 16. Dimension Agreement

**NOT RUN** for all dimensions:

- Query Quality
- Answerability
- Response Type
- GoldFact Correctness
- GoldFact Completeness
- Gold Minimality
- GoldEvidence
- TaskSuccessContract
- Source Support
- Ambiguity
- Privacy

## 17. GoldFact Agreement

**NOT RUN**.

The existing D3 engine remains the source of truth for fact-level comparison.

## 18. GoldEvidence Agreement

**NOT RUN**.

No A/B evidence review exists yet.

## 19. TaskContract Agreement

**NOT RUN**.

No A/B contract review exists yet.

## 20. Domain Agreement

- ORDER: **NOT RUN**
- TICKET: **NOT RUN**
- WARRANTY: **NOT RUN**

## 21. Semantic-family Agreement

**NOT RUN**.

No highest/lowest/high-risk family can be reported until valid A/B pairs exist.

## 22. Ticket Summary

D2 has 3 `TICKET_SUMMARY_LOOKUP` packets using semantic comparison. Real A/B annotation result: **NOT RUN**.

No conclusion is made about whether both annotators accept the semantic free-text Gold.

## 23. Product Minimality

D2 draft policy remains:

- `product_name`: critical
- `product_id`: optional companion

Real A/B acceptance of this minimality rule: **NOT RUN**.

## 24. Warranty

D2 answerability audit found 22/22 selected Warranty candidates answerable under the frozen fixture/tool semantics. D3-R real annotation of Warranty Gold validity/minimality/evidence: **NOT RUN**.

## 25. Surface Collision

D2 identified five `LOW_INFORMATION_DUPLICATE_CANDIDATE` packets. Their A/B Gold validity: **NOT RUN**.

Agreement and diversity selection remain separate concerns; even future A/B ACCEPT decisions will not automatically retain all five.

## 26. Disagreement Queue

Real disagreements: **NOT RUN**.

The queue file is empty because no valid A/B decisions exist, not because the annotators agreed on every case.

## 27. Infrastructure Errors

Observed runtime blocker before provider call:

`REAL_ANNOTATOR_RUNTIME_NOT_READY`.

Observed provider authentication/model/timeout/rate-limit/parse errors: **none**, because provider calls were not attempted.

D3-R hardens the backend semantics:

- 401/403/404 and other non-transient HTTP errors fail fast.
- timeout, connection failures, 429, and selected 5xx errors use bounded retry.
- retry budget comes from annotator config (`max_retries`).
- valid ACCEPT/REJECT/NEEDS_HUMAN_REVIEW decisions are never retried for semantic preference.

## 28. Annotation Cost Diagnostics

Actual provider calls: 0.

Input tokens: N/A.

Output tokens: N/A.

Provider cost: N/A.

No cost or token values were fabricated.

## 29. Artifacts

New real-run directory:

`artifacts/evaluation/dataset-expansion-d3-real-run/`

Contains:

- `annotation_runtime_manifest.json`
- `annotator_a_decisions.jsonl`
- `annotator_b_decisions.jsonl`
- `annotator_a_run_manifest.json`
- `annotator_b_run_manifest.json`
- `dual_annotation_pairing.jsonl`
- `annotation_agreement_summary.json`
- `annotation_agreement_summary.md`
- `annotation_dimension_agreement.json`
- `annotation_goldfact_agreement.json`
- `annotation_evidence_agreement.json`
- `annotation_contract_agreement.json`
- `annotation_domain_agreement.json`
- `annotation_family_agreement.json`
- `annotation_disagreement_queue.jsonl`
- `annotation_incomplete.jsonl`
- `consensus_annotation_candidates.jsonl`
- `phase_d3r_summary.json`

The original blocked D3 directory is preserved unchanged.

## 30. Tests

D3-R targeted:

`12 passed`.

Evaluation suite:

`231 passed, 2 skipped`.

Full repository:

`445 passed, 2 skipped`.

Compile:

`PASS`.

The two existing skips are the previously known real Production / real Judge integration dependency skips. Test fixtures do not count as annotation results.

## 31. Formal Dataset Invariance

Canonical dataset remains unchanged:

- Development: 34
- Validation: 5
- Formal canonical total: **39**
- New Formal Cases: **0**

The canonical Dev/Validation files match the D3 baseline by SHA-256.

The D2 frozen packet JSONL and annotation batch manifest also match the D3 baseline by SHA-256.

## 32. Production Diff

Compared with the Phase D3 input archive, content hashes under:

- `agents/`
- `tools/`
- `retrieval/`
- `context_engine/`
- `memory/`
- `artifact/`
- `governance/`
- `observability/`
- `production/`
- `deployments/`

show:

`Production behavior files changed = 0`.

D3-R changes are limited to annotation runtime/config/backend/CLI/test/docs/artifacts.

## 33. D4 Readiness

**NOT READY**.

D4 requires actual A/B decisions and a real disagreement/consensus set. Current decisive missing artifacts are non-empty real:

- `annotator_a_decisions.jsonl`
- `annotator_b_decisions.jsonl`

The next valid execution sequence is:

1. Create a non-committed real annotator runtime config using actual provider/model/base URLs.
2. Set API credentials in environment variables only.
3. Run D3-R `--check-only` until both A and B are READY.
4. Run provider smoke for both sides.
5. Run the 5–8 packet infrastructure pilot.
6. Freeze `private_gold_review_v1` if no infrastructure bug is found.
7. Execute formal A over all 76 packets and freeze A decisions.
8. Execute independent formal B over the same 76 packets and freeze B decisions.
9. Compute real agreement/disagreement with the existing D3 engine.
10. Only then decide whether D4 adjudication is ready.

No D4 action has been executed in this phase.
