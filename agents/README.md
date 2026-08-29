# Agents

Liorin 客服系统的可复用 Agent 工厂。

| Agent | 作用 |
|---|---|
| `order_agent.py` | 使用只读 SQL 回答结构化客户、订单、工单和质保问题。 |
| `knowledge_agent.py` | Agentic RAG 子图，接收主管下发的 Query Understanding / Retrieval Plan，负责手册、政策、FAQ、历史工单和结构化数据库的检索、评估、回答和校验；直接调用时保留理解/规划兜底。 |
| `conversation_supervisor.py` | 与客户对话，基于当前问题和 resolved Working Context 完成 Query Understanding、Clarification Decision、Retrieval Planning，并把任务路由给合适的专业 Agent。 |
| `support_workflow.py` | 在账户、订单、工单等客户专属问题前增加身份验证。 |

生产图由 `create_support_agent()` 创建，默认结构是：

客户问题 -> 身份验证 -> 会话主管 -> 订单 Agent / 知识 Agentic RAG 子图。

主管层的编排流程：

当前用户问题 + Context Runtime 选择后的 Working Context -> Query Understanding -> 判断是否澄清 -> Retrieval Planning -> 调用订单 Agent / 知识 Agent。

Working Context 是结构化历史状态，不是完整原始对话全文。它包含当前任务、confirmed slots、stale facts、forbidden context、open clarifications 和上游 Agent 输出。Query Understanding 只能继承 confirmed slots 和仍有效的 Agent 输出；被标记为 stale 或 forbidden 的历史事实不能用于 query enrichment 或 retrieval filters。

知识子图的核心流程：

接收主管下发的 Query Understanding / Retrieval Plan -> 动态选择手册/政策/FAQ/历史工单/结构化数据库 -> Dense/BM25/Exact 多路检索 -> RRF 融合 -> 重排 -> 父章节扩展 -> 证据评估和冲突检测 -> 必要时改写或补充检索（最多两次） -> 生成答案 -> 引用校验和答案忠实性校验 -> 必要时人工转接。

离线检查命令：

```bash
python evals/agentic_rag_eval.py
```

分层指标和消融实验：

```bash
python evals/agentic_rag_metrics.py
```

指标覆盖查询理解、知识源路由、Recall@K/MRR/NDCG@K、Rerank Top-1 和 NDCG 提升、Evidence Coverage、冲突识别、Answer Correctness、Faithfulness、工具选择、检索轮数、P95 延迟、Token 估算、检索成本和 Fallback 率。消融实验包含 `dense_only`、`dense_bm25`、`dense_bm25_rerank`、`metadata_filter`、`query_rewrite`、`evidence_grading` 和 `full_agentic_rag`。
