# DATA EXPANSION PHASE E1 — Mixed Gold Preparation

## 1. E1 Summary

Phase E1 is **COMPLETE** as a Gold-preparation phase. It consumed the frozen 58 `SOURCE_VALIDATED` Phase E0 Mixed candidates, produced a deterministic Gold Draft attempt for every candidate, assigned every candidate an explicit terminal pre-annotation status, and froze annotation packets for the subset that is already deterministically annotatable.

Actual result:

- E0 input candidates: **58**
- E0 effective semantic units: **48**
- Gold Draft attempts: **58**
- `READY_FOR_DUAL_ANNOTATION`: **16**
- `NEEDS_MANUAL_PRECHECK`: **42**
- `REJECTED_BEFORE_ANNOTATION`: **0**
- New Formal cases: **0**
- Annotation runs: **0**
- Production Agent execution: **NOT RUN**
- D3-R: **DEFERRED_BY_ENVIRONMENT**

The low READY count is intentional and is not an E1 failure. E1 identified a systematic Gold-definition defect in the three manual-routing families: the E0 query asks for section/topic-level “related usage/handling points”, while E0 binds only one AtomicFact from a section that actually contains multiple benchmark-usable facts. Treating that single fact as the complete answer Gold would create systematic false negatives/false positives. E1 therefore exposes this as pre-annotation debt instead of silently broadening or rewriting the candidate.

## 2. E0 Inputs

E1 consumes the frozen E0 artifacts under `artifacts/evaluation/dataset-expansion-e0-mixed/`.

Input integrity:

- `mixed_source_validated.jsonl`: **58**
- `mixed_rejected.jsonl`: **10**
- E0 candidate-set SHA-256 matches `mixed_candidate_manifest.json`.
- The 58 candidates contain exactly five validated families.
- No E0 candidate or source artifact was regenerated.

## 3. E0 Rejected Isolation

The ten `MIXED_ORDER_RETURN_POLICY` candidates remain permanently isolated from E1 Gold preparation.

- E0 rejected: **10**
- Overlap with E1 input: **0**
- `MIXED_ORDER_RETURN_POLICY` present in E1 input: **NO**

The original rejection reasons remain unchanged:

- `UNSUPPORTED_TEMPORAL_BASIS_DELIVERY_DATE_REQUIRED`
- `TIME_DRIFT_WITHOUT_FROZEN_REFERENCE_DATE`

E1 does not substitute `order_date` for delivery/sign-off date and does not invent a reference date.

## 4. MixedGoldDraft Contract

E1 adds the construction-only `MixedGoldDraft` contract. It is not a new canonical runtime schema and does not promote any sample to Formal Gold.

Each draft contains:

- `candidate_id`
- `gold_draft_version`
- `mixed_family_id`
- `mixed_mode`
- `expected_response_type`
- `structured_facts[]`
- `document_facts[]`
- `derived_facts[]`
- `answer_required_facts[]`
- `intermediate_required_facts[]`
- `optional_facts[]`
- `gold_evidence[]`
- `reasoning_contract`
- `task_success_contract_draft`
- `source_necessity_contract`
- `runtime_query_materialization`
- `answerability`
- `ambiguity_status`
- `annotation_status`
- `review_requirements`
- `quality_flags`
- `gold_information_signature`

Every draft remains:

- `human_reviewed = false`
- `formal_eligible = false`

## 5. Fact Role Model

E1 explicitly separates final-answer facts from task-internal facts.

Construction-layer roles:

- `ANSWER_REQUIRED`
- `TASK_REQUIRED_INTERMEDIATE`
- `SUPPORTING_ONLY`
- `OPTIONAL_OUTPUT`

Actual role counts across the 58 drafts:

- `TASK_REQUIRED_INTERMEDIATE`: **100**
- `ANSWER_REQUIRED`: **74**
- `SUPPORTING_ONLY`: **8**
- `OPTIONAL_OUTPUT`: **0**

The high intermediate count is expected for Mixed routing: correct use of a private structured entity must be observable even when its internal identity should not be printed to the user.

## 6. Structured Facts

E1 materializes **58 structured facts**, one source-critical structured fact per Mixed candidate.

Distribution:

- `order.product_id`: **18**
- `warranty.product_id`: **16**
- `order.status`: **8**
- `ticket.product_id`: **8**
- `warranty.coverage_status`: **8**

Role semantics:

- product identity used only to route to the correct manual: `TASK_REQUIRED_INTERMEDIATE`
- order status used as a policy decision input: `TASK_REQUIRED_INTERMEDIATE`
- warranty coverage status explicitly requested by the user: `ANSWER_REQUIRED`

## 7. Document Facts

E1 materializes **66 document facts** from the exact E0 fact references.

D0 fact-type labels among those 66 facts:

- `TROUBLESHOOTING_STEP`: **47**
- `WARRANTY_POLICY`: **8**
- `POLICY`: **4**
- `RETURN_POLICY`: **4**
- `FEATURE_OR_INSTRUCTION`: **3**

Manual facts are `ANSWER_REQUIRED` in the routing families, but the broader section-level query scope prevents E1 from proving that the one selected E0 atomic fact is the complete answer Gold. Those candidates are therefore PRECHECK.

## 8. Intermediate Facts

The central E1 invariant is preserved:

> `Intermediate Fact != Final Answer Required Fact`

For all 42 manual-routing candidates:

- `order.product_id`, `ticket.product_id`, or `warranty.product_id` is task-critical.
- It is required for correct source routing.
- It is backed by structured field-level evidence.
- It is **not** required to appear in the user-facing final answer.

The derived routing node `ROUTE_TO_MATCHED_PRODUCT_MANUAL` is also `TASK_REQUIRED_INTERMEDIATE`.

## 9. Answer Required Facts

Examples:

- Order Status + Policy: derived cancellation-policy decision is `ANSWER_REQUIRED`.
- Warranty Status + Policy: the current `coverage_status` plus both qualified standard-warranty policy facts are `ANSWER_REQUIRED`.
- Manual-routing cases: the manual fact is intended as `ANSWER_REQUIRED`, but the query-to-section scope currently makes completeness unresolved, so the case stays PRECHECK.

## 10. Derived Facts

E1 creates **58 derived facts**.

Distribution:

- `SOURCE_ROUTING`: **42**
- `POLICY_APPLICATION`: **8**
- `MULTI_SOURCE_SYNTHESIS`: **8**

Unsupported derivations: **0**.

E1 recomputes policy semantics from the source rather than trusting the E0 label blindly.

## 11. Gold Provenance Graph

`mixed_gold_provenance_graph.jsonl` freezes, for every candidate:

- structured fact IDs
- document fact IDs
- derived nodes
- derived input fact IDs
- rule reference
- answer-required facts
- intermediate facts

All 58 drafts preserve the dual-source chain. No derived policy/synthesis node is allowed to depend only on the document or only on the structured record.

## 12. Structured Evidence

Structured GoldEvidence count: **58**.

All structured evidence is field-level and privacy-preserving, e.g. conceptually:

- `record:order:hash:<digest>#status`
- `record:order:hash:<digest>#product_id`
- `record:ticket:hash:<digest>#product_id`
- `record:warranty:hash:<digest>#coverage_status`
- `record:warranty:hash:<digest>#product_id`

No row-level catch-all evidence is used.

## 13. Document Evidence

Document GoldEvidence count: **58**.

All new document evidence uses current stable section identity:

`<document_id>:sec:<stable-hash>`

No new legacy `Hxxx` section identity is introduced.

## 14. Dual-source Necessity

All **58 / 58** drafts retain:

- `structured_source_required = true`
- `document_source_required = true`
- structured GoldEvidence present
- document GoldEvidence present

Gold preparation never removes structured routing evidence simply because the final answer may consist mostly of manual advice.

## 15. Order Status + Policy

Input: **8**

Result:

- READY: **8**
- PRECHECK: **0**
- REJECT: **0**

Structured fact: `order.status` as `TASK_REQUIRED_INTERMEDIATE`.

Document policy fact: `TASK_REQUIRED_INTERMEDIATE`.

Derived decision: `ANSWER_REQUIRED`.

E1 recomputes the rule from the current policy source for each real order state.

## 16. Order Product + Manual

Input: **18**

Result:

- READY: **0**
- PRECHECK: **18**
- REJECT: **0**

The structured `order.product_id` routing fact is handled correctly as an intermediate fact and is never forced into the user-visible final answer.

The blocker is Gold completeness/minimality: each query asks for topic/section-level “related points”, while the selected manual section contains multiple usable facts and E0 selected only one fact.

## 17. Ticket + Troubleshooting

Input: **8**

Result:

- READY: **0**
- PRECHECK: **8**
- REJECT: **0**

`ticket.product_id` is routing-only. `ticket.summary` and unrelated ticket fields are not pulled into Gold.

Existing Formal Mixed Gold collision remains **0** after stable-section rechecking against the ten existing `TICKET_MANUAL` Formal cases.

The same section-scope completeness problem prevents the new eight from being directly frozen for annotation.

## 18. Warranty Status + Policy

Input: **8**

Result:

- READY: **8**
- PRECHECK: **0**
- REJECT: **0**

`warranty.coverage_status` is explicitly asked by the query and is therefore `ANSWER_REQUIRED`.

The two standard-warranty source statements are also `ANSWER_REQUIRED` because the query explicitly asks what standard warranty usually covers and usually excludes.

The E1 synthesis node is `SUPPORTING_ONLY`; it does not invent a case-specific promise such as “your repair will definitely be free”.

## 19. Warranty Product + Manual

Input: **16**

Result:

- READY: **0**
- PRECHECK: **16**
- REJECT: **0**

`warranty.product_id` remains `TASK_REQUIRED_INTERMEDIATE` and is backed by routing evidence.

The same broad section-query / single-AtomicFact incompleteness affects all sixteen cases.

## 20. Policy Rule Audit

Unique policy rule drafts: **4**.

Unique-rule classification:

- `DETERMINISTIC`: **2**
- `QUALIFIED_BUT_USABLE`: **2**
- `AMBIGUOUS`: **0**
- `UNSUPPORTED`: **0**

Candidate usage:

- deterministic rule usage: **4** candidates
- qualified-but-usable rule usage: **12** candidates
- ambiguous: **0**
- unsupported: **0**

## 21. Policy Ambiguity

The policy term `通常` is not converted into an absolute ALLOW/DENY rule.

For `Shipped` / `Delivered`, E1 freezes a qualified result equivalent to:

`STANDARD_POLICY_USUALLY_DIRECT_CANCEL_NOT_ALLOWED_USE_RETURN_REFUND`

rather than dropping the source qualifier.

For standard warranty scope, `通常覆盖` / `通常不属于` are preserved as qualified policy facts. Because the user query itself asks for what the policy *usually* covers/excludes, those cases remain usable.

## 22. Derived Decision Validation

All 58 E0 derived plans are recomputed at E1 construction time.

- Routing: exact relation check to the matched product manual.
- Order cancellation: enum/state policy application.
- Warranty: current coverage state plus qualified policy scope synthesis.

No LLM interpretation is used.

Unsupported derivation count: **0**.

## 23. Gold Minimality

Gold minimality issues: **42**.

Corrections applied by silently expanding/rephrasing the candidate: **0**.

Reason:

The E0 manual-routing query is broad at section/topic scope. E1 cannot deterministically decide that the one E0-selected atomic fact is the complete-but-minimal answer set without changing the question or defining a new section-summary annotation contract.

## 24. Gold Completeness

Gold completeness issues: **42**.

All 42 are the same systemic category:

`DOCUMENT_GOLD_COMPLETENESS_NOT_DETERMINISTIC`

The affected section contains **2–21** benchmark-usable facts while the E0 candidate binds one document AtomicFact.

This is a Candidate wording/Gold-scope problem, not a Source validity problem.

## 25. Gold Alignment

- Candidates checked: **58**
- Fully aligned and annotation-ready: **16**
- Explicit alignment/precheck issues: **42**
- Dual-source evidence complete: **58**

Alignment covers:

`Query -> Fact Roles -> Evidence -> Derivation -> TaskSuccessContract`

not merely private-style field alignment.

## 26. Runtime Query Materialization

All candidates reuse the D2 runtime materialization mechanism.

- Materializable: **58 / 58**
- Not materializable: **0**

Public E1 artifacts keep a redacted runtime preview and hashes; synthetic fixture business IDs are not persisted in public diagnostic output.

## 27. Query Leakage

Second-pass leakage checks after runtime materialization:

- structured fact leakage: **0**
- product routing fact leakage: **0**
- derived outcome leakage: **0**

A construction token being safe is not treated as sufficient; E1 checks the materialized query path as well.

## 28. Existing Formal Dedup

Existing Formal Mixed cases: **10**.

E1 reuses E0’s deterministic legacy-section alias bridge and compares current stable document sections.

Gold-level existing Formal collision: **0**.

## 29. Gold-level Diversity

Across all 58 drafts:

- unique Gold information signatures: **48**
- exact Gold duplicate excess: **0**
- same-reasoning low-information groups: **6**
- candidates in low-information entity-variation groups: **16**

E1 flags these groups but does not prune them automatically.

## 30. READY Count

`READY_FOR_DUAL_ANNOTATION = 16`

By family:

- `MIXED_ORDER_STATUS_POLICY`: **8**
- `MIXED_WARRANTY_STATUS_POLICY`: **8**

The READY set is therefore policy-heavy and should not yet be treated as a representative Mixed annotation batch.

## 31. PRECHECK Count

`NEEDS_MANUAL_PRECHECK = 42`

By family:

- `MIXED_ORDER_PRODUCT_MANUAL`: **18**
- `MIXED_TICKET_TROUBLESHOOTING`: **8**
- `MIXED_WARRANTY_PRODUCT_MANUAL`: **16**

Reasons:

- `BROAD_MANUAL_SECTION_SCOPE`: **42**
- `DOCUMENT_GOLD_COMPLETENESS_NOT_DETERMINISTIC`: **42**

## 32. REJECT Count

`REJECTED_BEFORE_ANNOTATION = 0`

No hidden reject was converted to PRECHECK merely to preserve count. The current issue is repairable candidate/Gold scope, not broken source relation or unsupported production capability.

## 33. Annotation Packet

Frozen E1 packets: **16**.

Packet contents include only:

- user query
- redacted runtime preview
- minimal structured source snapshot
- relevant document fact text + stable section identity
- Gold Draft to review
- fact roles
- derived reasoning
- TaskSuccessContract Draft
- dual-source necessity
- production capability summary
- review requirements

Packets do **not** include full manual sections, Production predictions, Agent traces, Judge results, another annotator’s result, adjudication or split assignment.

## 34. Batch Freeze

- Batch ID: `MIX-E1-1FECB833D0B9`
- Batch hash: `1fecb833d0b96ce695343df4543c27b6a50e98657c41ecc95a8068c3088d2861`
- Packet count: **16**
- Annotation runs: **0**
- Human review runs: **0**
- Formal eligible count: **0**

The batch hash excludes `created_at`, and rerunning the same E0 inputs produces the same packet/batch hashes.

## 35. Artifacts

Generated under `artifacts/evaluation/dataset-expansion-e1-mixed-gold/`:

- `mixed_gold_drafts.jsonl`
- `mixed_gold_draft_report.json`
- `mixed_gold_fact_roles.json`
- `mixed_gold_provenance_graph.jsonl`
- `mixed_policy_rule_drafts.jsonl`
- `mixed_policy_rule_audit.json`
- `mixed_derived_fact_report.json`
- `mixed_gold_alignment_report.json`
- `mixed_gold_minimality_report.json`
- `mixed_gold_completeness_report.json`
- `mixed_source_necessity_validation.json`
- `mixed_runtime_materialization.json`
- `mixed_query_leakage_report.json`
- `mixed_annotation_packets.jsonl`
- `mixed_annotation_packet_report.json`
- `mixed_source_snapshots.jsonl`
- `mixed_annotation_batch_manifest.json`
- `mixed_preannotation_review_queue.jsonl`
- `mixed_preannotation_rejected.jsonl`
- `mixed_gold_level_dedup.json`
- `mixed_ready_distribution.json`
- `phase_e1_summary.json`

## 36. Tests

E1 targeted tests cover:

- frozen E0 candidate count/hash
- permanent isolation of ten E0 rejected return-policy candidates
- intermediate vs final fact roles
- manual section-scope incompleteness
- deterministic / qualified policy handling
- warranty policy semantics
- dual-source evidence
- derived input provenance
- fail-closed missing evidence
- runtime materialization and leakage
- packet freeze/minimality
- batch reproducibility
- existing Formal dedup
- policy concentration
- private identifier leakage
- Formal canonical count
- D3-R deferred / no Production execution

Final commands/results are recorded in the repository handoff and turn output.

## 37. Production Diff

SHA-256 comparison with the Phase E0 input confirms:

`Production behavior files changed = 0`

Checked directories:

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

## 38. Formal Dataset Invariance

The two actual Formal canonical data files are byte-identical to the Phase E0 baseline:

- Development: **34**
- Validation: **5**
- Total Formal canonical: **39**

New Formal cases: **0**.

D2 frozen annotation batch, D3 blocked summary, D3-R real-run summary, and E0 candidate artifacts are also unchanged.

## 39. Next Stable Inputs

The next step can safely depend on:

- `mixed_gold_drafts.jsonl`
- `mixed_gold_provenance_graph.jsonl`
- `mixed_policy_rule_drafts.jsonl`
- `mixed_policy_rule_audit.json`
- `mixed_gold_alignment_report.json`
- `mixed_gold_minimality_report.json`
- `mixed_gold_completeness_report.json`
- `mixed_source_snapshots.jsonl`
- `mixed_preannotation_review_queue.jsonl`
- `mixed_gold_level_dedup.json`
- `mixed_ready_distribution.json`
- `mixed_annotation_packets.jsonl`
- `mixed_annotation_batch_manifest.json`

The correct next action is **not** to run dual annotation on all Mixed data yet. The systemic 42-case manual-query scope problem should be resolved first by a controlled candidate-quality repair stage that narrows each manual-routing query to a deterministic fact/symptom/step scope (or explicitly defines a section-summary Gold contract). That repair must not alter source truth or invent facts. The 16 frozen policy packets can remain immutable as a valid READY subset, but they are too policy-concentrated to serve as the representative Mixed batch by themselves.
