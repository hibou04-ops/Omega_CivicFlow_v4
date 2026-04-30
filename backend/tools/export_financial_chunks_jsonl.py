# -*- coding: utf-8 -*-
"""
export_financial_chunks_jsonl.py — STEP 1: 로컬에서 chunks JSONL export.

Workflow:
  STEP 1 (로컬, 이 스크립트): raw_text → chunks → JSONL
  STEP 2 (콜랩 A100): JSONL → BGE-M3 임베딩 → embeddings JSONL
  STEP 3 (로컬): embeddings JSONL → ChromaDB add

Output: financial_chunks.jsonl (한 줄당 하나의 chunk)
  {"chunk_uid": "fin_extract:95:7761", "text": "...", "metadata": {...}}
"""
import sys
import os
import json
import logging

THIS_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(THIS_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database import SessionLocal
from sqlalchemy import text
sys.path.insert(0, THIS_DIR)
from index_financial_extracts import extract_financial_chunks, make_chunk_uid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

OUTPUT_PATH = os.path.join(BACKEND_DIR, "..", "financial_chunks.jsonl")


def main():
    db = SessionLocal()
    try:
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

        log.info(f"대상 문서: {len(rows)}건")

        total_chunks = 0
        docs_with_chunks = 0
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            for doc_id, raw_text, company_name, company_norm, fy, report_type, filename in rows:
                chunks = extract_financial_chunks(raw_text)
                if chunks:
                    docs_with_chunks += 1
                    # Contextual header — 회사명/연도/보고서를 chunk 본문에 직접 주입.
                    # 목적: dense vector에 회사·연도 신호가 직접 인코딩되도록 하여
                    # 메타필터 의존도를 낮추고 long-tail 쿼리에서도 검색 회복력 확보.
                    company_for_header = company_norm or company_name or "미상"
                    fy_for_header = str(int(fy)) if fy else "미상"
                    report_for_header = report_type or "재무"
                    context_header = (
                        f"[회사: {company_for_header}] "
                        f"[사업연도: {fy_for_header}] "
                        f"[보고서: {report_for_header}]\n\n"
                    )
                    for c in chunks:
                        record = {
                            "chunk_uid": make_chunk_uid(doc_id, c["position"]),
                            "text": context_header + c["text"],
                            "metadata": {
                                "document_id": int(doc_id),
                                "company_name": company_norm or company_name or "",
                                "fiscal_year": int(fy) if fy else 0,
                                "report_type": report_type or "",
                                "source_file": filename or "",
                                "source_kind": "financial_extract",
                                "category": "financial",
                            },
                        }
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        total_chunks += 1

        size_mb = os.path.getsize(OUTPUT_PATH) / 1024 / 1024
        log.info("=" * 60)
        log.info(f"Exported: {total_chunks:,} chunks from {docs_with_chunks} docs")
        log.info(f"Output: {OUTPUT_PATH}")
        log.info(f"Size: {size_mb:.1f} MB")
        log.info("")
        log.info("Next: 이 파일을 콜랩에 업로드 → colab_embed_financial.py 실행")
    finally:
        db.close()


if __name__ == "__main__":
    main()
