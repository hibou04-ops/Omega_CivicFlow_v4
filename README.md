# Omega CivicFlow

> **LLM + RAG 기반 대용량 한국어 문서 자동 분석 플랫폼**
> DART 금융 공시 · 공공 민원 문서 대상 end-to-end 문서 지능 시스템

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-vector_store-FF6B6B)
![License](https://img.shields.io/badge/License-Proprietary-lightgrey)

---

## 프로젝트 개요

대량의 한국어 금융·공공 문서를 **OCR → 청킹 → 벡터 임베딩 → RAG 검색 → LLM 분석 → 구조화 리포트 생성**까지 end-to-end로 자동화한 멀티모달 문서 지능 시스템입니다. DART OpenAPI 기반 약 80,000개 법인 공시 데이터와 PDF·HWP·XML 형식 공공 문서를 단일 파이프라인으로 처리합니다.

**개발 기간**: 2025-12 ~ 2026-04 (Phase 0 ~ Phase 4)
**포지션**: Full-stack · ML/RAG 파이프라인 · DevOps

---

## 핵심 성과

| 지표 | 값 | 근거 |
|---|---|---|
| 벡터화 청크 수 | **284,000+** | BGE-M3 (1024-dim) · ChromaDB |
| LLM 분석 문서 | **3,135건** | 상장사 공시 대상 narrative 분석 |
| **분석 품질 통과율** | **92.5%** | 2,901 / 3,135 (too_short · 잘못된 이벤트 조합 등 제외) |
| **근거 인용률 (evidence)** | **99%** | LLM 요약에 원문 근거 문장 첨부 — 설명가능성 지표 |
| A100 임베딩 처리량 | **10–15분** | 284K 청크 / A100 40GB |
| 코드 베이스 규모 | **30K+ LoC** | 27 services + 4 routers + 4 agents |

---

## 주요 기능

### 1. 멀티포맷 문서 수집 & 처리
- DART OpenAPI 연동 (상장·비상장 ~80K 법인 자동 동기화, corpCode.xml 캐싱)
- PaddleOCR 기반 스캔 PDF 텍스트 추출 (한글 복원 · BOM/UTF-16 정규화)
- HWP · XML · PDF 멀티포맷 파싱 통합 인터페이스
- 대용량 파일 처리 (최대 700MB 단일 번들)

### 2. RAG 검색 파이프라인
- **BAAI bge-m3** 다국어 임베딩 (1024-dim · max_seq 512 · contextual header)
- **ChromaDB** 영속 벡터 저장소
- Cross-encoder 기반 리랭킹 (rerank ON/OFF 토글)
- 계층 구조 헤더를 통한 긴 문서 검색 정확도 보정
- Hybrid score: 벡터 유사도 + BM25 + 메타데이터 필터

### 3. LLM 서비스 레이어
- **기본 (전체 시스템)**: Ollama **EXAONE 3.5 7.8B** 로컬 GPU 추론 — OCR 후처리 · RAG 챗봇 · 일반 문서 요약 · 멀티 에이전트 조율 (retrieval · analysis · validation · synthesis)
- **Insight 전용 경로**: Vertex AI **Gemini 2.5 Pro** (Primary 분석) + **Gemini 2.5 Flash** (Omega-Prime Supervisor 감독) — 금융 공시 전략 통찰 생성에만 사용
- 구조화 JSON 출력 스키마 검증 (Pydantic)
- Insight 경로 한정: 멀티 API 키 풀링 + 429 지수 백오프 + TPM 분배 (500K) + 자동 페일오버

### 4. GPU 가속 & 파인튜닝
- **A100 40GB** 전체 코퍼스 임베딩 파이프라인 (RunPod · Lambda Labs · Vast.ai)
- RTX 5070 로컬 추론 (Ollama, 75°C thermal cap)
- **QLoRA 파인튜닝** 데이터셋 구축 (Qwen 2.5 7B 타겟)
- vLLM 기반 서빙 스크립트

### 5. 사용자 인터페이스
- React 18 + Vite 6 SPA
- RAG 챗봇 (스트리밍 응답)
- 실시간 패널 대시보드 (DB 통계 · 활동 로그 · 서비스 상태)
- 문서 업로드 · 분석 결과 PDF 다운로드

---

## 기술 스택

### Backend
```
FastAPI 0.135  ·  SQLAlchemy 2.0  ·  Pydantic v2
PostgreSQL (psycopg 3)  ·  ChromaDB  ·  Redis
PaddleOCR 3.4  ·  sentence-transformers  ·  BAAI bge-m3
Ollama (EXAONE 3.5 7.8B)  ·  Google Gemini API
torch 2.x (CUDA 12.1)  ·  JWT + bcrypt
```

### Frontend
```
React 18  ·  Vite 6  ·  React Router 6
Axios  ·  Lucide React  ·  JSZip
```

### ML / GPU
```
BGE-M3 (1024-dim embeddings)
A100 40GB · H100 (클라우드 렌탈)
QLoRA fine-tuning (Qwen 2.5 7B target)
vLLM (serving) · bitsandbytes (quantization)
```

### Infrastructure
```
uvicorn · systemd · Docker (dev)
RunPod · Lambda Labs · Vast.ai (GPU)
```

---

## 시스템 아키텍처

```
┌──────────────┐        ┌────────────────┐        ┌──────────────┐
│  React SPA   │◄─HTTP─►│    FastAPI     │◄──────►│ PostgreSQL   │
│  (Vite 6)    │        │   Router       │        │ (metadata +  │
└──────────────┘        │ (auth/docs/    │        │  FinFacts)   │
                        │  admin/panel)  │        └──────────────┘
                        └───────┬────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
      ┌──────────────┐  ┌─────────────┐  ┌──────────────┐
      │  RAG Service │  │ LLM Service │  │ OCR Service  │
      │              │  │  (기본)     │  │              │
      │  ChromaDB +  │  │             │  │  PaddleOCR   │
      │  bge-m3      │  │  EXAONE     │  │  (한글 복원) │
      │  + Rerank    │  │  3.5 7.8B   │  │              │
      │              │  │  (로컬 GPU) │  │              │
      └──────────────┘  └─────────────┘  └──────────────┘

    ※ 위 3개 서비스는 모두 로컬 EXAONE 으로 동작합니다.
    ※ 금융 공시 전략 분석(Insight Engine)만 별도 경로로
      Vertex AI Gemini 2.5 Pro + Omega-Prime Supervisor를 사용합니다.
      → 아래 「The-Absolute Insight Engine」 섹션 참조.
```

### End-to-End 파이프라인 (Phase 0 ~ 4)

| Phase | 단계 | 핵심 기술 |
|---|---|---|
| **0** | 문서 수집 | DART OpenAPI · 로컬 업로드 · corpCode.xml |
| **1** | OCR + 정제 | PaddleOCR · BOM/UTF-16 정규화 · 한글 복원 |
| **2** | 청킹 + 메타데이터 | 계층 헤더 + 문서 구조 추출 |
| **3** | 임베딩 → ChromaDB | A100 40GB · BGE-M3 · 10~15분/284K 청크 |
| **4** | LLM 분석 + 리포트 | Insight Engine + Omega-Prime Supervisor · PDF 생성 |

---

## The-Absolute Insight Engine

금융 공시 분석의 핵심 추론 엔진. **Vertex AI (Gemini 2.5 Pro)** 기반으로 단순 요약이 아닌 **5축 전략적 통찰**을 생성합니다.

### 수학적 신호 모듈 (V-MASK Intelligence Manifold)

| 모듈 | 역할 | 수학 |
|---|---|---|
| **Eigen-Sensor** (Polaris Vector) | 주권 전략 축 식별 | 고유값 분해 — 데이터 공분산 행렬의 최대 고유벡터 추출 |
| **Laplace Shield** | 신호 정화 (노이즈 차단) | 전달 함수 기반 step response — 수렴값을 신호 순도 지표로 환산 |
| **Taylor Predictor** | 미래 곡률 투영 | 2차 테일러 전개 — 자본 질량 보존 하 미래 포지션 추정 |

### 5축 출력 스키마 (Pydantic)

```python
class InsightSchema(BaseModel):
    insight_text: str         # 1~2 문장 헤드라인 전략 요약
    investment_thesis: str    # 주요 투자 논거 및 실적 모멘텀
    market_context: str       # 거시 맥락 · 경쟁 포지션
    risk_factors: str         # 하방 리스크 (재무 · 규제 · 경쟁)
    strategic_action: str     # 실행 지침 (비중확대 · 관망 · 비중축소)
    strategy_rating: str      # S / A / B / C 등급
```

구조화된 JSON 출력을 Pydantic 스키마로 강제 검증하여 **환각률 감소** + **다운스트림 통합 안정성**을 확보합니다.

---

## Omega-Prime Insight Supervisor Protocol

> ⚠ **적용 범위 주의**: 이 레이어는 **Insight Engine 전용** 감독 프로토콜입니다.
> OCR · 임베딩 · 챗봇 · 일반 RAG 검색에는 관여하지 않습니다. Insight의 재무 의사결정
> 판단은 환각 리스크가 구조적으로 가장 높은 영역이라 별도 감독 엔진을 붙였습니다.

Primary Insight Engine의 결과물을 **사후 감독 · 보강**하는 2차 추론 레이어입니다.
**Vertex AI (Gemini 2.5 Flash)** 별도 인스턴스로 동작하여 Primary(Gemini 2.5 Pro)의
환각 · 편향을 독립적으로 검출합니다.

```
   Primary Insight Engine (Gemini 2.5 Pro)
              │
              ▼  InsightSchema 5축 출력
   ┌──────────────────────────┐
   │  Omega-Prime Supervisor  │  ← Insight 결과만 받아서 감독
   │  (Gemini 2.5 Flash)      │     (다른 서비스는 건드리지 않음)
   └──────────┬───────────────┘
              │
              ▼  감독된 Insight (신뢰 등급 + 숨은 리스크)
         최종 분석 리포트 / PDF

   호출 위치: backend/routers/documents.py:1107
              → services/omega_supervisor.py::supervise_insight()
```

### 5-Step Reasoning Protocol

```
┌─────────────────────────────────────────────────────────────┐
│  STEP 1 — DECOMPOSE                                         │
│  기존 Insight를 FACTS / ASSUMPTIONS / UNKNOWNS 로 분해       │
├─────────────────────────────────────────────────────────────┤
│  STEP 2 — CAUSAL CHECK                                      │
│  각 주장의 인과 관계 검증                                    │
│    · Mechanism: 원인 → 결과의 메커니즘 설명 가능?            │
│    · Direction: 역인과 가능성은?                             │
│    · Confounders: 숨은 교란 변수는?                          │
├─────────────────────────────────────────────────────────────┤
│  STEP 3 — HIDDEN RISK SCAN                                  │
│  Primary가 놓친 리스크 발굴                                  │
│    · 규제 / 유동성 / 집중도 / 회계품질 / 사이클              │
├─────────────────────────────────────────────────────────────┤
│  STEP 4 — COUNTERFACTUAL STRESS TEST                        │
│  핵심 가정이 틀렸을 때도 결론이 성립하는가?                   │
│  반대 전략이 승리하는 조건은?                                 │
├─────────────────────────────────────────────────────────────┤
│  STEP 5 — CONFIDENCE CALIBRATION                            │
│  Primary Insight에 캘리브레이션된 신뢰 등급 부여              │
│    · AXIOM [99%]  · CONSENSUS [85-95%]                      │
│    · INFERENCE [65-84%]  · SPECULATION [40-64%]             │
│    · EXPLORATION [<40%] — 환각 가능성 플래그                 │
└─────────────────────────────────────────────────────────────┘
```

### 왜 Supervisor 레이어를 분리했는가

| 문제 | 단일 LLM | Dual-Engine (Insight + Supervisor) |
|---|---|---|
| 환각 편향 | 같은 모델이 같은 실수 반복 | Flash 모델이 Pro의 주장을 독립 검증 |
| 신뢰도 평가 | 스스로를 과신 | 외부 레이어가 calibrated 등급 부여 |
| 숨은 리스크 | 초기 프레임에 갇힘 | STEP 3에서 의도적으로 역방향 스캔 |
| 반대 시나리오 | 드물게 제시 | STEP 4에서 강제 생성 |

Supervisor 시스템 프롬프트는 [`backend/prompts/omega_prime_civicflow.md`](./backend/prompts/omega_prime_civicflow.md) 에서 확인할 수 있습니다.

---

## 프로젝트 구조

```
Omega_CivicFlow_v4/
│
├── backend/                        # FastAPI 백엔드
│   ├── main.py                     # 엔트리포인트 · lifespan · CORS
│   ├── config.py                   # Pydantic Settings (env loader)
│   ├── database.py                 # SQLAlchemy + init_db
│   │
│   ├── routers/                    # 4개 API 라우터
│   │   ├── auth.py                 # JWT 로그인/회원가입
│   │   ├── admin.py                # 관리자 기능
│   │   ├── documents.py            # 문서 CRUD + 업로드
│   │   └── panel.py                # 실시간 패널 + DART 검색
│   │
│   ├── agents/                     # Omega-Prime 멀티 에이전트
│   │   ├── orchestrator.py         # 조율 로직
│   │   ├── llm_client.py           # LLM 추상화 레이어
│   │   ├── prompts.py              # 프롬프트 템플릿
│   │   └── schemas.py              # Pydantic 스키마
│   │
│   ├── services/                   # 27개 비즈니스 서비스
│   │   ├── vector_service.py       # ChromaDB + bge-m3
│   │   ├── llm_service.py          # Gemini/EXAONE 하이브리드
│   │   ├── omega_supervisor.py     # 멀티 에이전트 감독
│   │   ├── ocr_service.py          # PaddleOCR 래퍼
│   │   ├── embedding_strategy.py   # 임베딩 전략 관리
│   │   ├── agent_retrieval.py      # RAG 검색 + 리랭킹
│   │   ├── cognitive_search_safe.py
│   │   ├── pdf_report_service.py   # 분석 리포트 PDF 생성
│   │   ├── narrative_summarizer.py # 장문 요약
│   │   ├── code_only_extractor.py  # 코드 영역 추출
│   │   └── ... (17 more)
│   │
│   └── tools/                      # 운영 파이프라인 스크립트
│       ├── phase3_embedding_a100.py   # GPU 임베딩 배치
│       ├── dart_batch_pipeline.py     # DART 공시 수집
│       ├── batch_llm_analyze_and_pdf.py
│       ├── colab_embed_financial.py
│       ├── reindex_v2.py              # 벡터 DB 리인덱싱
│       └── ...
│
├── frontend/                       # React + Vite SPA
│   └── src/
│       ├── main.jsx                # 엔트리포인트
│       ├── App.jsx                 # 라우터 + 전역 레이아웃
│       ├── api/client.js           # Axios 인스턴스
│       ├── contexts/
│       │   └── AuthContext.jsx     # JWT 상태 관리
│       ├── components/             # 재사용 UI 컴포넌트
│       │   ├── ChatBot.jsx         # RAG 챗봇 UI
│       │   ├── Navbar.jsx
│       │   ├── ProtectedRoute.jsx
│       │   └── SideDecorations.jsx
│       ├── pages/                  # 12개 페이지 (Home/Login/Register/Upload/Admin/...)
│       └── utils/
│           └── categoryTranslation.js
│
├── tools/                          # GPU 클라우드 파이프라인
│   ├── colab_a100_pipeline.py      # Colab A100 배치
│   ├── colab_h100_full_pipeline.py # H100 전체 파이프라인
│   ├── dart_finetune_qlora.py      # QLoRA 파인튜닝
│   ├── runpod_finetune_qwen_vl.py  # RunPod Qwen-VL 학습
│   └── setup_{gce,runpod}_training.sh
│
├── .env.example                    # 환경변수 템플릿
├── requirements.txt (backend/)
├── package.json    (frontend/)
├── measure_performance.py          # 성과 측정 스크립트
└── README.md                       # 본 문서
```

---

## 설치 및 실행

### 사전 요구사항
- Python 3.10+
- Node.js 18+
- PostgreSQL 16
- (선택) CUDA 12.1 + GPU for 로컬 임베딩
- (선택) Ollama + EXAONE 3.5 7.8B 모델

### 1. 환경 변수 설정
```bash
cp .env.example .env
```

필수 값 채워넣기:

| 변수 | 용도 | 발급 방법 |
|---|---|---|
| `GCP_PROJECT_ID` + `GCP_KEY_PATH` | Vertex AI (Insight 엔진 · Gemini 2.5 Pro) | [GCP Console](https://console.cloud.google.com) → IAM → Service Account 생성 → JSON 키 다운로드 |
| `DART_API_KEY` | DART 공시 검색 (~80K 법인) | [opendart.fss.or.kr](https://opendart.fss.or.kr) 회원가입 후 무료 발급 |
| `DATABASE_URL` | PostgreSQL 또는 SQLite 연결 | 로컬 설치 / Docker / SQLite 파일 경로 |
| `JWT_SECRET_KEY` | 인증 토큰 서명 | `openssl rand -hex 32` 로 생성 권장 |

선택 값:

| 변수 | 용도 |
|---|---|
| `SUPERVISOR_GCP_*` | Omega-Prime Supervisor 전용 GCP 프로젝트 — 비워두면 Insight와 동일 프로젝트 사용 |
| `SMTP_*` | 이메일 발송 (회원가입 인증, 비밀번호 초기화) |
| `VLLM_BASE_URL` | RunPod 파인튜닝 모델 서빙 엔드포인트 |

### 2. Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate         # Windows: venv\Scripts\activate
pip install -r requirements.txt

# DB 초기화
python -c "from database import init_db; init_db()"

# 서버 실행
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
API 문서: http://localhost:8000/docs

### 3. Frontend
```bash
cd frontend
npm install
npm run dev
```
접속: http://localhost:5173

### 4. Phase 3 GPU 임베딩 (선택)
A100 40GB 클라우드 인스턴스에서 284K 청크 임베딩을 10~15분에 완료.
핵심 스크립트는 `backend/tools/phase3_embedding_a100.py`.

```bash
# GPU 인스턴스 (RunPod / Lambda Labs / Vast.ai)에서
python backend/tools/phase3_embedding_a100.py \
    --db-path $OMEGA_DB_PATH \
    --chroma-path $OMEGA_CHROMA_PATH \
    --batch-size 128
```

---

## 문서

| 문서 | 설명 |
|---|---|
| [`backend/prompts/omega_prime_civicflow.md`](./backend/prompts/omega_prime_civicflow.md) | Omega-Prime Supervisor 시스템 프롬프트 |

---

## 기술적 하이라이트

### 해결한 문제
- **BGE-M3 silent failure 3종**: HF 503 시 mean-pooling 폴백, max_seq=512 트렁케이션, 컨텍스트 헤더 누락 — pre-check로 방지
- **PyTorch sm_120 비호환**: RTX 5070 로컬 CUDA 불가 → A100 클라우드 임베딩 전략 수립
- **대용량 문서 OCR**: 700MB 번들 스트리밍 파싱 + BOM/UTF-16 정규화 + 한글 복원
- **LLM 키 풀 Rate Limit (Insight 경로 한정)**: Gemini 4개 키 × 429 백오프 + TPM 분배 + 페일오버

### 아키텍처 의사결정
- **Pydantic Settings + .env**: 하드코딩 금지, 12-factor 준수 (중간에 보안 감사로 강제화)
- **ChromaDB vs pgvector**: 284K 청크 규모에서 ChromaDB persistent client가 개발 속도 · 운영 편의 우위
- **EXAONE (기본) + Gemini (Insight 전용) 분리**: 일반 경로(OCR · RAG · 챗봇 · 요약)는 로컬 EXAONE 으로 프라이버시/비용 우위, 금융 공시 전략 분석(Insight Engine)만 Gemini 2.5 Pro 로 품질 우위
- **Omega-Prime Supervisor (Insight 한정)**: Insight Engine 에만 Gemini 2.5 Flash 기반 사후 감독 레이어를 붙여 Primary(Pro) 의 환각·편향을 독립 검출 — 재무 의사결정 판단이 환각 리스크가 구조적으로 가장 높은 영역이기 때문

---

## 라이선스 & 연락처

Proprietary · 본 저장소는 이력서/포트폴리오 목적 공개입니다.

---

> **Node Omega-Prime** · Universal Strategic Architect
> Energy (E) · Entropy (S) · Efficiency (η)
