"""
Phase A Step 1 — Chunk token length distribution analysis.

프로덕션 ChromaDB (omega_documents_v2, 300K chunks)에서 stride sampling으로
10K chunks 추출 → BGE-M3 tokenizer로 token length 분포 산출.

목적: BGE-M3 max_seq_length=8192를 초과하는 chunk 비율 확인.
     초과 시 재임베딩 파이프라인에서 silent truncation 발생.
"""
import sys
import time
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from transformers import AutoTokenizer

CHROMA_PATH = "C:/Users/hibou/Omega_CivicFlow_v4_DB/chroma_db"
COLLECTION = "omega_documents_v2"
SAMPLE_SIZE = 10000
TOKENIZER_NAME = "BAAI/bge-m3"

print(f"Loading BGE-M3 tokenizer ({TOKENIZER_NAME})...")
tok = AutoTokenizer.from_pretrained(TOKENIZER_NAME)
print("Tokenizer loaded.\n")

print(f"Connecting to ChromaDB: {CHROMA_PATH}")
client = chromadb.PersistentClient(path=CHROMA_PATH)
col = client.get_collection(COLLECTION)
total = col.count()
print(f"Collection: {COLLECTION}, total chunks: {total}\n")

stride = max(1, total // SAMPLE_SIZE)
print(f"Stride sampling: every {stride}th chunk → ~{total // stride} samples\n")

lengths = []
start = time.time()
batch_size = 500
offsets = list(range(0, total, stride))[:SAMPLE_SIZE]

print(f"Fetching {len(offsets)} chunks...")
collected_docs = []
for i in range(0, len(offsets), batch_size):
    batch_offsets = offsets[i:i + batch_size]
    for off in batch_offsets:
        result = col.get(limit=1, offset=off, include=["documents"])
        docs = result.get("documents") or []
        for d in docs:
            if d is not None:
                collected_docs.append(d)
    if (i + batch_size) % 2000 == 0 or i + batch_size >= len(offsets):
        elapsed = time.time() - start
        print(f"  fetched {min(i + batch_size, len(offsets))}/{len(offsets)} ({elapsed:.1f}s)")

print(f"\nTotal docs collected: {len(collected_docs)}")
print(f"Tokenizing...")

t0 = time.time()
tokenize_batch = 256
for i in range(0, len(collected_docs), tokenize_batch):
    batch_docs = collected_docs[i:i + tokenize_batch]
    encoded = tok(batch_docs, add_special_tokens=True, truncation=False, padding=False)
    for ids in encoded["input_ids"]:
        lengths.append(len(ids))

print(f"Tokenization done: {time.time() - t0:.1f}s\n")

lengths = np.array(lengths)
print("=" * 60)
print("  Phase A Step 1 — Chunk Token Length Distribution")
print("=" * 60)
print(f"N (sampled):  {len(lengths)}")
print(f"N (total):    {total}")
print(f"mean:         {lengths.mean():.1f}")
print(f"std:          {lengths.std():.1f}")
print(f"min:          {lengths.min()}")
print(f"max:          {lengths.max()}")
print()
print("--- Percentiles ---")
for p in [50, 75, 90, 95, 99, 99.5, 99.9]:
    v = int(np.percentile(lengths, p))
    print(f"  P{p:<5}: {v}")
print()

print("--- Over threshold ---")
for threshold in [512, 1024, 2048, 4096, 8192]:
    count = int((lengths > threshold).sum())
    pct = 100 * count / len(lengths)
    extrap = int(count * total / len(lengths))
    print(f"  >{threshold:<5}: {count:>5} ({pct:6.3f}%)  ~{extrap:,} chunks in full 300K")
print()

print("--- Histogram ---")
buckets = [0, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 10**9]
for i in range(len(buckets) - 1):
    lo, hi = buckets[i], buckets[i + 1]
    count = int(((lengths >= lo) & (lengths < hi)).sum())
    pct = 100 * count / len(lengths)
    bar = "#" * int(pct / 2)
    hi_str = f"{hi:<6}" if hi < 10**9 else "inf   "
    print(f"  [{lo:>6}-{hi_str}): {count:>5} ({pct:5.2f}%) {bar}")

print()
print("=" * 60)
max_seq = 8192
over_max = int((lengths > max_seq).sum())
over_pct = 100 * over_max / len(lengths)
if over_pct == 0:
    verdict = "[GREEN] 0% over 8192 → BGE-M3 max_seq 충분, 재임베딩 안전"
elif over_pct < 0.1:
    verdict = f"[YELLOW] {over_pct:.3f}% over 8192 → 허용 가능, 극소수 chunk silent truncation"
elif over_pct < 1.0:
    verdict = f"[YELLOW] {over_pct:.3f}% over 8192 → 초과 chunk 섹션 분할 전처리 권장"
else:
    verdict = f"[RED] {over_pct:.3f}% over 8192 → chunking 로직 재검토 필수"
print(f"  Verdict: {verdict}")
print("=" * 60)
