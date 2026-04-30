# -*- coding: utf-8 -*-
"""
batch_llm_analyze_and_pdf.py — 3,135 OCR'd 문서 LLM 분석 + PDF 생성 배치

흐름 (문서 1건당):
  1. ocr_texts 로드 + text_preprocessor.preprocess
  2. await _analyze_with_best_engine(full_text)  ← Ollama exaone3.5:7.8b
  3. AnalysisResult 저장
  4. generate_pdf_report → PDF 생성
  5. doc.report_path 업데이트, status='analyzed'
  6. checkpoint 업데이트

복원력:
  - checkpoint: backend/tools/llm_analyze_checkpoint.json
  - --resume: 기존 checkpoint에서 이어서
  - 에러 시: 로그에 기록 + 다음 문서로 진행 (전체 안 멈춤)
  - Ctrl+C: 현재 문서 끝나면 안전 종료 (다음 사이클에 checkpoint 저장됨)

옵션:
  --limit N         처음 N건만 처리 (테스트/벤치마크)
  --resume          checkpoint에서 재개 (디폴트: 처음부터)
  --start-from ID   특정 doc_id부터 시작
  --no-pdf          PDF 생성 스킵 (LLM 분석만)

사용 예시:
  python backend/tools/batch_llm_analyze_and_pdf.py --limit 2     # 벤치마크
  python backend/tools/batch_llm_analyze_and_pdf.py --resume      # 풀배치 (재개)
"""
import sys
import os
import json
import time
import asyncio
import logging
import argparse
from datetime import datetime
from pathlib import Path

THIS_DIR = Path(__file__).parent
BACKEND_DIR = THIS_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CHECKPOINT_FILE = THIS_DIR / "llm_analyze_checkpoint.json"
LOG_FILE = THIS_DIR / "llm_analyze.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("BatchLLMAnalyze")


# ═══════════════════════════════════════════════════════════════
# Checkpoint 관리
# ═══════════════════════════════════════════════════════════════

def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("checkpoint 파일 손상, 새로 시작")
    return {
        "completed_doc_ids": [],
        "failed_doc_ids": [],
        "started_at": None,
        "stats": {"success": 0, "failed": 0, "total_time_sec": 0.0},
    }


def save_checkpoint(cp: dict) -> None:
    CHECKPOINT_FILE.write_text(
        json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ═══════════════════════════════════════════════════════════════
# 문서 1건 처리
# ═══════════════════════════════════════════════════════════════

async def process_one(doc_id: int, db, no_pdf: bool) -> dict:
    """
    문서 1건 처리 — LLM 분석 + (선택) PDF 생성.

    Returns: {'ok': bool, 'time': sec, 'error'?, 'pdf'?, 'category'?}
    """
    from models.models import Document, AnalysisResult, OcrText, Page
    from routers.documents import _analyze_with_best_engine
    from services.text_preprocessor import text_preprocessor
    from config import settings

    t0 = time.time()

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return {"ok": False, "time": 0, "error": "document not found"}

    # OCR 텍스트 재조합 (reanalyze 라우트와 동일 로직)
    ocr_texts = db.query(OcrText).filter(OcrText.document_id == doc.id).all()
    if not ocr_texts:
        return {"ok": False, "time": 0, "error": "no ocr_texts"}

    pages_for_preprocess = []
    for ot in sorted(ocr_texts, key=lambda x: x.id):
        page = db.query(Page).filter(Page.id == ot.page_id).first() if ot.page_id else None
        page_num = page.page_number if page else 1
        text = ot.cleaned_text or ot.raw_text or ""
        if text.strip():
            pages_for_preprocess.append((page_num, text))

    if not pages_for_preprocess:
        return {"ok": False, "time": 0, "error": "no valid text"}

    try:
        full_text = text_preprocessor.preprocess(pages_for_preprocess)
    except Exception:
        full_text = "\n\n".join(t for _, t in pages_for_preprocess)

    # LLM 분석 (Ollama exaone3.5:7.8b → vLLM fallback)
    try:
        analysis = await _analyze_with_best_engine(full_text)
    except Exception as e:
        return {"ok": False, "time": time.time() - t0, "error": f"LLM 호출 예외: {e}"}

    if not analysis or analysis.get("_is_error"):
        err_msg = (analysis or {}).get("summary", "unknown")[:120]
        return {"ok": False, "time": time.time() - t0, "error": f"LLM 에러: {err_msg}"}

    # AnalysisResult 저장 (existing → update / 없으면 → insert)
    try:
        existing = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.document_id == doc_id)
            .order_by(AnalysisResult.created_at.desc())
            .first()
        )
        if existing:
            existing.summary = analysis.get("summary", "")
            existing.category = analysis.get("category", "기타")
            existing.financial_metrics = analysis.get("financial_metrics", "해당 없음")
            existing.insight_vectors = analysis.get("insight_vectors", "해당 없음")
            existing.evidence = analysis.get("evidence", "")
            existing.raw_response = analysis
            existing.model_name = analysis.get("_model", settings.OLLAMA_MODEL)
            existing.processing_time = analysis.get("_processing_time", time.time() - t0)
        else:
            new_ar = AnalysisResult(
                document_id=doc.id,
                summary=analysis.get("summary", ""),
                category=analysis.get("category", "기타"),
                financial_metrics=analysis.get("financial_metrics", "해당 없음"),
                insight_vectors=analysis.get("insight_vectors", "해당 없음"),
                evidence=analysis.get("evidence", ""),
                raw_response=json.dumps(analysis, ensure_ascii=False, default=str),
                model_name=analysis.get("_model", settings.OLLAMA_MODEL),
                processing_time=analysis.get("_processing_time", time.time() - t0),
            )
            db.add(new_ar)
        doc.status = "analyzed"
        db.commit()
    except Exception as e:
        db.rollback()
        return {"ok": False, "time": time.time() - t0, "error": f"DB 저장 실패: {e}"}

    # PDF 생성 (옵션)
    pdf_path = None
    if not no_pdf:
        try:
            from services.pdf_report_service import generate_pdf_report
            pdf_path = generate_pdf_report(
                document_id=doc.id,
                filename=doc.filename,
                analysis_data={
                    "summary": analysis.get("summary", ""),
                    "category": analysis.get("category", "기타"),
                    "financial_metrics": analysis.get("financial_metrics", "해당 없음"),
                    "insight_vectors": analysis.get("insight_vectors", "해당 없음"),
                    "evidence": analysis.get("evidence", ""),
                    "raw_response": analysis,
                },
            )
            if pdf_path:
                doc.report_path = pdf_path
                db.commit()
        except Exception as e:
            logger.warning(f"  └─ PDF 생성 실패 (LLM 분석은 저장됨): {e}")

    elapsed = time.time() - t0
    return {
        "ok": True,
        "time": elapsed,
        "pdf": pdf_path,
        "category": analysis.get("category", "?"),
    }


# ═══════════════════════════════════════════════════════════════
# 메인 배치 루프
# ═══════════════════════════════════════════════════════════════

async def main_async(args):
    from database import SessionLocal
    from sqlalchemy import text as sql_text

    db = SessionLocal()
    try:
        # 처리 대상 doc_id 목록
        # status='ocr_done' AND AnalysisResult 없는 문서
        id_filter = ""
        if args.start_from:
            id_filter = f"AND d.id >= {int(args.start_from)}"

        rows = db.execute(sql_text(f"""
            SELECT d.id FROM documents d
            LEFT JOIN analysis_results ar ON ar.document_id = d.id
            WHERE d.status = 'ocr_done'
              AND ar.id IS NULL
              {id_filter}
            ORDER BY d.id
        """)).fetchall()
        all_doc_ids = [r[0] for r in rows]

        cp = load_checkpoint()
        done_set = set(cp["completed_doc_ids"]) if args.resume else set()

        if args.resume:
            logger.info(f"Resume mode: {len(done_set)} 건 완료됨, 스킵")

        pending = [d for d in all_doc_ids if d not in done_set]

        if args.limit:
            pending = pending[: args.limit]

        total = len(pending)
        if total == 0:
            logger.info("처리할 문서가 없습니다.")
            return

        logger.info("=" * 60)
        logger.info(f"Batch LLM Analyze + PDF — {total} documents")
        logger.info(f"Model      : Ollama exaone3.5:7.8b (via _analyze_with_best_engine)")
        logger.info(f"PDF gen    : {'OFF' if args.no_pdf else 'ON'}")
        logger.info(f"Checkpoint : {CHECKPOINT_FILE}")
        logger.info(f"Log file   : {LOG_FILE}")
        logger.info("=" * 60)

        if not cp.get("started_at"):
            cp["started_at"] = datetime.now().isoformat()

        t_start = time.time()
        success = 0
        failed = 0

        for idx, doc_id in enumerate(pending, 1):
            logger.info(f"[{idx}/{total}] doc_id={doc_id} 처리 중...")

            try:
                result = await process_one(doc_id, db, args.no_pdf)
            except KeyboardInterrupt:
                logger.warning("Ctrl+C 감지 — 현재 문서까지 저장하고 종료")
                save_checkpoint(cp)
                return
            except Exception as e:
                logger.error(f"  └─ 예외: {e}", exc_info=True)
                result = {"ok": False, "error": f"unhandled: {e}", "time": 0}

            if result["ok"]:
                success += 1
                cp["completed_doc_ids"].append(doc_id)
                logger.info(
                    f"  └─ OK ({result['time']:.1f}s) [{result.get('category', '?')}]"
                    f"{' + PDF' if result.get('pdf') else ''}"
                )
            else:
                failed += 1
                cp["failed_doc_ids"].append(
                    {"doc_id": doc_id, "error": result.get("error", "unknown")}
                )
                logger.warning(f"  └─ FAIL: {result.get('error', '')}")

            cp["stats"]["success"] = success + len(done_set)
            cp["stats"]["failed"] = failed
            cp["stats"]["total_time_sec"] = time.time() - t_start

            # checkpoint 매 5건마다 저장 (disk write 빈도 조절)
            if idx % 5 == 0 or idx == total:
                save_checkpoint(cp)

            # 진행률 + ETA 매 10건마다
            if idx % 10 == 0 or idx == total:
                elapsed = time.time() - t_start
                rate = idx / max(elapsed, 0.001)
                remaining_sec = (total - idx) / max(rate, 0.001)
                logger.info(
                    f"\n{'─' * 40}\n"
                    f"진행: {idx}/{total} ({idx * 100 // total}%)\n"
                    f"성공: {success} | 실패: {failed}\n"
                    f"평균: {elapsed / idx:.1f}s/문서\n"
                    f"경과: {elapsed / 60:.1f}분 | ETA: {remaining_sec / 60:.1f}분\n"
                    f"{'─' * 40}"
                )

        # ── 최종 저장 + 요약 ──
        save_checkpoint(cp)
        elapsed_total = time.time() - t_start
        logger.info("\n" + "=" * 60)
        logger.info("배치 완료")
        logger.info(f"총 처리   : {total}건")
        logger.info(f"성공     : {success}건")
        logger.info(f"실패     : {failed}건")
        logger.info(
            f"소요     : {elapsed_total / 60:.1f}분 "
            f"(평균 {elapsed_total / max(total, 1):.1f}s/문서)"
        )
        logger.info(f"Checkpoint: {CHECKPOINT_FILE}")
        logger.info("=" * 60)

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Batch LLM Analyze + PDF Generation (Ollama exaone3.5:7.8b)"
    )
    parser.add_argument("--limit", type=int, default=None, help="처음 N건만 처리 (테스트)")
    parser.add_argument("--resume", action="store_true", help="checkpoint에서 재개")
    parser.add_argument("--start-from", type=int, default=None, help="특정 doc_id부터 시작")
    parser.add_argument("--no-pdf", action="store_true", help="PDF 생성 스킵 (LLM만)")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
