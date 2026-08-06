# Phase 4 — Liorin Artifact Memory System

> 本文记录真实 Liorin 仓库中的 Artifact Memory 实现。
>
> 本阶段管理 Agent 已产生的中间产物，不实现 Long-term Memory、User Profile、ACL、新 Retrieval 系统或独立 Agent。原始 LangGraph messages、KnowledgeState evidence、trace 与 checkpoint 均继续保留。

## 1. 阶段结论

Phase 4 已把 Artifact Memory 接入现有 Context Runtime，而不是只新增一个孤立目录。

真实 Supervisor Tool Result 链路：

```text
Supervisor 调用 order_agent / knowledge_agent
        ↓
LangChain 生成 ToolMessage（完整返回仍保留在 MessagesState）
        ↓
conversation_supervisor model-call middleware
        ↓
ContextRuntime
        ↓
ContextBuilder
        ↓
ArtifactRegistry.create_artifact
  ├─ 完整 Tool payload → InMemoryArtifactStore
  ├─ IdentityContext 绑定
  └─ CREATED / AVAILABLE / REFERENCED lifecycle
        ↓
ContextItem(type=ARTIFACT_REFERENCE)
        ↓
bounded_model_messages 将当前 ToolMessage 内容替换为短引用
        ↓
Supervisor LLM
```

KnowledgeState Evidence 进入统一 ContextBuilder 时：

```text
verified_evidences / evidences / retrieval_response.evidences
        ↓
现有 Evidence descriptor 与 provenance 保留
        ↓
完整 Evidence payload → RETRIEVAL_EVIDENCE Artifact
        ↓
ContextItem(type=EVIDENCE_REFERENCE)
  ├─ citation/source/security/score metadata
  └─ artifact_id + short summary
```

因此：

- 完整 Tool Result 不再通过 Supervisor 的当前轮原生 Tool message 进入模型；
- 完整 Evidence payload 不进入 ContextItem；
- Context 仍保留引用、来源、验证状态和必要 metadata；
- Lazy Resolver 可以在同一身份边界内恢复原始 payload；
- 原始 state 没有被删除或覆盖。

## 2. 修改文件

### 新增

```text
artifact/
├── __init__.py
├── models.py
├── store.py
├── registry.py
└── resolver.py

evals/artifact_context_benchmark.py

tests/artifact/
├── test_artifact_runtime.py
└── test_artifact_benchmark.py

docs/PHASE4_ARTIFACT_MEMORY.md
```

### 修改

```text
context_engine/builder.py
context_engine/compaction/compressor.py
context_engine/__init__.py
pyproject.toml
CHANGELOG.md
```

没有修改：

```text
agents/
retrieval/
governance/
evaluators/
deployments/
memory/
identity/
```

`conversation_supervisor.py` 无需再次修改：Phase 1/3.2 已经让其 dynamic prompt 与 model-call middleware 调用 `ContextRuntime`；本阶段通过扩展 `ContextBuilder` 和 `bounded_model_messages` 的既有路径自动生效。

## 3. Artifact 模型

### 3.1 Artifact 与 Memory 的边界

```text
Artifact
= 已产生的工具结果、证据 payload、文档、报告、trace 或 summary

Memory
= 当前任务状态或未来需要保留的事实
```

Artifact 不会写入 WorkingMemory 的：

- confirmed_facts；
- decisions；
- open_questions；
- next_actions。

Working Memory 也不会持有 Artifact 完整 payload。

### 3.2 Artifact 字段

`artifact/models.py` 定义：

```text
artifact_id
artifact_type
identity_context
source
created_at
created_by
summary
metadata
location
size
status
payload
```

`payload` 是 Store 所有的完整中间产物。它是为最小 in-memory 实现增加的运行字段，不会出现在 `Artifact.to_reference()` 中。

### 3.3 ArtifactType

至少支持：

```text
RETRIEVAL_EVIDENCE
TOOL_RESULT
DOCUMENT
REPORT
TRACE
SUMMARY
```

类型不绑定具体客服业务，未来报告生成器、文件处理器或 trace export 可以复用同一 Registry。

### 3.4 JSON-safe

以下结构支持 JSON-safe 序列化：

```text
Artifact.to_state() / from_state()
Artifact.to_reference()
ArtifactLifecycleRecord.to_state() / from_state()
```

LangChain `Document` 类 payload 会被规范化为：

```json
{
  "page_content": "...",
  "metadata": {}
}
```

本阶段不把完整 Artifact 写入 LangGraph checkpoint。

## 4. Artifact Store 与 Registry

### 4.1 统一 Store 接口

`ArtifactStore` Protocol 提供：

```text
create_artifact()
get_artifact()
delete_artifact()
list_artifacts()
```

内部另提供 `update_artifact()`，供 Registry 更新 lifecycle state。

### 4.2 InMemoryArtifactStore

当前最小实现为进程内、线程安全 Store：

```text
InMemoryArtifactStore
  ├─ RLock
  ├─ artifact_id → Artifact
  └─ exact IdentityContext ownership check
```

删除时：

- payload 被移除；
- size 归零；
- status 变为 `DELETED`；
- metadata tombstone 暂时保留，以便审计删除事件。

### 4.3 ArtifactRegistry

Registry 负责：

- 生成或接收 artifact_id；
- payload fingerprint；
- 幂等创建；
- lifecycle 记录；
- reference / delete；
- process-local 默认 Registry。

Tool Result 和 Evidence Artifact ID 基于以下输入确定性生成：

```text
artifact_type
IdentityContext
source key
payload fingerprint
```

同一 payload 在 dynamic prompt 与 model-call middleware 中被重复观察时，不会创建两个 Artifact。不同 payload 不允许复用同一 artifact_id。

## 5. Identity 绑定

Artifact 创建必须提供完整 `IdentityContext`：

```text
tenant_id
user_id
conversation_id
thread_id
session_id
```

Store 的 get、delete、list 以及 Resolver 的 resolve 都要求调用方提供身份。

当前最小实现采用 exact identity matching：

```text
artifact.identity_context == requester.identity_context
```

因此不同 tenant、user、conversation、thread 或 session 均不能读取同一 Artifact。

无 IdentityContext 时：

- ContextBuilder 不创建 Artifact；
- 旧无身份上下文继续使用有限 placeholder，以保持旧测试/旧状态兼容；
- 不会产生“公共无主 Artifact”。

这只是所有权契约，不等同于认证或 ACL。

## 6. Artifact 生命周期

### 6.1 State

```text
CREATED
AVAILABLE
REFERENCED
ARCHIVED
DELETED
```

### 6.2 Event

为了区分持久状态和读取动作，另定义：

```text
CREATED
AVAILABLE
REFERENCED
RESOLVED
ARCHIVED
DELETED
```

`RESOLVED` 是读取事件，不需要成为持久状态。

### 6.3 Lifecycle Record

每条记录包含：

```text
artifact_id
event
identity_context
actor
reason
timestamp
metadata
```

当前真实记录点：

| 操作 | actor 示例 | reason 示例 |
|---|---|---|
| create | `context_engine.builder` | artifact metadata and payload registered |
| available | `context_engine.builder` | artifact is available for lazy resolution |
| reference | `context_engine.builder` | replace tool result payload with Artifact Reference |
| resolve | `artifact.resolver` | lazy load artifact payload |
| delete | 调用组件 | 业务提供的删除原因 |

生命周期记录当前由 process-local Registry 保存，尚未进入企业审计数据库。

## 7. Context Runtime 变化

### 7.1 Tool Result

Phase 3.2 前，Builder 虽然把 Tool message 标为 `ARTIFACT_REFERENCE`，但其 content 仍可能包含完整 Tool Result 或截断预览。

Phase 4 后，在身份存在时：

```json
{
  "artifact_id": "artifact-...",
  "artifact_type": "TOOL_RESULT",
  "summary": "knowledge_agent result; payload_size=... bytes",
  "source": "messages_state.tool:knowledge_agent",
  "location": "memory://artifact-...",
  "size": 48000,
  "status": "REFERENCED"
}
```

完整 Tool output 仅存在于：

- 原始 LangGraph ToolMessage；
- InMemoryArtifactStore payload。

`ContextRuntime.bounded_model_messages()` 会用上述引用替换当前轮 ToolMessage 的模型可见 content。原始 `request.state.messages` 不变。

### 7.2 Evidence

Evidence ContextItem 继续使用：

```text
ContextItemType.EVIDENCE_REFERENCE
```

而不是改成通用 Artifact 类型，从而保留现有 Selector 中 Evidence 的优先级与 required 语义。

其 metadata 新增：

```text
artifact_id
artifact_type=RETRIEVAL_EVIDENCE
artifact_summary
artifact_location
artifact_size
artifact_status
```

完整 evidence dict，包括：

- document page_content；
- parent context；
- trace；
- provenance；
- score / verification metadata；

进入 Artifact payload，不进入 ContextItem content。

### 7.3 Context manifest

`ContextSelection.runtime_metadata` 新增：

```json
{
  "artifacts": {
    "reference_count": 2,
    "references": [],
    "payloads_in_context": false
  }
}
```

该 manifest 可用于 debug 和未来 evaluation。

## 8. Lazy Loading

`ArtifactResolver` 支持：

```text
artifact_id
  + IdentityContext
        ↓
ArtifactRegistry.get_artifact
        ↓
identity ownership validation
        ↓
RESOLVED lifecycle event
        ↓
Artifact payload
```

接口：

```python
resolver.resolve(...)
resolver.resolve_artifact(...)
resolver.resolve_reference(...)
```

`ContextRuntime.resolve_artifact()` 提供 Runtime 级入口：它从 state 恢复 IdentityContext 后再调用 Resolver。

Lazy loading 不会自动把完整 payload 塞回下一个 prompt。调用方必须明确决定是否需要读取，以及如何对读取结果再次预算。

## 9. Compaction 集成

历史 Tool Result 在进入 Compactor 前已经是 Artifact Reference。

Compactor 对这类 item：

- 不读取 Artifact payload；
- 不把 reference content 原样复制到 Summary；
- 只在 `task_progress` 中记录有限数量的 `artifact_id`；
- 输出 `artifact_reference_count`；
- 保持 `tool_output_content_retained=false`。

因此：

```text
Artifact payload
  ≠ Compaction Summary
```

Summary 只保存“使用过哪些产物”的引用，不成为 Artifact Store 的替代品。

## 10. 测试

新增 10 个 Artifact 专项测试，覆盖：

1. Artifact model JSON round-trip；
2. create/get/list/delete；
3. 无身份创建拒绝与跨身份读取拒绝；
4. Tool Result → Artifact Reference；
5. Retrieval Evidence → Artifact Reference；
6. artifact_id Lazy Loading；
7. Compaction 不复制大 payload；
8. create/reference/resolve/delete lifecycle；
9. Supervisor middleware 的真实 Tool Result 替换；
10. 100 Tool Result benchmark。

执行结果：

```text
Artifact 专项：10 passed
Context + Working Memory + Identity + Artifact：51 passed
仓库 tests/：175 passed
Annotation integration：9 passed
compileall：passed
```

全量：

```text
python -m pytest -q
```

仍在 `evals/tests/test_benchmark_integration.py` collection 阶段被当前执行环境阻断：

```text
ModuleNotFoundError: No module named 'langchain_core'
```

该项没有标记为通过。

## 11. Artifact Context Benchmark

构造：

```text
100 个 knowledge_agent Tool Result
每个 payload 包含大体积中文证据/观察文本
最后追加新用户请求，使 100 个结果成为历史产物
```

结果：

```text
Tool Result 数量                       100
完整 payload Context tokens      2,070,400
Artifact Reference tokens            7,000
token reduction                    99.6619%
Artifact retrieval success          100%
Reference correctness               100%
Artifact count                         100
原始 history 保留                    100%
Artifact payload 出现在 Context       false
```

测量使用 Liorin provider-neutral token estimator 和 payload 精确相等校验，不代表真实 LLM 回答质量。

### 11.1 既有能力回归

```text
Working Memory 50 轮：
  cumulative token reduction 89.0534%
  information loss 0

Memory Delta：
  100 次重复状态 lifecycle records 0

Compaction：
  120–200 step token reduction 91.7404%
  Working Memory preservation 100%
  SummaryMetadata validity 100%
  original history retention 100%
```

Phase 4 后 Compaction benchmark 的“压缩前 ContextItems”已经先完成 Tool Artifact 化，因此输入 token 分母由 Phase 3.2 的 103,390 下降到 85,900。两个 reduction ratio 的测量边界不同，不能直接当作性能回退比较；最终预算前 Context 仍明显下降，状态保持率未降低。

## 12. 已知限制

1. `InMemoryArtifactStore` 不跨进程、不跨重启，不适合生产 durable storage；
2. process-local 默认 Registry 没有 TTL、容量限制、LRU 或磁盘溢写；
3. lifecycle records 仅在内存中，尚未写入 Governance Audit Store；
4. exact IdentityContext matching 尚未实现 conversation-scoped / user-scoped 可配置共享策略；
5. `ARCHIVED` 状态已定义，但本阶段没有对象存储归档 adapter；
6. REPORT 类型和统一创建接口已经具备，但仓库当前没有独立 Report producer，因此没有伪造报告接入链路；
7. Knowledge Agent 当前回答生成仍会按既有 Evidence 机制加载必要的、已经筛选/验证/限长的证据文本；本阶段消除的是完整 Evidence 在统一 Context Runtime 中的重复传播，不替换现有 grounding prompt；
8. Artifact summary 当前是确定性元数据摘要，不是语义摘要；
9. dynamic prompt 与 model-call middleware 仍各执行一次 ContextBuilder，幂等 ID 避免重复 Artifact，但会产生重复 REFERENCED audit event；
10. Store payload 未加密，ACL/认证/密钥管理属于后续 Governance；
11. 尚未完成真实 LangGraph Server、多 worker、模型 Provider 的端到端回归。

## 13. 回滚

没有数据库或 checkpoint schema 迁移。

回滚步骤：

1. 从 `ContextBuilder` 移除 ArtifactRegistry、Tool/Evidence registration 和 reference rendering；
2. 从 `ContextRuntime` 移除 Artifact manifest 与 resolve 入口；
3. 从 Compactor 移除 artifact reference metrics；
4. 删除 `artifact/`、Artifact tests、benchmark 和本文件；
5. 从 `pyproject.toml` wheel package 列表移除 `artifact`。

原始 messages、evidence、trace 和 checkpoint 始终未被迁移或删除，因此可以直接恢复 Phase 3.2 Context 行为。

## 14. 验收回答

### 新能力在哪里？

```text
artifact/models.py
artifact/store.py
artifact/registry.py
artifact/resolver.py
```

### Runtime 如何调用？

```text
conversation_supervisor middleware
  → ContextRuntime
  → ContextBuilder
  → ArtifactRegistry
  → ARTIFACT_REFERENCE / EVIDENCE_REFERENCE
  → bounded model messages / dynamic prompt
```

### 数据如何流动？

完整 payload 进入 Store；短引用进入 Context；Resolver 按身份恢复 payload；原始 state 保留。

### 如何测试？

`tests/artifact/` 覆盖模型、Store、Identity、Context、Resolver、Compaction、Lifecycle、Supervisor middleware 和 benchmark。

### 如何回滚？

删除 Artifact adapter 与 ContextBuilder 分支即可；无数据库、checkpoint 或 Evidence schema 迁移。
