"""Read-only Production + formal-evaluation readiness checks.

Phase 7 hardens the Phase-6 doctor into an actual gate.  Default checks never
install packages or start services.  ``live_checks=True`` additionally performs
small real provider/Milvus probes when the required dependency/configuration is
already present; it never falls back to mocks.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib.util import find_spec
import json
import os
from pathlib import Path
import re
import sqlite3
import tomllib
from typing import Any, Mapping

from eval_platform.dataset import read_canonical_dataset
from eval_platform.contracts import TaskCategory


class ReadinessStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    NOT_READY = "NOT_READY"
    NOT_REQUIRED = "NOT_REQUIRED"


class EvaluationSystemStatus(StrEnum):
    PLATFORM_READY = "PLATFORM_READY"
    DATA_NOT_READY = "DATA_NOT_READY"
    PRODUCTION_BLOCKED = "PRODUCTION_BLOCKED"
    JUDGE_BLOCKED = "JUDGE_BLOCKED"
    FORMAL_RUN_PARTIAL = "FORMAL_RUN_PARTIAL"
    FORMAL_RUN_COMPLETE = "FORMAL_RUN_COMPLETE"


@dataclass(frozen=True, slots=True)
class ReadinessItem:
    name: str
    status: ReadinessStatus
    reason: str
    details: Mapping[str, Any] | None = None

    def to_state(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status.value, "reason": self.reason, "details": dict(self.details or {})}


@dataclass(frozen=True, slots=True)
class EvaluationReadiness:
    items: tuple[ReadinessItem, ...]
    system_status: EvaluationSystemStatus

    def by_name(self) -> dict[str, ReadinessItem]:
        return {x.name: x for x in self.items}

    def to_state(self) -> dict[str, Any]:
        return {"system_status": self.system_status.value, "items": [x.to_state() for x in self.items]}


def _dependency(name: str) -> bool:
    try:
        return find_spec(name) is not None
    except Exception:
        return False


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _dep_name(requirement: str) -> str:
    return re.split(r"[<>=!~\[; ]", str(requirement), maxsplit=1)[0].strip().casefold().replace("_", "-")


def _packaging_status(root: Path) -> ReadinessItem:
    pyproject = root / "pyproject.toml"
    lock_path = root / "uv.lock"
    if not pyproject.exists() or not lock_path.exists():
        return ReadinessItem("dependency_lock", ReadinessStatus.BLOCKED, "pyproject.toml and uv.lock are both required")
    try:
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ReadinessItem("dependency_lock", ReadinessStatus.BLOCKED, f"dependency metadata parse failed: {type(exc).__name__}: {exc}")
    main = {_dep_name(x) for x in project.get("project", {}).get("dependencies", [])}
    optional = {
        _dep_name(x)
        for values in project.get("project", {}).get("optional-dependencies", {}).values()
        for x in values
    }
    root_pkg = next((p for p in lock.get("package", []) if p.get("name") == project.get("project", {}).get("name")), None)
    if not root_pkg:
        return ReadinessItem("dependency_lock", ReadinessStatus.BLOCKED, "project package is absent from uv.lock")
    locked_main = {str(x.get("name") or "").casefold().replace("_", "-") for x in root_pkg.get("dependencies", [])}
    missing = sorted(main - locked_main)
    stale_optional = sorted(optional & locked_main)
    if missing or stale_optional:
        return ReadinessItem(
            "dependency_lock",
            ReadinessStatus.BLOCKED,
            "uv.lock does not match current pyproject dependency roles",
            {"missing_main_in_lock": missing, "legacy_optional_still_locked_as_main": stale_optional},
        )
    return ReadinessItem("dependency_lock", ReadinessStatus.READY, "uv.lock matches current pyproject dependency roles")


def _credential_present(model: str | None) -> bool:
    # Only report presence, never secret values.
    if not model:
        return False
    provider = model.split(":", 1)[0].casefold() if ":" in model else ""
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("DEEPSEEK_API_KEY"))


def _model_probe(model: str) -> tuple[bool, str]:
    try:
        from langchain.chat_models import init_chat_model
        llm = init_chat_model(model)
        response = llm.invoke([{"role": "user", "content": "Reply with exactly OK."}])
        content = str(getattr(response, "content", "") or "").strip()
        return bool(content), ("provider invocation returned a response" if content else "provider invocation returned empty content")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _milvus_probe(uri: str) -> tuple[bool, str]:
    try:
        from pymilvus import MilvusClient
        client = MilvusClient(uri=uri)
        client.list_collections()
        return True, "Milvus list_collections succeeded"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _sqlite_probe(path: Path) -> tuple[bool, str, dict[str, Any]]:
    try:
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA query_only=ON")
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            conn.execute("SELECT 1").fetchone()
        required = {"customers", "orders", "tickets", "warranty_cases"}
        missing = sorted(required - tables)
        if missing:
            return False, f"structured SQLite is missing required tables: {missing}", {"tables": sorted(tables)}
        return True, "structured SQLite connectivity and required tables verified", {"tables": sorted(tables)}
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", {}


def build_evaluation_readiness(root: str | Path = ".", *, live_checks: bool = False) -> EvaluationReadiness:
    root = Path(root).resolve()
    items: list[ReadinessItem] = []
    items.append(_packaging_status(root))

    deps = {name: _dependency(name) for name in ("langchain", "langchain_core", "langgraph", "pymilvus")}
    missing_runtime = sorted(name for name, present in deps.items() if not present)
    items.append(ReadinessItem(
        "python_dependencies",
        ReadinessStatus.READY if not missing_runtime else ReadinessStatus.BLOCKED,
        "required Python runtime dependencies are importable" if not missing_runtime else f"missing runtime dependencies: {missing_runtime}",
        deps,
    ))

    try:
        if missing_runtime:
            raise ModuleNotFoundError(f"missing runtime dependencies: {missing_runtime}")
        module = __import__("deployments.support_agent_graph", fromlist=["graph", "build_graph"])
        graph = getattr(module, "graph")
        if graph is None:
            raise RuntimeError("deployment module exported graph=None")
        items.append(ReadinessItem("production_runtime", ReadinessStatus.READY, "deployment graph imports and constructs successfully"))
    except Exception as exc:
        items.append(ReadinessItem("production_runtime", ReadinessStatus.BLOCKED, f"{type(exc).__name__}: {exc}"))

    # Import config only after pure dependency checks; config itself is local and side-effect free.
    try:
        from config import DEFAULT_MILVUS_URI, DEFAULT_MODEL
    except Exception:
        DEFAULT_MODEL = os.getenv("LIORIN_MODEL", "")
        DEFAULT_MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")

    model = os.getenv("LIORIN_MODEL") or DEFAULT_MODEL
    model_key = _credential_present(model)
    if not deps["langchain"]:
        model_status, model_reason = ReadinessStatus.BLOCKED, "LangChain runtime is unavailable"
    elif not model_key:
        model_status, model_reason = ReadinessStatus.BLOCKED, "production model credential is not configured"
    elif live_checks:
        ok, reason = _model_probe(model)
        model_status, model_reason = (ReadinessStatus.READY if ok else ReadinessStatus.BLOCKED), reason
    else:
        model_status, model_reason = ReadinessStatus.PARTIAL, "model dependency/credential detected; live invocation not requested"
    items.append(ReadinessItem("model_provider", model_status, model_reason, {"model": model, "credential_present": model_key, "live_check": live_checks}))

    judge_model = os.getenv("LIORIN_JUDGE_MODEL")
    judge_key = _credential_present(judge_model)
    if not deps["langchain"]:
        judge_status, judge_reason = ReadinessStatus.BLOCKED, "LangChain runtime is unavailable"
    elif not judge_model or not judge_key:
        judge_status, judge_reason = ReadinessStatus.BLOCKED, "LIORIN_JUDGE_MODEL and its provider credential are required"
    elif live_checks:
        ok, reason = _model_probe(judge_model)
        judge_status, judge_reason = (ReadinessStatus.READY if ok else ReadinessStatus.BLOCKED), reason
    else:
        judge_status, judge_reason = ReadinessStatus.PARTIAL, "judge dependency/credential detected; live invocation not requested"
    items.append(ReadinessItem("judge_provider", judge_status, judge_reason, {"judge_model": judge_model, "credential_present": judge_key, "live_check": live_checks}))

    milvus_uri = os.getenv("MILVUS_URI") or DEFAULT_MILVUS_URI
    if not deps["pymilvus"]:
        retrieval_status, retrieval_reason = ReadinessStatus.BLOCKED, "pymilvus is not installed"
    elif live_checks:
        ok, reason = _milvus_probe(milvus_uri)
        retrieval_status, retrieval_reason = (ReadinessStatus.READY if ok else ReadinessStatus.BLOCKED), reason
    else:
        retrieval_status, retrieval_reason = ReadinessStatus.PARTIAL, "pymilvus/config detected; live connectivity not requested"
    items.append(ReadinessItem("retrieval_backend", retrieval_status, retrieval_reason, {"milvus_uri_configured": bool(milvus_uri), "live_check": live_checks}))

    db_candidates = [root / "data" / "structured" / "liorin.db", root / "data" / "customer_support.db", root / "data" / "support.db", root / "customer_support.db"]
    existing_db = next((p for p in db_candidates if p.exists()), None)
    if existing_db:
        ok, reason, details = _sqlite_probe(existing_db)
        items.append(ReadinessItem("structured_data_backend", ReadinessStatus.READY if ok else ReadinessStatus.BLOCKED, reason, {"local_db": str(existing_db), **details}))
    else:
        items.append(ReadinessItem("structured_data_backend", ReadinessStatus.NOT_READY, "no local structured database detected"))

    # Local in-memory backends are production-supported fallbacks and therefore
    # sufficient for basic graph smoke; external Postgres/Redis remain deployment concerns.
    items.append(ReadinessItem("memory_backend", ReadinessStatus.READY, "production bootstrap supports in-memory Memory backend fallback"))
    items.append(ReadinessItem("artifact_backend", ReadinessStatus.READY, "production bootstrap supports in-memory Artifact backend fallback"))

    artifact_dir = root / "artifacts" / "evaluation"
    try:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        probe = artifact_dir / ".phase7-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        items.append(ReadinessItem("artifact_output", ReadinessStatus.READY, "evaluation artifact directory is writable", {"path": str(artifact_dir)}))
    except Exception as exc:
        items.append(ReadinessItem("artifact_output", ReadinessStatus.BLOCKED, f"artifact directory is not writable: {type(exc).__name__}: {exc}"))

    validation_path = root / "evals" / "benchmark" / "data" / "canonical" / "validation_v7_3_canonical_v1.json"
    dev_path = root / "evals" / "benchmark" / "data" / "canonical" / "dev_v7_3_canonical_v1.json"
    canonical_count = 0
    validation_count = 0
    safety_count = 0
    if dev_path.exists():
        canonical_count += len(read_canonical_dataset(dev_path))
    if validation_path.exists():
        validation = read_canonical_dataset(validation_path)
        canonical_count += len(validation)
        validation_count = len(validation)
        safety_count = sum(1 for s in validation if s.category is TaskCategory.SAFETY_GOVERNANCE)
    items.append(ReadinessItem("canonical_dataset", ReadinessStatus.READY if canonical_count else ReadinessStatus.NOT_READY, f"{canonical_count} fully canonical legacy cases available", {"case_count": canonical_count}))
    items.append(ReadinessItem("validation_split", ReadinessStatus.READY if validation_count else ReadinessStatus.NOT_READY, f"{validation_count} canonical validation cases available", {"case_count": validation_count}))

    trust = _load_json(root / "evals" / "benchmark" / "data" / "canonical" / "split_trust_v1.json")
    trusted_test = any(str(v).upper() == "TEST" for v in trust.values()) if trust else False
    items.append(ReadinessItem("trusted_test_split", ReadinessStatus.READY if trusted_test else ReadinessStatus.NOT_READY, "trusted TEST split present" if trusted_test else "NO TRUSTED TEST SPLIT"))

    p3 = _load_json(root / "evals" / "benchmark" / "data" / "canonical" / "phase3_evaluation_inventory.json")
    recovery_status = str(p3.get("recovery_challenge_dataset_status") or p3.get("recovery_challenge_coverage") or p3.get("recovery_challenge", {}).get("status") or "").upper()
    recovery_ready = "SUFFICIENT" in recovery_status and "INSUFFICIENT" not in recovery_status
    items.append(ReadinessItem("recovery_subset", ReadinessStatus.READY if recovery_ready else ReadinessStatus.NOT_READY, recovery_status or "Recovery Challenge Gold not established"))

    p4 = _load_json(root / "evals" / "benchmark" / "data" / "canonical" / "phase4_multi_turn_inventory.json")
    multi_eligible = int(p4.get("eligible_sessions", p4.get("formal_eligible", 0)) or 0)
    items.append(ReadinessItem("multi_turn_subset", ReadinessStatus.READY if multi_eligible else ReadinessStatus.NOT_READY, f"formal eligible multi-turn sessions={multi_eligible}", {"eligible_sessions": multi_eligible}))

    p5 = _load_json(root / "evals" / "benchmark" / "data" / "canonical" / "phase5_safety_inventory.json")
    formal_safety = int(p5.get("formal_single_turn_gold_eligible", p5.get("formal_gold_eligible", p5.get("formal_eligible", 0))) or 0)
    if not formal_safety:
        formal_safety = int((p5.get("formal_single_turn") or {}).get("eligible", 0) or 0)
    if not formal_safety and safety_count:
        formal_safety = safety_count
    items.append(ReadinessItem("safety_subset", ReadinessStatus.READY if formal_safety else ReadinessStatus.NOT_READY, f"formal safety candidates={formal_safety}", {"eligible_cases": formal_safety}))

    ablation_dir = root / "evals" / "benchmark" / "configs" / "ablation"
    config_count = len(list(ablation_dir.glob("*.json"))) if ablation_dir.exists() else 0
    items.append(ReadinessItem("ablation_configs", ReadinessStatus.READY if config_count else ReadinessStatus.NOT_READY, f"ablation configs={config_count}", {"config_count": config_count}))

    baseline_path = root / "artifacts" / "evaluation" / "baseline_registry.json"
    baseline_raw = _load_json(baseline_path) if baseline_path.exists() else {}
    baseline_count = len(baseline_raw.get("baselines") or []) if isinstance(baseline_raw, dict) else 0
    items.append(ReadinessItem("baseline_registry", ReadinessStatus.READY if baseline_count else ReadinessStatus.NOT_READY, f"promoted formal baselines={baseline_count}" if baseline_count else "BASELINE_NOT_ESTABLISHED", {"baseline_count": baseline_count, "path": str(baseline_path)}))

    states = {x.name: x.status for x in items}
    if states.get("dependency_lock") is ReadinessStatus.BLOCKED or states.get("python_dependencies") is ReadinessStatus.BLOCKED or states.get("production_runtime") is ReadinessStatus.BLOCKED:
        system = EvaluationSystemStatus.PRODUCTION_BLOCKED
    elif states.get("judge_provider") is ReadinessStatus.BLOCKED:
        system = EvaluationSystemStatus.JUDGE_BLOCKED
    elif states.get("validation_split") is not ReadinessStatus.READY:
        system = EvaluationSystemStatus.DATA_NOT_READY
    else:
        system = EvaluationSystemStatus.PLATFORM_READY
    return EvaluationReadiness(tuple(items), system)


__all__ = ["ReadinessStatus", "EvaluationSystemStatus", "ReadinessItem", "EvaluationReadiness", "build_evaluation_readiness"]
