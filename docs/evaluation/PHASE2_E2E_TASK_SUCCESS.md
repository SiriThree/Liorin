# Phase 2：End-to-End Task Success、Criterion Evaluators 与 LLM Judge

## 1. Phase 2 Summary

Phase 2 状态：**PARTIAL**。

本阶段已经在 Phase 0 / Phase 1 冻结的唯一 Evaluation Core `eval_platform/` 上完成：

- 强类型 `CriterionJudgment`；
- formal `TaskSuccessEvaluator`；
- required criteria conjunction；
- Response / Agent / Tool / Authorization / Clarification / Handoff / Critical Fact / Minimum Grounding / Minimum Hallucination / Sensitive Leak evaluator；
- 可审计 LLM Judge Runtime；
- Judge Prompt versioning、structured output、retry/error/raw response contract；
- Evaluation Eligibility；
- Human Review Queue 导出；
- `score-existing-predictions`；
- Prediction / Judgment 物理分离；
- formal aggregate report 与 criterion coverage；
- 统一 `eval_platform.cli`；
- Judge calibration fixtures；
- Phase 0 single-execution 与 Phase 1 Gold Isolation/Canonical Dataset 回归。

Phase 2 **没有**重新设计 Canonical Dataset，也没有创建 `EvaluationV2` / `TaskSuccessV2` / `JudgeRecord2` 等平行类型体系。

正式不变量继续是：

```text
ONE CASE
  -> ONE PRODUCTION EXECUTION
  -> ONE TRACE
  -> ONE PREDICTION RECORD
  -> INDEPENDENT CRITERION EVALUATION
  -> BINARY / INCOMPLETE TASK JUDGMENT
```

本阶段没有生成正式 Validation Task Success 数字。原因不是 evaluator contract 缺失，而是当前容器无法导入真实 Production Graph 和真实 Judge provider：

```text
ModuleNotFoundError: No module named 'langchain'
```

此外，`uv sync --offline` 仍因本地 cache 缺少 `agentevals` 且网络禁用而失败。因此：

```text
Real Production Support Graph run     BLOCKED
Real LLM Judge run                    BLOCKED / NOT RUN
Formal Validation Task Success        NOT RUN
```

Stub/Fake Judge 只用于 Judge infrastructure tests，没有被包装成模型质量结果。

---

## 2. Production Evaluation Flow

正式链路现在为：

```text
CanonicalEvaluationSample
        |
        | Gold Isolation
        +-------------------------------+
        |                               |
        v                               |
RuntimeCaseInput                        |
        |                               |
        v                               |
ProductionEvaluationAdapter            |
        |                               |
        v                               |
ONE deployments.support_agent_graph    |
        |                               |
        v                               |
ONE AgentExecutionTrace                |
        |                               |
        v                               |
PredictionRecord <---------------------+
        |
        | frozen before scoring
        v
Criterion Evaluator Registry
        |
        +--> Deterministic evaluators
        +--> Independent LLM Judge
        +--> Trace/Safety evaluators
        |
        v
CriterionJudgment[]
        |
        v
TaskSuccessEvaluator
        |
        v
CaseJudgment
        |
        v
EvaluationRun + Formal Artifacts
```

`ProductionEvaluationAdapter` 仍然只接受 `RuntimeCaseInput`，不接受 `EvaluationSample` 或 Gold-bearing mapping。

Judge 只在 `PredictionRecord` 已经冻结之后执行。Judge 不会：

- 重新调用 `support_graph`；
- 重新调用 Knowledge Agent；
- 重新检索；
- 调 Tool；
- 修改 Prediction；
- 让 Production Agent 再回答一次。

`score_existing_predictions()` 进一步允许完全不调用 Production，只对已有 Prediction artifact 重新评分。

---

## 3. Criterion Evaluation Architecture

核心代码：

```text
eval_platform/contracts.py
eval_platform/criteria.py
eval_platform/task_success.py
eval_platform/judge.py
eval_platform/runner.py
```

Registry：

```text
SuccessCriterion
    -> CriterionEvaluator
```

当前 formal registry 覆盖：

```text
RESPONSE_TYPE_CORRECT
REQUIRED_AGENTS_CORRECT
REQUIRED_TOOLS_CORRECT
FORBIDDEN_TOOLS_NOT_CALLED
CRITICAL_FACTS_CORRECT
CRITICAL_FACTS_GROUNDED
CLARIFICATION_CORRECT
HANDOFF_CORRECT
AUTHORIZATION_CORRECT
NO_UNAUTHORIZED_ACCESS
NO_SENSITIVE_DATA_LEAK
NO_CRITICAL_HALLUCINATION
```

如果 required criterion 没有 evaluator，不允许静默跳过。Evaluation configuration / eligibility 必须暴露问题。

`ConditionalSuccessCriterion` 也不再是“定义了但不用”的字段。Phase 2 正式支持当前 Phase-1 contract 使用的有限表达式：

```text
clarification_required == true
handoff_required == true
authorization_required == true
```

未知 conditional expression 默认 fail closed。

---

## 4. CriterionJudgment Schema

Phase 2 在 `eval_platform.contracts` 中新增：

```text
CriterionStatus:
  PASS
  FAIL
  NOT_APPLICABLE
  NOT_EVALUATED
  ERROR

EvaluationMethod:
  DETERMINISTIC
  LLM_JUDGE
  HUMAN_REVIEW
  COMPOSITE
```

`CriterionJudgment`：

```text
criterion
status
evaluation_method
required
reason
evidence_refs
trace_refs
judge_record_id
error
metadata
```

不再允许 formal evaluator 只返回一个 `True / False`，因为后续 Failure Attribution 必须回答：

- 哪个 criterion 失败；
- 为什么失败；
- 用什么方法判断；
- 用了哪个 evidence / trace；
- 是否依赖 Judge；
- Judge infrastructure 是否失败。

`NOT_APPLICABLE` 与 `FAIL` 分离；`NOT_EVALUATED` / `ERROR` 与 `PASS` 分离。

若一个 **required** criterion 返回 `NOT_APPLICABLE`、`NOT_EVALUATED` 或 `ERROR`，Task Success 不会静默 PASS，而进入 `INCOMPLETE`（除非同时已有另一个 required criterion 明确 FAIL，此时已能确定任务失败）。

---

## 5. TaskSuccessEvaluator

正式实现：

```text
eval_platform/task_success.py::TaskSuccessEvaluator
```

输入：

```text
TaskSuccessContract
+
CriterionJudgment[]
```

输出：

```text
TaskSuccessResult:
  task_success
  required_criteria_total
  required_criteria_passed
  failed_criteria
  incomplete_criteria
  diagnostic_criteria
  reason
```

Task 状态：

```text
PASS
FAIL
INCOMPLETE
EXECUTION_ERROR
```

核心语义：

```text
all required criteria PASS
-> PASS

any required criterion FAIL
-> FAIL

required criterion ERROR / NOT_EVALUATED / NOT_APPLICABLE
and no decisive required FAIL
-> INCOMPLETE

Production execution failed
-> EXECUTION_ERROR
```

不存在：

```text
response = 0.2
facts = 0.3
grounding = 0.3
...
score >= 0.8 -> PASS
```

Diagnostic float 不参与 Task Success。

`task_success_bool` 只在：

```text
PASS -> true
FAIL -> false
```

对于：

```text
INCOMPLETE
EXECUTION_ERROR
```

为 `null`，避免把 evaluator infrastructure failure 偷转成 Agent quality failure。

---

## 6. Response Type Evaluation

实现：

```text
RESPONSE_TYPE_CORRECT
```

优先读取：

```text
PredictionRecord.response_type
vs
ExpectedBehavior.response_type
```

支持：

```text
ANSWER
CLARIFICATION
HANDOFF
REFUSAL
ERROR
```

当前 Production Trace 对 REFUSAL 等语义并非所有路径都有独立结构化 event，因此保留了一个**有界 fallback classifier**。Fallback 只用于目前缺少结构化 response semantic 的路径，并显式标记：

```text
evaluation_method = COMPOSITE
metadata.fallback_classifier = response_type_text_v1
```

它不是 LLM Judge，也不被伪装成纯 trace deterministic signal。

---

## 7. Agent / Tool Evaluation

### Agent

`REQUIRED_AGENTS_CORRECT` 从同一个 Production Trace 中读取 `agent_names`。

语义：

```text
required agents present
AND
forbidden agents absent
```

不比较没有被 Gold contract 要求的严格调用顺序。

### Tools

`REQUIRED_TOOLS_CORRECT` 和 `FORBIDDEN_TOOLS_NOT_CALLED` 只读取同一个 trace 中的真实 `TOOL_STARTED` 事实。

Evaluator **不会再次调用 Tool** 来确认结果。

额外 optional tool 不会自动造成 failure。

Structured business fact correctness 不由 tool name 代替，仍由 `GoldFact` 判断。

---

## 8. Authorization Evaluation

实现：

```text
AUTHORIZATION_CORRECT
NO_UNAUTHORIZED_ACCESS
```

输入来源优先是：

```text
AUTHORIZATION_DECISION trace events
workflow authorization state
observed evidence/resource refs
SafetyConstraint forbidden resources
```

不会通过：

```text
final answer contains "无权限"
```

直接推导安全 PASS。

如果 Trace 没有 authorization event：

```text
NOT_EVALUATED
error = MISSING_AUTHORIZATION_TRACE
```

而不是“没有异常所以安全”。

如果 trace 明确出现 unauthorized access / policy violation，或者 forbidden resource 已出现在 execution evidence 中，则 FAIL。

Phase 5 仍将负责完整 fail-anywhere Safety Evaluation；Phase 2 只冻结 Task Success 所需的基本 authorization contract。

---

## 9. Clarification / Handoff Evaluation

### Clarification

`CLARIFICATION_CORRECT` 使用：

```text
clarification_required
required_clarification_slots
Prediction response/action
final response
```

当 Gold 要求 clarification 时：

1. 必须实际触发 `CLARIFICATION`；
2. 必须询问必要 slot 或明确等价 slot；
3. slot 无法通过当前 bounded matcher 判定时，使用 `clarification_v1` Judge；
4. Judge 不可用时为 `NOT_EVALUATED`，不会把错误 slot 当 PASS。

当 Gold 明确 `clarification_required=false` 且 Agent 仍澄清时，输出：

```text
OVER_CLARIFICATION
```

作为 diagnostic；只有 Gold contract 真正要求该 criterion 时才决定 Task Success。

### Handoff

`HANDOFF_CORRECT` 使用：

```text
handoff_required
handoff_reason
response/action semantic
trace handoff reason
```

不只检查最终文本里有没有“人工客服”。

当 Gold 要求具体 handoff reason 但 trace 没有暴露 reason 时，返回 `NOT_EVALUATED`，而不是假定正确。

---

## 10. Critical Fact Correctness

正式 correctness 只使用 Phase-1 `GoldFact`，不使用：

```text
required_keywords
fact_coverage_proxy
```

`CRITICAL_FACTS_CORRECT` 根据 `comparison_mode` 分流：

### Deterministic

支持：

```text
EXACT
NORMALIZED_EXACT
NUMERIC
DATE
```

覆盖：

- exact string；
- normalized string；
- integer / numeric；
- date；
- boolean textual normalization；
- enum / order status / product model 等规范值。

### Semantic

```text
comparison_mode = SEMANTIC
```

必须进入独立 Judge：

```text
answer_correctness_v1
```

Judge 只得到完成这个 criterion 必要的字段：

```text
user query
gold semantic facts
final response
```

不默认得到 expected agent / expected tool / full hidden trace / unrelated Gold。

---

## 11. Minimum Grounding Criterion

Phase 2 实现的是：

```text
CRITICAL_FACTS_GROUNDED
```

这是 Task Success 所需的 minimum grounding PASS/FAIL，不是 Phase-3 完整 Grounded Claim Rate。

规则：

```text
GoldFact.supporting_evidence_ids
must be supported by evidence actually present in this Production execution
```

支持：

- `retrieved_evidence_ids`；
- `selected_evidence_ids`；
- canonical document ref；
- stable structured record ref；
- `alternative_group`。

因此可以出现：

```text
fact correctness = PASS
fact grounding   = FAIL
```

这两个维度明确分离。

### Alternative Evidence

同一个 `alternative_group` 中，命中任意人工/Gold 允许的 equivalent evidence 即可满足该组，不要求固定单 chunk。

### Structured Evidence

`TraceAdapter` 会在现有 Retrieval Trace 中把：

```text
db:<template>:<entity>
```

投影为稳定逻辑引用，例如：

```text
record:order:<order_id>
record:ticket:<ticket_id>
record:customer:<customer_id>
```

不会为了评分重新查询 DB。

### 已知限制

当前 `order_agent` 作为 specialist 的外层 tool invocation 能进入 unified trace，但其内部 SQL/structured tool result 并不保证都以 Retrieval evidence event 的形式进入 `TraceAdapter`。因此某些 Private / Mixed case 的 structured grounding 可能在真实运行时暴露为 evidence trace 缺口，而不是由 evaluator 再执行 DB 查询“补齐”。这是 Phase 2 保留的真实 observability 风险。

完整：

```text
claim extraction
claim-evidence entailment
Evidence Recall / Precision
Grounded Claim Rate
```

仍属于 Phase 3。

---

## 12. LLM Judge Architecture

实现：

```text
eval_platform/judge.py
```

核心 contract：

```text
JudgeConfig
JudgePromptVersion
JudgeRequest
JudgeResponse
JudgeRecord
JudgeRunMetadata
JudgeRuntime
JudgeProvider
LangChainStructuredJudgeProvider
```

`JudgeConfig` 保存：

```text
judge_name
provider
model
temperature
max_tokens
timeout
max_retries
prompt_version
schema_version
```

真实 provider lazy-load：

```text
langchain.chat_models.init_chat_model
```

因此 deterministic evaluator 不会因为当前缺少 LangChain 就完全不可测试。

Unit tests 使用 controlled stub provider 只测试 infrastructure，不产出正式质量指标。

---

## 13. Judge Prompt Versioning

当前 versioned prompt：

```text
answer_correctness_v1
clarification_v1
grounding_v1
hallucination_v1
```

没有使用一个 `general_judge_prompt` 判所有事情。

用途：

- `answer_correctness_v1`：semantic GoldFact correctness；
- `clarification_v1`：required missing slot 与 premature conclusion；
- `grounding_v1`：Phase-2 minimum grounding Judge contract / Phase-3 扩展接口；
- `hallucination_v1`：minimum critical contradiction / unsupported critical assertion。

Prompt version 写入 `JudgeRequest`、`JudgeRecord`、run metadata。

---

## 14. Judge Retry / Failure Semantics

Judge structured output 只接受合法 schema。

Phase 2 允许 Retry 的情况：

```text
timeout
provider error
invalid JSON
invalid structured schema
```

**不允许：**

```text
first valid judgment = FAIL
-> retry until PASS
```

Unit test 已明确验证：valid `FAIL` 只调用 Judge 一次。

所有 retry 都失败：

```text
CriterionStatus = ERROR
Task evaluation = INCOMPLETE
```

不会：

```text
Judge error -> PASS
```

`JudgeRecord` 保存：

```text
judge_record_id
case_id
criterion
model
provider
prompt_version
request_hash
structured_input
structured_result
rationale
raw_response
attempt_count
latency_ms
error
timestamp
```

`request_hash` 为稳定 SHA-256。

---

## 15. Gold Isolation

Production 和 Judge 是两个完全不同的边界。

### Production 可见

仅：

```text
RuntimeCaseInput:
  case_id
  query/messages
  identity
  config
  context
  metadata
```

### Production 不可见

```text
ExpectedBehavior
TaskSuccessContract
GoldEvidence
GoldFact
SafetyConstraint expected result
required_keywords
expected_answer
expected_source
...
```

### Judge 可见

Judge 可以在 Production execution 完成后看到完成**当前 criterion 所需的最小 Gold**。

例如 Fact Judge 不会默认看到 expected tool / agent；Clarification Judge 不会默认看到不相关 Gold。

Prediction artifact 继续通过 `assert_no_gold_leak()` 防止 Gold 进入运行产物。

---

## 16. Evaluation Eligibility

新增：

```text
EvaluationEligibilityStatus:
  ELIGIBLE
  MISSING_GOLD
  NEEDS_REVIEW
  UNSUPPORTED_CRITERION
  INVALID
```

Formal runner 在 Production execution 前先：

```text
validate_dataset()
-> evaluate_eligibility()
```

非法 Dataset fail closed。

Ineligible case：

- 不会 silently skip；
- 会产生显式 eligibility / CaseJudgment 状态；
- 不会调用 Production；
- 不进入正式 Task Success denominator。

### 当前真实数量

由：

```text
evals/scripts/build_phase2_evaluation_inventory.py
```

生成：

```text
evals/benchmark/data/canonical/phase2_evaluation_inventory.json
```

实际：

| Asset | Cases | ELIGIBLE | NEEDS_REVIEW |
|---|---:|---:|---:|
| `dev_v7_3_canonical_v1` | 34 | 34 | 0 |
| `validation_v7_3_canonical_v1` | 5 | 5 | 0 |
| `representative_seed_v1` | 15 | 0 | 15 |

所以当前 fully canonical legacy：

```text
39 ELIGIBLE
```

15 条 representative seed 继续是：

```text
SCHEMA / PIPELINE VALIDATION ONLY
NEEDS_REVIEW
```

没有因为 Phase 2 需要跑 evaluator 就伪造 `HUMAN_REVIEWED`。

另外，39 条 ELIGIBLE case 的完整 required contract **全部需要真实 LLM Judge**：

- dev 34 / 34；
- validation 5 / 5。

原因包括：

1. 39 条 legacy canonical 共 109 个 GoldFact，目前全部是 `SEMANTIC`；
2. 这些 case 的 contract 同时要求 `NO_CRITICAL_HALLUCINATION`，Phase 2 不允许用“关键词/事实出现”冒充 hallucination-free proof。

---

## 17. Aggregate Metric Definition

Formal report 实现：

```text
Overall End-to-End Task Success
Task Success by category
Task Success by subcategory
Task Success by difficulty
Execution Error Rate
Incomplete Evaluation Rate
Criterion Coverage
Eligibility Status
```

所有 rate 保存：

```text
numerator
denominator
rate
```

而不是只存百分比。

旧 component score 不会混入 Overall Task Success。

---

## 18. Task Success Denominator Policy

Phase 2 正式冻结 North Star denominator：

```text
Task Success
=
PASS
/
(PASS + evaluated FAIL + Production EXECUTION_ERROR)
```

具体处理：

### Agent / Production execution error

```text
execution_status = failed
-> TaskSuccessStatus.EXECUTION_ERROR
-> 从用户视角任务未完成
-> 计入 North Star denominator，按失败处理
```

### Evaluator / Judge infrastructure failure

```text
required criterion ERROR / NOT_EVALUATED
-> TaskSuccessStatus.INCOMPLETE
-> 不归罪于 Agent
-> 从 quality denominator 排除
-> 单独报告 Incomplete Evaluation Rate
```

### Invalid / missing Gold / needs review

```text
-> INELIGIBLE
-> 不调用 Production
-> 不进入 quality denominator
-> 显式统计原因
```

同时输出：

```text
attempted_task_success_diagnostic
```

作为诊断，但 North Star 仍只有一个正式语义。

---

## 19. Artifacts / Reports

每次 formal run 可以生成：

```text
evaluation_run.json
predictions.jsonl
judgments.jsonl
summary.json
summary.md
judge_records.jsonl
human_review_queue.jsonl
```

### Prediction artifact

`predictions.jsonl` 至少包含：

```text
case_id
run_id
trace_id
final_response
response_type
trace facts
runtime metrics
execution_status
execution_error
```

不含 Gold。

### Judgment artifact

`judgments.jsonl` 包含：

```text
case_id
run_id
execution_status
criterion_judgments
task_success_status
task_success_bool
failed_criteria
incomplete_criteria
trace_id
```

Prediction 与 Judgment 物理分离，通过 `case_id / run_id / trace_id` 关联。

### Summary

`summary.json / summary.md` 明确记录：

- dataset name / version / hash；
- eligible / ineligible；
- execution errors；
- incomplete evaluation；
- Overall Task Success numerator / denominator；
- by category；
- criterion coverage。

### Run metadata

记录：

```text
run_id
git_commit (不可获得时 null)
dataset_name
dataset_version
dataset_hash
evaluation_schema_version
evaluator_version
production_config_hash
model
embedding
judge_model
judge_provider
judge_prompt_versions
judge_run_metadata
timestamp
environment
denominator policy
```

无法获取的字段保存 `null`，不伪造。

---

## 20. Legacy Metric Compatibility

历史：

```text
macro_objective_score
objective_score
fact_coverage_proxy
```

继续只允许作为：

```text
LEGACY DIAGNOSTIC
```

`evals/benchmark/README.md` 已增加 Phase-2 迁移说明。

旧 `evals.benchmark.cli` 输出字段也继续命名为：

```text
legacy_macro_objective_score
```

而不是 formal Task Success。

旧 `eval_platform.evaluators.agent_evaluator()` 中的 runtime boolean 已在 Phase 0 语义降级为：

```text
self_reported_task_success_match
```

Phase 2 formal runner 完全不读取这个值作为 Task Success。

Formal 入口现在是：

```text
python -m eval_platform.cli validate ...
python -m eval_platform.cli run ...
python -m eval_platform.cli score-existing-predictions ...
python -m eval_platform.cli judge ...
python -m eval_platform.cli report ...
```

正式 `run` 支持：

```text
--dataset
--split
--category
--case-id
--limit
--output
--config
```

示例配置：

```text
evals/benchmark/configs/phase2_evaluation.example.json
```

默认 Judge `enabled=false`，不会用未配置 model 冒充真实 Judge。

---

## 21. Tests

### Evaluation suite

```bash
PYTHONPATH=. pytest -q tests/evaluation
```

最终结果：

```text
76 passed
```

覆盖：

- Phase 0 Production Adapter / Single Execution / Gold Isolation / Trace Consistency；
- Phase 1 Canonical Schema / Validator / Migration / Generated Assets；
- required conjunction；
- required FAIL；
- required ERROR；
- required NOT_APPLICABLE；
- execution error；
- Response Type；
- Agent；
- required/forbidden Tool；
- Authorization；
- missing authorization trace；
- Clarification；
- Handoff；
- exact/normalized/numeric/date/boolean/enum GoldFact；
- correctness vs grounding separation；
- alternative evidence；
- sensitive disclosure；
- minimum hallucination semantics；
- Judge structured output；
- invalid schema retry；
- timeout/provider failure；
- valid FAIL no retry-to-PASS；
- raw/prompt version persistence；
- JudgeRunMetadata；
- calibration dataset；
- single Production execution with Judge after Prediction freeze；
- score-existing-predictions no reexecution；
- prediction/judgment artifact separation；
- denominator policy；
- Human Review queue；
- Conditional Criteria；
- CLI；
- eligibility inventory。

### Broader compatibility regression

运行：

```bash
PYTHONPATH=. pytest -q \
  tests/evaluation \
  tests/production/test_production_platform.py \
  tests/production/test_production_benchmark.py \
  tests/governance/test_memory_governance.py \
  tests/governance/test_memory_governance_benchmark.py \
  tests/artifact/test_artifact_benchmark.py \
  tests/context_engine/test_context_contract_hardening.py \
  tests/context_engine/test_memory_lifecycle_contract.py
```

实际结果：

```text
114 passed in 1.71s
```

Phase-2 修改没有删除已有关键测试。

### Compile

```bash
PYTHONPATH=. python -m compileall -q .
```

结果：`PASS`。

### Canonical CLI validation

```bash
PYTHONPATH=. python -m eval_platform.cli validate \
  --dataset evals/benchmark/data/canonical/validation_v7_3_canonical_v1.json
```

结果：

```json
{
  "valid": true,
  "case_count": 5,
  "errors": []
}
```

---

## 22. Actual Results

### Code / contract regression

Phase-2 Evaluation tests：

```text
76 passed
```

更广泛 Phase 0/1 + Production Platform + Governance + Artifact + Context/Memory compatibility suite：

```text
114 passed in 1.71s
```

该数字只代表代码/契约回归，不代表 Agent answer quality。

### Data eligibility

```text
Legacy dev canonical         34 / 34 ELIGIBLE
Legacy validation canonical   5 / 5 ELIGIBLE
Representative seed           0 / 15 ELIGIBLE
                              15 / 15 NEEDS_REVIEW
```

### Judge dependency need

```text
Legacy dev requiring real Judge         34 / 34
Legacy validation requiring real Judge   5 / 5
```

### Formal model-quality result

```text
Validation End-to-End Task Success: NOT RUN
```

没有把 unit test、stub Judge、component benchmark 或 lexical proxy 包装成 Validation Task Success。

---

## 23. Production / Judge Blocked Items

### Production Graph

实际重新执行：

```bash
PYTHONPATH=. python -c "import deployments.support_agent_graph"
```

结果：

```text
ModuleNotFoundError: No module named 'langchain'
```

调用位置实际进入：

```text
deployments/support_agent_graph.py
-> agents/knowledge_agent.py
-> from langchain.chat_models import init_chat_model
```

因此：

```text
Production E2E execution = BLOCKED
```

### Real Judge Provider

实际重新导入：

```bash
PYTHONPATH=. python -c "from langchain.chat_models import init_chat_model"
```

同样：

```text
ModuleNotFoundError: No module named 'langchain'
```

因此：

```text
Real LLM Judge = BLOCKED / NOT RUN
```

### Offline dependency resolution

实际执行：

```bash
uv sync --offline
```

结果失败：

```text
agentevals was not found in the cache
network disabled
```

所以没有用 Mock Production 或 Stub Judge 改写成 PASS。

### Trusted Test

Phase 1 的信任模型仍然有效：

```text
DEVELOPMENT
VALIDATION
HISTORICAL_UNVERIFIED
```

仍然：

```text
NO TRUSTED TEST SPLIT YET
```

历史 `blind_test_inputs_v7_3` 没有被升级为 trusted test。

---

## 24. Phase 3 Stable Interfaces

Phase 3 Evidence Reliability / Agentic Recovery 可以直接依赖：

### Dataset / Gold

```text
CanonicalEvaluationSample
EvaluationSample
RuntimeCaseInput
ExpectedBehavior
TaskSuccessContract
GoldEvidence
GoldFact
SafetyConstraint
```

### Prediction / trace

```text
ProductionEvaluationAdapter
TraceAdapter
PredictionRecord

trace_facts:
  agent_names
  tool_names
  retrieved_evidence_ids
  selected_evidence_ids
  evidence_refs
  structured_evidence_refs
  verifier_actions
  recovery_actions
  handoff_reasons
  authorization_decisions
  retrieval_rounds
  model_calls
  tool_calls
```

### Formal judgments

```text
CriterionStatus
EvaluationMethod
CriterionJudgment
TaskSuccessStatus
TaskSuccessResult
TaskSuccessEvaluator
CaseJudgment
EvaluationRun
EvaluationEligibility
HumanReviewItem
```

### Judge

```text
JudgeConfig
JudgePromptVersion
JudgeRequest
JudgeResponse
JudgeRecord
JudgeRunMetadata
JudgeRuntime
```

### Runner / artifacts

```text
FormalEvaluationRunner.run()
FormalEvaluationRunner.score_existing_predictions()
build_formal_summary()
write_formal_artifacts()
read_prediction_jsonl()
```

Phase 3 应基于这些接口继续实现：

```text
Evidence Recall@K
Gold Evidence Recall
Selected Evidence Precision
claim extraction
claim-evidence entailment
Grounded Claim Rate
First-pass Failure
Recovery Action Distribution
Recovery Success within N rounds
```

不得为了 Evidence / Recovery 指标再次运行 Production Agent 或 Retrieval；所有 attribution 必须继续来自同一次 frozen Production execution trace。

---

## Code Changes Made in Phase 2

相对 Phase 1，主要代码改动：

```text
eval_platform/__init__.py                 modified
eval_platform/contracts.py                modified
eval_platform/production_adapter.py       modified
eval_platform/report.py                   modified
eval_platform/runner.py                   modified
eval_platform/validation.py               modified

eval_platform/calibration.py              added
eval_platform/cli.py                      added
eval_platform/criteria.py                 added
eval_platform/judge.py                    added
eval_platform/task_success.py             added

evals/benchmark/README.md                 modified
evals/benchmark/configs/phase2_evaluation.example.json added
evals/benchmark/data/calibration/judge_calibration_v1.json added
evals/benchmark/data/canonical/phase2_evaluation_inventory.json added
evals/scripts/build_phase2_evaluation_inventory.py added

tests/evaluation/test_phase2_task_success.py added
tests/evaluation/test_phase2_deterministic_criteria.py added
tests/evaluation/test_phase2_judge_runtime.py added
tests/evaluation/test_phase2_judge_calibration.py added
tests/evaluation/test_phase2_formal_runner.py added
tests/evaluation/test_phase2_cli_and_inventory.py added
tests/evaluation/test_phase2_conditional_criteria.py added
```

Production Agent Prompt、Retriever ranking、Verifier decision logic、Memory policy、Governance policy 没有为了提高 Evaluation 分数被修改。

---

## Phase 3 Entry Conditions

| Requirement | Status |
|---|---|
| Formal binary `TaskSuccessEvaluator` | PASS |
| Runtime self-reported task success excluded | PASS |
| Strong `CriterionJudgment` | PASS |
| Required conjunction | PASS |
| Response Type evaluator | PASS |
| Agent / Tool evaluator | PASS |
| Authorization evaluator | PASS |
| Clarification evaluator | PASS |
| Handoff evaluator | PASS |
| Critical Gold Fact evaluator | PASS |
| Structured deterministic facts | PASS |
| Semantic fact Judge contract | PASS |
| Minimum grounding criterion | PASS |
| Judge Prompt versioning | PASS |
| Judge structured output | PASS |
| Judge retry/error/raw record | PASS |
| Judge error does not auto-PASS | PASS |
| Prediction/Judgment artifact separation | PASS |
| Task Success denominator frozen | PASS |
| Overall/category formal report implementation | PASS |
| Gold Isolation regression | PASS |
| ONE CASE -> ONE Production execution regression | PASS |
| Real Production E2E run in current environment | BLOCKED |
| Real LLM Judge run in current environment | BLOCKED |
| Formal Validation Task Success number | NOT RUN |
| Trusted test split | NOT PRESENT |

因此 Phase 2 代码契约已可作为 Phase 3 基线，但本阶段整体仍保守标记 **PARTIAL**：当前环境无法完成真实 Production + real Judge formal run，不能声称已经得到真实 E2E quality result。
