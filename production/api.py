"""Minimal production HTTP surface over the existing LangGraph runtime."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from deployments.support_agent_graph import graph, production_runtime
from observability import get_default_metrics, get_default_trace_recorder
from production.health import health_check
from production.request_identity import RequestIdentityMismatch, TrustedRequestIdentity, bind_trusted_identity

app = FastAPI(title="Liorin Agent API", version="0.1.0")


class InvokeRequest(BaseModel):
    state: dict[str, Any]
    config: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 60.0


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return health_check(
        memory_backend=production_runtime.memory_backend,
        artifact_backend=production_runtime.artifact_backend,
        cache=production_runtime.cache,
    ).to_state()


@app.get("/readyz")
def readyz() -> dict[str, Any]:
    status = healthz()
    if status["status"] not in {"ok", "degraded"}:
        raise HTTPException(status_code=503, detail=status)
    return status


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> PlainTextResponse:
    registry = get_default_metrics()
    exporter = production_runtime.metrics_exporter
    if exporter is not None and exporter.__class__.__name__ == "PrometheusTextExporter":
        exporter.export(registry.snapshot())
        return PlainTextResponse(exporter.latest_text, media_type="text/plain; version=0.0.4")
    snapshot = registry.snapshot()
    lines = [f"liorin_{name} {value}" for name, value in sorted(snapshot.items())]
    return PlainTextResponse("\n".join(lines) + ("\n" if lines else ""), media_type="text/plain")


@app.get("/traces/{request_id}")
def trace(request_id: str) -> dict[str, Any]:
    item = get_default_trace_recorder().get(request_id)
    if item is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return item.to_state()


@app.post("/invoke")
async def invoke(
    request: InvokeRequest,
    tenant_id: str = Header(..., alias="X-Liorin-Tenant-Id"),
    user_id: str = Header(..., alias="X-Liorin-User-Id"),
    conversation_id: str = Header(..., alias="X-Liorin-Conversation-Id"),
    thread_id: str = Header(..., alias="X-Liorin-Thread-Id"),
    session_id: str = Header(..., alias="X-Liorin-Session-Id"),
) -> Any:
    if request.timeout_seconds <= 0:
        raise HTTPException(status_code=400, detail="timeout_seconds must be positive")
    try:
        state, config = bind_trusted_identity(
            request.state,
            request.config,
            TrustedRequestIdentity(tenant_id, user_id, conversation_id, thread_id, session_id),
        )
    except (ValueError, RequestIdentityMismatch) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        if hasattr(graph, "ainvoke"):
            return await asyncio.wait_for(
                graph.ainvoke(state, config=config),
                timeout=request.timeout_seconds,
            )
        return await asyncio.wait_for(
            asyncio.to_thread(graph.invoke, state, config),
            timeout=request.timeout_seconds,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="agent invocation timed out") from exc
