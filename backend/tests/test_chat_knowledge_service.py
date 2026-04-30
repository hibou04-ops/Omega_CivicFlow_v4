"""
Chat knowledge service unit checks.
"""

from services.chat_knowledge_service import (
    _extract_metric_value_from_line,
    canonical_metric_name,
    extract_limit_from_query,
    extract_trend_span,
    infer_period_type,
    infer_statement_scope,
    _parse_amount_phrase,
)


def test_metric_alias_resolution():
    assert canonical_metric_name("실적") == "operating_profit"
    assert canonical_metric_name("매출") == "revenue"
    assert canonical_metric_name("자기주식") == "treasury_stock_amount"


def test_query_defaults():
    assert extract_limit_from_query("영업이익 기준 상위 3개") == 3
    assert extract_limit_from_query("작년 실적 좋은 기업 top10") == 10
    assert extract_trend_span("최근 3년 매출 추세") == 3


def test_period_and_scope_inference():
    assert infer_period_type("사업보고서", "", raw={}, pages=[]) == "annual"
    assert infer_period_type("반기보고서", "", raw={}, pages=[]) == "semiannual"
    assert infer_period_type("주요사항보고서", "", raw={}, pages=[]) == "event"
    assert infer_statement_scope(raw={"summary": "연결재무제표 기준"}, pages=[]) == "consolidated"
    assert infer_statement_scope(raw={"summary": "별도재무제표 기준"}, pages=[]) == "separate"


def test_amount_phrase_parsing():
    assert _parse_amount_phrase("영업이익 210억원")[0] == 210 * 100_000_000
    assert _parse_amount_phrase("부채비율 120.5%")[0] == 120.5


def test_metric_value_extraction_prefers_keyword_adjacent_amount():
    summary_line = (
        "2025년 사업연도 동안 삼성전자는 매출액 71,839억원으로 전기 대비 10.2% 증가하였으며, "
        "영업이익은 28,540억원으로 38.6% 증가하였다."
    )
    assert _extract_metric_value_from_line("revenue", summary_line) == (71_839 * 100_000_000, "KRW", "KRW")
    assert _extract_metric_value_from_line("operating_profit", summary_line) == (28_540 * 100_000_000, "KRW", "KRW")
    assert _extract_metric_value_from_line("revenue", "매출액: 6조 1,809억원") == (6_180_900_000_000, "KRW", "KRW")
