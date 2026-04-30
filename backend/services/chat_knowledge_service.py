from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.models import AnalysisResult, CompanyProfile, Document, DocumentChunk, DocumentMetadata, FinancialFact, OcrText
from services.company_alias_master import COMPANY_ALIASES as MASTER_COMPANY_ALIASES, normalize_company_name
from services.vector_service import CHAT_CHUNK_COLLECTION_NAME, vector_service

logger = logging.getLogger(__name__)

ROUTE_QA = "qa"
ROUTE_COMPANY_SUMMARY = "company_summary"
ROUTE_RANKING_COMPARE = "ranking_compare"
ROUTE_TREND = "trend"

TXT_NO_DATA = "\uc790\ub8cc \ubd80\uc871"
TXT_CONCLUSION = "**\uacb0\ub860**"
TXT_EVIDENCE = "**\uadfc\uac70**"
TXT_RISK = "**\ub9ac\uc2a4\ud06c**"
TXT_CONFIDENCE = "**\ud655\uc2e0\ub3c4**"

K_RECENT = "\ucd5c\uadfc"
K_TREND = "\ucd94\uc138"
K_FLOW = "\ud750\ub984"
K_COMPARE = "\ube44\uad50"
K_TOP = "\uc0c1\uc704"
K_RANK = "\uc21c\uc704"
K_SUMMARY = "\uc694\uc57d"
K_SORT = "\uc815\ub9ac"
K_FINANCE = "\uc7ac\ubb34"
K_RESULT = "\uc2e4\uc801"
K_ANNUAL = "\uc0ac\uc5c5\ubcf4\uace0\uc11c"
K_HALF = "\ubc18\uae30\ubcf4\uace0\uc11c"
K_QUARTER = "\ubd84\uae30\ubcf4\uace0\uc11c"
K_AUDIT = "\uac10\uc0ac\ubcf4\uace0\uc11c"
K_MAJOR = "\uc8fc\uc694\uc0ac\ud56d\ubcf4\uace0\uc11c"
K_CONSOL = "\uc5f0\uacb0\uc7ac\ubb34\uc81c\ud45c"
K_SEP = "\ubcc4\ub3c4\uc7ac\ubb34\uc81c\ud45c"

METRICS: dict[str, dict[str, Any]] = {
    "revenue": {"label": "\ub9e4\ucd9c", "keywords": ["\ub9e4\ucd9c\uc561", "\ub9e4\ucd9c"], "unit": "KRW"},
    "operating_profit": {"label": "\uc601\uc5c5\uc774\uc775", "keywords": ["\uc601\uc5c5\uc774\uc775", "\uc601\uc5c5\uc775", K_RESULT], "unit": "KRW"},
    "net_income": {"label": "\uc21c\uc774\uc775", "keywords": ["\ub2f9\uae30\uc21c\uc774\uc775", "\uc21c\uc774\uc775", "\uc21c\uc775"], "unit": "KRW"},
    "total_assets": {"label": "\ucd1d\uc790\uc0b0", "keywords": ["\uc790\uc0b0\ucd1d\uacc4", "\ucd1d\uc790\uc0b0", "\uc790\uc0b0"], "unit": "KRW"},
    "total_liabilities": {"label": "\ucd1d\ubd80\ucc44", "keywords": ["\ubd80\ucc44\ucd1d\uacc4", "\ucd1d\ubd80\ucc44", "\ubd80\ucc44"], "unit": "KRW"},
    "equity": {"label": "\uc790\ubcf8", "keywords": ["\uc790\ubcf8\ucd1d\uacc4", "\ucd1d\uc790\ubcf8", "\uc790\ubcf8"], "unit": "KRW"},
    "operating_margin": {"label": "\uc601\uc5c5\uc774\uc775\ub960", "keywords": ["\uc601\uc5c5\uc774\uc775\ub960"], "unit": "PERCENT"},
    "debt_ratio": {"label": "\ubd80\ucc44\ube44\uc728", "keywords": ["\ubd80\ucc44\ube44\uc728"], "unit": "PERCENT"},
    "revenue_yoy": {"label": "\ub9e4\ucd9c YoY", "keywords": ["\ub9e4\ucd9c YoY", "\ub9e4\ucd9c \uc131\uc7a5\ub960", "\ub9e4\ucd9c \uc99d\uac00\uc728", "\ub9e4\ucd9c \uc0c1\uc2b9\ub960"], "unit": "PERCENT"},
    "op_yoy": {"label": "\uc601\uc5c5\uc774\uc775 YoY", "keywords": ["\uc601\uc5c5\uc774\uc775 YoY", "\uc601\uc5c5\uc774\uc775 \uc131\uc7a5\ub960", "\uc601\uc5c5\uc774\uc775 \uc99d\uac00\uc728", "\uc601\uc5c5\uc774\uc775 \uc0c1\uc2b9\ub960"], "unit": "PERCENT"},
    "dividend_amount": {"label": "\ubc30\ub2f9\uae08", "keywords": ["\ubc30\ub2f9\uae08\ucd1d\uc561", "\ud604\uae08\ubc30\ub2f9\ucd1d\uc561", "\ubc30\ub2f9\uae08", "\ubc30\ub2f9"], "unit": "KRW"},
    "treasury_stock_amount": {"label": "\uc790\uae30\uc8fc\uc2dd \uaddc\ubaa8", "keywords": ["\uc790\uae30\uc8fc\uc2dd", "\ucde8\ub4dd\uae08\uc561", "\ucc98\ubd84\uae08\uc561", "\uacc4\uc57d\uae08\uc561"], "unit": "KRW"},
    "capital_raise_amount": {"label": "\uc720\uc0c1\uc99d\uc790 \uaddc\ubaa8", "keywords": ["\uc720\uc0c1\uc99d\uc790", "\uc99d\uc790\uae08\uc561", "\uc870\ub2ec\uae08\uc561", "\ubaa8\uc9d1\ucd1d\uc561"], "unit": "KRW"},
    "capex": {"label": "CAPEX", "keywords": ["CAPEX", "capex", "\uc124\ube44\ud22c\uc790", "\uc720\ud615\uc790\uc0b0\ucde8\ub4dd"], "unit": "KRW"},
}

QUERY_METRIC_ALIASES = {
    K_RESULT: "operating_profit",
    "\uc601\uc5c5\uc774\uc775": "operating_profit",
    "\uc601\uc5c5\uc775": "operating_profit",
    "\uc601\uc5c5\uc774\uc775\ub960": "operating_margin",
    "\ub9e4\ucd9c": "revenue",
    "\ub9e4\ucd9c\uc561": "revenue",
    "\uc21c\uc774\uc775": "net_income",
    "\uc21c\uc775": "net_income",
    "\ub2f9\uae30\uc21c\uc774\uc775": "net_income",
    "\uc790\uc0b0": "total_assets",
    "\ucd1d\uc790\uc0b0": "total_assets",
    "\ubd80\ucc44": "total_liabilities",
    "\ucd1d\ubd80\ucc44": "total_liabilities",
    "\uc790\ubcf8": "equity",
    "\ub9e4\ucd9c\uadf8\ub8f9\uc728": "revenue_yoy",
    "\ub9e4\ucd9c \uadf8\ub8f9\uc728": "revenue_yoy",
    "\ub9e4\ucd9c\uc131\uc7a5\ub960": "revenue_yoy",
    "\ub9e4\ucd9c \uc131\uc7a5\ub960": "revenue_yoy",
    "\ub9e4\ucd9c\uc99d\uac00\uc728": "revenue_yoy",
    "\ub9e4\ucd9c \uc99d\uac00\uc728": "revenue_yoy",
    "\ub9e4\ucd9c\uc0c1\uc2b9\ub960": "revenue_yoy",
    "\ub9e4\ucd9c \uc0c1\uc2b9\ub960": "revenue_yoy",
    "\uc601\uc5c5\uc774\uc775\uadf8\ub8f9\uc728": "op_yoy",
    "\uc601\uc5c5\uc774\uc775 \uadf8\ub8f9\uc728": "op_yoy",
    "\uc601\uc5c5\uc774\uc775\uc131\uc7a5\ub960": "op_yoy",
    "\uc601\uc5c5\uc774\uc775 \uc131\uc7a5\ub960": "op_yoy",
    "\uc601\uc5c5\uc774\uc775\uc99d\uac00\uc728": "op_yoy",
    "\uc601\uc5c5\uc774\uc775 \uc99d\uac00\uc728": "op_yoy",
    "\uc601\uc5c5\uc774\uc775\uc0c1\uc2b9\ub960": "op_yoy",
    "\uc601\uc5c5\uc774\uc775 \uc0c1\uc2b9\ub960": "op_yoy",
    "\ubd80\ucc44\ube44\uc728": "debt_ratio",
    "\ubc30\ub2f9": "dividend_amount",
    "\ubc30\ub2f9\uae08": "dividend_amount",
    "\uc790\uae30\uc8fc\uc2dd": "treasury_stock_amount",
    "\uc720\uc0c1\uc99d\uc790": "capital_raise_amount",
    "\uc99d\uc790": "capital_raise_amount",
    "CAPEX": "capex",
    "capex": "capex",
    "\uc124\ube44\ud22c\uc790": "capex",
}

SUMMARY_METRICS = ["revenue", "operating_profit", "net_income", "total_assets", "total_liabilities", "equity"]
DERIVED_METRICS = {"operating_margin", "debt_ratio", "revenue_yoy", "op_yoy"}
_DERIVED_DEPENDENCIES = {
    "operating_margin": ("revenue", "operating_profit"),
    "debt_ratio": ("total_liabilities", "equity"),
    "revenue_yoy": ("revenue",),
    "op_yoy": ("operating_profit",),
}
_PERIOD_PRIORITY = {"annual": 0, "semiannual": 1, "quarterly": 2, "event": 3}
_REPORT_TYPE_PRIORITY = {
    K_ANNUAL: 0,
    K_AUDIT: 0,
    K_HALF: 1,
    K_QUARTER: 2,
}
_REPORT_TYPE_EXCLUDED = {K_MAJOR}
_GROWTH_HINTS = ("yoy", "\uc131\uc7a5\ub960", "\uc99d\uac00\uc728", "\uc0c1\uc2b9\ub960", "\uc99d\uac00", "\uc131\uc7a5")
_REVENUE_HINTS = ("\ub9e4\ucd9c", "\ub9e4\ucd9c\uc561")
_OPERATING_PROFIT_HINTS = ("\uc601\uc5c5\uc774\uc775", "\uc601\uc5c5\uc775", K_RESULT)
COMPANY_ALIASES = dict(MASTER_COMPANY_ALIASES)

STOCK_OUTLOOK_SLOT_LABELS = {
    "recent_performance": "\ucd5c\uadfc \uc2e4\uc801 \ubc29\ud5a5",
    "industry_cycle": "\uc5c5\ud669/\uc218\uc694 \ub610\ub294 \uac00\uaca9 \uc0ac\uc774\ud074",
    "market_expectation": "\uc2dc\uc7a5 \uae30\ub300 \ub610\ub294 \ubc38\ub958\uc5d0\uc774\uc158",
    "risk": "\ud575\uc2ec \ub9ac\uc2a4\ud06c",
}

_STOCK_OUTLOOK_SLOT_KEYWORDS = {
    "recent_performance": [
        "\uc2e4\uc801", "\ub9e4\ucd9c", "\uc601\uc5c5\uc774\uc775", "\uc21c\uc774\uc775", "\uac00\uc774\ub358\uc2a4", "\ubd84\uae30", "\uc99d\uac00", "\uac10\uc18c", "\ud751\uc790", "\uc801\uc790",
    ],
    "industry_cycle": [
        "\uc5c5\ud669", "\uc218\uc694", "\uc0ac\uc774\ud074", "\uac00\uaca9", "\uba54\ubaa8\ub9ac", "\ubc18\ub3c4\uccb4", "hbm", "\ucd9c\ud558", "asp", "\uc7ac\uace0", "capex",
    ],
    "market_expectation": [
        "\ubc38\ub958", "\ubc38\ub958\uc5d0\uc774\uc158", "per", "pbr", "\uba40\ud2f0\ud50c", "\ucee8\uc13c\uc11c\uc2a4", "\ubaa9\ud45c\uc8fc\uac00", "\uae30\ub300", "\uc120\ubc18\uc601", "\uc8fc\uac00",
    ],
    "risk": [
        "\ub9ac\uc2a4\ud06c", "\uc704\ud5d8", "\ubd88\ud655\uc2e4", "\uacbd\uc7c1", "\uaddc\uc81c", "\ud658\uc728", "\ub454\ud654", "\uc9c0\uc5f0", "\uc545\ud654", "\ubcc0\ub3d9\uc131",
    ],
}


def ensure_knowledge_schema() -> None:
    return None


def _safe_load_raw(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            parsed = json.loads(raw_value)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def normalize_company_name_for_storage(name: str) -> str:
    return normalize_company_name(name)


def canonical_metric_name(metric: str) -> str:
    return metric if metric in METRICS else QUERY_METRIC_ALIASES.get(metric, "")


def _metric_label(metric_name: str) -> str:
    return str(METRICS.get(metric_name, {}).get("label", metric_name or "\uc9c0\ud45c"))


def extract_limit_from_query(message: str, default_limit: int = 5) -> int:
    for pattern in (r"top\s*(\d+)", r"\uc0c1\uc704\s*(\d+)", r"(\d+)\s*\uac1c", r"(\d+)\s*\uacf3"):
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return max(1, min(int(match.group(1)), 20))
    return default_limit


def extract_trend_span(message: str, default_span: int = 3) -> int:
    for pattern in (rf"{K_RECENT}\s*(\d+)\s*\ub144", r"(\d+)\s*\ub144\s*" + K_TREND):
        match = re.search(pattern, message)
        if match:
            return max(2, min(int(match.group(1)), 10))
    return default_span


def infer_period_type(report_type: str, disclosure_title: str = "", raw: Optional[dict[str, Any]] = None, pages: Optional[list[dict[str, Any]]] = None) -> str:
    text = f"{report_type} {disclosure_title} {json.dumps(raw or {}, ensure_ascii=False)} " + " ".join((page.get('text', '') if isinstance(page, dict) else '')[:300] for page in pages or [])
    if K_HALF in text:
        return "semiannual"
    if K_QUARTER in text:
        return "quarterly"
    if K_ANNUAL in text or K_AUDIT in text:
        return "annual"
    return "event"


def infer_statement_scope(raw: Optional[dict[str, Any]] = None, pages: Optional[list[dict[str, Any]]] = None, report_type: str = "") -> str:
    text = f"{json.dumps(raw or {}, ensure_ascii=False)} {report_type} " + " ".join((page.get('text', '') if isinstance(page, dict) else '')[:300] for page in pages or [])
    if K_CONSOL in text or "\uc5f0\uacb0" in text:
        return "consolidated"
    if K_SEP in text or "\ubcc4\ub3c4" in text:
        return "separate"
    return ""


def resolve_query_metric(message: str, variables: Optional[dict[str, Any]] = None) -> str:
    metric = canonical_metric_name(str((variables or {}).get("metric") or ""))
    if metric:
        return metric
    lowered = message.lower()
    if any(keyword in lowered for keyword in _GROWTH_HINTS):
        if any(keyword in message for keyword in _REVENUE_HINTS):
            return "revenue_yoy"
        if any(keyword in message for keyword in _OPERATING_PROFIT_HINTS):
            return "op_yoy"
    for keyword, canonical in QUERY_METRIC_ALIASES.items():
        if keyword.lower() in lowered or keyword in message:
            return canonical
    return "operating_profit" if K_RESULT in message else ""


def classify_chat_route(message: str, variables: Optional[dict[str, Any]] = None) -> str:
    variables = variables or {}
    companies = list(variables.get("companies") or ([] if not variables.get("company") else [variables["company"]]))
    metric = resolve_query_metric(message, variables)
    stripped = message
    for company in companies:
        stripped = stripped.replace(company, " ")
    stripped = re.sub(r"[^0-9A-Za-z\uac00-\ud7a3]+", " ", stripped).strip()
    if (K_RECENT in message or K_TREND in message or K_FLOW in message) and metric:
        return ROUTE_TREND
    if len(companies) >= 2 and any(token in message.lower() for token in (K_COMPARE, "vs", K_TOP)):
        return ROUTE_RANKING_COMPARE
    if K_TOP in message or K_RANK in message or "top" in message.lower():
        return ROUTE_RANKING_COMPARE if metric else ROUTE_QA
    if companies and not stripped:
        return ROUTE_COMPANY_SUMMARY
    if companies and any(token in message for token in (K_SUMMARY, K_SORT, K_FINANCE)) or (companies and K_RESULT in message and metric in {"", "operating_profit", "revenue", "net_income"}):
        return ROUTE_COMPANY_SUMMARY
    return ROUTE_QA


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def classify_stock_outlook_support(text: str) -> list[str]:
    cleaned = _clean_text(text).lower()
    if not cleaned:
        return []

    matched: list[str] = []
    for slot, keywords in _STOCK_OUTLOOK_SLOT_KEYWORDS.items():
        if any(keyword.lower() in cleaned for keyword in keywords):
            matched.append(slot)
    return matched


def evaluate_stock_outlook_coverage(texts: list[str]) -> dict[str, list[str]]:
    coverage = {slot: [] for slot in STOCK_OUTLOOK_SLOT_LABELS}
    for text in texts:
        snippet = _clean_text(text)[:220]
        if not snippet:
            continue
        for slot in classify_stock_outlook_support(snippet):
            coverage[slot].append(snippet)
    return coverage


def _extract_years_from_text(text: str) -> list[int]:
    return sorted({int(year) for year in re.findall(r"(20\d{2})", text or "") if 2000 <= int(year) <= 2100})


def _parse_amount_phrase(text: str) -> tuple[Optional[float], str, str]:
    value = _clean_text(text)
    if not value:
        return None, "", ""
    percent = re.search(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*%", value)
    if percent:
        return float(percent.group(1).replace(",", "")), "PERCENT", "PERCENT"
    jo = re.search(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*\uc870(?:\s*([+-]?\d[\d,]*(?:\.\d+)?)\s*\uc5b5)?\s*\uc6d0?", value)
    if jo:
        return float(jo.group(1).replace(",", "")) * 1_0000_0000_0000 + float((jo.group(2) or "0").replace(",", "")) * 100_000_000, "KRW", "KRW"
    eok = re.search(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*\uc5b5(?:\uc6d0)?", value)
    if eok:
        return float(eok.group(1).replace(",", "")) * 100_000_000, "KRW", "KRW"
    won = re.search(r"([+-]?\d[\d,]*(?:\.\d+)?)\s*\uc6d0", value)
    if won:
        return float(won.group(1).replace(",", "")), "KRW", "KRW"
    return None, "", ""


def _amount_matches(line: str) -> list[tuple[int, int, tuple[Optional[float], str, str]]]:
    patterns = [r"[+-]?\d[\d,]*(?:\.\d+)?\s*\uc870(?:\s*[+-]?\d[\d,]*(?:\.\d+)?\s*\uc5b5)?\s*\uc6d0?", r"[+-]?\d[\d,]*(?:\.\d+)?\s*\uc5b5(?:\uc6d0)?", r"[+-]?\d[\d,]*(?:\.\d+)?\s*%", r"[+-]?\d[\d,]*(?:\.\d+)?\s*\uc6d0"]
    matches = []
    for pattern in patterns:
        for found in re.finditer(pattern, line):
            parsed = _parse_amount_phrase(found.group(0))
            if parsed[0] is not None:
                matches.append((found.start(), found.end(), parsed))
    return sorted(matches, key=lambda item: item[0])


def _extract_metric_value_from_line(metric_name: str, line: str) -> tuple[Optional[float], str, str]:
    keywords = METRICS.get(metric_name, {}).get("keywords", [])
    amounts = _amount_matches(line)
    positions = [line.find(keyword) for keyword in keywords if keyword in line]
    if not positions or not amounts:
        return None, "", ""
    return min(amounts, key=lambda item: min(abs(item[0] - pos) for pos in positions))[2]


def _parse_metric_value(value: Any) -> tuple[Optional[float], str, str]:
    if isinstance(value, (int, float)):
        return float(value), "NUMBER", "NUMBER"
    if isinstance(value, dict):
        for key in ("value", "amount", "metric_value", "number", "text"):
            if key in value:
                return _parse_metric_value(value[key])
    if isinstance(value, list):
        for item in value:
            parsed = _parse_metric_value(item)
            if parsed[0] is not None:
                return parsed
    if isinstance(value, str):
        return _parse_amount_phrase(value)
    return None, "", ""


def _filename_company_candidates(filename: str) -> list[str]:
    if not filename:
        return []

    candidates: list[str] = []
    patterns = [
        r"DART_[^_]+_([^_]+)_",
        r"^[^_]+_DART_[^_]+_([^_]+)_",
    ]
    for pattern in patterns:
        match = re.search(pattern, filename)
        if not match:
            continue
        token = normalize_company_name_for_storage(match.group(1))
        if token and token not in candidates:
            candidates.append(token)
    return candidates


def _is_suspicious_metric_value(
    metric_name: str,
    value: Optional[float],
    unit: str,
    currency: str,
    source_text: str = "",
) -> bool:
    if value is None:
        return True

    cleaned = _clean_text(source_text).lower()
    is_krw = unit == "KRW" or currency == "KRW"

    if metric_name == "treasury_stock_amount":
        if any(token in cleaned for token in ("주당", "1주당", "액면가", "per share", "share price", "단가")):
            return True
        if is_krw and abs(value) < 1_000_000:
            return True

    if metric_name == "capital_raise_amount":
        if any(token in cleaned for token in ("주당", "1주당", "액면가", "발행가", "발행가액")):
            return True
        if is_krw and abs(value) < 1_000_000:
            return True

    if metric_name in {
        "revenue",
        "operating_profit",
        "net_income",
        "total_assets",
        "total_liabilities",
        "equity",
        "capex",
        "dividend_amount",
    } and is_krw and abs(value) < 1_000_000:
        return True

    return False


def _guess_company_name(db: Session, doc: Document, latest_analysis: Optional[AnalysisResult], ocr_rows: list[OcrText]) -> tuple[str, str, float]:
    raw = _safe_load_raw(getattr(latest_analysis, "raw_response", None))
    corp_code = str(raw.get("corp_code") or "").strip()

    if corp_code:
        profile = db.query(CompanyProfile).filter(CompanyProfile.corp_code == corp_code).first()
        if profile and profile.company_name_norm:
            return profile.display_name or profile.company_name_norm, "corp_code_profile", 0.98

        metadata = db.query(DocumentMetadata).filter(DocumentMetadata.corp_code == corp_code).order_by(DocumentMetadata.id.desc()).first()
        if metadata and metadata.company_name_norm:
            return metadata.company_name or metadata.company_name_norm, "corp_code_metadata", 0.96

    title_text = f"{raw.get('title') or ''} {doc.filename}"
    for candidate in (raw.get("company_name"), raw.get("company"), raw.get("corp_name")):
        normalized = normalize_company_name_for_storage(str(candidate or ""))
        if normalized:
            return normalized, "raw_response", 0.93

    for candidate in _filename_company_candidates(title_text):
        if candidate:
            return candidate, "filename", 0.62

    header_text = " ".join((row.cleaned_text or row.raw_text or "")[:200] for row in (ocr_rows or [])[:2])
    for candidate in COMPANY_ALIASES.values():
        normalized = normalize_company_name_for_storage(candidate)
        if normalized and normalized in header_text:
            return normalized, "ocr_header", 0.58

    return "", "unresolved", 0.0


def _chunk_texts(rows: list[tuple[int, str]], target_size: int = 1200) -> list[dict[str, Any]]:
    chunks = []
    for page_no, text in rows:
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        for part in re.split(r"\n\s*\n", cleaned):
            part = part.strip()
            if not part:
                continue
            if len(part) <= target_size:
                chunks.append({"page_no": page_no, "text": part})
            else:
                for start in range(0, len(part), target_size):
                    piece = part[start:start + target_size].strip()
                    if piece:
                        chunks.append({"page_no": page_no, "text": piece})
    return chunks


def _extract_metric_records(latest_analysis: Optional[AnalysisResult], metadata: DocumentMetadata) -> list[dict[str, Any]]:
    raw = _safe_load_raw(getattr(latest_analysis, "raw_response", None))
    records, seen = [], set()
    metrics = raw.get("financial_metrics")
    if isinstance(metrics, dict):
        for key, value in metrics.items():
            metric_name = canonical_metric_name(str(key)) or canonical_metric_name(str(key).lower())
            parsed = _parse_metric_value(value)
            if metric_name and parsed[0] is not None:
                if _is_suspicious_metric_value(metric_name, parsed[0], parsed[1], parsed[2], str(value)):
                    continue
                seen.add(metric_name)
                records.append({"metric_name": metric_name, "metric_value_num": parsed[0], "metric_value_text": str(value), "unit": parsed[1], "currency": parsed[2], "source_text": str(value), "confidence": 0.95, "method": "raw_financial_metrics"})
    return records


def upsert_document_knowledge(db: Session, doc: Document, latest_analysis: Optional[AnalysisResult] = None, ocr_rows: Optional[list[OcrText]] = None) -> dict[str, Any]:
    latest_analysis = latest_analysis or db.query(AnalysisResult).filter(AnalysisResult.document_id == doc.id).order_by(AnalysisResult.id.desc()).first()
    ocr_rows = ocr_rows or db.query(OcrText).filter(OcrText.document_id == doc.id).order_by(OcrText.id.asc()).all()
    raw = _safe_load_raw(getattr(latest_analysis, "raw_response", None))
    company_name, company_source, company_confidence = _guess_company_name(db, doc, latest_analysis, ocr_rows)
    report_type = next((token for token in (K_ANNUAL, K_HALF, K_QUARTER, K_AUDIT, K_MAJOR) if token in f"{doc.filename} {getattr(latest_analysis, 'category', '')}"), str(getattr(latest_analysis, "category", "") or ""))
    filing_match = re.search(r"(20\d{2})[.\-/]?(0[1-9]|1[0-2])[.\-/]?([0-2]\d|3[01])", f"{doc.filename} {json.dumps(raw, ensure_ascii=False)}")
    filing_date = f"{filing_match.group(1)}-{filing_match.group(2)}-{filing_match.group(3)}" if filing_match else ""
    fiscal_years = _extract_years_from_text(f"{doc.filename} {getattr(latest_analysis, 'summary', '')} " + " ".join((row.cleaned_text or row.raw_text or "")[:500] for row in ocr_rows[:2]))
    fiscal_year = max(fiscal_years) if fiscal_years else (int(filing_date[:4]) if filing_date else None)
    pages = [{"text": row.cleaned_text or row.raw_text or ""} for row in ocr_rows[:3]]
    metadata = db.query(DocumentMetadata).filter(DocumentMetadata.document_id == doc.id).first() or DocumentMetadata(document_id=doc.id)
    metadata.company_name = company_name
    metadata.company_name_norm = normalize_company_name_for_storage(company_name)
    metadata.corp_code = str(raw.get("corp_code") or "")
    metadata.report_type = report_type
    metadata.disclosure_title = str(raw.get("title") or doc.filename)
    metadata.filing_date = filing_date
    metadata.fiscal_year = fiscal_year
    metadata.period_type = infer_period_type(report_type, doc.filename, raw=raw, pages=pages)
    metadata.statement_scope = infer_statement_scope(raw=raw, pages=pages, report_type=report_type)
    metadata.source_kind = company_source or "analysis"
    metadata.extraction_confidence = company_confidence if company_name else 0.0
    metadata.metadata_json = {
        **(raw or {}),
        "_company_link": {
            "source": company_source,
            "confidence": company_confidence,
            "filename_candidates": _filename_company_candidates(doc.filename),
        },
    }
    db.add(metadata)
    db.flush()

    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete(synchronize_session=False)
    page_rows = [(index + 1, row.cleaned_text or row.raw_text or "") for index, row in enumerate(ocr_rows)] or [(1, "\n\n".join(filter(None, [getattr(latest_analysis, "summary", ""), getattr(latest_analysis, "evidence", "")])))]
    chunks = []
    for item in _chunk_texts(page_rows):
        text = _clean_text(item["text"])
        if len(text) < 20:
            continue
        chunk = DocumentChunk(chunk_uid=hashlib.sha1(f"{doc.id}:{item['page_no']}:{text[:160]}".encode("utf-8")).hexdigest(), document_id=doc.id, page_no=item["page_no"], page_from=item["page_no"], page_to=item["page_no"], section_name="", text=text, text_hash=hashlib.sha1(text.encode("utf-8")).hexdigest(), source_kind="ocr_chunk", token_count=max(1, len(text) // 4), metadata_json={}, vector_collection=CHAT_CHUNK_COLLECTION_NAME)
        db.add(chunk)
        chunks.append(chunk)
    db.flush()

    db.query(FinancialFact).filter(FinancialFact.document_id == doc.id).delete(synchronize_session=False)
    facts = _extract_metric_records(latest_analysis, metadata)
    if not facts:
        for line in str(getattr(latest_analysis, "summary", "") or "").splitlines():
            for metric_name in METRICS:
                parsed = _extract_metric_value_from_line(metric_name, line)
                if parsed[0] is not None:
                    if _is_suspicious_metric_value(metric_name, parsed[0], parsed[1], parsed[2], line):
                        continue
                    facts.append({"metric_name": metric_name, "metric_value_num": parsed[0], "metric_value_text": _clean_text(line)[:255], "unit": parsed[1], "currency": parsed[2], "source_text": _clean_text(line)[:2000], "confidence": 0.8, "method": "summary_line"})
    for fact in facts:
        db.add(FinancialFact(fact_uid=hashlib.sha1(f"{doc.id}:{fact['metric_name']}:{fact['metric_value_text']}".encode("utf-8")).hexdigest(), document_id=doc.id, chunk_id=None, company_name_norm=metadata.company_name_norm, corp_code=metadata.corp_code, fiscal_year=metadata.fiscal_year, metric_name=fact["metric_name"], metric_value_num=fact["metric_value_num"], metric_value_text=fact["metric_value_text"], unit=fact["unit"], currency=fact["currency"], statement_scope=metadata.statement_scope, period_type=metadata.period_type, source_page=None, source_text=fact["source_text"], confidence=fact["confidence"], extraction_method=fact["method"]))

    if metadata.company_name_norm:
        profile = db.query(CompanyProfile).filter(CompanyProfile.company_name_norm == metadata.company_name_norm).first() or CompanyProfile(company_name_norm=metadata.company_name_norm)
        profile.display_name = metadata.company_name
        profile.corp_code = metadata.corp_code
        if metadata.fiscal_year and (not profile.latest_completed_fiscal_year or metadata.fiscal_year >= profile.latest_completed_fiscal_year):
            profile.latest_completed_fiscal_year = metadata.fiscal_year
            if metadata.period_type == "annual" and metadata.statement_scope == "consolidated":
                profile.latest_annual_consolidated_doc_id = doc.id
            elif metadata.period_type == "annual":
                profile.latest_annual_separate_doc_id = doc.id
        db.add(profile)

    if chunks:
        try:
            vector_service.index_chat_chunks([{"chunk_uid": chunk.chunk_uid, "document_id": doc.id, "filename": doc.filename, "company_name": metadata.company_name or metadata.company_name_norm, "company_name_norm": metadata.company_name_norm, "report_type": metadata.report_type, "page_no": chunk.page_no, "section_name": "", "fiscal_year": metadata.fiscal_year or 0, "period_type": metadata.period_type or "", "statement_scope": metadata.statement_scope or "", "source_kind": chunk.source_kind or "ocr_chunk", "text": chunk.text} for chunk in chunks], clear_document_id=doc.id, user_id=getattr(doc, "user_id", 0))
        except Exception as exc:
            logger.warning("chat chunk index failed for doc %s: %s", doc.id, exc)
    return {"success": True, "document_id": doc.id, "fact_count": len(facts), "chunk_count": len(chunks)}


def _format_value(value: Optional[float], unit: str, currency: str) -> str:
    if value is None:
        return TXT_NO_DATA
    if unit == "PERCENT" or currency == "PERCENT":
        return f"{value:,.1f}%"
    if unit == "KRW" or currency == "KRW":
        if abs(value) >= 1_0000_0000_0000:
            jo = int(abs(value) // 1_0000_0000_0000)
            eok = int((abs(value) % 1_0000_0000_0000) // 100_000_000)
            sign = "-" if value < 0 else ""
            return f"{sign}{jo}\uc870 {eok:,}\uc5b5\uc6d0" if eok else f"{sign}{jo}\uc870\uc6d0"
        if abs(value) >= 100_000_000:
            return f"{value / 100_000_000:,.0f}\uc5b5\uc6d0"
        return f"{value:,.0f}\uc6d0"
    return f"{value:,.0f}"


def _build_citation(fact: Optional[FinancialFact] = None, document: Optional[Document] = None, metadata: Optional[DocumentMetadata] = None, hit: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if hit:
        return {"document_id": hit.get("doc_id"), "filename": hit.get("filename", ""), "company": hit.get("company", ""), "source_text": _clean_text(str(hit.get("chunk") or ""))[:300]}
    return {"document_id": document.id if document else None, "filename": document.filename if document else "", "company": (metadata.company_name if metadata else "") or (fact.company_name_norm if fact else ""), "source_text": _clean_text(fact.source_text if fact else "")[:300]}


def _fact_row_payload(fact: FinancialFact, document: Document, metadata: Optional[DocumentMetadata]) -> dict[str, Any]:
    return {"company_name": (metadata.company_name if metadata else "") or fact.company_name_norm or "", "company_name_norm": fact.company_name_norm or "", "metric_name": fact.metric_name, "metric_label": _metric_label(fact.metric_name), "value": fact.metric_value_num, "value_display": _format_value(fact.metric_value_num, fact.unit or "", fact.currency or ""), "document_id": document.id, "filename": document.filename, "fiscal_year": fact.fiscal_year, "statement_scope": fact.statement_scope or (metadata.statement_scope if metadata else ""), "period_type": fact.period_type or (metadata.period_type if metadata else "")}


def _fact_query(db: Session, user_id: Optional[int] = None):
    query = db.query(FinancialFact, Document, DocumentMetadata).join(Document, Document.id == FinancialFact.document_id).outerjoin(DocumentMetadata, DocumentMetadata.document_id == FinancialFact.document_id)
    return query.filter(Document.user_id == user_id) if user_id is not None else query


def _latest_year(db: Session, companies: Optional[list[str]] = None, user_id: Optional[int] = None) -> int:
    query = _fact_query(db, user_id=user_id)
    if companies:
        query = query.filter(FinancialFact.company_name_norm.in_(companies))
    years = [fact.fiscal_year for fact, _, _ in query.all() if fact.fiscal_year]
    return max(years) if years else datetime.now().year - 1


def _facts_for_metric(db: Session, metric_name: str, companies: Optional[list[str]] = None, years: Optional[list[int]] = None, user_id: Optional[int] = None):
    query = _fact_query(db, user_id=user_id).filter(FinancialFact.metric_name == metric_name)
    if companies:
        query = query.filter(FinancialFact.company_name_norm.in_(companies))
    if years:
        query = query.filter(FinancialFact.fiscal_year.in_(years))
    rows = query.order_by(FinancialFact.fiscal_year.desc(), FinancialFact.id.desc()).all()
    return [
        (fact, document, metadata)
        for fact, document, metadata in rows
        if not _is_suspicious_metric_value(
            fact.metric_name,
            fact.metric_value_num,
            fact.unit or "",
            fact.currency or "",
            fact.source_text or fact.metric_value_text or "",
        )
    ]


def _is_derived_metric(metric_name: str) -> bool:
    return metric_name in DERIVED_METRICS


def _period_rank(period_type: str) -> int:
    return _PERIOD_PRIORITY.get((period_type or "").lower(), 4)


def _report_type_rank(report_type: str) -> int:
    return _REPORT_TYPE_PRIORITY.get((report_type or "").strip(), 5)


def _resolve_period(fact: FinancialFact, metadata: Optional[DocumentMetadata]) -> str:
    meta_period = (metadata.period_type if metadata else "") or ""
    if meta_period:
        return meta_period.lower()
    return (fact.period_type or "").lower()


def _collect_companies_for_metric(metric_name: str, db: Session, years: list[int], companies: list[str], user_id: Optional[int] = None) -> list[str]:
    if companies:
        return companies
    discovered: list[str] = []
    for base_metric in _DERIVED_DEPENDENCIES.get(metric_name, (metric_name,)):
        for fact, _document, metadata in _facts_for_metric(db, base_metric, None, years or None, user_id=user_id):
            report_type = (metadata.report_type if metadata else "") or ""
            if report_type in _REPORT_TYPE_EXCLUDED:
                continue
            company = fact.company_name_norm or (metadata.company_name_norm if metadata else "")
            if company and company not in discovered:
                discovered.append(company)
    return discovered


def _build_metric_matrix(
    db: Session,
    companies: list[str],
    years: list[int],
    user_id: Optional[int] = None,
) -> dict[str, dict[str, dict[int, dict[str, Any]]]]:
    matrix: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}
    base_metrics = sorted({metric for dependencies in _DERIVED_DEPENDENCIES.values() for metric in dependencies})
    for metric in base_metrics:
        metric_rows = _facts_for_metric(db, metric, companies or None, years or None, user_id=user_id)
        eligible: list[tuple[FinancialFact, Document, Optional[DocumentMetadata], str, str]] = []
        for fact, document, metadata in metric_rows:
            report_type = (metadata.report_type if metadata else "") or ""
            if report_type in _REPORT_TYPE_EXCLUDED:
                continue
            company_key = fact.company_name_norm or (metadata.company_name_norm if metadata else "")
            if not company_key or not fact.fiscal_year or fact.metric_value_num is None:
                continue
            eligible.append((fact, document, metadata, report_type, company_key))
        eligible.sort(
            key=lambda item: (
                item[4],
                -(item[0].fiscal_year or 0),
                _report_type_rank(item[3]),
                _period_rank(_resolve_period(item[0], item[2])),
                -(item[0].id or 0),
            ),
        )
        seen: set[tuple[str, int]] = set()
        for fact, document, metadata, report_type, company_key in eligible:
            key = (company_key, fact.fiscal_year or 0)
            if key in seen:
                continue
            seen.add(key)
            matrix.setdefault(metric, {}).setdefault(company_key, {})[fact.fiscal_year or 0] = {
                "value": float(fact.metric_value_num),
                "display": _format_value(fact.metric_value_num, fact.unit or "", fact.currency or ""),
                "scope": fact.statement_scope or (metadata.statement_scope if metadata else ""),
                "period": _resolve_period(fact, metadata),
                "report_type": report_type,
                "company_name": (metadata.company_name if metadata else "") or company_key,
                "citation": _build_citation(fact=fact, document=document, metadata=metadata),
            }
    return matrix


def _derived_metric_cell(
    metric_name: str,
    matrix: dict[str, dict[str, dict[int, dict[str, Any]]]],
    company: str,
    fiscal_year: int,
) -> Optional[dict[str, Any]]:
    def _cell(base_metric: str, year: int) -> Optional[dict[str, Any]]:
        return matrix.get(base_metric, {}).get(company, {}).get(year)

    def _annual(base_metric: str, year: int) -> bool:
        item = _cell(base_metric, year)
        return bool(item and item.get("period") == "annual")

    display_name = (
        (_cell("revenue", fiscal_year) or {}).get("company_name")
        or (_cell("operating_profit", fiscal_year) or {}).get("company_name")
        or company
    )
    if metric_name == "operating_margin":
        revenue = _cell("revenue", fiscal_year)
        op = _cell("operating_profit", fiscal_year)
        if not revenue or not op or not _annual("revenue", fiscal_year) or not _annual("operating_profit", fiscal_year):
            return None
        base = float(revenue["value"])
        if base == 0:
            return None
        value = float(op["value"]) / base * 100.0
        return {
            "value": value,
            "display": f"{value:,.1f}%",
            "company_name": display_name,
            "fiscal_year": fiscal_year,
            "statement_scope": revenue.get("scope") or op.get("scope") or "",
            "period_type": "annual",
            "citations": [revenue.get("citation"), op.get("citation")],
        }
    if metric_name == "debt_ratio":
        liabilities = _cell("total_liabilities", fiscal_year)
        equity = _cell("equity", fiscal_year)
        if not liabilities or not equity or not _annual("total_liabilities", fiscal_year) or not _annual("equity", fiscal_year):
            return None
        base = float(equity["value"])
        if base == 0:
            return None
        value = float(liabilities["value"]) / base * 100.0
        return {
            "value": value,
            "display": f"{value:,.1f}%",
            "company_name": display_name,
            "fiscal_year": fiscal_year,
            "statement_scope": liabilities.get("scope") or equity.get("scope") or "",
            "period_type": "annual",
            "citations": [liabilities.get("citation"), equity.get("citation")],
        }
    if metric_name == "revenue_yoy":
        current = _cell("revenue", fiscal_year)
        previous = _cell("revenue", fiscal_year - 1)
        if not current or not previous or not _annual("revenue", fiscal_year) or not _annual("revenue", fiscal_year - 1):
            return None
        base = float(previous["value"])
        if base == 0:
            return None
        value = (float(current["value"]) - base) / abs(base) * 100.0
        return {
            "value": value,
            "display": f"{value:+,.1f}%",
            "company_name": current.get("company_name") or display_name,
            "fiscal_year": fiscal_year,
            "statement_scope": current.get("scope") or previous.get("scope") or "",
            "period_type": "annual",
            "citations": [current.get("citation"), previous.get("citation")],
        }
    if metric_name == "op_yoy":
        current = _cell("operating_profit", fiscal_year)
        previous = _cell("operating_profit", fiscal_year - 1)
        if not current or not previous or not _annual("operating_profit", fiscal_year) or not _annual("operating_profit", fiscal_year - 1):
            return None
        base = float(previous["value"])
        if base == 0:
            return None
        value = (float(current["value"]) - base) / abs(base) * 100.0
        return {
            "value": value,
            "display": f"{value:+,.1f}%",
            "company_name": current.get("company_name") or display_name,
            "fiscal_year": fiscal_year,
            "statement_scope": current.get("scope") or previous.get("scope") or "",
            "period_type": "annual",
            "citations": [current.get("citation"), previous.get("citation")],
        }
    return None


def _dedupe_citations(citations: list[Optional[dict[str, Any]]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, str, str]] = set()
    for citation in citations:
        if not citation:
            continue
        key = (
            citation.get("document_id"),
            str(citation.get("filename") or ""),
            str(citation.get("source_text") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def _answer_derived_metric_ranking(message: str, metric_name: str, variables: dict[str, Any], db: Session, user_id: Optional[int] = None) -> dict[str, Any]:
    companies = [normalize_company_name_for_storage(name) for name in variables.get("companies", []) if name]
    years = [int(year) for year in variables.get("year_filters", []) if str(year).isdigit()]
    target_year = max(years) if years else _latest_year(db, companies or None, user_id=user_id)
    required_years = sorted({target_year, target_year - 1} if metric_name in {"revenue_yoy", "op_yoy"} else {target_year})
    candidate_companies = _collect_companies_for_metric(metric_name, db, required_years, companies, user_id=user_id)
    if not candidate_companies:
        return {"reply": TXT_NO_DATA, "payload": {"type": "ranking", "route": ROUTE_RANKING_COMPARE, "criteria": {"metric_name": metric_name, "metric_label": _metric_label(metric_name), "fiscal_year": target_year}, "rows": [], "series": [], "citations": []}}
    matrix = _build_metric_matrix(db, candidate_companies, required_years, user_id=user_id)
    rows: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for company in candidate_companies:
        cell = _derived_metric_cell(metric_name, matrix, company, target_year)
        if not cell:
            continue
        rows.append({
            "company_name": cell["company_name"],
            "company_name_norm": company,
            "metric_name": metric_name,
            "metric_label": _metric_label(metric_name),
            "value": cell["value"],
            "value_display": cell["display"],
            "document_id": None,
            "filename": "",
            "fiscal_year": cell["fiscal_year"],
            "statement_scope": cell["statement_scope"],
            "period_type": cell["period_type"],
        })
        citations.extend(_dedupe_citations(cell["citations"]))
    if not rows:
        return {"reply": TXT_NO_DATA, "payload": {"type": "ranking", "route": ROUTE_RANKING_COMPARE, "criteria": {"metric_name": metric_name, "metric_label": _metric_label(metric_name), "fiscal_year": target_year}, "rows": [], "series": [], "citations": []}}
    descending = not any(token in message for token in ("\ub0ae", "\uc801\uc740", "\ucd5c\uc800")) and metric_name != "debt_ratio"
    rows.sort(key=lambda item: item["value"], reverse=descending)
    if companies:
        order = {name: idx for idx, name in enumerate(companies)}
        rows.sort(key=lambda item: order.get(item["company_name_norm"], 999))
    selected = rows[: len(companies) if companies else int(variables.get("limit") or 5)]
    ranking = ", ".join(
        f"{idx}. {row['company_name']} {row['value_display']}"
        for idx, row in enumerate(selected, start=1)
    )
    reply = "\n".join(
        [
            f"{TXT_CONCLUSION}: {target_year}\ub144 {_metric_label(metric_name)} \uae30\uc900 \uc21c\uc704\ub294 {ranking}\uc785\ub2c8\ub2e4.",
            "",
            TXT_EVIDENCE,
            f"1. \uad6c\uc870\ud654\ub41c \uc7ac\ubb34 \ud329\ud2b8 DB\uc5d0\uc11c {target_year}\ub144 \uc5f0\uac04 \uac12\uc744 \uc6b0\uc120 \uc870\ud68c\ud588\uc2b5\ub2c8\ub2e4.",
            f"2. `{_metric_label(metric_name)}`\uc740 \uc5f0\uac04 \uae30\uc900 \ud329\ud2b8\ub85c \ub2e4\uc2dc \uacc4\uc0b0\ud588\uc2b5\ub2c8\ub2e4.",
            "",
            TXT_RISK,
            "- \uc804\ub144 \ub610\ub294 \ub2f9\ud574 \uc5f0\uac04 \uacf5\uc2dc\uac00 \ube44\uc5b4 \uc788\uc73c\uba74 \ud574\ub2f9 \uae30\uc5c5\uc740 \uc21c\uc704\uc5d0\uc11c \uc81c\uc678\ub429\ub2c8\ub2e4.",
            "",
            TXT_CONFIDENCE,
            "- INFERENCE [86%] - \uc5f0\uac04 \ud329\ud2b8 \uae30\ubc18 \uacc4\uc0b0 \uc21c\uc704\uc785\ub2c8\ub2e4.",
        ]
    )
    selected_citations = _dedupe_citations(citations)[: max(len(selected) * 2, 1)]
    return {
        "reply": reply,
        "payload": {"type": "ranking", "route": ROUTE_RANKING_COMPARE, "criteria": {"metric_name": metric_name, "metric_label": _metric_label(metric_name), "fiscal_year": target_year, "policy": "single_year_derived"}, "rows": selected, "series": [], "citations": selected_citations},
        "citations": selected_citations,
        "meta": {"intent": ROUTE_RANKING_COMPARE, "confidence": "INFERENCE [86%]", "evidence_count": len(selected_citations)},
    }


def _answer_derived_metric_trend(message: str, metric_name: str, variables: dict[str, Any], db: Session, user_id: Optional[int] = None) -> dict[str, Any]:
    companies = [normalize_company_name_for_storage(name) for name in variables.get("companies", []) if name]
    latest = _latest_year(db, companies or None, user_id=user_id)
    years = list(range(max(2000, latest - int(variables.get("trend_span") or extract_trend_span(message)) + 1), latest + 1))
    required_years = sorted(set(years + ([min(years) - 1] if years and metric_name in {"revenue_yoy", "op_yoy"} else [])))
    candidate_companies = _collect_companies_for_metric(metric_name, db, required_years, companies, user_id=user_id)
    if not candidate_companies:
        return {"reply": TXT_NO_DATA, "payload": {"type": "trend", "route": ROUTE_TREND, "criteria": {"metric_name": metric_name, "metric_label": _metric_label(metric_name), "years": years}, "rows": [], "series": [], "citations": []}}
    matrix = _build_metric_matrix(db, candidate_companies, required_years, user_id=user_id)
    series: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for company in candidate_companies[:5] if not companies else candidate_companies:
        points: list[dict[str, Any]] = []
        company_name = company
        for year in years:
            cell = _derived_metric_cell(metric_name, matrix, company, year)
            if not cell:
                continue
            company_name = cell["company_name"] or company_name
            points.append({"year": year, "value": cell["value"], "value_display": cell["display"], "document_id": None, "filename": ""})
            citations.extend(_dedupe_citations(cell["citations"]))
        if points:
            series.append({"company_name": company_name, "company_name_norm": company, "metric_name": metric_name, "metric_label": _metric_label(metric_name), "points": points})
    if not series:
        return {"reply": TXT_NO_DATA, "payload": {"type": "trend", "route": ROUTE_TREND, "criteria": {"metric_name": metric_name, "metric_label": _metric_label(metric_name), "years": years}, "rows": [], "series": [], "citations": []}}
    reply = "\n".join([f"{TXT_CONCLUSION}: {len(years)}\ub144 {_metric_label(metric_name)} {K_TREND}\uc785\ub2c8\ub2e4.", "", TXT_EVIDENCE] + [f"{idx}. {item['company_name']}: " + ", ".join(f"{point['year']}\ub144 {point['value_display']}" for point in item["points"]) for idx, item in enumerate(series[:3], start=1)] + ["", TXT_RISK, "- \uc804\ub144 \uc5f0\uac04 \ud329\ud2b8\uac00 \ube44\uba74 \ud574\ub2f9 \uc5f0\ub3c4\uc758 \uc131\uc7a5\ub960\uc740 \uacc4\uc0b0\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.", "", TXT_CONFIDENCE, "- INFERENCE [82%] - \uc5f0\uac04 \ud329\ud2b8 \uae30\ubc18 \ud30c\uc0dd \uc2dc\uacc4\uc5f4\uc785\ub2c8\ub2e4."])
    deduped_citations = _dedupe_citations(citations)
    return {"reply": reply, "payload": {"type": "trend", "route": ROUTE_TREND, "criteria": {"metric_name": metric_name, "metric_label": _metric_label(metric_name), "years": years, "policy": "derived_annual_only"}, "rows": [], "series": series, "citations": deduped_citations}, "citations": deduped_citations, "meta": {"intent": ROUTE_TREND, "confidence": "INFERENCE [82%]", "evidence_count": len(deduped_citations)}}


def _answer_derived_metric_qa(message: str, metric_name: str, variables: dict[str, Any], db: Session, user_id: Optional[int] = None) -> dict[str, Any]:
    company = normalize_company_name_for_storage(variables.get("company") or (variables.get("companies") or [""])[0])
    if not company:
        return {"reply": TXT_NO_DATA, "payload": {"type": "qa", "route": ROUTE_QA, "criteria": {"metric_name": metric_name}, "rows": [], "series": [], "citations": []}}
    years = [int(year) for year in variables.get("year_filters", []) if str(year).isdigit()]
    target_year = max(years) if years else _latest_year(db, [company], user_id=user_id)
    required_years = sorted({target_year, target_year - 1} if metric_name in {"revenue_yoy", "op_yoy"} else {target_year})
    matrix = _build_metric_matrix(db, [company], required_years, user_id=user_id)
    cell = _derived_metric_cell(metric_name, matrix, company, target_year)
    if not cell:
        return {"reply": TXT_NO_DATA, "payload": {"type": "qa", "route": ROUTE_QA, "criteria": {"company_name_norm": company, "metric_name": metric_name, "fiscal_year": target_year}, "rows": [], "series": [], "citations": []}}
    row = {
        "company_name": cell["company_name"],
        "company_name_norm": company,
        "metric_name": metric_name,
        "metric_label": _metric_label(metric_name),
        "value": cell["value"],
        "value_display": cell["display"],
        "document_id": None,
        "filename": "",
        "fiscal_year": target_year,
        "statement_scope": cell["statement_scope"],
        "period_type": cell["period_type"],
    }
    citations = _dedupe_citations(cell["citations"])
    reply = "\n".join([f"{TXT_CONCLUSION}: {row['company_name']}\uc758 {target_year}\ub144 {row['metric_label']}\uc740 {row['value_display']}\uc785\ub2c8\ub2e4.", "", TXT_EVIDENCE, "1. \uc5f0\uac04 \ud329\ud2b8\ub97c \uae30\ubc18\uc73c\ub85c \uc9c1\uc811 \uacc4\uc0b0\ud588\uc2b5\ub2c8\ub2e4.", f"2. \uae30\uc900 \uc5f0\ub3c4: {target_year}\ub144", "", TXT_RISK, "- \uc804\ub144 \ud329\ud2b8\uac00 \ub204\ub77d\ub418\uba74 YoY \uc9c0\ud45c\ub294 \ube44\uac8c\uc0b0 \ucc98\ub9ac\ub429\ub2c8\ub2e4.", "", TXT_CONFIDENCE, "- INFERENCE [86%] - \uc5f0\uac04 \ud329\ud2b8 \uae30\ubc18 \ud30c\uc0dd \uc9c0\ud45c\uc785\ub2c8\ub2e4."])
    return {"reply": reply, "payload": {"type": "qa", "route": ROUTE_QA, "criteria": {"company_name": row["company_name"], "company_name_norm": company, "metric_name": metric_name, "metric_label": row["metric_label"], "fiscal_year": target_year, "policy": "derived_annual_only"}, "rows": [row], "series": [], "citations": citations}, "citations": citations, "meta": {"intent": ROUTE_QA, "confidence": "INFERENCE [86%]", "evidence_count": len(citations)}}


def answer_ranking_compare(message: str, variables: dict[str, Any], db: Session, user_id: Optional[int] = None) -> dict[str, Any]:
    metric_name = resolve_query_metric(message, variables) or "operating_profit"
    if _is_derived_metric(metric_name):
        return _answer_derived_metric_ranking(message, metric_name, variables, db, user_id=user_id)
    companies = [normalize_company_name_for_storage(name) for name in variables.get("companies", []) if name]
    years = [int(year) for year in variables.get("year_filters", []) if str(year).isdigit()]
    # ── Year-target policy ──
    # 사용자가 연도를 명시했거나 회사 목록을 명시한 경우: 단일 target_year로 비교 (공정성)
    # top-N 일반 ranking (회사 미지정): per-company latest 정책 — 각 회사의 가장 최근 fact 사용
    #   이렇게 하면 fy=2026 분기 보고서가 있는 소형 회사만 잡혀 대기업이 누락되는 왜곡이 사라진다.
    if years:
        target_year = max(years)
        rows = _facts_for_metric(db, metric_name, companies or None, [target_year], user_id=user_id)
    elif companies:
        target_year = _latest_year(db, companies, user_id=user_id)
        rows = _facts_for_metric(db, metric_name, companies, [target_year], user_id=user_id)
    else:
        # top-N global ranking: 모든 facts → 회사별 latest dedupe (아래 best{} 로직이 처리)
        target_year = None
        rows = _facts_for_metric(db, metric_name, None, None, user_id=user_id)
    if not rows:
        # ── Retrieval fallback: structured ranking unavailable, cite per-company evidence chunks ──
        try:
            from services.cognitive_search_safe import cognitive_search_safe
            metric_label = _metric_label(metric_name)
            target_companies = companies[:5] if companies else []
            ev_lines: list[str] = []
            cits: list[dict[str, Any]] = []
            if target_companies:
                for c in target_companies:
                    sr = cognitive_search_safe(query=f"{c} {metric_label}", top_k=2, company_filter=c, user_id=user_id or 0)
                    for r in sr[:2]:
                        snippet = _clean_text(r.get("chunk", "") or "")[:180]
                        if not snippet:
                            continue
                        ev_lines.append(f"- {c}: {snippet}")
                        cits.append({"document_id": r.get("doc_id"), "filename": r.get("filename", ""), "company": r.get("company", "") or c, "source_text": snippet, "score": r.get("composite_score")})
            else:
                sr = cognitive_search_safe(query=f"{metric_label} {message}"[:180], top_k=5, user_id=user_id or 0)
                for r in sr[:5]:
                    snippet = _clean_text(r.get("chunk", "") or "")[:180]
                    if not snippet:
                        continue
                    ev_lines.append(f"- {r.get('company','?')}: {snippet}")
                    cits.append({"document_id": r.get("doc_id"), "filename": r.get("filename", ""), "company": r.get("company", ""), "source_text": snippet, "score": r.get("composite_score")})
            if ev_lines:
                reply = "\n".join([
                    f"{TXT_CONCLUSION}: {metric_label} \uad6c\uc870\ud654\ub41c \uc21c\uc704\uac00 \ubd80\uc7ac\ud558\uc5ec \uac80\uc0c9 \uccad\ud06c\uc5d0\uc11c \ud68c\uc0ac\ubcc4 \uad00\ub828 \uc99d\uac70\ub97c \uc81c\uc2dc\ud569\ub2c8\ub2e4.",
                    "",
                    TXT_EVIDENCE,
                    *ev_lines[:8],
                    "",
                    TXT_RISK,
                    "- \uc815\ub7c9 \uc21c\uc704\uac00 \uc544\ub2c8\ub77c \uc99d\uac70 \uccad\ud06c \uc778\uc6a9\uc774\ubbc0\ub85c \ub3d9\uc77c \uae30\uc900 \ube44\uad50 \ubd88\uac00.",
                    "",
                    TXT_CONFIDENCE,
                    "- INFERENCE [55%] - \uad6c\uc870\ud654 \ud329\ud2b8 \ubd80\uc7ac fallback\uc785\ub2c8\ub2e4.",
                ])
                return {"reply": reply, "payload": {"type": "ranking", "route": ROUTE_RANKING_COMPARE, "criteria": {"metric_name": metric_name, "metric_label": metric_label, "fiscal_year": target_year, "fallback": "retrieval"}, "rows": [], "series": [], "citations": cits}, "citations": cits, "meta": {"intent": ROUTE_RANKING_COMPARE, "confidence": "INFERENCE [55%]", "evidence_count": len(cits)}}
        except Exception as exc:
            logger.warning("answer_ranking_compare retrieval fallback failed: %s", exc)
        return {"reply": TXT_NO_DATA, "payload": {"type": "ranking", "route": ROUTE_RANKING_COMPARE, "criteria": {"metric_name": metric_name, "metric_label": _metric_label(metric_name), "fiscal_year": target_year}, "rows": [], "series": [], "citations": []}}
    best = {}
    for fact, document, metadata in rows:
        key = fact.company_name_norm or (metadata.company_name_norm if metadata else "")
        if key and key not in best and fact.metric_value_num is not None:
            best[key] = (fact, document, metadata)
    ordered = list(best.values())
    descending = not any(token in message for token in ("\ub0ae", "\uc801\uc740", "\ucd5c\uc800")) and metric_name != "debt_ratio"
    ordered.sort(key=lambda item: item[0].metric_value_num or 0.0, reverse=descending)
    if companies:
        order = {name: idx for idx, name in enumerate(companies)}
        ordered.sort(key=lambda item: order.get(item[0].company_name_norm or "", 999))
    selected = ordered[: len(companies) if companies else int(variables.get("limit") or 5)]
    payload_rows = [_fact_row_payload(fact, document, metadata) for fact, document, metadata in selected]
    citations = [_build_citation(fact=fact, document=document, metadata=metadata) for fact, document, metadata in selected]
    # 각 row의 fiscal_year를 함께 표시 (per-company latest 정책일 때 비교 기준 명확화)
    ranking = ", ".join(
        f"{idx}. {row['company_name']} {row['value_display']}" + (f" ({row['fiscal_year']}년)" if row.get('fiscal_year') and not target_year else "")
        for idx, row in enumerate(payload_rows, start=1)
    )
    year_label = f"{target_year}\ub144 " if target_year else "\ud68c\uc0ac\ubcc4 \ucd5c\uc2e0 \uc5f0\ub3c4 \uae30\uc900 "
    evidence_year = f"{target_year}\ub144 \uac12" if target_year else "\ud68c\uc0ac\ubcc4 \uac00\uc7a5 \ucd5c\uadfc \uc5f0\ub3c4 \uac12"
    reply = "\n".join([f"{TXT_CONCLUSION}: {year_label}{_metric_label(metric_name)} \uae30\uc900 \uc21c\uc704\ub294 {ranking}\uc785\ub2c8\ub2e4.", "", TXT_EVIDENCE, f"1. \uad6c\uc870\ud654\ub41c \uc7ac\ubb34 \ud329\ud2b8 DB\uc5d0\uc11c {evidence_year}\uc744 \uc6b0\uc120 \uc870\ud68c\ud588\uc2b5\ub2c8\ub2e4.", f"2. \ube44\uad50 \uc9c0\ud45c\ub294 `{_metric_label(metric_name)}`\uc785\ub2c8\ub2e4.", "", TXT_RISK, "- \uc5f0\uacb0/\ubcc4\ub3c4 \uae30\uc900\uacfc \uacf5\uc2dc \ub204\ub77d\uc5d0 \ub530\ub77c \uccb4\uac10\uacfc \ub2e4\ub97c \uc218 \uc788\uc2b5\ub2c8\ub2e4." + ("" if target_year else "\n- \ud68c\uc0ac\ubcc4 \uae30\uc900 \uc5f0\ub3c4\uac00 \uc11e\uc77c \uc218 \uc788\uc73c\ubbc0\ub85c \uacf5\uc815 \ube44\uad50\ub294 \uc5f0\ub3c4\ub97c \uba85\uc2dc\ud574\uc8fc\uc138\uc694."), "", TXT_CONFIDENCE, "- INFERENCE [82%] - \uad6c\uc870\ud654\ub41c \uc22b\uc790 \uae30\ubc18 \ube44\uad50\uc785\ub2c8\ub2e4."])
    return {"reply": reply, "payload": {"type": "ranking", "route": ROUTE_RANKING_COMPARE, "criteria": {"metric_name": metric_name, "metric_label": _metric_label(metric_name), "fiscal_year": target_year, "policy": "per_company_latest" if not target_year else "single_year"}, "rows": payload_rows, "series": [], "citations": citations}, "citations": citations, "meta": {"intent": ROUTE_RANKING_COMPARE, "confidence": "INFERENCE [82%]", "evidence_count": len(citations)}}


def answer_trend(message: str, variables: dict[str, Any], db: Session, user_id: Optional[int] = None) -> dict[str, Any]:
    metric_name = resolve_query_metric(message, variables) or "revenue"
    if _is_derived_metric(metric_name):
        return _answer_derived_metric_trend(message, metric_name, variables, db, user_id=user_id)
    companies = [normalize_company_name_for_storage(name) for name in variables.get("companies", []) if name]
    latest = _latest_year(db, companies or None, user_id=user_id)
    years = list(range(max(2000, latest - int(variables.get("trend_span") or extract_trend_span(message)) + 1), latest + 1))
    rows = _facts_for_metric(db, metric_name, companies or None, years, user_id=user_id)
    if not rows:
        # ── Retrieval fallback: structured time-series unavailable, cite per-company chunks ──
        try:
            from services.cognitive_search_safe import cognitive_search_safe
            metric_label = _metric_label(metric_name)
            target_companies = companies[:3] if companies else []
            ev_lines: list[str] = []
            cits: list[dict[str, Any]] = []
            if target_companies:
                for c in target_companies:
                    sr = cognitive_search_safe(query=f"{c} {metric_label} \ucd94\uc774", top_k=3, company_filter=c, prefer_recent=True, user_id=user_id or 0)
                    for r in sr[:3]:
                        snippet = _clean_text(r.get("chunk", "") or "")[:180]
                        if not snippet:
                            continue
                        ev_lines.append(f"- {c}: {snippet}")
                        cits.append({"document_id": r.get("doc_id"), "filename": r.get("filename", ""), "company": r.get("company", "") or c, "source_text": snippet, "score": r.get("composite_score")})
            if ev_lines:
                reply = "\n".join([
                    f"{TXT_CONCLUSION}: {metric_label} \uc2dc\uacc4\uc5f4 \uad6c\uc870\ud654 \ud329\ud2b8\uac00 \ubd80\uc7ac\ud558\uc5ec \uac80\uc0c9 \uccad\ud06c\uc5d0\uc11c \uc9c1\uc811 \uc778\uc6a9\ud569\ub2c8\ub2e4.",
                    "",
                    TXT_EVIDENCE,
                    *ev_lines[:6],
                    "",
                    TXT_RISK,
                    "- \uc2dc\uacc4\uc5f4 \ube44\uad50\uac00 \uc544\ub2cc \uccad\ud06c\ubcc4 \ub2e8\ud3b8 \uc778\uc6a9. \uad6c\uc870\ud654 \ud329\ud2b8\uac00 \ubcf5\uc6d0\ub418\uba74 \uc815\ud655\ud55c \ucd94\uc774 \ube44\uad50 \uac00\ub2a5.",
                    "",
                    TXT_CONFIDENCE,
                    "- INFERENCE [55%] - \uad6c\uc870\ud654 \ud329\ud2b8 \ubd80\uc7ac fallback\uc785\ub2c8\ub2e4.",
                ])
                return {"reply": reply, "payload": {"type": "trend", "route": ROUTE_TREND, "criteria": {"metric_name": metric_name, "metric_label": metric_label, "years": years, "fallback": "retrieval"}, "rows": [], "series": [], "citations": cits}, "citations": cits, "meta": {"intent": ROUTE_TREND, "confidence": "INFERENCE [55%]", "evidence_count": len(cits)}}
        except Exception as exc:
            logger.warning("answer_trend retrieval fallback failed: %s", exc)
        return {"reply": TXT_NO_DATA, "payload": {"type": "trend", "route": ROUTE_TREND, "criteria": {"metric_name": metric_name, "metric_label": _metric_label(metric_name), "years": years}, "rows": [], "series": [], "citations": []}}
    grouped, citations = {}, []
    for fact, document, metadata in rows:
        if fact.metric_value_num is None or not fact.fiscal_year:
            continue
        grouped.setdefault(fact.company_name_norm or "", {})
        grouped[fact.company_name_norm or ""][fact.fiscal_year] = (fact, document, metadata)
    if not companies:
        companies = [name for name in grouped.keys() if name][:5]
    series = []
    for company in companies:
        points, display_name = [], company
        for year in years:
            item = grouped.get(company, {}).get(year)
            if not item:
                continue
            fact, document, metadata = item
            display_name = (metadata.company_name if metadata else "") or display_name
            points.append({"year": year, "value": fact.metric_value_num, "value_display": _format_value(fact.metric_value_num, fact.unit or "", fact.currency or ""), "document_id": document.id, "filename": document.filename})
            citations.append(_build_citation(fact=fact, document=document, metadata=metadata))
        if points:
            series.append({"company_name": display_name, "company_name_norm": company, "metric_name": metric_name, "metric_label": _metric_label(metric_name), "points": points})
    reply = "\n".join([f"{TXT_CONCLUSION}: {len(years)}\ub144 {_metric_label(metric_name)} {K_TREND}\uc785\ub2c8\ub2e4.", "", TXT_EVIDENCE] + [f"{idx}. {item['company_name']}: " + ", ".join(f"{point['year']}\ub144 {point['value_display']}" for point in item["points"]) for idx, item in enumerate(series[:3], start=1)] + ["", TXT_RISK, "- \uc5f0\ub3c4\ubcc4 \uacf5\uc2dc \ub204\ub77d\uc774 \uc788\uc73c\uba74 \uc2dc\uacc4\uc5f4\uc774 \ube44\uc5b4 \ubcf4\uc77c \uc218 \uc788\uc2b5\ub2c8\ub2e4.", "", TXT_CONFIDENCE, "- INFERENCE [78%] - \uc800\uc7a5\ub41c \uc5f0\ub3c4\ubcc4 \ud329\ud2b8 \uae30\uc900\uc785\ub2c8\ub2e4."])
    return {"reply": reply, "payload": {"type": "trend", "route": ROUTE_TREND, "criteria": {"metric_name": metric_name, "metric_label": _metric_label(metric_name), "years": years}, "rows": [], "series": series, "citations": citations}, "citations": citations, "meta": {"intent": ROUTE_TREND, "confidence": "INFERENCE [78%]", "evidence_count": len(citations)}}


def answer_company_summary(message: str, variables: dict[str, Any], db: Session, user_id: Optional[int] = None) -> dict[str, Any]:
    company = normalize_company_name_for_storage(variables.get("company") or (variables.get("companies") or [""])[0])
    if not company:
        return {"reply": TXT_NO_DATA, "payload": {"type": "summary", "route": ROUTE_COMPANY_SUMMARY, "criteria": {}, "rows": [], "series": [], "citations": []}}
    query = db.query(DocumentMetadata, Document).join(Document, Document.id == DocumentMetadata.document_id).filter(DocumentMetadata.company_name_norm == company)
    if user_id is not None:
        query = query.filter(Document.user_id == user_id)
    item = query.order_by(DocumentMetadata.fiscal_year.desc(), Document.id.desc()).first()
    metadata = item[0] if item else None
    document = item[1] if item else None
    rows, citations = [], []
    if metadata is not None:
        for metric_name in SUMMARY_METRICS:
            facts = _facts_for_metric(db, metric_name, [company], [metadata.fiscal_year] if metadata.fiscal_year else None, user_id=user_id)
            if facts:
                fact, fact_doc, fact_meta = facts[0]
                rows.append(_fact_row_payload(fact, fact_doc, fact_meta))
                citations.append(_build_citation(fact=fact, document=fact_doc, metadata=fact_meta))
    analysis = db.query(AnalysisResult).filter(AnalysisResult.document_id == document.id).order_by(AnalysisResult.id.desc()).first() if document is not None else None
    summary_line = [f"7. \ubb38\uc11c \uc694\uc57d: {_clean_text(analysis.summary)[:200]}"] if analysis and analysis.summary else []

    # ── Retrieval fallback: when structured facts AND analysis summary are both missing,
    #    pull evidence chunks directly from the vector store so the 근거 section is not empty.
    #    Also runs when DocumentMetadata lookup failed (e.g. alias mismatch like 무림P&P vs 무림PP)
    #    because cognitive_search_safe handles its own alias normalization.
    fallback_used = False
    if not rows and not summary_line:
        try:
            from services.cognitive_search_safe import cognitive_search_safe
            display_company = (metadata.company_name if metadata else "") or company
            search_query = f"{display_company} \ub9e4\ucd9c \uc601\uc5c5\uc774\uc775 \uc2e4\uc801 \uc7ac\ubb34"
            search_results = cognitive_search_safe(query=search_query, top_k=5, company_filter=display_company, user_id=user_id or 0)
            for result in search_results[:5]:
                snippet = _clean_text(result.get("chunk", "") or "")[:220]
                if not snippet:
                    continue
                rows.append({
                    "metric_label": result.get("filename", "") or "\ubb38\uc11c \uc778\uc6a9",
                    "value_display": snippet,
                    "fiscal_year": metadata.fiscal_year if metadata else None,
                    "company_name": display_company,
                    "filename": result.get("filename", ""),
                })
                citations.append({
                    "document_id": result.get("doc_id"),
                    "filename": result.get("filename", ""),
                    "company": result.get("company", "") or display_company,
                    "source_text": snippet,
                    "score": result.get("composite_score"),
                })
            fallback_used = bool(rows)
        except Exception as exc:
            logger.warning("answer_company_summary retrieval fallback failed: %s", exc)

    fiscal_year_value = metadata.fiscal_year if metadata else None
    display_company_final = (metadata.company_name if metadata else "") or company

    if not rows and not summary_line:
        return {"reply": TXT_NO_DATA, "payload": {"type": "summary", "route": ROUTE_COMPANY_SUMMARY, "criteria": {"company_name_norm": company, "fiscal_year": fiscal_year_value}, "rows": [], "series": [], "citations": []}, "citations": [], "meta": {"intent": ROUTE_COMPANY_SUMMARY, "confidence": "EXPLORATION [40%]", "evidence_count": 0}}

    if fallback_used:
        evidence_lines = [f"{idx}. {row['value_display']} ({row['filename'][:40]})" for idx, row in enumerate(rows[:5], start=1)]
        confidence_text = "INFERENCE [68%] - \uad6c\uc870\ud654 \ud329\ud2b8 \ubd80\uc7ac\ub85c \uac80\uc0c9 \uccad\ud06c\uc5d0\uc11c \uc9c1\uc811 \uc778\uc6a9\ud588\uc2b5\ub2c8\ub2e4."
    else:
        evidence_lines = [f"{idx}. {row['metric_label']}: {row['value_display']}" for idx, row in enumerate(rows[:6], start=1)] + summary_line
        confidence_text = "INFERENCE [80%] - \ucd5c\uc2e0 \uad6c\uc870\ud654 \ud329\ud2b8\uc640 \ubb38\uc11c \uc694\uc57d\uc744 \ud568\uaed8 \uc0ac\uc6a9\ud588\uc2b5\ub2c8\ub2e4."

    reply = "\n".join([f"{TXT_CONCLUSION}: {display_company_final}\uc758 \ucd5c\uc2e0 \ubb38\uc11c \uae30\uc900 \ud575\uc2ec \uc7ac\ubb34\uc785\ub2c8\ub2e4.", "", TXT_EVIDENCE] + evidence_lines + ["", TXT_RISK, "- \ubc18\uae30/\ubd84\uae30 \uacf5\uc2dc\ub97c \uc5f0\uac04 \uc218\uce58\uc640 \uc9c1\uc811 \ube44\uad50\ud558\uba74 \uc65c\uace1\ub420 \uc218 \uc788\uc2b5\ub2c8\ub2e4.", "", TXT_CONFIDENCE, f"- {confidence_text}"])
    return {"reply": reply, "payload": {"type": "summary", "route": ROUTE_COMPANY_SUMMARY, "criteria": {"company_name": display_company_final, "company_name_norm": company, "fiscal_year": fiscal_year_value, "fallback": "retrieval" if fallback_used else ""}, "rows": rows, "series": [], "citations": citations}, "citations": citations, "meta": {"intent": ROUTE_COMPANY_SUMMARY, "confidence": "INFERENCE [68%]" if fallback_used else "INFERENCE [80%]", "evidence_count": len(citations)}}


def answer_qa(message: str, variables: dict[str, Any], db: Session, user_id: Optional[int] = None) -> dict[str, Any]:
    company = normalize_company_name_for_storage(variables.get("company") or (variables.get("companies") or [""])[0])
    metric_name = resolve_query_metric(message, variables)
    if company and metric_name and _is_derived_metric(metric_name):
        return _answer_derived_metric_qa(message, metric_name, variables, db, user_id=user_id)
    years = [int(year) for year in variables.get("year_filters", []) if str(year).isdigit()]
    if company and metric_name:
        rows = _facts_for_metric(db, metric_name, [company], years or None, user_id=user_id)
        if rows:
            fact, document, metadata = rows[0]
            row = _fact_row_payload(fact, document, metadata)
            citation = _build_citation(fact=fact, document=document, metadata=metadata)
            fiscal_year_label = f"{row['fiscal_year']}\ub144" if row.get("fiscal_year") else "\ubbf8\uc0c1"
            reply = "\n".join([f"{TXT_CONCLUSION}: {row['company_name']}\uc758 {row['metric_label']}\uc740 {row['value_display']}\uc785\ub2c8\ub2e4.", "", TXT_EVIDENCE, f"1. \uae30\uc900 \uc5f0\ub3c4: {fiscal_year_label}", f"2. \ubb38\uc11c: {row['filename']}", "", TXT_RISK, "- \uc5f0\uacb0/\ubcc4\ub3c4 \uae30\uc900 \ucc28\uc774\uac00 \uc788\uc744 \uc218 \uc788\uc2b5\ub2c8\ub2e4.", "", TXT_CONFIDENCE, "- INFERENCE [84%] - \uad6c\uc870\ud654\ub41c \uc218\uce58\uac00 \uc9c1\uc811 \uc870\ud68c\ub418\uc5c8\uc2b5\ub2c8\ub2e4."])
            return {"reply": reply, "payload": {"type": "qa", "route": ROUTE_QA, "criteria": {"company_name": row["company_name"], "company_name_norm": company, "metric_name": metric_name, "metric_label": _metric_label(metric_name)}, "rows": [row], "series": [], "citations": [citation]}, "citations": [citation], "meta": {"intent": ROUTE_QA, "confidence": "INFERENCE [84%]", "evidence_count": 1}}
        if metric_name in {"treasury_stock_amount", "capital_raise_amount", "capex"}:
            reply = "\n".join(
                [
                    f"{TXT_CONCLUSION}: {company}\uc758 {_metric_label(metric_name)}\uc740 \ud604\uc7ac \uad6c\uc870\ud654 \ud329\ud2b8\ub85c \uc989\uc2dc \ud655\uc815\ud558\uae30 \uc5b4\ub835\uc2b5\ub2c8\ub2e4.",
                    "",
                    TXT_EVIDENCE,
                    "1. \ud574\ub2f9 \uc9c0\ud45c\ub294 \uc8fc\ub2f9 \uac00\uaca9\uacfc \ucd1d\uc561\uc774 \ud63c\uc7ac\ub418\uae30 \uc26c\uc6cc \uc18c\uc561 \uc218\uce58\ub97c \uc81c\uc678\ud558\uace0 \uc788\uc2b5\ub2c8\ub2e4.",
                    "",
                    TXT_RISK,
                    "- \ubb38\uc11c \uc6d0\ubb38 \uae30\uc900 \ucd1d\uc561 \ud45c\ud604(\ucde8\ub4dd\uae08\uc561/\ucc98\ubd84\uae08\uc561/\uacc4\uc57d\uae08\uc561)\uc744 \ub2e4\uc2dc \ud655\uc778\ud574\uc57c \ud569\ub2c8\ub2e4.",
                    "",
                    TXT_CONFIDENCE,
                    "- INFERENCE [68%] - \ud604\uc7ac \uc800\uc7a5\ub41c \uc18c\uc561 \uc218\uce58\ub294 \uc624\ud0d0 \uac00\ub2a5\uc131\uc774 \ud07d\ub2c8\ub2e4.",
                ]
            )
            return {
                "reply": reply,
                "payload": {"type": "qa", "route": ROUTE_QA, "criteria": {"company_name_norm": company, "metric_name": metric_name, "needs_verification": True}, "rows": [], "series": [], "citations": []},
                "citations": [],
                "meta": {"intent": ROUTE_QA, "confidence": "INFERENCE [68%]", "evidence_count": 0},
            }

    # ── Retrieval fallback: structured facts missing, fall back to cognitive_search chunks ──
    if company:
        try:
            from services.cognitive_search_safe import cognitive_search_safe
            metric_label = _metric_label(metric_name) if metric_name else "\uc7ac\ubb34"
            search_query = f"{company} {metric_label} {message}"[:200]
            sr = cognitive_search_safe(query=search_query, top_k=3, company_filter=company, user_id=user_id or 0)
            ev_lines: list[str] = []
            cits: list[dict[str, Any]] = []
            for idx, r in enumerate(sr[:3], start=1):
                snippet = _clean_text(r.get("chunk", "") or "")[:200]
                if not snippet:
                    continue
                fname = r.get("filename", "") or ""
                ev_lines.append(f"{idx}. {snippet}" + (f" ({fname[:35]})" if fname else ""))
                cits.append({"document_id": r.get("doc_id"), "filename": fname, "company": r.get("company", "") or company, "source_text": snippet, "score": r.get("composite_score")})
            if ev_lines:
                reply = "\n".join([
                    f"{TXT_CONCLUSION}: {company}\uc758 {metric_label} \uad6c\uc870\ud654 \ud329\ud2b8\uac00 \ubd80\uc7ac\ud558\uc5ec \uac80\uc0c9 \uccad\ud06c\uc5d0\uc11c \uc9c1\uc811 \uc778\uc6a9\ud569\ub2c8\ub2e4.",
                    "",
                    TXT_EVIDENCE,
                    *ev_lines,
                    "",
                    TXT_RISK,
                    "- \uccad\ud06c \ud14d\uc2a4\ud2b8 \uc778\uc6a9\uc73c\ub85c, \uc815\ub7c9 \ube44\uad50 \uc2dc \uc815\ud569\uc131 \ubcc4\ub3c4 \ud655\uc778 \ud544\uc694.",
                    "- \ud68c\uacc4 \uae30\uc900(\uc5f0\uacb0/\ubcc4\ub3c4, \ubc18\uae30/\uc5f0\uac04) \ucc28\uc774\ub85c \uc9c1\uc811 \ube44\uad50\uac00 \uc65c\uace1\ub420 \uc218 \uc788\uc2b5\ub2c8\ub2e4.",
                    "",
                    TXT_CONFIDENCE,
                    "- INFERENCE [60%] - \uad6c\uc870\ud654 \ud329\ud2b8 \ubd80\uc7ac fallback\uc785\ub2c8\ub2e4.",
                ])
                return {"reply": reply, "payload": {"type": "qa", "route": ROUTE_QA, "criteria": {"company_name": company, "company_name_norm": company, "metric_name": metric_name or "", "metric_label": metric_label, "fallback": "retrieval"}, "rows": [], "series": [], "citations": cits}, "citations": cits, "meta": {"intent": ROUTE_QA, "confidence": "INFERENCE [60%]", "evidence_count": len(cits)}}
        except Exception as exc:
            logger.warning("answer_qa retrieval fallback failed: %s", exc)

    return {"reply": TXT_NO_DATA, "payload": {"type": "qa", "route": ROUTE_QA, "criteria": {"query": message}, "rows": [], "series": [], "citations": []}, "citations": [], "meta": {"intent": ROUTE_QA, "confidence": "EXPLORATION [35%]", "evidence_count": 0}}
