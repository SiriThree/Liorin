# Benchmark Expansion Phase E1-R：Manual-routing Query Scope Repair 与 Mixed Gold Re-freeze

## 1. E1-R Summary

Phase E1-R 只修复 Phase E1 中 42 条 `NEEDS_MANUAL_PRECHECK` 的 Manual-routing Mixed Case。没有重新生成 Candidate、没有重新采样业务实体、没有更换 Product/Manual/Section/selected AtomicFact，也没有触碰 Production 行为。

最终：

```text
Policy READY frozen          16
Manual PRECHECK input        42
REPAIRED_READY               42
STILL_PRECHECK                0
REJECTED_AFTER_REPAIR         0

Final READY                  58
Effective Gold units         48
Ready Mixed families          5
Products covered             20
Knowledge sources covered    21

Annotation Runs               0
New Formal Cases              0
Production Agent        NOT RUN
D3-R             DEFERRED_BY_ENVIRONMENT
```

E1-R 的 `COMPLETE` 表示 Query Scope Repair、Gold re-freeze 与新 annotation batch freeze 完成，不代表 Dual Annotation/Human Review/Formal Promotion 已完成。

## 2. E1 Inputs

真实 E1 输入重新确认：

```text
Gold Drafts          58
READY                16
PRECHECK             42
REJECT                0
```

42 条 PRECHECK：

```text
MIXED_ORDER_PRODUCT_MANUAL       18
MIXED_TICKET_TROUBLESHOOTING      8
MIXED_WARRANTY_PRODUCT_MANUAL    16
```

E0 的 10 条 `MIXED_ORDER_RETURN_POLICY` rejected case 与 E1-R repair input 交集为 0。

## 3. Repair Scope

E1-R 没有改 Source Truth。42 条只涉及 20 个 distinct E0-selected AtomicFact；修复对象是 Candidate Query Scope 以及由新 scope 决定的最小 `ANSWER_REQUIRED` Gold。

每条 lineage：

```text
original E0 candidate_id
→ E1 Gold Draft
→ E1-R repair_id / query_version
```

原 query 与 repaired query 都保留，禁止 silent overwrite。

## 4. Frozen Policy Cases

E1 中 16 条 Policy READY 全部冻结：

```text
MIXED_ORDER_STATUS_POLICY        8
MIXED_WARRANTY_STATUS_POLICY     8
```

逐 Case 重新计算并确认以下四类 hash 与 E1 完全一致：

```text
query hash
Gold Draft hash
GoldEvidence hash
annotation packet hash
```

`policy_freeze_verified = true`。

旧 E1 batch 保持：

```text
MIX-E1-1FECB833D0B9
1fecb833d0b96ce695343df4543c27b6a50e98657c41ecc95a8068c3088d2861
```

没有覆盖。

## 5. Manual Fact Scope Contract

新增 Construction-only `ManualFactScope`，至少冻结：

- candidate / document / section / selected fact identity
- selected fact text / source fact type
- fact granularity
- independently askable
- required context
- condition / action / symptom / object / constraint
- related fact IDs
- minimal coherent group
- repairability / reason
- repair type / intent ID
- deterministic question body

这不是新的 Runtime Evaluation schema。

## 6. Fact Granularity

42 条按 E1-R scope semantics 分类：

```text
CONDITIONAL_ACTION      14
TROUBLESHOOTING_STEP     6
FRAGMENT_ONLY            5
LIMITATION               5
SAFETY_INSTRUCTION       4
ATOMIC_ACTION            3
PROCEDURE_STEP           3
MULTI_FACT_DEPENDENT     2
```

原 D0 fact type：

```text
TROUBLESHOOTING_STEP      39
FEATURE_OR_INSTRUCTION     3
```

E1-R granularity 不改 D0 fact type，只用于 Query Scope construction。

## 7. Repairability

20 个 distinct selected facts 都找到 source-preserving deterministic repair plan，因此对应 42 条 entry-path Case 均可修复。

关键点：这不是把 section 全部事实加入 Gold，而是把宽 query 改成具体用户 intent。

## 8. Query Intent Contract

每条 repaired query 固定：

```text
intent_id
target selected fact
user-known context
hidden product identity
structured resolution requirement
document resolution requirement
exact answer scope
```

Product identity 继续由 Structured Source 获得，不能由 query 直接泄漏。

## 9. Order → Manual Repair

```text
input   18
ready   18
precheck 0
reject   0
```

`order.product_id` 继续保持：

```text
TASK_REQUIRED_INTERMEDIATE
ROUTING_EVIDENCE
```

Repaired query 只围绕 specific operation / condition / symptom / threshold / limitation 提问。

示意（脱敏）：

```text
订单 [ORDER_FIXTURE_ID] 里的设备具体型号我不记得了。
请先从订单确认对应产品，再根据该产品手册，
如果插头翻转重试后仍无法插入，下一步应该怎么办？
```

## 10. Ticket → Troubleshooting Repair

```text
input   8
ready   8
precheck 0
reject   0
```

没有读取 `ticket.summary` 来偷补 symptom。Structured requirement 仍只来自原 E0 plan 的 `ticket.product_id`。

示意：

```text
工单 [TICKET_FIXTURE_ID] 里没有写产品型号。
请先根据工单关联的产品确认对应手册。
如果换上另一块电池仍出现相同故障提示，下一步应该怎么办？
```

## 11. Warranty → Manual Repair

```text
input   16
ready   16
precheck 0
reject   0
```

`warranty.product_id` 继续是 routing intermediate。Warranty case 仍作为自然 structured entity entry point，没有变成仅靠 Manual 就能完成的 Knowledge-only Query。

## 12. Original vs Repaired Query

原始 42 条统一问题：

```text
BROAD_MANUAL_SECTION_SCOPE
DOCUMENT_GOLD_COMPLETENESS_NOT_DETERMINISTIC
```

旧 query 典型语义：

```text
“说明某 section 相关的使用或处理要点”
```

Repair 后改为：

```text
specific condition → action
specific symptom → next step
specific operation → instruction
specific threshold / limitation
specific safety prerequisite
```

所有 original/repaired text 均保留在 scope repair artifact。

## 13. Source Preservation

42 条 repair 的变化数：

```text
structured entity changed      0
product relation changed       0
manual changed                 0
section changed                0
selected source fact changed   0
```

没有 Candidate regeneration。

## 14. Structured Routing Preservation

所有 42 条：

```text
structured_source_required = true
```

Query 中没有 Product ID / Product Name。即使 Manual final answer 碰巧可以猜对，Mixed TaskSuccess 仍要求正确 routing evidence，不能把猜中当成功。

## 15. Manual Relation Preservation

所有 repaired case 保持：

```text
same structured entity
→ same product relation
→ same manual
→ same current stable section
→ same originally selected AtomicFact
```

没有更换一个“更好问”的 Manual fact。

## 16. Gold Rebuild

E1-R 不扩大 section-level Gold。

对于独立事实：selected fact 仍是唯一 `ANSWER_REQUIRED` Document Fact。

对于 context-dependent fragment，只增加同 section 的 minimal `SUPPORTING_ONLY` context fact，selected answer fact 不变。

## 17. Gold Completeness

```text
before issues   42
after issues     0
resolved        42
```

Query 收窄后，用户明确询问内容都能由 selected answer fact 覆盖。

## 18. Gold Minimality

```text
before issues   42
after issues     0
```

没有把 2–21 个 section facts 全部塞入 Gold。

## 19. Mixed Necessity

```text
Structured required   42 / 42
Document required     42 / 42
Repair-invalidated     0
```

所有 repair 后仍是真正 Mixed task。

## 20. Query Leakage

```text
clean                         42
product identity leakage      0
document answer leakage       0
raw fixture ID leakage        0
```

Materialized runtime preview 同样不持久化 raw fixture ID。

## 21. Gold-level Dedup

Manual repaired：

```text
Manual READY                    42
Unique repaired signatures      42
Low-information entity excess    0
```

最终全部 58 Gold units：

```text
Unique information signatures   48
Duplicate excess                 10
```

所以 42/42 repair 没有把有效 Benchmark Capacity 人为从 48 抬到 58。

## 22. Existing Formal Collision

现有 Formal Mixed：10。

Repair 后重新检查 query semantics / Gold value / structured entry type：

```text
exact existing Formal Gold collision = 0
```

尤其 Ticket family 没有因为 scope narrowing 变成现有 10 条 Formal 的直接 Gold duplicate。

## 23. Effective Diversity

```text
E0 effective                    48
E1 Gold effective               48
E1-R final effective            48
Final READY                     58
```

`READY count` 与 `effective diversity` 明确分开。

## 24. Repair READY

```text
REPAIRED_READY = 42
```

这表示 42 条都通过 Natural / Specific / Source-grounded / Gold-complete / Gold-minimal / Mixed-necessary / Non-leaking / Non-collision gates。

## 25. Still PRECHECK

```text
0
```

## 26. Rejected

```text
0
```

E1-R 没有通过换 Source / 换 Fact 来避免 reject；本批 20 个 selected facts 在 source-preserving scope rules 下均可形成明确任务。

## 27. Mixed Gold Re-freeze

新文件：

```text
mixed_gold_drafts_refrozen.jsonl
```

共 58 条：16 个 Policy Draft 完全复用 E1；42 个 Manual Draft 更新 active query materialization / scope metadata / minimal context，但 Source identity 与 selected answer fact 不变。

## 28. Annotation Packet Re-freeze

新 packet 数：

```text
58
```

其中前 16 个 Policy packet 直接复用 E1 原对象/hash；42 个 Manual packet 以 repaired query + minimal snapshot 重新冻结。

Packet 不包含 full section text、Production Prediction、Agent Trace、Judge Result、其他 Annotator Decision 或 split membership。

## 29. New Batch Manifest

```text
batch_id:
MIX-E1R-6987053D0F8F

batch_hash:
6987053d0f8f238fa6494f4ae828d9e552168239a1fc87618823d0b2164356d8

packet_count:
58
```

旧 E1 batch 保持不变。

## 30. Artifacts

输出目录：

```text
artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/
```

包含：

- `manual_scope_repair_input.jsonl`
- `manual_fact_scope_audit.jsonl`
- `manual_scope_repair_proposals.jsonl`
- `manual_scope_repair_results.jsonl`
- `manual_scope_repair_ready.jsonl`
- `manual_scope_repair_precheck.jsonl`
- `manual_scope_repair_rejected.jsonl`
- `manual_scope_repair_manifest.json`
- `manual_scope_fact_type_distribution.json`
- `manual_scope_gold_completeness.json`
- `manual_scope_gold_minimality.json`
- `manual_scope_mixed_necessity.json`
- `manual_scope_query_leakage.json`
- `manual_scope_gold_level_dedup.json`
- `manual_scope_existing_formal_collision.json`
- `manual_scope_effective_diversity.json`
- `mixed_gold_drafts_refrozen.jsonl`
- `mixed_source_snapshots_refrozen.jsonl`
- `mixed_annotation_packets_refrozen.jsonl`
- `mixed_annotation_batch_manifest_refrozen.json`
- `mixed_ready_distribution_refrozen.json`
- `phase_e1r_summary.json`

## 31. Tests

真实执行：

```text
E1-R targeted:
20 passed

Evaluation suite:
284 passed, 2 skipped

Full repository:
498 passed, 2 skipped

compileall:
PASS
```

2 个 skip 仍是既有 real Production / real Judge integration dependency tests，与 E1-R 无关。

## 32. Formal Dataset Invariance

```text
Development = 34
Validation  = 5
Formal      = 39
New Formal Cases = 0
```

两个 canonical 文件 SHA-256 与 E1 baseline 完全一致。

## 33. Production Diff

逐文件比较：

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

结果：

```text
Production behavior files changed = 0
```

## 34. Next Stable Inputs

后续 Mixed 工作可以稳定依赖：

- `mixed_gold_drafts_refrozen.jsonl`
- `mixed_source_snapshots_refrozen.jsonl`
- `mixed_annotation_packets_refrozen.jsonl`
- `mixed_annotation_batch_manifest_refrozen.json`
- `manual_fact_scope_audit.jsonl`
- `manual_scope_repair_manifest.json`
- `manual_scope_gold_level_dedup.json`
- `manual_scope_effective_diversity.json`

但 Real Annotator Runtime 仍是 `DEFERRED_BY_ENVIRONMENT`，因此当前不运行 Mixed Dual Annotation。

## Final Assessment

E1 的问题不是 Source 无效，而是宽 Query 使单 AtomicFact Gold 不完整。E1-R 通过 deterministic、source-preserving scope repair，把 42 条 query 收窄到 specific intent；12 条上下文依赖事实仅引入 1 条同 section supporting context，最大 group size=2，没有 section dump。

最终 Mixed Gold batch 已从仅 16 个 Policy READY 恢复为 58 READY、5 families、20 products、21 knowledge sources，同时 effective information units 仍为 48，避免把 repaired surface/entity variation 误当成新的 Benchmark Capacity。
