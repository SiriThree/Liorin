"""Context strategy configuration for controlled Phase-4 experiments.

This module does not implement a second context engine.  It only maps named
experiment strategies to switches already owned by ``ContextRuntime`` and
``ContextBuilder``.  The production default remains the full Liorin context,
memory and artifact policy.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any, Mapping


class ContextEvaluationStrategy(StrEnum):
    FULL_HISTORY = "FULL_HISTORY"
    SLIDING_WINDOW = "SLIDING_WINDOW"
    SUMMARY_ONLY = "SUMMARY_ONLY"
    LIORIN_CONTEXT = "LIORIN_CONTEXT"
    LIORIN_CONTEXT_MEMORY_ARTIFACT = "LIORIN_CONTEXT_MEMORY_ARTIFACT"


@dataclass(frozen=True, slots=True)
class ContextStrategyConfig:
    """Frozen, auditable context-only experiment configuration."""

    strategy: ContextEvaluationStrategy = ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT
    window_turns: int = 3
    max_tokens: int = 4096
    compaction_enabled: bool | None = None
    compaction_recent_messages: int | None = None
    selector_enabled: bool | None = None
    working_memory_enabled: bool | None = None
    long_term_memory_enabled: bool | None = None
    artifact_enabled: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, ContextEvaluationStrategy):
            object.__setattr__(self, "strategy", ContextEvaluationStrategy(str(self.strategy).upper()))
        if int(self.window_turns) <= 0:
            raise ValueError("window_turns must be greater than zero")
        if int(self.max_tokens) <= 0:
            raise ValueError("max_tokens must be greater than zero")
        object.__setattr__(self, "window_turns", int(self.window_turns))
        object.__setattr__(self, "max_tokens", int(self.max_tokens))

    @classmethod
    def for_strategy(
        cls,
        strategy: ContextEvaluationStrategy | str,
        *,
        window_turns: int = 3,
        max_tokens: int = 4096,
    ) -> "ContextStrategyConfig":
        if not isinstance(strategy, ContextEvaluationStrategy):
            strategy = ContextEvaluationStrategy(str(strategy).upper())
        values: dict[str, Any] = {
            "strategy": strategy,
            "window_turns": window_turns,
            "max_tokens": max_tokens,
        }
        if strategy is ContextEvaluationStrategy.FULL_HISTORY:
            values.update(
                compaction_enabled=False,
                selector_enabled=False,
                working_memory_enabled=False,
                long_term_memory_enabled=False,
                artifact_enabled=False,
            )
        elif strategy is ContextEvaluationStrategy.SLIDING_WINDOW:
            values.update(
                compaction_enabled=False,
                selector_enabled=False,
                working_memory_enabled=False,
                long_term_memory_enabled=False,
                artifact_enabled=False,
            )
        elif strategy is ContextEvaluationStrategy.SUMMARY_ONLY:
            values.update(
                compaction_enabled=True,
                compaction_recent_messages=0,
                selector_enabled=False,
                working_memory_enabled=False,
                long_term_memory_enabled=False,
                artifact_enabled=False,
            )
        elif strategy is ContextEvaluationStrategy.LIORIN_CONTEXT:
            values.update(
                compaction_enabled=True,
                selector_enabled=True,
                working_memory_enabled=True,
                long_term_memory_enabled=False,
                artifact_enabled=False,
            )
        elif strategy is ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT:
            values.update(
                compaction_enabled=True,
                selector_enabled=True,
                working_memory_enabled=True,
                long_term_memory_enabled=True,
                artifact_enabled=True,
            )
        return cls(**values)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ContextStrategyConfig":
        return cls(
            strategy=value.get("strategy") or ContextEvaluationStrategy.LIORIN_CONTEXT_MEMORY_ARTIFACT,
            window_turns=int(value.get("window_turns", 3)),
            max_tokens=int(value.get("max_tokens", 4096)),
            compaction_enabled=value.get("compaction_enabled"),
            compaction_recent_messages=value.get("compaction_recent_messages"),
            selector_enabled=value.get("selector_enabled"),
            working_memory_enabled=value.get("working_memory_enabled"),
            long_term_memory_enabled=value.get("long_term_memory_enabled"),
            artifact_enabled=value.get("artifact_enabled"),
        )

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["strategy"] = self.strategy.value
        return state

    @property
    def strategy_id(self) -> str:
        return self.strategy.value.casefold()

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(self.to_state(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(raw.encode("utf-8")).hexdigest()


__all__ = ["ContextEvaluationStrategy", "ContextStrategyConfig"]
