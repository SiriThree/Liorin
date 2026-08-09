# Benchmark Expansion Phase F0 — Troubleshooting / Clarification / Recovery-oriented Candidate Expansion

## 1. F0 Summary

Phase F0 is COMPLETE as a **dataset-construction phase**.

It constructs source-grounded Troubleshooting / Clarification / Recovery-oriented challenge candidates only. It does not create Formal Gold and does not run Production, annotators, judges, adjudication, or recovery executions.

Final construction result:

```text
Source-related sections / SourceUnits       137
Active benchmark-usable SourceUnits          28
Raw Candidates                              100
SOURCE_VALIDATED                             66
Rejected                                     34
Effective Semantic Units                     61
Scenario Families                            50
Procedure Families                           22
Symptom Families                              8
Products                                     12
Documents / Manuals                          12

Clarification Required                       12
False Clarification Controls                 11
Handoff / Escalation                          8
Recovery-oriented                            22

Observed Production First-pass Failures       0
Real Recovery Runs                            0
Recovered Cases                               0
New Formal Cases                              0
Annotation Runs                               0
Production Agent                         NOT RUN
D3-R                            DEFERRED_BY_ENVIRONMENT
```

The main quality decision in F0 is that 137 sections containing D0 Troubleshooting/Error-code facts are **not** treated as 137 benchmark-ready task units. Only 28 sections survive the active-troubleshooting gate after removing preventive-only instructions, warranty/disclaimer material, source fragments without actionable behavior, and other non-task contexts.

## 2. Frozen Previous Phases

The following inputs remain frozen:

- Private annotation batch: 76 packets, unchanged.
- Mixed E1-R batch: 58 packets, unchanged.
- Existing Formal Canonical: 39 samples (34 Development + 5 Validation), unchanged.
- D3-R: `DEFERRED_BY_ENVIRONMENT`, unchanged as historical state.

F0 only appends the `troubleshooting_expansion` state to `artifacts/evaluation/benchmark-expansion-roadmap-status.json`.

## 3. Troubleshooting Source Inventory

D0 identified 319 Troubleshooting/Error-code atomic facts across 137 sections. F0 re-reads the actual corpus and rebuilds these facts into section-level `TroubleshootingSourceUnit` objects instead of turning AtomicFacts directly into questions.

Actual F0 source space:

```text
SourceUnits                       137
Products represented in source     19
Documents represented in source    21
Benchmark-usable SourceUnits       28
Products in usable SourceUnits     14
Documents in usable SourceUnits    14
```

The validated candidate pool finally covers 12 products and 12 documents after cross-phase collision removal and semantic validation.

## 4. Source Units

`TroubleshootingSourceUnit` models a coherent section-level troubleshooting structure:

- symptom;
- product/document/section identity;
- required context;
- diagnostic steps;
- conditional branches;
- safety prerequisites;
- stop conditions;
- escalation conditions;
- manual fact identities;
- step-order semantics;
- benchmark usability flags.

F0 deliberately separates `SourceUnit` from `AtomicFact`: a procedure containing symptom → action → conditional continuation → escalation remains one coherent unit.

## 5. Product / Manual Coverage

Final SOURCE_VALIDATED pool:

```text
Unique products   12
Unique documents  12
```

Candidate distribution by product:

```text
LIO-PROD-001  7
LIO-PROD-006  6
LIO-PROD-008  4
LIO-PROD-009  5
LIO-PROD-010  4
LIO-PROD-012  8
LIO-PROD-013 10
LIO-PROD-014  5
LIO-PROD-015  6
LIO-PROD-016  7
LIO-PROD-018  1
LIO-PROD-020  3
```

The prompt's 15+ product coverage is treated as planning guidance, not a quota. F0 intentionally accepts 12-product coverage after excluding preventive-only/manual-topic material that would have increased coverage but weakened task semantics.

## 6. Symptom Families

Validated symptom-family distribution:

```text
START_OR_RESPONSE_FAILURE       14
WATER_FLOW_OR_DRAINAGE          14
OTHER_TROUBLESHOOTING           11
DOOR_OR_MECHANICAL               8
INDICATOR_OR_DISPLAY             8
CHARGING_OR_BATTERY              4
MAINTENANCE                      4
CONNECTIVITY_OR_INTERFACE        3
```

These are construction-layer semantic families inferred from the actual corpus. They are separate from task behavior such as Clarification or Handoff.

## 7. Task Behavior Taxonomy

Behavior labels are multi-dimensional; one candidate may be both Conditional and Recovery-oriented.

```text
DIRECT                         11
MULTI_STEP                      4
CONDITIONAL                    22
CLARIFICATION_REQUIRED         12
NO_CLARIFICATION_CONTROL       11
HANDOFF                         8
RECOVERY_ORIENTED              22
```

Actual mutually exclusive primary `task_type` counts:

```text
CLARIFICATION_REQUIRED                    12
DIRECT_TROUBLESHOOTING                    11
SUFFICIENT_CONTEXT_NO_CLARIFICATION       11
CONDITIONAL_TROUBLESHOOTING               10
ESCALATION_HANDOFF                         8
RECOVERY_ORIENTED_REWRITE                  5
RECOVERY_ORIENTED_SUPPLEMENT               5
MULTI_STEP_TROUBLESHOOTING                 4
```

## 8. Required Context

Source-level extraction finds contextual dependencies in 133 / 137 source sections, mostly because product-specific manual selection is contextual. This is **not** the same as saying 133 benchmark cases should clarify.

Only 12 validated candidates intentionally omit a truly required context field:

```text
product_name_or_model         5
previous_action_result        2
safety_symptom_presence       1
indicator_movement_pattern    1
power_source_type             1
drainage_state                1
new_battery_test_result       1
```

All missing context uses `safe_to_infer = false` semantics.

## 9. Direct Troubleshooting

11 validated Direct cases form the control group where user context is sufficient and a source-backed action can be returned without clarification or recovery.

Examples include real active symptoms such as:

- abnormal/no-response operation;
- engine cannot start;
- dishwasher cannot drain;
- oven door cannot open;
- camera capture/storage failure;
- water pump cannot draw water.

Preventive-only warnings and topic headings are excluded from the Direct pool.

## 10. Multi-step

4 validated candidates explicitly require multiple source-backed checks/actions.

F0 preserves source order semantics:

- `ORDERED`;
- `PARTIALLY_ORDERED`;
- `UNORDERED`.

For unordered source lists, the query asks for two supported checks with no ordering requirement rather than inventing a “first/second” procedure.

## 11. Conditional

22 candidates carry the `CONDITIONAL` behavior label; 10 use `CONDITIONAL_TROUBLESHOOTING` as the primary task type.

Conditions are taken directly from source branches, such as:

- issue still persists;
- fuel tank empty;
- plug/drain component loose;
- new battery test result;
- mouse indicator state;
- safety symptom presence.

Generic conditions such as “any problem” are not used as target branch semantics.

## 12. Clarification-required

12 candidates require clarification because the missing information changes the reliable action path.

They include two main designs:

1. Cross-product ambiguity where the product/model is genuinely needed to select the correct product-specific manual.
2. Source-backed branch ambiguity where a concrete condition/result is missing.

Clarification Gold at F0 remains a draft of required slot + intent; it is not a fixed question string and is not Formal Gold.

## 13. False Clarification Controls

11 `SUFFICIENT_CONTEXT_NO_CLARIFICATION` candidates form the over-clarification control group.

They explicitly contain enough product/symptom/branch context for an `ANSWER` response. They prevent a system from scoring well merely by asking unnecessary questions for every troubleshooting request.

16 scenario families contain paired full-context and clarification variants, and variants within a scenario family share future split grouping keys.

## 14. Safety Conditions

Source inventory:

```text
SourceUnits with safety condition  25
Validated safety-critical candidates 2
```

The lower candidate count is intentional. F0 does not turn every preventive safety warning into a troubleshooting task. Safety instructions are only candidate-critical when they are tied to an active source-backed problem path.

Safety-critical steps remain non-optional in future Gold preparation.

## 15. Escalation / Handoff

8 source-grounded Handoff candidates survive validation.

Examples of source-supported escalation conditions include:

- VR health symptoms requiring immediate stop and medical consultation;
- air-conditioner fault self-diagnosis indicator requiring dealer/service contact;
- pump ignition-system failure or damaged mechanical seal requiring dealer support;
- unresolved dishwasher troubleshooting requiring authorized service;
- drill new-battery diagnostic result requiring service/recycling handling;
- oven confirmed repair requirement;
- unresolved camera fault requiring authorized dealer support.

F0 rejects warranty/disclaimer text and generic support wording that merely contains words such as “repair” or “replacement”.

## 16. Recovery Eligibility

22 validated candidates are `RECOVERY_ORIENTED`.

Recovery trigger distribution:

```text
MISSING_REQUIRED_CONTEXT   12
WRONG_SCOPE_RETRIEVAL       5
PARTIAL_PROCEDURE           5
```

Acceptable-action occurrence distribution:

```text
CLARIFY      12
REWRITE      10
SUPPLEMENT   10
```

A candidate may list more than one acceptable action, so action counts are not mutually exclusive.

## 17. Recovery Trigger Types

F0 audits the real verifier/recovery action space and keeps the following trigger semantics in the matrix:

- `MISSING_REQUIRED_CONTEXT`;
- `AMBIGUOUS_QUERY`;
- `INSUFFICIENT_EVIDENCE`;
- `WRONG_SCOPE_RETRIEVAL`;
- `PARTIAL_PROCEDURE`;
- `CONFLICTING_EVIDENCE`.

Only source/task structures actually instantiated by the F0 candidate generator count toward Recovery-oriented coverage.

## 18. Recovery Action Matrix

The action matrix is grounded in the current Production `VerificationAction` capability space:

```text
CLARIFY
REWRITE
SUPPLEMENT
DECOMPOSE
RELAX_FILTERS
HANDOFF
```

Important examples:

- missing user-owned context → `CLARIFY` ALLOWED; blind `SUPPLEMENT`/`REWRITE` FORBIDDEN;
- wrong-scope retrieval → `REWRITE` ALLOWED; `SUPPLEMENT`/`DECOMPOSE`/`RELAX_FILTERS` CONDITIONAL;
- partial procedure → `SUPPLEMENT` ALLOWED;
- conflicting evidence → `HANDOFF` ALLOWED.

This is a capability matrix, not evidence that any recovery action has actually executed.

## 19. Observed vs Candidate Recovery Boundary

F0 strictly freezes:

```text
Observed Production First-pass Failures = 0
Real Recovery Runs                       = 0
Recovered Cases                          = 0
```

`RECOVERY_ORIENTED` therefore means only that the challenge structure has a source- and policy-supported recovery path if a future real first pass fails. It does not mean a failure or recovery has been observed.

## 20. Scenario Families

Final validated pool contains 50 scenario families.

Variant distribution:

```text
34 scenario families have 1 retained variant
16 scenario families have 2 retained variants
max retained variants / scenario = 2
```

Clarification and sufficient-context variants are grouped under the same `scenario_family_id` to prevent future split leakage.

## 21. Procedure Families

Final validated pool contains 22 procedure families.

Maximum retained candidates from a single procedure family: 5.

All candidates carry:

- document family;
- product family;
- source unit ID;
- procedure family ID;
- scenario family ID;
- semantic family ID.

No split is executed in F0.

## 22. Candidate Generation

Generation order is deterministic:

```text
Knowledge Corpus
→ TroubleshootingSourceUnit
→ Task Semantics
→ Required Context
→ Expected Behavior
→ RecoveryEligibility
→ Candidate Query
```

Generation method:

```text
DETERMINISTIC_SOURCE_UNIT_PLAN + CONTROLLED_LANGUAGE_RENDERER
```

LLM surface generation is not used.

## 23. Source Validation

Each retained candidate validates:

- document exists;
- section exists;
- SourceUnit exists;
- product relation is consistent;
- symptom/task structure is source-backed;
- required context is supported;
- required steps exist;
- conditional behavior is supported;
- safety/handoff behavior is supported where required;
- query does not leak target action;
- no private structured source is needed;
- recovery trigger/action is allowed by the real capability matrix.

## 24. Query Leakage

Validation fails closed on:

- verbatim target action leaked into the query;
- product/model leaked into a product-missing clarification case;
- internal `<ORDER_REF>`, `<TICKET_REF>`, `<WARRANTY_REF>` structured tokens;
- mixed/private dependency leakage;
- broad section-scope prompts without bounded Gold semantics.

Final validated pool has zero exact/normalized query duplicates.

## 25. Mixed Leakage

F0 is Knowledge Troubleshooting / Clarification / Recovery-oriented construction, not Private or Mixed construction.

Candidates that require private Ticket/Order/Warranty structured lookup are rejected from F0. The frozen Mixed E1-R benchmark remains the correct home for Ticket → Product → Manual tasks.

## 26. Existing Formal Collision

Existing Formal audit confirms:

```text
Existing Formal Troubleshooting cases  2
Existing Formal Mixed cases           10
```

Cross-stage collision filter rejected:

```text
8 unique candidates colliding with protected current Formal sections
4 candidates colliding with frozen Mixed Manual Gold facts
0 exact-query collisions
```

The raw report contains 9 Formal-section collision occurrences because one candidate was encountered through more than one protected reference; there are 8 unique candidate IDs.

## 27. Dedup

Final validated pool:

```text
Exact query duplicates                 0
Normalized query duplicates            0
Same source-unit excess               44
Same scenario-family excess           16
Same semantic-signature excess         5
Cross-product same-action excess       5
```

Repeated SourceUnits are not automatically duplicates because the same real scenario may yield Direct, Clarification, Control, Handoff, or Recovery-oriented variants. Effective diversity is therefore reported separately.

## 28. Source Concentration

```text
Max candidates / document     10 / 66 = 15.15%
Max candidates / section       5 / 66 = 7.58%
Max candidates / SourceUnit    5 / 66 = 7.58%
```

The phase's section-level >10% warning is not triggered.

## 29. Effective Diversity

```text
Raw Candidates                 100
SOURCE_VALIDATED                66
Effective Semantic Units        61
Semantic Duplicate Excess        5
Scenario Families               50
Procedure Families              22
Surface Variations               0
```

Effective semantics, not unique candidate IDs, is the capacity measure used for downstream planning.

## 30. Future Split Keys

Every candidate carries stable split-group keys for:

- `document_family`;
- `product_family`;
- `source_unit_id`;
- `procedure_family_id`;
- `scenario_family_id`;
- `semantic_family_id`.

Base/clarification/recovery challenge variants must remain in one split group in future Trusted Test construction.

## 31. Raw Candidates

```text
Raw Candidate Count = 100
Raw Status          = CANDIDATE only
```

No raw candidate is marked `FORMAL_ELIGIBLE`, `HUMAN_REVIEWED`, or `RECOVERED`.

## 32. Source Validated

```text
SOURCE_VALIDATED = 66
```

Primary task-type distribution is recorded in section 7.

## 33. Rejected

```text
Rejected candidates = 34
```

Reason occurrences are non-mutually-exclusive:

```text
SOURCE_UNIT_NOT_BENCHMARK_USABLE   20
REQUIRED_STEPS_MISSING             18
DUPLICATE_EXISTING_FORMAL_SECTION   9
SCOPE_TOO_BROAD                     5
DUPLICATE_FROZEN_MIXED_MANUAL_FACT  4
```

The important quality tightening is that preventive-only source material and non-actionable knowledge fragments are rejected rather than used to raise product/source coverage.

## 34. Artifacts

Generated under `artifacts/evaluation/dataset-expansion-f0-troubleshooting/`:

- `troubleshooting_source_units.jsonl`
- `troubleshooting_source_unit_report.json`
- `troubleshooting_task_plans.jsonl`
- `troubleshooting_raw_candidates.jsonl`
- `troubleshooting_source_validated.jsonl`
- `troubleshooting_rejected.jsonl`
- `troubleshooting_candidate_manifest.json`
- `troubleshooting_semantic_families.json`
- `troubleshooting_scenario_families.json`
- `troubleshooting_behavior_distribution.json`
- `troubleshooting_product_coverage.json`
- `troubleshooting_document_coverage.json`
- `troubleshooting_step_structure.json`
- `troubleshooting_context_requirements.json`
- `troubleshooting_clarification_candidates.jsonl`
- `troubleshooting_false_clarification_controls.jsonl`
- `troubleshooting_handoff_candidates.jsonl`
- `troubleshooting_recovery_eligibility.jsonl`
- `troubleshooting_recovery_action_matrix.json`
- `troubleshooting_source_concentration.json`
- `troubleshooting_dedup_report.json`
- `troubleshooting_existing_collision_report.json`
- `troubleshooting_effective_diversity.json`
- `phase_f0_summary.json`

Also updated, without overwriting history:

- `artifacts/evaluation/benchmark-expansion-roadmap-status.json`

## 35. Code Changes

New construction code:

- `evals/benchmark/expansion/troubleshooting_candidate.py`
- `evals/benchmark/expansion/troubleshooting_source.py`
- `evals/benchmark/expansion/troubleshooting_plan.py`
- `evals/benchmark/expansion/troubleshooting_context.py` was not created because context semantics fit the candidate/source contracts without a separate module.
- `evals/benchmark/expansion/troubleshooting_recovery.py`
- `evals/benchmark/expansion/troubleshooting_validation.py`
- `evals/benchmark/expansion/troubleshooting_dedup.py` was not created because dedup remains small and is implemented through the existing reporting/runner path.
- `evals/benchmark/expansion/troubleshooting_reporting.py`
- `evals/benchmark/expansion/f0_runner.py`

Modified integration files:

- `evals/benchmark/expansion/__init__.py`
- `eval_platform/cli.py`

New tests:

- `tests/evaluation/test_dataset_expansion_f0_troubleshooting.py`

Unified CLI:

```bash
python -m eval_platform.cli \
  dataset-expand-troubleshooting \
  --root . \
  --d0 artifacts/evaluation/dataset-expansion-d0 \
  --output artifacts/evaluation/dataset-expansion-f0-troubleshooting
```

## 36. Tests

Final test results:

```text
F0 targeted tests       18 passed
Evaluation tests       302 passed, 2 skipped
Full repository tests  516 passed, 2 skipped
compileall              PASS
```

The two existing skipped tests remain real Production / real Judge integration dependency skips. These are engineering regression results, not Agent quality or Recovery metrics.

## 37. Formal Dataset Invariance

Formal Canonical remains:

```text
Development  34
Validation    5
Formal Total 39
New Formal    0
```

No F0 candidate is written to canonical data.

## 38. Production Diff and Next Stable Inputs

Production behavior directories remain byte-identical to the E1-R baseline:

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

`Production behavior changed = 0`.

Stable inputs for the next phase:

- `troubleshooting_source_units.jsonl`
- `troubleshooting_task_plans.jsonl`
- `troubleshooting_source_validated.jsonl`
- `troubleshooting_candidate_manifest.json`
- `troubleshooting_semantic_families.json`
- `troubleshooting_scenario_families.json`
- `troubleshooting_context_requirements.json`
- `troubleshooting_step_structure.json`
- `troubleshooting_clarification_candidates.jsonl`
- `troubleshooting_false_clarification_controls.jsonl`
- `troubleshooting_handoff_candidates.jsonl`
- `troubleshooting_recovery_eligibility.jsonl`
- `troubleshooting_recovery_action_matrix.json`
- `troubleshooting_existing_collision_report.json`
- `troubleshooting_effective_diversity.json`

The next phase should be Troubleshooting Gold Preparation: freeze per-case required steps, conditions, context slots, safety/handoff requirements, evidence, response behavior, and Recovery eligibility without claiming observed Recovery.
