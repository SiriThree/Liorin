# DATA_EXPANSION_PHASE_G0_4_KNOWLEDGE_GOLD_PREPARATION

# 1. G0.4 Summary

Phase G0.4 completed Knowledge Gold Preparation for the frozen G0.3 SOURCE_VALIDATED pool and froze future dual-annotation packets.

```text
Input SOURCE_VALIDATED          171
Query Review excluded            8
G0.3 Rejected excluded           1
Drafted                         171
READY_FOR_DUAL_ANNOTATION       146
NEEDS_MANUAL_PRECHECK            25
REJECTED_BEFORE_ANNOTATION        0
Effective Gold Units            146
Annotation Packets              146
Annotation Runs                   0
New Formal Cases                  0
Production Agent            NOT RUN
D3-R              DEFERRED_BY_ENVIRONMENT
```

The lower READY count is deliberate. The 25 PRECHECK cases expose a real Gold-completeness boundary in broad MULTI_FACT queries; G0.4 does not rewrite the query or inflate Gold with the whole section.

# 2. Frozen Input / Isolation

G0.4 consumes only `knowledge_source_validated.jsonl` from G0.3.

```text
Validated input                  171
G0.3 query review                 8  EXCLUDED
G0.3 rejected                     1  EXCLUDED
Candidate-set hash
c21d9412fc16be1f1b2d56a8e349641c3c1c9f3866e9eee358565890096dd1e5
```

The 171 candidate IDs are disjoint from the 8 review IDs and the 1 rejected ID. Candidate query text and `query_sha256` are unchanged.

# 3. Knowledge Gold Draft Contract

Each draft preserves candidate/task lineage and stores:

- candidate/task identifiers and immutable query;
- primary task type, semantic family, reasoning type, difficulty, answer scope;
- `gold_facts`, `optional_facts`, `gold_evidence`;
- comparison, reasoning, and TaskSuccess contracts;
- answerability, ambiguity, annotation status, review requirements;
- source lineage and Gold-level information signature.

No production prediction, agent answer, judge result, or annotation output is used to construct Gold.

# 4. Task Type Gold Status

| Task type | Input | READY | PRECHECK | REJECT |
|---|---:|---:|---:|---:|
| COMPATIBILITY | 17 | 17 | 0 | 0 |
| DIRECT_FACT | 17 | 17 | 0 | 0 |
| FAQ_PROCESS | 5 | 5 | 0 | 0 |
| FEATURE_OR_INSTRUCTION | 42 | 42 | 0 | 0 |
| LIMITATION | 12 | 12 | 0 | 0 |
| MULTI_FACT_SYNTHESIS | 42 | 17 | 25 | 0 |
| MULTI_SECTION_SYNTHESIS | 13 | 13 | 0 | 0 |
| POLICY_OR_WARRANTY | 11 | 11 | 0 | 0 |
| PRODUCT_SPEC | 12 | 12 | 0 | 0 |


# 5. Gold Facts / Fact Roles

```text
Gold facts total       260
ANSWER_REQUIRED         252
REASONING_REQUIRED      0
SUPPORTING_ONLY           8
OPTIONAL_OUTPUT           0
```

Eight structural/intro facts are retained as supporting context rather than promoted to answer requirements. Six candidates required explicit role correction during alignment. No artificial `REASONING_REQUIRED` or `OPTIONAL_OUTPUT` facts were created merely to fill taxonomy buckets.

# 6. Comparison Contract

Construction-level modes:

```json
{
  "CONDITIONAL": 40,
  "EXACT_VALUE": 4,
  "NUMERIC": 1,
  "ORDERED_SEQUENCE": 45,
  "SEMANTIC": 102,
  "UNORDERED_SET": 60
}
```

Evaluator mapping:

```json
{
  "NORMALIZED_EXACT": 4,
  "NUMERIC": 1,
  "SEMANTIC": 247
}
```

Numeric Gold has no invented tolerance. Procedure facts use semantic ordered-sequence semantics where source order matters; multi-fact bounded sets use semantic unordered-set semantics.

# 7. Evidence

```text
GoldEvidence rows                  184
Unique evidence IDs                163
Documents                          22
Stable sections                    163
Whole-document violations           0
Unstable-section violations         0
```

Each evidence unit is document + stable section scoped, with source fact lineage. Whole manuals are never the sole required evidence.

# 8. Direct / Product Spec

`DIRECT_FACT` is 17/17 READY and `PRODUCT_SPEC` is 12/12 READY. Gold remains bounded to the frozen requested fact set; section-neighbor facts are not added simply because they exist in the source.

# 9. Feature / Instruction

`FEATURE_OR_INSTRUCTION` is 42/42 READY. Procedure-subset cases preserve only the requested operation/step scope. Gold does not expand a specific operation query into an entire procedure.

# 10. Compatibility

`COMPATIBILITY` is 17/17 READY. Comparison semantics are conditional/semantic rather than a bare boolean. Conditions and exceptions remain source-supported when present.

# 11. Limitation

`LIMITATION` is 12/12 READY. Gold freezes the limitation target/scope/condition represented by the source facts and does not infer additional restrictions.

# 12. Policy / Warranty

```text
Input                         11
Qualification preserved       11
Exception preserved           11
Absolute conversion           0
Region hallucination          0
Effective-time hallucination  0
Ambiguity                     0
```

All 11 validated Policy/Warranty candidates are READY. Qualified or conditional source wording is not normalized into an absolute guarantee.

# 13. FAQ

All 5 primary `FAQ_PROCESS` candidates are READY. FAQ Gold is grounded in answer semantics rather than exact canonical FAQ wording. Support FAQ also contributes multi-fact source units without sentence-level QA inflation.

# 14. Multi-fact Gold Audit

```text
Input                         42
READY                         17
PRECHECK                      25
REJECT                        0
Average ANSWER_REQUIRED       2.5
Necessity failures            3
Planned facts demoted           5
Facts promoted                  0
```

This is the only task family with significant Gold-preparation fallout. G0.4 does not convert the broad query into a narrower one and does not add the whole section to Gold.

# 15. Multi-section Gold Audit

```text
Input      13
READY      13
PRECHECK    0
REJECT      0
```

All 13 retain at least two required stable sections and pass the frozen two-section necessity relationship. `derived_fact_count = 0`: none of these 13 requires inventing a new deterministic conclusion beyond the frozen answer scope.

# 16. Gold Completeness

```text
Completeness issues found       24
Remaining PRECHECK               24
Role-correction cases             6
```

The 24 completeness issues are broad multi-fact queries whose wording can reasonably imply more section facts than the frozen 2–3 fact group. They remain PRECHECK.

# 17. Gold Minimality

```text
Minimality issues found      0
Remaining                     0
Role corrections              6
```

No READY Gold is expanded with irrelevant source facts. Structural headings/intros are demoted instead of becoming required answer claims.

# 18. Query ↔ Gold ↔ Evidence Alignment

```text
Input              171
Fully aligned      146
Cases with issues  25
```

Issue distribution:

```json
{
  "BROAD_GROUP_SCOPE_COMPLETENESS_UNCERTAIN": 24,
  "MULTI_FACT_ANSWER_SET_TOO_SMALL_AFTER_ROLE_CORRECTION": 3
}
```

Role corrections:

```json
{
  "NON_INFORMATIONAL_REQUIRED_FACT_DEMOTED": 6
}
```

# 19. Gold-level Dedup

```text
Drafted                         171
READY                           146
Effective Gold Units            146
Semantic Duplicate Excess       0
Unique Required Fact Sets       146
Unique Required Evidence Sets   137
```

An earlier implementation over-demoted factual propositions as headings and produced false duplicate groups. The heading classifier was narrowed before freeze. Final READY Gold has zero semantic duplicate excess.

# 20. Cross-stage Collision

```text
Formal exact Gold collision                0
Mixed source-fact overlap                  1
Troubleshooting source-fact overlap        0
```

The single Mixed overlap is a source-fact overlap, not an exact task-semantic/Gold duplicate, and is reported rather than silently rejected.

# 21. Effective Gold Diversity

```text
Drafted                171
READY                  146
Effective Gold Units   146
Duplicate Excess         0
```

READY is the denominator used for annotation packet capacity; PRECHECK remains drafted but is not annotation-ready.

# 22. Document Coverage

```text
G0.3 validated documents   22 / 22
G0.4 READY documents       22 / 22
Max READY / document       14
```

Quality filtering did not reduce document coverage.

# 23. Product Coverage

```text
G0.3 validated products   20 / 20
G0.4 READY products       20 / 20
```

All 20 products remain represented in READY Gold.

# 24. Previously Untested Sources

| Source | Input | READY | PRECHECK | REJECT |
|---|---:|---:|---:|---:|
| Air Purifier | 7 | 5 | 2 | 0 |
| Air Conditioner | 9 | 5 | 4 | 0 |
| Steam Cleaner | 8 | 8 | 0 | 0 |
| Bluetooth Laser Mouse | 8 | 4 | 4 | 0 |
| Support FAQ | 8 | 8 | 0 | 0 |


These sources are not forced to 100% READY. Air Purifier, Air Conditioner, and Bluetooth Laser Mouse expose the same broad multi-fact scope issue as the overall pool.

# 25. Annotation Packets

```text
Packet count        146
Unique packet hash  146
Unique snapshots    146
Isolation verified  True

Batch ID
KNOW-G0.4-1F5135FE1652

Batch Hash
1f5135fe16523c9f6a6f4535312cfb624652a917027a08fe2d06a17aa4bf154c

Gold Set Hash
9f8904172275995a7d181a6319a7bed960602abf773d6e7c0ec7efaef75c0624
```

Only READY candidates receive packets.

# 26. Precheck Queue

```text
Total PRECHECK   25
```

Reasons (reason counts can overlap):

```json
{
  "BROAD_GROUP_SCOPE_COMPLETENESS_UNCERTAIN": 24,
  "MULTI_FACT_ANSWER_SET_TOO_SMALL_AFTER_ROLE_CORRECTION": 3
}
```

Interpretation:
- `BROAD_GROUP_SCOPE_COMPLETENESS_UNCERTAIN`: query asks broadly for related requirements while selected Gold contains only a small coherent group from a richer section.
- `MULTI_FACT_ANSWER_SET_TOO_SMALL_AFTER_ROLE_CORRECTION`: a planned heading/intro was correctly demoted, leaving fewer than two genuine answer claims for a multi-fact task.

# 27. Rejected Before Annotation

```text
REJECTED_BEFORE_ANNOTATION = 0
```

Final reject reasons are empty. Gold-level false duplicate rejects observed during development were eliminated by fixing the over-broad structural-heading classifier before final freeze.

# 28. G0.3 Query Review 8

`UNCHANGED / EXCLUDED`.

The 8 `NEEDS_QUERY_REVIEW` candidates from G0.3 are not read as G0.4 Gold input, not repaired, and not included in packets.

# 29. G0.3 Rejected 1

`UNCHANGED / EXCLUDED`.

The active-troubleshooting drift candidate remains rejected in G0.3 and is not revived.

# 30. New Formal Cases

```text
0
```

# 31. Annotation Runs

```text
0
```

Packets are frozen for future A/B annotation only. No annotator decisions, agreement, adjudication, or human review occurred.

# 32. Production Agent

```text
NOT RUN
```

No Support Graph, Knowledge Agent, Retriever, Verifier, Production LLM, or Evaluation Judge was invoked for Gold construction.

# 33. D3-R

```text
DEFERRED_BY_ENVIRONMENT
```

Private real dual annotation remains deferred; G0.4 does not change D3-R state.

# 34. Existing Formal Dataset

```text
Development   34
Validation     5
Formal        39
```

Canonical hashes remain:

```text
dev_v7_3_canonical_v1.json
7a4f939739a73e6f2b8faae8bdea33c5b6f375fb77d333fb625e231cc7935a5d

validation_v7_3_canonical_v1.json
df7e66e95fdd88931a1f6368d9365a3b5cef835f40211e54b801e17d6465a60c
```

# 35. Previous Frozen Assets

SHA comparison against the G0.3 input repository reports zero changed files for:

- Private D2 artifacts;
- Mixed E1-R artifacts;
- Troubleshooting F0 artifacts;
- G0.1 Knowledge Source Space;
- G0.2 Knowledge TaskPlans;
- G0.3 Knowledge Candidates;
- D3 and D3-R history;
- Formal canonical files.

D3-R summary remains:

```text
d9f958306b13e58f02704f0b8344a6a6f834cc21f4d3f159f7c5168b02166de1
```

# 36. Artifacts

New G0.4 artifact directory:

```text
artifacts/evaluation/dataset-expansion-g0-4-knowledge-gold/
├── knowledge_gold_drafts.jsonl
├── knowledge_gold_draft_report.json
├── knowledge_gold_fact_roles.json
├── knowledge_gold_evidence.json
├── knowledge_gold_comparison_contract.json
├── knowledge_gold_reasoning_contract.json
├── knowledge_gold_alignment_report.json
├── knowledge_gold_completeness_report.json
├── knowledge_gold_minimality_report.json
├── knowledge_gold_policy_audit.json
├── knowledge_gold_multi_fact_audit.json
├── knowledge_gold_multi_section_audit.json
├── knowledge_gold_dedup_report.json
├── knowledge_gold_cross_stage_collision.json
├── knowledge_gold_source_concentration.json
├── knowledge_gold_ready_distribution.json
├── knowledge_preannotation_review_queue.jsonl
├── knowledge_preannotation_rejected.jsonl
├── knowledge_source_snapshots.jsonl
├── knowledge_annotation_packets.jsonl
├── knowledge_annotation_packet_report.json
├── knowledge_annotation_batch_manifest.json
└── phase_g0_4_summary.json
```

# 37. Code Changes

New:

```text
evals/benchmark/expansion/g0_4_runner.py
evals/benchmark/expansion/knowledge_gold.py
evals/benchmark/expansion/knowledge_gold_alignment.py
evals/benchmark/expansion/knowledge_gold_annotation_packet.py
evals/benchmark/expansion/knowledge_gold_comparison.py
evals/benchmark/expansion/knowledge_gold_policy.py
tests/evaluation/test_dataset_expansion_g0_4_knowledge_gold.py
```

Modified:

```text
evals/benchmark/expansion/__init__.py
eval_platform/cli.py
```

CLI:

```bash
python -m eval_platform.cli \
  dataset-prepare-knowledge-annotation \
  --root . \
  --g0-3 artifacts/evaluation/dataset-expansion-g0-3-knowledge-rendering \
  --g0-2 artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning \
  --g0-1 artifacts/evaluation/dataset-expansion-g0-1-knowledge-source \
  --output artifacts/evaluation/dataset-expansion-g0-4-knowledge-gold
```

# 38. Tests

```text
G0.4 targeted                    25 passed
Evaluation tests (batched)     390 passed, 2 skipped
Non-evaluation tests           214 passed
Main tests total               604 passed, 2 skipped
python -m compileall -q .       PASS
```

A single long `pytest tests/evaluation` process was externally time-limited before completion; it was not counted. All 51 Evaluation test files were subsequently executed in complete batches and summed only after each batch exited successfully.

# 39. Reproducibility

```text
Gold Set Hash
9f8904172275995a7d181a6319a7bed960602abf773d6e7c0ec7efaef75c0624

Annotation Batch Hash
1f5135fe16523c9f6a6f4535312cfb624652a917027a08fe2d06a17aa4bf154c
```

A clean rerun from the same frozen G0.1/G0.2/G0.3 inputs reproduces:

- 171 drafts;
- 146 READY / 25 PRECHECK / 0 REJECT;
- identical Gold set hash;
- identical per-packet hashes;
- identical batch ID/hash.

# 40. Production Behavior Diff

SHA comparison against the G0.3 baseline for:

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

Result:

```text
Production behavior source changed files = 0
```

Generated `__pycache__` / `.pyc` files are excluded and removed before packaging.

# 41. Next Stable Inputs

The next phase can rely on:

```text
knowledge_gold_drafts.jsonl
knowledge_preannotation_review_queue.jsonl
knowledge_preannotation_rejected.jsonl
knowledge_source_snapshots.jsonl
knowledge_annotation_packets.jsonl
knowledge_annotation_batch_manifest.json
knowledge_gold_alignment_report.json
knowledge_gold_multi_fact_audit.json
knowledge_gold_multi_section_audit.json
knowledge_gold_policy_audit.json
knowledge_gold_dedup_report.json
knowledge_gold_cross_stage_collision.json
```

The immutable future annotation batch is:

```text
KNOW-G0.4-1F5135FE1652
146 packets
```

# 42. Next Phase Recommendation

The 146 READY Gold cases are high-quality and can remain frozen for future Dual Annotation. However, the 25 PRECHECK cases are highly concentrated: all are `MULTI_FACT_SYNTHESIS`, representing 25/42 of that task family.

The next Knowledge-specific action should therefore be a narrow **G0.3-R / G0.4-R scope-repair path** rather than more candidate generation:

```text
25 PRECHECK
→ preserve Source / TaskPlan intent where valid
→ narrow only genuinely broad Query scope
→ re-run Gold completeness/minimality
→ freeze additional packets if deterministic
```

The existing 146 packets must remain immutable during that repair. If breadth expansion takes priority over closing Knowledge completeness, the 146-packet Knowledge batch is already sufficient to freeze this mainline temporarily and move to Safety / Governance Expansion; but the 25 PRECHECK cases should not be silently counted as annotation-ready.

No next phase is executed automatically.
