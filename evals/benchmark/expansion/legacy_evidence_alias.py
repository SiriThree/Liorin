"""Materialise the Phase-D0 deterministic legacy-section compatibility bridge."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_legacy_section_alias_map(root: str | Path, d0_dir: str | Path) -> dict[str, Any]:
    root = Path(root)
    d0 = Path(d0_dir)
    validation = json.loads((d0 / "source_reference_validation.json").read_text(encoding="utf-8"))
    rows = []
    bad = []
    for ref in validation.get("references", []):
        if ref.get("source_type") != "DOCUMENT":
            continue
        status = str(ref.get("status") or "")
        current = str(ref.get("current_section_id") or "")
        stable_hash = current.rsplit(":sec:", 1)[-1] if ":sec:" in current else ""
        row = {
            "case_id": ref.get("case_id"),
            "legacy_ref": f"{ref.get('legacy_document_id')}#{ref.get('legacy_section_id')}",
            "document_id": ref.get("legacy_document_id"),
            "legacy_heading": ref.get("legacy_heading"),
            "legacy_section_id": ref.get("legacy_section_id"),
            "current_section_id": current or None,
            "current_stable_hash": stable_hash or None,
            "resolution_method": "EXACT_NORMALIZED_HEADING_WITHIN_DOCUMENT",
            "resolution_status": "RESOLVED" if status == "UNIQUE_HEADING_ALIAS" and current else status,
        }
        rows.append(row)
        if row["resolution_status"] != "RESOLVED":
            bad.append(row)
    payload = {
        "schema_version": "1.0",
        "source": str((d0 / "source_reference_validation.json").relative_to(root) if (d0 / "source_reference_validation.json").is_relative_to(root) else d0 / "source_reference_validation.json"),
        "total_legacy_document_refs": len(rows),
        "resolved": len(rows) - len(bad),
        "ambiguous": sum(str(x["resolution_status"]).startswith("AMBIGUOUS") for x in bad),
        "missing": sum(str(x["resolution_status"]) in {"MISSING", "MISSING_SECTION"} for x in bad),
        "all_deterministically_resolved": not bad and len(rows) == 40,
        "aliases": rows,
    }
    if len(rows) != 40 or bad:
        raise ValueError(f"legacy section alias gate failed: total={len(rows)} unresolved={len(bad)}")
    return payload
