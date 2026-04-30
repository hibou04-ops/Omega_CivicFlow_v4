# HuggingFace 데이터셋 검색 매뉴얼

> 작성일: 2026-04-17
> 목적: 한국어 금융/법률 도메인 파인튜닝 데이터셋 탐색 가이드
> 대상자: 파인튜닝 데이터셋을 찾아야 하는 엔지니어 (본인)

---

## 1. HuggingFace Hub 생태계 개요

HuggingFace Hub에는 3가지 주요 리소스가 있습니다:

| 리소스 | URL 경로 | 용도 |
|--------|---------|------|
| **Models** | `huggingface.co/models` | 사전학습된 모델 (EXAONE, Gemma 4, BGE-M3) |
| **Datasets** | `huggingface.co/datasets` | 학습/평가 데이터셋 (지금 우리가 찾는 것) |
| **Spaces** | `huggingface.co/spaces` | 데모 앱 (참고용) |

**핵심 원칙:** 좋은 데이터셋은 보통 좋은 모델 저자의 계정에서 나옵니다. 예: BCCard가 금융 모델을 올렸다면, 그들의 데이터셋도 볼 만한 가치가 있습니다.

---

## 2. 검색 방법 — 3가지 경로

### 경로 A: 웹 UI 검색 (빠른 탐색)

```
https://huggingface.co/datasets?search=<키워드>
```

**좋은 검색 쿼리 패턴:**
- 도메인 + 언어: `korean finance`, `korean legal`, `korean financial QA`
- 데이터 형식 + 언어: `korean instruction`, `korean reasoning`
- 구체적 태스크: `QA dataset korean`, `RAG korean finance`
- 업로더 기반: `BCCard`, `beomi`, `42dot`, `lemon-mint`

**UI 필터 활용:**
- `Task Categories`: question-answering, text-generation
- `Languages`: Korean (ko)
- `Size`: 1K-10K (당신 용도에 맞는 크기)
- `License`: Apache 2.0, MIT, CC BY 4.0 (상업 이용 가능)

### 경로 B: HuggingFace CLI

```bash
# 설치 (한번만)
pip install huggingface_hub datasets

# 로그인 (모델/데이터 다운로드 시 필요)
huggingface-cli login

# 데이터셋 검색
huggingface-cli search datasets --query "korean finance"

# 특정 데이터셋 정보 확인
huggingface-cli inspect datasets BCCard/BCCard-Finance-Kor-QnA
```

### 경로 C: Python datasets 라이브러리 (실전 검증)

가장 강력한 방법. 다운로드 없이 메타데이터만 확인 가능.

```python
from datasets import load_dataset, get_dataset_config_names, get_dataset_infos

# 1. 어떤 sub-config이 있는지 확인
configs = get_dataset_config_names("BCCard/BCCard-Finance-Kor-QnA")
print(configs)

# 2. 전체 구조 확인 (다운로드 없이)
infos = get_dataset_infos("BCCard/BCCard-Finance-Kor-QnA")
print(infos)  # features, splits, size 모두 보임

# 3. 한 샘플만 스트리밍 (전체 다운로드 없이)
ds = load_dataset("BCCard/BCCard-Finance-Kor-QnA", streaming=True, split="train")
sample = next(iter(ds))
print(sample)

# 4. 문제 없으면 실제 다운로드
ds = load_dataset("BCCard/BCCard-Finance-Kor-QnA")
```

---

## 3. 데이터셋 평가 체크리스트

데이터셋을 발견했을 때 **다운로드 전** 확인할 것:

### 3.1 구조적 확인 (Dataset Card 페이지)
- [ ] **Task**: 당신이 하려는 것과 일치하는가? (QA? instruction-tuning?)
- [ ] **Size**: 학습에 적합한가? (QLoRA 300개, full FT는 10K+)
- [ ] **Format**: 스키마가 명확한가? (`user_input`, `reference`, `contexts` 같은 필드)
- [ ] **Language**: 100% 한국어인가? 혼재되었는가?
- [ ] **License**: 상업 이용 가능한가? 상업 제한이면 이력서용만

### 3.2 품질 신호
- [ ] **Downloads**: 월 100+ 다운로드면 커뮤니티 검증됨
- [ ] **Likes**: 10+ likes면 좋은 평가
- [ ] **Last Updated**: 6개월 내 업데이트가 최신성 좋음
- [ ] **README 품질**: 상세하면 작성자가 진지함
- [ ] **Citation**: 논문 citation 있으면 학계 검증됨

### 3.3 Red Flags ⚠️
- "Last updated 2년 전" + "Downloads 5" → 유령 데이터셋
- README 없음 → 내부용/미완성
- License가 `cc-by-nc-nd-4.0` → 상업 불가, 수정 불가
- Features가 `unknown` 또는 명시 안 됨 → 구조 불명
- Test/Train 분리 없음 → 평가 어려움

### 3.4 실제 샘플 확인 (필수)
데이터셋 카드 페이지의 **"Dataset Viewer"** 탭을 클릭하면 브라우저에서 직접 샘플을 볼 수 있습니다. 최소 10개는 보고 품질 판단하세요:
- 질문이 실제 사람이 물을 법한 것인가?
- 답변이 정확하고 완성된 문장인가?
- 컨텍스트가 답변을 뒷받침하는가?
- 인코딩 깨짐 없는가?

---

## 4. 당신 프로젝트를 위한 검색 전략

### 4.1 핵심 검색 쿼리 (순서대로 시도)

```
우선순위 1 (직접 fit):
- "korean finance QA"
- "korean financial instruction"
- "한국어 금융"
- "DART disclosure"
- "감사보고서" / "사업보고서"

우선순위 2 (유사 도메인):
- "korean legal QA"
- "KorQuAD"
- "korean reading comprehension"
- "korean reasoning"

우선순위 3 (증강용):
- "korean instruction tuning"
- "korean RAG"
- "korean alpaca"
```

### 4.2 주목할 만한 계정 (Korean 전문)

- **BCCard**: BC카드, 한국 금융 특화 ⭐
- **beomi**: Korean LLM 커뮤니티 허브, 여러 Korean 모델/데이터
- **LG AI Research** / **LGAI-EXAONE**: EXAONE 공식
- **Upstage**: Solar 계열, Korean 특화
- **42dot**: 42dot LLM Korean
- **lemon-mint**: Korean reasoning 컬렉션
- **HeegyuKim**: open-korean-instructions
- **KorQuAD**: Korean SQuAD

### 4.3 이미 발견한 후보 (2026-04-17 검색 결과)

#### 최우선 확인 ⭐⭐⭐
1. **BCCard/BCCard-Finance-Kor-QnA**
   - URL: https://huggingface.co/datasets/BCCard/BCCard-Finance-Kor-QnA
   - 가능성: 한국어 금융 QA, BC카드 공식
   - 확인 필요: 크기, 라이선스, 실제 샘플 품질

2. **BCCard/BCAI-Finance-Kor**
   - URL: https://huggingface.co/datasets/BCCard/BCAI-Finance-Kor
   - 가능성: 일반 한국 금융 텍스트
   - 확인 필요: QA 포맷인지 일반 텍스트인지

#### 보조 후보 ⭐⭐
3. **KorQuAD/squad_kor_v1, v2**
   - URL: https://huggingface.co/datasets/KorQuAD/squad_kor_v1
   - 한국어 QA의 표준, 60K+ 샘플
   - 금융 도메인은 아니지만 **질문/답변 스타일 레퍼런스**로 유용

4. **lawcompany/KLAID**
   - 한국 법률 AI 데이터셋
   - 금융과 법률은 어휘/문체가 겹침

5. **lemon-mint/korean-reasoning-datasets**
   - URL: https://huggingface.co/collections/lemon-mint/korean-reasoning-datasets
   - Korean 추론 데이터 모음, augmentation 용도

#### 영어 레퍼런스 (구조만 참고)
6. **sujet-ai/Sujet-Finance-Instruct-177k**
   - 영어 금융 instruction tuning 177K
   - 구조/프롬프트 디자인 참고용

### 4.4 검색 워크플로 (실전 예시)

```python
# Step 1: 빠른 메타데이터 확인
from datasets import get_dataset_infos

candidates = [
    "BCCard/BCCard-Finance-Kor-QnA",
    "BCCard/BCAI-Finance-Kor",
    "KorQuAD/squad_kor_v1",
    "lawcompany/KLAID",
]

for name in candidates:
    try:
        info = get_dataset_infos(name)
        for cfg, meta in info.items():
            print(f"=== {name} / {cfg} ===")
            print(f"  Size: {meta.dataset_size}")
            print(f"  Splits: {list(meta.splits.keys())}")
            print(f"  Features: {list(meta.features.keys())}")
            print(f"  Download: {meta.download_size}")
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
```

```python
# Step 2: 샘플 스트리밍 (상위 5개만)
from datasets import load_dataset

for name in candidates:
    print(f"\n=== {name} ===")
    try:
        ds = load_dataset(name, streaming=True, split="train")
        for i, sample in enumerate(ds):
            if i >= 5:
                break
            print(sample)
    except Exception as e:
        print(f"[FAIL]: {e}")
```

```python
# Step 3: 최종 후보만 전체 다운로드
from datasets import load_dataset
ds = load_dataset("BCCard/BCCard-Finance-Kor-QnA")
print(ds)
print(f"Train: {len(ds['train'])}")
```

---

## 5. 데이터셋 재사용 vs 직접 구축 결정 트리

```
HuggingFace에서 찾았나?
│
├─ Yes → 품질 체크리스트 통과?
│        │
│        ├─ Yes → 크기 충분? (300+)
│        │        │
│        │        ├─ Yes → 바로 사용 ✅
│        │        └─ No → 다른 데이터셋과 merge → 사용
│        │
│        └─ No → 후보 탈락, 다음 후보로
│
└─ No → 직접 구축 (DART 원본 → QA 생성)
```

---

## 6. 라이선스 빠른 가이드

| 라이선스 | 상업 이용 | 수정 가능 | 파생물 공개 의무 | 취업 포트폴리오 OK? |
|---------|---------|---------|-----------------|-------------------|
| Apache 2.0 | ✅ | ✅ | ❌ | ✅ |
| MIT | ✅ | ✅ | ❌ | ✅ |
| CC BY 4.0 | ✅ | ✅ | ❌ (저자표시만) | ✅ |
| CC BY-SA 4.0 | ✅ | ✅ | ✅ (same license) | ⚠️ |
| CC BY-NC | ❌ (비상업만) | ✅ | ❌ | ⚠️ (이력서만, 배포 X) |
| CC BY-NC-ND | ❌ | ❌ | ❌ | ❌ |
| 독자 라이선스 (LG 등) | 케바케 | 케바케 | 케바케 | 확인 필요 |

**이력서/포트폴리오 관점 팁:** Apache 2.0 or MIT 데이터로 파인튜닝한 모델은 GitHub에 공개하고 이력서에 쓸 수 있습니다. NC 라이선스는 "개인 학습용으로 사용"이라고 명시해야 합니다.

---

## 7. 면접 관점에서의 검색 스토리

"데이터셋을 어떻게 찾았나요?"라는 면접 질문에 답할 때:

**Bad answer:** "HuggingFace에서 검색했어요."

**Good answer:** "먼저 HuggingFace Hub에서 한국어 금융 도메인 QA 데이터셋을 검색했습니다. BCCard 같은 한국 금융 기업의 공식 계정을 우선 확인했고, KorQuAD 같은 범용 한국어 QA 데이터셋도 augmentation 후보로 검토했습니다. 각 후보는 라이선스(상업 이용 가능 여부), 크기, 샘플 품질(실제 10개 이상 열어보고 판단), 도메인 적합성 4가지 기준으로 평가했고, 기존 데이터셋이 요구사항을 충족하지 않을 때만 DART 원문에서 직접 QA를 생성하는 경로로 갔습니다."

이게 **"조사 후 판단 가능한 엔지니어"**의 signal입니다.

---

## 8. 지금 당장 할 수 있는 검증 커맨드

이 매뉴얼을 읽고 바로 실행할 수 있는 순서:

```bash
# 1. 환경 준비 (한번만)
pip install huggingface_hub datasets

# 2. 로그인 (필수는 아니지만 권장)
huggingface-cli login

# 3. 파이썬 실행하여 후보 3개 스캔
python -c "
from datasets import get_dataset_infos
for name in ['BCCard/BCCard-Finance-Kor-QnA', 'KorQuAD/squad_kor_v1', 'lawcompany/KLAID']:
    try:
        info = get_dataset_infos(name)
        for cfg, meta in info.items():
            print(f'{name}/{cfg}: splits={list(meta.splits.keys())}, size={meta.dataset_size}')
    except Exception as e:
        print(f'{name}: FAIL - {e}')
"
```

출력에서 가장 유망한 후보를 확인한 다음, 다음 단계로 샘플링/실제 다운로드를 진행합니다.

---

## 9. 추가 학습 자료

- **HuggingFace Datasets 공식 문서**: https://huggingface.co/docs/datasets
- **AwesomeKorean_Data** (songys): https://github.com/songys/AwesomeKorean_Data
- **open-korean-instructions** (HeegyuKim): https://github.com/HeegyuKim/open-korean-instructions

---

## 10. 체크포인트 — 이 매뉴얼을 마스터하면

- [ ] HuggingFace에서 키워드로 데이터셋을 30초 내 발견할 수 있다
- [ ] Dataset card만 보고 5분 내 품질/적합성 판단할 수 있다
- [ ] `load_dataset(streaming=True)`로 다운로드 없이 구조 확인할 수 있다
- [ ] 라이선스를 읽고 상업/포트폴리오 사용 가능 여부 즉답할 수 있다
- [ ] 기존 데이터셋 재사용 vs 직접 구축 결정을 체계적으로 내릴 수 있다

이 5가지가 체크되면 면접에서 "데이터셋 선정 역량"을 보여줄 수 있습니다.
