# Phase 1 Hardening — Memory Lifecycle Hook Contract

## 1. 目的

在进入 Phase 2 前，为未来 Conversation/Long-term Memory 和企业治理预留稳定生命周期边界，避免后续形成：

```text
Extractor → Store
```

未来必须遵循：

```text
Memory Candidate
        ↓
Policy
        ↓
Persist
        ↓
Context Injection
```

本次改造只建立模型和 Hook Protocol，不实现 Memory Store、Extractor、Policy Engine、事件发布或自动注入。

## 2. 修改文件

```text
context_engine/models.py
context_engine/__init__.py
tests/context_engine/test_memory_lifecycle_contract.py
docs/PHASE1_CONTEXT_RUNTIME.md
docs/PHASE1_MEMORY_LIFECYCLE_HARDENING.md
CHANGELOG.md
```

Agent、Retrieval、Evidence、Governance、Evaluation 和部署业务代码均未修改。

## 3. 新增契约

### 3.1 MemoryLifecycleEvent

```text
CREATED
UPDATED
RETRIEVED
EXPIRED
DELETED
```

这是不可变审计事件词汇。`RETRIEVED` 表示读取/注入发生，不等同于 Memory 持久状态变化。

### 3.2 MemoryLifecycleState

```text
CANDIDATE
POLICY_APPROVED
POLICY_REJECTED
PERSISTED
EXPIRED
DELETED
```

Event 与 State 分离，防止将一次读取事件错误写成 Memory 当前状态。

### 3.3 MemoryMetadata

```text
id
created_at
updated_at
source
confidence
lifecycle_state
```

校验要求：

- id/source 非空；
- created_at/updated_at 必须带时区；
- updated_at 不得早于 created_at；
- confidence 必须位于 `[0, 1]`；
- lifecycle_state 使用稳定枚举值，并兼容小写输入；
- 支持 `to_state()` / `from_state()`。

### 3.4 MemoryLifecycleRecord

```text
event
memory
occurred_at
actor
reason
attributes
```

该记录携带事件发生时的 MemoryMetadata 快照，并回答：

- 谁写入或读取；
- 为什么发生；
- 何时发生；
- 当时处于什么生命周期状态；
- 可关联 request/tenant/policy/trace 等扩展属性。

### 3.5 MemoryLifecycleHook

`MemoryLifecycleHook` 是 callable Protocol：

```python
def __call__(record: MemoryLifecycleRecord) -> None:
    ...
```

它只定义边界，不提供默认 subscriber，不拥有持久化职责，也不会被现有 Agent Runtime 自动调用。

## 4. 未来调用关系

```text
Extractor
  → MemoryMetadata(state=CANDIDATE)
  → MemoryLifecycleRecord(event=CREATED)
  → Policy
      ├─ approve → UPDATED / POLICY_APPROVED
      └─ reject  → UPDATED / POLICY_REJECTED
  → Store adapter
      → UPDATED / PERSISTED
  → ContextBuilder retrieval adapter
      → RETRIEVED event
      → ContextItem(type=MEMORY or USER_PROFILE)
```

当前仓库仅允许 `MemoryMetadata` 作为 JSON-safe reference metadata 附着在未来 `ContextItem` 上，不进行自动检索或注入。

## 5. 测试结果

```text
python -m compileall -q context_engine tests/context_engine
passed

python -m pytest -q tests/context_engine/test_memory_lifecycle_contract.py
5 passed

python -m pytest -q tests/context_engine
15 passed

python -m pytest -q tests
139 passed

python -m pytest -q evals/tests/test_annotation_pipeline_integration.py
9 passed
```

全量：

```text
python -m pytest -q
```

仍在 collection 阶段被当前环境缺少 `langchain_core` 阻断：

```text
ModuleNotFoundError: No module named 'langchain_core'
```

没有将全量测试记为通过。

## 6. 已知限制

- 没有 Memory content schema；
- 没有 Memory Candidate producer；
- 没有 Policy 决策实现；
- 没有 Store、TTL、删除执行器或审计数据库；
- 没有 Hook dispatcher/subscriber；
- 没有与 ContextBuilder 的真实 Memory retrieval integration；
- 没有 tenant/ACL/PII 策略字段，未来由 Governance/Policy 层扩展；
- 生命周期记录当前只保证序列化与基础校验，不保证事件顺序一致性。

## 7. 回滚

1. 从 `context_engine/models.py` 删除生命周期枚举、模型和 Protocol；
2. 从 `context_engine/__init__.py` 删除对应导出；
3. 删除生命周期契约测试与本文档；
4. 恢复 Phase 1 主文档和 CHANGELOG。

本次没有数据库迁移、外部资源或持久数据，因此可直接代码回滚。

## 8. Phase 2 边界

Phase 2 可以使用这些类型描述 Working/Conversation Memory 的生命周期事件，但不应提前实现 Long-term Memory Store。任何未来持久化写入都必须经过 Candidate 和 Policy，不能由 Extractor 直接写入。
