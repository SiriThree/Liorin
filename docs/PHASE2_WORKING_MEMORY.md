# Phase 2 — Liorin Working Memory Runtime

## 1. 结论

Phase 2 已在真实 `support_agent` 生命周期中加入 checkpoint-safe Working Memory。它不是聊天记录存储、向量记忆、长期记忆或独立 Memory Agent。

```text
Existing structured state
  → WorkingMemoryExtractor
  → Candidate
  → MemoryDelta / No-op Detection
  → WorkingMemoryPolicy
  → InMemoryWorkingMemoryLifecycleAdapter
  → IntermediateState.working_memory
  → LangGraph checkpoint
  → ContextBuilder
  → ContextItem(MEMORY)
  → Selector / Budget
  → supervisor dynamic_prompt
```

完整 MessagesState、Retrieval evidence、tool output 和 trace 继续由原系统保存；Working Memory 只保存当前任务状态。

## 2. 修改文件

新增：

```text
memory/__init__.py
memory/working/__init__.py
memory/working/models.py
memory/working/extractor.py
memory/working/updater.py
memory/working/serializer.py
evals/working_memory_benchmark.py
evals/benchmark/reports/working_memory_phase2_report.json
tests/memory/working/*
docs/PHASE2_WORKING_MEMORY.md
```

修改：

```text
agents/support_workflow.py
context_engine/builder.py
context_engine/selector.py
pyproject.toml
CHANGELOG.md
```

未修改 `conversation_supervisor.py`：Phase 1 已接入 `ContextRuntime`，本阶段通过 Builder 自动进入既有 dynamic prompt。

## 3. WorkingMemory 模型

位置：`memory/working/models.py`

```text
session_id
task_goal
current_intent
confirmed_facts
open_questions
constraints
decisions
failed_attempts
next_actions
last_updated
```

支持 `to_state()` / `from_state()`；仅输出 JSON-safe string、list 和 timezone-aware ISO datetime，可由 LangGraph checkpoint 恢复。

模型限制每类状态项数量和单项长度，避免 Working Memory 自身无限增长。这不是 Phase 4 Context Compaction。

## 4. 数据来源

`WorkingMemoryExtractor` 不调用 LLM，优先读取：

- `workflow_state`、`unresolved_slots`；
- `task_goal`、`current_intent`、`task_type`；
- customer/product/model/error/order/ticket 等结构化字段；
- requirements、covered/missing requirements；
- verification action、degraded reason、verification error；
- 显式 confirmed facts、constraints、decisions、next actions。

首次创建且没有结构化目标时，才使用最新用户消息作为 `task_goal`。不会总结全部历史。

明确不复制：

```text
完整 messages
candidate_documents
retrieval/evidence 正文
page_content / parent_context
tool output
trace / trace_events
```

## 5. 生命周期

### Candidate / Delta

Extractor 输出 Candidate 后，Phase 3.1 先计算语义 fingerprint 和 `MemoryUpdate`。只有 fingerprint 变化时才进入 Candidate lifecycle、Policy 和 Persist；相同状态直接 No-op，不产生 lifecycle record。

### Policy

`WorkingMemoryPolicy` 检查：

- 是否存在任务状态；
- 是否超过 Working Memory token 上限；
- 是否包含 page content、tool output、trace、candidate document 等污染标记。

输出 `POLICY_APPROVED` 或 `POLICY_REJECTED`。Extractor 不能直接写入。

### Persist / Update

当前没有 Memory Store，使用 `InMemoryWorkingMemoryLifecycleAdapter`。它保留进程内值和 lifecycle record；恢复的事实来源仍是 checkpoint：

```text
IntermediateState.session_id
IntermediateState.working_memory
IntermediateState.working_memory_lifecycle_records
```

真实变化的 Candidate/Policy/Persist records 会写入 graph state并携带 changed_fields、reason、fingerprint、additions/removals，最多保留 120 条。相同状态不会产生记录；120 条上限继续作为体积保护，而不再承担去重职责。

### Context Injection

`ContextBuilder` 将 checkpoint Working Memory 转为：

```text
ContextItemType.MEMORY
priority = 99
required = true
source = memory.working.checkpoint
```

并生成 `RETRIEVED` record，actor 为 `context_engine.builder`。读取事件附着在 ContextItem metadata 并保留在进程内 adapter，不改变持久状态 `PERSISTED`。

## 6. Runtime 接入

`IntermediateState` 新增：

```text
session_id
working_memory
working_memory_lifecycle_records
```

现有节点真实调用 Working Memory updater：

- `query_router`：创建/切换当前目标与意图；
- `verify_customer`：更新已确认身份、槽位和失败尝试；
- `collect_email`：更新槽位处理与下一步。

没有新增 Agent 或平行图。

Context priority：

```text
当前用户请求 100
Working Memory 99
Workflow State 96
Verified Evidence 91
旧历史消息 25-35
```

## 7. Checkpoint 恢复

测试构造 20 轮状态，持续更新 Working Memory 和 lifecycle records，然后执行 JSON checkpoint round-trip，并用新的 `WorkingMemoryUpdater` 恢复。

恢复后保留：

- 原任务目标；
- 已确认产品型号；
- 当前未解决问题；
- session_id。

当前容器没有真实 LangGraph 依赖，因此该测试验证的是实际 checkpoint state schema 与跨进程 adapter 恢复逻辑；真实 managed checkpoint 部署回归仍是已知限制。

## 8. 测试

```text
python -m pytest -q tests/memory/working tests/context_engine
22 passed

python -m pytest -q tests
146 passed

python -m pytest -q evals/tests/test_annotation_pipeline_integration.py
9 passed

python -m compileall -q memory context_engine agents evals tests
passed
```

覆盖：

- model round-trip；
- structured builder；
- Context Runtime injection；
- Candidate → Policy → Persist → Retrieved；
- 20 轮 checkpoint recovery；
- 不复制 messages/evidence/tool/trace；
- 隔离 stub 加载并执行真实 `support_workflow.query_router`。

全量 `python -m pytest -q` 仍会因当前环境缺少 `langchain_core` / `langgraph` 在 benchmark integration collection 阶段阻断，未标记为通过。

## 9. 50 轮 Benchmark

脚本：`evals/working_memory_benchmark.py`

报告：`evals/benchmark/reports/working_memory_phase2_report.json`

结果：

```text
turns                              50
context budget                     768
Before final prompt                12,980 estimated tokens
After final prompt                 724 estimated tokens
Before cumulative prompt           330,568
After cumulative prompt            36,186
Cumulative reduction               89.0534%
Before task-state completion       100%
After task-state completion        100%
Before information loss            0
After information loss             0
```

定义：

- Before：每轮重新注入完整消息历史；
- After：真实 Context Runtime budget + Working Memory + 当前轮消息；
- completion：当前目标、已确认事实和未解决槽位是否仍可用于决策；
- information loss：已引入但不再可用的必要事实/槽位数量。

该 benchmark 是确定性运行时状态评测，不调用模型，不代表真实回答正确率为 100%。

## 10. 兼容性与数据流

保留：Retrieval、Evidence Verification、source metadata、trace、Governance、Evaluation、Release Gate 和完整 MessagesState。

旧 checkpoint 没有 Working Memory 字段时，Builder 会忽略；下一次进入 query router 时创建 Working Memory，无数据库迁移。

## 11. 回滚

1. 删除 `IntermediateState` 的三个 Working Memory 字段；
2. 恢复三个 workflow 节点为原直接 update；
3. 删除 Builder 的 `_working_memory_items()`；
4. 恢复 Selector 顺序；
5. 删除 `memory/working/`、Phase 2 tests、benchmark、文档；
6. 从 wheel packages 删除 `memory`。

没有独立 Store 或数据库 schema migration。

## 12. 已知限制

- 没有 Conversation/Long-term/Artifact Memory；
- 完整 MessagesState checkpoint 仍增长；
- 没有 LLM fallback extractor；
- lifecycle adapter 是进程内实现；
- RETRIEVED 事件尚未进入企业审计库；
- 内部 session_id 尚未显式绑定 LangGraph thread_id；
- 规则抽取不能捕获自由文本中的全部隐含事实；
- 当前环境未执行真实 LangGraph deployment checkpoint 回归。

## 13. 下一阶段建议

Phase 3 应将 Evidence、Tool Result、File 和 Trace 引入 Artifact Memory，只向 Context Runtime 注入引用，不应扩大 Working Memory。

## 13. Pre-Phase 3 risk gates

The following risks are recorded in `docs/PHASE2_WORKING_MEMORY_RISKS.md` and are not claimed as implemented:

1. introduce a canonical `IdentityContext` covering tenant, user, conversation, LangGraph thread, and runtime session before cross-session or durable Memory injection;
2. introduce semantic `MemoryUpdate`/delta and no-op detection before durable persistence or an external audit sink;
3. introduce fact-level source, confidence, and verification before Working Memory facts can be promoted to Long-term Memory.

The current 120-record lifecycle cap is only a storage safety bound; it is not a substitute for delta-based idempotency. Current string `confirmed_facts` also must not be interpreted as uniformly verified facts.


## 13. Phase 3.1 Memory Delta 状态

Phase 2 风险 2 已在 `docs/PHASE3_1_MEMORY_DELTA.md` 完成：Working Memory 先执行 semantic fingerprint 和 No-op Detection；无变化时跳过 Policy、Persist 和 lifecycle，真实变化的 lifecycle attributes 携带可解释 Delta。
