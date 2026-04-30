from __future__ import annotations

import logging
import re
from typing import List, Optional, Protocol

from agents.schemas import RetrievedChunk
from services.cognitive_search_safe import cognitive_search_safe

logger = logging.getLogger(__name__)

RAG_R0 = "R0"
RAG_R1 = "R1"
RAG_R2 = "R2"
RAG_R3 = "R3"

_OUTLOOK_QUERY_SUFFIXES = [
    "\uc2e4\uc801 \uc804\ub9dd",
    "\uc5c5\ud669",
    "\uac00\uaca9 \uc0ac\uc774\ud074",
    "\uc2dc\uc7a5 \uae30\ub300",
    "\ub9ac\uc2a4\ud06c",
]


class Retriever(Protocol):
    async def search(
        self,
        queries: List[str],
        top_k: int = 8,
        company_filter: str = "",
        intent: str = "",
        time_horizon: str = "current",
        prefer_recent: bool = False,
        year_filters: Optional[List[str]] = None,
        rag_density: str = RAG_R2,
        query_rewrites: Optional[List[str]] = None,
        user_id: int = 0,
    ) -> List[RetrievedChunk]:
        ...


def _clean_query(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        cleaned = _clean_query(item)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered


def _search_domain(intent: str, query_text: str) -> str:
    lowered = query_text.lower()
    if any(token in query_text for token in ("\ub9ac\uc2a4\ud06c", "\uc704\ud5d8")):
        return "risk"
    if intent == "stock_outlook":
        if any(token in lowered for token in ("\ubc38\ub958", "valuation", "\uc2dc\uc7a5 \uae30\ub300", "\uae30\ub300", "target", "\ubaa9\ud45c\uc8fc\uac00")):
            return "competitive"
        if any(token in lowered for token in ("\uc5c5\ud669", "\uc218\uc694", "\uc0ac\uc774\ud074", "hbm", "\uba54\ubaa8\ub9ac", "\ubc18\ub3c4\uccb4")):
            return "growth"
        return "earnings"
    if intent in {"trend", "company_summary"}:
        return "earnings"
    return "general"


class CivicFlowRetriever:
    def __init__(self, db):
        self.db = db

    async def search(
        self,
        queries: List[str],
        top_k: int = 8,
        company_filter: str = "",
        intent: str = "",
        time_horizon: str = "current",
        prefer_recent: bool = False,
        year_filters: Optional[List[str]] = None,
        rag_density: str = RAG_R2,
        query_rewrites: Optional[List[str]] = None,
        user_id: int = 0,
    ) -> List[RetrievedChunk]:
        del time_horizon

        active_queries = _dedupe_keep_order(list(query_rewrites or queries or []))
        if not active_queries:
            return []

        if intent == "stock_outlook" and company_filter:
            active_queries.extend(f"{company_filter} {suffix}" for suffix in _OUTLOOK_QUERY_SUFFIXES)
            active_queries = _dedupe_keep_order(active_queries)

        # query_budget: R2 3→5로 확장 — 서브쿼리(distinctive 토큰) 모두 커버
        query_budget = 5 if rag_density == RAG_R2 else 8 if rag_density == RAG_R3 else len(active_queries)
        active_queries = active_queries[:query_budget]
        per_query_k = 5 if rag_density == RAG_R2 else 6 if rag_density == RAG_R3 else max(4, min(6, top_k))

        seen_chunk_ids = set()
        all_chunks: List[RetrievedChunk] = []

        # 원본 사용자 쿼리 — 서브쿼리 reranking 시 일관된 기준으로 사용
        original_query = active_queries[0] if active_queries else ""

        for query_text in active_queries:
            try:
                docs = cognitive_search_safe(
                    query=query_text,
                    top_k=per_query_k,
                    category_filter="",
                    company_filter=company_filter,
                    domain=_search_domain(intent, query_text),
                    year_filters=year_filters,
                    prefer_recent=prefer_recent,
                    rerank_query=original_query,
                    user_id=user_id,
                )
            except Exception as exc:
                logger.error("Retriever query error for '%s': %s", query_text[:80], exc)
                continue

            for index, doc in enumerate(docs):
                chunk_id = str(doc.get("chunk_uid") or doc.get("doc_id") or f"doc-{len(all_chunks)}-{index}")
                if chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk_id)
                all_chunks.append(
                    RetrievedChunk(
                        chunk_id=chunk_id,
                        source_class="retrieved_document",
                        text=str(doc.get("chunk") or ""),
                        metadata={
                            "filename": doc.get("filename", ""),
                            "company": doc.get("company", ""),
                            "category": doc.get("category", ""),
                            "score": doc.get("composite_score", doc.get("score", 0)),
                            "rerank_score": doc.get("rerank_score", 0),
                            "page_no": doc.get("page_no"),
                            "section_name": doc.get("section_name", ""),
                            "doc_id": doc.get("doc_id"),
                            "query": query_text,
                        },
                    )
                )

        # 가중합 정렬 — cognitive_search_safe v4와 동일 가중치 (reranker 신뢰도 상향)
        all_chunks.sort(
            key=lambda chunk: (
                float(chunk.metadata.get("rerank_score", 0) or 0) * 0.75
                + float(chunk.metadata.get("score", 0) or 0) * 0.25
            ),
            reverse=True,
        )
        logger.info("[Retriever] rag=%s intent=%s company=%s queries=%d retrieved=%d top_k=%d", rag_density, intent, company_filter, len(active_queries), len(all_chunks), top_k)
        return all_chunks[:top_k]
