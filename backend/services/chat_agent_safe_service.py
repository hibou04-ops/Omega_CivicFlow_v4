from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

import httpx
from sqlalchemy import func, or_

logger = logging.getLogger("omega.chat_agent")

from config import settings
from models.models import AnalysisResult, CompanyProfile, Document, DocumentMetadata, FinancialFact
from services.agent_retrieval import CivicFlowRetriever
from services.company_alias_master import COMPANY_ALIASES, aliases_for_company
from services.chat_knowledge_service import (
    ROUTE_COMPANY_SUMMARY,
    ROUTE_QA,
    ROUTE_RANKING_COMPARE,
    ROUTE_TREND,
    STOCK_OUTLOOK_SLOT_LABELS,
    SUMMARY_METRICS,
    answer_company_summary,
    answer_qa,
    answer_ranking_compare,
    answer_trend,
    classify_stock_outlook_support,
    evaluate_stock_outlook_coverage,
    extract_limit_from_query,
    extract_trend_span,
    normalize_company_name_for_storage,
    resolve_query_metric,
)
from services.chat_knowledge_service import (
    _facts_for_metric as _kb_facts_for_metric,
    _format_value as _kb_format_value,
    _latest_year as _kb_latest_year,
    _metric_label as _kb_metric_label,
)
from services.chat_profile_service import get_chatbot_profile
from agents.llm_client import OllamaLLMClient

_llm_client_singleton: OllamaLLMClient | None = None


def _get_llm_client() -> OllamaLLMClient:
    global _llm_client_singleton
    if _llm_client_singleton is None:
        _llm_client_singleton = OllamaLLMClient()
    return _llm_client_singleton

ROUTE_STOCK_OUTLOOK = "stock_outlook"
INTENT_DOCUMENT_QA = "document_qa"

RAG_R0 = "R0"
RAG_R1 = "R1"
RAG_R2 = "R2"
RAG_R3 = "R3"

TXT_NO_DATA = "\uc790\ub8cc \ubd80\uc871"
TXT_CONCLUSION = "**\uacb0\ub860**"
TXT_EVIDENCE = "**\uadfc\uac70**"
TXT_RISK = "**\ub9ac\uc2a4\ud06c**"
TXT_CONFIDENCE = "**\ud655\uc2e0\ub3c4**"

GREETING_PATTERNS = (
    "\uc548\ub155",
    "\uc548\ub155\ud558\uc138\uc694",
    "\uc548\ub1fd",
    "\uc548\ub1fd\ud558\uc138\uc694",
    "\uc778\ub0e5",
    "\uc778\ub155",
    "\u314e\u3147",
    "\u3147\u3134",
    "hi",
    "hello",
    "hey",
)
IDENTITY_PATTERNS = (
    "\ub10c \ubb50\uc57c",
    "\ub10c\ubb50\uc57c",
    "\ub10c \ubb50\uc5ec",
    "\ub10c\ubb50\uc5ec",
    "\ub108 \ubb50\uc57c",
    "\ub108\ubb50\uc57c",
    "\ub108\ub294 \ubb50\uc57c",
    "\ub10c \ub204\uad6c",
    "\ub108 \ub204\uad6c",
    "\ub204\uad6c\uc57c",
    "\ub204\uad6c\uc138\uc694",
    "\uc815\uccb4\uac00",
    "\uc815\uccb4\ub294",
    "\ubb34\uc2a8 \ubaa8\ub378",
    "\uc5b4\ub5a4 \ubaa8\ub378",
    "\uc5b4\ub5a4 ai",
    "\ubb34\uc2a8 ai",
    "\uc774 \ucc57\ubd07",
    "\uc774 \ubd07",
    "\ub2c8 \uc774\ub984",
    "\uc774\ub984\uc774 \ubb50",
    "\ucc57\ubd07 \uc774\ub984",
    "ai\uc57c",
    "ai\uc785\ub2c8\uae4c",
    "what are you",
    "who are you",
    "what is this",
    "who r u",
)
CAPABILITY_KEYWORDS = (
    "\ubb34\uc5c7\uc744 \ud560 \uc218",
    "\ubb50 \ud560 \uc218",
    "\ubed8 \ud560 \uc218",
    "\uc9c8\ubb38 \uc608\uc2dc",
    "\uc5b4\ub5bb\uac8c \ubb3c\uc5b4",
    "\uc5b4\ub5a4 \ud615\uc2dd",
    "\uc785\ub825 \ud615\uc2dd",
    "\uae30\ub2a5 \uc124\uba85",
)
HELP_REQUEST_PATTERNS = (
    "\ub3c4\uc640\uc918",
    "\ub3c4\uc640\uc918\uc694",
    "\ub3c4\uc640\uc8fc\uc138\uc694",
    "\ub3c4\uc640\ub2ec",
    "\ub3c4\uc640\uc8fc",
    "\ub3c4\uc6c0",
    "\ub3c4\uc640\uc904",
    "\ub3c4\uc640\uc8e4",
    "\ub3c4\uc640",
    "\ub3c4\uc6c0\uc774 \ud544",
    "\ub3c4\uc640\uc8fc\uc2e4",
    "\ud5ec\ud504",
    "help me",
    "help",
    "\uac00\uc774\ub4dc",
    "\uc0ac\uc6a9\ubc95",
    "\uc4f0\ub294 \ubc95",
    "\uc4f0\uace0\uc2f6\uc740\ub370",
)
PRODUCT_KEYWORDS = (
    "\ubb38\uc11c\ub294 \uc5b4\ub5bb\uac8c",
    "\ubb38\uc11c\ub294 \uc5b4\ub514",
    "\uc5c5\ub85c\ub4dc \ubc29\ubc95",
    "\uc5c5\ub85c\ub4dc\ub294",
    "\uc5b4\ub5a4 \uae30\ub2a5",
    "\ubb50 \ud560 \uc218",
)
INPUT_HELP_KEYWORDS = (
    "\ud68c\uc0ac\uba85 \ub2e4\uc2dc",
    "\ud68c\uc0ac\uba85\uc744 \ub2e4\uc2dc",
    "\ud68c\uc0ac\uba85 \uc801\uc5b4",
    "\ud68c\uc0ac\uba85\uc744 \uc801\uc5b4",
    "\ud68c\uc0ac\uba85 \uc785\ub825",
)
TIME_KEYWORDS = (
    "\uba87 \uc2dc",
    "\ud604\uc7ac \uc2dc\uac04",
    "\uc9c0\uae08 \uc2dc\uac04",
    "\uc624\ub298 \ub0a0\uc9dc",
    "\uc624\ub298 \uba87 \uc77c",
)
DOC_STATS_KEYWORDS = (
    "\ubb38\uc11c \uc218",
    "\ubb38\uc11c \uba87 \uac1c",
    "\uc5c5\ub85c\ub4dc \uc218",
    "\ud1b5\uacc4",
    "\ubb38\uc11c \ud1b5\uacc4",
)
COMPANY_STATS_KEYWORDS = (
    "\ud68c\uc0ac \uc885\ub958",
    "\ud68c\uc0ac \uba87 \uac1c",
    "\ub4f1\ub85d\ub41c \ud68c\uc0ac",
    "\uacf5\uc2dc\ub4f1\ub85d\ub41c \ud68c\uc0ac",
    "\ubb38\uc11c\uc5d0 \uc788\ub294 \ud68c\uc0ac",
    "\ud68c\uc0ac \uc218",
)
COMPANY_COUNT_KEYWORDS = (
    "\uba87 \uac1c",
    "\uac1c\uc218",
    "\uac2f\uc218",
    "\uc218",
    "\ucd1d",
    "\uc804\uccb4",
    "\uc885\ub958",
)
COMPANY_SCOPE_KEYWORDS = (
    "\ud68c\uc0ac",
    "\uacf5\uc2dc",
    "\ubb38\uc11c",
    "\ub4f1\ub85d",
)
DOC_SEARCH_KEYWORDS = (
    "\ubb38\uc11c \uac80\uc0c9",
    "\ubb38\uc11c \ucc3e\uc544",
    "\ub0b4 \ubb38\uc11c",
    "\uc5c5\ub85c\ub4dc \ubb38\uc11c",
)
SCAN_KEYWORDS = (
    "\uc8fc\ubaa9",
    "\ub208\uc5d0 \ub744\ub294",
    "\ub208\uc5d0\ub744\ub294",
    "\ub208\uc5d0 \ub744",
    "\ub208\uc5d0\ub744",
    "\ub208\uc5d0 \ub760",
    "\ub208\uc5d0\ub760",
    "\ub9cc\ud55c\uac83",
    "\ub9cc\ud55c \uac83",
    "\uc774\uc288",
    "\ud2b9\uc774\uc0ac\ud56d",
)
OUTLOOK_KEYWORDS = (
    "\uc804\ub9dd",
    "\uc8fc\uac00",
    "\uc624\ub97c\uae4c",
    "\ub0b4\ub9b4\uae4c",
    "\uad1c\ucc2e\uc544",
    "\uc0b4\uae4c",
    "\ub9e4\uc218",
    "\ucd94\ucc9c",
    "\ubc38\ub958",
    "\ub9ac\uc2a4\ud06c",
    "\uc5c5\ud669",
)
RANKING_KEYWORDS = ("top", "\uc0c1\uc704", "\uc21c\uc704", "\ube44\uad50", "vs", "\ub204\uac00 \ub354", "\ub354 \ub0ab")
# Context Mismatch Guard: \uc774\ubca4\ud2b8\ud615 \uc9c8\uc758(\uc0c1\uc7a5\ud3d0\uc9c0\u00b7\uac10\uc0ac\uc758\uacac \ub4f1) \ud0d0\uc9c0\uc6a9
EVENT_SIGNAL_KEYWORDS = (
    "\uc0c1\uc7a5\ud3d0\uc9c0", "\uad00\ub9ac\uc885\ubaa9", "\uac10\uc0ac\uc758\uacac", "\ubd80\uc801\uc815", "\ud55c\uc815\uc758\uacac",
    "\uc790\ubcf8\uc7a0\uc2dd", "\uacf5\uc2dc\uc704\ubc18", "\ubd88\uc131\uc2e4\uacf5\uc2dc", "\uacf5\uc2dc\ubc88\ubcf5",
    "\ud6a1\ub839", "\ubc30\uc784", "\ubd80\ub3c4", "\ud68c\uc0dd", "\ud30c\uc0b0", "\uac70\ub798\uc815\uc9c0", "\uac70\ub798\uc7ac\uac1c",
)
REASON_SIGNAL_KEYWORDS = ("\uc0ac\uc720", "\uc774\uc720", "\uc6d0\uc778", "\ubc1c\uc0dd", "\uc9c0\uc815", "\ucde8\uc18c", "\ud574\uc9c0", "\uc704\ubc18")
TREND_KEYWORDS = ("\ucd5c\uadfc", "\ucd94\uc138", "\ud750\ub984", "trend", "\ub144\uac04", "\ubd84\uae30\ubcc4")
SUMMARY_KEYWORDS = ("\uc694\uc57d", "\uc815\ub9ac", "\uc7ac\ubb34", "\uc2e4\uc801", "\uac1c\uc694")
DOCUMENT_QA_KEYWORDS = (
    "\ubb38\uc11c",
    "\uacf5\uc2dc",
    "\uadfc\uac70",
    "\ucd9c\ucc98",
    "\uc65c",
    "\uc5b4\ub514",
    "capex",
    "\ucea1\uc5d1\uc2a4",
    "\ub9ac\uc2a4\ud06c",
    "\uc124\uba85",
)
RECOMMEND_KEYWORDS = (
    "\ucd94\ucc9c\ud574",
    "\ucd94\ucc9c\ud574\uc918",
    "\uc88b\uc740 \uae30\uc5c5",
    "\uc0b4\ub9cc\ud55c",
    "\ub9e4\uc218 \ucd94\ucc9c",
)
FOLLOW_PREFIXES = (
    "\uadf8\ub7fc",
    "\uadf8 \ud68c\uc0ac",
    "\uadf8 \uae30\uc5c5",
    "\uadf8\uac74",
    "\uac54\ub294",
    "\uadf8\ub7ec\uba74",
    "\uadf8\ucabd",
)
BALANCE_ONLY_KEYWORDS = (
    "\uc790\uc0b0\ucd1d\uacc4",
    "\ubd80\ucc44\ucd1d\uacc4",
    "\uc790\ubcf8\ucd1d\uacc4",
    "\ubd80\ucc44\ube44\uc728",
    "\uc720\ub3d9\uc790\uc0b0",
    "\ube44\uc720\ub3d9\uc790\uc0b0",
)

STATIC_COMPANY_ALIASES = dict(COMPANY_ALIASES)

GENERIC_QUERY_STOPWORDS = {
    "\ucd5c\uadfc",
    "\uc791\ub144",
    "\uc62c\ud574",
    "\ub0b4\ub144",
    "\uc2e4\uc801",
    "\uc7ac\ubb34",
    "\uc694\uc57d",
    "\uc815\ub9ac",
    "\ucd94\uc138",
    "\ud750\ub984",
    "\ube44\uad50",
    "\uc0c1\uc704",
    "\uc21c\uc704",
    "\uc88b\uc740",
    "\uae30\uc5c5",
    "\uc8fc\uac00",
    "\uc804\ub9dd",
    "\ub9ac\uc2a4\ud06c",
    "\uadfc\uac70",
    "\ucd9c\ucc98",
    "\ubb38\uc11c",
    "\uacf5\uc2dc",
    "\ucd94\ucc9c",
    "\ub9e4\ucd9c",
    "\uc601\uc5c5\uc774\uc775",
    "\uc21c\uc774\uc775",
    "\uc790\uc0b0",
    "\ubd80\ucc44",
    "\uc790\ubcf8",
    "\ubd80\ucc44\ube44\uc728",
    "\uc790\uae30\uc8fc\uc2dd",
    "\uc720\uc0c1\uc99d\uc790",
    "capex",
}


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result: list[str] = []
    for item in items:
        cleaned = re.sub(r"\s+", " ", str(item or "").strip())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _clean_text(text: str, limit: int = 220) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def _compact(text: str) -> str:
    t = str(text or "").lower()
    t = t.replace("피앤피", "pp").replace("p&p", "pp").replace("피엔피", "pp")
    try:
        from services.stock_name_normalizer import PHONETIC_TO_ENGLISH
        for phonetic, eng in PHONETIC_TO_ENGLISH.items():
            t = t.replace(phonetic, eng.lower())
    except ImportError:
        pass
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]+", "", t)


def _last_user(history: list[dict[str, Any]]) -> str:
    for item in reversed(history or []):
        if (item.get("role") or item.get("sender")) == "user":
            return str(item.get("content") or item.get("text") or "")
    return ""


def _meta_examples(profile: dict[str, Any]) -> str:
    return "\n".join(f"- {item}" for item in [str(x).strip() for x in profile.get("example_queries", []) if str(x).strip()][:3])


def _looks_like_greeting(message: str) -> bool:
    stripped = (message or "").strip().lower()
    compact = _compact(stripped)
    if not compact or len(compact) > 8:
        return False
    if any(stripped == pattern or stripped.startswith(pattern + " ") for pattern in GREETING_PATTERNS):
        return True
    compact_patterns = {_compact(pattern) for pattern in GREETING_PATTERNS}
    if compact in compact_patterns:
        return True
    for pattern in compact_patterns:
        if len(pattern) >= 2 and SequenceMatcher(None, compact, pattern).ratio() >= 0.74:
            return True
    return False


def _looks_like_company_stats_query(message: str) -> bool:
    stripped = _clean_text(message, 300)
    if any(keyword in stripped for keyword in COMPANY_STATS_KEYWORDS):
        return True
    has_scope = any(keyword in stripped for keyword in COMPANY_SCOPE_KEYWORDS)
    has_count = any(keyword in stripped for keyword in COMPANY_COUNT_KEYWORDS)
    return has_scope and has_count


def _meta_reply(kind: str, profile: dict[str, Any]) -> dict[str, Any]:
    examples = _meta_examples(profile)
    if kind == "greeting":
        reply = "\n".join(
            [
                "\uc548\ub155\ud558\uc138\uc694. Node Omega-Prime\uc785\ub2c8\ub2e4.",
                "\uc5c5\ub85c\ub4dc\ub41c \uacf5\uc2dc/\uc7ac\ubb34\uc81c\ud45c \ubb38\uc11c\ub97c \uadfc\uac70\ub85c \uae30\uc5c5 \uc2e4\uc801\u00b7\ube44\uad50\u00b7\ucd94\uc138\u00b7\uacf5\uc2dc\ub97c \ubd84\uc11d\ud574 \ub4dc\ub9bd\ub2c8\ub2e4.",
                "",
                "\uc608\uc2dc \uc9c8\ubb38:",
                examples or "- \uc0bc\uc131\uc804\uc790 \ucd5c\uadfc 3\ub144 \ub9e4\ucd9c \ucd94\uc774\n- \uc0bc\uc131\uc804\uc790 vs SK\ud558\uc774\ub2c9\uc2a4 \uc601\uc5c5\uc774\uc775 \ube44\uad50\n- \ub124\uc774\ubc84 \ucd5c\uadfc \uacf5\uc2dc \uc694\uc57d",
            ]
        ).strip()
    elif kind == "identity":
        reply = "\n".join(
            [
                "\uc800\ub294 **Node Omega-Prime**\uc785\ub2c8\ub2e4. Omega CivicFlow\uc758 \ubb38\uc11c \uae30\ubc18 \uae30\uc5c5 \uc7ac\ubb34 \ubd84\uc11d \ucc57\ubd07\uc774\uc8e0.",
                "",
                "**\ud560 \uc218 \uc788\ub294 \uac83**:",
                "- \uc5c5\ub85c\ub4dc\ub41c DART \uacf5\uc2dc\u00b7\uc7ac\ubb34\uc81c\ud45c\u00b7\uc0ac\uc5c5\ubcf4\uace0\uc11c\uc5d0\uc11c \uc218\uce58 \ucd94\ucd9c",
                "- \ud2b9\uc815 \uae30\uc5c5\uc758 \uc2e4\uc801 \uc694\uc57d, \uc5f0\ub3c4\ubcc4 \ucd94\uc138, \uacbd\uc7c1\uc0ac \ube44\uad50",
                "- \uacf5\uc2dc \uac80\uc0c9\uacfc \ubb38\uc11c \ub0b4 \uadfc\uac70 \uc778\uc6a9",
                "",
                "**\uc798 \ubabb\ud558\ub294 \uac83**: \uc774\ubca4\ud2b8\u00b7\ub274\uc2a4 \ubaa8\ub2c8\ud130\ub9c1, \ubbf8\ub798 \uc8fc\uac00 \uc608\uce21, \uc544\uc9c1 \uc5c5\ub85c\ub4dc \uc548 \ub41c \uae30\uc5c5\uc758 \uc815\ubcf4.",
                "",
                "\ubb50\ub4e0 \ubb3c\uc5b4\ubcf4\uc138\uc694. \uc608: \"\uc0bc\uc131\uc804\uc790 \uc791\ub144 \ub9e4\ucd9c\", \"\ub124\uc774\ubc84 vs \uce74\uce74\uc624 \uc601\uc5c5\uc774\uc775\".",
            ]
        ).strip()
    elif kind in {"capability_help", "product_help"}:
        reply = "\n".join(
            [
                "\ub3c4\uc640\ub4dc\ub9b4\uac8c\uc694. \uc800\ub294 \uc5c5\ub85c\ub4dc\ub41c **\uae30\uc5c5 \ubb38\uc11c**\ub97c \uadfc\uac70\ub85c \ub2f5\ubcc0\ud558\ub294 \ubd84\uc11d \ucc57\ubd07\uc785\ub2c8\ub2e4.",
                "",
                "**\uc774\ub807\uac8c \ubb3c\uc5b4\ubcf4\uc138\uc694**:",
                "- `\uc0bc\uc131\uc804\uc790 \uc791\ub144 \uc2e4\uc801` \u2014 \ub2e8\uc77c \uae30\uc5c5 \uc694\uc57d",
                "- `\ub124\uc774\ubc84 \ucd5c\uadfc 3\ub144 \ub9e4\ucd9c \ucd94\uc774` \u2014 \uc5f0\ub3c4\ubcc4 \ucd94\uc138",
                "- `\uc0bc\uc131\uc804\uc790 vs SK\ud558\uc774\ub2c9\uc2a4 \uc601\uc5c5\uc774\uc775` \u2014 \ub2e4\uc911 \uae30\uc5c5 \ube44\uad50",
                "- `\uce74\uce74\uc624 \ucd5c\uadfc \uacf5\uc2dc` \u2014 DART \uacf5\uc2dc \uac80\uc0c9",
                "",
                "**\ud301**: \ud68c\uc0ac\uba85\ub9cc \uc801\uc5b4\ub3c4 \uc790\ub3d9 \uc694\uc57d\uc744 \uc2dc\ub3c4\ud569\ub2c8\ub2e4. \uc88c\uce21 \ubb38\uc11c \ud328\ub110\uc5d0\uc11c \ubb38\uc11c\ub97c \uba3c\uc800 \uc5c5\ub85c\ub4dc\ud574 \uc8fc\uc138\uc694.",
            ]
        ).strip()
    else:
        reply = "\n".join(
            [
                "\uc774 \uc9c8\ubb38\uc740 \ud604\uc7ac \ubd84\uc11d \ubc94\uc704 \ubc16\uc5d0 \uc788\uc2b5\ub2c8\ub2e4.",
                "\uc800\ub294 \uc5c5\ub85c\ub4dc\ub41c **\uac1c\ubcc4 \uae30\uc5c5 \ubb38\uc11c**\ub97c \uadfc\uac70\ub85c \ub2f5\ubcc0\ud558\uba70, \uc774\ubca4\ud2b8 \uc9d1\uacc4(\uc0c1\uc7a5\ud3d0\uc9c0 \ubaa9\ub85d \ub4f1)\ub098 \ub274\uc2a4 \uc9d1\uc801\uc740 \uc544\uc9c1 \uc9c0\uc6d0\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.",
                "",
                "\ub300\uc2e0 \uc774\ub7f0 \uc9c8\ubb38\uc740 \uac00\ub2a5\ud574\uc694:",
                "- `\ud2b9\uc815\uae30\uc5c5 \uc2e4\uc801` / `\ud2b9\uc815\uae30\uc5c5 vs \ub2e4\ub978\uae30\uc5c5` / `\ud2b9\uc815\uae30\uc5c5 \ucd5c\uadfc \uacf5\uc2dc`",
            ]
        ).strip()
    return {
        "reply": reply,
        "tools_used": [],
        "meta": {"intent": kind, "confidence": "CONSENSUS [90%]", "evidence_count": 0, "rag_density": RAG_R0, "company_binding": "unresolved"},
    }


def _extract_year_filters(query: str) -> tuple[list[str], bool]:
    current_year = datetime.now().year
    explicit = _dedupe(re.findall(r"(20\d{2})", query))
    recent = re.search("\ucd5c\uadfc\\s*(\\d+)\\s*\ub144", query)
    if recent:
        span = max(1, min(int(recent.group(1)), 5))
        return [str(year) for year in range(current_year - span + 1, current_year + 1)], True
    if explicit:
        return explicit, False
    if "\uc791\ub144" in query:
        return [str(current_year - 1)], True
    if "\uc62c\ud574" in query or "\uae08\ub144" in query:
        return [str(current_year)], True
    if "\ucd5c\uadfc" in query:
        return [str(current_year - 1), str(current_year)], True
    return [], False


def _extract_time_horizon(query: str) -> str:
    if any(token in query for token in ("\uc7a5\uae30", "3\ub144", "5\ub144")):
        return "long_term"
    if any(token in query for token in ("\uc911\uae30", "6\uac1c\uc6d4", "1\ub144")):
        return "mid_term"
    if any(token in query for token in ("\ub2e8\uae30", "\ub2f9\uc7a5", "\uc774\ubc88\ub2ec", "\uc774\ubc88 \ubd84\uae30")):
        return "short_term"
    if any(token in query for token in OUTLOOK_KEYWORDS):
        return "short_to_mid_term"
    return "current"


def _load_listed_corps() -> list[tuple[str, str, str]]:
    try:
        from routers.panel import _LISTED_CORPS

        return list(_LISTED_CORPS)
    except Exception:
        return []


def _query_terms(query: str) -> list[str]:
    cleaned = re.sub(r"[^0-9A-Za-z\uac00-\ud7a3]+", " ", query or "")
    tokens: list[str] = []
    for token in cleaned.split():
        if len(token) < 2 or token in GENERIC_QUERY_STOPWORDS:
            continue
        tokens.append(token)
    return _dedupe(sorted(tokens, key=len, reverse=True))


def _candidate_entry(canonical: str, display: str = "", *, corp_code: str = "", source: str = "", binding: str = "authoritative", score: float = 0.0) -> dict[str, Any]:
    normalized = normalize_company_name_for_storage(canonical or display)
    return {"canonical": normalized, "display": display or normalized, "corp_code": corp_code, "source": source, "binding": binding, "score": score}


def _merge_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = normalize_company_name_for_storage(item.get("canonical") or item.get("display") or "")
        if not key:
            continue
        current = merged.get(key)
        if current is None or float(item.get("score", 0)) > float(current.get("score", 0)):
            merged[key] = {**item, "canonical": key, "display": item.get("display") or key}
    return sorted(merged.values(), key=lambda item: (float(item.get("score", 0)), len(item.get("canonical", ""))), reverse=True)


def _static_alias_matches(query: str) -> list[dict[str, Any]]:
    compact_query = _compact(query)
    matches: list[dict[str, Any]] = []
    for alias, canonical in STATIC_COMPANY_ALIASES.items():
        alias_key = _compact(alias)
        if alias_key and len(alias_key) >= 2 and alias_key in compact_query:
            matches.append(_candidate_entry(canonical, canonical, source="static_alias", binding="authoritative", score=98 + min(len(alias_key), 10) * 0.01))
    return _merge_candidates(matches)


def _dart_matches(query: str) -> list[dict[str, Any]]:
    compact_query = _compact(query)
    matches: list[dict[str, Any]] = []
    
    for corp_name, corp_code, stock_code in _load_listed_corps():
        corp_key = _compact(corp_name)
        if not corp_key:
            continue
            
        if stock_code and query.strip() == stock_code:
            matches.append(_candidate_entry(corp_name, corp_name, corp_code=corp_code, source="dart_stock_code", binding="authoritative", score=100))
        elif corp_key == compact_query:
            matches.append(_candidate_entry(corp_name, corp_name, corp_code=corp_code, source="dart_listed", binding="authoritative", score=95))
        elif corp_key in compact_query:
            ratio = len(corp_key) / len(compact_query) if compact_query else 0
            matches.append(_candidate_entry(corp_name, corp_name, corp_code=corp_code, source="dart_listed", binding="candidate_confirmed" if ratio > 0.9 else "candidate_unconfirmed", score=70 + ratio * 20))
        elif len(compact_query) >= 2 and corp_key.startswith(compact_query):
            matches.append(_candidate_entry(corp_name, corp_name, corp_code=corp_code, source="dart_prefix", binding="candidate_unconfirmed", score=65))
            
    return _merge_candidates(matches)


def _db_authoritative_matches(query: str, db, user_id: int | None = None) -> list[dict[str, Any]]:
    terms = _query_terms(query)
    if not terms:
        return []

    matches: list[dict[str, Any]] = []
    profile_filters = []
    metadata_filters = []
    fact_filters = []
    for term in terms[:3]:
        profile_filters.extend([CompanyProfile.display_name.ilike(f"%{term}%"), CompanyProfile.company_name_norm.ilike(f"%{term}%")])
        metadata_filters.extend([DocumentMetadata.company_name.ilike(f"%{term}%"), DocumentMetadata.company_name_norm.ilike(f"%{term}%")])
        fact_filters.append(FinancialFact.company_name_norm.ilike(f"%{term}%"))

    if profile_filters:
        for row in db.query(CompanyProfile).filter(or_(*profile_filters)).limit(20).all():
            display = row.display_name or row.company_name_norm or ""
            matches.append(_candidate_entry(row.company_name_norm or display, display, corp_code=row.corp_code or "", source="company_profile", binding="authoritative", score=91))

    if metadata_filters:
        query_obj = db.query(DocumentMetadata, Document).join(Document, Document.id == DocumentMetadata.document_id)
        if user_id is not None:
            query_obj = query_obj.filter(Document.user_id == user_id)
        for metadata, _document in query_obj.filter(or_(*metadata_filters)).order_by(Document.id.desc()).limit(30).all():
            canonical = metadata.company_name_norm or metadata.company_name or ""
            matches.append(_candidate_entry(canonical, metadata.company_name or canonical, corp_code=metadata.corp_code or "", source="document_metadata", binding="authoritative", score=89))

    if fact_filters:
        query_obj = db.query(FinancialFact, Document).join(Document, Document.id == FinancialFact.document_id)
        if user_id is not None:
            query_obj = query_obj.filter(Document.user_id == user_id)
        for fact, _document in query_obj.filter(or_(*fact_filters)).order_by(Document.id.desc()).limit(20).all():
            if fact.company_name_norm:
                matches.append(_candidate_entry(fact.company_name_norm, fact.company_name_norm, corp_code=fact.corp_code or "", source="financial_fact", binding="authoritative", score=87))

    return _merge_candidates(matches)


def _infer_company_from_filename(filename: str) -> str:
    if not filename:
        return ""
    for pattern in (r"DART_[^_]+_([^_]+)_", r"^[^_]+_DART_[^_]+_([^_]+)_"):
        match = re.search(pattern, filename)
        if match:
            return normalize_company_name_for_storage(match.group(1))
    return ""


def _chroma_candidate_matches(query: str, user_id: int = 0) -> list[dict[str, Any]]:
    try:
        from services.cognitive_search_safe import cognitive_search_safe
        docs = cognitive_search_safe(query, top_k=6, user_id=user_id)
        matches: list[dict[str, Any]] = []
        seen = set()
        for doc in docs:
            company = doc.get("company")
            if company and company not in seen:
                seen.add(company)
                matches.append(_candidate_entry(company, company, source="chromadb_metadata", binding="candidate_unconfirmed", score=65))
        return matches
    except Exception:
        return []


def _candidate_matches(query: str, db, user_id: int | None = None) -> list[dict[str, Any]]:
    terms = _query_terms(query)
    if not terms:
        return []

    filters = []
    for term in terms[:3]:
        filters.extend([Document.filename.ilike(f"%{term}%"), DocumentMetadata.disclosure_title.ilike(f"%{term}%")])

    query_obj = db.query(Document, DocumentMetadata).outerjoin(DocumentMetadata, DocumentMetadata.document_id == Document.id)
    if user_id is not None:
        query_obj = query_obj.filter(Document.user_id == user_id)
    if filters:
        query_obj = query_obj.filter(or_(*filters))

    matches: list[dict[str, Any]] = []
    for document, metadata in query_obj.order_by(Document.id.desc()).limit(40).all():
        canonical = normalize_company_name_for_storage(metadata.company_name_norm) if metadata and metadata.company_name_norm else ""
        if not canonical:
            canonical = _infer_company_from_filename(document.filename)
        if canonical:
            display = (metadata.company_name if metadata else "") or canonical
            matches.append(_candidate_entry(canonical, display, corp_code=(metadata.corp_code if metadata else "") or "", source="filename_or_title", binding="candidate_unconfirmed", score=64))
    return _merge_candidates(matches)


def _suggest_companies(query: str, db, user_id: int | None = None, limit: int = 3) -> list[dict[str, Any]]:
    query_key = _compact(" ".join(_query_terms(query)) or query)
    suggestions: list[dict[str, Any]] = []
    combined = _db_authoritative_matches(query, db, user_id) + _dart_matches(query) + _candidate_matches(query, db, user_id) + _chroma_candidate_matches(query, user_id=user_id or 0)
    for item in _merge_candidates(combined):
        name_key = _compact(item.get("display") or item.get("canonical"))
        if not name_key:
            continue
        ratio = 1.0 if name_key in query_key or query_key in name_key else SequenceMatcher(None, query_key, name_key).ratio()
        if ratio >= 0.38:
            suggestions.append({**item, "score": max(float(item.get("score", 0)), ratio * 100)})
    return _merge_candidates(suggestions)[:limit]


_VS_SPLIT_RE = re.compile(r"\s*(?:vs\.?|versus|\ub300\ube44|\ub300|\ube44\uad50|,|/|\u00b7)\s*", re.IGNORECASE)


def _resolve_companies(query: str, db, user_id: int | None = None) -> dict[str, Any]:
    # ── 비교 쿼리 분할: "A vs B" → 각 회사를 독립 해석 후 병합 ──
    segments = [seg.strip() for seg in _VS_SPLIT_RE.split(query) if seg and seg.strip()]
    is_comparison = len(segments) >= 2

    # 1차: 전체 쿼리로 매칭
    full_query_matches = _static_alias_matches(query) + _dart_matches(query) + _db_authoritative_matches(query, db, user_id)

    # 2차: 비교 쿼리면 각 세그먼트도 매칭
    if is_comparison:
        for segment in segments:
            full_query_matches += _static_alias_matches(segment)
            full_query_matches += _dart_matches(segment)

    authoritative = _merge_candidates(full_query_matches)

    if authoritative:
        primary = authoritative[0]
        companies = [item["canonical"] for item in authoritative]
        # 비교 쿼리는 후보 수 제한 없이 모두 유지 (랭킹 비교용)
        candidate_limit = max(len(companies), 5) if is_comparison else 3
        return {"company": primary["canonical"], "company_display": primary.get("display") or primary["canonical"], "companies": companies, "binding": "authoritative", "corp_code": primary.get("corp_code", ""), "candidates": authoritative[:candidate_limit]}

    candidates = _suggest_companies(query, db, user_id, limit=3)
    if len(candidates) == 1 and len(_query_terms(query)) <= 2:
        candidate = candidates[0]
        return {"company": candidate["canonical"], "company_display": candidate.get("display") or candidate["canonical"], "companies": [candidate["canonical"]], "binding": "candidate_confirmed", "corp_code": candidate.get("corp_code", ""), "candidates": candidates}

    return {"company": "", "company_display": "", "companies": [], "binding": "candidate_unconfirmed" if candidates else "unresolved", "corp_code": "", "candidates": candidates}


def _remove_companies(query: str, companies: list[str]) -> str:
    text = query
    for company in sorted(companies, key=len, reverse=True):
        text = text.replace(company, " ")
    return re.sub(r"\s+", " ", text).strip(" ,.?/|")


def _company_terms_for_context(context: dict[str, Any]) -> list[str]:
    canonical = normalize_company_name_for_storage(context.get("company") or "")
    terms = set(aliases_for_company(canonical))
    terms.add(canonical)
    terms.add(str(context.get("company_display") or ""))
    for candidate in context.get("company_candidates") or []:
        if normalize_company_name_for_storage(candidate.get("canonical") or "") == canonical:
            terms.add(str(candidate.get("display") or ""))
    return [term for term in _dedupe([item.strip() for item in terms if str(item).strip()])]


def _is_company_only_query(message: str, context: dict[str, Any]) -> bool:
    if not context.get("company") and not context.get("company_candidates"):
        return False
        
    compact_msg = _compact(message)
    if context.get("company") and compact_msg == _compact(context["company"]):
        return True
        
    for cand in context.get("company_candidates") or []:
        if compact_msg == _compact(cand.get("canonical") or ""):
            return True

    stripped = _clean_text(message, 500)
    residual = _remove_companies(stripped, _company_terms_for_context(context))
    return not _query_terms(residual)


def _base_context(query: str, db, user_id: int | None = None) -> dict[str, Any]:
    company_resolution = _resolve_companies(query, db, user_id)
    metric = resolve_query_metric(query, {})
    year_filters, prefer_recent = _extract_year_filters(query)
    time_horizon = _extract_time_horizon(query)
    companies = list(company_resolution["companies"])
    focus_terms = _dedupe(
        companies
        + [company_resolution.get("company_display") or ""]
        + [str(item.get("display") or "") for item in company_resolution.get("candidates") or []]
    )
    return {
        "company": company_resolution["company"],
        "company_display": company_resolution["company_display"],
        "companies": companies,
        "company_binding": company_resolution["binding"],
        "company_candidates": company_resolution["candidates"],
        "corp_code": company_resolution["corp_code"],
        "metric": metric,
        "limit": extract_limit_from_query(query, 5),
        "trend_span": extract_trend_span(query, 3),
        "prefer_recent": prefer_recent or time_horizon != "current",
        "year_filters": year_filters,
        "time_horizon": time_horizon,
        "focus_query": _remove_companies(query, focus_terms) or query,
    }


def _should_inherit_context(query: str, context: dict[str, Any]) -> bool:
    stripped = query.strip()
    return stripped.startswith(FOLLOW_PREFIXES) or (not context["company"] and len(stripped) <= 12)


def _build_context(query: str, history: list[dict[str, Any]] | None, db, user_id: int | None = None) -> dict[str, Any]:
    context = _base_context(query, db, user_id)
    if history and _should_inherit_context(query, context):
        previous = _base_context(_last_user(history), db, user_id)
        for key in ("company", "company_display", "company_binding", "company_candidates", "corp_code", "metric", "year_filters"):
            if not context.get(key) and previous.get(key):
                context[key] = previous[key]
        if not context.get("companies") and previous.get("companies"):
            context["companies"] = previous["companies"]
        if context["time_horizon"] == "current" and previous["time_horizon"] != "current":
            context["time_horizon"] = previous["time_horizon"]
        if not context["prefer_recent"] and previous["prefer_recent"]:
            context["prefer_recent"] = True
        context["focus_query"] = _remove_companies(query, context["companies"]) or context["focus_query"]
    return context


def _classify_top(message: str, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    stripped = message.strip()
    lowered = stripped.lower()
    detail = re.search(r"(?:\ubb38\uc11c\s*)?#\s*(\d+)|(?:doc\s*)?#\s*(\d+)", stripped, re.IGNORECASE)
    if detail:
        return "doc_detail", {"document_id": int(detail.group(1) or detail.group(2))}
    if any(keyword in stripped for keyword in INPUT_HELP_KEYWORDS):
        return "product_help", {}
    if _looks_like_company_stats_query(stripped):
        return "company_stats", {}
    if any(keyword in stripped for keyword in DOC_STATS_KEYWORDS):
        return "doc_stats", {}
    if any(keyword in stripped for keyword in DOC_SEARCH_KEYWORDS):
        return "search_docs", {}
    if not context.get("company") and any(keyword in stripped for keyword in SCAN_KEYWORDS) and any(token in stripped for token in ("\uacf5\uc2dc", "\ubb38\uc11c")):
        return "market_scan", {}
    if ("\uacf5\uc2dc" in stripped or "dart" in lowered) and context.get("company"):
        return "dart", {"company_name": context["company"]}
    if any(keyword in stripped for keyword in TIME_KEYWORDS):
        return "time", {}
    if any(pattern in lowered for pattern in IDENTITY_PATTERNS):
        return "identity", {}
    if any(pattern in stripped for pattern in HELP_REQUEST_PATTERNS) or any(pattern in lowered for pattern in HELP_REQUEST_PATTERNS):
        return "capability_help", {}
    if any(keyword in stripped for keyword in PRODUCT_KEYWORDS):
        return "product_help", {}
    if any(keyword in stripped for keyword in CAPABILITY_KEYWORDS):
        return "capability_help", {}
    if _looks_like_greeting(stripped):
        return "greeting", {}
    return "knowledge", {}


def _format_doc_stats(user_id: int, db) -> str:
    total = db.query(func.count(Document.id)).filter(Document.user_id == user_id).scalar() or 0
    analyzed = db.query(func.count(Document.id)).filter(Document.user_id == user_id, Document.status == "analyzed").scalar() or 0
    return "\n".join([f"{TXT_CONCLUSION}: \ud604\uc7ac \ub0b4 \ubb38\uc11c\ub294 \ucd1d {total}\uac74\uc785\ub2c8\ub2e4.", "", TXT_EVIDENCE, f"1. \ubd84\uc11d \uc644\ub8cc \ubb38\uc11c: {analyzed}\uac74", f"2. \uc804\uccb4 \ubb38\uc11c: {total}\uac74"])


def _collect_company_stats(user_id: int, db, limit: int | None = None) -> list[dict[str, Any]]:
    rows = (
        db.query(
            DocumentMetadata.company_name_norm,
            func.max(DocumentMetadata.company_name).label("display_name"),
            func.count(DocumentMetadata.document_id).label("doc_count"),
        )
        .join(Document, Document.id == DocumentMetadata.document_id)
        .filter(
            Document.user_id == user_id,
            DocumentMetadata.company_name_norm.isnot(None),
            DocumentMetadata.company_name_norm != "",
        )
        .group_by(DocumentMetadata.company_name_norm)
        .order_by(func.count(DocumentMetadata.document_id).desc(), DocumentMetadata.company_name_norm.asc())
        .all()
    )
    stats: list[dict[str, Any]] = []
    source_rows = rows[:limit] if limit is not None else rows
    for company_name_norm, display_name, doc_count in source_rows:
        canonical = normalize_company_name_for_storage(company_name_norm or display_name or "")
        stats.append(
            {
                "company_name": display_name or canonical,
                "company_name_norm": canonical,
                "doc_count": int(doc_count or 0),
            }
        )
    return stats


def _format_company_stats(user_id: int, db) -> dict[str, Any]:
    rows = _collect_company_stats(user_id, db)
    total = len(rows)
    if total == 0:
        return {
            "reply": TXT_NO_DATA,
            "tools_used": ["get_document_stats"],
            "payload": {"type": "summary", "criteria": {"category": "company_stats"}, "rows": [], "series": [], "citations": []},
            "meta": {"intent": "company_stats", "confidence": "EXPLORATION [35%]", "evidence_count": 0, "rag_density": RAG_R0, "company_binding": "unresolved"},
        }
    display_rows = rows[:8]
    lines = [
        f"{TXT_CONCLUSION}: \uacf5\uc2dc/\ubb38\uc11c \uae30\uc900\uc73c\ub85c \ud655\uc778\ub41c \ud68c\uc0ac\ub294 \ucd1d {total}\uc885\ub958\uc785\ub2c8\ub2e4.",
        "",
        TXT_EVIDENCE,
    ]
    for index, item in enumerate(display_rows[:5], start=1):
        lines.append(f"{index}. {item['company_name']} - \uad00\ub828 \ubb38\uc11c {item['doc_count']}\uac74")
    lines.extend(
        [
            "",
            TXT_RISK,
            "- \ud68c\uc0ac\uba85 \uba54\ud0c0\ub370\uc774\ud130\uac00 \ube48 \ubb38\uc11c\ub294 \uc9d1\uacc4\uc5d0\uc11c \uc81c\uc678\ub420 \uc218 \uc788\uc2b5\ub2c8\ub2e4.",
            "",
            TXT_CONFIDENCE,
            "- INFERENCE [86%] - \ubb38\uc11c \uba54\ud0c0\ub370\uc774\ud130\uc758 \ud68c\uc0ac\uba85 \uc815\uaddc\ud654 \uac12\uc744 \uc9d1\uacc4\ud588\uc2b5\ub2c8\ub2e4.",
        ]
    )
    payload_rows = [
        {
            "metric_label": "\uad00\ub828 \ubb38\uc11c \uc218",
            "value_display": f"{item['doc_count']}\uac74",
            "fiscal_year": "-",
            "statement_scope": item["company_name"],
        }
        for item in display_rows
    ]
    return {
        "reply": "\n".join(lines),
        "tools_used": ["get_document_stats"],
        "payload": {"type": "summary", "criteria": {"category": "company_stats"}, "rows": payload_rows, "series": [], "citations": []},
        "meta": {"intent": "company_stats", "confidence": "INFERENCE [86%]", "evidence_count": total, "rag_density": RAG_R0, "company_binding": "unresolved"},
    }


def _format_recent_market_scan(user_id: int, db, limit: int = 5) -> dict[str, Any]:
    query = (
        db.query(Document, AnalysisResult, DocumentMetadata)
        .outerjoin(AnalysisResult, AnalysisResult.document_id == Document.id)
        .outerjoin(DocumentMetadata, DocumentMetadata.document_id == Document.id)
        .filter(Document.user_id == user_id)
        .order_by(Document.id.desc())
    )
    rows: list[dict[str, Any]] = []
    for document, analysis, metadata in query.limit(limit * 4).all():
        summary = _clean_text(getattr(analysis, "summary", "") or "", 180)
        title = (getattr(metadata, "disclosure_title", "") or "").strip()
        company_name = (getattr(metadata, "company_name", "") or "").strip()
        if not summary and not title:
            continue
        rows.append(
            {
                "document_id": document.id,
                "filename": document.filename,
                "company_name": company_name or "\ud68c\uc0ac\uba85 \ubbf8\uc0c1",
                "summary": summary or title or document.filename,
                "title": title or document.filename,
            }
        )
        if len(rows) >= limit:
            break
    if not rows:
        return {
            "reply": TXT_NO_DATA,
            "tools_used": ["search_my_documents"],
            "payload": {"type": "qa", "criteria": {"category": "market_scan"}, "rows": [], "series": [], "citations": []},
            "meta": {"intent": "market_scan", "confidence": "EXPLORATION [35%]", "evidence_count": 0, "rag_density": RAG_R0, "company_binding": "unresolved"},
        }
    lines = [
        f"{TXT_CONCLUSION}: \ucd5c\uadfc \uacf5\uc2dc/\ubb38\uc11c \uc911 \ud655\uc778\ud55c \ud56d\ubaa9\uc740 \ub2e4\uc74c\uacfc \uac19\uc2b5\ub2c8\ub2e4.",
        "",
        TXT_EVIDENCE,
    ]
    for index, item in enumerate(rows, start=1):
        lines.append(f"{index}. {item['company_name']} | {item['title']} | {item['summary']}")
    lines.extend(
        [
            "",
            TXT_RISK,
            "- \ud604\uc7ac\ub294 \ucd5c\uadfc \ub4f1\ub85d \uc21c\uc11c \uae30\uc900\uc758 \uc2a4\uce94\uc774\uba70, \uc911\uc694\ub3c4 \uc810\uc218\ud654\ub294 \uc544\uc9c1 \uc801\uc6a9\ud558\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.",
            "",
            TXT_CONFIDENCE,
            "- INFERENCE [72%] - \ucd5c\uadfc \ubb38\uc11c \uba54\ud0c0\ub370\uc774\ud130\uc640 \uc694\uc57d\uc744 \uae30\uc900\uc73c\ub85c \ubcf4\uc5ec\ub4dc\ub9b0 \uacb0\uacfc\uc785\ub2c8\ub2e4.",
        ]
    )
    citations = [
        {
            "document_id": item["document_id"],
            "filename": item["filename"],
            "company": item["company_name"],
            "source_text": item["summary"],
        }
        for item in rows
    ]
    return {
        "reply": "\n".join(lines),
        "tools_used": ["search_my_documents"],
        "payload": {"type": "qa", "criteria": {"category": "market_scan"}, "rows": [], "series": [], "citations": citations},
        "citations": citations,
        "meta": {"intent": "market_scan", "confidence": "INFERENCE [72%]", "evidence_count": len(rows), "rag_density": RAG_R0, "company_binding": "unresolved"},
    }


def _format_doc_detail(document_id: int, user_id: int, db) -> str:
    document = db.query(Document).filter(Document.id == document_id, Document.user_id == user_id).first()
    if document is None:
        return TXT_NO_DATA
    analysis = db.query(AnalysisResult).filter(AnalysisResult.document_id == document.id).order_by(AnalysisResult.id.desc()).first()
    metadata = db.query(DocumentMetadata).filter(DocumentMetadata.document_id == document.id).first()
    lines = [f"{TXT_CONCLUSION}: \ubb38\uc11c #{document.id} \uc0c1\uc138\uc785\ub2c8\ub2e4.", "", TXT_EVIDENCE, f"1. \ud30c\uc77c\uba85: {document.filename}", f"2. \uc0c1\ud0dc: {document.status}"]
    if metadata and metadata.company_name:
        lines.append(f"3. \ud68c\uc0ac\uba85: {metadata.company_name}")
    if analysis and analysis.summary:
        lines.extend(["", "**\ubb38\uc11c \uc694\uc57d**", re.sub(r"\\s+", " ", analysis.summary)[:300]])
    return "\n".join(lines)


def _search_docs(user_id: int, db, context: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    query = db.query(Document, AnalysisResult, DocumentMetadata).outerjoin(AnalysisResult, AnalysisResult.document_id == Document.id).outerjoin(DocumentMetadata, DocumentMetadata.document_id == Document.id).filter(Document.user_id == user_id).order_by(Document.id.desc())
    if context.get("company") and context.get("company_binding") == "authoritative":
        query = query.filter(DocumentMetadata.company_name_norm == normalize_company_name_for_storage(context["company"]))
    rows = []
    for document, analysis, metadata in query.limit(limit * 3).all():
        rows.append({"id": document.id, "filename": document.filename, "summary": getattr(analysis, "summary", "") or "", "company_name": getattr(metadata, "company_name", "") or ""})
        if len(rows) >= limit:
            break
    return rows


async def _search_dart(company_name: str, limit: int = 8) -> dict[str, Any]:
    try:
        from routers.panel import _resolve_corp_code

        corp_code = _resolve_corp_code(company_name)
        if not corp_code:
            return {"error": f"{company_name}\uc758 DART \ubc95\uc778\ucf54\ub4dc\ub97c \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4."}
        end_de = datetime.now().strftime("%Y%m%d")
        start_de = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("https://opendart.fss.or.kr/api/list.json", params={"crtfc_key": getattr(settings, "DART_API_KEY", ""), "corp_code": corp_code, "bgn_de": start_de, "end_de": end_de, "page_no": "1", "page_count": str(limit), "sort": "date", "sort_mth": "desc"})
        data = response.json() if response.status_code == 200 else {}
        return {"results": [{"corp_name": item.get("corp_name", company_name), "report_nm": item.get("report_nm", ""), "rcept_dt": item.get("rcept_dt", ""), "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}" if item.get("rcept_no") else ""} for item in data.get("list", [])[:limit]]}
    except Exception as exc:
        return {"error": f"DART \uc870\ud68c \uc911 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4: {exc}"}


# ─────────────────────────────────────────────────────────────────────
# v4: Answer Verification Guard — Self-RAG 패턴
# 생성된 답변이 근거에 충실한지 사후 검증. Faithfulness 스코어 극대화.
# ─────────────────────────────────────────────────────────────────────

def _verify_answer_grounding(answer: str, evidence_texts: list[str]) -> dict[str, Any]:
    """답변의 숫자/사실이 근거에 실제로 존재하는지 검증.

    Returns:
        {
            "grounded": bool,
            "grounding_ratio": float (0-1),
            "ungrounded_numbers": list[str],
            "has_foreign_chars": bool,
            "has_json_artifacts": bool,
        }
    """
    import re as _re

    all_evidence = " ".join(evidence_texts).lower().replace(",", "")
    answer_lower = answer.lower()

    # 1. 숫자 검증
    answer_numbers = set(_re.findall(r'\d{3,}(?:\.\d+)?', answer.replace(",", "")))
    ungrounded = []
    for num in answer_numbers:
        if num not in all_evidence:
            # 파생 계산 허용 (성장률 등)
            if not any(marker in answer_lower for marker in ["계산", "추정", "약", "파생", "대비"]):
                ungrounded.append(num)

    grounding_ratio = 1.0 - (len(ungrounded) / max(len(answer_numbers), 1)) if answer_numbers else 0.8

    # 2. 외국어 오염 검출
    cn_chars = len(_re.findall(r'[\u4e00-\u9fff]', answer))
    jp_chars = len(_re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', answer))
    has_foreign = cn_chars > 0 or jp_chars > 0

    # 3. JSON 아티팩트 검출
    json_markers = answer.count('{"') + answer.count('":') + answer.count('"}')
    has_json = json_markers >= 3

    return {
        "grounded": grounding_ratio >= 0.7 and not has_foreign and not has_json,
        "grounding_ratio": round(grounding_ratio, 3),
        "ungrounded_numbers": ungrounded[:5],
        "has_foreign_chars": has_foreign,
        "has_json_artifacts": has_json,
    }


def _sanitize_answer(answer: str) -> str:
    """v4: 답변에서 오염 요소를 자동 제거.

    - 중국어/일본어 문자 제거
    - JSON 아티팩트 제거
    - 깨진 유니코드 제거
    """
    import re as _re

    # 중국어 문자 제거 (한자 중 한국어에서 안 쓰는 문자)
    # 한국 한자(교육용 한자)는 보존하되, 간체자/문장 수준 중국어 제거
    answer = _re.sub(r'[\u3400-\u4dbf]', '', answer)  # CJK Extension A (rare)

    # 일본어 히라가나/카타카나 제거
    answer = _re.sub(r'[\u3040-\u309f\u30a0-\u30ff]', '', answer)

    # JSON 아티팩트 패턴 제거
    answer = _re.sub(r'\{["\'][\w_]+["\']:\s*["\']', '', answer)
    answer = _re.sub(r'["\']\s*\}', '', answer)

    # 연속 공백 정리
    answer = _re.sub(r'  +', ' ', answer)
    answer = _re.sub(r'\n{3,}', '\n\n', answer)

    return answer.strip()


def _looks_corrupted(text: str) -> bool:
    snippet = _clean_text(text, 200)
    return not snippet or any(marker in snippet for marker in ("å", "æ", "ç", "ï§", "Ð¦", "Â€")) or (snippet.count("?") >= 8 and len(snippet) < 120)


def _is_balance_only(text: str) -> bool:
    return any(keyword in text for keyword in BALANCE_ONLY_KEYWORDS) and not classify_stock_outlook_support(text)


def _chunk_citation(chunk) -> dict[str, Any]:
    """v4: 풍부한 citation 메타데이터 — RAGAS Answer Correctness 향상."""
    return {
        "document_id": chunk.metadata.get("doc_id"),
        "filename": chunk.metadata.get("filename", ""),
        "company": chunk.metadata.get("company", ""),
        "category": chunk.metadata.get("category", ""),
        "section_name": chunk.metadata.get("section_name", ""),
        "score": chunk.metadata.get("score", 0),
        "rerank_score": chunk.metadata.get("rerank_score", 0),
        "source_text": _clean_text(chunk.text, 400),  # v4: 300→400
        "text": _clean_text(chunk.text, 400),
    }


def _build_query_rewrites(user_message: str, context: dict[str, Any], intent: str) -> list[str]:
    """v4: Multi-perspective query expansion — Context Recall 극대화.

    원본 쿼리 + 다각도 서브쿼리로 검색 커버리지를 넓힌 뒤
    CrossEncoder reranker가 관련성을 판별한다.
    """
    company = context.get("company", "")
    metric = context.get("metric", "")
    focus_query = context.get("focus_query") or user_message
    if intent == ROUTE_STOCK_OUTLOOK and company:
        return _dedupe([
            f"{company} 실적 전망", f"{company} 업황", f"{company} 가격 사이클",
            f"{company} 시장 기대", f"{company} 리스크",
            f"{company} 매출 영업이익 추이",  # v4: 수치 기반 검색 추가
        ])[:6]
    if intent == ROUTE_TREND and company:
        parts = [company]
        if metric:
            parts.append(metric)
        parts.append("추세")
        if context.get("year_filters"):
            parts.append(" ".join(context["year_filters"]))
        return [" ".join(parts).strip(), f"{company} {metric or '매출'} 변화"]
    queries = [user_message]
    if company and metric:
        queries.append(f"{company} {metric}")
    if company and focus_query != user_message:
        queries.append(f"{company} {focus_query}")
    if any(keyword in user_message for keyword in ("근거", "출처", "왜")) and company:
        queries.append(f"{company} {focus_query} 근거")

    # v4: 회사 특정 쿼리에도 보조 검색어 추가 (document_qa 커버리지 확대)
    if company and intent == INTENT_DOCUMENT_QA:
        queries.append(f"{company} 사업보고서 감사보고서")
        queries.append(f"{company} 재무제표 핵심")

    # ── 회사 미특정 일반 쿼리 recall 보강 ──
    # 긴 자연어 쿼리("작년 상장폐지 사유 발생 기업 리스트")는 벡터 임베딩이 분산되어
    # distinctive 토큰("상장폐지")의 신호를 잃는다. 단독 토큰을 서브쿼리로 추가하여
    # multi-query 벡터 검색 → reranker가 판정한다.
    if not company:
        for token in _query_terms(user_message):
            if len(token) >= 3:
                queries.append(token)
            if len([q for q in queries if q != user_message]) >= 2:
                break
    return _dedupe(queries)[:6]  # v4: 5→6 확장


def _judge_chunks(*, chunks: list[Any], intent: str, company_filter: str, max_keep: int) -> dict[str, Any]:
    """v4: Quality-aware evidence judge — 오염 청크 자동 제거, 다양성 보장.

    변경점:
    - 중국어/JSON 오염 청크 자동 감지 및 제거
    - 정보 밀도 점수 추가 (재무 숫자가 포함된 청크 우선)
    - 다양성 보장: 같은 파일의 청크가 과대 대표되지 않도록 제한
    """
    kept: list[dict[str, Any]] = []
    seen = set()
    file_count: dict[str, int] = {}
    company_filter_compact = _compact(company_filter) if company_filter else ""
    company_filter_aliases = set()
    if company_filter:
        company_filter_aliases = {_compact(a) for a in aliases_for_company(company_filter) if a}
        company_filter_aliases.add(company_filter_compact)

    for chunk in chunks:
        text = _clean_text(chunk.text, 400)
        meta_company = normalize_company_name_for_storage(str(chunk.metadata.get("company", "")))
        if len(text) < 40 or _looks_corrupted(text):
            continue

        # v4: 중국어/일본어 오염 감지 — Faithfulness 저하 방지
        cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        jp_chars = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
        if cn_chars > 5 or jp_chars > 3:
            continue

        # v4: JSON 아티팩트 오염 감지
        json_markers = text[:200].count('{"') + text[:200].count('":') + text[:200].count('"}')
        if json_markers >= 4:
            continue

        if company_filter_compact and meta_company:
            meta_compact = _compact(meta_company)
            if meta_compact not in company_filter_aliases and company_filter_compact not in meta_compact and meta_compact not in company_filter_compact:
                continue
        supports = classify_stock_outlook_support(text) if intent == ROUTE_STOCK_OUTLOOK else []
        if intent == ROUTE_STOCK_OUTLOOK and _is_balance_only(text):
            continue
        signature = text[:140].lower()
        if signature in seen:
            continue
        seen.add(signature)

        # v4: 정보 밀도 점수 — 재무 숫자가 포함된 청크 우선
        number_count = len(re.findall(r'\d{3,}', text))
        info_density = min(number_count * 0.08, 0.3)

        # v4: 파일 다양성 제한 — 같은 파일에서 최대 2개 청크
        filename = chunk.metadata.get("filename", "unknown")
        file_count[filename] = file_count.get(filename, 0) + 1
        diversity_penalty = 0.15 if file_count[filename] > 2 else 0.0

        kept.append({
            "chunk": chunk,
            "text": text,
            "supports": supports,
            "score": float(chunk.metadata.get("score", 0) or 0) + 0.25 * len(supports) + info_density - diversity_penalty,
        })
    kept.sort(key=lambda item: (len(item["supports"]), item["score"]), reverse=True)
    kept = kept[:max_keep]
    if intent == ROUTE_STOCK_OUTLOOK:
        coverage = evaluate_stock_outlook_coverage([item["text"] for item in kept])
        covered = [slot for slot, snippets in coverage.items() if snippets]
        gaps = [label for slot, label in STOCK_OUTLOOK_SLOT_LABELS.items() if slot not in covered]
        return {"kept": kept, "coverage": coverage, "coverage_gaps": gaps, "enough_evidence": len(covered) >= 3}
    return {"kept": kept, "coverage": {}, "coverage_gaps": [], "enough_evidence": bool(kept)}


def _effective_company_filter(context: dict[str, Any]) -> str:
    return context.get("company", "") if context.get("company_binding") in {"authoritative", "candidate_confirmed"} else ""


async def _retrieve(user_message: str, context: dict[str, Any], intent: str, rag_density: str, db, user_id: int = 0) -> dict[str, Any]:
    company_filter = _effective_company_filter(context)
    query_rewrites = _build_query_rewrites(user_message, context, intent)
    logger.info(
        "Ω Retrieve — company_filter=%s intent=%s rag=%s rewrites=%s",
        company_filter, intent, rag_density, query_rewrites[:3],
    )
    retriever = CivicFlowRetriever(db)
    chunks = await retriever.search(
        queries=query_rewrites,
        query_rewrites=query_rewrites,
        top_k=8 if rag_density == RAG_R2 else 14,
        company_filter=company_filter,
        intent=intent,
        time_horizon=context.get("time_horizon", "current"),
        prefer_recent=bool(context.get("prefer_recent")),
        year_filters=context.get("year_filters") or None,
        rag_density=rag_density,
        user_id=user_id,
    )
    judged = _judge_chunks(chunks=chunks, intent=intent, company_filter=company_filter, max_keep=8 if rag_density == RAG_R2 else 8)  # v7: 5/7 → 8/8 (RAGAS eval k=8 일치)
    logger.info(
        "Ω Retrieve — retrieved=%d kept=%d enough=%s top_docs=%s",
        len(chunks), len(judged.get("kept", [])), judged.get("enough_evidence", False),
        [k["chunk"].metadata.get("filename", "")[:40] for k in judged.get("kept", [])[:3]],
    )
    return judged


def _time_label(time_horizon: str) -> str:
    return {
        "short_term": "\ub2e8\uae30",
        "mid_term": "\uc911\uae30",
        "long_term": "\uc7a5\uae30",
        "short_to_mid_term": "\ub2e8\uae30~\uc911\uae30",
    }.get(time_horizon, "\ub2e8\uae30~\uc911\uae30")


def _payload_has_content(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(payload.get("rows") or payload.get("series") or payload.get("citations"))


def _augment_meta(result: dict[str, Any], *, intent: str, rag_density: str, company_binding: str, fallback_reason: str = "") -> dict[str, Any]:
    meta = dict(result.get("meta") or {})
    meta["intent"] = intent
    meta["evidence_count"] = int(meta.get("evidence_count") or len(result.get("citations") or []))
    meta["rag_density"] = rag_density
    meta["company_binding"] = company_binding
    if fallback_reason:
        meta["fallback_reason"] = fallback_reason
    result["meta"] = meta
    result.setdefault("tools_used", [])
    if not result["tools_used"] and _payload_has_content(result.get("payload")):
        result["tools_used"] = ["structured_facts"]
    return result


def _make_followup(*, intent: str, light_answer: str, reason: str, question: str, company_candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    suggestion_line = ""
    if company_candidates:
        suggestion_line = " / ".join(item.get("display") or item.get("canonical") for item in company_candidates[:3])
    lines = [f"{TXT_CONCLUSION}: {light_answer}", "", TXT_EVIDENCE, f"1. {reason}", "", TXT_RISK, "- \ud68c\uc0ac\ub97c \uc798\ubabb \uc7a1\uc73c\uba74 \ud0c0\uc0ac \ubb38\uc11c\uac00 \uc11e\uc785\ub2c8\ub2e4.", "", TXT_CONFIDENCE, "- INFERENCE [62%]"]
    if suggestion_line:
        lines.extend(["", f"\ud6c4\ubcf4: {suggestion_line}"])
    lines.extend(["", question])
    return {
        "reply": "\n".join(lines),
        "tools_used": [],
        "payload": {"type": "qa", "route": intent, "criteria": {"follow_up": True, "company_candidates": company_candidates or []}, "rows": [], "series": [], "citations": []},
        "citations": [],
        "meta": {"intent": intent, "confidence": "INFERENCE [62%]", "evidence_count": 0, "rag_density": RAG_R0, "company_binding": "candidate_unconfirmed" if company_candidates else "unresolved"},
    }


def _is_event_listing_query(message: str) -> bool:
    """\uc774\ubca4\ud2b8 \uc2e0\ud638\uc5b4(\uc0c1\uc7a5\ud3d0\uc9c0\u00b7\uac10\uc0ac\uc758\uacac \ub4f1) + \uc774\uc720/\ub7ad\ud0b9 \uc2e0\ud638\uc5b4 \uacb0\ud569 \uc2dc True.

    Ranking route\uc758 default \uae30\uc5c5(big 4) fallback\uc73c\ub85c \uadc0\uacb0\ub418\ub294 \uac83\uc744 \ucc28\ub2e8\ud558\uae30 \uc704\ud55c \uac00\ub4dc.
    """
    stripped = _clean_text(message, 500)
    lowered = message.lower()
    has_event = any(kw in stripped for kw in EVENT_SIGNAL_KEYWORDS)
    has_reason_or_rank = (
        any(kw in stripped for kw in REASON_SIGNAL_KEYWORDS)
        or any(kw in lowered for kw in RANKING_KEYWORDS)
    )
    return has_event and has_reason_or_rank


def _classify_professional(message: str, context: dict[str, Any]) -> dict[str, Any]:
    lowered = message.lower()
    stripped = _clean_text(message, 500)
    focus_key = _compact(context.get("focus_query") or "")
    has_company = bool(context.get("company"))
    has_metric = bool(context.get("metric"))
    company_only = _is_company_only_query(message, context)
    multi_company = len(context.get("companies") or []) >= 2

    # ── B4: RANKING/COMPARE 우선 검사 (short_query 분기보다 먼저) ──
    # "삼성전자 vs SK하이닉스" 같은 짧은 비교 쿼리가 단일 회사 요약으로 빠지는 것 방지
    # ── Context Mismatch Guard: 이벤트 열거형 쿼리는 ranking_compare 우회 → 기본 QA로 위임 ──
    has_ranking_keyword = any(keyword in lowered for keyword in RANKING_KEYWORDS)
    event_listing = _is_event_listing_query(message)

    if (has_ranking_keyword or multi_company) and not event_listing:
        logger.info(
            "\u03a9 Classify \u2014 route=ranking_compare query=%r ranking_kw=%s multi=%s",
            message[:80], has_ranking_keyword, multi_company,
        )
        return {"intent": ROUTE_RANKING_COMPARE, "route": ROUTE_RANKING_COMPARE, "rag_density": RAG_R1, "missing_variable": ""}

    if event_listing:
        logger.info(
            "\u03a9 Classify \u2014 route=qa(event_listing) query=%r \u2014 bypass ranking_compare",
            message[:80],
        )
        # Fall through to classifier default (ROUTE_QA) — event queries 처리는 Phase 3 corp_events에서 완성

    query_tokens = _query_terms(message)
    is_short_query = len(query_tokens) <= 3 and len(message) <= 25
    if is_short_query:
        if context.get("company_binding") in {"authoritative", "candidate_confirmed"}:
            return {"intent": ROUTE_COMPANY_SUMMARY, "route": ROUTE_COMPANY_SUMMARY, "rag_density": RAG_R1, "missing_variable": ""}
        return {"intent": INTENT_DOCUMENT_QA, "route": ROUTE_QA, "rag_density": RAG_R1, "missing_variable": ""}

    has_scan_signal = any(keyword in stripped for keyword in SCAN_KEYWORDS)
    if any(keyword in stripped for keyword in RECOMMEND_KEYWORDS) and not has_company:
        return {"intent": INTENT_DOCUMENT_QA, "route": ROUTE_QA, "rag_density": RAG_R0, "missing_variable": "priority_axis"}
    if not has_company and has_metric and (has_scan_signal or "\uae30\uc5c5" in stripped or "\uacf5\uc2dc" in stripped):
        return {"intent": ROUTE_RANKING_COMPARE, "route": ROUTE_RANKING_COMPARE, "rag_density": RAG_R1, "missing_variable": ""}
    if any(keyword in stripped for keyword in OUTLOOK_KEYWORDS):
        return {"intent": ROUTE_STOCK_OUTLOOK, "route": ROUTE_STOCK_OUTLOOK, "rag_density": RAG_R2 if has_company else RAG_R0, "missing_variable": "" if has_company else "company"}
    if (any(keyword in stripped for keyword in TREND_KEYWORDS) or re.search("\ucd5c\uadfc\\s*\\d+\\s*\ub144", stripped)) and (has_company or has_metric):
        return {"intent": ROUTE_TREND, "route": ROUTE_TREND, "rag_density": RAG_R1, "missing_variable": "" if has_company or has_metric else "company"}
    if has_company and (company_only or not focus_key or any(keyword in stripped for keyword in SUMMARY_KEYWORDS)):
        return {"intent": ROUTE_COMPANY_SUMMARY, "route": ROUTE_COMPANY_SUMMARY, "rag_density": RAG_R1, "missing_variable": ""}
    if has_company and (has_metric or any(keyword in stripped for keyword in DOCUMENT_QA_KEYWORDS)):
        return {"intent": INTENT_DOCUMENT_QA, "route": ROUTE_QA, "rag_density": RAG_R2, "missing_variable": ""}
    if not has_company and (has_metric or any(keyword in stripped for keyword in DOCUMENT_QA_KEYWORDS)):
        return {"intent": INTENT_DOCUMENT_QA, "route": ROUTE_QA, "rag_density": RAG_R0, "missing_variable": "company"}
    # 세부 intent에 안 걸리면 일반 RAG QA로 위임 — Reranker가 관련성/근거를 판단
    # (이벤트·집계 쿼리, 회사 미특정 탐색 질문 포함)
    return {"intent": INTENT_DOCUMENT_QA, "route": ROUTE_QA, "rag_density": RAG_R2, "missing_variable": ""}


def _maybe_followup(classification: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    missing = classification.get("missing_variable") or ""
    if missing == "company":
        return _make_followup(intent=classification.get("intent") or INTENT_DOCUMENT_QA, light_answer="\uc9c8\ubb38\uc5d0 \ud3ec\ud568\ub41c \ud68c\uc0ac\ub97c \ud655\uc815\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.", reason="\uc774 \ucc57\ubd07\uc740 \ud68c\uc0ac \ubc14\uc778\ub529\uc774 \ud655\uc815\ub41c \ub4a4\uc5d0\ub9cc \ubb38\uc11c\uc640 \uc7ac\ubb34 \ud329\ud2b8\ub97c \uc548\uc804\ud558\uac8c \uc5f0\uacb0\ud569\ub2c8\ub2e4.", question="\ud68c\uc0ac\uba85\uc744 \ud558\ub098\ub9cc \ub2e4\uc2dc \uc801\uc5b4\uc8fc\uc138\uc694.", company_candidates=context.get("company_candidates") or [])
    if missing == "priority_axis":
        return _make_followup(intent=INTENT_DOCUMENT_QA, light_answer="\ucd94\ucc9c\ud615 \uc9c8\ubb38\uc740 \uc6b0\uc120 \uae30\uc900\uc774 \uc5c6\uc73c\uba74 \ub2f5\uc774 \ud754\ub4e4\ub9bd\ub2c8\ub2e4.", reason="\uc218\uc775\uc131, \uc131\uc7a5\uc131, \uc548\uc815\uc131, \uc5c5\uc885 \uc911 \ubb34\uc5c7\uc744 \uc6b0\uc120\ud560\uc9c0 \uba3c\uc800 \uc815\ud574\uc57c \ube44\uad50 \ucd95\uc774 \uace0\uc815\ub429\ub2c8\ub2e4.", question="\uc218\uc775\uc131 / \uc131\uc7a5\uc131 / \uc548\uc815\uc131 / \uc5c5\uc885 \uc911 \ud558\ub098\ub97c \uba3c\uc800 \ub9d0\uc500\ud574\uc8fc\uc138\uc694.")
    return None


def _stock_outlook_answer(user_message: str, context: dict[str, Any], structured: dict[str, Any], judged: dict[str, Any], rag_density: str) -> dict[str, Any]:
    company = context.get("company_display") or context.get("company", "")
    kept = judged["kept"]
    coverage = judged["coverage"]
    citations = [_chunk_citation(item["chunk"]) for item in kept]
    evidence_lines: list[str] = []
    rows = ((structured.get("payload") or {}).get("rows") or [])[:2]
    if rows:
        snapshot = ", ".join(f"{row['metric_label']} {row['value_display']}" for row in rows)
        evidence_lines.append(f"1. \uad6c\uc870\ud654 \ud329\ud2b8 \uae30\uc900 \ucd5c\uadfc \ud575\uc2ec \uc218\uce58\ub294 {snapshot}\uc785\ub2c8\ub2e4.")
    for slot in ("recent_performance", "industry_cycle", "market_expectation"):
        snippets = coverage.get(slot) or []
        if snippets:
            evidence_lines.append(f"{len(evidence_lines) + 1}. {STOCK_OUTLOOK_SLOT_LABELS[slot]} \uadfc\uac70: {snippets[0]}")
        if len(evidence_lines) >= 3:
            break
    conclusion = f"{company}\uc758 {_time_label(context.get('time_horizon', 'short_to_mid_term'))} \ubc29\ud5a5\uc131\uc740 \uc2e4\uc801\uacfc \uc5c5\ud669 \uadfc\uac70\ub97c \ud568\uaed8 \ubd10\uc57c \ud569\ub2c8\ub2e4."
    risk_text = (coverage.get("risk") or ["\ud575\uc2ec \ub9ac\uc2a4\ud06c \uadfc\uac70\uac00 \uc544\uc9c1 \ucda9\ubd84\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4."])[0]
    covered_count = len([slot for slot, snippets in coverage.items() if snippets])
    confidence = "INFERENCE [76%]" if covered_count >= 4 else "INFERENCE [71%]"
    reply = "\n".join([f"{TXT_CONCLUSION}: {conclusion}", "", TXT_EVIDENCE, *evidence_lines[:3], "", TXT_RISK, f"- {risk_text}", "- \uc2dc\uc7a5 \uae30\ub300\uac00 \uc774\ubbf8 \uc120\ubc18\uc601\ub418\uc5c8\uc744 \uc218 \uc788\uc2b5\ub2c8\ub2e4.", "", TXT_CONFIDENCE, f"- {confidence} - \uc2e4\uc801, \uc5c5\ud669, \uc2dc\uc7a5 \uae30\ub300, \ub9ac\uc2a4\ud06c \uc2ac\ub86f\uc744 \uae30\uc900\uc73c\ub85c \uc555\ucd95\ud588\uc2b5\ub2c8\ub2e4."])
    return {"reply": reply, "tools_used": ["structured_facts", "chromadb_search"], "payload": {"type": "qa", "route": ROUTE_STOCK_OUTLOOK, "criteria": {"query": user_message, "company_name": company, "coverage_slots": [slot for slot, snippets in coverage.items() if snippets]}, "rows": [], "series": [], "citations": citations}, "citations": citations, "meta": {"intent": ROUTE_STOCK_OUTLOOK, "confidence": confidence, "evidence_count": len(citations), "rag_density": rag_density, "company_binding": context.get("company_binding", "unresolved")}}


def _stock_outlook_shortage(context: dict[str, Any], judged: dict[str, Any], rag_density: str) -> dict[str, Any]:
    company = context.get("company_display") or context.get("company", "")
    citations = [_chunk_citation(item["chunk"]) for item in judged.get("kept", [])]
    gaps = judged.get("coverage_gaps") or list(STOCK_OUTLOOK_SLOT_LABELS.values())
    reply = "\n".join([f"{TXT_CONCLUSION}: {company} \uc804\ub9dd\uc740 \ud604\uc7ac \uadfc\uac70\uac00 \ubd80\uc871\ud574 \ub2e8\uc815\ud558\uc9c0 \uc54a\uaca0\uc2b5\ub2c8\ub2e4.", "", TXT_EVIDENCE, "1. \uc804\ub9dd \uc9c8\ubb38\uc740 \ucd5c\uadfc \uc2e4\uc801, \uc5c5\ud669, \uc2dc\uc7a5 \uae30\ub300, \ub9ac\uc2a4\ud06c \uc911 \ucd5c\uc18c 3\uac1c \ucd95\uc774 \ud544\uc694\ud569\ub2c8\ub2e4.", f"2. \ud604\uc7ac \ubd80\uc871\ud55c \ucd95: {', '.join(gaps[:3])}", "", TXT_RISK, "- \uadfc\uac70\uac00 \ube48 \uc0c1\ud0dc\uc5d0\uc11c \uc804\ub9dd\uc744 \uac15\ud589\ud558\uba74 \uc624\ub2f5 \ud655\ub960\uc774 \ub192\uc2b5\ub2c8\ub2e4.", "", TXT_CONFIDENCE, "- EXPLORATION [39%] - \ud604\uc7ac\ub294 \ubb38\uc11c \uadfc\uac70\uac00 \ucda9\ubd84\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.", "", "\uc6d0\ud558\uc2dc\uba74 \uae30\uac04\uc744 \ub2e8\uae30/\uc911\uae30 \uc911 \ud558\ub098\ub85c \uc9c0\uc815\ud574 \ub2e4\uc2dc \uc881\ud600\ub4dc\ub9ac\uaca0\uc2b5\ub2c8\ub2e4."])
    return {"reply": reply, "tools_used": ["chromadb_search"] if citations else [], "payload": {"type": "qa", "route": ROUTE_STOCK_OUTLOOK, "criteria": {"company_name": company, "insufficient_evidence": True}, "rows": [], "series": [], "citations": citations}, "citations": citations, "meta": {"intent": ROUTE_STOCK_OUTLOOK, "confidence": "EXPLORATION [39%]", "evidence_count": len(citations), "rag_density": rag_density, "company_binding": context.get("company_binding", "unresolved")}}


_RAG_SYSTEM_PROMPT = (
    "당신은 Omega-Prime 분석 챗봇입니다. 사용자가 업로드한 한국 기업의 공시·재무 문서 발췌(청크)만을 근거로 답변합니다.\n\n"
    "규칙:\n"
    "1. ★ FAITHFULNESS(근거 충실도) 최우선: 청크에 없는 수치/사실은 절대 지어내지 마세요. 없으면 '문서에 명시되지 않음'이라고 에둘러 표현하세요.\n"
    "2. 수치는 청크에 있는 숫자를 그대로 인용하고, 단위(억원/천원/%)를 명시하세요.\n"
    "3. ★ 모든 수치에 출처(파일명)를 반드시 명시하세요. 예: '[파일명] 기준'\n"
    "4. 출력 포맷을 정확히 지키세요:\n"
    "**결론**: [한 문장으로 핵심 답]\n\n"
    "**근거**\n"
    "1. [청크 인용, 파일명 명시]\n"
    "2. [...]\n\n"
    "**리스크**\n"
    "- [이 답변이 부정확할 수 있는 이유]\n\n"
    "**확신도**\n"
    "- INFERENCE/SPECULATION [퍼센트%] - [근거 품질 설명]\n\n"
    "5. 반드시 한국어로 답변하세요. 중국어(中), 일본어(日) 사용 금지.\n"
    "6. JSON 형식 출력 금지. 순수 마크다운만.\n\n"
    "★ 기억하세요: 환각(hallucination)보다 '자료 부족'이 100배 낫습니다."
)


async def _generic_retrieval_answer(user_message: str, judged: dict[str, Any], rag_density: str, context: dict[str, Any]) -> dict[str, Any]:
    kept = judged.get("kept") or []
    if not kept:
        return {"reply": TXT_NO_DATA, "tools_used": [], "payload": {"type": "qa", "route": ROUTE_QA, "criteria": {"query": user_message}, "rows": [], "series": [], "citations": []}, "citations": [], "meta": {"intent": INTENT_DOCUMENT_QA, "confidence": "EXPLORATION [35%]", "evidence_count": 0, "rag_density": rag_density, "company_binding": context.get("company_binding", "unresolved")}}

    citations = [_chunk_citation(item["chunk"]) for item in kept]
    company_hint = context.get("company_display") or context.get("company") or ""

    # ── LLM 기반 요약 (v4: 청크를 더 많이, 더 구조화하여 전달) ──
    chunk_blocks: list[str] = []
    for idx, item in enumerate(kept[:8], start=1):  # v7: 5→8 확장 (RAGAS eval 일치)
        filename = item["chunk"].metadata.get("filename", "unknown")
        section = item["chunk"].metadata.get("section_name", "")
        score = item.get("score", 0)
        text = (item.get("text") or "").strip()[:1500]  # v4: 1200→1500
        header = f"[청크 {idx}] 파일: {filename}"
        if section:
            header += f" | 섹션: {section}"
        header += f" | 관련도: {score:.2f}"
        chunk_blocks.append(f"{header}\n{text}")

    user_prompt = (
        f"질문: {user_message}\n\n"
        + (f"관련 기업: {company_hint}\n\n" if company_hint else "")
        + "관련 문서 청크:\n\n"
        + "\n\n---\n\n".join(chunk_blocks)  # v4: 구분선 추가
        + "\n\n★ 위 청크만을 근거로 Omega-Prime 포맷으로 답변하세요. 청크에 없는 정보는 절대 만들지 마세요."
    )

    try:
        llm_reply = await _get_llm_client().complete_text(
            system_prompt=_RAG_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
        )
        llm_reply = (llm_reply or "").strip()
    except Exception as exc:
        logger.warning("LLM fallback summarization failed: %s", exc)
        llm_reply = ""

    if llm_reply:
        # v4: Answer Verification Guard — 답변 사후 검증
        evidence_texts = [(item.get("text") or "") for item in kept]
        verification = _verify_answer_grounding(llm_reply, evidence_texts)

        # 오염 자동 제거
        if verification["has_foreign_chars"] or verification["has_json_artifacts"]:
            llm_reply = _sanitize_answer(llm_reply)

        # 근거 충실도 기반 동적 확신도
        if verification["grounding_ratio"] >= 0.85:
            confidence = "CONSENSUS [88%]"
        elif verification["grounding_ratio"] >= 0.7:
            confidence = "INFERENCE [75%]"
        elif verification["grounding_ratio"] >= 0.5:
            confidence = "INFERENCE [65%]"
        else:
            confidence = "SPECULATION [55%]"

        # 비근거 숫자 경고 추가
        if verification["ungrounded_numbers"]:
            ungrounded_note = f"\n\n> 주의: 일부 수치({', '.join(verification['ungrounded_numbers'][:3])})는 제공된 문서 청크에서 직접 확인되지 않았습니다."
            llm_reply += ungrounded_note

        return {
            "reply": llm_reply,
            "tools_used": ["chromadb_search", "llm_summary", "answer_verification"],
            "payload": {"type": "qa", "route": ROUTE_QA, "criteria": {"query": user_message, "fallback": "llm_summary"}, "rows": [], "series": [], "citations": citations},
            "citations": citations,
            "meta": {
                "intent": INTENT_DOCUMENT_QA,
                "confidence": confidence,
                "evidence_count": len(citations),
                "rag_density": rag_density,
                "company_binding": context.get("company_binding", "unresolved"),
                "grounding_ratio": verification["grounding_ratio"],
                "verified": verification["grounded"],
            },
        }

    # ── LLM \uc2e4\ud328 \uc2dc fallback: \uae30\uc874 raw \uc18c\ud504\ud2b8 \uc778\uc6a9 ──
    lines = [f"{TXT_CONCLUSION}: \uad6c\uc870\ud654 \ud329\ud2b8\ub9cc\uc73c\ub85c \ubd80\uc871\ud574 \uad00\ub828 \ubb38\uc11c\ub97c \ucd94\uac00 \uac80\uc0c9\ud574 \ub2f5\ubcc0\ud588\uc2b5\ub2c8\ub2e4.", "", TXT_EVIDENCE]
    lines.extend(f"{idx}. {item['chunk'].metadata.get('filename', '')} - {item['text'][:160]}" for idx, item in enumerate(kept[:3], start=1))
    lines.extend(["", TXT_RISK, "- LLM \uc694\uc57d\uc774 \uc77c\uc2dc\uc801\uc73c\ub85c \uc2e4\ud328\ud574 \ubb38\uc11c \ubc1c\ucdcc\ub9cc \uc778\uc6a9\ud588\uc2b5\ub2c8\ub2e4.", "- \ubb38\uc11c \ubc1c\ucdcc \uae30\ubc18\uc774\ub77c \uc218\uce58 \uc815\uaddc\ud654\ub098 \uc2dc\uc810 \uc815\ud569\uc131\uc774 \uc644\uc804\ud558\uc9c0 \uc54a\uc744 \uc218 \uc788\uc2b5\ub2c8\ub2e4.", "", TXT_CONFIDENCE, "- SPECULATION [57%] - \uad00\ub828 \ubb38\uc11c \uc870\uac01\uc744 \uadfc\uac70\ub85c \uc555\ucd95\ud55c \ub2f5\ubcc0\uc785\ub2c8\ub2e4."])
    return {"reply": "\n".join(lines), "tools_used": ["chromadb_search"], "payload": {"type": "qa", "route": ROUTE_QA, "criteria": {"query": user_message, "fallback": "retrieval"}, "rows": [], "series": [], "citations": citations}, "citations": citations, "meta": {"intent": INTENT_DOCUMENT_QA, "confidence": "SPECULATION [57%]", "evidence_count": len(citations), "rag_density": rag_density, "company_binding": context.get("company_binding", "unresolved")}}


# ──────────────────────────────────────────────────────────────────────────
# Deep ranking_compare synthesis — multi-metric + qualitative chunks + LLM
# ──────────────────────────────────────────────────────────────────────────

_DEEP_COMPARE_SYSTEM_PROMPT = """당신은 Omega-Prime 재무 분석가입니다. 여러 한국 기업의 DART 공시 데이터를 비교해 전문가 수준의 심층 비교 분석을 생성합니다.

[입력 구조]
- STRUCTURED FACTS: 다년도·다지표 숫자. 각 값에는 (consolidated/separate) 기준과, 연간이 아닐 경우 [분기]/[반기]/[이벤트] 라벨이 붙습니다.
- DERIVED METRICS: 위 숫자에서 파생 계산된 성장률·이익률·부채비율. 기간 불일치 시 해당 항목은 비어있습니다.
- QUALITATIVE EVIDENCE: 각 기업의 사업부문·주요제품·리스크 원문 청크.

[엄격 규칙]
1. 제공된 숫자 외 새로운 수치를 만들지 마세요. 파생 계산(성장률·비율)은 허용.
2. [분기] 또는 [반기] 라벨이 붙은 값은 연간값이 아닙니다. 연간 비교용으로 사용하지 말고, 부득이 참고 시 반드시 해당 라벨을 명시하세요.
3. DERIVED METRICS에 없는 YoY·비율을 임의 계산하지 마세요. 기간 불일치로 누락된 것이므로 "자료 없음/기간 불일치"로 표기.
4. 서로 다른 산업 기업의 절대액 단순 비교는 의미가 제한적임을 서두에 반드시 명시.
5. 청크에 없는 정성 주장(시장 점유율·경쟁사 동향 등)을 만들지 마세요. 청크 문장만 인용.
6. "자료 없음"·"공시 누락"을 숨기지 말고 명시.
7. 회사명은 그대로 쓰고 대괄호로 감싸지 마세요 (예: `SK하이닉스` ✓, `[SK하이닉스]` ✗).
8. 반드시 한국어.

[출력 구조 — 정확히 이 순서·헤딩 사용]

**결론**: 한 문장으로, 어느 기업이 어느 축(성장성/수익성/안정성)에서 우위인지. 절대액 우위가 아니라 축별 우위.

**산업 맥락**
각 기업별로 1~2줄, 산업 특성(사이클성·자본집약도·네트워크 효과 등) 명시.

**핵심 비교 지표**
| 지표 | 회사A | 회사B |
|---|---|---|
| 매출 (최근 연간) | ... | ... |
| 영업이익 (최근 연간) | ... | ... |
| 영업이익률 | ... | ... |
| 순이익 | ... | ... |
| 자기자본 | ... | ... |
| 부채비율 | ... | ... |
| 매출 YoY | ... | ... |
| 영익 YoY | ... | ... |

표에서 데이터가 없는 칸은 `자료 없음`으로 채우세요. [분기]/[반기] 라벨 값은 `(N조 [분기])` 식으로 라벨을 유지.

**실적 드라이버**
각 기업별로 청크 근거 기반 주요 매출원·성장 동력. 청크 직접 인용 가능.

**핵심 리스크**
각 기업별로 청크 근거 리스크.

**판단 축별 우위**
- 성장성: 어느 쪽, 근거 한 줄
- 수익성: 어느 쪽, 근거 한 줄
- 안정성(재무건전성): 어느 쪽, 근거 한 줄

**해석 주의**
공시 기준(연결/별도) 차이, 시점 차이, 공시 누락 가능성, 산업 특성 상이.

**확신도**
INFERENCE NN% — 한 줄 근거 (데이터 충실도에 따라 70~85% 범위, NN 자리에 실제 숫자).
"""


_PERIOD_PRIORITY = {"annual": 0, "semiannual": 1, "quarterly": 2, "event": 3}

# Document-level report_type priority. Annual reports (사업보고서/감사보고서)
# are authoritative for full-year financials. 분기/반기 보고서 are partial periods.
# 주요사항보고서 is a one-off event disclosure (acquisitions, etc.) whose
# numeric tables contain transaction amounts — NOT recurring financials — and
# must be excluded entirely from the financial comparison matrix.
_REPORT_TYPE_PRIORITY = {
    "\uc0ac\uc5c5\ubcf4\uace0\uc11c": 0,        # 사업보고서 — annual
    "\uac10\uc0ac\ubcf4\uace0\uc11c": 0,        # 감사보고서 — annual audit
    "\ubc18\uae30\ubcf4\uace0\uc11c": 1,        # 반기보고서 — semiannual
    "\ubd84\uae30\ubcf4\uace0\uc11c": 2,        # 분기보고서 — quarterly
}
_REPORT_TYPE_EXCLUDED = {
    "\uc8fc\uc694\uc0ac\ud56d\ubcf4\uace0\uc11c",  # 주요사항보고서 — event disclosure
}


def _period_rank(period_type: str) -> int:
    return _PERIOD_PRIORITY.get((period_type or "").lower(), 4)


def _report_type_rank(report_type: str) -> int:
    return _REPORT_TYPE_PRIORITY.get((report_type or "").strip(), 5)


def _resolve_period(fact, metadata) -> str:
    """metadata.period_type is more reliable than fact.period_type because the
    fact-level heuristic often mislabels partial-period values as 'annual'.
    Prefer metadata, fall back to fact, then empty."""
    meta_period = (metadata.period_type if metadata else "") or ""
    if meta_period:
        return meta_period.lower()
    return (fact.period_type or "").lower()


def _fetch_metric_matrix_for_compare(
    db,
    companies: list[str],
    years: list[int],
    user_id: int | None,
) -> dict[str, dict[str, dict[int, dict[str, Any]]]]:
    """Return {metric: {company_norm: {year: {value, display, scope, period, report_type}}}}.

    Filtering + dedupe strategy (hardened against the 2026-04 data quality audit):

    1. EXCLUDE documents with report_type == '주요사항보고서' entirely —
       those contain event-specific numbers (transaction amounts, injection
       sums, etc.) which get wrongly extracted as financial facts and pollute
       the comparison matrix. See tools/diagnose_compare_facts.py for the
       discovery trace.

    2. Sort by (company, -year, report_type_rank, period_rank, -id) so that
       for a given (company, year), a 사업보고서 fact always beats a
       분기보고서 fact, which beats an older or lower-priority fact.

    3. Period/scope are resolved from DocumentMetadata first (more reliable
       than the per-fact heuristic which often mislabels partial-period
       cumulatives as 'annual').
    """
    matrix: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}
    for metric in SUMMARY_METRICS:
        matrix[metric] = {}
        try:
            rows = _kb_facts_for_metric(db, metric, companies, years, user_id=user_id)
        except Exception as exc:
            logger.warning("metric matrix fetch failed for %s: %s", metric, exc)
            continue
        # Pre-filter: drop facts sourced from excluded report types
        eligible: list[tuple] = []
        for fact, doc, metadata in rows:
            report_type = (metadata.report_type if metadata else "") or ""
            if report_type in _REPORT_TYPE_EXCLUDED:
                continue
            eligible.append((fact, doc, metadata, report_type))
        # Sort: higher-priority report types first, then period, then latest id
        eligible.sort(
            key=lambda item: (
                item[0].company_name_norm or "",
                -(item[0].fiscal_year or 0),
                _report_type_rank(item[3]),
                _period_rank(_resolve_period(item[0], item[2])),
                -(item[0].id or 0),
            ),
        )
        seen: set[tuple[str, int]] = set()
        for fact, _doc, metadata, report_type in eligible:
            comp_key = fact.company_name_norm or ""
            yr_key = fact.fiscal_year or 0
            if not comp_key or not yr_key:
                continue
            key = (comp_key, yr_key)
            if key in seen:
                continue
            seen.add(key)
            value = fact.metric_value_num
            if value is None:
                continue
            scope = (metadata.statement_scope if metadata else "") or fact.statement_scope or ""
            period = _resolve_period(fact, metadata)
            matrix[metric].setdefault(comp_key, {})[yr_key] = {
                "value": float(value),
                "display": _kb_format_value(float(value), fact.unit or "", fact.currency or ""),
                "scope": scope,
                "period": period,
                "report_type": report_type,
            }
    return matrix


def _compute_derived_compare_metrics(
    matrix: dict[str, dict[str, dict[int, dict[str, Any]]]],
    companies: list[str],
    years: list[int],
) -> dict[str, dict[str, str]]:
    """Return {company_norm: {derived_key: display_str}}.

    Rules:
    - Margins/ratios use the latest year with any data for that metric.
    - YoY is computed ONLY when BOTH the latest and prior year cells
      have period_type == 'annual'. Quarterly-vs-annual comparisons are
      skipped to prevent nonsensical ratios (e.g. Q3 cumulative vs full year).
    """
    if not years:
        return {company: {} for company in companies}
    latest_year = max(years)
    prev_year = latest_year - 1
    derived: dict[str, dict[str, str]] = {}

    def _cell(metric: str, company: str, year: int) -> dict[str, Any] | None:
        return matrix.get(metric, {}).get(company, {}).get(year)

    def _value(metric: str, company: str, year: int) -> float | None:
        cell = _cell(metric, company, year)
        return cell["value"] if cell else None

    def _is_annual(metric: str, company: str, year: int) -> bool:
        cell = _cell(metric, company, year)
        return bool(cell and cell.get("period") == "annual")

    for company in companies:
        row: dict[str, str] = {}
        revenue_latest = _value("revenue", company, latest_year)
        op_latest = _value("operating_profit", company, latest_year)
        ni_latest = _value("net_income", company, latest_year)
        liab_latest = _value("total_liabilities", company, latest_year)
        equity_latest = _value("equity", company, latest_year)

        # Margins/ratios: require annual period_type on both numerator AND denominator
        # so a quarterly op_profit / annual revenue never mixes silently.
        if (
            revenue_latest and revenue_latest != 0 and op_latest is not None
            and _is_annual("revenue", company, latest_year)
            and _is_annual("operating_profit", company, latest_year)
        ):
            row["operating_margin"] = f"{(op_latest / revenue_latest * 100):,.1f}%"
        if (
            revenue_latest and revenue_latest != 0 and ni_latest is not None
            and _is_annual("revenue", company, latest_year)
            and _is_annual("net_income", company, latest_year)
        ):
            row["net_margin"] = f"{(ni_latest / revenue_latest * 100):,.1f}%"
        if (
            equity_latest and equity_latest != 0 and liab_latest is not None
            and _is_annual("equity", company, latest_year)
            and _is_annual("total_liabilities", company, latest_year)
        ):
            row["debt_ratio"] = f"{(liab_latest / equity_latest * 100):,.1f}%"

        # YoY — strict annual-annual guard
        revenue_prev = _value("revenue", company, prev_year)
        if (
            revenue_prev is not None and revenue_prev != 0
            and revenue_latest is not None
            and _is_annual("revenue", company, latest_year)
            and _is_annual("revenue", company, prev_year)
        ):
            row["revenue_yoy"] = f"{((revenue_latest - revenue_prev) / abs(revenue_prev) * 100):+,.1f}%"

        op_prev = _value("operating_profit", company, prev_year)
        if (
            op_prev is not None and op_prev != 0
            and op_latest is not None
            and _is_annual("operating_profit", company, latest_year)
            and _is_annual("operating_profit", company, prev_year)
        ):
            row["op_yoy"] = f"{((op_latest - op_prev) / abs(op_prev) * 100):+,.1f}%"

        derived[company] = row
    return derived


def _fetch_qualitative_compare_context(
    companies: list[str],
    company_display_map: dict[str, str],
    user_id: int = 0,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Return {company_norm: {"business": [hits], "risk": [hits]}}."""
    from services.cognitive_search_safe import cognitive_search_safe

    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for company in companies:
        display = company_display_map.get(company, company)
        business_hits: list[dict[str, Any]] = []
        risk_hits: list[dict[str, Any]] = []
        try:
            business_hits = cognitive_search_safe(
                query=f"{display} \uc0ac\uc5c5\ubd80\ubb38 \uc8fc\uc694\uc81c\ud488 \ub9e4\ucd9c\uad6c\uc131",
                top_k=2,
                company_filter=company,
                user_id=user_id,
            ) or []
        except Exception as exc:
            logger.warning("qual business chunks failed for %s: %s", company, exc)
        try:
            risk_hits = cognitive_search_safe(
                query=f"{display} \ub9ac\uc2a4\ud06c \uc704\ud5d8\uc694\uc778 \uacbd\uc7c1",
                top_k=2,
                company_filter=company,
                user_id=user_id,
            ) or []
        except Exception as exc:
            logger.warning("qual risk chunks failed for %s: %s", company, exc)
        out[company] = {"business": business_hits, "risk": risk_hits}
    return out


def _build_deep_compare_prompt(
    user_message: str,
    primary_metric_label: str,
    company_display_map: dict[str, str],
    companies: list[str],
    years: list[int],
    matrix: dict[str, dict[str, dict[int, dict[str, Any]]]],
    derived: dict[str, dict[str, str]],
    qual: dict[str, dict[str, list[dict[str, Any]]]],
) -> str:
    lines: list[str] = []
    lines.append(f"\uc0ac\uc6a9\uc790 \uc9c8\ubb38: {user_message}")
    lines.append(
        "\ube44\uad50 \ub300\uc0c1: " + ", ".join(company_display_map.get(c, c) for c in companies)
    )
    lines.append(f"\uc8fc\uc694 \uad00\uc2ec \uc9c0\ud45c: {primary_metric_label}")
    if years:
        lines.append(f"\ubd84\uc11d \uc5f0\ub3c4 \ubc94\uc704: {min(years)}~{max(years)}\ub144")
    lines.append("")
    lines.append("=" * 50)
    lines.append("STRUCTURED FACTS (\uad6c\uc870\ud654 \uc7ac\ubb34)")
    lines.append("=" * 50)
    period_label_map = {"semiannual": "\ubc18\uae30", "quarterly": "\ubd84\uae30", "event": "\uc774\ubca4\ud2b8"}
    for metric in SUMMARY_METRICS:
        metric_data = matrix.get(metric, {})
        if not any(metric_data.get(c) for c in companies):
            continue
        lines.append(f"\n[{_kb_metric_label(metric)}]")
        for company in companies:
            display = company_display_map.get(company, company)
            year_dict = metric_data.get(company, {})
            if not year_dict:
                lines.append(f"  - {display}: \uc790\ub8cc \uc5c6\uc74c")
                continue
            parts: list[str] = []
            for yr in sorted(year_dict.keys(), reverse=True):
                cell = year_dict[yr]
                scope_suffix = f" ({cell['scope']})" if cell.get("scope") else ""
                period = cell.get("period") or ""
                period_suffix = ""
                if period and period != "annual":
                    period_suffix = f" [{period_label_map.get(period, period)}]"
                parts.append(f"{yr}\ub144: {cell['display']}{scope_suffix}{period_suffix}")
            lines.append(f"  - {display}: " + " / ".join(parts))

    lines.append("")
    lines.append("=" * 50)
    lines.append("DERIVED METRICS (\ud30c\uc0dd \uacc4\uc0b0)")
    lines.append("=" * 50)
    derived_labels = [
        ("operating_margin", "\uc601\uc5c5\uc774\uc775\ub960"),
        ("net_margin", "\uc21c\uc774\uc775\ub960"),
        ("debt_ratio", "\ubd80\ucc44\ube44\uc728"),
        ("revenue_yoy", "\ub9e4\ucd9c YoY"),
        ("op_yoy", "\uc601\uc775 YoY"),
    ]
    for company in companies:
        display = company_display_map.get(company, company)
        row = derived.get(company, {})
        lines.append(f"\n[{display}]")
        if not row:
            lines.append("  - \ud30c\uc0dd \uacc4\uc0b0 \ubd88\uac00 (\uae30\ucd08 \uc790\ub8cc \ubd80\uc871)")
            continue
        for key, label in derived_labels:
            if key in row:
                lines.append(f"  - {label}: {row[key]}")

    lines.append("")
    lines.append("=" * 50)
    lines.append("QUALITATIVE EVIDENCE (\uc815\uc131 \uadfc\uac70 \uccad\ud06c)")
    lines.append("=" * 50)
    for company in companies:
        display = company_display_map.get(company, company)
        lines.append(f"\n<<{display}>>")
        biz = qual.get(company, {}).get("business") or []
        if biz:
            lines.append("  [\uc0ac\uc5c5/\uc81c\ud488]")
            for idx, hit in enumerate(biz[:2], start=1):
                snippet = _clean_text(str(hit.get("chunk") or ""), 280)
                fn = (hit.get("filename") or "")[:35]
                if snippet:
                    lines.append(f"  {idx}. ({fn}) {snippet}")
        else:
            lines.append("  [\uc0ac\uc5c5/\uc81c\ud488] \uccad\ud06c \uc5c6\uc74c")
        risk = qual.get(company, {}).get("risk") or []
        if risk:
            lines.append("  [\ub9ac\uc2a4\ud06c]")
            for idx, hit in enumerate(risk[:2], start=1):
                snippet = _clean_text(str(hit.get("chunk") or ""), 280)
                fn = (hit.get("filename") or "")[:35]
                if snippet:
                    lines.append(f"  {idx}. ({fn}) {snippet}")
        else:
            lines.append("  [\ub9ac\uc2a4\ud06c] \uccad\ud06c \uc5c6\uc74c")

    lines.append("")
    lines.append("=" * 50)
    lines.append("\uc704 \ub370\uc774\ud130\ub9cc\uc744 \uadfc\uac70\ub85c Omega-Prime \uc2ec\uce35 \ube44\uad50 \ud3ec\ub9f7\uc73c\ub85c \ub2f5\ubcc0\ud558\uc138\uc694.")
    return "\n".join(lines)


async def _deep_ranking_compare(
    user_message: str,
    context: dict[str, Any],
    db,
    user_id: int,
) -> dict[str, Any]:
    """Deep multi-metric + qualitative ranking_compare with LLM synthesis.

    Emits a single structured telemetry log line `Ω DeepCompare —` on every
    invocation (success or fallback). This line is the run-time evidence that
    the deep path executed and documents which pieces of context were
    available vs. missing. Grep for `Ω DeepCompare` in the backend log to
    produce an audit trail.
    """
    telemetry: dict[str, Any] = {
        "companies": [],
        "target_year": None,
        "analysis_years": [],
        "primary_metric": "",
        "matrix_cell_count": 0,
        "matrix_annual_cells": 0,
        "matrix_nonannual_cells": 0,
        "derived_company_count": 0,
        "derived_metric_count": 0,
        "qual_business_hits": 0,
        "qual_risk_hits": 0,
        "llm_ok": False,
        "llm_reply_len": 0,
        "fallback_reason": "",
        "evidence_count": 0,
    }

    def _emit_telemetry(reason: str = "") -> None:
        if reason:
            telemetry["fallback_reason"] = reason
        logger.info(
            "\u03a9 DeepCompare \u2014 companies=%s years=%s metric=%s "
            "matrix_cells=%d (annual=%d non_annual=%d) derived=%d/%d "
            "qual_biz=%d qual_risk=%d llm_ok=%s reply_len=%d evidence=%d fallback=%s",
            telemetry["companies"],
            telemetry["analysis_years"],
            telemetry["primary_metric"],
            telemetry["matrix_cell_count"],
            telemetry["matrix_annual_cells"],
            telemetry["matrix_nonannual_cells"],
            telemetry["derived_company_count"],
            telemetry["derived_metric_count"],
            telemetry["qual_business_hits"],
            telemetry["qual_risk_hits"],
            telemetry["llm_ok"],
            telemetry["llm_reply_len"],
            telemetry["evidence_count"],
            telemetry["fallback_reason"] or "none",
        )

    # ── Defense in Depth: classifier를 우회해 진입한 event listing 쿼리 차단 ──
    # (직접 호출 경로나 context 주입 등으로 classifier 가드가 적용되지 않은 경우를 방어)
    if _is_event_listing_query(user_message):
        _emit_telemetry(reason="event_listing_misroute")
        reply_lines = [
            f"{TXT_CONCLUSION}: \uc774 \uc9c8\ubb38\uc740 \uae30\uc5c5 \uc774\ubca4\ud2b8(\uc0c1\uc7a5\ud3d0\uc9c0\u00b7\uad00\ub9ac\uc885\ubaa9\u00b7\uac10\uc0ac\uc758\uacac \ub4f1)\uc5d0 \uad00\ud55c \uac83\uc73c\ub85c, \ud604\uc7ac \uc778\ub371\uc2a4(\uae30\uc5c5 \uc7ac\ubb34\u00b7\uc2e0\uc6a9 \ubb38\uc11c)\uc640 \ubd88\uc77c\uce58\ud569\ub2c8\ub2e4.",
            "",
            TXT_EVIDENCE,
            "1. \uac80\uc0c9 \ub300\uc0c1 \ubb38\uc11c\ub294 \uc7ac\ubb34\uc81c\ud45c\u00b7\uc0ac\uc5c5\ubcf4\uace0\uc11c\u00b7\uc2e0\uc6a9\ubd84\uc11d \uc704\uc8fc\uc774\uba70, \uc774\ubca4\ud2b8 \uacf5\uc2dc\u00b7\uc2ec\uc0ac \ubb38\uc11c\ub294 \ubcc4\ub3c4 \uc778\ub371\uc2f1\uc774 \ud544\uc694\ud569\ub2c8\ub2e4.",
            "2. \uc774 \uc720\ud615 \uc9c8\uc758\ub294 \uad6c\uc870\ud654 \uc774\ubca4\ud2b8 \ud14c\uc774\ube14(corp_events, Phase 3 \uc608\uc815)\uc774 \uc788\uc5b4\uc57c \uc9c1\uc811 \ub2f5\ubcc0 \uac00\ub2a5\ud569\ub2c8\ub2e4.",
            "",
            TXT_RISK,
            "- \ud604\uc7ac \ud30c\uc774\ud504\ub77c\uc778\uc5d0 \uc774\ubca4\ud2b8 \uc804\uc6a9 \ub9ac\ud2b8\ub9ac\ubc84\uac00 \uc5c6\uc5b4, \uc0dd\uc131 \uc2dc \uad00\ub828 \uc5c6\ub294 \uae30\uc5c5 \ube44\uad50\ub85c \uadc0\uacb0\ub420 \uc704\ud5d8\uc774 \uc788\uc2b5\ub2c8\ub2e4.",
            "",
            TXT_CONFIDENCE,
            "- INFERENCE [88%] - \uc774\ubca4\ud2b8 \uc2e0\ud638\uc5b4 \uba85\ud655, \uc778\ub371\uc2a4 \ucee4\ubc84\ub9ac\uc9c0 \ubd80\uc871",
        ]
        return {
            "reply": "\n".join(reply_lines),
            "tools_used": ["intent_guard"],
            "payload": {
                "type": "qa",
                "route": "event_listing_mismatch",
                "criteria": {"event_listing_detected": True, "query": user_message},
                "rows": [],
                "series": [],
                "citations": [],
            },
            "citations": [],
            "meta": {
                "intent": INTENT_DOCUMENT_QA,
                "confidence": "INFERENCE [88%]",
                "evidence_count": 0,
                "rag_density": RAG_R0,
                "company_binding": "event_listing_bypass",
            },
        }

    base = answer_ranking_compare(user_message, context, db, user_id=user_id)
    base_payload = base.get("payload") or {}
    base_rows = base_payload.get("rows") or []

    if not base_rows:
        telemetry["evidence_count"] = len(base.get("citations") or [])
        _emit_telemetry(reason="base_no_rows")
        return _augment_meta(
            base,
            intent=ROUTE_RANKING_COMPARE,
            rag_density=RAG_R1,
            company_binding=context.get("company_binding", "unresolved"),
        )

    companies_norm: list[str] = []
    company_display_map: dict[str, str] = {}
    for row in base_rows:
        norm = row.get("company_name_norm") or ""
        if not norm or norm in company_display_map:
            continue
        companies_norm.append(norm)
        company_display_map[norm] = row.get("company_name") or norm

    telemetry["companies"] = companies_norm

    if not companies_norm:
        _emit_telemetry(reason="no_companies_extracted")
        return _augment_meta(
            base,
            intent=ROUTE_RANKING_COMPARE,
            rag_density=RAG_R1,
            company_binding=context.get("company_binding", "unresolved"),
        )

    target_year = base_payload.get("criteria", {}).get("fiscal_year")
    if not target_year:
        try:
            target_year = _kb_latest_year(db, companies_norm, user_id=user_id)
        except Exception:
            target_year = datetime.now().year - 1
    telemetry["target_year"] = target_year
    years = [y for y in (target_year - 2, target_year - 1, target_year) if y and y >= 2000]
    telemetry["analysis_years"] = years

    primary_metric = base_payload.get("criteria", {}).get("metric_name") or "operating_profit"
    primary_metric_label = _kb_metric_label(primary_metric)
    telemetry["primary_metric"] = primary_metric

    matrix = _fetch_metric_matrix_for_compare(db, companies_norm, years, user_id)
    # Count filled cells & period breakdown for run-time audit
    for metric_dict in matrix.values():
        for company_dict in metric_dict.values():
            for cell in company_dict.values():
                telemetry["matrix_cell_count"] += 1
                if cell.get("period") == "annual":
                    telemetry["matrix_annual_cells"] += 1
                else:
                    telemetry["matrix_nonannual_cells"] += 1

    derived = _compute_derived_compare_metrics(matrix, companies_norm, years)
    telemetry["derived_company_count"] = sum(1 for v in derived.values() if v)
    telemetry["derived_metric_count"] = sum(len(v) for v in derived.values())

    qual = _fetch_qualitative_compare_context(companies_norm, company_display_map)
    for groups in qual.values():
        telemetry["qual_business_hits"] += len(groups.get("business") or [])
        telemetry["qual_risk_hits"] += len(groups.get("risk") or [])

    user_prompt = _build_deep_compare_prompt(
        user_message=user_message,
        primary_metric_label=primary_metric_label,
        company_display_map=company_display_map,
        companies=companies_norm,
        years=years,
        matrix=matrix,
        derived=derived,
        qual=qual,
    )

    llm_reply = ""
    try:
        llm_reply = await _get_llm_client().complete_text(
            system_prompt=_DEEP_COMPARE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
        )
        llm_reply = (llm_reply or "").strip()
        telemetry["llm_ok"] = bool(llm_reply)
        telemetry["llm_reply_len"] = len(llm_reply)
    except Exception as exc:
        logger.warning("Deep compare LLM synthesis failed: %s", exc)
        llm_reply = ""

    if not llm_reply:
        telemetry["evidence_count"] = len(base.get("citations") or [])
        _emit_telemetry(reason="deep_compare_llm_failed")
        return _augment_meta(
            base,
            intent=ROUTE_RANKING_COMPARE,
            rag_density=RAG_R1,
            company_binding=context.get("company_binding", "unresolved"),
            fallback_reason="deep_compare_llm_failed",
        )

    existing_citations: list[dict[str, Any]] = list(base.get("citations") or [])
    seen_doc_ids: set[Any] = {c.get("document_id") for c in existing_citations if c.get("document_id")}
    for company_norm, groups in qual.items():
        for group_name in ("business", "risk"):
            for hit in (groups.get(group_name) or [])[:1]:
                doc_id = hit.get("doc_id")
                if not doc_id or doc_id in seen_doc_ids:
                    continue
                seen_doc_ids.add(doc_id)
                existing_citations.append({
                    "document_id": doc_id,
                    "filename": hit.get("filename", ""),
                    "company": hit.get("company", "") or company_display_map.get(company_norm, ""),
                    "source_text": _clean_text(str(hit.get("chunk") or ""), 300),
                })

    enriched_payload = dict(base_payload)
    enriched_payload["citations"] = existing_citations
    enriched_payload["deep_compare"] = True
    enriched_payload["analysis_years"] = years

    telemetry["evidence_count"] = len(existing_citations)
    _emit_telemetry(reason="")

    result = {
        "reply": llm_reply,
        "tools_used": ["structured_facts", "chromadb_search", "llm_deep_compare"],
        "payload": enriched_payload,
        "citations": existing_citations,
        "meta": {
            "intent": ROUTE_RANKING_COMPARE,
            "confidence": "INFERENCE [82%]",
            "evidence_count": len(existing_citations),
        },
    }
    return _augment_meta(
        result,
        intent=ROUTE_RANKING_COMPARE,
        rag_density=RAG_R2,
        company_binding=context.get("company_binding", "unresolved"),
    )


_TRIVIAL_INPUT_RE = re.compile(r"^[\s\W_]*$", re.UNICODE)


def _is_trivial_input(message: str) -> bool:
    """문장부호/공백/특수문자뿐이거나 의미 있는 글자가 없는 입력 감지"""
    if not message or not message.strip():
        return True
    stripped = message.strip()
    # 한글/영문/숫자 글자가 2자 미만이면 trivial
    meaningful = re.sub(r"[^0-9A-Za-z\uac00-\ud7a3]", "", stripped)
    return len(meaningful) < 2


async def run_agent(user_message: str, history: list[dict[str, Any]], user_id: int, db) -> dict[str, Any]:
    profile = get_chatbot_profile()

    # ── 문서 보유 여부 사전 확인: 분석 완료 문서가 없으면 즉시 차단 ──
    analyzed_count = (
        db.query(func.count(Document.id))
        .filter(Document.user_id == user_id, Document.status == "analyzed")
        .scalar() or 0
    )
    if analyzed_count == 0:
        return {
            "reply": "\n".join([
                "**분석된 문서가 없습니다.**",
                "",
                "Omega Cortex는 업로드된 공시 문서를 기반으로 답변합니다.",
                "문서를 먼저 업로드하고 분석을 완료해 주세요.",
                "",
                "업로드 후 분석이 완료되면 다음과 같은 질문을 사용할 수 있습니다:",
                "- `삼성전자 작년 영업이익은?`",
                "- `최근 3년 매출 추이`",
                "- `A사 vs B사 영업이익 비교`",
            ]),
            "tools_used": [],
            "meta": {
                "intent": "no_documents",
                "confidence": "AXIOM [99%]",
                "evidence_count": 0,
                "rag_density": RAG_R0,
                "company_binding": "unresolved",
            },
        }

    # ── Trivial 입력 차단: ".", "?", " " 같은 잡음 입력 ──
    if _is_trivial_input(user_message):
        return {
            "reply": "\n".join([
                "\uc9c8\ubb38\uc774 \ube44\uc5b4 \uc788\uac70\ub098 \ub108\ubb34 \uc9e7\uc2b5\ub2c8\ub2e4.",
                "",
                "\uc608\uc2dc:",
                "- `\uc0bc\uc131\uc804\uc790 \uc791\ub144 \uc2e4\uc801`",
                "- `\ub124\uc774\ubc84 \ucd5c\uadfc 3\ub144 \ub9e4\ucd9c \ucd94\uc774`",
                "- `\uce74\uce74\uc624 vs \ub124\uc774\ubc84 \uc601\uc5c5\uc774\uc775`",
            ]),
            "tools_used": [],
            "meta": {"intent": "trivial_input", "confidence": "AXIOM [99%]", "evidence_count": 0, "rag_density": RAG_R0, "company_binding": "unresolved"},
        }

    # ── 히스토리 토큰 트리밍 (병행 요청 시 VRAM 보호) ──
    try:
        from services.session_pool import get_session_pool
        history = get_session_pool().get_trimmed_history(user_id, history)
    except Exception as _sp_err:
        logger.debug("SessionPool 트리밍 스킵: %s", _sp_err)

    context = _build_context(user_message, history, db, user_id)
    top_intent, params = _classify_top(user_message, context)

    # ── Observability: query entry log ──
    logger.info(
        "Ω Agent — raw_query=%s | company=%s | binding=%s | route=%s | aliases=%s | candidates=%s",
        user_message[:60],
        context.get("company", ""),
        context.get("company_binding", "unresolved"),
        top_intent,
        aliases_for_company(context.get("company", ""))[:3] if context.get("company") else [],
        [c.get("canonical", "") for c in (context.get("company_candidates") or [])[:3]],
    )

    if top_intent in {"greeting", "identity", "capability_help", "product_help"}:
        return _meta_reply(top_intent, profile)
    if top_intent == "time":
        return {"reply": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST"), "tools_used": [], "meta": {"intent": "time", "confidence": "AXIOM [99%]", "evidence_count": 0, "rag_density": RAG_R0, "company_binding": "unresolved"}}
    if top_intent == "company_stats":
        return _format_company_stats(user_id, db)
    if top_intent == "doc_stats":
        return {"reply": _format_doc_stats(user_id, db), "tools_used": ["get_document_stats"], "meta": {"intent": "document_stats", "confidence": "INFERENCE [88%]", "evidence_count": 0, "rag_density": RAG_R0, "company_binding": "unresolved"}}
    if top_intent == "doc_detail":
        return {"reply": _format_doc_detail(params["document_id"], user_id, db), "tools_used": ["get_document_detail"], "meta": {"intent": "document_detail", "confidence": "INFERENCE [88%]", "evidence_count": 0, "rag_density": RAG_R0, "company_binding": "unresolved"}}
    if top_intent == "search_docs":
        docs = _search_docs(user_id, db, context, limit=10)
        if not docs:
            return {"reply": TXT_NO_DATA, "tools_used": ["search_my_documents"], "meta": {"intent": "search_my_documents", "confidence": "EXPLORATION [35%]", "evidence_count": 0, "rag_density": RAG_R0, "company_binding": context.get("company_binding", "unresolved")}}
        lines = [f"{TXT_CONCLUSION}: \uc870\uac74\uc5d0 \ub9de\ub294 \ubb38\uc11c\ub97c \ucc3e\uc558\uc2b5\ub2c8\ub2e4.", "", TXT_EVIDENCE]
        missing_company_label = "\ud68c\uc0ac\uba85 \ubbf8\uc0c1"
        lines.extend(
            f"{idx}. \ubb38\uc11c #{item['id']} | {item['filename']} | {item.get('company_name') or missing_company_label}"
            for idx, item in enumerate(docs, start=1)
        )
        return {"reply": "\n".join(lines), "tools_used": ["search_my_documents"], "meta": {"intent": "search_my_documents", "confidence": "INFERENCE [80%]", "evidence_count": len(docs), "rag_density": RAG_R0, "company_binding": context.get("company_binding", "unresolved")}}
    if top_intent == "market_scan":
        return _format_recent_market_scan(user_id, db, limit=5)
    if top_intent == "dart":
        result = await _search_dart(params["company_name"])
        if result.get("error"):
            return {"reply": result["error"], "tools_used": ["search_dart_filings"], "meta": {"intent": "dart_search", "confidence": "SPECULATION [55%]", "evidence_count": 0, "rag_density": RAG_R0, "company_binding": context.get("company_binding", "unresolved")}}
        lines = [f"{TXT_CONCLUSION}: {params['company_name']} \uad00\ub828 \ucd5c\uadfc \uacf5\uc2dc\uc785\ub2c8\ub2e4.", "", TXT_EVIDENCE]
        lines.extend((f"{idx}. [{item['corp_name']} | {item['report_nm']} | {item['rcept_dt']}]({item['url']})" if item.get("url") else f"{idx}. {item['corp_name']} | {item['report_nm']} | {item['rcept_dt']}") for idx, item in enumerate(result.get("results", []), start=1))
        return {"reply": "\n".join(lines), "tools_used": ["search_dart_filings"], "meta": {"intent": "dart_search", "confidence": "INFERENCE [83%]", "evidence_count": len(result.get("results", [])), "rag_density": RAG_R0, "company_binding": context.get("company_binding", "unresolved")}}

    classification = _classify_professional(user_message, context)
    logger.info(
        "Ω Classify — intent=%s route=%s rag=%s missing=%s",
        classification.get("intent"), classification.get("route"), classification.get("rag_density"), classification.get("missing_variable"),
    )
    followup = _maybe_followup(classification, context)
    if followup is not None:
        return followup
    if classification["route"] == ROUTE_RANKING_COMPARE:
        return await _deep_ranking_compare(user_message, context, db, user_id=user_id)
    if classification["route"] == ROUTE_TREND:
        return _augment_meta(answer_trend(user_message, context, db, user_id=user_id), intent=ROUTE_TREND, rag_density=RAG_R1, company_binding=context.get("company_binding", "unresolved"))
    if classification["route"] == ROUTE_COMPANY_SUMMARY:
        structured_summary = answer_company_summary(user_message, context, db, user_id=user_id)
        if not _payload_has_content(structured_summary.get("payload")) and structured_summary.get("reply") == TXT_NO_DATA:
            judged = await _retrieve(user_message, context, ROUTE_QA, RAG_R2, db, user_id=user_id)
            return await _generic_retrieval_answer(user_message, judged, RAG_R2, context)
        return _augment_meta(structured_summary, intent=ROUTE_COMPANY_SUMMARY, rag_density=RAG_R1, company_binding=context.get("company_binding", "unresolved"))
    if classification["route"] == ROUTE_STOCK_OUTLOOK:
        structured = answer_company_summary(f"{context['company']} \ucd5c\uadfc \uc2e4\uc801 \uc694\uc57d", {"company": context["company"], "companies": [context["company"]], "year_filters": context.get("year_filters") or [], "metric": context.get("metric", ""), "trend_span": context.get("trend_span", 3)}, db, user_id=user_id)
        judged = await _retrieve(user_message, context, ROUTE_STOCK_OUTLOOK, RAG_R2, db, user_id=user_id)
        if not judged["enough_evidence"]:
            judged = await _retrieve(user_message, context, ROUTE_STOCK_OUTLOOK, RAG_R3, db, user_id=user_id)
            if judged["enough_evidence"]:
                return _stock_outlook_answer(user_message, context, structured, judged, RAG_R3)
            return _stock_outlook_shortage(context, judged, RAG_R3)
        return _stock_outlook_answer(user_message, context, structured, judged, RAG_R2)

    structured_qa = answer_qa(user_message, context, db, user_id=user_id)
    if _payload_has_content(structured_qa.get("payload")) or structured_qa.get("reply") != TXT_NO_DATA:
        return _augment_meta(structured_qa, intent=INTENT_DOCUMENT_QA, rag_density=RAG_R1, company_binding=context.get("company_binding", "unresolved"))
    # 회사 바인딩이 없어도 RAG + Reranker fallback으로 위임 — 이벤트/집계/탐색 쿼리 지원
    judged = await _retrieve(user_message, context, ROUTE_QA, RAG_R2, db)
    return await _generic_retrieval_answer(user_message, judged, RAG_R2, context)
