"""
Re-chunk all documents from ocr_texts.raw_text → document_chunks (clean rebuild).

1. 기존 document_chunks 테이블을 document_chunks_old_{timestamp}로 RENAME (백업)
2. 새 document_chunks 테이블 생성 (동일 스키마)
3. ocr_texts.raw_text → deep_clean_text → chunk_text_quality → INSERT
4. 진행률 로그, 완료 시 통계
"""
import sys
import sqlite3
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

BACKEND_DIR = Path("C:/Users/hibou/Omega_CivicFlow_v4/backend")
sys.path.insert(0, str(BACKEND_DIR))

from tools.chunk_only import chunk_text_quality, deep_clean_text

DB_PATH = "C:/Users/hibou/Omega_CivicFlow_v4_DB/omega_civicflow.db"

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA journal_mode=WAL")
cur = conn.cursor()

# 1. Backup existing table via RENAME
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_NAME = f"document_chunks_old_{TIMESTAMP}"
print(f"[1] Renaming document_chunks → {BACKUP_NAME}")
cur.execute(f"ALTER TABLE document_chunks RENAME TO {BACKUP_NAME}")
conn.commit()

# 2. Create new document_chunks table (identical schema)
print("[2] Creating new document_chunks table")
cur.execute("""
CREATE TABLE document_chunks (
    id INTEGER NOT NULL,
    chunk_uid VARCHAR(64) NOT NULL,
    document_id INTEGER NOT NULL,
    page_no INTEGER,
    page_from INTEGER,
    page_to INTEGER,
    section_name VARCHAR(255),
    text TEXT NOT NULL,
    text_hash VARCHAR(64),
    source_kind VARCHAR(50),
    token_count INTEGER,
    metadata_json JSON,
    vector_collection VARCHAR(100),
    indexed_at DATETIME,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(document_id) REFERENCES documents (id)
)
""")
cur.execute("CREATE INDEX idx_document_chunks_doc_id ON document_chunks(document_id)")
cur.execute("CREATE INDEX idx_document_chunks_chunk_uid ON document_chunks(chunk_uid)")
conn.commit()

# 3. Fetch all documents with raw_text + metadata
print("[3] Fetching documents...")
cur.execute("""
    SELECT d.id, d.filename,
           dm.company_name, dm.company_name_norm,
           dm.fiscal_year, dm.report_type,
           o.raw_text, o.cleaned_text
    FROM documents d
    LEFT JOIN ocr_texts o ON o.document_id = d.id
    LEFT JOIN document_metadata dm ON dm.document_id = d.id
    WHERE o.raw_text IS NOT NULL AND length(o.raw_text) > 100
    ORDER BY d.id
""")
docs = cur.fetchall()
print(f"  {len(docs)} documents to process")

# 4. Chunk each document and insert
insert_sql = """
INSERT INTO document_chunks
(chunk_uid, document_id, section_name, text, text_hash, source_kind, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

total_chunks = 0
stats = {"success": 0, "skip": 0, "error": 0}
t0 = time.time()
now_utc = datetime.now(timezone.utc).isoformat()

print("[4] Chunking + insert...")
for idx, row in enumerate(docs, 1):
    doc_id, filename, company, company_norm, fy, report_type, raw_text, cleaned_text = row
    try:
        text_source = cleaned_text if cleaned_text and len(cleaned_text) > 100 else raw_text
        if not text_source or len(text_source) < 100:
            stats["skip"] += 1
            continue

        cleaned = deep_clean_text(text_source)
        if len(cleaned) < 100:
            stats["skip"] += 1
            continue

        company_for_meta = company_norm or company or ""
        meta = {"company_name": company_for_meta}
        chunks = chunk_text_quality(cleaned, meta)

        if not chunks:
            stats["skip"] += 1
            continue

        batch_rows = []
        for ci, c in enumerate(chunks):
            chunk_hash = hashlib.sha256(c.encode("utf-8")).hexdigest()
            chunk_uid = f"rechunk_{doc_id}_{ci}_{chunk_hash[:12]}"[:64]
            batch_rows.append((chunk_uid, doc_id, None, c, chunk_hash, "rechunk_2026_04", now_utc))

        cur.executemany(insert_sql, batch_rows)
        total_chunks += len(batch_rows)
        stats["success"] += 1

        if idx % 100 == 0:
            conn.commit()
            elapsed = time.time() - t0
            rate = idx / max(elapsed, 1)
            eta = (len(docs) - idx) / max(rate, 0.01)
            print(f"  [{idx}/{len(docs)}] chunks={total_chunks:,} rate={rate:.1f}doc/s ETA={eta/60:.1f}min")

    except Exception as e:
        stats["error"] += 1
        print(f"  [ERR] doc {doc_id} ({filename[:40] if filename else 'unknown'}): {e}")

conn.commit()

elapsed = time.time() - t0
print()
print("=" * 60)
print("  재청킹 완료")
print("=" * 60)
print(f"문서 처리: {len(docs)}건")
print(f"  성공: {stats['success']}")
print(f"  스킵: {stats['skip']}")
print(f"  에러: {stats['error']}")
print(f"총 청크: {total_chunks:,}개")
print(f"소요: {elapsed:.1f}초 ({elapsed/60:.1f}분)")

cur.execute("SELECT COUNT(*) FROM document_chunks")
new_count = cur.fetchone()[0]
cur.execute(f"SELECT COUNT(*) FROM {BACKUP_NAME}")
old_count = cur.fetchone()[0]
print()
print(f"새 document_chunks: {new_count:,}")
print(f"백업 {BACKUP_NAME}: {old_count:,}")
print(f"차이: {new_count - old_count:+,}")

# Length stats
cur.execute("""
    SELECT
        COUNT(*),
        MIN(length(text)),
        MAX(length(text)),
        AVG(length(text))
    FROM document_chunks
""")
n, mn, mx, avg = cur.fetchone()
print(f"\n새 chunks 문자 길이: min={mn}, max={mx:,}, avg={int(avg)}")

conn.close()
print("\n완료. 재임베딩 필요 시 별도 작업.")
