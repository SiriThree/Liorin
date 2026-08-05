"""Privacy-preserving online feedback records and reviewed-label lifecycle."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from retrieval.security import hash_identifier, redact_text


@dataclass
class FeedbackRecord:
    request_id: str
    tenant_id: str
    rating: Literal["positive", "negative", "incorrect", "unsafe", "citation_issue"]
    feedback_id: str = field(default_factory=lambda: uuid4().hex)
    comment: str | None = None
    cited_evidence_ids: list[str] = field(default_factory=list)
    status: Literal["new", "triaged", "reviewed", "exported"] = "new"
    reviewer_id: str | None = None
    reviewed_label: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_safe_state(self) -> dict[str, Any]:
        row = asdict(self)
        row["request_id"] = hash_identifier(self.request_id, namespace="feedback_request")
        row["tenant_id"] = hash_identifier(self.tenant_id, namespace="feedback_tenant")
        row["reviewer_id"] = (
            hash_identifier(self.reviewer_id, namespace="feedback_reviewer") if self.reviewer_id else None
        )
        row["comment"] = redact_text(self.comment, limit=1000) if self.comment else None
        return row


class FeedbackStore:
    def __init__(self, path: Path):
        self.path = path

    def append(self, record: FeedbackRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_safe_state(), ensure_ascii=False, sort_keys=True) + "\n")

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def triage_summary(self) -> dict[str, Any]:
        rows = self.load()
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row.get("rating") or "unknown")] = counts.get(str(row.get("rating") or "unknown"), 0) + 1
        return {
            "total": len(rows),
            "by_rating": counts,
            "review_queue_size": sum(
                row.get("rating") != "positive" and row.get("status") in {"new", "triaged"}
                for row in rows
            ),
        }

    def export_review_queue(self, destination: Path) -> int:
        """Export privacy-safe negative/citation/security feedback for human review."""
        rows = [
            row for row in self.load()
            if row.get("rating") != "positive" and row.get("status") in {"new", "triaged"}
        ]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )
        return len(rows)

    def apply_review(
        self,
        feedback_id: str,
        *,
        reviewer_id: str,
        reviewed_label: dict[str, Any],
    ) -> None:
        """Attach a human-reviewed label without converting automatic feedback to Gold."""
        rows = self.load()
        updated = False
        for row in rows:
            if row.get("feedback_id") == feedback_id:
                row["reviewer_id"] = hash_identifier(reviewer_id, namespace="feedback_reviewer")
                row["reviewed_label"] = reviewed_label
                row["status"] = "reviewed"
                updated = True
                break
        if not updated:
            raise KeyError(f"unknown feedback id: {feedback_id}")
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
