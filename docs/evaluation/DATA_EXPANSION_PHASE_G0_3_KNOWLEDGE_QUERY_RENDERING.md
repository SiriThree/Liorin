# Benchmark Expansion Phase G0.3 — Controlled Query Rendering 与 Knowledge Candidate Validation

## 1. G0.3 Summary

**COMPLETE**。

本阶段只消费 G0.2 已冻结的 180 个 `KnowledgeTaskPlan`，执行 deterministic `CONTROLLED_LANGUAGE_RENDERER` 与 Candidate-level validation。没有重新选 SourceUnit、没有修改 TaskPlan、没有生成 Formal Gold、没有运行 Annotation、没有运行 Production Agent。

最终：

- Input TaskPlans: **180**
- Rendering Attempts: **180**
- SOURCE_VALIDATED: **171**
- NEEDS_QUERY_REVIEW: **8**
- REJECTED: **1**
- Effective Semantic Units: **171**
- Effective / SOURCE_VALIDATED: **100%**
- Semantic Duplicate Excess: **0**
- Document Coverage: **22 / 22**
- Product Coverage: **20 / 20**

## 2. G0.2 Frozen Input

输入 `knowledge_task_plans.jsonl` 数量仍为 180，`task_plan_set_hash`：

`f8cabae08e04aeb30d61cb5e7fd605ef0e947d768b828256e5a610e2df098a0d`

G0.2 `knowledge_task_plans.jsonl` 与 `knowledge_task_plan_manifest.json` 均与输入仓库 byte-identical。

## 3. Renderer Design

Renderer：`CONTROLLED_LANGUAGE_RENDERER`。

- `llm_used = false`
- renderer version: `controlled-knowledge-query-g0.3-v1`
- 1 TaskPlan -> max 1 active Candidate
- stable-hash driven finite surface grammar
- no Agent prediction, no Judge, no Retriever output

Renderer 只消费 frozen TaskPlan、Source Fact semantics、stable section heading、user-facing product name 与 rendering constraints。

## 4. Rendering Constraints

180 / 180 TaskPlan 均继续使用 G0.2 冻结的：

- `allowed_user_context`
- `required_user_context`
- `forbidden_answer_terms`
- `forbidden_internal_terms`
- `must_not_expand_scope`
- `must_not_reveal_answer`
- `product_name_allowed`
- `expected_query_intent`

Renderer 没有修改这些字段。

## 5. Rendering Attempts

180 / 180 TaskPlan 均产生一次 rendering attempt。

没有一个 Plan 产生多个 active paraphrase；Candidate ID 基于 `task_plan_id + render_version + normalized_query` 稳定生成。

## 6. Query Naturalness

Hard naturalness validation：

- Attempts: 180
- Hard PASS: 180
- Hard naturalness reject: 0
- Warning-bearing surfaces: 13

最终 8 条进入 `NEEDS_QUERY_REVIEW`，原因不是 Gold 不确定，而是 surface / planning semantic quality 仍值得人工 query review。

Surface：

- renderer patterns: **48**
- max single pattern ratio: **10.00%**
- max six-character prefix ratio: **2.22%**
- average query length: **27.46 chars**
- min/max: **13 / 46 chars**

没有单一模板统治数据。

## 7. Intent Preservation

- Intent alignment PASS: **179 / 180**
- Intent drift: **0**
- Category drift: **1**

唯一 hard category drift 是 G0.2 中漏过 ownership 的洗碗机 `机器不启动` Direct Plan。Renderer 后它明确成为 active troubleshooting query，因此 fail-closed 为 `CATEGORY_DRIFT_TROUBLESHOOTING`。

## 8. Scope Preservation

- Scope alignment PASS: **180 / 180**
- SCOPE_EXPANSION: 0
- SCOPE_COLLAPSE: 0
- SCOPE_MUTATION: 0

受控 renderer 没有通过“介绍一下/相关要点”等 broad surface 扩大 frozen answer scope。

## 9. Fact Alignment

- all required facts demanded: **180 / 180**
- required fact missing: 0
- supporting fact promoted: 0
- extra unsupported fact: 0

Query renderer 的 `render_metadata.targets` 必须与 frozen `required_fact_ids` 完全一致。

## 10. Evidence Alignment

- complete: **180 / 180**
- issues: 0

Candidate 继续绑定 G0.2 frozen `required_evidence_ids`；Query Rendering 不允许改变 Evidence dependency。

## 11. Answer Leakage

最终 180 attempts 的 leakage report：

- exact answer text: 0
- numeric: 0
- boolean: 0
- compatibility outcome: 0
- limitation outcome: 0
- policy conclusion: 0
- internal terms: 0

Section heading 本身若恰好被 AtomicFact inventory 记录为 heading-like fact，只允许作为 user-visible task context；若它是单一 required fact，则单独进入 heading-only review，不能借此绕过低信息量检查。

## 12. Internal Leakage

SOURCE_VALIDATED Query 中：

- `LIO-PROD-*`: 0
- `KSU-*`: 0
- `KTP-*`: 0
- `af:*`: 0
- `section_id/fact_id/document_id`: 0
- construction placeholders: 0

只使用真实 user-facing product name。

## 13. Direct / Spec

G0.2 Planned：

- DIRECT_FACT: 21
- PRODUCT_SPEC: 12

G0.3 SOURCE_VALIDATED：

- DIRECT_FACT: **17**
- PRODUCT_SPEC: **12**

Direct 下降来自 3 review + 1 active-troubleshooting reject。Spec 未发生 Candidate rejection。

## 14. Feature / Instruction

Planned: **42**

SOURCE_VALIDATED: **42 / 42**

Renderer 使用 condition-action / specific-operation / requirement patterns，避免把单一 frozen Fact 写成 broad “这个功能怎么用”。

## 15. Compatibility

Planned: 21

SOURCE_VALIDATED: **17**

NEEDS_QUERY_REVIEW: **4**

其中：

- `PLANNING_COMPATIBILITY_SEMANTICS_UNCERTAIN`: 3
- `VAGUE_COMPATIBILITY_SCOPE_REVIEW`: 1

Review case 保持 G0.2 task type 不变，没有在 G0.3 偷偷重分类。

## 16. Limitation

Planned: **12**

SOURCE_VALIDATED: **12 / 12**

Limitation queries 询问限制维度，但不提前声明“不支持/不能”等 Gold outcome；limitation leakage = 0。

## 17. Policy / Warranty

Planned: **12**

SOURCE_VALIDATED: **11**

NEEDS_QUERY_REVIEW: **1**

专项结果：

- qualification preserved: 12 / 12 attempts
- absolutization failures: 0
- region hallucination: 0
- effective-time hallucination: 0
- review: 1 `POLICY_SOURCE_CONTEXT_MISMATCH`

Review 来源是 Source section heading 与 fact region semantics 本身存在不协调，G0.3 没有现场修 Source Truth。

## 18. FAQ

Primary FAQ_PROCESS planned: **5**

SOURCE_VALIDATED: **5 / 5**

另外若干 FAQ coherent groups 以 `MULTI_FACT_SYNTHESIS` TaskPlan 存在。

FAQ primary query 均经过 deterministic naturalization；exact canonical question copy = 0。

## 19. Multi-fact

Planned: **42**

Rendered: 42

SOURCE_VALIDATED: **42 / 42**

- scope collapse: 0
- necessity preserved: 42 / 42
- average required facts: 2.67

Renderer 按同一 coherent topic 要求整个 bounded fact set，而不是只问其中一个 fact。

## 20. Multi-section

Planned: **13**

SOURCE_VALIDATED: **13 / 13**

逐 Case audit 均验证：

- explicit relation preserved
- >= 2 stable sections
- both sections necessary at construction contract level
- no category drift
- no mechanical “问题 A + 另外问题 B” fallback

G0.2 已经把第一版低置信 24 个 composition 收紧到 13 个；G0.3 没有为了数量重新扩回去。

## 21. Category Ownership

- Knowledge category preserved: 179 / 180
- Category drift: 1

FAQ 中关于订单/工单的**通用流程规则**仍属于 pure document knowledge，不因为出现“订单/工单”字样就自动判成 Private/Mixed；只有需要用户私有实体状态的 Query 才属于 category drift。

## 22. Cross-stage Collision

Query-level：

- Formal exact/normalized: 0
- Private category drift: 0
- Mixed query collision: 0
- Troubleshooting/category collision: 1

Plan-level frozen fact/evidence overlap仍由 G0.2 collision contract管理；G0.3不重新定义前一阶段的 plan-level ownership。

## 23. Candidate Dedup

SOURCE_VALIDATED 171 条：

- exact query duplicate excess: **0**
- normalized query duplicate excess: **0**
- semantic duplicate excess: **0**
- unique fact sets: **171**
- unique evidence sets: **161**
- unique query-intent signatures: **171**

早期 renderer 曾把不同 Compatibility / Multi-fact / Multi-section Plan collapse 成同一句 surface；最终版本已按 Task semantics 收紧，未把 wording variation 当 semantic diversity。

## 24. Renderer Collapse Audit

最终：

- Distinct validated TaskPlans: 171
- Effective Candidate semantics: 171
- Renderer semantic collapse: **0**

Effective / SOURCE_VALIDATED = 100%。

## 25. Effective Diversity

- Rendered: 180
- SOURCE_VALIDATED: **171**
- Effective Semantic Units: **171**
- Effective Ratio: **100%**
- Semantic Duplicate Excess: **0**

## 26. Document Coverage

G0.2 Plan: 22 / 22

G0.3 SOURCE_VALIDATED: **22 / 22**

没有为了保持 22/22 自动救回 review/reject；当前自然保留了全覆盖。

## 27. Product Coverage

G0.2 Plan: 20 / 20

G0.3 SOURCE_VALIDATED: **20 / 20**

## 28. Task Type Distribution

Validated 171：

- MULTI_FACT_SYNTHESIS: 42 (24.56%)
- FEATURE_OR_INSTRUCTION: 42 (24.56%)
- COMPATIBILITY: 17 (9.94%)
- DIRECT_FACT: 17 (9.94%)
- MULTI_SECTION_SYNTHESIS: 13 (7.60%)
- LIMITATION: 12 (7.02%)
- PRODUCT_SPEC: 12 (7.02%)
- POLICY_OR_WARRANTY: 11 (6.43%)
- FAQ_PROCESS: 5 (2.92%)

Feature 比例仍 < 25%。

## 29. Difficulty Distribution

G0.2 Plan：

- EASY 70
- MEDIUM 69
- HARD 41

Validated Candidate：

- EASY **66** (38.60%)
- MEDIUM **64** (37.43%)
- HARD **41** (23.98%)

Difficulty 沿用 frozen TaskPlan，没有根据 surface 长度修改。

## 30. Query Review Queue

总计：**8**

- `PLANNING_COMPATIBILITY_SEMANTICS_UNCERTAIN`: 3
- `LOW_VALUE_META_KNOWLEDGE_QUERY`: 2
- `HEADING_ONLY_FACT_QUERY_REVIEW`: 1
- `VAGUE_COMPATIBILITY_SCOPE_REVIEW`: 1
- `POLICY_SOURCE_CONTEXT_MISMATCH`: 1

这些只是 pre-candidate query review，不是 Human Reviewed Gold。

## 31. Rejected

总计：**1**

- `CATEGORY_DRIFT_TROUBLESHOOTING`: 1

TaskPlan：`KTP-06321e1fd45f44bd`

它的 surface 对应“洗碗机机器不启动”，属于 active troubleshooting，因此没有进入 Knowledge SOURCE_VALIDATED pool。

## 32. Candidate Manifest

- schema: `g0.3-knowledge-candidate-1`
- renderer: `controlled-knowledge-query-g0.3-v1`
- llm_used: false
- input TaskPlans: 180
- source validated: 171
- review: 8
- rejected: 1
- effective: 171
- max active candidate / plan: 1

Candidate Set Hash：

`c21d9412fc16be1f1b2d56a8e349641c3c1c9f3866e9eee358565890096dd1e5`

## 33. Reproducibility

独立 rerun 已由专项测试验证：

same G0.1 + same G0.2 -> same 180 attempts -> same query text -> same candidate IDs -> same status -> same Candidate Set Hash。

## 34. Artifacts

`artifacts/evaluation/dataset-expansion-g0-3-knowledge-rendering/`：

- knowledge_render_input.jsonl
- knowledge_render_results.jsonl
- knowledge_render_rejected.jsonl
- knowledge_query_review_queue.jsonl
- knowledge_raw_candidates.jsonl
- knowledge_source_validated.jsonl
- knowledge_candidate_manifest.json
- knowledge_rendering_pattern_report.json
- knowledge_query_naturalness_report.json
- knowledge_query_intent_alignment.json
- knowledge_query_scope_alignment.json
- knowledge_query_fact_alignment.json
- knowledge_query_evidence_alignment.json
- knowledge_query_leakage_report.json
- knowledge_query_policy_audit.json
- knowledge_query_multi_fact_audit.json
- knowledge_query_multi_section_audit.json
- knowledge_query_category_ownership.json
- knowledge_query_cross_stage_collision.json
- knowledge_candidate_dedup_report.json
- knowledge_candidate_effective_diversity.json
- knowledge_candidate_document_balance.json
- knowledge_candidate_product_balance.json
- knowledge_candidate_task_type_distribution.json
- knowledge_candidate_difficulty_distribution.json
- knowledge_candidate_reasoning_distribution.json
- knowledge_candidate_answer_scope_distribution.json
- phase_g0_3_summary.json

## 35. Code Changes

新增：

- `evals/benchmark/expansion/knowledge_candidate.py`
- `evals/benchmark/expansion/knowledge_query_renderer.py`
- `evals/benchmark/expansion/knowledge_query_validation.py`
- `evals/benchmark/expansion/knowledge_render_reporting.py`
- `evals/benchmark/expansion/g0_3_runner.py`
- `tests/evaluation/test_dataset_expansion_g0_3_knowledge_rendering.py`
- `docs/evaluation/DATA_EXPANSION_PHASE_G0_3_KNOWLEDGE_QUERY_RENDERING.md`

修改：

- `evals/benchmark/expansion/__init__.py`
- `eval_platform/cli.py`

统一 CLI：

```bash
python -m eval_platform.cli dataset-render-knowledge \
  --root . \
  --g0-2 artifacts/evaluation/dataset-expansion-g0-2-knowledge-planning \
  --g0-1 artifacts/evaluation/dataset-expansion-g0-1-knowledge-source \
  --output artifacts/evaluation/dataset-expansion-g0-3-knowledge-rendering
```

## 36. Tests

- G0.3 targeted: **22 passed**
- `tests/evaluation`: **365 passed, 2 skipped**
- primary repository `tests/` suite: **579 passed, 2 skipped**
- `python -m compileall -q .`: **PASS**

单独执行 repository-root `pytest` 会额外收集 `evals/tests/test_benchmark_integration.py`，当前容器仍缺既有 `langchain_core` integration dependency；这不是 G0.3 引入的回归。为保持与此前 Phase 一致的工程回归口径，主套件使用 `tests/`。

## 37. Formal Invariance

Formal Canonical：

- Development: 34
- Validation: 5
- Total: **39**

New Formal Cases: **0**。

Canonical files 与 G0.2 输入 byte-identical。

## 38. Production Diff / G0.4 Stable Inputs

Production behavior source diff：**0 changed files**。

测试/compileall 产生的 `__pycache__/*.pyc` 不属于行为源码，最终打包前清理。

G0.1 Source Space 与 G0.2 TaskPlan artifacts 均 byte-identical。

下一阶段稳定输入：

- `knowledge_source_validated.jsonl`
- `knowledge_query_review_queue.jsonl`
- `knowledge_render_rejected.jsonl`
- `knowledge_candidate_manifest.json`
- `knowledge_candidate_effective_diversity.json`
- `knowledge_query_fact_alignment.json`
- `knowledge_query_evidence_alignment.json`
- `knowledge_query_policy_audit.json`
- `knowledge_query_multi_fact_audit.json`
- `knowledge_query_multi_section_audit.json`
- `knowledge_query_cross_stage_collision.json`

当前建议：171 条 SOURCE_VALIDATED 已达到进入 **Knowledge Gold Preparation** 的规模与有效率条件；8 条 review 可单独进入未来 G0.3-R，但不需要为了追求 180/180 阻塞主线。下一阶段不应自动把 review/reject 补回 Candidate 数量。
