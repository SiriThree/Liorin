# Benchmark Expansion Phase D1：Private Business Query Source-grounded Candidate Pool

## 1. D1 Summary

Phase D1 仅建设 `PRIVATE_BUSINESS_QUERY` Candidate Pool，没有扩 Knowledge QA、Mixed、Troubleshooting、Recovery、Safety 或 Multi-turn。

阶段状态：**COMPLETE**。

实际结果：

- Raw candidates: **84**
- SOURCE_VALIDATED: **84**
- REJECTED: **0**
- Effective candidates: **84**
- Semantic families: **25**
- New Formal Cases: **0**
- New Human Reviewed Gold: **0**
- Production Agent: **NOT RUN**
- Judge: **NOT RUN**

84/84 全部通过 source validation 并不表示“自动成为 Gold”。生成器先从真实记录、真实 Production-exposed field 和真实 read capability 中确定性构造 task plan，再由独立 validator fail-closed 复核；正式 Gold 仍需要后续 annotation / adjudication / human review。

## 2. D0 Inputs Used

D1 直接读取：

- `artifacts/evaluation/dataset-expansion-d0/structured_source_inventory.json`
- `structured_fact_inventory.json`
- `production_capability_inventory.json`
- `source_reference_validation.json`
- `structured_concentration.json`
- `future_split_risks.json`
- `capacity_estimate.json`
- `phase_d0_summary.json`

D0 inventory hash：

`821acb2706a0b76d01230d7d10383e5f9af1ce8a6072373a3c26db8565236205`

D1 DB fingerprint：

`0166d9b2252286ed36978e63a3969eb041077fe6fc33ba8e9c7258d37af8ed78`

Tool registry fingerprint：

`357078e0ea6a82a7badf519450d9b440d330707c1bd55c690bf4342a0ce33e32`

## 3. Legacy Evidence Alias Bridge

在生成任何 Candidate 前先材料化：

`artifacts/evaluation/dataset-expansion-d1/legacy_section_alias_map.json`

结果：

- legacy document refs: **40**
- deterministic resolved: **40**
- ambiguous: **0**
- missing: **0**

映射明确记录：

`legacy document + Hxxx/POL-xxx + legacy_heading -> current stable hash section`

本阶段只建立 compatibility bridge，没有批量重写原有 39 条 canonical Gold。

## 4. Private Business Scope

只允许三个真实 Source Domain：

- ORDER
- TICKET
- WARRANTY

只允许 `READ_LOOKUP`。

没有构造：

- Customer Profile 普通查询
- write/update/delete/refund/cancel/create
- cross-user / cross-tenant negative query
- document policy / Mixed task
- unstable order/ticket event-level Gold

## 5. Candidate Contract

新增 construction-only `PrivateBusinessCandidate` 与 `StructuredTaskPlan`。

它们不是 `CanonicalEvaluationSample`，并显式包含：

- stable candidate ID
- semantic family
- record type
- privacy-preserving source entity ref
- source fields / source fact refs
- state / product / tenant / customer grouping refs
- source-valid task plan
- publishable candidate query
- structured field draft
- stable candidate evidence refs
- capability mapping
- duplicate keys
- split group keys
- expected value draft
- construction locator
- quality flags / rejection reasons
- `SOURCE_DERIVED_DRAFT`
- `formal_metric_eligible=false`
- `human_reviewed=false`

公开 Candidate query 使用 `<ORDER_REF:...>` / `<TICKET_REF:...>` / `<WARRANTY_REF:...>` privacy-safe token，不保存 raw ORD/TCK/WAR/CUST identifier。后续转 Canonical Runtime input 时必须通过受控 construction source materialization 恢复真实业务 ID；D1 Candidate 本身不直接用于 Production execution。

## 6. Order Candidate Space

共 **36** 条，**8** 个 semantic families：

- ORDER_STATUS_LOOKUP: 5
- ORDER_DATE_LOOKUP: 4
- ORDER_PRODUCT_LOOKUP: 5
- ORDER_QUANTITY_LOOKUP: 4
- ORDER_UNIT_PRICE_LOOKUP: 4
- ORDER_AMOUNT_LOOKUP: 4
- ORDER_CHANNEL_LOOKUP: 4
- ORDER_MULTI_FIELD_SUMMARY: 6

Order item-level family 仅选择单商品订单，避免当前 structured evidence identity 在一个订单多行 item 上发生 field-level collision。

Order status：

- Delivered: 15
- Cancelled: 8
- Processing: 7
- Shipped: 6

不是按 1419/55/13/13 的线上自然比例采样，而是明确为业务状态覆盖做 stratification。

## 7. Ticket Candidate Space

共 **26** 条，**9** 个 families：

- TICKET_STATUS_LOOKUP: 4
- TICKET_PRIORITY_LOOKUP: 3
- TICKET_ISSUE_TYPE_LOOKUP: 3
- TICKET_PRODUCT_LOOKUP: 3
- TICKET_ORDER_LINK_LOOKUP: 3
- TICKET_ASSIGNED_TEAM_LOOKUP: 3
- TICKET_SUMMARY_LOOKUP: 3
- TICKET_CREATED_AT_LOOKUP: 2
- TICKET_MULTI_FIELD_SUMMARY: 2

Ticket status：

- resolved: 8
- pending_customer: 6
- in_progress: 6
- open: 6

## 8. Warranty Candidate Space

共 **22** 条，**8** 个 families：

- WARRANTY_STATUS_LOOKUP: 3
- WARRANTY_COVERAGE_STATUS_LOOKUP: 4
- WARRANTY_COVERAGE_TYPE_LOOKUP: 3
- WARRANTY_EXPIRY_LOOKUP: 3
- WARRANTY_PRODUCT_LOOKUP: 3
- WARRANTY_ORDER_LINK_LOOKUP: 2
- WARRANTY_TICKET_LINK_LOOKUP: 2
- WARRANTY_MULTI_FIELD_SUMMARY: 2

Coverage status：

- in_warranty: 12
- expired: 10

真实 warranty status 也覆盖：

- active: 7
- under_review: 5
- denied: 2
- expired: 8

## 9. Semantic Families

总计 **25** 个 family：

- Order: 8
- Ticket: 9
- Warranty: 8

每个 family 对应真实 Production-exposed field set 与固定 structured read template，而不是按 query wording 定义。

## 10. State Sampling

49 条标记：

`RARE_STATE_COVERAGE`

35 条标记：

`BALANCED_FAMILY_STATE_COVERAGE`

这些 sampling reason 是 construction provenance，不表示线上业务流量分布。

## 11. Entity Sampling

- unique entities: **84 / 84 = 100%**
- max candidates per entity: **1**
- unique customers: **68 / 84 = 80.95%**
- max candidates per customer: **4**

没有通过同一个 Order/Ticket/Warranty 的 surface paraphrase 扩量。

## 12. Product / Tenant Diversity

- unique products represented: **20 / 20**
- unique tenants represented: **19 / 19**
- max candidates in one tenant: **6 / 84 = 7.14%**
- max candidates for one represented product: **6**
- max product concentration among product-resolved candidates: **9.52%**

当前没有 concentration warning。

## 13. Source Validation

Source validation 检查：

- entity exists
- record type valid
- field exists
- field Production-exposed
- owner/customer metadata exists
- tenant/customer grouping matches source
- allow-listed Tool template exists
- operation is read-only
- required value is source-resolvable
- stable structured evidence identity is derivable
- item-level order fields are single-row unambiguous
- no raw business ID leakage
- no answer leakage
- no Mixed leakage
- no Safety leakage

实际：**84/84 PASS，100%**。

这不是因为 validator permissive：专项测试验证 missing entity、unsupported field、event-level field、wrong owner、write semantics、Mixed leakage、Safety leakage、answer leakage、raw identifier leakage 都会 fail closed。

## 14. Production Capability Validation

所有 retained Candidate 均映射：

`private_structured_read`

实际 templates：

- Order: `order_detail`
- Ticket: `ticket_detail`
- Warranty: `warranty_cases`

D1 没有运行 Order Agent；这里只验证 construction source + Production Tool Registry 的能力契约。

## 15. Field Coverage

D0 有 **28** 类 ordinary-Gold usable Structured fact types。

D1 覆盖 **23** 类：

- Order target fields: 8
- Ticket target fields: 8
- Warranty target fields: 7

未覆盖 5 类及原因：

- `customer.customer_id`: Customer Profile 不属于 D1 普通 Private Query
- `customer.segment`: 同上
- `order.order_id`: entity selector，不作为 target fact
- `ticket.ticket_id`: entity selector
- `warranty.case_id`: entity selector

没有为了 100% field coverage 强行生成无价值问题。

## 16. Dedup

结果：

- exact query duplicates: **0**
- same entity + same field semantic duplicates: **0**
- rejected duplicates: **0**
- normalized surface collisions: **59**

59 个 normalized collisions 来自不同真实实体复用同一受控语言模板；在将 privacy-safe entity token 归一化后文本相同，但 source entity / source fact / candidate evidence 不同，因此保留，并在 dedup artifact 中明确记为：

`normalized_surface_collisions_retained_due_distinct_source_entity`

它们不是 59 个 paraphrase 扩量。

## 17. Leakage Detection

实际 retained pool：

- answer leakage: **0**
- raw private ID leakage: **0**
- hidden tenant/customer metadata leakage: **0**
- Mixed task leakage: **0**
- Safety task leakage: **0**
- write-operation leakage: **0**

Ticket free-text summary draft 会经过现有 PII/business-ID redaction；ID-valued expected facts使用 hashed structured refs。

## 18. Concentration Analysis

- max/entity: 1
- max/customer: 4
- max/product: 6
- max/tenant: 6
- max/semantic family: 6
- tenant ratio: 7.14%
- product ratio: 9.52%（product-resolved subset）

满足本阶段 concentration guard 的预期，不需要通过删除真实 minority-state coverage 来追求更均匀的业务自然分布。

## 19. Effective Diversity

- Raw candidates: 84
- Source Validated: 84
- Rejected: 0
- Surface-only variations: 0
- Effective candidates: 84
- Semantic families: 25
- Unique entity ratio: 100%
- Unique customer ratio: 80.95%

Difficulty：

- EASY: 66
- MEDIUM: 18
- HARD: 0

没有为了比例人工制造 HARD。当前 private-only Production contract 尚未冻结足够可靠的“缺 identifier 必须 clarification”或 multi-relation private-only semantics，因此 D1 不生成 clarification candidates；这些应先经 Production behavior contract 审计后再决定。

## 20. Raw Candidate Count

**84**，落在 D0 78–92 capacity-driven raw target 内。

## 21. Source Validated Count

**84**。

D0 曾规划约 60–70 条 source-valid，但这不是硬阈值。D1 generator 本身先 source-ground / stratify，再交给 validator，因此没有为了制造 rejection 先生成明显无效记录。后续 Gold Annotation / Review 可以在 84 条池中收敛到约 60–70 条更适合作为正式 Private Business 集的样本。

## 22. Rejection Reasons

实际 generated pool 的 REJECTED = **0**。

这不表示 hard reject 逻辑不存在；测试已验证以下都会 REJECT：

- source entity missing
- unsupported/non-exposed field
- unstable event-level field
- owner/tenant mismatch
- non-read operation
- Mixed leakage
- Safety leakage
- answer leakage
- raw private identifier leakage
- same entity + same field semantic duplicate

## 23. Candidate Artifacts

`artifacts/evaluation/dataset-expansion-d1/`

- `legacy_section_alias_map.json`
- `private_business_raw_candidates.jsonl`
- `private_business_source_validated.jsonl`
- `private_business_rejected.jsonl`
- `private_business_candidate_manifest.json`
- `private_business_distribution.json`
- `private_business_field_coverage.json`
- `private_business_state_coverage.json`
- `private_business_entity_concentration.json`
- `private_business_semantic_families.json`
- `private_business_dedup_report.json`
- `phase_d1_summary.json`

Candidate set SHA-256：

`7885191d82cb97e51e38e000d7a70a77dbea865b2cd61b74256c98ad950855f6`

## 24. Tests

D1 targeted：

`14 passed`

Evaluation suite：

`188 passed, 2 skipped`

Whole repository：

`402 passed, 2 skipped`

`compileall`: PASS。

两个 skip 仍是 Phase 7 real Production / real Judge integration，D1 不要求 Production/Judge。

## 25. Production Diff

与 D0 完整仓库逐文件 SHA-256 比较：

`Production behavior files changed = 0`

未修改：

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

原有 canonical Dev / Validation 文件 SHA-256 也保持不变。

既有文件仅修改：

- `eval_platform/cli.py`：增加 `dataset-expand-private`
- `evals/benchmark/expansion/__init__.py`：导出 D1 runner

其余均为 D1 construction code / artifacts / tests / docs。

## 26. Limitations

1. 这些 Candidate 尚未经过 Gold Annotation、Dual Annotation、Adjudication 或 Human Review。
2. publishable query 使用 privacy-safe entity token，正式 Runtime query 需要后续受控 materialization。
3. Warranty Production Tool 当前是 customer-level list template，而非 entity-scoped warranty detail template；D1 能证明字段/source/capability 可解析，但仍需后续 annotation/review 关注实际 agent-level可回答性。
4. Order item-level candidate 只使用单商品订单，以规避当前 field-level structured evidence identity 无 item ID 的歧义。
5. 没有 Clarification/HARD candidate，因为当前 private-only behavior contract 不足以让 construction layer自行定义“缺 ID 必须澄清”。
6. 84 SOURCE_VALIDATED 不等于 84 Formal Eligible。

## 27. Phase D2 Stable Inputs

下一阶段可以直接依赖：

- `legacy_section_alias_map.json`
- `private_business_source_validated.jsonl`
- `private_business_candidate_manifest.json`
- `private_business_distribution.json`
- `private_business_field_coverage.json`
- `private_business_state_coverage.json`
- `private_business_entity_concentration.json`
- `private_business_semantic_families.json`
- `private_business_dedup_report.json`
- D0 `structured_source_inventory.json`
- D0 `structured_fact_inventory.json`
- D0 `production_capability_inventory.json`

下一阶段若针对 Private Business，应优先进入 **Gold Annotation / Review**，而不是继续生成更多 Private Candidate。
