from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from .io_utils import read_json, sha256_json

ID_PATTERN = re.compile(r"(?:LIO-PROD-\d{3}|ORD-\d{4}-\d+|TCK-\d{4}-\d+|WAR-\d{4}-\d+|[A-Z]{1,5}[-_]?[A-Z0-9]{2,})", re.I)


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    ascii_tokens = re.findall(r"[a-z]+[a-z0-9_-]*|\d+(?:\.\d+)?", text)
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    cjk_tokens: list[str] = []
    for run in cjk_runs:
        cjk_tokens.extend(run)
        cjk_tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        if len(run) <= 8:
            cjk_tokens.append(run)
    ids = [match.group(0).lower() for match in ID_PATTERN.finditer(text)]
    return ascii_tokens + cjk_tokens + ids


@dataclass(frozen=True)
class IndexedChunk:
    payload: dict[str, Any]
    tokens: Counter[str]


class SourceIndex:
    def __init__(self, corpus_path: str, candidate_pool_paths: list[str] | None = None):
        corpus = read_json(corpus_path)
        if not isinstance(corpus, list):
            raise ValueError("corpus JSON must be a list")
        self.corpus: list[dict[str, Any]] = corpus
        self.by_chunk_id = {str(item["chunk_id"]): item for item in corpus}
        self._docs = [IndexedChunk(item, Counter(tokenize(self._text(item)))) for item in corpus]
        df: Counter[str] = Counter()
        for doc in self._docs:
            df.update(doc.tokens.keys())
        self._idf = {
            term: math.log(1 + (len(self._docs) - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }
        self._avgdl = sum(sum(doc.tokens.values()) for doc in self._docs) / max(1, len(self._docs))
        self.external_candidate_pools: dict[str, list[str]] = defaultdict(list)
        for pool_path in candidate_pool_paths or []:
            self._load_candidate_pool(pool_path)
        products = {}
        for item in corpus:
            pid = item.get("product_id")
            if pid and item.get("product_name"):
                products[pid] = {"product_id": pid, "product_name": item.get("product_name")}
        self.product_catalog = [products[key] for key in sorted(products)]


    def _load_candidate_pool(self, path: str) -> None:
        raw = read_json(path)
        rows = raw if isinstance(raw, list) else raw.get("predictions", raw.get("rows", []))
        if not isinstance(rows, list):
            raise ValueError(f"candidate pool must contain a list: {path}")
        for row in rows:
            sample_id = str(row.get("id") or row.get("sample_id") or "")
            prediction = row.get("prediction", row)
            ranked = prediction.get("ranked_chunk_ids") or row.get("ranked_chunk_ids") or []
            if not sample_id or not isinstance(ranked, list):
                continue
            for chunk_id in ranked:
                chunk_id = str(chunk_id)
                if chunk_id in self.by_chunk_id and chunk_id not in self.external_candidate_pools[sample_id]:
                    self.external_candidate_pools[sample_id].append(chunk_id)

    def adjacent_chunk_ids(self, chunk_ids: Iterable[str], radius: int = 1) -> list[str]:
        result: list[str] = []
        for chunk_id in chunk_ids:
            item = self.by_chunk_id.get(chunk_id)
            if not item:
                continue
            doc_id = item.get("document_id") or item.get("doc_id")
            ordinal = item.get("ordinal")
            if ordinal is None:
                continue
            for candidate in self.corpus:
                if (candidate.get("document_id") or candidate.get("doc_id")) != doc_id:
                    continue
                other = candidate.get("ordinal")
                if isinstance(other, int) and 0 < abs(other - ordinal) <= radius:
                    cid = str(candidate.get("chunk_id"))
                    if cid and cid not in result:
                        result.append(cid)
        return result

    @staticmethod
    def _text(item: dict[str, Any]) -> str:
        fields = [
            item.get("chunk_id"),
            item.get("source_type"),
            item.get("product_id"),
            item.get("product_name"),
            item.get("heading"),
            item.get("text"),
            item.get("record_id"),
            item.get("document_id"),
        ]
        return " ".join(str(x) for x in fields if x)

    def search(
        self,
        query: str,
        *,
        top_k: int = 16,
        source_types: Iterable[str] | None = None,
        product_id: str | None = None,
        include_chunk_ids: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        q = Counter(tokenize(query))
        allowed = set(source_types or [])
        scores: list[tuple[float, dict[str, Any]]] = []
        k1 = 1.5
        b = 0.75
        for doc in self._docs:
            item = doc.payload
            if allowed and item.get("source_type") not in allowed:
                continue
            if product_id and item.get("product_id") not in {None, product_id}:
                continue
            dl = sum(doc.tokens.values())
            score = 0.0
            for term, qtf in q.items():
                tf = doc.tokens.get(term, 0)
                if not tf:
                    continue
                denom = tf + k1 * (1 - b + b * dl / max(1.0, self._avgdl))
                score += self._idf.get(term, 0.0) * (tf * (k1 + 1) / denom) * min(2, qtf)
            exact_boost = 0.0
            text_lower = self._text(item).lower()
            for identifier in ID_PATTERN.findall(query or ""):
                if identifier.lower() in text_lower:
                    exact_boost += 8.0
            if product_id and item.get("product_id") == product_id:
                exact_boost += 2.0
            score += exact_boost
            if score > 0:
                scores.append((score, item))
        scores.sort(key=lambda pair: (-pair[0], str(pair[1].get("chunk_id"))))
        if not scores:
            fallback = []
            for doc in self._docs:
                item = doc.payload
                if allowed and item.get("source_type") not in allowed:
                    continue
                if product_id and item.get("product_id") not in {None, product_id}:
                    continue
                fallback.append(item)
                if len(fallback) >= top_k:
                    break
            scores = [(0.0, item) for item in fallback]
        selected = [self.compact(item, score, query) for score, item in scores[:top_k]]
        seen = {row["chunk_id"] for row in selected}
        for chunk_id in include_chunk_ids or []:
            if chunk_id in seen or chunk_id not in self.by_chunk_id:
                continue
            selected.append(self.compact(self.by_chunk_id[chunk_id], None, query))
            seen.add(chunk_id)
        return selected

    @staticmethod
    def _query_centered_snippet(text: str, query: str, max_chars: int = 3200) -> str:
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        if max_chars <= 2:
            return text[:max_chars]
        terms = sorted({t for t in tokenize(query) if len(t) >= 2}, key=len, reverse=True)
        lower = text.lower()
        positions = [lower.find(term.lower()) for term in terms]
        positions = [pos for pos in positions if pos >= 0]
        if not positions:
            return text[:max_chars]
        center = min(positions)
        start = max(0, center - max_chars // 3)
        end = min(len(text), start + max_chars)
        start = max(0, end - max_chars)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(text) else ""
        return (prefix + text[start:end] + suffix)[:max_chars]

    @classmethod
    def compact(cls, item: dict[str, Any], score: float | None, query: str = "") -> dict[str, Any]:
        text = str(item.get("text") or "")
        return {
            "chunk_id": item.get("chunk_id"),
            "source_type": item.get("source_type"),
            "source_file": item.get("source_file"),
            "heading": item.get("heading"),
            "product_id": item.get("product_id"),
            "product_name": item.get("product_name"),
            "record_id": item.get("record_id"),
            "text": cls._query_centered_snippet(text, query),
            "retrieval_score": round(score, 6) if score is not None else None,
        }

    def build_packet(self, sample: dict[str, Any], *, top_k: int, retrieval_pool_size: int, max_chars: int) -> dict[str, Any]:
        layer = sample["layer"]
        clean_input = sample.get("input", {})
        question = self._extract_query(clean_input)
        packet: dict[str, Any] = {
            "sample_id": sample["id"],
            "layer": layer,
            "input": clean_input,
            "source_context": [],
        }
        if layer == "agent_behavior":
            packet["source_context"] = self._context_from_state(clean_input.get("state_fixture", {}))
        elif layer == "answer_generation":
            packet["source_context"] = clean_input.get("evidences", [])
        else:
            source_types = None
            product_id = None
            if layer == "retrieval":
                scope = clean_input.get("source_scope")
                if scope in {"manual", "policy", "faq", "ticket_history", "database"}:
                    source_types = [scope]
                product_id = (clean_input.get("filters") or {}).get("product_id")
                count = retrieval_pool_size
            else:
                count = top_k
            external_ids = self.external_candidate_pools.get(str(sample["id"]), [])
            lexical = self.search(question, top_k=count, source_types=source_types, product_id=product_id)
            if layer == "retrieval":
                pooled: list[dict[str, Any]] = []
                seen: set[str] = set()
                # External pools can be BM25/Dense/Hybrid runs. Include them before filling from the local lexical pool.
                for chunk_id in external_ids:
                    item = self.by_chunk_id.get(chunk_id)
                    if not item:
                        continue
                    if source_types and item.get("source_type") not in set(source_types):
                        continue
                    if product_id and item.get("product_id") not in {None, product_id}:
                        continue
                    pooled.append(self.compact(item, None, question)); seen.add(chunk_id)
                for row in lexical:
                    cid = str(row.get("chunk_id"))
                    if cid not in seen:
                        pooled.append(row); seen.add(cid)
                seed_ids = [str(row.get("chunk_id")) for row in pooled[:8] if row.get("chunk_id")]
                for chunk_id in self.adjacent_chunk_ids(seed_ids, radius=1):
                    if chunk_id in seen or chunk_id not in self.by_chunk_id:
                        continue
                    item = self.by_chunk_id[chunk_id]
                    if source_types and item.get("source_type") not in set(source_types):
                        continue
                    if product_id and item.get("product_id") not in {None, product_id}:
                        continue
                    pooled.append(self.compact(item, None, question)); seen.add(chunk_id)
                lexical = pooled[:retrieval_pool_size]
            packet["source_context"] = lexical
        packet["source_context"] = self._trim_context(packet.get("source_context", []), max_chars=max_chars, query=question)
        if layer in {"query_understanding", "routing", "end_to_end"}:
            packet["product_catalog"] = self.product_catalog
        packet["packet_sha256"] = sha256_json(packet)
        return packet


    @classmethod
    def _trim_context(cls, rows: list[dict[str, Any]], *, max_chars: int, query: str) -> list[dict[str, Any]]:
        if not rows:
            return []
        trimmed=[]
        remaining=max_chars
        remaining_rows=len(rows)
        for row in rows:
            clone=dict(row)
            text=str(clone.get("text") or "")
            allowance=min(3200, max(0, remaining // max(1, remaining_rows)))
            clone["text"] = cls._query_centered_snippet(text, query, max_chars=max(1, allowance)) if allowance else ""
            remaining -= len(clone["text"])
            remaining_rows -= 1
            trimmed.append(clone)
        return trimmed

    @staticmethod
    def _extract_query(input_data: dict[str, Any]) -> str:
        if input_data.get("query"):
            return str(input_data["query"])
        if input_data.get("question"):
            return str(input_data["question"])
        conversation = input_data.get("conversation") or []
        return "\n".join(str(m.get("content", "")) for m in conversation)

    @staticmethod
    def _context_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for evidence in state.get("evidences", []) or []:
            document = evidence.get("document", evidence)
            metadata = document.get("metadata", {}) if isinstance(document, dict) else {}
            rows.append(
                {
                    "chunk_id": metadata.get("chunk_id") or evidence.get("citation_id"),
                    "source_type": evidence.get("source_type") or metadata.get("doc_type"),
                    "source_file": metadata.get("source_file"),
                    "heading": metadata.get("heading") or metadata.get("section"),
                    "record_id": metadata.get("record_id"),
                    "text": document.get("page_content", "") if isinstance(document, dict) else str(document),
                }
            )
        return rows
