"""Cross-stage source ownership audit for Phase G0.1."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def build_ownership_inputs(root: Path) -> dict[str, set[str]]:
    """Return fact/section usage observed in earlier frozen phases.

    TROUBLESHOOTING ownership is semantic and exclusive for active F0 source
    facts. MIXED/FORMAL entries are overlaps only: a document fact already used
    by a Mixed or Formal case may still support a genuinely different pure
    Knowledge task later. G0.1 records that overlap instead of deleting truth.
    """
    f0_units = _jsonl(root / "artifacts/evaluation/dataset-expansion-f0-troubleshooting/troubleshooting_source_units.jsonl")
    troubleshooting_fact_ids: set[str] = set()
    troubleshooting_sections: set[str] = set()
    for row in f0_units:
        if row.get("benchmark_usable"):
            troubleshooting_fact_ids.update(row.get("manual_fact_ids") or [])
            if row.get("section_id"):
                troubleshooting_sections.add(row["section_id"])

    mixed_fact_ids: set[str] = set()
    mixed_sections: set[str] = set()
    for row in _jsonl(root / "artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/mixed_gold_drafts_refrozen.jsonl"):
        for f in row.get("document_facts") or []:
            sf = (f.get("metadata") or {}).get("source_fact_id")
            if sf:
                mixed_fact_ids.add(sf)
        for e in row.get("gold_evidence") or []:
            if e.get("source_type") == "DOCUMENT" and e.get("section_id"):
                mixed_sections.add(e["section_id"])

    # The repaired scope artifact exposes selected manual fact ids directly.
    for row in _jsonl(root / "artifacts/evaluation/dataset-expansion-e1r-manual-scope-repair/manual_scope_repair_ready.jsonl"):
        mixed_fact_ids.update(row.get("selected_fact_scope") or [])
        if row.get("section_id"):
            mixed_sections.add(row["section_id"])

    formal_sections: set[str] = set()
    alias = root / "artifacts/evaluation/dataset-expansion-d1/legacy_section_alias_map.json"
    if alias.exists():
        payload = json.loads(alias.read_text(encoding="utf-8"))
        for row in payload.get("aliases", []) if isinstance(payload, dict) else []:
            if row.get("resolution_status") == "RESOLVED" and row.get("current_section_id"):
                formal_sections.add(row["current_section_id"])

    return {
        "troubleshooting_fact_ids": troubleshooting_fact_ids,
        "troubleshooting_sections": troubleshooting_sections,
        "mixed_fact_ids": mixed_fact_ids,
        "mixed_sections": mixed_sections,
        "formal_sections": formal_sections,
    }


def ownership_for_fact(*, fact_id: str, section_id: str, inputs: dict[str, set[str]]) -> tuple[str, tuple[str, ...]]:
    overlaps: list[str] = []
    if section_id in inputs["formal_sections"]:
        overlaps.append("FORMAL")
    if fact_id in inputs["mixed_fact_ids"] or section_id in inputs["mixed_sections"]:
        overlaps.append("MIXED")
    if fact_id in inputs["troubleshooting_fact_ids"]:
        overlaps.append("TROUBLESHOOTING")
        return "TROUBLESHOOTING", tuple(sorted(set(overlaps)))
    # Existing Formal/Mixed usage is an observed overlap, not proof that a pure
    # document fact intrinsically requires those categories.
    return "KNOWLEDGE_AVAILABLE", tuple(sorted(set(overlaps)))
