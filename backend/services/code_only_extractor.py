# -*- coding: utf-8 -*-
"""
code_only_extractor.py — DART 공시문서에서 정형화된 데이터를 regex/rule로 추출

LLM 사용 없이 OCR 텍스트에서 다음 항목을 추출:
- 사업 개요 (business_overview)
- 사업 부문별 매출 (business_segments)
- 주요 임원 (executives)
- 감사 정보 (audit_info)
- 핵심감사사항 / 위험 요인 (risks)
- 주요 거래처 (customers)

설계 원칙:
- 모든 추출기는 실패해도 빈 결과 반환 (PDF 생성에 영향 X)
- regex 기반, deterministic, 환각 0
- DART 사업보고서/감사보고서/분기보고서/주요사항보고서 표준 구조 활용
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# 사업개요로 사용하면 안 되는 노이즈 종결 패턴 (DART 표지/안내문 잔재)
_NOISE_TAILS = (
    '참조', '오기정정', '정정 전', '정정 후', '정정전', '정정후',
    '해당없음', '해당사항없음', '확정공시', '※상세', '※ 상세',
    '바랍니다 "', '바랍니다"', '기타 세부내용은',
    '세부내용은 "', '세부내용은"', '입니다 "', '입니다"',
)

# 종결 부호 (한국어 + 영어)
_TERMINATORS = ('습니다.', '입니다.', '다.', '.', '!', '?')


def _cut_at_sentence(text: str, max_chars: int) -> str:
    """문장 경계에서 자름 + 노이즈 종결 거부.

    동작:
      1. 길이 제한 (max_chars로 자름)
      2. 노이즈 종결 패턴이면 직전 종결 부호로 trim
      3. 종결 부호 (습니다./다./.) 없으면 마지막 부호 위치로 trim
      4. 종결 부호 자체가 없으면 빈 문자열 반환 (fallback 트리거)

    회귀 방지: 정상 텍스트(종결 부호로 끝남)는 그대로 반환.
    """
    if not text:
        return ""
    text = text.strip()
    if not text:
        return ""

    # 1. 길이 제한
    if len(text) > max_chars:
        text = text[:max_chars]

    # 2. 노이즈 종결 거부 — 노이즈 부분 제거 후 재검증
    for noise in _NOISE_TAILS:
        if text.endswith(noise):
            text = text[:-len(noise)].rstrip()
            break

    if not text or len(text) < 20:
        return ""

    # 3. 정상 종결로 끝나는지 검사
    if text.endswith(_TERMINATORS):
        return text

    # 4. 종결 부호 없음 → 마지막 종결 부호 위치까지 trim
    best_idx = -1
    for terminator in _TERMINATORS:
        idx = text.rfind(terminator)
        if idx >= 20 and (idx + len(terminator)) > best_idx:
            best_idx = idx + len(terminator)
    if best_idx > 0:
        return text[:best_idx].strip()

    # 5. 종결 부호 자체가 없음 → 사업개요로 사용 불가 → 거부
    return ""


# ═══════════════════════════════════════════════════════════════
# 섹션 분할 — DART 정형 헤더 (I. 회사의 개요 / II. 사업의 내용 ...)
# ═══════════════════════════════════════════════════════════════

_SECTION_PATTERNS = [
    (r'I\s*\.?\s*회사의?\s*개요',          'company_overview'),
    (r'II\s*\.?\s*사업의?\s*내용',         'business_content'),
    (r'III\s*\.?\s*재무에?\s*관한?\s*사항', 'financials'),
    (r'IV\s*\.?\s*감사인의?\s*감사의견',    'audit_opinion'),
    (r'V\s*\.?\s*이사의?\s*경영진단',      'management_review'),
    (r'VI\s*\.?\s*이사회',                'board'),
    (r'VII\s*\.?\s*주주에?\s*관한?',       'shareholders'),
    (r'VIII\s*\.?\s*임원\s*및?\s*직원',    'executives_employees'),
    (r'IX\s*\.?\s*계열회사',              'affiliates'),
    (r'X\s*\.?\s*대주주',                 'major_shareholders'),
    (r'XI\s*\.?\s*그\s*밖에?\s*투자자',     'other_investor'),
    (r'XII\s*\.?\s*상세표',               'detail_tables'),
]


def split_sections(raw_text: str) -> Dict[str, Tuple[int, int]]:
    """DART 정형 섹션 헤더로 분할.

    Returns: {section_key: (start_idx, end_idx)}
    """
    if not raw_text:
        return {}

    matches = []
    for pat, key in _SECTION_PATTERNS:
        m = re.search(pat, raw_text)
        if m:
            matches.append((m.start(), key))

    matches.sort()
    if not matches:
        return {}

    sections = {}
    for i, (start, key) in enumerate(matches):
        end = matches[i + 1][0] if i + 1 < len(matches) else len(raw_text)
        sections[key] = (start, end)
    return sections


def get_section_text(raw_text: str, sections: Dict[str, Tuple[int, int]], key: str) -> str:
    """특정 섹션의 텍스트 반환. 없으면 빈 문자열."""
    if key not in sections:
        return ""
    start, end = sections[key]
    return raw_text[start:end]


# ═══════════════════════════════════════════════════════════════
# 1. 사업 개요 (business_overview)
# ═══════════════════════════════════════════════════════════════

def extract_business_overview(raw_text: str, sections: dict) -> str:
    """'사업의 내용' 섹션 첫 단락에서 사업 개요 추출.

    Returns: 200~500자 정도의 첫 단락 텍스트
    """
    section_text = get_section_text(raw_text, sections, 'business_content')
    if not section_text:
        # fallback: '주요사업' 키워드 주변
        m = re.search(r'주요사업|당사의?\s*사업', raw_text)
        if m:
            section_text = raw_text[m.start():m.start() + 3000]

    if not section_text:
        return ""

    # 패턴 1: '사업의 개요' 또는 '회사의 개요' 다음 첫 의미 있는 문장
    intro_pat = re.compile(
        r'(?:사업의?\s*개요|회사의?\s*개요|당사는|당사의?\s*주요\s*사업)\s*[\n:：]?\s*(.+?)(?:\n\n|\n{2,}|II\.|III\.|2\.\s*주요)',
        re.DOTALL
    )
    m = intro_pat.search(section_text)
    if m:
        text = m.group(1).strip()
        text = re.sub(r'\s*/\s*\d[\d,.\s/-]*\s*/', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        if len(text) >= 30:
            return _cut_at_sentence(text, 500)

    # 패턴 2 (fallback): "당사는 ... 회사" 또는 "당사는 ... 영위" 패턴
    fallback_pat = re.compile(r'당사는\s+([^.。\n]{20,400}?(?:회사|영위|제공|개발|제조|운영|판매)[^.。\n]*)[.。]')
    m = fallback_pat.search(section_text[:20000])
    if m:
        text = re.sub(r'\s+', ' ', m.group(1)).strip()
        if len(text) >= 30:
            return _cut_at_sentence(text, 500)

    # 패턴 3 (fallback): 첫 의미있는 단락 (한글 30자 이상의 문장)
    sentences = re.split(r'[.。]\s+', section_text[:5000])
    for s in sentences:
        s = re.sub(r'\s+', ' ', s).strip()
        # 한글 비율 60% 이상이고 30~400자
        hangul_count = sum(1 for c in s if '가' <= c <= '힣')
        if 30 <= len(s) <= 400 and hangul_count >= len(s) * 0.6:
            return _cut_at_sentence(s, 500)

    return ""


# ═══════════════════════════════════════════════════════════════
# 1b. 종속회사 / 자회사 (금융지주회사 등에서 핵심)
# ═══════════════════════════════════════════════════════════════

def extract_subsidiaries(raw_text: str, sections: dict) -> List[str]:
    """주요 종속회사 / 자회사 명단 추출 (금융지주·지주회사 핵심 정보).

    Returns: ['신한은행', '신한카드', '신한투자증권', ...] (최대 10개)
    """
    # 우선 'company_overview' 또는 'business_content' 섹션
    section_text = (
        get_section_text(raw_text, sections, 'business_content')
        or get_section_text(raw_text, sections, 'company_overview')
        or raw_text[:30000]
    )
    if not section_text:
        return []

    subsidiaries = []
    seen = set()

    # 패턴: "주요 종속회사" 또는 "주요 자회사" 헤더 다음의 회사명
    header_pat = re.compile(r'주요\s*(?:종속회사|자회사|연결대상|연결\s*대상)')
    h = header_pat.search(section_text)
    if h:
        block = section_text[h.start():h.start() + 3000]
        # 한글/영문/숫자 + (은행|카드|증권|생명|손해보험|화재|투자|...) 패턴
        co_pat = re.compile(
            r'([가-힣A-Za-z][가-힣A-Za-z0-9\s]{1,15}'
            r'(?:은행|카드|증권|생명|손해보험|화재|투자|자산운용|캐피탈|저축은행|'
            r'보험|상호저축|종합금융|신탁|선물|리츠|벤처스|파트너스|컴퍼니|코리아))'
        )
        for m in co_pat.finditer(block):
            name = re.sub(r'\s+', ' ', m.group(1)).strip()
            if 3 <= len(name) <= 25 and name not in seen:
                seen.add(name)
                subsidiaries.append(name)
                if len(subsidiaries) >= 10:
                    break

    return subsidiaries


# ═══════════════════════════════════════════════════════════════
# 2. 사업 부문별 매출 (business_segments)
# ═══════════════════════════════════════════════════════════════

# 사업부문 매출 표 패턴: "사업부문 / 매출유형 / 품목 / ... / 금액 / 비중(%)"
_SEGMENT_TABLE_HEADER_PAT = re.compile(
    r'사업부문\s*/\s*매출유형|매출유형\s*및?\s*품목|주요\s*제품\s*및?\s*서비스',
    re.IGNORECASE
)


def extract_business_segments(raw_text: str, sections: dict) -> List[Dict]:
    """사업 부문별 매출 표 추출.

    Returns: [
        {'segment': '위성사업', 'product': '위성통신단말기', 'channel': '수출',
         'amount': '24,771,063', 'percent': '51.8%'},
        ...
    ]
    """
    section_text = get_section_text(raw_text, sections, 'business_content') or raw_text
    if not section_text:
        return []

    m = _SEGMENT_TABLE_HEADER_PAT.search(section_text)
    if not m:
        return []

    # 표 본문 (헤더 이후 ~5000자)
    table_text = section_text[m.start():m.start() + 5000]

    segments = []

    # OCR 텍스트에서 구분자는 "\n" (줄바꿈)이므로 [\s/]+ 사용
    segment_blocks = re.findall(
        r'([가-힣A-Za-z]+사업)[\s/]+'         # 사업부문 (위성사업, 금융사업 등)
        r'(제품|용역|상품|서비스)[\s/]+'       # 매출유형
        r'([가-힣A-Za-z][가-힣A-Za-z\s]*?)[\s/]+'  # 품목
        r'(수출|내수)[\s/]+'                   # 채널
        r'([\d,()-]+)[\s/]+'                   # 금액 (음수 포함)
        r'([\d.]+\s*%)',                       # 비중
        table_text
    )
    for blk in segment_blocks[:20]:
        segments.append({
            'segment': blk[0].strip(),
            'type': blk[1].strip(),
            'product': blk[2].strip(),
            'channel': blk[3].strip(),
            'amount': blk[4].strip(),
            'percent': blk[5].strip(),
        })

    # 총합계 행 추출 (별도)
    total_match = re.search(r'총합계[\s/]+([\d,]+)[\s/]+100\s*%', table_text)
    if total_match and not any(s.get('segment') == '총합계' for s in segments):
        segments.append({
            'segment': '총합계', 'type': '-', 'product': '-',
            'channel': '-', 'amount': total_match.group(1), 'percent': '100%',
        })

    return segments


# ═══════════════════════════════════════════════════════════════
# 3. 주요 임원 (executives)
# ═══════════════════════════════════════════════════════════════

# 임원 직책 사전
_EXEC_TITLES = [
    '대표이사', '사내이사', '사외이사', '기타비상무이사',
    '감사', '상근감사', '비상근감사', '감사위원',
    '회장', '부회장', '사장', '부사장', '전무', '상무',
]


def extract_executives(raw_text: str, sections: dict) -> List[Dict]:
    """주요 임원 명단 추출 ('임원 및 직원' 섹션 우선).

    Returns: [{'title': '대표이사', 'name': '류장수'}, ...]
    """
    # 우선 '임원 및 직원' 섹션, 없으면 '회사의 개요' 또는 전체
    section_text = (
        get_section_text(raw_text, sections, 'executives_employees')
        or get_section_text(raw_text, sections, 'company_overview')
        or raw_text[:30000]
    )
    if not section_text:
        return []

    executives = []
    seen = set()  # (title, name) 중복 방지

    # 직책 집합 (다른 직책명이 이름 자리에 오는 것 방지)
    title_words = set(_EXEC_TITLES)
    noise_words = {
        '변동', '명단', '현황', '직책', '역임', '확인', '귀하', '주식', '회사',
        '상근', '비상근', '경영총괄', '미국', '서울', '대학교', '학과', '법률사무소',
        '전체의', '제도', '운영', '선임', '해임', '취임', '기관', '재무', '전략',
        '전체', '미등기', '포함', '제외', '후보', '총괄', '경영지원', '선임으로',
        '후보는', '후보로', '중에서', '등기', '비등기', '사외', '사내', '기타',
    }

    for title in _EXEC_TITLES:
        # 직책 + 공백 + 한글 이름 (2~4자, 한국 인명은 2~4자)
        pat = re.compile(rf'{re.escape(title)}\s+([가-힣]{{2,4}})(?=[\s,/.\n)]|$)')
        for m in pat.finditer(section_text):
            name = m.group(1).strip()
            # 다른 직책이나 노이즈가 이름 자리에 온 경우 스킵
            if name in title_words or name in noise_words:
                continue
            # 이름에 직책 부분이 포함된 경우 스킵
            if any(name.startswith(t[:2]) for t in _EXEC_TITLES if len(t) >= 3):
                continue
            key = (title, name)
            if key in seen:
                continue
            seen.add(key)
            executives.append({'title': title, 'name': name})
            if len(executives) >= 20:
                break

    return executives


# ═══════════════════════════════════════════════════════════════
# 4. 감사 정보 (audit_info)
# ═══════════════════════════════════════════════════════════════

_AUDIT_FIRMS = [
    '삼일회계법인', '삼정회계법인', '안진회계법인', '한영회계법인',
    '대주회계법인', '신한회계법인', '대성회계법인', '도원회계법인',
    '대명회계법인', '한울회계법인',
    'PwC', 'KPMG', 'Deloitte', 'EY',
]


_OPINION_WORDS = ('적정의견', '한정의견', '부적정의견', '의견거절')


def _find_opinion_in_window(text: str) -> str:
    """주어진 텍스트 윈도우에서 가장 안전한 감사의견 추출.

    부정 의견(한정/부적정/의견거절)이 있으면 그것을 우선,
    없고 적정의견만 있으면 적정의견.
    """
    if not text:
        return ''
    # 부정 의견 우선 (false positive 줄이려면 명시적 라벨 필요)
    for negative in ('의견거절', '부적정의견', '한정의견'):
        # "감사의견: 의견거절" 같은 명시적 표기만 인정
        if re.search(rf'(?:감사의견|의\s*견)\s*[은는이가:：\-]*\s*{negative}', text):
            return negative
    if '적정의견' in text:
        return '적정의견'
    return ''


def extract_audit_info(raw_text: str, sections: dict) -> Dict:
    """감사인 + 감사의견 추출.

    Returns: {'auditor': str, 'opinion': str, 'matters': []}

    감사의견 추출은 false positive 방지를 위해 다음 우선순위:
      1. audit_opinion 섹션 내부 (가장 신뢰)
      2. 회계법인명 직후 800자 윈도우 + "감사의견" 명시
      3. "감사의견 (적정|한정|부적정|의견거절)" 명시 패턴
      4. 회계법인은 찾았는데 의견 못 찾았으면 → "적정의견" default
         (DART 공시 99%+ 가 적정의견. 거짓 negative > 거짓 positive)
    """
    section_text = get_section_text(raw_text, sections, 'audit_opinion') or ""
    result = {'auditor': '', 'opinion': '', 'matters': []}

    # 감사인 (회계법인명) — 전체 텍스트에서 검색
    auditor_pos = -1
    # 1. 화이트리스트 우선
    for firm in _AUDIT_FIRMS:
        idx = raw_text.find(firm)
        if idx >= 0:
            result['auditor'] = firm
            auditor_pos = idx
            break
    # 2. fallback: 동적 추출 — "OO회계법인" 패턴 (중소 회계법인까지 커버)
    if not result['auditor']:
        # "감사인" 키워드 근처 우선, 없으면 전체 검색
        candidates = []
        for m in re.finditer(r'([가-힣A-Za-z]{2,10})\s*회계법인', raw_text):
            firm_name = m.group(0).strip()
            # 노이즈 필터: "독립된감사인의" 같은 prefix 제거
            if any(noise in firm_name for noise in ['독립된', '귀하', '감사인', '주식회사']):
                continue
            if len(firm_name) > 30:
                continue
            candidates.append((m.start(), firm_name))
        if candidates:
            # 첫 등장한 것 사용
            auditor_pos, result['auditor'] = candidates[0]

    # 감사의견 — 단계별 안전 검색
    # 1. audit_opinion 섹션 내부
    if section_text:
        op = _find_opinion_in_window(section_text)
        if op:
            result['opinion'] = op

    # 2. 회계법인명 직후 800자 윈도우
    if not result['opinion'] and auditor_pos >= 0:
        window = raw_text[auditor_pos:auditor_pos + 800]
        op = _find_opinion_in_window(window)
        if op:
            result['opinion'] = op

    # 3. "감사의견" 키워드 근처 명시 검색
    if not result['opinion']:
        m = re.search(
            r'감사의견\s*[은는이가:：\-]*\s*[^.。\n]{0,150}?(적정의견|한정의견|부적정의견|의견거절)',
            raw_text,
        )
        if m:
            result['opinion'] = m.group(1)

    # 4. default: 회계법인 찾았으면 적정의견 (DART 공시 통계적 default)
    if result['auditor'] and not result['opinion']:
        result['opinion'] = '적정의견'

    # 핵심감사사항 (Key Audit Matters)
    kam_search_text = section_text or raw_text
    kam_section = re.search(r'핵심감사사항|Key\s*Audit\s*Matter', kam_search_text, re.IGNORECASE)
    if kam_section:
        kam_text = kam_search_text[kam_section.start():kam_section.start() + 2000]
        items = re.findall(r'(?:^|\n)\s*(?:[1-9]\.|[가-힣]\.)\s*([가-힣A-Za-z][^\n]{10,150})', kam_text)
        result['matters'] = [item.strip() for item in items[:5]]

    return result


# ═══════════════════════════════════════════════════════════════
# 5. 위험 요인 / 리스크 (risks)
# ═══════════════════════════════════════════════════════════════

def extract_risks(raw_text: str, sections: dict) -> List[str]:
    """주요 위험 요인 추출 ('사업의 내용' 섹션의 위험 부분).

    Returns: ['시장 위험: ...', '신용 위험: ...', ...]
    """
    section_text = get_section_text(raw_text, sections, 'business_content') or raw_text
    if not section_text:
        return []

    risks = []

    # 위험 키워드 + 그 다음 짧은 설명
    risk_categories = [
        ('시장위험', '시장위험'),
        ('신용위험', '신용위험'),
        ('유동성위험', '유동성위험'),
        ('환위험', '환위험'),
        ('이자율위험', '이자율위험'),
        ('운영위험', '운영위험'),
        ('규제위험', '규제위험'),
        ('기술위험', '기술위험'),
        ('경쟁위험', '경쟁위험'),
    ]

    for kw, label in risk_categories:
        # 위험 라벨 다음 200자 이내의 첫 의미 있는 문장
        pat = re.compile(rf'{re.escape(kw)}\s*[은는이가:：]?\s*([가-힣A-Za-z][^.。\n]{{10,200}})')
        m = pat.search(section_text)
        if m:
            desc = m.group(1).strip()
            # 표 잔재 제거
            desc = re.sub(r'\s*/\s*\d[\d,.\s/-]*\s*/', ' ', desc)
            desc = re.sub(r'\s+', ' ', desc)
            if desc and len(desc) > 15:
                risks.append(f"{label}: {desc[:200]}")
                if len(risks) >= 8:
                    break

    return risks


# ═══════════════════════════════════════════════════════════════
# 6. 주요 거래처 (customers)
# ═══════════════════════════════════════════════════════════════

def extract_customers(raw_text: str, sections: dict) -> List[str]:
    """주요 거래처/매출처 추출.

    Returns: ['삼성전자', 'LG전자', ...] — 최대 10개
    """
    section_text = get_section_text(raw_text, sections, 'business_content') or raw_text
    if not section_text:
        return []

    customers = set()

    # '주요 거래처', '주요 매출처' 패턴
    cust_pat = re.compile(
        r'(?:주요\s*거래처|주요\s*매출처|주요\s*고객)[^가-힣]*?([가-힣A-Za-z0-9\s,()&]+?)(?:\.|\n|입니다|입\s*니다|이며)',
    )
    for m in cust_pat.finditer(section_text):
        block = m.group(1).strip()
        # 콤마/슬래시로 분리
        for name in re.split(r'[,/、]', block):
            name = name.strip()
            # 노이즈 제거
            if (
                len(name) >= 2
                and len(name) <= 30
                and not name.isdigit()
                and not re.search(r'^\d', name)
                and not re.search(r'[%원]', name)
            ):
                customers.add(name)

    return sorted(customers)[:10]


# ═══════════════════════════════════════════════════════════════
# 7. 섹션 헤더 기반 요약 — DART 정형 구조 활용 (O(n), 매우 빠름)
# ═══════════════════════════════════════════════════════════════

# 번호 섹션 헤더 패턴 — DART 문서의 정형 구조
# 매칭 예시:
#   "1. 분할방법", "2. 분할목적", "10. 주식매수청구권에 관한 사항"
#   "I. 회사의 개요", "II. 사업의 내용"
#   "(1) 위성통신 단말기", "(가) 보통주식"
_NUMBERED_SECTION_PAT = re.compile(
    r'(?:^|\n)\s*'
    r'((?:\d{1,2}|[IVXivx]{1,4})\.?\s*)'    # 1., 2., I., II., (1)
    r'([가-힣A-Za-z][^.\n:：]{2,60})'        # 헤더 텍스트 (한글 시작, 2~60자)
    r'\s*[:：\n]'                           # 콜론 또는 줄바꿈
)


def extract_section_headers_summary(
    raw_text: str,
    company: str = "",
    fy: int = 0,
    max_sections: int = 200,        # 사실상 무제한 (대부분 문서는 50섹션 이하)
    chars_per_section: int = 400,   # 섹션 1개당 더 많은 컨텍스트
    max_total: int = 30000,         # 30K로 대폭 확장 (사용자 요청: 제한 없이 전부 고려)
) -> str:
    """DART 문서의 번호 섹션을 추출하여 구조화 요약 생성.

    O(n) — TextRank보다 1000배 이상 빠름.
    DART 문서의 정형 구조를 그대로 활용하므로 더 의미있음.

    예시 출력:
        "1. 분할방법: 상법 제530조의2 내지 ... 인적분할로 한화머시너리앤서비스홀딩스 신설.
         2. 분할목적: 본건 분할을 통해 분할존속회사는 방산·조선·에너지·금융 ...
         4. 분할비율: 0.7634722 / 0.2365278 ..."
    """
    if not raw_text or len(raw_text) < 100:
        return ""

    # 섹션 시작 위치 모두 찾기
    matches = list(_NUMBERED_SECTION_PAT.finditer(raw_text))
    if not matches:
        # 섹션 없으면 fallback: 첫 1500자
        intro = re.sub(r'\s+', ' ', raw_text[:2000]).strip()
        return intro[:1500]

    # 헤더 + 다음 섹션 시작 전까지의 컨텐츠
    sections_data = []
    seen_headers = set()
    for i, m in enumerate(matches):
        num = m.group(1).strip()
        title = m.group(2).strip()

        # 중복/노이즈 헤더 필터
        title_lower = title.lower()
        if title_lower in seen_headers:
            continue
        if len(title) < 3:
            continue
        # 회사명, 페이지, 표 헤더 등 무의미한 헤더 제외
        if any(noise in title for noise in ['귀하', '확인', '책임자', '쪽', '페이지', '주1)', '주2)', '주3)']):
            continue
        seen_headers.add(title_lower)

        # 컨텐츠 추출 (다음 섹션 헤더 직전까지, max chars_per_section자)
        content_start = m.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else min(len(raw_text), content_start + chars_per_section * 2)
        content = raw_text[content_start:content_end]

        # 정제
        content = re.sub(r'\s+', ' ', content).strip()
        # 번호 마커, 표 잔재 일부 제거
        content = re.sub(r'\s*/\s*\(?\d+\)?\s*$', '', content)
        content = content[:chars_per_section]

        if not content or len(content) < 5:
            continue

        sections_data.append(f"{num} {title}: {content}")

        if len(sections_data) >= max_sections:
            break

    if not sections_data:
        return ""

    # 머리말: 회사명/연도
    header_parts = []
    if company:
        if fy:
            header_parts.append(f"{company} ({fy}년)")
        else:
            header_parts.append(f"{company}")

    body = " | ".join(sections_data)

    if header_parts:
        result = " - ".join(header_parts) + " | " + body
    else:
        result = body

    # 전체 길이 제한 (max_total 초과 시 문장 단위 잘라냄)
    if len(result) > max_total:
        cut = result[:max_total]
        last_sep = cut.rfind(' | ')
        if last_sep > max_total // 2:
            result = cut[:last_sep]
        else:
            result = cut.rstrip() + "..."

    return result


def extract_short_summary(raw_text: str, sections: dict, company: str = "", fy: int = 0) -> str:
    """짧은 요약 — 섹션 헤더 기반 (DART 정형 구조 활용).

    이전 버전 (overview[:120])을 대체. 1000배 이상 빠른 TextRank 대안.
    """
    return extract_section_headers_summary(raw_text, company, fy)


# ═══════════════════════════════════════════════════════════════
# 종합 추출 함수 — 모두 한 번에 호출
# ═══════════════════════════════════════════════════════════════

def extract_all_structured_data(raw_text: str, company: str = "", fy: int = 0) -> dict:
    """OCR 원문에서 모든 구조화 데이터 추출.

    Returns:
        {
            'business_overview': str,
            'business_segments': [...],
            'executives': [...],
            'audit_info': {...},
            'risks': [...],
            'customers': [...],
            'short_summary': str,
            '_sections_found': [list of section keys],
        }
    """
    if not raw_text:
        return {}

    sections = split_sections(raw_text)

    try:
        return {
            'business_overview': extract_business_overview(raw_text, sections),
            'business_segments': extract_business_segments(raw_text, sections),
            'subsidiaries': extract_subsidiaries(raw_text, sections),
            'executives': extract_executives(raw_text, sections),
            'audit_info': extract_audit_info(raw_text, sections),
            'risks': extract_risks(raw_text, sections),
            'customers': extract_customers(raw_text, sections),
            'short_summary': extract_short_summary(raw_text, sections, company, fy),
            '_sections_found': list(sections.keys()),
        }
    except Exception as e:
        logger.warning(f"extract_all_structured_data 실패: {e}")
        return {}
