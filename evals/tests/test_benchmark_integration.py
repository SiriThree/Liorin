from __future__ import annotations

import json
from unittest.mock import patch
from pathlib import Path

from langchain_core.documents import Document

from evals.benchmark.corpus_registry import BenchmarkCorpusRegistry
from evals.benchmark.runner import LAYER_ADAPTERS
from evals.benchmark.scoring.scorer import score_predictions


def test_each_benchmark_layer_prediction_schema(tmp_path: Path):
    dataset = json.loads(Path("evals/benchmark/data/validation_v7_3.json").read_text(encoding="utf-8"))
    seen = set()
    rows = []
    for sample in dataset:
        if sample["layer"] in seen:
            continue
        seen.add(sample["layer"])
        kwargs = {}
        if sample["layer"] in {"retrieval", "answer_generation", "end_to_end"}:
            kwargs["registry"] = BenchmarkCorpusRegistry()
        row = LAYER_ADAPTERS[sample["layer"]](sample, **kwargs)
        rows.append(row)
        assert row["id"] == sample["id"]
        assert isinstance(row["prediction"], dict)
        assert isinstance(row["diagnostics"], dict)
    assert seen == {"query_understanding", "routing", "retrieval", "answer_generation", "agent_behavior", "end_to_end"}


def test_chunk_id_mapping_is_exact():
    registry = BenchmarkCorpusRegistry()
    known = next(iter(registry.by_chunk_id))
    mapped = registry.map_document(Document(page_content="x", metadata={"chunk_id": known, "doc_type": "manual"}))
    assert mapped.benchmark_chunk_id == known
    row = next(item for item in registry.rows if item.get("source_file") and item.get("heading") and item.get("text"))
    location_mapped = registry.map_document(
        Document(
            page_content=row["text"],
            metadata={
                "chunk_id": "production-generated-id",
                "source_file": row["source_file"],
                "section": row["heading"],
                "doc_type": row["source_type"],
            },
        )
    )
    assert location_mapped.benchmark_chunk_id == row["chunk_id"]
    unmapped = registry.map_document(Document(page_content="x", metadata={"chunk_id": "not-in-public-manifest"}))
    assert unmapped.benchmark_chunk_id is None
    assert unmapped.unmapped_reason


def test_scorer_layer_filter_and_partial_submission(tmp_path: Path):
    dataset = json.loads(Path("evals/benchmark/data/validation_v7_3.json").read_text(encoding="utf-8"))
    sample = next(row for row in dataset if row["layer"] == "retrieval")
    prediction = [{"id": sample["id"], "prediction": {"ranked_chunk_ids": list(sample["gold"]["qrels"])[:3]}}]
    pred_path = tmp_path / "predictions.json"
    pred_path.write_text(json.dumps(prediction, ensure_ascii=False), encoding="utf-8")
    report = score_predictions(
        pred_path,
        "evals/benchmark/data/validation_v7_3.json",
        layers={"retrieval"},
        allow_partial=True,
    )
    assert report["sample_count"] == 1
    assert report["missing_prediction_ids"] == []
    assert "retrieval" in report["by_layer"]
    assert "fact_coverage_proxy is deterministic lexical coverage" in report["warning"]


def test_end_to_end_adapter_attempts_support_graph():
    dataset = json.loads(Path("evals/benchmark/data/validation_v7_3.json").read_text(encoding="utf-8"))
    sample = next(row for row in dataset if row["layer"] == "end_to_end")
    from evals.benchmark.adapters import end_to_end

    with patch("evals.benchmark.adapters.end_to_end.create_support_agent") as create_support:
        create_support.side_effect = RuntimeError("offline graph unavailable")
        row = end_to_end.predict(sample, registry=BenchmarkCorpusRegistry())
    assert row["diagnostics"]["support_graph_called"] is True
    assert "offline graph unavailable" in row["diagnostics"]["support_graph_fallback_reason"]
