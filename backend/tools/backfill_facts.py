"""
FinancialFact Backfill — analysis_results.financial_metrics 텍스트 파싱
GPU/LLM 불필요. 순수 문자열 파싱 + DB INSERT.
"""
import sys, re, json, hashlib, logging
sys.path.insert(0, '.')

from database import SessionLocal
from models.models import AnalysisResult, DocumentMetadata, FinancialFact
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

# ── 메트릭명 정규화 맵 ──
METRIC_MAP = {
    "매출액": "revenue",
    "매출": "revenue",
    "영업이익": "operating_profit",
    "영업손실": "operating_profit",
    "당기순이익": "net_income",
    "당기순손실": "net_income",
    "순이익": "net_income",
    "순손실": "net_income",
    "자산총계": "total_assets",
    "총자산": "total_assets",
    "부채총계": "total_liabilities",
    "총부채": "total_liabilities",
    "자본총계": "equity",
    "총자본": "equity",
    "배당금": "dividend_amount",
    "배당": "dividend_amount",
    "부채비율": "debt_ratio",
    "영업이익률": "operating_margin",
}

def parse_value(val_str: str) -> float | None:
    """'2,465,365,135원' → 2465365135.0, '24.7억원' → 2470000000.0"""
    if not val_str:
        return None
    val_str = val_str.strip().replace(",", "").replace(" ", "")
    # 단위 변환
    multiplier = 1.0
    if "조" in val_str:
        val_str = val_str.replace("조", "").replace("원", "").strip()
        multiplier = 1e12
    elif "억" in val_str:
        val_str = val_str.replace("억", "").replace("원", "").strip()
        multiplier = 1e8
    elif "만" in val_str:
        val_str = val_str.replace("만", "").replace("원", "").strip()
        multiplier = 1e4
    elif "천" in val_str:
        val_str = val_str.replace("천", "").replace("원", "").strip()
        multiplier = 1e3
    else:
        val_str = val_str.replace("원", "").replace("%", "").strip()
    
    # 음수 처리
    negative = False
    if val_str.startswith("-") or val_str.startswith("△") or val_str.startswith("▲"):
        negative = True
        val_str = val_str.lstrip("-△▲ ")
    
    try:
        num = float(val_str) * multiplier
        return -num if negative else num
    except ValueError:
        return None


def make_fact_uid(doc_id, company, fy, metric, scope):
    raw = f"{doc_id}|{company}|{fy}|{metric}|{scope or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def parse_financial_metrics(text: str) -> list[dict]:
    """'매출액: 2,465,365,135원 | 자산총계: 9,454,690,182원' → [{metric, value}, ...]"""
    if not text or not text.strip():
        return []
    
    results = []
    # Split by |, then parse key: value
    parts = re.split(r'\s*\|\s*', text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # "매출액: 2,465원" or "매출액 2,465원"
        match = re.match(r'([가-힣A-Za-z]+)\s*[:：]?\s*(.+)', part)
        if not match:
            continue
        label = match.group(1).strip()
        value_str = match.group(2).strip()
        
        metric_name = METRIC_MAP.get(label)
        if not metric_name:
            continue
        
        value = parse_value(value_str)
        if value is None or value == 0:
            continue
        
        results.append({"metric_name": metric_name, "value": value})
    
    return results


def main():
    db = SessionLocal()
    
    # 기존 fact_uid 로드 (중복 방지)
    existing_uids = set(
        uid for (uid,) in db.query(FinancialFact.fact_uid).all()
    )
    log.info(f"기존 팩트: {len(existing_uids)}건")
    
    # financial_metrics가 비어있지 않은 analysis_results 조회
    rows = db.execute(text("""
        SELECT ar.document_id, ar.financial_metrics,
               dm.company_name, dm.company_name_norm, dm.fiscal_year,
               dm.statement_scope, dm.corp_code
        FROM analysis_results ar
        JOIN document_metadata dm ON dm.document_id = ar.document_id
        WHERE ar.financial_metrics IS NOT NULL 
          AND ar.financial_metrics != ''
          AND LENGTH(ar.financial_metrics) > 5
    """)).fetchall()
    
    log.info(f"파싱 대상: {len(rows)}건")
    
    new_facts = []
    skipped = 0
    errors = 0
    
    for doc_id, fm_text, company, company_norm, fy, scope, corp_code in rows:
        if not company_norm or not fy:
            skipped += 1
            continue
        
        metrics = parse_financial_metrics(fm_text)
        for m in metrics:
            uid = make_fact_uid(doc_id, company_norm, fy, m["metric_name"], scope)
            if uid in existing_uids:
                skipped += 1
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
                statement_scope=scope,
                period_type="annual",
                confidence=0.85,
                extraction_method="backfill_from_summary",
            )
            new_facts.append(fact)
            existing_uids.add(uid)
    
    # Bulk insert
    if new_facts:
        db.bulk_save_objects(new_facts)
        db.commit()
    
    # 최종 통계
    total_after = db.query(FinancialFact).count()
    log.info(f"신규 삽입: {len(new_facts)}건 | 스킵(중복/누락): {skipped} | 에러: {errors}")
    log.info(f"총 팩트: {total_after}건")
    
    # 회사별 커버리지
    from sqlalchemy import func
    companies = db.query(FinancialFact.company_name_norm).distinct().count()
    rev_count = db.query(FinancialFact).filter(FinancialFact.metric_name == "revenue").count()
    op_count = db.query(FinancialFact).filter(FinancialFact.metric_name == "operating_profit").count()
    log.info(f"회사 수: {companies} | revenue: {rev_count}건 | operating_profit: {op_count}건")
    
    db.close()
    log.info("완료")


if __name__ == "__main__":
    main()
