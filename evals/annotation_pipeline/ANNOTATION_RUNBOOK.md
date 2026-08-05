# Annotation Runbook

## 安装

```bash
python -m pip install -r requirements-annotation.txt
```

## 配置三个独立模型

复制配置：

```bash
cp configs/annotators.example.yaml configs/annotators.local.yaml
```

填写三个不同的 provider/model/base URL，并设置密钥环境变量。不要把密钥写入 YAML。

## 可选：合并多个检索器候选池

在 YAML 中加入：

```yaml
candidate_pool_paths:
  - reports/bm25_validation_predictions_v7_3.json
  - reports/dense_candidate_pool.json
  - reports/hybrid_candidate_pool.json
```

文件每行或每项至少包含：

```json
{"id":"RET7-0001","prediction":{"ranked_chunk_ids":["..."]}}
```

## 执行

```bash
python scripts/run_multi_agent_annotation.py \
  --config configs/annotators.local.yaml
```

程序可断点续跑。不要在同一 output directory 下更换模型、Prompt、数据或候选池。

## 流程审计

```bash
python scripts/audit_annotation_pipeline.py \
  --run-dir annotation_runs/real_run_v7_4 \
  --output annotation_runs/real_run_v7_4/audit_report.json
```

## 一致性门禁

```bash
python scripts/check_agreement_thresholds.py \
  annotation_runs/real_run_v7_4/agreement_report.json \
  --manifest annotation_runs/real_run_v7_4/run_manifest.json \
  --output annotation_runs/real_run_v7_4/agreement_gate.json
```

门禁失败时，先分析分歧类型并更新指南或样本，然后用新 output directory 重新运行 A/B。

## 人工复核

编辑：

```text
annotation_runs/real_run_v7_4/human_review_queue.json
```

每条填写：

```json
{
  "reviewer_id": "reviewer-name",
  "status": "approved | modified | rejected",
  "final_annotation": null,
  "notes": ""
}
```

应用复核：

```bash
python scripts/apply_human_reviews.py \
  --run-dir annotation_runs/real_run_v7_4
```

## 对外表述

正确：

> 评测集采用双 Agent 独立标注、第三 Agent 分歧仲裁，并由人工复核全部分歧、高风险样本和随机抽样数据。

错误：

> 评测集经过人工双标。

## 导出新版本 Gold

人工复核完成后：

```bash
python scripts/apply_human_reviews.py \
  --run-dir annotation_runs/real_run_v7_4

python scripts/export_reviewed_dataset.py \
  --dataset evals/benchmark/data/dev_v7_3.json \
  --reviewed-annotations annotation_runs/real_run_v7_4/final_annotations_after_human_review.json \
  --output data/reviewed_dataset_v7_4.json
```

默认会保留旧 `gold`，并新增 `reviewed_gold_v7_4` 供差异检查。只有完成抽检和语义审计后，才应使用 `--replace-gold`。

## 重要限制

- `backend: mock` 只验证流程，审计状态为 `PASS_FLOW_ONLY`，一致性门禁会返回 `INVALID_MOCK_RUN`。
- 三个 AI 的一致并不等价于事实正确；高风险人工复核不可删除。
- 若 A/B 一致性门禁失败，必须重写指南、Prompt 或歧义样本并重新独立标注，不能只依赖 C 仲裁。
