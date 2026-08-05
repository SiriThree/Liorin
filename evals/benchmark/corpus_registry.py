"""Exact mapping between production evidence metadata and benchmark chunk IDs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from .data_paths import CORPUS_PATH


@dataclass(frozen=True)
class ChunkMapping:
    benchmark_chunk_id: str | None
    production_chunk_id: str | None
    source_type: str | None
    source_file: str | None
    unmapped_reason: str | None = None


class BenchmarkCorpusRegistry:
    """Registry with exact chunk-id lookups.

    The integration deliberately does not guess by title or fuzzy text. If a
    production document has a chunk_id not present in the benchmark corpus, the
    caller gets an explicit unmapped record for diagnostics.
    """

    def __init__(self, corpus_path: str | Path = CORPUS_PATH):
        self.corpus_path = Path(corpus_path)
        self.rows: list[dict[str, Any]] = json.loads(self.corpus_path.read_text(encoding="utf-8"))
        self.by_chunk_id = {str(row["chunk_id"]): row for row in self.rows if row.get("chunk_id")}
        self.by_exact_location: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in self.rows:
            key = self._location_key(
                row.get("source_file"),
                row.get("heading"),
                row.get("source_type"),
            )
            if key:
                self.by_exact_location.setdefault(key, []).append(row)

    @staticmethod
    def _norm_text(value: Any) -> str:
        return "".join(str(value or "").split()).lower()

    @classmethod
    def _location_key(cls, source_file: Any, heading: Any, source_type: Any) -> tuple[str, str, str] | None:
        if not source_file or not heading or not source_type:
            return None
        normalized_source = "database" if source_type in {"structured_db", "database"} else str(source_type)
        return (str(source_file), str(heading), normalized_source)

    @classmethod
    def _text_matches(cls, benchmark_row: dict[str, Any], doc: Document) -> bool:
        left = cls._norm_text(benchmark_row.get("text"))
        right = cls._norm_text(doc.page_content)
        if len(left) < 20 or len(right) < 20:
            return False
        return left in right or right in left

    def map_document(self, doc: Document) -> ChunkMapping:
        metadata = doc.metadata or {}
        chunk_id = metadata.get("chunk_id")
        source_type = metadata.get("doc_type") or metadata.get("source_type") or metadata.get("source")
        source_file = metadata.get("source_file")
        if chunk_id and str(chunk_id) in self.by_chunk_id:
            return ChunkMapping(str(chunk_id), str(chunk_id), str(source_type), str(source_file))
        key = self._location_key(source_file, metadata.get("heading") or metadata.get("section"), source_type)
        if key:
            candidates = [row for row in self.by_exact_location.get(key, []) if self._text_matches(row, doc)]
            if len(candidates) == 1:
                return ChunkMapping(
                    str(candidates[0]["chunk_id"]),
                    str(chunk_id) if chunk_id else None,
                    str(candidates[0].get("source_type") or source_type),
                    str(source_file),
                )
            if len(candidates) > 1:
                return ChunkMapping(
                    None,
                    str(chunk_id) if chunk_id else None,
                    str(source_type) if source_type else None,
                    str(source_file) if source_file else None,
                    "multiple benchmark chunks match exact source_file/heading/text containment",
                )
        return ChunkMapping(
            None,
            str(chunk_id) if chunk_id else None,
            str(source_type) if source_type else None,
            str(source_file) if source_file else None,
            "production chunk_id is absent from benchmark corpus manifest",
        )

    def source_type_for(self, benchmark_chunk_id: str) -> str | None:
        row = self.by_chunk_id.get(benchmark_chunk_id)
        return str(row.get("source_type")) if row else None
