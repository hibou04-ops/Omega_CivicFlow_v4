"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Text Preprocessor (Phase 3)
구조화 전처리 엔진 (Structural Preprocessing Engine)

A. 표 구조 복원 (Table Structure Reconstruction)
B. 섹션 자동 태깅 (Section Auto Tagging)
C. 숫자 정규화 (Numeric Normalization)
═══════════════════════════════════════════════════════
"""

import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 데이터 구조 정의
# ═══════════════════════════════════════════════════════

SECTION_TYPES = {
    "재무상태표": ["재무상태표", "연결재무상태표", "별도재무상태표", "대차대조표"],
    "손익계산서": ["손익계산서", "연결손익계산서", "별도손익계산서", "포괄손익계산서",
                 "연결포괄손익계산서", "별도포괄손익계산서"],
    "현금흐름표": ["현금흐름표", "연결현금흐름표", "별도현금흐름표"],
    "자본변동표": ["자본변동표", "연결자본변동표", "별도자본변동표"],
    "주석": ["주석", "재무제표에 대한 주석", "주석사항"],
    "감사보고서": ["감사보고서", "감사의견", "독립된 감사인의 감사보고서",
                 "감사인의 감사보고서"],
    "사업개요": ["사업의 내용", "사업의 개요", "회사의 개요", "회사 개요"],
    "위험관리": ["위험관리", "리스크 관리", "금융위험관리", "재무위험관리",
               "신용위험", "시장위험", "유동성위험"],
    "배당": ["배당에 관한 사항", "배당", "주당배당금"],
    "주주": ["주주에 관한 사항", "최대주주", "주주총회"],
}

FINANCIAL_UNITS = {
    "천원": 1_000,
    "백만원": 1_000_000,
    "억원": 100_000_000,
    "원": 1,
    "천주": 1_000,
    "주": 1,
}


@dataclass
class DocumentBlock:
    """구조화된 문서 블록"""
    block_type: str  # "heading", "paragraph", "table", "unknown"
    section: str     # 섹션 이름 (재무상태표, 손익계산서 등)
    page_num: int
    text: str
    table_md: str = ""        # 마크다운 테이블 (table 타입일 때)
    unit: str = ""            # 감지된 단위 (천원, 백만원 등)
    period: str = ""          # 감지된 기간 (당기, 전기 등)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════
# B. 섹션 자동 태깅
# ═══════════════════════════════════════════════════════

class SectionTagger:
    """
    한국 재무/사업보고서 섹션 자동 분류기
    텍스트 라인에서 섹션 헤더를 감지하고 태그를 부여
    """

    def __init__(self):
        # 섹션 키워드를 정규식 패턴으로 컴파일
        self._patterns: List[Tuple[str, re.Pattern]] = []
        for section_name, keywords in SECTION_TYPES.items():
            for kw in keywords:
                # 공백과 특수문자를 유연하게 매칭
                flexible_kw = re.sub(r'\s+', r'\\s*', kw)
                pattern = re.compile(
                    rf'^\s*(?:[\d.]+\s*)?{flexible_kw}\s*$',
                    re.IGNORECASE
                )
                self._patterns.append((section_name, pattern))

    def detect_section(self, line: str) -> Optional[str]:
        """
        한 줄의 텍스트가 섹션 헤더인지 판별
        Returns: 섹션 이름 또는 None
        """
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) > 50:
            return None

        for section_name, pattern in self._patterns:
            if pattern.match(line_stripped):
                return section_name

        return None

    def tag_pages(self, pages_text: List[Tuple[int, str]]) -> List[DocumentBlock]:
        """
        페이지별 텍스트를 섹션 단위로 태깅
        Input: [(page_num, text), ...]
        Output: [DocumentBlock, ...]
        """
        blocks: List[DocumentBlock] = []
        current_section = "일반"

        for page_num, page_text in pages_text:
            lines = page_text.split('\n')
            current_block_lines: List[str] = []

            for line in lines:
                detected = self.detect_section(line)
                if detected:
                    # 이전 블록 저장
                    if current_block_lines:
                        block_text = '\n'.join(current_block_lines).strip()
                        if block_text:
                            blocks.append(DocumentBlock(
                                block_type="paragraph",
                                section=current_section,
                                page_num=page_num,
                                text=block_text,
                            ))
                        current_block_lines = []

                    current_section = detected
                    blocks.append(DocumentBlock(
                        block_type="heading",
                        section=current_section,
                        page_num=page_num,
                        text=line.strip(),
                    ))
                else:
                    current_block_lines.append(line)

            # 페이지 끝 잔여 블록 저장
            if current_block_lines:
                block_text = '\n'.join(current_block_lines).strip()
                if block_text:
                    blocks.append(DocumentBlock(
                        block_type="paragraph",
                        section=current_section,
                        page_num=page_num,
                        text=block_text,
                    ))

        logger.info(
            f"  ├─ 섹션 태깅 완료 — {len(blocks)} 블록, "
            f"섹션: {set(b.section for b in blocks)}"
        )
        return blocks


# ═══════════════════════════════════════════════════════
# A. 표 구조 복원
# ═══════════════════════════════════════════════════════

class TableParser:
    """
    텍스트 라인 기반 재무제표 표 구조 복원기
    PyMuPDF native text에서 표 후보 영역을 탐지하고 마크다운 테이블로 변환
    """

    # 숫자 패턴: 1,234,567 또는 (1,234) 또는 - 또는 빈 값
    NUMBER_PATTERN = re.compile(
        r'[\(\-]?[\d,]+(?:\.\d+)?[\)]?|[-–—]'
    )

    # 계정명 패턴: 한글 시작, 공백 후 숫자 열이 따라오는 구조
    TABLE_ROW_PATTERN = re.compile(
        r'^(\s*[가-힣\w\s\(\)·]+?)\s{2,}([\d,\(\)\-–—\s]+)$'
    )

    def detect_and_convert_tables(self, blocks: List[DocumentBlock]) -> List[DocumentBlock]:
        """
        DocumentBlock 리스트에서 표 후보를 탐지하고 마크다운 테이블로 변환
        표가 검출되면 block_type을 "table"로 변경하고 table_md를 채움
        """
        result: List[DocumentBlock] = []

        for block in blocks:
            if block.block_type == "heading":
                result.append(block)
                continue

            # 재무제표 섹션의 paragraph만 표 탐지 시도
            financial_sections = {"재무상태표", "손익계산서", "현금흐름표", "자본변동표"}
            if block.section not in financial_sections:
                result.append(block)
                continue

            # 표 자동 탐지 시도
            table_md, unit, period = self._try_parse_table(block.text)

            if table_md:
                block.block_type = "table"
                block.table_md = table_md
                block.unit = unit
                block.period = period
                result.append(block)
            else:
                result.append(block)

        table_count = sum(1 for b in result if b.block_type == "table")
        if table_count > 0:
            logger.info(f"  ├─ 표 구조 복원 — {table_count}개 표 발견")

        return result

    def _try_parse_table(self, text: str) -> Tuple[str, str, str]:
        """
        텍스트 블록에서 표를 탐지하고 마크다운으로 변환
        Returns: (markdown_table, detected_unit, detected_period)
                 표가 아니면 ("", "", "")
        """
        lines = text.split('\n')
        if len(lines) < 3:
            return ("", "", "")

        # 단위 탐지
        unit = self._detect_unit(text)
        period = self._detect_period(text)

        # 표 행 후보 수집
        table_rows: List[Tuple[str, List[str]]] = []
        header_line = ""

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # 단위 행 건너뛰기
            if any(u in stripped for u in ["단위:", "(단위", "단위 :"]):
                continue

            # 숫자 열을 포함하는 행 탐지
            row = self._parse_table_row(stripped)
            if row:
                account_name, values = row
                table_rows.append((account_name, values))
            elif self._is_header_line(stripped):
                header_line = stripped

        # 최소 3개 행이 있어야 표로 인정
        if len(table_rows) < 3:
            return ("", "", "")

        # 열 수 결정 (최빈 열 수)
        col_counts = [len(vals) for _, vals in table_rows]
        if not col_counts:
            return ("", "", "")
        most_common_cols = max(set(col_counts), key=col_counts.count)

        # 헤더 구성
        headers = self._build_headers(header_line, most_common_cols, period)

        # 마크다운 테이블 생성
        md_lines = []
        md_lines.append("| " + " | ".join(headers) + " |")
        md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        for account, values in table_rows:
            # 열 수 맞추기 (부족하면 빈 값)
            padded = values + [""] * (most_common_cols - len(values))
            padded = padded[:most_common_cols]
            row_str = "| " + account + " | " + " | ".join(padded) + " |"
            md_lines.append(row_str)

        unit_str = f"(단위: {unit})" if unit else ""
        md = unit_str + "\n" + "\n".join(md_lines) if unit_str else "\n".join(md_lines)

        return (md, unit, period)

    def _parse_table_row(self, line: str) -> Optional[Tuple[str, List[str]]]:
        """
        한 줄에서 계정명과 숫자 열을 분리
        Returns: (계정명, [숫자값1, 숫자값2, ...]) 또는 None
        """
        # 전략: 2개 이상 공백으로 구분된 토큰 중 숫자 패턴을 찾음
        tokens = re.split(r'\s{2,}', line.strip())
        if len(tokens) < 2:
            return None

        # 마지막에서부터 숫자 토큰 찾기
        values = []
        account_parts = []
        found_number = False

        for i, token in enumerate(reversed(tokens)):
            token_clean = token.strip()
            if self.NUMBER_PATTERN.fullmatch(token_clean) and token_clean:
                values.insert(0, token_clean)
                found_number = True
            else:
                # 숫자를 찾은 후 비숫자가 나오면 계정명으로 간주
                if found_number:
                    account_parts = tokens[:len(tokens) - i]
                    break
                elif i == len(tokens) - 1:
                    account_parts = [tokens[0]]

        if not found_number or not account_parts:
            return None

        account_name = " ".join(account_parts).strip()

        # 계정명이 너무 짧거나 숫자만이면 무시
        if len(account_name) < 2 or account_name.replace(" ", "").isdigit():
            return None

        return (account_name, values)

    def _is_header_line(self, line: str) -> bool:
        """헤더 행인지 판별 (당기/전기/주석 등 포함)"""
        header_keywords = ["당기", "전기", "전전기", "당반기", "전반기",
                          "제.*기", "금액", "주석"]
        return any(re.search(kw, line) for kw in header_keywords)

    def _build_headers(self, header_line: str, col_count: int, period: str) -> List[str]:
        """표 헤더 구성"""
        headers = ["계정과목"]

        if header_line:
            # 헤더 라인에서 열 이름 추출
            tokens = re.split(r'\s{2,}', header_line.strip())
            for t in tokens:
                if any(kw in t for kw in ["당기", "전기", "금액", "기말", "기초"]):
                    headers.append(t.strip())

        # 부족한 헤더 보충
        default_headers = ["당기", "전기", "전전기", "주석"]
        while len(headers) < col_count + 1:
            idx = len(headers) - 1
            if idx < len(default_headers):
                headers.append(default_headers[idx])
            else:
                headers.append(f"열{idx+1}")

        return headers[:col_count + 1]

    def _detect_unit(self, text: str) -> str:
        """텍스트에서 단위 탐지"""
        for unit_name in FINANCIAL_UNITS:
            if re.search(rf'단위\s*[:：]?\s*{unit_name}', text):
                return unit_name
            if re.search(rf'\(\s*{unit_name}\s*\)', text):
                return unit_name
        return ""

    def _detect_period(self, text: str) -> str:
        """텍스트에서 기간 정보 탐지"""
        period_match = re.search(r'제\s*(\d+)\s*기', text)
        if period_match:
            return f"제{period_match.group(1)}기"
        return ""


# ═══════════════════════════════════════════════════════
# C. 숫자 정규화
# ═══════════════════════════════════════════════════════

class NumericNormalizer:
    """
    재무 수치 정규화 엔진
    괄호 음수, 콤마, 단위 변환 등을 처리
    """

    @staticmethod
    def normalize_number(raw: str) -> Optional[float]:
        """
        문자열을 정규화된 숫자로 변환
        (1,234) → -1234.0 / 1,234,567 → 1234567.0 / - → None
        """
        if not raw:
            return None

        s = raw.strip()

        # '-' 또는 '–' 만 있으면 None (데이터 없음)
        if s in ['-', '–', '—', '']:
            return None

        # 괄호 음수 처리: (1,234) → -1234
        is_negative = False
        if s.startswith('(') and s.endswith(')'):
            is_negative = True
            s = s[1:-1]
        elif s.startswith('-') or s.startswith('△') or s.startswith('▲'):
            is_negative = True
            s = s[1:]

        # 콤마 제거
        s = s.replace(',', '')

        # 숫자 변환
        try:
            value = float(s)
            return -value if is_negative else value
        except ValueError:
            return None

    @staticmethod
    def apply_unit(value: float, unit: str) -> float:
        """단위를 적용하여 원 단위로 변환"""
        multiplier = FINANCIAL_UNITS.get(unit, 1)
        return value * multiplier

    @staticmethod
    def format_korean(value: float) -> str:
        """
        숫자를 한국어 읽기 좋은 형태로 포맷
        134155456609 → "1,341억 5,546만원"
        """
        abs_val = abs(value)
        sign = "-" if value < 0 else ""

        if abs_val >= 1_0000_0000:
            eok = abs_val / 1_0000_0000
            if eok == int(eok):
                return f"{sign}{int(eok):,}억원"
            return f"{sign}{eok:,.1f}억원"
        elif abs_val >= 1_0000:
            man = abs_val / 1_0000
            if man == int(man):
                return f"{sign}{int(man):,}만원"
            return f"{sign}{man:,.1f}만원"
        else:
            return f"{sign}{int(abs_val):,}원"

    def normalize_text_numbers(self, text: str, unit: str = "") -> str:
        """
        텍스트 내 숫자를 정규화 (원본 보존 + 정규화 주석 추가)
        "(1,234)" → "(1,234)[-1,234천원]" 형태
        주의: 원문을 파괴하지 않고 정보를 추가만 함
        """
        if not unit:
            return text

        def _replace_number(match):
            raw = match.group(0)
            normalized = self.normalize_number(raw)
            if normalized is not None:
                applied = self.apply_unit(normalized, unit)
                formatted = self.format_korean(applied)
                return f"{raw}[={formatted}]"
            return raw

        # 숫자 패턴: (1,234) 또는 1,234,567 또는 1,234.56
        pattern = r'\([\d,]+(?:\.\d+)?\)|[\d,]+(?:\.\d+)?'
        return re.sub(pattern, _replace_number, text)


# ═══════════════════════════════════════════════════════
# 통합 전처리기
# ═══════════════════════════════════════════════════════

class TextPreprocessor:
    """
    Phase 3 통합 전처리 엔진
    OCR 추출 텍스트 → 구조화된 LLM 입력 텍스트

    파이프라인: 섹션 태깅 → 표 구조 복원 → 숫자 정규화 → LLM용 포맷팅
    """

    def __init__(self):
        self.section_tagger = SectionTagger()
        self.table_parser = TableParser()
        self.normalizer = NumericNormalizer()

    def preprocess(self, pages_text: List[Tuple[int, str]]) -> str:
        """
        전체 전처리 파이프라인 실행
        Input: [(page_num, cleaned_text), ...]
        Output: LLM에 제공할 구조화된 텍스트

        1. 섹션 자동 태깅
        2. 표 구조 복원
        3. LLM용 구조화 텍스트 포맷팅
        """
        if not pages_text:
            return ""

        # 1. 섹션 태깅
        blocks = self.section_tagger.tag_pages(pages_text)

        # 2. 표 구조 복원
        blocks = self.table_parser.detect_and_convert_tables(blocks)

        # 3. LLM용 포맷팅
        formatted = self._format_for_llm(blocks)

        logger.info(
            f"  ├─ 전처리 완료 — "
            f"{len(pages_text)} 페이지 → {len(blocks)} 블록 → "
            f"{len(formatted)}자 구조화 텍스트"
        )

        return formatted

    def _format_for_llm(self, blocks: List[DocumentBlock]) -> str:
        """
        DocumentBlock 리스트를 LLM 입력용 구조화 텍스트로 변환
        섹션 태그 + 표 마크다운 포함
        """
        parts: List[str] = []
        current_section = ""

        for block in blocks:
            # 섹션 변경 시 구분자 삽입
            if block.section != current_section:
                current_section = block.section
                parts.append(f"\n[섹션: {current_section}]")

            if block.block_type == "heading":
                parts.append(f"\n### {block.text}")

            elif block.block_type == "table" and block.table_md:
                parts.append(block.table_md)

            elif block.block_type == "paragraph":
                text = block.text.strip()
                if text:
                    parts.append(text)

        return "\n".join(parts)

    def get_section_summary(self, pages_text: List[Tuple[int, str]]) -> Dict[str, List[str]]:
        """
        각 섹션에 포함된 핵심 텍스트 요약 반환 (디버깅/모니터링용)
        """
        blocks = self.section_tagger.tag_pages(pages_text)
        summary: Dict[str, List[str]] = {}

        for block in blocks:
            if block.section not in summary:
                summary[block.section] = []
            preview = block.text[:100] + "..." if len(block.text) > 100 else block.text
            summary[block.section].append(preview)

        return summary


# 싱글턴 인스턴스
text_preprocessor = TextPreprocessor()
