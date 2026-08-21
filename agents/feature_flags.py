"""Auditable Production feature switches used by controlled Evaluation experiments.

Defaults preserve the deployed Liorin behavior.  Evaluation may build the same
Production graph with one or more switches disabled; no benchmark-specific Agent
implementation is created here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AgentFeatureConfig:
    agentic_recovery_enabled: bool = True
    evidence_verifier_enabled: bool = True
    query_rewrite_enabled: bool = True
    supplement_enabled: bool = True
    clarification_recovery_enabled: bool = True
    reranker_enabled: bool = True
    parent_expansion_enabled: bool = True
    entity_scoped_routing_enabled: bool = False
    semantic_verifier_enabled: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "AgentFeatureConfig":
        raw = dict(value or {})
        return cls(**{name: bool(raw.get(name, getattr(cls(), name))) for name in asdict(cls())})

    def to_state(self) -> dict[str, bool]:
        return {name: bool(value) for name, value in asdict(self).items()}

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(self.to_state(), sort_keys=True, separators=(",", ":"))
        return sha256(raw.encode("utf-8")).hexdigest()


FULL_AGENT_FEATURES = AgentFeatureConfig()

__all__ = ["AgentFeatureConfig", "FULL_AGENT_FEATURES"]
