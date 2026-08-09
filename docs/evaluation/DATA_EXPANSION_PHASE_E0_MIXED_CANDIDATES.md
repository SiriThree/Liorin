# Benchmark Expansion Phase E0：Mixed Structured + Knowledge Candidate Pool

## 1. E0 Summary
E0 仅建设 `MIXED_KNOWLEDGE_STRUCTURED` Candidate。最终 68 raw、58 `SOURCE_VALIDATED`、10 rejected、48 effective semantic signatures、5 validated families，阶段 **COMPLETE**。没有运行 Production Agent、Annotator、Judge，没有生成 Formal Case。

## 2. D3-R Deferred Status
Private Dual Annotation 保持 `DEFERRED_BY_ENVIRONMENT`：76 frozen packets、A decisions=0、B decisions=0、Agreement=`NOT_RUN`、resumable=true。D2/D3/D3-R 原 artifacts 未修改。

## 3. Existing Mixed Formal Audit
34 Dev + 5 Validation 中重新统计 Mixed=10，effective=10，全部集中 `TICKET_MANUAL` / `MIXED_TICKET_MANUAL` 一个 semantic family。

## 4. Mixed Source Space
D0 的真实 DB、20 product manuals、售后 policy、atomic facts、relation inventory 与当前 canonical 是唯一 source of truth；未使用互联网或模型常识扩充事实。

## 5. Mixed Relation Families
D0 6 个 potential family 均重新验证；E0 最终 5/6 source-valid。`MIXED_ORDER_RETURN_POLICY` 因时间基准不成立而整体拒绝。

## 6. Mixed Modes
Validated：`ENTITY_TO_KNOWLEDGE_ROUTING`=42，`POLICY_APPLICATION`=8，`CROSS_SOURCE_SYNTHESIS`=8。

## 7. MixedTaskPlan
每条 Candidate 先确定 structured record/fact、document fact/section、join path、necessity、reasoning contract、evidence、capability mapping，再渲染 query；不存在“先想问题再找证据”。

## 8. Mixed Necessity Contract
58/58 retained 都满足 structured source 和 document source 同时 required；删去任一 source 都不能完整完成当前任务。

## 9. Order + Return Policy
Raw=10，validated=0，rejected=10。政策依据是“已签收商品通常需要在 7 天内”，而当前普通 Structured Gold 没有 stable delivery-date fact；`order_date` 不能替代，且“现在还能退吗”没有 frozen reference date 会漂移。

## 10. Order Status + Policy
8/8 validated；Processing/Shipped/Delivered/Cancelled 各 2。Derived outcome 分别为资格检查、不能直接取消应转退货/退款、不要重复取消。

## 11. Order + Product Manual
18/18 validated。Structured `order.product_id` 用于识别正确产品，manual section 用于回答具体使用/处理问题；query 不泄露 product id/name。

## 12. Ticket + Troubleshooting
8/8 validated，新 Candidate 有意低于其它核心 routing family，并优先使用未被现有 10 Formal Mixed 占用的 current section；existing Formal collision=0。

## 13. Warranty + Policy
8/8 validated，coverage_status `expired`=4、`in_warranty`=4。Task 同时要求当前 structured coverage state 与 policy coverage/exclusion semantics。

## 14. Warranty + Product Manual
16/16 validated。Structured Warranty 负责 product routing，manual 提供知识事实；不要求把内部 routing product identity 强制输出给用户。

## 15. Structured Evidence
所有 retained Candidate 都有 field-level privacy-preserving stable refs，如 `record:<type>:hash:<digest>#field`。实体类型：order=26、ticket=8、warranty=24。

## 16. Document Evidence
所有新 document refs 使用 current stable `document_id:sec:<hash>`；不新增 legacy Hxxx。Validated pool 覆盖 21 个 document sources（20 manuals + 1 policy）、22 个 unique sections、25 个 unique document facts。

## 17. Derived Reasoning
Reasoning labels：`ENTITY_RESOLUTION`=42、`SOURCE_ROUTING`=42、`POLICY_APPLICATION`=8、`CONDITIONAL_APPLICATION`=8、`MULTI_SOURCE_SYNTHESIS`=8；没有泛称所有任务都是 multi-hop。

## 18. Temporal Safety
10 个 Return-policy raw attempt 均因 `UNSUPPORTED_TEMPORAL_BASIS_DELIVERY_DATE_REQUIRED` 与 `TIME_DRIFT_WITHOUT_FROZEN_REFERENCE_DATE` fail closed。

## 19. Region / Effective-time Limitations
Knowledge inventory 没有 explicit region / effective_from / effective_to metadata；E0 没有生成地区政策比较或政策版本比较 Gold。

## 20. Query Leakage
Public Candidate query 使用 `<ORDER_REF:…>` / `<TICKET_REF:…>` / `<WARRANTY_REF:…>` construction token；raw ORD/TCK/WAR/CUST ID=0。Routing family 额外验证 product id/name 不得出现在 query。

## 21. Source Validation
每条 retained Candidate 验证 structured entity 存在、document fact/section source-linked、两类 evidence 齐全、relation/necessity 成立、query 无 region/product/structured fact leakage。

## 22. Family Distribution
Raw：Return-policy 10、Order-status-policy 8、Order-manual 18、Ticket-troubleshooting 8、Warranty-policy 8、Warranty-manual 16。Validated 除 Return-policy 外全部保留，共 58。

## 23. Structured State Distribution
Order-policy 四状态均覆盖；Warranty-policy expired/in_warranty 各 4。Routing families 记录真实 entity state，但不机械按线上流量比例采样。

## 24. Product Coverage
20/20 products 都进入 validated Mixed Pool；max candidates/product=4。D0 未被 Formal Evidence 覆盖的 LIO-PROD-017～020 已全部通过真实 relation 获得 Mixed manual coverage。

## 25. Document Coverage
20/20 product manuals + after-sales policy 被 validated pool 覆盖。FAQ 未强行混入，因为当前没有证明它与 structured entity context 同时必要。

## 26. Policy Concentration
Policy retained=16；max cases/policy fact=8，max cases/policy section=8；最大单 fact 占全部 validated 13.79%，低于 15% warning line，因此 `concentration_warning=false`。

## 27. Entity Concentration
58 validated Candidate 使用 58 个不同 structured entity，max/entity=1；unique customers=53；unique tenants=19/19；max/customer=4；max/tenant=8。

## 28. Semantic Dedup
58 validated 对应 48 effective semantic signatures、58 unique source combinations。重复主要来自合法的 policy state/entity sampling，不按 entity unique 自动当作独立语义。

## 29. Existing Formal Dedup
新 Candidate 与现有 10 Formal Mixed 的 current document section collision=0；没有简单复制现有 Ticket+Manual evidence combination。

## 30. Effective Diversity
Effective=48，满足 E0 minimum；Validated families=5，满足至少 5/6。Raw count 本身不是完成依据。

## 31. Raw Candidates
`mixed_raw_candidates.jsonl` 固定 68 条，全部 status=`CANDIDATE`；source validation 前不提前标 SOURCE_VALIDATED。

## 32. Source Validated
58 条 `SOURCE_VALIDATED`。这些仍为 `SOURCE_DERIVED_DRAFT`，`human_reviewed=false`，`formal_metric_eligible=false`。

## 33. Rejected
10 条，全部来自 `MIXED_ORDER_RETURN_POLICY`；每条同时记录 temporal basis 与 time-drift 两个 rejection reason，没有为凑 family 数量降低标准。

## 34. Artifacts
输出目录 `artifacts/evaluation/dataset-expansion-e0-mixed/`：existing inventory、raw/validated/rejected JSONL、manifest、family/relation/necessity/state/document/policy/entity/dedup/effective-diversity/derived-outcome reports、`phase_e0_summary.json`。另新增 `benchmark-expansion-roadmap-status.json` 冻结 D3-R deferred 状态。

## 35. Tests
D0/E0 专项：15 passed。`tests/evaluation`: 246 passed, 2 skipped。全仓库：460 passed, 2 skipped。`compileall`: PASS。SKIP 为此前真实 Production/Judge integration dependency skip，不属于 E0 quality metric。

## 36. Production Diff
与 D3-R 输入仓库逐文件 SHA-256 对比，`agents/ tools/ retrieval/ context_engine/ memory/ artifact/ governance/ observability/ production/ deployments/` changed files = **0**。

## 37. Formal Dataset Invariance
`dev_v7_3_canonical_v1.json` 与 `validation_v7_3_canonical_v1.json` 均与基线 SHA-256 相同；Formal Canonical before=39 / after=39；New Formal Cases=0。D2 annotation batch、D3 summary、D3-R summary 也保持不变。

## 38. Next-step Stable Inputs
下一阶段可直接依赖 `mixed_source_validated.jsonl`、`mixed_candidate_manifest.json`、`mixed_source_necessity_report.json`、`mixed_dedup_report.json`、`mixed_policy_fact_concentration.json`、`mixed_effective_diversity.json` 以及 D0 source/fact/relation inventories。建议下一步做 **Mixed Gold Preparation**：冻结 routing intermediate vs answer-required facts、derived policy decision、field-level GoldEvidence、runtime materialization；不要继续扩大 Candidate Pool。
