# Phase 5 — Liorin Long-term Memory + Memory Fact System

> 本文记录真实 Liorin 仓库中的 Phase 5 实现。
>
> 本阶段实现的是结构化、身份绑定、经 Policy 审批的长期事实，不是 Conversation History Storage、聊天记录向量库、独立 Memory Agent、User Profile、ACL 或新的 Retrieval 系统。Working Memory、Context Compaction、Artifact Memory、Evidence、Trace 与原始 MessagesState 均继续保留。

## 1. 阶段结论

Phase 5 已形成真实双向运行链路，而不是只新增 Memory 表或孤立 Store。

写入链路：

```text
support_workflow structured state / latest explicit user confirmation
        ↓
MemoryCandidateExtractor
        ↓
MemoryFactCandidate
        ↓
MemoryFactDeltaDetector
        ↓
No-op Detection
        ↓
MemoryFactPolicy
        ↓
LongTermMemoryRuntime
        ↓
MemoryFactStore
        ↓
MemoryLifecycleRecord
```

读取链路：

```text
new conversation / new session runtime state
        ↓
IdentityContext
        ↓
ContextBuilder
        ↓
MemoryRetriever
        ↓
relevant, non-expired, same-owner MemoryFact only
        ↓
ContextItem(type=MEMORY)
        ↓
Compaction / Selector / Budget
        ↓
conversation_supervisor dynamic_prompt
        ↓
Supervisor LLM
```

本阶段可以证明：

1. 长期 Memory 是结构化 Fact，不是消息副本；
2. 写入经过 Candidate、Delta、No-op、Policy 和 Persist；
3. 读取按 `tenant_id + user_id` 隔离，并限制相关性和数量；
4. 过期 Fact 不会注入 Context；
5. Memory 通过现有 Context Runtime 进入模型；
6. Working Memory、Artifact Memory 与 Long-term Memory 保持不同职责。

## 2. 修改文件

### 新增

```text
memory/facts/
├── __init__.py
├── models.py
├── delta.py
├── extractor.py
├── policy.py
├── store.py
├── retriever.py
└── runtime.py

evals/long_term_memory_benchmark.py
evals/benchmark/reports/long_term_memory_phase5_report.json
artifacts/evals/LONG_TERM_MEMORY_PHASE5_BENCHMARK.json

tests/memory/facts/
├── __init__.py
├── test_memory_fact_runtime.py
└── test_long_term_memory_benchmark.py

docs/PHASE5_LONG_TERM_MEMORY.md
```

### 修改

```text
memory/__init__.py
context_engine/builder.py
agents/support_workflow.py
agents/conversation_supervisor.py
config.py
.env.example
tests/memory/working/test_support_workflow_integration.py
docs/PHASE2_WORKING_MEMORY_RISKS.md
CHANGELOG.md
```

未替换或删除：

```text
retrieval/
governance/
evaluators/
existing evidence / trace logic
artifact/
WorkingMemory
Context Compaction
```

`agents/` 的修改仅用于把已有 workflow structured state 接入 Long-term Memory Runtime，以及把已有 Context Runtime 配置传给 Supervisor；没有创建新 Agent，也没有改变原有路由、Retrieval 或 Evidence 语义。

## 3. MemoryFact 模型

`memory/facts/models.py` 定义：

```text
fact_id
identity_context
key
value
source
confidence
verified
observed_at
verified_at
verified_by
created_at
updated_at
expires_at
```

### 3.1 Fact 而不是聊天记录

`MemoryFact` 对 value 大小设置上限，并且 Candidate Extractor 只消费结构化字段和当前显式确认，不读取全部 conversation history。

禁止进入 Long-term Memory 的内容：

- 全部用户消息；
- 全部 Agent 回复；
- Tool Result 正文；
- Retrieval chunk 正文；
- Trace；
- Compaction Summary；
- Artifact payload。

这些内容分别继续由 MessagesState、Evidence/Trace、Compaction 和 Artifact Memory 管理。

### 3.2 来源与可信度

支持来源：

```text
user_confirmation
business_system
workflow_state
agent_inference
legacy_checkpoint
```

语义约束：

- 用户明确确认：可以使用 `confidence=1.0, verified=true`；
- 业务系统结果：可以使用高置信度和可信 verifier；
- Workflow structured state：由字段来源决定可信度；
- Agent 推断：默认低置信度、`verified=false`；
- 旧 Working Memory 字符串：`legacy_checkpoint, confidence=0.5, verified=false`。

`verified=true` 时必须同时提供：

```text
verified_at
verified_by
```

### 3.3 JSON-safe 与 checkpoint 兼容

`MemoryFact` 和 `MemoryFactCandidate` 支持：

```python
to_state()
from_state()
```

值、时间、IdentityContext 均会转换为 JSON-safe state。

本阶段没有把完整长期 Fact 集合写入 LangGraph checkpoint；旧 Phase 2/3/4 checkpoint schema 不需要迁移。旧 `WorkingMemory.confirmed_facts: list[str]` 仍可读取，但只产生保守 Candidate，不会自动变成已验证长期事实。

## 4. Candidate 提取流程

`MemoryCandidateExtractor` 仅从以下来源提取：

1. `memory_fact_candidates` 显式结构化输入；
2. `user_confirmed_facts`；
3. `business_system_facts`；
4. 已知 workflow stable fields，例如产品型号、产品名称、地区；
5. 旧 Working Memory 的 `confirmed_facts`；
6. 当前最新一条用户消息中的窄范围显式确认表达。

当前消息提取示例：

```text
我确认设备型号是 LF-900
model is LF-900
```

它是确定性、窄范围规则，不会扫描历史消息，也不会每轮调用 LLM 总结对话。

Extractor 只创建 Candidate，不直接调用 Store。

## 5. Promotion Policy

`MemoryFactPolicy` 至少检查：

```text
identity ownership
non-anonymous user
stability
future reuse value
source trust
confidence threshold
verification state
expiry risk
fact size
```

默认行为：

- 已验证的用户确认和业务系统事实可以批准；
- 未验证 Agent inference 被拒绝；
- `legacy_checkpoint` 字符串被拒绝自动提升；
- 匿名用户不持久化长期 Memory；
- 已经过期或即将无效的 Candidate 不会被批准；
- 不具备未来复用价值的临时状态不进入长期 Store。

Policy 返回结构化 `MemoryPolicyDecision`，包含：

```text
approved
reason
criteria
```

Lifecycle 中会记录批准或拒绝原因。

## 6. Memory Delta 与 No-op

长期 Fact 更新复用 Phase 3.1 的 `MemoryUpdate`：

```text
changed_fields
reason
previous_fingerprint
candidate_fingerprint
additions
removals
```

`MemoryFactDeltaDetector` 使用 canonical semantic fingerprint。

Fingerprint 覆盖：

```text
owner
key
value
source
confidence
verified
verification provenance
expiry
```

不把 `created_at`、`updated_at` 等易变时间戳当作语义变化。

相同 Fact 重复处理时：

```text
previous_fingerprint == candidate_fingerprint
        ↓
No-op
        ↓
不执行 Policy
不执行 Store update
不产生 Persisted UPDATED lifecycle
```

相同、已被 Policy 拒绝的 Candidate 也通过 fingerprint 抑制重复拒绝记录，避免 workflow 每次调用造成审计噪声。

## 7. Long-term Memory Store

`MemoryFactStore` Protocol 提供：

```text
save()
get()
update()
delete()
search()
```

当前实现为：

```text
InMemoryMemoryFactStore
  ├─ process-local
  ├─ thread-safe RLock
  ├─ fact_id → MemoryFact
  └─ tenant_id + user_id ownership validation
```

接口不绑定具体后端，未来可以实现 PostgreSQL、Redis 或 Vector Store adapter，而不改变 Candidate/Policy/Context API。

## 8. Identity 隔离

每条 Fact 保存完整 `IdentityContext`，记录首次观察来源：

```text
tenant_id
user_id
conversation_id
thread_id
session_id
```

长期读取的 durable owner boundary 为：

```text
tenant_id + user_id
```

原因：

- Long-term Memory 必须允许同一用户跨 conversation/session 使用；
- conversation/thread/session 仍保留为 provenance；
- 不同 tenant 或 user 必须拒绝访问。

因此：

```text
同 tenant + 同 user + 新 conversation/session → 可以检索
不同 tenant 或不同 user                    → 不能检索
```

这不是 ACL 或认证系统。IdentityContext 仍是归属契约；生产环境还需由认证层提供可信 ID。

## 9. Retrieval

`MemoryRetriever` 输入当前 Context，而不是无条件返回全部 Store。

检索步骤：

```text
current user request / workflow state
        ↓
query normalization + structured key hints
        ↓
Store owner filtering
        ↓
expiry filtering
        ↓
relevance scoring
        ↓
limit
```

默认最大注入数量由配置控制：

```text
LIORIN_LONG_TERM_MEMORY_RETRIEVAL_LIMIT=6
```

Memory 未命中时不会为凑数量返回不相关 Fact。

过期 Fact：

- 不进入结果；
- 产生一次 `EXPIRED` lifecycle record；
- 不会因为重复查询无限追加 EXPIRED 事件。

## 10. Context Runtime 注入

`ContextBuilder` 在已有构建流程中调用 Long-term Memory Runtime：

```text
MessagesState / workflow / WorkingMemory
        ↓
IdentityContext resolution
        ↓
LongTermMemoryRuntime.retrieve_for_context
        ↓
ContextItem(type=MEMORY)
        ↓
Compaction
        ↓
Selector
        ↓
BudgetManager
```

单个 Fact 注入格式：

```json
{
  "type": "MEMORY",
  "content": "LF-900",
  "source": "memory.facts.product_model",
  "metadata": {
    "memory_kind": "long_term_fact",
    "fact_id": "memory-fact:...",
    "key": "product_model",
    "confidence": 1.0,
    "source": "user_confirmation",
    "verified": true,
    "identity_context": {}
  }
}
```

优先级：

- verified Fact：98；
- unverified but policy-approved Fact：90；
- 当前用户请求仍为最高优先级；
- Working Memory 保持原样且不参与长期 Fact 替换。

`ContextRuntime` manifest 会记录本次注入的 Fact 数量和有限 metadata，便于 debug/evaluation。

## 11. 真实 Workflow 接入

`agents/support_workflow.py` 的 `_with_working_memory` 现在执行：

```text
existing structured state
        ↓
WorkingMemory update + Delta
        ↓
LongTermMemoryRuntime.promote_from_state
        ↓
Candidate / Delta / Policy / Persist
        ↓
long_term_memory_lifecycle_records 写入 checkpoint
```

新增的 state 字段仅用于候选输入和 lifecycle 审计：

```text
memory_fact_candidates
user_confirmed_facts
business_system_facts
long_term_memory_lifecycle_records
```

不会把 Store 中的全部 Fact 复制进 checkpoint。

下一次不同 conversation/thread/session 的同一用户请求进入 `conversation_supervisor` 时，现有 `dynamic_prompt` 和 model-call middleware 均通过 `ContextRuntime` 检索长期 Fact。

## 12. Memory 生命周期

复用 Phase 1 生命周期协议：

```text
CREATED
UPDATED
RETRIEVED
EXPIRED
DELETED
```

每条 `MemoryLifecycleRecord` 包含：

```text
actor
reason
occurred_at
identity_context
MemoryMetadata
attributes.source
attributes.fact_key
Delta attributes
```

流程示例：

```text
Candidate CREATED
        ↓
Policy UPDATED / POLICY_APPROVED
        ↓
Persist CREATED or UPDATED / PERSISTED
        ↓
Context retrieval RETRIEVED
```

删除通过 `LongTermMemoryRuntime.delete()` 完成，并记录 `DELETED`。读取事件不会改变持久状态。

## 13. 配置

新增：

```text
LIORIN_LONG_TERM_MEMORY_ENABLED=true
LIORIN_LONG_TERM_MEMORY_RETRIEVAL_LIMIT=6
```

可通过 `config.Context` 和 Supervisor request config 传播到 `ContextRuntime`。

关闭该功能时：

- ContextBuilder 不检索长期 Fact；
- 已有 Store 数据不删除；
- Working Memory、Artifact、Compaction 和原有 Agent 链路继续工作。

## 14. Benchmark

执行：

```text
python -m evals.long_term_memory_benchmark
```

场景：

- 100 个相互隔离的用户；
- Session A 每个用户通过完整 Candidate → Delta → Policy → Store 流程写入 3 个结构化事实；
- Session B 使用不同的 conversation、thread 和 session；
- Session B 只查询设备型号；
- 同时尝试不同用户/租户读取和过期 Fact 注入。

结果：

```text
case_count                              100
Session A persisted facts               300
Session B expected facts                100

Before precision                       0.0%
Before recall                          0.0%

After precision                      100.0%
After recall                         100.0%
Wrong Injection Rate                   0.0%
Cross-identity injections                 0
Expired injections                        0

Cumulative Context token increase       200
Average Context token increase           2.0
Candidate/Policy/Persist lifecycle       900
Retrieved lifecycle                     200
```

`RETRIEVED=200` 的原因是 benchmark 分别验证了显式 Retriever 结果和 ContextBuilder 注入，两条真实读取路径各产生一次审计记录。

指标定义：

- Precision：返回 Fact 中 key/value 与当前请求期望一致的比例；
- Recall：期望 Fact 被取回的比例；
- Wrong Injection Rate：无关或跨身份 Fact 占注入结果的比例；
- Context Token Increase：使用现有 provider-neutral token estimator 的模型可见 Context 增量。

限制：该 benchmark 是确定性 Fact 检索和 Context 注入评测，不调用外部 LLM，也不代表真实客服回答正确率。

报告位置：

```text
evals/benchmark/reports/long_term_memory_phase5_report.json
artifacts/evals/LONG_TERM_MEMORY_PHASE5_BENCHMARK.json
```

## 15. 测试结果

### MemoryFact 专项

```text
python -m pytest -q tests/memory/facts
10 passed
```

覆盖：

- MemoryFact JSON round-trip；
- 旧 WorkingMemory 保守迁移；
- tenant/user identity isolation；
- Candidate 必须经过 Policy；
- Delta No-op 不重复保存；
- 只检索相关 Fact；
- 跨 session Context injection；
- 过期 Fact 不注入；
- update/delete lifecycle；
- Long-term Memory benchmark 门禁。

### Context / Memory / Identity / Artifact 回归

```text
python -m pytest -q tests/memory tests/context_engine tests/identity tests/artifact
61 passed
```

### 仓库 tests

```text
python -m pytest -q tests
185 passed
```

### Annotation integration

```text
python -m pytest -q evals/tests/test_annotation_pipeline_integration.py
9 passed
```

### 编译

```text
python -m compileall -q artifact context_engine identity memory agents evals tests
passed
```

### 全量 pytest

```text
python -m pytest -q
```

当前执行环境在 collection 阶段被阻断：

```text
ModuleNotFoundError: No module named 'langchain_core'
```

失败来自：

```text
evals/tests/test_benchmark_integration.py
```

没有将全量 pytest 标记为通过。

## 16. 已知限制

1. Store 是 process-local in-memory，多 worker/重启后不会保留；
2. IdentityContext 是归属契约，不等于已实现认证、ACL 或授权；
3. 当前 Retriever 是结构化 key/lexical relevance，不是 embedding/vector retrieval；
4. Candidate Extractor 只支持有限结构化字段和窄范围显式确认；
5. 尚未实现用户主动查看、纠正、撤回或批量删除长期 Fact 的产品接口；
6. 尚未实现持久 Store migration、加密、TTL scheduler、容量限制和冲突版本治理；
7. 同一 `tenant_id + user_id + key` 当前对应一个 deterministic fact_id，复杂多值事实需要后续 schema 扩展；
8. lifecycle audit 当前同时保存在 process memory 和有限 checkpoint record 中，不是企业审计数据库；
9. dynamic prompt 与 model-call middleware 都会执行 Context build，可能产生两次 RETRIEVED 审计记录；
10. 未实现基于真实模型回答的 Memory usefulness、contradiction 和 stale-fact 评测；
11. 当前运行环境没有完成真实 LangGraph Server / durable checkpoint / provider model 端到端验证。

## 17. 回滚

本阶段没有数据库迁移，也没有改变旧 checkpoint 的必填 schema。

回滚步骤：

1. 从 `support_workflow._with_working_memory` 移除 Long-term Memory promotion；
2. 从 `ContextBuilder` 移除 `_long_term_memory_items()`；
3. 从 `ContextRuntime` 和 Supervisor 移除长期 Memory 配置传播；
4. 删除 `memory/facts/`；
5. 删除新增 config 和 `.env.example` 项；
6. 删除专项 tests、benchmark、报告和文档；
7. 保留 Working Memory、IdentityContext、Memory Delta、Compaction 和 Artifact Memory。

关闭 `LIORIN_LONG_TERM_MEMORY_ENABLED` 也可作为运行时软回滚，只停止 Context 检索，不删除 Store 数据。

## 18. 验收问题回答

### 18.1 新能力在哪里？

- 核心模型和 Runtime：`memory/facts/`；
- 写入接入：`agents/support_workflow.py`；
- 读取和注入：`context_engine/builder.py`；
- Supervisor 配置传播：`agents/conversation_supervisor.py`；
- 评测：`evals/long_term_memory_benchmark.py`。

### 18.2 Runtime 如何调用？

- Workflow 调用 `LongTermMemoryRuntime.promote_from_state()`；
- ContextBuilder 调用 `LongTermMemoryRuntime.retrieve_for_context()`；
- ContextRuntime 将结果转成 `ContextItemType.MEMORY`；
- Supervisor 已有 dynamic prompt/model-call middleware 消费该 Context。

### 18.3 数据如何流动？

```text
structured state
  → Candidate
  → Delta / No-op
  → Policy
  → Store
  → relevant retrieval
  → ContextItem(MEMORY)
  → Compaction / Selector / Budget
  → Supervisor LLM
```

### 18.4 如何测试？

- 10 个 MemoryFact 专项测试；
- 61 个 Context/Memory/Identity/Artifact 回归；
- 185 个仓库 tests；
- 100-user 多 Session benchmark；
- 全量 pytest 的环境阻断已独立报告。

### 18.5 如何回滚？

可以通过配置关闭读取，或删除 promotion/injection 适配和 `memory/facts/`；旧 checkpoint、Evidence、Artifact、Working Memory 均不需要迁移。
