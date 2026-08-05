# Evaluation Protocol

## 三个评测轨道

### A. Objective Core

使用 `evaluate_predictions.py` 计算：

- 查询理解：实体、任务类型、语义需求、澄清决策。
- 路由：必要来源召回、可接受来源精度、禁用来源规避、计划查询数。
- 检索：Recall@1/3/5/10、MRR、nDCG@10、MAP@10。
- Agent 行为：动作、原因码、补充来源、澄清槽位、预算遵守。
- 端到端：响应类型、决策码、来源覆盖、动作和检索轮数。

### B. Generative Grounding

参考评分器报告 `fact_coverage_proxy`、引用召回和高风险动作规避。由于自然语言存在等价改写，正式报告还必须使用以下任一方法：

1. 冻结模型、冻结 Prompt、冻结 Judge 的 LLM Judge；报告 Judge 型号、版本、Prompt 和重复运行方差。
2. 两名独立人工标注员按原子事实与引用逐项评分，分歧由第三人仲裁。

不得把词面代理分数单独称为“答案正确率”。

### C. Blind Test

- 调参只能使用 Dev；模型选择只能使用 Validation。
- Blind Test Gold 由未参与调参的维护者或 CI 账户保管。
- 每个版本只允许一次正式盲测提交。
- 访问 Gold 后，该版本只能用于回归，不能继续声称盲测。

## 提交格式

JSON 数组，每项包含 `id` 和 `prediction`。字段示例见 `examples/submission_example.json`。

## 报告要求

必须同时报告各层结果、样本数量、失败数、延迟/成本和使用的数据版本。禁止只挑选最好的一层或只报告开发集。
