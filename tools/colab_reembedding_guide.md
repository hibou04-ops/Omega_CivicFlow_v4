# Colab A100 재임베딩 가이드 (v2 chunks → `omega_documents_v3`)

## 사전 준비 (로컬)
1. `python tools/export_chunks_for_colab.py` 실행 완료 (`_chunks_v2.jsonl` 생성)
2. JSONL 파일을 Colab에 업로드 (`/content/_chunks_v2.jsonl`)

## Colab Runtime
Runtime > Change runtime type > **GPU > A100**

---

## Cell 1 — 환경 + aria2 모델 다운로드 (전체 aria2 기반)

```python
import subprocess
from pathlib import Path

MODEL_DIR = "/content/bge-m3"
Path(MODEL_DIR).mkdir(parents=True, exist_ok=True)
Path(f"{MODEL_DIR}/1_Pooling").mkdir(parents=True, exist_ok=True)

!apt-get install -qq -y aria2 > /dev/null
print("aria2 설치 완료")

BASE = "https://huggingface.co/BAAI/bge-m3/resolve/main"

# pytorch_model.bin — 이미 있으면 skip
pytorch_path = Path(f"{MODEL_DIR}/pytorch_model.bin")
if pytorch_path.exists() and pytorch_path.stat().st_size > 2_000_000_000:
    print(f"pytorch_model.bin 이미 존재 ({pytorch_path.stat().st_size / 1e9:.2f} GB), skip")
else:
    print("pytorch_model.bin 다운로드 (16 parallel)...")
    !aria2c -x 16 -s 16 -c --console-log-level=warn \
        --auto-file-renaming=false --allow-overwrite=true \
        -d {MODEL_DIR} -o pytorch_model.bin \
        {BASE}/pytorch_model.bin

# 작은 파일도 aria2로 (wget이 HF에서 차단되는 경우 있음)
print("\n설정/토크나이저 파일 (aria2)...")
small_files = [
    ("config.json", MODEL_DIR),
    ("tokenizer.json", MODEL_DIR),
    ("tokenizer_config.json", MODEL_DIR),
    ("sentencepiece.bpe.model", MODEL_DIR),
    ("special_tokens_map.json", MODEL_DIR),
    ("sentence_bert_config.json", MODEL_DIR),
    ("modules.json", MODEL_DIR),
    ("config_sentence_transformers.json", MODEL_DIR),
    ("1_Pooling/config.json", f"{MODEL_DIR}/1_Pooling"),
]
for fname, target_dir in small_files:
    local_name = fname.split("/")[-1]
    url = f"{BASE}/{fname}"
    result = subprocess.run(
        ["aria2c",
         "-x", "4", "-s", "4", "-c",
         "--console-log-level=error",
         "--summary-interval=0",
         "--auto-file-renaming=false",
         "--allow-overwrite=true",
         "-d", target_dir,
         "-o", local_name,
         url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  [ERR] {fname}: {result.stderr[-200:]}")
    else:
        size = Path(target_dir, local_name).stat().st_size
        print(f"  {fname} ({size:,} bytes)")

print("\n모든 파일 다운로드 완료")
```

---

## Cell 2 — BGE-M3 로드 (max_seq=512, 기존 설계 유지)

```python
from sentence_transformers import SentenceTransformer
import torch

print("모델 로드 중...")
model = SentenceTransformer("/content/bge-m3", device="cuda")
model.max_seq_length = 512
print(f"로드 완료. max_seq_length={model.max_seq_length}, dim={model.get_sentence_embedding_dimension()}")
print(f"GPU: {torch.cuda.get_device_name(0)}")
```

---

## Cell 3 — JSONL 로드 + 배치 임베딩

```python
import json
import numpy as np
import time
from pathlib import Path

INPUT = "/content/_chunks_v2.jsonl"
OUTPUT = "/content/_embeddings_v2.jsonl"
BATCH_SIZE = 64

chunks = []
with open(INPUT, "r", encoding="utf-8") as f:
    for line in f:
        chunks.append(json.loads(line))

print(f"로드: {len(chunks):,} chunks")

t0 = time.time()
with open(OUTPUT, "w", encoding="utf-8") as out_f:
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        texts = [c["text"] for c in batch]
        embs = model.encode(
            texts,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        for c, e in zip(batch, embs):
            rec = {
                "chunk_uid": c["chunk_uid"],
                "document_id": c["document_id"],
                "text": c["text"],
                "embedding": e.tolist(),
            }
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        if (i // BATCH_SIZE) % 50 == 0:
            elapsed = time.time() - t0
            rate = (i + len(batch)) / max(elapsed, 1)
            eta = (len(chunks) - i - len(batch)) / max(rate, 1)
            print(f"  {i + len(batch):,}/{len(chunks):,} rate={rate:.0f}/s ETA={eta/60:.1f}min")

print(f"\n완료: {time.time() - t0:.1f}s")
print(f"Output: {OUTPUT}")
```

---

## Cell 4 — 다운로드 링크

```python
from google.colab import files
files.download("/content/_embeddings_v2.jsonl")
```

---

## 로컬 복귀 후
1. 다운로드한 `_embeddings_v2.jsonl`을 `tools/` 폴더로 이동
2. `python tools/import_embeddings_to_chroma.py` 실행
3. ChromaDB `omega_documents_v3` 컬렉션 생성 확인
4. 설정 파일 (`backend/config.py` 또는 env) `CHROMA_COLLECTION_NAME=omega_documents_v3` 변경
5. RAGAS 평가 실행 → 점수 확인

## 예상 시간
- 다운로드 (aria2): ~30초
- 모델 로드: ~10초
- 312,572 chunks 임베딩 (A100, batch 64): **~15분**
- 파일 다운로드: ~1-2분

## 롤백
`omega_documents_v3` 컬렉션만 새로 만들므로 기존 `omega_documents_v2`는 그대로 보존. 설정 파일만 되돌리면 즉시 원복.
