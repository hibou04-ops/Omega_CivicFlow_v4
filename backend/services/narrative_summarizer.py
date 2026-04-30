# -*- coding: utf-8 -*-
"""
narrative_summarizer.py — 진짜 요약 (자연어 템플릿 기반)

LLM 없이 추출된 데이터를 한국어 자연어 템플릿으로 재구성.
복사-붙여넣기가 아닌, 실제로 condensed + 가독성 있는 요약.

데이터 소스:
  1. financial_facts (DB): 매출/이익/자산 등 검증된 숫자
  2. code_only_extractor: 사업개요, 사업부문, 임원, 감사정보, 위험, 거래처
  3. document_metadata: 회사명, 보고서종류, 사업연도, 공시일

출력 예시 (사업보고서):
  "AP위성은 위성통신 단말기와 인공위성 부품을 개발·제조하는 기업입니다.
   2025년 매출액은 478억원으로 전년 대비 18.5% 감소했으며, 영업손실 43억원,
   당기순손실 28억원을 기록했습니다. 자산총계 1,263억원, 자본총계 1,039억원,
   부채비율 21.6%로 재무 건전성은 양호합니다. 위성사업 부문에서 위성통신단말기
   수출이 매출의 51.8%를 차지하며, 주요 고객은 UAE THURAYA입니다.
   삼일회계법인이 2025년 감사를 수행했으며 적정의견을 표명했습니다."
"""

import re
from typing import Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# 헬퍼 — 한국어 조사 처리 (받침 자동 판별)
# ═══════════════════════════════════════════════════════════════

def with_josa(word: str, particle: str) -> str:
    """단어 끝 받침을 자동 판별하여 조사 결합.

    Args:
        word: 대상 단어 (한글 가정. 영문/숫자는 받침 없음 처리)
        particle: '은는', '이가', '을를', '과와', '으로', '이라'

    Examples:
        with_josa("신한지주", "은는") → "신한지주는"
        with_josa("AP위성", "은는") → "AP위성은"
        with_josa("삼일회계법인", "이가") → "삼일회계법인이"
        with_josa("적정의견", "을를") → "적정의견을"
    """
    if not word:
        return word
    last_ch = word[-1]
    code = ord(last_ch)
    is_hangul = 0xAC00 <= code <= 0xD7A3
    if is_hangul:
        final = (code - 0xAC00) % 28
        has_final = final != 0
        is_rieul = final == 8  # ㄹ 받침
    else:
        # 비한글: 영문/숫자는 보수적으로 받침 없음 처리
        has_final = False
        is_rieul = False

    if particle == '은는':
        return word + ('은' if has_final else '는')
    elif particle == '이가':
        return word + ('이' if has_final else '가')
    elif particle == '을를':
        return word + ('을' if has_final else '를')
    elif particle == '과와':
        return word + ('과' if has_final else '와')
    elif particle == '으로':
        return word + ('로' if (not has_final or is_rieul) else '으로')
    elif particle == '이라':
        return word + ('이라' if has_final else '라')
    return word + particle


# ═══════════════════════════════════════════════════════════════
# 헬퍼 — 단위 변환
# ═══════════════════════════════════════════════════════════════

def _krw_to_kor(value: Optional[float]) -> str:
    """원화 → 한국 단위 (조/억/만 원)"""
    if value is None:
        return "정보 없음"
    abs_v = abs(float(value))
    sign = "-" if value < 0 else ""
    if abs_v >= 1_000_000_000_000:
        return f"{sign}{abs_v / 1_000_000_000_000:.2f}조원"
    elif abs_v >= 100_000_000:
        return f"{sign}{abs_v / 100_000_000:,.0f}억원"
    elif abs_v >= 10_000:
        return f"{sign}{abs_v / 10_000:,.0f}만원"
    else:
        return f"{sign}{int(abs_v):,}원"


def _calc_ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """비율(%) 계산. None safe."""
    if num is None or den is None or den == 0:
        return None
    return num / den * 100


# ═══════════════════════════════════════════════════════════════
# 핵심 재무 포맷 — financial_facts → UI 한 줄 텍스트
# ═══════════════════════════════════════════════════════════════

# financial_facts.metric_name (정본) → 한국어 라벨 + 표시 순서
_FINANCIAL_LABEL_ORDER: List[tuple] = [
    ("revenue", "매출액"),
    ("operating_profit", "영업이익"),
    ("net_income", "당기순이익"),
    ("total_assets", "자산총계"),
    ("total_liabilities", "부채총계"),
    ("equity", "자본총계"),
]


def format_financial_metrics(facts: Dict[str, float]) -> str:
    """financial_facts dict → UI '핵심 재무' 필드용 한 줄 텍스트.

    예: '매출액 478억원 | 영업이익 -43억원 | 당기순이익 -28억원 | 자산총계 1,263억원 | 부채비율 21.6%'

    Args:
        facts: {metric_name: value_in_krw} — e.g. {'revenue': 47812373057.0, ...}

    Returns:
        포맷된 한국어 문자열. 빈 facts면 '해당 없음'.
    """
    if not facts:
        return "해당 없음"

    parts: List[str] = []
    for key, label in _FINANCIAL_LABEL_ORDER:
        val = facts.get(key)
        if val is not None:
            parts.append(f"{label} {_krw_to_kor(val)}")

    if not parts:
        return "해당 없음"

    # 부채비율 = 총부채 / 자본총계 × 100
    liab = facts.get("total_liabilities")
    eq = facts.get("equity")
    ratio = _calc_ratio(liab, eq)
    if ratio is not None:
        parts.append(f"부채비율 {ratio:.1f}%")

    return " | ".join(parts)


def format_financial_metrics_or_event(
    facts: Dict[str, float],
    raw_text: str = "",
) -> str:
    """핵심 재무 텍스트 — P&L 우선, 없으면 이벤트 핵심 숫자로 fallback.

    사업/분기/감사보고서 → 매출·이익·자산·부채·자본·부채비율
    주요사항/기타공시(이벤트) → 처분금액/취득금액/발행총액/사채총액/계약금액/비율/주식수 등

    Args:
        facts: financial_facts dict (P&L 숫자)
        raw_text: OCR 원문 (fallback 추출용)
    """
    pnl = format_financial_metrics(facts)
    if pnl != "해당 없음":
        return pnl

    if not raw_text:
        return "해당 없음"

    # 이벤트 핵심 숫자 추출 (_extract_event_terms는 주요사항/기타공시 전용 로직 재사용)
    try:
        terms = _extract_event_terms(raw_text)
    except Exception:
        terms = {}

    if not terms:
        return "해당 없음"

    priority = [
        "사채총액", "발행가액", "발행총액", "취득금액", "처분금액", "계약금액",
        "합병비율", "분할비율", "감자비율", "전환가액", "행사가액",
        "주식수", "처분주식수", "취득주식수",
    ]
    ordered = [(k, terms[k]) for k in priority if k in terms]
    # 나머지
    ordered += [(k, v) for k, v in terms.items() if k not in priority and k not in {
        "취득방법", "처분방법", "취득목적", "처분목적", "상대회사",
    }]

    if not ordered:
        return "해당 없음"

    return " | ".join(f"{k} {v}" for k, v in ordered[:5])


# DART 표지 필드 블랙리스트 — _extract_dart_title이 4순위 regex로 오매칭하는 패턴
# (사업보고서 표지의 "제출대상법인 유형: 주권상장법인 / 면제사유발생: 해당사항 없음" 등)
_TITLE_BLACKLIST_NORM = {
    "주권상장법인면제사유발생",
    "주권상장법인",
    "면제사유발생",
    "해당사항없음",
    "제출대상법인",
    "제출대상법인유형",
    "유형",
}


def extract_document_title(raw_text: str, report_type_fallback: str = "") -> str:
    """raw_text에서 DART 공시 제목 추출 (disclosure_title 용).

    예:
      "주요사항보고서(자본으로인정되는채무증권발행결정) 한국투자금융지주..."
        → "자본으로인정되는채무증권발행결정"
      "자기주식처분결과보고서 (주)희림종합건축사사무소 ..."
        → "자기주식처분결과보고서"
      "사업보고서 에이피위성..." (generic type)
        → report_type_fallback ("사업보고서")

    실패·블랙리스트 매칭 시 report_type_fallback 반환.
    """
    if not raw_text:
        return (report_type_fallback or "").strip()
    try:
        title = _extract_dart_title(raw_text)
    except Exception:
        title = None
    title = (title or "").strip()
    if not title:
        return (report_type_fallback or "").strip()
    # 블랙리스트 — DART 표지 필드 오매칭 차단
    title_norm = re.sub(r"\s+", "", title)
    if title_norm in _TITLE_BLACKLIST_NORM:
        return (report_type_fallback or "").strip()
    return title


# ═══════════════════════════════════════════════════════════════
# 사업 개요 정제 — "사업의 내용" 첫 의미 단락 추출 (정제)
# ═══════════════════════════════════════════════════════════════

# 노이즈 종결 (DART 표지/안내문 잔재 — 사업개요로 부적합)
_OVERVIEW_NOISE_TAILS = (
    '참조', '오기정정', '정정 전', '정정 후', '정정전', '정정후',
    '해당없음', '해당사항없음', '확정공시', '※상세', '※ 상세',
    '바랍니다 "', '바랍니다"', '기타 세부내용은',
    '세부내용은 "', '세부내용은"', '입니다 "', '입니다"',
    '4)', '3)', '주주가...)',
)
# 노이즈 시작 패턴 (이걸로 시작하면 사업개요 아님 — 표 헤더/안내문 잔재)
_OVERVIEW_NOISE_STARTS = (
    '가. 사업부문', '나. 사업부문', '다. 사업부문',
    '사업부문별 종속', '주요 종속회사 현황', '연결대상 종속',
    '위험기준', '확정공시', '오기정정',
    '생산능력', '생산실적', '가동률 해당없음',
    '※', '주1)', '주2)', '주3)',
    '구분 ', '사업의 개요 가.',
)
_OVERVIEW_TERMINATORS = ('습니다.', '입니다.', '다.', '.', '!', '?')


def _clean_business_text(text: str, max_chars: int = 200) -> str:
    """사업 설명 텍스트 정제 — 표 잔재 제거 + 종결 검증.

    출력 보장:
      - 종결 부호 ('다.'/'.'/'습니다.')로 끝나거나
      - 빈 문자열 반환 (fallback 트리거)
      - 노이즈 종결 패턴 거부
    """
    if not text:
        return ""

    # 표 잔재 제거
    text = re.sub(r'\s*/\s*\(?[\d,.\s]+\)?\s*/', ' ', text)
    text = re.sub(r'\s+\d{1,3}(,\d{3})+(\.\d+)?\s*%?', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # 노이즈 시작 패턴 사전 거부 (표 헤더/안내문)
    if any(text.startswith(noise) for noise in _OVERVIEW_NOISE_STARTS):
        return ""

    # "당사는/회사의/본사가" prefix 제거 (조사 + 공백까지)
    text = re.sub(r'^(?:당사(?:는|가|의|에서|와|와는|도)?\s*|본사(?:는|가|의)?\s*|회사(?:는|가|의)?\s*)', '', text).strip()

    # 표 헤더 패턴 제거
    text = re.sub(r'^[가-힣A-Za-z]*?(?:현황|개요|구분|요약)\s*\([^)]*\)\s*', '', text).strip()

    # prefix 제거 후 다시 노이즈 시작 검사
    if any(text.startswith(noise) for noise in _OVERVIEW_NOISE_STARTS):
        return ""

    # 길이 제한
    if len(text) > max_chars:
        text = text[:max_chars]

    # 노이즈 종결 제거
    for noise in _OVERVIEW_NOISE_TAILS:
        if text.endswith(noise):
            text = text[:-len(noise)].rstrip()
            break

    if not text or len(text) < 20:
        return ""

    # 정상 종결 검사
    if text.endswith(_OVERVIEW_TERMINATORS):
        return text

    # 종결 부호 없음 → 마지막 종결 부호로 trim
    best_idx = -1
    for terminator in _OVERVIEW_TERMINATORS:
        idx = text.rfind(terminator)
        if idx >= 20 and (idx + len(terminator)) > best_idx:
            best_idx = idx + len(terminator)
    if best_idx > 0:
        return text[:best_idx].strip()

    # 종결 부호 없음 → 거부
    return ""


# ═══════════════════════════════════════════════════════════════
# 1. 사업보고서 / 분기보고서 요약 템플릿
# ═══════════════════════════════════════════════════════════════

_FINANCIAL_INDUSTRY_KEYWORDS = (
    '은행', '지주', '금융지주', '증권', '보험', '카드',
    '캐피탈', '저축은행', '자산운용', '종금', '신용카드',
    '종합금융', '신탁', '리츠', '벤처투자', '창업투자',
    '신협', '농협', '수협', '새마을금고', '저축', '할부금융',
    '금융', '파이낸셜', '인베스트먼트',
)


def _is_financial_industry(company: str, overview: str = "") -> bool:
    """은행·금융지주·증권·보험 등 금융업 여부 판별.

    이들 업종은 '부채'에 예금/보험계약부채/RP 등이 포함되어
    부채비율(부채/자본)이 의미 없음. BIS·자기자본비율 사용 권장.
    """
    text = (company or "") + " " + (overview or "")
    return any(kw in text for kw in _FINANCIAL_INDUSTRY_KEYWORDS)


def summarize_business_report(
    company: str, fy: int, report_type: str,
    facts: Dict[str, float],
    extracted: dict,
) -> str:
    """사업보고서/분기보고서 자연어 요약."""
    parts = []
    overview = _clean_business_text(extracted.get('business_overview', ''), 150)
    is_financial = _is_financial_industry(company, overview)
    subsidiaries = extracted.get('subsidiaries', []) or []

    # 첫 문장: 회사 + 사업 영역
    if is_financial and subsidiaries:
        # 금융지주: 자회사 리스트로 첫 문장 구성
        sub_list = ", ".join(subsidiaries[:5])
        more = f" 등 {len(subsidiaries)}개" if len(subsidiaries) > 5 else ""
        sub_with_josa = with_josa(sub_list + more, '을를')
        parts.append(f"{with_josa(company, '은는')} {sub_with_josa} 자회사로 두고 있는 금융지주회사입니다.")
    elif overview:
        # overview가 이미 완전한 문장이면 회사명 prefix만 추가 (이중 wrap 방지)
        if overview.endswith(('습니다.', '입니다.', '다.', '.')):
            parts.append(f"{with_josa(company, '은는')} {overview}")
        else:
            parts.append(f"{with_josa(company, '은는')} {with_josa(overview, '을를')} 영위하는 기업입니다.")
    elif subsidiaries:
        # 일반 지주회사
        sub_list = ", ".join(subsidiaries[:5])
        more = f" 등 {len(subsidiaries)}개" if len(subsidiaries) > 5 else ""
        sub_with_josa = with_josa(sub_list + more, '을를')
        parts.append(f"{with_josa(company, '은는')} {sub_with_josa} 자회사로 두고 있는 지주회사입니다.")
    else:
        parts.append(f"{with_josa(company, '은는')} {fy}년 {report_type}를 공시했습니다.")

    # 재무 실적 (financial_facts 사용 — 정확한 숫자)
    revenue = facts.get('revenue') or facts.get('sales')
    op_profit = facts.get('operating_profit') or facts.get('operating_income')
    net_income = facts.get('net_income') or facts.get('net_profit')
    assets = facts.get('total_assets')
    liabilities = facts.get('total_liabilities')
    equity = facts.get('equity') or facts.get('total_equity')

    if revenue is not None:
        # 금융업은 매출 대신 영업수익 표기
        revenue_label = "영업수익" if is_financial else "매출액"
        fin_parts = [f"{fy}년 {revenue_label} {_krw_to_kor(revenue)}"]
        if op_profit is not None:
            fin_parts.append(f"영업{'손실' if op_profit < 0 else '이익'} {_krw_to_kor(op_profit)}")
        if net_income is not None:
            fin_parts.append(f"당기순{'손실' if net_income < 0 else '이익'} {_krw_to_kor(net_income)}")
        joined = ", ".join(fin_parts)
        parts.append(with_josa(joined, '을를') + " 기록했습니다.")

    # 재무상태
    if assets is not None and liabilities is not None and equity is not None:
        bs_parts = [
            f"자산총계 {_krw_to_kor(assets)}",
            f"부채총계 {_krw_to_kor(liabilities)}",
            f"자본총계 {_krw_to_kor(equity)}",
        ]
        if is_financial:
            # 금융업: 부채비율 대신 자기자본비율 (자본/자산)
            equity_ratio = _calc_ratio(equity, assets)
            if equity_ratio is not None:
                bs_parts.append(f"자기자본비율 {equity_ratio:.1f}%")
        else:
            # 일반 기업: 부채비율 (부채/자본) — sanity 범위
            debt_ratio = _calc_ratio(liabilities, equity)
            if debt_ratio is not None:
                if -100 <= debt_ratio <= 5000:
                    bs_parts.append(f"부채비율 {debt_ratio:.1f}%")
                elif debt_ratio > 5000 or debt_ratio < -100:
                    # 자본 잠식 또는 비정상 → 표시 생략, 자기자본비율로 대체
                    eq_ratio = _calc_ratio(equity, assets)
                    if eq_ratio is not None:
                        bs_parts.append(f"자기자본비율 {eq_ratio:.1f}% (자본 변동 큼)")
        parts.append(", ".join(bs_parts) + "를 기록했습니다.")

    # 영업이익률 (금융업 제외 — 영업수익률은 의미 다름)
    if not is_financial and revenue and op_profit is not None and revenue != 0:
        margin = op_profit / revenue * 100
        parts.append(f"영업이익률은 {margin:.1f}%입니다.")

    # 사업 부문 (중복 제거)
    segments = extracted.get('business_segments', [])
    if segments:
        seen_seg = set()
        unique_segs = []
        for s in segments:
            if s.get('segment') == '총합계':
                continue
            key = (s.get('segment', ''), s.get('product', ''), s.get('channel', ''))
            if key in seen_seg:
                continue
            seen_seg.add(key)
            unique_segs.append(s)
        main_segs = unique_segs[:2]
        if main_segs:
            seg_parts = []
            for s in main_segs:
                seg_label = " ".join(filter(None, [s.get('segment', ''), s.get('product', ''), s.get('channel', '')])).strip()
                pct = s.get('percent', '').strip()
                if seg_label and pct:
                    seg_parts.append(f"{seg_label} {pct}")
            if seg_parts:
                parts.append(f"주요 매출 구성: {' / '.join(seg_parts)}.")

    # 감사 정보
    audit = extracted.get('audit_info', {})
    if isinstance(audit, dict):
        auditor = audit.get('auditor', '')
        opinion = audit.get('opinion', '')
        if auditor or opinion:
            audit_str = ""
            if auditor:
                audit_str = f"{with_josa(auditor, '이가')} "
            audit_str += "감사를 수행"
            if opinion:
                audit_str += f"하여 {with_josa(opinion, '을를')} 표명"
            parts.append(audit_str + "했습니다.")

    # 위험 요인 (핵심 1~3개, 빈 항목 필터)
    risks = extracted.get('risks', [])
    if risks:
        risk_labels = [r.split(':')[0].strip() for r in risks[:3] if r and r.split(':')[0].strip()]
        if risk_labels:
            parts.append(f"주요 위험 요인: {', '.join(risk_labels)}.")

    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════
# 2. 주요사항보고서 요약 템플릿 (이벤트 중심)
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# 적응형 추출 파라미터 (OCR 길이별)
# ═══════════════════════════════════════════════════════════════

def get_adaptive_params(text_len: int) -> dict:
    """OCR 길이에 따른 가변 추출 파라미터.

    원리:
      - 짧은 문서 (<10K): 전체가 핵심 → 전체 검색
      - 중간 (10K-50K): 표지+본문 → 표지 위주
      - 큰 (50K-200K): 표지(3K) + 본문 다수 → 표지 한정
      - 대형 (>200K): 사업보고서 → 표지 한정 + 본문 sample
    """
    if text_len < 10_000:
        return dict(event_w=text_len, terms_w=text_len, overview_w=text_len,
                    subs_w=text_len, audit_w=text_len)
    elif text_len < 50_000:
        return dict(event_w=5_000, terms_w=10_000, overview_w=text_len,
                    subs_w=text_len, audit_w=text_len)
    elif text_len < 200_000:
        return dict(event_w=3_000, terms_w=5_000, overview_w=50_000,
                    subs_w=50_000, audit_w=text_len)
    else:
        return dict(event_w=3_000, terms_w=5_000, overview_w=100_000,
                    subs_w=100_000, audit_w=text_len)


# ═══════════════════════════════════════════════════════════════
# 이벤트 감지 — DART 표준 제목 패턴 우선
# ═══════════════════════════════════════════════════════════════

# 부정적 이벤트 (false positive 위험): 명시적 컨텍스트 필수
_NEGATIVE_EVENTS = {'회생절차', '해산', '부도', '상장폐지', '횡령', '배임'}

# fallback 키워드 매칭 (제목/첫 줄에서 못 찾을 때만)
_EVENT_KEYWORDS = [
    # 분할 (구체적인 것 우선)
    ('회사분할합병결정', '회사 분할합병'),
    ('회사분할합병', '회사 분할합병'),
    ('인적분할', '인적분할'),
    ('물적분할', '물적분할'),
    ('회사분할결정', '회사 분할'),
    ('분할합병', '분할합병'),
    ('회사분할', '회사 분할'),
    ('분할결정', '회사 분할'),
    # 합병
    ('회사합병결정', '합병'),
    ('합병계약', '합병'),
    ('합병결정', '합병'),
    ('회사합병', '합병'),
    ('소규모합병', '소규모 합병'),
    ('간이합병', '간이 합병'),
    # 주식교환·이전
    ('주식교환·이전', '주식교환·이전'),
    ('주식교환이전', '주식교환·이전'),
    ('주식의포괄적교환', '주식의 포괄적 교환'),
    ('주식의포괄적이전', '주식의 포괄적 이전'),
    ('주식교환', '주식교환'),
    # 증자·감자
    ('유상증자결정', '유상증자'),
    ('무상증자결정', '무상증자'),
    ('유상감자', '유상감자'),
    ('무상감자', '무상감자'),
    ('주식병합', '주식병합'),
    ('주식분할', '주식분할'),
    ('감자결정', '감자'),
    ('유상증자', '유상증자'),
    ('무상증자', '무상증자'),
    # 사채 발행 (자본증권 포함 — 누락 발견된 신규)
    ('상각형조건부자본증권', '상각형 조건부자본증권 발행'),
    ('조건부자본증권발행', '조건부자본증권 발행'),
    ('조건부자본증권', '조건부자본증권 발행'),
    ('신종자본증권발행', '신종자본증권 발행'),
    ('신종자본증권', '신종자본증권 발행'),
    ('자본으로인정되는채무증권발행', '자본인정 채무증권 발행'),
    ('자본으로인정되는채무증권', '자본인정 채무증권 발행'),
    ('자본인정채무증권', '자본인정 채무증권 발행'),
    ('전환사채권발행', '전환사채(CB) 발행'),
    ('신주인수권부사채권발행', '신주인수권부사채(BW) 발행'),
    ('교환사채권발행', '교환사채(EB) 발행'),
    ('전환사채', '전환사채(CB) 발행'),
    ('신주인수권부사채', '신주인수권부사채(BW) 발행'),
    ('교환사채', '교환사채(EB) 발행'),
    # 자기주식 — 신탁계약 포함 (누락 발견된 신규)
    ('자기주식취득신탁계약체결', '자기주식 취득 신탁계약 체결'),
    ('자기주식취득신탁계약해지', '자기주식 취득 신탁계약 해지'),
    ('자기주식처분신탁계약체결', '자기주식 처분 신탁계약 체결'),
    ('자기주식처분신탁계약해지', '자기주식 처분 신탁계약 해지'),
    ('자기주식취득신탁', '자기주식 취득 신탁계약'),
    ('자기주식처분신탁', '자기주식 처분 신탁계약'),
    ('자기주식취득결정', '자기주식 취득'),
    ('자기주식처분결정', '자기주식 처분'),
    ('자기주식소각결정', '자기주식 소각'),
    ('자기주식취득', '자기주식 취득'),
    ('자기주식처분', '자기주식 처분'),
    ('자기주식소각', '자기주식 소각'),
    # 영업·자산 양수도
    ('영업양수결정', '영업 양수'),
    ('영업양도결정', '영업 양도'),
    ('자산양수결정', '자산 양수'),
    ('자산양도결정', '자산 양도'),
    ('영업양수도', '영업양수도'),
    ('자산양수도', '자산양수도'),
    # 타법인 주식
    ('타법인주식및출자증권취득', '타법인 주식 취득'),
    ('타법인주식및출자증권처분', '타법인 주식 처분'),
    # 기타 중요 이벤트 (부정 키워드는 strict matching 필요)
    ('해산사유발생', '해산 사유 발생'),
    ('해산결정', '해산'),
    ('횡령·배임혐의발생', '횡령·배임 혐의'),
    ('횡령·배임사실확인', '횡령·배임 사실 확인'),
    ('부도발생', '부도 발생'),
    ('회생절차개시신청', '회생절차 개시 신청'),
    ('회생절차개시결정', '회생절차 개시 결정'),
    # 상장폐지: "주권등 상장폐지"는 부분 (DR 등) — 별도 처리
    ('주권등상장폐지', '주권등 상장폐지 (해외 DR 등)'),
    ('상장폐지결정', '상장폐지'),
    # 기타
    ('최대주주변경', '최대주주 변경'),
    ('단일판매·공급계약', '대규모 단일 공급계약'),
    ('단일판매공급계약', '대규모 단일 공급계약'),
    ('단일판매', '대규모 단일 공급계약'),
    ('주요경영사항', '주요 경영사항'),
]


def _extract_dart_title(raw_text: str) -> Optional[str]:
    """DART 표준 제목 패턴 직접 추출 — 가장 정확.

    패턴:
      "주요사항보고서(자기주식취득 신탁계약 체결 결정)"
      "주요사항보고서(상각형 조건부자본증권 발행결정)"
      "자기주식처분결과보고서"  (기타공시)
      "감사보고서"
    """
    head = raw_text[:1000]

    # 1순위: 주요사항보고서(...) 패턴
    m = re.search(r'주요사항보고서\s*\(\s*([^()]{2,60})\s*\)', head)
    if m:
        title = re.sub(r'\s+', ' ', m.group(1)).strip()
        if title:
            return title

    # 2순위: 정정신고 (보고) — 정정 케이스
    m = re.search(r'정\s*정\s*신\s*고[^.\n]{0,80}?주요사항보고서\s*\(?\s*([^()]{2,60}?)\s*\)?', head)
    if m:
        title = re.sub(r'\s+', ' ', m.group(1)).strip()
        if title and 4 <= len(title) <= 60:
            return title

    # 3순위: 기타공시 표지 ("○○○보고서") - 자기주식처분결과/취득결과/감사 등
    # 첫 보고서 occurrence만 캡처 (greedy 매칭으로 인한 중복 캡처 방지)
    # 예: "자기주식처분결과보고서 현대자동차 자기주식처분결과보고서" 같은 OCR 중복
    head_first = head[:60]
    # (1) 공백 보존 버전: 자연 경계가 있으면 더 안전
    m = re.match(r'\s*([가-힣]{4,15}보고서)(?=\s|$|[\(\[가-힣])', head_first)
    if not m:
        # (2) 공백 산재 OCR fallback: 정규화 후 lazy 매칭으로 최단 보고서 캡처
        head_norm = re.sub(r'\s+', '', head_first)
        m = re.match(r'([가-힣]{4,15}?보고서)', head_norm)
    if m:
        title = m.group(1)
        # 너무 generic한 것 제외
        if title not in ('주요사항보고서', '사업보고서', '분기보고서', '반기보고서', '감사보고서'):
            return title

    # 4순위: "○○○○ 결정/발행결정/폐지/발생" 패턴 직접 추출
    m = re.search(
        r'([가-힣A-Za-z·][가-힣A-Za-z·\s]{2,40}?'
        r'(?:발행결정|발행|취득결정|처분결정|소각결정|체결결정|해지결정|'
        r'결정|폐지|개시신청|개시결정|발생|선임|해임|취소))',
        head
    )
    if m:
        candidate = re.sub(r'\s+', ' ', m.group(1)).strip()
        for noise in ['주식회사', '귀중', '이사회', '대표이사', '본점', '소재지', '주요사항보고서']:
            candidate = candidate.replace(noise, '').strip()
        if 4 <= len(candidate) <= 60 and not candidate.isdigit():
            return candidate
    return None


def _detect_event_type(raw_text: str, doc_title: str = "") -> str:
    """이벤트 유형 감지 — DART 표준 제목 우선 + 키워드 fallback.

    우선순위:
      1. DART 표준 제목 패턴 ("주요사항보고서(...)")
      2. 키워드 매칭 (적응형 윈도우, 부정 이벤트는 strict)
    """
    # 1순위: DART 제목 직접 추출
    title = _extract_dart_title(raw_text)
    if title:
        return title

    # 2순위: 키워드 매칭 (적응형 윈도우)
    params = get_adaptive_params(len(raw_text))
    search = (doc_title or "") + " " + raw_text[:params['event_w']]
    search_norm = re.sub(r'\s+', '', search)

    for kw, label in _EVENT_KEYWORDS:
        kw_norm = re.sub(r'\s+', '', kw)
        if kw_norm in search_norm:
            # 부정 이벤트는 더 엄격한 컨텍스트 요구
            base_kw = next((n for n in _NEGATIVE_EVENTS if n in kw), None)
            if base_kw:
                # 제목/첫 줄에 명시적으로 있어야 함 (boilerplate 방지)
                if base_kw not in raw_text[:500]:
                    continue
            return label

    return "주요 경영사항"


def _extract_dates(raw_text: str) -> Dict[str, str]:
    """주요사항보고서의 핵심 일정 추출."""
    dates = {}
    patterns = {
        '이사회결의일': r'이사회\s*결의일?\s*[:：]?\s*(\d{4}[\s.년-]+\d{1,2}[\s.월-]+\d{1,2})',
        '주주총회': r'주주총회(?:예정일|일자)?\s*[:：]?\s*(\d{4}[\s.년-]+\d{1,2}[\s.월-]+\d{1,2})',
        '분할기일': r'분할기일\s*[:：]?\s*(\d{4}[\s.년-]+\d{1,2}[\s.월-]+\d{1,2})',
        '상장예정일': r'(?:재상장|신규상장|상장)\s*예정일?\s*[:：]?\s*(\d{4}[\s.년-]+\d{1,2}[\s.월-]+\d{1,2})',
        '납입일': r'납입일\s*[:：]?\s*(\d{4}[\s.년-]+\d{1,2}[\s.월-]+\d{1,2})',
        '처분기간': r'처분기간\s*[:：]?\s*(\d{4}[\s.년-]+\d{1,2}[\s.월-]+\d{1,2})',
        '취득기간': r'취득기간\s*[:：]?\s*(\d{4}[\s.년-]+\d{1,2}[\s.월-]+\d{1,2})',
        '제출일': r'주요사항보고서\s*제출일?\s*[:：]?\s*(\d{4}[\s.년-]+\d{1,2}[\s.월-]+\d{1,2})',
    }
    for label, pat in patterns.items():
        m = re.search(pat, raw_text[:20000])
        if m:
            dates[label] = re.sub(r'\s+', ' ', m.group(1)).strip()
    return dates


def _format_won(amount_str: str) -> Optional[str]:
    """원화 금액 문자열을 한국 단위로 변환. 실패 시 None."""
    try:
        amt = int(amount_str.replace(',', '').replace(' ', ''))
        if amt <= 0:
            return None
        if amt >= 1_000_000_000_000:
            return f"{amt / 1_000_000_000_000:.2f}조원"
        elif amt >= 100_000_000:
            return f"{amt / 100_000_000:,.0f}억원"
        elif amt >= 10_000:
            return f"{amt / 10_000:,.0f}만원"
        else:
            return f"{amt:,}원"
    except (ValueError, AttributeError):
        return None


def _extract_event_terms(raw_text: str) -> Dict[str, str]:
    """주요사항보고서의 핵심 조건 추출 (확장판).

    추출 항목:
      - 비율: 분할/합병/감자비율
      - 금액: 발행/취득/처분/계약금액, 사채총액
      - 수량: 신주/처분 주식수
      - 상대회사
      - 자금사용 목적
      - 표면이자율, 만기
    """
    terms = {}
    params = get_adaptive_params(len(raw_text))
    text = raw_text[:params['terms_w']]

    # ─── 비율 ───────────────────────────────────────
    m = re.search(r'분할비율[\s가-힣()]*?(\d+\.\d{4,})\s*[/:\s]\s*(\d+\.\d{4,})', text)
    if m:
        terms['분할비율'] = f"존속 {m.group(1)} / 신설 {m.group(2)}"

    m = re.search(r'합병비율[\s가-힣()]*?(\d+(?:\.\d+)?)\s*[:：]\s*(\d+\.\d+)', text)
    if m:
        terms['합병비율'] = f"{m.group(1)} : {m.group(2)}"

    m = re.search(r'감자비율\s*[(%)]*\s*(\d+\.?\d*)', text)
    if m:
        terms['감자비율'] = f"{m.group(1)}%"

    # ─── 상대회사 ────────────────────────────────────
    m = re.search(r'주식회사\s*([가-힣A-Za-z][가-힣A-Za-z0-9\s&]{1,20}?)\s*[를을](?:흡수)?(?:합병|분할합병)', text)
    if m:
        cleaned = re.sub(r'\s+', ' ', m.group(1)).strip()
        terms['상대회사'] = "주식회사 " + cleaned
    else:
        m = re.search(r'당사와\s+([가-힣A-Za-z][가-힣A-Za-z0-9\s&()㈜주식회사]{2,30}?)\s*(?:간의?|및)\s*(?:합병|분할합병)', text)
        if m:
            terms['상대회사'] = re.sub(r'\s+', ' ', m.group(1)).strip()

    # ─── 금액 (사채/증자/취득/처분/계약 모두 포함) ──
    # DART 표 구조: 라벨\n보통주식\n금액 — 중간 토큰 허용
    LABEL_TO_NUM = r'\s*[\s가-힣()주식]{0,40}?([\d,]{8,})'

    # 사채 권면총액 — 권면/전자등록 prefix 필수
    # (자기주식 취득결과보고서의 "취득가액총액(원)"과 충돌 방지)
    # 형태: "권면총액", "권면(전자등록)총액", "전자등록총액"
    pat_face_value = r'(?:권면(?:\s*\(\s*전자등록\s*\))?|전자등록)\s*총액\s*\(?원\)?'
    m = re.search(pat_face_value + LABEL_TO_NUM, text)
    if m:
        formatted = _format_won(m.group(1))
        if formatted:
            terms['사채총액'] = formatted

    # 발행가액
    m = re.search(r'발행가액\s*\(?원\)?' + LABEL_TO_NUM, text)
    if m:
        formatted = _format_won(m.group(1))
        if formatted:
            terms['발행가액'] = formatted

    # 취득예정금액 (자기주식 취득결정 — 줄바꿈/보통주식 토큰 허용)
    m = re.search(r'취득(?:예정|예상)?\s*금액\s*\(?원\)?' + LABEL_TO_NUM, text)
    if m:
        formatted = _format_won(m.group(1))
        if formatted:
            terms['취득금액'] = formatted

    # 처분(예정)금액
    m = re.search(r'처분(?:예정|예상|가액)?\s*금액?\s*(?:총액)?\s*\(?원\)?' + LABEL_TO_NUM, text)
    if m:
        formatted = _format_won(m.group(1))
        if formatted:
            terms['처분금액'] = formatted

    # 계약금액
    m = re.search(r'계약금액\s*\(?원\)?' + LABEL_TO_NUM, text)
    if m:
        formatted = _format_won(m.group(1))
        if formatted:
            terms['계약금액'] = formatted

    # ─── 수량 (자기주식 — 줄바꿈/주식종류 토큰 허용) ──
    LABEL_TO_QTY = r'\s*[\s가-힣()주식]{0,30}?([\d,]{4,})'

    # 취득예정주식
    m = re.search(r'취득(?:예정|예상)?\s*주식\s*\(?주\)?' + LABEL_TO_QTY, text)
    if m:
        terms['주식수'] = f"{m.group(1)}주"
    else:
        m = re.search(r'(?:신주\s*발행\s*수|신주식수|발행주식수)\s*\(?주\)?' + LABEL_TO_QTY, text)
        if m:
            terms['주식수'] = f"{m.group(1)}주"

    # 처분주식 (자기주식 처분결정/결과)
    m = re.search(r'처분(?:할|예정|보고|예상)?\s*주식\s*(?:총?수)?\s*\(?주\)?' + LABEL_TO_QTY, text)
    if m and '주식수' not in terms:
        terms['처분주식수'] = f"{m.group(1)}주"

    # 자기주식 처분결과보고서 표 패턴: "처분보고 주식의 종류 및 주식수\n보통주식 [총] 600,000주"
    # "기명식 보통주 1,102,878주, 우선주 1,254,420주" 형태도 커버
    if '주식수' not in terms and '처분주식수' not in terms:
        m = re.search(r'처분(?:보고)?\s*주식의?\s*종류[\s가-힣]{0,40}(?:보통주식?|기타주식?)[\s가-힣]{0,8}([\d,]{4,})주?', text)
        if m:
            terms['처분주식수'] = f"{m.group(1).strip()}주"
        else:
            # 자기주식취득결과 패턴: "취득보고 주식의 종류 ... 보통주 X,XXX주"
            m = re.search(r'(?:취득|처분)보고\s*주식의?\s*종류[\s가-힣]{0,40}기명식?\s*보통주\s*([\d,]{4,})주', text)
            if m:
                terms['처분주식수'] = f"{m.group(1).strip()}주"

    # 처분 총액 — 처분결과보고서 표 행 (가장 큰 숫자가 곧 총액)
    if '처분금액' not in terms and ('처분결과' in raw_text[:200] or '처분주식수' in terms):
        candidates = re.findall(r'(\d{1,3}(?:,\d{3}){2,5})', text[:2500])
        if candidates:
            largest_str = max(candidates, key=lambda s: int(s.replace(',', '')))
            val = int(largest_str.replace(',', ''))
            # 1억~100조 범위 (sanity, 작은 회사 처분도 커버)
            if 100_000_000 <= val <= 100_000_000_000_000:
                terms['처분금액'] = _format_won(largest_str)

    # ─── 자금조달 목적 ──────────────────────────────
    # DART 표 형식: "시설자금 (원) X / 영업양수자금 (원) Y / 운영자금 (원) Z" 등
    # 실제 금액이 있는 카테고리만 추출
    funding_section = re.search(r'자금조달의?\s*목적([^가-힣]{0,5}[가-힣\s,()/0-9-]{10,500})', text)
    if funding_section:
        block = funding_section.group(1)
        # "시설자금 (원) 270,000,000,000" 같은 패턴 (금액 있는 것만)
        category_with_amount = re.findall(
            r'(시설자금|영업양수자금|운영자금|채무상환자금|타법인\s*증권\s*취득자금|기타자금)'
            r'\s*\(?원\)?\s*([\d,]{6,})',
            block
        )
        used_categories = []
        for cat, amt_str in category_with_amount:
            try:
                amt = int(amt_str.replace(',', ''))
                if amt > 0:
                    used_categories.append(re.sub(r'\s+', '', cat))
            except ValueError:
                pass
        if used_categories:
            terms['자금조달목적'] = "·".join(used_categories[:4])

    # ─── 사채 이자율 ────────────────────────────────
    m = re.search(r'표면이자율\s*\(?\%?\)?\s*([\d.]+)', text)
    if m:
        try:
            r = float(m.group(1))
            if 0 < r < 30:  # sanity
                terms['표면이자율'] = f"{r}%"
        except ValueError:
            pass

    # ─── 자기주식 취득목적 ──────────────────────────
    m = re.search(r'취득목적\s*([가-힣\s,·]{4,50}?)(?=\s*\d+\.|\n\s*\d|취득방법)', text)
    if m:
        purpose = re.sub(r'\s+', ' ', m.group(1)).strip()
        if purpose and 4 <= len(purpose) <= 50:
            terms['취득목적'] = purpose

    # ─── 자기주식 취득방법 ──────────────────────────
    m = re.search(r'취득방법\s*([가-힣\s]{2,20}?)(?=\s*\d+\.|\n\s*\d|위탁)', text)
    if m:
        method = re.sub(r'\s+', ' ', m.group(1)).strip()
        if method and 2 <= len(method) <= 20:
            terms['취득방법'] = method

    # ─── 자기주식 처분목적 ──────────────────────────
    m = re.search(r'처분목적\s*([가-힣\s,·]{4,50}?)(?=\s*\d+\.|\n\s*\d|처분방법)', text)
    if m:
        purpose = re.sub(r'\s+', ' ', m.group(1)).strip()
        if purpose and 4 <= len(purpose) <= 50:
            terms['처분목적'] = purpose

    # ─── 단일 계약 상대방 ──────────────────────────
    # 콜론 필수 + label-like 후보 거부 (표 헤더 행 매칭 방지)
    if '상대회사' not in terms:
        m = re.search(
            r'(?:계약\s*상대방|매수자|매도자)(?:명)?\s*[:：]\s*'
            r'([가-힣A-Za-z][가-힣A-Za-z0-9\s&()]{2,30}?)(?:\s*\n|$|,)',
            text
        )
        if m:
            candidate = re.sub(r'\s+', ' ', m.group(1)).strip()
            # 표 헤더 라벨 거부 (예: "회사 또는최대주주와의관계")
            if not any(noise in candidate for noise in
                       ('또는', '관계', '여부', '내용', '구분', '경위', '계획')):
                terms['상대회사'] = candidate

    return terms


def extract_evidence_quotes(
    raw_text: str,
    facts: Dict[str, float] = None,
    max_quotes: int = 3,
) -> List[str]:
    """OCR 원문에서 핵심 사실을 포함한 짧은 인용문 추출.

    분석 결과 UI의 "근거 문장" 영역에 표시할 OCR quote.

    설계 원칙 (2026-04 재개정):
      - 최대 3개, 각 25~110자 (UI 카드 한 줄 기준)
      - 표 raw dump (헤더 중복/숫자 컬럼/짧은 토큰) 거부
      - 자연 서술문(다/니다/합니다) 가점
      - 라벨:값 + 키워드 + 숫자 우선

    Returns: 각 25~110자 인용문 (최대 max_quotes개)
    """
    if not raw_text:
        return []

    quotes = []
    seen = set()
    head = raw_text[:8000]

    MIN_LEN = 25
    MAX_LEN = 110  # UI 카드 한 줄 가독 한계 (140 → 110, 더 타이트)

    # 핵심 키워드 (DART 공시 표 라벨 + 사업/감사보고서)
    KEYWORD_PAT = re.compile(
        r'(?:취득(?:예정|결정)?\s*(?:주식|금액|기간|목적|방법)|'
        r'처분(?:예정|결정|보고)?\s*(?:주식|금액|가액|기간|목적|방법|대상)|'
        r'발행(?:총|결정|예정)?\s*(?:가액|총액|주식)|'
        r'(?:권면|전자등록)?\s*총액|'
        r'합병비율|분할비율|감자비율|'
        r'표면이자율|만기|이자지급|'
        r'납입일|결정일|이사회결의일|분할기일|상장예정일|'
        r'자금조달|채무상환|영업양수|시설자금|운영자금|'
        r'계약\s*(?:금액|상대방|내용|기간)|'
        r'주주환원|주식소각|배당가능이익|'
        # 사업·감사보고서 키워드
        r'매출액|매출\s|영업이익|영업손실|당기순이익|당기순손실|'
        r'자산총계|부채총계|자본총계|영업수익|'
        r'주요\s*제품|주요\s*고객|주요\s*거래처|'
        r'감사의견|감사인|핵심감사사항|적정의견|'
        r'사업의?\s*개요|사업의?\s*내용)'
    )

    def _has_label_value(line: str) -> bool:
        """라벨:값 또는 라벨 [공백] 값 형태인지 확인."""
        return bool(re.search(r'[가-힣]{2,}\s*[:：]\s*\S', line))

    def _is_table_dump(line: str) -> bool:
        """표 raw dump 판정 — 한글 비율 기반.

        - 라벨:값 형태이면 절대 dump 아님 (날짜/금액 라인 보호)
        - 한글이 18% 미만이면 dump (1,102,294 1,102,294 261,500 같은 순수 숫자행)
        """
        if not line:
            return True
        if _has_label_value(line):
            return False
        korean = sum(1 for c in line if '가' <= c <= '힣')
        return (korean / len(line)) < 0.18

    # 표 컬럼 헤더 전형 어휘 (sentence context에서는 거의 안 나옴)
    _TABLE_COL_WORDS = {
        '기초수량', '기말수량', '기초재고', '기말재고', '주문수량', '처분수량',
        '취득수량', '변동수량', '기초', '기말', '소계', '합계', '구분', '비고',
        '종류', '수량', '일자', '금액', '잔액', '단가', '주식종류', '주식수',
        '매도위탁', '증권회사', '금융투자업자', '고유번호',
        '취득방법', '처분방법', '취득가액', '처분가액',
    }

    def _is_likely_table(line: str) -> bool:
        """강화된 표 감지 — 한글 비율은 높지만 문장이 아닌 표 컬럼·행 코알레션.

        감지 시그널 (any hit → 거부):
          1) 동일 짧은 토큰 반복 ('보통주식 기타주식 보통주식 기타주식')
          2) 연속된 1자 한글 토큰 3개 이상 ('일 자 종 류 수 량')  ← 결정적 시그널
          3) 짧은 토큰(1-3자 한글) 비율 45% 초과
          4) '- N - N' dash-숫자 패턴 (표 합계 행)
          5) 순수 숫자 토큰 3개 이상
          6) 괄호 라벨 반복 ('(주) (주)')
          7) 표 컬럼 헤더 전형 어휘 2개 이상
        """
        if not line:
            return True
        tokens = line.split()
        if len(tokens) < 3:
            return False

        # 1. 반복 짧은 토큰
        from collections import Counter
        counts = Counter(tokens)
        repeated_short = sum(
            1 for t, c in counts.items()
            if c >= 2 and 2 <= len(t) <= 6 and re.match(r'^[가-힣]', t)
        )
        if repeated_short >= 2:
            return True

        # 2. 연속 1자 한글 토큰 — "일 자 종 류 수 량" 패턴
        max_consec = 0
        cur_consec = 0
        for t in tokens:
            if len(t) == 1 and '가' <= t <= '힣':
                cur_consec += 1
                max_consec = max(max_consec, cur_consec)
            else:
                cur_consec = 0
        if max_consec >= 3:
            return True

        # 3. 짧은 토큰 비율 (thresold 55 → 45로 완화)
        short_tok = sum(
            1 for t in tokens
            if 1 <= len(t) <= 3 and re.match(r'^[가-힣A-Za-z]+$', t)
        )
        if len(tokens) >= 5 and short_tok / len(tokens) > 0.45:
            return True

        # 4. dash-number 패턴
        dash_num = len(re.findall(r'-\s*\d{1,3}(?:,\d{3})+', line))
        if dash_num >= 2:
            return True

        # 5. 순수 숫자 토큰 3개 이상
        num_tokens = sum(1 for t in tokens if re.match(r'^[\d,.\-()]+$', t))
        if num_tokens >= 3:
            return True

        # 6. 괄호 라벨 반복
        if len(re.findall(r'\([가-힣]\)', line)) >= 2:
            return True

        # 7. 표 컬럼 헤더 어휘 2개 이상 동시 등장
        col_word_hits = sum(1 for w in _TABLE_COL_WORDS if w in line)
        if col_word_hits >= 2:
            return True

        return False

    def _is_natural_sentence(line: str) -> bool:
        """자연 서술문 판정 — 종결 어미로 끝나는지 확인."""
        if not line:
            return False
        stripped = line.rstrip()
        endings = (
            '다.', '다', '니다.', '니다', '습니다.', '습니다',
            '됩니다.', '됩니다', '입니다.', '입니다', '합니다.', '합니다',
            '였습니다.', '했습니다.', '하였습니다.',
        )
        return any(stripped.endswith(e) for e in endings)

    def _has_comma_number(line: str) -> bool:
        """1,234 형태 콤마 숫자 또는 ○○○주, ○○○원 단위 숫자."""
        return bool(re.search(r'\d{1,3}(?:,\d{3})+|\d{2,}주|\d{2,}원', line))

    def _trim_to_sentence(line: str, limit: int = MAX_LEN) -> str:
        """길면 가장 가까운 문장 경계에서 자르기."""
        line = re.sub(r'\s+', ' ', line).strip()
        if len(line) <= limit:
            return line
        # 문장 종결자 우선
        cut = line[:limit]
        last_term = max(
            cut.rfind('. '), cut.rfind('다. '), cut.rfind('. '),
            cut.rfind(' / '), cut.rfind('). '), cut.rfind('니다.'),
        )
        if last_term >= MIN_LEN:
            return cut[:last_term + 1].strip()
        # 문장 종결자 없으면 마지막 공백
        last_space = cut.rfind(' ')
        if last_space >= MIN_LEN:
            return cut[:last_space].strip() + '…'
        return cut.strip() + '…'

    # OCR 줄을 ~120자 청크로 그룹화 (이전 250 → 120, 더 짧고 집중)
    raw_lines = [l.strip() for l in head.split('\n') if l.strip()]
    groups = []
    cur = []
    cur_len = 0
    MAX_GROUP = 140
    for line in raw_lines:
        # 번호 섹션 헤더 (예: "1. ...", "가. ...", "3. 처분내용") 만나면 새 청크 시작
        is_section_header = bool(re.match(r'^(?:\d{1,2}\.|[가-힣]\.)\s', line))
        if is_section_header and cur:
            groups.append(' '.join(cur).strip())
            cur = [line]
            cur_len = len(line)
            continue
        # 청크가 충분히 크면 새로 시작
        if cur_len + len(line) + 1 > MAX_GROUP:
            if cur:
                groups.append(' '.join(cur).strip())
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += len(line) + 1
    if cur:
        groups.append(' '.join(cur).strip())

    NOISE_TOKENS = ('귀중', '귀하', '대표이사', '본점 소재지', '(전 화)', '홈페이지',
                    '작성책임자', '작 성 책 임', '금융감독원장')

    # relaxed 모드에서도 유지되는 강한 표 시그널
    _AUDIT_HEADER_WORDS = (
        '감사인', '감사의견', '의견변형', '강조사항', '핵심감사사항',
        '계속기업 관련', '계속기업관련', '사업연도 구분',
    )

    def _strong_table_signal(line: str) -> bool:
        """relaxed 모드에서도 거부되는 강한 표/비문장 시그널.

        - 연속된 1자 한글 토큰 3개 이상 ('회 사 명', '일 자 종 류 수 량', '대 표 이 사')
        - 감사보고서 헤더 3개 이상 동시 등장 ('감사인 감사의견 의견변형 강조사항...')
        - dash-숫자 패턴 2개 이상
        - DART 표지 필드 덤프 ('제출대상법인 유형' + '면제사유발생')
        - 목차 (TOC) 라인 '제목 ------- 페이지수'
        - '(단위 : ...)' 표 단위 마커
        - '(주N)' 표 주석 마커 2회 이상
        - 정정 전/후 대비 라인
        """
        if not line:
            return True
        tokens = line.split()

        # 1. 연속 1-char 한글
        max_consec = 0
        cur = 0
        for t in tokens:
            if len(t) == 1 and '가' <= t <= '힣':
                cur += 1
                if cur > max_consec:
                    max_consec = cur
            else:
                cur = 0
        if max_consec >= 3:
            return True

        # 2. 감사 헤더 3개 이상
        if sum(1 for w in _AUDIT_HEADER_WORDS if w in line) >= 3:
            return True

        # 3. dash-숫자
        if len(re.findall(r'-\s*\d{1,3}(?:,\d{3})+', line)) >= 2:
            return True

        # 4. DART 표지 필드
        if '제출대상법인' in line and '면제사유발생' in line:
            return True

        # 5. 목차 라인 (연속 하이픈 4개 이상)
        if re.search(r'-{4,}', line) or '―――' in line or '━━━' in line:
            return True

        # 6. 표 단위 마커
        if '(단위' in line or '(단위 :' in line:
            return True

        # 7. 표 주석 마커 '(주1)', '(주2)' ... 2회 이상
        if len(re.findall(r'\(주\d+\)', line)) >= 2:
            return True

        # 8. 정정 전/후 대비
        if '정정 전' in line and '정정 후' in line:
            return True

        # 9. 로마자 섹션 헤더 3개 이상 (I. II. III. — 목차 코알레션)
        if len(re.findall(r'\b[IVX]+\.', line)) >= 3:
            return True

        # 10. 순수 숫자 토큰 4개 이상 (relaxed 모드에서도 거부)
        num_tokens_strong = sum(1 for t in tokens if re.match(r'^[\d,.\-()]+$', t) and len(t) >= 3)
        if num_tokens_strong >= 4:
            return True

        # 11. '해당사항' 2회 이상 반복 (표 행 dump)
        if line.count('해당사항') >= 2:
            return True

        return False

    def _accept(line: str, strict: bool = True) -> Optional[str]:
        """라인이 인용 적합하면 trim해서 반환, 아니면 None.

        strict=True: 기본. _is_likely_table(약한 시그널) 포함 모든 필터 적용.
        strict=False: relaxed. 강한 시그널만 거부. T1~T4에서 quote 부족 시 fallback.
        """
        if not line or line in seen:
            return None
        if any(noise in line for noise in NOISE_TOKENS):
            return None
        if _is_table_dump(line):
            return None
        if _strong_table_signal(line):
            return None
        if strict and _is_likely_table(line):
            return None
        trimmed = _trim_to_sentence(line)
        if not (MIN_LEN <= len(trimmed) <= MAX_LEN):
            return None
        return trimmed

    # T0: 자연 서술문(다/니다 종결) + 키워드 — 가장 가독성 높음
    for line in groups:
        if len(quotes) >= max_quotes:
            break
        if not _is_natural_sentence(line):
            continue
        if not KEYWORD_PAT.search(line):
            continue
        accepted = _accept(line)
        if accepted:
            quotes.append(accepted)
            seen.add(line)

    # T1: 라벨:값 + 키워드 + 숫자 (가장 깨끗 — 날짜/금액 명시)
    for line in groups:
        if len(quotes) >= max_quotes:
            break
        if not _has_label_value(line):
            continue
        if not KEYWORD_PAT.search(line):
            continue
        if not (_has_comma_number(line) or re.search(r'\d{4}년', line)):
            continue
        accepted = _accept(line)
        if accepted:
            quotes.append(accepted)
            seen.add(line)

    # T2: 키워드 + 콤마 숫자 (라벨 없이도 정보 풍부)
    if len(quotes) < max_quotes:
        for line in groups:
            if len(quotes) >= max_quotes:
                break
            if not KEYWORD_PAT.search(line):
                continue
            if not _has_comma_number(line):
                continue
            accepted = _accept(line)
            if accepted:
                quotes.append(accepted)
                seen.add(line)

    # T3: 키워드 + 한글 비율 30% 이상 (표 헤더 줄줄이 거부)
    if len(quotes) < max_quotes:
        for line in groups:
            if len(quotes) >= max_quotes:
                break
            if not KEYWORD_PAT.search(line):
                continue
            korean = sum(1 for c in line if '가' <= c <= '힣')
            if korean / max(len(line), 1) < 0.30:
                continue
            accepted = _accept(line)
            if accepted:
                quotes.append(accepted)
                seen.add(line)

    # T4: 큰 숫자 (10억+) + 라벨:값 — 마지막 fallback
    if len(quotes) < 2:
        for line in groups:
            if len(quotes) >= max_quotes:
                break
            if not _has_label_value(line):
                continue
            big_nums = re.findall(r'\d{1,3}(?:,\d{3}){3,}', line)
            if not big_nums:
                continue
            try:
                val = int(big_nums[0].replace(',', ''))
                if val < 1_000_000_000:
                    continue
            except ValueError:
                continue
            accepted = _accept(line)
            if accepted:
                quotes.append(accepted)
                seen.add(line)

    # T5 (relaxed fallback): strict tiers에서 2개 미만일 때,
    # _is_likely_table 필터를 off하고 키워드+라벨:값 있는 라인 재수집.
    # _is_table_dump(한글 18% 미만)는 여전히 적용 → 순수 숫자행은 여전히 거부.
    if len(quotes) < 2:
        for line in groups:
            if len(quotes) >= max_quotes:
                break
            if not _has_label_value(line) and not KEYWORD_PAT.search(line):
                continue
            accepted = _accept(line, strict=False)
            if accepted:
                quotes.append(accepted)
                seen.add(line)

    return quotes[:max_quotes]


def _format_date_kor(s: str) -> str:
    """'2024 02 07' / '2024-02-07' / '2024.02.07' → '2024년 2월 7일'"""
    if not s:
        return s
    m = re.search(r'(\d{4})[\s.년/-]+(\d{1,2})[\s.월/-]+(\d{1,2})', s)
    if m:
        return f"{m.group(1)}년 {int(m.group(2))}월 {int(m.group(3))}일"
    return s.strip()


def summarize_main_report(
    company: str, fy: int, report_type: str,
    raw_text: str,
    facts: Dict[str, float],
    extracted: dict,
) -> str:
    """주요사항보고서 자연어 요약 (이벤트 중심, 풍부화)."""
    parts = []

    event_type = _detect_event_type(raw_text)

    # 첫 문장: 회사 + 이벤트 (이미 "결정/폐지/발생"으로 끝나면 동사 변경)
    if any(event_type.endswith(suffix) for suffix in ('결정', '폐지', '발생', '신청', '발행')):
        verb = "공시했습니다"
    else:
        verb = "결정·공시했습니다"
    parts.append(f"{with_josa(company, '이가')} {with_josa(event_type, '을를')} {verb}.")

    # 회사 사업 영역 (한 줄, 짧게) — _clean_business_text가 이미 검증·trim 완료
    overview = _clean_business_text(extracted.get('business_overview', ''), 100)
    if overview and len(overview) >= 20:
        parts.append(f"({overview})")

    # 핵심 조건 (확장됨 — 금액/비율/수량/목적)
    terms = _extract_event_terms(raw_text)
    if terms:
        # 우선순위 정렬: 금액 → 비율 → 수량 → 목적 → 기타
        priority = ['사채총액', '발행가액', '취득금액', '처분금액', '계약금액',
                    '분할비율', '합병비율', '감자비율',
                    '주식수', '처분주식수', '표면이자율',
                    '취득방법', '취득목적', '처분목적',
                    '상대회사', '자금조달목적']
        ordered = [(k, terms[k]) for k in priority if k in terms]
        ordered += [(k, v) for k, v in terms.items() if k not in priority]
        terms_str = " / ".join(f"{k} {v}" for k, v in ordered[:6])  # 최대 6개
        parts.append(f"핵심 조건 — {terms_str}.")

    # 주요 일정 (한국식 포맷)
    dates = _extract_dates(raw_text)
    if dates:
        priority = ['이사회결의일', '주주총회', '분할기일', '납입일', '상장예정일']
        ordered = [(k, _format_date_kor(dates[k])) for k in priority if k in dates]
        ordered += [(k, _format_date_kor(v)) for k, v in dates.items() if k not in priority]
        dates_str = " / ".join(f"{k} {v}" for k, v in ordered[:5])
        parts.append(f"주요 일정 — {dates_str}.")

    # 분할/합병/사채의 경우 목적/사유 추가
    if '분할' in event_type or '합병' in event_type:
        purpose_match = re.search(r'분할목적[^.]*?\.([^.]{20,300}\.)', raw_text[:15000])
        if purpose_match:
            purpose = re.sub(r'\s+', ' ', purpose_match.group(1)).strip()
            parts.append(f"목적: {purpose[:200]}")
    elif '사채' in event_type or '자본증권' in event_type:
        # 사채발행: 자금사용 (terms에서 못 잡았으면 대안 검색)
        if '자금조달목적' not in terms:
            m = re.search(r'(?:채무상환|운영자금|시설자금|타법인\s*증권\s*취득|영업양수)', raw_text[:5000])
            if m:
                parts.append(f"자금사용: {m.group(0)}.")

    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════
# 3. 감사보고서 요약 템플릿
# ═══════════════════════════════════════════════════════════════

def _extract_audit_opinion_from_text(raw_text: str) -> str:
    """raw_text에서 감사의견 키워드 직접 매칭 (extractor 실패 시 fallback).

    의견거절 → '의견거절'
    부적정의견 → '부적정의견'
    한정의견 → '한정의견'
    적정의견 → '적정의견'
    """
    if not raw_text:
        return ""
    head = raw_text[:4000]  # 감사의견은 보통 상단
    for opinion in ("의견거절", "부적정의견", "한정의견", "적정의견"):
        if opinion in head:
            return opinion
    # "의견을 표명하지 않" 형태 (의견거절 우회 표현)
    if re.search(r"의견을?\s*표명\s*(?:하지\s*않|할\s*수\s*없)", head):
        return "의견거절"
    return ""


def _extract_auditor_from_text(raw_text: str) -> str:
    """raw_text에서 감사인명 직접 추출.

    패턴: '○○회계법인', '○○ 공인회계사 감사반(제NNN호)', '○○회계감사반'
    """
    if not raw_text:
        return ""
    head = raw_text[:3500]
    # 회계법인 (가장 흔함)
    m = re.search(r"([가-힣A-Za-z]{2,8})\s*회계법인", head)
    if m:
        return m.group(1) + "회계법인"
    # 공인회계사 감사반 (소형 감사보고서)
    m = re.search(r"([가-힣A-Za-z]{2,8})\s*공인회계사\s*감사반", head)
    if m:
        return m.group(1) + " 공인회계사 감사반"
    # 회계감사반
    m = re.search(r"([가-힣A-Za-z]{2,8})\s*회계감사반", head)
    if m:
        return m.group(1) + "회계감사반"
    return ""


def _extract_critical_events_from_text(raw_text: str) -> List[str]:
    """raw_text에서 투자자 판단에 결정적인 중대 사건 추출.

    반환: 사람이 읽을 수 있는 한국어 사건 문장 목록 (최대 3개)
    """
    if not raw_text:
        return []
    head = raw_text[:6000]
    events: List[str] = []

    # 파산선고 신청/결정
    if re.search(r"파산\s*(?:선고|신청|결정)", head):
        events.append("파산 관련 절차가 진행 중")
    # 회생절차 개시
    if re.search(r"회생\s*(?:절차|계획|신청)", head):
        events.append("기업 회생절차 진행 중")
    # 계속기업 불확실성
    if re.search(r"계속기업[^.]{0,40}(?:불확실|중대한\s*의문|존속능력)", head):
        events.append("계속기업 존속능력에 중대한 불확실성")
    # 상장폐지 사유
    if re.search(r"상장폐지\s*사유", head):
        events.append("상장폐지 사유 발생")
    # 감사범위 제한
    if re.search(r"감사범위(?:의)?\s*제한", head):
        events.append("감사범위 제한 발생")
    return events[:3]


def summarize_audit_report(
    company: str, fy: int, report_type: str,
    facts: Dict[str, float],
    extracted: dict,
    raw_text: str = "",
) -> str:
    """감사보고서 자연어 요약 (풍부화).

    extracted.audit_info가 비어도 raw_text에서 직접 감사의견·감사인·중대사건을
    추출해 최소한의 의미 있는 요약을 보장한다.
    """
    parts = []
    overview = _clean_business_text(extracted.get('business_overview', ''), 100)
    is_financial = _is_financial_industry(company, overview)
    subsidiaries = extracted.get('subsidiaries', []) or []

    # 첫 문장: 회사 소개 (사업 영역 또는 자회사)
    if is_financial and subsidiaries:
        sub_list = ", ".join(subsidiaries[:4])
        parts.append(
            f"{with_josa(company, '은는')} {sub_list} 등을 자회사로 두고 있는 "
            f"금융회사로, {fy}년 감사보고서입니다."
        )
    elif overview:
        # overview가 완전한 문장이면 그대로, 아니면 wrap
        if overview.endswith(('습니다.', '입니다.', '다.', '.')):
            parts.append(f"{with_josa(company, '은는')} {overview} {fy}년 감사보고서입니다.")
        else:
            parts.append(
                f"{with_josa(company, '은는')} {with_josa(overview, '을를')} "
                f"영위하는 기업으로, {fy}년 감사보고서입니다."
            )
    else:
        parts.append(f"{with_josa(company, '은는')} {fy}년 감사보고서를 공시했습니다.")

    # 감사인 + 감사의견 (extractor 우선, raw_text fallback)
    audit = extracted.get('audit_info') or {}
    if not isinstance(audit, dict):
        audit = {}
    auditor = (audit.get('auditor') or '').strip()
    opinion = (audit.get('opinion') or '').strip()
    # Fallback: 직접 raw_text에서 추출
    if not auditor:
        auditor = _extract_auditor_from_text(raw_text)
    if not opinion:
        opinion = _extract_audit_opinion_from_text(raw_text)

    if auditor and opinion:
        parts.append(
            f"{with_josa(auditor, '이가')} 감사를 수행하여 "
            f"{with_josa(opinion, '을를')} 표명했습니다."
        )
    elif auditor:
        parts.append(f"{with_josa(auditor, '이가')} 감사를 수행했습니다.")
    elif opinion:
        parts.append(f"감사의견은 {opinion}입니다.")

    # 중대 사건 (파산/회생/계속기업 불확실성 등) — raw_text 직접 스캔
    critical_events = _extract_critical_events_from_text(raw_text)
    if critical_events:
        parts.append("주의: " + ", ".join(critical_events) + ".")

    # 재무 — 매출/이익 (financial_facts 우선, 풍부화)
    revenue = facts.get('revenue') or facts.get('sales')
    op_profit = facts.get('operating_profit') or facts.get('operating_income')
    net_income = facts.get('net_income') or facts.get('net_profit')
    assets = facts.get('total_assets')
    liabilities = facts.get('total_liabilities')
    equity = facts.get('equity') or facts.get('total_equity')

    if revenue is not None:
        revenue_label = "영업수익" if is_financial else "매출액"
        fin_parts = [f"{fy}년 {revenue_label} {_krw_to_kor(revenue)}"]
        if op_profit is not None:
            fin_parts.append(f"영업{'손실' if op_profit < 0 else '이익'} {_krw_to_kor(op_profit)}")
        if net_income is not None:
            fin_parts.append(f"당기순{'손실' if net_income < 0 else '이익'} {_krw_to_kor(net_income)}")
        joined = ", ".join(fin_parts)
        parts.append(with_josa(joined, '을를') + " 기록했습니다.")

    # 재무상태
    if assets is not None and equity is not None:
        bs_parts = [f"자산총계 {_krw_to_kor(assets)}"]
        if liabilities is not None:
            bs_parts.append(f"부채총계 {_krw_to_kor(liabilities)}")
        bs_parts.append(f"자본총계 {_krw_to_kor(equity)}")
        if is_financial:
            equity_ratio = _calc_ratio(equity, assets)
            if equity_ratio is not None:
                bs_parts.append(f"자기자본비율 {equity_ratio:.1f}%")
        else:
            if liabilities is not None and equity != 0:
                debt_ratio = _calc_ratio(liabilities, equity)
                if debt_ratio is not None and -100 <= debt_ratio <= 5000:
                    bs_parts.append(f"부채비율 {debt_ratio:.1f}%")
        parts.append(", ".join(bs_parts) + "를 기록했습니다.")

    # 핵심감사사항 (KAM)
    if isinstance(audit, dict):
        matters = audit.get('matters', [])
        if matters:
            kam_str = " / ".join(m[:80] for m in matters[:3])
            parts.append(f"핵심감사사항: {kam_str}.")

    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════
# 4. 기타공시 / 일반 요약 템플릿
# ═══════════════════════════════════════════════════════════════

def summarize_general(
    company: str, fy: int, report_type: str,
    raw_text: str,
    facts: Dict[str, float],
    extracted: dict,
) -> str:
    """기타공시 / 분류 안 된 보고서 요약 (풍부화)."""
    parts = []
    overview = _clean_business_text(extracted.get('business_overview', ''), 100)
    is_financial = _is_financial_industry(company, overview)

    # 이벤트 유형 감지 — DART 표준 제목 사용
    event = _detect_event_type(raw_text)

    # 첫 문장: 회사 + 이벤트 (또는 유형)
    if event and event != "주요 경영사항":
        parts.append(f"{with_josa(company, '이가')} {with_josa(event, '을를')} 공시했습니다.")
    elif overview:
        if overview.endswith(('습니다.', '입니다.', '다.', '.')):
            parts.append(f"{with_josa(company, '은는')} {overview} ({report_type})")
        else:
            parts.append(
                f"{with_josa(company, '은는')} {with_josa(overview, '을를')} "
                f"영위하는 기업으로, {report_type}를 공시했습니다."
            )
    else:
        parts.append(f"{with_josa(company, '은는')} {report_type}를 공시했습니다.")

    # 핵심 조건 (terms 풍부화 활용)
    terms = _extract_event_terms(raw_text)
    if terms:
        priority = ['사채총액', '발행가액', '취득금액', '처분금액', '계약금액',
                    '분할비율', '합병비율', '감자비율', '주식수', '처분주식수',
                    '취득방법', '취득목적', '처분목적', '상대회사']
        ordered = [(k, terms[k]) for k in priority if k in terms]
        ordered += [(k, v) for k, v in terms.items() if k not in priority]
        terms_str = " / ".join(f"{k} {v}" for k, v in ordered[:5])
        if terms_str:
            parts.append(f"핵심 — {terms_str}.")

    # 일정
    dates = _extract_dates(raw_text)
    if dates:
        priority = ['이사회결의일', '주주총회', '납입일', '상장예정일',
                    '제출일', '처분기간', '취득기간']
        ordered = [(k, _format_date_kor(dates[k])) for k in priority if k in dates]
        if ordered:
            dates_str = " / ".join(f"{k} {v}" for k, v in ordered[:3])
            parts.append(f"일정 — {dates_str}.")

    # 재무 요약 (있으면)
    revenue = facts.get('revenue') or facts.get('sales')
    net_income = facts.get('net_income') or facts.get('net_profit')
    if revenue is not None:
        revenue_label = "영업수익" if is_financial else "매출액"
        fin_str = f"최근 {revenue_label} {_krw_to_kor(revenue)}"
        if net_income is not None:
            fin_str += f", 당기순{'손실' if net_income < 0 else '이익'} {_krw_to_kor(net_income)}"
        parts.append(fin_str + ".")

    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════
# 메인 디스패처
# ═══════════════════════════════════════════════════════════════

def compose_narrative_summary(
    company: str,
    fy: int,
    report_type: str,
    raw_text: str,
    facts: Dict[str, float],
    extracted: dict,
) -> str:
    """문서 유형별 자연어 요약 작성 (디스패처).

    Args:
        company: 회사명 (정규화됨)
        fy: 사업연도 (없으면 0)
        report_type: 보고서 유형 (사업보고서/주요사항보고서/감사보고서/...)
        raw_text: OCR 원문 (이벤트 추출용)
        facts: financial_facts dict {metric_name: value_in_krw}
        extracted: code_only_extractor 출력 dict

    Returns:
        한국어 자연어 요약 (200~800자)
    """
    rt = (report_type or "").strip()

    if "사업보고서" in rt or "분기보고서" in rt or "반기보고서" in rt:
        return summarize_business_report(company, fy, rt, facts, extracted)
    elif "주요사항" in rt or "주요사항보고서" in rt:
        return summarize_main_report(company, fy, rt, raw_text, facts, extracted)
    elif "감사보고서" in rt:
        return summarize_audit_report(company, fy, rt, facts, extracted, raw_text=raw_text)
    else:
        return summarize_general(company, fy, rt, raw_text, facts, extracted)
