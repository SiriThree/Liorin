"""Runtime instrumentation helpers used by existing Agent tools."""
from __future__ import annotations

from contextlib import nullcontext
from hashlib import sha256
from time import perf_counter
from typing import Any, Callable, TypeVar

from observability.events import RuntimeEventType
from observability.metrics import get_default_metrics
from observability.trace import get_default_trace_recorder
from reliability import RetryPolicy, execute_with_timeout

T = TypeVar("T")


def invoke_observed_tool(
    tool_name: str,
    operation: Callable[[], T],
    *,
    timeout_seconds: float,
    retry_policy: RetryPolicy | None = None,
    input_preview: str = "",
) -> T:
    recorder = get_default_trace_recorder()
    existing = recorder.current()
    request_id = "tool:" + sha256(f"{tool_name}|{input_preview}".encode("utf-8")).hexdigest()[:20]
    trace_context = (
        nullcontext(existing)
        if existing is not None
        else recorder.trace(
            request_id=request_id,
            conversation_id="conversation:tool-execution",
            thread_id="thread:tool-execution",
            agent_name="conversation_supervisor",
        )
    )
    started = perf_counter()
    with trace_context:
        recorder.emit(RuntimeEventType.TOOL_STARTED, attributes={"tool_name": tool_name, "input_preview": input_preview[:300]})
        try:
            call = lambda: execute_with_timeout(operation, timeout_seconds)
            result = retry_policy.execute(call) if retry_policy is not None else call()
        except Exception as exc:
            latency = (perf_counter() - started) * 1000
            get_default_metrics().increment("tool_failure_count")
            get_default_metrics().observe("tool_latency_ms", latency)
            recorder.emit(RuntimeEventType.TOOL_FAILED, attributes={"tool_name": tool_name, "latency_ms": latency, "error": type(exc).__name__})
            raise
        latency = (perf_counter() - started) * 1000
        get_default_metrics().increment("tool_success_count")
        get_default_metrics().observe("tool_latency_ms", latency)
        recorder.emit(RuntimeEventType.TOOL_COMPLETED, attributes={"tool_name": tool_name, "latency_ms": latency, "success": True})
        return result
