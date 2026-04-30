# -*- coding: utf-8 -*-
"""
test_narrative_samples.py — narrative_summarizer 3건 샘플 검증

각 보고서 유형(사업보고서/주요사항보고서/감사보고서)에서 1건씩
자동 선택하여 narrative 출력만 확인 (PDF 생성 없음, DB 쓰기 없음).
"""
import sys
from pathlib import Path

THIS_DIR = Path(__file__).parent
BACKEND_DIR = THIS_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import SessionLocal
from models.models import Document, OcrText, DocumentMetadata
from sqlalchemy import text as sql_text
from services.code_only_extractor import extract_all_structured_data
from services.narrative_summarizer import compose_narrative_summary


def find_sample(db, report_type_kw: str) -> int | None:
    """report_type에 키워드가 포함된 doc 1건 찾기 (텍스트 풍부한 순)."""
    rows = db.execute(sql_text("""
        SELECT d.id, dm.report_type, dm.company_name_norm,
               (SELECT SUM(LENGTH(ot.raw_text)) FROM ocr_texts ot WHERE ot.document_id = d.id) AS text_len
          FROM documents d
          JOIN document_metadata dm ON dm.document_id = d.id
         WHERE dm.report_type LIKE :kw
           AND d.status IN ('analyzed', 'ocr_done')
        ORDER BY text_len DESC NULLS LAST
        LIMIT 1
    """), {"kw": f"%{report_type_kw}%"}).fetchone()
    if rows:
        return rows[0], rows[1], rows[2], rows[3]
    return None


def run_one(db, doc_id: int, label: str):
    print("=" * 70)
    print(f"[{label}] doc_id={doc_id}")
    print("=" * 70)

    doc = db.query(Document).filter(Document.id == doc_id).first()
    meta = db.query(DocumentMetadata).filter(DocumentMetadata.document_id == doc_id).first()
    if not doc or not meta:
        print("문서 또는 메타 없음")
        return

    company = meta.company_name_norm or meta.company_name or "미확인"
    fy = meta.fiscal_year or 0
    report_type = meta.report_type or "기타"
    print(f"회사: {company} | 사업연도: {fy} | 유형: {report_type}")
    print(f"파일명: {doc.filename}")

    # OCR
    ocr_rows = db.query(OcrText).filter(OcrText.document_id == doc_id).all()
    raw_text = "\n\n".join(
        ot.raw_text or "" for ot in sorted(ocr_rows, key=lambda x: x.id)
        if ot.raw_text and len(ot.raw_text.strip()) > 10
    )
    print(f"OCR 길이: {len(raw_text):,}자")

    # financial_facts
    ff_rows = db.execute(sql_text("""
        SELECT metric_name, metric_value_num FROM financial_facts
        WHERE document_id = :doc_id AND metric_value_num IS NOT NULL
    """), {"doc_id": doc_id}).fetchall()
    facts = {r[0]: float(r[1]) for r in ff_rows}
    print(f"financial_facts: {len(facts)}건 → {list(facts.keys())[:6]}")

    # extractor
    extracted = extract_all_structured_data(raw_text, company, fy)

    # narrative
    summary = compose_narrative_summary(
        company=company, fy=fy, report_type=report_type,
        raw_text=raw_text, facts=facts, extracted=extracted,
    )

    print("\n--- 생성된 요약 ---")
    print(summary)
    print(f"\n요약 길이: {len(summary)}자")
    print()


def main():
    db = SessionLocal()
    try:
        targets = [
            ("사업보고서", "사업보고서"),
            ("주요사항", "주요사항보고서"),
            ("감사보고서", "감사보고서"),
        ]
        for kw, label in targets:
            res = find_sample(db, kw)
            if res:
                doc_id, rt, comp, tlen = res
                run_one(db, doc_id, label)
            else:
                print(f"[{label}] 샘플 없음 (kw={kw})\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
