"""Deterministic structured compressor for historical runtime context."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any

from context_engine.models import (
    ContextItem,
    ContextItemType,
    SummaryMetadata,
    SummarySourceRange,
    estimate_token_cost,
)
from context_engine.compaction.models import CompactionResult, CompactionSummary
from context_engine.compaction.reconstructor import CompactionReconstructor
from context_engine.compaction.trigger import is_compactable_history
from identity import IdentityContext


_DECISION_MARKERS = ("决定", "选择", "采用", "确认执行", "下一步", "方案", "decision")
_CONFIRMATION_MARKERS = ("确认", "型号", "订单", "客户", "邮箱", "错误码", "事实", "confirmed")
_FAILURE_MARKERS = ("失败", "未找到", "无法", "错误", "超时", "拒绝", "not found", "failed")


@dataclass(slots=True)
class ContextCompressor:
    """Replace old messages/tool observations with one structured summary."""

    recent_message_count: int = 6
    summary_max_tokens: int = 512
    generated_by: str = "context_engine.compaction.ContextCompressor/v1"
    confidence: float = 0.8
    snippet_max_chars: int = 180
    max_entries_per_section: int = 8
    reconstructor: CompactionReconstructor | None = None

    def __post_init__(self) -> None:
        if self.recent_message_count < 0:
            raise ValueError("recent_message_count must not be negative")
        if self.summary_max_tokens <= 0:
            raise ValueError("summary_max_tokens must be greater than zero")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.snippet_max_chars <= 0 or self.max_entries_per_section <= 0:
            raise ValueError("summary limits must be greater than zero")
        if self.reconstructor is None:
            self.reconstructor = CompactionReconstructor()

    def compact(self, items: Iterable[ContextItem]) -> CompactionResult:
        materialized = list(items)
        identity = self._resolve_identity(materialized)
        compactable = [item for item in materialized if is_compactable_history(item)]
        compacted_items = self._select_old_history(compactable)
        if not compacted_items:
            raise ValueError("No historical ContextItems are eligible for compaction")

        compacted_ids = {item.id for item in compacted_items}
        preserved = [item for item in materialized if item.id not in compacted_ids]
        original_token_cost = sum(int(item.token_cost or 0) for item in compacted_items)
        content = self._build_structured_content(compacted_items)
        content = self._fit_summary_budget(content)

        assert self.reconstructor is not None
        provisional_summary = CompactionSummary(
            summary_content=content,
            summary_metadata=SummaryMetadata(
                source_range=self._source_range(compacted_items),
                generated_by=self.generated_by,
                confidence=self.confidence,
                created_at=datetime.now(timezone.utc),
                original_token_cost=original_token_cost,
                compressed_token_cost=0,
                identity_context=identity,
            ),
            identity_context=identity,
        )
        rendered = self.reconstructor.render_content(provisional_summary)
        compressed_cost = estimate_token_cost(rendered)
        summary = CompactionSummary(
            summary_content=content,
            summary_metadata=SummaryMetadata(
                source_range=provisional_summary.summary_metadata.source_range,
                generated_by=self.generated_by,
                confidence=self.confidence,
                created_at=provisional_summary.summary_metadata.created_at,
                original_token_cost=original_token_cost,
                compressed_token_cost=compressed_cost,
                identity_context=identity,
            ),
            identity_context=identity,
        )
        summary_item = self.reconstructor.to_context_item(summary)
        result_items = tuple(preserved + [summary_item])
        return CompactionResult(
            items=result_items,
            summary=summary,
            compacted_item_ids=tuple(item.id for item in compacted_items),
            preserved_item_ids=tuple(item.id for item in preserved),
            attributes={
                "recent_message_count": self.recent_message_count,
                "source_history_retained": True,
                "tool_output_content_retained": False,
                "artifact_reference_count": sum(
                    1
                    for item in compacted_items
                    if item.type is ContextItemType.ARTIFACT_REFERENCE
                    and item.metadata.get("artifact_id")
                ),
            },
        )

    def _select_old_history(self, compactable: list[ContextItem]) -> list[ContextItem]:
        dialogue = sorted(
            [
                item
                for item in compactable
                if item.type in {
                    ContextItemType.USER_MESSAGE,
                    ContextItemType.ASSISTANT_MESSAGE,
                }
            ],
            key=lambda item: int(item.metadata.get("sequence", 0)),
        )
        retained_dialogue_ids = {
            item.id
            for item in (
                dialogue[-self.recent_message_count :]
                if self.recent_message_count
                else []
            )
        }
        return [
            item
            for item in compactable
            if item.id not in retained_dialogue_ids
        ]

    @staticmethod
    def _resolve_identity(items: list[ContextItem]) -> IdentityContext:
        identities = {
            json.dumps(
                item.metadata.get("identity_context"),
                ensure_ascii=False,
                sort_keys=True,
            )
            for item in items
            if item.metadata.get("identity_context") is not None
        }
        if len(identities) != 1:
            raise ValueError("Compaction requires one consistent IdentityContext")
        raw = json.loads(next(iter(identities)))
        return IdentityContext.from_state(raw)

    def _build_structured_content(
        self, items: list[ContextItem]
    ) -> dict[str, list[str]]:
        chronological = sorted(
            items,
            key=lambda item: int(item.metadata.get("sequence", 0)),
        )
        user_count = sum(item.type is ContextItemType.USER_MESSAGE for item in items)
        assistant_count = sum(item.type is ContextItemType.ASSISTANT_MESSAGE for item in items)
        tool_count = sum(item.type is ContextItemType.ARTIFACT_REFERENCE for item in items)
        progress = [
            f"已压缩历史上下文 {len(items)} 项：用户消息 {user_count}、助手消息 {assistant_count}、工具观察 {tool_count}。"
        ]
        if tool_count:
            tool_ids = [
                str(item.metadata.get("artifact_id") or item.id)
                for item in items
                if item.type is ContextItemType.ARTIFACT_REFERENCE
            ]
            progress.append(
                "历史工具观察仅保留引用：" + "、".join(tool_ids[:6])
                + ("…" if len(tool_ids) > 6 else "")
            )

        sections: dict[str, list[str]] = {
            "task_progress": progress,
            "important_decisions": [],
            "confirmed_information": [],
            "pending_questions": [],
            "failed_attempts": [],
        }
        for item in chronological:
            if item.type is ContextItemType.ARTIFACT_REFERENCE:
                continue
            snippet = self._snippet(item)
            lowered = snippet.casefold()
            if any(marker.casefold() in lowered for marker in _DECISION_MARKERS):
                self._append_unique(sections["important_decisions"], snippet)
            if any(marker.casefold() in lowered for marker in _CONFIRMATION_MARKERS):
                self._append_unique(sections["confirmed_information"], snippet)
            if "?" in snippet or "？" in snippet:
                self._append_unique(sections["pending_questions"], snippet)
            if any(marker.casefold() in lowered for marker in _FAILURE_MARKERS):
                self._append_unique(sections["failed_attempts"], snippet)

        # Ensure the summary remains useful even when the deterministic markers
        # do not match domain-specific phrasing.
        if not sections["confirmed_information"]:
            for item in chronological:
                if item.type is ContextItemType.USER_MESSAGE:
                    self._append_unique(
                        sections["confirmed_information"], self._snippet(item)
                    )
                    if len(sections["confirmed_information"]) >= 2:
                        break
        return sections

    def _snippet(self, item: ContextItem) -> str:
        role = str(item.metadata.get("role") or item.type.value).lower()
        text = re.sub(r"\s+", " ", item.content).strip()
        if len(text) > self.snippet_max_chars:
            text = text[: self.snippet_max_chars - 1].rstrip() + "…"
        return f"{role}: {text}"

    def _append_unique(self, values: list[str], value: str) -> None:
        if value and value not in values and len(values) < self.max_entries_per_section:
            values.append(value)

    def _fit_summary_budget(
        self, content: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        fitted = {key: list(values) for key, values in content.items()}

        def token_cost() -> int:
            return estimate_token_cost(
                json.dumps(
                    fitted,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )

        removable_order = (
            "confirmed_information",
            "pending_questions",
            "important_decisions",
            "failed_attempts",
            "task_progress",
        )
        while token_cost() > self.summary_max_tokens:
            removable = next(
                (
                    key
                    for key in removable_order
                    if len(fitted[key]) > (1 if key == "task_progress" else 0)
                ),
                None,
            )
            if removable is None:
                break
            fitted[removable].pop(0)

        if token_cost() > self.summary_max_tokens:
            for key in removable_order:
                fitted[key] = [
                    value[:80].rstrip() + ("…" if len(value) > 80 else "")
                    for value in fitted[key]
                ]
        return fitted

    @staticmethod
    def _source_range(items: list[ContextItem]) -> SummarySourceRange:
        sequences = [
            int(item.metadata.get("sequence", 0))
            for item in items
            if item.type in {
                ContextItemType.USER_MESSAGE,
                ContextItemType.ASSISTANT_MESSAGE,
                ContextItemType.ARTIFACT_REFERENCE,
            }
        ]
        return SummarySourceRange(
            start_turn=min(sequences) if sequences else None,
            end_turn=max(sequences) if sequences else None,
            source_item_ids=tuple(item.id for item in items),
        )
