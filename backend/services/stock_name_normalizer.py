"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Stock Name Normalizer
종목명 정규화 엔진 (해밀토니안 사전 매핑)

DART corpCode.xml의 공식 종목명을 기반으로,
LLM이 생성한 한국어 음독 회사명을 공식 종목명으로 변환합니다.

예: "에스케이하이닉스" → "SK하이닉스"
    "엘지전자" → "LG전자"
    "케이비금융지주" → "KB금융지주"
═══════════════════════════════════════════════════════
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 영문 약어 → 한국어 음독 매핑 (역방향 변환용)
# ═══════════════════════════════════════════════════════

# 영문→음독: LLM이 "SK" 대신 "에스케이"로 쓰는 패턴 역변환
PHONETIC_TO_ENGLISH = {
    "에스케이": "SK",
    "엘지": "LG",
    "케이비": "KB",
    "엔에이치": "NH",
    "케이티": "KT",
    "디비": "DB",
    "엘에스": "LS",
    "비엔케이": "BNK",
    "디지비": "DGB",
    "제이비": "JB",
    "에이치디": "HD",
    "씨제이": "CJ",
    "에스디": "SD",
    "지에스": "GS",
    "에이치엘비": "HLB",
    "에이치케이": "HK",
    "이마트": "이마트",  # 이건 원래 한국어
    "삼성에스디에스": "삼성SDS",
    "엘엔씨바이오": "LnCBio",
    "티씨케이": "TCK",
    "에스에이엠티": "SAMT",
    "에이티넘인베스트": "에이티넘인베스트",
    "에프엔가이드": "FnGuide",
    "엔씨소프트": "NCSOFT",
    "아이오케이": "IOK",
    "에코프로비엠": "에코프로비엠",
    "카카오": "카카오",
    "네이버": "NAVER",
    "포스코": "POSCO",
    "제이와이피": "JYP",
    "와이지": "YG",
    "에스엠": "SM",
    "하이브": "하이브",
    "크래프톤": "크래프톤",
    "셀트리온": "셀트리온",
    "에이피알": "APR",
    "디엘": "DL",
    "에이에스엠엘": "ASML",
    "티엘비": "TLB",
    "에이치엘": "HL",
    "티와이홀딩스": "TY홀딩스",
}

# 완전 일치 특수 매핑 (정확히 매핑이 필요한 종목)
EXACT_OVERRIDE = {
    "에스케이하이닉스": "SK하이닉스",
    "에스케이텔레콤": "SK텔레콤",
    "에스케이이노베이션": "SK이노베이션",
    "에스케이바이오팜": "SK바이오팜",
    "에스케이바이오사이언스": "SK바이오사이언스",
    "에스케이케미칼": "SK케미칼",
    "에스케이가스": "SK가스",
    "에스케이네트웍스": "SK네트웍스",
    "에스케이렌터카": "SK렌터카",
    "에스케이스퀘어": "SK스퀘어",
    "에스케이씨": "SKC",
    "에스케이디스커버리": "SK디스커버리",
    "에스케이아이이테크놀로지": "SK아이이테크놀로지",
    "에스케이실트론": "SK실트론",
    "엘지전자": "LG전자",
    "엘지화학": "LG화학",
    "엘지디스플레이": "LG디스플레이",
    "엘지유플러스": "LG유플러스",
    "엘지이노텍": "LG이노텍",
    "엘지에너지솔루션": "LG에너지솔루션",
    "엘지생활건강": "LG생활건강",
    "엘지헬로비전": "LG헬로비전",
    "엘지씨엔에스": "LG CNS",
    "케이비금융지주": "KB금융",
    "케이비금융": "KB금융",
    "케이비증권": "KB증권",
    "케이비국민은행": "KB국민은행",
    "케이티": "KT",
    "케이티앤지": "KT&G",
    "케이티지": "KT&G",
    "케이티즈": "KT&G",
    "엔에이치투자증권": "NH투자증권",
    "디비금융투자": "DB금융투자",
    "디비하이텍": "DB하이텍",
    "디비손해보험": "DB손해보험",
    "에이치디현대": "HD현대",
    "에이치디한국조선해양": "HD한국조선해양",
    "에이치디현대중공업": "HD현대중공업",
    "에이치디현대미포": "HD현대미포",
    "에이치디현대일렉트릭": "HD현대일렉트릭",
    "에이치디현대건설기계": "HD현대건설기계",
    "에이치디현대인프라코어": "HD현대인프라코어",
    "씨제이제일제당": "CJ제일제당",
    "씨제이대한통운": "CJ대한통운",
    "씨제이이엔엠": "CJ ENM",
    "씨제이프레시웨이": "CJ프레시웨이",
    "씨제이올리브영": "CJ올리브영",
    "씨제이씨지브이": "CJ CGV",
    "지에스건설": "GS건설",
    "지에스리테일": "GS리테일",
    "지에스칼텍스": "GS칼텍스",
    "지에스에너지": "GS에너지",
    "디엘이앤씨": "DL이앤씨",
    "디엘건설": "DL건설",
    "디엘케미칼": "DL케미칼",
    "비엔케이금융지주": "BNK금융지주",
    "디지비금융지주": "DGB금융지주",
    "제이비금융지주": "JB금융지주",
    "포스코홀딩스": "POSCO홀딩스",
    "포스코인터내셔널": "POSCO인터내셔널",
    "포스코퓨처엠": "POSCO퓨처엠",
    "포스코스틸리온": "POSCO스틸리온",
    "포스코이앤씨": "POSCO이앤씨",
    "엔씨소프트": "NCSOFT",
}


# ═══════════════════════════════════════════════════════
# 메인 정규화 함수
# ═══════════════════════════════════════════════════════

# DART 공식 종목명 캐시 (서버 시작 시 자동 빌드)
_OFFICIAL_NAMES: dict[str, str] = {}  # {"sk하이닉스": "SK하이닉스", ...}
_NORMALIZER_READY = False


def _ensure_initialized():
    """지연 초기화 — 최초 호출 시 DART 사전 빌드"""
    global _NORMALIZER_READY
    if _NORMALIZER_READY:
        return
    _build_normalizer_from_dart()


def _build_normalizer_from_dart():
    """DART _LISTED_CORPS에서 공식 종목명 사전 구축"""
    global _OFFICIAL_NAMES, _NORMALIZER_READY
    try:
        from routers.panel import _LISTED_CORPS, _CORP_LOADED, _CORP_DICT
        _CORP_LOADED.wait(timeout=30)

        for corp_name, corp_code, stock_code in _LISTED_CORPS:
            key = corp_name.lower().replace(" ", "").replace("(주)", "").replace("주식회사", "")
            _OFFICIAL_NAMES[key] = corp_name

        for key, (code, name, stock) in _CORP_DICT.items():
            if stock:
                _OFFICIAL_NAMES[key] = name

        _NORMALIZER_READY = True
        logger.info(f"✦ 종목명 정규화 사전 구축 완료: {len(_OFFICIAL_NAMES):,}건")
    except Exception as e:
        logger.warning(f"종목명 정규화 사전 구축 실패: {e}")
        _NORMALIZER_READY = True  # 실패해도 재시도 방지


def normalize_company_name(name: str) -> str:
    """
    LLM 출력 회사명 → 공식 종목명 변환

    1단계: EXACT_OVERRIDE 매칭 (하드코딩 특수 케이스)
    2단계: PHONETIC_TO_ENGLISH 패턴 매칭 (접두사 변환)
    3단계: DART 공식 종목명 퍼지 매칭
    """
    if not name or len(name) < 2:
        return name

    _ensure_initialized()

    original = name.strip()
    cleaned = original.replace(" ", "").replace("주식회사", "").replace("(주)", "")
    cleaned_lower = cleaned.lower()

    # 1단계: 완전 일치 오버라이드
    if cleaned in EXACT_OVERRIDE:
        return EXACT_OVERRIDE[cleaned]

    # 2단계: 음독 접두사 → 영문 변환
    for phonetic, english in sorted(PHONETIC_TO_ENGLISH.items(),
                                      key=lambda x: len(x[0]), reverse=True):
        if cleaned.startswith(phonetic):
            remainder = cleaned[len(phonetic):]
            candidate = english + remainder
            # DART 사전에서 확인
            candidate_key = candidate.lower().replace(" ", "")
            if candidate_key in _OFFICIAL_NAMES:
                return _OFFICIAL_NAMES[candidate_key]
            # DART에 없어도 변환 적용 (대부분 맞음)
            return candidate

    # 3단계: DART 공식명 직접 매칭
    if cleaned_lower in _OFFICIAL_NAMES:
        return _OFFICIAL_NAMES[cleaned_lower]

    # 4단계: 부분 매칭 (90% 이상 일치)
    if _NORMALIZER_READY and len(cleaned) >= 3:
        for key, official in _OFFICIAL_NAMES.items():
            if cleaned_lower in key or key in cleaned_lower:
                return official

    return original


def normalize_text_company_names(text: str) -> str:
    """
    텍스트 내의 모든 회사명을 정규화.
    EXACT_OVERRIDE의 키를 기준으로 텍스트에서 교체.
    """
    if not text:
        return text

    result = text
    # 긴 패턴부터 매칭 (에스케이하이닉스 > 에스케이)
    for phonetic, official in sorted(EXACT_OVERRIDE.items(),
                                      key=lambda x: len(x[0]), reverse=True):
        if phonetic in result:
            result = result.replace(phonetic, official)

    return result
