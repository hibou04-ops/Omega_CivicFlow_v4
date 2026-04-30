# HuggingFace 데이터셋 다운로드 실전 가이드

> 작성일: 2026-04-17
> 환경: Windows 11, Python 3.11, Omega CivicFlow v4 프로젝트
> 목적: HuggingFace 데이터셋을 로컬로 받는 실전 명령어

---

## 0. 준비 — 패키지 설치 (최초 1회)

```bash
# Git Bash 또는 cmd에서
pip install huggingface_hub datasets
```

또는 가상환경 사용 시:
```bash
cd C:/Users/hibou/Omega_CivicFlow_v4
backend/venv/Scripts/activate
pip install huggingface_hub datasets
```

**설치 확인:**
```bash
python -c "import datasets; print(datasets.__version__)"
python -c "from huggingface_hub import HfApi; print('OK')"
```

---

## 1. 로그인 — Gated Dataset용 (필요 시)

일부 데이터셋은 라이선스 동의가 필요합니다 (EXAONE, Llama 등도 해당).

**토큰 발급:**
1. https://huggingface.co 회원가입
2. https://huggingface.co/settings/tokens 에서 `Read` 권한 토큰 생성
3. 토큰 복사

**CLI 로그인:**
```bash
huggingface-cli login
# 프롬프트에 토큰 붙여넣기
```

**로그인 확인:**
```bash
huggingface-cli whoami
```

토큰은 `~/.cache/huggingface/token`에 저장됩니다. 다음부턴 자동.

---

## 2. 다운로드 방법 4가지

### 방법 A: `datasets.load_dataset()` — 가장 일반적

Python에서 직접 로드. 자동으로 캐시 폴더(`~/.cache/huggingface/datasets/`)에 저장.

```python
from datasets import load_dataset

# 전체 다운로드 + 로드
ds = load_dataset("BCCard/BCCard-Finance-Kor-QnA")

# 스플릿별 접근
print(ds)  # DatasetDict({train: ..., test: ...})
print(ds["train"][0])  # 첫 번째 샘플
print(len(ds["train"]))  # 행 수
```

**캐시 위치 (Windows):**
```
C:\Users\hibou\.cache\huggingface\datasets\
```

**특정 config만 다운로드:**
```python
ds = load_dataset("BCCard/BCAI-Finance-Kor", "config_name")
```

### 방법 B: 스트리밍 — 다운로드 없이 확인

디스크에 저장하지 않고 네트워크로 스트리밍. **탐색 단계에 적합.**

```python
from datasets import load_dataset

ds = load_dataset("BCCard/BCCard-Finance-Kor-QnA", streaming=True, split="train")

# 처음 5개만 보기
for i, sample in enumerate(ds):
    if i >= 5:
        break
    print(sample)
```

장점: 용량 큰 데이터도 몇 초 내 구조 확인 가능.
단점: 반복 접근 시마다 네트워크 요청.

### 방법 C: `snapshot_download()` — 원시 파일 그대로

JSONL, CSV, Parquet 등 원본 파일을 그대로 다운받고 싶을 때.

```python
from huggingface_hub import snapshot_download

path = snapshot_download(
    repo_id="BCCard/BCCard-Finance-Kor-QnA",
    repo_type="dataset",
    local_dir="C:/Users/hibou/Omega_CivicFlow_v4/data/bccard",
)
print(f"Downloaded to: {path}")
```

**주요 파라미터:**
- `repo_type="dataset"` (vs `"model"`)
- `local_dir` 지정 시 해당 경로에 저장, 미지정 시 캐시로
- `allow_patterns=["*.jsonl"]` 로 특정 파일만 받기
- `ignore_patterns=["*.parquet"]` 로 특정 파일 제외

### 방법 D: `hf_hub_download()` — 단일 파일만

특정 파일 하나만 받을 때.

```python
from huggingface_hub import hf_hub_download

file_path = hf_hub_download(
    repo_id="BCCard/BCCard-Finance-Kor-QnA",
    filename="bccard-finance-qna.jsonl",
    repo_type="dataset",
    local_dir="C:/Users/hibou/Downloads",
)
```

**언제 쓰나:** 데이터셋 페이지에서 파일 구조를 보고 필요한 하나만 받을 때.

---

## 3. CLI만으로 다운로드

Python 안 쓰고 터미널에서 바로:

```bash
# 전체 저장소 받기
huggingface-cli download BCCard/BCCard-Finance-Kor-QnA \
    --repo-type dataset \
    --local-dir C:/Users/hibou/Omega_CivicFlow_v4/data/bccard

# 특정 파일만
huggingface-cli download BCCard/BCCard-Finance-Kor-QnA \
    bccard-finance-qna.jsonl \
    --repo-type dataset \
    --local-dir C:/Users/hibou/Downloads
```

---

## 4. 웹 UI로 다운로드 (GUI 선호 시)

1. HuggingFace 데이터셋 페이지 방문: `https://huggingface.co/datasets/<user>/<dataset>`
2. **Files and versions** 탭 클릭
3. 원하는 파일 우측 **다운로드 아이콘**(↓) 클릭
4. 브라우저 다운로드 폴더에 저장

당신이 방금 받은 `c:/Users/hibou/Downloads/bccard-finance-qna.jsonl`이 이 방법의 결과입니다.

---

## 5. 받은 파일 활용 패턴

### JSONL 파일 읽기
```python
import json

records = []
with open("C:/Users/hibou/Downloads/bccard-finance-qna.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        records.append(json.loads(line))

print(f"Total: {len(records)}")
print(records[0])
```

### datasets 라이브러리로 불러오기 (권장)
```python
from datasets import load_dataset

ds = load_dataset(
    "json",
    data_files="C:/Users/hibou/Downloads/bccard-finance-qna.jsonl",
    split="train"
)
print(ds)
print(ds[0])
```

이렇게 하면 HuggingFace 표준 포맷으로 통합됨. 나중에 파인튜닝 스크립트에 그대로 넣을 수 있음.

### Parquet 파일 읽기
```python
import pyarrow.parquet as pq

table = pq.read_table("train.parquet")
df = table.to_pandas()
print(df.head())
```

---

## 6. 오프라인 / 회사망 환경 트릭

### 환경변수로 캐시 위치 변경
```bash
# Windows
set HF_HOME=D:/hf_cache
set HF_DATASETS_CACHE=D:/hf_cache/datasets

# 또는 .env 파일
HF_HOME=D:/hf_cache
```

### 기존 캐시 확인
```bash
huggingface-cli scan-cache
```
출력 예:
```
REPO ID                             REPO TYPE SIZE ON DISK
BCCard/BCCard-Finance-Kor-QnA      dataset   17.1M
```

### 오프라인 모드
```bash
set TRANSFORMERS_OFFLINE=1
set HF_DATASETS_OFFLINE=1
```
캐시된 데이터만 사용. 네트워크 못 타는 환경용.

---

## 7. 실전 워크플로 — 우리 프로젝트에 적용

### 시나리오 1: 후보 3개 빠르게 탐색

```python
# 파일: explore_candidates.py
from datasets import load_dataset

candidates = [
    "BCCard/BCAI-Finance-Kor",
    "KorQuAD/squad_kor_v1",
    "lawcompany/KLAID",
]

for name in candidates:
    print(f"\n=== {name} ===")
    try:
        ds = load_dataset(name, streaming=True, split="train")
        for i, sample in enumerate(ds):
            if i >= 3:
                break
            print(f"  Sample {i}: {str(sample)[:200]}")
    except Exception as e:
        print(f"  [FAIL] {e}")
```

실행:
```bash
python explore_candidates.py
```

### 시나리오 2: 유망한 1개만 전체 다운로드

탐색 결과 `BCCard/BCAI-Finance-Kor`가 유망하면:

```python
from datasets import load_dataset

ds = load_dataset("BCCard/BCAI-Finance-Kor")
ds.save_to_disk("C:/Users/hibou/Omega_CivicFlow_v4/data/bcai_finance_kor")
```

### 시나리오 3: 원본 JSONL 받아서 프로젝트에 편입

```bash
huggingface-cli download BCCard/BCAI-Finance-Kor \
    --repo-type dataset \
    --local-dir C:/Users/hibou/Omega_CivicFlow_v4/data/bcai_finance_kor
```

프로젝트 폴더 구조:
```
Omega_CivicFlow_v4/
├── data/
│   └── bcai_finance_kor/
│       ├── README.md
│       ├── train.parquet (or .jsonl)
│       └── dataset_info.json
├── tools/
│   └── finetune/
└── ...
```

---

## 8. 흔한 에러와 해결

### `OSError: [Errno 28] No space left`
캐시가 C: 드라이브 꽉 참. 해결:
```bash
set HF_HOME=D:/hf_cache
```

### `401 Unauthorized / Gated repo`
로그인 안 됨 or 라이선스 동의 안 함.
```bash
# 로그인
huggingface-cli login

# 데이터셋 페이지 방문 → "Agree and access" 클릭
```

### `ConnectionError: HTTP Error 503`
HuggingFace 서버 일시 불안정. 재시도 + 거울 사용:
```bash
set HF_ENDPOINT=https://hf-mirror.com
```
(중국/한국 네트워크에서 자주 빠름)

### `datasets.exceptions.DatasetGenerationError`
데이터셋 스크립트 버그. 우회:
```python
# trust_remote_code=True 대신 직접 파일 다운로드
from huggingface_hub import snapshot_download
snapshot_download("user/dataset", repo_type="dataset", local_dir="./data")
# 그리고 load_dataset("json", data_files="./data/*.jsonl")
```

### 속도 느림 (한국에서 자주 발생)
aria2로 병렬 다운로드 (기존 메모리에도 있는 기법):
```bash
pip install aria2p
# 또는 hf_transfer 사용
pip install hf_transfer
set HF_HUB_ENABLE_HF_TRANSFER=1
```

---

## 9. 다운로드 전 마지막 체크

**5초 결정 체크리스트:**
- [ ] 라이선스가 상업/파인튜닝 OK? (Apache 2.0, MIT)
- [ ] 크기가 예상 가능? (< 10GB)
- [ ] 스토리지 여유? (`df -h`)
- [ ] 이미 받은 거 아님? (`huggingface-cli scan-cache`)

**큰 데이터(10GB+) 받기 전:**
- `streaming=True`로 먼저 구조 확인
- 필요한 split만 다운로드 (`split="train[:1000]"` 같이 슬라이싱)

---

## 10. 지금 당장 실행할 커맨드

당신이 이 문서 읽고 바로 할 수 있는 3단계:

```bash
# Step 1: 설치 확인
pip install huggingface_hub datasets

# Step 2: 후보 스캔 (이미 받은 BCCard 제외한 2개)
python -c "
from datasets import load_dataset
for name in ['BCCard/BCAI-Finance-Kor', 'KorQuAD/squad_kor_v1']:
    try:
        ds = load_dataset(name, streaming=True, split='train')
        print(f'\n=== {name} ===')
        for i, s in enumerate(ds):
            if i >= 2: break
            print(str(s)[:300])
    except Exception as e:
        print(f'{name}: FAIL - {e}')
"

# Step 3: 최종 후보 로컬 다운로드
# (2번 결과 보고 유망한 것만)
huggingface-cli download <선택한_데이터셋> \
    --repo-type dataset \
    --local-dir C:/Users/hibou/Omega_CivicFlow_v4/data/
```

---

## 11. 면접 질문 대비

**Q: HuggingFace에서 데이터 어떻게 받았나요?**

**Bad answer:** "웹에서 다운로드 버튼 눌렀어요."

**Good answer:**
"먼저 `streaming=True` 모드로 구조와 샘플을 확인한 후, 도메인 적합성을 검증한 다음 `snapshot_download`로 원본 파일을 프로젝트 `data/` 폴더에 받아서 `.gitignore`에 추가했습니다. 큰 데이터는 `hf_transfer`로 병렬 다운로드하고, 라이선스는 Apache 2.0 / MIT만 상업 이용 가능한 것으로 필터링했습니다."

**Q: 받은 데이터가 프로젝트에 안 맞으면?**

"먼저 도메인/포맷 미스매치를 정량 평가합니다. 예: BCCard 카드 상품 Q&A는 DART 공시 분석에 fit 안 맞아서, Stage 1 warmup으로 쓰거나 폐기 판단했습니다. 잘못된 데이터로 파인튜닝하면 '결' 오염이 생기니 도메인 일치를 가장 먼저 검증합니다."
