# Benchmark Expansion Phase D3：Private Business Dual Independent Annotation 与 Agreement Analysis

## 1. D3 Summary

Phase D3 的工程基础设施已完成，但当前真实 Annotator 环境不可用，因此阶段状态为 **PARTIAL**。

- Frozen READY packets: 76
- D2 PRECHECK excluded: 8 / 8
- Annotator A valid decisions: 0
- Annotator B valid decisions: 0
- Valid dual pairs: 0
- Agreement metrics: NOT RUN
- Adjudication runs: 0
- Human review: 0
- New formal cases: 0
- Production Agent: NOT RUN

本阶段没有使用 MockBackend、fixture decisions、复制结果或 deterministic fake decisions 产生 Agreement。

## 2. D2 Frozen Inputs

实际读取 `artifacts/evaluation/dataset-expansion-d2/`：

- `private_business_annotation_packets.jsonl`
- `annotation_batch_manifest.json`
- `private_business_preannotation_review_queue.jsonl`
- `private_business_gold_drafts.jsonl`
- `private_business_source_snapshots.jsonl`
- `private_business_field_semantics.json`
- `private_business_runtime_materialization.json`
- `private_business_warranty_answerability.json`
- `private_business_surface_collision_review.json`
- `private_business_gold_alignment_report.json`

D3 没有重新生成 Candidate、Gold Draft 或 Packet。

## 3. Batch Integrity

实际验证：

- packet_count = 76
- precheck_count = 8
- batch_id = `PBQ-D2-C3B3AA7C6549`
- batch_hash = `c3b3aa7c65497813a9947e2ee0a8f05bae84958c0f5f09ba1f7bc1f3bc22e01c`
- candidate_set_hash = `7885191d82cb97e51e38e000d7a70a77dbea865b2cd61b74256c98ad950855f6`
- 76 packet hash 全部重新计算并与 manifest 一致
- 8 PRECHECK candidate_id 与 READY packet 交集为 0

任何 packet 内容变动都会导致 D3 fail closed。

## 4. Annotator Configuration

D3 复用了现有 `evals/annotation_pipeline` 的：

- `AgentConfig`
- `JSONBackend`
- `OpenAICompatibleBackend`
- bounded infrastructure retry
- JSON structured-output transport

并新增 Private Gold Review 专用 consumer，而不是复用旧 `answer_correctness` Judge。

当前容器没有任何实际 Annotator credential：

- `ANNOTATOR_A_API_KEY`: unset
- `ANNOTATOR_B_API_KEY`: unset
- `OPENAI_API_KEY`: unset
- DeepSeek / Anthropic 等其他常见 key: unset
- local Ollama/OpenAI-compatible service: unavailable

因此尚未冻结真实 provider/model identity。仓库中的 `private_business_dual_annotation.example.yaml` 只是配置模板，不代表实际执行过相应模型。

## 5. Independence Guarantee

真实 run 路径要求：

- A/B distinct `annotator_id`
- separate `annotation_run_id`
- separate backend call context
- same frozen packet bytes / packet hash
- A output never enters B request
- B output never enters A request
- no Production Prediction / Agent Trace / Judge output
- no adjudication context

同模型时只有显式 `allow_same_model_independent_runs=true` 才允许，并标为 `SAME_MODEL_INDEPENDENT_RUNS`；否则要求 model-diverse signature。

## 6. Annotation Prompt

Prompt version：`private_gold_review_v1`

Prompt hash：`319996558482ca2b5d0b2c3b1cfb4d9c713800bb2a7afbde7173d5fbb7535064`

核心任务定义：Reviewer 只审核 Gold Draft 是否 source-supported、complete、minimal、evidence-aligned、response-behavior-correct、contract-correct、unambiguous、privacy-safe；不是回答用户问题，也不是评价 Liorin Agent。

展示顺序固定为：

1. User Query
2. Source Snapshot
3. Production Capability
4. Gold Draft To Review
5. Review Requirements
6. Output Schema

Source 在 Gold Draft 之前，减少 anchoring。Prompt 不展示 D2 的 `READY_FOR_DUAL_ANNOTATION` pipeline classification。

## 7. AnnotationDecision Schema

D3 将 D2 的 `private-business-gold-review-decision-v1` 语义落实为严格结构化输出，并补充 Agreement 所需的细粒度 review：

- overall decision: ACCEPT / ACCEPT_WITH_EDITS / REJECT / NEEDS_HUMAN_REVIEW
- 11 critical dimensions
- per-GoldFact review
- per-GoldEvidence review
- TaskSuccessContract component review
- structured suggested edits
- brief source-grounded rationale
- annotator metadata / packet hash / run id

`ACCEPT` 必须所有关键维度 PASS 且无 ambiguity；`ACCEPT_WITH_EDITS` 必须提供结构化 edit。合法 REJECT / NEEDS_HUMAN_REVIEW 不会因为结果“不好看”而重试。

## 8. Annotator A Run

状态：**BLOCKED**

- successful annotations: 0
- credential configured: false
- actual API calls: 0

Run manifest 已生成，但它记录的是 readiness/blocker，不是 annotation result。

## 9. Annotator B Run

状态：**BLOCKED**

- successful annotations: 0
- credential configured: false
- actual API calls: 0

## 10. Dual Pairing

`dual_annotation_pairing.jsonl` 包含 76 条 frozen candidate pairing record，但全部为：

`pair_status = ANNOTATION_BLOCKED`

没有任何 `VALID` pair。

## 11. Annotation Completion

- Frozen packets: 76
- A completed: 0
- B completed: 0
- Valid pairs: 0
- Incomplete pairs: 76

`annotation_incomplete.jsonl` 逐条记录 `INCOMPLETE_DUAL_ANNOTATION`，原因是 `REAL_ANNOTATOR_ENVIRONMENT_UNAVAILABLE`。

## 12. Overall Decision Agreement

**NOT RUN**

Agreement denominator 只能包含 A/B 都有 valid structured decision 且 packet hash 完全一致的 case。当前 denominator = 0。

## 13. Exact Case Agreement

**NOT RUN**

当前 numerator = 0，denominator = 0，rate = null。不得解释为 0%。

## 14. Dimension Agreement

**NOT RUN**。已实现维度：

- Query Quality
- Answerability
- Response Type
- GoldFact Correctness
- GoldFact Completeness
- Gold Minimality
- GoldEvidence
- TaskSuccessContract
- Source Support
- Ambiguity
- Privacy

## 15. GoldFact Agreement

**NOT RUN**。

基础设施可比较每个 draft fact 的：source support、criticality、value、comparison mode、keep/edit/remove。

## 16. GoldEvidence Agreement

**NOT RUN**。

基础设施可比较 entity、field、required semantics、supporting relation。

## 17. TaskContract Agreement

**NOT RUN**。

基础设施可比较 required criteria / agents / tools / authorization / grounding requirements。

## 18. Order Agreement

**NOT RUN**。

D2 READY packet 中 Order cases 仍保持 frozen；当前没有真实 A/B decision。

## 19. Ticket Agreement

**NOT RUN**。

## 20. Warranty Agreement

**NOT RUN**。

## 21. Semantic-family Agreement

**NOT RUN**。

已实现 family-level exact-case agreement aggregation；只会在 valid pairs > 0 后报告。

## 22. Ticket Summary Analysis

D2 的 3 条 Ticket Summary packet 未被真实 Annotator 调用，因此 Annotator Agreement **NOT RUN**。不能根据 D2 deterministic Gold preparation 自称已验证 free-text semantic boundary。

## 23. Product Gold Minimality Analysis

D2 的 `product_name critical / product_id optional companion` 尚未获得双 Annotator 认可，因此状态 **NOT RUN**。

## 24. Surface Collision Analysis

D2 的 5 条 LOW_INFORMATION_DUPLICATE_CANDIDATE 仍保留在 frozen READY packet 中。D3 没有自动 dedup，也没有真实 annotation result，因此它们的 Gold annotation validity **NOT RUN**。

## 25. Disagreement Severity

Agreement analyzer 已实现：

- HIGH: ACCEPT vs REJECT、answerability / response type / source support、fact/evidence substantive disagreement
- MEDIUM: contract / criticality / comparison/minimality 等
- LOW: non-semantic/minor edit differences

当前真实 disagreement count = 0，因为没有 valid pair；这不能解释为“没有 disagreement”。

## 26. Disagreement Queue

`annotation_disagreement_queue.jsonl` 当前为空，因为 Agreement 没有运行，不是因为 A/B 100% 一致。

真实 run 后 substantive A != B 会全部进入 D4，不会自动选择高 confidence 一方。

## 27. Infrastructure Errors

当前 blocker 发生在调用之前：两个真实 Annotator credential/provider 都未配置。因此：

- provider request count = 0
- timeout = 0 observed
- rate limit = 0 observed
- parse error = 0 observed

代码已实现：provider/backend error → `ANNOTATOR_INFRA_ERROR`；structured parse/validation only 做 bounded retry；valid semantic REJECT 不 retry。

## 28. Artifacts

生成：

- `annotator_a_decisions.jsonl`（空，未伪造 decision）
- `annotator_b_decisions.jsonl`（空）
- `annotator_a_run_manifest.json`
- `annotator_b_run_manifest.json`
- `dual_annotation_pairing.jsonl`
- `annotation_agreement_summary.json/.md`
- `annotation_dimension_agreement.json`
- `annotation_family_agreement.json`
- `annotation_domain_agreement.json`
- `annotation_goldfact_agreement.json`
- `annotation_evidence_agreement.json`
- `annotation_contract_agreement.json`
- `annotation_disagreement_queue.jsonl`
- `annotation_incomplete.jsonl`
- `consensus_annotation_candidates.jsonl`
- `phase_d3_summary.json`

## 29. Tests

D3 targeted：14 passed。

`tests/evaluation`：219 passed, 2 skipped。

全项目 `tests/`：433 passed, 2 skipped。

`compileall`：PASS。

测试中的 fake backend 只验证 schema/retry/pairing/agreement logic，从未写入正式 D3 Agreement artifacts。

## 30. Production Diff

与 D2 baseline 比较，清理 Python bytecode/cache 后：

`Production behavior files changed = 0`

检查目录：agents/tools/retrieval/context_engine/memory/artifact/governance/observability/production/deployments。

## 31. Formal Dataset Invariance

Canonical formal files SHA-256 与 D2 baseline 一致：

- Development = 34
- Validation = 5
- Formal total = 39
- New Formal Cases = 0

## 32. D4 Stable Inputs

D4 只能在真实双标注完成后消费：

- D2 `private_business_annotation_packets.jsonl`
- D2 `annotation_batch_manifest.json`
- D3 immutable `annotator_a_decisions.jsonl`
- D3 immutable `annotator_b_decisions.jsonl`
- `dual_annotation_pairing.jsonl`
- Agreement artifacts
- `annotation_disagreement_queue.jsonl`
- `consensus_annotation_candidates.jsonl`

当前后五类真实 decision/agreement 输入尚未产生，因此 **不应启动 D4 Adjudication**。

## Current stopping point

当前正确下一步不是修 Gold、调 Agreement 或进入 D4，而是配置两个真实可调用 Annotator provider/model，然后以新的 D3 output directory 对同一 frozen batch 执行完整 A/B run。第一轮真实结果必须冻结，无论 Agreement 高低都不得覆盖重跑来“优化一致率”。
