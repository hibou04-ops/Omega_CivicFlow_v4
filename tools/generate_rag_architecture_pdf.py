"""
Omega CivicFlow RAG 아키텍처 설명 PDF 생성기
"""
import os
import sys

# fpdf2 설치 확인
try:
    from fpdf import FPDF
except ImportError:
    os.system(f"{sys.executable} -m pip install fpdf2")
    from fpdf import FPDF


class RAGArchPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("Noto", "", r"C:\Windows\Fonts\malgun.ttf", uni=True)
        self.add_font("Noto", "B", r"C:\Windows\Fonts\malgunbd.ttf", uni=True)

    def header(self):
        if self.page_no() > 1:
            self.set_font("Noto", "B", 8)
            self.set_text_color(150, 130, 80)
            self.cell(0, 6, "Omega CivicFlow v4 — RAG Architecture Guide", align="R")
            self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_font("Noto", "", 7)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def title_page(self):
        self.add_page()
        self.ln(60)
        self.set_font("Noto", "B", 28)
        self.set_text_color(40, 40, 40)
        self.cell(0, 15, "Ω Omega CivicFlow v4", align="C", ln=True)
        self.ln(5)
        self.set_font("Noto", "B", 20)
        self.set_text_color(150, 130, 80)
        self.cell(0, 12, "RAG 파이프라인 아키텍처 가이드", align="C", ln=True)
        self.ln(10)
        self.set_font("Noto", "", 11)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Retrieval-Augmented Generation 시스템 설계 문서", align="C", ln=True)
        self.cell(0, 8, "구조화 팩트 + 벡터 검색 하이브리드 RAG", align="C", ln=True)
        self.ln(30)
        self.set_font("Noto", "", 9)
        self.cell(0, 6, "Version 4.0  |  2026-03-30  |  Omega-Prime Architecture Team", align="C", ln=True)

    def section_title(self, num, title):
        self.ln(6)
        self.set_font("Noto", "B", 14)
        self.set_text_color(150, 130, 80)
        self.cell(0, 10, f"{num}. {title}", ln=True)
        self.set_draw_color(150, 130, 80)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def sub_title(self, title):
        self.ln(3)
        self.set_font("Noto", "B", 11)
        self.set_text_color(60, 60, 60)
        self.cell(0, 8, f"▸ {title}", ln=True)
        self.ln(1)

    def body(self, text):
        self.set_font("Noto", "", 9)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def bullet(self, items):
        self.set_font("Noto", "", 9)
        self.set_text_color(50, 50, 50)
        for item in items:
            self.cell(8)
            self.cell(0, 5.5, f"• {item}", ln=True)
        self.ln(2)

    def code_block(self, text):
        self.set_fill_color(245, 243, 235)
        self.set_font("Noto", "", 8)
        self.set_text_color(80, 60, 30)
        y = self.get_y()
        self.rect(12, y, 186, 6 * text.count('\n') + 10, style='F')
        self.set_xy(15, y + 3)
        self.multi_cell(180, 5, text)
        self.ln(3)

    def table_row(self, cols, widths, bold=False, header=False):
        self.set_font("Noto", "B" if bold or header else "", 8)
        if header:
            self.set_fill_color(150, 130, 80)
            self.set_text_color(255, 255, 255)
        else:
            self.set_fill_color(250, 248, 240)
            self.set_text_color(50, 50, 50)
        h = 7
        for i, col in enumerate(cols):
            self.cell(widths[i], h, str(col), border=1, fill=True)
        self.ln(h)


def build_pdf():
    pdf = RAGArchPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ═══ PAGE 1: Title ═══
    pdf.title_page()

    # ═══ PAGE 2: 목차 ═══
    pdf.add_page()
    pdf.set_font("Noto", "B", 16)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 12, "목차 (Table of Contents)", ln=True)
    pdf.ln(5)
    toc = [
        ("1", "시스템 개요 (System Overview)", 3),
        ("2", "데이터 파이프라인 (Data Pipeline)", 4),
        ("3", "저장소 아키텍처 (Storage Architecture)", 6),
        ("4", "질의 처리 엔진 (Query Processing Engine)", 8),
        ("5", "4종 라우팅 시스템 (4-Route System)", 10),
        ("6", "파생 팩트 엔진 (Derived Facts Engine)", 13),
        ("7", "멀티턴 대화 이력 (Multi-Turn Context)", 14),
        ("8", "벡터 검색 폴백 (Vector Search Fallback)", 16),
        ("9", "프론트엔드 통합 (Frontend Integration)", 17),
        ("10", "향후 로드맵 (Future Roadmap)", 18),
    ]
    pdf.set_font("Noto", "", 10)
    for num, title, page in toc:
        pdf.set_text_color(50, 50, 50)
        pdf.cell(10, 7, num)
        pdf.cell(150, 7, title)
        pdf.set_text_color(150, 130, 80)
        pdf.cell(0, 7, str(page), align="R", ln=True)

    # ═══ SECTION 1: 시스템 개요 ═══
    pdf.add_page()
    pdf.section_title("1", "시스템 개요 (System Overview)")
    pdf.body(
        "Omega CivicFlow v4는 DART(전자공시시스템) 문서를 자동으로 수집, 분석, 구조화하여 "
        "자연어 질의에 정확한 답변을 제공하는 하이브리드 RAG(Retrieval-Augmented Generation) 시스템입니다.\n\n"
        "기존 RAG 시스템의 '요약문 임베딩 중심 검색'이 갖는 한계를 극복하기 위해, "
        "구조화 팩트 테이블(Structured Facts)과 벡터 시맨틱 검색(Vector Semantic Search)을 결합한 "
        "듀얼 검색 아키텍처를 채택했습니다."
    )
    pdf.sub_title("핵심 설계 원칙")
    pdf.bullet([
        "Facts First: 숫자 질의(매출, 영업이익 등)는 구조화 팩트 DB에서 정확한 값을 직접 조회",
        "Vector Fallback: 정성적 질의(사업 전략, 위험 요인 등)는 ChromaDB 벡터 검색으로 처리",
        "Schema Extraction: LLM이 문서에서 회사명, 회계연도, 재무지표를 정규화하여 추출",
        "Scope Preference: 연결(consolidated) > 별도(separate) > 미확인 순으로 자동 우선순위 적용",
    ])

    pdf.sub_title("전체 아키텍처 흐름")
    pdf.code_block(
        "[사용자 질의]\n"
        "    ↓\n"
        "[Intent 분류] → DOC_STATS / DOC_DETAIL / DART_SEARCH / KNOWLEDGE\n"
        "    ↓ (KNOWLEDGE)\n"
        "[Route 분류] → qa / company_summary / ranking_compare / trend\n"
        "    ↓\n"
        "[구조화 팩트 DB 조회] ──(성공)──→ [응답 생성 + Citation]\n"
        "    ↓ (실패)\n"
        "[파생 팩트 계산] ──(성공)──→ [응답 생성]\n"
        "    ↓ (실패)\n"
        "[ChromaDB 벡터 검색] ──(성공)──→ [원문 청크 응답]\n"
        "    ↓ (실패)\n"
        "[메타데이터 검색] → [문서 목록 응답]"
    )

    # ═══ SECTION 2: 데이터 파이프라인 ═══
    pdf.add_page()
    pdf.section_title("2", "데이터 파이프라인 (Data Pipeline)")
    pdf.body(
        "문서가 업로드되면 다단계 파이프라인을 통해 구조화됩니다. "
        "각 단계는 독립적으로 실행되며, 실패 시 해당 단계만 재시도할 수 있습니다."
    )

    pdf.sub_title("Stage 1: 문서 수집 및 OCR")
    pdf.bullet([
        "DART ZIP → PDF 추출 → OCR 텍스트 변환 (Tesseract / Google Vision)",
        "페이지별 텍스트 저장: OcrText 테이블 (page_no, content)",
        "메타데이터 자동 추출: 회사명, 보고서 유형, 회계연도 (DocumentMetadata)",
    ])

    pdf.sub_title("Stage 2: LLM 분석 (Schema Extraction)")
    pdf.bullet([
        "Gemini 2.5 Pro에 OCR 텍스트와 구조화 스키마를 전달",
        "추출 대상: company_name, fiscal_year, metric_name, metric_value, unit, scope",
        "11개 표준 메트릭으로 정규화: revenue, operating_profit, net_income, ...",
        "confidence score 부여 (0.0 ~ 1.0)",
    ])

    pdf.sub_title("Stage 3: 구조화 팩트 저장")
    pdf.body(
        "추출된 재무 데이터는 FinancialFact 테이블에 정규화된 형태로 저장됩니다. "
        "각 팩트는 고유한 fact_uid (SHA-256 해시)로 중복을 방지합니다."
    )
    pdf.code_block(
        "fact_uid = SHA256(\n"
        "    document_id + company_name_norm + fiscal_year +\n"
        "    metric_name + statement_scope + period_type\n"
        ")"
    )

    pdf.sub_title("Stage 4: 벡터 인덱싱")
    pdf.bullet([
        "OCR 텍스트를 500자 단위로 분할 → DocumentChunk 테이블 저장",
        "각 청크에 메타데이터 태깅: company_name, page_no, section_name",
        "ChromaDB에 임베딩 벡터 저장 (collection: chat_chunks)",
        "검색 시 메타데이터 필터 + 코사인 유사도 복합 스코어링",
    ])

    # ═══ SECTION 3: 저장소 아키텍처 ═══
    pdf.add_page()
    pdf.section_title("3", "저장소 아키텍처 (Storage Architecture)")
    pdf.body(
        "Omega CivicFlow v4는 관계형 DB(SQLite)와 벡터 DB(ChromaDB)의 "
        "하이브리드 저장소를 사용합니다."
    )

    pdf.sub_title("SQLite 관계형 테이블 (7개 핵심 테이블)")
    w = [45, 145]
    pdf.table_row(["테이블명", "역할"], w, header=True)
    tables = [
        ("documents", "원본 문서 메타데이터 (파일명, 상태, 업로드 시간)"),
        ("document_metadata", "DART 메타데이터 (회사명, 회계연도, 보고서유형, scope)"),
        ("analysis_results", "LLM 분석 결과 (요약, 카테고리, raw JSON)"),
        ("document_chunks", "500자 단위 텍스트 청크 (벡터 검색 원본)"),
        ("financial_facts", "구조화 재무 팩트 (11개 메트릭, 정규화된 수치)"),
        ("company_profiles", "회사별 최신 회계연도/문서 캐시"),
        ("ocr_texts", "페이지별 OCR 원문 텍스트"),
    ]
    for name, role in tables:
        pdf.table_row([name, role], w)

    pdf.ln(5)
    pdf.sub_title("ChromaDB 벡터 컬렉션")
    pdf.bullet([
        "컬렉션명: chat_chunks",
        "임베딩 모델: Gemini text-embedding-004",
        "차원: 768D",
        "메타데이터 필터: company_name, fiscal_year, page_no, section_name",
        "검색 방식: 코사인 유사도 + 메타데이터 필터 복합 스코어링",
    ])

    pdf.sub_title("FinancialFact 스키마 상세")
    w2 = [40, 25, 125]
    pdf.table_row(["컬럼", "타입", "설명"], w2, header=True)
    cols = [
        ("company_name_norm", "STR", "정규화된 회사명 (normalize_company_name 함수 적용)"),
        ("fiscal_year", "INT", "회계연도 (2024, 2025 등)"),
        ("metric_name", "STR", "표준 메트릭명 (revenue, operating_profit 등 11종)"),
        ("metric_value_num", "FLOAT", "수치값 (원 단위, 예: 23670000000000.0)"),
        ("statement_scope", "STR", "재무제표 범위 (consolidated / separate / 빈값)"),
        ("period_type", "STR", "기간 유형 (annual / quarterly)"),
        ("confidence", "FLOAT", "추출 신뢰도 (0.0 ~ 1.0)"),
    ]
    for name, typ, desc in cols:
        pdf.table_row([name, typ, desc], w2)

    # ═══ SECTION 4: 질의 처리 엔진 ═══
    pdf.add_page()
    pdf.section_title("4", "질의 처리 엔진 (Query Processing Engine)")
    pdf.body(
        "사용자 질의는 2단계 분류를 거쳐 최적의 처리 경로로 라우팅됩니다."
    )

    pdf.sub_title("Stage 1: Intent 분류 (_classify_intent)")
    pdf.body("사용자 메시지의 의도를 7가지로 분류합니다:")
    w3 = [40, 65, 85]
    pdf.table_row(["Intent", "트리거 패턴", "처리 방식"], w3, header=True)
    intents = [
        ("DOC_STATS", "현황, 통계, 총 몇개", "DB 집계 쿼리"),
        ("DOC_DETAIL", "#숫자 (문서 ID)", "단일 문서 상세 조회"),
        ("DART_SEARCH", "공시, DART", "DART API 실시간 검색"),
        ("SEARCH_DOCS", "목록, 리스트 + 필터", "메타데이터 필터 검색"),
        ("IDENTITY", "정체, 누구", "프로필 응답"),
        ("TIME", "몇시, 날짜", "현재 시간 응답"),
        ("KNOWLEDGE", "(기본)", "RAG 라우터로 이관"),
    ]
    for it in intents:
        pdf.table_row(list(it), w3)

    pdf.ln(4)
    pdf.sub_title("Stage 2: Route 분류 (classify_chat_route)")
    pdf.body(
        "KNOWLEDGE intent인 경우, 질의의 성격에 따라 4가지 전문 라우트로 분기합니다. "
        "각 라우트는 서로 다른 데이터 조회 전략과 응답 포맷을 사용합니다."
    )
    w4 = [35, 55, 100]
    pdf.table_row(["Route", "트리거 예시", "처리 전략"], w4, header=True)
    routes = [
        ("ranking_compare", "top5, 비교, 상위, 높은", "팩트 DB 정렬 → 테이블 렌더링"),
        ("trend", "추세, 변화, 최근 3년", "연도별 시계열 그룹핑 → 차트 데이터"),
        ("company_summary", "삼성전자 요약, 실적", "회사별 핵심 6개 지표 집계"),
        ("qa", "(기본 폴백)", "벡터 검색 → 원문 청크 인용"),
    ]
    for r in routes:
        pdf.table_row(list(r), w4)

    # ═══ SECTION 5: 4종 라우트 상세 ═══
    pdf.add_page()
    pdf.section_title("5", "4종 라우팅 시스템 상세")

    pdf.sub_title("5-1. ranking_compare (랭킹/비교)")
    pdf.body(
        "재무 지표 기준으로 기업을 정렬하여 순위를 매깁니다.\n"
        "질의 예: '작년 영업이익 top5', '2025년 매출액 높은 기업'"
    )
    pdf.code_block(
        "처리 흐름:\n"
        "1. resolve_query_metric() → 메트릭 정규화 (예: '실적' → 'operating_profit')\n"
        "2. extract_limit_from_query() → 상위 N개 추출 (기본 10)\n"
        "3. _query_fact_rows() → DB 조회 (scope_preference 적용)\n"
        "4. [NEW] _compute_derived_facts() → 파생 메트릭 폴백\n"
        "5. 내림/오름차순 정렬 → 테이블 + Citation 생성"
    )

    pdf.sub_title("5-2. company_summary (기업 요약)")
    pdf.body(
        "특정 기업의 핵심 재무지표 6개를 한눈에 보여줍니다.\n"
        "질의 예: '삼성전자 재무 요약', 'LG에너지솔루션 실적'"
    )
    pdf.bullet([
        "핵심 6개 지표: 매출액, 영업이익, 당기순이익, 자산총계, 부채총계, 자본총계",
        "연결/별도 재무제표 구분 표시",
        "벡터 검색으로 정성적 보충 정보 추가",
    ])

    pdf.sub_title("5-3. trend (추세 분석)")
    pdf.body(
        "동일 기업의 특정 지표를 연도별로 추적합니다.\n"
        "질의 예: '삼성전자 매출 추이', '최근 3년 영업이익 변화'"
    )
    pdf.bullet([
        "extract_trend_span()으로 분석 기간 결정 (기본 3년)",
        "연도별 시계열 데이터 생성 → series 배열로 반환",
        "전년 대비 증감율 자동 계산",
    ])

    pdf.sub_title("5-4. qa (일반 질의응답)")
    pdf.body(
        "구조화 팩트로 답변할 수 없는 정성적/탐색적 질의를 처리합니다.\n"
        "질의 예: '삼성전자 사업 위험 요인', '배당 정책 변경 이유'"
    )
    pdf.bullet([
        "ChromaDB 벡터 검색 (cognitive_search_safe)",
        "상위 6개 관련 청크 추출",
        "회사명/연도/카테고리 메타데이터 필터 적용",
        "코사인 유사도 + SOURCE_PRIORITY 복합 스코어링",
    ])

    # ═══ SECTION 6: 파생 팩트 엔진 ═══
    pdf.add_page()
    pdf.section_title("6", "파생 팩트 엔진 (Derived Facts Engine)")
    pdf.body(
        "영업이익률(operating_margin)과 부채비율(debt_ratio)처럼 DB에 직접 저장되지 않은 "
        "비율 메트릭을 구성요소 팩트로부터 동적으로 계산합니다.\n\n"
        "이 엔진은 _query_fact_rows()가 빈 결과를 반환할 때 자동으로 활성화됩니다."
    )

    pdf.sub_title("파생 공식 정의")
    w5 = [40, 75, 75]
    pdf.table_row(["파생 메트릭", "공식", "구성요소"], w5, header=True)
    pdf.table_row(["operating_margin", "operating_profit ÷ revenue × 100", "영업이익 + 매출액"], w5)
    pdf.table_row(["debt_ratio", "total_liabilities ÷ equity × 100", "부채총계 + 자본총계"], w5)

    pdf.ln(3)
    pdf.sub_title("처리 흐름")
    pdf.code_block(
        "_compute_derived_facts(db, 'operating_margin', years=[2025]):\n"
        "  1. _query_fact_rows('operating_profit') → 793건\n"
        "  2. _query_fact_rows('revenue') → 805건\n"
        "  3. 회사+연도 기준 매칭 → 630건 교집합\n"
        "  4. operating_profit ÷ revenue × 100 계산\n"
        "  5. FinancialFact 호환 객체 반환 (extraction_method='derived')"
    )
    pdf.body(
        "기존 직접 팩트가 있는 경우에도, 파생 계산으로 누락 기업을 보충합니다. "
        "이를 통해 랭킹 쿼리에서 모든 기업이 포함된 완전한 결과를 제공합니다."
    )

    # ═══ SECTION 7: 멀티턴 대화 ═══
    pdf.add_page()
    pdf.section_title("7", "멀티턴 대화 이력 (Multi-Turn Context)")
    pdf.body(
        "\"작년 실적 좋은 기업 top5\" → \"그 중 삼성전자 자세히\" 같은 연속 대화를 지원합니다.\n"
        "이전 턴의 컨텍스트(회사명, 메트릭, 연도, 라우트)를 현재 질의에 자동 병합합니다."
    )

    pdf.sub_title("후속 질문 감지 패턴 (18개)")
    pdf.bullet([
        "대명사/지시어: '그 중', '위 결과', '거기서', '그 기업', '그 회사'",
        "시간 참조: '방금', '아까'",
        "확장 요청: '자세히', '더 알려', '좀 더', '구체적', '세부', '상세'",
        "연속 요청: '이어서', '추가로', '다시', '거기에'",
    ])

    pdf.sub_title("컨텍스트 병합 로직")
    pdf.code_block(
        "_merge_followup_context(message, variables, prev_ctx):\n"
        "  1. companies: 현재 없으면 이전 전체 유지, 있으면 현재만\n"
        "     예: '그 중 삼성전자' → companies=['삼성전자'] + 이전 metric/year\n"
        "  2. metric: 현재 없으면 이전 것 사용\n"
        "  3. year_filters: 현재 없으면 이전 것 사용\n"
        "  4. route: 단일 회사 → company_summary로 전환\n"
        "           그 외 → 이전 route 유지"
    )

    pdf.sub_title("이력 추출 (_extract_prev_context)")
    pdf.body(
        "프론트엔드가 보내는 history 배열에서 가장 최근 assistant 응답의 payload를 분석합니다.\n"
        "payload.criteria에서 metric_name, fiscal_year를, payload.rows에서 회사명 목록을 추출합니다.\n"
        "최대 10턴 (MAX_HISTORY_TURNS)까지 참조합니다."
    )

    # ═══ SECTION 8: 벡터 검색 ═══
    pdf.add_page()
    pdf.section_title("8", "벡터 검색 폴백 (Vector Search Fallback)")
    pdf.body(
        "구조화 팩트와 파생 팩트 모두 결과가 없을 때, ChromaDB 벡터 검색으로 폴백합니다."
    )
    pdf.sub_title("검색 파이프라인")
    pdf.bullet([
        "cognitive_search_safe() 호출",
        "쿼리 임베딩 생성 (Gemini text-embedding-004)",
        "메타데이터 필터 적용: company, category, year",
        "코사인 유사도 상위 6개 청크 추출",
        "SOURCE_PRIORITY 가중치 적용 (financial_metrics: 0.97 > summary: 0.93 > ...)",
        "회사별 그룹핑 → 최대 3개 청크/회사 표시",
    ])

    pdf.sub_title("스코어링 체계")
    w6 = [50, 30, 110]
    pdf.table_row(["소스 유형", "가중치", "설명"], w6, header=True)
    scores = [
        ("financial_metrics", "0.97", "재무제표에서 추출된 수치 데이터"),
        ("summary", "0.93", "LLM이 생성한 요약문"),
        ("key_point", "0.88", "핵심 사항/주요 포인트"),
        ("evidence", "0.80", "근거 자료/참고 정보"),
        ("ocr", "0.72", "원문 OCR 텍스트"),
    ]
    for s in scores:
        pdf.table_row(list(s), w6)

    # ═══ SECTION 9: 프론트엔드 ═══
    pdf.add_page()
    pdf.section_title("9", "프론트엔드 통합 (Frontend Integration)")

    pdf.sub_title("API 통신")
    pdf.code_block(
        "POST /panel/chat\n"
        "Body: { message: '작년 실적 top5', history: [...] }\n"
        "Response: {\n"
        "  reply: '기준: 2025년 연간, ...',\n"
        "  payload: { type, route, criteria, rows, citations },\n"
        "  tools_used: ['structured_facts'],\n"
        "  error: false\n"
        "}"
    )

    pdf.sub_title("구조화 응답 렌더링")
    pdf.bullet([
        "PayloadTable: rows 배열 → 정렬된 테이블 (glassmorphism 디자인)",
        "CitationPanel: citations 배열 → 클릭 가능한 원문보기 링크 (/view/:id)",
        "renderMarkdown(): 마크다운 텍스트 → HTML 변환 (제목, 볼드, 링크)",
        "TypingIndicator: 로딩 중 애니메이션 (3-dot bounce)",
    ])

    pdf.sub_title("대화 이력 전송")
    pdf.body(
        "messages 상태 배열에 { role, content, payload }를 저장하고, "
        "매 요청 시 history 파라미터로 백엔드에 전달합니다. "
        "백엔드는 history에서 이전 턴의 payload를 추출하여 "
        "후속 질문의 컨텍스트를 복원합니다."
    )

    # ═══ SECTION 10: 로드맵 ═══
    pdf.add_page()
    pdf.section_title("10", "향후 로드맵 (Future Roadmap)")

    pdf.sub_title("Phase 2: Comparison Engine 강화")
    pdf.bullet([
        "동종업계 자동 분류 및 peer comparison",
        "업종 평균 대비 개별 기업 위치 시각화",
        "다중 메트릭 복합 비교 (매출 + 영업이익 + 순이익 동시)",
    ])

    pdf.sub_title("Phase 3: Thesis Engine (패턴·이상치)")
    pdf.bullet([
        "연도별 급변 지표 자동 감지 (YoY 변화율 임계값)",
        "이상치(outlier) 알림 및 원인 추적",
        "산업 트렌드 자동 리포트 생성",
    ])

    pdf.sub_title("Phase 4: Market Data Integration")
    pdf.bullet([
        "실시간 주가 데이터 연동",
        "PER, PBR 등 시장 밸류에이션 지표 계산",
        "DART 공시 + 시장 반응 연계 분석",
    ])

    pdf.sub_title("Phase 5: Audit Engine")
    pdf.bullet([
        "전기 대비 수치 검증 (cross-validation)",
        "감사의견 변경 자동 감지",
        "재무제표 일관성 검증 (자산 = 부채 + 자본)",
    ])

    # ═══ 저장 ═══
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "Omega_CivicFlow_RAG_Architecture_Guide.pdf"
    )
    pdf.output(out_path)
    print(f"✅ PDF 생성 완료: {out_path}")
    return out_path


if __name__ == "__main__":
    build_pdf()
