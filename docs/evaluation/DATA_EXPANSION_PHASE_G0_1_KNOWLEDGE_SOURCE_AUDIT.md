# Benchmark Expansion Phase G0.1：Knowledge Source Space Audit 与 KnowledgeSourceUnit Construction

## 1. G0.1 Summary

**Phase G0.1 = COMPLETE**

本阶段只完成 Knowledge Source Space 审计、AtomicFact task-usability re-audit、KnowledgeSourceUnit / CoherentFactGroup 构建、Category Ownership 与 Capacity Blueprint。

严格保持：

```text
New Queries       = 0
New Candidates    = 0
New Formal Cases  = 0
Annotation Runs   = 0
Production Agent  = NOT RUN
D3-R              = DEFERRED_BY_ENVIRONMENT
```

G0.1 的核心结果不是把 `4907 heuristic-usable facts` 包装成 4907 个问题，而是得到真实容量漏斗：

```text
4913 AtomicFact Candidates
        ↓
4500 task-construction-usable facts
        ├─ 3156 TASK_USABLE / independently askable
        ├─ 1343 GROUP_ONLY
        └─    1 CONTEXT_DEPENDENT
        ↓
228 minimal coherent fact groups
        ↓
1355 KnowledgeSourceUnits
        ↓
1220 benchmark-usable SourceUnits
        ↓
1195 effective SourceUnit semantics
```

## 2. Previous Frozen State

开始前及完成后均重新确认：

```text
Formal Canonical                       39      UNCHANGED
Private frozen annotation batch        76      UNCHANGED
Mixed E1-R frozen annotation batch     58      UNCHANGED
Troubleshooting F0 source-valid        66      UNCHANGED
D3-R                           DEFERRED_BY_ENVIRONMENT
```

Frozen semantic hashes：

```text
Private batch hash:
c3b3aa7c65497813a9947e2ee0a8f05bae84958c0f5f09ba1f7bc1f3bc22e01c

Mixed batch hash:
6987053d0f8f238fa6494f4ae828d9e552168239a1fc87618823d0b2164356d8

Troubleshooting F0 candidate-set hash:
9617f6c8846306df50d1c253f12873cd5d3042d77eeca12e0783164e4b6774c0
```

## 3. Knowledge Corpus Inventory

重新直接扫描当前 `data/knowledge/`，并与 D0 artifact 比较：

```text
Knowledge Sources       22
Product Manuals         20
After-sales Policy       1
Support FAQ              1
Stable Sections       1216
AtomicFacts           4913
D0 heuristic usable   4907
```

Source drift：

```text
NO_SOURCE_DRIFT
22/22 document SHA identical to D0
4913/4913 AtomicFact rows identical to D0
```

因此 G0.1 没有修改 Source Truth，也没有修订 D0 facts；只是增加更严格的 task-construction audit layer。

## 4. Document Inventory

全部 22 Source 均保留 deterministic document / stable section identity。

- Source types 仅使用实际存在的 `manual / policy / faq`。
- `region = null`、`effective_from = null`、`effective_to = null` 的 Source 不被解释成 `GLOBAL` 或某个默认时间范围。
- Knowledge Corpus fingerprint：`ddb153a29a039f7b0e00b04eefe6f666809577ac10d8f4ae8be4c71a8d6da6eb`。

## 5. Section Audit

1216 Stable Sections 全量进入 `knowledge_section_audit.jsonl`。

每个 Section 记录：

```text
document_id
section_id
heading
parent_heading
section_path
section_text
fact_ids
fact_count
section_semantics
section_structure
benchmark_usable
```

实际识别到的主要 structure 包括：

```text
SINGLE_FACT
ATTRIBUTE_TABLE
BULLET_FACT_LIST
PROCEDURE
CONDITION_ACTION
COMPATIBILITY_RULE
LIMITATION_RULE
POLICY_RULE
FAQ_QA
MULTI_FACT_DESCRIPTION
FRAGMENT_CONTAINER
```

没有使用 `1 Section = 1 future Question` 的假设。

## 6. AtomicFact Re-audit

最终 task-usability 状态：

```text
TASK_USABLE                  3156
GROUP_ONLY                   1343
CONTEXT_DEPENDENT            1
FRAGMENT                     225
NON_TASK_INFORMATION         47
CATEGORY_OWNERSHIP_EXCLUDED  135
UNSUPPORTED                  6
-------------------------------
TOTAL                        4913
```

其中 D0 的 4907 `heuristic benchmark usable` 被明显收紧。D0 usability 只代表“看起来像可抽取事实”；G0.1 `TASK_USABLE` 则要求该事实本身具有足够完整、稳定的未来 Task core 语义。

## 7. Task Usability Taxonomy

- `TASK_USABLE`：可直接成为未来一个明确、最小 task 的核心事实。
- `GROUP_ONLY`：单独不完整，但可与少量相关 facts 组成 coherent task。
- `CONTEXT_DEPENDENT`：Source truth 成立，但必须保留 heading / condition / referent 等上下文。
- `FRAGMENT`：如“然后…… / 此时……”等无法稳定作为 task core 的片段。
- `NON_TASK_INFORMATION`：目录、FCC/法律文本、文档元信息等无合适用户任务意义内容。
- `CATEGORY_OWNERSHIP_EXCLUDED`：当前已经由 active Troubleshooting 等类别拥有。
- `UNSUPPORTED`：D0 原已 fail-closed 的 cross/external reference 等事实。

## 8. Fact Relationship

KnowledgeSourceUnit relationship 分布：

| Relationship | SourceUnits |
|---|---:|
| INDEPENDENT | 867 |
| CONDITION_ACTION | 275 |
| PROCEDURE | 93 |
| COMPATIBILITY_RELATION | 47 |
| ATTRIBUTE_VALUE | 35 |
| POLICY_RULE | 15 |
| LIMITATION | 14 |
| QUESTION_ANSWER | 8 |
| MULTI_FACT_DESCRIPTION | 1 |

这里 relationship 描述 Source 内部事实结构，不代表已经生成某种 Candidate task。

## 9. KnowledgeSourceUnit Contract

新增 `KnowledgeSourceUnit` construction contract，至少冻结：

```text
source_unit_id
document_id
section_ids
source_type
product_id / product_family
semantic_topic
unit_type
fact_ids
primary_fact_ids
supporting_fact_ids
context_fact_ids
fact_relationship
independent_askable_fact_ids
coherent_fact_group_ids
required_local_context
category_ownership
knowledge_usability
semantic_signature
cross_product_signature
quality_flags
```

SourceUnit ID 基于 document、stable section、relationship、normalized semantic content 生成 deterministic hash，不依赖生成顺序。

## 10. Independent Askable Facts

```text
Independent askable facts            3156
Task-construction-usable facts        4500
Ratio                                 70.13%
```

剩余可参与任务构造的 facts 主要进入 coherent grouping，而不是被丢弃或强行独立成题。

## 11. Coherent Fact Groups

```text
Coherent Fact Groups    228
Average facts/group     2.71
Maximum facts/group     3
```

所有自动构建 group 均限制为 1–3 facts，且同一 section 不生成 sliding-window 组合，避免 group combinatorial inflation。

## 12. Required Local Context

```text
Facts requiring some local context: 4533
```

Context 类型：

```json
{
  "attribute_label_or_table_header": 43,
  "condition_clause": 378,
  "preceding_context": 67,
  "referent_context": 455,
  "section_heading": 4416
}
```

特别是所有 `ATTRIBUTE_VALUE` facts 均保留 `attribute_label_or_table_header`，不会把 `3.2kg` 之类值脱离属性名直接当事实。

## 13. Procedure Structures

Procedure inflation audit：

```text
Procedure SourceUnits                       93
Procedure effective SourceUnits             90
Facts/steps if mechanically inflated        792
Mechanical inflation avoided                699
```

也就是说，类似 10-step procedure 不会默认变成 10 个独立 SourceUnit / 10 个 future questions。

## 14. Table Structures

`PRODUCT_SPEC / ATTRIBUTE_VALUE` 保留：

```text
product
attribute label / table header
value
unit / local context
stable section
```

Task Planning 后续可以选择独立规格事实，但 G0.1 不生成 Spec Query。

## 15. Compatibility / Limitation Structures

实际 Source 中保留：

```text
COMPATIBILITY_RELATION SourceUnits  47
LIMITATION SourceUnits              14
```

关系保留 subject / condition / exception 语义，不把单独“支持”“不可”当成完整关系。

## 16. Policy / FAQ Structures

FAQ inflation：

```text
FAQ sentence facts      17
FAQ SourceUnits          8
Inflation prevented      9
```

Policy inflation：

```text
Policy facts             23
Policy SourceUnits        7
Inflation prevented       16
```

FAQ canonical question 只作为 Source structure 保存，**本阶段没有生成 FAQ Candidate Query**。

Policy 中“通常 / 可能”等 qualified wording 继续通过 `POLICY_AMBIGUITY` flag 保留，G0.1 不解释成绝对 outcome。

## 17. Category Ownership

Fact-level primary ownership：

```json
{
  "KNOWLEDGE_AVAILABLE": 4778,
  "TROUBLESHOOTING": 135
}
```

已观察到的 cross-stage overlap：

```json
{
  "FORMAL": 302,
  "MIXED": 162,
  "TROUBLESHOOTING": 135
}
```

关键语义：

- 135 个 active F0 Troubleshooting facts 被 `TROUBLESHOOTING` exclusive ownership 排除。
- `FORMAL` / `MIXED` overlap 只表示某 Source fact 已被前阶段使用，不代表这个 document fact 永久失去纯 Knowledge task 价值。
- 当前没有事实因为“天然需要 Structured DB”而被 G0.1 判为 `MIXED` primary ownership；真正 Structured dependency 要在后续 Task Planning 出现时 fail closed。

## 18. Troubleshooting Exclusions

```text
Active Troubleshooting-owned facts = 135
Owned-by-other-category SourceUnits = 42
```

F0 active symptom / diagnostic / conditional troubleshooting / escalation facts 不再被当作普通 Knowledge capacity 重复计算。

需要注意：D0 的 `fact_type=TROUBLESHOOTING_STEP` 是粗启发式类型，不等价于 F0 ownership。只有 F0 重新证明为 active troubleshooting 的 source semantics 才 exclusive exclusion。

## 19. Mixed Exclusions

```text
Primary MIXED-owned facts = 0
Observed Mixed overlaps   = 162
```

G0.1 尚未生成 Task，因此不能因为某 manual fact 曾被 Mixed case 使用，就断言未来纯 document lookup 必然依赖 Structured DB。

## 20. Cross-product Semantic Duplicates

Fact-level exact normalized semantic duplicate：

```text
Duplicate groups       12
Duplicate facts        25
Duplicate excess       13
```

典型真实重复包括：

- `立即擦拭溢出的燃油。` — LIO-PROD-008, LIO-PROD-012
- `不补充机油则无法再次启动。` — LIO-PROD-008, LIO-PROD-012
- `：与排放控制系统相关。` — LIO-PROD-008, LIO-PROD-012
- `加油时务必关闭发动机。` — LIO-PROD-008, LIO-PROD-012
- `加油时注意不要将燃油洒在发动机或消音器上。` — LIO-PROD-008, LIO-PROD-012
- `发动机开关控制点火系统。` — LIO-PROD-008, LIO-PROD-012

这些不会被自动删除，因为不同产品仍可能需要 source-specific grounding；但后续 Capacity / Candidate selection 不能全部当作独立能力。

## 21. Source Coverage

```text
Sources total             22
Sources with usable KSU   22
Sources without usable    0
```

| Document | Type | Usable Units | Effective Units |
|---|---|---:|---:|
| LIO-PROD-001_VR头显手册 | manual | 34 | 34 |
| LIO-PROD-002_人体工学椅手册 | manual | 7 | 7 |
| LIO-PROD-003_健身单车手册 | manual | 78 | 77 |
| LIO-PROD-004_健身追踪器手册 | manual | 122 | 109 |
| LIO-PROD-005_儿童电动摩托车手册 | manual | 29 | 29 |
| LIO-PROD-006_冰箱手册 | manual | 99 | 96 |
| LIO-PROD-007_功能键盘手册 | manual | 55 | 53 |
| LIO-PROD-008_发电机手册 | manual | 64 | 64 |
| LIO-PROD-009_可编程温控器手册 | manual | 38 | 38 |
| LIO-PROD-010_吹风机手册 | manual | 61 | 61 |
| LIO-PROD-011_摩托艇手册 | manual | 61 | 61 |
| LIO-PROD-012_水泵手册 | manual | 61 | 61 |
| LIO-PROD-013_洗碗机手册 | manual | 112 | 111 |
| LIO-PROD-014_烤箱手册 | manual | 65 | 65 |
| LIO-PROD-015_电钻手册 | manual | 61 | 61 |
| LIO-PROD-016_相机手册 | manual | 102 | 102 |
| LIO-PROD-017_空气净化器手册 | manual | 30 | 30 |
| LIO-PROD-018_空调手册 | manual | 77 | 72 |
| LIO-PROD-019_蒸汽清洁机手册 | manual | 27 | 27 |
| LIO-PROD-020_蓝牙激光鼠标手册 | manual | 22 | 22 |
| after_sales_policy | policy | 7 | 7 |
| liorin_support_faq | faq | 8 | 8 |

这里是 Source capacity，不是 Candidate distribution；长 Manual 拥有更多 SourceUnits 不意味着 G0.2 应按文档长度比例采样。

## 22. Product Coverage

```text
Products total             20
Products with usable KSU   20
Products without usable    0
```

| Product | Usable Units | Effective Units |
|---|---:|---:|
| LIO-PROD-001 | 34 | 34 |
| LIO-PROD-002 | 7 | 7 |
| LIO-PROD-003 | 78 | 77 |
| LIO-PROD-004 | 122 | 109 |
| LIO-PROD-005 | 29 | 29 |
| LIO-PROD-006 | 99 | 96 |
| LIO-PROD-007 | 55 | 53 |
| LIO-PROD-008 | 64 | 64 |
| LIO-PROD-009 | 38 | 38 |
| LIO-PROD-010 | 61 | 61 |
| LIO-PROD-011 | 61 | 61 |
| LIO-PROD-012 | 61 | 61 |
| LIO-PROD-013 | 112 | 111 |
| LIO-PROD-014 | 65 | 65 |
| LIO-PROD-015 | 61 | 61 |
| LIO-PROD-016 | 102 | 102 |
| LIO-PROD-017 | 30 | 30 |
| LIO-PROD-018 | 77 | 72 |
| LIO-PROD-019 | 27 | 27 |
| LIO-PROD-020 | 22 | 22 |

## 23. Fact Type Funnel

| Fact Type | Source | TASK_USABLE | Independent | Group-only | Hard-excluded | Effective Contribution |
|---|---:|---:|---:|---:|---:|---:|
| FEATURE_OR_INSTRUCTION | 3633 | 2356 | 2356 | 1075 | 201 | 943 |
| SAFETY_INSTRUCTION | 707 | 484 | 484 | 173 | 50 | 173 |
| TROUBLESHOOTING_STEP | 317 | 115 | 115 | 57 | 145 | 94 |
| WARRANTY | 76 | 50 | 50 | 18 | 8 | 33 |
| COMPATIBILITY | 69 | 64 | 64 | 0 | 5 | 48 |
| PRODUCT_SPEC | 43 | 41 | 41 | 0 | 2 | 35 |
| LIMITATION | 20 | 19 | 19 | 0 | 1 | 16 |
| AFTER_SALES | 13 | 7 | 7 | 6 | 0 | 5 |
| FAQ_PROCESS | 10 | 0 | 0 | 10 | 0 | 4 |
| POLICY | 10 | 9 | 9 | 0 | 1 | 5 |
| RETURN_POLICY | 9 | 8 | 8 | 1 | 0 | 6 |
| WARRANTY_POLICY | 4 | 3 | 3 | 1 | 0 | 2 |
| ERROR_CODE | 2 | 0 | 0 | 2 | 0 | 1 |

最重要的变化是：Source 中 `FEATURE_OR_INSTRUCTION=3633`，但 G0.1 没有把 3633 条直接当 future question capacity。大量 procedure steps、fragments、context-dependent units 被 grouping / ownership / usability gate 压缩。

## 24. Capacity Funnel

```text
AtomicFact Candidates                  4913
D0 heuristic usable                    4907
Task-construction usable               4500
  ├─ Independent askable               3156
  ├─ GROUP_ONLY                        1343
  └─ CONTEXT_DEPENDENT                 1
Fragments                              225
Non-task information                   47
Troubleshooting-owned                  135
Unsupported                            6
Coherent fact groups                   228
KnowledgeSourceUnits                   1355
Benchmark-usable SourceUnits           1220
Effective SourceUnits                  1195
```

这才是后续 Knowledge Candidate planning 的真实数据基础。

## 25. Effective Source Units

```text
Raw KSU                  1355
Benchmark usable KSU     1220
Effective KSU            1195
```

`effective` 使用 normalized semantic signatures 做折扣，不按 source_unit_id 直接计数。

当前 1195 effective semantics **不等于建议生成 1195 道题**；Candidate selection 仍需 source balance、task balance、fact-type balance 和 cross-stage dedup。

## 26. Previous Untested Source Audit

D0 指出的 5 个此前 Formal 未覆盖 Source 已逐个重新验证：

| Source | Exists | TASK_USABLE facts | Usable KSU | Effective KSU | G0.2 Priority |
|---|---|---:|---:|---:|---|
| Air Purifier | YES | 98 | 30 | 30 | YES |
| Air Conditioner | YES | 152 | 77 | 72 | YES |
| Steam Cleaner | YES | 75 | 27 | 27 | YES |
| Bluetooth Laser Mouse | YES | 28 | 22 | 22 | YES |
| Support FAQ | YES | 0 | 8 | 8 | YES |

五者都仍有真实 Knowledge capacity，因此 G0.2 应优先覆盖，而不是继续只从已有高频 Formal source 采样。

## 27. P0 / P1 / P2 Source Priority

当前只在 SourceUnit 层标 priority，不生成 Query：

```text
P0  672
P1  539
P2  9
```

P0 原则包括：

- previously untested / under-covered Source；
- Compatibility / Limitation；
- Policy / FAQ；
- minimal multi-fact coherent units；
- 其它高信息量、尚未覆盖的 SourceUnit。

P1 主要是 common spec / common feature / maintenance 等正常能力覆盖。

P2 主要是 high-frequency generic instruction、cross-product duplicated semantics 或低边际价值来源。

P0 数量本身不是 G0.2 Candidate quota。

## 28. Candidate Capacity Blueprint

```text
Minimum high-quality candidate capacity  120
Recommended first-wave capacity           180
Upper reasonable capacity                 240
Confidence                                HIGH
```

依据：

```json
{
  "coherent_fact_groups": 228,
  "effective_source_units": 1195,
  "independent_askable_facts": 3156,
  "principle": "balanced source-unit/task-semantic selection; no paraphrase multiplication",
  "semantic_topics": 18,
  "usable_sources": 22
}
```

因此原 G0 的 `160–190 Raw` 规划在真实 SourceSpace 上是可支持的；建议第一波仍控制在 **约 180 raw planning units**，而不是因为 Source capacity 大就无限扩容。

## 29. Reproducibility

```text
knowledge_source_space_hash:
206fac5baaf012483066e913e56bfb10fb6ce97cc1d4d6dfeb9b22b8800cc40b

corpus_fingerprint:
ddb153a29a039f7b0e00b04eefe6f666809577ac10d8f4ae8be4c71a8d6da6eb
```

同一 corpus 重跑：

- KSU IDs stable；
- FactGroup IDs stable；
- counts stable；
- semantic source-space hash stable；
- timestamp / generated_at 不参与 semantic hash。

## 30. Artifacts

新增：

```text
artifacts/evaluation/dataset-expansion-g0-1-knowledge-source/
├── knowledge_document_inventory.json
├── knowledge_section_audit.jsonl
├── knowledge_atomic_fact_audit.jsonl
├── knowledge_source_units.jsonl
├── knowledge_source_unit_report.json
├── knowledge_fact_relationship_distribution.json
├── knowledge_independent_askable_facts.jsonl
├── knowledge_coherent_fact_groups.jsonl
├── knowledge_context_dependencies.json
├── knowledge_category_ownership.json
├── knowledge_cross_product_semantic_duplicates.json
├── knowledge_source_coverage.json
├── knowledge_product_coverage.json
├── knowledge_fact_type_funnel.json
├── knowledge_capacity_funnel.json
├── knowledge_uncovered_source_units.json
├── knowledge_previous_uncovered_source_audit.json
├── knowledge_capacity_blueprint.json
├── knowledge_inflation_audit.json
├── knowledge_source_space_manifest.json
└── phase_g0_1_summary.json
```

## 31. Code Changes

新增：

```text
evals/benchmark/expansion/
├── knowledge_source_unit.py
├── knowledge_source.py
├── knowledge_ownership.py
├── knowledge_capacity.py
├── knowledge_source_reporting.py
└── g0_1_runner.py
```

修改：

```text
evals/benchmark/expansion/__init__.py
eval_platform/cli.py
```

统一 CLI：

```bash
python -m eval_platform.cli \
  dataset-audit-knowledge-source \
  --root . \
  --d0 artifacts/evaluation/dataset-expansion-d0 \
  --output artifacts/evaluation/dataset-expansion-g0-1-knowledge-source
```

没有新建 parallel Evaluation Framework。

## 32. Tests

最终真实回归：

```text
G0.1 targeted:
19 passed

Evaluation:
321 passed, 2 skipped

Full repository:
535 passed, 2 skipped

compileall:
PASS
```

两个 SKIP 仍是既有 real Production / real Judge integration dependency tests，与 G0.1 无关。

测试覆盖包括：

- D0/current corpus exact drift gate；
- AtomicFact trace；
- KSU → fact → section → document trace；
- Independent askability；
- fragment / procedure / table / condition preservation；
- active Troubleshooting ownership；
- FAQ/Policy/Procedure inflation；
- cross-product duplicate；
- previous-uncovered sources；
- stable ID / semantic hash reproducibility；
- zero Query / Candidate / Formal / Annotation boundary。

## 33. Formal Dataset Invariance

```text
Development = 34
Validation  = 5
Formal      = 39
```

SHA-256：

```text
dev_v7_3_canonical_v1.json
7a4f939739a73e6f2b8faae8bdea33c5b6f375fb77d333fb625e231cc7935a5d

validation_v7_3_canonical_v1.json
df7e66e95fdd88931a1f6368d9365a3b5cef835f40211e54b801e17d6465a60c
```

均与 F0 baseline 完全一致。

## 34. Production Diff

对以下目录逐文件 SHA-256 比较：

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

最终：

```text
Production behavior changed files = 0
```

G0.1 只新增 dataset-construction artifacts / code / tests / docs，并向现有统一 CLI 增加 source-audit command。

## 35. G0.2 Stable Inputs

下一阶段可以稳定依赖：

```text
knowledge_document_inventory.json
knowledge_section_audit.jsonl
knowledge_atomic_fact_audit.jsonl
knowledge_source_units.jsonl
knowledge_independent_askable_facts.jsonl
knowledge_coherent_fact_groups.jsonl
knowledge_context_dependencies.json
knowledge_category_ownership.json
knowledge_cross_product_semantic_duplicates.json
knowledge_source_coverage.json
knowledge_product_coverage.json
knowledge_fact_type_funnel.json
knowledge_capacity_funnel.json
knowledge_uncovered_source_units.json
knowledge_previous_uncovered_source_audit.json
knowledge_capacity_blueprint.json
knowledge_source_space_manifest.json
```

G0.2 应优先做 **Knowledge Task Planning / balanced source-unit selection**，而不是直接生成 Query。

基于 G0.1 的真实结果，G0.2 优先顺序建议：

1. P0：此前未覆盖 Source、Compatibility、Limitation、Policy/FAQ、minimal multi-fact units；
2. 控制 `FEATURE_OR_INSTRUCTION`，不能按其 Source 数量占比采样；
3. 从约 180 个 first-wave planning slots 开始；
4. 在 TaskPlan 冻结 required facts / evidence / reasoning / scope 后，才允许进入 controlled query rendering；
5. 保持 F0 active troubleshooting ownership 与 Mixed structured dependency guard。

**G0.1 到此停止。没有生成任何 Query，也没有自动开始 G0.2。**
