"""Deterministic source inventories for Phase D0."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

UNICODE_ESCAPE_PATTERN = re.compile(r"#U([0-9A-Fa-f]{4,6})")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def decode_escaped_filename(value: str) -> str:
    return UNICODE_ESCAPE_PATTERN.sub(lambda m: chr(int(m.group(1), 16)), value)


def section_identifier(document_id: str, section_path: str, start: int) -> str:
    digest = hashlib.sha1(f"{document_id}|{section_path}|{start}".encode("utf-8")).hexdigest()[:12]
    return f"{document_id}:sec:{digest}"


def markdown_sections(text: str, document_id: str) -> list[dict[str, Any]]:
    matches = list(HEADING.finditer(text))
    if not matches:
        return [{"section_id": section_identifier(document_id, "root", 0), "title": "root", "path": "root", "level": 0, "start": 0, "end": len(text), "text": text}]
    rows: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    if matches[0].start() > 0 and text[:matches[0].start()].strip():
        body = text[:matches[0].start()]
        rows.append({"section_id": section_identifier(document_id, "preamble", 0), "title": "preamble", "path": "preamble", "level": 0, "start": 0, "end": matches[0].start(), "text": body})
    for idx, match in enumerate(matches):
        level = len(match.group(1)); title = match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        path = " / ".join(x[1] for x in stack)
        start = match.start(); end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        rows.append({"section_id": section_identifier(document_id, path, start), "title": title, "path": path, "level": level, "start": start, "end": end, "text": text[start:end].strip()})
    return rows


def _products(root: Path) -> dict[str, dict[str, Any]]:
    rows = json.loads((root / "data/structured/products.json").read_text(encoding="utf-8"))
    return {str(row["product_id"]): row for row in rows}


def build_document_source_inventory(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    products = _products(root)
    knowledge = root / "data/knowledge"
    files: list[tuple[Path, str]] = []
    for directory, source_type in ((knowledge / "manuals", "manual"), (knowledge / "policies", "policy"), (knowledge / "faq", "faq")):
        files.extend((path, source_type) for path in sorted(directory.glob("*.md")))
    docs, all_sections = [], []
    for path, source_type in files:
        decoded = decode_escaped_filename(path.name)
        stem = Path(decoded).stem
        text = path.read_text(encoding="utf-8", errors="replace")
        product_id = stem.split("_", 1)[0] if source_type == "manual" else None
        product = products.get(product_id or "") or {}
        document_id = stem
        sections = markdown_sections(text, document_id)
        doc = {
            "source_id": f"source:{source_type}:{document_id}",
            "document_id": document_id,
            "path": str(path.relative_to(root)),
            "source_type": source_type,
            "title": sections[0]["title"] if sections else stem,
            "product_family": product.get("category"),
            "product_id": product_id,
            "product_model": product.get("name") if source_type == "manual" else None,
            "region": None,
            "language": "zh-CN",
            "effective_from": None,
            "effective_to": None,
            "authority": "manual" if source_type == "manual" else ("policy" if source_type == "policy" else "faq"),
            "section_count": len(sections),
            "stable_section_identity_available": True,
            "benchmark_usable": True,
            "why_usable": "checked-in source with deterministic document/section identity",
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        docs.append(doc)
        for s in sections:
            all_sections.append({**s, "source_id": doc["source_id"], "document_id": document_id, "source_type": source_type, "product_id": product_id, "product_name": product.get("name")})
    return docs, all_sections


def _extract_sql_templates(source_path: Path) -> dict[str, dict[str, Any]]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    rows: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        value_node = None
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SQL_TEMPLATES" for t in node.targets):
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "SQL_TEMPLATES":
            value_node = node.value
        if not isinstance(value_node, ast.Dict):
            continue
        for key, value in zip(value_node.keys, value_node.values):
            if not isinstance(key, ast.Constant) or not isinstance(value, ast.Call):
                continue
            template_id = str(key.value)
            args = value.args
            if len(args) < 4:
                continue
            def literal(n):
                try: return ast.literal_eval(n)
                except Exception: return None
            rows[template_id] = {"template_id": template_id, "sql": literal(args[1]), "parameter_order": list(literal(args[2]) or ()), "description": literal(args[3])}
    return rows


def _select_fields(sql: str) -> list[str]:
    match = re.search(r"\bSELECT\s+(.*?)\s+FROM\s", sql or "", flags=re.I | re.S)
    if not match:
        return []
    fields = []
    for raw in match.group(1).split(","):
        item = raw.strip()
        alias = re.search(r"\s+AS\s+([A-Za-z_][A-Za-z0-9_]*)$", item, flags=re.I)
        if alias:
            fields.append(alias.group(1))
        else:
            fields.append(item.split(".")[-1].strip().strip('"`[]'))
    return fields


def build_structured_source_inventory(root: Path) -> dict[str, Any]:
    db_path = root / "data/structured/liorin.db"
    templates = _extract_sql_templates(root / "tools/database.py")
    template_fields = {tid: _select_fields(row["sql"]) for tid, row in templates.items()}
    exposed = defaultdict(set)
    # map output fields by semantic record type
    for tid, fields in template_fields.items():
        if tid == "order_events": rtype = "order_event"
        elif tid.startswith("order_") or tid == "customer_orders": rtype = "order"
        elif tid == "ticket_events": rtype = "ticket_event"
        elif tid.startswith("ticket_") or tid == "customer_tickets": rtype = "ticket"
        elif tid.startswith("warranty_"): rtype = "warranty"
        elif tid.startswith("customer_"): rtype = "customer"
        else: rtype = "unknown"
        exposed[rtype].update(fields)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        table_rows = []
        for table in tables:
            cols = [dict(cid=r[0], name=r[1], type=r[2], notnull=bool(r[3]), default=r[4], pk=bool(r[5])) for r in conn.execute(f"PRAGMA table_info({table})")]
            count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            table_rows.append({"table": table, "record_count": count, "columns": cols})
    mapping = {
        "customers": "customer", "products": "product", "orders": "order", "order_items": "order_item",
        "order_status_events": "order_event", "tickets": "ticket", "ticket_events": "ticket_event", "warranty_cases": "warranty",
    }
    for row in table_rows:
        rtype = mapping.get(row["table"], row["table"])
        row["record_type"] = rtype
        row["fields_exposed_through_production_tool"] = sorted(exposed.get(rtype, set()))
        row["fields_not_exposed_through_production_tool"] = sorted({c["name"] for c in row["columns"]} - exposed.get(rtype, set()))
    return {"database": str(db_path.relative_to(root)), "tables": table_rows, "sql_templates": [{**v, "output_fields": template_fields[k]} for k, v in sorted(templates.items())]}
