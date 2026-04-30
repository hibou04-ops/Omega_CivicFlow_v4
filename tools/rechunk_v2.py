"""
Rechunk v2 — RAGAS 95 target chunker.

chunk_text_quality (기존) + post-processing hard max enforcement.
MAX_CHARS = 1000 (safe below 512 tokens for Korean).

Pipeline:
1. Backup document_chunks → document_chunks_v1_{ts}
2. Create new document_chunks (same schema)
3. For each document: deep_clean_text → chunk_text_quality → enforce_hard_max → INSERT
4. Verify max <= MAX_CHARS, print histogram
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

MAX_CHARS = 1000
OVERLAP_CHARS = 100
MIN_CHARS = 80

# Korean-aware recursive separators, ordered by preference
SEPARATORS = [
    "\n\n",
    "\n",
    "다. ",
    "요. ",
    "습니다. ",
    ". ",
    ", ",
    " ",
    "",
]


def recursive_split(text: str, max_chars: int, seps_idx: int = 0) -> list:
    """Split text into chunks of at most max_chars, respecting boundaries."""
    if len(text) <= max_chars:
        return [text]

    if seps_idx >= len(SEPARATORS):
        # Force char-level split with overlap
        chunks = []
        i = 0
        step = max(1, max_chars - OVERLAP_CHARS)
        while i < len(text):
            chunks.append(text[i:i + max_chars])
            i += step
        return chunks

    sep = SEPARATORS[seps_idx]

    if sep == "":
        # Char-level fallback
        chunks = []
        i = 0
        step = max(1, max_chars - OVERLAP_CHARS)
        while i < len(text):
            chunks.append(text[i:i + max_chars])
            i += step
        return chunks

    if sep not in text:
        return recursive_split(text, max_chars, seps_idx + 1)

    parts = text.split(sep)
    chunks = []
    current = ""
    for p in parts:
        if not p:
            continue
        candidate = current + (sep if current else "") + p
        if len(candidate) > max_chars:
            if current:
                chunks.append(current)
            current = p
        else:
            current = candidate
    if current:
        chunks.append(current)

    # Recurse on any remaining oversized chunks
    final = []
    for c in chunks:
        if len(c) <= max_chars:
            final.append(c)
        else:
            final.extend(recursive_split(c, max_chars, seps_idx + 1))
    return final


def extract_prefix(chunk: str) -> tuple:
    """Extract '[company] section_title\\n' or '[company]\\n' prefix."""
    if not chunk.startswith("["):
        return "", chunk
    end = chunk.find("\n")
    if 0 < end < 200:
        return chunk[:end + 1], chunk[end + 1:]
    return "", chunk


def enforce_hard_max(chunks: list, max_chars: int = MAX_CHARS) -> tuple:
    """
    Post-process chunks to enforce hard max_chars.
    Preserves prefix across splits.
    Returns (final_chunks, num_oversized_input).
    """
    final = []
    oversized = 0
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final.append(chunk)
            continue

        oversized += 1
        prefix, body = extract_prefix(chunk)
        body_budget = max_chars - len(prefix)

        if body_budget < 200:
            # Prefix too long — keep chunk as-is (shouldn't happen in practice)
            final.append(chunk)
            continue

        sub_chunks = recursive_split(body, body_budget)
        for sc in sub_chunks:
            sc_stripped = sc.strip()
            if len(sc_stripped) >= MIN_CHARS:
                final.append(prefix + sc_stripped)
    return final, oversized


def chunk_text_v2(text: str, meta: dict) -> tuple:
    """RAGAS 95 chunker: chunk_text_quality + hard max enforcement."""
    raw_chunks = chunk_text_quality(text, meta)
    return enforce_hard_max(raw_chunks, MAX_CHARS)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    TS = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP = f"document_chunks_v1_{TS}"

    print(f"[1] Backing up document_chunks → {BACKUP}")
    cur.execute(f"ALTER TABLE document_chunks RENAME TO {BACKUP}")
    conn.commit()

    print("[2] Creating new document_chunks (v2 clean schema)")
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
    cur.execute("CREATE INDEX idx_chunks_doc_id ON document_chunks(document_id)")
    cur.execute("CREATE INDEX idx_chunks_chunk_uid ON document_chunks(chunk_uid)")
    conn.commit()

    print("[3] Fetching documents...")
    cur.execute("""
        SELECT d.id, d.filename,
               dm.company_name, dm.company_name_norm,
               o.raw_text, o.cleaned_text
        FROM documents d
        LEFT JOIN ocr_texts o ON o.document_id = d.id
        LEFT JOIN document_metadata dm ON dm.document_id = d.id
        WHERE o.raw_text IS NOT NULL AND length(o.raw_text) > 100
        ORDER BY d.id
    """)
    docs = cur.fetchall()
    print(f"  {len(docs)} documents to process")

    insert_sql = """
    INSERT INTO document_chunks
    (chunk_uid, document_id, section_name, text, text_hash, source_kind, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """

    total_chunks = 0
    total_oversized_fixed = 0
    stats = {"success": 0, "skip": 0, "error": 0}
    t0 = time.time()
    now_utc = datetime.now(timezone.utc).isoformat()

    print("[4] Chunking v2 (hard max enforced)...")
    for idx, row in enumerate(docs, 1):
        doc_id, filename, company, company_norm, raw_text, cleaned_text = row
        try:
            text_source = cleaned_text if cleaned_text and len(cleaned_text) > 100 else raw_text
            if not text_source or len(text_source) < 100:
                stats["skip"] += 1
                continue

            cleaned = deep_clean_text(text_source)
            if len(cleaned) < 100:
                stats["skip"] += 1
                continue

            meta = {"company_name": (company_norm or company or "")}
            chunks, oversized = chunk_text_v2(cleaned, meta)
            total_oversized_fixed += oversized

            if not chunks:
                stats["skip"] += 1
                continue

            batch_rows = []
            for ci, c in enumerate(chunks):
                chunk_hash = hashlib.sha256(c.encode("utf-8")).hexdigest()
                chunk_uid = f"v2_{doc_id}_{ci}_{chunk_hash[:12]}"[:64]
                batch_rows.append((chunk_uid, doc_id, None, c, chunk_hash, "rechunk_v2_2026_04", now_utc))

            cur.executemany(insert_sql, batch_rows)
            total_chunks += len(batch_rows)
            stats["success"] += 1

            if idx % 100 == 0:
                conn.commit()
                elapsed = time.time() - t0
                rate = idx / max(elapsed, 1)
                eta = (len(docs) - idx) / max(rate, 0.01)
                print(f"  [{idx}/{len(docs)}] chunks={total_chunks:,} oversized_fixed={total_oversized_fixed} rate={rate:.1f}doc/s ETA={eta/60:.1f}min")

        except Exception as e:
            stats["error"] += 1
            print(f"  [ERR] doc {doc_id}: {e}")

    conn.commit()
    elapsed = time.time() - t0

    print()
    print("=" * 60)
    print("  재청킹 v2 완료 (RAGAS 95 타겟)")
    print("=" * 60)
    print(f"문서: {len(docs)} (성공 {stats['success']}, 스킵 {stats['skip']}, 에러 {stats['error']})")
    print(f"총 chunks: {total_chunks:,}")
    print(f"hard max 강제 분할된 oversized chunks: {total_oversized_fixed}")
    print(f"소요: {elapsed:.1f}초 ({elapsed/60:.1f}분)")

    cur.execute("SELECT MIN(length(text)), MAX(length(text)), AVG(length(text)) FROM document_chunks")
    mn, mx, avg = cur.fetchone()
    print(f"\n문자 길이: min={mn}, max={mx}, avg={int(avg)}")

    if mx > MAX_CHARS:
        print(f"⚠ MAX={mx} > MAX_CHARS={MAX_CHARS}: enforcement 실패!")
    else:
        print(f"✓ 모든 chunks <= {MAX_CHARS} chars — hard max enforced")

    cur.execute("""
        SELECT
            SUM(CASE WHEN length(text) <= 256 THEN 1 ELSE 0 END),
            SUM(CASE WHEN length(text) > 256 AND length(text) <= 512 THEN 1 ELSE 0 END),
            SUM(CASE WHEN length(text) > 512 AND length(text) <= 800 THEN 1 ELSE 0 END),
            SUM(CASE WHEN length(text) > 800 AND length(text) <= 1000 THEN 1 ELSE 0 END),
            SUM(CASE WHEN length(text) > 1000 THEN 1 ELSE 0 END)
        FROM document_chunks
    """)
    b1, b2, b3, b4, b5 = cur.fetchone()
    total = b1 + b2 + b3 + b4 + b5
    print(f"\n히스토그램:")
    print(f"  [0-256]:      {b1:>7,}  ({100*b1/total:5.2f}%)")
    print(f"  (256-512]:    {b2:>7,}  ({100*b2/total:5.2f}%)")
    print(f"  (512-800]:    {b3:>7,}  ({100*b3/total:5.2f}%)")
    print(f"  (800-1000]:   {b4:>7,}  ({100*b4/total:5.2f}%)")
    print(f"  (>1000):      {b5:>7,}  ({100*b5/total:5.2f}%)  ← 0이어야 함")

    conn.close()
    print("\n완료. 다음 단계: Colab A100에서 BGE-M3 재임베딩.")


if __name__ == "__main__":
    main()
