# -*- coding: utf-8 -*-
"""
index_financial_extracts.py — Selective raw_text chunking for financial keywords.

WHY this exists:
- Phase 3 chunking이 cleaned_text 기반으로 수행되어 NAVER 같은 일부 회사의 핵심 재무표가
  ChromaDB에 indexed 되지 않음.
- raw_text는 OCR 원문이라 모든 표가 살아있음 (이미 backfill_facts_from_ocr.py가 사용).
- 전체 raw_text를 재chunking하는 건 1.5M chunks → 큰 작업.
- 대신 매출/영업이익/자본총계 등 핵심 재무 키워드 주변 ±500자만 추출 → 수만 개 chunks만 추가.

WHAT this does:
- READ ocr_texts.raw_text + document_metadata
- 각 doc에서 재무 키워드 위치 찾아 ±500자 청크 추출 (위치 dedupe로 중복 방지)
- BGE-M3로 배치 임베딩
- ChromaDB omega_documents_v2 에 추가 (chunk_uid prefix 'fin_extract:'로 충돌 방지)
- source_kind='financial_extract' metadata로 rollback 용이

Run: python backend/tools/index_financial_extracts.py
"""
import sys
import os
import re
import hashlib
import logging
import time

THIS_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(THIS_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database import SessionLocal
from sqlalchemy import text
import services.vector_service as _vs

# CPU 부담 줄이기: vector_service의 EMBED_WORKERS를 patch (16 → 4)
_vs.EMBED_WORKERS = 4

from services.vector_service import _get_collection, _get_embeddings_batch, COLLECTION_NAME

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# 핵심 재무 키워드 (이 키워드 주변 청크만 추출)
FINANCIAL_KEYWORDS = [
    "매출액", "매출", "영업수익",
    "영업이익", "영업손실",
    "당기순이익", "당기순손실", "순이익",
    "자산총계", "총자산",
    "부채총계", "총부채",
    "자본총계", "총자본",
    "자본금",
    "EBITDA", "ebitda",
    "재무상태표", "손익계산서",
    "포괄손익계산서", "현금흐름표",
    "연결재무제표",
]

CHUNK_HALFWIDTH = 500           # 키워드 ±500자
MIN_CHUNK_LEN = 200             # 너무 짧은 건 의미 없음
DEDUPE_DISTANCE = 600           # 같은 doc에서 청크 간 최소 거리 (400→600 더 sparse)
MAX_CHUNKS_PER_DOC = 12         # doc당 최대 청크 수 (30→12, 핵심 표만)
BATCH_SIZE = 8                  # 임베딩 배치 크기 (64→8, CPU 부담 ↓)
SLEEP_BETWEEN_BATCHES = 0.6     # 배치 사이 휴식 (CPU 식히기)
EMBED_WORKERS_OVERRIDE = 4      # vector_service의 16 workers를 4로 제한


# 라벨 직후 즉시 큰 콤마 숫자가 와야 함 (whitespace만 허용)
_IMMEDIATE_BIG_NUMBER_RE = re.compile(r'^[\s\n]*\(?[-△▲]?\s*\d{1,3}(?:,\d{3}){2,}')


def _is_financial_table_context(raw_text: str, pos: int, kw_len: int = 4) -> bool:
    """
    표 형식: 라벨 다음 줄에 즉시 큰 콤마 숫자.
    본문 텍스트: 라벨 다음에 한국어 문장.

    예시:
    - "수익(매출액)\\n7,180,223,099" → True (표)
    - "매출원은 서치플랫폼..." → False (본문)
    - "자본금 변동사항\\n당사는..." → False (본문)
    """
    label_end = pos + kw_len
    next_text = raw_text[label_end:label_end + 80]
    return bool(_IMMEDIATE_BIG_NUMBER_RE.match(next_text))


def extract_financial_chunks(raw_text: str) -> list:
    """raw_text에서 재무 키워드 주변 ±500자 청크 추출.
    필터링: 키워드 직후 즉시 큰 콤마 숫자 (재무표 형식)만 통과.
    """
    if not raw_text or len(raw_text) < MIN_CHUNK_LEN:
        return []

    # (label_start, label_end) 쌍 수집 — kw 길이 정확히 알기 위해
    candidates = []  # list of (start, end)
    for kw in FINANCIAL_KEYWORDS:
        for m in re.finditer(re.escape(kw), raw_text):
            candidates.append((m.start(), m.end()))

    if not candidates:
        return []

    candidates.sort()

    # Filter: 라벨 직후 즉시 큰 콤마 숫자
    filtered = []
    for start, end in candidates:
        next_text = raw_text[end:end + 80]
        if _IMMEDIATE_BIG_NUMBER_RE.match(next_text):
            filtered.append(start)

    if not filtered:
        return []

    # Dedupe by distance
    dedupe_positions = []
    last_pos = -DEDUPE_DISTANCE - 1
    for p in filtered:
        if p - last_pos >= DEDUPE_DISTANCE:
            dedupe_positions.append(p)
            last_pos = p
        if len(dedupe_positions) >= MAX_CHUNKS_PER_DOC:
            break

    chunks = []
    for pos in dedupe_positions:
        cstart = max(0, pos - CHUNK_HALFWIDTH)
        cend = min(len(raw_text), pos + CHUNK_HALFWIDTH)
        chunk_text = raw_text[cstart:cend].strip()
        if len(chunk_text) >= MIN_CHUNK_LEN:
            chunks.append({
                "text": chunk_text,
                "position": pos,
            })
    return chunks


def make_chunk_uid(doc_id: int, position: int) -> str:
    """fin_extract: prefix로 기존 chunk_uid와 충돌 방지."""
    return f"fin_extract:{doc_id}:{position}"


def main(limit_docs: int = 0):
    """limit_docs > 0이면 처음 N개 문서만 처리 (sample run / dry test용)."""
    db = SessionLocal()
    collection = _get_collection(COLLECTION_NAME)
    if collection is None:
        log.error("ChromaDB collection 로드 실패")
        return

    try:
        # ── Idempotent: 기존 fin_extract chunks 삭제 (전체 run에서만) ──
        if limit_docs == 0:
            try:
                existing = collection.get(where={"source_kind": "financial_extract"}, include=[])
                if existing and existing.get("ids"):
                    collection.delete(ids=existing["ids"])
                    log.info(f"기존 fin_extract 청크 삭제: {len(existing['ids'])}건")
            except Exception as e:
                log.warning(f"기존 fin_extract 조회 실패 (skip): {e}")

        before_count = collection.count()
        log.info(f"Collection 시작 count: {before_count}")
        if limit_docs > 0:
            log.info(f"⚠ SAMPLE MODE: 처음 {limit_docs}개 문서만 처리")

        # raw_text 가져오기
        rows = db.execute(text("""
            SELECT o.document_id, o.raw_text, dm.company_name, dm.company_name_norm,
                   dm.fiscal_year, dm.report_type, d.filename
            FROM ocr_texts o
            JOIN document_metadata dm ON dm.document_id = o.document_id
            JOIN documents d ON d.id = o.document_id
            WHERE dm.company_name_norm IS NOT NULL
              AND dm.company_name_norm != ''
              AND o.raw_text IS NOT NULL
              AND length(o.raw_text) > 500
        """)).fetchall()

        if limit_docs > 0:
            rows = rows[:limit_docs]
        log.info(f"대상 문서: {len(rows)}건")

        # ── Phase 1: 청크 추출 ──
        all_chunks = []  # list of (doc_id, position, text, metadata)
        docs_with_chunks = 0
        for doc_id, raw_text, company_name, company_norm, fy, report_type, filename in rows:
            chunks = extract_financial_chunks(raw_text)
            if chunks:
                docs_with_chunks += 1
                for c in chunks:
                    metadata = {
                        "document_id": int(doc_id),
                        "company_name": company_norm or company_name or "",
                        "fiscal_year": int(fy) if fy else 0,
                        "report_type": report_type or "",
                        "source_file": filename or "",
                        "source_kind": "financial_extract",
                        "category": "financial",
                    }
                    all_chunks.append((doc_id, c["position"], c["text"], metadata))

        log.info(f"추출된 청크: {len(all_chunks)}건 (from {docs_with_chunks} docs)")

        if not all_chunks:
            log.warning("추출된 청크 없음 → 종료")
            return

        # ── Phase 2: 배치 임베딩 + ChromaDB add ──
        added = 0
        start_time = time.time()
        for batch_start in range(0, len(all_chunks), BATCH_SIZE):
            batch = all_chunks[batch_start:batch_start + BATCH_SIZE]
            texts = [b[2] for b in batch]

            embeddings = _get_embeddings_batch(texts)

            ids = []
            valid_embeddings = []
            valid_documents = []
            valid_metadatas = []
            for (doc_id, pos, txt, meta), emb in zip(batch, embeddings):
                if emb is None:
                    continue
                uid = make_chunk_uid(doc_id, pos)
                ids.append(uid)
                valid_embeddings.append(emb)
                valid_documents.append(txt)
                valid_metadatas.append(meta)

            if ids:
                try:
                    collection.add(
                        ids=ids,
                        embeddings=valid_embeddings,
                        documents=valid_documents,
                        metadatas=valid_metadatas,
                    )
                    added += len(ids)
                except Exception as e:
                    log.warning(f"ChromaDB add 실패 (batch {batch_start}): {e}")

            # ── CPU 휴식: 배치 사이 sleep ──
            time.sleep(SLEEP_BETWEEN_BATCHES)

            if (batch_start // BATCH_SIZE) % 20 == 0:
                elapsed = time.time() - start_time
                rate = added / max(elapsed, 1)
                eta = (len(all_chunks) - added) / max(rate, 0.1)
                log.info(f"  진행: {added}/{len(all_chunks)} ({rate:.1f} ch/s, ETA {eta/60:.1f}분)")

        elapsed = time.time() - start_time
        after_count = collection.count()
        log.info("=" * 60)
        log.info(f"신규 추가: {added}건 / {len(all_chunks)} 시도")
        log.info(f"Collection: {before_count} → {after_count} (+{after_count - before_count})")
        log.info(f"소요 시간: {elapsed:.1f}s ({added / max(elapsed,1):.1f} chunks/s)")
        log.info("완료")
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="처음 N개 문서만 (sample mode)")
    args = parser.parse_args()
    main(limit_docs=args.limit)
