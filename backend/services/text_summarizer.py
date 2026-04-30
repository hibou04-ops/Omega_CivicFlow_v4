"""
═══════════════════════════════════════════════════════════════
Omega CivicFlow — Pure Python 고품질 DART 문서 분석 엔진 v3
═══════════════════════════════════════════════════════════════

LLM/API/GPU 없이 DART 공시문서를 구조화 분석.
카테고리별 전용 추출 + 금융 포맷팅 + 구조화 요약.

아키텍처:
  Phase 1: 전처리 (XML 태그/메타데이터 정제, 띄어쓰기 교정)
  Phase 2: 구조 추출 (회사명, 분류, 재무수치, 날짜, 이벤트)
  Phase 3: TextRank 핵심 문장 선별 (가중치 기반)
  Phase 4: 카테고리별 템플릿 요약 합성
  Phase 5: 투자자 인사이트 생성
"""

import re
import math
import logging
from collections import Counter
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Phase 1: 전처리
# ═══════════════════════════════════════════════════════════════

_XML_TAG_PREFIXES = (
    "TD", "DOCUMENT-NAME", "FORMULA-VERSION", "COMPANY-NAME",
    "COVER-TITLE", "REPORT-NAME", "SUBMISSION-DATE",
    "CORP-NAME", "CORP-CODE", "STOCK-CODE",
    "BUSINESS-NUMBER", "CEO-NAME", "ADDRESS",
    "PHONE", "FAX", "HOMEPAGE", "INDUTY-CODE",
    "ACCOUNT-MONTH", "REPORT-CODE", "REPORT-TYPE",
    "AUDIT-NOTE", "CURRENCY", "UNIT",
    "TITLE", "TU", "TH", "TE", "P", "TABLE", "TR", "TF", "TCAPTION",
)

_BOILERPLATE_PATTERNS = [
    r'금\s*융\s*감\s*독\s*원\s*장\s*귀\s*하',
    r'작\s*성\s*책\s*임\s*\.?\s*자\s*[:：]',
    r'\(직\s*책\).*?\(성\s*명\).*?\(전\s*화\)',
    r'\(전\s*화\)\s*[\d\-]+',
    r'\(홈페이지\)\s*http\S+',
    r'본\s*점\s*소\s*재\s*지\s*[:：]',
    r'발행인의\s*명칭\s*및\s*주소',
    r'가\.\s*명\s*칭\s*[:：]',
    r'나\.\s*주\s*소\s*[:：]',
]


def clean_text(text: str) -> str:
    """DART 텍스트 정제 — XML 태그, 보일러플레이트, 전각 공백 제거"""
    if not text:
        return ""

    # HTML/XML 태그
    text = re.sub(r'<[^>]+>', '', text)

    # DART XML 필드 태그 (TD: , TITLE: 등)
    tag_pattern = '|'.join(_XML_TAG_PREFIXES)
    text = re.sub(
        rf'(?:^|\n)\s*(?:{tag_pattern})\s*:\s*',
        '\n', text, flags=re.MULTILINE
    )

    # 보일러플레이트
    for bp in _BOILERPLATE_PATTERNS:
        text = re.sub(bp, '', text)

    # 노이즈 줄 필터
    lines = text.split('\n')
    clean_lines = []
    for line in lines:
        s = line.strip()
        if not s:
            clean_lines.append('')
            continue
        if len(s) <= 3:
            continue
        if re.match(r'^[\d\s,.\-–—:/]+$', s):
            continue
        if re.match(r'^https?://', s):
            continue
        clean_lines.append(s)

    text = '\n'.join(clean_lines)

    # 특수 공백 정규화
    text = text.replace('\u3000', ' ')
    text = text.replace('\xa0', ' ')
    text = text.replace('\u200b', '')
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 한글-숫자 간격
    text = re.sub(r'([가-힣])(\d)', r'\1 \2', text)
    text = re.sub(r'(\d)([가-힣])', r'\1 \2', text)

    # 괄호 정리
    text = re.sub(r'\s*\(\s*', '(', text)
    text = re.sub(r'\s*\)\s*', ') ', text)

    # 단위 붙여쓰기
    text = re.sub(r'(\d)\s+(원|백만원|억원|천원|주|천주|%)', r'\1\2', text)

    # 조사 붙여쓰기
    text = re.sub(r'([가-힣])\s+(은|는|이|가|을|를|의|에|와|과|로|으로|도|만|까지|부터|에서)\s', r'\1\2 ', text)

    # 띄어쓰기 교정 (확장 사전 v2)
    _SPACING_DICT = [
        (r'대\s*표\s*이\s*사', '대표이사'),
        (r'회\s*사\s*명', '회사명'),
        (r'영\s*업\s*이\s*익', '영업이익'),
        (r'당\s*기\s*순\s*이\s*익', '당기순이익'),
        (r'매\s*출\s*액', '매출액'),
        (r'자\s*산\s*총\s*계', '자산총계'),
        (r'부\s*채\s*총\s*계', '부채총계'),
        (r'자\s*본\s*총\s*계', '자본총계'),
        (r'감\s*사\s*의\s*견', '감사의견'),
        (r'유\s*상\s*증\s*자', '유상증자'),
        (r'무\s*상\s*증\s*자', '무상증자'),
        (r'전\s*환\s*사\s*채', '전환사채'),
        # v2 확장
        (r'영\s*업\s*활\s*동', '영업활동'),
        (r'투\s*자\s*활\s*동', '투자활동'),
        (r'재\s*무\s*활\s*동', '재무활동'),
        (r'현\s*금\s*흐\s*름', '현금흐름'),
        (r'이\s*익\s*잉\s*여\s*금', '이익잉여금'),
        (r'포\s*괄\s*손\s*익', '포괄손익'),
        (r'재\s*무\s*상\s*태\s*표', '재무상태표'),
        (r'손\s*익\s*계\s*산\s*서', '손익계산서'),
        (r'사\s*업\s*보\s*고\s*서', '사업보고서'),
        (r'감\s*사\s*보\s*고\s*서', '감사보고서'),
        (r'주\s*요\s*사\s*항', '주요사항'),
        (r'정\s*정\s*신\s*고', '정정신고'),
        (r'연\s*결\s*재\s*무', '연결재무'),
        (r'별\s*도\s*재\s*무', '별도재무'),
        (r'핵\s*심\s*감\s*사', '핵심감사'),
        (r'적\s*정\s*의\s*견', '적정의견'),
        (r'한\s*정\s*의\s*견', '한정의견'),
        (r'계\s*속\s*기\s*업', '계속기업'),
        (r'우\s*발\s*부\s*채', '우발부채'),
        (r'자\s*기\s*주\s*식', '자기주식'),
        (r'배\s*당\s*수\s*익\s*률', '배당수익률'),
        (r'부\s*채\s*비\s*율', '부채비율'),
        (r'영\s*업\s*이\s*익\s*률', '영업이익률'),
        (r'주\s*당\s*이\s*익', '주당이익'),
        (r'주\s*당\s*배\s*당\s*금', '주당배당금'),
        (r'매\s*출\s*총\s*이\s*익', '매출총이익'),
        (r'법\s*인\s*세\s*비\s*용', '법인세비용'),
        (r'주\s*식\s*발\s*행', '주식발행'),
        (r'보\s*통\s*주', '보통주'),
        (r'우\s*선\s*주', '우선주'),
        (r'발\s*행\s*주\s*식', '발행주식'),
        (r'신\s*주\s*인\s*수\s*권', '신주인수권'),
        (r'주\s*주\s*총\s*회', '주주총회'),
        (r'이\s*사\s*회', '이사회'),
        (r'외\s*부\s*감\s*사', '외부감사'),
    ]
    for pat, repl in _SPACING_DICT:
        text = re.sub(pat, repl, text)

    # 중국어/일본어 잔여물
    text = re.sub(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]+', '', text)

    return text.strip()


def _to_single_line(text: str) -> str:
    """줄바꿈 → 공백, 연속 공백 정리"""
    return re.sub(r'\s+', ' ', text).strip()


# ═══════════════════════════════════════════════════════════════
# Phase 2: 구조 추출
# ═══════════════════════════════════════════════════════════════

def extract_company_name(text: str, filename: str = "") -> str:
    """회사명 추출 (다단계 폴백)"""
    # 1) 파일명 DART 패턴
    m = re.search(r'DART_P\d+_(.+?)_(\d{13,14})', filename)
    if m:
        name = m.group(1).strip()
        if len(name) >= 2 and re.search(r'[가-힣a-zA-Z]', name):
            return name

    # 2) 파일명 [회사명] 패턴
    m = re.search(r'\[([가-힣a-zA-Z][가-힣a-zA-Z\s]{1,15})\]', filename)
    if m:
        return m.group(1).strip()

    # 3) COMPANY-NAME 직접
    m = re.search(r'COMPANY-NAME\s*:\s*(.{2,30})', text[:3000])
    if m:
        name = re.sub(r'[\n\r].*', '', m.group(1)).strip()
        name = re.sub(r'\(주\)', '', name).strip()
        if len(name) >= 2:
            return name

    # 4) 텍스트 패턴
    for pat in [
        r'회사명\s*[:：]\s*([가-힣a-zA-Z][가-힣a-zA-Z ()\uFF08\uFF09]{1,25})',
        r'주식회사\s+([가-힣a-zA-Z]{2,15})',
        r'([가-힣]{2,10})\s*주식회사',
    ]:
        m = re.search(pat, text[:5000])
        if m:
            name = re.sub(r'[\n\r].*', '', m.group(1)).strip()
            if name not in {"주식회사", "유한회사", "대표이사", "감사보고서",
                           "사업보고서", "재무제표", "합계", "소계", "금액"} and len(name) >= 2:
                return name

    return "미확인"


# ── 문서 분류 ──

CATEGORY_KEYWORDS = {
    "재무제표": ["재무상태표", "손익계산서", "포괄손익", "현금흐름표",
                "자본변동표", "재무제표", "연결재무", "자산총계", "부채총계",
                "자본총계", "이익잉여금"],
    "사업보고서": ["사업보고서", "사업의 내용", "주요제품", "매출현황",
                 "연구개발", "종업원", "임원현황", "이사회", "지배구조",
                 "사업의 개요"],
    "감사보고서": ["감사보고서", "감사의견", "핵심감사사항", "독립된 감사인",
                 "적정의견", "한정의견", "부적정의견", "의견거절"],
    "주요사항보고서": ["주요사항보고서", "유상증자", "무상증자", "전환사채",
                    "신주인수권", "합병", "분할", "주식교환"],
    "자기주식": ["자기주식", "자사주", "자기주식처분", "자기주식취득"],
    "정정신고": ["정정신고", "정정사유", "정정 전", "정정 후", "정정일자"],
    "배당": ["현금배당", "주당배당금", "배당기준일", "배당수익률"],
}


def classify_document(text: str, filename: str = "") -> str:
    """키워드 빈도 + 위치 가중 분류"""
    head = text[:5000]
    body = text[5000:30000]
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(head.count(kw) * 3 + body.count(kw) for kw in keywords)
        if score > 0:
            scores[cat] = score
    return max(scores, key=scores.get) if scores else "기타공시"


# ── 숫자 포맷팅 ──

def format_korean_number(raw: str) -> str:
    """숫자를 한국어 금융 포맷으로 변환: 134,155 → 약 13.4만"""
    try:
        num_str = raw.replace(',', '').replace(' ', '')
        val = float(num_str)
        if val >= 1_0000_0000_0000:  # 조
            return f"{val / 1_0000_0000_0000:,.1f}조"
        elif val >= 1_0000_0000:  # 억
            return f"{val / 1_0000_0000:,.1f}억"
        elif val >= 1_0000:  # 만
            return f"{val / 1_0000:,.1f}만"
        else:
            return f"{val:,.0f}"
    except (ValueError, TypeError):
        return raw


def _parse_number(raw: str) -> Optional[float]:
    """문자열 → 숫자 (콤마, 괄호 음수 처리)"""
    try:
        s = raw.strip().replace(',', '')
        neg = False
        if s.startswith('(') and s.endswith(')'):
            neg = True
            s = s[1:-1]
        elif s.startswith(('-', '△', '▲')):
            neg = True
            s = s[1:]
        val = float(s)
        return -val if neg else val
    except (ValueError, TypeError):
        return None


# ── 재무수치 추출 ──

FINANCIAL_PATTERNS = {
    "매출액": [
        r'매출액\s*[:：]?\s*([\-]?[\d,]+(?:\.\d+)?)\s*(백만원|억원|원|천원)?',
        r'(?:영업수익|수익\(매출액\))\s*[:：]?\s*([\-]?[\d,]+(?:\.\d+)?)\s*(백만원|억원|원|천원)?',
    ],
    "영업이익": [
        r'영업이익\s*(?:\(손실\))?\s*[:：]?\s*([\-]?[\d,]+(?:\.\d+)?)\s*(백만원|억원|원|천원)?',
    ],
    "당기순이익": [
        r'(?:연결)?당기순이익\s*[:：]?\s*([\-]?[\d,]+(?:\.\d+)?)\s*(백만원|억원|원|천원)?',
        r'당기순(?:이익|손실)\s*[:：]?\s*([\-]?[\d,]+(?:\.\d+)?)\s*(백만원|억원|원|천원)?',
    ],
    "자산총계": [
        r'자산총계\s*[:：]?\s*([\d,]+(?:\.\d+)?)\s*(백만원|억원|원|천원)?',
    ],
    "부채총계": [
        r'부채총계\s*[:：]?\s*([\d,]+(?:\.\d+)?)\s*(백만원|억원|원|천원)?',
    ],
    "자본총계": [
        r'자본총계\s*[:：]?\s*([\d,]+(?:\.\d+)?)\s*(백만원|억원|원|천원)?',
    ],
    "영업활동현금흐름": [
        r'영업활동\s*(?:으로\s*인한\s*)?현금흐름\s*[:：]?\s*([\-]?[\d,]+(?:\.\d+)?)\s*(백만원|억원|원|천원)?',
    ],
}


def extract_financial_metrics(text: str) -> Dict[str, Dict]:
    """재무수치 추출 + 원본/단위/포맷 포함"""
    doc_unit = ""
    m = re.search(r'단위\s*[:：]?\s*(천원|백만원|억원|원)', text[:10000])
    if m:
        doc_unit = m.group(1)

    results = {}
    for metric, patterns in FINANCIAL_PATTERNS.items():
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                raw = m.group(1).strip()
                unit = m.group(2) if m.group(2) else doc_unit
                if raw.replace(',', '').replace('-', '').replace('.', ''):
                    results[metric] = {
                        "raw": raw,
                        "unit": unit,
                        "display": f"{raw}{unit}" if unit else raw,
                        "value": _parse_number(raw),
                    }
                    break
    return results


def extract_dates(text: str) -> List[str]:
    """문서 내 날짜 추출"""
    dates = re.findall(r'(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', text[:10000])
    return [f"{y}.{m.zfill(2)}.{d.zfill(2)}" for y, m, d in dates[:5]]


def extract_disclosure_title(text: str) -> str:
    """공시 제목 추출"""
    for pat in [
        r'(?:보고서명|공시제목|문서명)\s*[:：]\s*(.{5,80})',
        r'COVER-TITLE\s*:\s*(.{5,80})',
    ]:
        m = re.search(pat, text[:5000])
        if m:
            title = _to_single_line(m.group(1))
            return title[:80]
    return ""


# ── 맥락 추론 ──

def extract_context(text: str) -> Dict[str, str]:
    """전년비, 사유, 이벤트 등 맥락 정보 추출"""
    ctx = {}
    head = text[:20000]

    # YoY 증감
    for metric_kr, key in [("매출", "매출_YoY"), ("영업이익", "영업이익_YoY"),
                            ("순이익", "순이익_YoY"), ("당기순이익", "순이익_YoY")]:
        m = re.search(rf'{metric_kr}.*?(?:전년|전기)\s*(?:대비|비)\s*([\d.]+)\s*%\s*(증가|감소|상승|하락)', head)
        if m:
            ctx[key] = f"{m.group(1)}% {m.group(2)}"

    # 감사의견
    m = re.search(r'감사의견\s*[:：]?\s*(적정|한정|부적정|의견거절)', head)
    if m:
        ctx["감사의견"] = m.group(1)
    elif "적정의견" in head:
        ctx["감사의견"] = "적정"

    # 유상증자
    m = re.search(r'유상증자.*?([\d,]+)\s*(주|원|억)', head)
    if m:
        ctx["유상증자"] = f"{m.group(1)}{m.group(2)}"

    # 배당
    m = re.search(r'(?:주당\s*)?배당금\s*[:：]?\s*([\d,]+)\s*원', head)
    if m:
        ctx["배당금"] = m.group(1)

    # 배당수익률
    m = re.search(r'배당수익률\s*[:：]?\s*([\d.]+)\s*%', head)
    if m:
        ctx["배당수익률"] = f"{m.group(1)}%"

    # 합병비율
    m = re.search(r'합병.*?비율\s*[:：]?\s*([\d.:]+)', head)
    if m:
        ctx["합병비율"] = m.group(1)

    # 정정 전/후
    m = re.search(r'정정\s*전\s*[:：]\s*(.{10,100}?)(?:정정\s*후|$)', head)
    if m:
        ctx["정정_전"] = _to_single_line(m.group(1))[:100]
    m = re.search(r'정정\s*후\s*[:：]\s*(.{10,100})', head)
    if m:
        ctx["정정_후"] = _to_single_line(m.group(1))[:100]

    # 주요 사유/원인
    for pat in [
        r'(?:주요\s*(?:원인|사유|이유|목적))\s*[:：은는]?\s*(.{15,200}?)[.。\n]',
        r'(?:이는|그\s*이유는|처분\s*사유)\s+(.{15,200}?)[.。\n]',
    ]:
        m = re.search(pat, head)
        if m:
            ctx["사유"] = _to_single_line(m.group(1))[:150]
            break

    # 자기주식 관련
    m = re.search(r'(?:보통주|주식)\s*([\d,]+)\s*주', head)
    if m:
        ctx["주식수"] = f"{m.group(1)}주"

    m = re.search(r'1주당\s*(?:처분|취득|발행)?\s*가액?\s*[:：]?\s*([\d,]+)\s*원', head)
    if m:
        ctx["1주당가액"] = f"{m.group(1)}원"

    # ★ 처분/취득 구분 (핵심 정보)
    if '처분결과보고서' in head or '처분결정' in head:
        ctx["거래유형"] = "처분(매도)"
    elif '취득결과보고서' in head or '취득결정' in head:
        ctx["거래유형"] = "취득(매수)"
    elif '처분' in head and '취득' not in head:
        ctx["거래유형"] = "처분(매도)"
    elif '취득' in head and '처분' not in head:
        ctx["거래유형"] = "취득(매수)"

    # 처분/취득 사유 (사내근로복지기금 등)
    m = re.search(r'(사내근로복지기금|우리사주조합|임직원\s*복지|경영목적|주주환원|'
                  r'교환사채|신탁계약|소각|스톡옵션|주식매수선택권)', head)
    if m:
        ctx["목적"] = m.group(1)

    return ctx


# ═══════════════════════════════════════════════════════════════
# Phase 3: TextRank 핵심 문장
# ═══════════════════════════════════════════════════════════════

_NOISE_PATTERNS = [
    r'^\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일$',
    r'^주식회사\s+\S{2,15}$', r'^\S{2,10}\s*주식회사$',
    r'^[\d\s,.\-–—:/()]+$', r'^\(?\d[\d\-]+\d\)?$',
    r'^[가-힣]\s*\.\s*[가-힣]',
    r'^대표이사', r'^회사명', r'본점소재지|작성책임',
    r'경[가-힣]{1,4}\s+[가-힣]+[시군구]',
    r'서울[가-힣]*\s+[가-힣]+[구동로]',
    r'전화|팩스|홈페이지|http|CFO|CEO',
    r'^부터$|^까지$|^사업연도$',
    r'1주당처분가액|처분가액총|매도위탁',
    r'주문수량|처분수량|금융투자업자|고유번호',
    r'처분예정주식|일치여부|차이발생',
    r'법제\s*\d+\s*조|보유상황',
    r'FORMULA-VERSION|DOCUMENT-NAME|COMPANY-NAME|COVER-TITLE',
]

_STOPWORDS = {
    "있는", "하는", "것이", "위한", "대한", "관한", "따라", "통해",
    "있다", "한다", "된다", "이다", "바와", "같이", "위하", "있으",
    "하여", "대하", "따른", "의한", "것으", "경우", "사항", "해당",
    "이상", "이하", "미만", "초과", "다음", "기타", "기준", "관련",
    "대로", "바에", "같은", "해서", "하고", "또한", "그리고", "또는",
}

_CRITICAL_KEYWORDS = {
    "매출액": 2.0, "영업이익": 2.0, "당기순이익": 2.0, "순이익": 1.8,
    "자산총계": 1.5, "부채총계": 1.5, "자본총계": 1.5, "현금흐름": 1.5,
    "배당": 1.5, "주당배당금": 1.8,
    "증가": 1.5, "감소": 1.5, "상승": 1.3, "하락": 1.3,
    "전년대비": 1.8, "전기대비": 1.8,
    "유상증자": 2.0, "무상증자": 2.0, "합병": 2.0, "분할": 2.0,
    "전환사채": 1.8, "신주인수권": 1.8,
    "적정의견": 2.0, "한정의견": 2.5, "부적정의견": 3.0,
    "결론": 1.5, "종합": 1.5, "결정": 1.5, "승인": 1.5, "의결": 1.5,
    "원인": 1.5, "사유": 1.5, "목적": 1.3,
    "개선": 1.5, "악화": 1.5, "성장": 1.3, "위험": 1.5,
}


def _is_noise(s: str) -> bool:
    for pat in _NOISE_PATTERNS:
        if re.search(pat, s):
            return True
    if len(re.findall(r'[가-힣]', s)) < 5:
        return True
    return False


def _tokenize(text: str) -> List[str]:
    return [w for w in re.findall(r'[가-힣]{2,}', text) if w not in _STOPWORDS]


def textrank_extract(text: str, n: int = 10) -> List[str]:
    """TextRank 핵심 문장 추출"""
    raw = re.split(r'(?<=[.!?。다함임음됨])\s+|\n{2,}', text)
    sents = [_to_single_line(s) for s in raw if 20 <= len(s.strip()) <= 500 and not _is_noise(s.strip())]

    if not sents:
        return []
    if len(sents) <= n:
        return sents

    # TF-IDF
    doc_freq = Counter()
    sent_tokens = []
    for s in sents:
        tokens = set(_tokenize(s))
        sent_tokens.append(tokens)
        for t in tokens:
            doc_freq[t] += 1

    N = len(sents)
    vectors = []
    for tokens in sent_tokens:
        vec = {}
        tf = Counter(_tokenize(" ".join(tokens)))
        for w, c in tf.items():
            if doc_freq[w] > 0:
                vec[w] = c * (math.log(N / doc_freq[w]) + 1)
        vectors.append(vec)

    # Similarity → TextRank
    def cosine(a, b):
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[k] * b[k] for k in common)
        ma = math.sqrt(sum(v ** 2 for v in a.values()))
        mb = math.sqrt(sum(v ** 2 for v in b.values()))
        return dot / (ma * mb) if ma > 0 and mb > 0 else 0.0

    sim = [[cosine(vectors[i], vectors[j]) if i != j else 0.0 for j in range(N)] for i in range(N)]
    for i in range(N):
        rs = sum(sim[i])
        if rs > 0:
            sim[i] = [s / rs for s in sim[i]]

    scores = [1.0] * N
    for _ in range(30):
        scores = [0.15 + 0.85 * sum(sim[j][i] * scores[j] for j in range(N) if j != i) for i in range(N)]

    # Bonus
    for i, s in enumerate(sents):
        for kw, w in _CRITICAL_KEYWORDS.items():
            if kw in s:
                scores[i] += w
        if len(re.findall(r'[\d,]+', s)) >= 2:
            scores[i] += 1.0
        pos = i / N
        if pos < 0.1:
            scores[i] += 1.5
        elif pos < 0.3:
            scores[i] += 0.5
        elif pos > 0.9:
            scores[i] += 0.8

    ranked = sorted(range(N), key=lambda i: scores[i], reverse=True)
    return [sents[i] for i in sorted(ranked[:n])]


# ═══════════════════════════════════════════════════════════════
# Phase 4: 카테고리별 구조화 요약 합성
# ═══════════════════════════════════════════════════════════════

def _build_header(company: str, category: str, title: str, dates: List[str]) -> str:
    """[개요] 도입부"""
    parts = []
    if company != "미확인":
        if title:
            parts.append(f"{company}이(가) '{title}'을(를) 공시하였습니다.")
        else:
            parts.append(f"{company}의 {category} 공시문서입니다.")
    else:
        parts.append(f"{category} 공시문서입니다.")

    if dates:
        parts.append(f"(공시일: {dates[0]})")

    return " ".join(parts)


def _validate_financial_value(name: str, val: float, unit: str) -> bool:
    """비정상 재무수치 필터링 — 환각 방지"""
    if val is None:
        return False
    # 단위 반영 실제값 계산
    actual = val
    if unit == "천원":
        actual = val * 1000
    elif unit == "백만원":
        actual = val * 1_000_000
    elif unit == "억원":
        actual = val * 1_0000_0000
    # 핵심 재무지표가 100원 미만이면 비정상 (SPAC 등 극소기업도 최소 수백만원)
    major_metrics = {"매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계"}
    if name in major_metrics and abs(actual) < 100:
        return False
    return True


def _build_financials_section(metrics: Dict[str, Dict], doc_unit: str) -> str:
    """[핵심 재무지표] 섹션 — 비정상 수치 필터링 포함"""
    if not metrics:
        return ""

    items = []
    for name, data in metrics.items():
        val = data.get("value")
        unit = data.get("unit", doc_unit)

        # 비정상 수치 검증
        if not _validate_financial_value(name, val, unit):
            continue

        if val is not None:
            # 단위 변환 → 원 단위 통일 후 포맷팅
            if unit == "천원":
                actual_won = int(val * 1000)
            elif unit == "백만원":
                actual_won = int(val * 1_000_000)
            elif unit == "억원":
                actual_won = int(val * 1_0000_0000)
            else:
                actual_won = int(val)
            display = format_korean_number(str(abs(actual_won)))
            sign = "-" if actual_won < 0 else ""
            items.append(f"{name} {sign}{display}원")
        else:
            items.append(f"{name} {data['display']}")

    if not items:
        return ""
    return "주요 재무지표: " + ", ".join(items) + "."


def _build_context_section(ctx: Dict[str, str]) -> List[str]:
    """[맥락 분석] 섹션"""
    parts = []

    # YoY
    for key in ["매출_YoY", "영업이익_YoY", "순이익_YoY"]:
        if key in ctx:
            metric = key.replace("_YoY", "")
            val = ctx[key]
            direction = "개선" if any(w in val for w in ["증가", "상승"]) else "악화"
            parts.append(f"{metric} 전년 대비 {val} ({direction} 추세).")

    # 감사의견
    if ctx.get("감사의견"):
        opinion = ctx["감사의견"]
        if opinion == "적정":
            parts.append("감사의견: 적정 — 재무제표의 신뢰성이 확인되었습니다.")
        else:
            parts.append(f"⚠️ 감사의견: {opinion} — 재무제표에 중대한 제한사항이 있습니다.")

    # 이벤트
    if ctx.get("유상증자"):
        parts.append(f"유상증자 규모: {ctx['유상증자']} — 기존 주주 지분 희석 가능성이 있습니다.")

    if ctx.get("배당금"):
        bps = ctx["배당금"]
        extra = f" (배당수익률 {ctx['배당수익률']})" if ctx.get("배당수익률") else ""
        parts.append(f"주당 배당금: {bps}원{extra}.")

    if ctx.get("합병비율"):
        parts.append(f"합병비율: {ctx['합병비율']}.")

    # 정정
    if ctx.get("정정_전") and ctx.get("정정_후"):
        parts.append(f"정정 전: {ctx['정정_전']} → 정정 후: {ctx['정정_후']}.")
    elif ctx.get("정정_전"):
        parts.append(f"정정 내용: {ctx['정정_전']}.")

    # 사유
    if ctx.get("사유"):
        parts.append(f"공시 사유: {ctx['사유']}.")

    return parts


def _build_treasury_section(ctx: Dict[str, str]) -> str:
    """[자기주식] 전용 요약 블록"""
    parts = []

    # ★ 처분/취득 구분 (가장 중요한 정보)
    if ctx.get("거래유형"):
        parts.append(f"거래유형: {ctx['거래유형']}")

    if ctx.get("주식수"):
        parts.append(f"대상 주식: 보통주 {ctx['주식수']}")
    if ctx.get("1주당가액"):
        parts.append(f"1주당 가액: {ctx['1주당가액']}")
    if ctx.get("목적"):
        parts.append(f"목적: {ctx['목적']}")

    return " | ".join(parts) + "." if parts else ""


def _filter_sentences(sents: List[str], company: str) -> List[str]:
    """TextRank 문장 중 요약에 넣을 고품질 문장만 필터"""
    noise_kw = [
        "회사명", "대표이사", "본점소재지", "작성책임", "귀하", "귀중",
        "1주당처분가액", "처분가액총", "매도위탁",
        "주문수량", "처분수량", "금융투자업자", "고유번호",
        "처분예정주식", "일치여부", "차이발생시",
        "FORMULA-VERSION", "DOCUMENT-NAME", "COMPANY-NAME", "SPAN:",
        "전화", "팩스", "홈페이지", "http",
        "목 차", "목차", "외부감사 실시내용",
    ]

    # DART 폼 필드 레이블 패턴
    form_label_patterns = [
        r'^[가-마]\.\s',             # "가. ", "나. ", "다. " 시작
        r'^\d+\.\s*$',              # "3." 같은 단독 섹션 번호
        r'^\d+\.\s*[가-힣]{1,6}\s*:', # "1. 정정대상 :" 등
        r'처분기간\s*:', r'처분보고\s', r'주요사항보고서\s*제출일',
        r'정정대상\s*공시', r'정정사항\s*항', r'최초제출일',
        r'처분결과보고서$',           # 제목 단독 출현
        r'^-\s*\d{4}\s*년',          # "- 2025 년 5 월..." 날짜만
        # 주소 패턴
        r'[가-힣]+(?:광역시|특별시|특별자치)',
        r'[가-힣]+[시군구]\s+[가-힣]+[동읍면로길]',
    ]

    toc_pattern = re.compile(r'[가-힣]+\s*-\s*\d+')

    result = []
    seen_prefixes = set()
    seen_titles = set()  # 문서 제목 중복 방지

    for s in sents:
        s = _to_single_line(s)
        if len(s) < 25:
            continue

        # 노이즈 키워드
        if any(kw in s for kw in noise_kw):
            continue

        # 회사명만
        if company != "미확인" and s.strip() == company:
            continue

        # DART 폼 레이블
        if any(re.search(pat, s) for pat in form_label_patterns):
            continue

        # "나. 처분기간", "다. 처분보고" 등 (줄 시작이 아니더라도)
        if re.search(r'[가-마]\.\s*(처분|취득|주요사항|정정|배정|발행)', s):
            continue

        # 끝이 숫자+"." ("3.", "5.") 로 끝나면 제거
        s = re.sub(r'\s+\d+\.\s*$', '.', s)

        # OCR 코드/숫자 덩어리
        if re.search(r'\d{8,}', s):
            non_digit = re.sub(r'[\d\s,.()]', '', s)
            if len(non_digit) < len(s) * 0.3:
                continue

        # 숫자 비중 40% 이상
        digits_chars = len(re.findall(r'[\d,.()\-]', s))
        if len(s) > 0 and digits_chars / len(s) > 0.4:
            continue

        # 괄호 숫자 3개 이상
        if len(re.findall(r'\([\d,]+\)', s)) >= 3:
            continue

        # 목차 패턴
        if len(toc_pattern.findall(s)) >= 2:
            continue

        # 문서 제목 중복 방지 ("자기주식처분결과보고서" 등)
        title_match = re.search(r'(자기주식처분결과보고서|사업보고서|감사보고서|'
                                r'주요사항보고서|정정신고)', s)
        if title_match:
            title_key = title_match.group(1)
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

        # 앞 30자 중복 방지
        prefix = s[:30]
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)

        # 마침표 정리
        if not s.endswith(('.', '다.', '함.', '임.', '됨.', '음.')):
            s = s.rstrip('.,;:') + '.'
        result.append(s)

    return result


def synthesize_summary(
    company: str,
    category: str,
    title: str,
    dates: List[str],
    metrics: Dict[str, Dict],
    ctx: Dict[str, str],
    key_sents: List[str],
    doc_unit: str = "",
) -> str:
    """구조화 요약 합성"""
    sections = []

    # [1] 개요
    sections.append(_build_header(company, category, title, dates))

    # [2] 카테고리 전용 블록
    if category == "자기주식":
        treasury = _build_treasury_section(ctx)
        if treasury:
            sections.append(treasury)

    # [3] 재무지표
    fin = _build_financials_section(metrics, doc_unit)
    if fin:
        sections.append(fin)

    # [4] 맥락 분석
    ctx_parts = _build_context_section(ctx)
    sections.extend(ctx_parts)

    # [5] 핵심 내용 (TextRank, 최대 8문장 → 긴 문서도 충분히 커버)
    filtered = _filter_sentences(key_sents, company)
    for s in filtered[:8]:
        sections.append(s)

    result = " ".join(sections)

    # 최소 길이 보충 (300자 미만이면 추가 문장)
    if len(result) < 300 and filtered:
        for extra in filtered[8:]:
            result += " " + extra
            if len(result) >= 500:
                break

    # 최대 길이 제한 (3000자, 문장 경계에서 자름)
    if len(result) > 3000:
        cut = result[:3000]
        last_period = max(cut.rfind('.'), cut.rfind('다.'))
        if last_period > 500:
            result = cut[:last_period + 1]
        else:
            result = cut.rstrip() + "..."

    # 최종 정제
    result = re.sub(r'[\n\r]+', ' ', result)
    result = re.sub(r'\s{2,}', ' ', result)
    return result.strip()


# ═══════════════════════════════════════════════════════════════
# Phase 5: 투자자 인사이트
# ═══════════════════════════════════════════════════════════════

def generate_insight(
    category: str,
    metrics: Dict[str, Dict],
    ctx: Dict[str, str],
) -> str:
    """투자자 관점 인사이트"""
    insights = []

    # YoY 신호
    for key in ["매출_YoY", "영업이익_YoY", "순이익_YoY"]:
        if key in ctx:
            name = key.replace("_YoY", "")
            val = ctx[key]
            if any(w in val for w in ["증가", "상승"]):
                insights.append(f"✅ {name} 개선 ({val})")
            else:
                insights.append(f"⚠️ {name} 악화 ({val})")

    # 감사의견
    opinion = ctx.get("감사의견")
    if opinion == "적정":
        insights.append("✅ 감사 적정의견 — 재무 신뢰도 확인")
    elif opinion:
        insights.append(f"🚨 감사 {opinion} — 재무제표 신뢰도 리스크")

    # 이벤트
    if ctx.get("유상증자"):
        insights.append(f"⚠️ 유상증자 {ctx['유상증자']} — 지분 희석")
    if ctx.get("배당금"):
        extra = f", 수익률 {ctx['배당수익률']}" if ctx.get("배당수익률") else ""
        insights.append(f"💰 배당 {ctx['배당금']}원{extra}")
    if ctx.get("합병비율"):
        insights.append(f"🔄 합병 (비율 {ctx['합병비율']})")

    # 부채비율
    debt_data = metrics.get("부채총계", {})
    equity_data = metrics.get("자본총계", {})
    if debt_data.get("value") and equity_data.get("value"):
        d = debt_data["value"]
        e = equity_data["value"]
        if e > 0:
            ratio = d / e * 100
            if ratio > 200:
                insights.append(f"🚨 부채비율 {ratio:.0f}% — 재무건전성 위험")
            elif ratio > 100:
                insights.append(f"⚠️ 부채비율 {ratio:.0f}% — 주의 필요")
            elif ratio < 50:
                insights.append(f"✅ 부채비율 {ratio:.0f}% — 안정적 재무구조")

    # 영업이익률
    rev_data = metrics.get("매출액", {})
    op_data = metrics.get("영업이익", {})
    if rev_data.get("value") and op_data.get("value") and rev_data["value"] > 0:
        margin = op_data["value"] / rev_data["value"] * 100
        if margin > 15:
            insights.append(f"✅ 영업이익률 {margin:.1f}% — 수익성 우수")
        elif margin > 5:
            insights.append(f"영업이익률 {margin:.1f}%")
        elif margin > 0:
            insights.append(f"⚠️ 영업이익률 {margin:.1f}% — 수익성 부진")
        else:
            insights.append(f"🚨 영업적자 — 수익성 위기")

    if not insights:
        insights.append(f"{category} 공시 — 상세 내용은 원문 확인 권장")

    return " | ".join(insights)


# ═══════════════════════════════════════════════════════════════
# 통합 분석 API
# ═══════════════════════════════════════════════════════════════

def analyze_document_pure_python(text: str, filename: str = "") -> Dict:
    """
    순수 Python DART 문서 분석.
    pdf_report_service.generate_pdf_report() 호환.
    """
    # Phase 1
    clean = clean_text(text)

    # Phase 2
    company = extract_company_name(clean, filename)
    category = classify_document(clean, filename)
    metrics = extract_financial_metrics(clean)
    title = extract_disclosure_title(clean)
    dates = extract_dates(clean)
    ctx = extract_context(clean)

    # 단위 감지
    doc_unit = ""
    m = re.search(r'단위\s*[:：]?\s*(천원|백만원|억원|원)', clean[:10000])
    if m:
        doc_unit = m.group(1)

    # Phase 3 — TextRank 핵심 문장 추출 (n=20으로 충분한 후보 확보)
    key_sents = textrank_extract(clean, n=20)

    # Phase 4
    summary = synthesize_summary(
        company, category, title, dates, metrics, ctx, key_sents, doc_unit,
    )

    # Phase 5
    insight = generate_insight(category, metrics, ctx)

    # 재무지표 문자열 (DB 호환) — 비정상 수치 필터링
    doc_u = ""
    m_u = re.search(r'단위\s*[:：]?\s*(천원|백만원|억원|원)', clean[:10000])
    if m_u:
        doc_u = m_u.group(1)
    financial_items = []
    for k, v in metrics.items():
        if _validate_financial_value(k, v.get("value"), v.get("unit", doc_u)):
            financial_items.append(f"{k}: {v['display']}")
    financial_str = " | ".join(financial_items) if financial_items else ""

    # ═══ 근거 문장 — summary와 분리된 독립 추출 ═══
    # summary에 사용된 문장은 evidence에서 제외
    summary_sents_set = set()
    for s in _filter_sentences(key_sents, company)[:4]:
        # 앞 40자를 기준으로 중복 판별 (정제 과정에서 미세 차이 발생 가능)
        summary_sents_set.add(s[:40])

    # evidence 후보: TextRank 상위 문장 중 summary에 포함되지 않은 것
    filtered_evidence = _filter_sentences(key_sents, company)
    evidence_unique = []
    for s in filtered_evidence:
        if s[:40] not in summary_sents_set:
            evidence_unique.append(s)

    # evidence가 부족하면 OCR에서 숫자/키워드 포함 문장 직접 추출
    if len(evidence_unique) < 3:
        _ev_candidates = re.split(r'(?<=[.!?。다함임음됨])\s+|\n{2,}', clean)
        for s in _ev_candidates:
            s = _to_single_line(s)
            if len(s) < 30 or len(s) > 400:
                continue
            if _is_noise(s):
                continue
            # 숫자 + 재무 키워드 포함 문장 우선
            has_number = bool(re.search(r'[\d,]+', s))
            has_keyword = any(kw in s for kw in ["매출", "이익", "자산", "부채", "자본",
                                                  "현금", "배당", "증자", "처분", "취득",
                                                  "감사", "합병", "전환", "발행", "결정"])
            if has_number and has_keyword and s[:40] not in summary_sents_set:
                if s not in evidence_unique:
                    evidence_unique.append(s)
                if len(evidence_unique) >= 5:
                    break

    evidence = " // ".join(evidence_unique[:5]) if evidence_unique else ""

    # ═══ 최종 정제 (모든 출력 필드) ═══
    summary = _sanitize_output(summary)
    evidence = _sanitize_output(evidence)

    return {
        "summary": summary,
        "category": category,
        "company_name": company,
        "disclosure_title": title,
        "financial_metrics": financial_str,
        "evidence": evidence,
        "insight_vectors": insight,
        "_method": "pure_python_textrank_v3",
        "_context": ctx,
        "_dates": dates,
    }


def _sanitize_output(text: str) -> str:
    """모든 출력 필드에 대한 최종 정제 — 잔여 노이즈 완전 제거"""
    if not text:
        return text

    # 줄바꿈 → 공백
    text = re.sub(r'[\n\r]+', ' ', text)

    # 끝에 붙은 섹션 번호: "170,397주 3." → "170,397주."
    text = re.sub(r'\s+\d+\.\s*$', '.', text)
    # 문장 중간의 단독 숫자+점: "...주 3. 처분보고..." → "...주. 처분보고..."
    text = re.sub(r'\s+(\d+)\.\s+', '. ', text)

    # "나.", "다." 등 폼 레이블 잔여
    text = re.sub(r'\s+[가-마]\.\s+', ' ', text)
    text = re.sub(r'\s+[가-마]\.\s*$', '.', text)

    # "SPAN:", "N N N" 등 OCR 잔여
    text = re.sub(r'SPAN:\s*', '', text)
    text = re.sub(r'\bN\s+N\s+N\b', '', text)

    # 잘린 영어 이름 제거: "결정 J. P." → "결정."
    text = re.sub(r'\s+[A-Z]\.\s*[A-Z]?\.\s*$', '.', text)
    # 문장 끝 불완전 영어: "...결정 J." → "...결정."
    text = re.sub(r'\s+[A-Z]\.\s*$', '.', text)
    # 문장 끝 불완전 영어 단어: "...고려하여 결정 Morgan" 등
    text = re.sub(r'\s+[A-Z][a-z]*\s*$', '.', text)

    # 연속 공백/마침표
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r'\.\s*\.', '.', text)

    # 끝 정리
    text = text.strip()
    if text and not text.endswith('.'):
        text = text.rstrip('.,;:') + '.'

    return text
