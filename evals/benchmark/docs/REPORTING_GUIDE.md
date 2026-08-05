# Reporting Guide

## 推荐写法

> 我们在 Liorin Agentic RAG Benchmark v7.3 上评估系统。该数据集包含 612 条来源可追溯样本，按产品、政策章节、数据库实体和问题模板隔离为 Dev、Validation 与 Blind Test。检索覆盖五类知识源，并分别报告查询理解、路由、检索、Agent 行为和端到端指标。

结果表中必须注明：

- 数据版本与 Git/文件哈希；
- Blind Test 是否由独立保管方执行；
- 是否访问过私有 Gold；
- 模型、Embedding、Reranker、Judge、Prompt 版本；
- P50/P95 延迟、Token 或调用成本；
- 自动事实代理分数与 Judge/人工分数分开报告。

## 禁止写法

- “行业权威公开 Benchmark”；
- 在访问 Blind Gold 后仍称其为首次盲测；
- 把词面覆盖代理称为绝对答案正确率；
- 只报告最好一次或最好子集而不披露完整层级结果。
