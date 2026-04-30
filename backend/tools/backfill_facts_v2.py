"""
FinancialFact Deep Backfill — summary 텍스트에서 재무 수치 정규식 추출
기존 backfill_facts.py의 financial_metrics 컬럼 파싱에 더해,
summary/evidence 텍스트에서 '매출액 XX억원' 패턴을 추가 추출.
"""
import sys, re, json, hashlib, logging
sys.path.insert(0, '.')

from database import SessionLocal
from models.models import AnalysisResult, DocumentMetadata, FinancialFact
from sqlalchemy import text, func

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)

# ── 메트릭 패턴 (정규식) ──
# "매출액: 12조원", "매출액 약 1,234억원", "영업이익: -500억원" 등
METRIC_PATTERNS = [
    # label: value 형태
    (r'매출액\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'revenue'),
    (r'매출\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'revenue'),
    (r'영업이익\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'operating_profit'),
    (r'영업손실\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'operating_profit'),
    (r'당기순이익\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'net_income'),
    (r'당기순손실\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'net_income'),
    (r'순이익\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'net_income'),
    (r'자산총계\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'total_assets'),
    (r'총자산\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'total_assets'),
    (r'부채총계\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'total_liabilities'),
    (r'총부채\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'total_liabilities'),
    (r'자본총계\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'equity'),
    (r'총자본\s*[:：]?\s*약?\s*([\-△▲]?\s*[\d,\.]+\s*(?:조|억|만|천)?(?:원)?)', 'equity'),
]


def parse_value(val_str: str):
    """'12.04조원' → 12040000000000.0"""
    if not val_str:
        return None
    val_str = val_str.strip().replace(",", "").replace(" ", "")
    
    negative = False
    if val_str.startswith(("-", "△", "▲")):
        negative = True
        val_str = val_str.lstrip("-△▲ ")
    
    multiplier = 1.0
    if "조" in val_str:
        val_str = val_str.replace("조", "").replace("원", "").strip()
        multiplier = 1e12
    elif "억" in val_str:
        val_str = val_str.replace("억", "").replace("원", "").strip()
        multiplier = 1e8
    elif "만" in val_str:
        val_str = val_str.replace("만", "").replace("원", "").strip()
        multiplier = 1e4
    elif "천" in val_str:
        val_str = val_str.replace("천", "").replace("원", "").strip()
        multiplier = 1e3
    else:
        val_str = val_str.replace("원", "").replace("%", "").strip()
    
    try:
        num = float(val_str) * multiplier
        if num == 0:
            return None
        return -num if negative else num
    except ValueError:
        return None


# ── Unit context patterns (DART 표 헤더 단위 선언) ──
# parse_value()는 값 문자열 자체에 포함된 조/억/만/천 만 인식하므로,
# "(단위: 백만원)" 같은 표 헤더 컨텍스트를 별도로 sniff한다.
_UNIT_CONTEXT_RE = re.compile(
    r'\(?\s*단위\s*[:：]\s*(조원?|억원?|백만원?|천원?|원)\s*\)?'
)
_UNIT_MULTIPLIER = {
    "조": 1e12, "조원": 1e12,
    "억": 1e8, "억원": 1e8,
    "백만": 1e6, "백만원": 1e6,
    "천": 1e3, "천원": 1e3,
    "원": 1.0,
}

# 값 문자열 자체에 명시적 단위가 있는지 확인 (있으면 parse_value가 이미 처리함)
_VALUE_INLINE_UNIT_RE = re.compile(r'(조|억|만|천|백만)')


def _detect_unit_context(text: str, label_pos: int, window_back: int = 800, window_fwd: int = 50) -> float:
    """
    Unit context detection with row-level priority.

    Priority order:
    1) Row-level: 같은 행(직전 \\n 또는 │로 끊어지는 작은 범위)에서 인라인 단위 마커
       (백만원/천원/억원/조원) 검색. DART 표가 한 행에 단위를 명시하는 경우 처리.
    2) Header sniff: label_pos 직전 window_back 자 안에서 가장 가까운 (단위: ...) 선언.
    3) 선언이 없으면 1.0.
    """
    # ── 1) Row-level scan ──
    # 같은 "행" 경계: 직전 \n 또는 직전 200자 시작점 중 더 가까운 위치부터
    row_start = max(0, label_pos - 200)
    nl = text.rfind("\n", row_start, label_pos)
    if nl >= 0:
        row_start = nl + 1
    # 행 끝: label_pos 이후 다음 \n까지 (단, 250자 max)
    row_end_search = min(len(text), label_pos + 250)
    nl_end = text.find("\n", label_pos, row_end_search)
    row_end = nl_end if nl_end >= 0 else row_end_search
    row_text = text[row_start:row_end]

    # 행 내 인라인 단위 마커 검출 (괄호 안 또는 직접)
    row_unit_re = re.compile(r'(?:\(|│|\s)\s*단위\s*[:：]?\s*(조원?|억원?|백만원?|천원?|원)|(?:백만원|천원|억원|조원)(?=[│\s\),])')
    row_match = row_unit_re.search(row_text)
    if row_match:
        token = row_match.group(1) if row_match.group(1) else row_match.group(0).strip("(│ )")
        mult = _UNIT_MULTIPLIER.get(token)
        if mult is not None:
            return mult

    # ── 2) Header sniff (label 앞쪽 window_back 자) ──
    start = max(0, label_pos - window_back)
    window_text = text[start:label_pos]
    rel_label_pos = label_pos - start

    best_dist = None
    best_mult = 1.0
    for m in _UNIT_CONTEXT_RE.finditer(window_text):
        unit_token = m.group(1)
        mult = _UNIT_MULTIPLIER.get(unit_token, 1.0)
        decl_pos = m.start()
        dist = rel_label_pos - decl_pos
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_mult = mult
    return best_mult


def _has_inline_unit(value_str: str) -> bool:
    """캡처된 값 문자열 자체가 조/억/만/천/백만 단위를 이미 포함하면 True."""
    return bool(_VALUE_INLINE_UNIT_RE.search(value_str))


# ── Table parser v2: cell-based (DART OCR │-separated structure) ──
# v1 (extract_metrics_from_text_table)는 char-window 휴리스틱 → 부분합/잘못된 행 침범 다수.
# v2는 │로 split해서 같은 행 같은 표 셀 단위로 정밀 추출.
_LABEL_TO_METRIC_CELL = {
    "매출액": "revenue",
    "매출": "revenue",
    "영업수익": "revenue",
    "영업수익(매출액)": "revenue",
    "수익(매출액)": "revenue",
    "(매출액)": "revenue",
    "영업이익": "operating_profit",
    "영업이익(손실)": "operating_profit",
    "영업손실": "operating_profit",
    "영업손실(이익)": "operating_profit",
    "당기순이익": "net_income",
    "당기순손실": "net_income",
    "연결총당기순이익": "net_income",
    "총당기순이익": "net_income",
    "당기순이익(손실)": "net_income",
    "당기순손실(이익)": "net_income",
    "자산총계": "total_assets",
    "부채총계": "total_liabilities",
    "자본총계": "equity",
    "지배기업소유주지분": "equity",
}

_LABEL_NUM_PREFIX_RE = re.compile(r'^([IVXivx]+\.|\d+\.|\d+\)|[가-힣]\.)\s*')
_NUMBER_ANNOT_RE = re.compile(r'\s*\((주|note|n)\.?\s*\d*\)\s*$|\s*\*\d+\s*$', re.IGNORECASE)


def _parse_cell_number(cell: str):
    """단일 셀이 숫자 (옵션 부호/괄호 음수/주석 제거)이면 float, 아니면 None."""
    if not cell:
        return None
    s = cell.strip()
    s = _NUMBER_ANNOT_RE.sub("", s)
    if not s:
        return None
    negative = False
    if s.startswith(("-", "△", "▲")):
        negative = True
        s = s[1:].lstrip()
    if s.startswith("(") and s.endswith(")") and len(s) >= 3:
        negative = True
        s = s[1:-1].strip()
    s = s.replace(",", "").replace(" ", "")
    if not s or not re.match(r"^\d+(?:\.\d+)?$", s):
        return None
    try:
        v = float(s)
        return -v if negative else v
    except ValueError:
        return None


def _is_label_cell(cell_clean: str):
    """셀 전체가 메트릭 라벨이면 metric_name 반환, 아니면 None."""
    if not cell_clean:
        return None
    # 번호 prefix 제거 (1. 매출액, II. 영업이익, 가. 자본총계 등)
    stripped = _LABEL_NUM_PREFIX_RE.sub("", cell_clean).strip()
    # exact match
    if stripped in _LABEL_TO_METRIC_CELL:
        return _LABEL_TO_METRIC_CELL[stripped]
    # 후행 (단위) (주1) 등 제거 후 재시도
    no_paren = re.sub(r"\s*\([^)]*\)\s*$", "", stripped).strip()
    if no_paren in _LABEL_TO_METRIC_CELL:
        return _LABEL_TO_METRIC_CELL[no_paren]
    return None


def extract_metrics_from_table_v2(text: str) -> list:
    """
    Cell-based DART table parser.

    Algorithm:
    1. Split text by │ into cells
    2. For each cell, check if it is a metric label
    3. If yes, scan FORWARD through subsequent cells:
       - skip empty cells
       - collect numeric cells until first non-numeric cell (table row boundary)
       - take FIRST numeric cell (DART convention: 당기/최신연도가 첫 컬럼)
    4. Apply unit context from nearest 단위 declaration in earlier cells
    5. Apply per-metric sanity range
    6. Cross-metric dedup (same value in two metrics → reject both)

    Returns list of {"metric_name": ..., "value": ...} dicts.
    """
    if not text:
        return []

    # DART OCR raw_text는 \n 으로 셀/행 구분 (한 셀 = 한 줄). │는 거의 사용 안 됨.
    cells = text.split("\n")

    # Pre-compute unit declaration cell positions
    cell_units: dict[int, float] = {}
    for idx, cell in enumerate(cells):
        m = re.search(r"단위\s*[:：]\s*(조원?|억원?|백만원?|천원?|원)", cell)
        if m:
            token = m.group(1)
            mult = _UNIT_MULTIPLIER.get(token)
            if mult is not None:
                cell_units[idx] = mult

    def nearest_unit_before(cell_idx: int, max_lookback: int = 300) -> float:
        """Find nearest unit declaration in cells [cell_idx - max_lookback, cell_idx)."""
        best_idx = -1
        for i in cell_units.keys():
            if i < cell_idx and (cell_idx - i) <= max_lookback:
                if i > best_idx:
                    best_idx = i
        return cell_units.get(best_idx, 1.0) if best_idx >= 0 else 1.0

    metric_sanity = {
        "revenue": (1e8, 5e14),
        "operating_profit": (1e7, 6e13),
        "net_income": (1e7, 6e13),
        "total_assets": (1e8, 1e15),
        "total_liabilities": (1e8, 1e15),
        "equity": (1e8, 1e15),
    }

    results = []
    seen_metrics = set()

    for idx, cell in enumerate(cells):
        cell_clean = cell.strip()
        if not cell_clean:
            continue

        metric_name = _is_label_cell(cell_clean)
        if not metric_name or metric_name in seen_metrics:
            continue

        # Scan forward for numeric cells
        numbers = []
        for j in range(idx + 1, min(idx + 10, len(cells))):
            next_clean = cells[j].strip()
            if not next_clean:
                continue
            v = _parse_cell_number(next_clean)
            if v is not None:
                numbers.append(v)
                if len(numbers) >= 5:
                    break
            else:
                # Non-numeric cell → table row boundary, stop
                break

        if not numbers:
            continue

        # First column = most recent year (DART convention)
        value = numbers[0]

        # Apply unit context
        unit_mult = nearest_unit_before(idx)
        if unit_mult != 1.0:
            value = value * unit_mult

        # Sanity range
        lo, hi = metric_sanity.get(metric_name, (1e8, 1e15))
        if not (lo <= abs(value) <= hi):
            continue

        results.append({"metric_name": metric_name, "value": value})
        seen_metrics.add(metric_name)

    # Cross-metric dedup
    value_groups: dict[int, list[str]] = {}
    for m in results:
        key = int(round(abs(m["value"])))
        value_groups.setdefault(key, []).append(m["metric_name"])
    bad_values = {k for k, names in value_groups.items() if len(names) > 1}

    cleaned = [m for m in results if int(round(abs(m["value"]))) not in bad_values]
    return cleaned


# ── Table-aware label patterns (DART OCR vertical-bar table form) ──
# DART raw_text는 "수익(매출액)│4,512,334,640│1,668,557,445│6,180,892,085" 같은
# 표 형식으로 변환되어 있어 기존 inline 패턴(METRIC_PATTERNS)으론 매칭 불가.
_LABEL_TO_METRIC = [
    (re.compile(r'수익\s*\(\s*매출액\s*\)'), 'revenue'),
    (re.compile(r'(?<![가-힣])매출액(?![가-힣])'), 'revenue'),
    (re.compile(r'(?<![가-힣])영업수익(?![가-힣])'), 'revenue'),
    (re.compile(r'영업이익(?:\s*\([^)]*\))?(?!률)'), 'operating_profit'),
    (re.compile(r'영업손실(?:\s*\([^)]*\))?'), 'operating_profit'),
    (re.compile(r'당기순이익(?:\s*\([^)]*\))?'), 'net_income'),
    (re.compile(r'당기순손실(?:\s*\([^)]*\))?'), 'net_income'),
    (re.compile(r'(?<![가-힣])순이익(?![가-힣률])'), 'net_income'),
    (re.compile(r'(?:자산총계|총자산)(?:\s*\([^)]*\))?'), 'total_assets'),
    (re.compile(r'(?:부채총계|총부채)(?:\s*\([^)]*\))?'), 'total_liabilities'),
    (re.compile(r'(?:자본총계|총자본)(?:\s*\([^)]*\))?'), 'equity'),
]

# 라벨 직후에 등장하는 숫자 컬럼 (separator: │ | 공백 ) 후 숫자
_AFTER_LABEL_NUMBER_RE = re.compile(
    r'[│|\s\)]+([\-△▲]?\s*[\d,]+(?:\.\d+)?(?:\s*(?:조|억|백만|만|천)?원?)?)'
)


def extract_metrics_from_text_table(text: str) -> list:
    """
    표 형식 텍스트에서 재무 수치 추출.
    DART OCR raw_text의 │ 구분 컬럼 구조 처리.

    각 라벨 다음 ~200자 내에서 최대 5개 숫자 컬럼을 캡처하고,
    그 중 절댓값이 가장 큰 값을 사용 (보통 합계 컬럼).
    Unit context sniffing은 라벨 위치 기준으로 적용.
    """
    if not text:
        return []
    results = []
    seen_metrics = set()
    for label_pat, metric_name in _LABEL_TO_METRIC:
        if metric_name in seen_metrics:
            continue
        for label_match in label_pat.finditer(text):
            label_pos = label_match.start()
            label_end = label_match.end()
            after_text = text[label_end:label_end + 200]

            # 라벨 직후 최대 5개 숫자 캡처
            number_matches = list(_AFTER_LABEL_NUMBER_RE.finditer(after_text))[:5]
            if not number_matches:
                continue

            # Unit context: label 위치 기준 sniff
            ctx_mult = _detect_unit_context(text, label_pos)

            values = []
            for nm in number_matches:
                raw = nm.group(1).strip()
                v = parse_value(raw)
                if v is None:
                    continue
                if not _has_inline_unit(raw) and ctx_mult != 1.0:
                    v = v * ctx_mult
                # 최소 임계: 1억원 (재무 표 항목은 보통 이 이상)
                if abs(v) < 1e8 and metric_name not in ('operating_margin', 'debt_ratio'):
                    continue
                values.append(v)

            if values:
                # 합계 컬럼은 보통 가장 큰 값 (절댓값 기준)
                best = max(values, key=lambda x: abs(x))
                # 메트릭별 sanity range (한국 상장사 실제 분포 기준):
                # - revenue: ~삼성전자 300조 → 상한 500조
                # - operating_profit/net_income: ~삼성전자 30조 → 상한 60조
                # - total_assets/total_liabilities/equity: ~신한지주 700조 → 상한 1000조
                metric_sanity = {
                    "revenue": (1e8, 5e14),
                    "operating_profit": (1e7, 6e13),
                    "net_income": (1e7, 6e13),
                    "total_assets": (1e8, 1e15),
                    "total_liabilities": (1e8, 1e15),
                    "equity": (1e8, 1e15),
                }
                lo, hi = metric_sanity.get(metric_name, (1e8, 1e15))
                if lo <= abs(best) <= hi:
                    results.append({"metric_name": metric_name, "value": best})
                    seen_metrics.add(metric_name)
                    break
            # else: try the next label match

    # ── Cross-metric dedup: 같은 값이 여러 메트릭에 나오면 표 파싱 오류 가능성 → 모두 drop ──
    value_groups: dict[int, list[str]] = {}
    for m in results:
        key = int(round(abs(m["value"])))
        value_groups.setdefault(key, []).append(m["metric_name"])
    bad_values = {k for k, names in value_groups.items() if len(names) > 1}

    # ── Cross-metric sanity: operating_profit > revenue * 0.6 → 둘 다 의심 → drop op ──
    rev_val = next((m["value"] for m in results if m["metric_name"] == "revenue"), None)
    op_val = next((m["value"] for m in results if m["metric_name"] == "operating_profit"), None)
    drop_metrics = set()
    if rev_val and op_val and abs(op_val) > abs(rev_val) * 0.6:
        drop_metrics.add("operating_profit")
    # net_income > revenue도 비슷
    ni_val = next((m["value"] for m in results if m["metric_name"] == "net_income"), None)
    if rev_val and ni_val and abs(ni_val) > abs(rev_val):
        drop_metrics.add("net_income")

    cleaned = [
        m for m in results
        if int(round(abs(m["value"]))) not in bad_values and m["metric_name"] not in drop_metrics
    ]

    # ── Cross-metric scale normalization (보수적) ──
    # revenue가 신뢰 범위 (1조~500조) 안에 있을 때만 anchor로 사용.
    # SPAC 같이 revenue가 비현실적(>500조)인 경우는 anchor 신뢰 못함 → skip.
    rev_value = next((m["value"] for m in cleaned if m["metric_name"] == "revenue"), None)
    if rev_value is not None and 1e12 <= abs(rev_value) <= 5e14:
        rev_scale = abs(rev_value)
        for m in cleaned:
            if m["metric_name"] == "revenue":
                continue
            v = abs(m["value"])
            if v == 0:
                continue
            ratio = rev_scale / v
            # 1e5 ~ 1e7 배 차이면 백만 단위 누락 가능성 → ×1e6
            # 변환 후 값이 anchor의 1/100 ~ 100배 사이일 때만 적용
            if 1e5 <= ratio <= 1e7:
                scaled = m["value"] * 1e6
                if 1e8 <= abs(scaled) <= 1e15 and rev_scale / 100 <= abs(scaled) <= rev_scale * 100:
                    m["value"] = scaled

    return cleaned


def extract_metrics_from_text(text: str) -> list:
    """텍스트에서 재무 수치 추출 (단위 컨텍스트 인식)"""
    if not text:
        return []
    results = []
    seen_metrics = set()
    for pattern, metric_name in METRIC_PATTERNS:
        matches = re.finditer(pattern, text)
        for match in matches:
            if metric_name in seen_metrics:
                continue  # 같은 메트릭은 첫 번째 매칭만
            raw_value_str = match.group(1)
            value = parse_value(raw_value_str)
            if value is None:
                continue

            # ── Unit context sniffing ──
            # 캡처값에 inline 단위(조/억/만/천/백만)가 없으면 주변 단위 선언 적용
            if not _has_inline_unit(raw_value_str):
                ctx_mult = _detect_unit_context(text, match.start())
                if ctx_mult != 1.0:
                    value = value * ctx_mult

            # 너무 작은 값 필터 (1만원 미만은 의미없음)
            if abs(value) < 10000 and metric_name not in ('operating_margin', 'debt_ratio'):
                continue
            results.append({"metric_name": metric_name, "value": value})
            seen_metrics.add(metric_name)
    return results


def make_fact_uid(doc_id, company, fy, metric, scope):
    raw = f"{doc_id}|{company}|{fy}|{metric}|{scope or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def main():
    db = SessionLocal()
    
    existing_uids = set(uid for (uid,) in db.query(FinancialFact.fact_uid).all())
    before_count = len(existing_uids)
    log.info(f"기존 팩트: {before_count}건")
    
    # 모든 analysis_results + metadata 조인
    rows = db.execute(text("""
        SELECT ar.document_id, ar.summary, ar.financial_metrics, ar.evidence,
               dm.company_name, dm.company_name_norm, dm.fiscal_year,
               dm.statement_scope, dm.corp_code
        FROM analysis_results ar
        JOIN document_metadata dm ON dm.document_id = ar.document_id
        WHERE dm.company_name_norm IS NOT NULL
          AND dm.company_name_norm != ''
          AND dm.company_name_norm != '미확인'
          AND dm.fiscal_year IS NOT NULL
    """)).fetchall()
    
    log.info(f"대상 문서: {len(rows)}건")
    
    new_facts = []
    stats = {"from_fm_col": 0, "from_summary": 0, "from_evidence": 0, "skipped": 0}
    
    for doc_id, summary, fm_text, evidence, company, company_norm, fy, scope, corp_code in rows:
        if not company_norm or not fy:
            stats["skipped"] += 1
            continue
        
        all_metrics = {}  # metric_name -> value (dedupe by metric)
        
        # Source 1: financial_metrics 컬럼 (파이프 구분)
        if fm_text and fm_text.strip() and len(fm_text.strip()) > 5:
            parts = re.split(r'\s*\|\s*', fm_text)
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                match = re.match(r'([가-힣A-Za-z]+)\s*[:：]?\s*(.+)', part)
                if not match:
                    continue
                label = match.group(1).strip()
                value_str = match.group(2).strip()
                metric_map = {
                    "매출액": "revenue", "매출": "revenue",
                    "영업이익": "operating_profit", "영업손실": "operating_profit",
                    "당기순이익": "net_income", "당기순손실": "net_income",
                    "순이익": "net_income", "순손실": "net_income",
                    "자산총계": "total_assets", "총자산": "total_assets",
                    "부채총계": "total_liabilities", "총부채": "total_liabilities",
                    "자본총계": "equity", "총자본": "equity",
                }
                mn = metric_map.get(label)
                if mn:
                    v = parse_value(value_str)
                    if v is not None:
                        all_metrics[mn] = v
                        stats["from_fm_col"] += 1
        
        # Source 2: summary 텍스트 정규식
        summary_metrics = extract_metrics_from_text(summary)
        for m in summary_metrics:
            if m["metric_name"] not in all_metrics:
                all_metrics[m["metric_name"]] = m["value"]
                stats["from_summary"] += 1
        
        # Source 3: evidence 텍스트 정규식
        evidence_metrics = extract_metrics_from_text(evidence)
        for m in evidence_metrics:
            if m["metric_name"] not in all_metrics:
                all_metrics[m["metric_name"]] = m["value"]
                stats["from_evidence"] += 1
        
        # Insert
        for metric_name, value in all_metrics.items():
            uid = make_fact_uid(doc_id, company_norm, fy, metric_name, scope)
            if uid in existing_uids:
                stats["skipped"] += 1
                continue
            
            fact = FinancialFact(
                fact_uid=uid,
                document_id=doc_id,
                company_name_norm=company_norm,
                corp_code=corp_code,
                fiscal_year=fy,
                metric_name=metric_name,
                metric_value_num=value,
                unit="KRW",
                statement_scope=scope,
                period_type="annual",
                confidence=0.80,
                extraction_method="deep_backfill_v2",
            )
            new_facts.append(fact)
            existing_uids.add(uid)
    
    if new_facts:
        db.bulk_save_objects(new_facts)
        db.commit()
    
    after_count = db.query(FinancialFact).count()
    companies = db.query(FinancialFact.company_name_norm).distinct().count()
    
    log.info(f"=== 결과 ===")
    log.info(f"신규: {len(new_facts)}건 (fm컬럼: {stats['from_fm_col']}, summary: {stats['from_summary']}, evidence: {stats['from_evidence']})")
    log.info(f"스킵: {stats['skipped']}")
    log.info(f"총 팩트: {before_count} -> {after_count} (+{after_count - before_count})")
    log.info(f"총 회사: {companies}")
    
    # 핵심 메트릭 커버리지
    for mn in ['revenue', 'operating_profit', 'net_income', 'total_assets', 'total_liabilities', 'equity']:
        cnt = db.query(FinancialFact).filter(FinancialFact.metric_name == mn).count()
        comp = db.query(FinancialFact.company_name_norm).filter(FinancialFact.metric_name == mn).distinct().count()
        log.info(f"  {mn}: {cnt}건 / {comp}사")
    
    # 삼성전자 확인
    samsung = db.query(FinancialFact).filter(FinancialFact.company_name_norm == '삼성전자').all()
    log.info(f"\n삼성전자 팩트: {len(samsung)}건")
    for s in samsung:
        log.info(f"  {s.metric_name} = {s.metric_value_num:,.0f} fy={s.fiscal_year}")
    
    db.close()
    log.info("완료")


if __name__ == "__main__":
    main()
