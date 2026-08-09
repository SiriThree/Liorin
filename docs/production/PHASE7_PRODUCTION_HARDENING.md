# Production Hardening Phase 7

## 1. Phase 7 Summary

Phase 0–6 已经完成 Evaluation Platform 的工程收敛。本阶段没有增加新的 Evaluation domain、metric 或 framework，而是重新检查真实 Production readiness，并修复 Structured Business Query 的真实 Production wiring。

当前结论：

- **Production Hardening: PARTIAL**
- **Formal Evaluation: BLOCKED / NOT RUN**
- Safe structured business tool wiring: **implemented and regression-tested**
- Real Support Graph / Knowledge / Structured / Mixed smoke: **BLOCKED by runtime dependencies**
- Real Judge: **BLOCKED**
- Formal Validation: **NOT RUN**

本阶段没有用 mock Agent、stub Judge、fixture metric、历史 `-95.2%` 或 test count 代替正式质量结果。

## 2. Initial Production Readiness

Phase 7 重新执行，而不是继承 Phase 6 状态：

```text
Python 3.13.5
uv 0.10.0
langchain       MISSING
langchain_core  MISSING
langgraph       MISSING
pymilvus        MISSING
Support Graph   BLOCKED at import
```

首次失败点仍在 Production Python dependency layer，而不是 Evaluation runner。

## 3. Dependency Audit

依赖事实来源：

```text
pyproject.toml
+
uv.lock
```

仓库没有 `requirements.txt` / `requirements-dev.txt` 作为第二套 source of truth。

`pyproject.toml` 中 Production main dependency 保留真实 runtime 所需 LangChain/LangGraph/Milvus/provider/httpx 等包。

Phase 6 已将：

```text
agentevals
openevals
```

迁移到 `legacy-evaluation` optional extra。Phase 7 再次扫描 Python source/tests，真实 runtime import count 仍为 0，因此没有把它们重新放回 main dependency。

## 4. Packaging / Lock Fix

当前 `pyproject.toml` 的依赖角色已经正确，但 `uv.lock` 仍是旧 resolution：

```text
missing main dependencies in root lock role:
- httpx
- jieba
- pyyaml

legacy optional dependencies still reflected as root/main:
- agentevals
- openevals
```

实际执行 `uv lock --check` 失败。当前 package registry 无法解析 `httpx`；显式使用 public PyPI 时当前环境也无法完成 DNS/network resolution。

因此：

- 没有手工修改 lock hash；
- 没有删除真实 Production dependency 来让 lock 变绿；
- 没有伪造新的 `uv.lock`；
- dependency lock 状态保持 **BLOCKED / STALE**。

## 5. Production Graph Import

实际执行：

```bash
PYTHONPATH=. python -c "import deployments.support_agent_graph"
```

结果：

```text
agents/knowledge_agent.py
from langchain.chat_models import init_chat_model
ModuleNotFoundError: No module named 'langchain'
```

因此：

```text
Graph import       BLOCKED
Graph construction NOT RUN
Graph smoke        NOT RUN
```

## 6. Production Bootstrap

`deployments/support_agent_graph.py` 仍通过真实 Production bootstrap 构造：

```text
bootstrap_production_runtime()
create_order_agent()
create_knowledge_agent()
create_support_agent()
```

Readiness 被拆分而不是要求所有外部系统一次 READY：

- Structured SQLite: **READY**
- Memory in-memory Production fallback: **READY**
- Artifact in-memory Production fallback: **READY**
- LangChain/LangGraph runtime: **BLOCKED**
- Milvus client/runtime: **BLOCKED**
- Model provider: **BLOCKED**
- Judge provider: **BLOCKED**

## 7. Structured Business Tool Audit

Phase 7 重新确认原始真实缺口不是一个简单工具名问题。

旧状态：

```text
Order Agent
→ execute_sql
→ arbitrary SQL entrypoint is fail-closed
```

同时 Supervisor 调用 Order Agent 时只传递 query/messages，没有传递经过验证的 `customer_id / identity_context / structured permission`。因此即使直接把 tool list 改成 `execute_sql_template`，真实调用仍会因缺 Principal 而 fail closed。

本阶段修复了完整链路：

```text
Support Workflow verifies customer
→ mints internal structured:read:self capability
→ Supervisor ToolRuntime hidden state
→ OrderAgentState
→ execute_sql_template ToolRuntime
→ tenant/customer/permission/owner authorization
→ read-only parameterized template
→ structured result
→ stable evidence trace
```

## 8. execute_sql Legacy Status

`tools.database.execute_sql` 重新审计后确认：

- 不执行输入 SQL；
- 永远 fail closed；
- 产生 `ATTEMPT_BLOCKED` security decision；
- 只保留 legacy compatibility / safety fixture compatibility。

Production Order Agent 不再注册它。

最终状态：**DEPRECATE, KEEP FOR COMPATIBILITY**。

没有 DELETE，因为历史 tests/evaluation fixtures 仍引用其安全语义。

## 9. execute_sql_template Security Contract

`execute_sql_template` 现在正式满足：

- no arbitrary SQL;
- fixed template allowlist;
- parameterized SQL;
- hidden `ToolRuntime.state` principal;
- verified `IdentityContext` required;
- tenant-aware;
- verified customer ownership;
- `structured:read:self` permission required;
- entity-scoped order/ticket ownership check;
- read-only SQLite (`mode=ro`, `query_only`, restrictive authorizer);
- structured result;
- stable evidence refs;
- authorization trace;
- fail closed on missing/invalid identity, permission, template or entity.

Model-visible arguments只有：

```text
template_id
entity_id (only when required by the selected template)
```

模型不能提供 tenant/customer/permission，也不能提供 SQL text。

## 10. Order Agent Tool Wiring

`agents/order_agent.py` 已做最小接口兼容改造：

```text
BEFORE:
LLM writes SELECT SQL
→ execute_sql

AFTER:
LLM selects allow-listed template_id/entity_id
→ execute_sql_template
```

新增 `OrderAgentState`：

```text
customer_id
tenant_id
identity_context
structured_permissions
```

这些字段由上游可信 runtime state 注入，不是模型 tool arguments。

`ORDER_AGENT_BASE_TOOLS` 现在只包含：

```text
execute_sql_template
```

没有趁机重写 Agent 架构或行为调优。

## 11. Structured Evidence Trace

Phase 3 已冻结 Structured Evidence identity：

```text
record:<record_type>:<record_id>#<field_path>
```

Phase 7 发现通用 Trace sanitizer 会把原始 `ORD-...` 等业务 ID redaction 成同一个 placeholder，导致 identity 失去唯一性。

因此改为 privacy-preserving stable identity：

```text
record:order:hash:<deterministic_digest>#order_date
record:ticket:hash:<deterministic_digest>#status
record:warranty:hash:<deterministic_digest>#status
```

原始 business record ID 不写入 Evaluation Trace。

Evaluation matcher 使用相同 deterministic normalization，因此 Canonical Gold 的原始 `record_id` 仍可与 Trace hash identity 精确匹配。

本阶段 test 已覆盖 Order/Ticket/Warranty structured trace contract；真实 Agent-level trace smoke 仍因 Production runtime BLOCKED 而 NOT RUN。

## 12. Authorization

真实授权链现在为：

```text
Gateway/runtime IdentityContext
→ tenant identity
→ Support customer verification
→ parameterized email lookup bound to tenant
→ verified customer_id
→ structured:read:self capability
→ Supervisor hidden ToolRuntime state
→ Order Agent hidden state
→ execute_sql_template
→ tenant/customer/entity ownership authorization
```

同时修复了原 `validate_customer_email()` 的字符串拼 SQL：现在复用 parameterized `lookup_customer_by_email()`，并拒绝 tenant mismatch。

`IdentityContext.user_id` 与业务 `customer_id` 保持不同 namespace；Trace actor user 使用 gateway user identity，业务 owner 以 hashed customer owner ref 记录，避免错误比较两个 ID namespace。

## 13. Knowledge Flow Smoke

**NOT RUN / BLOCKED**。

原因：Support Graph 无法 import，尚未到 model/retrieval execution 阶段。

没有使用 mock Knowledge Agent 代替真实 smoke。

## 14. Structured Flow Smoke

Production Graph 级 private structured query：**NOT RUN / BLOCKED**。

但是本地真实 SQLite + safe template component regression 已执行，验证：

- same tenant + same owner allow;
- wrong owner deny;
- wrong tenant deny;
- missing permission deny;
- invalid template deny;
- injection-like entity parameter does not become SQL;
- valid query returns structured data;
- ALLOW_READ security trace exists;
- stable hashed evidence ref exists;
- raw order identifier is not persisted in trace.

这只能证明 structured tool contract，而不是 Support Graph end-to-end smoke。

## 15. Mixed Flow Smoke

**NOT RUN / BLOCKED**。

Mixed Knowledge + Structured 需要同时具备：

```text
Production Agent runtime
Milvus/document retrieval
Structured business tool
real model
```

当前前两项尚未 READY，因此没有编造 mixed smoke。

## 16. Real Judge Readiness

Phase 2–5 的 `JudgeRuntime` 没有改写。

当前环境：

```text
langchain unavailable
LIORIN_JUDGE_MODEL not configured in process env
provider credential not configured in process env
```

`.env.example` 已明确增加独立 `LIORIN_JUDGE_MODEL` 配置，Production model 和 Judge model 不再隐式绑定。

Real Judge：**BLOCKED**。

## 17. Judge Calibration

以下已有 calibration contracts 保留：

```text
answer_correctness_v1
claim_extraction_v1
claim_evidence_entailment_v1
context_relevance_v1
prompt_injection_outcome_v1
```

Real calibration：**NOT RUN**。

原因：real Judge provider BLOCKED。

没有把 structured-output unit/stub tests 当真实 agreement。

## 18. Canonical Dataset Readiness

Phase 7 Doctor 重新读取实际数据：

```text
Canonical fully eligible legacy: 39
Validation canonical:           5
Formal safety candidates:       3
Formal multi-turn sessions:     0
Recovery challenge:             NOT READY
Trusted TEST:                   NOT PRESENT
```

没有自动生成/Review 新数据。

## 19. Formal Evaluation Readiness

Formal run 的 required gate 尚未满足：

```text
Production Runtime    BLOCKED
Real model            BLOCKED
Milvus/retrieval      BLOCKED
Real Judge            BLOCKED
Validation Gold       READY
Gold Isolation        PASS via regression
Single Execution      PASS via regression
```

所以 Formal Evaluation Readiness：**BLOCKED**。

## 20. One-case Formal Smoke

**NOT RUN**。

按照运行协议，在 Production Runtime / retrieval / model / Judge readiness 未通过前没有执行 Validation 1-case。

没有 fallback 到 mock。

## 21. Development Evaluation

**NOT RUN**。

没有用 development fixture 或 component test 代替 3–10 case real Production development run。

## 22. Validation Evaluation

**NOT RUN**。

当前 Validation Gold 数仍为 `N=5`，但 Production/Judge gate 未满足，因此没有 numerator、denominator 或 Task Success。

即使未来跑通，`N=5` 也只能标 `SMALL SAMPLE / EXPLORATORY`。

## 23. Formal Metrics

当前全部仍为：

```text
End-to-End Task Success             NOT RUN
Required Gold Evidence Recall       NOT RUN
Selected Evidence Precision         NOT RUN
Grounded Claim Rate                 NOT RUN
First-pass Failure Recovery Rate    NOT RUN
Safety Pass Rate                    NOT RUN
Context Quality-Cost                NOT RUN
Memory Contamination Rate           NOT RUN
Failure Attribution Coverage        NOT RUN
Ablation Gain                       NOT RUN
```

## 24. Resume-safe Metrics Status

`docs/evaluation/RESUME_SAFE_METRICS.md` 继续保持：

```text
SAFE_TO_USE QUALITY METRICS: NONE
```

Phase 7 的 `377 passed / 2 skipped`、Structured Tool tests、dataset counts 都是 Engineering evidence，不是 formal Agent quality metrics。

## 25. Regression Baseline Status

Baseline Registry 仍为空。

原因：尚无 `VALID` formal Production run。

没有自动 promote，也没有基于 `N=5` 建长期 release baseline。

## 26. Tests

实际执行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider tests/evaluation
# 163 passed, 2 skipped

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider \
  tests/evaluation/test_phase7_production_hardening.py \
  tests/test_enterprise_governance_stage4.py
# 44 passed, 2 skipped

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. pytest -q -p no:cacheprovider tests
# 377 passed, 2 skipped

python -m compileall -q .
# PASS
```

两个 SKIP 都是当前缺 real LangChain runtime 的 Production/Judge integration tests，并非被伪装成 PASS。

## 27. Actual Results

真实工程结果：

- Full repository regression: **377 PASS / 2 SKIP**.
- Evaluation regression: **163 PASS / 2 SKIP**.
- Structured Tool + Governance focused: **44 PASS / 2 SKIP**.
- Compileall: **PASS**.
- SQLite production dataset connectivity: **READY**.
- Structured tables verified: customers/orders/order_status_events/tickets/ticket_events/warranty_cases 等。
- Local DB counts observed during readiness: customers 300, orders 1500, order status events 7296, tickets 420, ticket events 1576, warranty cases 140.
- Production Support Graph import: **BLOCKED**.
- Real Judge: **BLOCKED**.
- Formal Agent quality: **NOT RUN**.

## 28. Blocked / NOT RUN

### BLOCKED

- `uv.lock` refresh/resolution in current package/network environment;
- LangChain/LangGraph runtime imports;
- pymilvus runtime;
- Production Support Graph import/construction;
- real model provider;
- real Judge provider;
- real Milvus retrieval smoke.

### NOT RUN

- Knowledge QA Production smoke;
- private Structured Support Graph smoke;
- Mixed Knowledge + Structured smoke;
- real Judge calibration;
- 1-case formal eval;
- small development eval;
- validation eval;
- all formal quality metrics.

## 29. Remaining Production Gaps

1. Regenerate `uv.lock` from current `pyproject.toml` in a network/package-registry environment that can resolve all real Production dependencies.
2. Install/sync LangChain/LangGraph/Milvus/provider packages and verify Support Graph import.
3. Configure real `LIORIN_MODEL` provider credential and execute model smoke.
4. Verify Milvus connectivity/index and Knowledge retrieval flow.
5. Configure independent `LIORIN_JUDGE_MODEL` and execute real Judge calibration.
6. Execute Support Graph structured query smoke to prove the newly wired safe tool inside the actual Agent runtime.
7. Execute Mixed Knowledge + Structured smoke.
8. Phase 4 multi-turn data still needs real human review; Recovery Challenge still needs Gold review; Trusted TEST still absent.
9. The current customer verification mechanism is tenant-bound and parameterized, but business `customer_id` remains a separate identity namespace from gateway `user_id`; production deployment must preserve that mapping contract.

## 30. Next Step

Phase 7 should not expand Evaluation further.

The immediate next operational sequence is:

```text
network/package registry capable environment
→ uv lock
→ uv sync
→ Support Graph import
→ graph construction
→ Knowledge smoke
→ Structured smoke
→ Mixed smoke
→ real Judge smoke/calibration
→ doctor READY
→ 1-case formal eval
→ development subset
→ N=5 exploratory validation
```

只有这条链真实通过以后，才应该更新 formal metrics、Final Evaluation Report、Resume-safe provenance 或考虑第一个 regression baseline。
