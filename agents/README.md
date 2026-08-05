# Agents

Liorin 客服系统的可复用 Agent 工厂。

| Agent | 作用 |
|---|---|
| `order_agent.py` | 使用只读 SQL 回答结构化客户、订单、工单和质保问题。 |
| `knowledge_agent.py` | Agentic RAG 子图，负责手册、政策、FAQ、历史工单和结构化数据库的理解、规划、检索、评估、回答和校验。 |
| `conversation_supervisor.py` | 与客户对话，并把问题路由给合适的专业 Agent。 |
| `support_workflow.py` | 在账户、订单、工单等客户专属问题前增加身份验证。 |

生产图由 `create_support_agent()` 创建，默认结构是：

客户问题 -> 身份验证 -> 会话主管 -> 订单 Agent / 知识 Agentic RAG 子图。

知识子图的核心流程：

理解问题 -> 判断是否澄清 -> 生成检索计划 -> 动态选择手册/政策/FAQ/历史工单/结构化数据库 -> Dense/BM25/Exact 多路检索 -> RRF 融合 -> 重排 -> 父章节扩展 -> 证据评估和冲突检测 -> 必要时改写或补充检索（最多两次） -> 生成答案 -> 引用校验和答案忠实性校验 -> 必要时人工转接。

离线检查命令：

```bash
python evals/agentic_rag_eval.py
```

分层指标和消融实验：

```bash
python evals/agentic_rag_metrics.py
```

指标覆盖查询理解、知识源路由、Recall@K/MRR/NDCG@K、Rerank Top-1 和 NDCG 提升、Evidence Coverage、冲突识别、Answer Correctness、Faithfulness、工具选择、检索轮数、P95 延迟、Token 估算、检索成本和 Fallback 率。消融实验包含 `dense_only`、`dense_bm25`、`dense_bm25_rerank`、`metadata_filter`、`query_rewrite`、`evidence_grading` 和 `full_agentic_rag`。
