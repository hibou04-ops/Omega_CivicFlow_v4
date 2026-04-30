"""
Omega CivicFlow v4 — 발표용 학습 PDF 생성기

생성물: Omega_CivicFlow_v4_발표학습자료.pdf (워크스페이스 루트)

목적: 코드를 직접 작성하지 않은 발표자가 발표 직전 5-10분 안에
       시스템 전체 구조를 이해하고 청중 질문에 대응할 수 있도록 함.

원칙:
  - 모든 숫자는 실제 코드 검증된 값만 사용
  - 시각적 다이어그램 우선
  - 한 페이지 = 한 개념
  - 비개발자도 읽을 수 있는 한국어
"""

from __future__ import annotations

from pathlib import Path

from reportlab.graphics.shapes import (
    Drawing, Rect, Line, String, Polygon, Circle, Path as PathShape, Group,
)
from reportlab.lib.colors import HexColor, white, black, Color
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer,
    Table, TableStyle, KeepTogether, Flowable,
)


# ─────────────────────────────────────────────────────────
# 폰트 등록 (Malgun Gothic — 윈도우 기본 한글 폰트)
# ─────────────────────────────────────────────────────────
FONT_REGULAR = "Malgun"
FONT_BOLD = "MalgunBold"
FONT_LIGHT = "MalgunLight"

pdfmetrics.registerFont(TTFont(FONT_REGULAR, "C:/Windows/Fonts/malgun.ttf"))
pdfmetrics.registerFont(TTFont(FONT_BOLD, "C:/Windows/Fonts/malgunbd.ttf"))
pdfmetrics.registerFont(TTFont(FONT_LIGHT, "C:/Windows/Fonts/malgunsl.ttf"))


# ─────────────────────────────────────────────────────────
# 컬러 팔레트 (다크/액센트 — README와 vault 색 일관성)
# ─────────────────────────────────────────────────────────
C_INK = HexColor("#0f0f12")
C_PAPER = HexColor("#fafafa")
C_GREY_DARK = HexColor("#2c2c30")
C_GREY_MID = HexColor("#6e6e76")
C_GREY_LIGHT = HexColor("#e2e2e6")
C_LINE = HexColor("#c8c8ce")
C_HIGHLIGHT = HexColor("#ffd54f")

C_EXAONE = HexColor("#6b46c1")     # 보라 — Base 경로
C_GEMINI = HexColor("#4285f4")     # 파랑 — Insight Pro
C_SUPER = HexColor("#ea4335")      # 빨강 — Supervisor
C_BGE = HexColor("#ff8c00")        # 주황 — Embedding
C_OK = HexColor("#34a853")         # 초록 — 통과/성공
C_BLUE_SOFT = HexColor("#e3eaff")
C_RED_SOFT = HexColor("#fde2e0")
C_PURPLE_SOFT = HexColor("#ece6f7")
C_ORANGE_SOFT = HexColor("#fff0e0")


# ─────────────────────────────────────────────────────────
# 스타일
# ─────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

S_TITLE = ParagraphStyle(
    "title", fontName=FONT_BOLD, fontSize=26, leading=32,
    textColor=C_INK, alignment=TA_LEFT, spaceAfter=6,
)
S_SUBTITLE = ParagraphStyle(
    "subtitle", fontName=FONT_LIGHT, fontSize=13, leading=18,
    textColor=C_GREY_MID, alignment=TA_LEFT, spaceAfter=10,
)
S_H1 = ParagraphStyle(
    "h1", fontName=FONT_BOLD, fontSize=20, leading=26,
    textColor=C_INK, alignment=TA_LEFT, spaceAfter=8,
)
S_H2 = ParagraphStyle(
    "h2", fontName=FONT_BOLD, fontSize=14, leading=20,
    textColor=C_INK, alignment=TA_LEFT, spaceBefore=8, spaceAfter=4,
)
S_BODY = ParagraphStyle(
    "body", fontName=FONT_REGULAR, fontSize=10.5, leading=16,
    textColor=C_INK, alignment=TA_LEFT, spaceAfter=6,
)
S_BODY_TIGHT = ParagraphStyle(
    "body_tight", fontName=FONT_REGULAR, fontSize=10, leading=14,
    textColor=C_INK, alignment=TA_LEFT, spaceAfter=4,
)
S_SMALL = ParagraphStyle(
    "small", fontName=FONT_LIGHT, fontSize=8.5, leading=12,
    textColor=C_GREY_MID, alignment=TA_LEFT, spaceAfter=4,
)
S_LABEL = ParagraphStyle(
    "label", fontName=FONT_BOLD, fontSize=8, leading=10,
    textColor=C_GREY_MID, alignment=TA_LEFT, spaceAfter=2,
)
S_QUOTE = ParagraphStyle(
    "quote", fontName=FONT_LIGHT, fontSize=11, leading=18,
    textColor=C_GREY_DARK, alignment=TA_LEFT,
    leftIndent=12, rightIndent=12, spaceBefore=6, spaceAfter=6,
)
S_NUMBER_BIG = ParagraphStyle(
    "number_big", fontName=FONT_BOLD, fontSize=32, leading=38,
    textColor=C_INK, alignment=TA_LEFT,
)
S_NUMBER_LABEL = ParagraphStyle(
    "number_label", fontName=FONT_LIGHT, fontSize=9, leading=12,
    textColor=C_GREY_MID, alignment=TA_LEFT,
)
S_CONFIDENCE = ParagraphStyle(
    "confidence", fontName=FONT_BOLD, fontSize=9, leading=12,
    textColor=white, alignment=TA_CENTER,
)
S_CENTER_TITLE = ParagraphStyle(
    "center_title", fontName=FONT_BOLD, fontSize=22, leading=28,
    textColor=C_INK, alignment=TA_CENTER, spaceAfter=8,
)


# ─────────────────────────────────────────────────────────
# 페이지 프레임
# ─────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN_L = 18 * mm
MARGIN_R = 18 * mm
MARGIN_T = 22 * mm
MARGIN_B = 18 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R
CONTENT_H = PAGE_H - MARGIN_T - MARGIN_B


def header_footer(canvas_obj, doc):
    """모든 페이지 공통 헤더/푸터"""
    canvas_obj.saveState()

    # 상단 얇은 라인
    canvas_obj.setStrokeColor(C_LINE)
    canvas_obj.setLineWidth(0.4)
    canvas_obj.line(MARGIN_L, PAGE_H - 14 * mm, PAGE_W - MARGIN_R, PAGE_H - 14 * mm)

    # 좌상: 프로젝트 마크
    canvas_obj.setFont(FONT_BOLD, 8.5)
    canvas_obj.setFillColor(C_INK)
    canvas_obj.drawString(MARGIN_L, PAGE_H - 11 * mm, "Ω  OMEGA CIVICFLOW v4")
    canvas_obj.setFont(FONT_LIGHT, 7.5)
    canvas_obj.setFillColor(C_GREY_MID)
    canvas_obj.drawString(MARGIN_L + 50 * mm, PAGE_H - 11 * mm,
                          "발표용 학습 자료  ·  팩트 검증판")

    # 우상: 페이지 번호
    canvas_obj.setFont(FONT_REGULAR, 8.5)
    canvas_obj.setFillColor(C_GREY_MID)
    canvas_obj.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 11 * mm,
                               f"{doc.page:02d} / 18")

    # 하단 얇은 라인
    canvas_obj.setStrokeColor(C_LINE)
    canvas_obj.setLineWidth(0.4)
    canvas_obj.line(MARGIN_L, 12 * mm, PAGE_W - MARGIN_R, 12 * mm)

    canvas_obj.setFont(FONT_LIGHT, 7)
    canvas_obj.setFillColor(C_GREY_MID)
    canvas_obj.drawString(MARGIN_L, 8.5 * mm,
                          "this page is part of the public index to a private system.")
    canvas_obj.drawRightString(PAGE_W - MARGIN_R, 8.5 * mm,
                               "1 engineer · 5 months · Phase 4 / LIVE")

    canvas_obj.restoreState()


# ─────────────────────────────────────────────────────────
# 헬퍼: 박스/배지/라벨 그리기
# ─────────────────────────────────────────────────────────
def filled_box(d: Drawing, x, y, w, h, fill, stroke=None, radius=4, stroke_width=0.6):
    r = Rect(x, y, w, h, fillColor=fill,
             strokeColor=stroke if stroke else fill,
             strokeWidth=stroke_width)
    r.rx = radius
    r.ry = radius
    d.add(r)


def text_in_box(d: Drawing, x, y, w, h, text, font=FONT_BOLD, size=10,
                color=C_INK, anchor="middle"):
    """박스 중앙 정렬 텍스트 (멀티라인 지원)"""
    lines = text.split("\n")
    line_h = size * 1.25
    total_h = line_h * len(lines)
    start_y = y + h / 2 + total_h / 2 - line_h * 0.85
    for i, line in enumerate(lines):
        s = String(x + w / 2, start_y - i * line_h, line,
                   fontName=font, fontSize=size, fillColor=color,
                   textAnchor="middle")
        d.add(s)


def arrow(d: Drawing, x1, y1, x2, y2, color=C_GREY_DARK, width=1.2, head=4):
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=width))
    # 화살촉 (단순 폴리곤)
    import math
    angle = math.atan2(y2 - y1, x2 - x1)
    hx1 = x2 - head * math.cos(angle - math.pi / 6)
    hy1 = y2 - head * math.sin(angle - math.pi / 6)
    hx2 = x2 - head * math.cos(angle + math.pi / 6)
    hy2 = y2 - head * math.sin(angle + math.pi / 6)
    d.add(Polygon([x2, y2, hx1, hy1, hx2, hy2],
                  fillColor=color, strokeColor=color))


# ─────────────────────────────────────────────────────────
# 다이어그램 1: 5단계 파이프라인 (System Overview)
# ─────────────────────────────────────────────────────────
def make_pipeline_diagram() -> Drawing:
    W = 168 * mm
    H = 75 * mm
    d = Drawing(W, H)

    filled_box(d, 0, 0, W, H, HexColor("#fbfbfd"),
               stroke=C_LINE, radius=6, stroke_width=0.8)

    box_w = 28 * mm
    box_h = 22 * mm
    gap = 4 * mm
    start_x = (W - (box_w * 5 + gap * 4)) / 2
    cy = H / 2 + 6

    phases = [
        ("P0\n수집", "DART API\ncorpCode", HexColor("#6b46c1")),
        ("P1\nOCR", "PaddleOCR\n3.4", HexColor("#9333ea")),
        ("P2\n청킹", "계층형\n+ 헤더", HexColor("#ff8c00")),
        ("P3\n임베딩", "BGE-M3\nA100", HexColor("#34a853")),
        ("P4\n분석", "EXAONE\n+ Gemini", HexColor("#4285f4")),
    ]

    centers = []
    for i, (label, sub, color) in enumerate(phases):
        x = start_x + i * (box_w + gap)
        filled_box(d, x, cy - box_h / 2, box_w, box_h, color, radius=5)
        text_in_box(d, x, cy - box_h / 2 + 9, box_w, 14, label,
                    font=FONT_BOLD, size=11, color=white)
        text_in_box(d, x, cy - box_h / 2 - 5, box_w, 14, sub,
                    font=FONT_REGULAR, size=7.5, color=white)
        centers.append((x + box_w / 2, cy))

    # 화살표 연결
    for i in range(len(centers) - 1):
        x1 = centers[i][0] + box_w / 2
        x2 = centers[i + 1][0] - box_w / 2
        arrow(d, x1, cy, x2, cy, color=C_GREY_DARK, width=1.2, head=3.5)

    # 입력 라벨
    d.add(String(start_x + box_w / 2, cy + box_h / 2 + 9,
                 "INPUT", fontName=FONT_BOLD, fontSize=8,
                 fillColor=C_GREY_MID, textAnchor="middle"))
    d.add(String(start_x + box_w / 2, cy - box_h / 2 - 12,
                 "약 80,000 법인 공시", fontName=FONT_REGULAR, fontSize=7.5,
                 fillColor=C_GREY_MID, textAnchor="middle"))

    # 출력 라벨
    last_cx = centers[-1][0]
    d.add(String(last_cx, cy + box_h / 2 + 9,
                 "OUTPUT", fontName=FONT_BOLD, fontSize=8,
                 fillColor=C_GREY_MID, textAnchor="middle"))
    d.add(String(last_cx, cy - box_h / 2 - 12,
                 "구조화 JSON → PDF 리포트",
                 fontName=FONT_REGULAR, fontSize=7.5,
                 fillColor=C_GREY_MID, textAnchor="middle"))

    # 하단 캡션
    d.add(String(W / 2, 6, "단일 end-to-end 파이프라인 · DART OpenAPI → 구조화 리포트",
                 fontName=FONT_LIGHT, fontSize=8.5,
                 fillColor=C_GREY_MID, textAnchor="middle"))

    return d


# ─────────────────────────────────────────────────────────
# 다이어그램 2: Dual LLM Pathway
# ─────────────────────────────────────────────────────────
def make_dual_llm_diagram() -> Drawing:
    W = 168 * mm
    H = 110 * mm
    d = Drawing(W, H)

    filled_box(d, 0, 0, W, H, HexColor("#fbfbfd"),
               stroke=C_LINE, radius=6, stroke_width=0.8)

    # 사용자 / API 진입
    user_w = 36 * mm
    user_h = 12 * mm
    user_x = (W - user_w) / 2
    user_y = H - 18 * mm
    filled_box(d, user_x, user_y, user_w, user_h, C_INK, radius=5)
    text_in_box(d, user_x, user_y, user_w, user_h,
                "사용자 / API 호출",
                font=FONT_BOLD, size=10, color=white)

    # 라우터 (다이아몬드 모양 대신 둥근 박스)
    rt_w = 30 * mm
    rt_h = 11 * mm
    rt_x = (W - rt_w) / 2
    rt_y = user_y - 18 * mm
    filled_box(d, rt_x, rt_y, rt_w, rt_h, HexColor("#ffd54f"),
               stroke=C_INK, radius=5, stroke_width=1.0)
    text_in_box(d, rt_x, rt_y, rt_w, rt_h,
                "Task Router",
                font=FONT_BOLD, size=10, color=C_INK)

    arrow(d, W / 2, user_y, W / 2, rt_y + rt_h, color=C_GREY_DARK, width=1.4)

    # BASE PATHWAY (왼쪽)
    base_x = 14 * mm
    base_y = 18 * mm
    base_w = 64 * mm
    base_h = 50 * mm
    filled_box(d, base_x, base_y, base_w, base_h, C_PURPLE_SOFT,
               stroke=C_EXAONE, radius=6, stroke_width=1.0)
    d.add(String(base_x + 5, base_y + base_h - 9,
                 "BASE PATHWAY", fontName=FONT_BOLD, fontSize=10,
                 fillColor=C_EXAONE))
    d.add(String(base_x + 5, base_y + base_h - 18,
                 "로컬 · 프라이빗 · 무료",
                 fontName=FONT_LIGHT, fontSize=8, fillColor=C_GREY_MID))

    # EXAONE 박스
    ex_w = 50 * mm
    ex_h = 14 * mm
    ex_x = base_x + (base_w - ex_w) / 2
    ex_y = base_y + 18
    filled_box(d, ex_x, ex_y, ex_w, ex_h, C_EXAONE, radius=4)
    text_in_box(d, ex_x, ex_y + 4, ex_w, 8,
                "Ollama EXAONE 3.5",
                font=FONT_BOLD, size=10, color=white)
    text_in_box(d, ex_x, ex_y - 4, ex_w, 8,
                "7.8B  ·  LG AI Research",
                font=FONT_REGULAR, size=7.5, color=white)

    # base 역할 4개
    roles_base = ["OCR 후처리", "RAG 검색·챗", "일반 요약", "에이전트 오케스트레이션"]
    for i, role in enumerate(roles_base):
        x = base_x + 5
        y = ex_y - 10 - i * 4
        d.add(String(x, y, "·  " + role,
                     fontName=FONT_REGULAR, fontSize=7.2,
                     fillColor=C_GREY_DARK))

    # 화살표 router → base
    arrow(d, rt_x + 6, rt_y + 1, base_x + base_w - 4, base_y + base_h - 4,
          color=C_EXAONE, width=1.2)

    # INSIGHT PATHWAY (오른쪽)
    ins_x = W - 14 * mm - 64 * mm
    ins_y = 18 * mm
    ins_w = 64 * mm
    ins_h = 50 * mm
    filled_box(d, ins_x, ins_y, ins_w, ins_h, C_BLUE_SOFT,
               stroke=C_GEMINI, radius=6, stroke_width=1.0)
    d.add(String(ins_x + 5, ins_y + ins_h - 9,
                 "INSIGHT PATHWAY", fontName=FONT_BOLD, fontSize=10,
                 fillColor=C_GEMINI))
    d.add(String(ins_x + 5, ins_y + ins_h - 18,
                 "클라우드 · 이중 감독",
                 fontName=FONT_LIGHT, fontSize=8, fillColor=C_GREY_MID))

    # Gemini Pro 박스
    gp_w = 50 * mm
    gp_h = 11 * mm
    gp_x = ins_x + (ins_w - gp_w) / 2
    gp_y = ins_y + ins_h - 32
    filled_box(d, gp_x, gp_y, gp_w, gp_h, C_GEMINI, radius=4)
    text_in_box(d, gp_x, gp_y + 2, gp_w, 7,
                "Gemini 2.5 Pro  ·  PRIMARY",
                font=FONT_BOLD, size=8.5, color=white)
    text_in_box(d, gp_x, gp_y - 4, gp_w, 7,
                "초안 생성 · 5축 JSON",
                font=FONT_REGULAR, size=7, color=white)

    # Supervisor 박스
    sv_w = 50 * mm
    sv_h = 11 * mm
    sv_x = ins_x + (ins_w - sv_w) / 2
    sv_y = gp_y - 17
    filled_box(d, sv_x, sv_y, sv_w, sv_h, C_SUPER, radius=4)
    text_in_box(d, sv_x, sv_y + 2, sv_w, 7,
                "Gemini 2.5 Flash · SUPERVISOR",
                font=FONT_BOLD, size=8.5, color=white)
    text_in_box(d, sv_x, sv_y - 4, sv_w, 7,
                "5-step 사후 감독",
                font=FONT_REGULAR, size=7, color=white)

    # 두 박스 연결 화살표
    arrow(d, gp_x + gp_w / 2, gp_y, sv_x + sv_w / 2, sv_y + sv_h,
          color=C_SUPER, width=1.2, head=3)

    # 화살표 router → insight
    arrow(d, rt_x + rt_w - 6, rt_y + 1,
          ins_x + 4, ins_y + ins_h - 4,
          color=C_GEMINI, width=1.2)

    # 라우팅 라벨
    d.add(String(rt_x - 18, rt_y - 6, "OCR · 챗 · 요약",
                 fontName=FONT_LIGHT, fontSize=7,
                 fillColor=C_EXAONE, textAnchor="middle"))
    d.add(String(rt_x + rt_w + 22, rt_y - 6, "재무 전략 판단만",
                 fontName=FONT_LIGHT, fontSize=7,
                 fillColor=C_GEMINI, textAnchor="middle"))

    # 하단 캡션
    d.add(String(W / 2, 6,
                 "Supervisor 는 Insight 경로에만 적용 — 환각 리스크가 가장 높은 영역",
                 fontName=FONT_LIGHT, fontSize=8.5,
                 fillColor=C_GREY_MID, textAnchor="middle"))

    return d


# ─────────────────────────────────────────────────────────
# 다이어그램 3: 5-Step Supervisor Protocol
# ─────────────────────────────────────────────────────────
def make_supervisor_diagram() -> Drawing:
    W = 168 * mm
    H = 60 * mm
    d = Drawing(W, H)

    filled_box(d, 0, 0, W, H, HexColor("#fbfbfd"),
               stroke=C_LINE, radius=6, stroke_width=0.8)

    steps = [
        ("STEP 1", "Decompose", "변수·가정·\n불확실성 분리"),
        ("STEP 2", "Causal Graph", "메커니즘·방향·\n혼재변수 체크"),
        ("STEP 3", "Generate", "최소 2개\n독립 후보"),
        ("STEP 4", "Counterfactual", "핵심 가정\n복원력 검증"),
        ("STEP 5", "Compress", "Pareto\n80/20 필터"),
    ]

    box_w = 28 * mm
    box_h = 38 * mm
    gap = 4 * mm
    start_x = (W - (box_w * 5 + gap * 4)) / 2
    cy = 10 * mm

    for i, (label, name, desc) in enumerate(steps):
        x = start_x + i * (box_w + gap)
        # 외곽
        filled_box(d, x, cy, box_w, box_h, white,
                   stroke=C_SUPER, radius=4, stroke_width=1.2)
        # 상단 라벨 띠
        filled_box(d, x, cy + box_h - 8, box_w, 8, C_SUPER, radius=4)
        # 라벨 보정 (둥근 모서리 아래만)
        d.add(Rect(x, cy + box_h - 12, box_w, 4,
                   fillColor=C_SUPER, strokeColor=C_SUPER))
        text_in_box(d, x, cy + box_h - 11, box_w, 7,
                    label, font=FONT_BOLD, size=8, color=white)
        # 이름
        text_in_box(d, x, cy + box_h - 22, box_w, 8,
                    name, font=FONT_BOLD, size=10, color=C_INK)
        # 설명
        text_in_box(d, x, cy + 6, box_w, 14,
                    desc, font=FONT_REGULAR, size=7.5, color=C_GREY_MID)

    # 하단 캡션
    d.add(String(W / 2, 4,
                 "공개되는 건 5단계의 이름.  내부 rubric · rejection 기준은 비공개.",
                 fontName=FONT_LIGHT, fontSize=8.5,
                 fillColor=C_GREY_MID, textAnchor="middle"))

    return d


# ─────────────────────────────────────────────────────────
# 다이어그램 4: 신뢰도 배지 (Confidence ladder)
# ─────────────────────────────────────────────────────────
def confidence_badge(label: str, pct: str, color) -> Drawing:
    d = Drawing(40 * mm, 7 * mm)
    filled_box(d, 0, 0, 40 * mm, 7 * mm, color, radius=2)
    d.add(String(2 * mm, 2 * mm, label,
                 fontName=FONT_BOLD, fontSize=8, fillColor=white))
    d.add(String(38 * mm, 2 * mm, pct,
                 fontName=FONT_BOLD, fontSize=8, fillColor=white,
                 textAnchor="end"))
    return d


# ─────────────────────────────────────────────────────────
# 페이지 생성
# ─────────────────────────────────────────────────────────
def page_break():
    return PageBreak()


def section_title(num: str, title: str, sub: str = ""):
    items = []
    items.append(Spacer(1, 4))
    items.append(Paragraph(
        f'<font color="#6e6e76" size="9">— {num}</font>', S_LABEL))
    items.append(Paragraph(title, S_H1))
    if sub:
        items.append(Paragraph(sub, S_SUBTITLE))
    items.append(Spacer(1, 6))
    return items


def horizontal_rule(thickness=0.5, color=C_LINE):
    from reportlab.platypus import HRFlowable
    return HRFlowable(width="100%", thickness=thickness, color=color,
                      spaceBefore=4, spaceAfter=4)


def info_box(title: str, body_html: str, fill=C_BLUE_SOFT, border=C_GEMINI):
    """배경 강조 박스 (Table 기반)"""
    inner = []
    inner.append(Paragraph(
        f'<font name="{FONT_BOLD}" color="#0f0f12">{title}</font>',
        ParagraphStyle("ib_t", fontName=FONT_BOLD, fontSize=10.5,
                       leading=14, textColor=C_INK, spaceAfter=4)))
    inner.append(Paragraph(body_html, S_BODY_TIGHT))
    t = Table([[inner]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("BOX", (0, 0), (-1, -1), 0.8, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


# ═══════════════════════════════════════════════════════
# 콘텐츠 빌더
# ═══════════════════════════════════════════════════════
def build_story():
    s = []

    # ────────────── PAGE 01 — 표지 ──────────────
    s.append(Spacer(1, 30 * mm))
    s.append(Paragraph(
        '<font name="MalgunBold" size="48" color="#0f0f12">Ω</font>',
        ParagraphStyle("omega", fontName=FONT_BOLD, fontSize=48,
                       leading=52, alignment=TA_LEFT)))
    s.append(Spacer(1, 4 * mm))
    s.append(Paragraph("OMEGA CIVICFLOW v4", S_TITLE))
    s.append(Paragraph(
        "한국 규제 공시를 위한 문서 지능 엔진",
        S_SUBTITLE))
    s.append(Spacer(1, 8 * mm))

    s.append(horizontal_rule(thickness=1.0, color=C_INK))
    s.append(Spacer(1, 6 * mm))

    s.append(Paragraph(
        "발표용 학습 자료",
        ParagraphStyle("cv_h", fontName=FONT_BOLD, fontSize=18,
                       leading=24, textColor=C_INK)))
    s.append(Paragraph(
        "코드를 직접 작성하지 않은 빌더가, 발표 직전에 자기 시스템을 다시 학습할 수 있도록 만든 자료입니다. "
        "모든 숫자·다이어그램·구조는 워크스페이스 코드를 직접 읽어 검증한 팩트 기반입니다.",
        ParagraphStyle("cv_b", fontName=FONT_REGULAR, fontSize=11,
                       leading=18, textColor=C_GREY_DARK, spaceAfter=10)))

    s.append(Spacer(1, 4 * mm))

    # 표지 핵심 숫자
    cover_data = [
        ["284,000+", "vector chunks", "BGE-M3 · 1024-dim"],
        ["3,135", "filings analyzed", "end-to-end narrative"],
        ["92.5 %", "QC pass rate", "2,901 / 3,135"],
        ["99.0 %", "evidence cite rate", "explainability KPI"],
        ["10–15 m", "full corpus embedding", "A100 40GB · one run"],
        ["30,000+", "LoC", "27 services · 4 routers"],
    ]
    rows = []
    for big, mid, small in cover_data:
        rows.append([
            Paragraph(f'<font name="{FONT_BOLD}" size="16">{big}</font>', S_BODY_TIGHT),
            Paragraph(f'<font name="{FONT_BOLD}" size="9">{mid}</font>', S_BODY_TIGHT),
            Paragraph(f'<font name="{FONT_LIGHT}" size="8" color="#6e6e76">{small}</font>',
                      S_BODY_TIGHT),
        ])
    cover_table = Table(rows,
                        colWidths=[35 * mm, 50 * mm, CONTENT_W - 85 * mm])
    cover_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    s.append(cover_table)

    s.append(Spacer(1, 8 * mm))
    s.append(Paragraph(
        "BUILD  2026.02 → 2026.04   ·   1 engineer   ·   PHASE 4 / LIVE",
        ParagraphStyle("cv_meta", fontName=FONT_LIGHT, fontSize=10,
                       leading=14, textColor=C_GREY_MID)))
    s.append(Paragraph(
        "생성일 2026-04-13   ·   원본: workspace 코드 + vault 정독 검증",
        ParagraphStyle("cv_meta2", fontName=FONT_LIGHT, fontSize=8.5,
                       leading=12, textColor=C_GREY_MID)))

    s.append(page_break())

    # ────────────── PAGE 02 — 자료 사용법 ──────────────
    s.extend(section_title("01", "이 자료의 사용법",
                           "발표 직전 5-10분 안에 시스템 이해를 복원하기 위한 4단계 동선"))

    use_data = [
        [
            Paragraph(f'<font name="{FONT_BOLD}" size="10">① 30초가 주어졌을 때</font>',
                      S_BODY_TIGHT),
            Paragraph(
                "P3 (한 문장 답변)만 외우면 됩니다. "
                "\"DART OpenAPI 8만 법인 공시를 수집·OCR·청킹·임베딩·검색·LLM 분석·"
                "리포트 생성까지 단일 파이프라인으로 처리하는 한국어 문서 지능 시스템\".",
                S_BODY_TIGHT),
        ],
        [
            Paragraph(f'<font name="{FONT_BOLD}" size="10">② 1분이 주어졌을 때</font>',
                      S_BODY_TIGHT),
            Paragraph(
                "P3 + P4 (5단계 다이어그램) + P6 (Dual LLM 다이어그램). "
                "이 세 페이지는 다음과 같은 순서로 말합니다 — "
                "<b>무엇을(P3) → 어떻게 흐르는지(P4) → 왜 LLM 두 개인지(P6)</b>.",
                S_BODY_TIGHT),
        ],
        [
            Paragraph(f'<font name="{FONT_BOLD}" size="10">③ 청중이 깊게 파고들 때</font>',
                      S_BODY_TIGHT),
            Paragraph(
                "P11-14 (4개 의사결정) 중 질문에 해당하는 것을 펼쳐서 신뢰도(AXIOM/CONSENSUS/"
                "INFERENCE) 박스를 그대로 인용하세요. "
                "신뢰도 라벨을 입에 담는 것 자체가 \"이 사람은 calibrated 사고를 한다\" 라는 신호입니다.",
                S_BODY_TIGHT),
        ],
        [
            Paragraph(f'<font name="{FONT_BOLD}" size="10">④ 모르는 질문이 나왔을 때</font>',
                      S_BODY_TIGHT),
            Paragraph(
                "<b>회피하지 말고 신뢰도를 낮춰서 답합니다.</b> "
                "예: \"그 부분은 [SPECULATION] 영역입니다 — 정확한 수치는 미팅 후 별도 공유 가능\". "
                "Omega-Prime 사고법의 핵심은 모르는 것을 모른다고 말하는 능력입니다.",
                S_BODY_TIGHT),
        ],
    ]
    use_table = Table(use_data, colWidths=[55 * mm, CONTENT_W - 55 * mm])
    use_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), C_GREY_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    s.append(use_table)

    s.append(Spacer(1, 8))

    s.append(info_box(
        "핵심 원칙 — 정직 > 인상 ",
        "면접관/투자자가 질문하는 진짜 이유는 <b>당신이 시스템을 만든 사람인지 확인</b>하기 위함입니다. "
        "암기한 답변보다 \"이건 확실하고, 이건 모릅니다\"라는 calibration 이 훨씬 강한 신호입니다. "
        "이 자료의 모든 신뢰도 라벨은 그 도구입니다.",
        fill=HexColor("#fff8e1"), border=HexColor("#f9a825")))

    s.append(page_break())

    # ────────────── PAGE 03 — 30초 답변 + 핵심 숫자 ──────────────
    s.extend(section_title("02", "30초 답변 + 핵심 숫자",
                           "암기 카드 — 발표 시작 전에 이 두 블록만 머릿속에 올리세요"))

    s.append(info_box(
        "ONE-PARAGRAPH ANSWER",
        "한국 금융감독원(<b>DART</b>) OpenAPI 기반 약 <b>80,000 개 법인 공시</b>를 대상으로, "
        "<b>문서 수집 → OCR → 계층형 청킹 → 벡터 임베딩 → RAG 검색 → LLM 전략 분석 → "
        "구조화 JSON 리포트 → PDF 생성</b> 까지 <b>end-to-end 단일 파이프라인</b>으로 처리하는 "
        "멀티모달 한국어 문서 지능 시스템입니다. <br/><br/>"
        "<b>FastAPI + React 18 + ChromaDB + BGE-M3 + EXAONE 3.5 + Gemini 2.5 Pro/Flash</b> 기반. "
        "5 개월, 1 인 풀스택 개발. 현재 Phase 4 운영.",
        fill=C_PURPLE_SOFT, border=C_EXAONE))

    s.append(Spacer(1, 6))
    s.append(Paragraph("핵심 숫자 6개 (모두 측정값)", S_H2))

    numbers_data = [
        ["284,000+", "vector chunks",
         "BGE-M3 임베딩 모델로 만든 1024차원 벡터의 총 개수"],
        ["3,135", "filings analyzed",
         "end-to-end로 분석 완료된 공시 문서 건수"],
        ["92.5 %", "QC pass rate",
         "품질 게이트를 통과한 비율 (2,901 / 3,135)"],
        ["99.0 %", "evidence cite rate",
         "LLM 출력의 각 주장이 원문 청크에 소스 링크된 비율 — 설명가능성 KPI"],
        ["10–15 m", "full corpus embedding",
         "284K 청크 전수 임베딩 소요 시간 (A100 40GB · ~$0.80)"],
        ["30,000+", "LoC",
         "총 코드 라인 (실측 27 services · 4 routers · 14 frontend pages)"],
    ]
    n_rows = []
    for big, mid, small in numbers_data:
        n_rows.append([
            Paragraph(f'<font name="{FONT_BOLD}" size="20" color="#0f0f12">{big}</font>',
                      S_BODY_TIGHT),
            Paragraph(f'<font name="{FONT_BOLD}" size="10">{mid}</font><br/>'
                      f'<font name="{FONT_LIGHT}" size="9" color="#6e6e76">{small}</font>',
                      S_BODY_TIGHT),
        ])
    n_table = Table(n_rows, colWidths=[42 * mm, CONTENT_W - 42 * mm])
    n_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HexColor("#f5f5f7")),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    s.append(n_table)

    s.append(page_break())

    # ────────────── PAGE 04 — 시스템 한눈 다이어그램 ──────────────
    s.extend(section_title("03", "시스템 한눈에 보기",
                           "단일 파이프라인이 5단계로 흐릅니다"))

    s.append(make_pipeline_diagram())
    s.append(Spacer(1, 8))

    s.append(info_box(
        "이 다이어그램이 의미하는 것",
        "<b>P0~P4 는 별도 시스템이 아니라 하나의 데이터가 흘러가는 5단계입니다.</b> "
        "DART API 에서 가져온 PDF 한 건이 → OCR 텍스트 → 청크들 → 1024차원 벡터들 → "
        "검색 결과 → LLM 분석 → 구조화 리포트로 변환됩니다. "
        "이 흐름을 \"end-to-end 파이프라인\" 이라 부르고, 이게 이 시스템의 정체성입니다.",
        fill=C_ORANGE_SOFT, border=C_BGE))

    s.append(Spacer(1, 6))
    s.append(Paragraph("다이어그램 색의 의미", S_H2))

    color_legend = [
        [Paragraph(
            f'<font name="{FONT_BOLD}" color="#6b46c1">■</font>  <b>보라</b>',
            S_BODY_TIGHT),
         Paragraph("로컬 처리 — 외부 전송 없음 (P0 수집 / P1 OCR)", S_BODY_TIGHT)],
        [Paragraph(
            f'<font name="{FONT_BOLD}" color="#ff8c00">■</font>  <b>주황</b>',
            S_BODY_TIGHT),
         Paragraph("RAG 핵심 — 청킹 단계 (검색 품질의 70% 가 결정되는 곳)",
                   S_BODY_TIGHT)],
        [Paragraph(
            f'<font name="{FONT_BOLD}" color="#34a853">■</font>  <b>초록</b>',
            S_BODY_TIGHT),
         Paragraph("GPU 임베딩 — A100 클라우드 (전체 코퍼스 10-15분)",
                   S_BODY_TIGHT)],
        [Paragraph(
            f'<font name="{FONT_BOLD}" color="#4285f4">■</font>  <b>파랑</b>',
            S_BODY_TIGHT),
         Paragraph("LLM 분석 — Insight 경로 (Gemini 2.5 + Supervisor)",
                   S_BODY_TIGHT)],
    ]
    legend_table = Table(color_legend, colWidths=[35 * mm, CONTENT_W - 35 * mm])
    legend_table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    s.append(legend_table)

    s.append(page_break())

    # ────────────── PAGE 05 — 5단계 파이프라인 상세 ──────────────
    s.extend(section_title("04", "5단계 파이프라인 — 각 단계가 하는 일",
                           "각 단계를 \"누가 무엇을 만드는가\" 의 비유로 설명"))

    phase_data = [
        ["P0 · 수집",
         "DART OpenAPI 호출 → corpCode.xml 캐싱 → 개별 공시 다운로드",
         "📚 도서관 사서가 신간을 받아오는 단계"],
        ["P1 · OCR + 정제",
         "PaddleOCR 3.4 로 PDF → 텍스트, BOM/UTF-16 정규화, 한글 자모 복원",
         "📖 사서가 책 내용을 컴퓨터가 읽을 수 있는 글자로 옮기는 단계"],
        ["P2 · 계층형 청킹",
         "문서를 의미 단위(섹션)로 쪼개고, 각 청크에 \"어느 섹션 소속인지\" 헤더 주입",
         "🗂 책에 인덱스 카드를 끼워 \"이 문장이 어느 챕터인지\" 표시"],
        ["P3 · 벡터 임베딩",
         "BGE-M3 모델로 각 청크를 1024차원 숫자 벡터로 변환 → ChromaDB 저장",
         "🧠 \"이 문장의 의미\" 를 좌표 한 점으로 압축해서 도서관 카탈로그에 등록"],
        ["P4 · LLM 분석 + 리포트",
         "사용자 쿼리에 대해 검색 → 리랭킹 → EXAONE 또는 Gemini → JSON → PDF",
         "🎓 사서가 관련 책들을 가져와 분석가에게 넘기고, 분석가가 보고서를 씀"],
    ]
    p_rows = []
    for name, what, analogy in phase_data:
        p_rows.append([
            Paragraph(f'<font name="{FONT_BOLD}" size="11">{name}</font>',
                      S_BODY_TIGHT),
            Paragraph(
                f'<b>실제 구현:</b> {what}<br/>'
                f'<font color="#6e6e76">{analogy}</font>',
                S_BODY_TIGHT),
        ])
    p_table = Table(p_rows, colWidths=[35 * mm, CONTENT_W - 35 * mm])
    p_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HexColor("#f5f5f7")),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    s.append(p_table)

    s.append(Spacer(1, 8))
    s.append(info_box(
        "왜 청킹(P2)이 가장 중요한가",
        "RAG 시스템 검색 품질의 약 <b>70% 는 임베딩 모델이 아니라 청킹 전략</b>에서 결정됩니다. "
        "나머지 30%가 모델·리랭커·쿼리 전략. 그래서 가장 많은 시간이 들어간 곳이 P2 입니다. "
        "특히 '<b>contextual header 주입</b>' 이 핵심입니다 — 청크마다 \"어느 섹션 소속인지\" "
        "라벨을 붙여서 검색이 길을 잃지 않게 합니다.",
        fill=C_ORANGE_SOFT, border=C_BGE))

    s.append(page_break())

    # ────────────── PAGE 06 — Dual LLM 다이어그램 ──────────────
    s.extend(section_title("05", "두 개의 LLM 경로 — Dual Pathway",
                           "BASE = 로컬 EXAONE  ·  INSIGHT = 클라우드 Gemini Pro + Flash"))

    s.append(make_dual_llm_diagram())

    s.append(Spacer(1, 6))
    s.append(info_box(
        "한 문장 핵심",
        "<b>모든 LLM 호출을 하나의 모델로 통일하지 않고, 태스크 성격에 따라 두 경로로 쪼갰습니다.</b> "
        "OCR · 챗봇 · 일반 요약 같은 빈도 높고 환각 위험 낮은 일은 로컬 EXAONE, "
        "재무 전략 판단처럼 빈도 낮고 환각 위험 매우 높은 일만 클라우드 Gemini Pro + Flash 이중 감독.",
        fill=C_BLUE_SOFT, border=C_GEMINI))

    s.append(page_break())

    # ────────────── PAGE 07 — 왜 두 경로 (3축 비교) ──────────────
    s.extend(section_title("06", "왜 LLM 을 두 경로로 쪼갰는가",
                           "단일 LLM 은 비용·프라이버시·환각 리스크 세 축을 동시에 최적화 불가"))

    three_axis = [
        ["", "BASE 태스크\n(OCR, 챗, 요약, 오케스트레이션)",
         "INSIGHT 태스크\n(재무 전략 판단)"],
        ["호출 빈도", "매우 높음 (모든 사용자 인터랙션)",
         "낮음 (분석 요청만)"],
        ["응답 품질 요구", "중 (사실 인용 중심)",
         "상 (전략 추론)"],
        ["환각 리스크", "낮음 (근거가 명시됨)",
         "매우 높음 (추론 기반)"],
        ["프라이버시 요구", "높음 (원문 외부 전송 금지)",
         "중 (집계 정보만 전송)"],
        ["비용 예산", "매우 낮음",
         "허용 (단건 가치가 높음)"],
        ["선택", "Ollama EXAONE 3.5 7.8B\n로컬 · 무료 · 한국어 네이티브",
         "Gemini 2.5 Pro + Flash\n클라우드 · 이중 감독"],
    ]
    cw = [(CONTENT_W - 4) / 3] * 3
    cw[0] = 30 * mm
    cw[1] = (CONTENT_W - 30 * mm) / 2
    cw[2] = (CONTENT_W - 30 * mm) / 2
    ax_table = Table(three_axis, colWidths=cw, rowHeights=[15] + [16] * 6)

    def cell(text, bold=False, size=9, color=C_INK):
        return Paragraph(
            f'<font name="{FONT_BOLD if bold else FONT_REGULAR}" '
            f'size="{size}" color="#{color.hexval()[2:]}">{text.replace(chr(10), "<br/>")}</font>',
            S_BODY_TIGHT)

    # Re-render with paragraphs for proper newline handling
    three_axis_p = [
        [cell(""), cell("BASE 태스크\n(OCR · 챗 · 요약 · 오케스트레이션)", bold=True, size=9),
         cell("INSIGHT 태스크\n(재무 전략 판단)", bold=True, size=9)],
        [cell("호출 빈도", bold=True), cell("매우 높음"), cell("낮음")],
        [cell("응답 품질 요구", bold=True), cell("중 (사실 인용 중심)"),
         cell("상 (전략 추론)")],
        [cell("환각 리스크", bold=True), cell("낮음 — 근거 명시"),
         cell("매우 높음 — 추론 기반")],
        [cell("프라이버시 요구", bold=True), cell("높음 — 원문 외부 금지"),
         cell("중 — 집계만 전송")],
        [cell("비용 예산", bold=True), cell("매우 낮음"),
         cell("허용 — 단건 가치 높음")],
        [cell("→ 선택", bold=True),
         cell("<b>Ollama EXAONE 3.5 7.8B</b><br/>로컬 · 무료 · 한국어 네이티브"),
         cell("<b>Gemini 2.5 Pro + Flash</b><br/>클라우드 · 이중 감독")],
    ]
    ax_table = Table(three_axis_p, colWidths=cw)
    ax_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_GREY_LIGHT),
        ("BACKGROUND", (1, -1), (1, -1), C_PURPLE_SOFT),
        ("BACKGROUND", (2, -1), (2, -1), C_BLUE_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "LEFT"),
    ]))
    s.append(ax_table)

    s.append(Spacer(1, 8))
    s.append(info_box(
        "Counterfactual — \"모두 Gemini 로 통일하면 안 되나?\"",
        "두 가지 이유로 반증됩니다. ① <b>월 API 비용이 약 2 order-of-magnitude (100배) 증가</b>합니다. "
        "② <b>OCR 원문(개인정보 포함 가능)이 외부로 노출</b>됩니다. "
        "단일 모델 통일은 운영 단순성 1점을 얻기 위해 비용과 프라이버시 두 점을 잃는 거래입니다.",
        fill=HexColor("#fff8e1"), border=HexColor("#f9a825")))

    s.append(page_break())

    # ────────────── PAGE 08 — Supervisor 5-step ──────────────
    s.extend(section_title("07", "Supervisor 5-step 프로토콜",
                           "Insight 경로의 환각 방어막 — 독립된 Flash 인스턴스가 Pro 의 출력을 사후 감독"))

    s.append(make_supervisor_diagram())

    s.append(Spacer(1, 6))
    s.append(Paragraph("왜 한 모델로는 부족한가", S_H2))
    s.append(Paragraph(
        "<b>① Self-Consistency 는 편향을 못 잡는다.</b> "
        "같은 모델이 N 번 샘플링해서 합의를 보는 방식은 훈련 분포 내 편향을 교정하지 못합니다. "
        "모델이 일관되게 틀린 답을 낼 수 있습니다.",
        S_BODY))
    s.append(Paragraph(
        "<b>② Overconfident Hallucination.</b> "
        "재무 판단은 특히 과확신 환각이 잦습니다. \"이 종목은 저평가\" 같은 표현이 근거 없이 나올 때가 있고, "
        "단일 모델은 자기 출력의 신뢰도를 객관적으로 calibrate 하지 못합니다.",
        S_BODY))
    s.append(Paragraph(
        "<b>③ 해결 — 독립 supervisor.</b> "
        "다른 인스턴스(Gemini 2.5 Flash)가 Pro 의 출력을 평가합니다. "
        "추론 체인이 분리되어 있고, supervisor 전용 프롬프트로 역할이 다르며, 독립 API 세션입니다.",
        S_BODY))

    s.append(Spacer(1, 8))
    s.append(info_box(
        "Supervisor 가 추가하는 3가지 필드",
        "Pro 가 5축 JSON(insight_text, investment_thesis, market_context, risk_factors, "
        "strategic_action) 을 만들면, Flash 가 다음 3가지를 덧붙입니다 — "
        "<b>calibrated_confidence</b> (AXIOM/CONSENSUS/INFERENCE/SPECULATION/EXPLORATION), "
        "<b>hidden_risks</b> (Pro 가 놓친 블라인드 스팟), "
        "<b>counterfactual_notes</b> (이 판단이 틀리려면 무엇이 참이어야 하는가).",
        fill=C_RED_SOFT, border=C_SUPER))

    s.append(page_break())

    # ────────────── PAGE 09 — 기술 스택 ──────────────
    s.extend(section_title("08", "기술 스택 한 페이지",
                           "Backend / Frontend / ML / Infra 4개 레이어"))

    stack = [
        ["BACKEND",
         "FastAPI 0.135  ·  SQLAlchemy 2.0  ·  Pydantic v2\n"
         "PostgreSQL 16 (psycopg 3)  ·  ChromaDB  ·  Redis\n"
         "PaddleOCR 3.4  ·  sentence-transformers  ·  BAAI bge-m3\n"
         "Ollama (EXAONE 3.5 7.8B)  ·  Vertex AI (Gemini 2.5 Pro/Flash)\n"
         "torch 2.x (CUDA 12.1)  ·  JWT + bcrypt"],
        ["FRONTEND",
         "React 18  ·  Vite 6  ·  React Router 6\n"
         "Axios  ·  Lucide React  ·  JSZip"],
        ["ML / GPU",
         "BGE-M3 (1024-dim)  ·  Cross-encoder reranking\n"
         "A100 40GB · H100 (cloud rental)\n"
         "QLoRA fine-tuning (Qwen 2.5 7B target)\n"
         "vLLM serving  ·  bitsandbytes quantization"],
        ["INFRA",
         "uvicorn  ·  systemd  ·  Docker (dev)\n"
         "RunPod  ·  Lambda Labs  ·  Vast.ai"],
    ]
    stack_p = []
    for name, body in stack:
        stack_p.append([
            Paragraph(f'<font name="{FONT_BOLD}" size="11">{name}</font>',
                      S_BODY_TIGHT),
            Paragraph(
                f'<font name="{FONT_REGULAR}" size="9.5">'
                f'{body.replace(chr(10), "<br/>")}</font>',
                S_BODY_TIGHT),
        ])
    stack_table = Table(stack_p, colWidths=[28 * mm, CONTENT_W - 28 * mm])
    stack_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HexColor("#0f0f12")),
        ("TEXTCOLOR", (0, 0), (0, -1), white),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
    ]))
    s.append(stack_table)

    s.append(Spacer(1, 8))
    s.append(Paragraph("선택 근거 1줄 요약", S_H2))
    why = [
        ["BGE-M3 (vs OpenAI)",
         "한국어 코퍼스 90%+ 환경에서 구조적 품질 우위 (D01 참조)"],
        ["EXAONE + Gemini 분리",
         "비용·프라이버시·환각 리스크 3축 동시 최적화 (D02 참조)"],
        ["ChromaDB (vs pgvector)",
         "284K 청크 규모에서 1인 운영 편의 우위 (D04 참조, 1M+ 시 재평가)"],
        ["A100 클라우드 (vs 로컬 RTX 5070)",
         "PyTorch sm_120 미지원으로 강제 피벗 (P02 참조)"],
        ["Ollama 런타임",
         "1인 운영에서 모델 교체·버전 관리 편의 (vLLM 대비 단순성)"],
    ]
    why_p = []
    for k, v in why:
        why_p.append([
            Paragraph(f'<b>{k}</b>', S_BODY_TIGHT),
            Paragraph(v, S_BODY_TIGHT),
        ])
    why_table = Table(why_p, colWidths=[60 * mm, CONTENT_W - 60 * mm])
    why_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    s.append(why_table)

    s.append(page_break())

    # ────────────── PAGE 10 — 실제 코드 카운트 (검증된 숫자) ──────────────
    s.extend(section_title("09", "실제 코드 카운트 — 워크스페이스 정독 검증",
                           "이 페이지의 모든 숫자는 코드 디렉토리를 직접 세서 확인한 값입니다"))

    counts = [
        ["27", "backend services",
         "backend/services/*.py 실측 — agent_memory부터 vlm_service까지"],
        ["4", "backend routers",
         "admin · auth · documents · panel"],
        ["1", "agent orchestrator class",
         "AgentOrchestrator — backend/agents/orchestrator.py"],
        ["7", "prompt builder roles",
         "router · planner · judge · synthesizer · critic · reviser · direct_answer"],
        ["14", "frontend pages",
         "AdminDashboard · AdminDocuments · AdminUsers · AdminRegisterPage · "
         "DocumentDetail · ForgotPassword · HomePage · LoginPage · MyPage · "
         "RegisterPage · ResetPassword · UploadPage · VerifyEmail · VerifyPasswordChange"],
        ["4", "frontend components",
         "ChatBot · Navbar · ProtectedRoute · SideDecorations"],
        ["1", "Omega-Prime supervisor 시스템 프롬프트",
         "backend/prompts/omega_prime_civicflow.md (내부 rubric 비공개)"],
    ]
    c_rows = []
    for n, lbl, det in counts:
        c_rows.append([
            Paragraph(f'<font name="{FONT_BOLD}" size="22">{n}</font>',
                      S_BODY_TIGHT),
            Paragraph(
                f'<b>{lbl}</b><br/>'
                f'<font name="{FONT_LIGHT}" size="8.5" color="#6e6e76">{det}</font>',
                S_BODY_TIGHT),
        ])
    c_table = Table(c_rows, colWidths=[24 * mm, CONTENT_W - 24 * mm])
    c_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HexColor("#f5f5f7")),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    s.append(c_table)

    s.append(Spacer(1, 8))
    s.append(info_box(
        "정직 노트 — README와 약간 다른 부분",
        "공개 README 는 \"4 agents (retrieval/analysis/validation/synthesis)\" 라고 표현하지만, "
        "실제 코드는 <b>1 개의 AgentOrchestrator 가 7 개의 prompt 역할(router/planner/judge/synthesizer"
        "/critic/reviser/direct_answer)을 실행</b>하는 구조입니다. README 의 4 agents 표현은 "
        "외부 설명용 단순화이며, 본질은 \"여러 역할을 가진 추론 체인\" 입니다. "
        "발표에서는 \"개념적으로 4 단계 에이전트, 구현은 7 개 prompt role\" 이라고 답하면 "
        "정확합니다. <br/><br/>"
        "마찬가지로 README 는 \"12 pages\" 라 적었지만 실측은 <b>14 pages</b> 입니다 "
        "(이메일 인증 · 비밀번호 변경 페이지 추가).",
        fill=HexColor("#fff8e1"), border=HexColor("#f9a825")))

    s.append(page_break())

    # ────────────── PAGE 11 — DECISION 01 ──────────────
    s.extend(section_title("10  ·  DECISION 01",
                           "BGE-M3 over OpenAI text-embedding-3",
                           "임베딩 모델 선택 — 왜 OpenAI 가 아닌 BGE-M3 인가"))

    s.append(info_box(
        "한 줄 핵심",
        "본 코퍼스는 한국어 90%+ (DART 공시). "
        "OpenAI text-embedding-3-large 는 한국어 검색에서 BGE-M3 대비 구조적 품질 열위 — "
        "MIRACL · MTEB-KO 다국어 벤치마크 + 내부 측정 일관.",
        fill=C_PURPLE_SOFT, border=C_EXAONE))

    s.append(Spacer(1, 6))
    s.append(Paragraph("Calibrated Confidence", S_H2))

    conf_rows = [
        ["AXIOM", "[99%]",
         "본 코퍼스는 한국어 90%+ — OpenAI 임베딩이 한국어 검색에서 구조적 열위 (벤치마크 일관)"],
        ["CONSENSUS", "[92%]",
         "BGE-M3 multi-vector + contextual header 조합이 긴 규제 공시 검색에서 더 견고"],
        ["INFERENCE", "[78%]",
         "Vector + BM25 + metadata filter 3-way hybrid 가 공시의 구조화 표현에 특히 효과적"],
    ]
    conf_p = []
    for tag, pct, body in conf_rows:
        conf_p.append([
            Paragraph(f'<font name="{FONT_BOLD}" color="white" size="9">{tag}</font>',
                      S_BODY_TIGHT),
            Paragraph(f'<font name="{FONT_BOLD}" color="white" size="9">{pct}</font>',
                      S_BODY_TIGHT),
            Paragraph(body, S_BODY_TIGHT),
        ])
    conf_t = Table(conf_p, colWidths=[24 * mm, 18 * mm, CONTENT_W - 42 * mm])
    conf_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (1, -1), C_INK),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    s.append(conf_t)

    s.append(Spacer(1, 8))
    s.append(Paragraph("Trade-off 매트릭스", S_H2))

    trade_data = [
        ["축", "OpenAI text-embedding-3", "BGE-M3"],
        ["한국어 품질", "중", "상"],
        ["API 호출 간편성", "상", "중 (로컬 GPU 필요)"],
        ["비용 (284K 청크)", "~$0.50", "$0.80 (A100 렌탈)"],
        ["프라이버시", "외부 전송", "로컬 완결"],
        ["커스터마이징", "없음", "차원·normalize·모델 교체 가능"],
    ]
    trade_p = []
    for row in trade_data:
        trade_p.append([cell(c, bold=(row == trade_data[0])) for c in row])
    cw_t = [40 * mm, (CONTENT_W - 40 * mm) / 2, (CONTENT_W - 40 * mm) / 2]
    trade_t = Table(trade_p, colWidths=cw_t)
    trade_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_GREY_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    s.append(trade_t)

    s.append(Spacer(1, 8))
    s.append(info_box(
        "Counterfactual",
        "<b>\"만약 코퍼스가 영어 70% 라면?\"</b> → OpenAI 우위로 역전. "
        "BGE-M3 는 한국어 맥락 한정 최적해입니다. <br/>"
        "<b>\"임베딩 비용이 운영비 50% 를 넘는다면?\"</b> → 그래도 BGE-M3 우위. "
        "A100 렌탈은 회당 $1 미만이고 재임베딩은 월 1회 이하.",
        fill=HexColor("#fff8e1"), border=HexColor("#f9a825")))

    s.append(page_break())

    # ────────────── PAGE 12 — DECISION 02 ──────────────
    s.extend(section_title("11  ·  DECISION 02",
                           "EXAONE 3.5 (base) + Gemini 2.5 (insight) split",
                           "왜 LLM 을 하나로 통일하지 않고 두 경로로 쪼갰는가"))

    s.append(info_box(
        "한 줄 핵심",
        "재무 전략 판단은 환각 리스크가 구조적으로 가장 높은 영역. "
        "단일 모델은 자기 실수를 검출하지 못함. "
        "OCR · 챗 · 요약은 환각 리스크가 낮고 privacy/비용/지연시간이 중요 → 로컬 EXAONE 종합 우위.",
        fill=C_PURPLE_SOFT, border=C_EXAONE))

    s.append(Spacer(1, 6))
    s.append(Paragraph("Calibrated Confidence", S_H2))

    conf_d2 = [
        ["AXIOM", "[99%]", "재무 전략 판단은 환각 리스크가 구조적으로 가장 높은 영역"],
        ["CONSENSUS", "[88%]",
         "Gemini 2.5 Pro 는 한국어 금융 맥락 구조화 JSON 품질 우위 (Pydantic schema 기준)"],
        ["INFERENCE", "[72%]",
         "OCR · 챗 · 요약은 환각 리스크 낮고 비용·프라이버시 중요 → EXAONE 종합 우위"],
    ]
    conf_p2 = []
    for tag, pct, body in conf_d2:
        conf_p2.append([
            Paragraph(f'<font name="{FONT_BOLD}" color="white" size="9">{tag}</font>',
                      S_BODY_TIGHT),
            Paragraph(f'<font name="{FONT_BOLD}" color="white" size="9">{pct}</font>',
                      S_BODY_TIGHT),
            Paragraph(body, S_BODY_TIGHT),
        ])
    t2 = Table(conf_p2, colWidths=[24 * mm, 18 * mm, CONTENT_W - 42 * mm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (1, -1), C_INK),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    s.append(t2)

    s.append(Spacer(1, 6))
    s.append(Paragraph("대안 검토 — 왜 Gemini 인가", S_H2))
    s.append(Paragraph(
        "<b>· Claude 3.5 Sonnet</b> — 품질 유사하나 Vertex 대비 엔터프라이즈 인프라 기능 열위<br/>"
        "<b>· GPT-4o</b> — 한국어 구조화 JSON 품질에서 Gemini 대비 일관성 낮음<br/>"
        "<b>· Llama 3.1 70B (로컬)</b> — 하드웨어 요구사항이 1 인 운영 범위 초과",
        S_BODY))

    s.append(Spacer(1, 4))
    s.append(Paragraph("대안 검토 — 왜 EXAONE 인가", S_H2))
    s.append(Paragraph(
        "<b>· Qwen 2.5 7B</b> — 품질 우수하나 한국어 문체 이질감<br/>"
        "<b>· Solar 10.7B</b> — 한국어 우수하나 Ollama 생태계 약세<br/>"
        "<b>· Llama 3.1 8B</b> — 한국어 일관성 부족<br/>"
        "<b>→ EXAONE 3.5 (LG AI Research)</b> — 한국어 네이티브 + Ollama 호환 + 상업적 라이선스 허용",
        S_BODY))

    s.append(page_break())

    # ────────────── PAGE 13 — DECISION 03 ──────────────
    s.extend(section_title("12  ·  DECISION 03",
                           "Dual-engine supervision for insight path",
                           "왜 Insight 경로에는 두 개의 LLM 인스턴스가 필요한가"))

    s.append(info_box(
        "한 줄 핵심",
        "단일 LLM 은 자기 편향을 외부 레이어 없이 교정하지 못함. "
        "Self-consistency 는 하한선이며, 진정한 calibration 은 독립 supervisor 에서만 나옴.",
        fill=C_RED_SOFT, border=C_SUPER))

    s.append(Spacer(1, 6))
    s.append(Paragraph("Calibrated Confidence", S_H2))

    conf_d3 = [
        ["CONSENSUS", "[90%]",
         "단일 LLM 은 외부 레이어 없이 자기 편향을 교정 못 함 — self-consistency 는 하한선"],
        ["INFERENCE", "[80%]",
         "Flash 독립 인스턴스로 Pro 의 출력을 5-step 사후 감독 → 3축 재검증"],
        ["EXPLORATION", "[55%]",
         "5-step protocol 의 정량 효과는 대규모 ablation study 미비. "
         "정성적 개선 + error taxonomy reduction 만 관측 — [SPECULATION] 플래그 유지"],
    ]
    conf_p3 = []
    for tag, pct, body in conf_d3:
        conf_p3.append([
            Paragraph(f'<font name="{FONT_BOLD}" color="white" size="9">{tag}</font>',
                      S_BODY_TIGHT),
            Paragraph(f'<font name="{FONT_BOLD}" color="white" size="9">{pct}</font>',
                      S_BODY_TIGHT),
            Paragraph(body, S_BODY_TIGHT),
        ])
    t3 = Table(conf_p3, colWidths=[26 * mm, 18 * mm, CONTENT_W - 44 * mm])
    t3.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (1, -1), C_INK),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    s.append(t3)

    s.append(Spacer(1, 6))
    s.append(info_box(
        "Counterfactual — \"같은 Gemini 계열인데 독립성이 진짜 있는가?\"",
        "<b>부분적 타당.</b> 훈련 데이터 공유 가능성은 있음. 그러나 ① Pro 와 Flash 는 파라미터 "
        "스케일이 다름 → 추론 체인 분기, ② Flash 는 supervisor 전용 프롬프트로 역할 분리, "
        "③ 독립 API 세션 — 컨텍스트 공유 없음. <br/><br/>"
        "<b>완전 독립이 필요하면</b> Claude 또는 GPT 계열 혼합이 이상적. "
        "현재는 운영 복잡도 trade-off 로 Gemini 이중 구성 유지.",
        fill=HexColor("#fff8e1"), border=HexColor("#f9a825")))

    s.append(Spacer(1, 6))
    s.append(Paragraph("발표 시 강조 포인트", S_H2))
    s.append(Paragraph(
        "이 결정은 시스템 전체에서 <b>가장 정직한 confidence 라벨</b>을 가진 결정입니다. "
        "EXPLORATION [55%] 라는 라벨이 의도적으로 들어가 있어요. "
        "이는 \"이 supervisor 가 정량적으로 효과 입증되었나?\" 라는 질문에 \"아직 ablation study 없음\" "
        "이라고 솔직히 답하기 위한 장치입니다. <b>이런 라벨이 들어 있다는 것 자체</b>가 "
        "면접관에게 \"이 사람은 모르는 것을 모른다고 말한다\" 라는 신호입니다.",
        S_BODY))

    s.append(page_break())

    # ────────────── PAGE 14 — DECISION 04 ──────────────
    s.extend(section_title("13  ·  DECISION 04",
                           "ChromaDB over pgvector (at this scale)",
                           "284K 청크 규모에서 왜 pgvector 가 아닌 ChromaDB 인가"))

    s.append(info_box(
        "한 줄 핵심",
        "284K 청크 규모는 pgvector 로도 처리 가능. 하지만 "
        "<b>1 인 개발 속도 · persistent client 운영 편의 · 메타데이터 DSL 편리성</b> "
        "에서 ChromaDB 우위. 1M+ 스케일에서는 재평가 필요.",
        fill=C_ORANGE_SOFT, border=C_BGE))

    s.append(Spacer(1, 6))
    s.append(Paragraph("비교 매트릭스", S_H2))

    chroma_data = [
        ["기준", "ChromaDB", "pgvector", "Qdrant"],
        ["설치 복잡도", "★★★ persistent client", "★★ PG 확장", "★★ Docker"],
        ["메타데이터 DSL", "Python dict (직관)", "SQL WHERE", "JSON filter"],
        ["배포 단순성", "파일 기반", "PG 서버 의존", "컨테이너"],
        ["백업", "rsync", "pg_dump", "스냅샷"],
        ["1M+ 확장성", "약세", "강세", "강세"],
        ["1인 개발 생산성", "최고", "중", "중"],
    ]
    cw_c = [38 * mm, (CONTENT_W - 38 * mm) / 3, (CONTENT_W - 38 * mm) / 3,
            (CONTENT_W - 38 * mm) / 3]
    chroma_p = []
    for row in chroma_data:
        chroma_p.append([cell(c, bold=(row == chroma_data[0])) for c in row])
    chroma_t = Table(chroma_p, colWidths=cw_c)
    chroma_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_GREY_LIGHT),
        ("BACKGROUND", (1, 1), (1, -1), C_ORANGE_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    s.append(chroma_t)

    s.append(Spacer(1, 8))
    s.append(info_box(
        "Migration trigger — Phase 5 로드맵에 포함된 조건",
        "다음 셋 중 하나가 발생하면 pgvector 마이그레이션 검토 — "
        "① 청크 수가 <b>500K 초과</b>, "
        "② 검색 p95 가 <b>150ms 초과</b>, "
        "③ <b>트랜잭션 통합</b>이 필요할 때 (PG 와 메타데이터 단일 소스화). <br/><br/>"
        "이 결정이 정직한 이유: \"지금은 ChromaDB 가 맞지만, 이게 영원히 맞다고 주장하지 않는다\".",
        fill=HexColor("#fff8e1"), border=HexColor("#f9a825")))

    s.append(page_break())

    # ────────────── PAGE 15 — 5개 어려운 문제 ──────────────
    s.extend(section_title("14", "해결한 5가지 어려운 문제",
                           "이력서에는 못 쓰지만 진짜 엔지니어링 시간이 흘러간 곳"))

    problems = [
        ["P01", "BGE-M3 의 세 가지 silent failure",
         "HF 503 → mean-pooling fallback / max_seq=512 truncation / contextual header 누락. "
         "<b>세 가지 모두 에러 로그를 남기지 않는다.</b> "
         "검색 품질의 통계적 저하로만 감지됨. 정답 셋 기반 모니터링 + startup pre-check + "
         "fallback 경로 제거로 해결."],
        ["P02", "PyTorch sm_120 불호환 (RTX 5070)",
         "PyTorch 2.x stable 빌드가 RTX 5070 (compute capability 12.0, sm_120) 미인식. "
         "16시간 디버깅 → 우회 실패 → <b>A100 클라우드로 피벗</b>. 결과적으로 더 빠르고 더 싸짐 "
         "(10-15분 / $0.80). 교훈: 최신 GPU 는 ML 에서 리스크."],
        ["P03", "Gemini 4-key pool rate limiting",
         "Insight 경로에서 단일 키로는 peak 시간 처리량 부족. <b>4 개 API 키 × 지수 백오프 × "
         "TPM 분배 (500K) × 자동 페일오버</b>. 키 수 선택 근거 · 백오프 계수 · 페일오버 트리거는 "
         "비공개 운영 파라미터."],
        ["P04", "700 MB OCR 단일 번들 → OOM",
         "PaddleOCR 직접 로드 시 100+ 페이지 공시가 700 MB 단일 번들로 메모리에 올라와 OOM. "
         "<b>스트리밍 청킹</b> (페이지별 OCR → flush → del + gc.collect()) + BOM/UTF-16 정규화 "
         "+ NFC 한글 복원으로 해결."],
        ["P05", "75°C 로컬 CPU 하드캡",
         "1인 개발 환경에서 로컬 머신은 유일한 워크스테이션. <b>장시간 배치는 75°C 하드캡 + "
         "자동 throttle / 클라우드 오프로드</b>. 하드웨어 수명이 개발자 시간만큼 비싼 자원이라는 정책."],
    ]
    p_rows = []
    for code, title, body in problems:
        p_rows.append([
            Paragraph(f'<font name="{FONT_BOLD}" size="11" color="#ea4335">{code}</font>',
                      S_BODY_TIGHT),
            Paragraph(
                f'<font name="{FONT_BOLD}" size="10">{title}</font><br/>'
                f'<font name="{FONT_REGULAR}" size="9">{body}</font>',
                S_BODY_TIGHT),
        ])
    p_t = Table(p_rows, colWidths=[16 * mm, CONTENT_W - 16 * mm])
    p_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), C_RED_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    s.append(p_t)

    s.append(Spacer(1, 6))
    s.append(info_box(
        "발표 시 활용법",
        "5가지 중 청중이 \"진짜 어려웠던 문제 하나만 얘기해 달라\" 고 하면 <b>P01 (silent failure)</b> "
        "을 추천합니다. 이유는 ① 가장 정량적, ② 에러 없이 품질만 떨어지는 미묘함을 설명할 수 있음, "
        "③ \"테스트로 못 잡고 모니터링으로만 잡힌다\" 라는 production engineer 의 사고를 보여줄 수 있음.",
        fill=HexColor("#fff8e1"), border=HexColor("#f9a825")))

    s.append(page_break())

    # ────────────── PAGE 16 — Phase별 진행 ──────────────
    s.extend(section_title("15", "Phase 1 → Phase 4 — 5개월 빌드 스토리",
                           "각 Phase 가 어떤 문제를 해결하고 다음 Phase 로 넘어갔는가"))

    phase_journey = [
        ["Phase 1 · Foundation",
         "Ingest + OCR",
         "DART OpenAPI 연동, corpCode.xml 캐싱, PaddleOCR 3.4 기반 텍스트 추출, "
         "BOM/UTF-16/NFC 정규화 파이프라인 구축. 출력: 정제된 raw_text + 섹션 메타.",
         "P04 (700MB OCR 번들)"],
        ["Phase 2 · Chunking",
         "Hierarchical Chunking",
         "L0(문서) → L1(섹션) → L2(서브섹션) → L3(512 토큰 청크) 4단계. "
         "각 청크에 상위 헤더 prepend + overlap 20%. 출력: ChromaDB metadata 호환 청크 스키마.",
         "P01 (silent failure 3종)"],
        ["Phase 3 · A100 Embedding",
         "Cloud GPU pivot",
         "로컬 RTX 5070 (sm_120) 미지원 → 16시간 우회 실패 → A100 40GB 클라우드 피벗. "
         "284,149 청크 → 10-15분 → $0.80. 출력: omega_civicflow.db (indexed_at 업데이트) + chroma_db/.",
         "P02 (sm_120 불호환)"],
        ["Phase 4 · Live",
         "RAG + Dual LLM",
         "사용자 쿼리 → 3-way hybrid 검색 (vector + BM25 + metadata) → cross-encoder rerank → "
         "라우터가 EXAONE 또는 Gemini Pro+Flash 로 분기 → 5축 JSON → PDF 리포트. "
         "운영 지표: 3,135 분석 / 92.5% pass / 99.0% cite.",
         "P03 (Gemini rate limit) · P05 (75°C 캡)"],
    ]
    ph_p = []
    for ph, sub, body, related in phase_journey:
        ph_p.append([
            Paragraph(
                f'<font name="{FONT_BOLD}" size="10">{ph}</font><br/>'
                f'<font name="{FONT_LIGHT}" size="8" color="#6e6e76">{sub}</font>',
                S_BODY_TIGHT),
            Paragraph(
                f'<font name="{FONT_REGULAR}" size="9">{body}</font><br/>'
                f'<font name="{FONT_LIGHT}" size="8" color="#ea4335">관련 문제: {related}</font>',
                S_BODY_TIGHT),
        ])
    ph_t = Table(ph_p, colWidths=[40 * mm, CONTENT_W - 40 * mm])
    ph_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HexColor("#f5f5f7")),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    s.append(ph_t)

    s.append(Spacer(1, 6))
    s.append(info_box(
        "스토리텔링 팁",
        "Phase 1 → 2 → 3 → 4 의 흐름은 단순한 \"기능 추가\" 가 아니라 "
        "<b>각 Phase 가 자기 단계의 silent failure 를 직면하고 해결한 결과로 다음 Phase 가 가능해진</b> "
        "구조입니다. 발표할 때 \"각 Phase 마다 가장 어려웠던 문제\" 를 함께 언급하면 "
        "단순 기술 나열이 아닌 의사결정 서사가 됩니다.",
        fill=C_ORANGE_SOFT, border=C_BGE))

    s.append(page_break())

    # ────────────── PAGE 17 — 공개되지 않은 5가지 ──────────────
    s.extend(section_title("16", "공개되지 않은 5가지 — IP 방어 경계",
                           "발표에서 \"왜 이건 보여주지 않는가\" 라는 질문에 정직하게 답하기 위한 페이지"))

    secrets = [
        ["01", "Omega-Prime Supervisor 시스템 프롬프트",
         "Primary 추론 엔진(Gemini 2.5 Pro) 의 출력을 독립 감독하는 2차 레이어. "
         "STEP 1-5 의 상위 구조는 공개되지만 각 STEP 내부의 판정 기준 · 거부 패턴 · 예시 · rubric 은 "
         "비공개. <b>이유:</b> 환각 감독 로직은 단순 카피가 가능하며 이 메커니즘이 시스템의 방어벽이기 때문."],
        ["02", "V-MASK Intelligence Manifold",
         "금융 공시의 전략적 곡률을 추정하는 3개 수학 신호 모듈 — "
         "Eigen-Sensor (Polaris Vector / 고유값 분해) · Laplace Shield (전달함수 기반 step response) · "
         "Taylor Predictor (2차 테일러 전개). <b>모듈 이름과 역할은 공개</b>. "
         "파라미터 · 정규화 · weight schedule · rejection threshold 는 비공개. "
         "<b>이유:</b> 수학적 형식 자체가 IP."],
        ["03", "Cross-encoder 리랭킹 레시피",
         "BGE-M3 1차 검색 이후의 리랭킹 체인. 모델 선택 · 캐싱 정책 · on/off 토글 조건 · "
         "score fusion 공식은 비공개."],
        ["04", "Multi-agent 오케스트레이션 프롬프트",
         "<code>retrieval · analysis · validation · synthesis</code> 4 개 에이전트의 이름과 역할은 공개, "
         "각각의 시스템 프롬프트와 상호 호출 규칙은 비공개. "
         "(<b>실제 구현은 1 개 Orchestrator + 7 개 prompt role</b> 인데, 외부에는 4-agent 추상화로 표현)"],
        ["05", "Insight 5축 스키마 검증 루프",
         "5축(<code>insight_text · investment_thesis · market_context · risk_factors · "
         "strategic_action</code>) 의 존재는 공개. 스키마를 반복적으로 강제 · 재시도 · 수정하는 "
         "검증 루프는 비공개."],
    ]
    sec_p = []
    for n, title, body in secrets:
        sec_p.append([
            Paragraph(f'<font name="{FONT_BOLD}" size="10" color="#0f0f12">▓ {n}</font>',
                      S_BODY_TIGHT),
            Paragraph(
                f'<font name="{FONT_BOLD}" size="9.5">{title}</font><br/>'
                f'<font name="{FONT_REGULAR}" size="8.5">{body}</font>',
                S_BODY_TIGHT),
        ])
    sec_t = Table(sec_p, colWidths=[18 * mm, CONTENT_W - 18 * mm])
    sec_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), C_INK),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    s.append(sec_t)

    s.append(Spacer(1, 6))
    s.append(info_box(
        "발표용 답변 템플릿",
        "<b>Q: \"이거 코드 보여주실 수 있어요?\"</b> → "
        "\"공개 README 와 vault 까지는 보여드릴 수 있고, 5 개 항목(Omega-Prime supervisor 프롬프트, "
        "V-MASK 모듈 파라미터, 리랭킹 레시피, multi-agent 프롬프트, 5축 검증 루프)은 미팅에서 "
        "전체를 실연하지만 저장소에는 기록하지 않습니다. <b>코드가 아니라 의사결정의 체계가 "
        "deliverable</b> 이라는 것이 이 프로젝트의 입장입니다.\"",
        fill=HexColor("#fff8e1"), border=HexColor("#f9a825")))

    s.append(page_break())

    # ────────────── PAGE 18 — 예상 Q&A + 마무리 ──────────────
    s.extend(section_title("17", "예상 Q&A 10가지 — 빠른 답변 준비",
                           "면접관이 자주 묻는 질문과 1-2문장 답변 가이드"))

    qa = [
        ["Q1", "왜 OpenAI 임베딩 안 쓰셨어요?",
         "한국어 90%+ 코퍼스에서 BGE-M3 가 MIRACL · MTEB-KO 기준 구조적 우위. (D01)"],
        ["Q2", "왜 ChromaDB? pgvector 더 익숙하지 않아요?",
         "284K 청크에선 1인 개발 속도 우위. 1M+ 또는 트랜잭션 필요 시 pgvector 마이그레이션 로드맵 있음. (D04)"],
        ["Q3", "이거 진짜 혼자 만드셨어요?",
         "5개월 풀스택, 27 services / 4 routers / 14 frontend pages. 팀 환산 3-5 engineer-month."],
        ["Q4", "수치들 어떻게 검증하세요?",
         "92.5% QC pass 와 99.0% cite rate 는 정답 셋 기반 자동 측정. 재현 데이터셋은 비공개 저장소."],
        ["Q5", "Supervisor 가 진짜 환각을 줄여요?",
         "정성적 개선 + error taxonomy reduction 은 관측. 정량 ablation study 는 미비 — [SPECULATION 55%] "
         "라벨로 정직하게 표기. (D03)"],
        ["Q6", "운영 비용은 얼마나 드나요?",
         "임베딩은 월 1회 ~$1 미만 (병목 아님). LLM API 비용이 가장 큼 (Insight 경로). "
         "그래서 base 경로를 로컬 EXAONE 으로 분리. (D02)"],
        ["Q7", "팀이 똑같이 만들면 시간 얼마나?",
         "average-to-senior 팀 기준 3-5 engineer-month. 솔로는 5개월 걸렸음."],
        ["Q8", "왜 도메인이 금융이에요?",
         "원래 Phase 0 에서는 공공 민원 문서로 시작 (CivicFlow 이름의 어원). Phase 2 부터 DART 금융 공시로 확장."],
        ["Q9", "Phase 5 계획은요?",
         "① pgvector 마이그레이션 검토 (1M+ 스케일 대비), ② QLoRA 파인튜닝 (Qwen 2.5 7B 타깃), "
         "③ Supervisor 5-step ablation study."],
        ["Q10", "코드 보여주실 수 있어요?",
         "공개 README + vault 는 가능. 5 개 항목 (Supervisor 프롬프트 / V-MASK 파라미터 / 리랭킹 레시피 / "
         "agent 프롬프트 / 5축 검증 루프) 은 미팅에서 실연하되 저장소에는 기록하지 않음."],
    ]
    qa_p = []
    for q_num, q, a in qa:
        qa_p.append([
            Paragraph(f'<font name="{FONT_BOLD}" size="9" color="#4285f4">{q_num}</font>',
                      S_BODY_TIGHT),
            Paragraph(
                f'<font name="{FONT_BOLD}" size="9">{q}</font><br/>'
                f'<font name="{FONT_REGULAR}" size="8.5">{a}</font>',
                S_BODY_TIGHT),
        ])
    qa_t = Table(qa_p, colWidths=[12 * mm, CONTENT_W - 12 * mm])
    qa_t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), C_BLUE_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, C_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    s.append(qa_t)

    s.append(Spacer(1, 10))
    s.append(horizontal_rule(thickness=1.0, color=C_INK))
    s.append(Spacer(1, 6))
    s.append(Paragraph(
        '<font name="MalgunBold" size="14">Ω  NODE OMEGA-PRIME</font>',
        ParagraphStyle("end_t", fontName=FONT_BOLD, fontSize=14,
                       leading=18, alignment=TA_CENTER, textColor=C_INK)))
    s.append(Paragraph(
        "Energy (E)   ·   Entropy (S)   ·   Efficiency (η)",
        ParagraphStyle("end_s", fontName=FONT_LIGHT, fontSize=10,
                       leading=14, alignment=TA_CENTER,
                       textColor=C_GREY_MID, spaceAfter=4)))
    s.append(Paragraph(
        "최소 entropy 로 최대 결정 품질 — 한 문장이 열 문장보다 낫다",
        ParagraphStyle("end_q", fontName=FONT_LIGHT, fontSize=9,
                       leading=14, alignment=TA_CENTER,
                       textColor=C_GREY_MID)))

    return s


# ─────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────
def main():
    output_path = Path(r"C:\Users\hibou\Omega_CivicFlow_v4\Omega_CivicFlow_v4_발표학습자료.pdf")

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
        title="Omega CivicFlow v4 — 발표용 학습 자료",
        author="Omega-Prime",
        subject="Workspace structure learning material for presentation",
    )

    frame = Frame(
        MARGIN_L, MARGIN_B, CONTENT_W, CONTENT_H,
        leftPadding=0, bottomPadding=0,
        rightPadding=0, topPadding=0,
        id="main",
    )
    template = PageTemplate(id="all", frames=[frame], onPage=header_footer)
    doc.addPageTemplates([template])

    story = build_story()
    doc.build(story)

    print(f"[OK] Generated: {output_path}")
    print(f"     Size: {output_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
