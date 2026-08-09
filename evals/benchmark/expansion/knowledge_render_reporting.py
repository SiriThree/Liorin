"""Reporting helpers for G0.3."""
from __future__ import annotations
from collections import Counter, defaultdict
from typing import Any


def distribution(rows:list[dict[str,Any]], key:str)->dict[str,Any]:
    c=Counter(r[key] for r in rows);n=len(rows)
    return {k:{"count":v,"ratio":round(v/max(1,n),6)} for k,v in sorted(c.items())}


def surface_report(rows:list[dict[str,Any]])->dict[str,Any]:
    pats=Counter(r.get("render_pattern") for r in rows);prefix=Counter(r["candidate_query"][:6] for r in rows);lengths=[len(r["candidate_query"]) for r in rows]
    return {"renderer_patterns":dict(sorted(pats.items())),"pattern_count":len(pats),"max_pattern_count":max(pats.values(),default=0),"max_pattern_ratio":round(max(pats.values(),default=0)/max(1,len(rows)),6),"query_prefix_top10":prefix.most_common(10),"max_prefix_ratio":round(max(prefix.values(),default=0)/max(1,len(rows)),6),"average_query_length":round(sum(lengths)/max(1,len(lengths)),2),"min_query_length":min(lengths,default=0),"max_query_length":max(lengths,default=0)}


def balance(rows:list[dict[str,Any]], doc_map:dict[str,dict[str,Any]])->dict[str,Any]:
    docs=Counter(d for r in rows for d in r.get("document_ids",[]));products=Counter(p for r in rows for p in r.get("product_ids",[]))
    return {"documents":{"covered":len(docs),"plans_per_document":dict(sorted(docs.items())),"max":max(docs.values(),default=0),"max_ratio":round(max(docs.values(),default=0)/max(1,len(rows)),6)},"products":{"covered":len(products),"plans_per_product":dict(sorted(products.items())),"max":max(products.values(),default=0),"max_ratio":round(max(products.values(),default=0)/max(1,len(rows)),6)}}
