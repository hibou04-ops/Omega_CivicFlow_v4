# Colab Embedding — chunks_v7b.jsonl → BGE-M3 → embeddings_v7b.jsonl

274,199 chunks | BGE-M3 | A100 40GB | ~15분 예상

---

## Cell 1 — GPU 확인

```python
import torch
print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
    print("VRAM:", round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1), "GB")
```

---

## Cell 2 — Drive 마운트

```python
from google.colab import drive
drive.mount('/content/drive')
```

---

## Cell 3 — 패키지 설치

```python
!pip install -q sentence-transformers==3.1.1 FlagEmbedding
```

---

## Cell 4 — BGE-M3 다운로드
HF Hub stall 대비 aria2 fallback 포함.

```python
import os
MODEL_DIR = "/content/bge-m3"

if not os.path.exists(MODEL_DIR):
    try:
        from huggingface_hub import snapshot_download
        snapshot_download("BAAI/bge-m3", local_dir=MODEL_DIR)
        print("HF Hub 다운로드 완료")
    except Exception as e:
        print(f"HF Hub 실패 ({e}) → aria2 fallback")
        os.makedirs(MODEL_DIR, exist_ok=True)
        files = [
            "config.json", "tokenizer.json", "tokenizer_config.json",
            "special_tokens_map.json", "sentencepiece.bpe.model",
            "pytorch_model.bin",
        ]
        base = "https://huggingface.co/BAAI/bge-m3/resolve/main"
        for f in files:
            !aria2c -x 16 -s 16 -d {MODEL_DIR} "{base}/{f}"
else:
    print("모델 캐시 존재, 스킵")
```

---

## Cell 5 — 청크 파일 업로드
Drive에 `chunks_v7b.jsonl` 업로드 후 경로 지정.

```python
# Drive에 올려둔 경로 수정
CHUNKS_PATH = "/content/drive/MyDrive/chunks_v7b.jsonl"
OUTPUT_PATH = "/content/drive/MyDrive/embeddings_v7b.jsonl"
CHECKPOINT_PATH = "/content/drive/MyDrive/embed_v7b_checkpoint.json"

import os
assert os.path.exists(CHUNKS_PATH), f"파일 없음: {CHUNKS_PATH}"
lines = sum(1 for _ in open(CHUNKS_PATH, encoding="utf-8"))
print(f"청크 수: {lines:,}")
```

---

## Cell 6 — 체크포인트 로드

```python
import json

def load_checkpoint(cp_path):
    if os.path.exists(cp_path):
        d = json.load(open(cp_path, encoding="utf-8"))
        print(f"체크포인트 로드: {d['done']:,}개 완료")
        return d
    return {"done": 0, "total": 0}

cp = load_checkpoint(CHECKPOINT_PATH)
START_IDX = cp["done"]
print(f"시작 인덱스: {START_IDX}")
```

---

## Cell 7 — 전체 청크 로드

```python
print("청크 로딩...")
chunks = []
with open(CHUNKS_PATH, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            chunks.append(json.loads(line))

print(f"총 {len(chunks):,}개")

# 이미 처리한 것 건너뜀 (resume)
remaining = chunks[START_IDX:]
print(f"임베딩 대상: {len(remaining):,}개")
```

---

## Cell 8 — 모델 로드

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(MODEL_DIR, device="cuda")
model.max_seq_length = 1024   # 512는 93% 청크 silent truncation 발생
print("embedding dim:", model.get_sentence_embedding_dimension())
print("max_seq_length:", model.max_seq_length)
```

---

## Cell 8b — GPU 강제 이동 (CPU fallback 방지)

```python
import torch

print("CUDA available:", torch.cuda.is_available())
print("현재 device:", next(model.parameters()).device)

if str(next(model.parameters()).device) == "cpu":
    model = model.to("cuda")
    print("→ CUDA 이동 완료")

print("최종 device:", next(model.parameters()).device)

# 워밍업 (첫 배치 느린 것 방지)
_ = model.encode(["워밍업"], batch_size=1, normalize_embeddings=True)
print("워밍업 완료")
```

---

## Cell 9 — 임베딩 실행 (체크포인트 포함)

```python
import time
import numpy as np

BATCH_SIZE = 64        # A100 40GB 최적
SAVE_EVERY = 1000      # 1000청크마다 체크포인트

def save_checkpoint(cp_path, done, total):
    tmp = cp_path + ".tmp"
    json.dump({"done": done, "total": total}, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, cp_path)

# append 모드 (resume 안전)
out_f = open(OUTPUT_PATH, "a", encoding="utf-8", buffering=1)

print(f"임베딩 시작 (배치={BATCH_SIZE}, {len(remaining):,}개)...")
t0 = time.time()
done = 0

for i in range(0, len(remaining), BATCH_SIZE):
    batch = remaining[i : i + BATCH_SIZE]
    texts = [c["text"] for c in batch]

    vecs = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    for c, vec in zip(batch, vecs):
        rec = {
            "chunk_id":        c["chunk_id"],
            "text":            c["text"],
            "embedding":       vec.tolist(),
            "company_name":    c["company_name"],
            "fiscal_year":     c["fiscal_year"],
            "report_type":     c["report_type"],
            "statement_scope": c["statement_scope"],
            "chunk_type":      c["chunk_type"],
            "rcept_no":        c["rcept_no"],
            "xml_role":        c["xml_role"],
            "contains_table":  c["contains_table"],
            "has_unit_annotation": c["has_unit_annotation"],
            "token_estimate":  c["token_estimate"],
            "chunk_version":   c.get("chunk_version", "v7"),
        }
        out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    done += len(batch)
    global_done = START_IDX + done

    if done % SAVE_EVERY == 0:
        out_f.flush()
        save_checkpoint(CHECKPOINT_PATH, global_done, len(chunks))
        elapsed = time.time() - t0
        rate = done / elapsed
        eta = (len(remaining) - done) / rate
        print(f"  [{global_done:,}/{len(chunks):,}] {rate:.0f}청크/s | ETA {eta/60:.1f}m")

out_f.flush()
out_f.close()
save_checkpoint(CHECKPOINT_PATH, START_IDX + done, len(chunks))

elapsed = time.time() - t0
print(f"\n완료: {done:,}개 | {elapsed:.1f}s | {done/elapsed:.0f}청크/s")
print(f"출력: {OUTPUT_PATH}")
```

---

## Cell 10 — 결과 확인

```python
n_lines = sum(1 for _ in open(OUTPUT_PATH, encoding="utf-8"))
size_mb = os.path.getsize(OUTPUT_PATH) / 1024 / 1024
print(f"임베딩 JSONL: {n_lines:,}줄 | {size_mb:.0f} MB")

# 샘플 확인
sample = json.loads(open(OUTPUT_PATH, encoding="utf-8").readline())
print(f"embedding dim: {len(sample['embedding'])}")
print(f"샘플 company: {sample['company_name']}")
print(f"샘플 chunk_type: {sample['chunk_type']}")
print(f"샘플 scope: {sample['statement_scope']}")
```

---

## 완료 후 로컬 작업

Drive에서 `embeddings_v7b.jsonl` 다운로드 → `C:/Users/hibou/Desktop/` 저장 후:

### Step 1 — ChromaDB 임포트

```
cd C:/Users/hibou/Omega_CivicFlow_v4/backend
venv/Scripts/python tools/dart_pipeline/import_to_chromadb.py \
  --input   C:/Users/hibou/Desktop/embeddings_v7b.jsonl \
  --db-path C:/Users/hibou/Omega_CivicFlow_v4_DB/chroma_db \
  --collection omega_documents_v7
```

예상 소요: 274K 벡터 / 1000배치 = ~275 upsert → **5~10분** (CPU only)

재시작 안전: 체크포인트 자동 저장 (`embeddings_v7b.import_checkpoint.json`)

### Step 2 — 검증

```
venv/Scripts/python tools/dart_pipeline/import_to_chromadb.py \
  --verify \
  --db-path C:/Users/hibou/Omega_CivicFlow_v4_DB/chroma_db \
  --collection omega_documents_v7
```

총 벡터 수 274,199 확인 후 → Step 3.

### Step 3 — config .env 업데이트

`C:/Users/hibou/Omega_CivicFlow_v4/backend/.env` 에서:

```
CHROMA_COLLECTION_NAME=omega_documents_v7
```

추가 또는 기존 값 교체. 백엔드 재시작하면 새 컬렉션으로 전환됨.
