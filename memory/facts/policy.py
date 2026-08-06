"""Deterministic promotion policy for long-term MemoryFact candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from math import ceil
from memory.facts.models import MemoryFactCandidate, MemoryFactSource, display_value


_TRANSIENT_OR_SENSITIVE_KEYS = {
    "customer_id",
    "customer_email",
    "email",
    "phone",
    "order_id",
    "ticket_id",
    "error_code",
    "identity_status",
    "workflow_stage",
    "current_intent",
    "open_question",
    "next_action",
    "completed_turn",
}

_STABLE_KEY_HINTS = (
    "product_model",
    "product_name",
    "device_model",
    "preferred_language",
    "language_preference",
    "communication_preference",
    "accessibility_preference",
    "region",
    "timezone",
    "preferred_contact_channel",
)


@dataclass(frozen=True, slots=True)
class MemoryPolicyDecision:
    approved: bool
    reason: str
    criteria: Mapping[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "criteria": dict(self.criteria),
        }


class MemoryFactPolicy:
    """Evaluate stability, future value, trust, identity and expiry risk."""

    def __init__(
        self,
        *,
        minimum_confidence: float = 0.8,
        maximum_value_tokens: int = 256,
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")
        if maximum_value_tokens <= 0:
            raise ValueError("maximum_value_tokens must be greater than zero")
        self.minimum_confidence = float(minimum_confidence)
        self.maximum_value_tokens = int(maximum_value_tokens)

    def evaluate(
        self,
        candidate: MemoryFactCandidate,
        *,
        now: datetime | None = None,
    ) -> MemoryPolicyDecision:
        now = now or datetime.now(timezone.utc)
        key = candidate.key.casefold()
        source = candidate.source.casefold()
        criteria = {
            "stable": self._is_stable(candidate),
            "future_reuse": self._has_future_reuse(candidate),
            "trusted_source": self._trusted_source(candidate),
            "identity_bound": not candidate.identity_context.is_anonymous,
            "not_expired": candidate.expires_at is None or candidate.expires_at > now,
            "bounded_value": max(1, ceil(len(display_value(candidate.value).encode("utf-8")) / 4))
            <= self.maximum_value_tokens,
            "confidence_sufficient": candidate.confidence >= self.minimum_confidence,
        }
        if key in _TRANSIENT_OR_SENSITIVE_KEYS or any(
            key.startswith(f"{prefix}.") for prefix in _TRANSIENT_OR_SENSITIVE_KEYS
        ):
            return MemoryPolicyDecision(False, "transient or sensitive key is not long-term memory", criteria)
        if not criteria["identity_bound"]:
            return MemoryPolicyDecision(False, "anonymous identity cannot own long-term memory", criteria)
        if not criteria["not_expired"]:
            return MemoryPolicyDecision(False, "candidate is already expired", criteria)
        if not criteria["bounded_value"]:
            return MemoryPolicyDecision(False, "candidate value exceeds fact size policy", criteria)
        if not criteria["stable"] or not criteria["future_reuse"]:
            return MemoryPolicyDecision(False, "candidate is not stable/reusable enough", criteria)
        if not criteria["trusted_source"] or not criteria["confidence_sufficient"]:
            return MemoryPolicyDecision(False, "candidate source/confidence is insufficient", criteria)
        if source == MemoryFactSource.AGENT_INFERENCE.value and not candidate.verified:
            return MemoryPolicyDecision(False, "unverified agent inference cannot be promoted", criteria)
        return MemoryPolicyDecision(True, "stable identity-bound fact approved", criteria)

    @staticmethod
    def _is_stable(candidate: MemoryFactCandidate) -> bool:
        metadata = candidate.metadata
        if metadata.get("stable") is not None:
            return bool(metadata.get("stable"))
        key = candidate.key.casefold()
        return key in _STABLE_KEY_HINTS or candidate.source in {
            MemoryFactSource.USER_CONFIRMATION.value,
            MemoryFactSource.BUSINESS_SYSTEM.value,
        }

    @staticmethod
    def _has_future_reuse(candidate: MemoryFactCandidate) -> bool:
        metadata = candidate.metadata
        if metadata.get("future_reuse") is not None:
            return bool(metadata.get("future_reuse"))
        key = candidate.key.casefold()
        return key in _STABLE_KEY_HINTS

    @staticmethod
    def _trusted_source(candidate: MemoryFactCandidate) -> bool:
        source = candidate.source.casefold()
        if source in {
            MemoryFactSource.USER_CONFIRMATION.value,
            MemoryFactSource.BUSINESS_SYSTEM.value,
        }:
            return candidate.verified and candidate.confidence >= 0.9
        if source == MemoryFactSource.WORKFLOW_STATE.value:
            return candidate.confidence >= 0.8
        if source == MemoryFactSource.AGENT_INFERENCE.value:
            return candidate.verified and candidate.confidence >= 0.9
        # legacy checkpoints are intentionally conservative and are never
        # silently promoted as verified facts.
        return False


# Public name requested by the Phase 5 contract.
MemoryPolicy = MemoryFactPolicy


__all__ = ["MemoryFactPolicy", "MemoryPolicy", "MemoryPolicyDecision"]
