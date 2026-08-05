from __future__ import annotations

import copy
import re
from typing import Any

from .models import AnnotationEnvelope

IGNORE_PATHS = {"/confidence", "/rationale"}
SET_LIKE_PATH_SUFFIXES = {
    "/quality_issues", "/clarification_slots", "/must_not_invent",
    "/required_sources", "/conditional_sources", "/optional_sources",
    "/forbidden_sources", "/forbidden_claims", "/allowed_actions",
    "/reason_codes", "/supplemental_sources", "/required_actions",
}


def _norm_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip()).lower()
    return value


def normalize_for_compare(value: Any, path: str = "") -> Any:
    if isinstance(value, dict):
        return {
            key: normalize_for_compare(val, f"{path}/{key}")
            for key, val in sorted(value.items())
            if f"{path}/{key}" not in IGNORE_PATHS
        }
    if isinstance(value, list):
        normalized = [normalize_for_compare(item, path) for item in value]
        if any(path.endswith(suffix) for suffix in SET_LIKE_PATH_SUFFIXES):
            return sorted(normalized, key=repr)
        if path.endswith("/requirements") or path.endswith("/atomic_facts"):
            return sorted(normalized, key=repr)
        return normalized
    return _norm_scalar(value)


def diff_annotations(annotation_a: dict[str, Any], annotation_b: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    _diff(annotation_a, annotation_b, "", conflicts)
    return conflicts


def _diff(a: Any, b: Any, path: str, conflicts: list[dict[str, Any]]) -> None:
    if path in IGNORE_PATHS:
        return
    if type(a) is not type(b):
        conflicts.append({"path": path or "/", "value_a": a, "value_b": b})
        return
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            p = f"{path}/{key}"
            if p in IGNORE_PATHS:
                continue
            if key not in a:
                conflicts.append({"path": p, "value_a": None, "value_b": b[key]})
            elif key not in b:
                conflicts.append({"path": p, "value_a": a[key], "value_b": None})
            else:
                _diff(a[key], b[key], p, conflicts)
        return
    if isinstance(a, list):
        if normalize_for_compare(a, path) != normalize_for_compare(b, path):
            conflicts.append({"path": path or "/", "value_a": a, "value_b": b})
        return
    if _norm_scalar(a) != _norm_scalar(b):
        conflicts.append({"path": path or "/", "value_a": a, "value_b": b})


def _decode_pointer(path: str) -> list[str]:
    if path in {"", "/"}:
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in path.lstrip("/").split("/")]


def set_json_pointer(document: dict[str, Any], path: str, value: Any) -> None:
    parts = _decode_pointer(path)
    if not parts:
        if not isinstance(value, dict):
            raise ValueError("root replacement must be an object")
        document.clear(); document.update(value); return
    cursor: Any = document
    for part in parts[:-1]:
        if not isinstance(cursor, dict):
            raise ValueError(f"cannot traverse non-object at {path}")
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def merge_with_resolutions(annotation_a: dict[str, Any], annotation_b: dict[str, Any], conflicts: list[dict[str, Any]], resolutions: list[dict[str, Any]]) -> dict[str, Any]:
    merged = copy.deepcopy(annotation_a)
    expected = {item["path"] for item in conflicts}
    actual = {item["path"] for item in resolutions}
    if expected != actual:
        raise ValueError("resolution paths do not match conflict paths")
    for item in resolutions:
        set_json_pointer(merged, item["path"], item["value"])
    merged["confidence"] = min(float(annotation_a.get("confidence", 0.0)), float(annotation_b.get("confidence", 0.0)))
    merged["rationale"] = "Adjudicated from independent A/B annotations."
    return AnnotationEnvelope.model_validate({"annotation": merged}).annotation.model_dump(mode="json")
