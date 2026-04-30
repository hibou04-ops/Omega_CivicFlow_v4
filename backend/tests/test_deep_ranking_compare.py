"""
Deep ranking_compare regression tests — quality fix evidence suite.

Covers the fix for the "SK하이닉스 vs 네이버" shallow-output bug (2026-04-10):
- Period priority dedupe: annual > semiannual > quarterly > event
- Annual-only guards on margins, ratios, and YoY growth rates
- Prompt template placeholder hygiene (no literal [기업A]/[퍼센트%] leaks)
- Context builder correctly labels non-annual values with [분기]/[반기]

Before the fix, quarterly facts with higher fact.id silently overrode annual
facts during dedupe, producing nonsensical derived values such as a
매출 YoY of -89.7% (actual value was closer to +100%). These tests lock in
the fix so the regression cannot re-enter.

Run: pytest backend/tests/test_deep_ranking_compare.py -v
"""

from __future__ import annotations

from unittest.mock import patch

from services.chat_agent_safe_service import (
    _DEEP_COMPARE_SYSTEM_PROMPT,
    _REPORT_TYPE_EXCLUDED,
    _build_deep_compare_prompt,
    _compute_derived_compare_metrics,
    _fetch_metric_matrix_for_compare,
    _period_rank,
    _report_type_rank,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _cell(value: float, period: str = "annual", scope: str = "consolidated") -> dict:
    return {
        "value": float(value),
        "display": f"{value:,.0f}",
        "scope": scope,
        "period": period,
    }


class _FakeFact:
    """Minimal stand-in for FinancialFact used by matrix dedupe tests."""

    def __init__(
        self,
        company: str,
        year: int,
        metric: str,
        value: float,
        period: str,
        fact_id: int,
        unit: str = "KRW",
        currency: str = "KRW",
    ) -> None:
        self.company_name_norm = company
        self.fiscal_year = year
        self.metric_name = metric
        self.metric_value_num = value
        self.period_type = period
        self.statement_scope = "consolidated"
        self.id = fact_id
        self.unit = unit
        self.currency = currency
        self.source_text = ""
        self.metric_value_text = ""


class _FakeMetadata:
    """Minimal stand-in for DocumentMetadata."""

    def __init__(self, report_type: str = "", period_type: str = "", statement_scope: str = "consolidated") -> None:
        self.report_type = report_type
        self.period_type = period_type
        self.statement_scope = statement_scope


# ── Period priority ────────────────────────────────────────────────────

def test_period_rank_prefers_annual():
    assert _period_rank("annual") == 0
    assert _period_rank("semiannual") == 1
    assert _period_rank("quarterly") == 2
    assert _period_rank("event") == 3
    assert _period_rank("") == 4


def test_period_rank_case_insensitive():
    assert _period_rank("ANNUAL") == 0
    assert _period_rank("Quarterly") == 2
    assert _period_rank("SEMIANNUAL") == 1


# ── Derived metric guards ──────────────────────────────────────────────

def test_derived_all_annual_computes_every_metric():
    """Full annual data → margins/ratios/YoY all computed accurately."""
    matrix = {
        "revenue": {
            "sk": {
                2024: _cell(66e12),
                2023: _cell(32.7e12),
            },
        },
        "operating_profit": {
            "sk": {
                2024: _cell(23.4e12),
                2023: _cell(-7.7e12),
            },
        },
        "net_income": {"sk": {2024: _cell(18e12)}},
        "total_assets": {},
        "total_liabilities": {"sk": {2024: _cell(35e12)}},
        "equity": {"sk": {2024: _cell(80e12)}},
    }
    derived = _compute_derived_compare_metrics(matrix, ["sk"], [2023, 2024])
    row = derived["sk"]
    assert row["operating_margin"] == "35.5%"   # 23.4 / 66
    assert row["net_margin"] == "27.3%"         # 18 / 66
    assert row["debt_ratio"] == "43.8%"         # 35 / 80
    assert row["revenue_yoy"] == "+101.8%"      # (66 - 32.7) / 32.7
    assert row["op_yoy"] == "+403.9%"           # (23.4 - (-7.7)) / 7.7


def test_derived_quarterly_latest_skips_yoy_regression():
    """REGRESSION: quarterly rev 2024 vs annual rev 2023 → YoY must be SKIPPED.

    Without this guard we previously produced -89.7% YoY (from a Q1 cumulative
    vs annual comparison) which was the headline symptom of the original bug.
    """
    matrix = {
        "revenue": {
            "sk": {
                2024: _cell(3.3e12, period="quarterly"),  # Q1 cumulative
                2023: _cell(32.7e12, period="annual"),
            },
        },
        "operating_profit": {},
        "net_income": {},
        "total_assets": {},
        "total_liabilities": {},
        "equity": {},
    }
    derived = _compute_derived_compare_metrics(matrix, ["sk"], [2023, 2024])
    assert "revenue_yoy" not in derived["sk"], "quarterly/annual YoY must be skipped"


def test_derived_mixed_period_operating_margin_skipped():
    """Revenue quarterly + op annual → operating margin must be SKIPPED."""
    matrix = {
        "revenue": {"sk": {2024: _cell(3.3e12, period="quarterly")}},
        "operating_profit": {"sk": {2024: _cell(0.5e12, period="annual")}},
        "net_income": {},
        "total_assets": {},
        "total_liabilities": {},
        "equity": {},
    }
    derived = _compute_derived_compare_metrics(matrix, ["sk"], [2024])
    assert "operating_margin" not in derived["sk"]


def test_derived_both_quarterly_margin_still_skipped():
    """Both quarterly → we still require annual for margin reliability."""
    matrix = {
        "revenue": {"sk": {2024: _cell(3.3e12, period="quarterly")}},
        "operating_profit": {"sk": {2024: _cell(0.5e12, period="quarterly")}},
        "net_income": {},
        "total_assets": {},
        "total_liabilities": {},
        "equity": {},
    }
    derived = _compute_derived_compare_metrics(matrix, ["sk"], [2024])
    assert "operating_margin" not in derived["sk"]


def test_derived_debt_ratio_requires_both_annual():
    """Annual equity + quarterly liabilities → debt ratio must be SKIPPED."""
    matrix = {
        "revenue": {},
        "operating_profit": {},
        "net_income": {},
        "total_assets": {},
        "total_liabilities": {"sk": {2024: _cell(35e12, period="quarterly")}},
        "equity": {"sk": {2024: _cell(80e12, period="annual")}},
    }
    derived = _compute_derived_compare_metrics(matrix, ["sk"], [2024])
    assert "debt_ratio" not in derived["sk"]


def test_derived_empty_years_returns_empty_rows():
    derived = _compute_derived_compare_metrics({}, ["sk", "naver"], [])
    assert derived == {"sk": {}, "naver": {}}


def test_derived_multi_company_independent():
    """Company A quarterly + Company B annual should not cross-contaminate."""
    matrix = {
        "revenue": {
            "a": {2024: _cell(10e12, period="quarterly"), 2023: _cell(40e12, period="annual")},
            "b": {2024: _cell(50e12, period="annual"), 2023: _cell(45e12, period="annual")},
        },
        "operating_profit": {
            "a": {2024: _cell(2e12, period="quarterly")},
            "b": {2024: _cell(8e12, period="annual")},
        },
        "net_income": {},
        "total_assets": {},
        "total_liabilities": {},
        "equity": {},
    }
    derived = _compute_derived_compare_metrics(matrix, ["a", "b"], [2023, 2024])
    # A has quarterly latest → margins and YoY all skipped
    assert "operating_margin" not in derived["a"]
    assert "revenue_yoy" not in derived["a"]
    # B has full annual → computed
    assert derived["b"]["operating_margin"] == "16.0%"   # 8 / 50
    assert derived["b"]["revenue_yoy"] == "+11.1%"       # (50 - 45) / 45


# ── Matrix dedupe: annual beats quarterly via period priority ──────────

def test_matrix_dedupe_prefers_annual_over_quarterly():
    """REGRESSION: quarterly with higher fact.id must NOT override annual with lower id.

    This was the core bug: _facts_for_metric sorts by (fiscal_year DESC, id DESC),
    so a more-recently-inserted quarterly fact would win the dedupe. The fix adds
    period_type as a sort key between year and id.
    """
    def _fake_facts(_db, metric, _companies, _years, user_id=None):
        if metric == "revenue":
            return [
                # quarterly id=999 (inserted later)
                (_FakeFact("sk", 2024, "revenue", 46e12, "quarterly", fact_id=999), None, None),
                # annual id=100 (inserted earlier)
                (_FakeFact("sk", 2024, "revenue", 66e12, "annual", fact_id=100), None, None),
            ]
        return []

    with patch(
        "services.chat_agent_safe_service._kb_facts_for_metric",
        side_effect=_fake_facts,
    ):
        matrix = _fetch_metric_matrix_for_compare(
            db=None,
            companies=["sk"],
            years=[2024],
            user_id=1,
        )

    cell = matrix["revenue"]["sk"][2024]
    assert cell["value"] == 66e12, f"expected annual 66조, got {cell['value']}"
    assert cell["period"] == "annual"


def test_matrix_dedupe_prefers_semiannual_over_quarterly():
    def _fake_facts(_db, metric, *_args, **_kwargs):
        if metric == "revenue":
            return [
                (_FakeFact("sk", 2024, "revenue", 15e12, "quarterly", fact_id=999), None, None),
                (_FakeFact("sk", 2024, "revenue", 30e12, "semiannual", fact_id=500), None, None),
            ]
        return []

    with patch(
        "services.chat_agent_safe_service._kb_facts_for_metric",
        side_effect=_fake_facts,
    ):
        matrix = _fetch_metric_matrix_for_compare(None, ["sk"], [2024], 1)

    assert matrix["revenue"]["sk"][2024]["value"] == 30e12
    assert matrix["revenue"]["sk"][2024]["period"] == "semiannual"


def test_matrix_dedupe_falls_back_to_quarterly_when_annual_missing():
    """When only quarterly exists, it is still returned (with period label)."""
    def _fake_facts(_db, metric, *_args, **_kwargs):
        if metric == "revenue":
            return [
                (_FakeFact("sk", 2024, "revenue", 46e12, "quarterly", fact_id=999), None, None),
            ]
        return []

    with patch(
        "services.chat_agent_safe_service._kb_facts_for_metric",
        side_effect=_fake_facts,
    ):
        matrix = _fetch_metric_matrix_for_compare(None, ["sk"], [2024], 1)

    cell = matrix["revenue"]["sk"][2024]
    assert cell["value"] == 46e12
    assert cell["period"] == "quarterly"


# ── Report type filter (2026-04 data quality fix) ──────────────────────

def test_report_type_rank_prefers_annual_reports():
    """사업보고서 and 감사보고서 should rank highest (0)."""
    assert _report_type_rank("사업보고서") == 0
    assert _report_type_rank("감사보고서") == 0
    assert _report_type_rank("반기보고서") == 1
    assert _report_type_rank("분기보고서") == 2
    assert _report_type_rank("") == 5
    assert _report_type_rank("unknown") == 5


def test_report_type_excluded_set_includes_event_report():
    """주요사항보고서 must be excluded — contains event-specific numbers,
    not recurring financials."""
    assert "주요사항보고서" in _REPORT_TYPE_EXCLUDED


def test_matrix_excludes_juyo_sahang_entirely():
    """REGRESSION: 주요사항보고서 영업양수결정 facts contaminated the matrix
    with transaction amounts (4.79조) masquerading as 2025 SK하이닉스 revenue.

    After the fix, ALL facts sourced from 주요사항보고서 must be dropped even
    if they are the only available data — we'd rather return "자료 없음" than
    pollute the comparison with unrelated transaction amounts.
    """
    bad_meta = _FakeMetadata(report_type="주요사항보고서", period_type="annual")

    def _fake_facts(_db, metric, *_args, **_kwargs):
        if metric == "revenue":
            return [
                (_FakeFact("sk", 2025, "revenue", 4.79e12, "annual", fact_id=9999), None, bad_meta),
            ]
        return []

    with patch(
        "services.chat_agent_safe_service._kb_facts_for_metric",
        side_effect=_fake_facts,
    ):
        matrix = _fetch_metric_matrix_for_compare(None, ["sk"], [2025], 1)

    assert "sk" not in matrix["revenue"], (
        "fact from 주요사항보고서 must be dropped even when it is the only one"
    )


def test_matrix_prefers_사업보고서_over_분기보고서():
    """REGRESSION: 분기보고서 facts (correct partial-period values) must not
    outrank 사업보고서 facts even when the 분기 fact has a higher fact.id.

    Before the fix, the dedupe used (period, -id) priority. Because
    fact.period_type was wrongly set to 'annual' on quarterly reports, both
    facts looked equivalent and the higher id (분기보고서) won.
    """
    sabeop_meta = _FakeMetadata(report_type="사업보고서", period_type="annual")
    bungi_meta = _FakeMetadata(report_type="분기보고서", period_type="quarterly")

    def _fake_facts(_db, metric, *_args, **_kwargs):
        if metric == "revenue":
            return [
                # 분기보고서 Q3 cumulative, higher id (more recent upload)
                (_FakeFact("sk", 2025, "revenue", 64e12, "annual", fact_id=8000), None, bungi_meta),
                # 사업보고서 annual, lower id (older upload)
                (_FakeFact("sk", 2025, "revenue", 97e12, "annual", fact_id=100), None, sabeop_meta),
            ]
        return []

    with patch(
        "services.chat_agent_safe_service._kb_facts_for_metric",
        side_effect=_fake_facts,
    ):
        matrix = _fetch_metric_matrix_for_compare(None, ["sk"], [2025], 1)

    cell = matrix["revenue"]["sk"][2025]
    assert cell["value"] == 97e12, (
        f"사업보고서 should outrank 분기보고서, got {cell['value']}"
    )
    assert cell["report_type"] == "사업보고서"
    assert cell["period"] == "annual"


def test_matrix_metadata_period_overrides_wrong_fact_period():
    """REGRESSION: fact.period_type is unreliable (sometimes 'annual' on
    quarterly data). _resolve_period must prefer metadata.period_type.
    """
    bungi_meta = _FakeMetadata(report_type="분기보고서", period_type="quarterly")

    def _fake_facts(_db, metric, *_args, **_kwargs):
        if metric == "revenue":
            return [
                # fact says annual, metadata says quarterly → trust metadata
                (_FakeFact("sk", 2025, "revenue", 15e12, "annual", fact_id=9000), None, bungi_meta),
            ]
        return []

    with patch(
        "services.chat_agent_safe_service._kb_facts_for_metric",
        side_effect=_fake_facts,
    ):
        matrix = _fetch_metric_matrix_for_compare(None, ["sk"], [2025], 1)

    cell = matrix["revenue"]["sk"][2025]
    assert cell["period"] == "quarterly", (
        f"metadata.period_type must override fact.period_type, got {cell['period']}"
    )


def test_matrix_falls_back_to_banki_when_no_사업보고서():
    """When only 반기보고서 and 분기보고서 exist, 반기 should win (rank 1 < 2)."""
    banki_meta = _FakeMetadata(report_type="반기보고서", period_type="semiannual")
    bungi_meta = _FakeMetadata(report_type="분기보고서", period_type="quarterly")

    def _fake_facts(_db, metric, *_args, **_kwargs):
        if metric == "revenue":
            return [
                (_FakeFact("sk", 2025, "revenue", 30e12, "semiannual", fact_id=7000), None, banki_meta),
                (_FakeFact("sk", 2025, "revenue", 50e12, "quarterly", fact_id=9000), None, bungi_meta),
            ]
        return []

    with patch(
        "services.chat_agent_safe_service._kb_facts_for_metric",
        side_effect=_fake_facts,
    ):
        matrix = _fetch_metric_matrix_for_compare(None, ["sk"], [2025], 1)

    cell = matrix["revenue"]["sk"][2025]
    assert cell["report_type"] == "반기보고서"
    assert cell["period"] == "semiannual"


# ── Prompt template hygiene ─────────────────────────────────────────────

def test_prompt_template_has_no_literal_placeholder_leaks():
    """LLM echoes literal placeholders verbatim — they must not appear in the template."""
    banned_tokens = [
        "[기업A]",
        "[기업B]",
        "[동일]",
        "[퍼센트%]",
        "[한 문장",
    ]
    for token in banned_tokens:
        assert token not in _DEEP_COMPARE_SYSTEM_PROMPT, (
            f"Literal placeholder '{token}' leaked into prompt template"
        )


def test_prompt_template_has_required_sections():
    required = [
        "결론",
        "산업 맥락",
        "핵심 비교 지표",
        "실적 드라이버",
        "핵심 리스크",
        "판단 축별 우위",
        "해석 주의",
        "확신도",
    ]
    for section in required:
        assert section in _DEEP_COMPARE_SYSTEM_PROMPT, (
            f"Required section missing: {section}"
        )


def test_prompt_template_explicitly_bans_bracketed_company_names():
    """Rule 7 tells the LLM not to wrap company names in brackets."""
    assert "대괄호" in _DEEP_COMPARE_SYSTEM_PROMPT
    assert "SK하이닉스" in _DEEP_COMPARE_SYSTEM_PROMPT  # used as positive example


def test_prompt_template_explicitly_bans_fake_yoy_calculation():
    """Rule 3 tells the LLM not to invent YoY values when DERIVED METRICS is empty."""
    assert "기간 불일치" in _DEEP_COMPARE_SYSTEM_PROMPT
    assert "자료 없음" in _DEEP_COMPARE_SYSTEM_PROMPT


# ── Context builder: period labels are visible in the prompt ───────────

def test_build_prompt_marks_quarterly_values_with_label():
    matrix = {
        "revenue": {
            "sk": {
                2024: _cell(66e12, period="annual"),
                2025: _cell(15e12, period="quarterly"),
            },
        },
        "operating_profit": {},
        "net_income": {},
        "total_assets": {},
        "total_liabilities": {},
        "equity": {},
    }
    derived = _compute_derived_compare_metrics(matrix, ["sk"], [2024, 2025])
    qual = {"sk": {"business": [], "risk": []}}
    prompt = _build_deep_compare_prompt(
        user_message="매출 비교",
        primary_metric_label="매출",
        company_display_map={"sk": "SK하이닉스"},
        companies=["sk"],
        years=[2024, 2025],
        matrix=matrix,
        derived=derived,
        qual=qual,
    )
    # [분기] label must decorate the 2025 quarterly value
    assert "[분기]" in prompt, "quarterly label missing from prompt"
    # Locate the SK revenue line and verify per-year labeling
    revenue_section_start = prompt.index("[매출]")
    revenue_section = prompt[revenue_section_start : revenue_section_start + 400]
    assert "2025년" in revenue_section
    assert "2024년" in revenue_section
    # 2025 part should have [분기], 2024 part should not
    parts = revenue_section.split("/")
    part_2024 = next((p for p in parts if "2024년" in p), "")
    part_2025 = next((p for p in parts if "2025년" in p), "")
    assert "[분기]" in part_2025
    assert "[분기]" not in part_2024


def test_build_prompt_shows_missing_metric_as_unavailable():
    matrix = {
        "revenue": {"sk": {2024: _cell(66e12)}},
        "operating_profit": {},
        "net_income": {},
        "total_assets": {},
        "total_liabilities": {},
        "equity": {},
    }
    derived = _compute_derived_compare_metrics(matrix, ["sk", "naver"], [2024])
    qual = {"sk": {"business": [], "risk": []}, "naver": {"business": [], "risk": []}}
    prompt = _build_deep_compare_prompt(
        user_message="비교",
        primary_metric_label="매출",
        company_display_map={"sk": "SK하이닉스", "naver": "NAVER"},
        companies=["sk", "naver"],
        years=[2024],
        matrix=matrix,
        derived=derived,
        qual=qual,
    )
    # naver has no revenue → "자료 없음"
    assert "자료 없음" in prompt
