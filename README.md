# Liorin

Liorin 是一个基于 LangGraph 的电商客服 Agent 项目。它面向虚构科技电商 TechHub，能够结合订单数据库、产品/政策文档检索和客户身份验证，回答用户关于订单、商品、退货、保修、配送、兼容性等问题。

这个仓库已经从原来的教学演示结构收束为一个更干净的项目形态：只保留一条生产 Agent 路径，即 `customer_support_agent`。

## 核心能力

- 查询结构化数据：客户、订单、订单明细、商品、库存、历史价格。
- 检索非结构化文档：产品规格、兼容性说明、退货政策、保修政策、配送说明、支持 FAQ。
- 处理客户身份验证：涉及“我的订单”“我的购买记录”等账户相关问题时，会要求用户提供邮箱并验证客户身份。
- 多 Agent 协作：Supervisor 负责理解用户问题，并把任务分发给 SQL 数据库专家或文档检索专家。
- 支持评测和仿真：保留离线评测、CI 回归门禁和模拟客服流量脚本。

## 架构

```text
customer_support_agent
  -> query_router
  -> verify_customer / collect_email
  -> supervisor_agent
      -> sql_agent
      -> docs_agent
```

主要流程：

1. `query_router` 判断问题是否需要客户身份验证。
2. `verify_customer` / `collect_email` 负责提取、收集并验证客户邮箱。
3. `supervisor_agent` 与用户交互，并决定调用哪个专家 Agent。
4. `sql_agent` 通过只读 SQL 查询 TechHub SQLite 数据库。
5. `docs_agent` 检索产品文档和政策文档，提供 RAG 支撑。

生产图在 [langgraph.json](langgraph.json) 中配置为：

```json
{
  "graphs": {
    "customer_support_agent": "./deployments/customer_support_agent_graph.py:graph"
  }
}
```

## 项目结构

```text
agents/
  sql_agent.py                     # 数据库查询专家，使用只读 SQL
  docs_agent.py                    # 产品和政策文档检索专家
  supervisor_agent.py              # 负责路由和整合答案
  supervisor_hitl_agent.py         # 身份验证 + Supervisor 的完整图

tools/
  database.py                      # SQLite 连接和只读 SQL 工具
  documents.py                     # 产品文档/政策文档检索工具

deployments/
  customer_support_agent_graph.py  # LangGraph 部署入口

evals/
  baseline_dataset.json            # 离线评测数据集
  run_ci_eval.py                   # CI 回归评测脚本

evaluators/                        # 正确性和工具调用数评测器
simulations/                       # 生产流量仿真脚本
data/                              # TechHub 示例数据和文档
config.py                          # 全局配置
langgraph.json                     # LangGraph 图配置
pyproject.toml                     # Python 依赖配置
```

## 环境要求

- Python 3.13
- Git
- [uv](https://docs.astral.sh/uv/)
- 至少一个模型提供商 API Key，例如 Anthropic 或 OpenAI
- 可选：LangSmith API Key，用于 tracing、评测和部署观测

## 安装

安装依赖：

```bash
uv sync
```

创建环境变量文件：

```bash
cp .env.example .env
```

在 `.env` 中配置模型和 API Key。常用配置如下：

```bash
LIORIN_MODEL="anthropic:claude-haiku-4-5"
ANTHROPIC_API_KEY="your-anthropic-api-key"

LANGSMITH_TRACING="true"
LANGSMITH_PROJECT="liorin"
LANGSMITH_API_KEY="your-langsmith-api-key"

EMBEDDING_PROVIDER="huggingface"
```

如果使用 OpenAI 模型或 OpenAI Embeddings，也可以配置：

```bash
LIORIN_MODEL="openai:gpt-5-mini"
OPENAI_API_KEY="your-openai-api-key"
EMBEDDING_PROVIDER="openai"
```

## 构建向量库

文档检索依赖本地向量库。首次运行时会自动构建，也可以手动构建：

```bash
uv run python data/data_generation/build_vectorstore.py
```

默认使用 HuggingFace Embeddings，本地运行，不需要额外 API Key。若设置 `EMBEDDING_PROVIDER=openai`，则需要配置 `OPENAI_API_KEY`。

## 本地运行

启动 LangGraph 本地开发服务：

```bash
uv run langgraph dev
```

可用图名称：

```text
customer_support_agent
```

## 数据集

项目内置 TechHub 合成数据，可直接用于开发和测试：

- 50 个客户
- 25 个商品
- 250 个订单
- 439 条订单明细
- 30 份 Markdown 文档，包括产品规格、兼容性、退货、保修、配送和支持 FAQ

关键数据位置：

```text
data/structured/techhub.db          # SQLite 数据库
data/structured/SCHEMA.md           # 数据库 schema 说明
data/documents/                     # 产品和政策文档
data/data_generation/               # 数据生成与校验脚本
```

## 评测

运行离线回归评测：

```bash
uv run python evals/run_ci_eval.py --threshold 0.8
```

评测内容：

- `correctness_evaluator`：基于参考答案判断最终回答是否正确。
- `count_total_tool_calls_evaluator`：统计 trace 中的工具调用次数。

运行评测需要配置：

```bash
LANGSMITH_API_KEY
ANTHROPIC_API_KEY 或 OPENAI_API_KEY
```

GitHub Actions 中的回归门禁配置在：

```text
.github/workflows/eval-regression.yml
```

## 仿真

模拟真实客服对话流量：

```bash
uv run python simulations/run_simulation.py
uv run python simulations/run_simulation.py --count 5
uv run python simulations/run_simulation.py --count 3 --mode static
```

仿真系统会：

- 从数据库中选择真实的合成客户和订单。
- 生成不同类型的客服场景。
- 自动处理邮箱验证 interrupt。
- 将 trace 写入 LangSmith，便于观察线上表现。

## 部署入口

生产图入口文件：

```text
deployments/customer_support_agent_graph.py
```

该文件导出 `graph`，由 `langgraph.json` 引用。部署到 LangGraph / LangSmith 时，平台会加载这个图。

## 当前裁剪状态

这个仓库已经移除了原教学仓库中的基础版和教程资产，包括：

- Jupyter 教程 notebooks
- 基础版 `db_agent.py`
- 多个演示用 deployment graph
- 教程图片和演示脚本

现在项目保留的是面向实际使用的核心路径：`customer_support_agent`。
