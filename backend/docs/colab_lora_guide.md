# Colab LoRA 학습 가이드 — Omega CivicFlow

> **목표:** Llama 3.1 8B Instruct를 공공 민원 문서 분류/요약 태스크에 특화 학습

---

## Colab 필수 설치 패키지

```python
!pip install transformers==5.3.0 peft==0.18.1 trl==0.29.0 \
    bitsandbytes==0.49.2 accelerate datasets
```

## GPU 환경 자동 감지

> 노트북 첫 셀에서 실행하여 A100/T4 플랜을 자동 결정

```python
import subprocess
result = subprocess.run(
    ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
    capture_output=True, text=True
)
gpu_info = result.stdout.strip()
print(f"GPU: {gpu_info}")

if "A100" in gpu_info:
    print("→ A100 플랜 적용")
    RANK, ALPHA, MAX_LEN, BATCH, GRAD_ACCUM = 16, 32, 4096, 2, 8
elif "T4" in gpu_info:
    print("→ T4 플랜 적용 (메모리 절약 모드)")
    RANK, ALPHA, MAX_LEN, BATCH, GRAD_ACCUM = 8, 16, 2048, 1, 16
else:
    print(f"→ 미확인 GPU, T4 플랜으로 폴백")
    RANK, ALPHA, MAX_LEN, BATCH, GRAD_ACCUM = 8, 16, 2048, 1, 16
```

---

## 환경별 학습 설정

### 🔵 A100 (권장 — Colab Pro+)

| 항목 | 값 |
|------|---|
| VRAM | 40GB |
| 베이스 모델 | `meta-llama/Llama-3.1-8B-Instruct` |
| 학습 방식 | QLoRA (4-bit) |
| rank / alpha | 16 / 32 |
| max_length | 4096 |
| batch size | 2, gradient_accumulation 8 |
| lr | 2e-4 |
| 예상 학습시간 | ~1-2시간 |

### 🟡 T4 (무료 — Colab 기본)

> ⚠ T4 VRAM 12~15GB 실질적. Llama 3.1 8B QLoRA는 OOM 위험 있음.

| 항목 | 1순위 (안정) | 2순위 (8B 도전) |
|------|------------|----------------|
| 베이스 모델 | `mistralai/Mistral-7B-Instruct-v0.3` | `meta-llama/Llama-3.1-8B-Instruct` |
| VRAM 사용량 | ~10-12GB ✅ | ~13-15GB ⚠ |
| rank / alpha | 8 / 16 | 8 / 16 |
| max_length | 2048 | 1024 (더 줄임) |
| batch size | 1, grad_accum 16 | 1, grad_accum 16 |

**T4 OOM 방지 필수 설정:**

```python
from transformers import BitsAndBytesConfig
import torch

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_use_double_quant=True,   # 메모리 추가 절약
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
)

# TrainingArguments에서 반드시:
# optim="paged_adamw_8bit"  ← 일반 adamw 대신
```

> 💡 T4 학습 시 **구글 드라이브 마운트 필수** — 세션 종료 시 학습 결과 날아감!
> `from google.colab import drive; drive.mount('/content/drive')`

---

## 학습 데이터 (AI Hub 3종)

1. **문서요약 텍스트** → 요약 태스크
2. **민원 업무 자동화 언어 데이터** → 분류 태스크
3. **공공 민원 상담 LLM 데이터** → 멀티태스크

---

## GGUF 병합 변환 및 Ollama 적용 (⭐ 권장)

### Step 1. Colab에서 어댑터를 베이스 모델에 병합

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

base_model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-3.1-8B-Instruct",
    torch_dtype=torch.float16,
    device_map="auto"
)
merged_model = PeftModel.from_pretrained(base_model, "/content/adapter")
merged_model = merged_model.merge_and_unload()

merged_model.save_pretrained("/content/drive/MyDrive/doc-llm/merged_model")
tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-3.1-8B-Instruct")
tokenizer.save_pretrained("/content/drive/MyDrive/doc-llm/merged_model")
print("병합 완료!")
```

### Step 2. 로컬에서 llama.cpp로 GGUF 변환

```bash
# llama.cpp 클론 (처음 한 번만)
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
pip install -r requirements.txt

# HuggingFace 포맷 → GGUF 변환
python convert_hf_to_gguf.py /path/to/merged_model \
    --outfile doc-llm-merged.gguf \
    --outtype q4_k_m    # Q4_K_M: 속도·품질 균형 (권장)
```

> 양자화 옵션: `q4_k_m` (권장) | `q8_0` (품질 우선) | `q2_k` (초경량)

### Step 3. Ollama에 등록 및 실행

```bash
cat > Modelfile << 'EOF'
FROM ./doc-llm-merged.gguf
PARAMETER temperature 0.2
PARAMETER num_ctx 8192
SYSTEM 당신은 공공 민원 문서 분석 보조 모델이다. 반드시 JSON으로만 답하고,
        summary, category, department, evidence를 포함한다.
EOF

ollama create doc-llm-v1 -f Modelfile
ollama run doc-llm-v1
# → 로컬 서버: http://localhost:11434
```
