"""
Import Colab 임베딩 결과 (_embeddings_v2.jsonl) → ChromaDB omega_documents_v3.

Input: tools/_embeddings_v2.jsonl (Colab에서 다운로드)
Output: ChromaDB 새 컬렉션 omega_documents_v3

기존 omega_documents_v2는 건드리지 않음 (rollback 안전).
"""
import sys
import json
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import chromadb

CHROMA_PATH = "C:/Users/hibou/Omega_CivicFlow_v4_DB/chroma_db"
INPUT = Path("C:/Users/hibou/Omega_CivicFlow_v4_DB/_embeddings_v2.jsonl")
NEW_COLLECTION = "omega_documents_v3"
BATCH_SIZE = 1000

if not INPUT.exists():
    print(f"[ERR] {INPUT} 파일이 없습니다. Colab에서 다운로드한 _embeddings_v2.jsonl을 tools/에 넣으세요.")
    sys.exit(1)

print(f"[1] ChromaDB 연결: {CHROMA_PATH}")
client = chromadb.PersistentClient(path=CHROMA_PATH)

# 기존 v3 있으면 drop
existing = [c.name for c in client.list_collections()]
if NEW_COLLECTION in existing:
    print(f"[WARN] 기존 {NEW_COLLECTION} 삭제")
    client.delete_collection(NEW_COLLECTION)

print(f"[2] {NEW_COLLECTION} 컬렉션 생성")
col = client.create_collection(
    name=NEW_COLLECTION,
    metadata={"hnsw:space": "cosine"},
)

print(f"[3] JSONL 스트리밍 → 배치 insert (batch_size={BATCH_SIZE})")
t0 = time.time()

batch_ids = []
batch_embs = []
batch_docs = []
batch_metas = []
total = 0

def flush():
    global batch_ids, batch_embs, batch_docs, batch_metas
    if not batch_ids:
        return
    col.add(
        ids=batch_ids,
        embeddings=batch_embs,
        documents=batch_docs,
        metadatas=batch_metas,
    )
    batch_ids = []
    batch_embs = []
    batch_docs = []
    batch_metas = []

with open(INPUT, "r", encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        batch_ids.append(rec["chunk_uid"])
        batch_embs.append(rec["embedding"])
        batch_docs.append(rec["text"])
        batch_metas.append({
            "chunk_uid": rec["chunk_uid"],
            "document_id": str(rec["document_id"]),
            "source_kind": "rechunk_v2_2026_04",
        })
        total += 1

        if len(batch_ids) >= BATCH_SIZE:
            flush()
            if total % 10000 == 0:
                elapsed = time.time() - t0
                rate = total / max(elapsed, 1)
                print(f"  inserted {total:,} ({rate:.0f}/s)")

flush()
elapsed = time.time() - t0
print(f"\n완료: {total:,} vectors, {elapsed:.1f}초 ({elapsed/60:.1f}분)")

print(f"\n컬렉션 상태:")
for c in client.list_collections():
    print(f"  {c.name}: {c.count():,}")

print(f"\n다음 단계: backend/config.py 또는 환경변수에서 CHROMA_COLLECTION_NAME={NEW_COLLECTION} 로 변경")
