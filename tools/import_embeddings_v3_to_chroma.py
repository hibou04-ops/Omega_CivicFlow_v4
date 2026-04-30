"""
_embeddings_v3.jsonl (v4 청커 + BGE-M3) → ChromaDB omega_documents_v4

Input : C:/Users/hibou/Omega_CivicFlow_v4_DB/_embeddings_v3.jsonl
Output: ChromaDB 컬렉션 omega_documents_v4

기존 v3 컬렉션은 건드리지 않음 (rollback 안전).
"""
import sys, json, time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import chromadb

CHROMA_PATH = "C:/Users/hibou/Omega_CivicFlow_v4_DB/chroma_db"
INPUT       = Path("C:/Users/hibou/Omega_CivicFlow_v4_DB/_embeddings_v3.jsonl")
NEW_COLLECTION = "omega_documents_v4"
BATCH_SIZE  = 1000

if not INPUT.exists():
    print(f"[ERR] {INPUT} 없음 — Drive에서 다운로드 후 Omega_CivicFlow_v4_DB/ 에 저장하세요.")
    sys.exit(1)

print(f"[1] ChromaDB: {CHROMA_PATH}")
client = chromadb.PersistentClient(path=CHROMA_PATH)

existing = [c.name for c in client.list_collections()]
if NEW_COLLECTION in existing:
    print(f"[WARN] 기존 {NEW_COLLECTION} 삭제 후 재생성")
    client.delete_collection(NEW_COLLECTION)

print(f"[2] 컬렉션 생성: {NEW_COLLECTION}")
col = client.create_collection(
    name=NEW_COLLECTION,
    metadata={"hnsw:space": "cosine"},
)

print(f"[3] JSONL → ChromaDB (batch={BATCH_SIZE})")
t0 = time.time()

batch_ids   = []
batch_embs  = []
batch_docs  = []
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
    batch_ids = []; batch_embs = []; batch_docs = []; batch_metas = []

with open(INPUT, "r", encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        batch_ids.append(rec["chunk_uid"])
        batch_embs.append(rec["embedding"])
        batch_docs.append(rec["text"])
        batch_metas.append({
            "chunk_uid":   rec["chunk_uid"],
            "document_id": str(rec["document_id"]),
            "company":     rec.get("company", ""),
            "category":    rec.get("category", ""),
            "source_kind": "chunk_v4_2026_04",
        })
        total += 1

        if len(batch_ids) >= BATCH_SIZE:
            flush()
            if total % 50000 == 0:
                elapsed = time.time() - t0
                print(f"  {total:,}건 ({total/max(elapsed,1):.0f}/s)")

flush()

elapsed = time.time() - t0
print(f"\n완료: {total:,} vectors, {elapsed:.1f}초 ({elapsed/60:.1f}분)")

print("\n컬렉션 현황:")
for c in client.list_collections():
    print(f"  {c.name}: {c.count():,}")

print(f"\n다음 단계:")
print(f"  backend/config.py 또는 .env 에서 CHROMA_COLLECTION_NAME={NEW_COLLECTION} 로 변경")
print(f"  변경 후 backend 재시작")
