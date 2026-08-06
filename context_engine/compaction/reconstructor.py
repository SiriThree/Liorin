"""Reconstruct compacted summaries into ContextItems."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json

from context_engine.models import ContextItem, ContextItemType
from context_engine.compaction.models import CompactionSummary


class CompactionReconstructor:
    """Convert an auditable CompactionSummary into model-visible context."""

    source = "context_engine.compaction"

    @staticmethod
    def render_content(summary: CompactionSummary) -> str:
        return json.dumps(
            {
                key: list(values)
                for key, values in summary.summary_content.items()
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_context_item(self, summary: CompactionSummary) -> ContextItem:
        content = self.render_content(summary)
        digest = sha256(content.encode("utf-8")).hexdigest()[:16]
        metadata = summary.summary_metadata
        return ContextItem(
            id=f"compaction-summary-{digest}",
            type=ContextItemType.SUMMARY,
            content=content,
            source=self.source,
            priority=78,
            timestamp=metadata.created_at,
            metadata={
                "required": False,
                "compaction_summary": True,
                "summary_metadata": metadata.to_state(),
                "summary_metadata_status": "validated",
                "eligible_for_compaction_metrics": True,
                "identity_context": summary.identity_context,
                "dedupe_key": "summary:context_compaction",
                "sequence": -10,
            },
        )
