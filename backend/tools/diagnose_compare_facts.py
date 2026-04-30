# -*- coding: utf-8 -*-
"""
Diagnose whether the FinancialFact table has the multi-metric · annual data
required for the deep_ranking_compare path to produce a meaningful answer.

Problem context (2026-04-10):
    "SK하이닉스 vs 네이버" returned a shallow template answer. After wiring
    up _deep_ranking_compare, the first LLM run still produced a wrong
    매출 YoY of -89.7% because quarterly facts were overriding annual facts.
    The dedupe bug is fixed in code, but the fix only helps if annual facts
    actually exist for every (company, metric, year). This script answers
    exactly that question.

What it prints:
    1. For each target company, the full (metric, year, period_type) matrix
       that would be fed to _fetch_metric_matrix_for_compare.
    2. A quality verdict per (company, metric, year): OK / QUARTERLY-ONLY /
       MISSING, and an overall grade per company.
    3. A suggestion for backfill if critical gaps exist.

Usage:
    python backend/tools/diagnose_compare_facts.py
    python backend/tools/diagnose_compare_facts.py --companies skhynix naver samsung
    python backend/tools/diagnose_compare_facts.py --years 2023 2024 2025
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

# Force UTF-8 stdout on Windows (cp949 default can't print Korean / box-drawing)
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import SessionLocal  # noqa: E402
from models.models import Document, DocumentMetadata, FinancialFact  # noqa: E402
from services.chat_knowledge_service import (  # noqa: E402
    METRICS,
    SUMMARY_METRICS,
    _metric_label,
    normalize_company_name_for_storage,
)

# Metrics we care about for ranking_compare quality
CORE_METRICS = SUMMARY_METRICS  # revenue, operating_profit, net_income, total_assets, total_liabilities, equity


def _period_label(period: str) -> str:
    return {
        "annual": "연간",
        "semiannual": "반기",
        "quarterly": "분기",
        "event": "이벤트",
    }.get((period or "").lower(), period or "미분류")


def _verdict(facts_by_year: dict, year: int) -> tuple[str, str]:
    """Return (status, note) for a single (metric, year) cell."""
    facts = facts_by_year.get(year) or []
    if not facts:
        return "MISSING", "없음"
    # Prefer annual
    annuals = [f for f in facts if (f["period"] or "").lower() == "annual"]
    if annuals:
        return "OK", f"annual×{len(annuals)}"
    periods = ",".join(sorted({(f["period"] or "?") for f in facts}))
    return "NON_ANNUAL", f"only {periods}"


def run(companies: list[str], years: list[int]) -> int:
    companies_norm = [normalize_company_name_for_storage(c) for c in companies]
    print("=" * 72)
    print("DEEP_RANKING_COMPARE FACTS DIAGNOSIS")
    print("=" * 72)
    print(f"Target companies : {companies_norm}")
    print(f"Target years     : {years}")
    print(f"Core metrics     : {CORE_METRICS}")
    print()

    db = SessionLocal()
    try:
        grade_card: dict[str, dict[str, int]] = defaultdict(lambda: {"OK": 0, "NON_ANNUAL": 0, "MISSING": 0})
        missing_detail: list[str] = []

        # Fetch matching facts once, bucket by (company, metric)
        rows = (
            db.query(FinancialFact, Document, DocumentMetadata)
            .join(Document, Document.id == FinancialFact.document_id)
            .outerjoin(DocumentMetadata, DocumentMetadata.document_id == FinancialFact.document_id)
            .filter(FinancialFact.company_name_norm.in_(companies_norm))
            .filter(FinancialFact.metric_name.in_(CORE_METRICS))
            .filter(FinancialFact.fiscal_year.in_(years))
            .all()
        )

        bucket: dict[tuple[str, str], dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for fact, _doc, meta in rows:
            comp = fact.company_name_norm or ""
            metric = fact.metric_name or ""
            year = fact.fiscal_year or 0
            if not comp or not metric or not year:
                continue
            bucket[(comp, metric)][year].append({
                "value": fact.metric_value_num,
                "period": fact.period_type or (meta.period_type if meta else "") or "",
                "scope": fact.statement_scope or (meta.statement_scope if meta else "") or "",
                "id": fact.id,
            })

        for company in companies_norm:
            print("-" * 72)
            print(f"[{company}]")
            print("-" * 72)
            header = f"{'지표':<18} " + " ".join(f"{y:>7}" for y in years)
            print(header)
            for metric in CORE_METRICS:
                facts_by_year = bucket.get((company, metric), {})
                row_cells: list[str] = []
                for year in years:
                    status, _note = _verdict(facts_by_year, year)
                    grade_card[company][status] += 1
                    symbol = {"OK": " [OK] ", "NON_ANNUAL": " [NA] ", "MISSING": " [--] "}[status]
                    row_cells.append(f"{symbol:>7}")
                    if status == "MISSING":
                        missing_detail.append(f"{company}.{metric}.{year}")
                    elif status == "NON_ANNUAL":
                        missing_detail.append(
                            f"{company}.{metric}.{year} (non-annual: {facts_by_year[year][0]['period']})"
                        )
                print(f"{_metric_label(metric):<18} " + " ".join(row_cells))

            # Value-spread audit: for the latest year of each metric, show
            # all fact values + periods + scopes + ids. This is the key audit
            # that explains WHY the dedupe picks a particular value.
            print("    -- Value spread (latest year) --")
            for metric in CORE_METRICS:
                years_dict = bucket.get((company, metric), {})
                if not years_dict:
                    continue
                latest = max(years_dict.keys())
                facts = years_dict[latest]
                # Sort the same way as the production dedupe to show
                # which fact would win
                priority = {"annual": 0, "semiannual": 1, "quarterly": 2, "event": 3}
                facts_sorted = sorted(
                    facts,
                    key=lambda f: (priority.get((f["period"] or "").lower(), 4), -(f["id"] or 0)),
                )
                winner = facts_sorted[0]
                line = f"    {_metric_label(metric)} {latest}:"
                for i, f in enumerate(facts_sorted[:6]):
                    val = f["value"]
                    if val is None:
                        val_str = "None"
                    elif abs(val) >= 1e12:
                        val_str = f"{val / 1e12:.2f}조"
                    elif abs(val) >= 1e8:
                        val_str = f"{val / 1e8:.0f}억"
                    else:
                        val_str = f"{val:,.0f}"
                    prefix = " *" if i == 0 else "  "
                    line += f"\n     {prefix} id={f['id']} period={f['period'] or '?'} scope={f['scope'] or '?'} val={val_str}"
                # Check value-spread: if top2 differ by >5%, flag it
                if len(facts_sorted) >= 2:
                    v1 = facts_sorted[0]["value"] or 0
                    v2 = facts_sorted[1]["value"] or 0
                    if v1 and v2 and abs(v1 - v2) / max(abs(v1), abs(v2)) > 0.05:
                        line += f"\n        !! VALUE SPREAD: top2 differ > 5% ({v1:,.0f} vs {v2:,.0f})"
                print(line)
            print()

        # Grade card
        print("=" * 72)
        print("GRADE CARD")
        print("=" * 72)
        for company, counts in grade_card.items():
            total = sum(counts.values())
            if total == 0:
                grade = "F (no data)"
            else:
                ok_ratio = counts["OK"] / total
                if ok_ratio >= 0.9:
                    grade = "A (excellent)"
                elif ok_ratio >= 0.75:
                    grade = "B (good)"
                elif ok_ratio >= 0.5:
                    grade = "C (partial)"
                elif ok_ratio >= 0.25:
                    grade = "D (weak)"
                else:
                    grade = "F (insufficient)"
            print(
                f"  {company:<20} OK={counts['OK']:>3} "
                f"NON_ANNUAL={counts['NON_ANNUAL']:>3} MISSING={counts['MISSING']:>3} "
                f"→ {grade}"
            )

        print()
        if missing_detail:
            print("=" * 72)
            print(f"GAPS TO BACKFILL ({len(missing_detail)} cells)")
            print("=" * 72)
            for item in missing_detail[:30]:
                print(f"  - {item}")
            if len(missing_detail) > 30:
                print(f"  ... +{len(missing_detail) - 30} more")
        else:
            print("No gaps detected — deep_compare should produce full output.")

        # Return non-zero if any MISSING to let CI/scripts fail loudly
        return 0 if not any(counts["MISSING"] for counts in grade_card.values()) else 2

    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--companies",
        nargs="+",
        default=["skhynix", "naver"],
        help="Company names (display or alias). Will be normalized. Default: skhynix naver",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=[2023, 2024, 2025],
        help="Fiscal years to check. Default: 2023 2024 2025",
    )
    args = parser.parse_args()
    return run(args.companies, args.years)


if __name__ == "__main__":
    sys.exit(main())
