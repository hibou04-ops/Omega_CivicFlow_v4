"""
Safe chat retrieval and routing regression checks.
"""

import sys
from datetime import datetime

from services.chat_agent_safe_service import _build_query_variables
from services.chat_knowledge_service import (
    ROUTE_COMPANY_SUMMARY,
    ROUTE_QA,
    ROUTE_RANKING_COMPARE,
    ROUTE_TREND,
    classify_chat_route,
)
from services.cognitive_search_safe import _extract_years_from_filename, _score_metadata_hints


def test_query_variable_decomposition():
    query = "최근 2년 삼성전자와 SK하이닉스 CAPEX 비교"
    variables = _build_query_variables(query)
    current_year = datetime.now().year

    assert set(variables["companies"]) == {"삼성전자", "SK하이닉스"}
    assert variables["prefer_recent"] is True
    assert variables["year_filters"] == [str(current_year - 1), str(current_year)]
    assert "삼성전자" not in variables["focus_query"]
    assert "SK하이닉스" not in variables["focus_query"]


def test_chat_route_classification_examples():
    cases = {
        "작년 실적 좋은 기업 top10": ROUTE_RANKING_COMPARE,
        "영업이익 기준 상위 3개": ROUTE_RANKING_COMPARE,
        "최근 3년 매출 추세": ROUTE_TREND,
        "뉴온 작년 실적 요약": ROUTE_COMPANY_SUMMARY,
        "남양유업 자기주식 규모": ROUTE_QA,
    }

    for query, expected in cases.items():
        variables = _build_query_variables(query)
        assert classify_chat_route(query, variables) == expected
        assert variables["route"] == expected


def test_query_variable_filters_company_stopwords():
    ranking_variables = _build_query_variables("영업이익 기준 상위 3개")
    qa_variables = _build_query_variables("남양유업 자기주식 규모")

    assert ranking_variables["companies"] == []
    assert ranking_variables["company"] == ""
    assert qa_variables["companies"] == ["남양유업"]


def test_filename_year_extraction():
    filename = "06a24081_DART_P2_삼성전자_20250515001922.zip.pdf"
    assert _extract_years_from_filename(filename) == ["2025"]


def test_metadata_hint_scoring():
    meta = {
        "company": "삼성전자",
        "category": "사업보고서",
        "filename": "06a24081_DART_P2_삼성전자_20250515001922.zip.pdf",
        "source": "llm",
    }
    score = _score_metadata_hints(
        meta,
        query_tokens=["capex", "투자"],
        company_filter="삼성전자",
        category_filter="사업보고서",
        year_filters=["2025"],
        prefer_recent=False,
    )
    assert score >= 0.9


if __name__ == "__main__":
    failures = 0
    for test_fn in (
        test_query_variable_decomposition,
        test_chat_route_classification_examples,
        test_query_variable_filters_company_stopwords,
        test_filename_year_extraction,
        test_metadata_hint_scoring,
    ):
        try:
            test_fn()
            print(f"[PASS] {test_fn.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"[FAIL] {test_fn.__name__}: {exc}")

    if failures:
        sys.exit(1)
    print("All tests passed!")
