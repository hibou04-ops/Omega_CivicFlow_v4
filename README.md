# Omega CivicFlow v4 — DART 공시 OCR-RAG 분석 플랫폼

금융감독원 DART 공시 문서를 **OCR → 전처리 → 벡터 인덱싱 → RAG 검색 → LLM 분석 → PDF 보고서 생성**까지 자동 처리하는 풀스택 AI 문서 분석 플랫폼입니다.

> 본 저장소는 이력서·포트폴리오용 공개 README입니다.
> OCR-RAG 코어 모듈은 **단계적 공개 진행 중**이며, **핵심 Insight 생성 로직만** 지적재산 보호를 위해 비공개로 유지합니다.

---

## Why this matters

이 프로젝트의 차별점은 "RAG 파이프라인을 만들었다"가 아니라 **운영 품질을 좌우하는 의사결정을 어떻게 검증했는가**입니다.

- **모델 선택 의사결정** — Qwen 2.5 7B + QLoRA 1차 시도 → evidence field 중국어 오염 진단 → EXAONE 3.5 7.8B + LoRA로 교체. 모델 선택이 운영 품질을 좌우한다는 실무 학습.
- **LLM 역할 분리** — 단일 모델에 모든 역할을 맡기지 않고, OCR 후처리·요약·재무 추론·독립 검증을 각각 다른 모델 경로에 배치.
- **RAG vs Fine-tuning 검증** — 두 경로는 대체재가 아닌 상호 보완재. RAG는 근거 검색, Fine-tuning은 문체·태스크 적응 담당으로 역할 분리 확인.

---

## Problem

DART 공시 문서는 양이 많고, PDF 구조가 복잡하며, 기업별 비교와 핵심 리스크 추출에 시간이 많이 듭니다.

- 공시 PDF를 사람이 직접 열람해야 함
- OCR 노이즈와 표/문단 구조 때문에 검색 품질이 불안정함
- LLM 요약 결과가 근거 문서와 분리되면 신뢰하기 어려움
- 기업별 핵심 변화·리스크·전략적 의미를 반복적으로 분석하기 어려움

이 프로젝트는 공시 문서를 자동으로 처리하고, 검색 가능한 벡터 인덱스와 LLM 기반 분석 리포트를 생성하기 위해 만들었습니다.

---

## Pipeline

```text
DART PDF Upload
  → OCR (EasyOCR)
  → Text Cleaning / Preprocessing
  → Hierarchical Chunking
  → Embedding (BGE-M3, 1024-dim)
  → ChromaDB Vector Index
  → RAG Retrieval (+ Korean reranker)
  → LLM Analysis (role-separated)
  → Insight Validation (independent supervisor)
  → PDF Report Generation
```

---

## Architecture

```text
Frontend
  - React + Vite

Backend
  - FastAPI
  - SQLAlchemy 2.0
  - PostgreSQL

Document Pipeline
  - EasyOCR
  - Hierarchical chunking (header injection)
  - BGE-M3 embedding (1024-dim)
  - dragonkue/bge-reranker-v2-m3-ko (Korean reranker)

Vector Store
  - ChromaDB

LLM Layer
  - Ollama  · EXAONE 3.5 7.8B          — OCR 후처리 / 요약 / RAG 챗
  - vLLM    · EXAONE 3.5 + LoRA        — 도메인 적응 서빙 경로
  - Vertex AI · Gemini 2.5 Pro          — 재무 추론 (Insight engine)
  - Vertex AI · Gemini 2.5 Flash        — 독립 supervisor / 검증 레이어

Infra
  - Google Cloud (Vertex AI, GCE L4)
  - RunPod / Colab A100 (embedding pipeline)

Evaluation
  - RAGAS (retrieval / generation quality)
  - 내부 QC gating
```

---

## Scale & Evaluation

- **3,135** DART 공시 문서 처리
- **1,106** 고유 기업 인덱싱
- **612,880** 벡터 인덱스 생성
- **RAGAS 기반 내부 평가 — 83.52%** (v9 baseline)

> RAGAS 점수는 내부 평가셋 기준입니다.
> 실제 운영 품질은 OCR 품질, 문서 구조, 검색 query, chunking 전략에 따라 달라질 수 있습니다.

---

## Fine-tuning — Model swap decision

도메인 적응 실험을 단순 "QLoRA 돌려봤습니다"로 끝내지 않고, **모델 교체 의사결정**으로 마무리한 트랙입니다.

| 단계 | 시도 | 결과 |
|---|---|---|
| 1차 | `Qwen/Qwen2.5-7B-Instruct` + QLoRA (RunPod A100) | 학습은 성공, 그러나 **evidence field에서 중국어 토큰 오염** 진단 |
| 2차 | `EXAONE 3.5 7.8B` + LoRA (GCE L4) | 한국어 우세도 확보, 운영 vLLM 경로에 통합 |

핵심 학습:

- **모델 선택이 운영 품질을 좌우한다** — 한국어 공시 도메인에서는 베이스 모델의 언어 우세도가 LoRA 학습량보다 더 결정적이었음
- **RAG는 근거 검색** 담당, **Fine-tuning은 문체·태스크 적응** 담당 — 두 경로를 별도 평가축으로 분리해 검증
- 운영 EXAONE 채택 후 evidence field 언어 일관성 회복 확인

---

## LLM Routing — Role separation

```text
┌─────────────────────────────────────────────────────────┐
│ BASE PATHWAY  ·  EXAONE 3.5 7.8B (Ollama / vLLM+LoRA)   │
│   - OCR post-processing                                 │
│   - RAG retrieval + chat                                │
│   - General summarization                               │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼  Insight 경로만 분기
┌─────────────────────────────────────────────────────────┐
│ INSIGHT PATHWAY  ·  Vertex AI                           │
│   PRIMARY    → Gemini 2.5 Pro    (재무 전략 추론)       │
│   SUPERVISOR → Gemini 2.5 Flash  (독립 사후 감독)       │
│                · calibrated confidence                  │
│                · hidden-risk scan                       │
│                · counterfactual stress test             │
└─────────────────────────────────────────────────────────┘
```

Supervisor 레이어는 Insight 경로에만 적용됩니다. 재무 의사결정 판단은 환각 리스크가 구조적으로 가장 높은 영역이라 별도 감독이 필요하다고 판단했습니다.

---

## Code disclosure policy

이 저장소는 단계적으로 공개를 진행하고 있습니다. **핵심 Insight 생성 로직 한 가지만 비공개로 유지**하며, 그 외 OCR-RAG 코어 모듈은 정리되는 대로 순차적으로 공개될 예정입니다.

| 영역 | 상태 |
|---|---|
| OCR · 전처리 · 청킹 | 단계적 공개 예정 |
| 임베딩 · 벡터 인덱싱 | 단계적 공개 예정 |
| RAG 검색 · reranker | 단계적 공개 예정 |
| Fine-tuning 스크립트 (Qwen / EXAONE) | 단계적 공개 예정 |
| 평가 파이프라인 (RAGAS) | 단계적 공개 예정 |
| **핵심 Insight 생성 로직 + Omega-Prime Supervisor 시스템 프롬프트** | **비공개 유지** |

비공개 사유: 환각 감독·5축 스키마 검증·Counterfactual stress test 메커니즘은 단순 카피가 가능하며 본 시스템의 방어벽이기 때문입니다. 채용·미팅 자리에서는 전체를 실연합니다.

---

## Related — Prompt CI / Agent Validation Stack

CivicFlow를 개발하면서 **LLM 분석 결과를 그대로 신뢰하기 어렵다**는 문제를 반복적으로 경험했습니다.

- RAG 검색 결과가 항상 충분하지 않음
- LLM 요약이 근거 문서와 어긋나는 경우 발생
- 모델별 응답 품질 차이가 큼
- 평가셋 없이 프롬프트를 수정하면 개선 여부를 판단할 수 없음

이 문제를 일반화해 도구화한 것이 **PyPI 5종**으로 배포한 Prompt CI & Agent Validation Stack입니다.

- `omegaprompt` · `omega-lock` · `antemortem-cli` · `mini-omega-lock` · `mini-antemortem-cli`
- 누적 8,799 다운로드 / real-user 2,645 (mirror·CI bot 분리 측정, 2026-04 기준)
- 4 MCP 서버 / 18 agent-callable tools / 461 테스트 케이스
- 방법론: train/test split · pre-declared gate · holdout 검증 · append-only audit artifact

CivicFlow는 실전 AI 시스템 구현 사례, omegaprompt 계열은 그 검증 문제를 일반화한 도구 트랙입니다.

---

## Author

곽경훈 — AI Engineer · LLM Validation & RAG Systems
- GitHub: [github.com/hibou04-ops](https://github.com/hibou04-ops)
- Email: hibouaile04@gmail.com

---

## License

Proprietary — 본 저장소는 이력서·포트폴리오 목적의 공개 지표입니다.

- 본 문서의 텍스트·구조·프레이밍 재사용 금지
- 비공개로 유지되는 Insight 로직·프롬프트·데이터셋·모델은 비공개 자산
- 상업적 파생·재사용·재배포 금지
- 라이선싱·컨설팅·공동 개발은 개별 협의
