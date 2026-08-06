# Phase 3.2 — Liorin Context Compaction Engine

> 本文记录真实 Liorin 仓库中的 Context Compaction Engine 实现。
>
> 本阶段只压缩 Supervisor 模型可见的临时 Context 视图，不删除或覆盖 LangGraph checkpoint、原始 messages、trace、evidence，也不实现 Long-term Memory、Memory Store、Artifact Store、User Profile 或 ACL。

## 1. 阶段结论

Phase 3.2 已将 Context Compaction 接入现有 Supervisor Runtime：

```text
LangGraph IntermediateState
  ├─ messages（原始历史，继续 checkpoint）
  ├─ working_memory（原样保留）
  ├─ identity_context
  ├─ workflow_state
  └─ evidence / artifact references
          ↓
ContextBuilder
          ↓
CompactionTrigger
  ├─ no  → ContextSelector
  └─ yes → ContextCompressor
              ↓
          CompactionValidator
              ↓
          CompactionReconstructor
              ↓
          ContextSelector
              ↓
ContextBudgetManager
          ↓
dynamic_prompt + 当前轮原生 messages
          ↓
Supervisor LLM
```

`agents/conversation_supervisor.py` 的 `dynamic_prompt` 和 model-call middleware 都创建同配置的 `ContextRuntime`，因此压缩结果真实进入 Supervisor 模型调用边界，不是孤立 compressor 文件。

## 2. 修改文件

### 新增

```text
context_engine/compaction/
├── __init__.py
├── models.py
├── trigger.py
├── compressor.py
├── validator.py
└── reconstructor.py

evals/context_compaction_benchmark.py

tests/context_engine/compaction/
├── __init__.py
├── test_context_compaction.py
└── test_context_compaction_benchmark.py

docs/PHASE3_2_CONTEXT_COMPACTION.md
```

### 修改

```text
context_engine/builder.py
context_engine/models.py
context_engine/__init__.py
agents/conversation_supervisor.py
config.py
.env.example
CHANGELOG.md
```

没有修改：

```text
agents/support_workflow.py
agents/knowledge_agent.py
agents/order_agent.py
retrieval/
governance/
evaluators/
deployments/
memory/working/
memory/delta/
identity/
```

## 3. Compaction Model

### 3.1 CompactionSummary

`CompactionSummary` 复用已有 `SummaryMetadata`，包含：

```text
summary_content
summary_metadata
identity_context
```

`summary_content` 强制包含五个结构化区段：

```text
task_progress
important_decisions
confirmed_information
pending_questions
failed_attempts
```

它不是普通聊天摘要，也不是 Memory。它只表达被压缩历史中已经发生的任务轨迹。

### 3.2 SummaryMetadata

每个压缩摘要都必须包含：

```text
source_range
  ├─ start_turn
  ├─ end_turn
  └─ source_item_ids
generated_by
confidence
created_at
original_token_cost
compressed_token_cost
identity_context
```

摘要缺少身份、来源范围或合法成本信息时不能通过 `CompactionValidator`。

### 3.3 JSON-safe

`CompactionSummary.to_state()` / `from_state()`、`SummaryMetadata.to_state()` / `from_state()` 均为 JSON-safe，可用于 debug、evaluation 和未来 checkpoint/store 设计。

本阶段不把摘要写入 checkpoint，因此没有新增持久化 schema 或数据库迁移。

## 4. 触发策略

`CompactionTrigger` 支持两种真实触发：

1. ContextItem 总 token cost 超过当前 `LIORIN_CONTEXT_MAX_TOKENS`；
2. ContextItem 数量超过配置阈值。

只有至少存在两个可压缩历史 item 时才会触发。

配置项：

```text
LIORIN_CONTEXT_COMPACTION_ENABLED=true
LIORIN_CONTEXT_COMPACTION_ITEM_THRESHOLD=24
LIORIN_CONTEXT_COMPACTION_RECENT_MESSAGES=6
LIORIN_CONTEXT_COMPACTION_SUMMARY_MAX_TOKENS=512
```

这些配置同时进入 `config.Context`，LangGraph Runtime 可按执行上下文覆盖，不依赖 compressor 内部硬编码。

触发结果以 `CompactionDecision` 进入 Context manifest：

```json
{
  "should_compact": true,
  "reason": "token_threshold_exceeded",
  "input_tokens": 12000,
  "item_count": 80,
  "compactable_item_count": 70,
  "token_threshold": 4096,
  "item_threshold": 24
}
```

## 5. 压缩对象与保护边界

### 5.1 允许压缩

- 旧 `USER_MESSAGE`；
- 旧 `ASSISTANT_MESSAGE`；
- 来自 `messages_state` 的历史 Tool observation；
- 经过 Builder 规范化后的重复历史项。

### 5.2 禁止压缩

- 当前用户请求；
- 当前轮 Tool/ReAct 轨迹；
- `ContextItemType.MEMORY` 的 Working Memory；
- `IdentityContext`；
- 当前 `WORKFLOW_STATE`；
- required Evidence Reference；
- 显式 Retrieval / Evidence / Artifact reference。

### 5.3 Recent Messages

默认保留最近 6 条历史 user/assistant ContextItem，不进入摘要。当前用户轮次始终通过原生消息通道进入模型。

### 5.4 Tool observation

历史 Tool observation 的完整内容不会写入摘要，也不会创建 Artifact 数据库。摘要仅记录工具观察数量和有限 source item ID placeholder。

原始 Tool message 仍留在 LangGraph messages/checkpoint 中。

## 6. Summary 生成

当前 compressor 是确定性结构化实现，没有每轮调用 LLM 对完整历史做总结。

生成过程：

```text
可压缩历史 ContextItems
        ↓
保留 recent messages
        ↓
旧消息按时间排序
        ↓
结构化规则提取
  ├─ task_progress
  ├─ important_decisions
  ├─ confirmed_information
  ├─ pending_questions
  └─ failed_attempts
        ↓
摘要 token 上限收缩
        ↓
SummaryMetadata
```

`generated_by` 当前为：

```text
context_engine.compaction.ContextCompressor/v1
```

默认 confidence 为 `0.8`，表示确定性规则生成且已通过结构与状态验证，但不等于人工审核或 LLM 语义事实验证。

## 7. Validation

`CompactionValidator` 在压缩前后比较 Working Memory 的规范化快照，包括：

```text
ContextItem id
Working Memory rendered content
source
session_id
identity_context
```

这覆盖 Working Memory 中的：

```text
task_goal
confirmed_facts
open_questions
decisions
constraints
failed_attempts
next_actions
```

还会验证：

- 前后 IdentityContext 完全一致；
- Summary 身份与 SummaryMetadata 身份一致；
- source item IDs 存在；
- `original_token_cost >= compressed_token_cost`；
- SummaryMetadata 可完整 round-trip。

关键状态缺失时抛出 `CompactionValidationError`。Runtime 捕获失败并回退到未压缩的 Selector/Budget 路径，因此压缩失败不会阻断客服请求。

## 8. Reconstruction

`CompactionReconstructor` 提供最小接口：

```text
CompactionSummary
        ↓
ContextItem(type=SUMMARY)
```

生成的 ContextItem 包含：

```text
source=context_engine.compaction
compaction_summary=true
summary_metadata_status=validated
eligible_for_compaction_metrics=true
identity_context
```

该接口用于：

- Supervisor prompt；
- debug；
- Context manifest；
- benchmark/evaluation。

它不负责恢复原始 messages；原始 history 本来就没有被删除。

## 9. Context 生命周期

### 9.1 原始状态

原始 `messages`、trace、evidence 和 checkpoint 继续由现有 LangGraph / Retrieval / Governance 链路保存。

### 9.2 临时压缩视图

每次 Supervisor model call：

1. Builder 从当前 state 构造 ContextItems；
2. Trigger 判断是否需要压缩；
3. Compressor 只替换临时 item 列表中的旧历史；
4. Validator 检查 Working Memory 和身份；
5. Selector/Budget 选择最终 Context；
6. Summary 进入 dynamic prompt；
7. 调用结束后，不写回或覆盖原始 state。

因此 Summary 生命周期是 model-call scoped，而不是 Long-term Memory 生命周期。

## 10. Identity 关联

Compaction 要求所有参与 ContextItems 只有一个一致 `IdentityContext`。

摘要和 metadata 同时携带：

```text
tenant_id
user_id
conversation_id
thread_id
session_id
```

以下情况拒绝压缩并回退：

- 没有 IdentityContext；
- Context 中出现多个身份；
- Summary 与 SummaryMetadata 身份不一致；
- 压缩后身份集合变化。

这为未来 Summary 存储和治理建立归属边界，但本阶段不实现跨 session 存储或 ACL。

## 11. Runtime Manifest

`ContextSelection.to_manifest()` 新增：

```text
runtime_metadata.compaction
```

成功时包括：

- trigger decision；
- compacted item IDs；
- preserved item count；
- source range；
- token before/after；
- compression ratio；
- identity；
- validation result；
- source history retained 标志。

失败时包括：

- failure reason；
- failure detail；
- fallback 未压缩标志。

manifest 是临时可观测数据，不写入 checkpoint。

## 12. Benchmark

执行：

```bash
python -m evals.context_compaction_benchmark
```

场景：

```text
5 条 trajectory
steps = 120 / 140 / 160 / 180 / 200
包含 user、assistant 和大体积 historical tool observation
Context budget = 1024
```

结果：

```text
Before ContextItems tokens              103,390
After Compaction、进入 Selector tokens     6,970
After Budget tokens                        4,530
Compaction token reduction               93.2585%
Working Memory preservation              100%
SummaryMetadata validity                 100%
Compaction success                       100%
Original history retention               100%
Generated summaries                      5
```

Benchmark 输出：

```text
evals/benchmark/reports/context_compaction_phase3_2_report.json
```

说明：

- token 使用 provider-neutral 估算；
- state preservation 是 Validator 的精确 Working Memory 比较；
- 不调用外部 LLM；
- 不代表真实回答正确率或摘要语义质量已经达到生产门槛。

Phase 2 与 Phase 3.1 benchmark 回归保持不变：

```text
Working Memory 累计 token 降幅  89.0534%
Working Memory 信息丢失          0
100 次重复 Memory update lifecycle records  0
```

## 13. 测试结果

### Compaction 专项

```text
python -m pytest -q tests/context_engine/compaction
7 passed
```

覆盖：

- token threshold trigger；
- SummaryMetadata 完整性与 JSON round-trip；
- Working Memory 原样保留；
- 关键状态丢失时 validation failure；
- ContextBuilder → Compactor → Selector/Budget 集成；
- Supervisor dynamic prompt 和 model-call middleware 真实接入；
- 120–200 step benchmark 门禁。

### Context / Memory / Identity 回归

```text
python -m pytest -q tests/context_engine tests/memory tests/identity
41 passed
```

### 仓库 tests

```text
python -m pytest -q tests/
165 passed
```

### Annotation integration

```text
python -m pytest -q evals/tests/test_annotation_pipeline_integration.py
9 passed
```

### 编译

```text
python -m compileall -q context_engine identity memory agents evals
passed
```

### 全量 pytest

```text
python -m pytest -q
```

当前环境在 collection 阶段被阻断：

```text
ModuleNotFoundError: No module named 'langchain_core'
```

失败来自 `evals/tests/test_benchmark_integration.py`。没有将全量测试标记为通过。

## 14. 已知限制

1. 当前摘要由确定性规则生成，不具备完整语义蕴含验证；
2. Summary 为 model-call scoped，不持久化，也没有增量 summary merge；
3. 没有 Artifact Store，历史 Tool observation 只能使用 source item ID placeholder；
4. token 估算不是 provider 精确 tokenizer；
5. ContextBuilder 在 dynamic prompt 和 model-call middleware 中各执行一次，长轨迹会重复计算压缩；
6. 未实现 Summary lifecycle event、TTL、删除、版本替换或跨 session 治理；
7. IdentityContext 是归属契约，不等于认证或 ACL；
8. 当前环境未完成真实 LangGraph Server / provider model 端到端压缩回归；
9. 原始 MessagesState checkpoint 仍持续增长，本阶段只解决模型可见 Context 增长；
10. 真实任务完成率与摘要语义保真仍需基于生产模型和人工 gold 评测。

## 15. 回滚

本阶段没有数据库或 checkpoint schema 迁移。

回滚步骤：

1. 从 `ContextRuntime.select()` 移除 Trigger/Compressor/Validator；
2. 恢复 Builder → Selector → Budget；
3. 从 Supervisor 删除 compaction 参数传播；
4. 删除 `context_engine/compaction/`；
5. 从 `config.Context`、`.env.example` 删除 compaction 配置；
6. 删除专项 benchmark、tests 和文档；
7. 保留原有 SummaryMetadata、IdentityContext、Working Memory 和 Memory Delta。

回滚后原始 checkpoint、messages、trace 和 evidence 不需要迁移。
