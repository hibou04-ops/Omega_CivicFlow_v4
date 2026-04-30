"""
Omega CivicFlow — 전체 문서 PDF 보고서 일괄 재생성
DB에 있는 모든 분석완료 문서에 대해 OCR 원천 텍스트 기반 요약 PDF를 재생성합니다.
"""
import sys
import os
import time
import logging

# 백엔드 루트를 sys.path에 추가
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(BACKEND_DIR, "backend")
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from database import SessionLocal
from models.models import Document, AnalysisResult, OcrText
from services.pdf_report_service import generate_pdf_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def main():
    db = SessionLocal()
    try:
        # [패치] 분석완료 문서 중 제일 끝 150건 강제 추출
        docs = (
            db.query(Document)
            .filter(Document.status == "analyzed")
            .order_by(Document.id.desc())
            .limit(150)
            .all()
        )
        # 해당 150건에 대해서만 이어하기(Skip) 방어막을 뚫고 덮어쓰도록(Overwrite) 유도
        for d in docs:
            d.report_path = None
        total = len(docs)
        logger.info(f"═══ PDF 일괄 재생성 시작: {total}건 ═══")

        success = 0
        fail = 0
        skip = 0

        for idx, doc in enumerate(docs, 1):
            try:
                # 이미 성공적으로 생성된 PDF가 있다면 스킵 (강제 종료 후 이어하기 용도)
                if doc.report_path and os.path.exists(doc.report_path):
                    skip += 1
                    if idx % 50 == 0 or idx == total:
                        logger.info(f"[{idx}/{total}] 진행중... 기존 PDF 스킵 완료")
                    continue

                # AnalysisResult 가져오기
                ar = (
                    db.query(AnalysisResult)
                    .filter(AnalysisResult.document_id == doc.id)
                    .first()
                )
                if not ar:
                    logger.warning(f"[{idx}/{total}] #{doc.id} — AnalysisResult 없음, 스킵")
                    skip += 1
                    continue

                # OCR 텍스트 결합
                ocr_rows = (
                    db.query(OcrText)
                    .filter(OcrText.document_id == doc.id)
                    .order_by(OcrText.id)
                    .all()
                )
                ocr_text = "\n".join(
                    (row.cleaned_text or row.raw_text or "")
                    for row in ocr_rows
                )

                # analysis_data 구성
                analysis_data = {
                    "summary": ar.summary or "",
                    "category": ar.category or "",
                    "financial_metrics": ar.financial_metrics or "",
                    "raw_response": ar.raw_response,
                }

                # PDF 생성
                result = generate_pdf_report(
                    document_id=doc.id,
                    filename=doc.filename,
                    analysis_data=analysis_data,
                    ocr_text=ocr_text,
                )

                if result:
                    # DB에 report_path 업데이트
                    doc.report_path = result
                    db.commit()
                    success += 1
                    if idx % 50 == 0 or idx == total:
                        logger.info(
                            f"[{idx}/{total}] 진행중... "
                            f"성공={success} 실패={fail} 스킵={skip}"
                        )
                else:
                    fail += 1
                    logger.warning(f"[{idx}/{total}] #{doc.id} — PDF 생성 실패")

            except Exception as e:
                fail += 1
                logger.error(f"[{idx}/{total}] #{doc.id} — 예외: {e}")
                db.rollback()

        logger.info(f"═══ PDF 일괄 재생성 완료 ═══")
        logger.info(f"  총 대상: {total}")
        logger.info(f"  성공: {success}")
        logger.info(f"  실패: {fail}")
        logger.info(f"  스킵: {skip}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
