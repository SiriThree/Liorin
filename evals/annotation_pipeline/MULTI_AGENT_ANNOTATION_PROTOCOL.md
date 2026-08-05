# 多 Agent 独立标注与人工风险复核协议

## 1. 定位

本流程用于提高 Liorin Agentic RAG Benchmark 的标注可靠性，正式名称为：

> 双 Agent 独立标注 + 第三 Agent 分歧仲裁 + 人工高风险抽检

它不是人工双标。对外报告必须如实说明标注主体为 AI Agent，并单独披露人工复核范围。

## 2. 角色隔离

- Agent A：独立标注全部样本，不读取原 Gold，不读取 B 的结果。
- Agent B：独立标注全部样本，不读取原 Gold，不读取 A 的结果。
- Agent C：仅处理 A/B 的分歧字段；一致字段由程序锁定，C 无权改写。
- Human Reviewer：复核全部分歧、高风险样本，以及无分歧样本的固定随机抽样。

严格模式要求 A、B、C 使用不同的 provider/base_url/model 组合。若使用同一模型家族，必须在报告中披露同源偏差风险。

## 3. Gold 隔离

标注请求只包含：

- sample id 与 layer；
- 原始 input；
- 从冻结语料独立构建的 source packet；
- 产品目录；
- 当前层级的输出 Schema。

请求包递归禁止出现 `gold`、`annotation` 和 `split` 字段。运行审计会重新检查该约束。

## 4. 候选池

Retrieval 层默认使用本地 BM25 候选、同文档相邻 Chunk，并可通过 `candidate_pool_paths` 合并 Dense、Hybrid 或其他检索器的预计算 Top-K。候选池不得从现有 qrels 或 hard-negative Gold 反推。

每个候选由 A/B 独立标注 0–3 级 qrel：

- 3：直接且完整回答核心需求；
- 2：核心答案的必要组成部分；
- 1：背景相关但单独不足；
- 0：不相关或具有误导性。

## 5. 分歧与仲裁

程序忽略 rationale 和 confidence 的词面差异，对实质字段进行结构化比较。存在分歧时：

1. 生成精确 JSON Pointer conflict path；
2. C 只返回这些 path 的 resolution；
3. 程序拒绝遗漏、新增或重复 resolution；
4. 一致字段从 A/B 共识中保留；
5. C 可以将样本标为 `ambiguous` 或 `unanswerable`。

## 6. 人工复核范围

人工队列自动包含：

- 全部 A/B 分歧；
- 数字、日期、金额、型号、错误码；
- 退款、退货、取消、赔付、维修、质保；
- 身份、权限、隐私；
- 安全警告、伤害和医疗建议；
- 工具失败、证据冲突、低置信度；
- 无分歧样本的固定 10% 随机抽样。

人工可选择 `approved`、`modified` 或 `rejected`。修改后的标注必须重新通过同一 Schema 校验。

## 7. 一致性门槛

`check_agreement_thresholds.py` 默认检查：

- 分类字段 Cohen’s Kappa ≥ 0.80；
- Retrieval Weighted Kappa ≥ 0.80；
- Retrieval 二值相关 F1 ≥ 0.90；
- 多标签 Jaccard ≥ 0.85；
- 原子事实 Source Ref Jaccard ≥ 0.90；
- 数字一致率 ≥ 0.98；
- 高风险 forbidden claims Jaccard ≥ 0.90。

若未达标，应修改标注规范、Prompt 或歧义样本后重新运行 A/B。不能只依靠 C 仲裁掩盖低一致性。

## 8. 输出

每次运行生成：

- `source_packets.jsonl`
- `annotator_a.jsonl`
- `annotator_b.jsonl`
- `adjudicator_c.jsonl`
- `adjudicated.jsonl`
- `agreement_report.json`
- `human_review_queue.json`
- `run_spec.json`
- `run_manifest.json`
- `audit_report.json`

所有文件支持断点续跑；若数据、模型或 Prompt 配置发生变化，必须使用新的 output directory。
