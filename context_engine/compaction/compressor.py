"""Deterministic structured compressor for historical runtime context."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping as MappingABC
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
_CORRECTION_MARKERS = ("更正", "纠正", "说错", "不是", "改成", "correct", "correction")
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
            "corrections": [],
            "pending_questions": [],
            "failed_attempts": [],
            "continuity_notes": [],
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
            if any(marker.casefold() in lowered for marker in _CORRECTION_MARKERS):
                self._append_unique(sections["corrections"], snippet)
            if "?" in snippet or "？" in snippet:
                self._append_unique(sections["pending_questions"], snippet)
            if any(marker.casefold() in lowered for marker in _FAILURE_MARKERS):
                self._append_unique(sections["failed_attempts"], snippet)
            if (
                item.type is ContextItemType.ASSISTANT_MESSAGE
                and any(marker.casefold() in lowered for marker in ("继续", "下一轮", "待确认", "continue"))
            ):
                self._append_unique(sections["continuity_notes"], snippet)

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
            "corrections",
            "pending_questions",
            "important_decisions",
            "failed_attempts",
            "continuity_notes",
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


SemanticCompactionCallable = Callable[
    [MappingABC[str, Any]],
    MappingABC[str, Iterable[str] | str],
]


@dataclass(slots=True)
class HybridSemanticContextCompressor:
    """Try semantic narrative compaction, then fall back deterministically.

    The semantic callable receives only compactable narrative history. Protected
    working memory, verified evidence, artifact references, identity metadata,
    and active task state remain outside the semantic compression boundary.
    """

    semantic_compactor: SemanticCompactionCallable | None = None
    fallback: ContextCompressor | None = None
    recent_message_count: int = 6
    summary_max_tokens: int = 512
    generated_by: str = "context_engine.compaction.HybridSemanticContextCompressor/v1"
    confidence: float = 0.74
    snippet_max_chars: int = 220
    max_items: int = 80

    def __post_init__(self) -> None:
        if self.fallback is None:
            self.fallback = ContextCompressor(
                recent_message_count=self.recent_message_count,
                summary_max_tokens=self.summary_max_tokens,
                generated_by="context_engine.compaction.ContextCompressor/fallback-v1",
            )

    def compact(self, items: Iterable[ContextItem]) -> CompactionResult:
        materialized = list(items)
        if self.semantic_compactor is None:
            return self._fallback(materialized, "semantic_compactor_not_configured")

        identity: IdentityContext
        try:
            identity = ContextCompressor._resolve_identity(materialized)
            compactable = [item for item in materialized if is_compactable_history(item)]
            assert self.fallback is not None
            compacted_items = self.fallback._select_old_history(compactable)
            if not compacted_items:
                raise ValueError("No historical ContextItems are eligible for compaction")
            content = self._semantic_content(compacted_items)
            summary = self._summary(compacted_items, identity, content)
            summary_item = CompactionReconstructor().to_context_item(summary)
            compacted_ids = {item.id for item in compacted_items}
            preserved = [item for item in materialized if item.id not in compacted_ids]
            return CompactionResult(
                items=tuple(preserved + [summary_item]),
                summary=summary,
                compacted_item_ids=tuple(item.id for item in compacted_items),
                preserved_item_ids=tuple(item.id for item in preserved),
                attributes={
                    "compaction_mode": "hybrid_semantic",
                    "semantic_compaction_applied": True,
                    "semantic_item_count": len(compacted_items),
                    "source_history_retained": True,
                    "tool_output_content_retained": False,
                },
            )
        except Exception as exc:
            return self._fallback(materialized, f"{type(exc).__name__}: {exc}")

    def _fallback(self, items: list[ContextItem], reason: str) -> CompactionResult:
        assert self.fallback is not None
        result = self.fallback.compact(items)
        attributes = {
            **dict(result.attributes),
            "compaction_mode": "hybrid_semantic",
            "semantic_compaction_applied": False,
            "semantic_compaction_failed": True,
            "fallback_mode": "deterministic",
            "fallback_reason": reason,
        }
        return CompactionResult(
            items=result.items,
            summary=result.summary,
            compacted_item_ids=result.compacted_item_ids,
            preserved_item_ids=result.preserved_item_ids,
            validation=result.validation,
            attributes=attributes,
        )

    def _semantic_content(self, items: list[ContextItem]) -> dict[str, list[str]]:
        payload = {
            "schema": {
                "sections": [
                    "task_progress",
                    "important_decisions",
                    "confirmed_information",
                    "corrections",
                    "pending_questions",
                    "failed_attempts",
                    "continuity_notes",
                ]
            },
            "items": [
                {
                    "id": item.id,
                    "type": item.type.value,
                    "role": item.metadata.get("role"),
                    "sequence": item.metadata.get("sequence"),
                    "content": self._snippet(item),
                }
                for item in items[: self.max_items]
            ],
        }
        assert self.semantic_compactor is not None
        raw = self.semantic_compactor(payload)
        if not isinstance(raw, MappingABC):
            raise TypeError("semantic compactor must return a mapping")
        allowed_sections = set(payload["schema"]["sections"])
        unknown_sections = set(raw) - allowed_sections
        if unknown_sections:
            raise ValueError(
                "semantic compactor returned unsupported sections: "
                + ", ".join(sorted(str(section) for section in unknown_sections))
            )
        content = {key: self._section_values(raw.get(key)) for key in allowed_sections}
        content = self._fallback_fill(content, items)
        return self._fit_summary_budget(content)

    def _section_values(self, raw: Iterable[str] | str | None) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            values = [raw]
        else:
            values = list(raw)
        return [str(value).strip() for value in values if str(value).strip()]

    def _fallback_fill(
        self,
        content: dict[str, list[str]],
        items: list[ContextItem],
    ) -> dict[str, list[str]]:
        if content["task_progress"]:
            return content
        assert self.fallback is not None
        deterministic = self.fallback._build_structured_content(items)
        return {
            key: content.get(key) or list(deterministic.get(key) or [])
            for key in content
        }

    def _fit_summary_budget(
        self,
        content: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        assert self.fallback is not None
        original_limit = self.fallback.summary_max_tokens
        try:
            self.fallback.summary_max_tokens = self.summary_max_tokens
            return self.fallback._fit_summary_budget(content)
        finally:
            self.fallback.summary_max_tokens = original_limit

    def _summary(
        self,
        compacted_items: list[ContextItem],
        identity: IdentityContext,
        content: dict[str, list[str]],
    ) -> CompactionSummary:
        original_token_cost = sum(int(item.token_cost or 0) for item in compacted_items)
        provisional = CompactionSummary(
            summary_content=content,
            summary_metadata=SummaryMetadata(
                source_range=ContextCompressor._source_range(compacted_items),
                generated_by=self.generated_by,
                confidence=self.confidence,
                created_at=datetime.now(timezone.utc),
                original_token_cost=original_token_cost,
                compressed_token_cost=0,
                identity_context=identity,
            ),
            identity_context=identity,
        )
        rendered = CompactionReconstructor().render_content(provisional)
        return CompactionSummary(
            summary_content=content,
            summary_metadata=SummaryMetadata(
                source_range=provisional.summary_metadata.source_range,
                generated_by=self.generated_by,
                confidence=self.confidence,
                created_at=provisional.summary_metadata.created_at,
                original_token_cost=original_token_cost,
                compressed_token_cost=estimate_token_cost(rendered),
                identity_context=identity,
            ),
            identity_context=identity,
        )

    def _snippet(self, item: ContextItem) -> str:
        text = re.sub(r"\s+", " ", item.content).strip()
        if len(text) > self.snippet_max_chars:
            text = text[: self.snippet_max_chars - 1].rstrip() + "…"
        return text
