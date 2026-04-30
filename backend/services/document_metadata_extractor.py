"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Document Metadata Extractor
메타데이터 전처리 엔진 (Pre-LLM Metadata Extraction)

파이프라인:
  OCR 텍스트 → 라인 정제 → 섹션 제목 추출
  → 회사명 후보 추출 → 스코어링 → 메타데이터 확정
  → LLM에 immutable 변수로 주입

핵심 원칙: LLM이 회사명/섹션을 구분하는 것이 아니라,
전처리기가 먼저 구분한 뒤 LLM에는 확정된 값만 주입.
═══════════════════════════════════════════════════════
"""

import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 데이터 구조
# ═══════════════════════════════════════════════════════

@dataclass
class CompanyCandidate:
    """회사명 후보 — 점수 + 근거"""
    name: str
    score: int
    line_index: int
    source_line: str
    match_type: str  # "label", "pattern", "suffix"


@dataclass
class ExtractedMetadata:
    """전처리에서 확정된 메타데이터"""
    company_name: Optional[str] = None
    company_confidence: float = 0.0
    sections: List[Dict[str, Any]] = field(default_factory=list)
    document_type_hint: str = ""
    candidates_debug: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "company_name": self.company_name or "미확인",
            "company_confidence": self.company_confidence,
            "sections": self.sections,
            "document_type_hint": self.document_type_hint,
        }


# ═══════════════════════════════════════════════════════
# A. 섹션 제목 패턴 — 회사명에서 반드시 제외
# ═══════════════════════════════════════════════════════

SECTION_PATTERNS = [
    re.compile(r"^\d+\.\s*.+"),                          # 1. 일반사항
    re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.\s*.+"),              # Ⅰ. 회사의 개요
    re.compile(r"^[IVXLC]+\.\s*.+"),                     # I. General
    re.compile(r"^[가-하]\.\s*.+"),                       # 가. 나. 다.
    re.compile(r"^목\s*차\s*$"),                          # 목차
    re.compile(r"^주\s*석\s*$"),                          # 주석
    re.compile(r"^재\s*무\s*제\s*표\s*$"),                  # 재무제표
    re.compile(r"^감\s*사\s*보\s*고\s*서\s*$"),              # 감사보고서
    re.compile(r"^사\s*업\s*보\s*고\s*서\s*$"),              # 사업보고서
    re.compile(r"^반\s*기\s*보\s*고\s*서\s*$"),              # 반기보고서
    re.compile(r"^분\s*기\s*보\s*고\s*서\s*$"),              # 분기보고서
    re.compile(r"^연\s*결\s*재\s*무\s*제\s*표\s*$"),          # 연결재무제표
    re.compile(r"^별\s*도\s*재\s*무\s*제\s*표\s*$"),          # 별도재무제표
    re.compile(r"^재무상태표\s*$"),
    re.compile(r"^손익계산서\s*$"),
    re.compile(r"^포괄손익계산서\s*$"),
    re.compile(r"^현금흐름표\s*$"),
    re.compile(r"^자본변동표\s*$"),
    re.compile(r"^이사의\s*경영진단\s*"),
    re.compile(r"^독립된\s*감사인"),
    re.compile(r"^\[?첨부\]?\s*"),
    re.compile(r"^【.+】\s*$"),                           # 【주요사항】
]

# 섹션 제목에 흔히 등장하는 키워드 (회사명에서 감점용)
NEGATIVE_KEYWORDS = [
    "일반사항", "목차", "주석", "재무제표", "감사보고서",
    "사업보고서", "반기보고서", "분기보고서", "위험관리",
    "연결재무제표", "별도재무제표", "요약", "개요", "현황",
    "사업의 내용", "재무에 관한", "회사의 개요",
    "이사의 경영진단", "감사인의", "배당에 관한",
    "주주에 관한", "임원 및 직원", "그 밖에",
    "기타 참고사항", "전문가의 확인", "대표이사 등의 확인",
    "손익계산서", "현금흐름표", "자본변동표", "포괄손익계산서",
    "재무상태표",
]


# ═══════════════════════════════════════════════════════
# B. 회사명 추출 패턴
# ═══════════════════════════════════════════════════════

# 레이블 기반 추출 (최고 신뢰도) — "회사명: XXX" 형태
COMPANY_LABEL_PATTERNS = [
    (re.compile(r'회사명\s*[:：]\s*(.+?)(?:\s{2,}|\n|$)'), 10),
    (re.compile(r'법인명\s*[:：]\s*(.+?)(?:\s{2,}|\n|$)'), 10),
    (re.compile(r'상호\s*[:：]\s*(.+?)(?:\s{2,}|\n|$)'), 9),
    (re.compile(r'상호명\s*[:：]\s*(.+?)(?:\s{2,}|\n|$)'), 9),
    (re.compile(r'발행회사\s*[:：]\s*(.+?)(?:\s{2,}|\n|$)'), 8),
    (re.compile(r'제출인\s*[:：]\s*(.+?)(?:\s{2,}|\n|$)'), 8),
    (re.compile(r'신고인\s*[:：]\s*(.+?)(?:\s{2,}|\n|$)'), 7),
    (re.compile(r'발행인\s*[:：]\s*(.+?)(?:\s{2,}|\n|$)'), 7),
    (re.compile(r'회사의\s*명칭\s*[:：]\s*(.+?)(?:\s{2,}|\n|$)'), 9),
]

# 패턴 기반 추출 — 라인에서 회사명 구조 감지
COMPANY_STRUCT_PATTERNS = [
    re.compile(r'주식회사\s+[가-힣A-Za-z0-9&()\.\-\s]+'),
    re.compile(r'[가-힣A-Za-z0-9&()\.\-\s]+\s*주식회사'),
    re.compile(r'\(주\)\s*[가-힣A-Za-z0-9&()\.\-\s]+'),
    re.compile(r'[가-힣A-Za-z0-9&()\.\-\s]+㈜'),
]

# 법인 접미사 키워드 (가산점)
CORP_SUFFIX_TOKENS = ["주식회사", "(주)", "㈜"]


# ═══════════════════════════════════════════════════════
# 핵심 함수들
# ═══════════════════════════════════════════════════════

def normalize_lines(text: str) -> List[str]:
    """
    OCR 텍스트를 라인 단위로 분해 + 정규화.
    빈 줄 제거, 다중 공백 축소.
    """
    lines = []
    for line in text.splitlines():
        s = " ".join(line.strip().split())
        if s:
            lines.append(s)
    return lines


def is_section_title(line: str) -> bool:
    """
    이 줄이 섹션 제목인지 판별.
    섹션 제목은 회사명 후보에서 반드시 제외됨.
    """
    stripped = line.strip()
    if not stripped:
        return False
    return any(p.match(stripped) for p in SECTION_PATTERNS)


def looks_like_company_name(line: str) -> bool:
    """
    이 줄이 회사명일 가능성이 있는지 판별.
    섹션 제목이면 즉시 False.
    네거티브 키워드 포함 시 False.
    """
    if is_section_title(line):
        return False
    if any(kw in line for kw in NEGATIVE_KEYWORDS):
        return False
    return any(p.search(line) for p in COMPANY_STRUCT_PATTERNS)


def score_company_candidate(line: str, line_index: int) -> int:
    """
    회사명 후보 라인을 점수화.
    높은 점수 = 회사명일 확률이 높음.

    가점:
      - "주식회사", "(주)", "㈜" 포함: +5
      - 문서 앞부분 (line < 80): +3
      - 적정 길이 (3~40자): +2

    감점:
      - 섹션 제목: -10
      - 네거티브 키워드: -8
      - 번호 접두사 (1. 2.): -4
      - 길이 초과 (>80): -2
    """
    score = 0

    # 법인 키워드 포함 가점
    if any(token in line for token in CORP_SUFFIX_TOKENS):
        score += 5

    # 문서 앞부분 가점
    if line_index < 80:
        score += 3

    # 적정 길이 가점
    if 3 <= len(line) <= 40:
        score += 2
    elif len(line) > 80:
        score -= 2

    # 섹션 제목 강한 감점
    if is_section_title(line):
        score -= 10

    # 네거티브 키워드 감점
    if any(kw in line for kw in NEGATIVE_KEYWORDS):
        score -= 8

    # 번호 접두사 감점
    if re.match(r"^\d+\.\s*", line):
        score -= 4

    return score


def extract_company_name_from_labels(text: str) -> Optional[CompanyCandidate]:
    """
    레이블 기반 회사명 추출.
    "회사명: XXX", "법인명: XXX" 등의 형태에서 추출.
    가장 높은 신뢰도를 가지는 방법.
    """
    head_text = text[:5000]  # 상단 영역만 탐색

    best: Optional[CompanyCandidate] = None

    for pattern, base_score in COMPANY_LABEL_PATTERNS:
        match = pattern.search(head_text)
        if not match:
            continue

        raw = match.group(1).strip()[:50]

        # 빈 값, 숫자만, 섹션 제목 필터
        if not raw or raw.isdigit():
            continue
        if is_section_title(raw):
            continue
        if any(kw in raw for kw in NEGATIVE_KEYWORDS):
            continue

        # 한글 포함 필수
        if not re.search(r'[가-힣]', raw):
            continue

        candidate = CompanyCandidate(
            name=raw,
            score=base_score + 5,  # 레이블 기반은 높은 기본 점수
            line_index=0,
            source_line=match.group(0).strip(),
            match_type="label",
        )

        if best is None or candidate.score > best.score:
            best = candidate

    return best


def extract_company_name_from_lines(text: str) -> Optional[CompanyCandidate]:
    """
    라인 단위 스캐닝으로 회사명 후보를 추출하고 최고점 선택.
    """
    lines = normalize_lines(text[:10000])  # 앞부분 우선 탐색
    candidates: List[CompanyCandidate] = []

    for idx, line in enumerate(lines):
        if not looks_like_company_name(line):
            continue

        score = score_company_candidate(line, idx)

        # 실제 회사명 부분만 추출 (줄 전체가 아닌 매칭 부분)
        extracted_name = _extract_name_from_line(line)
        if not extracted_name:
            continue

        candidates.append(CompanyCandidate(
            name=extracted_name,
            score=score,
            line_index=idx,
            source_line=line,
            match_type="pattern",
        ))

    if not candidates:
        return None

    # 최고점 선택
    candidates.sort(key=lambda c: c.score, reverse=True)
    best = candidates[0]

    # 최소 점수 미달 시 None
    if best.score < 3:
        return None

    return best


def _extract_name_from_line(line: str) -> Optional[str]:
    """
    라인에서 회사명 부분만 추출.
    "주식회사 동국생명과학" → "주식회사 동국생명과학"
    "(주)동국생명과학" → "(주)동국생명과학"
    """
    for pattern in COMPANY_STRUCT_PATTERNS:
        match = pattern.search(line)
        if match:
            name = match.group(0).strip()
            # 길이 제한
            if 2 <= len(name) <= 50:
                return name
    return None


def extract_sections(text: str) -> List[Dict[str, Any]]:
    """
    문서에서 섹션 제목 목록을 추출.
    LLM에 문서 구조 정보로 전달.
    """
    lines = normalize_lines(text)
    sections = []

    for idx, line in enumerate(lines):
        if is_section_title(line):
            sections.append({
                "title": line,
                "line_index": idx,
            })

    return sections


def detect_document_type_hint(text: str) -> str:
    """
    텍스트 앞부분에서 문서 유형 힌트를 추출.
    """
    head = text[:3000].lower() if text else ""

    type_keywords = {
        "사업보고서": ["사업보고서"],
        "반기보고서": ["반기보고서"],
        "분기보고서": ["분기보고서"],
        "감사보고서": ["감사보고서", "감사의견"],
        "정정신고(보고)": ["정정신고", "정정 전", "정정 후"],
        "주요사항보고서": ["주요사항보고서", "주요경영사항"],
        "유상증자결정": ["유상증자", "신주발행", "제3자배정"],
    }

    scores = {}
    for doc_type, keywords in type_keywords.items():
        score = sum(1 for kw in keywords if kw in head)
        if score > 0:
            scores[doc_type] = score

    if not scores:
        return ""

    return max(scores, key=scores.get)


# ═══════════════════════════════════════════════════════
# 통합 추출 함수
# ═══════════════════════════════════════════════════════

def extract_document_metadata(text: str) -> ExtractedMetadata:
    """
    OCR 텍스트에서 메타데이터를 전처리 단계에서 확정.

    파이프라인:
      1. 라인 정제
      2. 레이블 기반 회사명 추출 (최우선)
      3. 라인 스캐닝 기반 회사명 추출 (fallback)
      4. 섹션 제목 추출
      5. 문서 유형 힌트 추출
      6. 확정된 메타데이터 반환

    Returns:
        ExtractedMetadata with confirmed company name,
        sections list, and document type hint.
    """
    result = ExtractedMetadata()

    if not text or len(text.strip()) < 10:
        return result

    # ── 1. 레이블 기반 추출 (최우선) ──
    label_candidate = extract_company_name_from_labels(text)

    # ── 2. 라인 스캐닝 기반 추출 ──
    line_candidate = extract_company_name_from_lines(text)

    # ── 3. 최종 선택 ──
    # 레이블 기반이 있으면 우선, 없으면 라인 기반 사용
    chosen = None
    if label_candidate and label_candidate.score >= 5:
        chosen = label_candidate
        result.company_confidence = 0.9
    elif line_candidate and line_candidate.score >= 5:
        chosen = line_candidate
        result.company_confidence = 0.7
    elif label_candidate:
        chosen = label_candidate
        result.company_confidence = 0.6
    elif line_candidate:
        chosen = line_candidate
        result.company_confidence = 0.5

    if chosen:
        # metadata_validator의 검증 함수 재사용
        from services.metadata_validator import metadata_validator
        validated = metadata_validator._validate_company_name(chosen.name)
        if validated != "미확인":
            result.company_name = validated
        else:
            result.company_name = None
            result.company_confidence = 0.0

    # ── 4. 섹션 제목 추출 ──
    result.sections = extract_sections(text)

    # ── 5. 문서 유형 힌트 ──
    result.document_type_hint = detect_document_type_hint(text)

    # ── 6. 디버그용 후보 목록 ──
    debug_candidates = []
    if label_candidate:
        debug_candidates.append({
            "name": label_candidate.name,
            "score": label_candidate.score,
            "type": "label",
            "source": label_candidate.source_line[:80],
        })
    if line_candidate:
        debug_candidates.append({
            "name": line_candidate.name,
            "score": line_candidate.score,
            "type": "pattern",
            "line_index": line_candidate.line_index,
            "source": line_candidate.source_line[:80],
        })
    result.candidates_debug = debug_candidates

    logger.info(
        f"  ├─ 메타데이터 전처리 완료 — "
        f"회사: {result.company_name or '미확인'} "
        f"(conf: {result.company_confidence:.0%}), "
        f"섹션: {len(result.sections)}개, "
        f"문서유형 힌트: {result.document_type_hint or '없음'}"
    )

    return result


# ═══════════════════════════════════════════════════════
# 유틸리티: LLM 프롬프트용 메타데이터 블록 생성
# ═══════════════════════════════════════════════════════

def build_metadata_prompt_block(metadata: ExtractedMetadata) -> str:
    """
    전처리에서 확정된 메타데이터를 LLM 프롬프트에 주입할
    immutable 블록으로 포맷팅.
    """
    company = metadata.company_name or "미확인"
    sections_str = ", ".join(
        s["title"] for s in metadata.sections[:10]
    ) if metadata.sections else "없음"

    return (
        f"[IMMUTABLE METADATA — 전처리 확정 값, 수정 금지]\n"
        f"company_name = {company}\n"
        f"document_type_hint = {metadata.document_type_hint or '미확인'}\n"
        f"\n"
        f"[DOCUMENT SECTIONS — 이것은 섹션 제목이며 회사명이 아님]\n"
        f"{sections_str}\n"
        f"\n"
        f"[STRICT RULES]\n"
        f"1. 위 company_name을 그대로 사용하세요.\n"
        f"2. 섹션 제목(1. 일반사항, 목차, 주석 등)을 회사명으로 사용하지 마세요.\n"
        f"3. 확정 메타데이터와 다른 값을 생성하지 마세요.\n"
    )
