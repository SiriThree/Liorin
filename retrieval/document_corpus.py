"""Versioned local corpus with a Document -> Section -> Chunk hierarchy."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from langchain_core.documents import Document

from config import BASE_PATH, DEFAULT_DB_PATH
from retrieval.filters import document_matches_filters, principal_can_access
from retrieval.metadata import (
    HEADING_PATTERN,
    base_metadata_for_file,
    chunk_identifier,
    extract_error_codes,
    extract_product_models,
    infer_section_type,
    section_identifier,
    metadata_time_epoch,
)
from retrieval.protocols import RetrievalFilters, RetrievalPrincipal
from retrieval.security import mark_document_security, validate_document_file

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
CORPUS_SCHEMA_VERSION = "stage2.1-document-section-chunk"


@dataclass(frozen=True)
class MarkdownSection:
    document_id: str
    section_id: str
    title: str
    section_path: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class CorpusSnapshot:
    version: str
    documents: tuple[Document, ...]
    sections: dict[str, str]
    section_metadata: dict[str, dict[str, Any]]
    security_incidents: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def _knowledge_files() -> list[Path]:
    root = BASE_PATH / "data" / "knowledge"
    files: list[Path] = []
    for directory in (root / "manuals", root / "policies", root / "faq"):
        if directory.exists():
            files.extend(sorted(directory.glob("*.md")))
    return files


def corpus_version() -> str:
    """Return a content-version key used by corpus, BM25 and metadata indexes."""

    pieces: list[str] = [f"schema:{CORPUS_SCHEMA_VERSION}"]
    for path in _knowledge_files():
        stat = path.stat()
        pieces.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
    if DEFAULT_DB_PATH.exists():
        stat = DEFAULT_DB_PATH.stat()
        pieces.append(f"{DEFAULT_DB_PATH}:{stat.st_mtime_ns}:{stat.st_size}")
    return hashlib.sha256("|".join(pieces).encode("utf-8")).hexdigest()[:20]


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str, int]:
    if not text.startswith("---\n"):
        return {}, text, 0
    closing = text.find("\n---\n", 4)
    if closing < 0:
        return {}, text, 0
    raw = text[4:closing]
    body_start = closing + 5
    try:
        import yaml

        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            parsed = {}
    except Exception:
        parsed = {}
        for line in raw.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            parsed[key.strip()] = value.strip().strip('"\'')
    return parsed, text[body_start:], body_start


def _sectionize(text: str, document_id: str, *, offset: int = 0) -> list[MarkdownSection]:
    matches = list(HEADING_PATTERN.finditer(text))
    if not matches:
        section_id = section_identifier(document_id, "root", offset)
        return [
            MarkdownSection(
                document_id=document_id,
                section_id=section_id,
                title="root",
                section_path="root",
                start=offset,
                end=offset + len(text),
                text=text,
            )
        ]

    sections: list[MarkdownSection] = []
    heading_stack: list[tuple[int, str]] = []
    if matches[0].start() > 0 and text[: matches[0].start()].strip():
        preamble = text[: matches[0].start()]
        section_id = section_identifier(document_id, "preamble", offset)
        sections.append(
            MarkdownSection(
                document_id=document_id,
                section_id=section_id,
                title="preamble",
                section_path="preamble",
                start=offset,
                end=offset + matches[0].start(),
                text=preamble,
            )
        )

    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, title))
        section_path = " / ".join(item[1] for item in heading_stack)
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        section_id = section_identifier(document_id, section_path, offset + start)
        sections.append(
            MarkdownSection(
                document_id=document_id,
                section_id=section_id,
                title=title,
                section_path=section_path,
                start=offset + start,
                end=offset + end,
                text=section_text,
            )
        )
    return sections


def _chunk_section(section: MarkdownSection) -> Iterable[tuple[int, int, str]]:
    text = section.text
    if len(text) <= CHUNK_SIZE:
        yield section.start, section.start + len(text), text
        return
    cursor = 0
    chunk_index = 0
    while cursor < len(text):
        end = min(len(text), cursor + CHUNK_SIZE)
        if end < len(text):
            newline = text.rfind("\n", cursor + CHUNK_SIZE // 2, end)
            if newline > cursor:
                end = newline
        chunk = text[cursor:end].strip()
        if chunk:
            yield section.start + cursor, section.start + end, chunk
            chunk_index += 1
        if end >= len(text):
            break
        cursor = max(cursor + 1, end - CHUNK_OVERLAP)


def _load_markdown_chunks(path: Path, doc_type: str) -> tuple[list[Document], dict[str, str], dict[str, dict[str, Any]]]:
    validate_document_file(path)
    raw_text = path.read_text(encoding="utf-8")
    front_matter, body, body_offset = _parse_front_matter(raw_text)
    base = base_metadata_for_file(path, doc_type, raw_text, front_matter=front_matter)
    mark_document_security(base, raw_text)
    document_id = str(base["document_id"])
    chunks: list[Document] = []
    sections: dict[str, str] = {}
    section_metadata: dict[str, dict[str, Any]] = {}
    for section in _sectionize(body, document_id, offset=body_offset):
        sections[section.section_id] = section.text
        section_error_codes = extract_error_codes(section.text)
        section_product_models = base.get("product_models") or extract_product_models(section.text)
        common = {
            **base,
            "section_id": section.section_id,
            "parent_id": section.section_id,
            "section": section.title,
            "section_path": section.section_path,
            "section_start": section.start,
            "section_end": section.end,
            "section_type": infer_section_type(section.text, section.title),
            "error_codes": section_error_codes,
            "product_models": section_product_models,
        }
        if section_error_codes:
            common["error_code"] = section_error_codes[0]
        if section_product_models:
            common["product_model"] = section_product_models[0]
        section_metadata[section.section_id] = dict(common)
        for chunk_index, (chunk_start, chunk_end, chunk_text) in enumerate(_chunk_section(section)):
            chunk_error_codes = extract_error_codes(chunk_text)
            chunk_product_models = base.get("product_models") or extract_product_models(chunk_text)
            metadata = {
                **common,
                "chunk_id": chunk_identifier(section.section_id, chunk_index),
                "chunk_start": chunk_start,
                "chunk_end": chunk_end,
                "start_index": chunk_start,  # compatibility alias
                "error_codes": chunk_error_codes,
                "product_models": chunk_product_models,
                "page": None,
            }
            if chunk_error_codes:
                metadata["error_code"] = chunk_error_codes[0]
            else:
                metadata.pop("error_code", None)
            if chunk_product_models:
                metadata["product_model"] = chunk_product_models[0]
            else:
                metadata.pop("product_model", None)
            chunks.append(Document(page_content=chunk_text, metadata=metadata))
    return chunks, sections, section_metadata


def _load_ticket_history_documents(limit: int = 500) -> tuple[list[Document], dict[str, str], dict[str, dict[str, Any]]]:
    if not DEFAULT_DB_PATH.exists():
        return [], {}, {}
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    conn.row_factory = sqlite3.Row
    query = """
        SELECT t.ticket_id, t.parent_ticket_id, t.customer_id, c.tenant_id,
               t.product_id, p.name AS product_name, t.order_id, t.issue_type,
               t.priority, t.status, t.created_at, t.summary, t.channel,
               t.assigned_team, t.customer_sentiment,
               GROUP_CONCAT(te.event_type || '@' || te.happened_at, ' -> ') AS events
        FROM tickets t
        JOIN customers c ON c.customer_id = t.customer_id
        LEFT JOIN products p ON p.product_id = t.product_id
        LEFT JOIN ticket_events te ON te.ticket_id = t.ticket_id
        GROUP BY t.ticket_id
        ORDER BY t.created_at DESC
        LIMIT ?
    """
    rows = conn.execute(query, (limit,)).fetchall()
    conn.close()
    docs: list[Document] = []
    sections: dict[str, str] = {}
    section_metadata: dict[str, dict[str, Any]] = {}
    for row in rows:
        content = (
            f"历史工单 {row['ticket_id']}\n"
            f"产品：{row['product_name']}（{row['product_id']}）\n"
            f"订单：{row['order_id'] or '未知'}\n"
            f"问题类型：{row['issue_type']}\n"
            f"优先级：{row['priority']}；当前状态：{row['status']}；创建时间：{row['created_at']}\n"
            f"处理团队：{row['assigned_team']}；客户情绪：{row['customer_sentiment']}\n"
            f"摘要：{row['summary'] or '空摘要'}\n"
            f"事件链路：{row['events'] or '无'}"
        )
        document_id = str(row["ticket_id"])
        section_id = section_identifier(document_id, "历史工单", 0)
        metadata = {
            "document_id": document_id,
            "doc_id": document_id,
            "section_id": section_id,
            "chunk_id": chunk_identifier(section_id, 0),
            "parent_id": section_id,
            "section": "历史工单",
            "section_path": "历史工单",
            "section_start": 0,
            "section_end": len(content),
            "chunk_start": 0,
            "chunk_end": len(content),
            "doc_type": "ticket_history",
            "source": "ticket_history",
            "source_file": "liorin.db:tickets",
            "version": str(row["created_at"]),
            "effective_from": row["created_at"],
            "effective_to": None,
            "effective_from_ts": metadata_time_epoch(row["created_at"]),
            "effective_to_ts": 0,
            "tenant_id": row["tenant_id"],
            "allowed_user_ids": [row["customer_id"]],
            "allowed_groups": [],
            "required_permissions": ["ticket:read"],
            "classification": "confidential",
            "visibility": "private",
            "owner": row["customer_id"],
            "source_trust": "internal_database",
            "security_status": "safe",
            "prompt_injection_risk": 0,
            "security_finding_types": [],
            "contains_pii_types": ["ticket_id", "order_id", "customer_id"],
            "acl_identity_public": False,
            "active": row["status"] != "deleted",
            "ticket_id": row["ticket_id"],
            "parent_ticket_id": row["parent_ticket_id"],
            "customer_id": row["customer_id"],
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "order_id": row["order_id"],
            "issue_type": row["issue_type"],
            "status": row["status"],
            "section_type": "ticket_history",
            "language": "zh-CN",
            "region": None,
            "error_codes": extract_error_codes(content),
            "product_models": extract_product_models(content),
            "page": None,
        }
        docs.append(Document(page_content=content, metadata=metadata))
        sections[section_id] = content
        section_metadata[section_id] = dict(metadata)
    return docs, sections, section_metadata


@lru_cache(maxsize=4)
def _load_snapshot(version: str) -> CorpusSnapshot:
    chunks: list[Document] = []
    sections: dict[str, str] = {}
    section_metadata: dict[str, dict[str, Any]] = {}
    security_incidents: list[dict[str, Any]] = []
    root = BASE_PATH / "data" / "knowledge"
    for directory, doc_type in (
        (root / "manuals", "manual"),
        (root / "policies", "policy"),
        (root / "faq", "faq"),
    ):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*")):
            if not path.is_file():
                continue
            try:
                file_chunks, file_sections, file_meta = _load_markdown_chunks(path, doc_type)
            except (OSError, UnicodeError, ValueError) as exc:
                security_incidents.append({
                    "file_name": path.name,
                    "doc_type": doc_type,
                    "status": "isolated",
                    "error_type": type(exc).__name__,
                })
                continue
            chunks.extend(file_chunks)
            sections.update(file_sections)
            section_metadata.update(file_meta)
    ticket_docs, ticket_sections, ticket_meta = _load_ticket_history_documents()
    chunks.extend(ticket_docs)
    sections.update(ticket_sections)
    section_metadata.update(ticket_meta)
    for document in chunks:
        document.metadata["corpus_version"] = version
    for metadata in section_metadata.values():
        metadata["corpus_version"] = version
    return CorpusSnapshot(version, tuple(chunks), sections, section_metadata, tuple(security_incidents))


def get_corpus_snapshot(version: str | None = None) -> CorpusSnapshot:
    return _load_snapshot(version or corpus_version())


def load_chunked_documents(version: str | None = None) -> list[Document]:
    """Return chunks for the current version; cache invalidates when inputs change."""

    return list(get_corpus_snapshot(version).documents)


def clear_corpus_cache() -> None:
    _load_snapshot.cache_clear()


def _section_window(
    text: str,
    *,
    section_start: int,
    anchor_start: int | None,
    anchor_end: int | None,
    max_chars: int,
) -> str:
    """Keep the section heading and a window around the matched chunk."""

    if len(text) <= max_chars:
        return text
    relative_start = max(0, (anchor_start or section_start) - section_start)
    relative_end = max(relative_start, (anchor_end or anchor_start or section_start) - section_start)
    heading_end = text.find("\n")
    heading = text[: heading_end + 1] if 0 <= heading_end < 300 else text[: min(240, len(text))]
    separator = "\n…\n"
    window_budget = max(200, max_chars - len(heading) - len(separator))
    center = (relative_start + relative_end) // 2
    window_start = max(0, center - window_budget // 2)
    window_end = min(len(text), window_start + window_budget)
    window_start = max(0, window_end - window_budget)
    if window_start <= len(heading):
        return text[:max_chars]
    return (heading + separator + text[window_start:window_end])[:max_chars]


def get_section_context(
    section_id: str | None,
    *,
    principal: RetrievalPrincipal,
    filters: RetrievalFilters,
    max_chars: int = 2400,
    anchor_start: int | None = None,
    anchor_end: int | None = None,
    corpus_version: str | None = None,
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """Return an authorized section window and metadata.

    Returns ``(context, metadata, denial_reason)``. ACL is evaluated independently
    from metadata filters so observability does not mislabel a hierarchy mismatch as
    a permission denial.
    """

    if not section_id:
        return None, None, None
    snapshot = get_corpus_snapshot(corpus_version) if corpus_version else get_corpus_snapshot()
    metadata = snapshot.section_metadata.get(section_id)
    if metadata is None:
        return None, None, None
    if not principal_can_access(metadata, principal):
        return None, metadata, "parent_section_permission_denied"
    if not document_matches_filters(metadata, filters, principal):
        return None, metadata, "parent_section_filter_mismatch"
    text = snapshot.sections.get(section_id)
    if not text:
        return None, metadata, None
    return (
        _section_window(
            text,
            section_start=int(metadata.get("section_start") or 0),
            anchor_start=anchor_start,
            anchor_end=anchor_end,
            max_chars=max_chars,
        ),
        metadata,
        None,
    )


def get_parent_context(
    parent_id: str | None,
    max_chars: int = 2400,
    *,
    principal: RetrievalPrincipal | None = None,
    filters: RetrievalFilters | None = None,
) -> str | None:
    """Compatibility wrapper; production callers must pass principal and filters."""

    principal = principal or RetrievalPrincipal.anonymous()
    filters = filters or RetrievalFilters(tenant_id=principal.tenant_id)
    context, _metadata, _denial = get_section_context(
        parent_id,
        principal=principal,
        filters=filters,
        max_chars=max_chars,
    )
    return context


def corpus_debug_manifest() -> str:
    snapshot = get_corpus_snapshot()
    return json.dumps(
        {
            "version": snapshot.version,
            "chunks": len(snapshot.documents),
            "sections": len(snapshot.sections),
            "security_incidents": len(snapshot.security_incidents),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
