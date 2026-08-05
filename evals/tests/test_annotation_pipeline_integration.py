from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

EVALS_ROOT = Path(__file__).resolve().parents[1]
if str(EVALS_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALS_ROOT))

from annotation_pipeline.compare import diff_annotations, merge_with_resolutions
from annotation_pipeline.config import load_config
from annotation_pipeline.gold_export import annotation_to_gold
from annotation_pipeline.io_utils import read_jsonl
from annotation_pipeline.pipeline import AnnotationPipeline
from annotation_pipeline.source_index import SourceIndex
from scripts.audit_annotation_pipeline import audit, forbidden_key_paths


def test_no_gold_leak_recursive_and_packet_budget():
    dataset = json.loads(Path("evals/tests/fixtures/annotation_smoke_dataset.json").read_text(encoding="utf-8"))
    sample = next(row for row in dataset if row["layer"] == "retrieval")
    index = SourceIndex("evals/benchmark/corpus/corpus_v7_3.json")
    packet = index.build_packet(sample, top_k=8, retrieval_pool_size=20, max_chars=9000)
    assert forbidden_key_paths(packet) == []
    assert sum(len(str(row.get("text", ""))) for row in packet["source_context"]) <= 9000
    assert packet["source_context"]


def test_c_cannot_modify_consensus_path():
    a = {
        "sample_id": "ROU-X",
        "layer": "routing",
        "quality_status": "valid",
        "confidence": 0.9,
        "quality_issues": [],
        "rationale": "a",
        "required_sources": ["manual"],
        "conditional_sources": [],
        "optional_sources": [],
        "forbidden_sources": ["policy"],
        "min_queries": 1,
        "parallelizable": False,
    }
    b = dict(a)
    b["required_sources"] = ["policy"]
    conflicts = diff_annotations(a, b)
    assert {item["path"] for item in conflicts} == {"/required_sources"}
    try:
        merge_with_resolutions(
            a,
            b,
            conflicts,
            [{"path": "/forbidden_sources", "value": ["database"], "reason": "bad", "source_refs": []}],
        )
    except ValueError as exc:
        assert "resolution paths do not match conflict paths" in str(exc)
    else:
        raise AssertionError("C must not resolve consensus paths")


def test_mock_pipeline_flow_and_audit(tmp_path: Path):
    raw = Path("evals/configs/mock_flow_test.yaml").read_text(encoding="utf-8")
    run_dir = tmp_path / "mock-run"
    raw = raw.replace("annotation_runs/mock_flow_test", str(run_dir))
    raw = raw.replace("tests/fixtures/annotation_smoke_dataset.json", str(Path("evals/tests/fixtures/annotation_smoke_dataset.json").resolve()))
    raw = raw.replace("benchmark/corpus/corpus_v7_3.json", str(Path("evals/benchmark/corpus/corpus_v7_3.json").resolve()))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(raw, encoding="utf-8")
    manifest = AnnotationPipeline(load_config(config_path)).run()
    assert manifest["sample_count"] == 12
    audited = audit(run_dir)
    assert audited["status"] == "PASS_FLOW_ONLY"
    assert audited["semantic_results_valid"] is False
    assert audited["invariants"]["no_gold_in_agent_packets"]
    assert audited["invariants"]["c_called_only_for_disagreements"]
    assert audited["invariants"]["all_disagreements_in_human_queue"]
    c_rows = read_jsonl(run_dir / "adjudicator_c.jsonl")
    disagreement_ids = {row["sample_id"] for row in read_jsonl(run_dir / "adjudicated.jsonl") if row["had_disagreement"]}
    assert {row["sample_id"] for row in c_rows} == disagreement_ids


def test_independence_signature_rejected_when_equal(tmp_path: Path):
    raw = Path("evals/configs/mock_flow_test.yaml").read_text(encoding="utf-8")
    raw = raw.replace("provider: mock-b", "provider: mock-a")
    raw = raw.replace("model: mock-model-b", "model: mock-model-a")
    raw = raw.replace("base_url: mock://b", "base_url: mock://a")
    raw = raw.replace("annotation_runs/mock_flow_test", str(tmp_path / "run"))
    raw = raw.replace("tests/fixtures/annotation_smoke_dataset.json", str(Path("evals/tests/fixtures/annotation_smoke_dataset.json").resolve()))
    raw = raw.replace("benchmark/corpus/corpus_v7_3.json", str(Path("evals/benchmark/corpus/corpus_v7_3.json").resolve()))
    cfg = tmp_path / "bad_independence.yaml"
    cfg.write_text(raw, encoding="utf-8")
    try:
        load_config(cfg)
    except ValueError as exc:
        assert "strict independence" in str(exc)
    else:
        raise AssertionError("strict A/B/C independence should reject equal signatures")


def test_random_consensus_review_is_deterministic(tmp_path: Path):
    raw = Path("evals/configs/mock_flow_test.yaml").read_text(encoding="utf-8")
    raw = raw.replace("tests/fixtures/annotation_smoke_dataset.json", str(Path("evals/tests/fixtures/annotation_smoke_dataset.json").resolve()))
    raw = raw.replace("benchmark/corpus/corpus_v7_3.json", str(Path("evals/benchmark/corpus/corpus_v7_3.json").resolve()))
    queues = []
    for index in range(2):
        run_dir = tmp_path / f"run-{index}"
        cfg = tmp_path / f"config-{index}.yaml"
        cfg.write_text(raw.replace("annotation_runs/mock_flow_test", str(run_dir)), encoding="utf-8")
        AnnotationPipeline(load_config(cfg)).run()
        queue = json.loads((run_dir / "human_review_queue.json").read_text(encoding="utf-8"))
        queues.append([row["sample_id"] for row in queue if "random_consensus_sample" in row["mandatory_reasons"]])
    assert queues[0] == queues[1]


def test_mock_gate_is_invalid(tmp_path: Path):
    raw = Path("evals/configs/mock_flow_test.yaml").read_text(encoding="utf-8")
    run_dir = tmp_path / "mock-gate"
    raw = raw.replace("annotation_runs/mock_flow_test", str(run_dir))
    raw = raw.replace("tests/fixtures/annotation_smoke_dataset.json", str(Path("evals/tests/fixtures/annotation_smoke_dataset.json").resolve()))
    raw = raw.replace("benchmark/corpus/corpus_v7_3.json", str(Path("evals/benchmark/corpus/corpus_v7_3.json").resolve()))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(raw, encoding="utf-8")
    AnnotationPipeline(load_config(cfg)).run()
    result = subprocess.run(
        [
            sys.executable,
            "evals/scripts/check_agreement_thresholds.py",
            str(run_dir / "agreement_report.json"),
            "--manifest",
            str(run_dir / "run_manifest.json"),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "INVALID_MOCK_RUN" in result.stdout


def test_run_fingerprint_rejects_config_drift(tmp_path: Path):
    raw = Path("evals/configs/mock_flow_test.yaml").read_text(encoding="utf-8")
    run_dir = tmp_path / "drift-run"
    raw = raw.replace("annotation_runs/mock_flow_test", str(run_dir))
    raw = raw.replace("tests/fixtures/annotation_smoke_dataset.json", str(Path("evals/tests/fixtures/annotation_smoke_dataset.json").resolve()))
    raw = raw.replace("benchmark/corpus/corpus_v7_3.json", str(Path("evals/benchmark/corpus/corpus_v7_3.json").resolve()))
    cfg1 = tmp_path / "config1.yaml"
    cfg1.write_text(raw, encoding="utf-8")
    AnnotationPipeline(load_config(cfg1))
    cfg2 = tmp_path / "config2.yaml"
    cfg2.write_text(raw.replace("mock-model-b", "mock-model-b-changed"), encoding="utf-8")
    try:
        AnnotationPipeline(load_config(cfg2))
    except RuntimeError as exc:
        assert "different dataset/model/prompt configuration" in str(exc)
    else:
        raise AssertionError("configuration drift should be rejected")


def test_export_preserves_old_gold_by_default():
    sample = {"id": "ROU-X", "layer": "routing", "input": {"question": "x"}, "gold": {"legacy": True}}
    annotation = {
        "sample_id": "ROU-X",
        "layer": "routing",
        "quality_status": "valid",
        "confidence": 0.9,
        "quality_issues": [],
        "rationale": "r",
        "required_sources": ["manual"],
        "conditional_sources": [],
        "optional_sources": ["faq"],
        "forbidden_sources": ["policy", "database", "ticket_history"],
        "min_queries": 1,
        "parallelizable": False,
    }
    new_gold = annotation_to_gold(sample, annotation)
    assert sample["gold"] == {"legacy": True}
    assert new_gold["required_sources"] == ["manual"]


def test_human_review_approved_modified_rejected(tmp_path: Path):
    from scripts.apply_human_reviews import main as apply_main

    raw = Path("evals/configs/mock_flow_test.yaml").read_text(encoding="utf-8")
    run_dir = tmp_path / "review-run"
    raw = raw.replace("annotation_runs/mock_flow_test", str(run_dir))
    raw = raw.replace("tests/fixtures/annotation_smoke_dataset.json", str(Path("evals/tests/fixtures/annotation_smoke_dataset.json").resolve()))
    raw = raw.replace("benchmark/corpus/corpus_v7_3.json", str(Path("evals/benchmark/corpus/corpus_v7_3.json").resolve()))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(raw, encoding="utf-8")
    AnnotationPipeline(load_config(cfg)).run()
    queue = json.loads((run_dir / "human_review_queue.json").read_text(encoding="utf-8"))
    assert len(queue) >= 3
    adjudicated = read_jsonl(run_dir / "adjudicated.jsonl")
    by_id = {row["sample_id"]: row for row in adjudicated}
    modified_annotation = by_id[queue[1]["sample_id"]]["final_annotation"]
    modified_annotation = {**modified_annotation, "rationale": "human modified rationale"}
    reviews = [
        {"sample_id": queue[0]["sample_id"], "human_review": {"reviewer_id": "r1", "status": "approved", "notes": ""}},
        {"sample_id": queue[1]["sample_id"], "human_review": {"reviewer_id": "r1", "status": "modified", "notes": "fix", "final_annotation": modified_annotation}},
        {"sample_id": queue[2]["sample_id"], "human_review": {"reviewer_id": "r1", "status": "rejected", "notes": "bad sample"}},
    ]
    for row in queue[3:]:
        reviews.append({"sample_id": row["sample_id"], "human_review": {"reviewer_id": "r1", "status": "approved", "notes": ""}})
    reviews_path = tmp_path / "reviews.json"
    output_path = tmp_path / "reviewed.json"
    reviews_path.write_text(json.dumps(reviews, ensure_ascii=False), encoding="utf-8")
    old_argv = sys.argv
    try:
        sys.argv = [
            "apply_human_reviews.py",
            "--run-dir",
            str(run_dir),
            "--reviews",
            str(reviews_path),
            "--output",
            str(output_path),
        ]
        apply_main()
    finally:
        sys.argv = old_argv
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"]["approved"] >= 1
    assert payload["summary"]["modified"] == 1
    assert payload["summary"]["rejected"] == 1
