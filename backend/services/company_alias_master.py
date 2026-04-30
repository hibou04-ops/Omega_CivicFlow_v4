# -*- coding: utf-8 -*-
from __future__ import annotations

import re


_CORP_SUFFIXES = (
    "주식회사",
    "(주)",
    "㈜",
)


_CANONICAL_ALIAS_GROUPS: dict[str, list[str]] = {
    "SK하이닉스": [
        "SK하이닉스",
        "sk하이닉스",
        "sk 하이닉스",
        "SK hynix",
        "hynix",
        "하이닉스",
        "에스케이하이닉스",
        "에스케이 하이닉스",
    ],
    "NAVER": [
        "NAVER",
        "naver",
        "네이버",
    ],
    "카카오": [
        "카카오",
        "kakao",
    ],
    "삼성전자": [
        "삼성전자",
        "samsung electronics",
        "삼전",
        "삼성",
        "samsung",
    ],
    "LG에너지솔루션": [
        "LG에너지솔루션",
        "LG 에너지솔루션",
        "lg에너지솔루션",
        "LG에너지",
        "엘지에너지솔루션",
        "엘지 에너지솔루션",
        "엘지에너지",
    ],
    "LG화학": [
        "LG화학",
        "LG 화학",
        "lg화학",
        "엘지화학",
        "엘지 화학",
    ],
    "LG전자": [
        "LG전자",
        "LG 전자",
        "lg전자",
        "엘지전자",
        "엘지 전자",
    ],
    "LG생활건강": [
        "LG생활건강",
        "LG 생활건강",
        "lg생활건강",
        "엘지생활건강",
        "엘지 생활건강",
        "LG Household",
        "lg household",
    ],
    "현대자동차": [
        "현대자동차",
        "현대차",
        "현대",
        "hyundai motor",
        "hyundai",
    ],
    "현대글로비스": [
        "현대글로비스",
        "hyundai glovis",
        "글로비스",
    ],
    "현대다이모스": [
        "현대다이모스",
        "hyundai dymos",
        "다이모스",
    ],
    "POSCO홀딩스": [
        "POSCO홀딩스",
        "POSCO 홀딩스",
        "posco홀딩스",
        "posco holdings",
        "포스코홀딩스",
        "포스코 홀딩스",
        "포스코",
    ],
    "기아": [
        "기아",
        "기아자동차",
        "기아차",
    ],
    "KB금융": [
        "KB금융",
        "KB금융지주",
        "kb금융",
        "kb 금융",
        "케이비금융",
        "케이비 금융",
    ],
    "신한지주": [
        "신한지주",
        "신한금융",
        "신한금융지주",
    ],
    "하나금융지주": [
        "하나금융지주",
        "하나금융",
    ],
    "셀트리온": [
        "셀트리온",
    ],
    "삼성바이오로직스": [
        "삼성바이오로직스",
        "삼바",
    ],
    "현대모비스": [
        "현대모비스",
    ],
    "두산에너빌리티": [
        "두산에너빌리티",
        "두산에너",
    ],
    "포스코퓨처엠": [
        "포스코퓨처엠",
        "포스코 퓨처엠",
        "posco future m",
    ],
    "크래프톤": [
        "크래프톤",
        "krafton",
    ],
    "HD현대에너지솔루션": [
        "HD현대에너지솔루션",
        "HD 현대에너지솔루션",
        "현대에너지솔루션",
    ],
    "HD현대마린솔루션": [
        "HD현대마린솔루션",
        "HD 현대마린솔루션",
        "현대마린솔루션",
    ],
    "HD현대미포": [
        "HD현대미포",
        "HD 현대미포",
        "현대미포",
    ],
    "HD현대마린엔진": [
        "HD현대마린엔진",
        "HD 현대마린엔진",
        "현대마린엔진",
    ],
    "HD현대일렉트릭": [
        "HD현대일렉트릭",
        "HD 현대일렉트릭",
        "현대일렉트릭",
    ],
    "HD현대건설기계": [
        "HD현대건설기계",
        "HD 현대건설기계",
        "현대건설기계",
        "HD건설기계",
    ],
    "한화": [
        "한화",
    ],
    "한화에어로스페이스": [
        "한화에어로스페이스",
        "한화 에어로스페이스",
        "한에로",
        "한화에어로",
    ],
    "아모레퍼시픽": [
        "아모레퍼시픽",
    ],
    "이수페타시스": [
        "이수페타시스",
    ],
    "제주반도체": [
        "제주반도체",
    ],
    "SK스퀘어": [
        "SK스퀘어",
        "SK 스퀘어",
        "에스케이스퀘어",
        "에스케이 스퀘어",
    ],
    "SK이노베이션": [
        "SK이노베이션",
        "SK 이노베이션",
        "에스케이이노베이션",
        "sk이노베이션",
    ],
    "SK텔레콤": [
        "SK텔레콤",
        "SK 텔레콤",
        "에스케이텔레콤",
        "SKT",
        "skt",
    ],
    "삼성SDI": [
        "삼성SDI",
        "삼성sdi",
        "삼성 SDI",
        "samsung sdi",
    ],
    "삼성물산": [
        "삼성물산",
    ],
    "삼성생명": [
        "삼성생명",
    ],
    "현대건설": [
        "현대건설",
    ],
    "현대제철": [
        "현대제철",
    ],
    "현대위아": [
        "현대위아",
    ],
    "무림PP": [
        "무림PP",
        "무림pp",
        "무림 PP",
        "무림P&P",
        "무림 P&P",
        "무림피앤피",
        "무림 피앤피",
        "무림피엔피",
        "Moorim P&P",
        "moorim p&p",
        "moorimpp",
    ],
    "무림SP": [
        "무림SP",
        "무림sp",
        "무림 SP",
        "무림S&P",
    ],
    "무림페이퍼": [
        "무림페이퍼",
        "무림 페이퍼",
        "moorim paper",
        "Moorim Paper",
    ],
}


def _normalize_alias_key(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip())
    for suffix in _CORP_SUFFIXES:
        text = text.replace(suffix, "")
    return text.lower()


def _fallback_clean_name(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip())
    for suffix in _CORP_SUFFIXES:
        text = text.replace(suffix, "")
    return text


def _build_company_aliases() -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for canonical, aliases in _CANONICAL_ALIAS_GROUPS.items():
        for alias in [canonical, *aliases]:
            key = _normalize_alias_key(alias)
            if key:
                alias_map[key] = canonical
    return alias_map


COMPANY_ALIASES: dict[str, str] = _build_company_aliases()


def normalize_company_name(name: str) -> str:
    key = _normalize_alias_key(name)
    if not key:
        return ""
    return COMPANY_ALIASES.get(key, _fallback_clean_name(name))


def aliases_for_company(canonical: str) -> list[str]:
    normalized = normalize_company_name(canonical)
    aliases = list(_CANONICAL_ALIAS_GROUPS.get(normalized, []))
    if normalized and normalized not in aliases:
        aliases.insert(0, normalized)
    return aliases


def canonical_company_names() -> list[str]:
    return sorted(_CANONICAL_ALIAS_GROUPS.keys())
