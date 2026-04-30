"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Text Quality Analyzer
OCR 텍스트 품질 검증 및 readability score 측정

- 깨진 한글(자모 분리) 감지
- 페이지별 readability score 계산
- 품질 기반 텍스트 태깅 ([OCR 품질 낮음])
- 요약문 post-processing (깨진 문자열 정제)
═══════════════════════════════════════════════════════
"""

import re
import logging
from typing import List, Tuple, Dict

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 한글 자모 범위 (유니코드)
# ═══════════════════════════════════════════════════════
# 초성: ㄱ-ㅎ (0x3131-0x314E)
# 중성: ㅏ-ㅣ (0x314F-0x3163)
# 종성 + 기타: (0x3164-0x318E)
_JAMO_PATTERN = re.compile(r'[\u3131-\u318E]')
_COMPLETE_HANGUL = re.compile(r'[\uAC00-\uD7A3]')

# 적어도 한 줄에 하나 있어야 할 "의미 있는" 문자
_MEANINGFUL_CHAR = re.compile(r'[\uAC00-\uD7A3a-zA-Z0-9]')

# OCR 깨짐 시 자주 나타나는 무의미 패턴
_GARBAGE_PATTERNS = [
    re.compile(r'[\u3131-\u318E]{3,}'),          # 자모 3개 이상 연속
    re.compile(r'[^\w\s\uAC00-\uD7A3]{5,}'),     # 특수문자 5개 이상 연속
    re.compile(r'(.)\1{4,}'),                      # 같은 문자 5회 이상 반복
    re.compile(r'[\ufffd\ufffe\uffff]'),           # 유니코드 대체 문자
]


def compute_readability_score(text: str) -> float:
    """
    텍스트의 가독성 점수를 0.0~1.0으로 측정.

    측정 기준:
    1. 완성형 한글 비율 (높을수록 좋음)
    2. 자모 분리 비율 (낮을수록 좋음)
    3. 특수문자 과다 비율 (낮을수록 좋음)
    4. 가비지 패턴 발견 횟수 (적을수록 좋음)
    5. 평균 줄 길이 적정성 (너무 짧거나 길면 감점)
    """
    if not text or len(text.strip()) < 10:
        return 0.0

    total_chars = len(text)
    non_space = sum(1 for c in text if not c.isspace())
    if non_space == 0:
        return 0.0

    # 1. 완성형 한글 비율
    complete_hangul = len(_COMPLETE_HANGUL.findall(text))
    hangul_ratio = complete_hangul / non_space

    # 2. 자모 분리 비율 (감점 요소)
    jamo_count = len(_JAMO_PATTERN.findall(text))
    jamo_penalty = min(jamo_count / max(non_space, 1), 1.0)

    # 3. 특수문자 비율 (감점 요소)
    special = sum(1 for c in text if not c.isalnum() and not c.isspace()
                  and '\uAC00' <= c <= '\uD7A3' is False)
    special_ratio = special / non_space

    # 4. 가비지 패턴 횟수
    garbage_hits = sum(len(p.findall(text)) for p in _GARBAGE_PATTERNS)
    garbage_penalty = min(garbage_hits * 0.1, 0.5)

    # 5. 줄 분석
    lines = [l for l in text.split('\n') if l.strip()]
    meaningful_lines = sum(1 for l in lines if _MEANINGFUL_CHAR.search(l))
    line_quality = meaningful_lines / max(len(lines), 1)

    # 종합 점수 계산
    score = (
        hangul_ratio * 0.3 +
        (1.0 - jamo_penalty) * 0.2 +
        (1.0 - min(special_ratio, 1.0)) * 0.15 +
        (1.0 - garbage_penalty) * 0.15 +
        line_quality * 0.2
    )

    return max(0.0, min(1.0, score))


def clean_broken_korean(text: str) -> str:
    """
    깨진 한글 자모 분리 정제.
    - 연속 자모를 가능한 한 완성형으로 복원
    - 복원 불가능한 자모 연속은 제거
    - OCR 가비지 패턴 제거
    """
    if not text:
        return ""

    result = text

    # 1. 연속 자모 3개 이상 → 제거 (복원 불가)
    result = re.sub(r'[\u3131-\u318E]{3,}', '', result)

    # 2. 유니코드 대체 문자 제거
    result = re.sub(r'[\ufffd\ufffe\uffff]', '', result)

    # 3. 같은 문자 5회 이상 반복 → 1개로
    result = re.sub(r'(.)\1{4,}', r'\1', result)

    # 4. 의미 없는 단일 자모 (한글 사이가 아닌 곳의 자모 제거)
    # 예: "사석 ㅇ엣속을" → "사석 엣속을"
    result = re.sub(r'(?<![가-힣])[ㄱ-ㅎㅏ-ㅣ](?![가-힣])', '', result)

    # 5. 빈 줄 정리
    result = re.sub(r'\n{3,}', '\n\n', result)

    return result.strip()


def tag_text_by_quality(
    pages: List[Dict],
    quality_threshold: float = 0.6,
) -> Tuple[str, List[Dict]]:
    """
    페이지별 readability score를 측정하고,
    품질 기반 태그를 붙인 full_text를 생성.

    Args:
        pages: [{"page_number": int, "text": str, "confidence": float}, ...]
        quality_threshold: 이 점수 미만이면 [OCR 품질 낮음] 태그

    Returns:
        (tagged_full_text, enriched_pages)
    """
    tagged_parts = []
    enriched_pages = []

    for page in pages:
        page_num = page.get("page_number", 0)
        text = page.get("text", "")
        ocr_confidence = page.get("confidence", 1.0)

        if not text or not text.strip():
            enriched_pages.append({**page, "readability": 0.0, "quality_tag": "empty"})
            continue

        # 1. 깨진 한글 정제
        cleaned = clean_broken_korean(text)

        # 2. 품질 점수 측정
        readability = compute_readability_score(cleaned)

        # 3. OCR 신뢰도와 결합 (가중 평균)
        combined_score = readability * 0.6 + ocr_confidence * 0.4

        # 4. 태그 결정
        if combined_score < 0.3:
            quality_tag = "very_low"
            # 너무 낮으면 LLM에 전달하지 않음
            logger.info(
                f"  ├─ 페이지 {page_num} 제외 "
                f"(품질: {combined_score:.0%})"
            )
        elif combined_score < quality_threshold:
            quality_tag = "low"
            tagged_parts.append(
                f"\n[페이지 {page_num} — OCR 품질 낮음, 참고용]\n{cleaned}\n"
            )
        else:
            quality_tag = "good"
            tagged_parts.append(f"\n[페이지 {page_num}]\n{cleaned}\n")

        enriched_pages.append({
            **page,
            "text": cleaned,
            "readability": round(combined_score, 3),
            "quality_tag": quality_tag,
        })

    tagged_full_text = "\n".join(tagged_parts)
    return tagged_full_text, enriched_pages


# ── LLM markdown asterisk 마커 정리 ──
_BOLD_ASTERISK_RE = re.compile(r"\*\*([^*\n]+?)\*\*")
_ITALIC_ASTERISK_RE = re.compile(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])")
_LIST_ASTERISK_RE = re.compile(r"^(\s*)\*\s+", re.MULTILINE)
_RESIDUAL_ASTERISK_RE = re.compile(r"\*+")


def strip_markdown_asterisks(text: str) -> str:
    """LLM이 생성한 markdown asterisk 마커(**bold**, *italic*, * list)를 제거.
    내용은 보존, 마커만 제거. 리스트 마커는 • 으로 치환.
    챗봇 응답·PDF 리포트·요약문 등 사용자 노출 직전에 호출.
    """
    if not text:
        return text
    text = _BOLD_ASTERISK_RE.sub(r"\1", text)
    text = _ITALIC_ASTERISK_RE.sub(r"\1", text)
    text = _LIST_ASTERISK_RE.sub(r"\1• ", text)
    text = _RESIDUAL_ASTERISK_RE.sub("", text)
    return text


# ═══════════════════════════════════════════════════════
# 자본시장법 준수 — 무인가 투자자문 어구 deterministic 정제
# ═══════════════════════════════════════════════════════
# 본 시스템은 투자자문업 인가가 없으므로 직접 매수/매도 권유 어구는
# 자본시장법 제18조 위반 (무인가 영업) 형사처벌 대상이 될 수 있다.
# Layer 1 (생성)에서 LLM 프롬프트로 예방하고, Layer 2 (이 함수)에서
# deterministic regex로 잔존 어구를 catch한다.
# 내용/문맥은 보존하면서 advisory 어조만 observational 어조로 치환.
# ═══════════════════════════════════════════════════════

_LEGAL_ADVISORY_REPLACEMENTS = [
    # 등급/추천 어구 (Strong Buy / Buy / Hold / Reduce 패턴)
    (re.compile(r"강력\s*매수\s*\(?\s*Strong\s*Buy\s*\)?", re.IGNORECASE), "구조적 강세 신호 다수 관찰"),
    (re.compile(r"\(?\s*Strong\s*Buy\s*\)?", re.IGNORECASE), "구조적 강세 신호"),
    (re.compile(r"\(?\s*Buy\s*\)?", re.IGNORECASE), "데이터 시그널"),
    (re.compile(r"\(?\s*Hold\s*\)?", re.IGNORECASE), "추가 데이터 필요"),
    (re.compile(r"\(?\s*Reduce\s*\)?", re.IGNORECASE), "노출 축소 시나리오"),
    # 직접 매수/매도 권유
    (re.compile(r"매수\s*(?:추천|권유|권장|권고)"), "데이터 신호 관찰"),
    (re.compile(r"매도\s*(?:추천|권유|권장|권고)"), "구조적 약세 신호 관찰"),
    (re.compile(r"분할\s*매수"), "단계적 노출 형성"),
    (re.compile(r"분할\s*매도"), "단계적 노출 축소"),
    # 비중/포지션 조정 어구
    (re.compile(r"비중\s*확대"), "노출 증대 시나리오"),
    (re.compile(r"비중\s*축소"), "노출 축소 시나리오"),
    (re.compile(r"비중\s*유지"), "현 노출 유지 시나리오"),
    (re.compile(r"포지션\s*구축"), "관찰 시나리오 형성"),
    (re.compile(r"포지션\s*청산"), "관찰 시나리오 종료"),
    (re.compile(r"포지션\s*확대"), "관찰 시나리오 강화"),
    (re.compile(r"포지션\s*축소"), "관찰 시나리오 약화"),
    # 매매 타이밍
    (re.compile(r"매수\s*타이밍"), "진입 시점 관찰"),
    (re.compile(r"매도\s*타이밍"), "종료 시점 관찰"),
    (re.compile(r"이익\s*실현"), "관찰 시나리오 종료"),
    # 자산배분 어구
    (re.compile(r"(?:전체\s*)?투자\s*예정\s*금액"), "관찰 대상 금액"),
    (re.compile(r"(?:매력적인|좋은)\s*(?:진입|매수)\s*(?:구간|시점)"), "구조적 관찰점"),
    (re.compile(r"적극적으로\s*확대"), "단계적으로 증대"),
    # 직접 매매 동사 (단어 경계 — 분석 어구 보호)
    (re.compile(r"(?<![\w가-힣])사세요(?![\w가-힣])"), "관찰해보세요"),
    (re.compile(r"(?<![\w가-힣])파세요(?![\w가-힣])"), "재검토해보세요"),
    (re.compile(r"매수하시기\s*바랍니다"), "관찰 대상으로 추가하실 수 있습니다"),
    (re.compile(r"매도하시기\s*바랍니다"), "관찰 시나리오를 종료하실 수 있습니다"),
]

LEGAL_DISCLAIMER = (
    "\n\n※ 본 분석은 공시 데이터에 기반한 구조적·관찰적 분류이며, "
    "자본시장법상 투자권유·투자자문에 해당하지 않습니다. "
    "본 시스템은 투자자문업 인가를 보유하지 않으며, "
    "투자 결정은 자격 있는 투자자문사 또는 금융기관과 상의하여 "
    "본인 책임 하에 내려주시기 바랍니다."
)


def strip_legal_advisory(text: str, append_disclaimer: bool = False) -> str:
    """LLM이 생성한 무인가 투자자문 어구를 deterministic하게 정제.

    Layer 2 안전망 (Layer 1 = 프롬프트 instruction).
    Args:
        text: 정제 대상
        append_disclaimer: True면 끝에 법적 disclaimer 자동 추가
    Returns:
        advisory 어구가 observational 어구로 치환된 텍스트
    """
    if not text:
        return text
    result = text
    for pattern, replacement in _LEGAL_ADVISORY_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    if append_disclaimer and "투자권유" not in result:
        result = result.rstrip() + LEGAL_DISCLAIMER
    return result


def sanitize_summary_text(summary: str) -> str:
    """
    LLM이 생성한 요약문에서 깨진 OCR 잔해 및 LLM 메타 텍스트를 정리.
    Post-processing 검증. markdown asterisk 마커도 함께 제거.
    """
    if not summary:
        return ""

    # ── 0a. markdown asterisk 마커 우선 제거 ──
    result = strip_markdown_asterisks(summary)
    if result is None:
        result = summary

    # 0. LLM 지시문 누출 문장 제거
    _INSTRUCTION_LEAK_PATTERNS = [
        r'JSON\s*형식으로\s*(구성|출력|변환|생성)',
        r'템플릿을?\s*기반으로',
        r'다음은\s*문서\s*내용을?\s*기반으로\s*생성된',
        r'다음은.*JSON\s*데이터',
        r'귀하의\s*요구\s*사항',
        r'아래[는와]\s*(요약|분석|결과)',
        r'요청하신\s*(대로|바와)',
        r'제공된\s*(문서|정보|데이터)를?\s*(분석|처리)',
        r'추출하여\s*JSON',
        r'JSON\s*(데이터|형식|구조)입니다',
        r'다음과\s*같[은이].*JSON',
        r'```',
    ]
    sentences = re.split(r'(?<=[.다니요])\s*', result)
    clean_sentences = []
    for sent in sentences:
        skip = False
        for pat in _INSTRUCTION_LEAK_PATTERNS:
            if re.search(pat, sent, re.IGNORECASE):
                skip = True
                break
        if not skip:
            clean_sentences.append(sent)
    result = " ".join(clean_sentences).strip()

    # 0b. JSON 잔재 줄 제거 ( { } [ ] "key": 등)
    lines = result.split('\n')
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped in ('{', '}', '[', ']', '{}', '[]'):
            continue
        if re.match(r'^"[a-z_]+":\s*', stripped, re.IGNORECASE):
            continue
        clean_lines.append(line)
    result = '\n'.join(clean_lines).strip()

    # 0c. 중국어 비율 감지 — 경고만 (내용이 중요할 수 있으므로 제거하지 않음)
    cn_sentences = re.split(r'(?<=[.。!?\n])\s*', result)
    for s in cn_sentences:
        cjk = sum(1 for c in s if '\u4e00' <= c <= '\u9fff')
        total = len(s.replace(" ", ""))
        if total > 0 and (cjk / total) > 0.2:
            logger.warning(f"⚠ 중국어 비율 높은 문장 감지 (제거하지 않음): {s[:60]}...")

    # 1. 자모 제거
    result = re.sub(r'[\u3131-\u318E]+', '', result)

    # 2. 유니코드 대체 문자 제거
    result = re.sub(r'[\ufffd\ufffe\uffff]', '', result)

    # 3. 깨진 문자열 패턴 제거 (특수문자 3개 이상 연속)
    result = re.sub(r'[^\w\s\uAC00-\uD7A3,.()%\-:;]{3,}', '', result)

    # 4. 반복 문자 정리
    result = re.sub(r'(.)\1{3,}', r'\1', result)

    # 5. 다중 공백 정리
    result = re.sub(r' {2,}', ' ', result)
    result = re.sub(r'\n{3,}', '\n\n', result)

    return result.strip()

