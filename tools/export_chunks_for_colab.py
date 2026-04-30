"""
Export v2 re-chunks from SQLite → JSONL for Colab embedding.

Output: tools/_chunks_v2.jsonl
Each line: {"chunk_uid": "...", "document_id": int, "text": "..."}
"""
import sys
import sqlite3
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = "C:/Users/hibou/Omega_CivicFlow_v4_DB/omega_civicflow.db"
OUTPUT = Path("C:/Users/hibou/Omega_CivicFlow_v4/tools/_chunks_v2.jsonl")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("""
    SELECT chunk_uid, document_id, text
    FROM document_chunks
    WHERE source_kind = 'rechunk_v2_2026_04'
    ORDER BY document_id, id
""")

n = 0
with open(OUTPUT, "w", encoding="utf-8") as f:
    for chunk_uid, doc_id, text in cur:
        rec = {"chunk_uid": chunk_uid, "document_id": int(doc_id), "text": text}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        n += 1
conn.close()

size_mb = OUTPUT.stat().st_size / 1024 / 1024
print(f"Exported: {n:,} chunks")
print(f"Output: {OUTPUT}")
print(f"Size: {size_mb:.1f} MB")
print(f"\n다음 단계:")
print(f"  1. 이 JSONL 파일을 Colab에 업로드")
print(f"  2. tools/colab_reembedding_guide.md 셀 1~4 실행")
print(f"  3. 생성된 _embeddings_v2.jsonl 다운로드")
print(f"  4. python tools/import_embeddings_to_chroma.py 실행")
