# Benchmark Expansion Phase D0：真实数据源审计、Fact Space 与 Coverage Blueprint

## 1. Executive Summary

Phase D0 仅做数据源与覆盖空间审计；没有生成新的正式 Benchmark Case、没有运行 Production Agent、没有修改 Production Prompt/Retriever/Verifier/Tool/Context/Memory，也没有生成 Human Reviewed Gold。

重新审计后，当前正式 Canonical 仍为 **39** 条，其中 Development 34、Validation 5；按 source fact/evidence/contract/semantic family 去除 surface variation 后，有效 Case 为 **35**，存在 4 条 surface variation。当前正式数据只覆盖 **5 个 semantic families**。

真实知识源为 **22 个文档 / 1216 个稳定 section**；D0 确定性抽取 **4913 个 source-linked AtomicFact candidates**（其中 4907 个满足当前启发式 benchmark-usable 约束，但它们不是 Human Reviewed Gold）。Structured Production Tool 暴露形成 41 类字段事实，其中 28 类当前适合普通业务 Gold；Relation family 13 条，Mixed family 6 条，Safety attack surface 12 个。

基于独立 facts / relations / entity states / task semantics，而非 paraphrase 倍增，D0 建议正式数据集优先收敛到 **326–414 条**；当前 source space 的保守 minimum 约 204，upper reasonable bound 约 536。候选池建议先准备 **474–569 条**，预留去重、source validation 与 review 淘汰空间。这个范围是规划估计，不是 Benchmark 质量指标。

## 2. Current Dataset Inventory

- Formal canonical: 39
- Development: 34
- Validation: 5
- Formal Safety candidates inside canonical: 3
- Formal multi-turn eligible: 0
- Recovery challenge ready: FALSE
- Trusted TEST present: FALSE
- Historical blind remains HISTORICAL_UNVERIFIED; representative seeds/calibration/security fixtures remain non-formal.

完整逐文件 inventory 见 `existing_dataset_inventory.json`，区分 trust、annotation、case/asset record count、GoldEvidence/GoldFact/Safety/identity coverage。

## 3. Effective Diversity Audit

- Raw formal cases: 39
- Effective cases: 35
- Surface variations: 4
- Existing semantic families: 5
- Exact/normalized query duplicates: 0
- Same GoldFact-set duplicate excess: 4
- Same GoldEvidence-set duplicate excess: 4

现有 semantic family 分布：
- `KNOWLEDGE_DOCUMENT_LOOKUP`: 16
- `MIXED_TICKET_MANUAL`: 10
- `PRODUCT_SPEC_LOOKUP`: 8
- `SAFETY_SENSITIVE_DATA`: 3
- `TROUBLESHOOT_DIRECT`: 2

## 4. Document Source Inventory

真实 checked-in Knowledge Corpus 共 22 个 source：manual 20、policy 1、FAQ 1。与 `products.json` 对齐的产品手册为 20 本。

总稳定 section 数：1216。section 最多的文档为 `LIO-PROD-006_冰箱手册`（127 sections）。

当前文档 metadata 没有显式 region/effective_from/effective_to；因此不能凭模型常识扩展地区/时效政策 Gold。

## 5. Structured Data Inventory

- `customers`: 300
- `products`: 20
- `orders`: 1500
- `order_items`: 3355
- `order_status_events`: 7296
- `tickets`: 420
- `ticket_events`: 1576
- `warranty_cases`: 140

实际数据库包含 19 个 tenant、300 个 customer、20 个 product；1025 个订单包含多个 product；17 个 ticket 没有可靠 order_id。

注意：真实 SQLite 中 `ticket_events = 1576`，与 `data/structured/SCHEMA.md` 中历史文字值 1633 不一致；D0 以实际数据库为 source of truth。

## 6. Atomic Fact Space

D0 从真实 Markdown section 做确定性 sentence/bullet/step extraction，得到 4913 个 source-linked `AtomicFact` candidates；其中 4907 个满足当前 source-resolution/文本完整性启发式。它们仍然只是 Dataset Construction candidates，不等于 Canonical GoldFact。

- `FEATURE_OR_INSTRUCTION`: 3633
- `SAFETY_INSTRUCTION`: 707
- `TROUBLESHOOTING_STEP`: 317
- `WARRANTY`: 76
- `COMPATIBILITY`: 69
- `PRODUCT_SPEC`: 43
- `LIMITATION`: 20
- `AFTER_SALES`: 13
- `POLICY`: 10
- `FAQ_PROCESS`: 10
- `RETURN_POLICY`: 9
- `WARRANTY_POLICY`: 4
- `ERROR_CODE`: 2

每个 AtomicFact 都保留 source_id/document_id/current section_id；无法 source-resolve 的 fact 不允许未来直接升级为 Gold。

## 7. Troubleshooting Fact Space

- Troubleshooting / error-code fact candidates: 319
- Related sections: 137
- Multi-step sections: 21
- Sections with missing-info/conditional context signals: 72
- Handoff/escalation sections: 40
- Conditional sections: 86

现有 formal Troubleshooting 只有 2 条，因此这是 D1 的最大 P0 扩展空间之一。

## 8. Structured Fact Space

Production allow-listed SQL templates 可形成 41 类 structured output field fact；其中 28 类当前可作为普通业务 Gold 类型。

主要可用类型包括 `order.status/order_date/product_id/product_name/quantity/total_amount`、`ticket.status/product_id/issue_type/priority/created_at`、`warranty.coverage_status/status/expires_at/product_id` 等。

两类限制被显式排除：
- Customer name/company/source_system 等不应因为工具能返回就成为常规 Benchmark 容量核心。
- `order_events` / `ticket_events` 虽可查询，但当前 Tool output 未带 `event_id`，导致同一 order/ticket 的多事件无法形成唯一 event-level Production evidence identity；10 类 event field 暂不计普通 Gold capacity。

## 9. Relation Space

共识别 13 条真实 relation families，包括 Customer→Order、Order→Product、Order→Event、Customer→Ticket、Ticket→Product/Order/Event、Customer→Warranty、Warranty→Product/Order/Ticket、Product→Manual、Product→After-sales Policy。

这些关系均可追到 SQLite join key、products.manual_file 或 repository-global policy applicability；没有增加数据库不存在的 relation。

## 10. Mixed Knowledge + Structured Space

D0 识别 6 个真实 Mixed families；每个 family 都要求至少一个 STRUCTURED_DATA unit 与一个 DOCUMENT unit 都对 Task Success 必要：
- `mixed:order-date:return-policy`: order.order_date + RETURN_POLICY; join `order -> after_sales_policy`; raw entity capacity 1500（不直接等于正式 Case capacity）。
- `mixed:order-status:cancel-policy`: order.status + RETURN_POLICY, POLICY; join `order -> after_sales_policy`; raw entity capacity 1500（不直接等于正式 Case capacity）。
- `mixed:order-product:manual`: order.product_id + FEATURE_OR_INSTRUCTION, PRODUCT_SPEC, SAFETY_INSTRUCTION, TROUBLESHOOTING_STEP; join `order -> order_items -> product -> manual`; raw entity capacity 1500（不直接等于正式 Case capacity）。
- `mixed:ticket-product:troubleshooting`: ticket.product_id + TROUBLESHOOTING_STEP, ERROR_CODE, SAFETY_INSTRUCTION; join `ticket -> product -> manual`; raw entity capacity 420（不直接等于正式 Case capacity）。
- `mixed:warranty-status:policy`: warranty.coverage_status + WARRANTY_POLICY, POLICY; join `warranty -> after_sales_policy`; raw entity capacity 140（不直接等于正式 Case capacity）。
- `mixed:warranty-product:manual`: warranty.product_id + TROUBLESHOOTING_STEP, SAFETY_INSTRUCTION, FEATURE_OR_INSTRUCTION; join `warranty -> product -> manual`; raw entity capacity 140（不直接等于正式 Case capacity）。

D0 对 Mixed 的正式推荐容量只按独立 relation semantics 保守估计为 54 左右，而不是对 1500 个订单做笛卡尔扩增。

## 11. Production Capability Alignment

- Knowledge document QA: supported by Supervisor → Knowledge Agent → hybrid retrieval.
- Troubleshooting / clarification / recovery: supported by Knowledge Agent retrieval/verifier/recovery path.
- Private structured read: supported by verified identity → Order Agent → `execute_sql_template` read-only templates.
- Mixed structured + knowledge: Supervisor supports multiple specialists; real full Production smoke remains Phase 7 environment-blocked, so capability trace status stays PARTIAL until live proof.
- Business writes/refunds/cancel/ticket-create side effects: NOT PRESENT as executable tools. Future Benchmark must not invent them.

## 12. Response Behavior Space

Current formal response distribution: {'ANSWER': 36, 'CLARIFICATION': 3}. Clarification-required formal cases = 3; handoff-required formal cases = 0.

Production/schema can express ANSWER、CLARIFICATION、HANDOFF、REFUSAL、ERROR；but Handoff and general ambiguity-driven clarification are heavily under-covered by current formal data.

## 13. Clarification / Handoff Space

Current 3 clarification cases are all SENSITIVE_DATA identity-verification cases. There is no formal clarification coverage for ambiguous product/model/symptom/region, despite Query Understanding and manuals supporting such ambiguity semantics.

Handoff should only be generated from existing verifier/policy semantics such as unresolved evidence conflict/insufficiency or manual escalation; D0 creates no new handoff rules.

## 14. Safety Attack Surface

Real audited attack surfaces = 12. They include tenant/user/session isolation, identity conflict, unauthorized structured query, cross-user/cross-tenant memory/artifact, user/retrieved-content prompt injection, and sensitive data. Current formal Safety cases = 3 and all are concentrated in one `SENSITIVE_DATA` semantic family.

No unauthorized refund/write attack surface is created because Production exposes no such write capability.

## 15. Semantic Families

Existing formal data collapses to only 5 families; source/capability audit identifies 30 source-grounded candidate family definitions for future D1 construction. This count is a task-space blueprint, not new Cases.

High-value uncovered families include order status/date/product self-query, ticket/warranty status, direct return/warranty policy, troubleshooting missing-context, six Mixed relations, and real governance boundaries.

## 16. Existing Coverage Matrix

| Category | Existing | Effective | Existing Families | Recommended Capacity | Gap |
|---|---:|---:|---:|---:|---:|
| KNOWLEDGE_QA | 24 | 22 | 2 | 150 | 128 |
| TROUBLESHOOTING | 2 | 2 | 1 | 70 | 68 |
| PRIVATE_BUSINESS_QUERY | 0 | 0 | 0 | 60 | 60 |
| MIXED_KNOWLEDGE_STRUCTURED | 10 | 10 | 1 | 54 | 44 |
| SAFETY_GOVERNANCE | 3 | 1 | 1 | 36 | 35 |

## 17. Evidence Complexity Distribution

Required evidence units: {'1': 29, '2': 9, '3+': 1}; source mix: {'document_only': 29, 'document_plus_structured': 10}; alternative-group cases: 0.

当前 39 条 formal 中 29 条 document-only，10 条 document+structured，**0 条 structured-only**；这直接解释了 `PRIVATE_BUSINESS_QUERY` formal coverage 为 0。

## 18. Reasoning Complexity Distribution

- `clarification`: 3
- `conditional_troubleshooting`: 2
- `multi_fact_lookup`: 24
- `multi_source_synthesis`: 10

这不是抽象“reasoning score”，只是按真实依赖形态对现有 Case 做可解释分类。

## 19. Source Concentration

Formal Case 的 document concentration Top：
- `LIO-PROD-001_VR头显手册.md`: 3 cases
- `LIO-PROD-002_人体工学椅手册.md`: 3 cases
- `LIO-PROD-003_健身单车手册.md`: 6 cases
- `LIO-PROD-004_健身追踪器手册.md`: 7 cases
- `LIO-PROD-005_儿童电动摩托车手册.md`: 7 cases
- `LIO-PROD-006_冰箱手册.md`: 1 cases
- `LIO-PROD-007_功能键盘手册.md`: 1 cases
- `LIO-PROD-008_发电机手册.md`: 1 cases

当前有 5 个示例列出的未覆盖文档；完整统计为 `5 of 22 checked-in knowledge documents have no formal canonical evidence reference.`。最高单 evidence/section 复用达到 3 次，当前尚未出现几十条围绕同一 section 的极端泄漏，但扩容时必须设 section/fact family group cap。

## 20. Structured Entity Concentration

当前 formal Mixed 使用 10 个不同 ticket record，各只出现 1 次；没有订单/保修 Structured formal family。Public audit artifact 对 structured record ID 使用 hash，不暴露原始 TCK/ORD/CUST/WAR identifiers。

源数据库实体足够丰富，但后续 Split 不应随机按 Case 切分同一 customer/entity family。

## 21. Benchmark Blind Spots

- **P0 PRIVATE_BUSINESS_QUERY_FORMAL_COVERAGE** — No fully migrated PRIVATE_BUSINESS_QUERY cases despite production-readable structured facts.
- **P0 TROUBLESHOOTING_DEPTH** — Existing formal troubleshooting coverage is tiny relative to source-linked troubleshooting sections/facts.
- **P0 MIXED_RELATION_DIVERSITY** — Existing mixed cases are concentrated in one legacy family while 6 production-supported mixed families are source-grounded.
- **P0 SAFETY_ATTACK_SURFACE_DIVERSITY** — Formal safety cases cover 1 subcategory labels versus 12 audited real attack surfaces.
- **P1 LEGACY_SECTION_IDENTITY_MIGRATION** — Formal canonical document Gold uses legacy Hxxx section ids; current corpus uses hashed section ids. D0 validates a unique-heading bridge, but D1 should materialize an explicit migration map before new formal case generation.
- **P1 STRUCTURED_EVENT_IDENTITY_GAP** — order_events/ticket_events templates omit event_id from output, so event-level field facts do not yet have unique stable Production evidence identity and are excluded from normal structured Gold capacity.
- **P1 REGION_EFFECTIVE_TIME_SOURCE_GAP** — Current checked-in knowledge documents do not carry explicit region/effective_from/effective_to metadata; region- or time-specific policy cases cannot be expanded as formal Gold without additional governed source metadata.
- **P1 UNTESTED_DOCUMENTS** — 5 of 22 checked-in knowledge documents have no formal canonical evidence reference.
- **P1 UNTESTED_STRUCTURED_FIELDS** — 28 production-readable structured fact types have no formal field-level coverage.
- **P1 CLARIFICATION_AND_HANDOFF** — Current formal canonical set contains little/no reviewed clarification/handoff behavior relative to real ambiguity/escalation space.
- **P2 MULTI_TURN_REVIEW_DEBT** — Phase 4 has candidate multi-turn sessions but zero formal eligible sessions; D0 does not review them.

其中 section identity audit 进一步确认：formal document Gold 的 40 个 legacy Hxxx refs 均能通过 `legacy_heading` 唯一映射到当前 hash section；10/10 structured Gold records 仍存在。这个 alias bridge 必须显式 materialize，不能把 legacy ID 与 current ID 当作同一个 identity。

## 22. Source Capacity Estimate

| Category | Minimum | Recommended | Upper Reasonable | Confidence |
|---|---:|---:|---:|---|
| KNOWLEDGE_QA | 80 | 150 | 220 | HIGH |
| TROUBLESHOOTING | 35 | 70 | 100 | MEDIUM |
| PRIVATE_BUSINESS_QUERY | 35 | 60 | 90 | HIGH |
| MIXED_KNOWLEDGE_STRUCTURED | 30 | 54 | 78 | MEDIUM |
| SAFETY_GOVERNANCE | 24 | 36 | 48 | MEDIUM |

Total planning envelope: minimum 204, recommended point 370, upper reasonable bound 536. Recommended operating range is **326–414** because source-linked candidate counts are much larger than the number of truly independent task semantics.

## 23. Expansion Priority

P0: Private Structured Query、Troubleshooting/Clarification/Recovery、Mixed relation diversity、Safety/Governance diversity。

P1: legacy→current section identity bridge、structured event identity、5 个未测文档/FAQ、Production-exposed structured fields、region/effective-time source metadata、Handoff coverage。

P2: multi-turn review debt and long-tail manual details after P0/P1 diversity is established.

## 24. Recommended Candidate Pool

建议 D1 candidate pool **474–569**，规划上预留约 22–35% 给 source mismatch、duplicate/surface variation、ambiguous Gold 和人工 review 淘汰。这个 rejection range 是建设预算假设，不是观测到的模型错误率。

## 25. Recommended Formal Dataset Range

**推荐正式目标：326–414 条。** 当前 source space upper reasonable bound 约 536；D0 不支持在没有更多独立 source/family 的情况下把 600 条强行定义为高质量正式容量。

一个更均衡的 recommended point 是：Knowledge 150、Troubleshooting 70、Private Business 60、Mixed 54、Safety 36，总计约 370。正式分布必须在 D1/D2 review 后再冻结。

## 26. Future Split Contamination Risks

- Same source section / same GoldFact-evidence family 跨 Dev/Test：HIGH leakage risk。
- Same semantic family + surface paraphrase 跨 split：HIGH。
- Same customer/order/ticket/warranty family 跨 split：HIGH。
- 完全随机 product/manual 切分：MEDIUM，容易夸大跨产品泛化。
- Same policy section 同时出现在 validation/trusted test：HIGH。

未来 group split keys 建议：document family、stable section/evidence group、semantic family、product/model family、customer/entity group、policy family。D0 不执行 split。

## 27. Unsupported Areas

- Production 不存在的退款/取消/创建工单等 write side effects。
- 数据库中未被 allow-listed Production Tool 暴露的普通业务字段。
- Event-level Gold（当前 order/ticket event tool output 缺 event_id stable identity）。
- 没有真实 region/effective-time source metadata 的地区/时效政策扩展。
- Historical blind 不可升级为 trusted test。
- 未人工 Review 的 Phase 4 multi-turn / recovery candidate 不可直接进入 formal benchmark。

## 28. Tests

Phase D0 新增测试覆盖：existing count reproducibility、document inventory stability、fact→source valid、real SQLite/tool exposure、event identity gap、relation validity、semantic-family determinism、surface variation、legacy source-ref bridge、inventory hash stability、privacy-safe structured refs、unsupported capability、no-new-case invariant。

实际测试结果见 Phase D0 最终交付回复；Production Agent 和 Real Judge 在 D0 均 `NOT REQUIRED`。

## 29. Actual Results

- Inventory hash: `821acb2706a0b76d01230d7d10383e5f9af1ce8a6072373a3c26db8565236205`
- Formal canonical raw/effective: 39 / 35
- Knowledge sources/sections: 22 / 1216
- AtomicFact candidates: 4913 total, 4907 heuristic usable
- Structured fact types: 41 total, 28 ordinary-Gold usable
- Relation/Mixed/Safety surfaces: 13 / 6 / 12
- Existing/available semantic families: 5 / 30
- Source reference validation: {'RESOLVED': 10, 'UNIQUE_HEADING_ALIAS': 40}
- New formal cases generated: 0

## 30. Phase D1 Stable Inputs

下一阶段可直接依赖以下 immutable/audited construction inputs：
- `existing_dataset_inventory.json`
- `document_source_inventory.json`
- `structured_source_inventory.json`
- `atomic_fact_inventory.jsonl`
- `structured_fact_inventory.json`
- `source_reference_validation.json`
- `relation_inventory.json`
- `mixed_combination_inventory.json`
- `semantic_family_inventory.json`
- `safety_attack_surface_inventory.json`
- `coverage_matrix.json` / `coverage_gaps.json`
- `capacity_estimate.json`
- `future_split_risks.json`

Phase D1 不应先平均铺量。第一优先级应是 **Private Structured + Mixed + Troubleshooting/Clarification + Safety**，因为这四块当前覆盖与真实 Production/Source capacity 的差距最大，也最能区分 Liorin 与普通单轮 RAG。

**Phase D0 到此停止；没有自动开始 D1。**
