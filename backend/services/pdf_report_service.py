"""
═══════════════════════════════════════════════════════
Omega CivicFlow — PDF Report Generation Service v2
A4 안전 좌표계 기반 구조화 보고서 렌더링 엔진
═══════════════════════════════════════════════════════

설계 원칙:
- A4 (210 x 297mm) 기준, 상하좌우 안전 마진 15mm
- 유효 너비 = 180mm (절대 초과 금지)
- 모든 좌표는 마진 기점으로 계산
- 긴 텍스트는 반드시 줄바꿈 (ellipsis 금지)
- 표 컬럼 합 = 유효 너비 이하
"""

import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

from fpdf import FPDF

from config import settings
from services.text_quality import strip_markdown_asterisks, strip_legal_advisory


def _sanitize_for_render(text: str) -> str:
    """렌더링 직전 정제 — markdown asterisk + 자본시장법 advisory 어구 모두 제거.
    기존 DB에 저장된 raw text도 이 한 함수로 자동 정제됨."""
    if not text:
        return text
    return strip_legal_advisory(strip_markdown_asterisks(str(text)))

logger = logging.getLogger(__name__)

# ─── 레이아웃 상수 ───
PAGE_W = 210           # A4 너비 mm
MARGIN_L = 15          # 좌측 마진
MARGIN_R = 15          # 우측 마진
MARGIN_T = 18          # 상단 마진 (헤더 포함)
MARGIN_B = 18          # 하단 마진 (푸터 포함)
USABLE_W = PAGE_W - MARGIN_L - MARGIN_R  # 180mm

# 키-값 레이아웃
LABEL_W = 38           # 라벨 너비
VALUE_W = USABLE_W - LABEL_W  # 142mm

# 폰트
FONT_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
MALGUN_REGULAR = str(FONT_DIR / "malgun.ttf")
MALGUN_BOLD = str(FONT_DIR / "malgunbd.ttf")

# 출력
REPORTS_DIR = Path(settings.UPLOAD_DIR) / "reports"


# ═══════════════════════════════════════════════════════
# Hybrid: financial_facts ground truth 주입 (검증된 재무 지표)
# ═══════════════════════════════════════════════════════

# financial_facts metric → 한국어 라벨
_METRIC_LABELS = {
    'revenue': '매출액',
    'sales': '매출액',
    'operating_profit': '영업이익',
    'operating_income': '영업이익',
    'operating_loss': '영업손실',
    'net_income': '당기순이익',
    'net_profit': '당기순이익',
    'net_loss': '당기순손실',
    'total_assets': '자산총계',
    'total_liabilities': '부채총계',
    'equity': '자본총계',
    'total_equity': '자본총계',
    'capital_stock': '자본금',
    'ebitda': 'EBITDA',
    'cash_and_equivalents': '현금및현금성자산',
    'gross_profit': '매출총이익',
}

# 표시 순서 — 손익 → 재무상태 → 기타
_METRIC_ORDER = [
    'revenue', 'sales', 'gross_profit',
    'operating_profit', 'operating_income', 'operating_loss',
    'net_income', 'net_profit', 'net_loss',
    'total_assets', 'total_liabilities',
    'equity', 'total_equity', 'capital_stock',
    'ebitda', 'cash_and_equivalents',
]


def _format_krw_to_kor(value: float, unit: str = 'KRW') -> str:
    """원화 금액을 한국 단위 (억/조) 표기로 변환.

    예: 47,812,373,057 → "478억 원"
        12,627,718,818 → "126억 원"
        1,500,000,000,000 → "1.5조 원"
    """
    if value is None:
        return "-"
    if unit and unit not in ('KRW', 'WON', '원', None):
        return f"{value:,.0f} {unit}"

    abs_v = abs(float(value))
    sign = "-" if value < 0 else ""

    if abs_v >= 1_000_000_000_000:           # 1조 이상
        return f"{sign}{abs_v / 1_000_000_000_000:,.2f}조 원"
    elif abs_v >= 100_000_000:                # 1억 이상
        return f"{sign}{abs_v / 100_000_000:,.0f}억 원"
    elif abs_v >= 10_000:                     # 1만 이상
        return f"{sign}{abs_v / 10_000:,.0f}만 원"
    else:
        return f"{sign}{int(abs_v):,} 원"


def _fetch_financial_facts(document_id: int) -> dict:
    """financial_facts 테이블에서 해당 문서의 재무 지표 조회.

    Returns: {metric_name: {'value': float, 'unit': str, 'fy': int, 'scope': str}}
    같은 metric에 여러 fiscal_year가 있으면 최신 연도만 보존.
    """
    try:
        from database import SessionLocal
        from sqlalchemy import text
    except ImportError:
        return {}

    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT metric_name, metric_value_num, unit, fiscal_year, statement_scope
            FROM financial_facts
            WHERE document_id = :doc_id
              AND metric_value_num IS NOT NULL
            ORDER BY fiscal_year DESC, id ASC
        """), {"doc_id": document_id}).fetchall()
    except Exception as e:
        logger.warning(f"financial_facts 조회 실패 (doc_id={document_id}): {e}")
        return {}
    finally:
        db.close()

    facts = {}
    for row in rows:
        name = row[0]
        # 가장 최신 fiscal_year (위에서 ORDER BY DESC)을 우선 보존
        if name not in facts:
            facts[name] = {
                'value': float(row[1]),
                'unit': row[2] or 'KRW',
                'fy': row[3],
                'scope': row[4],
            }
    return facts


def _render_financial_facts_section(pdf, document_id: int, next_section) -> bool:
    """재무 핵심 지표 섹션 렌더링 (financial_facts ground truth).

    Returns: True if section was rendered, False if no facts available.
    """
    facts = _fetch_financial_facts(document_id)
    if not facts:
        return False

    # 데이터 행 만들기 (정해진 순서대로)
    rows = []
    seen = set()
    for m in _METRIC_ORDER:
        if m in facts and m not in seen:
            f = facts[m]
            label = _METRIC_LABELS.get(m, m)
            raw_str = f"{int(f['value']):,}"
            kor_str = _format_krw_to_kor(f['value'], f['unit'])
            rows.append([label, raw_str, kor_str])
            seen.add(m)

    # ORDER에 없는 metric 추가
    for m, f in facts.items():
        if m not in seen:
            label = _METRIC_LABELS.get(m, m)
            raw_str = f"{int(f['value']):,}"
            kor_str = _format_krw_to_kor(f['value'], f['unit'])
            rows.append([label, raw_str, kor_str])
            seen.add(m)

    if not rows:
        return False

    # 파생 비율 (검증된 데이터로 계산 → 환각 없음)
    rev = facts.get('revenue', {}).get('value') or facts.get('sales', {}).get('value')
    op = facts.get('operating_profit', {}).get('value') or facts.get('operating_income', {}).get('value')
    ni = facts.get('net_income', {}).get('value') or facts.get('net_profit', {}).get('value')
    liab = facts.get('total_liabilities', {}).get('value')
    eq = facts.get('equity', {}).get('value') or facts.get('total_equity', {}).get('value')

    if rev and op is not None:
        rows.append(['영업이익률', '-', f"{op / rev * 100:.1f}%"])
    if rev and ni is not None:
        rows.append(['순이익률', '-', f"{ni / rev * 100:.1f}%"])
    if eq and liab is not None and eq != 0:
        rows.append(['부채비율', '-', f"{liab / eq * 100:.1f}%"])

    # 섹션 렌더
    next_section("재무 핵심 지표 (검증된 데이터)")
    pdf.body_text(
        "아래 수치는 원본 공시문서 표에서 직접 추출된 검증 데이터(ground truth)입니다. "
        "AI 요약과 별도로, 자동 추출 파이프라인이 산출한 정확한 숫자입니다."
    )
    pdf.ln(2)

    fy_set = sorted({f['fy'] for f in facts.values() if f.get('fy')}, reverse=True)
    if fy_set:
        pdf.body_text(f"사업연도: {', '.join(str(y) for y in fy_set)}")
        pdf.ln(2)

    headers = ["지표", "원 단위 (KRW)", "표시"]
    pdf.safe_table(headers, rows, [0.3, 0.4, 0.3])
    pdf.ln(3)

    return True


def _sanitize_company_for_pdf(company: str) -> str:
    """
    PDF 렌더링 직전 최종 방어선 — 숫자형 회사명 차단.
    llm_service와 독립적으로 동작하여 이중 방어.
    """
    if not company or not company.strip():
        return "미확인"

    name = company.strip()

    # 쉼표 제거 후 순수 숫자이면 차단
    if name.replace(',', '').replace('.', '').replace(' ', '').isdigit():
        logger.warning(f"PDF 방어선: 숫자형 회사명 차단 — '{name}' → '미확인'")
        return "미확인"

    # 숫자 비율 50% 초과면 차단
    digits = sum(1 for c in name if c.isdigit())
    total = sum(1 for c in name if not c.isspace())
    if total > 0 and (digits / total) > 0.5:
        logger.warning(f"PDF 방어선: 숫자 과다 회사명 차단 — '{name}' → '미확인'")
        return "미확인"

    # 한글/영문 없으면 차단
    if not re.search(r'[가-힣a-zA-Z]', name):
        logger.warning(f"PDF 방어선: 비문자 회사명 차단 — '{name}' → '미확인'")
        return "미확인"

    return name


class CivicFlowPDF(FPDF):
    """A4 안전 좌표계 기반 한국어 보고서 PDF"""

    def __init__(self):
        super().__init__(format="A4")
        self.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)
        self.set_auto_page_break(auto=True, margin=MARGIN_B)

        # 한글 폰트
        if os.path.exists(MALGUN_REGULAR):
            self.add_font("malgun", "", MALGUN_REGULAR, uni=True)
            bold_path = MALGUN_BOLD if os.path.exists(MALGUN_BOLD) else MALGUN_REGULAR
            self.add_font("malgun", "B", bold_path, uni=True)
            self._ff = "malgun"
        else:
            self._ff = "Helvetica"

    # ─── 헤더/푸터 ───

    def header(self):
        self.set_font(self._ff, "", 7)
        self.set_text_color(140, 140, 140)
        self.set_xy(MARGIN_L, 8)
        self.cell(USABLE_W, 5, "Omega CivicFlow  |  공시문서 분석 보고서", 0, 1, "R")
        # 구분선 — 마진 안쪽에만
        self.set_draw_color(0, 180, 180)
        self.set_line_width(0.4)
        y = self.get_y()
        self.line(MARGIN_L, y, MARGIN_L + USABLE_W, y)
        self.set_y(MARGIN_T + 2)

    def footer(self):
        self.set_y(-12)
        self.set_font(self._ff, "", 7)
        self.set_text_color(160, 160, 160)
        self.cell(USABLE_W, 5, f"- {self.page_no()} -", 0, 0, "C")

    # ─── 기본 렌더링 블록 ───

    def section_title(self, title: str, level: int = 1):
        """섹션 제목 (유효 너비 안에서만 렌더링)"""
        if level == 1:
            self.ln(5)
            self.set_font(self._ff, "B", 12)
            self.set_text_color(0, 140, 140)
            self.multi_cell(USABLE_W, 8, title)
            # 구분선
            self.set_draw_color(0, 180, 180)
            self.set_line_width(0.3)
            y = self.get_y()
            self.line(MARGIN_L, y, MARGIN_L + USABLE_W, y)
            self.ln(3)
        else:
            self.ln(3)
            self.set_font(self._ff, "B", 10)
            self.set_text_color(50, 50, 50)
            self.multi_cell(USABLE_W, 7, title)
            self.ln(1)

    def body_text(self, text: str):
        """본문 — 유효 너비 안에서 줄바꿈. markdown asterisk + 자본시장법 advisory 어구 자동 제거."""
        if not text:
            return
        clean = _sanitize_for_render(text)
        self.set_font(self._ff, "", 9)
        self.set_text_color(40, 40, 40)
        self.multi_cell(USABLE_W, 5.5, clean)
        self.ln(2)

    def kv_row(self, label: str, value: str):
        """키-값 행 — 라벨(38mm) + 값(142mm), 값이 길면 자동 줄바꿈. advisory 어구도 자동 정제."""
        val = _sanitize_for_render(str(value).strip()) if value else "해당 없음"

        # 페이지 하단 근접 시 미리 페이지 넘김 (라벨+값 분리 방지)
        min_row_height = 12  # 라벨+값 최소 높이
        if self.get_y() + min_row_height > self.h - MARGIN_B:
            self.add_page()

        y_start = self.get_y()

        # 라벨
        self.set_font(self._ff, "B", 9)
        self.set_text_color(80, 80, 80)
        self.set_xy(MARGIN_L, y_start)
        self.cell(LABEL_W, 6, label, 0, 0)

        # 값 — multi_cell 사용 (자동 줄바꿈)
        self.set_font(self._ff, "", 9)
        self.set_text_color(30, 30, 30)
        self.set_xy(MARGIN_L + LABEL_W, y_start)
        self.multi_cell(VALUE_W, 6, val)

        # 라벨보다 값이 더 많은 줄을 차지할 수 있으므로 y 보정
        if self.get_y() < y_start + 6:
            self.set_y(y_start + 6)
        self.ln(0.5)

    def bullet(self, text: str):
        """불릿 포인트 — markdown asterisk + 자본시장법 advisory 어구 자동 제거."""
        if not text:
            return
        clean = _sanitize_for_render(text)
        self.set_font(self._ff, "", 9)
        self.set_text_color(40, 40, 40)
        indent = 6
        self.set_x(MARGIN_L + indent)
        bullet_w = USABLE_W - indent
        self.multi_cell(bullet_w, 5.5, f"- {clean}")
        self.ln(1)

    def safe_table(self, headers: List[str], rows: List[List[str]], col_ratios: List[float] = None):
        """
        안전한 표 — 컬럼 합 = USABLE_W, 셀 내 줄바꿈 지원
        col_ratios: 각 컬럼의 비율 (합=1.0), 미지정 시 균등 분할
        """
        n = len(headers)
        if not col_ratios:
            col_ratios = [1.0 / n] * n
        widths = [USABLE_W * r for r in col_ratios]

        # 헤더
        self.set_font(self._ff, "B", 8)
        self.set_fill_color(0, 140, 140)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(widths[i], 7, str(h), 1, 0, "C", True)
        self.ln(7)

        # 데이터 행
        self.set_font(self._ff, "", 8)
        self.set_text_color(40, 40, 40)
        fill = False
        for row in rows:
            cell_texts = []
            max_lines = 1
            for i, cell in enumerate(row):
                txt = str(cell) if cell else "-"
                cell_texts.append(txt)
                # 한글은 약 3.5mm/글자 (8pt 기준), 영문/숫자는 ~2mm
                avg_char_w = 3.2  # 한글 위주 보수적 추정
                char_per_line = max(int(widths[i] / avg_char_w), 3)
                lines = max(1, -(-len(txt) // char_per_line))  # ceiling div
                max_lines = max(max_lines, lines)

            row_h = max(7, max_lines * 5.5)

            # 페이지 넘김 체크
            if self.get_y() + row_h > self.h - MARGIN_B:
                self.add_page()
                # 헤더 재출력
                self.set_font(self._ff, "B", 8)
                self.set_fill_color(0, 140, 140)
                self.set_text_color(255, 255, 255)
                for i, h in enumerate(headers):
                    self.cell(widths[i], 7, str(h), 1, 0, "C", True)
                self.ln(7)
                self.set_font(self._ff, "", 8)
                self.set_text_color(40, 40, 40)

            if fill:
                self.set_fill_color(245, 247, 250)
            else:
                self.set_fill_color(255, 255, 255)

            y_before = self.get_y()
            x_start = MARGIN_L
            y_max = y_before  # 가장 높은 셀 하단 추적

            for i, txt in enumerate(cell_texts):
                self.set_xy(x_start, y_before)
                # 배경+테두리용 rect 먼저 그리기
                self.rect(x_start, y_before, widths[i], row_h, "DF")
                # multi_cell로 텍스트 줄바꿈 렌더링
                self.set_xy(x_start + 0.5, y_before + 0.5)
                self.multi_cell(widths[i] - 1, 5, txt, 0, "L")
                y_after = self.get_y()
                if y_after > y_max:
                    y_max = y_after
                x_start += widths[i]

            # 모든 셀의 높이가 다를 수 있으므로 실제 최대 y로 이동
            actual_h = max(row_h, y_max - y_before)
            self.set_y(y_before + actual_h)
            fill = not fill

    def disclaimer(self):
        """면책 문구 — 마지막 페이지 하단 고정"""
        self.ln(6)
        self.set_draw_color(180, 180, 180)
        y = self.get_y()
        self.line(MARGIN_L, y, MARGIN_L + USABLE_W, y)
        self.ln(3)
        self.set_font(self._ff, "", 7)
        self.set_text_color(140, 140, 140)
        self.multi_cell(USABLE_W, 4,
            "본 보고서는 자동 추출 파이프라인(OCR + 구조화 추출)이 원본 공시문서를 분석하여 생성한 참고용 요약입니다. "
            "투자 결정의 근거로 사용할 수 없으며, 정확한 정보는 원본 공시문서를 반드시 확인하시기 바랍니다."
        )


# ═══════════════════════════════════════════════════════
# 보고서 생성 함수
# ═══════════════════════════════════════════════════════

def generate_pdf_report(
    document_id: int,
    filename: str,
    analysis_data: Dict[str, Any],
    ocr_text: str = "",
) -> Optional[str]:
    """분석 결과 → 구조화 PDF 보고서 생성"""
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # raw_response에서 확장 JSON 추출 (이중 인코딩 방어)
        raw = analysis_data.get("raw_response")
        ext = {}
        if isinstance(raw, str):
            try:
                decoded = json.loads(raw)
                # 이중 인코딩 감지: json.loads 결과가 str이면 한 번 더 디코딩
                if isinstance(decoded, str):
                    decoded = json.loads(decoded)
                if isinstance(decoded, dict):
                    ext = decoded
            except (json.JSONDecodeError, TypeError):
                ext = {}
        elif isinstance(raw, dict):
            ext = raw

        # ── 최종 정제 단계: 종목명 정규화 ──
        try:
            from services.stock_name_normalizer import normalize_text_company_names

            def _normalize_dict(obj):
                """dict/list/str 재귀 종목명 정규화"""
                if isinstance(obj, str):
                    return normalize_text_company_names(obj)
                elif isinstance(obj, dict):
                    return {k: _normalize_dict(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [_normalize_dict(item) for item in obj]
                return obj

            ext = _normalize_dict(ext)
        except Exception as e:
            logger.warning(f"PDF 정제 단계 처리 실패 (무시): {e}")

        # ── 회사명 추론: 파일명에서 항상 추출 (LLM보다 파일명 우선) ──
        try:
            # 모든 파일명 형식 지원:
            #   DART_P4_현대모비스_20240510000826.zip.pdf
            #   46855749_DART_P0_AP완성_20260312000696.zip
            #   hexprefix_DART_P2_NAVER_20251114001436.zip.pdf
            fn_match = re.search(r'DART_P\d+_(.+?)_(\d{13,14})', filename or '')
            if fn_match:
                fn_company = fn_match.group(1).strip()
                # 파일명에서 추출한 회사명이 유효하면 무조건 사용
                if fn_company and len(fn_company) >= 2 and re.search(r'[가-힣a-zA-Z]', fn_company):
                    current_co = ext.get('company_name', '')
                    # 파일명 회사명을 항상 우선 사용 (LLM은 'ë‚˜. 주' 같은 쓰레기를 추출할 수 있음)
                    if current_co != fn_company:
                        logger.info(f"회사명 교정: '{current_co}' → '{fn_company}' (파일명 우선)")
                    ext['company_name'] = fn_company
                    if '_safe_context' in ext and isinstance(ext['_safe_context'], dict):
                        ext['_safe_context']['safe_company_name'] = fn_company
        except Exception as e:
            logger.warning(f"회사명 추론 실패 (무시): {e}")

        # ── DB에서 document_metadata 보강 조회 (disclosure_title 정본) ──
        # analysis_data + raw_response(ext)가 놓치는 필드를 DB에서 직접 로드
        db_disclosure_title = ""
        db_report_type = ""
        try:
            from database import SessionLocal
            from sqlalchemy import text as sql_text
            _db = SessionLocal()
            try:
                _row = _db.execute(
                    sql_text("SELECT disclosure_title, report_type FROM document_metadata WHERE document_id = :did"),
                    {"did": document_id},
                ).fetchone()
                if _row:
                    db_disclosure_title = (_row[0] or "").strip()
                    db_report_type = (_row[1] or "").strip()
            finally:
                _db.close()
        except Exception as e:
            logger.warning(f"document_metadata 조회 실패 (무시): {e}")

        # 필드 추출 — SafeRenderContext 우선 사용
        safe_ctx = ext.get("_safe_context", {})
        doc_type = ext.get("document_type", {})
        if not isinstance(doc_type, dict):
            doc_type = {"primary": str(doc_type) if doc_type else "", "secondary": ""}

        primary = safe_ctx.get("safe_document_type",
                    doc_type.get("primary", ext.get("_doc_type", db_report_type or "기타공시")))
        secondary = doc_type.get("secondary", ext.get("_doc_secondary", ""))

        # 회사명: safe context → raw → 방어선
        company = safe_ctx.get("safe_company_name",
                    ext.get("company_name", "미확인"))
        # 종목명 정규화 (에스케이하이닉스 → SK하이닉스)
        try:
            from services.stock_name_normalizer import normalize_company_name
            company = normalize_company_name(company)
        except Exception:
            pass
        company = _sanitize_company_for_pdf(company)

        # 공시명: DB → safe context → raw → 방어선
        # DB의 document_metadata.disclosure_title이 backfill된 정본 (예: '자기주식처분결과보고서')
        disclosure = (
            db_disclosure_title
            or safe_ctx.get("safe_filing_title", "")
            or ext.get("disclosure_title", "")
            or "미확인"
        )

        summary = ext.get("summary", analysis_data.get("summary", ""))
        category = safe_ctx.get("safe_category",
                    ext.get("category", analysis_data.get("category", "기타")))
        key_points = ext.get("key_points", [])
        key_changes = ext.get("key_changes", [])
        offering = ext.get("offering_terms", {})
        third_party = ext.get("third_party_allotment", {})
        risk_notes = ext.get("risk_notes", [])
        key_audit_matters = ext.get("key_audit_matters", [])
        footnote_risks = ext.get("footnote_risks", [])

        # 근거 문장 — analysis_results.evidence (backfill된 bullet 텍스트) 우선
        evidence_text_direct = (analysis_data.get("evidence") or "").strip()
        evidence = ext.get("evidence_detailed", ext.get("evidence", []))

        # 핵심 재무 — analysis_results.financial_metrics (backfill된 텍스트) 우선
        # '매출액 478억원 | 영업이익 -43억원 | ...' 또는 '처분금액 71억원 | 처분주식수 291,400주'
        financial_text_direct = (analysis_data.get("financial_metrics") or "").strip()
        financial = ext.get("financial_metrics", financial_text_direct or "해당 없음")

        initial_date = ext.get("initial_filing_date", "")
        amend_date = ext.get("amendment_date", "")
        event_type = safe_ctx.get("safe_event_type",
                      ext.get("event_type", ""))

        # ─── PDF 생성 ───
        pdf = CivicFlowPDF()
        pdf.alias_nb_pages()
        pdf.add_page()

        # ── 보고서 제목 ──
        pdf.set_font(pdf._ff, "B", 15)
        pdf.set_text_color(20, 20, 20)
        title = _make_title(primary, secondary, company)
        pdf.multi_cell(USABLE_W, 9, title)
        pdf.ln(1)

        # 부제 (생성일, 원본) — 파일명 회사명을 교정된 회사명으로 교체
        pdf.set_font(pdf._ff, "", 8)
        pdf.set_text_color(120, 120, 120)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        if company and company != "미확인":
            display_fn = re.sub(
                r'^([a-f0-9]+_DART_P\d+)_.+_(\d{13,14})',
                rf'\1_{company}_\2', filename or ''
            )
        else:
            display_fn = filename or ''
        pdf.multi_cell(USABLE_W, 5, f"생성일: {now}  |  원본: {display_fn}")
        pdf.ln(4)

        # ── 동적 섹션 번호 카운터 ──
        sec_num = [0]
        def next_section(title):
            sec_num[0] += 1
            pdf.section_title(f"Section {sec_num[0]} - {title}")

        # ── 문서 메타 요약 (항상) ──
        next_section("문서 메타 요약")
        pdf.kv_row("문서 유형", primary + (f" / {secondary}" if secondary else ""))
        pdf.kv_row("회사명", company)
        pdf.kv_row("공시명", disclosure)
        if initial_date:
            pdf.kv_row("최초 제출일", str(initial_date))
        if amend_date:
            pdf.kv_row("정정일", str(amend_date))
        if event_type:
            pdf.kv_row("이벤트 유형", str(event_type))
        pdf.kv_row("카테고리", category)

        # ── 재무 핵심 지표 (financial_facts ground truth) ──
        # LLM 환각 방지: 핵심 숫자는 OCR 표 추출 결과를 직접 사용 (단위 변환 정확)
        try:
            _render_financial_facts_section(pdf, document_id, next_section)
        except Exception as e:
            logger.warning(f"financial_facts 섹션 렌더링 실패 (무시): {e}")

        # ── Code-only 추출 데이터 (analysis_data에 있으면 렌더) ──
        # 사업 개요
        biz_overview = ext.get("business_overview", "")
        if biz_overview and len(biz_overview.strip()) > 20:
            next_section("사업 개요")
            pdf.body_text(biz_overview)

        # 사업 부문별 매출
        biz_segs = ext.get("business_segments", [])
        if biz_segs and isinstance(biz_segs, list) and len(biz_segs) > 0:
            next_section("사업 부문별 매출")
            headers_seg = ["사업부문", "유형", "품목", "채널", "금액(천원)", "비중"]
            rows_seg = []
            for s in biz_segs[:15]:
                if isinstance(s, dict):
                    rows_seg.append([
                        s.get("segment", "-"), s.get("type", "-"),
                        s.get("product", "-"), s.get("channel", "-"),
                        s.get("amount", "-"), s.get("percent", "-"),
                    ])
            if rows_seg:
                pdf.safe_table(headers_seg, rows_seg, [0.15, 0.1, 0.25, 0.1, 0.2, 0.1])

        # 주요 임원
        exec_list = ext.get("executives", [])
        if exec_list and isinstance(exec_list, list) and len(exec_list) > 0:
            next_section("주요 임원")
            for ex in exec_list[:15]:
                if isinstance(ex, dict):
                    pdf.bullet(f"{ex.get('title', '')} {ex.get('name', '')}")

        # 감사 정보
        audit_data = ext.get("audit_info", {})
        if isinstance(audit_data, dict) and (audit_data.get("auditor") or audit_data.get("opinion")):
            next_section("감사 정보")
            if audit_data.get("auditor"):
                pdf.kv_row("감사인", audit_data["auditor"])
            if audit_data.get("opinion"):
                pdf.kv_row("감사의견", audit_data["opinion"])
            matters = audit_data.get("matters", [])
            if matters:
                pdf.section_title("핵심감사사항", level=2)
                for m_item in matters[:5]:
                    if isinstance(m_item, str) and m_item.strip():
                        pdf.bullet(m_item)

        # 위험 요인
        code_risks = ext.get("risks", [])
        if code_risks and isinstance(code_risks, list) and len(code_risks) > 0:
            next_section("위험 요인 (OCR 추출)")
            for cr in code_risks[:8]:
                if isinstance(cr, str) and cr.strip():
                    pdf.bullet(cr)

        # 주요 거래처
        cust_list = ext.get("customers", [])
        if cust_list and isinstance(cust_list, list) and len(cust_list) > 0:
            next_section("주요 거래처")
            for cust in cust_list[:10]:
                if isinstance(cust, str) and cust.strip():
                    pdf.bullet(cust)

        # ── 핵심 요약 (항상) ──
        # code-only 모드: short_summary 사용 / LLM 모드: LLM summary 사용
        display_summary = summary
        if (not display_summary or len(display_summary.strip()) <= 10) and ext.get("short_summary"):
            display_summary = ext["short_summary"]
        next_section("핵심 요약 (Executive Summary)")
        if display_summary and len(display_summary.strip()) > 10:
            pdf.body_text(display_summary)
        else:
            pdf.body_text("요약 정보가 충분하지 않습니다. 원본 공시문서를 확인하세요.")

        # ── 핵심 재무 요약 (analysis_data.financial_metrics 텍스트) ──
        # P&L 또는 이벤트 핵심 숫자를 한 섹션에 표시. 문서 유형 무관 항상 렌더.
        if financial_text_direct and financial_text_direct not in ("해당 없음", ""):
            next_section("핵심 재무 요약")
            # '매출액 478억원 | 영업이익 -43억원 | ...' 형식
            for item in financial_text_direct.split(" | "):
                item = item.strip()
                if not item:
                    continue
                # 마지막 공백 기준으로 라벨/값 분리 ('매출액 478억원' → '매출액' + '478억원')
                parts = item.rsplit(" ", 1)
                if len(parts) == 2 and parts[1]:
                    pdf.kv_row(parts[0].strip(), parts[1].strip())
                else:
                    pdf.body_text(item)

        if key_points and isinstance(key_points, list):
            valid_pts = [pt for pt in key_points[:5] if isinstance(pt, str) and pt.strip()]
            if valid_pts:
                pdf.section_title("투자자/검토자 주목 포인트", level=2)
                for pt in valid_pts:
                    pdf.bullet(pt)

        # ── 정정 전/후 비교 (데이터 있을 때만) ──
        if key_changes and isinstance(key_changes, list) and len(key_changes) > 0:
            rows = []
            for ch in key_changes:
                if isinstance(ch, dict):
                    rows.append([
                        ch.get("field", "-"),
                        ch.get("before", "-"),
                        ch.get("after", "-"),
                        ch.get("meaning", "-"),
                    ])
            if rows:
                # 정정 전 값이 전부 '-'이면 의미 없는 비교표 → 섹션 숨김
                has_before = any(
                    row[1] not in ("-", "", "없음", "해당 없음", "null", "None")
                    for row in rows
                )
                if has_before:
                    next_section("정정 전/후 비교")
                    headers = ["항목", "정정 전", "정정 후", "의미"]
                    pdf.safe_table(headers, rows, [0.2, 0.25, 0.25, 0.3])

        # ── 주요 조건 / 재무지표 (데이터 있을 때만) ──
        _render_section4(pdf, primary, offering, third_party, financial, next_section)

        # ── 핵심감사사항 (Key Audit Matters) ──
        if key_audit_matters and isinstance(key_audit_matters, list):
            valid_kam = [k for k in key_audit_matters if isinstance(k, str) and k.strip()]
            if valid_kam:
                next_section("핵심감사사항 (Key Audit Matters)")
                for kam in valid_kam:
                    pdf.bullet(kam)

        # ── 리스크 (데이터 있을 때만) ──
        if risk_notes and isinstance(risk_notes, list):
            valid_notes = [n for n in risk_notes if isinstance(n, str) and n.strip()]
            if valid_notes:
                next_section("리스크 및 유의사항")
                for note in valid_notes:
                    pdf.bullet(note)

        # ── 주석 기반 리스크 (Footnote Risks) ──
        if footnote_risks and isinstance(footnote_risks, list):
            valid_fr = [f for f in footnote_risks if isinstance(f, str) and f.strip()]
            if valid_fr:
                next_section("주석 기반 리스크 (Footnote Risks)")
                for fr in valid_fr:
                    pdf.bullet(fr)

        # ── 근거 문장 (analysis_data.evidence 텍스트 우선, 없으면 ext.evidence dict 리스트) ──
        if evidence_text_direct:
            # Backfill된 bullet text: '\n• 나. 처분기간...\n• 2. 처분보고...'
            next_section("근거 문장")
            for line in evidence_text_direct.split("\n"):
                line = line.strip().lstrip("•").strip()
                if line:
                    pdf.bullet(line)
        else:
            _render_evidence(pdf, evidence, next_section)

        # ── 면책 ──
        pdf.disclaimer()

        # 저장
        safe_name = f"report_{document_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        out = str(REPORTS_DIR / safe_name)
        pdf.output(out)

        logger.info(f"PDF 보고서 생성 완료 - #{document_id} -> {safe_name}")
        return out

    except Exception as e:
        logger.error(f"PDF 보고서 생성 실패 - #{document_id}: {e}", exc_info=True)
        return None


def _format_financial_value(key: str, value: Any) -> str:
    """숫자형 값을 적절한 단위를 붙여 포맷팅"""
    v_str = str(value).strip().replace(',', '')
    try:
        f_val = float(v_str)

        # 단일 날짜 등 숫자 변환 피하기
        if key.endswith('_date') or key.endswith('_time'):
            return str(value)

        # 비율 지표
        if key in ("debt_ratio", "operating_margin", "discount_rate"):
            return f"{f_val:,.1f}%"
        # 주식/수량 (정수)
        if key in ("new_shares",):
            return f"{int(f_val):,}주"
        # 발행가액 등 (단순 원 지표)
        if key in ("issue_price", "reference_price"):
            return f"{int(f_val):,}원"

        # 거액 재무 지표 자릿수 처리 (조, 억, 만)
        abs_v = abs(f_val)
        sign = "-" if f_val < 0 else ""

        if abs_v >= 1_0000_0000_0000:
            jo = int(abs_v // 1_0000_0000_0000)
            eok = int((abs_v % 1_0000_0000_0000) / 1_0000_0000)
            if eok > 0:
                return f"{sign}{jo:,}조 {eok:,}억 원"
            return f"{sign}{jo:,}조 원"
        elif abs_v >= 1_0000_0000:
            eok = abs_v / 1_0000_0000
            if eok.is_integer():
                return f"{sign}{int(eok):,}억 원"
            return f"{sign}{eok:,.1f}억 원"
        elif abs_v >= 1_0000:
            man = abs_v / 1_0000
            if man.is_integer():
                return f"{sign}{int(man):,}만 원"
            return f"{sign}{man:,.1f}만 원"
        
        # 1만원 미만 소액
        if f_val.is_integer():
            return f"{int(f_val):,}원"
        return f"{f_val:,.1f}원"
    except ValueError:
        return str(value)


def _render_section4(pdf, primary, offering, third_party, financial, next_section):
    """문서 유형에 따라 조건표 또는 재무지표 (동적 섹션 번호)"""
    # 유상증자/공시 이벤트 → 조건표
    if offering and isinstance(offering, dict):
        labels_map = {
            "share_type": "신주 종류", "new_shares": "신주 수",
            "fund_use": "자금조달 목적", "offering_method": "증자 방식",
            "issue_price": "발행가액", "reference_price": "기준주가",
            "discount_rate": "할인율", "payment_date": "납입일",
            "listing_date": "상장예정일",
        }
        rows = []
        for k, label in labels_map.items():
            v = offering.get(k)
            if v and str(v) not in ("null", "해당 없음", "None", ""):
                formatted_v = _format_financial_value(k, v)
                rows.append([label, formatted_v])
        if rows:
            next_section("주요 조건 정리")
            for label, val in rows:
                pdf.kv_row(label, val)

    # 제3자배정
    if third_party and isinstance(third_party, dict):
        tp_map = {
            "allottee": "배정 대상자", "relationship": "관계",
            "selection_reason": "선정 경위", "legal_basis": "법적 근거",
        }
        tp_rows = []
        for k, label in tp_map.items():
            v = third_party.get(k)
            if v and str(v) not in ("null", "해당 없음", "None", ""):
                tp_rows.append([label, str(v)])
        if tp_rows:
            pdf.section_title("제3자배정 대상자 정보", level=2)
            for label, val in tp_rows:
                pdf.kv_row(label, val)

    # 재무제표 → 재무지표
    fin_types = {"재무제표", "사업보고서", "감사보고서"}
    if primary in fin_types:
        # financial이 문자열인 경우 dict로 변환 시도
        fin_dict = financial
        if isinstance(fin_dict, str) and fin_dict != "해당 없음":
            try:
                fin_dict = json.loads(fin_dict)
            except (json.JSONDecodeError, TypeError):
                fin_dict = None
        if isinstance(fin_dict, dict):
            fm_map = {
                "revenue": "매출액",
                "operating_income": "영업이익",
                "net_income": "당기순이익",
                "assets_total": "자산총계",
                "liabilities_total": "부채총계",
                "equity_total": "자본총계",
                "debt_ratio": "부채비율",
                "operating_margin": "영업이익률",
                "operating_cash_flow": "영업활동현금흐름",
                "cash_end": "기말 현금및현금성자산",
            }
            fm_rows = []
            for k, label in fm_map.items():
                v = fin_dict.get(k)
                if v and str(v) not in ("null", "해당 없음", "None", ""):
                    formatted_v = _format_financial_value(k, v)
                    fm_rows.append([label, formatted_v])
            if fm_rows:
                next_section("주요 재무 지표")
                for label, val in fm_rows:
                    pdf.kv_row(label, val)
        elif isinstance(financial, str) and financial not in ("해당 없음", ""):
            # 파이프 구분 문자열도 렌더링 (예: "자산총계: 4조 | 부채총계: 2조")
            next_section("주요 재무 지표")
            for item in financial.split(" | "):
                parts = item.split(": ", 1)
                if len(parts) == 2:
                    pdf.kv_row(parts[0].strip(), parts[1].strip())
                else:
                    pdf.body_text(item)


def _render_evidence(pdf, evidence, next_section):
    """근거 문장 (동적 섹션 번호)"""
    if not evidence:
        return

    items = []
    if isinstance(evidence, list):
        for i, ev in enumerate(evidence[:7], 1):
            if isinstance(ev, dict):
                page = ev.get("page", "")
                quote = ev.get("quote", "")
                why = ev.get("why_it_matters", "")
                if not quote:
                    continue
                line = f"[p.{page}] " if page else f"[{i}] "
                line += quote
                if why:
                    line += f" -- {why}"
                items.append(line)
            elif isinstance(ev, str) and ev.strip():
                items.append(f"[{i}] {ev}")
    elif isinstance(evidence, str) and evidence.strip():
        items.append(evidence)

    if items:
        next_section("근거 문장")
        for item in items:
            pdf.bullet(item)


def _make_title(primary: str, secondary: str, company: str) -> str:
    """보고서 제목 생성"""
    parts = []
    if company and company != "미확인":
        parts.append(company)

    type_labels = {
        "정정신고(보고)": "정정신고 분석 보고서",
        "유상증자결정": "유상증자결정 분석 보고서",
        "주요사항보고서": "주요사항보고서 분석 보고서",
        "재무제표": "재무제표 분석 보고서",
        "사업보고서": "사업보고서 분석 보고서",
        "감사보고서": "감사보고서 분석 보고서",
    }
    label = type_labels.get(primary, f"{primary} 분석 보고서")

    if primary == "정정신고(보고)" and secondary:
        label = f"{secondary} 정정 공시 분석 보고서"

    parts.append(label)
    return " - ".join(parts)


# ═══════════════════════════════════════════════════════
# Insight PDF 생성 함수
# ═══════════════════════════════════════════════════════

_DECISION_LABELS = {
    "direct_answer": "직접 판단",
    "clarify": "추가 정보 필요",
    "route": "전문가 라우팅",
    "partial_answer": "부분 판단",
    "defer_until_input": "입력 대기",
}

_AXIS_LABELS = {
    "F": "Finance (금융)",
    "E": "Engineering (공학)",
    "S": "Strategy (전략)",
    "D": "Design (디자인)",
    "R": "Relations (관계)",
}

_CONFIDENCE_LABELS = {
    "AXIOM": "AXIOM [99%]",
    "CONSENSUS": "CONSENSUS [85-95%]",
    "INFERENCE": "INFERENCE [65-84%]",
    "SPECULATION": "SPECULATION [40-64%]",
    "EXPLORATION": "EXPLORATION [<40%]",
}

_EVIDENCE_LABELS = {"high": "높음", "medium": "보통", "low": "낮음"}


def generate_insight_pdf(
    document_id: int,
    filename: str,
    company_name: str,
    insight_data: Dict[str, Any],
) -> Optional[str]:
    """Insight 데이터 → A4 Insight 보고서 PDF 생성"""
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        company = _sanitize_company_for_pdf(company_name or "미확인")

        pdf = CivicFlowPDF()
        pdf.alias_nb_pages()
        pdf.add_page()

        # ── 보고서 제목 ──
        pdf.set_font(pdf._ff, "B", 15)
        pdf.set_text_color(20, 20, 20)
        title_parts = []
        if company and company != "미확인":
            title_parts.append(company)
        title_parts.append("전략 Insight 보고서")
        pdf.multi_cell(USABLE_W, 9, " - ".join(title_parts))
        pdf.ln(1)

        # 부제
        pdf.set_font(pdf._ff, "", 8)
        pdf.set_text_color(120, 120, 120)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        model = insight_data.get("model_name", "")
        proc_time = insight_data.get("processing_time", 0)
        created = insight_data.get("created_at", "")
        sub_parts = [f"생성일: {now}"]
        if model:
            sub_parts.append(f"모델: {model}")
        if proc_time:
            sub_parts.append(f"처리: {proc_time:.1f}s")
        pdf.multi_cell(USABLE_W, 5, "  |  ".join(sub_parts))
        pdf.ln(1)
        pdf.set_font(pdf._ff, "", 7.5)
        pdf.set_text_color(140, 140, 140)
        # 원본 파일명도 한 줄 표기
        if filename:
            pdf.multi_cell(USABLE_W, 4.5, f"원본: {filename}")
        pdf.ln(4)

        sec_num = [0]

        def next_section(title):
            sec_num[0] += 1
            pdf.section_title(f"Section {sec_num[0]} - {title}")

        # ── 전략 등급 ──
        rating = insight_data.get("strategy_rating", "")
        if rating:
            next_section("전략 등급")
            pdf.body_text(_sanitize_for_render(rating))

        # ── 핵심 투자 시사점 ──
        thesis = insight_data.get("investment_thesis", "")
        if thesis:
            next_section("핵심 투자 시사점")
            pdf.body_text(_sanitize_for_render(thesis))

        # ── 시장 컨텍스트 ──
        market = insight_data.get("market_context", "")
        if market:
            next_section("시장 컨텍스트")
            pdf.body_text(_sanitize_for_render(market))

        # ── 리스크 팩터 ──
        risks = insight_data.get("risk_factors", "")
        if risks:
            next_section("리스크 팩터")
            pdf.body_text(_sanitize_for_render(risks))

        # ── 전략적 행동 지침 ──
        action = insight_data.get("strategic_action", "")
        if action:
            next_section("전략적 행동 지침")
            pdf.body_text(_sanitize_for_render(action))

        # ── 면책 문구 ──
        pdf.ln(4)
        pdf.set_draw_color(180, 180, 180)
        y = pdf.get_y()
        pdf.line(MARGIN_L, y, MARGIN_L + USABLE_W, y)
        pdf.ln(3)
        pdf.set_font(pdf._ff, "", 7)
        pdf.set_text_color(140, 140, 140)
        pdf.multi_cell(
            USABLE_W, 4,
            "본 Insight는 공시 정보에 기반한 AI 생성 참고 자료이며, 투자 자문이나 매수·매도 권유가 아닙니다. "
            "투자 결정은 반드시 본인의 판단과 책임하에 이루어져야 합니다. "
            "정확한 정보는 원본 공시문서를 반드시 확인하시기 바랍니다.",
        )

        # 저장
        safe_name = f"insight_{document_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        out = str(REPORTS_DIR / safe_name)
        pdf.output(out)

        logger.info(f"Insight PDF 생성 완료 - #{document_id} -> {safe_name}")
        return out

    except Exception as e:
        logger.error(f"Insight PDF 생성 실패 - #{document_id}: {e}", exc_info=True)
        return None
