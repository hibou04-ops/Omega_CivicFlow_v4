# -*- coding: utf-8 -*-
"""
backfill_facts_from_ocr.py — Restore financial_facts directly from ocr_texts.cleaned_text
when AnalysisResult.summary is empty (post-reset state).

WHY this exists:
- backfill_facts_v2.py reads from analysis_results.summary/financial_metrics/evidence
- After clean_reset_pipeline.py, analysis_results table is empty (0 rows)
- Re-running dart_xml_batch_ingest.py would require Gemini API calls (cost + risk)
- ocr_texts table is INTACT (3,135 rows of cleaned_text per document)
- The pure regex extraction logic (METRIC_PATTERNS) does not need LLM at all

WHAT this does:
- READ ocr_texts JOIN document_metadata (no writes to those tables)
- For each document, run extract_metrics_from_text on cleaned_text
- INSERT into financial_facts with fact_uid for idempotency
- Safe to re-run; existing facts with same uid are skipped

Run: python backend/tools/backfill_facts_from_ocr.py
"""
import sys
import os
import logging

THIS_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(THIS_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from database import SessionLocal
from models.models import FinancialFact
from sqlalchemy import text

# Reuse the pure extraction functions from backfill_facts_v2.py — no LLM, no I/O
sys.path.insert(0, THIS_DIR)
from backfill_facts_v2 import (  # noqa: E402
    extract_metrics_from_text,
    extract_metrics_from_text_table,
    extract_metrics_from_table_v2,
    make_fact_uid,
)


def _hybrid_extract(raw_text: str, cleaned_text: str = "") -> list:
    """
    Hybrid extraction:
    1) v2 (cell-based) 우선 — 더 정밀한 단위 처리, 작은 회사 처리
    2) v2가 못 찾은 메트릭은 v1 (char-window) 결과로 보충
    3) 둘 다 못 찾으면 cleaned_text inline 형식 시도
    """
    v2_results = extract_metrics_from_table_v2(raw_text)
    v2_metric_names = {m["metric_name"] for m in v2_results}

    v1_results = extract_metrics_from_text_table(raw_text)
    # v1 결과 중 v2에 없는 메트릭만 추가
    supplemental = [m for m in v1_results if m["metric_name"] not in v2_metric_names]

    combined = v2_results + supplemental
    if combined:
        return combined

    # 둘 다 실패 시 cleaned_text inline form 시도
    if cleaned_text:
        return extract_metrics_from_text(cleaned_text)
    return []

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)


def main():
    db = SessionLocal()
    try:
        # ── Idempotent refresh: delete previous facts created by THIS script only.
        # 다른 추출 경로(deep_backfill_v2 등)는 그대로 보존된다.
        deleted = db.query(FinancialFact).filter(
            FinancialFact.extraction_method == "ocr_text_regex_backfill"
        ).delete(synchronize_session=False)
        db.commit()
        if deleted:
            log.info(f"기존 ocr_text_regex_backfill facts 삭제: {deleted}건")

        existing_uids = set(uid for (uid,) in db.query(FinancialFact.fact_uid).all())
        before = len(existing_uids)
        log.info(f"기존 facts (다른 경로 보존): {before}건")

        # raw_text를 사용 (cleaned_text는 OCR 정제 과정에서 재무 표가 빠진 경우가 많음)
        rows = db.execute(text("""
            SELECT o.document_id,
                   o.raw_text,
                   o.cleaned_text,
                   dm.company_name,
                   dm.company_name_norm,
                   dm.fiscal_year,
                   dm.statement_scope,
                   dm.corp_code
            FROM ocr_texts o
            JOIN document_metadata dm ON dm.document_id = o.document_id
            WHERE dm.company_name_norm IS NOT NULL
              AND dm.company_name_norm != ''
              AND dm.company_name_norm != '미확인'
              AND dm.fiscal_year IS NOT NULL
              AND o.raw_text IS NOT NULL
              AND length(o.raw_text) > 200
        """)).fetchall()

        log.info(f"대상 문서: {len(rows)}건")

        new_facts = []
        docs_with_metrics = 0
        total_metric_extractions = 0

        for doc_id, raw_text, cleaned_text, company_name, company_norm, fy, scope, corp_code in rows:
            if not company_norm or not fy:
                continue
            # Hybrid: v2 (cell-based) 우선 + v1 (char-window) fallback
            metrics = _hybrid_extract(raw_text, cleaned_text or "")
            if not metrics:
                continue
            docs_with_metrics += 1
            doc_added = 0
            for m in metrics:
                uid = make_fact_uid(doc_id, company_norm, fy, m["metric_name"], scope)
                if uid in existing_uids:
                    continue
                fact = FinancialFact(
                    fact_uid=uid,
                    document_id=doc_id,
                    company_name_norm=company_norm,
                    corp_code=corp_code,
                    fiscal_year=fy,
                    metric_name=m["metric_name"],
                    metric_value_num=m["value"],
                    unit="KRW",
                    statement_scope=scope or "",
                    period_type="annual",
                    confidence=0.70,
                    extraction_method="ocr_text_regex_backfill",
                )
                new_facts.append(fact)
                existing_uids.add(uid)
                doc_added += 1
                total_metric_extractions += 1

            if doc_added > 0 and docs_with_metrics % 200 == 0:
                log.info(f"  진행: {docs_with_metrics} docs / {len(new_facts)} facts queued")

        if new_facts:
            db.bulk_save_objects(new_facts)
            db.commit()

        after = db.query(FinancialFact).count()
        company_count = db.query(FinancialFact.company_name_norm).distinct().count()

        log.info("=" * 60)
        log.info(f"신규 facts: {len(new_facts)}건")
        log.info(f"facts 총합: {before} → {after}")
        log.info(f"facts 보유 회사: {company_count}")
        log.info(f"메트릭 추출 성공 문서: {docs_with_metrics} / {len(rows)}")

        # 핵심 메트릭 커버리지
        log.info("─" * 60)
        log.info("핵심 메트릭 커버리지:")
        for mn in ["revenue", "operating_profit", "net_income", "total_assets", "total_liabilities", "equity"]:
            cnt = db.query(FinancialFact).filter(FinancialFact.metric_name == mn).count()
            comp = db.query(FinancialFact.company_name_norm).filter(FinancialFact.metric_name == mn).distinct().count()
            log.info(f"  {mn:25s} {cnt:6d}건 / {comp:4d}사")

        # 검증: 핵심 회사 facts
        log.info("─" * 60)
        log.info("검증 회사 facts:")
        for c in ["삼성전자", "NAVER", "LG에너지솔루션", "현대자동차", "무림PP"]:
            facts = db.query(FinancialFact).filter(FinancialFact.company_name_norm == c).all()
            log.info(f"  {c:18s} {len(facts):4d}건")
            for f in facts[:3]:
                log.info(f"      {f.metric_name:20s} {f.metric_value_num:>20,.0f} fy={f.fiscal_year}")

    finally:
        db.close()
    log.info("완료")


if __name__ == "__main__":
    main()
