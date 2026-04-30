"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Background Tasks
에너지 변환 노드 (Energy Conversion Nodes)
OCR + LLM 분석을 Celery 워커에서 비동기 처리
═══════════════════════════════════════════════════════
"""

import json
import logging
import asyncio
from celery_app import celery_app
from database import SessionLocal
from models.models import Document, AnalysisResult
from config import settings

logger = logging.getLogger("omega.civicflow.tasks")


def _run_async(coro):
    """동기 컨텍스트에서 async 함수 실행"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def process_document_task(self, document_id: int):
    """
    단일 문서의 OCR + LLM 분석을 백그라운드에서 처리
    """
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            logger.error(f"문서 #{document_id} 찾을 수 없음")
            return {"status": "error", "detail": "문서 없음"}

        logger.info(f"🔄 백그라운드 처리 시작 — 문서 #{doc.id}: {doc.filename}")

        # 1. OCR 텍스트 추출
        from services.ocr_service import extract_text_from_file
        import os

        file_path = doc.file_path
        if not os.path.exists(file_path):
            doc.status = "failed"
            db.commit()
            return {"status": "failed", "detail": "파일 없음"}

        try:
            doc.status = "ocr_running"
            db.commit()
            ocr_result = extract_text_from_file(file_path)
            full_text = ocr_result.get("full_text", "")
            pages = ocr_result.get("pages", [])

            # 페이지별 저장
            from models.models import Page, OcrText
            for page_data in pages:
                page = Page(
                    document_id=doc.id,
                    page_number=page_data.get("page_number", 1),
                    width=page_data.get("width", 0),
                    height=page_data.get("height", 0),
                )
                db.add(page)
                db.flush()

                ocr_text = OcrText(
                    page_id=page.id,
                    text=page_data.get("text", ""),
                    confidence=page_data.get("confidence", 0.0),
                )
                db.add(ocr_text)

            doc.status = "ocr_done"
            db.commit()

        except Exception as e:
            logger.error(f"OCR 실패 — 문서 #{doc.id}: {e}")
            doc.status = "failed"
            db.commit()
            return {"status": "failed", "detail": f"OCR 실패: {str(e)}"}

        # 2. 텍스트 전처리
        try:
            from services.text_preprocessor import TextPreprocessor
            preprocessor = TextPreprocessor()
            # preprocess()는 List[Tuple[int, str]]을 기대
            pages_for_preprocess = [
                (p.get("page_number", i+1), p.get("text", ""))
                for i, p in enumerate(pages) if p.get("text")
            ]
            if pages_for_preprocess:
                full_text = preprocessor.preprocess(pages_for_preprocess)
        except Exception as e:
            logger.warning(f"전처리 실패 (원본 텍스트 사용): {e}")

        # 2.5 OCR 텍스트 품질 태깅 — 품질 낮은 페이지에 경고 태그
        try:
            from services.text_quality import tag_text_by_quality
            tagged_text, enriched_pages = tag_text_by_quality(pages)
            if tagged_text.strip():
                full_text = tagged_text
                logger.info(
                    f"  ├─ 품질 태깅 완료 — "
                    f"good: {sum(1 for p in enriched_pages if p.get('quality_tag')=='good')}, "
                    f"low: {sum(1 for p in enriched_pages if p.get('quality_tag')=='low')}, "
                    f"excluded: {sum(1 for p in enriched_pages if p.get('quality_tag')=='very_low')}"
                )
        except Exception as e:
            logger.warning(f"품질 태깅 실패 (원본 텍스트 사용): {e}")

        # 3. LLM 분석 — VRAM 상태에 따라 자동 분기
        # docx 패턴: VRAM 85% 초과 시 GPU 0% 코드온리로 전환
        analysis = {}
        try:
            doc.status = "analyzing"
            db.commit()

            # VRAM 체크
            from services.session_pool import get_vram_usage
            from models.models import DocumentMetadata
            vram = get_vram_usage()
            use_code_only = vram["pct"] > 85.0

            if use_code_only:
                # ── 코드온리 경로: GPU 0%, ~50ms ──
                logger.info(
                    f"  ⚡ VRAM {vram['pct']:.1f}% > 85%% → 코드온리 모드 "
                    f"(문서 #{doc.id})"
                )
                from services.code_only_extractor import extract_all_structured_data
                from services.narrative_summarizer import (
                    compose_narrative_summary,
                    format_financial_metrics_or_event,
                )
                import time as _time

                meta = db.query(DocumentMetadata).filter(
                    DocumentMetadata.document_id == doc.id
                ).first()
                company = (meta.company_name_norm or "미확인") if meta else "미확인"
                fy = (meta.fiscal_year or 0) if meta else 0
                report_type = (meta.report_type or "기타") if meta else "기타"

                t0 = _time.time()
                extracted = extract_all_structured_data(full_text, company, fy)
                summary_text = compose_narrative_summary(
                    company=company, fy=fy, report_type=report_type,
                    raw_text=full_text, facts={}, extracted=extracted,
                )
                financial_metrics = format_financial_metrics_or_event({}, full_text)

                analysis = {
                    "summary": summary_text,
                    "category": report_type,
                    "financial_metrics": financial_metrics,
                    "insight_vectors": "",
                    "evidence": "",
                    "_model": "code_only_v1",
                    "_processing_time": _time.time() - t0,
                    "_vram_trigger": round(vram["pct"], 1),
                }
            else:
                # ── LLM 경로: 정상 분석 ──
                logger.info(
                    f"  🧠 VRAM {vram['pct']:.1f}%% → LLM 모드 (문서 #{doc.id})"
                )
                from services.llm_service import LLMService
                llm_service = LLMService()
                analysis = _run_async(llm_service.analyze_document(full_text))

            analysis_record = AnalysisResult(
                document_id=doc.id,
                summary=analysis.get("summary", ""),
                category=analysis.get("category", "기타"),
                financial_metrics=str(analysis.get("financial_metrics", "데이터 불충분")) if isinstance(analysis.get("financial_metrics"), dict) else analysis.get("financial_metrics", "데이터 불충분"),
                insight_vectors=str(analysis.get("insight_vectors", "데이터 불충분")) if isinstance(analysis.get("insight_vectors"), dict) else analysis.get("insight_vectors", "데이터 불충분"),
                evidence=analysis.get("evidence", ""),
                raw_response=analysis,
                model_name=analysis.get("_model", settings.OLLAMA_MODEL),
                processing_time=analysis.get("_processing_time", 0.0),
            )
            db.add(analysis_record)
            doc.status = "analyzed"
            db.commit()

            logger.info(f"✅ 분석 완료 — 문서 #{doc.id} [{analysis.get('category', 'N/A')}]")

        except Exception as e:
            db.rollback()
            doc.status = "ocr_done"
            db.commit()
            logger.error(f"LLM 분석 실패 — 문서 #{doc.id}: {e}")

        return {
            "status": doc.status,
            "document_id": doc.id,
            "filename": doc.filename,
            "category": analysis.get("category"),
            "summary": analysis.get("summary"),
        }

    except Exception as e:
        logger.error(f"태스크 실패 — 문서 #{document_id}: {e}")
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()


@celery_app.task
def process_batch_email_task(user_email: str, results: list):
    """분석 완료 후 이메일 발송"""
    from services.email_service import send_analysis_result_email
    try:
        send_analysis_result_email(user_email, results)
        logger.info(f"📧 이메일 발송 완료 → {user_email}")
    except Exception as e:
        logger.error(f"이메일 발송 실패: {e}")
