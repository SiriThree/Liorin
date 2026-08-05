"""Gold isolation and reproducible evaluation run metadata."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any

FORBIDDEN_RUNTIME_KEYS = frozenset({
    "gold", "reviewed_gold", "reviewed_gold_v7_4", "qrels", "expected_action",
    "expected_document_ids", "expected_section_ids", "required_atomic_facts",
    "forbidden_sources", "outdated_sources",
})


def find_gold_paths(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if str(key).casefold() in FORBIDDEN_RUNTIME_KEYS or "gold" in str(key).casefold():
                found.append(child)
            found.extend(find_gold_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(find_gold_paths(item, f"{path}[{index}]"))
    return found


def assert_no_gold_leak(runtime_packet: Any) -> None:
    paths = find_gold_paths(runtime_packet)
    if paths:
        raise ValueError("gold fields entered runtime packet: " + ", ".join(paths[:10]))


def config_fingerprint(config: dict[str, Any]) -> str:
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def build_run_metadata(
    *,
    root: Path,
    dataset_path: Path,
    split: str,
    index_manifest: dict[str, Any] | None,
    model_versions: dict[str, str],
    config: dict[str, Any],
    mock_mode: bool,
) -> dict[str, Any]:
    dataset_hash = sha256(dataset_path.read_bytes()).hexdigest()
    return {
        "code_version": _git_commit(root) or "unversioned-checkout",
        "dataset_hash": dataset_hash,
        "split": split,
        "index_manifest": index_manifest,
        "model_versions": model_versions,
        "config_fingerprint": config_fingerprint(config),
        "mock_mode": mock_mode,
        "result_claim_level": "mock_only" if mock_mode else "runtime_measured",
    }
