# Liorin Changelog

## Phase 5 — Long-term Memory + Memory Fact System

### 修改文件

- 新增 `memory/facts/`：MemoryFact、Candidate Extractor、Delta、Promotion Policy、Store、Retriever 与 LongTermMemoryRuntime。
- 修改 `agents/support_workflow.py`：Working Memory 更新后执行 Candidate → Delta → Policy → Persist，并保存 lifecycle records。
- 修改 `context_engine/builder.py`：按 Identity 和当前请求检索相关长期 Fact，转为 `ContextItem(type=MEMORY)`。
- 修改 `agents/conversation_supervisor.py`、`config.py`、`.env.example`：传播长期 Memory 开关和 retrieval limit。
- 新增多 Session benchmark、10 个专项测试和 `docs/PHASE5_LONG_TERM_MEMORY.md`。
- 更新 `docs/PHASE2_WORKING_MEMORY_RISKS.md`：MemoryFact confidence 风险标记为 Phase 5 基础修复。

### 新增能力

- identity-bound structured `MemoryFact`，包含 source、confidence、verified、observation/verification/expiry 时间；
- 旧 `confirmed_facts: list[str]` 以 `legacy_checkpoint / confidence=0.5 / verified=false` 保守读取；
- Candidate → MemoryUpdate → No-op → Policy → Persist 强制流程；
- `save/get/update/delete/search` Store Protocol 和 process-local in-memory 实现；
- `tenant_id + user_id` 跨 session owner isolation；
- relevant-only retrieval、limit、expiry exclusion；
- CREATED/UPDATED/RETRIEVED/EXPIRED/DELETED lifecycle audit；
- Context Runtime `MEMORY` 注入，未绕过 Compaction/Selector/Budget。

### 数据流变化

```text
Working/Workflow structured state
  → MemoryFactCandidate
  → Delta / No-op
  → Promotion Policy
  → MemoryFactStore
  → relevant same-owner retrieval
  → ContextItem(MEMORY)
  → Compaction / Selector / Budget
  → Supervisor LLM
```

聊天记录、Tool payload、Evidence、Trace 和 Artifact 不进入 Long-term Memory。

### 测试结果

- MemoryFact 专项：10 passed。
- Context + Memory + Identity + Artifact：61 passed。
- 仓库 `tests/`：185 passed。
- Annotation integration：9 passed。
- compileall：passed。
- 全量 pytest 仍因当前环境缺少 `langchain_core` 在 benchmark integration collection 阶段阻断，未标记为通过。

### Benchmark

- 100 个隔离用户，Session A 写入 300 个 Fact；
- Session B 使用不同 conversation/thread/session；
- Memory Precision：100%；
- Memory Recall：100%；
- Wrong Injection Rate：0%；
- cross-identity injection：0；
- expired injection：0；
- 平均模型可见 Context 增量：2 estimated tokens。

### 已知限制

- Store/lifecycle 为 process-local in-memory；
- 尚无认证、ACL、加密、durable backend、TTL scheduler 或用户纠正接口；
- Retriever 为 structured/lexical relevance，不是向量检索；
- 当前 deterministic fact_id 以 tenant/user/key 唯一，复杂多值事实需要 schema 扩展；
- 尚未完成真实 LangGraph Server/provider model 回归与 answer-quality Memory evaluation。

### 回滚

关闭 `LIORIN_LONG_TERM_MEMORY_ENABLED` 可软回滚读取；完全回滚时移除 support workflow promotion、ContextBuilder Fact injection、配置和 `memory/facts/`。没有数据库或旧 checkpoint migration。

## Phase 4 — Artifact Memory System

### 修改文件

- 新增 `artifact/`：Artifact model、in-memory Store、Registry、Resolver 与 lifecycle contract。
- 修改 `context_engine/builder.py`：Tool Result 与 Knowledge Evidence 完整 payload 注册为身份绑定 Artifact，模型 Context 仅保留引用。
- 修改 `context_engine/compaction/compressor.py`：Summary 仅记录 artifact_id，不复制 Tool payload。
- 修改 `context_engine/__init__.py`、`pyproject.toml`：导出并打包 Artifact Runtime。
- 新增 100 Tool Result benchmark、10 个专项测试和 `docs/PHASE4_ARTIFACT_MEMORY.md`。

### 新增能力

- `RETRIEVAL_EVIDENCE / TOOL_RESULT / DOCUMENT / REPORT / TRACE / SUMMARY` Artifact 类型；
- IdentityContext 强绑定与跨身份读取拒绝；
- create/get/delete/list Store 接口；
- CREATED/AVAILABLE/REFERENCED/RESOLVED/DELETED lifecycle audit；
- Supervisor 当前轮 ToolMessage payload → Artifact Reference 的真实 middleware 接入；
- Evidence payload → Evidence Reference + artifact_id；
- Lazy Resolver 与 ContextRuntime resolve 入口；
- Compaction artifact-reference-only summary。

### 数据流变化

```text
Tool/Evidence payload
  → ArtifactRegistry / InMemoryArtifactStore
  → identity-bound Artifact Reference
  → ContextBuilder / Selector / Budget / Compaction
  → Supervisor LLM
```

原始 messages、checkpoint、trace 和 evidence 保持不变。

### 测试结果

- Artifact 专项：10 passed。
- Context + Memory + Identity + Artifact：51 passed。
- 仓库 `tests/`：175 passed。
- Annotation integration：9 passed。
- compileall：passed。
- 全量 pytest 仍因当前环境缺少 `langchain_core` 在 benchmark integration collection 阶段阻断，未标记为通过。

### Benchmark

- 100 个大 Tool Result；
- full payload Context：2,070,400 tokens；
- Artifact references：7,000 tokens；
- token reduction：99.6619%；
- lazy retrieval success：100%；
- reference correctness：100%；
- original history retention：100%。

### 已知限制

- Store 与 lifecycle audit 均为 process-local in-memory；
- 尚无 TTL、durable backend、encryption、ACL 或 archive adapter；
- REPORT 类型已支持，但当前仓库没有真实独立 Report producer；
- Knowledge Agent 当前 grounding prompt 仍按既有机制读取必要的已验证/限长 Evidence；
- 尚未完成真实 LangGraph Server/multi-worker/provider 回归。

### 回滚

移除 Artifact package、ContextBuilder registration/reference 分支、Compaction artifact metrics、tests/benchmark/docs；没有数据库或 checkpoint 迁移。

## Phase 3.2 — Context Compaction Engine

### 修改文件

- 新增 `context_engine/compaction/`：trigger、structured compressor、validator、reconstructor 和 auditable models。
- 修改 `context_engine/builder.py`：真实接入 Build → Compaction → Selector → Budget。
- 修改 `agents/conversation_supervisor.py`：dynamic prompt 与 model-call middleware 传播 Runtime compaction 配置。
- 修改 `config.py`、`.env.example`：增加可配置 trigger、recent-message 和 summary budget。
- 新增 120–200 step benchmark、专项 tests 和 `docs/PHASE3_2_CONTEXT_COMPACTION.md`。

### 新增能力

- token/item threshold CompactionTrigger；
- identity-bound `CompactionSummary`，复用 SummaryMetadata；
- task_progress / decisions / confirmed information / pending questions / failed attempts 结构化摘要；
- Working Memory 和 IdentityContext 精确保留验证；
- 压缩失败自动回退未压缩 Selector/Budget；
- Compaction manifest 与最小 Summary → ContextItem reconstruction。

### 数据流变化

```text
ContextBuilder
  → Compaction Decision
  → ContextCompressor / Validator
  → ContextSelector
  → ContextBudgetManager
  → Supervisor dynamic prompt
```

原始 messages、checkpoint、trace 和 evidence 保持不变。

### 测试结果

- Compaction 专项：7 passed。
- Context + Memory + Identity：41 passed。
- 仓库 `tests/`：165 passed。
- Annotation integration：9 passed。
- compileall：passed。
- 全量 pytest 仍因当前环境缺少 `langchain_core` 在 benchmark integration collection 阶段阻断，未标记为通过。

### Benchmark

- 5 条 120–200 step trajectories；
- full ContextItems：103,390 tokens；
- compacted Context：6,970 tokens；
- token reduction：93.2585%；
- Working Memory preservation：100%；
- SummaryMetadata validity：100%；
- compaction success：100%；
- original history retention：100%。

### 已知限制

- 摘要为确定性规则生成且只在 model-call 内存在；
- 未实现 Artifact Store、Summary merge/TTL/删除或 provider 精确 tokenizer；
- MessagesState checkpoint 仍增长；
- 未完成真实 LangGraph Server/provider model 端到端回归。

### 回滚

移除 ContextRuntime compaction 分支、Supervisor 参数传播、配置、模块、tests/benchmark/docs；没有数据库或 checkpoint 迁移。

## Phase 3.1 — Memory Delta Runtime

### 修改文件

- 新增 `memory/delta/`：`MemoryUpdate`、canonical semantic fingerprint 和 Delta detector。
- 修改 `memory/working/updater.py`：Candidate 后先计算 Delta；No-op 跳过 Policy、Persist 和 lifecycle。
- 修改 `agents/support_workflow.py`：No-op 时不写 Working Memory/checkpoint lifecycle partial update。
- 新增 100 次重复更新 benchmark、Delta tests 和 `docs/PHASE3_1_MEMORY_DELTA.md`。
- 更新 Phase 2 benchmark、风险文档和 Working Memory 文档。

### 新增能力

- Working Memory SHA-256 语义 fingerprint；
- `changed_fields`、`additions`、`removals` 和业务 reason；
- timestamp-only / order-only No-op detection；
- lifecycle records 携带可解释 Delta；
- 重复状态不执行 Policy、不 Persist、不生成 lifecycle record。

### 数据流变化

```text
WorkingMemory Candidate
  → Memory Delta
  → No-op Detection
  → Policy
  → Persist / checkpoint
```

### 测试结果

- Delta + Working Memory + Context + Identity：34 passed。
- 仓库 `tests/`：158 passed。
- Annotation integration：9 passed。
- compileall：passed。
- 全量 pytest 仍因当前环境缺少 `langchain_core` 在 benchmark integration collection 阶段阻断，未标记为通过。

### Benchmark

- 相同状态重复处理 100 次；
- Phase 2 估算 lifecycle records：300；
- Phase 3.1 实际 lifecycle records：0；
- No-op：100；
- 重复更新 lifecycle 降幅：100%；
- 随后一次真实变化正常 Persist，并产生 3 条 lifecycle record。

### 已知限制

- 仅覆盖 Working Memory；
- Delta 只进入 lifecycle attributes，不是独立 Store；
- 尚未实现 MemoryFact confidence；
- 未完成真实 LangGraph managed checkpoint 回归。

### 回滚

移除 Delta detector 和 attributes，恢复 Extractor → Policy → Persist 以及 support workflow 的旧写回逻辑；没有数据库迁移。

## Phase 2 — Working Memory Runtime

### 修改文件

- 新增 `memory/working/`：model、structured extractor、policy/updater、serializer、in-memory lifecycle adapter。
- 修改 `agents/support_workflow.py`：现有节点真实生成并 checkpoint Working Memory。
- 修改 `context_engine/builder.py`：注入 `ContextItemType.MEMORY` 并生成 RETRIEVED event。
- 修改 `context_engine/selector.py`：Working Memory 优先于 workflow/evidence/history。
- 新增 50 轮 benchmark、tests 和 `docs/PHASE2_WORKING_MEMORY.md`。

### 新增能力

- checkpoint-safe Working Memory；
- Existing State → Candidate → Policy → Persist/Update；
- lifecycle records；
- Context Runtime injection；
- 20 轮 checkpoint recovery；
- messages/evidence/tool/trace 污染防护。

### 数据流变化

```text
support workflow structured state
  → WorkingMemoryExtractor
  → WorkingMemoryPolicy
  → lifecycle adapter
  → IntermediateState.working_memory
  → checkpoint
  → ContextBuilder
  → ContextItem(MEMORY)
  → Selector/Budget
  → supervisor dynamic prompt
```

### 测试结果

- Phase 2 + Context：22 passed。
- 仓库 `tests/`：146 passed。
- Annotation integration：9 passed。
- compileall：passed。
- 全量 pytest 因当前环境缺少 LangChain/LangGraph 在 collection 阶段阻断，未标记为通过。

### Benchmark

- 50 turns；
- final prompt 12,980 → 724 estimated tokens；
- cumulative 330,568 → 36,186；
- reduction 89.0534%；
- structured task-state completion 100% → 100%；
- required-state loss 0。

该结果不是 LLM 回答正确率。

### 已知限制

- 未实现 Conversation/Long-term/Artifact Memory；
- MessagesState checkpoint 仍增长；
- adapter 为进程内实现；
- session_id 尚未绑定 thread_id；
- 未执行真实 LangGraph deployment checkpoint 回归。

### 回滚

移除 Working Memory state、workflow updater、Builder injection、`memory/working/`、tests/benchmark/docs；没有数据库迁移。

## Phase 1 Hardening — Memory Lifecycle Hook Contract

### 修改文件

- 修改 `context_engine/models.py`：新增 Memory lifecycle event/state、metadata、audit record 和 hook Protocol。
- 修改 `context_engine/__init__.py`：导出生命周期公共契约。
- 新增 `tests/context_engine/test_memory_lifecycle_contract.py`。
- 新增 `docs/PHASE1_MEMORY_LIFECYCLE_HARDENING.md`。
- 更新 `docs/PHASE1_CONTEXT_RUNTIME.md`。

### 新增能力

- 为 `Memory Candidate → Policy → Persist → Context Injection` 预留稳定状态与事件契约；
- 区分 lifecycle event 与 persistent state；
- `MemoryMetadata` checkpoint/log-safe roundtrip；
- `MemoryLifecycleRecord` 记录 actor、reason、occurred_at 和扩展 attributes；
- `MemoryLifecycleHook` callable Protocol。

### 数据流变化

当前业务数据流不变。没有 Memory Store、Extractor、Policy Engine、事件 dispatcher 或自动 Context Injection。新增模型只作为未来组件之间的公共契约。

### 测试结果

- `python -m compileall -q context_engine tests/context_engine`：通过。
- 生命周期新增测试：5 passed。
- `python -m pytest -q tests/context_engine`：15 passed。
- `python -m pytest -q tests`：139 passed。
- Annotation integration：9 passed。
- 全量 `python -m pytest -q`：仍因当前环境缺少 `langchain_core` 在 collection 阶段阻断。

### 已知限制

- 只定义 contract，不产生、发布或持久化 lifecycle event；
- 没有事件顺序验证、TTL 执行、删除执行器、tenant/ACL/PII policy；
- Future Memory 写入必须经 Candidate/Policy，当前阶段不实现 Store。

### 回滚

删除新增 lifecycle 模型/导出/测试/文档即可。没有持久化迁移。

## Phase 1 Hardening — Memory / Summary Contract Reservation

### 修改文件

- 修改 `context_engine/models.py`：预留 `MEMORY`、`MEMORY_SUMMARY`、`USER_PROFILE`；新增 `SummarySourceRange`、`SummaryMetadata` 和可审计 Summary 判定。
- 修改 `context_engine/builder.py`：接收并校验 SummaryMetadata；旧 Summary 标记为 missing/invalid，并声明为不具备压缩评测资格。
- 修改 `context_engine/selector.py`：为未来 Memory 类型预留稳定展示顺序。
- 修改 `context_engine/__init__.py`：导出 Summary 元数据模型。
- 新增 `tests/context_engine/test_context_contract_hardening.py`。
- 更新 `docs/PHASE1_CONTEXT_RUNTIME.md`。

### 新增能力

- Context API 无破坏性预留 Memory 类型；
- Future producer 小写类型输入兼容；
- Summary 来源范围、生成器、置信度、生成时间和压缩成本的结构化契约；
- `tokens_saved` / `compression_ratio` 计算；
- 旧占位 Summary 与可审计 Compaction Summary 明确区分。

### 数据流变化

业务数据流不变。仅当 state 提供 `context_summary_metadata` 或 `conversation_summary_metadata` 时，Builder 会将其校验并附加到 Summary `ContextItem`；没有合法元数据的 Summary 仍可兼容展示，但会被标记为 `eligible_for_compaction_metrics=false`。未来 evaluator 必须据此过滤。

### 测试结果

- `python -m compileall -q context_engine tests/context_engine`：通过。
- `python -m pytest -q tests/context_engine`：10 passed。
- `python -m pytest -q tests`：134 passed。
- `python -m pytest -q evals/tests/test_annotation_pipeline_integration.py`：9 passed。
- 全量 `python -m pytest -q`：仍因当前环境缺少 `langchain_core` 在 collection 阶段阻断。

### 已知限制

- 未实现真实 Memory Store、Memory extraction/retrieval 或 Compactor；
- SummaryMetadata 只做结构和基本数值校验，未做摘要语义一致性验证；
- 预留类型不会被 Phase 1 Builder 自动生成。

### 回滚

删除新增 enum 值和 Summary 元数据模型、恢复 Builder/Selector、删除 hardening tests 即可。没有持久化迁移；但进入后续阶段后不建议回滚这些公共契约。

## Phase 1 — Context Runtime Layer

### 修改文件

- 新增 `context_engine/models.py`：统一 ContextItem、类型和选择 manifest。
- 新增 `context_engine/builder.py`：MessagesState/KnowledgeState/workflow state 转换、prompt rendering、active-turn message view。
- 新增 `context_engine/selector.py`：required/priority 选择和重复信息去重。
- 新增 `context_engine/budget.py`：`max_tokens` 硬预算和重要项截断。
- 新增 `context_engine/__init__.py`：Context Runtime 公共入口。
- 修改 `agents/conversation_supervisor.py`：dynamic prompt 和 model-call boundary 接入 Context Runtime。
- 修改 `agents/support_workflow.py`：真实维护 `workflow_state` 和 `unresolved_slots`。
- 修改 `config.py`、`.env.example`：增加 `LIORIN_CONTEXT_MAX_TOKENS`。
- 修改 `pyproject.toml`：将 `context_engine` 纳入 wheel package。
- 新增 `tests/context_engine/test_context_runtime.py`。
- 新增 `docs/PHASE1_CONTEXT_RUNTIME.md`。

### 新增能力

- 统一 ContextItem 表示；
- MessagesState/KnowledgeState/workflow state 统一转换；
- required/priority/dedup selection；
- provider-neutral token budget；
- Supervisor 历史消息模型可见窗口；
- Evidence reference 去重；
- context selection manifest。

### 数据流变化

```text
原：完整 MessagesState → Supervisor model

现：MessagesState / workflow / KnowledgeState refs
    → ContextBuilder
    → ContextSelector
    → ContextBudgetManager
    → dynamic prompt
    + 当前轮次原始 messages
    → Supervisor model
```

完整消息、Evidence、trace、metadata 和 source 仍保存在原 state/trace 中。

### 测试结果

- `python -m compileall -q context_engine agents config.py`：通过。
- `python -m pytest -q tests/context_engine/test_context_runtime.py`：5 passed。
- `python -m pytest -q tests`：134 passed（包含 Phase 1 hardening）。
- `python -m pytest -q evals/tests/test_annotation_pipeline_integration.py`：9 passed。
- 全量 `python -m pytest -q`：因环境缺少 `langchain_core` 在 collection 阶段阻断。
- 使用既有隔离 stub 执行 benchmark integration：3 passed，1 failed；失败原因是 stub `StateGraph` 不支持 `invoke`。

### 已知限制

- 未压缩 LangGraph checkpoint 中的完整 MessagesState；
- 未移除 KnowledgeState 中的 Evidence 正文副本；
- 未实现 Memory Store、Artifact Store、长期记忆或删除治理；
- token 估算不是 provider 精确 tokenizer；
- 当前环境无法完成真实 LangChain/LangGraph 端到端测试。

### 回滚

删除 Context Runtime middleware、恢复原 Supervisor dynamic prompt、移除新增 state/config 字段并删除 `context_engine/` 即可。没有数据库迁移或持久数据格式升级。

## Phase 2 Risk Contract — Identity, Delta, and Fact Confidence

### Modified files

- Added `docs/PHASE2_WORKING_MEMORY_RISKS.md`.
- Updated `docs/PHASE2_WORKING_MEMORY.md` with explicit pre-Phase 3 gates.
- Updated `CHANGELOG.md`.

### Recorded architecture gates

- A canonical `IdentityContext` must map tenant, user, conversation, LangGraph thread, and runtime session before cross-session/durable Memory injection.
- Working Memory requires semantic delta/no-op detection before durable persistence or an external audit sink; the existing 120-record cap is not deduplication.
- Facts require per-fact source, confidence, verification, and checkpoint migration before promotion to Long-term Memory.

### Runtime and data flow

No runtime, state schema, Agent, Retrieval, Evidence, Governance, Evaluation, or deployment code changed. Phase 2 remains checkpoint-local Working Memory.

### Tests

Documentation-only hardening. No new pytest result is claimed. Python source hashes were checked unchanged during packaging.

### Known limitations

The three contracts are recorded but not implemented. The system must not be represented as enterprise-governed durable Memory until their acceptance gates are met.

### Rollback

Remove the risk document and the appended references. No data migration is involved.

## Phase 3.0 — IdentityContext Foundation

### 修改文件

- 新增 `identity/models.py`：定义 checkpoint-safe `IdentityContext`。
- 新增 `identity/resolver.py`：集中解析 Runtime、checkpoint、principal 和 Phase 2 session 身份。
- 新增 `identity/__init__.py`，并将 `identity` 纳入 wheel package。
- 修改 `agents/support_workflow.py`：在真实 Working Memory 更新链路解析并持久化 identity。
- 修改 `context_engine/models.py`：ContextItem、SummaryMetadata、MemoryLifecycleRecord 支持 identity。
- 修改 `context_engine/builder.py`：为所有当前 ContextItem 附加已持久化身份。
- 修改 `memory/working/updater.py`：Working Memory lifecycle 记录身份归属。
- 修改 `memory/working/serializer.py`：checkpoint payload 支持 identity，并校验 session 一致性。
- 新增 `tests/identity/test_identity_context.py`；更新 workflow integration test。
- 新增 `docs/PHASE3_0_IDENTITY_CONTEXT.md`；更新 Phase 2 风险状态。

### 新增能力

- tenant/user/conversation/thread/session 的统一身份契约；
- JSON-safe checkpoint roundtrip；
- LangGraph Runtime thread 与 server user 的集中解析；
- Phase 2 session 向 IdentityContext 的兼容迁移；
- 跨 thread、tenant、established user、conversation、session 冲突检测；
- Context、Summary 和 Memory lifecycle 身份归属。

### 数据流变化

```text
Runtime state / LangGraph execution info
    → IdentityResolver
    → IdentityContext
    → IntermediateState checkpoint
    → Working Memory lifecycle + ContextItem metadata
```

没有 Memory Store、Long-term Memory、User Profile、ACL 或权限执行器。

### 测试结果

- `python -m pytest -q tests/identity tests/context_engine tests/memory/working`：29 passed。
- `python -m pytest -q tests`：153 passed。
- Annotation integration：9 passed。
- compileall：passed。
- 全量 pytest：当前环境缺少 `langchain_core`，在 benchmark integration collection 阶段失败。

### 已知限制

- identity 是归属契约，不是认证/授权；
- anonymous/public fallback 仍需后续 policy 限制；
- identity 尚未显式传播到专业子 Agent 和 Artifact permission boundary；
- 当前环境未执行真实 LangGraph Server checkpoint 回归。

### 回滚

删除 identity package 和关联 state/metadata 字段，恢复 Working Memory updater/serializer 签名即可。没有数据库迁移；新增 checkpoint 字段可由旧代码忽略。

## Phase 6 — Memory Governance, Evaluation, and Production Hardening

### Modified files

- Added `storage/interfaces.py`, `storage/memory_backend.py`, `storage/artifact_backend.py` and `storage/__init__.py`.
- Added `governance/acl.py`, `governance/policy.py`, `governance/audit.py` and `governance/lifecycle.py`.
- Added `metrics/memory.py` and `metrics/__init__.py`.
- Added `evaluators/memory_governance.py` and `evals/memory_governance_benchmark.py`.
- Added `tests/governance/*` and `docs/PHASE6_MEMORY_GOVERNANCE.md`.
- Updated `memory/facts/store.py`, `memory/facts/retriever.py`, `memory/facts/runtime.py`, `evaluators/__init__.py`, `governance/README.md` and `pyproject.toml`.

### New capabilities

- Backend-neutral Memory and Artifact persistence contracts with in-memory reference adapters.
- Runtime-enforced tenant/user ACL before Memory write, read, retrieval, correction and deletion.
- User, fact and tenant deletion plus policy-gated correction with lifecycle history retention.
- Real Runtime counters for retrieval, writes, no-op, policy, context tokens, failures and ACL blocks.
- Deterministic Memory precision, recall, wrong-injection, stale-use and forgetting evaluators.
- Fail-soft Agent paths for backend/retrieval/audit failures and fail-closed policy failures.
- Sensitive content, prompt-injection and content-format rejection before persistence.

### Data flow change

```text
Structured candidate
  -> Memory Delta
  -> ACL WRITE
  -> Governed Promotion Policy
  -> MemoryBackend
  -> Lifecycle Audit + Metrics

Context request
  -> ACL READ
  -> MemoryBackend search
  -> expiry/content confidence filters
  -> Context Runtime MEMORY items
```

Existing Context Runtime, Working Memory, Compaction, Artifact Registry, Retrieval and Evidence flows remain in place.

### Rollback

Restore the Phase 5 `memory/facts/store.py`, `retriever.py` and `runtime.py`; remove the new `storage`, `metrics`, governance and evaluation modules. There is no database migration because the delivered backend remains in-memory.

## Phase 7 — Production Agent Platform

### Modified files

- Added production PostgreSQL Memory/Artifact backends, Redis/local cache adapters and DB-API transaction helpers under `storage/backends/` and `storage/cache/`.
- Added retry, timeout, circuit breaker and resilient backend decorators under `reliability/`.
- Added replayable Agent traces, runtime events, tool instrumentation and unified metrics exporters under `observability/`.
- Added environment bootstrap, trusted request identity binding, health probes and FastAPI deployment surface under `production/`.
- Added the unified Dataset → Runtime → Trace → Evaluator → Report adapter under `eval_platform/`.
- Added Docker Compose deployment assets under `deploy/`.
- Added `evals/production_benchmark.py`, `tests/production/*` and `docs/PHASE7_PRODUCTION_AGENT_PLATFORM.md`.
- Minimally instrumented the existing Supervisor, Context Runtime, Long-term Memory Runtime and Artifact Runtime; their business behavior and public state models remain compatible.

### New capabilities

- Runtime-selectable InMemory/PostgreSQL persistence without business-code backend checks.
- Transactional Memory Fact mutation plus lifecycle audit outbox.
- Redis read-through cache with TTL and mutation invalidation; cache is never the source of truth.
- Retry, timeout, circuit breaker and graceful degradation around Backend and Supervisor tool calls.
- Replayable request traces covering Agent, Context, Tool, Memory, Artifact and Backend events.
- Unified quality, cost, performance and reliability metrics with Prometheus/OpenTelemetry exporter interfaces.
- Unified evaluation runner reusing existing Liorin evaluators.
- Docker deployment for Agent API, PostgreSQL, Redis, OpenTelemetry Collector and Prometheus.

### Data flow change

```text
Deployment bootstrap
  -> Backend/Cache/Reliability selection
  -> existing Runtime default registries
  -> support graph
  -> Context/Memory/Artifact operations
  -> Trace + Metrics + Evaluation report
```

### Test result

- Production tests: 15 passed.
- Repository `tests/`: 212 passed.
- Annotation integration: 9 passed.
- compileall: passed.
- Full pytest remains blocked during the existing benchmark integration collection because the execution environment does not install `langchain_core`.

### Known limitations

- PostgreSQL/Redis are contract-tested but were not available as external services in the delivery environment.
- Audit outbox publishing, persistent trace storage, distributed locking and object storage remain future production adapters.
- The 1,000-request benchmark measures deterministic platform overhead without an external LLM or network services.

### Rollback

Set the backend to `memory`, disable Redis/observability, or restore the Phase 6 bootstrap and remove Phase 7 infrastructure packages. No checkpoint schema migration is required.
