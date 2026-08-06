"""Security and governance policy chain for MemoryFact promotion."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from memory.facts.models import MemoryFactCandidate, display_value
from memory.facts.policy import MemoryFactPolicy, MemoryPolicyDecision


_SENSITIVE_KEY_PARTS = {
    "password", "passwd", "secret", "api_key", "access_token", "refresh_token",
    "credit_card", "card_number", "cvv", "ssn", "身份证", "银行卡", "密码", "密钥",
    "customer_email", "email", "phone", "mobile",
}
_SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:sk|api)[-_][A-Za-z0-9_-]{16,}\b", re.I),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{8,}\d)(?!\d)"),
)
_INJECTION_PATTERNS = (
    re.compile(r"ignore (?:all |any )?(?:previous|prior) instructions", re.I),
    re.compile(r"reveal (?:the )?(?:system|developer) prompt", re.I),
    re.compile(r"system prompt", re.I),
    re.compile(r"developer message", re.I),
    re.compile(r"忽略(?:以上|之前|先前).{0,12}(?:指令|要求|规则)"),
    re.compile(r"(?:泄露|输出|显示).{0,10}(?:系统提示词|开发者消息)"),
    re.compile(r"越狱|jailbreak", re.I),
)


@dataclass(frozen=True, slots=True)
class MemoryContentValidation:
    valid: bool
    reason: str
    sensitive: bool = False
    prompt_injection: bool = False


class MemoryContentValidator:
    def __init__(self, *, maximum_chars: int = 4096) -> None:
        self.maximum_chars = int(maximum_chars)

    def validate(self, candidate: MemoryFactCandidate) -> MemoryContentValidation:
        key = candidate.key.casefold()
        rendered = display_value(candidate.value)
        if any(part in key for part in _SENSITIVE_KEY_PARTS):
            return MemoryContentValidation(False, "sensitive memory key rejected", sensitive=True)
        if len(rendered) > self.maximum_chars:
            return MemoryContentValidation(False, "memory content exceeds governance length limit")
        if any(ord(char) < 32 and char not in "\n\r\t" for char in rendered):
            return MemoryContentValidation(False, "memory content contains invalid control characters")
        if any(pattern.search(rendered) for pattern in _SENSITIVE_PATTERNS):
            return MemoryContentValidation(False, "obvious sensitive content rejected", sensitive=True)
        if any(pattern.search(rendered) for pattern in _INJECTION_PATTERNS):
            return MemoryContentValidation(False, "prompt injection content rejected", prompt_injection=True)
        return MemoryContentValidation(True, "content validation passed")


class GovernedMemoryPolicy:
    """Run security validation before the existing deterministic promotion policy."""

    def __init__(
        self,
        *,
        base_policy: MemoryFactPolicy | None = None,
        validator: MemoryContentValidator | None = None,
    ) -> None:
        self.base_policy = base_policy or MemoryFactPolicy()
        self.validator = validator or MemoryContentValidator()

    def evaluate(
        self,
        candidate: MemoryFactCandidate,
        *,
        now: datetime | None = None,
    ) -> MemoryPolicyDecision:
        try:
            validation = self.validator.validate(candidate)
            if not validation.valid:
                return MemoryPolicyDecision(
                    False,
                    validation.reason,
                    {
                        "content_valid": False,
                        "sensitive": validation.sensitive,
                        "prompt_injection": validation.prompt_injection,
                    },
                )
            base = self.base_policy.evaluate(candidate, now=now)
            return MemoryPolicyDecision(
                base.approved,
                base.reason,
                {**dict(base.criteria), "content_valid": True},
            )
        except Exception as exc:
            return MemoryPolicyDecision(
                False,
                "memory policy failure; fail-closed rejection",
                {"policy_error": type(exc).__name__},
            )


__all__ = ["GovernedMemoryPolicy", "MemoryContentValidation", "MemoryContentValidator"]
