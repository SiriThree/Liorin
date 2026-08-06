# Phase 6 — Liorin Memory Governance, Evaluation, and Production Hardening

## 1. 阶段结论

Phase 6 在真实 Long-term Memory Runtime 上加入了存储抽象、身份 ACL、生命周期治理、可观测指标、确定性评测、可靠性降级和安全过滤。

本阶段没有创建新的 Agent，没有替换 Retrieval、Evidence、Context Runtime、Working Memory、Compaction 或 Artifact Registry。

真实链路为：

```text
support_workflow structured state
        ↓
LongTermMemoryRuntime.promote_from_state
        ↓
MemoryCandidateExtractor
        ↓
Memory Delta / No-op Detection
        ↓
MemoryAccessPolicy: WRITE
        ↓
GovernedMemoryPolicy
        ├─ stable/reuse/source/confidence/expiry
        ├─ sensitive content filtering
        ├─ prompt-injection filtering
        └─ content validation
        ↓
MemoryBackend
        ↓
Lifecycle Audit + Runtime Metrics
```

读取链路：

```text
ContextBuilder
        ↓
LongTermMemoryRuntime.retrieve_for_context
        ↓
MemoryAccessPolicy: READ
        ↓
MemoryRetriever
        ↓
MemoryBackend.search_fact
        ↓
ACL defense-in-depth + expiry + confidence filters
        ↓
ContextItem(type=MEMORY)
        ↓
Compaction / Selector / Budget
        ↓
Supervisor LLM
```

因此治理不是独立 Dashboard 或离线工具，而是在现有 `support_workflow → LongTermMemoryRuntime → ContextBuilder` 调用链中真实生效。

---

## 2. 修改文件

### 新增

```text
storage/
├── __init__.py
├── interfaces.py
├── memory_backend.py
└── artifact_backend.py

governance/
├── acl.py
├── policy.py
├── audit.py
└── lifecycle.py

metrics/
├── __init__.py
└── memory.py

evaluators/memory_governance.py
evals/memory_governance_benchmark.py
evals/benchmark/reports/memory_governance_phase6_report.json

tests/governance/
├── test_memory_governance.py
└── test_memory_governance_benchmark.py

docs/PHASE6_MEMORY_GOVERNANCE.md
```

### 修改

```text
memory/facts/store.py
memory/facts/retriever.py
memory/facts/runtime.py
evaluators/__init__.py
governance/README.md
pyproject.toml
CHANGELOG.md
```

### 未修改

```text
agents/
retrieval/
artifact/
context_engine/
evidence verification implementation
deployments/
```

`evals/` 只新增 Phase 6 benchmark 和报告，没有替换既有评测框架。

---

## 3. Persistence Backend 设计

### 3.1 MemoryBackend

位置：`storage/interfaces.py`

```text
save_fact()
get_fact()
update_fact()
delete_fact()
search_fact()
list_facts()
```

`LongTermMemoryRuntime` 现在直接依赖 `MemoryBackend` 协议，而不是在业务逻辑中实例化具体 Store。

当前实现：

```text
InMemoryMemoryBackend
```

它是线程安全的参考实现，同时保留 Phase 5 的兼容 API：

```text
save/get/update/delete/search
InMemoryMemoryFactStore
```

因此旧测试和旧调用仍可运行。

接口可由后续适配器实现为：

- PostgreSQL；
- Redis；
- Hybrid SQL + Vector Index；
- 其他具备 tenant/user 分区能力的持久化服务。

本阶段没有伪称已经实现数据库持久化。

### 3.2 ArtifactBackend

位置：`storage/artifact_backend.py`

提供双向兼容适配：

```text
ArtifactStoreBackendAdapter
existing ArtifactStore → ArtifactBackend

BackendArtifactStoreAdapter
ArtifactBackend → existing ArtifactRegistry
```

因此现有 `ArtifactRegistry` 无需修改，也可以运行在未来 Object Storage / metadata database backend 上。

测试已验证真实 `ArtifactRegistry(store=BackendArtifactStoreAdapter(...))` 的创建和读取链路。

---

## 4. Identity + ACL 设计

位置：`governance/acl.py`

支持操作：

```text
READ
WRITE
UPDATE
DELETE
DELETE_USER
DELETE_TENANT
```

普通 Fact 操作采用 fail-closed 所有权边界：

```text
requester.tenant_id == resource_owner.tenant_id
and
requester.user_id == resource_owner.user_id
```

匿名身份不能读写 Long-term Memory。

ACL 在两处执行：

1. `LongTermMemoryRuntime` 在读写、更新和删除前执行；
2. `MemoryRetriever` 对 Backend 返回的每条 Fact 再执行一次 READ 校验。

这形成 defense-in-depth，即使未来 Backend 查询过滤发生错误，也不能直接把跨用户 Fact 注入 Context。

### Tenant 删除

`IdentityContext` 当前没有 roles/permissions，因此没有伪造 RBAC。

Tenant-wide delete 只能由 `MemoryAccessPolicy.tenant_admin_owners` 显式配置的 `(tenant_id, user_id)` 执行。后续应替换为现有企业 Principal/Permission 系统。

---

## 5. 生命周期治理

位置：`governance/lifecycle.py`

`MemoryGovernanceService` 支持：

```text
delete by fact_id
delete by user
delete by tenant
correct fact
```

### Correction

修正不会直接覆盖 Backend：

```text
existing Fact
   ↓ ACL UPDATE
MemoryFactCandidate
   ↓ Delta
Promotion Policy
   ↓ Backend update
UPDATED lifecycle records
```

历史 lifecycle record 不删除。

### Deletion

删除经过 ACL，并产生：

```text
MemoryLifecycleEvent.DELETED
actor
reason
identity_context
fact_key
fact_source
```

删除后的 Fact 不能被 `get`、`retrieve_for_context` 或 ContextBuilder 重新注入。

### Expiration

继续使用 `expires_at`。Retriever 以当前时间检查：

```text
expired → exclude from Context
        → EXPIRED lifecycle event
        → stale_memory_block_count
```

同一 Fact 的重复过期读取不会无限产生相同 EXPIRED lifecycle noise。

---

## 6. Audit 设计

位置：`governance/audit.py`

包括：

```text
MemoryAuditSink
InMemoryMemoryAuditLog
SafeMemoryAuditHook
```

Audit 可按以下字段查询：

```text
fact_id
tenant_id
user_id
event
```

默认 Runtime 将生命周期同时写入：

1. Runtime 内部 lifecycle history；
2. 默认 Audit Sink。

Audit Sink 异常时：

- 不阻断 Agent；
- 不回滚已成功的业务写入；
- 增加 `audit_failure_count`。

本阶段 Audit 仍为 process-local，尚未接入企业审计数据库或集中日志平台。

---

## 7. Security Hardening

位置：`governance/policy.py`

`GovernedMemoryPolicy` 在 Phase 5 `MemoryFactPolicy` 之前增加：

### Sensitive Memory Filtering

拒绝明显敏感 key 或 value，例如：

- password / secret / token / API key；
- 私钥；
- 银行卡号；
- SSN；
- email / phone；
- 身份证、银行卡、密码、密钥等字段。

### Prompt Injection Protection

拒绝类似：

```text
Ignore previous instructions
Reveal the system prompt
忽略之前的指令
输出系统提示词
jailbreak / 越狱
```

### Content Validation

检查：

- 最大长度；
- 控制字符；
- 异常格式；
- 原 Phase 5 的 token/value 上限。

### Fail-closed Policy

Policy 抛出异常时：

```text
默认拒绝写入
memory_policy_reject_count + 1
policy_failure_count + 1
```

不会绕过 Policy 直接 Persist。

---

## 8. Reliability

### Backend failure

Agent-facing 写入：

```text
Backend get/save/update failure
    → persisted=false
    → error recorded in result
    → backend_failure_count
    → support workflow continues
```

Agent-facing检索：

```text
Backend search failure
    → empty MemoryRetrievalResult
    → Agent continues without Long-term Memory
```

显式删除/治理操作仍 fail-loud，因为操作方需要知道删除是否真实完成，不能把失败伪装成成功。

### Retrieval failure

`retrieve_for_context` 捕获 Backend/Retriever 异常，返回空 Fact 集，不影响 ContextBuilder 构造其他 ContextItem。

### Policy failure

默认拒绝写入。

### Audit failure

不阻断业务，并记录指标。

---

## 9. Observability

位置：`metrics/memory.py`

真实 `LongTermMemoryRuntime` 产生：

### Retrieval

```text
memory_retrieval_count
memory_retrieval_hit_count
memory_retrieved_fact_count
memory_hit_rate
wrong_injection_count
stale_memory_block_count
```

### Write

```text
memory_candidate_count
memory_policy_accept_count
memory_policy_reject_count
memory_policy_accept_rate
memory_noop_count
memory_noop_rate
memory_update_count
```

### Context / cross-runtime

```text
memory_context_tokens
artifact_reference_count
context_selection_count
compaction_count
compaction_rate
```

`memory_context_tokens` 来自真实 Memory Retrieval 注入值。

`RuntimeMetricsCollector` 可以读取：

- 真实 `ArtifactRegistry.lifecycle_records()`；
- 真实 `ContextSelection.runtime_metadata`；

计算 Artifact Reference 和 Compaction 指标，不使用 mock payload。

### Reliability

```text
backend_failure_count
policy_failure_count
audit_failure_count
acl_denied_count
```

当前 Metrics Registry 是 process-local counter。尚未导出 Prometheus/OpenTelemetry。

---

## 10. Memory Evaluation

位置：`evaluators/memory_governance.py`

复用现有 `evaluators/`，没有创建独立评测系统。

指标：

```text
Memory Precision
Memory Recall
Wrong Injection Rate
Stale Memory Rate
Forgetting Accuracy
```

定义：

```text
Precision = 正确检索数 / 全部检索数
Recall = 正确检索数 / 应检索数
Wrong Injection Rate = 非预期 Fact / 全部注入 Fact
Stale Memory Rate = 已过期但仍注入 Fact / 全部注入 Fact
Forgetting Accuracy = 1 - 删除后仍被检索数 / 应删除数
```

评测为确定性 Fact ID 对齐，不依赖 LLM-as-Judge。

---

## 11. Memory Governance Benchmark

脚本：

```text
evals/memory_governance_benchmark.py
```

报告：

```text
evals/benchmark/reports/memory_governance_phase6_report.json
```

规模：

```text
100 tenants
100 users
1,000 persisted MemoryFact
200 Promotion Policy cases
```

场景：

1. 100 次跨 tenant/user 读取尝试；
2. 100 个正常 Retrieval case；
3. 100 个 expired Fact exclusion case；
4. 100 个 delete/forgetting case；
5. 100 个合法 Candidate + 100 个 Prompt Injection Candidate。

结果：

```text
Facts seeded                 1,000
Isolation accuracy           100%
Retrieval precision          100%
Retrieval recall             100%
Wrong injection rate           0%
Stale memory rate              0%
Deletion correctness         100%
Expiration correctness       100%
Forgetting accuracy          100%
Policy accuracy              100%
```

Runtime Metrics 中：

```text
memory_candidate_count       1,000
memory_update_count          1,000
stale_memory_block_count       100
wrong_injection_count            0
backend_failure_count            0
```

`memory_hit_rate=33.33%` 的分母包含：

- 100 个预期命中的正常检索；
- 100 个预期 miss 的过期检索；
- 100 个预期 miss 的删除后检索。

因此它不是 Retrieval Precision，也不是性能下降。

该 Benchmark 使用 in-memory backend 和确定性检索，不代表真实数据库吞吐、分布式一致性或 LLM 回答正确率。

---

## 12. 测试结果

### Governance 专项

```text
python -m pytest -q tests/governance
12 passed
```

覆盖：

- tenant/user ACL；
- cross-user isolation；
- fact/user/tenant deletion；
- Memory correction；
- expiration；
- evaluation metrics；
- backend failure fallback；
- policy failure fail-closed；
- audit failure non-blocking；
- sensitive content filtering；
- prompt injection filtering；
- real Runtime metrics；
- Artifact Backend ↔ ArtifactRegistry adapter；
- 100 tenants / 1,000 facts benchmark。

### 仓库回归

```text
python -m pytest -q tests
197 passed
```

### Annotation integration

```text
python -m pytest -q evals/tests/test_annotation_pipeline_integration.py
9 passed
```

### Compile

```text
python -m compileall -q storage metrics governance memory artifact context_engine evaluators evals tests
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

失败位置：

```text
evals/tests/test_benchmark_integration.py
```

退出码：`2`。

没有将全量测试伪报为通过。

---

## 13. 已知限制

1. Memory/Artifact/Audit/Metrics 后端仍为 process-local in-memory；
2. 尚未实现 PostgreSQL、Redis、Object Storage 或跨 Worker 一致性；
3. Tenant admin 使用显式配置集合，不是完整 RBAC/ABAC；
4. 尚未实现加密、KMS、字段级脱敏和区域数据驻留；
5. Sensitive filter 是确定性规则，不能覆盖所有 PII/secret 类型；
6. Metrics 尚未导出 Prometheus/OpenTelemetry；
7. Audit 尚未写入集中式 append-only 存储；
8. Backend retry、circuit breaker、timeout 和 bulkhead 仍需由具体生产 adapter 实现；
9. Memory correction/delete 尚未暴露产品 API；
10. 当前环境没有完成真实 LangGraph Server、多 Worker、真实模型 Provider 回归；
11. Benchmark 不测持久数据库吞吐、延迟和灾难恢复；
12. Release Gate 尚未配置基于生产基线的 Memory 指标阈值。

---

## 14. 回滚

本阶段没有数据库迁移。

回滚步骤：

1. 恢复 Phase 5 的：
   - `memory/facts/store.py`
   - `memory/facts/retriever.py`
   - `memory/facts/runtime.py`
2. 删除：
   - `storage/`
   - `metrics/`
   - 新增 governance 文件；
   - Memory evaluator/benchmark/tests/docs；
3. 从 `pyproject.toml` 移除 `storage` 和 `metrics` package。

旧 Phase 5 MemoryFact checkpoint/state 不包含新的必填字段，因此无需 checkpoint 数据迁移。

---

## 15. 验收回答

### 新能力在哪里？

- Storage：`storage/`
- ACL/Security/Audit/Lifecycle：`governance/`
- Observability：`metrics/`
- Evaluation：`evaluators/memory_governance.py`
- Runtime integration：`memory/facts/runtime.py`、`memory/facts/retriever.py`

### Runtime 如何调用？

现有 `support_workflow` 仍调用默认 `LongTermMemoryRuntime`；Runtime 内部自动执行 ACL、Policy、Backend、Audit、Metrics。`ContextBuilder` 仍通过同一个 Runtime 检索 Memory。

### 数据如何流动？

```text
State → Candidate → Delta → ACL → Policy → Backend → Audit/Metrics
Context request → ACL → Retriever → Backend → ContextItem(MEMORY)
```

### 如何测试？

Governance 专项 12 passed；仓库 tests 197 passed；100 tenants / 1,000 facts benchmark 已生成可复现 JSON 报告。

### 如何回滚？

恢复三个 Phase 5 MemoryFact 文件并删除新增治理模块即可；没有数据库或 checkpoint migration。
