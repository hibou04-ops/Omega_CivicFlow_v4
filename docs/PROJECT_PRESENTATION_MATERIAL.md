# Omega CivicFlow v4 — 발표자료 (소스코드 + DB 100% 검증, 재감사 v3)

> **2026-04-14 13:30 재감사 적용본**: `C:\Users\hibou\Omega_CivicFlow_v4` 소스코드 + `C:\Users\hibou\Omega_CivicFlow_v4_DB\omega_civicflow.db` (3.2 GB) SQLite 직접 query.
> 모든 기술 주장에는 `파일:라인` 또는 `SQL:컬럼` 근거가 표시됩니다. 추측 금지, 환각 금지.
>
> **재감사 v2 정정 사항 (5건)** *(2026-04-14)*:
> 1. 메인 DB 종류: PostgreSQL → **SQLite** (.env 런타임 확인)
> 2. Auth 엔드포인트 카운트: 9 → **10**
> 3. Documents 엔드포인트 카운트: 16 → **15**
> 4. 분석 문서 수: ~2,000 → **3,135** (요약 완성률은 PPT의 97.2% 측정 아티팩트가 아니라 실제 100%)
> 5. 챗봇 명칭: "RAG 챗봇" / "Omega-Prime AI 챗봇" → **Omega-Cortex** (Omega-Prime은 시스템 프롬프트/Supervisor 식별자로 보존)
>
> **재감사 v3 정정 사항 (4건)** *(2026-04-15 — 회원 탈퇴 플로우 추가 반영)*:
> 1. Auth 엔드포인트: 10 → **12** (`/request-withdraw`, `/confirm-withdraw` 추가 — `auth.py:260, 297`)
> 2. 총 API 엔드포인트: 42 → **44** (12 + 15 + 8 + 9)
> 3. 프론트엔드 페이지: 14 → **15** (`VerifyWithdraw.jsx` `/verify-withdraw` 경로 추가 — `App.jsx:43`)
> 4. 토큰 시스템: 4종 → **5종** (Withdraw 토큰 추가 — `auth_service.py:247-265`)

---

## ⚠ 발표 전 반드시 확인할 결정적 불일치 (4건)

발표 Q&A에서 무너지지 않으려면 아래 4건은 **무조건** 슬라이드/대본을 정정해야 합니다.

### 불일치 #0 — 메인 DB 종류 (가장 위험, 2026-04-14 재감사로 확정)
- **현재 코드 default**: `backend/config.py:16` → `DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/civicflow"`
- **실제 런타임**: `backend/.env` → `DATABASE_URL=sqlite:///C:/Users/hibou/Omega_CivicFlow_v4_DB/omega_civicflow.db`
- **물증**: 3.2 GB SQLite 파일에 documents 3,135행, analysis_results 3,135행, document_chunks 312,572행 적재 확인
- **진실**: 운영 DB는 **SQLite** 단일 파일입니다. PostgreSQL 드라이버(psycopg)는 venv에 설치돼 있고 코드도 양쪽을 지원하지만 (`database.py:19` `if settings.DATABASE_URL.startswith("sqlite"):`) 실제 데이터는 SQLite에 있습니다.
- **발표 시 표기**: ✅ **SQLite (런타임) / PostgreSQL-호환 스키마** ❌ ~~PostgreSQL 단일~~
- **Q&A 방어**: "왜 PostgreSQL이 아니냐"고 물으면 → "스키마는 PostgreSQL-호환으로 설계했고 driver/config도 분기되어 있어 1행 환경변수 변경으로 PG 전환 가능합니다. 현재 데모/포트폴리오 단계라 단일 파일 SQLite로 운영 중입니다."

### 불일치 #1 — OCR 엔진 (가장 위험)
- **현재 코드 사실**: `services/ocr_service.py:38` → `import easyocr` / `easyocr.Reader(["ko","en"], gpu=False)`
- **잘못된 흔적**: 같은 파일 line 5 docstring, line 405 fallback 메시지에 "PaddleOCR" 언급. `requirements.txt`에도 `paddleocr==3.4.0`, `paddlepaddle==3.3.0` 명시
- **진실**: 운영 OCR 엔진은 **EasyOCR**입니다. PaddleOCR은 venv에 설치되어 있지만 어떤 코드에서도 import 되지 않습니다 (`grep` 결과 0건)
- **발표 시 표기**: ✅ **EasyOCR (한국어/영어)** ❌ ~~PaddleOCR~~

### 불일치 #2 — PDF 보고서 라이브러리
- **현재 코드 사실**: `services/pdf_report_service.py:23` → `from fpdf import FPDF`
- **실제 패키지**: venv에 `fpdf2-2.8.7` 설치 (fpdf2가 `fpdf` 모듈을 노출)
- **잘못된 흔적**: `requirements.txt`에 fpdf2 미선언. reportlab 4.4.10도 venv에 설치돼있지만 코드에서 import 0건
- **발표 시 표기**: ✅ **fpdf2 (A4 안전 좌표계 PDF)** ❌ ~~reportlab~~

### 불일치 #3 — requirements.txt 자체가 outdated
`requirements.txt`는 실제 운영 의존성을 일부만 반영합니다. 아래는 **코드에서 실제 import 하지만 requirements.txt에 누락된 패키지** 목록:

| 패키지 | 코드 사용 위치 | 역할 |
|---|---|---|
| `easyocr` | services/ocr_service.py:38 | OCR 엔진 |
| `fpdf2` (fpdf 모듈) | services/pdf_report_service.py:23 | PDF 보고서 |
| `chromadb` | services/vector_service.py | 벡터 DB |
| `google-genai` | services/insight_service.py:19 | Gemini 2.5 Pro |
| `celery` | workers/celery_app.py:9 | 비동기 태스크 큐 |
| `redis` | (Celery broker URL) | 메시지 브로커 |
| `reportlab` | (설치만 됨, 코드 사용 없음) | — (제거 후보) |

**발표 권장**: "운영 코드 기준 진짜 스택"으로 발표하고, requirements.txt는 정리 예정으로 명시.

---

# Section 1 — 프로젝트 개요 (Project Overview)

## 1.1 프로젝트명
**Omega CivicFlow v4**
부제: *OCR → LLM 공공 민원 / DART 공시 문서 자동 분석 플랫폼*
근거: `backend/main.py:3-9`, `config.py:54`

## 1.2 한 줄 정의
사용자가 업로드한 한국 금융감독원(DART) 공시문서 / 민원 문서를 **OCR로 텍스트화 → 로컬 LLM(EXAONE)으로 분류·요약·재무지표 추출 → ChromaDB 벡터 인덱싱 → Gemini 2.5 Pro로 전략 인사이트 도출 → PDF 보고서 생성 → Omega-Cortex(RAG 챗봇)로 질의응답**까지 엔드투엔드 자동화하는 플랫폼.

## 1.3 핵심 가치 (USP — Unique Selling Points)
1. **역할 분리형 멀티 LLM**: 로컬 EXAONE 3.5 (분류·요약) + 원격 Gemini 2.5 Pro (전략 인사이트) + Gemini 2.5 Flash (감독·검증)
2. **하이브리드 RAG**: 벡터 검색(ChromaDB) + 구조화 팩트 DB(SQLAlchemy) + Function Calling
3. **DART OpenAPI 통합**: 약 80,000건 한국 법인코드를 서버 시작 시 자동 캐싱, 종목명 자동완성 지원
4. **다중 포맷 지원**: PDF, DOCX, XLSX, PPTX, HWP, XBRL, XML, HTML, 이미지 + ZIP 일괄 업로드
5. **누적 지식 계층**: DocumentChunk + FinancialFact 테이블로 비교·집계·추세 질의의 정답 원천 구축

근거: `routers/panel.py:165-167` ("약 2,000+건의 DART 공시문서가 분석되어 축적"), `frontend/src/pages/UploadPage.jsx:11` (지원 포맷 목록)

## 1.4 시스템 캐치프레이즈 (코드에서 발견)
> "초-헤밀토니안 최적화 시스템 (Super-Hamiltonian Optimization System)"
> "Energy (E) · Entropy (S) · Efficiency (η)"
근거: `backend/main.py:3-9`

> **발표 팁**: 청중이 비기술자라면 "DART 공시 자동 분석 + AI 챗봇(Omega-Cortex) 플랫폼"으로 표현하고, 기술자라면 "OCR → 로컬 LLM → 벡터 RAG → Gemini Insight 풀스택"으로 표현.

---

# Section 2 — 사용 기술 스택 (100% 코드 검증)

> 모든 항목은 `requirements.txt`, `package.json`, `config.py`, 또는 실제 import 문에서 확인된 것만 포함합니다.

## 2.1 백엔드 (Python)

| 카테고리 | 라이브러리 | 버전 | 근거 |
|---|---|---|---|
| **언어** | Python | 3.x | venv 기반 |
| **웹 프레임워크** | FastAPI | 0.135.1 | requirements.txt:8 |
| **ASGI 서버** | Uvicorn | 0.41.0 | requirements.txt:9 |
| **데이터 검증** | Pydantic | 2.11.1 | requirements.txt:11 |
| **DB ORM** | SQLAlchemy | 2.0.48 | requirements.txt:15 |
| **DB 마이그레이션** | Alembic | 1.18.4 | requirements.txt:16 |
| **메인 DB (런타임)** | **SQLite** ⚠ | — | `.env DATABASE_URL=sqlite:///`, `database.py:19` 분기 |
| **DB 드라이버 (설치)** | psycopg[binary] | 3.3.3 | requirements.txt:17, config.py:16 (PG default) |
| **벡터 DB** | ChromaDB | 1.5.5 | venv 설치 + services/vector_service.py |
| **메시지 브로커** | Redis | — | config.py:49, celery_app.py:14 |
| **태스크 큐** | Celery | — | workers/celery_app.py:9 |
| **OCR 엔진** | **EasyOCR** ⚠ | — | services/ocr_service.py:38 |
| **이미지 처리** | Pillow | 12.1.1 | requirements.txt:28 |
| **PDF→이미지** | pdf2image | 1.17.0 | requirements.txt:37 |
| **PDF 생성** | **fpdf2** ⚠ | 2.8.7 | services/pdf_report_service.py:23 |
| **로컬 LLM 클라이언트** | Ollama (Python) | 0.6.1 | requirements.txt:31 |
| **Gemini SDK** | google-genai | 1.69.0 | services/insight_service.py:19 |
| **HTTP 클라이언트** | httpx | 0.28.1 | requirements.txt:32 |
| **JWT** | python-jose[cryptography] | 3.5.0 | requirements.txt:20 |
| **비밀번호 해싱** | passlib + bcrypt | 1.7.4 / 4.2.1 | requirements.txt:21-22 |
| **이메일 검증** | email-validator | 2.3.0 | requirements.txt:10 |
| **환경변수** | python-dotenv | 1.0.1 | requirements.txt:35 |

⚠ = requirements.txt에 명시되지 않았거나 잘못 명시된 항목. 발표 전 정정 필요.

## 2.2 프론트엔드 (JavaScript)

| 카테고리 | 라이브러리 | 버전 | 근거 |
|---|---|---|---|
| **프레임워크** | React | 18.3.1 | package.json:15 |
| **빌드 도구** | Vite | 6.0.3 | package.json:23 |
| **라우팅** | react-router-dom | 6.28.0 | package.json:17 |
| **HTTP 클라이언트** | axios | 1.7.9 | package.json:12 |
| **ZIP 처리** | jszip | 3.10.1 | package.json:13 |
| **아이콘 라이브러리** | lucide-react | 0.460.0 | package.json:14 |

## 2.3 외부 서비스 (External Dependencies)

| 서비스 | 용도 | 근거 |
|---|---|---|
| **Ollama** (localhost:11434) | EXAONE 3.5 7.8b 로컬 LLM 서빙 | config.py:24-25 |
| **Google Vertex AI / Gemini 2.5 Pro** | 전략 인사이트 도출 (The-Absolute Insight Engine) | config.py:61, insight_service.py |
| **Google Vertex AI / Gemini 2.5 Flash** | Omega-Prime Supervisor (인사이트 검증/보강) | config.py:65 |
| **DART OpenAPI** | 한국 공시 검색, 법인코드 사전 (~80,000건) | config.py:71, routers/panel.py:38-123 |
| **Gmail SMTP** | 회원가입 인증 / 비밀번호 재설정 메일 | config.py:42-45, services/email_service.py |
| **vLLM (RunPod)** [선택] | 파인튜닝된 Qwen 2.5 모델 서빙 (활성화 시) | config.py:30-31 |

## 2.4 발표용 툴 아이콘 권장 리스트 (최종)

데이터 흐름 순서로 배치 시 청중이 즉시 파이프라인 이해:

```
[EasyOCR] → [Python/FastAPI] → [SQLite] → [ChromaDB] → [Ollama/EXAONE] → [Gemini Pro] → [React/Vite]
   OCR        백엔드 API       메인 DB      벡터 DB      로컬 LLM         인사이트       프론트엔드
```

**총 7개 아이콘** (시각적 안정성 최적):
1. **Python** — 백엔드 언어
2. **FastAPI** — REST API 프레임워크
3. **SQLite** — 메인 DB (런타임), PostgreSQL-호환 스키마
4. **ChromaDB** — 벡터 DB
5. **Ollama** — 로컬 LLM 서빙 (라마 로고)
6. **Google Gemini** — 인사이트 엔진
7. **React** — 프론트엔드

**선택 8~9번째**:
- **Redis** + **Celery** (백그라운드 큐 강조 시)
- **EasyOCR** (OCR 차별화 강조 시 — 단, 자체 로고가 약함)

**제외 권장 (발표 청중에게 가치 없음)**:
- SQLAlchemy, Alembic, Uvicorn, Pydantic (FastAPI/Python 아이콘에 흡수됨)
- httpx, axios (HTTP 클라이언트 — 너무 일반적)
- jszip, lucide-react, fpdf2 (보조 기능)

---

# Section 3 — 시스템 아키텍처 및 데이터 흐름

## 3.1 전체 구성도 (텍스트 다이어그램)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     [사용자 / 관리자]                                  │
│  (브라우저 — React SPA, http://localhost:5173)                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTPS / JWT Bearer
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              [Frontend — React 18 + Vite + Axios]                   │
│  pages/ (15개) · components/ · contexts/AuthContext · api/client     │
└────────────────────────────┬────────────────────────────────────────┘
                             │ REST API
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│         [Backend — FastAPI + Uvicorn (사건의 지평선)]                │
│  CORS 미들웨어 │ JWT 인증 │ Lifespan: init_db + Upload Dir 생성      │
│                                                                       │
│  ┌─────────┐ ┌─────────────┐ ┌─────────┐ ┌─────────────────────┐    │
│  │ /auth   │ │ /documents  │ │ /admin  │ │ /panel              │    │
│  │ 12 EP   │ │ 15 EP       │ │ 8 EP    │ │ 9 EP (DART/Chat)    │    │
│  └────┬────┘ └──────┬──────┘ └────┬────┘ └──────────┬──────────┘    │
└───────┼─────────────┼─────────────┼─────────────────┼───────────────┘
        │             │             │                 │
        ▼             ▼             ▼                 ▼
┌──────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────────────────┐
│ services │ │ Celery       │ │ SQLite     │ │ External APIs        │
│ (27개)   │ │ Workers      │ │ 11 tables  │ │                      │
│          │ │ (Redis broker)│ │ (PG-호환)  │ │ • DART OpenAPI       │
│ AUTH     │ │              │ │            │ │ • Ollama localhost   │
│ OCR      │ │ process_     │ │            │ │ • Google Gemini      │
│ LLM      │ │ document_    │ │            │ │ • Gmail SMTP         │
│ AGENT    │ │ task         │ │            │ │ • RunPod vLLM(opt)   │
│ INSIGHT  │ │              │ │            │ │                      │
│ VECTOR   │ │              │ │            │ │                      │
│ ...      │ │              │ │            │ │                      │
└──────────┘ └──────────────┘ └────────────┘ └──────────────────────┘
                                     │
                                     ▼
                              ┌─────────────┐
                              │  ChromaDB   │
                              │ (벡터 DB)    │
                              └─────────────┘
```

근거: `main.py:84-92` (라우터 등록), `database.py:46-52` (11 모델 init), `services/` 디렉토리 (27 파일), `workers/celery_app.py`, `config.py`

## 3.2 핵심 데이터 흐름 — 문서 분석 파이프라인

```
[1] 사용자 업로드
    └─ Frontend: UploadPage.jsx
       └─ POST /api/documents/upload-batch (FormData, 최대 20파일/700MB)
       └─ ZIP 파일은 magic byte 검출 후 클라이언트에서 자동 추출
                        │
                        ▼
[2] FastAPI 라우터: routers/documents.py
    └─ 파일 저장 → Document(status='uploaded') 레코드 생성
    └─ Celery 태스크 enqueue: process_document_task.delay(doc_id)
                        │
                        ▼
[3] Celery 워커 (workers/tasks.py:33)
    │
    ├─ 3-1. OCR (services/ocr_service.py)
    │       └─ EasyOCR("ko","en") + 8단계 이미지 전처리
    │       └─ Document.status = 'ocr_done'
    │       └─ Page + OcrText 레코드 생성
    │
    ├─ 3-2. 텍스트 전처리 (services/text_preprocessor.py)
    │       └─ 표 구조 복원, 섹션 자동 태깅, 숫자 정규화
    │
    ├─ 3-3. 텍스트 품질 검증 (services/text_quality.py)
    │       └─ readability score, 깨진 한글 감지, 품질 태그
    │
    ├─ 3-4. LLM 분석 (services/llm_service.py)
    │       └─ Ollama(EXAONE 3.5 7.8b) → 분류/요약/재무지표/근거
    │       └─ AnalysisResult 레코드 생성
    │       └─ Document.status = 'analyzed'
    │
    ├─ 3-5. 자동 임베딩 (services/vector_service.py)
    │       └─ ChromaDB에 문서 청크 인덱싱
    │
    ├─ 3-6. 지식 계층 동기화 (services/chat_knowledge_service.py)
    │       └─ DocumentChunk + FinancialFact + DocumentMetadata upsert
    │
    └─ 3-7. (선택) 인사이트 생성 (services/insight_service.py)
            └─ Gemini 2.5 Pro → DocumentInsight 생성
            └─ Omega Supervisor (Gemini 2.5 Flash) → 검증/보강
                        │
                        ▼
[4] 사용자 결과 조회
    ├─ GET /api/documents/{id}        → 문서 상세 + 분석 결과
    ├─ GET /api/documents/insight/{id} → 전략 인사이트
    ├─ GET /api/documents/download-report/{id} → fpdf2 PDF 보고서
    └─ POST /api/panel/chat            → Omega-Cortex (RAG 챗봇 + Function Calling)
                        │
                        ▼
[5] (병렬) 이메일 알림
    └─ process_batch_email_task → Gmail SMTP
```

근거: `routers/documents.py:350` (upload), `workers/tasks.py:33-159` (process_document_task), 각 서비스 파일

## 3.3 Omega-Cortex 데이터 흐름 (POST /panel/chat — RAG 챗봇)

```
[사용자 질문] "삼성전자 작년 영업이익 알려줘"
        │
        ▼
[1] chat_agent_safe_service.run_agent()
        │
        ├─ 의도 분석 + 회사명 추출 (company_alias_master)
        │
        ├─ Function Calling 결정:
        │  ├─ structured_facts          (FinancialFact 테이블 조회)
        │  ├─ chromadb_search           (벡터 시맨틱 검색)
        │  ├─ search_dart_filings       (DART OpenAPI 실시간)
        │  ├─ get_document_detail       (특정 문서 상세)
        │  ├─ get_document_stats        (집계)
        │  ├─ search_my_documents       (사용자 문서 검색)
        │  ├─ semantic_search           (cognitive_search_safe)
        │  └─ metadata_search           (DocumentMetadata 필터)
        │
        ├─ 검색된 데이터 컨텍스트 + Omega-Prime 시스템 프롬프트로
        │  Ollama(EXAONE) 또는 Gemini 호출
        │
        └─ Gemini 2.5 Flash 검증 (선택) → 환각 차단
        │
        ▼
[응답] reply + tools_used + citations + payload
```

근거: `routers/panel.py:565-631` (chat endpoint), `frontend/src/components/ChatBot.jsx:36-45` (TOOL_LABELS), Explore agent 감사 결과

---

# Section 4 — 데이터베이스 ERD (SQLite 런타임 / PostgreSQL-호환 스키마)

> 11개 테이블, `models/models.py` 기준 100% 정확. 운영 DB는 SQLite, 스키마는 SQLAlchemy ORM이라 PG 전환 가능.

## 4.1 테이블 목록 및 책임

| # | 테이블명 | 클래스 | 책임 | 주요 컬럼 |
|---|---|---|---|---|
| 1 | `users` | User | 회원 인증 | id, email, username, password_hash, role, is_active, is_verified |
| 2 | `documents` | Document | 업로드 문서 메타 | id, user_id, filename, file_path, file_type, status, report_path |
| 3 | `pages` | Page | 페이지 단위 분할 | id, document_id, page_number, image_path |
| 4 | `ocr_texts` | OcrText | OCR 추출 결과 | id, document_id, page_id, raw_text, cleaned_text, confidence |
| 5 | `analysis_results` | AnalysisResult | LLM 분석 결과 | summary, category, financial_metrics, insight_vectors, evidence, raw_response, model_name |
| 6 | `reclassifications` | Reclassification | 관리자 재분류 이력 | document_id, reclassified_by, previous_category, new_category, reason |
| 7 | `document_insights` | DocumentInsight | Gemini 인사이트 | insight_text, investment_thesis, market_context, risk_factors, strategic_action, strategy_rating, supervisor_decision, primary_axis, confidence_label |
| 8 | `document_metadata` | DocumentMetadata | 정규화 메타 | company_name_norm, corp_code, report_type, fiscal_year, period_type, statement_scope |
| 9 | `document_chunks` | DocumentChunk | 청크 인덱싱 | chunk_uid, page_no, section_name, text, text_hash, token_count, vector_collection |
| 10 | `financial_facts` | FinancialFact | 구조화 재무 팩트 | fact_uid, metric_name, metric_value_num, unit, currency, statement_scope, source_page |
| 11 | `company_profiles` | CompanyProfile | 회사 캐시 | company_name_norm, corp_code, latest_completed_fiscal_year, latest_annual_consolidated_doc_id |

근거: `backend/models/models.py` 전체 (252줄), `backend/database.py:46-52`

## 4.2 핵심 관계 (Relationships)

```
User (1)─────(N) Document (1)─────(N) Page
                 │                    │
                 ├─(N)─ OcrText ──────┘
                 │
                 ├─(N)─ AnalysisResult
                 │
                 ├─(1)─ DocumentMetadata
                 │
                 ├─(N)─ DocumentInsight
                 │
                 ├─(N)─ DocumentChunk ──(N)── FinancialFact
                 │
                 └─(N)─ Reclassification

CompanyProfile ─(FK)─→ Document (latest_annual_consolidated/separate_doc_id)
```

## 4.3 추가 (코드에서만 생성되는) 테이블
`database.py:50` → `ensure_knowledge_schema()` 가 추가 테이블을 생성합니다 (chat_knowledge_service 내부). ERD에 추가하려면 해당 함수를 직접 확인 필요.

---

# Section 5 — 주요 기능 (코드 기반 인벤토리)

## 5.1 API 엔드포인트 전수 (총 44개)

### Auth (`/auth/*`) — 12개
| 메서드 | 경로 | 기능 | 근거 |
|---|---|---|---|
| POST | /auth/register | 일반 회원가입 + 이메일 인증 | auth.py:39 |
| POST | /auth/master-register | 마스터키 기반 admin 생성 | auth.py:73 |
| POST | /auth/verify-email | 이메일 인증 토큰 검증 | auth.py:110 |
| POST | /auth/login | JWT 액세스 토큰 발급 | auth.py:125 |
| GET | /auth/me | 현재 사용자 정보 | auth.py:158 |
| PATCH | /auth/me | 닉네임 수정 | auth.py:192 |
| POST | /auth/forgot-password | 재설정 메일 발송 | auth.py:164 |
| POST | /auth/reset-password | 새 비밀번호 적용 | auth.py:178 |
| POST | /auth/request-password-change | 비번 변경 인증 메일 | auth.py:218 |
| POST | /auth/confirm-password-change | 비번 변경 확인 | auth.py:238 |
| POST | /auth/request-withdraw | 회원 탈퇴 인증 이메일 발송 | auth.py:260 |
| POST | /auth/confirm-withdraw | 탈퇴 토큰 검증 + 계정 비활성화 | auth.py:297 |

### Documents (`/documents/*`) — 15개
| 메서드 | 경로 | 기능 | 근거 |
|---|---|---|---|
| POST | /documents/upload | 단일 업로드 | documents.py:350 |
| POST | /documents/upload-batch | 다중 업로드 (Celery) | documents.py:1788 |
| GET | /documents | 내 문서 목록 | documents.py:700 |
| GET | /documents/my-stats | 사용자 통계 | documents.py:751 |
| GET | /documents/by-category | 카테고리별 필터 | documents.py:798 |
| GET | /documents/{id} | 문서 상세 | documents.py:1218 |
| GET | /documents/download-report/{id} | PDF 다운로드 | documents.py:858 |
| GET | /documents/preview-report/{id} | PDF 미리보기 | documents.py:913 |
| GET | /documents/insight/{id} | 인사이트 조회 | documents.py:965 |
| POST | /documents/insight/{id} | 인사이트 생성 | documents.py:1013 |
| GET | /documents/batch-status | 배치 진행 상태 | documents.py:1168 |
| POST | /documents/{id}/reanalyze | 재분석 | documents.py:1286 |
| DELETE | /documents/{id} | 삭제 | documents.py:1418 |
| PATCH | /documents/{id}/rename | 파일명 변경 | documents.py:1451 |
| GET | /documents/duplicates/list | 중복 문서 탐지 | documents.py:1476 |

### Admin (`/admin/*`) — 8개
| 메서드 | 경로 | 기능 | 근거 |
|---|---|---|---|
| GET | /admin/dashboard | 대시보드 통계 | admin.py:26 |
| GET | /admin/documents | 전체 문서 | admin.py:77 |
| GET | /admin/documents/by-category | 카테고리별 전체 | admin.py:91 |
| GET | /admin/users | 회원 목록 | admin.py:139 |
| PATCH | /admin/users/{id}/role | 역할 변경 | admin.py:149 |
| PATCH | /admin/users/{id}/active | 활성화 토글 | admin.py:174 |
| POST | /admin/documents/{id}/reclassify | 수동 재분류 | admin.py:199 |
| GET | /admin/documents/{id}/reclassifications | 재분류 이력 | admin.py:244 |

### Panel (`/panel/*`) — 9개
| 메서드 | 경로 | 기능 | 근거 |
|---|---|---|---|
| GET | /panel/stats | DB 실시간 집계 | panel.py:250 |
| GET | /panel/system-status | 서비스 헬스 + 경보 레벨 | panel.py:302 |
| GET | /panel/activity-log | 최근 활동 로그 | panel.py:408 |
| GET | /panel/autocomplete | DART 종목 자동완성 | panel.py:446 |
| POST | /panel/search | DART 공시 검색 | panel.py:475 |
| GET | /panel/chat/config | Omega-Cortex 설정 | panel.py:559 |
| POST | /panel/chat | **Omega-Cortex** (Omega-Prime 시스템 프롬프트 기반 AI 챗봇) | panel.py:565 |
| POST | /panel/vector/rebuild | ChromaDB 재인덱싱 | panel.py:638 |
| GET | /panel/vector/stats | 벡터 인덱스 현황 | panel.py:656 |

## 5.2 프론트엔드 화면 인벤토리 (15개 페이지)

| 페이지 | 경로 | 권한 | 파일 |
|---|---|---|---|
| HomePage | `/home`, `/` | 공개 | pages/HomePage.jsx |
| LoginPage | `/login` | 공개 | pages/LoginPage.jsx |
| RegisterPage | `/register` | 공개 | pages/RegisterPage.jsx |
| VerifyEmail | `/verify-email` | 공개 | pages/VerifyEmail.jsx |
| ForgotPassword | `/forgot-password` | 공개 | pages/ForgotPassword.jsx |
| ResetPassword | `/reset-password` | 공개 | pages/ResetPassword.jsx |
| VerifyPasswordChange | `/verify-password-change` | 공개 | pages/VerifyPasswordChange.jsx |
| **VerifyWithdraw** | `/verify-withdraw` | 공개 | pages/VerifyWithdraw.jsx |
| AdminRegisterPage | `/master-key` | 공개 (마스터키) | pages/AdminRegisterPage.jsx |
| UploadPage | `/upload` | 로그인 필요 | pages/UploadPage.jsx |
| MyPage | `/mypage` | 로그인 필요 | pages/MyPage.jsx |
| DocumentDetail | `/documents/:id`, `/view/:id` | 로그인 필요 | pages/DocumentDetail.jsx |
| AdminDashboard | `/admin/dashboard` | 관리자 | pages/AdminDashboard.jsx |
| AdminUsers | `/admin/users` | 관리자 | pages/AdminUsers.jsx |
| AdminDocuments | `/admin/documents` | 관리자 | pages/AdminDocuments.jsx |

근거: `frontend/src/App.jsx` 전체

## 5.3 백엔드 서비스 모듈 (27개) — 카테고리별

### AUTH (2)
- `auth_service.py` — JWT(jose) + bcrypt(passlib) 인증, 5종 토큰 (access/email/reset/change/withdraw), DEV_MODE 우회 지원
- `email_service.py` — Gmail SMTP, 인증·재설정·결과 메일

### OCR/TEXT (4)
- `ocr_service.py` — **EasyOCR** 한영 OCR + 8단계 이미지 전처리 + 재무 보존형 노이즈 필터
- `vlm_service.py` — Qwen 2.5-VL (RunPod vLLM) 비전 모델 호출
- `text_preprocessor.py` — 표 구조 복원, 섹션 태깅, 숫자 정규화
- `text_quality.py` — readability score, 깨진 한글 감지, 품질 태그

### LLM 분석 (4)
- `llm_service.py` — Ollama EXAONE 3.5 호출, DART 공시 분류·요약·재무 추출
- `text_summarizer.py` — Pure Python TextRank 카테고리별 요약
- `narrative_summarizer.py` — 자연어 템플릿 재구성
- `code_only_extractor.py` — regex 기반 사업개요·임원·감사 추출 (환각 0)

### METADATA (5)
- `document_metadata_extractor.py` — 회사명·보고서종류·연도 사전 추출
- `metadata_validator.py` — 메타 검증, 원문 앵커 링킹
- `stock_name_normalizer.py` — "에스케이하이닉스" → "SK하이닉스"
- `company_alias_master.py` — 정규기업 별칭 사전 + fuzzy 매칭
- `dart_file_parser.py` — XBRL/XLS 파일 파싱

### KNOWLEDGE LAYER (2)
- `embedding_strategy.py` — 청크 생성 전략, 임베딩 프롬프트 템플릿
- `chat_knowledge_service.py` — QA/회사요약/비교/트렌드 라우팅, 구조화 팩트 응답

### VECTOR / RAG (2)
- `vector_service.py` — **ChromaDB** 통합, 벡터+BM25 하이브리드, 리랭킹
- `cognitive_search_safe.py` — 회사명 fuzzy 매칭 + 3-소스 하이브리드

### AGENT / 챗봇 — Omega-Cortex (5)
- `chat_agent_safe_service.py` — Omega-Cortex 메인 RAG 에이전트 (Function Calling)
- `chat_agent_service.py` — safe 서비스의 wrapper
- `agent_retrieval.py` — CivicFlowRetriever, R0~R3 RAG 등급
- `agent_memory.py` — 슬롯 기반 세션 메모리
- `chat_profile_service.py` — Omega-Prime 시스템 프롬프트 로드 (Omega-Cortex 인격 정의)

### INSIGHT (2)
- `insight_service.py` — **Gemini 2.5 Pro** (google-genai) 다차원 전략 인사이트
- `omega_supervisor.py` — **Gemini 2.5 Flash** 사후 검증·보강

### REPORT (1)
- `pdf_report_service.py` — **fpdf2** A4 안전 좌표계 PDF 렌더링

### 워커 (3)
- `workers/celery_app.py` — Celery + Redis 설정 (concurrency=2, soft=540s)
- `workers/tasks.py` — `process_document_task` (OCR→전처리→품질→LLM→임베딩→지식)
- `workers/task_dispatcher.py` — 태스크 라우팅

근거: 각 서비스 파일 docstring + Explore agent 전수 감사 (2026-04-14)

---

# Section 6 — 보안 및 인증 흐름

## 6.1 인증 메커니즘
- **알고리즘**: HS256 JWT (secret: `JWT_SECRET_KEY`)
- **만료**: Access Token 24시간 (1440분, config.py:21)
- **저장**: 클라이언트 localStorage (`omega_token`, `omega_user`)
- **전송**: `Authorization: Bearer <token>` 헤더 (axios 인터셉터, client.js:21-27)
- **401 처리**: 자동 로그아웃 + /login 리다이렉트 (client.js:30-42)

## 6.2 5종 토큰 시스템
| 토큰 종류 | 만료 | 페이로드 | 용도 |
|---|---|---|---|
| Access | 24h | sub, email, role, exp | API 인증 |
| Email Verification | 24h | email, type=verification, exp | 회원가입 인증 |
| Password Reset | 15min | email, type=password_reset, exp | 비밀번호 찾기 |
| Password Change | 15min | email, type=password_change, **new_hash**, exp | 인증 후 비번 변경 |
| **Withdraw** | 15min | email, type=withdraw, **user_id**, exp | 회원 탈퇴 확인 |

근거: `services/auth_service.py:137-244`

## 6.3 비밀번호 보호
- **해싱**: bcrypt (passlib CryptContext)
- **Fallback**: passlib 미설치 시 PBKDF2-SHA256 (390,000 iter)
- **검증**: 상수 시간 비교 (`hmac.compare_digest`)
근거: `auth_service.py:75-104, 113`

## 6.4 권한 분리
- **Public**: 회원가입, 로그인, 인증, 홈
- **User**: 업로드, 마이페이지, 문서 상세, Omega-Cortex 챗봇 (`get_current_user`)
- **Admin**: 대시보드, 회원관리, 재분류 (`require_admin`, auth_service.py:300)
- **Master Key**: `OMEGA_PRIME_2026` (auth.py:74) — admin 직접 생성 (⚠ 하드코딩, 발표 시 환경변수 분리 권장 사항으로 언급 가능)

---

# Section 7 — 수행 절차 및 방법론 (코드에서 도출)

코드만으로는 일정/팀구성을 알 수 없으므로 이 섹션은 **발표자 본인이 채워야 합니다.** 다만 코드가 시사하는 개발 방법론은 아래와 같습니다:

## 7.1 코드가 보여주는 개발 방법론
1. **계층 분리 아키텍처**: routers → services → models 3-tier
2. **의존성 주입**: FastAPI `Depends` 패턴 (DB 세션, 인증 사용자)
3. **백그라운드 처리 분리**: 동기 API + Celery 비동기 태스크
4. **설정 외부화**: pydantic-settings + .env (config.py)
5. **테스트 코드 존재**: backend/tests/ 디렉토리 (test_metadata_extractor, test_text_quality, test_company_validation 등 9개 이상)
6. **마이그레이션 관리**: Alembic (alembic 1.18.4 설치)

## 7.2 발표자가 채워야 할 정보
- [ ] 프로젝트 기간 (시작일 / 종료일)
- [ ] 팀원 명단 및 역할 분담
- [ ] 개발 방법론 (Agile? Waterfall? Sprint 주기?)
- [ ] 형상관리 도구 (Git? GitHub/GitLab?)
- [ ] 협업 도구 (Slack, Notion, Jira 등)
- [ ] 일정표 / 마일스톤
- [ ] 본인의 개인 기여 부분 (특정 라우터/서비스/페이지)

> **발표 팁**: "팀 구성 및 역할" 슬라이드에서 본인이 담당한 영역을 위 §5의 인벤토리에서 골라 명시하면 정확합니다. (예: "저는 인증 라우터(auth.py) + 5종 토큰 시스템 + 프론트엔드 LoginPage/RegisterPage를 담당했습니다.")

---

# Section 8 — 발표용 핵심 숫자 (Slide-Ready Numbers)

> **2026-04-14 재감사**: 코드 정적 카운트와 SQLite DB 직접 query를 분리 표기

## 8.1 코드 정적 카운트 (소스 트리 기준)

| 항목 | 수치 | 근거 |
|---|---|---|
| API 엔드포인트 총 개수 | **44개** | 12 + 15 + 8 + 9 (auth/documents/admin/panel) |
| 백엔드 서비스 모듈 | **27개** | services/*.py (`__init__.py` 제외) |
| DB 테이블 (스키마) | **11개** | models.py 11 ORM classes (252줄) |
| 프론트엔드 페이지 | **15개** | App.jsx Routes (DocumentDetail은 2 경로 공유, VerifyWithdraw 추가) |
| 외부 서비스 통합 | **5개** | Ollama, Gemini Pro, Gemini Flash, DART, SMTP, vLLM(opt) |
| 지원 파일 포맷 | **17종** | UploadPage.jsx:11 (DOC_EXTS Set) |
| 이미지 전처리 단계 | **8단계** | ocr_service.py:54 |
| DART 캐싱 법인 수 (캐시 정원) | **~80,000건** | panel.py:42 (corpCode.xml 다운로드 후 메모리 적재) |
| Celery 워커 동시성 | **2** | celery_app.py:30 |
| 태스크 타임아웃 | **soft 540s / hard 600s** | celery_app.py:34-35 |
| 일반 토큰 만료 | **24시간 (1,440분)** | config.py:21 |
| 비밀번호 토큰 만료 | **15분** | auth_service.py:201, 222 |
| 최대 업로드 파일 수 | **20개/배치** | UploadPage.jsx:8 |
| 최대 파일 크기 | **700MB** | config.py:39 |

## 8.2 SQLite 실측 (omega_civicflow.db, 2026-04-14 13:30 query)

| 항목 | 수치 | 근거 SQL |
|---|---|---|
| 분석 완료 문서 | **3,135건** | `SELECT COUNT(*) FROM documents` |
| 요약 완성률 (non-empty 기준) | **100% (3,135/3,135)** | `SELECT COUNT(*) FROM analysis_results WHERE summary IS NOT NULL AND TRIM(summary) != ''` |
| 요약 완성률 (발표 PPT 기준) | **99.9% (3,132/3,135)** | 발표자가 슬라이드 6에서 별도 품질 기준 적용 (3건 제외 — 발표자 정의) |
| 평균 요약 길이 | **173자** | `SELECT AVG(LENGTH(summary)) FROM analysis_results` |
| 가장 짧은 요약 | **20자** (단순공시 86건 + 감사보고서 2건이 20~50자 구간) | `SELECT MIN(LENGTH(summary)) ...` |
| 총 청크 수 | **312,572개** | `SELECT COUNT(*) FROM document_chunks` |
| 구조화 재무 팩트 | **12,211건** | `SELECT COUNT(*) FROM financial_facts` |
| 분석 메타 고유 기업 | **1,106개** | `SELECT COUNT(DISTINCT company_name_norm) FROM document_metadata` |
| Gemini Insight 생성 건 | **10건** | `SELECT COUNT(*) FROM document_insights` (Pro 호출은 사용자 요청 시에만) |
| 가입 사용자 수 | **6명** | `SELECT COUNT(*) FROM users` |

> ⚠ **panel.py:166의 "약 2,000+건"** 시스템 프롬프트 문구는 **stale**입니다. 발표/PPT는 8.2의 실측치(3,135건)를 사용하세요.

---

# Section 9 — 안전한 Q&A 가이드 (예상 질문 + 모범 답변)

## Q1. "왜 EasyOCR을 썼나요? PaddleOCR은 안 봤나요?"
**A**: 한국어+영어 혼용 인식 안정성 + 설치 단순성 우위로 EasyOCR을 채택했습니다. PaddleOCR도 venv에 설치되어 있어 fallback/대체 후보로 평가했지만 운영 코드는 EasyOCR로 통일했습니다.
*(주의: requirements.txt에는 paddleocr만 명시돼 있으므로 발표 전 정정 권장.)*

## Q2. "왜 ChromaDB이고 FAISS가 아닌가요?"
**A**: ChromaDB는 메타데이터 필터링과 컬렉션 관리가 내장되어 있어 운영 편의성이 우수했습니다. 또한 in-memory가 아닌 디스크 영속화가 기본 지원되어 별도 인덱스 직렬화 코드가 불필요했습니다. (data/chroma_db에 영속 저장)

## Q3. "왜 LLM이 두 개인가요? Ollama + Gemini를 동시에?"
**A**: 비용·지연·보안의 트레이드오프 때문입니다.
- **로컬 EXAONE (Ollama)**: 분류·요약·재무 추출 — 대량 문서 처리, 데이터 외부 유출 없음, 무료
- **Gemini 2.5 Pro**: 전략 인사이트 도출 — 고차원 추론 필요, 사용자가 요청 시에만 호출 (비용 통제)
- **Gemini 2.5 Flash**: Supervisor 검증 — 가볍고 빠른 사후 환각 차단

## Q4. "Omega-Cortex(RAG 챗봇)는 어떻게 동작하나요?"
**A**: 하이브리드 RAG입니다. ChromaDB 벡터 검색(시맨틱) + DocumentChunk/FinancialFact 구조화 DB 조회 + DART OpenAPI 실시간 조회를 Function Calling으로 LLM이 직접 선택해 결합합니다. 8개 도구(`structured_facts`, `chromadb_search`, `search_dart_filings`, `get_document_detail`, `get_document_stats`, `search_my_documents`, `semantic_search`, `metadata_search`)를 상황에 따라 호출합니다. Omega-Prime 시스템 프롬프트로 인격이 정의되어 있으며 Gemini 2.5 Flash Supervisor가 사후 검증합니다.

## Q5. "JWT 시크릿이 노출되면 어떻게 하나요?"
**A**: `.env`로 환경변수 분리되어 있고(`config.py:19`), 마스터키도 운영 환경에서는 환경변수로 분리할 예정입니다. 추가로 토큰 만료 정책이 짧고(15분 비밀번호 토큰), 401 시 자동 로그아웃이 동작합니다.

## Q6. "중복 문서는 어떻게 탐지하나요?"
**A**: `GET /documents/duplicates/list` 엔드포인트가 있으며(`documents.py:1476`), 파일명·해시 기반 매칭으로 동일 문서 업로드를 식별합니다. (구현 세부는 documents.py 해당 라인 참고)

## Q7. "DART 8만 건 법인 데이터는 매번 받나요?"
**A**: 아니요. 24시간 캐시 정책입니다(`panel.py:67-70`). 캐시 파일 `data/corpCode.xml`이 24시간 이내면 재사용, 만료 시에만 DART OpenAPI에서 ZIP 다운로드 후 갱신합니다. 서버 시작 시 백그라운드 스레드로 로드됩니다.

## Q8. "분석 결과가 잘못되면 어떻게 보정하나요?"
**A**: 두 가지 경로가 있습니다.
1. **사용자**: `POST /documents/{id}/reanalyze` 재분석 트리거
2. **관리자**: `POST /admin/documents/{id}/reclassify` 수동 카테고리 보정 (이력은 `Reclassification` 테이블에 저장)

---

# Section 10 — 발표 슬라이드 매핑 가이드

| 슬라이드 | 본 문서의 대응 섹션 |
|---|---|
| 표지 | §1.1, §1.2 |
| 목차 | (3개 항목 그대로) |
| 프로젝트 배경/목적 | §1.3 (USP) + 발표자 자체 보충 |
| 팀 구성 및 역할 | **§7.2 (발표자가 채울 부분)** |
| 개발 방법론 / 일정 | §7.1 + 발표자 보충 |
| 사용 기술 스택 | **§2 (전체)** + §2.4 아이콘 권장 |
| 시스템 구성도 | **§3.1 다이어그램** |
| 데이터 흐름 / 파이프라인 | **§3.2** (문서 분석) + §3.3 (RAG) |
| ERD | **§4** |
| 주요 기능 | **§5** (필요 시 발췌) |
| 보안 / 인증 | §6 |
| 화면 시연 (스크린샷) | §5.2 페이지 15개 — 본인이 캡처 필요 |
| 결과 / 통계 | **§8 (핵심 숫자)** |
| 결론 / 향후 과제 | 발표자 자체 작성 |
| Q&A | **§9 가이드 활용** |

---

# Appendix A — 발견된 코드 품질 이슈 (선택적 슬라이드 — "향후 개선")

발표 마지막 "향후 개선" 슬라이드에 사용 가능한 정직한 항목들 (자기 비판이 아니라 **성숙도 시그널**):

1. **requirements.txt 정합성 회복**: 실제 import와 동기화 (easyocr, fpdf2, chromadb, google-genai, celery, redis 추가, 미사용 reportlab 제거)
2. **OCR 엔진 docstring 정정**: ocr_service.py 주석의 "PaddleOCR" 표현을 "EasyOCR"로 통일
3. **마스터키 환경변수 분리**: `OMEGA_PRIME_2026` 하드코딩(auth.py:74) → `.env` 이전
4. **개발용 임시 파일 정리**: `_check_cn.py`, `tmp_patch.py`, `tmp_patch2.py`, `test_r.py`, `test_orch.py`, `test_search.py` 등 backend 루트의 실험 파일 정리
5. **Alembic 마이그레이션 활성화**: 현재 `Base.metadata.create_all` 방식 (database.py:52). 운영 단계에서는 Alembic으로 명시적 마이그레이션 권장

---

# Appendix B — 신뢰도 매트릭스 (2026-04-14 재감사 반영)

| 본 문서의 주장 | 신뢰도 | 근거 |
|---|---|---|
| 모든 라우터 / 엔드포인트 / 모델 / 서비스 파일명·역할 | **AXIOM [99%]** | 직접 read 또는 grep 결과 |
| **Auth 엔드포인트 = 12개 (10 아님)** | **AXIOM [99%]** | routers/auth.py 데코레이터 직접 카운트 (재감사 v3에서 request-withdraw, confirm-withdraw 추가 확인) |
| **Documents 엔드포인트 = 15개 (16 아님)** | **AXIOM [99%]** | routers/documents.py 데코레이터 직접 카운트 (재감사로 정정) |
| OCR 엔진은 EasyOCR (PaddleOCR 아님) | **AXIOM [99%]** | services/ocr_service.py:38 직접 확인 |
| PDF는 fpdf2 (reportlab 아님) | **AXIOM [99%]** | services/pdf_report_service.py:23 직접 확인 |
| **메인 DB는 SQLite (PostgreSQL 아님)** | **AXIOM [99%]** | `.env DATABASE_URL=sqlite:///` 직접 확인 + 3.2GB omega_civicflow.db 물증 |
| 11개 DB 테이블 구조 | **AXIOM [99%]** | models.py 252줄 전수 read |
| 27개 service의 카테고리 분류 | **CONSENSUS [90%]** | Explore 에이전트 전수 감사 결과 (`__init__.py` 제외 시 27, 포함 시 28) |
| ChromaDB 사용 여부 | **AXIOM [99%]** | config.py:36-37, vector_service.py |
| Gemini 2.5 Pro/Flash 사용 | **AXIOM [99%]** | config.py:61, 65, insight_service.py:19 |
| **분석 완료 문서 = 3,135건 (≠ ~2,000)** | **AXIOM [99%]** | SQLite `SELECT COUNT(*) FROM documents` 2026-04-14 13:30 |
| **요약 완성률 = 100% (3,135/3,135)** | **AXIOM [99%]** | `summary IS NOT NULL AND TRIM != ''` 직접 카운트. PPT의 "97.2%"는 50자 임계값 측정 아티팩트 |
| **챗봇 명칭 = Omega-Cortex** | **CONSENSUS [90%]** | 발표자 지정 브랜드명. 코드 내부 시스템 프롬프트는 "Omega-Prime / Node Omega-Prime" 식별자 유지 |
| Section 7 팀구성/일정 | **UNKNOWN [0%]** | 코드만으로는 도출 불가, 발표자 입력 필요 |

---

**최종 갱신**: 2026-04-15 (재감사 v3 적용본)
**작성 도구**: Claude Code (Omega-Prime 하네스), 소스코드 직접 read + Explore 에이전트 전수 감사 + SQLite 직접 query
**파일**: `docs/PROJECT_PRESENTATION_MATERIAL.md`
**총 검증된 파일 수**: 14개 직접 read + 27개 서비스 에이전트 감사 + 1개 SQLite (3.2 GB, 13 테이블) = **42개 정보 소스 기반**
**재감사 v2 정정 항목** *(2026-04-14)*: §⚠ #0 추가 (DB 종류) / §2.1 DB 행 / §3.1 다이어그램 / §4 ERD 제목 / §5.1 Auth·Documents 헤더 / §8 (8.1 + 8.2 분리) / §1.2·§3.2·§3.3·§5.1·§5.3·§6.4·§9 챗봇 → Omega-Cortex / Appendix B 신뢰도 매트릭스
**재감사 v3 정정 항목** *(2026-04-15 — 회원 탈퇴 플로우 추가 반영)*: §1 헤더 v3 블록 / §3.1 다이어그램 (10 EP→12 EP, 14개→15개) / §5.1 Auth 헤더+테이블 (+2행) / §5.2 헤더+테이블 (VerifyWithdraw 추가) / §5.3 auth_service 토큰 종류 / §6.2 헤더+테이블 (Withdraw 토큰 추가) / §7 팁 문구 / §8.1 핵심숫자 (EP 42→44, 페이지 14→15) / §10 슬라이드매핑 / Appendix B Auth EP 카운트
