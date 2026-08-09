# Phase 4：Context / Memory Quality-Cost、Multi-turn Evaluation 与 Memory Contamination

## 1. Phase 4 Summary

### 阶段结论

**PARTIAL**

Phase 4 已在 Phase 0–3 的统一 `eval_platform` 上完成多轮 Session 契约、五类 Context Strategy 配置与真实 ContextRuntime wiring、Context/Memory/Artifact observability、Context Recall / Precision、Token Accounting、Working / Long-term Memory 诊断、Memory Contamination、Artifact 诊断、Session-level binary success、paired Quality-Cost aggregation、统一 CLI 与正式 artifact 输出。

没有创建新的 Context Evaluation Framework，没有复制五份 Agent，也没有重新定义 Phase 2 Task Success 或 Phase 3 Grounded Claim Rate。

当前阶段不能标记 COMPLETE 的原因有两个：

1. 当前执行环境无法导入 Production Support Graph：`ModuleNotFoundError: No module named 'langchain'`；真实 Context Relevance Judge 同样被该依赖阻塞。
2. 当前新增的 12 个 multi-turn candidate sessions 全部明确标记为 `MODEL_GENERATED_UNREVIEWED`，其中 9 个为 `NEEDS_REVIEW`、3 个为 `MISSING_CONTEXT_GOLD`，正式 `ELIGIBLE` session 数为 0。

因此以下正式质量/成本数字全部是 **NOT RUN**，不能用 fixture 或历史 component benchmark 代替：

- Context Strategy Token Reduction
- Turn / Session Task Success
- Grounded Claim Rate by strategy
- Context Recall / Context Precision by strategy
- Memory Contamination Rate by strategy
- Quality-Cost paired comparison

### 核心不变量

```text
(session_id, strategy)
        ↓
independent experiment stream
        ↓
ONE USER TURN
→ ONE Production Invocation
→ ONE Trace
→ ONE PredictionRecord
        ↓
Task / Grounding / Context / Memory / Artifact Evaluation
```

不同 strategy 是显式实验组；同一个 `(session, strategy, turn)` 内不存在为统计 Context 而隐藏执行第二次 Agent。

---

## 2. Multi-turn Evaluation Architecture

Phase 4 继续扩展 Phase 1 的 Canonical Evaluation 数据体系，新增 `CanonicalEvaluationSession`，没有创建平行 Benchmark。

```text
CanonicalEvaluationSession
│
├── initial_identity
├── initial_context
├── SessionTaskSuccessContract
│
└── turns[]
    │
    ├── CanonicalEvaluationTurn
    │   ├── user_input
    │   ├── runtime_input_delta
    │   ├── ExpectedBehavior
    │   ├── TaskSuccessContract
    │   ├── GoldEvidence / GoldFact / SafetyConstraint
    │   ├── RequiredContextUnit[]
    │   ├── MemoryExpectation
    │   └── ArtifactExpectation
    │
    ├── to existing EvaluationSample
    │       │ Gold Isolation
    │       ▼
    │   RuntimeCaseInput
    │       ↓
    │   ProductionEvaluationAdapter
    │       ↓
    │   ONE Production invocation
    │       ↓
    │   PredictionRecord schema 4.0
    │
    ├── Phase 2 TaskSuccessEvaluator
    ├── Phase 3 Evidence / Claim Grounding
    └── Phase 4 Context / Memory / Artifact diagnostics
            ↓
      SessionTaskSuccessContract
            ↓
      binary Session-level PASS / FAIL / INCOMPLETE / EXECUTION_ERROR
```

Production multi-turn continuity 使用同一个真实 deployment graph 的 top-level checkpointer；Specialist agent 的现有 behavior 不为 Evaluation 重写。

---

## 3. Session Schema

核心代码：

```text
eval_platform/context_memory.py
```

### `CanonicalEvaluationSession`

核心字段：

```text
session_id
schema_version = 1.0
split
category
subcategory
difficulty
tags
initial_identity
initial_context
turns[]
session_success_contract
annotation_metadata
source_metadata
```

### `CanonicalEvaluationTurn`

核心字段：

```text
turn_id
turn_index
user_input
runtime_input_delta
expected_behavior
task_success_contract
gold_evidence
gold_facts
safety_constraints
required_context_units
memory_expectations
artifact_expectations
state_updates
annotation_status
```

支持稳定 JSON / JSONL round-trip，并通过 canonical normalized JSON 计算 SHA-256 dataset hash。

当前 Phase 4 candidate dataset hash：

```text
0fc7b243e0013423787702d3576bb2836b6fe39d17bc4739390d0cd0ac527fea
```

---

## 4. Session / Turn Task Success

### Turn-level

每一个 Turn 继续直接复用 Phase 2：

```text
PredictionRecord + Canonical Gold
→ CriterionJudgment[]
→ TaskSuccessEvaluator
→ PASS / FAIL / INCOMPLETE / EXECUTION_ERROR
```

没有 Phase 4 专属的 `memory_answer_accuracy` 或 `context_success_score`。

### Session-level

新增 `SessionTaskSuccessContract`，支持：

```text
required_terminal_task_success
required_turn_ids
require_no_safety_violation
require_no_memory_contamination
```

Session success 不是 turn score 平均值。

例如一个 4-turn troubleshooting session 可以允许前几轮合法 Clarification，最终 terminal task 满足 contract 才判 session PASS。

---

## 5. Dataset Eligibility

正式状态：

```text
ELIGIBLE
NEEDS_REVIEW
MISSING_CONTEXT_GOLD
MISSING_MEMORY_GOLD
MISSING_TASK_GOLD
UNSUPPORTED_STRATEGY
OBSERVABILITY_INSUFFICIENT
INVALID
```

`validate_sessions()` 默认显式产生 eligibility，不 silently skip。

对于正式 Quality-Cost 实验，当前要求 session annotation 真实达到 `HUMAN_REVIEWED` 且必要 Context / Memory / Task Gold 完整。

当前 candidate dataset **不满足正式 metrics eligibility**。

---

## 6. Context Strategy Definitions

核心代码：

```text
context_engine/strategy.py
```

强类型：

```text
ContextEvaluationStrategy
ContextStrategyConfig
```

支持五组：

### FULL_HISTORY — READY

```text
compaction_enabled = false
selector_enabled = false
working_memory_enabled = false
long_term_memory_enabled = false
artifact_enabled = false
```

语义：不做 conversation history selection / compaction 的完整原始对话 baseline；Retrieval、Tool、Verifier、Governance、Recovery 仍走相同 Production 行为。

修复了一个实验真实性细节：在 `artifact_enabled=false` 时，历史 Tool Result 不再因为 Artifact offload 逻辑被截断成 placeholder，FULL_HISTORY 确实保留历史 Tool payload。

### SLIDING_WINDOW — READY

```text
same as FULL_HISTORY
+ history_policy = last N user turns
```

默认 `window_turns=3`，进入 `ContextStrategyConfig`、runtime metadata 和 config fingerprint，不是隐藏常量。

### SUMMARY_ONLY — READY / PARTIAL

```text
compaction_enabled = true
compaction_recent_messages = 0
selector_enabled = false
working_memory_enabled = false
long_term_memory_enabled = false
artifact_enabled = false
```

复用现有 `ContextCompactor / Validator / Reconstructor`，没有为 Benchmark 写新 Summary Prompt。

当前真实 compaction validator 会 fail closed；对非常短、压缩后反而更昂贵或 metadata 不合法的 history，可能保留原 history 并记录 compaction failure。这是现有 Production 语义，不为实验强行绕过。因此策略 wiring READY，但“每个输入都必定得到 compacted summary”并不成立。

### LIORIN_CONTEXT — READY

```text
compaction_enabled = true
selector_enabled = true
working_memory_enabled = true
long_term_memory_enabled = false
artifact_enabled = false
```

复用真实 Context Runtime / Selector / Budget / Compaction / Working Memory；关闭长期 Memory 与 Artifact reuse。

### LIORIN_CONTEXT_MEMORY_ARTIFACT / LIORIN_FULL — READY as config, formal run NOT RUN

```text
compaction_enabled = true
selector_enabled = true
working_memory_enabled = true
long_term_memory_enabled = true
artifact_enabled = true
```

这是当前默认 Production Context policy，不创建 Evaluation-only Memory 或 Artifact implementation。

---

## 7. Strategy Wiring

策略不是五份 Agent，而是同一个：

```text
ProductionEvaluationAdapter
        ↓
deployments.support_agent_graph.build_graph(...)
        ↓
Support Workflow
        ↓
conversation_supervisor
        ↓
ContextRuntime
        ↓
ContextStrategyConfig
```

`config.Context` 新增：

```text
context_strategy
context_sliding_window_turns
```

默认仍是：

```text
LIORIN_CONTEXT_MEMORY_ARTIFACT
```

因此不提供 Evaluation config 时，现有 Production 默认行为保持不变。

`ProductionEvaluationAdapter.for_context_strategy()` 使用同一个 deployment graph builder，并打开 top-level checkpointer 来支持多轮 session stream。

---

## 8. Experiment Fairness Protocol

`check_strategy_fairness()` 冻结允许变化的字段仅限 Context / Memory / Artifact policy。

同一 session 的不同策略必须共享：

```text
same dataset/session/user turns
same model config
same embedding
same retriever / reranker
same verifier
same agents/tools
same identity/governance
same business data
same recovery config
same temperature / other production config
```

Phase 4 runner 固定：

```text
agentic_recovery_enabled = true
```

不会把 `FULL_HISTORY + recovery off` 与 `LIORIN_FULL + recovery on` 比较。

Run metadata 保存：

```text
strategy_config
strategy_config_hash
dataset_hash
common_production_config_hash
agentic_recovery_fixed = true
single_execution_per_session_strategy_turn = true
git_commit = null  # 当前 ZIP checkout 无 .git，未伪造
```

---

## 9. Context Observability Audit

### Matrix

| Field | Status | Actual source |
|---|---|---|
| context build id | AVAILABLE | `CONTEXT_ASSEMBLED.context_build_id` |
| model call id | AVAILABLE | `MODEL_CALL.model_call_id` |
| items before / after selection | AVAILABLE / derived | ContextRuntime candidate + final item trace |
| ContextItem stable identity | AVAILABLE | `ContextItem.stable_id` + source refs |
| type / source / ref | AVAILABLE | context item trace |
| selected / dropped / truncated | AVAILABLE | context assembly trace |
| drop reason | AVAILABLE | context trace metadata |
| item estimated tokens | AVAILABLE | ContextItem token cost |
| final/model input token count | PARTIAL | provider actual when available; otherwise estimator |
| summary id / source range | AVAILABLE when compaction succeeds | existing SummaryMetadata |
| summary facts retained/lost | PARTIAL | requires Gold / semantic comparison; not fully intrinsic in Production trace |
| memory fact ids | AVAILABLE / PARTIAL | long-term fact id + stable working-memory fact refs |
| memory origin identity | AVAILABLE | traced origin identity metadata |
| artifact refs | AVAILABLE | Artifact reference metadata |
| artifact origin identity | AVAILABLE | traced Artifact identity context |
| retrieval evidence refs | AVAILABLE | Phase 3 trace facts |
| tool result refs | PARTIAL | Phase 3 structured observability carry-over |
| causal memory influence on answer | PARTIAL | selected-into-context observable; counterfactual causality is not claimed |

所有 Phase 4 formal context metrics 都从 frozen Trace / Prediction 读取，不触发第二次 Agent。

---

## 10. ContextItem Identity

继续复用真实 `ContextItem` identity，并把 Evaluation 需要的 lineage 写入 trace：

```text
context_item_id / stable_id
source_type
source_ref
context_build_id
selected
drop_reason
memory_kind
fact_id
artifact_id
summary_metadata
origin_identity_context
working_memory_fact_refs
```

不使用 list index 作为正式 identity。

Working Memory 中原本没有逐条 persisted fact id 的结构化字段，因此 Phase 4 对可评测字段生成 deterministic SHA-256 stable refs，例如：

```text
wmfact:confirmed_fact:<hash>
wmfact:constraint:<hash>
wmfact:decision:<hash>
wmfact:open_question:<hash>
```

它们只用于 tracing/evaluation identity，不改变 Working Memory state 或 policy。

---

## 11. RequiredContextUnit

新增：

```text
RequiredContextUnit
```

类型包括：

```text
USER_FACT
ENTITY
SLOT
DECISION
OPEN_QUESTION
CONSTRAINT
PREVIOUS_TOOL_RESULT_REF
PREVIOUS_EVIDENCE_REF
MEMORY_FACT
ARTIFACT_REF
```

它描述：

> 当前 Turn 的相关 decision/model input 做对任务真正需要哪些历史/状态单元。

它不等于“所有历史消息”，也不会进入 Production Runtime。

---

## 12. Context Recall

正式定义：

```text
required context units actually selected into
final task-relevant model context
/
all required context units
```

Phase 4 最小正式评估位置冻结为：

```text
final observed ContextRuntime selection
associated with the turn's Production model path
```

MemoryFact 仅存在于 Store、但 Selector 没选进当前 Context，不算 Recall 命中。

输出保留：

```text
numerator
denominator
rate
missing_required_units
```

真实策略指标当前 **NOT RUN**，因为无正式 eligible multi-turn sessions 且 Production blocked。

---

## 13. Context Precision

正式 denominator 只覆盖 selectable context：

```text
historical
memory
artifact
retrieval/tool-derived selectable items
```

不把 mandatory system/safety/tool schema 当 irrelevant noise。

分类：

```text
REQUIRED
HELPFUL
IRRELEVANT
HARMFUL
NOT_EVALUATED
```

正式 Precision：

```text
REQUIRED + HELPFUL
/
all evaluated selectable context items
```

一个 context item 不在 Gold 中时不会自动变成 IRRELEVANT；无法 deterministic 判断时保持 `NOT_EVALUATED`。

Phase 4 在已有 `JudgeRuntime` 中新增版本化：

```text
context_relevance_v1
```

并增加 `phase4_context_relevance_calibration_v1.json`，覆盖 REQUIRED / HELPFUL / IRRELEVANT / HARMFUL。Calibration fixtures 明确是 `carefully_constructed_fixture` 且 `human_reviewed=false`，不是正式 benchmark 数据。

当前 real Judge blocked，因此 semantic Context Precision 完整结果 **NOT RUN**。

---

## 14. Token Accounting

新增明确来源：

```text
PROVIDER_ACTUAL
TOKENIZER_ESTIMATE
HEURISTIC_ESTIMATE
UNKNOWN
```

`conversation_supervisor` 在真实 Model response 出现：

```text
usage_metadata.input_tokens
usage_metadata.prompt_tokens
response_metadata.*
```

时记录：

```text
PROVIDER_ACTUAL
```

否则使用当前 Context selection estimate，并明确：

```text
HEURISTIC_ESTIMATE
```

不会把 estimator 冒充 API actual token。

### Turn Input Tokens

定义为：

```text
该 Turn 所有 Production LLM MODEL_CALL input token 总和
```

不是只测最终 Answer call。

### 聚合支持

```text
Avg Input Tokens
Median Input Tokens
P95 Input Tokens
Max Input Tokens
Total Input Tokens
Avg Model Calls
P95 Model Calls
Total Session Input Tokens
Avg Tokens / Session
P95 Tokens / Session
```

当前正式 Production 数字 **NOT RUN**。

---

## 15. Actual vs Estimated Tokens

`TraceAdapter` 把每次 `MODEL_CALL` 的：

```text
model_call_id
context_build_id
input_tokens
output_tokens
token_count_source
message_count
strategy
```

投影到 Prediction schema 4.0。

正式报告可以按 source 分拆 token usage，避免把 heuristic 和 provider actual 混在一起。

历史 `production_benchmark.py` 的 estimator 继续可以作为 engineering diagnostic，但不会出现在 Phase 4 正式 Quality-Cost 首页。

---

## 16. Working Memory Evaluation

重新扫描实际 `WorkingMemory` 后，Evaluation 使用真实字段体系，而不是旧文档假设。

Phase 4 对 selected Working / Long-term Memory context 计算：

### Working Memory Recall

```text
required working-memory facts selected into context
/
all required working-memory facts
```

### Working Memory Precision

```text
allowed/required selected memory facts
/
all selected memory facts
```

`memory_diagnostics.jsonl` 保存：

```text
memory_dependent
working_memory_recall
working_memory_precision
required_fact_ids
selected_fact_ids
unexpected_fact_ids
```

所以“不为空”不再等于“Memory 质量好”。

---

## 17. Long-term Memory Evaluation

Long-term Memory evaluation 复用真实 `MemoryFact` stable fact id / IdentityContext scope，并关注：

```text
required fact retrieved/selected
wrong fact filtered
TTL/stale handling
identity scope
```

当前可以从 Context Trace 看到已选中的 long-term fact ID 与 origin identity。

Phase 4 没有创建 Evaluation-only memory store，也没有把“写入成功”作为长期记忆质量指标。

完整正式 cross-session benefit 仍需要 reviewed/eligible multi-turn session，当前 **NOT RUN**。

---

## 18. Fact Supersession

`MemoryExpectation` 支持：

```text
superseded_fact_ids
stale_fact_ids
active_entity_refs
```

例如：

```text
FR-100
↓ user correction
FR-200
```

后续 Turn 如果 selected context 仍使用 superseded FR-100，可记录：

```text
SUPERSEDED_FACT_USED
```

如果旧 fact 只存在于 Store 但未选入 model context，则不算 contamination。

当前 candidate sessions 包含 `USER_CORRECTION / FACT_SUPERSESSION / STALE_MEMORY_RESISTANCE` 场景，但均未 human review，因此只用于 contract/pipeline testing。

---

## 19. Memory Contamination

正式建立：

```text
MemoryContaminationEvent
```

事件类型：

```text
STALE_FACT_USED
SUPERSEDED_FACT_USED
WRONG_ENTITY_FACT_USED
CROSS_SESSION_FACT_USED
CROSS_USER_FACT_USED
CROSS_TENANT_FACT_USED
UNSUPPORTED_MEMORY_FACT_USED
IRRELEVANT_MEMORY_INFLUENCED_ANSWER
```

正式核心语义：

> stale/wrong fact 必须被 selected into current model context（或后续有影响证据）才构成 contamination；仅仅 Store 里存在旧数据不算。

### Memory Contamination Rate

```text
memory-dependent evaluable turns
with >=1 harmful contamination event
/
all evaluable memory-dependent turns
```

同时报告 event count/type distribution。

当前正式 rate **NOT RUN**。

---

## 20. Stale Memory

Phase 4 优先支持可可靠 Gold 的：

```text
STALE_BY_USER_CORRECTION
STALE_BY_ENTITY_SWITCH
```

通过 `stale_fact_ids / superseded_fact_ids / active_entity_refs` 表达。

Time/policy staleness 如果 dataset 没有独立有效期 Gold，不自动推断，应该继续 `NEEDS_REVIEW`。

---

## 21. Cross-session / Cross-user Isolation

### Cross-session

Working Memory 可以配置：

```text
disallow_cross_session_working_memory = true
```

如果 origin `session_id` 与当前 Session 不一致并被选中，产生：

```text
CROSS_SESSION_FACT_USED
```

Long-term Memory 是否允许跨 session 则仍由真实 memory/governance policy 决定，不统一禁止。

### Cross-user / Cross-tenant

如果 selected MemoryFact origin identity 与当前不同：

```text
CROSS_USER_FACT_USED
CROSS_TENANT_FACT_USED
```

事件同时：

```text
safety_violation = true
```

不会只记成普通 Context Precision FAIL。

当前 candidate dataset 有 cross-session / cross-user / cross-tenant scenarios，但因缺正式 Context Gold / Review 仍不进入 formal metrics。

---

## 22. Artifact Evaluation

`ArtifactExpectation` 支持：

```text
required_artifact_ids
required_source_refs
identity_scoped
```

`ArtifactDiagnostic` 可以区分：

```text
CORRECT_REUSE
MISSING
WRONG_ARTIFACT
WRONG_IDENTITY
CONTENT_INSUFFICIENT
NOT_SELECTED
NOT_EVALUATED
```

Trace 中会记录 Artifact ID、source ref、origin identity、selected status。

Artifact `resolve(id)` 成功不等于 Task Success；正式 evaluator 要求正确 Artifact 真正进入 task context，并满足 identity scope。

### Artifact Token Saving

artifact row 中保留 estimator diagnostic，但**正式 token saving 只能通过相同 session 的 Strategy paired model input tokens 比较**：

```text
FULL_HISTORY actual/estimated Production tokens
vs
LIORIN_FULL actual/estimated Production tokens
```

不会用 raw bytes - artifact ID 长度冒充正式节省。

---

## 23. Summary / Compaction Quality

继续复用现有：

```text
ContextCompactor
ContextCompactionValidator
ContextReconstructor
SummaryMetadata
```

Trace 可看到：

```text
summary_metadata
source_range
generated_by
created_at
original/compressed cost
tokens_saved
validation status
```

Phase 4 没有重写 Summary Prompt。

### 当前支持程度

- summary identity/source range：AVAILABLE when compaction succeeds
- validator / reconstruction metadata：AVAILABLE/PARTIAL
- required fact retained：可通过 RequiredContextUnit/Gold diagnostic
- summary hallucination：需要独立 source-vs-summary semantic evaluation；real Judge blocked，formal NOT RUN

Failure taxonomy 已预留：

```text
SUMMARY_LOST_REQUIRED_FACT
SUMMARY_INTRODUCED_FALSE_FACT
SUMMARY_STALE_AFTER_UPDATE
```

---

## 24. Context Failure Attribution

`ContextFailureReason` 当前覆盖：

```text
CONTEXT_REQUIRED_FACT_DROPPED
SUMMARY_LOST_REQUIRED_FACT
SUMMARY_INTRODUCED_FALSE_FACT
SUMMARY_STALE_AFTER_UPDATE
MEMORY_NOT_WRITTEN
MEMORY_NOT_RETRIEVED
MEMORY_NOT_SELECTED
MEMORY_STALE
MEMORY_CONTAMINATION
MEMORY_POLICY_BLOCKED
ARTIFACT_NOT_REGISTERED
ARTIFACT_NOT_RESOLVED
ARTIFACT_WRONG_IDENTITY
ARTIFACT_CONTENT_INSUFFICIENT
ARTIFACT_CONTEXT_NOT_SELECTED
ENTITY_CONTEXT_LOST
CONTEXT_BUDGET_EXHAUSTED
OVER_CONTEXT_FAILURE
```

这些是 Phase 5 全局 Failure Taxonomy 的 Context/Memory 子集，不替代 Task Success。

---

## 25. Quality-Cost Comparison

每个 Strategy summary 同时支持：

```text
Eligible Sessions
Eligible Turns
Avg / Median / P95 / Max Input Tokens
Avg / P95 Model Calls
Turn Task Success
Session Task Success
Grounded Claim Rate
Context Recall
Context Precision
Memory Contamination Rate
Execution Error Rate
```

Task Success 与 Grounded Claim Rate 分别复用 Phase 2 / Phase 3，不创建新的 quality score。

### 相对 FULL_HISTORY

paired subset 上计算：

```text
Token Reduction
= (Full avg tokens - Strategy avg tokens) / Full avg tokens

Task Success Delta
= Strategy success - Full success
# percentage points

Grounded Claim Rate Delta
= Strategy grounded rate - Full grounded rate
# percentage points
```

不生成 `quality_cost_score`。

---

## 26. Pairwise Strategy Results

只有相同 session ID、两个 strategy 都执行且没有 execution error 的 pair 进入直接 cost comparison。

每个 session 分类：

```text
BOTH_PASS
FULL_PASS_STRATEGY_FAIL
FULL_FAIL_STRATEGY_PASS
BOTH_FAIL
```

Execution Error 不会 silent drop；Strategy-level Execution Error Rate 单独报告，避免 survivor bias。

当前正式 paired results：**NOT RUN**。

原因：0 formal eligible sessions + Production dependency blocked。

---

## 27. Artifact / Report Format

正式 Phase 4 artifact writer 已实现：

```text
context_strategy_summary.json
context_strategy_summary.md
context_turn_diagnostics.jsonl
context_session_diagnostics.jsonl
memory_diagnostics.jsonl
memory_contamination.jsonl
artifact_diagnostics.jsonl
quality_cost_summary.json
quality_cost_summary.md
context_experiment_run.json
```

其中 `memory_diagnostics.jsonl` 保存 Working Memory quality numerator/denominator/fact ids，而不是只保存“有几个 memory item”。

Prediction schema 升级为：

```text
4.0
```

新增 Context Snapshot / MODEL_CALL / token-source trace facts；旧 Prediction 仍可反序列化，不会 silent 改旧 JSON 的解释。

Evaluation artifacts 保存 stable ref / identity metadata，不为了 debug 把私有 Artifact payload 全文复制到 report。

---

## 28. Dataset Counts

生成资产：

```text
evals/benchmark/data/canonical/phase4_multi_turn_candidates_v1.json
evals/benchmark/data/canonical/phase4_multi_turn_inventory.json
evals/benchmark/data/canonical/phase4_multi_turn_manifest.json
```

可复现脚本：

```text
evals/scripts/build_phase4_multi_turn_assets.py
```

真实统计：

```text
candidate sessions     12
turns                  29
avg turns/session       2.4167
eligible sessions       0
NEEDS_REVIEW            9
MISSING_CONTEXT_GOLD    3
```

Category：

```text
KNOWLEDGE_QA                  5
TROUBLESHOOTING               3
MIXED_KNOWLEDGE_STRUCTURED    1
SAFETY_GOVERNANCE             3
```

主要 tags：

```text
ENTITY_CARRY_OVER              2
WORKING_MEMORY_REUSE           2
FACT_SUPERSESSION              2
STALE_MEMORY_RESISTANCE        2
SLOT_CARRY_OVER                1
FOLLOW_UP_QUERY                1
TOPIC_SWITCH                   1
RETURN_TO_PREVIOUS_TOPIC       1
PRIVATE_IDENTITY_CONTINUITY    1
LONG_TERM_MEMORY_REUSE         1
ARTIFACT_REUSE                 1
PRONOUN_REFERENCE              1
CROSS_SESSION_ISOLATION        1
CROSS_USER_ISOLATION           1
CROSS_TENANT_ISOLATION         1
STRUCTURED_PLUS_DOCUMENT       1
IRRELEVANT_OLD_CONTEXT         1
OVER_CONTEXT                   1
```

Annotation truth：

```text
MODEL_GENERATED_UNREVIEWED
formal_metric_eligible = false
```

没有伪造 `HUMAN_REVIEWED`。

---

## 29. Tests

### Evaluation suite

```bash
PYTHONPATH=. pytest -q tests/evaluation
```

真实结果：

```text
118 passed in 0.70s
```

### Combined required regression

```bash
PYTHONPATH=. pytest -q \
  tests/evaluation \
  tests/context_engine \
  tests/memory \
  tests/artifact \
  tests/production \
  tests/governance
```

真实最终结果：

```text
199 passed in 1.81s
```

第一次跨目录 combined run 暴露一个 test-order isolation 问题：`MemoryMetricsRegistry` 是 process-global，旧测试在同一 pytest process 中会继承前一个测试的 stale counter，导致 `stale_memory_block_count` 从预期 1 变成 2。Production 本身需要 global metrics，因此没有修改 Production runtime；新增 `tests/conftest.py` 在**测试边界** reset default Memory metrics，使跨 suite regression 可重复。修复后上面的 199/199 全部通过。

### Compile

```bash
PYTHONPATH=. python -m compileall -q .
```

结果：

```text
PASS
```

### Unified CLI pipeline audit

```bash
PYTHONPATH=. python -m eval_platform.cli experiment context \
  --dataset evals/benchmark/data/canonical/phase4_multi_turn_candidates_v1.json \
  --strategies FULL_HISTORY,LIORIN_CONTEXT_MEMORY_ARTIFACT \
  --output <dir>
```

结果：CLI `EXIT=0`，正确返回 12 个 ineligible candidate session、`result_count=0`；没有因为无 eligible session 而偷偷调用 Production，也没有生成正式质量指标。

测试 PASS 只说明代码/契约/aggregation/wiring regression，不是 Agent quality score。

---

## 30. Actual Results

### 正式数据准备度

```text
Candidate sessions    12
Formal eligible        0
Formal executed        0
```

### 正式 Quality-Cost 结果

```text
Token Reduction                  NOT RUN
Turn Task Success                NOT RUN
Session Task Success             NOT RUN
Grounded Claim Rate              NOT RUN
Context Recall                   NOT RUN
Context Precision                NOT RUN
Memory Contamination Rate        NOT RUN
Artifact token saving            NOT RUN
FULL vs LIORIN paired delta      NOT RUN
```

Fixture/unit-test 数字不进入本节。

---

## 31. Production Status

Phase 4 重新执行实际 Production import：

```bash
PYTHONPATH=. python -c "import deployments.support_agent_graph"
```

真实异常：

```text
agents/knowledge_agent.py
from langchain.chat_models import init_chat_model

ModuleNotFoundError: No module named 'langchain'
```

因此：

```text
Real Support Graph import       BLOCKED
One-session Production smoke    BLOCKED
Paired strategy smoke           NOT RUN
Development strategy run        NOT RUN
Validation strategy run         NOT RUN
```

另尝试：

```bash
uv sync --offline
```

真实失败：

```text
agentevals>=0.0.9 was not found in the local cache
network disabled
```

没有改用 Mock Production 后声称真实 strategy smoke PASS。

---

## 32. Judge Status

Phase 4 复用 Phase 2 `JudgeRuntime`，新增：

```text
context_relevance_v1
```

真实 provider dependency 重新检查：

```text
ModuleNotFoundError: No module named 'langchain'
```

因此：

```text
Real Context Relevance Judge          BLOCKED / NOT RUN
Context relevance calibration quality NOT RUN
Summary hallucination semantic judge  NOT RUN
Artifact content relevance judge      NOT RUN
```

Stub / controlled fixtures 只证明 structured schema、parser 和 infrastructure，不是 LLM quality metric。

---

## 33. Blocked / NOT RUN

### BLOCKED

```text
Production Support Graph dependency
Real Judge dependency
```

### NOT RUN

```text
all formal strategy quality metrics
all formal Production token metrics
all formal pairwise strategy results
all formal Memory contamination rates
all formal Context relevance semantic metrics
```

### 原因不是被隐藏的测试失败

核心 Evaluation / Context / Memory / Artifact / Production / Governance regression 已 199/199 PASS。

---

## 34. Remaining Review Debt

当前 Multi-turn benchmark 最大缺口是 Gold，而不是代码数量。

```text
candidate sessions             12
eligible                       0
needs human review             9
missing context gold           3
missing audited memory gold    present in isolation candidates
missing supersession review    candidate annotations only
```

下一步正式跑 Context Strategy Comparison 前，需要至少：

1. 独立 review candidate sessions；
2. 补齐 `RequiredContextUnit`；
3. 对 memory-dependent turns 标明 required/allowed/superseded/stale fact refs；
4. 对 Artifact reuse case 标注 required artifact/source refs；
5. 明确 session terminal success contract；
6. 不从 Production prediction 反推 Gold。

少量 reviewed exploratory sessions 比自动生成 100 个虚假 benchmark 更可信。

---

## 35. Phase 5 Stable Interfaces

Phase 5 可以直接依赖：

### Strategy / runtime

```text
ContextEvaluationStrategy
ContextStrategyConfig
ContextRuntime strategy wiring
ProductionEvaluationAdapter.for_context_strategy(...)
ContextStrategyExperimentRunner
```

### Multi-turn Canonical

```text
CanonicalEvaluationSession
CanonicalEvaluationTurn
SessionTaskSuccessContract
SessionEligibility
RequiredContextUnit
MemoryExpectation
ArtifactExpectation
```

### Observability

```text
context_build_id
model_call_id
context item stable refs
selected/dropped/truncated context trace
summary metadata
memory fact / working-memory stable refs
artifact refs/origin identity
MODEL_CALL token_count_source
PredictionRecord schema 4.0
```

### Evaluators

```text
evaluate_context_turn()
evaluate_working_memory()
evaluate_memory_contamination()
evaluate_artifacts()
evaluate_session_success()
```

### Aggregation

```text
aggregate_context_strategy()
paired_quality_cost()
quality_cost_frontier()
write_phase4_artifacts()
```

### Stable semantic invariants

```text
Task Success remains Phase-2 North Star
Grounded Claim Rate remains Phase-3 definition
Correctness != Grounding
Observability Failure != Retrieval Failure
Stale fact stored != Memory contamination
Cross-user/tenant memory contamination is also Safety violation
Quality and Cost remain separate axes
No weighted Quality-Cost score
Per (session,strategy,turn): ONE Production invocation
```

这些接口可以直接作为 Phase 5 全局 Failure Attribution / Safety / Regression Gate 的 Context-Memory 输入，不需要重新设计 Task Success 或 Context Strategy data model。

---

# Appendix A：本阶段主要代码修改

### 新增

```text
context_engine/strategy.py

eval_platform/context_memory.py
eval_platform/multi_turn_seed.py

evals/scripts/build_phase4_multi_turn_assets.py

evals/benchmark/configs/phase4_context_experiment.example.json

evals/benchmark/data/canonical/phase4_multi_turn_candidates_v1.json
evals/benchmark/data/canonical/phase4_multi_turn_inventory.json
evals/benchmark/data/canonical/phase4_multi_turn_manifest.json

evals/benchmark/data/calibration/phase4_context_relevance_calibration_v1.json

tests/evaluation/test_phase4_context_strategies.py
tests/evaluation/test_phase4_session_contract.py
tests/evaluation/test_phase4_context_metrics.py
tests/evaluation/test_phase4_artifact_quality_cost.py
tests/evaluation/test_phase4_fairness_and_runner.py
tests/evaluation/test_phase4_judge_and_prediction_schema.py
tests/evaluation/test_phase4_cli.py

tests/conftest.py
```

### 修改

```text
config.py
.env.example

context_engine/__init__.py
context_engine/builder.py

agents/conversation_supervisor.py

deployments/support_agent_graph.py

eval_platform/__init__.py
eval_platform/production_adapter.py
eval_platform/judge.py
eval_platform/runner.py
eval_platform/cli.py
```

没有为 Phase 4 修改：

```text
Retriever ranking algorithm
Verifier decision policy
Agent Prompt content
Memory extraction policy
Memory governance policy
Artifact governance policy
```

---

# Appendix B：Legacy -95.2% Status

历史：

```text
1,520,001 → 72,972
Token reduction ≈ 95.2%
```

当前正式状态：

```text
LEGACY_COMPONENT_DIAGNOSTIC
NOT A PHASE-4 FORMAL QUALITY-COST RESULT
```

原因：它没有在同一批正式 multi-turn sessions、同一模型/检索/业务逻辑、不同 Context strategy 的 paired Production executions 上重新测量 Task Success + Groundedness + actual/estimated token cost。

Phase 4 不删除这些工程 benchmark，但它们只能进入 diagnostics / legacy appendix。

---

# Appendix C：Carry-over Production Gaps

## Structured Evidence / Order Agent

Phase 3 已建立 `execute_sql_template` 的 structured Tool Result → Evidence trace projection；但实际 `agents/order_agent.py` 仍注册 fail-closed legacy `execute_sql`，并没有把安全 template tool 真实接入 Order Agent。

Phase 4 遵守阶段边界，没有为了 Context experiment 重构该 Production business wiring。

状态：

```text
CARRY_OVER_PRODUCTION_GAP
```

涉及 Mixed/private structured multi-turn session 时，如果该 wiring 阻止真实 structured trace，应标 `OBSERVABILITY_INSUFFICIENT / PRODUCTION_WIRING_BLOCKED`，不能由 evaluator 再查询数据库补数据。

## Git metadata

当前交付来自 ZIP checkout，没有 `.git` history，因此 run metadata 的 `git_commit` 保持 `null`，未伪造 commit hash。

---

# Phase 5 Entry Readiness

代码层的 Phase 4 contracts、wiring、diagnostics 和 regression 已经具备 Phase 5 依赖条件；但正式 Phase 4 experiment 仍受以下条件阻塞：

```text
[✓] Canonical Multi-turn Session Contract
[✓] Turn-level Task Success reuses Phase 2
[✓] Session-level binary Task Success Contract
[✓] Context Strategy Enum / Config
[✓] FULL_HISTORY wiring
[✓] SLIDING_WINDOW wiring
[✓] SUMMARY_ONLY real compactor wiring (fail-closed semantics preserved)
[✓] LIORIN_CONTEXT wiring
[✓] LIORIN_CONTEXT_MEMORY_ARTIFACT wiring
[✓] Strategy fairness checker
[✓] Context observability audit
[✓] stable Context item identity
[✓] RequiredContextUnit
[✓] Context Recall evaluator
[✓] Context Precision contract/evaluator
[✓] token actual-vs-estimate labeling
[✓] Avg/P95/session token aggregation
[✓] Working Memory evaluator
[✓] Supersession evaluator/diagnostic
[✓] Memory Contamination evaluator
[✓] Cross-session / cross-user / cross-tenant memory checks
[✓] Artifact diagnostic
[✓] Quality-Cost aggregation/report
[✓] Task Success remains North Star
[✓] Grounded Claim Rate reuses Phase 3
[✓] Gold Isolation regression
[✓] per-(session,strategy,turn) Single Execution contract regression
[ ] Reviewed / formally eligible multi-turn sessions
[ ] Real Production dependencies available
[ ] Real Context Judge available
[ ] Formal Context Strategy run executed
```

因此 Phase 4 总体结论保持 **PARTIAL**，而不是为了“阶段完成”强行写 COMPLETE。
