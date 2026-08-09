# DATA EXPANSION PHASE G0.2 — KNOWLEDGE TASK PLANNING

## 1. G0.2 Summary

Phase G0.2 is **COMPLETE**.

The phase consumes the frozen G0.1 Knowledge Source Space and performs deterministic, capability-balanced selection and task-semantic planning only. It does **not** render user queries and does not construct Candidates, Gold, annotation packets, or Formal cases.

Final planning state:

```text
Effective KSU input             1195
TaskPlan proposals              1318
PLANNED                          180
DEFERRED                        1065
REJECTED                          73
Effective TaskPlan semantics     180
Semantic duplicate excess          0
Knowledge sources                 22 / 22
Products                          20 / 20
G0.1 source topics selected       17 / 18
New Queries                        0
New Candidates                     0
New Formal Cases                   0
Annotation Runs                    0
Production Agent              NOT RUN
```

The only G0.1 source topic not selected is `warranty_rule`; its sole effective KSU carries `POLICY_AMBIGUITY`, so it is deliberately excluded from the first wave instead of being retained for topic coverage.

## 2. G0.1 Frozen Inputs

The input source-space manifest is frozen at:

```text
Effective SourceUnits:
1195

knowledge_source_space_hash:
206fac5baaf012483066e913e56bfb10fb6ce97cc1d4d6dfeb9b22b8800cc40b

corpus_fingerprint:
ddb153a29a039f7b0e00b04eefe6f666809577ac10d8f4ae8be4c71a8d6da6eb
```

G0.2 does not rewrite, merge, repair, or reclassify G0.1 KSU truth. If a KSU/fact is unsuitable for a task plan, G0.2 rejects or defers the plan.

Previous frozen assets remain unchanged:

```text
Formal Canonical              39
Private Frozen Packets        76
Mixed Frozen Packets          58
Troubleshooting F0 Source-valid 66
D3-R                          DEFERRED_BY_ENVIRONMENT
```

## 3. Selection Strategy

Planning uses deterministic constrained selection:

```text
Hard quality filter
→ effective KSU representative folding
→ P0/P1/P2 priority
→ previously-uncovered source reservation
→ rare/high-value task-type reservation
→ source/product balancing
→ multi-fact / multi-section reservation
→ difficulty balancing
→ P0/P1 deterministic fill
→ dedup / concentration recheck
```

Pure random sampling is not used. Stable hashes are used for deterministic IDs and tie behavior.

## 4. P0 / P1 / P2

Effective KSU eligibility:

```text
P0 available   654
P1 available   532
P2 available     9
```

Final selection:

```text
P0 selected    135
P1 selected     45
P2 selected      0
```

P1 is intentionally represented in ordinary Direct/Spec/Feature capability coverage so the first wave does not collapse into an almost all-P0 set. P2 is not used to fill the target.

## 5. Task Type Taxonomy

Primary task type is independent from source Fact Type.

Final primary types:

| Task Type | Plans | Ratio |
|---|---:|---:|
| DIRECT_FACT | 21 | 11.67% |
| PRODUCT_SPEC | 12 | 6.67% |
| FEATURE_OR_INSTRUCTION | 42 | 23.33% |
| COMPATIBILITY | 21 | 11.67% |
| LIMITATION | 12 | 6.67% |
| POLICY_OR_WARRANTY | 12 | 6.67% |
| FAQ_PROCESS | 5 | 2.78% |
| MULTI_FACT_SYNTHESIS | 42 | 23.33% |
| MULTI_SECTION_SYNTHESIS | 13 | 7.22% |

## 6. Source Balance

All 22 knowledge sources are represented.

Largest ordinary document concentrations:

```text
LIO-PROD-004 Fitness Tracker     12 / 180 = 6.67%
LIO-PROD-006 Refrigerator       11 / 180 = 6.11%
LIO-PROD-013 Dishwasher         10 / 180 = 5.56%
```

No document exceeds the 8% concentration warning threshold.

## 7. Product Balance

All 20 product manuals are represented.

Highest product plan count is 12; lowest is 4. Selection is not uniform by product, because source diversity is not equivalent to equal quota sampling.

## 8. Semantic Topic Balance

G0.1 exposes 18 source semantic topics. G0.2 selects 17.

The missing topic is:

```text
warranty_rule
```

Its only effective source unit is ambiguous and therefore not forced into the first wave.

Largest selected source-topic contribution is compatibility-related source material at 29 source-unit occurrences across 180 plans (16.11%). No source semantic topic exceeds 20%.

Composition relation labels are reported separately from the original G0.1 source topics and are not used to inflate source-topic coverage.

## 9. Previously Untested Sources

All five sources previously absent from Formal evidence are selected:

| Source | G0.1 Effective KSU | Planned | Effective |
|---|---:|---:|---:|
| Air Purifier | 30 | 7 | 7 |
| Air Conditioner | 72 | 9 | 9 |
| Steam Cleaner | 27 | 8 | 8 |
| Bluetooth Laser Mouse | 22 | 8 | 8 |
| Support FAQ | 8 | 8 | 8 |

No source is retained merely because it was previously untested; all selected plans still pass the common quality gates.

## 10. Feature / Instruction Cap

```text
FEATURE_OR_INSTRUCTION = 42 / 180 = 23.33%
```

The hard 25% cap passes.

This is intentionally far below the raw corpus distribution, where Feature/Instruction dominates AtomicFacts.

## 11. Direct / Spec

```text
DIRECT_FACT    21
PRODUCT_SPEC   12
Combined       33 / 180 = 18.33%
```

The 20% Direct+Spec cap passes, preventing the first wave from becoming a parameter-lookup benchmark.

## 12. Compatibility

G0.1 contains 47 `COMPATIBILITY_RELATION` KSU. After effective representative folding and plan-quality validation, the planner has 43 compatibility proposals, 39 quality-valid proposals, and selects 21.

Compatibility plans freeze subject/relation/object semantics through required facts and evidence; Query wording is deferred.

## 13. Limitation

G0.1 contains 14 KSU whose relationship is explicitly `LIMITATION`. Planning classification also detects a small number of independently askable limitation facts from other KSU structures.

```text
Limitation proposals       16
Quality-valid              15
Selected                   12
```

The first wave prioritizes limitation capacity without forcing all available instances.

## 14. Policy / Warranty

```text
POLICY_OR_WARRANTY plans    12
Unique primary source units 12
Unique required fact sets   12
```

Three selected plans come from the central after-sales policy; other selected plans use source-grounded warranty information present in product manuals.

Plans carrying `POLICY_AMBIGUITY` are rejected rather than converted into absolute policy decisions.

## 15. FAQ

Support FAQ contains 8 effective G0.1 Q/A SourceUnits.

All 8 FAQ SourceUnits are represented somewhere in the first-wave plans. Five are primary `FAQ_PROCESS` plans; the remaining represented FAQ units participate in bounded multi-fact plans rather than being duplicated as additional FAQ paraphrases.

FAQ sentence inflation remains prohibited.

## 16. Multi-fact Planning

```text
MULTI_FACT_SYNTHESIS plans  42
Average required facts     2.67
Maximum required facts        3
```

All are derived from G0.1 minimal coherent fact groups. Required fact sets remain 2–3 facts and supporting-only facts are not promoted into required facts.

Construction-level necessity failures in the selected set: **0**.

## 17. Multi-section Planning

Final:

```text
MULTI_SECTION_SYNTHESIS plans   13
Average sections / plan          2.0
Maximum sections / plan          2
```

The original planning attempt could construct 24 Multi-section plans using same-product complementary-topic + lexical-overlap heuristics. Human-readable auditing exposed false compositions such as unrelated installation and voltage facts from the same product.

That approach was rejected.

Final Multi-section planning now requires:

```text
same product domain
+ different stable sections
+ independent source facts
+ non-fragment / non-navigation facts
+ explicit cross-section concept reference
+ relation-specific semantic evidence
+ both evidence units necessary by the construction contract
```

Generic `SAME_TOPIC_CROSS_REFERENCE` or fallback `EXPLICIT_CROSS_REFERENCE` alone is not sufficient for a PLANNED composition.

The final count of 13 is below the planning suggestion of 18–24. This is an intentional quality result, not a capacity failure.

## 18. Required Facts

Every TaskPlan freezes `required_fact_ids[]` before Query Rendering.

Examples of valid structural shapes:

```text
SINGLE_FACT
→ exactly 1 required fact

BOUNDED_FACT_SET
→ 2–3 required facts

MULTI_FACT_SYNTHESIS
→ >=2 required facts

MULTI_SECTION_SYNTHESIS
→ facts backed by >=2 stable sections
```

## 19. Supporting Facts

`supporting_fact_ids[]` is separate from required facts.

The planner never adds a fact merely to make a task look multi-fact. A fact that is not needed for answer completeness stays supporting or is omitted.

## 20. Evidence

Every plan freezes `required_evidence_ids[]` at stable section level.

For multi-section plans, at least two distinct evidence sections are required.

Whole-document evidence is not used as the only evidence identity.

## 21. Answer Scope

Final distribution:

```text
SINGLE_FACT               87
BOUNDED_FACT_SET           29
COMPATIBILITY_JUDGMENT     21
PROCEDURE_SUBSET           18
SYNTHESIZED_CONCLUSION     13
LIMITATION_JUDGMENT        12
```

Answer scope is frozen before Query Rendering to prevent G0.3 from generating broad questions with narrow fact sets.

## 22. Reasoning Type

Final distribution:

```text
DIRECT_LOOKUP               53
MULTI_FACT_SYNTHESIS        42
COMPATIBILITY_REASONING     21
MULTI_SECTION_SYNTHESIS     13
POLICY_INTERPRETATION       12
LIMITATION_REASONING        12
ATTRIBUTE_LOOKUP            12
CONDITION_APPLICATION       10
SET_RETRIEVAL                5
```

## 23. Difficulty

Difficulty is derived from task structure, not query length:

```text
EASY       70   38.89%
MEDIUM     69   38.33%
HARD       41   22.78%
```

This satisfies the first-wave planning guidance without artificially composing unrelated sources to manufacture HARD cases.

## 24. Rendering Constraints

All 180 plans freeze rendering constraints:

```text
allowed_user_context
required_user_context
forbidden_answer_terms
forbidden_internal_terms
must_not_expand_scope
must_not_reveal_answer
product_name_allowed
expected_query_intent
answer_scope
```

`candidate_query` does not exist in G0.2 artifacts.

## 25. Plan-level Dedup

```text
PLANNED TaskPlans             180
Unique Plan Signatures        180
Effective Task Semantics      180
Semantic Duplicate Excess       0
Cross-product Duplicate Plans   0
Unique Fact Sets              180
Unique Evidence Sets          169
```

Earlier planning exposed two Air-conditioner facts equivalent to “部分机型不支持此功能”. They are now rejected as unresolved deictic source-unit issues rather than being counted as independent plans.

## 26. Cross-product Duplicates

G0.1 identified generic cross-product semantic duplicates. The first wave defaults to one effective representative per cross-product semantic signature.

Final selected cross-product duplicate plans:

```text
0
```

## 27. Cross-stage Collision

Single-fact exact reuse is filtered against existing assets:

```text
COLLIDES_FORMAL_FACT   30 rejected proposals
COLLIDES_MIXED_FACT    28 rejected proposals
```

Active Troubleshooting overlap is an exclusive rejection gate for both single and composite plans.

The selected set contains no Troubleshooting-owned required facts.

A small number of composite plans contain facts previously observed in Formal/Mixed contexts, but only when the required fact set + evidence set + reasoning + answer scope creates a distinct Knowledge task. This is reported separately and is not treated as an exact plan duplicate.

## 28. Source Concentration

```text
Max plans / document      12 / 180 = 6.67%
Max plans / section        2
Sections with 2 plans     22
Sections >2                0
Max SourceUnit reuse       2
```

SourceUnit reuse above one occurs only through explicit multi-section composition; a KSU is otherwise used at most once as a primary source.

## 29. Semantic Concentration

Maximum semantic-family concentration:

```text
20 / 180 = 11.11%
```

The 12% warning threshold is not triggered.

Maximum original G0.1 source-topic contribution is 16.11%, below the 20% topic warning threshold.

## 30. Effective Plan Diversity

```text
TaskPlans                  180
Effective semantics        180
Duplicate excess             0
Unique fact sets           180
Unique evidence sets       169
```

The first wave therefore represents planned capability diversity rather than wording variation.

## 31. Future Split Keys

All 180 plans freeze:

```text
document_family
product_family
section_family
fact_family
semantic_family_id
source_unit_ids
composition_family_id
```

No split is executed in G0.2.

## 32. TaskPlan Manifest

Current manifest:

```text
schema_version        g0.2-knowledge-task-plan-1
planning_version      deterministic-balanced-knowledge-planning-g0.2-1
eligible_ksu_count    1195
proposal_count        1318
planned_count          180
deferred_count        1065
rejected_count          73
effective_plan_count   180
source_count             22
product_count            20
source topic count        17
task type count            9
max active Candidate / plan 1
```

TaskPlan set hash:

```text
f8cabae08e04aeb30d61cb5e7fd605ef0e947d768b828256e5a610e2df098a0d
```

A full rerun from the same frozen G0.1 input reproduces the same selected KSU set, Plan IDs, counts, and TaskPlan-set hash.

## 33. Artifacts

G0.2 produces:

```text
artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning/

knowledge_selection_eligible_pool.jsonl
knowledge_selection_priority_report.json
knowledge_source_balance_plan.json
knowledge_task_type_quota.json
knowledge_multi_fact_compositions.jsonl
knowledge_multi_section_compositions.jsonl
knowledge_task_plan_proposals.jsonl
knowledge_task_plans.jsonl
knowledge_task_plan_deferred.jsonl
knowledge_task_plan_rejected.jsonl
knowledge_task_plan_manifest.json
knowledge_task_type_distribution.json
knowledge_reasoning_distribution.json
knowledge_answer_scope_distribution.json
knowledge_difficulty_distribution.json
knowledge_document_balance.json
knowledge_product_balance.json
knowledge_semantic_topic_balance.json
knowledge_semantic_family_balance.json
knowledge_previous_uncovered_source_selection.json
knowledge_plan_dedup_report.json
knowledge_plan_cross_stage_collision.json
knowledge_plan_concentration_report.json
knowledge_task_plan_effective_diversity.json
phase_g0_2_summary.json
```

## 34. Tests

Dedicated G0.2 tests cover:

```text
G0.1 source-space freeze
1195 effective representative reconstruction
no Query/Candidate/Gold construction
180 PLANNED / 180 Effective semantics
P0/P1/P2 selection
Feature and Direct/Spec caps
Task-type coverage
Difficulty balance
22/22 source and 20/20 product coverage
5/5 previously-uncovered sources
source-topic balance
multi-fact minimality
strong multi-section relation evidence
unresolved deictic rejection
Troubleshooting ownership exclusion
hard plan validation
rendering-constraint completeness
future split keys
section/KSU reuse bounds
FAQ/Policy inflation guards
frozen prior assets
full planning reproducibility
```

Final regression results:

```text
G0.2 dedicated       22 passed
Evaluation suite     343 passed, 2 skipped
Full repository      557 passed, 2 skipped
compileall           PASS
```

The two skips remain the existing real Production / real Judge integration dependency skips. These are engineering/data-construction regression results, not Knowledge QA accuracy.

## 35. Formal Invariance

G0.2 creates no Formal sample.

Expected and verified canonical baseline:

```text
Development  34
Validation    5
Formal       39
```

## 36. Production Diff

G0.2 is Dataset Construction only.

The following Production behavior directories are hash-compared against the G0.1 input baseline:

```text
agents/
tools/
retrieval/
context_engine/
memory/
artifact/
governance/
observability/
production/
deployments/
```

Final SHA comparison against the G0.1 input baseline:

```text
Production behavior changed files = 0
```

The entire G0.1 source-space artifact directory is byte-identical to the input baseline. Private D2, Mixed E1-R, Troubleshooting F0, D3-R history, and both canonical Formal files are also unchanged.

## 37. G0.3 Stable Inputs

G0.3 Controlled Query Rendering may depend on:

```text
knowledge_task_plans.jsonl
knowledge_task_plan_manifest.json
knowledge_task_type_distribution.json
knowledge_reasoning_distribution.json
knowledge_answer_scope_distribution.json
knowledge_difficulty_distribution.json
knowledge_document_balance.json
knowledge_product_balance.json
knowledge_semantic_topic_balance.json
knowledge_semantic_family_balance.json
knowledge_previous_uncovered_source_selection.json
knowledge_plan_dedup_report.json
knowledge_plan_cross_stage_collision.json
knowledge_plan_concentration_report.json
knowledge_task_plan_effective_diversity.json
```

The next phase must preserve the frozen task semantics and may render at most one active Candidate per TaskPlan. It must not multiply each plan into paraphrase-counted data.
