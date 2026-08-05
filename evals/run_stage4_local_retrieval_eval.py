"""Run the current production BM25 path on the source-grounded v7.3 validation split.

This runner never reads gold until after retrieval predictions have been written.  It
uses a minimal ``Document`` compatibility class only when LangChain is unavailable;
all corpus loading, ACL filtering, BM25 indexing and scoring use production modules.
The resulting report is a local sparse-retrieval measurement, not a Milvus, LLM or
full Agentic RAG result.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import types
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_document_compatibility() -> bool:
    try:
        import langchain_core.documents  # noqa: F401
        return False
    except (ModuleNotFoundError, ImportError):
        core = sys.modules.get("langchain_core") or types.ModuleType("langchain_core")
        documents = types.ModuleType("langchain_core.documents")

        class Document:
            def __init__(self, page_content: str, metadata: dict[str, Any] | None = None):
                self.page_content = page_content
                self.metadata = metadata or {}

        documents.Document = Document
        core.documents = documents
        core.__path__ = []
        sys.modules["langchain_core"] = core
        sys.modules["langchain_core.documents"] = documents
        return True


COMPATIBILITY_SHIM_USED = _install_document_compatibility()

from evals.benchmark.corpus_registry import BenchmarkCorpusRegistry
from evals.benchmark.scoring.scorer import score_predictions
from evals.gold_isolation import assert_no_gold_leak, build_run_metadata
from retrieval.budget import RetrievalBudget
from retrieval.protocols import RetrievalPrincipal
from retrieval.sparse_retriever import bm25_search, get_bm25_index
from retrieval.filters import principal_can_access


def principal() -> RetrievalPrincipal:
    return RetrievalPrincipal(
        user_id="benchmark-service",
        tenant_id="default",
        roles=["knowledge_admin"],
        groups=["benchmark"],
        permissions=["knowledge:read", "classification:confidential:read", "admin:audit"],
        authenticated=True,
        region="CN",
    )


def generate_predictions(dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registry = BenchmarkCorpusRegistry()
    predictions: list[dict[str, Any]] = []
    # Gold is deliberately not passed to this loop.  Only sample input is visible.
    for sample in dataset:
        if sample.get("layer") != "retrieval":
            continue
        request = dict(sample.get("input") or {})
        query = str(request.get("query") or "")
        filters = dict(request.get("filters") or {})
        source = request.get("source_scope")
        if source and source != "all":
            filters["source"] = source
        started = time.perf_counter()
        result = bm25_search(
            query,
            principal=principal(),
            filters=filters,
            k=20,
            budget=RetrievalBudget(max_dense_queries=0, max_sparse_queries=2, max_candidates=40).start(),
        )
        latency_ms = (time.perf_counter() - started) * 1000
        ranked: list[str] = []
        unmapped: list[dict[str, Any]] = []
        acl_violations: list[str] = []
        returned_sources: list[str] = []
        for evidence in result.evidences:
            if not principal_can_access(evidence.document.metadata, principal()):
                acl_violations.append(str(evidence.document.metadata.get("chunk_id") or "unknown"))
            returned_sources.append(str(evidence.document.metadata.get("source") or evidence.source_type))
            mapped = registry.map_document(evidence.document)
            if mapped.benchmark_chunk_id:
                ranked.append(mapped.benchmark_chunk_id)
            else:
                unmapped.append(mapped.__dict__)
        predictions.append({
            "id": sample["id"],
            "prediction": {
                "ranked_chunk_ids": ranked,
                "latency_ms": round(latency_ms, 3),
                "retrieval_status": str(result.status),
            },
            "diagnostics": {
                "production_retriever": "retrieval.sparse_retriever.bm25_search",
                "candidate_count": result.candidate_count,
                "unmapped": unmapped,
                "error_types": [error.error_type for error in result.errors],
                "acl_violations": acl_violations,
                "returned_sources": sorted(set(returned_sources)),
                "requested_source": source,
            },
        })
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="evals/benchmark/data/validation_v7_3.json")
    parser.add_argument("--predictions", default="evals/reports/stage4_local_bm25_predictions.json")
    parser.add_argument("--report", default="evals/reports/stage4_local_bm25_report.json")
    args = parser.parse_args()
    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    runtime_dataset = [
        {"id": row["id"], "layer": row["layer"], "input": row.get("input", {})}
        for row in dataset
    ]
    assert_no_gold_leak(runtime_dataset)
    warmup_started = time.perf_counter()
    index = get_bm25_index()
    index_warmup_ms = (time.perf_counter() - warmup_started) * 1000
    predictions = generate_predictions(runtime_dataset)
    predictions_path = Path(args.predictions)
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    predictions_path.write_text(json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata = build_run_metadata(
        root=Path.cwd(),
        dataset_path=dataset_path,
        split="validation",
        index_manifest={
            "retriever": "bm25",
            "corpus_version": index.version,
            "document_count": len(index.docs),
        },
        model_versions={"llm": "not_used", "embedding": "not_used", "reranker": "not_used"},
        config={"k": 20, "acl_principal": "benchmark-service/default", "source": "production_bm25"},
        mock_mode=False,
    )
    metadata.update({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "claim_scope": "local_production_bm25_only",
        "langchain_document_compatibility_shim": COMPATIBILITY_SHIM_USED,
        "gold_access_boundary": "predictions serialized before scorer reads gold",
        "index_warmup_ms": round(index_warmup_ms, 3),
        "latency_scope": "warm-query latency; index construction recorded separately",
    })
    report = score_predictions(
        predictions_path,
        dataset_path,
        layers={"retrieval"},
        run_metadata=metadata,
    )
    latencies = sorted(float(row["prediction"]["latency_ms"]) for row in predictions)
    def percentile(p: float) -> float:
        if not latencies:
            return 0.0
        position = (len(latencies) - 1) * p
        lower = int(position)
        upper = min(len(latencies) - 1, lower + 1)
        fraction = position - lower
        return latencies[lower] * (1 - fraction) + latencies[upper] * fraction
    acl_violations = sum(len(row["diagnostics"]["acl_violations"]) for row in predictions)
    filter_failures = sum(
        1 for row in predictions
        if row["diagnostics"].get("requested_source") not in {None, "all"}
        and any(source != row["diagnostics"]["requested_source"] for source in row["diagnostics"]["returned_sources"])
    )
    report["runtime_metrics"] = {
        "p50_latency_ms": percentile(0.50),
        "p95_latency_ms": percentile(0.95),
        "p99_latency_ms": percentile(0.99),
        "timeout_rate": sum(row["prediction"]["retrieval_status"] == "timeout" for row in predictions) / max(1, len(predictions)),
        "dependency_error_rate": sum(row["prediction"]["retrieval_status"] == "dependency_error" for row in predictions) / max(1, len(predictions)),
        "acl_violation_rate": acl_violations / max(1, sum(len(row["prediction"]["ranked_chunk_ids"]) for row in predictions)),
        "filter_accuracy": 1.0 - filter_failures / max(1, len(predictions)),
        "unmapped_evidence_count": sum(len(row["diagnostics"]["unmapped"]) for row in predictions),
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "sample_count": report["sample_count"],
        "by_layer": report["by_layer"],
        "error_count": report["error_count"],
        "runtime_metrics": report["runtime_metrics"],
        "claim_scope": metadata["claim_scope"],
        "compatibility_shim": COMPATIBILITY_SHIM_USED,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
