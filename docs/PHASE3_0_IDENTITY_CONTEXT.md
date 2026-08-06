# Phase 3.0 — Liorin IdentityContext Foundation

> 本文记录真实 Liorin 仓库中的 Phase 3.0 实现结果。
>
> 本阶段只建立身份契约、解析、checkpoint 归属和 Context/Memory 元数据关联；不实现 Long-term Memory、Memory Store、User Profile、认证或权限系统。

## 1. 阶段结论

Phase 3.0 已将原先分散且语义不完整的 `session_id` 扩展为统一的 `IdentityContext`：

```text
Runtime / checkpoint state
        ↓
IdentityResolver
        ↓
IdentityContext
        ↓
IntermediateState.identity_context
        ├─ Working Memory lifecycle records
        ├─ ContextItem.metadata.identity_context
        └─ future SummaryMetadata.identity_context
```

真实运行接入点位于：

```text
agents/support_workflow.py
    query_router / verify_customer / collect_email
        ↓
    _with_working_memory
        ↓
    IdentityResolver.resolve
        ↓
    checkpoint update
```

因此 IdentityContext 不是孤立模型，也不是 Demo。它在每次顶层工作流更新 Working Memory 前被解析，并与 Working Memory 使用同一个 `session_id` 写入 LangGraph state。

---

## 2. Identity 模型设计

新增：

```text
identity/
├── __init__.py
├── models.py
└── resolver.py
```

### 2.1 IdentityContext

```python
IdentityContext(
    tenant_id: str,
    user_id: str,
    conversation_id: str,
    thread_id: str,
    session_id: str,
)
```

特性：

- frozen dataclass；
- 字段非空与长度校验；
- 禁止五个字段全部使用同一个值；
- `to_state()` / `from_state()`；
- 输出为纯字符串字典，可 JSON 序列化；
- 可直接进入 LangGraph checkpoint；
- `is_anonymous` 用于允许匿名用户在验证后升级为明确用户，但不会允许已建立的用户身份被静默替换。

### 2.2 字段语义

| 字段 | 语义 | 当前来源 |
|---|---|---|
| `tenant_id` | 数据和未来 Memory/Artifact 的租户隔离边界 | 显式 state、RetrievalPrincipal、runtime context；否则 `tenant:public` |
| `user_id` | 用户级 Memory 的所属主体 | 显式 user、RetrievalPrincipal、runtime/server identity、验证后的 customer；否则 `user:anonymous` |
| `conversation_id` | 业务会话标识 | 显式 state/runtime；否则从 thread 派生带 `conversation:` 前缀的独立标识 |
| `thread_id` | LangGraph checkpoint execution thread | `Runtime.execution_info.thread_id`、RunnableConfig、显式 state；最后才生成 fallback |
| `session_id` | Working Memory Runtime 生命周期 | 旧 Phase 2 session、显式 runtime session；否则从 thread 派生带 `session:` 前缀的独立标识 |

“统一”指所有组件从一个 IdentityContext 获取映射，不表示五个 ID 使用相同值。

---

## 3. IdentityResolver

`IdentityResolver` 是唯一身份解析入口，避免 Agent、ContextBuilder 和 Memory updater 各自拼装 ID。

### 3.1 解析来源

Resolver 支持：

1. 现有 checkpoint 中的 `identity_context`；
2. LangGraph `Runtime.execution_info.thread_id`；
3. 当前 RunnableConfig 的 `configurable.thread_id`；
4. Runtime context 中显式提供的 tenant/user/conversation/session；
5. LangGraph Server user identity；
6. Retrieval principal；
7. 旧 Phase 2 的 `session_id` 与 `working_memory.session_id`；
8. 已验证 `customer_id` 作为没有其他用户身份来源时的兼容映射。

### 3.2 冲突策略

为避免跨会话或跨租户注入，以下情况抛出 `IdentityResolutionError`：

- checkpoint `thread_id` 与当前 LangGraph thread 不同；
- 已建立 tenant 与新的非默认 tenant 冲突；
- 已建立的非匿名 user 与新的 user 冲突；
- conversation 或 session 与当前显式值冲突。

允许的受控升级：

- `tenant:public` → 明确 tenant；
- `user:anonymous` → 已认证 user 或验证后的 customer。

---

## 4. 接入位置

### 4.1 Support Workflow

`IntermediateState` 新增：

```python
identity_context: NotRequired[dict[str, str]]
```

`session_id` 暂时保留作为 Phase 2 checkpoint 兼容镜像，但其值由 `IdentityContext.session_id` 统一产生。

`_with_working_memory()` 现在执行：

```text
workflow updates
    ↓
IdentityResolver.resolve(candidate_state, runtime)
    ↓
identity_context + canonical session_id
    ↓
WorkingMemoryUpdater.update(... identity_context=...)
    ↓
checkpoint update
```

### 4.2 Context Runtime

`ContextItem.metadata` 现在正式支持：

```json
{
  "identity_context": {
    "tenant_id": "...",
    "user_id": "...",
    "conversation_id": "...",
    "thread_id": "...",
    "session_id": "..."
  }
}
```

`ContextBuilder` 只恢复 checkpoint 中已经存在的 IdentityContext，然后附加到本次生成的所有 ContextItem。它不会在 prompt 构造阶段创建新身份。

Identity 只作为 metadata 参与归属、审计和未来权限判断，当前不会把 tenant/user/thread 原文渲染进模型 prompt。

### 4.3 SummaryMetadata

`SummaryMetadata` 新增可选字段：

```python
identity_context: IdentityContext | None = None
```

兼容规则：

- 新 Summary 可以记录 tenant/user/conversation/thread/session 归属；
- 旧 Summary state 缺少 `identity_context` 时仍可读取；
- `to_state()` 在 identity 为空时不增加新 key，保持旧序列化形状；
- 缺少 identity 的旧 Summary 仍不能被视为完整的企业治理记录。

### 4.4 MemoryLifecycleRecord

`MemoryLifecycleRecord` 新增相同的可选 `identity_context`。

Phase 2 Working Memory 的以下事件现在携带身份：

- Candidate `CREATED/UPDATED`；
- Policy `UPDATED`；
- Persist `CREATED/UPDATED`；
- Context injection `RETRIEVED`。

旧 lifecycle record 没有 identity 时仍可恢复为 `identity_context=None`。

---

## 5. Checkpoint 变化

### 5.1 新 checkpoint 字段

```json
{
  "identity_context": {
    "tenant_id": "tenant-acme",
    "user_id": "user-42",
    "conversation_id": "conversation-900",
    "thread_id": "langgraph-thread-77",
    "session_id": "runtime-session-12"
  },
  "session_id": "runtime-session-12",
  "working_memory": {
    "session_id": "runtime-session-12"
  },
  "working_memory_lifecycle_records": [
    {
      "identity_context": {
        "tenant_id": "tenant-acme",
        "user_id": "user-42",
        "conversation_id": "conversation-900",
        "thread_id": "langgraph-thread-77",
        "session_id": "runtime-session-12"
      }
    }
  ]
}
```

必须保持：

```text
identity_context.session_id
    == state.session_id
    == working_memory.session_id
```

### 5.2 Phase 2 checkpoint 迁移

旧 checkpoint 不含 `identity_context` 时：

- 复用旧 `session_id`；
- 优先使用真实 LangGraph `thread_id`；
- 创建独立 conversation ID；
- tenant/user 暂时使用 public/anonymous，直到 Runtime 提供更明确身份；
- 生成后的 IdentityContext 写回 checkpoint，之后不再重复推导。

### 5.3 恢复验证

测试对完整 checkpoint payload 执行：

```text
Python models
    ↓ to_state
JSON dumps / loads
    ↓ from_state
IdentityContext + WorkingMemory
```

恢复后 identity、Working Memory session、任务目标和已确认事实保持一致。

---

## 6. 修改文件列表

### 新增

```text
identity/__init__.py
identity/models.py
identity/resolver.py
tests/identity/test_identity_context.py
docs/PHASE3_0_IDENTITY_CONTEXT.md
```

### 修改

```text
agents/support_workflow.py
context_engine/models.py
context_engine/builder.py
context_engine/__init__.py
memory/working/updater.py
memory/working/serializer.py
tests/memory/working/test_support_workflow_integration.py
pyproject.toml
docs/PHASE2_WORKING_MEMORY_RISKS.md
CHANGELOG.md
```

未修改：

```text
agents/conversation_supervisor.py
agents/knowledge_agent.py
agents/order_agent.py
retrieval/
governance/
evaluators/
deployments/
```

---

## 7. 测试结果

### 新增与相关回归

```text
python -m pytest -q tests/identity tests/context_engine tests/memory/working
29 passed
```

其中 identity 专项覆盖：

1. IdentityContext JSON-safe roundtrip；
2. 五字段语义区分；
3. Runtime thread/server user 解析；
4. 跨 thread checkpoint 冲突拒绝；
5. Phase 2 session 迁移；
6. 匿名 user 验证后升级；
7. checkpoint restore；
8. ContextItem/ContextBuilder identity metadata；
9. SummaryMetadata 新旧兼容；
10. MemoryLifecycleRecord 新旧兼容。

### 仓库测试

```text
python -m pytest -q tests
153 passed
```

### Annotation integration

```text
python -m pytest -q evals/tests/test_annotation_pipeline_integration.py
9 passed
```

### 编译检查

```text
python -m compileall -q identity context_engine memory agents tests/identity tests/memory/working
passed
```

### 全量 pytest

```text
python -m pytest -q
```

当前环境在 collection 阶段失败：

```text
ModuleNotFoundError: No module named 'langchain_core'
```

失败来自 `evals/tests/test_benchmark_integration.py` 的真实 LangChain 依赖未安装，不是 Identity 测试断言失败。本阶段没有把全量 pytest 伪报为通过。

---

## 8. 已知限制

1. IdentityContext 是身份归属契约，不是身份认证结果；当前不会验证 token、签名或登录会话。
2. 没有权限系统、ACL 决策或跨租户查询实现。
3. 没有 Long-term Memory、Memory Store、User Profile 或 Artifact Store。
4. 当 Runtime 不提供 tenant/user 时，会使用 `tenant:public` 和 `user:anonymous`；这些默认值不应获得私有 Memory 访问权。
5. `session_id` 当前默认与 checkpoint thread 生命周期映射，尚未使用独立 run ID 划分一次性执行 session。
6. IdentityContext 尚未显式传入 Supervisor 内部调用的 Order Agent/Knowledge Agent 输入；当前只在顶层 state、ContextItem 和 Working Memory lifecycle 中生效。
7. 旧 Summary/Lifecycle 没有 identity 时仍可读取，但不满足未来完整治理要求。
8. Resolver 只建立冲突检测，不提供身份合并、账户绑定或跨 conversation 关联服务。
9. 当前容器缺少真实 LangChain/LangGraph 依赖，尚未完成托管 LangGraph Server checkpoint 的端到端恢复测试。

---

## 9. 回滚

本阶段没有数据库或外部 Store 迁移。

回滚步骤：

1. 从 `IntermediateState` 和 `_with_working_memory` 移除 identity 解析与 checkpoint 字段；
2. 移除 ContextItem、SummaryMetadata、MemoryLifecycleRecord 的可选 identity 字段；
3. 恢复 WorkingMemory updater/serializer 原签名；
4. 从 wheel package 移除 `identity`；
5. 删除 `identity/`、identity tests 和本阶段文档。

已有 Phase 2 checkpoint 中多出的 `identity_context` 是附加字段；旧代码忽略该字段即可，不需要数据回写。

---

## 10. 下一阶段门禁

进入 Phase 3.1/Phase 3 后仍需完成：

- Memory Delta 与 no-op detection；
- lifecycle record 幂等与有效更新计数；
- identity 向子 Agent、Artifact 和 Evidence permission boundary 的传播；
- 对 anonymous/public identity 的注入限制；
- 在真实 LangGraph deployment 中验证 thread restore；
- Long-term Memory 前实现 `MemoryFact` source/confidence/verified 契约。
