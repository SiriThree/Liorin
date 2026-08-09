# DATA EXPANSION PHASE D2 — Private Business Gold Preparation

## 1. D2 Summary

Phase D2 converts the frozen Phase D1 `PRIVATE_BUSINESS_QUERY` candidate set into deterministic Gold Drafts and frozen annotation packets. It does **not** run Production, a Judge, dual annotators, adjudication or human review, and it does not create formal canonical samples.

Actual result:

- D1 source-validated input: **84**
- Gold Draft attempts/classified: **84 / 84**
- `READY_FOR_DUAL_ANNOTATION`: **76**
- `NEEDS_MANUAL_PRECHECK`: **8**
- `REJECTED_BEFORE_ANNOTATION`: **0**
- new formal cases: **0**
- dual-annotation runs: **0**
- human-reviewed Gold: **0**
- Production Agent: **NOT RUN**
- Judge: **NOT RUN**

D2 status: **COMPLETE**. Completion means every candidate received an explicit deterministic classification with no silent unresolved ambiguity. It does not mean the 76 READY packets are human-reviewed or formal-eligible.

## 2. D1 Inputs

D2 consumes the frozen Phase D1 artifacts under `artifacts/evaluation/dataset-expansion-d1/`, especially:

- `private_business_source_validated.jsonl`
- `private_business_candidate_manifest.json`
- `private_business_field_coverage.json`
- `private_business_state_coverage.json`
- `private_business_entity_concentration.json`
- `private_business_semantic_families.json`
- `private_business_dedup_report.json`
- `legacy_section_alias_map.json`

The candidate set hash is checked against the D1 manifest before D2 proceeds. D2 does not regenerate another Private candidate pool.

## 3. Gold Draft Contract

D2 adds `PrivateBusinessGoldDraft` as a Dataset Construction intermediate. It is not a new Evaluation runtime schema.

The draft carries:

- candidate identity and semantic family;
- expected response type;
- Phase-1/2-compatible Task Success criteria;
- field-level GoldFact drafts;
- field-level Structured GoldEvidence drafts;
- identity and tool expectations;
- answerability and ambiguity state;
- runtime materialization status;
- source provenance;
- annotation status;
- review requirements and priority;
- required vs optional facts;
- forbidden extra-disclosure scope.

Maximum D2 status is `READY_FOR_DUAL_ANNOTATION`.

## 4. Field Semantics Registry

D2 audits the **23 Structured field types actually covered by D1**, not every database column.

Classification:

- `USER_FACING`: **21**
- `BUSINESS_VALID_BUT_REVIEW`: **2**
- `INTERNAL_ONLY`: **0**
- `SENSITIVE`: **0**
- `UNSUPPORTED`: **0**

The two fields deliberately not auto-approved are:

- `ticket.priority`
- `ticket.assigned_team`

Both are exposed by the Production tool, but tool exposure alone does not prove that they are appropriate normal customer-facing benchmark facts. All candidates depending on these fields are routed to manual precheck.

`ticket.summary` is classified as user-facing for the selected D1 records, but it requires semantic comparison and receives high review priority.

The registry is materialized as `private_business_field_semantics.json`.

## 5. GoldFact Materialization

D2 materializes **99 GoldFact Drafts**:

- critical: **94**
- optional/non-critical: **5**

Value types:

- `ENUM`: **44**
- `STRING`: **26**
- `DATE`: **17**
- `FLOAT`: **8**
- `INTEGER`: **4**

Comparison modes:

- `NORMALIZED_EXACT`: **67**
- `DATE`: **17**
- `NUMERIC`: **12**
- `SEMANTIC`: **3**

Only the three selected `TICKET_SUMMARY_LOOKUP` facts require future semantic Judge evaluation.

### Product representation minimality

`ORDER_PRODUCT_LOOKUP` is a special minimality case. The source/tool exposes both `product_id` and `product_name`, but the user asks which product was purchased. D2 therefore marks:

- `product_name`: critical;
- `product_id`: optional companion.

This avoids forcing future Task Success to require both a code and a name when one user-facing product identity is sufficient.

## 6. GoldEvidence Materialization

D2 materializes **99 field-level Structured GoldEvidence Drafts**.

Identity format remains privacy-preserving and stable, for example:

```text
record:order:hash:<digest>#status
record:ticket:hash:<digest>#priority
record:warranty:hash:<digest>#expires_at
```

Raw `ORD-*`, `TCK-*`, `WAR-*`, customer IDs and emails are not persisted in Gold Drafts, annotation packets, source snapshots or D2 public artifacts.

Every critical GoldFact has resolvable supporting field-level evidence.

## 7. TaskSuccessContract Draft

Normal Private lookup drafts reuse the existing canonical `SuccessCriterion` system. Required criteria include:

- `RESPONSE_TYPE_CORRECT`
- `REQUIRED_AGENTS_CORRECT`
- `REQUIRED_TOOLS_CORRECT`
- `CRITICAL_FACTS_CORRECT`
- `CRITICAL_FACTS_GROUNDED`
- `AUTHORIZATION_CORRECT`
- `NO_UNAUTHORIZED_ACCESS`
- `NO_SENSITIVE_DATA_LEAK`
- `NO_CRITICAL_HALLUCINATION`

Expected specialist:

```text
order_agent
```

Expected Production tool:

```text
execute_sql_template
```

The draft also records the required template ID (`order_detail`, `ticket_detail`, or `warranty_cases`) separately from the tool name.

## 8. Gold Minimality

Gold Drafts contain only the facts required by the user query, plus explicitly non-critical companion facts when necessary to represent source identity.

D2 does not require the Agent to emit all fields returned by a structured row.

All normal self-query drafts also record forbidden extra-disclosure scope for other-user private data and unrelated internal fields.

## 9. Gold Alignment

Query plan, candidate fields, GoldFact field paths and GoldEvidence field paths are checked independently.

Actual result:

- aligned: **84 / 84**
- misaligned: **0**
- multi-field candidates: **15**
- multi-field aligned: **15 / 15**

No missing-fact, extra-fact, missing-evidence or extra-evidence defect remains silently unresolved.

## 10. Order Audit

Input Order candidates: **36**.

Status:

- READY: **36**
- PRECHECK: **0**
- REJECT: **0**

Order facts include status, date, product, quantity, unit price, total amount, channel and status+date summaries.

Amount fields use numeric comparison. The Production Order Agent prompt explicitly requires `¥X.XX` output; D2 records this as the display/currency contract rather than inventing a currency independently.

## 11. Ticket Audit

Input Ticket candidates: **26**.

Status:

- READY: **18**
- PRECHECK: **8**
- REJECT: **0**

Manual-precheck families:

- `TICKET_PRIORITY_LOOKUP`: 3
- `TICKET_ASSIGNED_TEAM_LOOKUP`: 3
- `TICKET_MULTI_FIELD_SUMMARY` (`status + priority`): 2

The reason is business-facing visibility uncertainty, not missing source data.

### Ticket summary

Three `TICKET_SUMMARY_LOOKUP` candidates remain READY. Their selected source values require no redaction change in the current batch, but:

- comparison mode is `SEMANTIC`;
- `judge_required=true` for future scoring;
- review priority is HIGH.

If a later source summary contains redactable sensitive content, the D2 construction path rejects it from normal Private Gold rather than silently retaining it.

## 12. Warranty Answerability

Input Warranty candidates: **22**.

Status:

- READY: **22**
- PRECHECK: **0**
- REJECT: **0**

The Production template is customer-level `warranty_cases`, not an entity-scoped warranty-detail template. D2 therefore executes a construction-time answerability audit against the real SQLite source.

Results:

- target uniquely identifiable: **22 / 22**
- tool result sufficient: **22 / 22**
- ambiguous: **0**
- insufficient: **0**

Customer warranty-case counts among the selected 22 candidates:

- 1 case: 13 candidates
- 2 cases: 2 candidates
- 3 cases: 7 candidates

Because future runtime materialization supplies the synthetic fixture `case_id` and the safe tool output includes `case_id`, the target case can be uniquely selected from the small customer-level list without modifying Production.

## 13. Order-item Ambiguity

All 36 Order candidates are re-audited.

Item-level candidates (`product`, `quantity`, `price_per_unit`): **13**.

- valid single-item source: **13 / 13**
- ambiguous multi-item: **0**

D2 never picks the first row of a multi-item order. Regression tests prove a real multi-item source is classified `AMBIGUOUS_MULTI_ITEM` and fails closed.

## 14. Runtime Query Materialization

D1 candidate queries use construction tokens such as `<ORDER_REF:...>`. D2 adds deterministic runtime materialization.

Actual result:

- materializable: **84 / 84**
- not materializable: **0**

The structured dataset is explicitly synthetic fixture data, so future RuntimeCaseInput may legally contain fixture business IDs. D2 nevertheless does **not persist raw business IDs** in public artifacts.

The public materialization artifact stores structures such as:

```json
{
  "policy": "RAW_FIXTURE_ID_ALLOWED",
  "status": "MATERIALIZABLE",
  "runtime_query_redacted": "请帮我查一下订单 [ORDER_FIXTURE_ID] 现在是什么状态？",
  "runtime_query_sha256": "...",
  "raw_identifier_persisted": false
}
```

The construction function can deterministically materialize the true synthetic runtime query when a later governed conversion step needs it.

## 15. Surface Collision Review

D1 reported 59 normalized surface-collision excess cases. D2 expands that into **25 collision groups**:

- HIGH-information groups: **10**
- MEDIUM-information groups: **14**
- LOW-information groups: **1**

Candidate-level classification:

- HIGH-information: **35**
- MEDIUM-information: **44**
- LOW-information: **5**

The low-information group contains five `ORDER_STATUS_LOOKUP` candidates sharing the same common state/value bucket; they are flagged `LOW_INFORMATION_DUPLICATE_CANDIDATE` and `FUTURE_DEDUP_REVIEW` but are **not automatically deleted in D2**.

This preserves the prompt requirement that D2 assigns retention priority without prematurely cutting 84 candidates to a target count.

## 16. Annotation Packet

Only `READY_FOR_DUAL_ANNOTATION` drafts receive frozen annotation packets.

Actual packet count: **76**.

Batch:

- batch ID: `PBQ-D2-C3B3AA7C6549`
- batch hash: `c3b3aa7c65497813a9947e2ee0a8f05bae84958c0f5f09ba1f7bc1f3bc22e01c`

Each packet contains only information necessary for **Gold Draft quality review**:

- candidate query;
- redacted runtime-query preview;
- task category/family;
- minimal SourceSnapshot;
- GoldFact/GoldEvidence draft;
- TaskSuccessContract draft;
- answerability;
- Production capability summary;
- review requirements;
- frozen `AnnotationDecision` output contract.

The packet explicitly excludes Production prediction, Agent answer/trace, Judge answer, other annotator decisions, adjudication and split/test membership.

## 17. Source Snapshot

D2 creates one minimal source snapshot for each of the 84 input candidates.

A snapshot includes only:

- record type;
- privacy-safe entity alias;
- requested source fields and values;
- ownership validity;
- tenant validity;
- source record hash;
- snapshot hash.

Unrequested amount/channel/internal fields are not copied into a status-only packet.

The packet embeds only the minimal snapshot view and stable snapshot hash.

## 18. Annotation Batch Freeze

Packet and snapshot hashing is deterministic. Non-semantic timestamps are excluded from the batch hash.

The manifest records:

- frozen D1 candidate-set hash;
- packet count;
- ordered packet hashes;
- source snapshot hashes;
- Gold Draft version;
- batch hash;
- `annotation_runs = 0`;
- `human_review_runs = 0`;
- `formal_eligible_count = 0`.

Repeated D2 runs over the same frozen input produce the same packet/batch hashes.

## 19. READY Count

`READY_FOR_DUAL_ANNOTATION`: **76**.

By domain:

- Order: 36
- Ticket: 18
- Warranty: 22

READY is not Human Review and is not Formal Eligibility.

## 20. NEEDS_PRECHECK Count

`NEEDS_MANUAL_PRECHECK`: **8**.

All eight are Ticket candidates:

- priority-related: 5
- assigned-team-related: 3

The source/tool can answer them, but D2 cannot prove from current Production semantics alone that these fields are appropriate normal customer-facing benchmark targets.

## 21. REJECTED Count

`REJECTED_BEFORE_ANNOTATION`: **0** in the frozen D1 pool.

This is not evidence that rejection logic is absent. D2 regression tests cover:

- multi-item Order ambiguity;
- field alignment defects;
- raw private-ID persistence;
- non-deterministic materialization;
- insufficient Warranty selection semantics;
- sensitive free-text handling.

No such hard defect is present in the selected 84 D1 source-valid candidates.

## 22. Main Quality Risks

Before D3, the important remaining risks are:

1. **Ticket business visibility** — priority and assigned team require manual policy/business review.
2. **Ticket summary semantics** — three cases need semantic Judge during future scoring and high annotation attention.
3. **Low-information collision group** — five common-state Order status cases should be explicitly considered in later adjudication/dedup.
4. **Fixture identifier conversion** — raw synthetic IDs are intentionally materialized only in a controlled runtime-conversion step, not public artifacts.
5. **Product representation** — D2 avoids overconstraining Order product answers by making product ID optional and product name critical.
6. **Small Warranty list semantics** — current 22 are answerable, but this conclusion is source-specific and must not be generalized to arbitrary future customers with larger/truncated lists.

## 23. Artifacts

Generated under `artifacts/evaluation/dataset-expansion-d2/`:

- `private_business_gold_drafts.jsonl`
- `private_business_gold_draft_report.json`
- `private_business_annotation_packets.jsonl`
- `private_business_annotation_packet_report.json`
- `private_business_source_snapshots.jsonl`
- `annotation_batch_manifest.json`
- `private_business_field_semantics.json`
- `private_business_runtime_materialization.json`
- `private_business_warranty_answerability.json`
- `private_business_surface_collision_review.json`
- `private_business_gold_alignment_report.json`
- `private_business_preannotation_rejected.jsonl`
- `private_business_preannotation_review_queue.jsonl`
- `phase_d2_summary.json`

## 24. Code Changes

New D2 construction modules under `evals/benchmark/expansion/`:

- `gold_draft.py`
- `gold_alignment.py`
- `field_semantics.py`
- `runtime_materialization.py`
- `annotation_packet.py`
- `preannotation_review.py`
- `d2_runner.py`

Updated:

- `evals/benchmark/expansion/__init__.py`
- `eval_platform/cli.py`

Unified CLI command:

```bash
python -m eval_platform.cli dataset-prepare-private-annotation \
  --root . \
  --d1 artifacts/evaluation/dataset-expansion-d1 \
  --output artifacts/evaluation/dataset-expansion-d2
```

No new formal CLI framework was created.

## 25. Tests

D2 targeted tests:

```text
17 passed
```

Evaluation regression after D2:

```text
205 passed, 2 skipped
```

Full repository regression after D2:

```text
419 passed, 2 skipped
```

The two skips remain the previously known real Production / real Judge integration skips. Production/Judge are not required for D2.

`python -m compileall -q .`: PASS.

## 26. Production Diff

Compared with the frozen D1 repository, source content under:

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

has **0 Production behavior file changes**.

D2 changes only dataset-construction/evaluation tooling, tests, artifacts and documentation.

## 27. Formal Dataset Invariance

The existing formal canonical dataset remains:

- Development: 34
- Validation: 5
- Total: **39**

The canonical JSON files retain their D1 hashes.

D2 creates:

- new formal cases: **0**
- Human Reviewed Gold: **0**
- split assignments: **0**
- Trusted Test cases: **0**

## 28. Phase D3 Stable Inputs

A future dual-independent-annotation phase can depend directly on:

- `private_business_annotation_packets.jsonl`
- `annotation_batch_manifest.json`
- `private_business_gold_drafts.jsonl`
- `private_business_source_snapshots.jsonl`
- `private_business_field_semantics.json`
- `private_business_runtime_materialization.json`
- `private_business_warranty_answerability.json`
- `private_business_surface_collision_review.json`
- `private_business_gold_alignment_report.json`
- `private_business_preannotation_review_queue.jsonl`

D3 should send exactly the same frozen packet/hash to Annotator A and B. The eight precheck cases should **not** be silently included until their field-visibility question is resolved. D3 must not reinterpret `READY_FOR_DUAL_ANNOTATION` as Human Reviewed or Formal Eligible.
