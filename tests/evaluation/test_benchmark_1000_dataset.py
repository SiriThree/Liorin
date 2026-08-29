from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "benchmark" / "data" / "canonical" / "liorin_benchmark_1000_v1.jsonl"
MANIFEST = ROOT / "evals" / "benchmark" / "data" / "canonical" / "liorin_benchmark_1000_v1.manifest.json"


def _rows():
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_benchmark_1000_contract():
    rows = _rows()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert len(rows) == 1000
    assert Counter(row["category"] for row in rows) == {
        "KNOWLEDGE_QA": 600,
        "PRIVATE_BUSINESS_DATA": 150,
        "MIXED_KNOWLEDGE_STRUCTURED": 150,
        "SAFETY_GOVERNANCE": 100,
    }
    assert Counter(row["case_mode"] for row in rows) == {
        "single_turn": 500,
        "multi_turn_session": 500,
    }
    assert Counter((row["category"], row["case_mode"]) for row in rows) == {
        ("KNOWLEDGE_QA", "single_turn"): 300,
        ("KNOWLEDGE_QA", "multi_turn_session"): 300,
        ("PRIVATE_BUSINESS_DATA", "single_turn"): 75,
        ("PRIVATE_BUSINESS_DATA", "multi_turn_session"): 75,
        ("MIXED_KNOWLEDGE_STRUCTURED", "single_turn"): 75,
        ("MIXED_KNOWLEDGE_STRUCTURED", "multi_turn_session"): 75,
        ("SAFETY_GOVERNANCE", "single_turn"): 50,
        ("SAFETY_GOVERNANCE", "multi_turn_session"): 50,
    }
    assert manifest["case_count"] == 1000
    assert manifest["dataset_sha256"] == sha256(DATASET.read_bytes()).hexdigest()


def test_benchmark_1000_product_balance_and_uniqueness():
    rows = _rows()
    product_rows = [row for row in rows if row.get("product")]

    assert len(product_rows) == 900
    assert set(Counter(row["product"]["product_id"] for row in product_rows).values()) == {45}
    assert sum(
        1 for row in rows if row["category"] == "KNOWLEDGE_QA"
    ) == 600
    assert len({row["case_id"] for row in rows}) == 1000
    assert len({row["query"] for row in rows}) == 1000
    assert len({row["source_semantic"]["semantic_id"] for row in rows}) == 1000


def test_benchmark_1000_source_grounding_fields():
    for row in _rows():
        assert row["query"] == row["input"]["query"]
        if row["case_mode"] == "single_turn":
            assert row["input"]["messages"] == [{"role": "user", "content": row["query"]}]
        else:
            messages = row["input"]["messages"]
            assert len(messages) >= 3
            assert sum(1 for message in messages if message["role"] == "user") >= 2
        assert row["source_semantic"]["source_refs"]
        assert row["gold_evidence"]
        assert row["gold_facts"]
        assert all(evidence["required"] for evidence in row["gold_evidence"])


def test_benchmark_1000_multi_turn_session_gold_contract():
    rows = [row for row in _rows() if row["case_mode"] == "multi_turn_session"]

    assert len(rows) == 500
    task_types = Counter(row["multi_turn_gold"]["multi_turn_task_type"] for row in rows)
    for task_type in {
        "clarification_resume",
        "entity_carryover",
        "fact_update_supersession",
        "task_switch_context_isolation",
        "cross_agent_state_transfer",
        "cross_session_long_term_memory",
    }:
        assert task_types[task_type] > 0
    for row in rows:
        gold = row["multi_turn_gold"]
        assert gold["active_task"]
        assert gold["current_confirmed_facts"]
        assert gold["session_success_criteria"]
        assert gold["turn_level_scoring_is_diagnostic_only"] is True
        assert isinstance(gold["expected_final_turn_index"], int)
        assert "session_level_e2e_task_success" in row["diagnostic_metrics"]


def test_benchmark_1000_knowledge_uses_raw_manual_or_catalog_sources():
    for row in _rows():
        if row["category"] != "KNOWLEDGE_QA":
            continue
        source_ref = row["source_semantic"]["source_refs"][0]
        source_file = source_ref["source_file"]
        assert source_file.startswith("data/knowledge/manuals/") or source_file == "data/structured/products.json"
        assert (ROOT / source_file).exists()
        if source_file.startswith("data/knowledge/manuals/"):
            assert isinstance(source_ref["line_no"], int)
            raw_lines = (ROOT / source_file).read_text(encoding="utf-8").splitlines()
            source_text = row["source_semantic"]["source_text"].rstrip("…")
            raw_line = " ".join(raw_lines[source_ref["line_no"] - 1].split())
            assert source_text[:80] in raw_line
