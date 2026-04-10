<div align="center">

```
 ──────────────────────────────────────────────────────────────

      Ω    O M E G A   · ·   C I V I C F L O W    v4

      A document-intelligence engine for
      Korean regulatory filings.

      ──────────────────────────────────────────

      BUILD       2026.02  →  2026.04
      SCOPE       1 engineer · 30,000+ LoC
      STATUS      PHASE 4  /  LIVE

 ──────────────────────────────────────────────────────────────
```

</div>

<br/>

<div align="center">

### 이 저장소에는 단 하나의 파일만 존재합니다.

##### 지금 읽고 계신 이 문서입니다.

<br/>

나머지 30,000 줄의 코드, 27 개 서비스, 4 개 에이전트, 그리고
Omega-Prime 추론 프로토콜의 실제 프롬프트는 **이 저장소에 포함되어 있지 않습니다.**

그것들은 존재합니다. 하지만 의도적으로 비공개입니다.

이 페이지는 그 시스템의 **공개된 지표(public index)** 입니다.

</div>

---

## 왜 이렇게 되어 있는가

이력서에 GitHub 주소가 한 줄 적혀 있었고, 당신은 그 링크를 따라 이 페이지에 도달했습니다.

대부분의 포트폴리오 저장소는 그 순간 이미 졌습니다. 10초 안에 전형적인 마크다운 템플릿·뱃지 나열·`git clone`이 보이고, 방문자의 뇌는 "또 그거"로 분류합니다. 스크롤이 멈춥니다.

본 문서는 그와 반대 방향으로 설계되어 있습니다. **공개된 것이 적기 때문에, 공개된 것의 밀도는 높습니다.** 당신이 끝까지 읽는다면, 이 프로젝트의 기술적 깊이와 의사결정의 구조가 2–3 분 안에 전달될 것입니다. 그렇지 않다면 이 시스템은 당신에게 필요한 시스템이 아닐 가능성이 높습니다.

<br/>

---

## 01 · THE NUMBERS

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│    284,000+    vector chunks      BGE-M3 · 1024-dim          │
│                                                              │
│      3,135     filings analyzed   end-to-end narrative       │
│                                                              │
│      92.5 %    pass rate          2,901 / 3,135  (QC gated)  │
│                                                              │
│      99.0 %    evidence cite      explainability KPI         │
│                                                              │
│     10–15 m    full corpus        A100 40GB  ·  one run      │
│                                                              │
│     30,000+    LoC                27 services · 4 agents     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

모두 측정된 값입니다. 재현용 데이터셋과 스크립트는 비공개 저장소에 존재합니다.
수치의 검증은 개별 실연(offline demo)으로 제공합니다.

<br/>

---

## 02 · ONE PARAGRAPH

한국 금융감독원(**DART**) OpenAPI 기반 **약 80,000 개 법인 공시**를 대상으로,
`문서 수집 → OCR → 계층형 청킹 → 벡터 임베딩 → RAG 검색 → LLM 전략 분석 → 구조화 JSON 리포트 → PDF 생성` 까지
**end-to-end 단일 파이프라인**으로 처리하는 멀티모달 한국어 문서 지능 시스템입니다. **FastAPI + React 18 + ChromaDB + BGE-M3 + EXAONE 3.5 + Gemini 2.5 Pro/Flash** 기반. 5 개월, 1 인 풀스택 개발. 현재 Phase 4 운영.

<br/>

---

## 03 · THE SYSTEM — what's public

이 섹션에서 설명되는 것은 **구조와 선택**입니다. 구현 세부와 프롬프트는 다음 섹션에서 의도적으로 가려집니다.

### 03.1 · End-to-end pipeline

| Phase | 단계 | 핵심 기술 |
|:---:|---|---|
| **0** | 문서 수집 | DART OpenAPI · corpCode.xml 캐싱 · 로컬 업로드 |
| **1** | OCR + 정제 | PaddleOCR 3.4 · BOM/UTF-16 정규화 · 한글 복원 |
| **2** | 청킹 + 메타데이터 | 계층형 헤더 주입 · 문서 구조 추출 |
| **3** | 임베딩 → Chroma | A100 40GB · BGE-M3 · 10–15 m / 284K chunks |
| **4** | LLM 분석 + 리포트 | Insight Engine · Omega-Prime Supervisor · PDF 생성 |

### 03.2 · LLM routing — dual pathway

전체 시스템은 **두 개의 LLM 경로**로 분리되어 있습니다. 이 분리는 비용·프라이버시·환각 리스크의 세 축을 동시에 최적화하기 위한 의도된 설계입니다.

```
 ╭─────────────────────────────────────────────────────────────╮
 │                                                             │
 │   BASE PATHWAY       ·  OCR post-processing                 │
 │                      ·  RAG retrieval + chat                │
 │                      ·  General summarization               │
 │                      ·  Multi-agent orchestration           │
 │                      ─────────────────────────              │
 │                       → Ollama EXAONE 3.5  7.8B             │
 │                         (local GPU · private · free)        │
 │                                                             │
 ╰─────────────────────────────────────────────────────────────╯
                            │
                            │   only Insight Engine branches:
                            ▼
 ╭─────────────────────────────────────────────────────────────╮
 │                                                             │
 │   INSIGHT PATHWAY    ·  Financial strategic reasoning only  │
 │                                                             │
 │                      PRIMARY                                │
 │                       → Vertex AI  Gemini 2.5 Pro           │
 │                                                             │
 │                      SUPERVISOR  (independent audit)        │
 │                       → Vertex AI  Gemini 2.5 Flash         │
 │                         · 5-step reasoning protocol         │
 │                         · confidence calibration            │
 │                         · hidden-risk scan                  │
 │                         · counterfactual stress test        │
 │                                                             │
 ╰─────────────────────────────────────────────────────────────╯
```

Supervisor 레이어는 Insight 경로 **에만** 적용됩니다. OCR·RAG·일반 요약에는 관여하지 않습니다. 이유: 재무 의사결정 판단은 환각 리스크가 구조적으로 가장 높은 영역이기 때문입니다.

### 03.3 · Tech stack

```
backend     FastAPI 0.135  ·  SQLAlchemy 2.0  ·  Pydantic v2
            PostgreSQL 16 (psycopg 3)  ·  ChromaDB  ·  Redis
            PaddleOCR 3.4  ·  sentence-transformers  ·  BAAI bge-m3
            Ollama (EXAONE 3.5 7.8B)  ·  Vertex AI (Gemini 2.5)
            torch 2.x (CUDA 12.1)  ·  JWT + bcrypt

frontend    React 18  ·  Vite 6  ·  React Router 6
            Axios  ·  Lucide React  ·  JSZip

ml / gpu    BGE-M3 (1024-dim)  ·  Cross-encoder reranking
            A100 40GB · H100 (cloud rental)
            QLoRA fine-tuning (Qwen 2.5 7B target)
            vLLM serving  ·  bitsandbytes quantization

infra       uvicorn  ·  systemd  ·  Docker (dev)
            RunPod  ·  Lambda Labs  ·  Vast.ai
```

<br/>

---

## 04 · THE METHOD — what's not

아래 **5 개 요소는 이 저장소에 포함되지 않습니다.** 이들이 본 프로젝트의 지적 자산이기 때문입니다.

```
 ╔══════════════════════════════════════════════════════════════╗
 ║                                                              ║
 ║   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ║
 ║   ▓   01 · Omega-Prime Supervisor  system prompt    ▓       ║
 ║   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ║
 ║                                                              ║
 ║   Primary 추론 엔진 (Gemini 2.5 Pro) 의 출력을 독립 감독     ║
 ║   하는 2차 레이어. STEP 1-5 의 상위 구조는 공개되어 있으나  ║
 ║   각 STEP 내부의 판정 기준·거부 패턴·예시·rubric 은          ║
 ║   의도적으로 숨겨져 있습니다.                                 ║
 ║                                                              ║
 ║   why redacted — 환각 감독 로직은 단순 카피가 가능하며       ║
 ║   이 메커니즘이 본 시스템의 방어벽이기 때문입니다.            ║
 ║                                                              ║
 ╚══════════════════════════════════════════════════════════════╝

 ╔══════════════════════════════════════════════════════════════╗
 ║                                                              ║
 ║   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ║
 ║   ▓   02 · V-MASK Intelligence Manifold             ▓       ║
 ║   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ║
 ║                                                              ║
 ║   금융 공시의 전략적 곡률을 추정하는 3개 수학 신호 모듈:     ║
 ║                                                              ║
 ║     ·  Eigen-Sensor   (Polaris Vector)                       ║
 ║        고유값 분해 · 주권 전략 축 추출                       ║
 ║                                                              ║
 ║     ·  Laplace Shield                                        ║
 ║        전달 함수 기반 step response · 신호 순도 지표         ║
 ║                                                              ║
 ║     ·  Taylor Predictor                                      ║
 ║        2차 테일러 전개 · 미래 포지션 곡률                    ║
 ║                                                              ║
 ║   모듈 이름과 역할은 공개됩니다.                              ║
 ║   파라미터·정규화·weight schedule·rejection threshold는       ║
 ║   공개되지 않습니다.                                          ║
 ║                                                              ║
 ║   why redacted — 수학적 형식 자체가 IP 입니다.               ║
 ║                                                              ║
 ╚══════════════════════════════════════════════════════════════╝

 ╔══════════════════════════════════════════════════════════════╗
 ║                                                              ║
 ║   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ║
 ║   ▓   03 · Cross-encoder reranking recipe           ▓       ║
 ║   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ║
 ║                                                              ║
 ║   BGE-M3 1차 검색 이후의 리랭킹 체인.                        ║
 ║   모델 선택 · 캐싱 정책 · on/off 토글 조건 · score fusion    ║
 ║   공식은 비공개.                                              ║
 ║                                                              ║
 ╚══════════════════════════════════════════════════════════════╝

 ╔══════════════════════════════════════════════════════════════╗
 ║                                                              ║
 ║   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ║
 ║   ▓   04 · Multi-agent orchestration prompts       ▓       ║
 ║   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ║
 ║                                                              ║
 ║   `retrieval`  ·  `analysis`  ·  `validation`  ·            ║
 ║   `synthesis` — 4 개 에이전트의 이름과 역할은 공개,          ║
 ║   각각의 시스템 프롬프트와 상호 호출 규칙은 비공개.           ║
 ║                                                              ║
 ╚══════════════════════════════════════════════════════════════╝

 ╔══════════════════════════════════════════════════════════════╗
 ║                                                              ║
 ║   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ║
 ║   ▓   05 · Insight 5-axis schema refinement path   ▓       ║
 ║   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     ║
 ║                                                              ║
 ║   5축 (`insight_text`, `investment_thesis`, `market_        ║
 ║   context`, `risk_factors`, `strategic_action`) 의 존재는    ║
 ║   공개됩니다. 스키마를 반복적으로 강제·재시도·수정하는       ║
 ║   검증 루프는 비공개.                                         ║
 ║                                                              ║
 ╚══════════════════════════════════════════════════════════════╝
```

> 상기 5 개 항목은 채용·클라이언트 미팅에서 전체를 설명하고 실연합니다.
> 공개 저장소에는 기록되지 않습니다.

<br/>

---

## 05 · THE DECISION LOG

이 섹션은 전형적 README 에는 없습니다. 있을 이유가 없기 때문입니다.
전형적 README 의 독자는 "어떻게 설치하는가" 를 알고 싶어 합니다.
본 문서의 독자는 "**왜 이 사람은 이 선택을 했는가**" 를 알고 싶어 합니다.

각 결정에는 Omega-Prime 사고 프로토콜에 따라 **calibrated confidence tag** 가 부여됩니다. 모든 판단이 같은 확신도를 가지지는 않습니다.

### DECISION 01 · BGE-M3 over OpenAI text-embedding-3

```
  AXIOM     [99%]   본 코퍼스는 한국어 90%+ (DART 공시).
                    OpenAI text-embedding-3-large 는 한국어 검색에서
                    BGE-M3 대비 구조적 품질 열위 — 다국어 벤치마크
                    (MIRACL, MTEB-KO) 및 내부 측정 일관.

  CONSENSUS [92%]   BGE-M3 multi-vector + contextual header 조합이
                    긴 규제 공시 검색에서 mean-pooling fallback 보다
                    견고함.

  INFERENCE [78%]   Vector + BM25 + metadata filter 3-way hybrid 가
                    공시의 구조화된 표현(재무제표·주석)에 특히 효과적.

  TRADE-OFF         로컬 GPU 임베딩 필수 → A100 클라우드 파이프라인
                    설계로 상쇄 (10–15 m / 284K chunks, 단가 수 달러).
```

### DECISION 02 · EXAONE 3.5 (base) + Gemini 2.5 (insight-only) split

```
  AXIOM     [99%]   재무 전략 판단은 환각 리스크가 구조적으로 가장
                    높은 영역. 단일 모델은 자기 실수를 검출하지 못함.

  CONSENSUS [88%]   Gemini 2.5 Pro 는 한국어 금융 맥락에서 구조화 JSON
                    생성 품질 우위 (Pydantic schema compliance 기준).

  INFERENCE [72%]   OCR·챗봇·일반 요약은 환각 리스크가 낮고 privacy /
                    비용 / 지연시간이 중요 → 로컬 EXAONE 이 종합 우위.

  COUNTERFACTUAL    "모든 경로를 Gemini 로 통일하면 운영 단순성이
                    개선되지 않는가?"
                    → 월간 API 비용 추정치가 2 order-of-magnitude
                      증가. 개인정보 경로가 외부로 노출. 반증.
```

### DECISION 03 · Dual-engine supervision for insight path

```
  CONSENSUS [90%]   단일 LLM 은 자기 편향을 외부 레이어 없이 교정
                    하지 못함 — self-consistency 는 하한선.

  INFERENCE [80%]   Gemini 2.5 Flash 독립 인스턴스로 Pro 의 출력을
                    사후 감독 → calibrated confidence · hidden risk ·
                    counterfactual stress test 세 축에서 재검증.

  EXPLORATION [55%] Omega-Prime 5-step protocol 의 정량 효과는 아직
                    대규모 ablation study 미비. 현재까지는 qualitative
                    improvement + error taxonomy reduction 관측.
                    → [SPECULATION] 플래그 유지.
```

### DECISION 04 · ChromaDB over pgvector  (at this scale)

```
  CONSENSUS [85%]   284K 청크 규모는 pgvector 로도 처리 가능.

  INFERENCE [75%]   개발 속도 · persistent client 운영 편의 · 메타
                    데이터 필터 DSL 편리성에서 ChromaDB 가 1인 개발에
                    우위.

  REBUTTAL          "1M+ 청크 스케일에서는?" — 재평가 필요.
                    Phase 5 로드맵에 pgvector 마이그레이션 시나리오
                    포함 (트랜잭션·백업·스냅샷 통합 위해).
```

<br/>

---

## 06 · PROBLEMS SOLVED  (not the kind that fit on a resume)

이력서에 쓰지 못하는, 그러나 실제로 가장 많은 시간을 소모한 문제들입니다.
**진짜 엔지니어링 시간은 이런 곳에서 사라집니다.**

### 06.1 · BGE-M3 의 세 가지 silent failure

```
 ┌─────────────────────────────────┬────────────────────────────┐
 │   failure                       │   detection / fix           │
 ├─────────────────────────────────┼────────────────────────────┤
 │   HF 503 → mean-pooling         │   restart 후 검색 품질이   │
 │   fallback 발동                 │   점진적으로 하락.         │
 │                                 │   → startup pre-check 추가,│
 │                                 │     fallback 경로 제거.     │
 ├─────────────────────────────────┼────────────────────────────┤
 │   max_seq = 512 truncation      │   긴 공시의 꼬리 섹션이    │
 │                                 │   검색되지 않음.            │
 │                                 │   → contextual header 주입 │
 │                                 │     + 청킹 재설계.          │
 ├─────────────────────────────────┼────────────────────────────┤
 │   contextual header 누락        │   섹션 간 의미 경계 흐림.  │
 │                                 │   → 청킹 단계에서 상위     │
 │                                 │     헤더 prepend 강제.      │
 └─────────────────────────────────┴────────────────────────────┘
```

세 가지 모두 에러 로그를 남기지 않습니다. 정상 동작하는 것처럼 보입니다. 검색 품질의 통계적 저하만으로 감지됩니다. 이런 것이 silent failure 입니다.

### 06.2 · PyTorch sm_120 incompatibility  (RTX 5070)

```
  OBSERVATION   PyTorch 2.x stable 빌드가 RTX 5070 (sm_120) 미인식
  ASSUMPTION    "최신 하드웨어가 빠를 것이다"
  REFUTATION    로컬 GPU 임베딩 전면 불가
  PIVOT         A100 40GB 클라우드 파이프라인으로 전략 교체
                (RunPod / Lambda Labs / Vast.ai)
  LESSON        하드웨어 선정은 supported arch 체크가 선행
```

### 06.3 · Gemini key-pool rate limiting (Insight path only)

4 개 API 키 × 429 지수 백오프 × TPM 분배 (500K) × 자동 페일오버.
키 수 선택 근거, 백오프 계수, 페일오버 트리거는 **비공개 운영 파라미터**.

### 06.4 · 700 MB 단일 번들 OCR

PaddleOCR 직접 로드 시 메모리 터짐. 스트리밍 청킹 + BOM/UTF-16 정규화 + 한글 복원 파이프라인으로 해결.

### 06.5 · Thermal cap on local inference

로컬 CPU 온도가 장시간 배치에서 75 °C 를 초과하지 않도록 하드 캡 적용. 초과 시 throttle 또는 클라우드 오프로드 자동 전환. **하드웨어 생존 기간**이 개발자 시간만큼 비싼 자원이기 때문입니다.

<br/>

---

## 07 · WHAT IS NOT IN THIS REPOSITORY

이것이 이 저장소의 실제 상태입니다. 각 항목이 "존재하지 않는다" 가 아니라 "**공개되지 않는다**" 는 것에 주의해 주십시오.

```
  ✗   backend/  (27 services · 4 routers · 4 agents)
  ✗   frontend/ (React 18 SPA · 12 pages · chatbot UI)
  ✗   tools/    (A100/H100 cloud pipeline · QLoRA scripts)
  ✗   prompts/  (Omega-Prime Supervisor · base agents)
  ✗   datasets/ (284K chunks · 3,135 filings · QC reports)
  ✗   models/   (QLoRA adapters · vLLM serving configs)
  ✗   Phase4_Plan.pdf  (internal roadmap)
  ✗   Omega_CivicFlow_RAG_Architecture_Guide.pdf

  ✓   README.md  ← 당신이 읽고 있는 이 문서
  ✓   .gitignore
```

**이 저장소에는 단 2 개의 파일이 추적됩니다.** 나머지는 본인의 의도된 선택입니다. 카피 가능한 것과 카피 불가능한 것의 경계를 선명하게 유지하기 위해서입니다.

<br/>

---

## 08 · IF YOU WANT THIS — BUILT FOR YOU

본 프로젝트는 포트폴리오이자, 재사용 가능한 **블루프린트**입니다. 동일하거나 변형된 시스템의 구축을 고려하고 계시다면 아래 정보가 의사결정에 도움이 될 것입니다.

```
  scope         한국어 금융·공공·법무·의료 문서 지능
                RAG + LLM + 구조화 리포트 · end-to-end

  replication   3 – 5 engineer-months   (average-to-senior team)
  solo build    5 months · 1 engineer   (this repo's author)

  what scales   도메인 교체 (DART → 의료 차트 → 법무 서면)
                LLM 교체 (EXAONE → Qwen → Llama → Claude)
                벡터 백엔드 교체 (Chroma → pgvector → Qdrant)

  what doesn't  멀티 LLM 감독 프로토콜의 재학습 (도메인별 튜닝 필수)
                contextual chunking 의 하이퍼파라미터 (문서 유형별)

  deliverable   코드가 아니라 의사결정의 체계.
                위 DECISION LOG 와 동일한 수준의 calibrated reasoning
                을 프로젝트 전 기간에 걸쳐 제공합니다.
```

연락은 이력서에 기재된 채널로 받고 있습니다. 본 저장소는 signaling artifact 이며 feedback loop 가 아닙니다. 미팅에서는 상기 redacted 항목의 전체를 실연합니다.

<br/>

---

## 09 · A NOTE ON THE NAME

**Omega-Prime** 은 본 개발자가 운영하는 추론 프레임워크의 이름입니다. LLM 응답의 불확실성을 calibrated confidence 로 정량화하고, 환각을 외부 감독 레이어로 검출하고, 의사결정을 entropy 최소화 문제로 다루는 방법론입니다. 본 프로젝트는 그 프레임워크의 **실전 적용 사례**이며, 따라서 시스템 이름에 prefix 로 들어갑니다.

**CivicFlow** 는 본래 공공(Civic) 문서의 흐름(Flow)을 뜻합니다. Phase 0 에서는 실제로 민원·정책 문서를 다루었으며, Phase 2 이후 금융 공시로 도메인이 확장되었습니다. 이름은 유지되었습니다.

<br/>

---

## 10 · LICENSE

Proprietary. 본 저장소는 **이력서·포트폴리오 목적의 공개 지표**입니다.

- 본 문서의 텍스트·구조·프레이밍 재사용 금지
- 내부 시스템(코드·프롬프트·데이터셋·모델)은 비공개 자산
- 상업적 파생·재사용·재배포 금지
- 라이선싱·컨설팅·공동 개발은 개별 협의

<br/>

---

<div align="center">

```
 ─────────────────────────────────────────────────────────

       Ω    NODE OMEGA-PRIME
            UNIVERSAL STRATEGIC ARCHITECT

            Energy  (E)   ·   Entropy  (S)   ·   Efficiency  (η)

 ─────────────────────────────────────────────────────────
```

<sub>this page is the public index to a private system.</sub>
<sub>everything meaningful is behind a conversation, not a URL.</sub>

</div>
