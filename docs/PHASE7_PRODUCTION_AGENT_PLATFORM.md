# Phase 7 — Production Agent Platform

## 1. 阶段结论

Phase 7 在 Phase 6 的 Context、Working Memory、Long-term Memory、Artifact、Identity、ACL、Audit 和 Evaluation 基础上增加生产基础设施适配层。现有 Agent、Context Runtime、Memory Runtime 和 Artifact Runtime 没有被重写；生产部署通过 Backend、Cache、Observability、Reliability 和 Bootstrap 接口切换基础设施。

本阶段真实接入链路为：

```text
LangGraph deployment entry
        ↓
production.bootstrap
        ├─ MemoryBackend: InMemory / PostgreSQL
        ├─ ArtifactBackend: InMemory / PostgreSQL
        ├─ Cache: disabled / local TTL / Redis
        ├─ Retry + Timeout + Circuit Breaker
        ├─ MetricsExporter
        └─ default Runtime registry replacement
        ↓
existing support_workflow / conversation_supervisor
        ↓
ContextRuntime + LongTermMemoryRuntime + ArtifactRegistry
```

业务代码仍只依赖既有抽象。`LongTermMemoryRuntime` 不直接调用 PostgreSQL，`ArtifactRegistry` 不直接调用 Redis。

---

## 2. 修改文件

### 新增模块

```text
storage/backends/
├── _dbapi.py
├── postgres_memory_backend.py
├── postgres_artifact_backend.py
├── redis_cache.py
└── __init__.py

storage/cache/
├── interfaces.py
├── memory.py
├── adapters.py
├── context.py
└── __init__.py

reliability/
├── retry.py
├── timeout.py
├── circuit_breaker.py
├── backend.py
└── __init__.py

observability/
├── events.py
├── trace.py
├── instrumentation.py
├── metrics.py
└── __init__.py

production/
├── config.py
├── bootstrap.py
├── health.py
├── request_identity.py
├── api.py
└── __init__.py

eval_platform/
├── dataset.py
├── runner.py
├── evaluators.py
├── report.py
└── __init__.py

deploy/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── prometheus.yml
├── otel-collector-config.yml
└── README.md

 evals/production_benchmark.py
 tests/production/test_production_platform.py
 tests/production/test_production_benchmark.py
```

### 增量修改

```text
agents/conversation_supervisor.py
artifact/__init__.py
artifact/registry.py
artifact/resolver.py
config.py
context_engine/builder.py
context_engine/models.py
deployments/support_agent_graph.py
memory/facts/__init__.py
memory/facts/runtime.py
memory/facts/store.py
storage/__init__.py
storage/artifact_backend.py
pyproject.toml
.env.example
CHANGELOG.md
```

对 `agents/`、`context_engine/`、`memory/` 和 `artifact/` 的修改仅用于基础设施注入和观测，不改变其业务语义。

---

## 3. Production Storage

### 3.1 Memory Backend

`PostgresMemoryBackend` 实现 Phase 6 已定义的 Backend 契约：

```text
save_fact
get_fact
update_fact
delete_fact
search_fact
list_facts
```

实现特点：

- DB-API connection factory，生产默认使用 psycopg；
- 参数化 SQL；
- tenant/user 归属字段进入查询条件；
- JSON-safe `MemoryFact.to_state()` 持久化；
- schema/table 初始化幂等；
- SQLite dialect 仅用于不依赖外部数据库的契约测试，不是新的业务 Store。

### 3.2 Artifact Backend

`PostgresArtifactBackend` 实现：

```text
save_artifact
get_artifact
delete_artifact
list_artifacts
```

Artifact payload 与 metadata 继续使用现有 Artifact 模型；`ArtifactRegistry` 通过 `BackendArtifactStoreAdapter` 使用 Backend，业务调用方式不变。

### 3.3 Transaction Boundary

Memory Fact 的创建、修改和删除支持：

```text
Fact mutation
    +
Lifecycle audit outbox record
        ↓
同一数据库事务提交
```

对应接口：

```text
save_fact_with_audit
update_fact_with_audit
delete_fact_with_audit
```

这保证数据库事务提交后至少存在可发布的审计 outbox，不会出现 Fact 已提交但完全没有可追踪审计数据。当前阶段没有实现 outbox publisher；外部集中式 Audit Sink 仍需后续部署组件消费该表。

---

## 4. Cache Layer

### 4.1 缓存边界

Redis 只作为 read-through cache：

```text
Cache hit  → 返回缓存副本
Cache miss → Backend 查询 → 写入 TTL cache
Mutation   → Backend 先成功 → cache 更新或失效
```

Cache 不是唯一数据源。Redis 清空后，Memory 和 Artifact 仍可从 Backend 恢复。

### 4.2 缓存范围

- Memory Fact get/search；
- Artifact metadata/payload snapshot；
- Context Selection 的短 TTL assembly result。

### 4.3 Invalidation

- Fact save/update/delete 会失效同一 `tenant + user` 的 search cache；
- Artifact delete/update 会失效对应 Artifact cache；
- 缓存键包含身份边界，禁止跨用户命中；
- Context cache key 基于可序列化 Runtime state 指纹。

---

## 5. Reliability Engineering

### 5.1 Retry

`RetryPolicy` 为临时 Backend 和 Tool 失败提供有界重试：

- 最大尝试次数可配置；
- 指数退避参数可配置；
- 每次 retry 记录 `retry_count`；
- 不无限重试。

### 5.2 Timeout

`execute_with_timeout` 为 Backend 和专业 Agent Tool 调用建立超时边界。Supervisor 的 `order_agent` 和 `knowledge_agent` 工具通过 `invoke_observed_tool` 使用 timeout 和 retry。

### 5.3 Circuit Breaker

`CircuitBreaker` 支持：

```text
CLOSED
  ↓ 连续失败达到阈值
OPEN
  ↓ recovery timeout
HALF_OPEN
  ├─ 成功 → CLOSED
  └─ 失败 → OPEN
```

### 5.4 Graceful Degradation

| 故障 | Runtime 行为 |
|---|---|
| Memory Backend 读取失败 | 返回空 Memory，继续 Context 构造 |
| Memory Backend 写入失败 | 拒绝 Persist，Working Memory 与 Agent 继续 |
| Artifact Store 读取失败 | Artifact reference/summary 仍保留，Resolver 明确报错 |
| Cache 失败 | 回退到 Backend；Cache 不作为 source of truth |
| Tool timeout | 记录 Tool failure，交由现有 Agent fallback 处理 |
| Policy failure | 沿用 Phase 6 fail-closed，不写长期 Memory |
| Audit hook failure | 不阻断 Agent；事务 outbox 仍保留数据库审计记录 |

显式用户删除等治理操作仍保持 fail-loud，避免伪造删除成功。

---

## 6. Agent Observability

### 6.1 Trace Model

`AgentExecutionTrace` 包含：

```text
request_id
conversation_id
thread_id
agent_name
start_time
end_time
status
error
ordered events
```

`TraceRecorder` 使用 ContextVar 传播当前 trace，支持：

- 嵌套 Context、Memory、Artifact 和 Tool 事件；
- JSON-safe `to_state()`；
- 按时间排序的 `replay()`；
- 通过 `/traces/{request_id}` 查询进程内 trace。

### 6.2 Context Trace

Context Runtime 记录：

```text
context_items
token_count
full_token_count
compaction_applied
compaction_success
artifact_reference_count
memory_hits
cache_hit
selection manifest
```

### 6.3 Tool Trace

记录：

```text
tool_name
input preview
start/end
latency
success/error
```

### 6.4 Memory 与 Artifact Trace

Memory：

```text
MEMORY_READ
MEMORY_WRITE
MEMORY_UPDATE
MEMORY_BLOCKED
BACKEND_FAILURE
```

Artifact：

```text
ARTIFACT_CREATED
ARTIFACT_REFERENCED
ARTIFACT_RESOLVED
ARTIFACT_DELETED
```

这些事件来自真实 Runtime 方法，而不是 benchmark mock。

---

## 7. Unified Metrics

### 7.1 MetricsExporter

定义统一接口：

```python
class MetricsExporter(Protocol):
    def export(self, snapshot: Mapping[str, float]) -> None: ...
```

实现：

- `InMemoryMetricsExporter`；
- `PrometheusTextExporter`；
- `OpenTelemetryMetricsExporter`（按需导入 OpenTelemetry）。

### 7.2 指标范围

Quality：

```text
memory_precision
memory_recall
answer_success_rate
fallback_rate
```

Cost：

```text
prompt_tokens
completion_tokens
context_tokens
artifact_saved_tokens
```

Performance：

```text
agent latency
context_latency_ms
memory_latency_ms
tool_latency_ms
artifact_latency_ms
```

Reliability：

```text
error_rate
tool_failure_rate
backend_failure_count
backend_failure_rate
retry_count
metrics_export_failure_count
```

同时保留 Phase 6 的 Memory governance metrics。派生 rate 在统一 snapshot 阶段计算，不要求业务代码自行计算分母。

---

## 8. Unified Evaluation Platform

统一数据流：

```text
EvaluationDataset
        ↓
EvaluationRunner
        ↓
Existing Agent/Runtime callable
        ↓
AgentExecutionTrace
        ↓
Existing + built-in evaluators
        ↓
EvaluationReport
```

`eval_platform` 没有替换 `evals/` 或 `evaluators/`。它为既有 evaluator 提供统一调用契约。

内置 evaluator：

- Context：token reduction、state preservation；
- Memory：precision、recall、wrong injection、stale rate、forgetting accuracy；
- Artifact：reference correctness、recovery success；
- Agent：task success、tool correctness、fallback quality。

Report 包含：

```text
dataset_name
scenario results
aggregate metrics
success_rate
trace snapshot
errors
```

---

## 9. Deployment

### 9.1 服务

`deploy/docker-compose.yml` 包含：

```text
agent-api
postgres
redis
otel-collector
prometheus
```

### 9.2 启动

```bash
cd deploy
cp .env.example .env
docker compose up --build
```

Agent API：

```text
GET  /healthz
GET  /readyz
GET  /metrics
GET  /traces/{request_id}
POST /invoke
```

`POST /invoke` 要求受信网关提供：

```text
X-Liorin-Tenant-Id
X-Liorin-User-Id
X-Liorin-Conversation-Id
X-Liorin-Thread-Id
X-Liorin-Session-Id
```

API 会以这些身份头覆盖 Runtime identity，并拒绝请求体或 `configurable.thread_id` 冲突。该机制阻止请求体直接伪造 ACL 身份，但不替代 OAuth/OIDC；生产部署必须由认证网关清理并重新注入这些头。

### 9.3 Runtime Bootstrap

`deployments/support_agent_graph.py` 在创建 graph 前执行 `bootstrap_production_runtime()`：

```text
LIORIN_STORAGE_BACKEND=memory
    → InMemory Backend

LIORIN_STORAGE_BACKEND=postgres
    → PostgreSQL Backend

LIORIN_REDIS_ENABLED=true
    → Redis read-through cache
```

现有 Agent 无需感知 Backend 类型。

### 9.4 环境配置

主要配置：

```text
LIORIN_STORAGE_BACKEND
LIORIN_POSTGRES_DSN
LIORIN_POSTGRES_SCHEMA
LIORIN_REDIS_ENABLED
LIORIN_REDIS_URL
LIORIN_CACHE_TTL_SECONDS
LIORIN_BACKEND_RETRY_ATTEMPTS
LIORIN_BACKEND_TIMEOUT_SECONDS
LIORIN_CIRCUIT_FAILURE_THRESHOLD
LIORIN_CIRCUIT_RECOVERY_SECONDS
LIORIN_TOOL_TIMEOUT_SECONDS
LIORIN_OBSERVABILITY_ENABLED
LIORIN_METRICS_EXPORTER
```

---

## 10. Production Benchmark

Benchmark：`evals/production_benchmark.py`

规模：

```text
1,000 requests
100 users
10 tenants
100 seeded cross-session Memory Facts
1 Artifact per request
10 injected Memory search failures
```

结果：

```text
Request success rate                 100%
Mean platform latency                0.3110 ms
P50                                  0.2616 ms
P95                                  0.3993 ms
P99                                  0.6480 ms
Memory hit rate                       99%
Artifact retrieval success           100%
Injected backend failures             10
Failure recovery rate                100%
Context tokens before          1,520,001
Context tokens after              72,972
Token reduction                  95.1992%
Artifact saved tokens          1,427,009
Backend failure rate             0.9091%
```

Benchmark 使用真实 Context、Memory、Artifact、Metrics 和降级链路，但使用 in-memory Backend，并且没有调用外部 LLM、PostgreSQL 或 Redis。因此：

- latency 不是生产网络延迟；
- 不代表模型回答质量；
- PostgreSQL/Redis 仅通过契约测试和 SQLite DB-API 测试验证；
- token 使用现有 provider-neutral estimator。

---

## 11. 测试结果

最终测试结果以交付时 `PHASE7_TEST_OUTPUT.txt` 为准。阶段实现完成时：

```text
Production tests                       15 passed
Repository tests/                     212 passed
Annotation integration                  9 passed
compileall                             passed
```

全量 `python -m pytest -q` 在当前执行环境仍会在既有 benchmark integration collection 阶段因为缺少 `langchain_core` 失败。该阻断不是 Phase 7 断言失败，没有计为通过。

---

## 12. 已知限制

1. PostgreSQL Backend 已实现真实 DB-API SQL，但当前交付环境没有外部 PostgreSQL 服务，测试使用 SQLite dialect 验证接口与事务行为。
2. Redis Adapter 已实现真实 Redis client 接口，但当前交付环境没有外部 Redis 服务。
3. Transactional outbox 已写入，但尚未实现独立 publisher、重试队列和集中 Audit 消费者。
4. Trace 当前默认保存在进程内；尚未实现持久 Trace Backend 和跨 Worker 聚合。
5. OpenTelemetry exporter 是适配接口；生产 Collector SDK/provider 初始化需要部署环境配置。
6. Health probe 当前确认 Runtime 组件已配置，尚未执行数据库深度查询和 Redis ping。
7. HTTP 身份头必须由认证网关注入；Liorin 本阶段没有实现 OAuth/OIDC token 验证。
8. Context cache 当前缓存 selection state，仍需生产压测决定 TTL 和容量上限。
9. Tool timeout 已接入 Supervisor 的专业 Agent tools；其他未来外部 Connector 必须使用同一 instrumentation helper。
10. Artifact Backend 当前将 payload 保存在 PostgreSQL JSON 中；超大文件应在下一阶段切换 Object Storage，PostgreSQL 仅保存 metadata/location。
11. 生产 benchmark 不包含外部 LLM、Milvus、PostgreSQL 和 Redis 网络成本。
12. 当前环境无法重新解析现有 `uv.lock` 中的 `agentevals` registry 依赖；Dockerfile 对 Phase 7 基础设施依赖执行显式安装，原 lock 文件未被伪造更新。

---

## 13. 回滚

Phase 7 没有改变 MemoryFact、Artifact 或 checkpoint 的公共序列化结构。

回滚方式：

1. 将部署环境设为：

```text
LIORIN_STORAGE_BACKEND=memory
LIORIN_REDIS_ENABLED=false
LIORIN_OBSERVABILITY_ENABLED=false
```

即可在不改业务代码的情况下回退到进程内 Backend。

2. 完全代码回滚时：

- 恢复 Phase 6 的 `deployments/support_agent_graph.py`；
- 恢复 Phase 6 的 default Runtime getter/setter 文件；
- 删除 `production/`、`observability/`、`reliability/`、`eval_platform/`、`storage/backends/`、`storage/cache/` 和 `deploy/`；
- 恢复 Phase 6 的 `conversation_supervisor.py`、`context_engine/builder.py`、`memory/facts/runtime.py` 和 Artifact instrumentation。

PostgreSQL 表是新增基础设施状态，代码回滚不要求立即删除数据；可在完成备份和治理审计后单独下线。
