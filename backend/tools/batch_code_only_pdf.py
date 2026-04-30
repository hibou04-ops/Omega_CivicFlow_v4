# -*- coding: utf-8 -*-
"""
batch_code_only_pdf.py — Code-only 확장판 PDF 생성 배치

LLM 사용 없이 OCR 텍스트 + financial_facts에서 정형 데이터 추출 → PDF 생성.

포함 섹션:
  1. 문서 메타
  2. 재무 핵심 지표 (financial_facts ground truth)
  3. 사업 개요 (OCR regex)
  4. 사업 부문별 매출 (OCR 표 파싱)
  5. 주요 임원 (OCR regex)
  6. 감사 정보 (OCR regex)
  7. 위험 요인 (OCR regex)
  8. 주요 거래처 (OCR regex)
  9. 핵심 요약 (템플릿 기반)

장점:
  - LLM 없음 → GPU 0%, CPU 부하 낮음 (75°C 이하 안전)
  - 환각 0% (모든 데이터는 OCR 원문에서 직접 추출)
  - 속도: 1문서 ~50ms → 3,135건 ~3분
  - 비용: $0

옵션:
  --limit N         처음 N건만 (테스트)
  --resume          checkpoint에서 재개
  --start-from ID   특정 doc_id부터 시작

사용:
  python backend/tools/batch_code_only_pdf.py --limit 5     # 테스트
  python backend/tools/batch_code_only_pdf.py --resume       # 풀배치
"""
import sys
import os
import re
import json
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path

THIS_DIR = Path(__file__).parent
BACKEND_DIR = THIS_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CHECKPOINT_FILE = THIS_DIR / "code_only_checkpoint.json"
LOG_FILE = THIS_DIR / "code_only_batch.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("CodeOnlyBatch")


# ═══════════════════════════════════════════════════════════════
# 보일러플레이트 제거 (extractor 호출 전 전처리)
# ═══════════════════════════════════════════════════════════════
# 보수적 패턴만 사용. 본문 내용을 잘못 잘라내지 않도록 주의.

_BOILERPLATE_PATTERNS = [
    # DART 표지/안내문
    re.compile(r'금융감독원\s*전자공시시스템[^.。]{0,300}?(?:이용|안내)[^.。]{0,100}?[.。]'),
    # 단위 표기 (재무는 financial_facts에서 가져오므로 안전)
    re.compile(r'\(단위\s*[:：]\s*[^)]{0,30}\)'),
    # 각주 번호 마커
    re.compile(r'주\s*\d{1,2}\)\s*'),
    # OCR 구분선 (4자 이상 연속)
    re.compile(r'[-=─━_]{4,}'),
    # 페이지 번호 패턴
    re.compile(r'(?:^|\n)\s*-\s*\d{1,4}\s*-\s*(?:\n|$)'),
]


def _strip_boilerplate(text: str) -> str:
    """보일러플레이트 제거 (보수적). 본문은 보존."""
    if not text:
        return text
    for pat in _BOILERPLATE_PATTERNS:
        text = pat.sub(' ', text)
    # 연속 공백 정규화
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ═══════════════════════════════════════════════════════════════
# ProcessPool 워커 — 각 워커는 자체 DB 세션 생성
# ═══════════════════════════════════════════════════════════════

_worker_db = None


def _worker_init():
    """워커 프로세스 1회 초기화 — 자체 SessionLocal 생성."""
    global _worker_db
    if _worker_db is None:
        from database import SessionLocal
        _worker_db = SessionLocal()
        # SQLite WAL + busy_timeout (동시 쓰기 안정성)
        try:
            from sqlalchemy import text as sql_text
            _worker_db.execute(sql_text("PRAGMA journal_mode=WAL"))
            _worker_db.execute(sql_text("PRAGMA busy_timeout=30000"))
            _worker_db.commit()
        except Exception:
            pass


def _worker_process(doc_id: int) -> dict:
    """ProcessPool용 picklable 워커 함수."""
    global _worker_db
    if _worker_db is None:
        _worker_init()
    try:
        result = process_one(doc_id, _worker_db)
        result['doc_id'] = doc_id
        return result
    except Exception as e:
        return {'ok': False, 'doc_id': doc_id, 'error': f'worker exception: {e}', 'time': 0}


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"completed_doc_ids": [], "failed_doc_ids": [], "started_at": None,
            "stats": {"success": 0, "failed": 0, "total_time_sec": 0.0}}


def save_checkpoint(cp: dict) -> None:
    CHECKPOINT_FILE.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


def process_one(doc_id: int, db) -> dict:
    """문서 1건 Code-only 처리 (LLM 없음).

    Returns: {'ok': bool, 'time': sec, 'error'?, 'pdf'?}
    """
    from models.models import Document, AnalysisResult, OcrText, DocumentMetadata
    from services.code_only_extractor import extract_all_structured_data
    from services.pdf_report_service import generate_pdf_report

    t0 = time.time()

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return {"ok": False, "time": 0, "error": "document not found"}

    # OCR 원문 로드
    ocr_rows = db.query(OcrText).filter(OcrText.document_id == doc_id).all()
    if not ocr_rows:
        return {"ok": False, "time": 0, "error": "no ocr_texts"}

    raw_text = "\n\n".join(
        ot.raw_text or "" for ot in sorted(ocr_rows, key=lambda x: x.id)
        if ot.raw_text and len(ot.raw_text.strip()) > 10
    )
    if not raw_text or len(raw_text) < 100:
        return {"ok": False, "time": 0, "error": "insufficient text"}

    # 보일러플레이트 제거 (extractor 호출 전 전처리)
    raw_text = _strip_boilerplate(raw_text)

    # 메타데이터
    meta = db.query(DocumentMetadata).filter(DocumentMetadata.document_id == doc_id).first()
    company = meta.company_name_norm or meta.company_name or "미확인" if meta else "미확인"
    fy = meta.fiscal_year or 0 if meta else 0
    report_type = meta.report_type or "기타" if meta else "기타"

    # ── 구조화 데이터 추출 (code-only, O(n) — 매우 빠름) ──
    extracted = extract_all_structured_data(raw_text, company, fy)

    # ── financial_facts 조회 (narrative summarizer 입력) ──
    try:
        from sqlalchemy import text as sql_text
        ff_rows = db.execute(sql_text("""
            SELECT metric_name, metric_value_num FROM financial_facts
            WHERE document_id = :doc_id AND metric_value_num IS NOT NULL
        """), {"doc_id": doc_id}).fetchall()
        facts_dict = {r[0]: float(r[1]) for r in ff_rows}
    except Exception:
        facts_dict = {}

    # ── 진짜 자연어 요약 (narrative_summarizer, 템플릿 기반) ──
    disclosure_title_text = ""
    try:
        from services.narrative_summarizer import (
            compose_narrative_summary, extract_evidence_quotes,
            format_financial_metrics_or_event, extract_document_title,
        )
        summary_text = compose_narrative_summary(
            company=company, fy=fy, report_type=report_type,
            raw_text=raw_text, facts=facts_dict, extracted=extracted,
        )
        # 근거 문장 (UI "근거 문장" 영역용)
        evidence_quotes = extract_evidence_quotes(raw_text, facts=facts_dict, max_quotes=5)
        evidence_text = "\n• " + "\n• ".join(evidence_quotes) if evidence_quotes else ""
        # 핵심 재무 — P&L 우선, 없으면 이벤트 핵심 숫자 (처분금액/발행총액 등)
        financial_metrics_text = format_financial_metrics_or_event(facts_dict, raw_text)
        # 공시명 — raw_text에서 실제 제목 추출 (generic/blacklist 오매칭 시 report_type으로 fallback)
        disclosure_title_text = extract_document_title(raw_text, report_type_fallback=report_type)
    except Exception as e:
        logger.warning(f"  narrative 요약 실패 (fallback): {e}")
        summary_text = extracted.get("short_summary", "")
        evidence_text = ""
        financial_metrics_text = "해당 없음"

    # 추출 결과를 raw_response에 병합 (PDF 섹션 렌더용)
    merged_raw = dict(extracted)
    merged_raw["summary"] = summary_text

    # analysis_data 구성 (generate_pdf_report 호환 형식)
    analysis_data = {
        "summary": summary_text,
        "category": report_type,
        "financial_metrics": financial_metrics_text,
        "insight_vectors": "",
        "evidence": evidence_text,
        "raw_response": merged_raw,
    }

    # AnalysisResult 저장 (idempotent: upsert)
    try:
        from config import settings
        existing = (
            db.query(AnalysisResult)
            .filter(AnalysisResult.document_id == doc_id)
            .order_by(AnalysisResult.created_at.desc())
            .first()
        )
        if existing:
            existing.summary = analysis_data["summary"]
            existing.category = report_type
            existing.financial_metrics = financial_metrics_text
            existing.insight_vectors = ""
            existing.evidence = analysis_data["evidence"]
            existing.raw_response = json.dumps(extracted, ensure_ascii=False, default=str)
            existing.model_name = "code_only_v1"
            existing.processing_time = time.time() - t0
        else:
            new_ar = AnalysisResult(
                document_id=doc_id,
                summary=analysis_data["summary"],
                category=report_type,
                financial_metrics=financial_metrics_text,
                insight_vectors="",
                evidence=analysis_data["evidence"],
                raw_response=json.dumps(extracted, ensure_ascii=False, default=str),
                model_name="code_only_v1",
                processing_time=time.time() - t0,
            )
            db.add(new_ar)
        # ── document_metadata.disclosure_title 보강 ──
        # 기존 값이 '보고서 유형: XXX' 같은 라벨이거나 비어있으면 실제 제목으로 교체
        if disclosure_title_text and meta is not None:
            current = (meta.disclosure_title or "").strip()
            if not current or current.startswith("보고서 유형") or current == report_type:
                meta.disclosure_title = disclosure_title_text
        doc.status = "analyzed"
        db.commit()
    except Exception as e:
        db.rollback()
        return {"ok": False, "time": time.time() - t0, "error": f"DB 저장 실패: {e}"}

    # PDF 생성
    pdf_path = None
    try:
        pdf_path = generate_pdf_report(
            document_id=doc_id,
            filename=doc.filename,
            analysis_data=analysis_data,
        )
        if pdf_path:
            doc.report_path = pdf_path
            db.commit()
    except Exception as e:
        logger.warning(f"  └─ PDF 생성 실패 (추출 결과는 DB 저장됨): {e}")

    elapsed = time.time() - t0
    n_segs = len(extracted.get("business_segments", []))
    n_execs = len(extracted.get("executives", []))
    audit_str = extracted.get("audit_info", {}).get("opinion", "?")

    return {
        "ok": True, "time": elapsed, "pdf": pdf_path,
        "segs": n_segs, "execs": n_execs, "audit": audit_str,
    }


def main():
    parser = argparse.ArgumentParser(description="Code-only PDF Generation Batch")
    parser.add_argument("--limit", type=int, default=None, help="처음 N건만 (테스트)")
    parser.add_argument("--resume", action="store_true", help="checkpoint에서 재개")
    parser.add_argument("--start-from", type=int, default=None, help="특정 doc_id부터 시작")
    parser.add_argument("--workers", type=int, default=4, help="ProcessPool 워커 수 (기본 4, 1=직렬)")
    args = parser.parse_args()

    from database import SessionLocal
    from sqlalchemy import text as sql_text

    db = SessionLocal()
    try:
        id_filter = f"AND d.id >= {int(args.start_from)}" if args.start_from else ""

        rows = db.execute(sql_text(f"""
            SELECT d.id FROM documents d
            WHERE d.status IN ('ocr_done', 'analyzed')
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
        logger.info(f"Code-only PDF Batch — {total} documents")
        logger.info(f"Mode: Code-only (LLM 없음, GPU 0%)")
        logger.info(f"Workers: {args.workers}")
        logger.info(f"Checkpoint: {CHECKPOINT_FILE}")
        logger.info("=" * 60)

        if not cp.get("started_at"):
            cp["started_at"] = datetime.now().isoformat()

        t_start = time.time()
        success = 0
        failed = 0
        idx = 0

        def handle_result(doc_id: int, result: dict):
            """결과 1건 후처리 — 직렬/병렬 공통 로직."""
            nonlocal success, failed, idx
            idx += 1
            if result.get("ok"):
                success += 1
                cp["completed_doc_ids"].append(doc_id)
                if idx <= 10 or idx % 100 == 0:
                    logger.info(
                        f"  [{idx}/{total}] doc={doc_id} OK "
                        f"({result.get('time', 0)*1000:.0f}ms, "
                        f"segs={result.get('segs', 0)}, "
                        f"audit={result.get('audit', '?')})"
                    )
            else:
                failed += 1
                cp["failed_doc_ids"].append({"doc_id": doc_id, "error": result.get("error", "unknown")})
                logger.warning(f"  [{idx}/{total}] doc={doc_id} FAIL: {result.get('error', '')[:100]}")

            cp["stats"]["success"] = success + len(done_set)
            cp["stats"]["failed"] = failed
            cp["stats"]["total_time_sec"] = time.time() - t_start

            if idx % 50 == 0 or idx == total:
                save_checkpoint(cp)

            if idx % 100 == 0 or idx == total:
                elapsed = time.time() - t_start
                rate = idx / max(elapsed, 0.001)
                remaining_sec = (total - idx) / max(rate, 0.001)
                logger.info(
                    f"  진행: {idx}/{total} ({idx * 100 // total}%) "
                    f"| 성공: {success} 실패: {failed} "
                    f"| 경과: {elapsed:.0f}s | ETA: {remaining_sec:.0f}s"
                )

        # ─── 병렬/직렬 분기 ───────────────────────────────
        if args.workers > 1:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            logger.info(f"ProcessPoolExecutor 모드 ({args.workers} workers)")
            try:
                with ProcessPoolExecutor(
                    max_workers=args.workers,
                    initializer=_worker_init,
                ) as executor:
                    futures = {executor.submit(_worker_process, d): d for d in pending}
                    try:
                        for fut in as_completed(futures):
                            doc_id = futures[fut]
                            try:
                                result = fut.result()
                            except Exception as e:
                                result = {"ok": False, "error": str(e), "time": 0}
                            handle_result(doc_id, result)
                    except KeyboardInterrupt:
                        logger.warning("Ctrl+C — checkpoint 저장 후 종료")
                        save_checkpoint(cp)
                        executor.shutdown(wait=False, cancel_futures=True)
                        return
            except Exception as e:
                logger.error(f"ProcessPool 오류: {e}")
                save_checkpoint(cp)
                raise
        else:
            # 직렬 모드 (기존 로직)
            for doc_id in pending:
                try:
                    result = process_one(doc_id, db)
                except KeyboardInterrupt:
                    logger.warning("Ctrl+C — checkpoint 저장 후 종료")
                    save_checkpoint(cp)
                    return
                except Exception as e:
                    logger.error(f"  [doc={doc_id}] 예외: {e}")
                    result = {"ok": False, "error": str(e), "time": 0}
                handle_result(doc_id, result)

        save_checkpoint(cp)
        elapsed_total = time.time() - t_start
        logger.info("\n" + "=" * 60)
        logger.info("배치 완료")
        logger.info(f"총 처리: {total}건 | 성공: {success} | 실패: {failed}")
        logger.info(f"소요: {elapsed_total:.1f}초 ({elapsed_total / 60:.1f}분)")
        logger.info(f"평균: {elapsed_total * 1000 / max(total, 1):.0f} ms/문서")
        logger.info("=" * 60)

    finally:
        db.close()


if __name__ == "__main__":
    main()
