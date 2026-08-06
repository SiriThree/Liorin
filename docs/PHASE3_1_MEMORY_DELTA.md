# Phase 3.1 — Liorin Memory Delta Runtime

> 本文记录真实 Liorin 仓库中的 Phase 3.1 实现结果。
>
> 本阶段只实现 Working Memory 的语义 Delta、Fingerprint、No-op Detection 和 lifecycle 审计关联；不实现 Memory Store、Long-term Memory、Conversation Memory、User Profile 或权限系统。

## 1. 阶段结论

Phase 3.1 已将 Working Memory 更新语义从“调用 updater 就更新”改为“只有结构化任务状态实际变化才更新”。

真实运行链路：

```text
Existing workflow/checkpoint state
        ↓
WorkingMemoryExtractor
        ↓
WorkingMemory Candidate
        ↓
MemoryDeltaDetector
        ├─ semantic fingerprint equal
        │      ↓
        │   No-op
        │   - skip Policy
        │   - skip lifecycle adapter
        │   - emit no lifecycle record
        │   - return previous WorkingMemory
        │
        └─ semantic fingerprint changed
               ↓
           WorkingMemoryPolicy
               ↓
           Lifecycle Adapter Persist
               ↓
           LangGraph checkpoint update
```

`agents/support_workflow.py` 仍是实际接入点，没有新增 Agent 或平行 Runtime。

---

## 2. 修改文件

### 新增

```text
memory/delta/__init__.py
memory/delta/models.py
memory/delta/detector.py
tests/memory/delta/__init__.py
tests/memory/delta/test_memory_delta.py
tests/memory/delta/test_memory_delta_benchmark.py
evals/memory_delta_benchmark.py
evals/benchmark/reports/memory_delta_phase3_1_report.json
docs/PHASE3_1_MEMORY_DELTA.md
```

### 修改

```text
memory/__init__.py
memory/working/updater.py
agents/support_workflow.py
evals/working_memory_benchmark.py
tests/memory/working/test_working_memory_runtime.py
tests/memory/working/test_support_workflow_integration.py
docs/PHASE2_WORKING_MEMORY.md
docs/PHASE2_WORKING_MEMORY_RISKS.md
CHANGELOG.md
```

未修改 Retrieval、Evidence、Governance、deployment graph 或长期记忆接口。

---

## 3. Delta 模型

位置：`memory/delta/models.py`

```python
MemoryUpdate(
    changed_fields,
    reason,
    previous_fingerprint,
    candidate_fingerprint,
    additions,
    removals,
)
```

### 3.1 字段语义

- `changed_fields`：发生语义变化的 WorkingMemory 字段；
- `reason`：调用方提供的业务原因，例如“customer provided model number”；
- `previous_fingerprint`：旧语义状态的 SHA-256；
- `candidate_fingerprint`：候选语义状态的 SHA-256；
- `additions`：按字段记录新加入的状态值；
- `removals`：按字段记录被移除的状态值。

支持：

```python
to_state()
from_state()
is_noop
```

输出只包含 string、list 和 dict，可安全写入 lifecycle attributes 或 JSON 日志。

### 3.2 模型约束

- fingerprint 必须是 64 位 SHA-256 十六进制字符串；
- fingerprint 相同则 `changed_fields` 必须为空；
- fingerprint 不同则必须至少存在一个 `changed_field`；
- additions/removals 只能引用 `changed_fields`；
- reason 不能为空。

---

## 4. Fingerprint 策略

位置：`memory/delta/detector.py`

参与 fingerprint 的字段：

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
```

明确排除：

```text
last_updated
```

原因：时间戳只是 updater 调用时间，不是任务状态变化。若包含 `last_updated`，每次调用都会产生不同 fingerprint，No-op Detection 将失效。

集合类字段经过：

```text
去重 → 排序 → canonical JSON → SHA-256
```

因此仅顺序变化但内容相同，不会产生无意义更新。标量字段保持规范化后的原值。

空旧状态使用空 canonical payload 的稳定 fingerprint；首次创建仍会产生真实 Delta。

---

## 5. No-op 流程

`WorkingMemoryUpdater.update()` 当前顺序：

```text
Extract Candidate
    ↓
Detect Delta
    ↓
if previous exists and delta.is_noop:
    return previous memory
    policy = None
    persisted = false
    lifecycle_records = []
else:
    evaluate policy
    persist/update
```

无变化时保证：

1. 不运行 `WorkingMemoryPolicy`；
2. 不调用 `InMemoryWorkingMemoryLifecycleAdapter.persist()`；
3. 不产生 Candidate / Policy / Persist lifecycle record；
4. 不更新 `last_updated`；
5. 返回原 WorkingMemory；
6. `support_workflow` 不把 `working_memory` 或 `working_memory_lifecycle_records` 放入该次 checkpoint partial update。

IdentityContext、workflow state 等现有业务字段仍按原图逻辑更新；No-op 只阻止无意义的 Working Memory 持久化。

---

## 6. Lifecycle 变化

真实变化时，Candidate、Policy 和 Persist 三类记录的 `attributes` 均附带：

```json
{
  "changed_fields": ["confirmed_facts"],
  "reason": "customer provided model number",
  "previous_fingerprint": "...",
  "candidate_fingerprint": "...",
  "additions": {
    "confirmed_facts": ["product_model=LF-900"]
  },
  "removals": {}
}
```

因此未来审计系统能够回答：

- 哪些字段改变；
- 为什么改变；
- 旧状态和新状态是否可唯一关联；
- 增加或移除了哪些状态值。

无变化时不写 lifecycle record。Lifecycle 表达状态变化，而不是函数调用次数。

IdentityContext 继续附着在每条真实 lifecycle record 上，没有破坏 Phase 3.0 身份归属。

---

## 7. Checkpoint 兼容

Phase 3.1 没有给 WorkingMemory checkpoint 增加必填 Delta 字段。

旧 Phase 2/3.0 checkpoint 仍保持：

```json
{
  "session_id": "...",
  "identity_context": {},
  "working_memory": {},
  "working_memory_lifecycle_records": []
}
```

恢复流程：

```text
legacy working_memory state
    ↓ WorkingMemory.from_state
previous WorkingMemory
    ↓ extractor + MemoryDeltaDetector
new candidate / no-op
```

新 lifecycle record 只是在既有 `attributes` 中增加 Delta 数据；旧 record 缺少这些 attributes 时仍由现有 `MemoryLifecycleRecord.from_state()` 读取。

没有数据库迁移，也没有 Memory Store schema。

---

## 8. Runtime 接入证明

`agents/support_workflow.py::_with_working_memory()` 仍调用真实 `WorkingMemoryUpdater`。

更新后：

```text
result.records_to_state() 为空
    → 不写 working_memory_lifecycle_records

result.persisted == false
    → 不写 working_memory
```

集成测试加载真实 `agents/support_workflow.py`，连续两次执行相同 `query_router` 状态：

- 第一次生成 Working Memory 和三条 lifecycle record；
- 第二次保持同一语义状态；
- 第二次 Command update 不包含 `working_memory`；
- 第二次 Command update 不包含 `working_memory_lifecycle_records`。

因此 No-op 不是孤立工具函数，而是进入真实图节点的 checkpoint partial update 路径。

---

## 9. 测试结果

### 9.1 Delta + Working Memory + Context + Identity

```text
python -m pytest -q \
  tests/memory/delta \
  tests/memory/working \
  tests/context_engine \
  tests/identity

34 passed
```

覆盖：

- 字段变化检测；
- additions/removals；
- timestamp-only No-op；
- No-op 跳过 Policy/Persist/lifecycle；
- JSON-safe round-trip；
- Phase 2 checkpoint 恢复；
- lifecycle Delta attributes；
- 真实 support workflow 重复调用；
- 原 Working Memory、Context Runtime、IdentityContext 回归。

### 9.2 仓库 tests

```text
python -m pytest -q tests
158 passed
```

### 9.3 Annotation integration

```text
python -m pytest -q evals/tests/test_annotation_pipeline_integration.py
9 passed
```

### 9.4 编译

```text
python -m compileall -q memory context_engine identity agents evals tests
passed
```

### 9.5 全量 pytest

```text
python -m pytest -q
```

当前执行环境仍在 benchmark integration 收集阶段失败：

```text
ModuleNotFoundError: No module named 'langchain_core'
```

失败文件：

```text
evals/tests/test_benchmark_integration.py
```

未将全量测试标记为通过。

---

## 10. 100 次重复更新 Benchmark

脚本：

```text
evals/memory_delta_benchmark.py
```

报告：

```text
evals/benchmark/reports/memory_delta_phase3_1_report.json
```

场景：

1. 先创建一份有效 Working Memory；
2. 将完全相同的结构化状态连续处理 100 次；
3. 再执行一次真实字段变化，验证正常持久化没有退化。

结果：

```text
重复调用次数                              100
Phase 2 估算 lifecycle records            300
Phase 3.1 实际 lifecycle records           0
Phase 2 估算 persisted updates             100
Phase 3.1 实际 persisted updates            0
检测到 No-op                               100
重复更新 lifecycle 降幅                    100%
最终真实变化 persisted                     true
最终真实变化 lifecycle records              3
最终真实变化字段                            confirmed_facts,
                                            open_questions,
                                            next_actions
```

Phase 2 估算按照原流程每次调用产生 Candidate + Policy + Persist 三条记录。该 benchmark 是确定性 Runtime 行为评测，不调用外部模型。

---

## 11. Working Memory 功能保持

Phase 2 的 50 轮 benchmark 已适配 No-op 为正常结果：

- Policy 明确拒绝仍会报错；
- 无语义变化不再被错误视为 Policy failure；
- Working Memory 状态、Context 注入和信息保真逻辑不变。

仓库测试和原 Working Memory benchmark 均通过，证明已有功能未下降。

---

## 12. 已知限制

- Fingerprint 当前只覆盖 WorkingMemory，不覆盖未来 Conversation/Artifact/Long-term Memory；
- 集合字段按 set-like 语义处理，不能表达相同值的重复次数；
- Delta 没有单独持久化为 checkpoint 顶层对象，只进入真实 lifecycle record attributes；
- No-op 调用不会生成审计事件，这是有意设计；未来如需调用级 telemetry，应使用独立 metric/trace，而不是 Memory lifecycle；
- lifecycle adapter 仍是进程内实现，checkpoint state 仍是恢复事实来源；
- 当前环境缺少真实 LangChain/LangGraph，未完成 managed checkpoint 部署端到端回归；
- `MemoryFact` 的 source/confidence/verified 仍未实现，不能将 Working Memory 事实直接提升为 Long-term Memory。

---

## 13. 回滚

1. 删除 `memory/delta/`；
2. 将 `WorkingMemoryUpdater` 恢复为 Extractor → Policy → Adapter；
3. 移除 lifecycle Delta attributes；
4. 恢复 `_with_working_memory()` 每次写回 Working Memory/lifecycle records 的旧逻辑；
5. 恢复 Phase 2 benchmark 对每轮 `persisted=true` 的要求；
6. 删除 Delta tests、benchmark、报告和本文档。

没有数据库或持久化 schema migration。旧 checkpoint 不包含必需的 Delta 字段，因此可直接回滚；但回滚后重复 lifecycle 噪声会恢复。
