"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Metadata Validator & Anchor Linker
메타데이터 앵커 링킹 시스템

모든 메타데이터 필드를 원문 앵커와 연결하고,
검증을 거친 SafeRenderContext만 렌더링에 사용.

파이프라인: 후보 추출 → 검증 → 채택 → safe context 생성
═══════════════════════════════════════════════════════
"""

import re
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 데이터 구조
# ═══════════════════════════════════════════════════════

@dataclass
class AnchoredField:
    """앵커 기반 메타데이터 필드 — 값 + 근거 + 신뢰도"""
    value: str = "미확인"
    source_text: str = ""        # 원문에서 추출한 근거 문장
    source_page: int = 0         # 근거가 발견된 페이지
    confidence: float = 0.0      # 0.0 ~ 1.0
    validation_pass: bool = False
    fallback_used: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_confirmed(self) -> bool:
        return self.validation_pass and self.confidence >= 0.5


@dataclass
class SafeRenderContext:
    """렌더링에 사용할 검증 완료 메타데이터"""
    company_name: AnchoredField = field(default_factory=AnchoredField)
    filing_title: AnchoredField = field(default_factory=AnchoredField)
    document_type: AnchoredField = field(default_factory=AnchoredField)
    category: AnchoredField = field(default_factory=AnchoredField)
    event_type: AnchoredField = field(default_factory=AnchoredField)
    filing_date: AnchoredField = field(default_factory=AnchoredField)

    # 렌더링 전용 — 검증 통과 값 또는 fallback
    safe_company_name: str = "미확인"
    safe_filing_title: str = "미확인"
    safe_category: str = "기타"
    safe_document_type: str = "기타공시"
    safe_event_type: str = ""
    safe_subject_for_summary: str = "해당 공시는"

    def to_dict(self) -> dict:
        return {
            "company_name": self.company_name.to_dict(),
            "filing_title": self.filing_title.to_dict(),
            "document_type": self.document_type.to_dict(),
            "category": self.category.to_dict(),
            "event_type": self.event_type.to_dict(),
            "filing_date": self.filing_date.to_dict(),
            "safe_company_name": self.safe_company_name,
            "safe_filing_title": self.safe_filing_title,
            "safe_category": self.safe_category,
            "safe_document_type": self.safe_document_type,
            "safe_event_type": self.safe_event_type,
            "safe_subject_for_summary": self.safe_subject_for_summary,
        }


# ═══════════════════════════════════════════════════════
# 블랙리스트 / 화이트리스트 패턴
# ═══════════════════════════════════════════════════════

# 메타데이터 필드에 절대 허용하지 않는 패턴
_UNIVERSAL_BLACKLIST = [
    re.compile(r'^[\d,\.\s]+$'),                     # 순수 숫자
    re.compile(r'^\d{8,14}$'),                        # 접수번호/문서번호
    re.compile(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}'),   # 날짜
    re.compile(r'_rendered|\.pdf|\.txt|doc_id|tmp',
               re.IGNORECASE),                        # 시스템 문자열
    re.compile(r'^page_?\d+', re.IGNORECASE),         # 페이지 번호
]

# 회사명 전용 블랙리스트
_COMPANY_BLACKLIST = [
    re.compile(r'^[\d,]+(?:\s*주)?$'),                # 주식수
    re.compile(r'^[\d,]+(?:\s*원)?$'),                # 금액
    re.compile(r'\d{4}년'),                           # 날짜 (2026년)
    re.compile(r'^(주요사항보고서|유상증자결정|사업보고서|감사보고서|'
               r'정정신고|재무제표|현금흐름표|손익계산서|재무상태표|'
               r'재무제표에 대한|포괄손익계산서|자본변동표|'
               r'기타공시|주석)'),                     # 문서유형/문장파편
    re.compile(r'^\d+$'),                             # 순수 숫자
]



# 유효한 카테고리 enum
VALID_CATEGORIES = {
    "유상증자결정", "정정신고(보고)", "주요사항보고서",
    "사업보고서", "반기보고서", "분기보고서",
    "재무제표", "감사보고서", "주석", "기타공시",
    # vlm_service에서 사용하는 추가 카테고리
    "무상증자", "전환사채", "신주인수권부사채",
    "자기주식", "합병", "분할", "감자",
}


# ═══════════════════════════════════════════════════════
# MetadataValidator 클래스
# ═══════════════════════════════════════════════════════

class MetadataValidator:
    """
    메타데이터 앵커 링킹 시스템.
    후보 추출 → 검증 → 채택 → SafeRenderContext 생성
    """

    # ── 회사명 추출 패턴 (우선순위순) ──
    _COMPANY_PATTERNS = [
        (r'회사명\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)', 1.0),
        (r'법인명\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)', 1.0),
        (r'상호\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)', 0.95),
        (r'상호명\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)', 0.95),
        (r'발행회사\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)', 0.9),
        (r'제출인\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)', 0.9),
        (r'신고인\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)', 0.85),
        (r'발행인\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)', 0.85),
        (r'회사의\s*명칭\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)', 0.95),
        (r'주식회사\s+(.+?)(?:\s*[\(\[]|\s{2,}|\n|$)', 0.8),
        (r'㈜\s*(.+?)(?:\s{2,}|\n|$)', 0.8),
        (r'\(주\)\s*(.+?)(?:\s{2,}|\n|$)', 0.8),
    ]

    # ── 공시명 추출 패턴 ──
    _FILING_TITLE_PATTERNS = [
        (r'(정정신고서?\s*\(.+?\))', 0.95),
        (r'(주요사항보고서\s*\(.+?\))', 0.95),
        (r'(사업보고서\s*\(.+?\))', 0.9),
        (r'(감사보고서)', 0.9),
        (r'(반기보고서)', 0.9),
        (r'(분기보고서)', 0.9),
    ]

    # ── 날짜 추출 패턴 ──
    _DATE_PATTERNS = [
        (r'제출일\s*[:\s]\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', 1.0),
        (r'접수일\s*[:\s]\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', 0.9),
        (r'기준일\s*[:\s]\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', 0.85),
    ]

    def extract_anchored_metadata(
        self,
        full_text: str,
        pages: Optional[List[Tuple[int, str]]] = None,
    ) -> Dict[str, AnchoredField]:
        """
        원문에서 앵커 기반 메타데이터 추출.
        각 필드에 source_text, source_page, confidence를 부여.

        NOTE: document_metadata_extractor는 llm_service에서 별도 호출됨.
        여기서는 기존 패턴 기반 추출만 수행하여 순환 호출 방지.
        """
        # 페이지 정보가 없으면 전체 텍스트를 1페이지로 취급
        if not pages:
            pages = [(1, full_text)]

        # 상단 텍스트 (메타 블록 우선 탐색 영역)
        head_text = full_text[:3000]

        result = {}

        # 1. 회사명 (기존 앵커 패턴 기반)
        result["company_name"] = self._extract_field(
            head_text, pages, self._COMPANY_PATTERNS,
            validator=self._validate_company_name
        )

        # 2. 공시명
        result["filing_title"] = self._extract_field(
            head_text, pages, self._FILING_TITLE_PATTERNS,
            validator=self._validate_filing_title
        )

        # 3. 제출일
        result["filing_date"] = self._extract_field(
            head_text, pages, self._DATE_PATTERNS,
            validator=self._validate_date
        )

        return result

    def _extract_field(
        self,
        text: str,
        pages: List[Tuple[int, str]],
        patterns: List[Tuple[str, float]],
        validator=None,
    ) -> AnchoredField:
        """단일 필드에 대해 패턴 기반 후보 추출 + 검증"""
        best: Optional[AnchoredField] = None

        for pattern_str, base_confidence in patterns:
            match = re.search(pattern_str, text)
            if not match:
                continue

            raw_value = match.group(1).strip()[:100]
            source_text = match.group(0).strip()[:200]

            # 소스 페이지 찾기
            source_page = self._find_source_page(source_text, pages)

            # 검증
            validated_value = raw_value
            validation_pass = True
            if validator:
                validated_value = validator(raw_value)
                validation_pass = (validated_value != "미확인")

            if not validation_pass:
                continue

            candidate = AnchoredField(
                value=validated_value,
                source_text=source_text,
                source_page=source_page,
                confidence=base_confidence,
                validation_pass=True,
                fallback_used=False,
            )

            # 가장 높은 신뢰도 후보 채택
            if best is None or candidate.confidence > best.confidence:
                best = candidate

        if best and best.validation_pass:
            return best

        # 후보 없음 → fallback
        return AnchoredField(
            value="미확인",
            confidence=0.0,
            validation_pass=False,
            fallback_used=True,
        )

    def _find_source_page(self, source_text: str, pages: List[Tuple[int, str]]) -> int:
        """source_text가 어느 페이지에 있는지 찾기"""
        # 짧은 키워드로 검색
        search_key = source_text[:50]
        for page_num, page_text in pages:
            if search_key in page_text:
                return page_num
        return 1  # 기본값

    # ═══════════════════════════════════════════════════════
    # 필드별 Validator
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _validate_company_name(candidate: str) -> str:
        """회사명 검증 — 문장 파편 및 OCR 깨짐 한글 차단"""
        if not candidate or not candidate.strip():
            return "미확인"

        name = candidate.strip()
        name = re.sub(r'\s+', ' ', name)
        name = name.strip('.,;:!?[]{}"\'')

        if not name or name in ("미확인", "정보 없음"):
            return "미확인"

        # 공통 블랙리스트
        for pattern in _UNIVERSAL_BLACKLIST:
            if pattern.search(name):
                return "미확인"

        # 회사명 전용 블랙리스트
        for pattern in _COMPANY_BLACKLIST:
            if pattern.search(name):
                return "미확인"

        # ── 한국어 문장 어미/조사 감지 (문장 파편 차단) ──
        _SENTENCE_ENDINGS = [
            "세요", "습니다", "합니다", "입니다", "됩니다",
            "니다", "하세요", "드립니다", "겠습니다",
            "시오", "십시오", "하여", "으로", "에서",
            "하는", "있는", "없는", "이며", "으며",
            "였다", "했다", "된다", "한다", "는데",
            "지만", "에게", "부터", "까지", "대한",
            "안세요", "을세요", "의세요",
        ]
        for ending in _SENTENCE_ENDINGS:
            if name.endswith(ending):
                logger.debug(f"회사명 거부 (문장 어미 감지): '{name}'")
                return "미확인"

        # ── OCR 깨짐 한글 감지 (음절 조합 자연스러움 검증) ──
        # 공백으로 분리된 단어가 3개 이상이고, 어느 단어도 알려진 법인 키워드가 아니면 의심
        words = name.split()
        if len(words) >= 3:
            _CORP_KEYWORDS = [
                "주식회사", "㈜", "(주)", "회사", "법인", "증권", "은행",
                "보험", "투자", "건설", "전자", "제약", "바이오",
                "에너지", "솔루션", "홀딩스", "그룹", "코리아",
            ]
            has_corp_keyword = any(kw in name for kw in _CORP_KEYWORDS)
            if not has_corp_keyword:
                # readability 점수로 OCR 깨짐 검증
                from services.text_quality import compute_readability_score
                score = compute_readability_score(name)
                if score < 0.4:
                    logger.debug(f"회사명 거부 (OCR 깨짐 의심, score={score:.2f}): '{name}'")
                    return "미확인"

        # 숫자 비율 검증
        digits = sum(1 for c in name if c.isdigit())
        total = sum(1 for c in name if not c.isspace())
        if total > 0 and (digits / total) > 0.5:
            return "미확인"

        # 한글/영문 포함 검증
        if not re.search(r'[가-힣a-zA-Z]', name):
            return "미확인"

        # 콜론(:) 포함 시 거부 (주소/대표이사 오염 패턴)
        if ':' in name or '：' in name:
            return "미확인"

        # 주소 키워드 포함 시 거부
        _ADDR_KEYWORDS = ['구 ', '동 ', '로 ', '길 ', '번지', '층', '호']
        for kw in _ADDR_KEYWORDS:
            if kw in name:
                return "미확인"

        # 대표이사/본점소재지 오염 차단
        _CONTAMINATION = [
            re.compile(r'대\s*표\s*이\s*사'),
            re.compile(r'본\s*점\s*소\s*재\s*지'),
            re.compile(r'등\s*기\s*번\s*호'),
            re.compile(r'사업자\s*등록'),
            re.compile(r'서울|경기|부산|인천|대구|광주|대전|울산|세종|강원|충청|전라|경상|제주'),
        ]
        for pat in _CONTAMINATION:
            if pat.search(name):
                return "미확인"

        # 길이 제한 (실제 법인명은 대부분 20자 이내)
        if len(name) < 2 or len(name) > 30:
            return "미확인"

        # 쉼표 제거 후 순수 숫자 재검증
        if name.replace(',', '').replace(' ', '').isdigit():
            return "미확인"

        return name

    @staticmethod
    def _validate_filing_title(candidate: str) -> str:
        """공시명/보고서명 검증 — OCR 깨짐 및 LLM 환각 차단"""
        if not candidate or not candidate.strip():
            return "미확인"

        title = candidate.strip()[:100]

        # 공통 블랙리스트
        for pattern in _UNIVERSAL_BLACKLIST:
            if pattern.search(title):
                return "미확인"

        # 한글 포함 필수
        if not re.search(r'[가-힣]', title):
            return "미확인"

        if len(title) < 3:
            return "미확인"

        # DART 공시명에 반드시 포함되어야 할 키워드 중 하나
        _FILING_KEYWORDS = [
            "보고서", "신고서", "공시", "결정", "변경",
            "증자", "감자", "합병", "분할", "취득",
            "처분", "의결권", "거래", "정정",
            "주총", "이사회", "소송", "계약", "투자",
            "배당", "감사", "선임", "해임", "사임",
            "공개매수", "자기주식", "전환", "교환",
        ]
        has_keyword = any(kw in title for kw in _FILING_KEYWORDS)
        if not has_keyword:
            logger.debug(f"공시명 거부 (DART 키워드 없음): '{title}'")
            return "미확인"

        return title

    @staticmethod
    def _validate_date(candidate: str) -> str:
        """날짜 검증"""
        if not candidate:
            return "미확인"
        # YYYY-MM-DD 또는 YYYY.MM.DD 형식 확인
        if re.match(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$', candidate.strip()):
            return candidate.strip()
        return "미확인"

    @staticmethod
    def validate_category(candidate: str) -> str:
        """카테고리를 유효한 enum에 매핑"""
        if not candidate:
            return "기타"
        candidate = candidate.strip()
        if candidate in VALID_CATEGORIES:
            return candidate
        # 부분 매칭 시도
        for cat in VALID_CATEGORIES:
            if cat in candidate or candidate in cat:
                return cat
        return candidate if len(candidate) < 20 else "기타"

    # ═══════════════════════════════════════════════════════
    # SafeRenderContext 생성
    # ═══════════════════════════════════════════════════════

    def build_safe_render_context(
        self,
        anchored: Dict[str, AnchoredField],
        doc_type: str = "기타공시",
        doc_secondary: str = "",
        category: str = "기타",
        event_type: str = "",
        llm_company: str = "",
        llm_filing_title: str = "",
    ) -> SafeRenderContext:
        """
        추출된 앵커 메타데이터 + LLM 결과를 합쳐
        렌더링 전용 SafeRenderContext를 생성.
        """
        ctx = SafeRenderContext()

        # ── 회사명 ──
        company_field = anchored.get("company_name", AnchoredField())
        if company_field.is_confirmed:
            ctx.company_name = company_field
            ctx.safe_company_name = company_field.value
        elif llm_company:
            validated = self._validate_company_name(llm_company)
            if validated != "미확인":
                ctx.company_name = AnchoredField(
                    value=validated, confidence=0.5,
                    validation_pass=True, fallback_used=False,
                    source_text="LLM 추출",
                )
                ctx.safe_company_name = validated
            else:
                ctx.safe_company_name = "미확인"
                ctx.company_name = AnchoredField(fallback_used=True)
        else:
            ctx.safe_company_name = "미확인"
            ctx.company_name = AnchoredField(fallback_used=True)

        # ── 공시명 ──
        filing_field = anchored.get("filing_title", AnchoredField())
        if filing_field.is_confirmed:
            ctx.filing_title = filing_field
            ctx.safe_filing_title = filing_field.value
        elif llm_filing_title:
            validated = self._validate_filing_title(llm_filing_title)
            if validated != "미확인":
                ctx.filing_title = AnchoredField(
                    value=validated, confidence=0.4,
                    validation_pass=True, fallback_used=False,
                    source_text="LLM 추출",
                )
                ctx.safe_filing_title = validated

        # ── 카테고리/문서유형 ──
        safe_cat = self.validate_category(category)
        ctx.safe_category = safe_cat
        ctx.category = AnchoredField(
            value=safe_cat, confidence=0.8,
            validation_pass=True,
        )

        ctx.safe_document_type = doc_type
        ctx.document_type = AnchoredField(
            value=doc_type, confidence=0.8,
            validation_pass=True,
        )

        # ── 이벤트 유형 ──
        if event_type:
            ctx.safe_event_type = event_type
            ctx.event_type = AnchoredField(
                value=event_type, confidence=0.7,
                validation_pass=True,
            )

        # ── 제출일 ──
        date_field = anchored.get("filing_date", AnchoredField())
        if date_field.is_confirmed:
            ctx.filing_date = date_field

        # ── summary 주어 결정 ──
        if ctx.safe_company_name != "미확인":
            ctx.safe_subject_for_summary = ctx.safe_company_name + "은(는)"
        else:
            ctx.safe_subject_for_summary = "해당 공시는"

        logger.info(
            f"  ├─ SafeRenderContext 생성 — "
            f"회사: {ctx.safe_company_name} "
            f"(conf: {ctx.company_name.confidence:.1%}), "
            f"유형: {ctx.safe_document_type}"
        )

        return ctx


# 싱글턴
metadata_validator = MetadataValidator()
