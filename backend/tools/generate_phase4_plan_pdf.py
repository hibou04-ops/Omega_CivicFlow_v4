# -*- coding: utf-8 -*-
"""
Generate Phase 4 plan PDF (한글) using reportlab + Windows malgun.ttf font.
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT


# ── Korean font registration ──
pdfmetrics.registerFont(TTFont("Malgun", "C:/Windows/Fonts/malgun.ttf"))
pdfmetrics.registerFont(TTFont("MalgunBd", "C:/Windows/Fonts/malgunbd.ttf"))

OUT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Phase4_Plan.pdf"))


def make_styles():
    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        name="KoBase",
        fontName="Malgun",
        fontSize=10,
        leading=15,
        textColor=black,
        alignment=TA_LEFT,
    )
    title = ParagraphStyle(
        name="KoTitle",
        parent=base,
        fontName="MalgunBd",
        fontSize=18,
        leading=24,
        spaceAfter=8,
        textColor=HexColor("#1a1a2e"),
    )
    h1 = ParagraphStyle(
        name="KoH1",
        parent=base,
        fontName="MalgunBd",
        fontSize=14,
        leading=20,
        spaceBefore=12,
        spaceAfter=6,
        textColor=HexColor("#0f3460"),
    )
    h2 = ParagraphStyle(
        name="KoH2",
        parent=base,
        fontName="MalgunBd",
        fontSize=11,
        leading=16,
        spaceBefore=8,
        spaceAfter=4,
        textColor=HexColor("#16213e"),
    )
    code = ParagraphStyle(
        name="KoCode",
        parent=base,
        fontName="Courier",
        fontSize=8,
        leading=12,
        leftIndent=10,
        textColor=HexColor("#222"),
        backColor=HexColor("#f4f4f8"),
        borderPadding=6,
        spaceBefore=4,
        spaceAfter=8,
    )
    note = ParagraphStyle(
        name="KoNote",
        parent=base,
        fontSize=9,
        leftIndent=10,
        textColor=HexColor("#444"),
    )
    return {"base": base, "title": title, "h1": h1, "h2": h2, "code": code, "note": note}


def P(text, style):
    return Paragraph(text, style)


def make_table(data, col_widths=None, header=True):
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    style = [
        ("FONT", (0, 0), (-1, -1), "Malgun", 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#cccccc")),
    ]
    if header:
        style += [
            ("FONT", (0, 0), (-1, 0), "MalgunBd", 9),
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#0f3460")),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ]
    t.setStyle(TableStyle(style))
    return t


def main():
    doc = SimpleDocTemplate(
        OUT_PATH,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="CivicFlow Phase 4 Plan",
        author="Omega-Prime",
    )
    s = make_styles()
    story = []

    # ── Title ──
    story.append(P("CivicFlow Phase 4 — Financial Chunks Re-indexing 플랜", s["title"]))
    story.append(P("작성일: 2026-04-08 / 실행 예정: 다음 세션", s["note"]))
    story.append(Spacer(1, 6))

    # ── 0. 요약 ──
    story.append(P("0. 한 줄 요약", s["h1"]))
    story.append(P(
        "raw_text의 핵심 재무 키워드 주변 청크 22,251개를 ChromaDB에 추가 indexing → "
        "정성 답변 (회사 요약, 검색 fallback)의 evidence quality 회복. "
        "콜랩 A100 사용 (CPU 부담 없음).",
        s["base"],
    ))

    # ── 1. 현재 상태 ──
    story.append(P("1. 현재 상태 (작업 시작 전 baseline)", s["h1"]))
    state_data = [
        ["항목", "값"],
        ["ChromaDB 컬렉션", "omega_documents_v2"],
        ["기존 chunks", "278,723건"],
        ["financial_facts", "9,767건 / 1,041 회사 (정량 답변 정상)"],
        ["analysis_results", "0건 (이 작업과 무관)"],
        ["리랭커", "복원 완료 (dragonkue/bge-reranker-v2-m3-ko)"],
        ["임베딩 모델", "BAAI/bge-m3 (1024-dim)"],
    ]
    story.append(make_table(state_data, col_widths=[55 * mm, 110 * mm]))
    story.append(Spacer(1, 4))
    story.append(P(
        "<b>해결하려는 문제:</b> NAVER 같은 일부 회사의 매출 표가 cleaned_text 기반 chunking에서 빠져 "
        "ChromaDB에 indexed 되지 않음. 결과: 'NAVER 매출액' 검색 시 자기주식 처분 공시만 반환됨. "
        "정량 답변(answer_qa)은 financial_facts에서 가져와 정상이지만, 정성 답변 (answer_company_summary 같은) "
        "evidence는 잘못된 청크를 인용.",
        s["base"],
    ))

    # ── 2. STEP 0 (이미 완료) ──
    story.append(P("2. STEP 0 — 사전 준비 (이미 완료)", s["h1"]))
    step0_data = [
        ["완료 항목", "결과"],
        ["raw_text → chunks JSONL export", "✅ 22,251 chunks / 2,243 docs / 41 MB"],
        ["출력 파일", "C:\\Users\\hibou\\Omega_CivicFlow_v4\\financial_chunks.jsonl"],
        ["소요 시간", "6초"],
        ["사용 키워드", "매출액/매출/영업수익/영업이익/당기순이익/자산총계/부채총계/자본총계/EBITDA"],
        ["필터", "라벨 직후 즉시 큰 콤마 숫자 (재무 표 형식만 통과)"],
    ]
    story.append(make_table(step0_data, col_widths=[55 * mm, 110 * mm]))

    # ── 3. STEP 1: 콜랩 A100 임베딩 ──
    story.append(P("3. STEP 1 — 콜랩 A100 임베딩 (예상 5~10분)", s["h1"]))
    story.append(P("3-1. 콜랩 노트북 새로 만들기", s["h2"]))
    story.append(P("Runtime → Change runtime type → <b>A100 GPU</b> 선택", s["base"]))

    story.append(P("3-2. 파일 업로드 (2개)", s["h2"]))
    story.append(P("다음 두 파일을 콜랩에 업로드:", s["base"]))
    upload_data = [
        ["파일", "로컬 경로", "크기"],
        ["financial_chunks.jsonl", "C:\\Users\\hibou\\Omega_CivicFlow_v4\\", "41 MB"],
        ["colab_embed_financial.py", "C:\\Users\\hibou\\Omega_CivicFlow_v4\\backend\\tools\\", "~3 KB"],
    ]
    story.append(make_table(upload_data, col_widths=[55 * mm, 80 * mm, 25 * mm]))

    story.append(P("3-3. 라이브러리 설치 (콜랩 셀)", s["h2"]))
    story.append(P("!pip install sentence-transformers -q", s["code"]))

    story.append(P("3-4. 임베딩 실행 (콜랩 셀)", s["h2"]))
    story.append(P(
        "!python colab_embed_financial.py \\<br/>"
        "    --input financial_chunks.jsonl \\<br/>"
        "    --output financial_embeddings.jsonl \\<br/>"
        "    --batch-size 128",
        s["code"],
    ))
    story.append(P("예상 출력: ~90 MB JSONL (각 청크에 1024-dim embedding 포함)", s["note"]))

    story.append(P("3-5. 결과 다운로드 (콜랩 셀)", s["h2"]))
    story.append(P(
        "from google.colab import files<br/>"
        "files.download('financial_embeddings.jsonl')",
        s["code"],
    ))

    story.append(PageBreak())

    # ── 4. STEP 2 ──
    story.append(P("4. STEP 2 — 로컬 ChromaDB import (예상 1~2분, CPU 거의 안 씀)", s["h1"]))
    story.append(P("4-1. 다운로드 받은 financial_embeddings.jsonl을 로컬에 저장", s["h2"]))
    story.append(P("권장 위치: <b>C:\\Users\\hibou\\Omega_CivicFlow_v4\\financial_embeddings.jsonl</b>", s["base"]))

    story.append(P("4-2. import 실행", s["h2"]))
    story.append(P(
        "cd C:\\Users\\hibou\\Omega_CivicFlow_v4<br/>"
        "python backend/tools/import_financial_embeddings.py",
        s["code"],
    ))
    story.append(P("위치가 다르면:", s["note"]))
    story.append(P(
        "python backend/tools/import_financial_embeddings.py --input <full_path>",
        s["code"],
    ))

    story.append(P("4-3. 예상 결과", s["h2"]))
    expected_data = [
        ["항목", "Before", "After"],
        ["Collection chunks", "278,723", "~300,974 (+22,251)"],
        ["source_kind='financial_extract'", "0", "22,251"],
    ]
    story.append(make_table(expected_data, col_widths=[60 * mm, 50 * mm, 55 * mm]))

    # ── 5. STEP 3 검증 ──
    story.append(P("5. STEP 3 — 검증 (예상 5분)", s["h1"]))

    story.append(P("5-1. 검색 quality 직접 확인", s["h2"]))
    story.append(P("Windows bash 또는 cmd:", s["base"]))
    story.append(P(
        "cd C:\\Users\\hibou\\Omega_CivicFlow_v4\\backend<br/>"
        "python -c \"<br/>"
        "import sys; sys.path.insert(0, '.')<br/>"
        "from services.cognitive_search_safe import cognitive_search_safe<br/>"
        "sr = cognitive_search_safe('NAVER 매출액', top_k=3, company_filter='NAVER')<br/>"
        "for r in sr:<br/>"
        "    print(f'rerank={r[\"rerank_score\"]:.4f}')<br/>"
        "    print(f'  {r[\"chunk\"][:200]}')<br/>"
        "\"",
        s["code"],
    ))
    story.append(P(
        "<b>기대:</b> 매출 표 청크가 위로 (rerank_score 높음). "
        "이전엔 자기주식 공시만 나옴 (rerank_score &lt; 0.001).",
        s["note"],
    ))

    story.append(P("5-2. 답변 quality 확인", s["h2"]))
    story.append(P(
        "python -c \"<br/>"
        "import sys; sys.path.insert(0, '.')<br/>"
        "from services.chat_knowledge_service import answer_company_summary<br/>"
        "from database import SessionLocal<br/>"
        "db = SessionLocal()<br/>"
        "r = answer_company_summary('NAVER 회사 요약', {'company':'NAVER','companies':['NAVER']}, db, user_id=1)<br/>"
        "print(r['reply'][:600])<br/>"
        "db.close()<br/>"
        "\"",
        s["code"],
    ))
    story.append(P(
        "<b>기대:</b> 근거 섹션에 자기주식 공시 대신 매출/영업이익/자본총계 표 인용.",
        s["note"],
    ))

    story.append(P("5-3. 빠른 종합 검증", s["h2"]))
    story.append(P("기존 quantitative 검증 스크립트 재실행:", s["base"]))
    story.append(P(
        "python -c \"<br/>"
        "import sys; sys.path.insert(0, '.')<br/>"
        "from services.chat_knowledge_service import answer_qa, answer_ranking_compare<br/>"
        "from database import SessionLocal<br/>"
        "db = SessionLocal()<br/>"
        "for q in ['삼성전자 매출액', 'NAVER 매출액', '영업이익 상위 5개']:<br/>"
        "    if '상위' in q:<br/>"
        "        r = answer_ranking_compare(q, {'companies':[]}, db, user_id=1)<br/>"
        "    else:<br/>"
        "        c = q.split()[0]<br/>"
        "        r = answer_qa(q, {'company':c,'companies':[c]}, db, user_id=1)<br/>"
        "    print(f'[{q}]', r['reply'].split(chr(10))[0][:150])<br/>"
        "db.close()<br/>"
        "\"",
        s["code"],
    ))

    story.append(PageBreak())

    # ── 6. Rollback ──
    story.append(P("6. Rollback (문제 생기면)", s["h1"]))
    story.append(P(
        "이 작업은 ADD-ONLY이고 source_kind='financial_extract' 태그로 격리되어 있어 "
        "안전하게 삭제 가능. 기존 278,723 chunks는 영향 없음.",
        s["base"],
    ))
    story.append(P(
        "python -c \"<br/>"
        "import sys; sys.path.insert(0, '.')<br/>"
        "from services.vector_service import _get_collection, COLLECTION_NAME<br/>"
        "col = _get_collection(COLLECTION_NAME)<br/>"
        "existing = col.get(where={'source_kind': 'financial_extract'}, include=[])<br/>"
        "if existing and existing.get('ids'):<br/>"
        "    col.delete(ids=existing['ids'])<br/>"
        "    print(f'Deleted: {len(existing[\\\"ids\\\"])}')<br/>"
        "\"",
        s["code"],
    ))

    # ── 7. 파일 목록 ──
    story.append(P("7. 사용되는 파일 목록", s["h1"]))
    file_data = [
        ["파일", "위치", "역할"],
        ["financial_chunks.jsonl", "C:\\Users\\hibou\\Omega_CivicFlow_v4\\", "STEP 1 입력 (이미 생성)"],
        ["colab_embed_financial.py", "backend\\tools\\", "콜랩 임베딩 스크립트"],
        ["financial_embeddings.jsonl", "(콜랩 → 로컬)", "STEP 2 입력 (콜랩 출력)"],
        ["import_financial_embeddings.py", "backend\\tools\\", "STEP 2 실행 스크립트"],
        ["export_financial_chunks_jsonl.py", "backend\\tools\\", "(이미 실행됨) STEP 0"],
        ["index_financial_extracts.py", "backend\\tools\\", "(참고) 로컬 단독 실행 옵션"],
    ]
    story.append(make_table(file_data, col_widths=[55 * mm, 50 * mm, 60 * mm]))

    # ── 8. 잔존 이슈 ──
    story.append(P("8. 잔존 이슈 (이 작업과 별개, 후속 과제)", s["h1"]))
    issues_data = [
        ["이슈", "현상", "후속 작업"],
        ["케이씨피드/이수페타시스 ranking outlier", "매출/영업이익 표 파싱이 잘못된 셀 잡음", "표 파서 v3 (행 구조 인식)"],
        ["무림PP revenue 7,316억 → 정확하지만 일부 metric 부정확", "작은 회사 anchor 부족", "anchor 로직 보강"],
        ["NAVER net_income 부정확", "표 cell 선택 휴리스틱 한계", "LLM 기반 추출 (별도 작업)"],
    ]
    story.append(make_table(issues_data, col_widths=[55 * mm, 55 * mm, 55 * mm]))

    # ── 9. 안전 메모 ──
    story.append(P("9. 안전 메모", s["h1"]))
    safety = [
        "• 이 작업은 ChromaDB ADD-ONLY. 기존 278,723 chunks 변경 없음.",
        "• 새 chunks는 source_kind='financial_extract' 태그로 격리.",
        "• 임베딩 모델은 동일 (BAAI/bge-m3, 1024-dim) — 호환성 보장.",
        "• financial_facts 테이블은 이미 정상. 이 작업과 무관.",
        "• 중간에 멈춰도 안전 (각 batch가 독립적으로 commit).",
        "• Rollback 명령 1줄로 깨끗이 되돌릴 수 있음 (위 6번 참조).",
        "• 콜랩 A100 사용 시 CPU 부담 0. 로컬 import 단계도 CPU 거의 안 씀.",
    ]
    for line in safety:
        story.append(P(line, s["base"]))

    story.append(Spacer(1, 12))
    story.append(P(
        "─" * 60 + "<br/>"
        "<i>이 PDF는 다음 세션 시작 시 컨텍스트 복원을 위한 참고용입니다. "
        "Claude에게 'Phase 4 plan PDF 봐주세요' 라고 알려주시면 됩니다.</i>",
        s["note"],
    ))

    doc.build(story)
    print(f"PDF created: {OUT_PATH}")
    print(f"Size: {os.path.getsize(OUT_PATH) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
