"""
Safe cognitive search override for chat retrieval improvements.

하이엔드 RAG 검색 파이프라인 v3
- 회사명 퍼지 매칭 (alias map + 부분 매칭)
- 하이브리드 3-소스 검색 (벡터 + BM25 + 메타데이터)
- SQL 기반 메타데이터 보강 (ChromaDB bare metadata 보완)
- 적응형 임계값 (쿼리 의도 기반)
- 재무 키워드 밀도 부스트
- 회사명 정규화 통합
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from services.vector_service import (
    _get_collection,
    _get_embedding,
    _tokenize,
    _bm25_score,
    _chunks_similar,
    VECTOR_WEIGHT,
    KEYWORD_WEIGHT,
    META_WEIGHT,
    DEDUP_THRESHOLD,
    COLLECTION_NAME,
    _user_collection,
    _user_chunk_collection,
    search_chat_chunks,
)


# ── SQL 메타데이터 보강 캐시 ──
_doc_meta_cache: Dict[str, Dict] = {}
_doc_meta_cache_ready = False


def _ensure_doc_meta_cache():
    """document_metadata + documents 테이블에서 document_id → 메타 매핑 빌드 (1회)"""
    global _doc_meta_cache, _doc_meta_cache_ready
    if _doc_meta_cache_ready:
        return
    try:
        from database import SessionLocal
        db = SessionLocal()
        try:
            from sqlalchemy import text
            rows = db.execute(text(
                "SELECT dm.document_id, dm.company_name, dm.company_name_norm, "
                "dm.corp_code, dm.report_type, dm.fiscal_year, "
                "d.filename "
                "FROM document_metadata dm "
                "JOIN documents d ON d.id = dm.document_id"
            )).fetchall()
            for row in rows:
                doc_id_str = str(row[0])
                _doc_meta_cache[doc_id_str] = {
                    "company_name": row[1] or "",
                    "company_name_norm": row[2] or "",
                    "corp_code": row[3] or "",
                    "report_type": row[4] or "",
                    "fiscal_year": str(row[5]) if row[5] else "",
                    "filename": row[6] or "",
                }
            logger.info("✦ SQL 메타 캐시 빌드 완료: %d건", len(_doc_meta_cache))
        finally:
            db.close()
    except Exception as e:
        logger.warning("SQL 메타 캐시 빌드 실패: %s", e)
    _doc_meta_cache_ready = True


def _enrich_meta_from_sql(meta: Dict, chunk_text: str = "") -> Dict:
    """ChromaDB bare metadata를 SQL 테이블 데이터로 보강"""
    _ensure_doc_meta_cache()
    doc_id = str(meta.get("document_id", ""))
    if not doc_id or doc_id not in _doc_meta_cache:
        return meta

    sql_meta = _doc_meta_cache[doc_id]
    enriched = dict(meta)
    # company_name 보강 (ChromaDB에 없으면 SQL에서)
    if not enriched.get(_META_COMPANY_KEY):
        enriched[_META_COMPANY_KEY] = sql_meta.get("company_name_norm") or sql_meta.get("company_name", "")
    # source_file / filename 보강
    if not enriched.get("source_file") and not enriched.get("filename"):
        enriched["source_file"] = sql_meta.get("filename", "")
    # category / report_type 보강
    if not enriched.get("category"):
        enriched["category"] = sql_meta.get("report_type", "")
    return enriched

# NOTE: omega_document_chunks_v2 removed — 0 documents, dead weight.
# Only COLLECTION_NAME (omega_documents_v2) is searched.

# v2 metadata key for company name
_META_COMPANY_KEY = "company_name"

logger = logging.getLogger(__name__)

# ── 회사명 별칭 매핑 (챗봇과 동기화) ──
_COMPANY_ALIAS_MAP = {
    "sk하이닉스": "SK하이닉스",
    "하이닉스": "SK하이닉스",
    "에스케이하이닉스": "SK하이닉스",
    "sk hynix": "SK하이닉스",
    "hynix": "SK하이닉스",
    "삼전": "삼성전자",
    "samsung": "삼성전자",
    "삼성": "삼성전자",
    "현대차": "현대자동차",
    "현대": "현대자동차",
    "hyundai": "현대자동차",
    "hyundai motor": "현대자동차",
    "기아차": "기아",
    "naver": "NAVER",
    "네이버": "NAVER",
    "kakao": "카카오",
    "lg에너지": "LG에너지솔루션",
    "lg에너지솔루션": "LG에너지솔루션",
    "엘지에너지솔루션": "LG에너지솔루션",
    "엘지에너지": "LG에너지솔루션",
    "lg생활건강": "LG생활건강",
    "엘지생활건강": "LG생활건강",
    "lg화학": "LG화학",
    "엘지화학": "LG화학",
    "lg전자": "LG전자",
    "엘지전자": "LG전자",
    "한에로": "한화에어로스페이스",
    "한화에어로": "한화에어로스페이스",
    "두산에너": "두산에너빌리티",
    "삼바": "삼성바이오로직스",
    "셀트리온": "셀트리온",
    "포스코": "POSCO홀딩스",
    "현대글로비스": "현대글로비스",
    "글로비스": "현대글로비스",
    "현대다이모스": "현대다이모스",
    "다이모스": "현대다이모스",
    "skt": "SK텔레콤",
    "sk텔레콤": "SK텔레콤",
    "에스케이텔레콤": "SK텔레콤",
    "sk이노베이션": "SK이노베이션",
    "에스케이이노베이션": "SK이노베이션",
    "삼성sdi": "삼성SDI",
    # 무림 그룹 — canonical은 DB의 company_name_norm과 동일하게 유지 (무림PP / 무림SP는 별개 회사)
    "무림pp": "무림PP",
    "무림PP": "무림PP",
    "무림p&p": "무림PP",
    "무림P&P": "무림PP",
    "무림피앤피": "무림PP",
    "무림 피앤피": "무림PP",
    "무림피엔피": "무림PP",
    "moorimpp": "무림PP",
    "무림sp": "무림SP",
    "무림SP": "무림SP",
    "무림s&p": "무림SP",
    "무림페이퍼": "무림페이퍼",
}


def _normalize_company_for_search(name: str) -> List[str]:
    """회사명을 검색용으로 정규화 — 원본 + canonical + canonical 그룹의 모든 alias 반환.
    forward(alias→canonical) 후 그 canonical로 reverse(canonical→all aliases)까지 수행하여
    '무림피앤피' 같은 alias 입력도 같은 canonical 그룹의 모든 변형('무림PP', '무림P&P', ...)을 받는다."""
    if not name:
        return []

    results = [name]
    lowered = name.lower().strip()

    # Forward: alias → canonical
    canonical = None
    if lowered in _COMPANY_ALIAS_MAP:
        canonical = _COMPANY_ALIAS_MAP[lowered]
    elif name in _COMPANY_ALIAS_MAP:
        canonical = _COMPANY_ALIAS_MAP[name]
    if canonical and canonical not in results:
        results.append(canonical)

    # Reverse: canonical → 같은 canonical 그룹의 모든 alias
    target_canonical = canonical or name
    target_lower = target_canonical.lower()
    for alias, alias_canonical in _COMPANY_ALIAS_MAP.items():
        if alias_canonical == target_canonical or alias_canonical.lower() == target_lower:
            if alias not in results:
                results.append(alias)
            alias_upper = alias.upper()
            if alias_upper not in results:
                results.append(alias_upper)

    # "(주)", "주식회사" 제거 변형
    for variant in list(results):
        cleaned = re.sub(r'(주식회사|\(주\)|㈜)\s*', '', variant).strip()
        if cleaned and cleaned not in results:
            results.append(cleaned)

    return results


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    ordered = []
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _extract_years_from_filename(filename: str) -> List[str]:
    return _dedupe_keep_order(re.findall(r"(20\d{2})", filename or ""))


# ── 재무 시그널 키워드 (검색 밀도 + 리랭킹용) ──
_FINANCIAL_SIGNAL_KEYWORDS = {
    "매출액", "영업이익", "당기순이익", "순이익", "자산총계", "부채총계", "자본총계",
    "현금흐름", "영업활동", "투자활동", "재무활동",
    "전기 대비", "전년 동기", "증가", "감소", "전기", "당기",
    "배당", "증자", "유상증자", "무상증자", "전환사채",
    "감사의견", "적정의견", "부채비율",
    "매출 증가", "영업이익률", "순이익률",
    "자기주식", "처분", "취득",
}


def _company_match_score(
    company_filter: str,
    meta_company: str,
    chunk_text: str,
    company_variants: List[str],
    meta_filename: str = "",
) -> float:
    """회사명 매칭 점수 — 퍼지 매칭 포함"""
    if not company_filter:
        return 0.0

    score = 0.0

    # 1) 메타데이터 company_name 필드 매칭 (가장 신뢰)
    meta_lower = meta_company.lower()
    for variant in company_variants:
        if variant.lower() in meta_lower or meta_lower in variant.lower():
            score = max(score, 0.6)
            break

    # 2) 청크 텍스트 내 회사명 포함 (보조 근거)
    chunk_lower = chunk_text[:2000].lower()
    for variant in company_variants:
        if variant.lower() in chunk_lower:
            score = max(score, 0.4)
            break

    # 3) 파일명에 회사명 포함
    if meta_filename:
        fn_lower = meta_filename.lower()
        for variant in company_variants:
            if variant.lower() in fn_lower:
                score = max(score, 0.35)
                break

    return min(score, 1.0)


def _score_metadata_hints(
    meta: Dict,
    query_tokens: List[str],
    category_filter: str = "",
    company_filter: str = "",
    company_variants: List[str] = None,
    year_filters: Optional[List[str]] = None,
    prefer_recent: bool = False,
    chunk_text: str = "",
) -> float:
    # v2 uses 'company_name'; legacy used 'company'
    company = str(meta.get(_META_COMPANY_KEY, "") or meta.get("company", ""))
    category = str(meta.get("category", "") or meta.get("doc_type", ""))
    filename = str(meta.get("source_file", "") or meta.get("filename", ""))

    score = 0.0

    # 회사명 매칭 (퍼지)
    if company_variants:
        score += _company_match_score(
            company_filter, company, chunk_text, company_variants, meta_filename=filename
        )
    elif company_filter and company_filter in company:
        score += 0.55

    # 카테고리 매칭
    if category_filter and category_filter in category:
        score += 0.30

    # 쿼리 토큰이 메타데이터(회사명, 파일명)에 포함
    for token in query_tokens[:6]:
        if token and len(token) >= 2:
            if token in company:
                score += 0.12
                break
    for token in query_tokens[:6]:
        if token and len(token) >= 2:
            if token in filename:
                score += 0.10
                break

    # 연도 매칭
    filename_years = _extract_years_from_filename(filename)
    if year_filters:
        if any(year in filename_years for year in year_filters):
            score += 0.35
        # 청크 텍스트 내 연도 언급도 체크
        elif any(year in chunk_text[:500] for year in year_filters):
            score += 0.20
    elif prefer_recent and filename_years:
        latest_year = max(int(year) for year in filename_years)
        current_year = datetime.now().year
        if latest_year >= current_year - 1:
            score += 0.18
        elif latest_year >= current_year - 2:
            score += 0.10

    # OCR 원문 소스 약간의 보너스
    if meta.get("source") == "ocr":
        score += 0.03

    return min(score, 1.0)


def _domain_boost(domain: str, chunk_text: str) -> float:
    domain_keywords = {
        "risk": {"리스크", "위험", "소송", "감사의견", "부채", "우발", "부적정", "한정"},
        "growth": {"투자", "증설", "생산능력", "R&D", "성장", "매출 증가", "신규"},
        "earnings": {"매출", "영업이익", "순이익", "실적", "매출액", "흑자", "적자"},
        "competitive": {"점유율", "경쟁", "시장", "비교", "1위"},
    }
    keywords = domain_keywords.get(domain, set())
    if not keywords:
        return 1.0
    matches = sum(1 for kw in keywords if kw in chunk_text)
    if matches >= 3:
        return 1.20
    elif matches >= 1:
        return 1.12
    return 1.0


def _financial_density_boost(chunk_text: str) -> float:
    """재무 키워드 밀도 기반 부스트 (최대 +20%)"""
    signal_count = sum(1 for sk in _FINANCIAL_SIGNAL_KEYWORDS if sk in chunk_text)
    chunk_len_100 = max(len(chunk_text) / 100, 1)
    density = signal_count / chunk_len_100
    return min(density * 0.05, 0.20)


# ── SQL 키워드 LIKE fallback 구현 ──
# 벡터 검색이 놓치는 distinctive 토큰(상장폐지/감사의견/CB 등)을
# SQLite document_chunks.text 에서 직접 조회하여 recall을 보장.

_SQL_FALLBACK_STOPWORDS = {
    # 시간/지시
    "최근", "작년", "올해", "내년", "금년", "당해", "해당", "관련", "당시", "현재",
    # 엔티티 일반
    "기업", "회사", "문서", "공시", "보고서", "분기", "연도", "사업", "산업", "시장",
    # 결과/구조 메타
    "리스트", "목록", "현황", "상황", "내용", "정보", "자료", "데이터", "구조",
    "발생", "사유", "원인", "결과", "이유", "방법", "대상", "범위", "전체", "일부",
    "실적", "재무", "요약", "정리", "비교", "분석", "설명", "확인", "평가",
    # 문법/조사/어미
    "있는", "없는", "된", "한", "하는", "였던", "했던", "입니다", "받은", "받는",
    "대한", "대해", "위한", "위해", "중인", "된다", "있어", "있다", "한다",
    "어떤", "무슨", "어디", "왜", "언제", "어떻게", "무엇", "뭐", "몇", "얼마",
    "그리고", "또는", "하지만", "따라", "통해", "포함", "제외", "기타",
    "top", "vs", "and", "or", "the", "a", "an", "of", "in", "to", "for",
}


def _append_sql_keyword_candidates(
    query_tokens: List[str],
    year_filters: Optional[List[str]],
    limit: int,
    all_ids: List,
    all_metadatas: List,
    all_documents: List,
    all_distances: List,
) -> None:
    """SQLite document_chunks.text LIKE 직접 검색으로 벡터 후보를 보강.

    - distinctive 토큰(길이 ≥ 2, stopword 제외) 선별
    - 2개 이상이면 AND 매칭 (모든 토큰이 포함된 청크만, 고정밀)
      ex) '감사의견' ∧ '거절' → 실제 의견거절 사례만 hit
    - 0 결과면 OR로 완화 (고리콜)
    - 1개뿐이면 단독 OR
    """
    distinctive = [
        t for t in query_tokens
        if t and len(t) >= 2 and t.lower() not in _SQL_FALLBACK_STOPWORDS
    ]
    if not distinctive:
        return

    # 길이 내림차순 (distinctive한 긴 토큰 우선), 중복 제거
    distinctive = sorted(set(distinctive), key=lambda x: (-len(x), x))[:4]

    try:
        from database import SessionLocal
        from sqlalchemy import text as sql_text
        db = SessionLocal()
        try:
            _ensure_doc_meta_cache()

            def _run(join_op: str, tokens: List[str]):
                like_conds = []
                params: Dict = {"limit": limit}
                for i, tok in enumerate(tokens):
                    like_conds.append(f"dc.text LIKE :tok{i}")
                    params[f"tok{i}"] = f"%{tok}%"
                where_clause = f" {join_op} ".join(like_conds)

                year_clause = ""
                if year_filters:
                    year_conds = []
                    for i, yr in enumerate(year_filters):
                        year_conds.append(f"(d.filename LIKE :yr{i} OR dc.text LIKE :yrt{i})")
                        params[f"yr{i}"] = f"%{yr}%"
                        params[f"yrt{i}"] = f"%{yr}%"
                    year_clause = " AND (" + " OR ".join(year_conds) + ")"

                sql = (
                    "SELECT dc.chunk_uid, dc.text, dc.document_id, dc.page_no, dc.section_name, "
                    "d.filename "
                    "FROM document_chunks dc "
                    "JOIN documents d ON d.id = dc.document_id "
                    f"WHERE ({where_clause}){year_clause} "
                    "LIMIT :limit"
                )
                return db.execute(sql_text(sql), params).fetchall()

            rows: List = []
            if len(distinctive) >= 2:
                rows = _run("AND", distinctive)
                logger.info("  │  SQL fallback AND(%s) → %d rows", ",".join(distinctive), len(rows))
                if not rows:
                    rows = _run("OR", distinctive)
                    logger.info("  │  SQL fallback OR fallback → %d rows", len(rows))
            else:
                rows = _run("OR", distinctive)
                logger.info("  │  SQL fallback single(%s) → %d rows", distinctive[0], len(rows))

            seen = set(all_ids)
            for row in rows:
                cuid = str(row[0] or "")
                if not cuid or cuid in seen:
                    continue
                seen.add(cuid)
                doc_id_str = str(row[2])
                sql_meta = _doc_meta_cache.get(doc_id_str, {})
                all_ids.append(cuid)
                all_metadatas.append({
                    "document_id": row[2],
                    "company_name": sql_meta.get("company_name_norm") or sql_meta.get("company_name", ""),
                    "source_file": row[5] or sql_meta.get("filename", ""),
                    "category": sql_meta.get("report_type", ""),
                    "page_no": row[3],
                    "section_name": row[4] or "",
                    "source": "sql_keyword",
                })
                all_documents.append(str(row[1] or ""))
                all_distances.append(0.45)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("SQL keyword fallback failed: %s", exc)


def _contextual_compress(chunk_text: str, query: str, query_tokens: List[str]) -> str:
    """Contextual Compression — 청크에서 쿼리 관련 문장만 추출.

    전체 청크 대신 핵심 문장만 LLM에 전달하면:
    - Context Precision ↑ (노이즈 감소)
    - Faithfulness ↑ (관련 근거만 참조)
    - 토큰 효율 ↑

    규칙:
    - 재무 숫자가 포함된 문장은 항상 유지
    - 쿼리 키워드가 포함된 문장은 유지
    - 첫 문장(보통 제목/요약)은 항상 유지
    """
    # 문장 분리 (한국어 마침표 + 줄바꿈 기준)
    sentences = re.split(r'(?<=[.。다요음함됨임])\s+|\n+', chunk_text)
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) >= 10]

    if len(sentences) <= 3:
        return chunk_text  # 이미 짧으면 압축 불필요

    query_lower = query.lower()
    token_set = {t.lower() for t in query_tokens if t and len(t) >= 2}

    # 재무 핵심 키워드 (항상 유지)
    financial_signals = {
        "매출액", "영업이익", "당기순이익", "순이익", "자산총계", "부채총계",
        "자본총계", "현금흐름", "배당", "부채비율", "영업이익률",
    }

    kept = []
    for idx, sent in enumerate(sentences):
        sent_lower = sent.lower()

        # 규칙 1: 첫 문장 항상 유지
        if idx == 0:
            kept.append(sent)
            continue

        # 규칙 2: 쿼리 키워드 매칭
        token_hits = sum(1 for t in token_set if t in sent_lower)
        if token_hits >= 1:
            kept.append(sent)
            continue

        # 규칙 3: 재무 숫자 포함 문장
        has_number = bool(re.search(r'\d{2,}', sent))
        has_financial = any(fk in sent for fk in financial_signals)
        if has_number and has_financial:
            kept.append(sent)
            continue

        # 규칙 4: 쿼리 단어가 문장에 직접 포함
        if any(qw in sent_lower for qw in query_lower.split() if len(qw) >= 2):
            kept.append(sent)
            continue

    return " ".join(kept) if kept else chunk_text


def cognitive_search_safe(
    query: str,
    top_k: int = 5,
    category_filter: str = "",
    company_filter: str = "",
    domain: str = "",
    year_filters: Optional[List[str]] = None,
    prefer_recent: bool = False,
    rerank_query: str = "",
    user_id: int = 0,
) -> List[Dict]:
    """
    하이엔드 RAG 검색 파이프라인 v3 (clean path only)

    v3 변경:
    - metadata key: company_name (v2 컬렉션 호환)
    - 단일 컬렉션 검색 (omega_documents_v2 only)
    - legacy 컬렉션 제거
    - 디버그 로깅 강화
    - user_id: 계정별 컬렉션 격리
    """
    collection_main = _get_collection(_user_collection(user_id))

    if collection_main is None:
        logger.warning("Ω CogSearch v3 — collection '%s' is None, aborting", COLLECTION_NAME)
        return []

    logger.info(
        "Ω CogSearch v3 — START query=%s company=%s collection=%s",
        query[:40], company_filter, COLLECTION_NAME,
    )

    # 회사명 변형 목록 생성
    company_variants = _normalize_company_for_search(company_filter)

    query_tokens = _tokenize(query)
    query_emb = _get_embedding(query)
    if query_emb is None:
        return []

    where_general = {}
    if category_filter:
        where_general["category"] = category_filter

    # 후보군 확대 — 회사 필터가 있으면 더 넓게 검색
    if company_filter:
        fetch_k = min(max(top_k * 10, 60), 200)  # 회사 한정이므로 넉넉히
    else:
        fetch_k = min(max(top_k * 8, 40), 80)

    all_ids = []
    all_metadatas = []
    all_documents = []
    all_distances = []

    def _query_collection(col, where_clause, n):
        """컬렉션 쿼리 헬퍼"""
        if col is None:
            return
        try:
            col_count = col.count()
            if col_count == 0:
                return
        except Exception:
            return
        try:
            results = col.query(
                query_embeddings=[query_emb],
                n_results=min(n, col_count),
                where=where_clause if where_clause else None,
                include=["documents", "metadatas", "distances"],
            )
            if results and results.get("ids") and results["ids"][0]:
                all_ids.extend(results["ids"][0])
                all_metadatas.extend(results["metadatas"][0] if results["metadatas"] else [{}] * len(results["ids"][0]))
                all_documents.extend(results["documents"][0] if results["documents"] else [""] * len(results["ids"][0]))
                all_distances.extend(results["distances"][0] if results["distances"] else [1.0] * len(results["ids"][0]))
                logger.debug(
                    "  _query_collection [%s] where=%s → %d hits",
                    col.name, where_clause, len(results["ids"][0]),
                )
        except Exception as exc:
            logger.warning("cognitive search query failed (%s): %s", col.name, exc)

    # ── 1차: 회사명 메타데이터 필터 (company_name이 ChromaDB에 있을 때만) ──
    if company_filter:
        for variant in company_variants[:6]:
            where_company = {_META_COMPANY_KEY: variant}
            if category_filter:
                where_company = {"$and": [{_META_COMPANY_KEY: variant}, {"category": category_filter}]}
            _query_collection(collection_main, where_company, fetch_k)
            if all_ids:
                logger.info("  ├─ company meta hit on variant=%s → %d results", variant, len(all_ids))
                break

        # 카테고리 없이 재시도
        if not all_ids:
            for variant in company_variants[:6]:
                _query_collection(collection_main, {_META_COMPANY_KEY: variant}, fetch_k)
                if all_ids:
                    logger.info("  ├─ company retry hit on variant=%s → %d results", variant, len(all_ids))
                    break

    # ── 2차: document_id 기반 검색 (col.get — 임베딩 불필요, SQL 메타에서 역매핑) ──
    if company_filter and not all_ids:
        _ensure_doc_meta_cache()
        exact_doc_ids = []
        fuzzy_doc_ids = []
        cf_lower = company_filter.lower()
        for doc_id, sql_meta in _doc_meta_cache.items():
            cn = (sql_meta.get("company_name_norm") or sql_meta.get("company_name", "")).lower()
            if cn == cf_lower:
                exact_doc_ids.append(doc_id)
            elif cf_lower in cn or cn in cf_lower:
                fuzzy_doc_ids.append(doc_id)
            elif any(v.lower() in cn or cn in v.lower() for v in company_variants if v):
                fuzzy_doc_ids.append(doc_id)
        # Prioritize exact matches, then fuzzy
        matching_doc_ids = exact_doc_ids + fuzzy_doc_ids
        if matching_doc_ids and collection_main is not None:
            for doc_id in matching_doc_ids[:30]:
                try:
                    results = collection_main.get(
                        where={"document_id": doc_id},
                        limit=min(fetch_k, 40),
                        include=["documents", "metadatas"],
                    )
                    if results and results.get("ids"):
                        for i, _id in enumerate(results["ids"]):
                            all_ids.append(_id)
                            all_metadatas.append(results["metadatas"][i] if results.get("metadatas") and i < len(results["metadatas"]) else {})
                            all_documents.append(results["documents"][i] if results.get("documents") and i < len(results["documents"]) else "")
                            all_distances.append(0.3)  # synthetic distance for non-vector results
                except Exception as exc:
                    logger.debug("doc_id get failed for %s: %s", doc_id, exc)
            if all_ids:
                logger.info("  ├─ SQL doc_id fallback (col.get) → %d results from %d matching docs", len(all_ids), len(matching_doc_ids))

    # ── 3차: 일반 벡터 검색 (항상 실행) ──
    # SQL doc_id fallback이 모든 doc chunks를 균일하게 가져오므로, query semantic을
    # 반영한 vector-similar chunks가 빠질 수 있다. SQL fallback과 별개로 vector search를
    # 추가 실행해 query-relevant chunks를 보강한다. 중복은 후속 dedupe에서 제거.
    prev_count = len(all_ids)
    _query_collection(collection_main, where_general if where_general else None, fetch_k)
    if len(all_ids) > prev_count:
        logger.info("  ├─ general vector search added %d results", len(all_ids) - prev_count)

    # ── 3.5차: SQL 키워드 LIKE fallback (recall 보험) ──
    # 벡터 검색이 긴 쿼리의 distinctive 토큰(상장폐지/감사의견/유상증자/CB 등)을
    # 후보에 못 담는 경우를 보강. document_chunks.text를 SQLite LIKE로 직접 검색해
    # 벡터 후보와 union. BM25 + reranker가 이후에 정렬.
    prev_count = len(all_ids)
    _append_sql_keyword_candidates(
        query_tokens=query_tokens,
        year_filters=year_filters,
        limit=40,
        all_ids=all_ids,
        all_metadatas=all_metadatas,
        all_documents=all_documents,
        all_distances=all_distances,
    )
    if len(all_ids) > prev_count:
        logger.info("  ├─ SQL keyword fallback added %d results", len(all_ids) - prev_count)

    # ── 4차: 필터 완전 제거 fallback ──
    if not all_ids:
        _query_collection(collection_main, None, fetch_k)

    if not all_ids:
        logger.warning("  └─ ALL search paths returned 0 results for query=%s", query[:40])
        return []

    # ── 복합 스코어링 ──
    candidates = []
    seen_ids = set()

    for idx, _chunk_id in enumerate(all_ids):
        if _chunk_id in seen_ids:
            continue
        seen_ids.add(_chunk_id)

        raw_meta = all_metadatas[idx] if idx < len(all_metadatas) else {}
        meta = _enrich_meta_from_sql(raw_meta, chunk_text=(all_documents[idx] if idx < len(all_documents) else ""))
        dist = all_distances[idx] if idx < len(all_distances) else 1.0
        chunk_text = all_documents[idx] if idx < len(all_documents) else ""

        if not chunk_text or len(chunk_text.strip()) < 20:
            continue

        # 벡터 유사도 (코사인 거리 → 유사도)
        vector_score = max(0.0, 1.0 - dist)

        # BM25 키워드 매칭
        doc_tokens = _tokenize(chunk_text)
        bm25 = _bm25_score(query_tokens, doc_tokens)
        bm25_norm = min(bm25 / max(len(query_tokens) * 1.5, 1), 1.0)

        # 메타데이터 매칭 (회사명 퍼지 포함)
        meta_score = _score_metadata_hints(
            meta,
            query_tokens,
            category_filter=category_filter,
            company_filter=company_filter,
            company_variants=company_variants,
            year_filters=year_filters,
            prefer_recent=prefer_recent,
            chunk_text=chunk_text,
        )

        # 가중 합산
        composite = (
            VECTOR_WEIGHT * vector_score +
            KEYWORD_WEIGHT * bm25_norm +
            META_WEIGHT * meta_score
        )

        # 연도 매칭 부스트
        if year_filters and any(year in chunk_text for year in year_filters):
            composite *= 1.08

        # 도메인 부스트
        composite *= _domain_boost(domain, chunk_text)

        # 재무 키워드 밀도 부스트
        composite += _financial_density_boost(chunk_text)

        # 회사명 직접 매칭 부스트 (퍼지)
        if company_variants:
            chunk_lower = chunk_text[:3000].lower()
            for variant in company_variants:
                if variant.lower() in chunk_lower:
                    composite *= 1.35
                    break

        # 메타데이터 회사명 정밀 매칭 부스트 (SQL 보강 메타 기반)
        resolved_company = str(meta.get(_META_COMPANY_KEY, "") or meta.get("company", ""))
        if company_filter and resolved_company:
            rc_lower = resolved_company.lower()
            cf_lower = company_filter.lower()
            if rc_lower == cf_lower:
                composite *= 1.60  # 정확히 일치
            elif cf_lower in rc_lower or rc_lower in cf_lower:
                composite *= 1.30  # 부분 포함
        resolved_filename = str(meta.get("source_file", "") or meta.get("filename", ""))

        candidates.append({
            # 메타 키는 'document_id'가 정본 (ChromaDB + SQL 양쪽 모두).
            # 'doc_id'는 레거시 key — fallback으로만 둔다.
            "doc_id": meta.get("document_id") or meta.get("doc_id"),
            "filename": resolved_filename,
            "chunk": chunk_text,
            "vector_score": round(vector_score, 4),
            "bm25_score": round(bm25_norm, 4),
            "meta_score": round(meta_score, 4),
            "composite_score": round(composite, 4),
            "category": str(meta.get("category", "") or meta.get("doc_type", "")),
            "company": resolved_company,
            "source": meta.get("source", ""),
            "page_no": meta.get("page_no") or meta.get("page"),
            "section_name": meta.get("section_name", "") or meta.get("section_title", ""),
            "chunk_uid": _chunk_id,
        })

    # ── Strict company post-filter ──
    # 회사 필터가 명시된 경우, 메타데이터/청크 텍스트에 variants가 전혀 없는 청크는 hard reject.
    # 이는 무림피앤피 → 무림SP 같은 prefix-only 오염을 차단한다.
    if company_filter and company_variants:
        variant_lowers = [v.lower() for v in company_variants if v and len(v) >= 3]
        strict_filtered = []
        for c in candidates:
            cn = (c.get("company") or "").lower()
            chunk_lower = (c.get("chunk") or "")[:1500].lower()
            fname_lower = (c.get("filename") or "").lower()
            meta_match = bool(cn) and any(
                cn == v or (v in cn and len(v) >= 4) or (cn in v and len(cn) >= 4)
                for v in variant_lowers
            )
            chunk_match = any(v in chunk_lower for v in variant_lowers if len(v) >= 4)
            fname_match = any(v in fname_lower for v in variant_lowers if len(v) >= 4)
            if meta_match or chunk_match or fname_match:
                strict_filtered.append(c)
        if strict_filtered:
            candidates = strict_filtered
            logger.info(
                "  ├─ strict company post-filter: kept %d/%d candidates for company=%s",
                len(strict_filtered), len(candidates), company_filter,
            )

    # ── Quality-aware scoring: 오염 청크 감지 및 패널티 ──
    for c in candidates:
        chunk_text = c.get("chunk", "")
        penalty = 0.0
        # 중국어 오염 감지
        cn_chars = len(re.findall(r'[\u4e00-\u9fff]', chunk_text[:500]))
        if cn_chars > 3:
            penalty += 0.15
        # 일본어 오염 감지
        jp_chars = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', chunk_text[:500]))
        if jp_chars > 2:
            penalty += 0.10
        # JSON 아티팩트 오염 감지
        json_markers = chunk_text[:300].count('{"') + chunk_text[:300].count('":')
        if json_markers >= 3:
            penalty += 0.12
        if penalty > 0:
            c["composite_score"] = max(0.01, c["composite_score"] - penalty)
            c["quality_penalty"] = round(penalty, 3)

    # 임계값: 0.08 (recall 우선, 이전 0.15에서 대폭 완화)
    filtered = [c for c in candidates if c["composite_score"] >= 0.08]
    filtered.sort(key=lambda item: item["composite_score"], reverse=True)

    # ── 리랭킹을 위해 넉넉한 후보군(3배수) 확보 ──
    rerank_fetch_k = min(max(top_k * 3, 15), 50)

    # 중복 제거 (리랭킹 풀 구성)
    deduped = []
    for candidate in filtered:
        if any(_chunks_similar(candidate["chunk"], existing["chunk"]) > DEDUP_THRESHOLD for existing in deduped):
            continue
        deduped.append(candidate)
        if len(deduped) >= rerank_fetch_k:
            break

    # ── CrossEncoder 리랭킹 (복원) ──
    # dragonkue/bge-reranker-v2-m3-ko cross-encoder 모델로 query-chunk pair 직접 평가.
    # rerank_score를 composite_score와 합산해 최종 정렬.
    try:
        from services.vector_service import _get_reranker_model
        reranker = _get_reranker_model()
        if reranker is not None and len(deduped) >= 2:
            # 서브쿼리로 호출되는 경우 원본 사용자 쿼리로 reranking해야
            # 조각난 토큰("감사의견")이 false positive를 만드는 문제 방지
            effective_rerank_query = rerank_query.strip() or query
            pairs = [(effective_rerank_query, (c.get("chunk") or "")[:512]) for c in deduped]
            rerank_scores = reranker.predict(pairs, show_progress_bar=False)
            # bge-reranker scores: 보통 0~1 사이 (더 큰 값이 더 관련 있음)
            for c, s in zip(deduped, rerank_scores):
                c["rerank_score"] = float(s)
            # 최종 정렬: rerank_score를 우선 (×0.75), composite_score를 보조 (×0.25)
            # v4: CrossEncoder 신뢰도 상향 — 의미적 관련성 판단은 reranker가 더 정확
            deduped.sort(
                key=lambda c: c.get("rerank_score", 0.0) * 0.75 + c.get("composite_score", 0.0) * 0.25,
                reverse=True,
            )
            logger.info(
                "  ├─ CrossEncoder reranked %d candidates (top score=%.4f)",
                len(deduped), deduped[0].get("rerank_score", 0.0),
            )
        else:
            for c in deduped:
                c["rerank_score"] = 0.0
    except Exception as exc:
        logger.warning("CrossEncoder 리랭킹 실패 → composite_score만 사용: %s", exc)
        for c in deduped:
            c["rerank_score"] = 0.0

    # 최종 탑 K 절사
    final_results = deduped[:top_k]

    # ── Contextual Compression: 질문 관련 문장만 추출 ──
    # 긴 청크에서 query와 무관한 문장을 제거해 Context Precision 향상.
    # 원본은 full_chunk에 보존.
    for candidate in final_results:
        chunk_text = candidate.get("chunk", "")
        if len(chunk_text) > 400:
            compressed = _contextual_compress(chunk_text, query, query_tokens)
            if compressed and len(compressed) >= 80:
                candidate["full_chunk"] = chunk_text
                candidate["chunk"] = compressed

    if final_results:
        final_results[0]["pareto"] = True
        for candidate in final_results[1:]:
            candidate["pareto"] = False

    for candidate in final_results:
        candidate["score"] = candidate["composite_score"]

    # ── Observability: debug log for each retrieval ──
    logger.info(
        "Ω CogSearch v3 — query=%s company=%s collection=%s → %d/%d candidates → %d results",
        query[:30], company_filter, COLLECTION_NAME, len(filtered), len(candidates), len(final_results),
    )
    if final_results:
        top = final_results[0]
        logger.info(
            "  └─ top result: company=%s score=%.4f filename=%s",
            top.get("company", ""), top.get("composite_score", 0), top.get("filename", "")[:60],
        )
    else:
        logger.warning(
            "  └─ NO RESULTS for query=%s company_filter=%s (0 candidates passed threshold)",
            query[:40], company_filter,
        )

    return final_results
