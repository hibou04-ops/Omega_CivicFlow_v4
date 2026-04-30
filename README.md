# Omega CivicFlow v4 — DART 공시 OCR-RAG AI 분석 플랫폼

Omega CivicFlow v4는 금융감독원 DART 공시 문서를 OCR, 전처리, 벡터 인덱싱, RAG 검색, LLM 분석, PDF 보고서 생성까지 자동 처리하는 비공개 AI 문서 분석 플랫폼입니다.

공시 문서를 업로드하면 기업별 핵심 내용 요약, 전략 Insight, 리스크 분석, 근거 기반 질의응답, PDF 리포트 생성을 하나의 파이프라인으로 처리합니다.

> 핵심 분석 로직, 학습 데이터, 운영 코드는 지적재산 보호를 위해 비공개로 관리합니다.
> 이 README는 시스템 구조, 처리 흐름, 평가 방식, 비식별 예시만 문서화합니다.

---

## Problem

DART 공시 문서는 양이 많고, PDF 구조가 복잡하며, 기업별 비교와 핵심 리스크 추출에 시간이 많이 듭니다.

기존 방식의 문제는 다음과 같았습니다.

- 공시 PDF를 사람이 직접 열람해야 함
- OCR 노이즈와 표/문단 구조 때문에 검색 품질이 불안정함
- LLM 요약 결과가 근거 문서와 분리되면 신뢰하기 어려움
- 기업별 핵심 변화, 리스크, 전략적 의미를 반복적으로 분석하기 어려움

이 프로젝트는 공시 문서를 자동으로 처리하고, 검색 가능한 벡터 인덱스와 LLM 기반 분석 리포트를 생성하기 위해 만들었습니다.

---

## Pipeline

```text
DART PDF Upload
  → OCR
  → Text Cleaning / Preprocessing
  → Chunking
  → Embedding
  → ChromaDB Vector Index
  → RAG Retrieval
  → LLM Analysis
  → Insight Validation
  → PDF Report Generation
```

주요 처리 흐름:

1. DART 공시 PDF 업로드
2. OCR 및 텍스트 전처리
3. 문서 chunking 및 embedding
4. ChromaDB 기반 벡터 검색 인덱스 구축
5. RAG 검색으로 근거 문서 추출
6. EXAONE 3.5 / Gemini 2.5 모델을 역할별로 분리해 요약·분석·검증 수행
7. PDF 리포트 생성

---

## Architecture

```text
Frontend
  - React 18

Backend
  - FastAPI
  - SQLAlchemy 2.0
  - SQLite

Document Pipeline
  - PaddleOCR
  - Hierarchical chunking
  - BGE-M3 embedding (1024-dim)

Vector Store
  - ChromaDB

LLM Layer
  - EXAONE 3.5 (Ollama, local)         — OCR post-processing, RAG chat, summarization
  - Gemini 2.5 Pro (Vertex AI)          — Insight engine (financial reasoning only)
  - Gemini 2.5 Flash (Vertex AI)        — Independent supervisor / audit layer

Evaluation
  - RAGAS (retrieval / generation quality)
  - Internal QC gating
```

LLM은 단일 모델에 모든 역할을 맡기지 않고, **요약·검색·전략 Insight·검증**의 역할을 분리해 사용했습니다. 환각 리스크가 가장 큰 재무 추론 경로에는 별도 supervisor 레이어를 두어 1차 출력을 독립 감독합니다.

---

## Scale

- **3,135** DART disclosure documents processed
- **1,106** unique companies indexed
- **612,880** vector entries generated
- **RAGAS-based internal evaluation: 83.52%**

> RAGAS 점수는 내부 평가셋(v9 baseline) 기준입니다.
> 실제 운영 품질은 OCR 품질, 문서 구조, 검색 query, chunking 전략에 따라 달라질 수 있습니다.

---

## LoRA / QLoRA Experiments

공시 문서 도메인에 맞춘 응답 품질을 실험하기 위해 **QLoRA 기반 LLM 도메인 적응 실험**을 수행했습니다 (target: `Qwen/Qwen2.5-7B-Instruct`, A100 80GB, bitsandbytes 4-bit + PEFT).

실험 목적:

- OCR 이후 추출된 공시 텍스트의 요약 품질 개선
- 공시 문체와 도메인 용어에 대한 모델 적응
- RAG 검색 결과 기반 답변 형식 안정화
- 일반 요약 vs. 공시 분석형 응답의 차이 비교

실험 결과:

- RAG는 **근거 검색**을 담당하는 것이 적합함
- Fine-tuning은 **문체·태스크 적응**에서 더 큰 효과를 가짐
- 두 경로는 대체재가 아니라 **상호 보완적**

> 운영 환경의 EXAONE 3.5는 LG의 베이스 모델을 그대로 사용합니다.
> QLoRA 실험은 Qwen 2.5 7B를 타겟으로 한 별도 연구 트랙입니다.

---

## Private Components

이 프로젝트는 실제 운영 목적과 지적재산 보호를 위해 전체 코드를 공개하지 않습니다.

비공개 항목:

- 핵심 Insight 생성 로직 및 5축 스키마 검증 루프
- Omega-Prime Supervisor 시스템 프롬프트
- 운영 백엔드 / 프런트엔드 / 에이전트 코드
- 학습 및 평가 데이터셋 (3,135 filings · 612,880 vectors)
- 프롬프트 템플릿 및 멀티에이전트 오케스트레이션 규칙
- Cross-encoder reranking recipe / score fusion
- 자동화 스케줄러 및 운영 설정

공개 저장소에서는 시스템 구조, 처리 흐름, 평가 방식, 비식별 예시만 제공합니다.

```text
✗  backend/   (FastAPI services, agents, routers)
✗  frontend/  (React 18 SPA, chatbot UI)
✗  tools/     (cloud embedding pipeline, QLoRA scripts)
✗  prompts/   (Omega-Prime Supervisor, agent prompts)
✗  datasets/  (filings, chunks, QC reports)
✗  models/    (LoRA adapters, reranker configs)

✓  README.md   ← 이 문서
✓  .gitignore
```

---

## Relationship to Prompt CI / Audit Stack

CivicFlow를 개발하면서 **LLM 분석 결과를 그대로 신뢰하기 어렵다**는 문제를 반복적으로 경험했습니다.

특히 다음 문제가 자주 발생했습니다.

- RAG 검색 결과가 항상 충분하지 않음
- LLM 요약이 근거 문서와 어긋나는 경우 발생
- 모델별 응답 품질 차이가 큼
- 평가 셋 없이 프롬프트를 수정하면 개선 여부를 판단하기 어려움

이 문제를 일반화해 도구화한 것이 **omegaprompt · omega-lock · antemortem-cli** 기반의 Prompt CI & Agent Validation Stack입니다.

CivicFlow는 실전 AI 시스템 구현 사례, omegaprompt 계열은 그 검증 문제를 일반화한 도구 트랙입니다.

---

## License

Proprietary. 본 저장소는 **이력서·포트폴리오 목적의 공개 지표**입니다.

- 본 문서의 텍스트·구조·프레이밍 재사용 금지
- 내부 시스템(코드·프롬프트·데이터셋·모델)은 비공개 자산
- 상업적 파생·재사용·재배포 금지
- 라이선싱·컨설팅·공동 개발은 개별 협의
