"""
import_to_chromadb.py
=====================
embeddings_v7b.jsonl → ChromaDB PersistentClient

Usage:
  python backend/tools/dart_pipeline/import_to_chromadb.py \
    --input   C:/Users/hibou/Desktop/embeddings_v7b.jsonl \
    --db-path C:/Users/hibou/Omega_CivicFlow_v4/backend/chroma_db \
    --collection omega_documents_v7

Resume: safe to re-run. Checkpoint tracks last completed line index.
        ChromaDB upsert is idempotent by chunk_id.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── ChromaDB metadata field whitelist ─────────────────────────────────────────
# All scalar fields from embeddings_v7b.jsonl (strings + booleans + ints).
# embedding + text are handled separately (embeddings= / documents=).
_META_FIELDS = (
    "company_name",
    "fiscal_year",
    "report_type",
    "statement_scope",
    "chunk_type",
    "rcept_no",
    "xml_role",
    "contains_table",
    "has_unit_annotation",
    "token_estimate",
    "chunk_version",
)


# ── Checkpoint helpers ─────────────────────────────────────────────────────────

def _cp_path(input_path: Path) -> Path:
    return input_path.with_suffix(".import_checkpoint.json")


def _load_checkpoint(input_path: Path) -> int:
    cp = _cp_path(input_path)
    if not cp.exists():
        return 0
    try:
        d = json.loads(cp.read_text(encoding="utf-8"))
        done = int(d.get("done", 0))
        log.info("체크포인트: %d줄 완료", done)
        return done
    except Exception as e:
        log.warning("체크포인트 읽기 실패 (%s) — 처음부터 시작", e)
        return 0


def _save_checkpoint(input_path: Path, done: int, total: int) -> None:
    cp = _cp_path(input_path)
    tmp = cp.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps({"done": done, "total": total}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(cp)
    except Exception as e:
        log.warning("체크포인트 저장 실패: %s", e)


# ── Metadata sanitizer ────────────────────────────────────────────────────────

def _build_metadata(rec: dict) -> dict:
    """
    ChromaDB metadata must contain only str/int/float/bool.
    None → "" for strings, None → 0 for ints, booleans pass through.
    """
    meta: dict = {}
    for field in _META_FIELDS:
        val = rec.get(field)
        if val is None:
            # fiscal_year / chunk_version / report_type are strings
            if field in ("token_estimate",):
                meta[field] = 0
            elif field in ("contains_table", "has_unit_annotation"):
                meta[field] = False
            else:
                meta[field] = ""
        else:
            meta[field] = val
    return meta


# ── Count total lines ─────────────────────────────────────────────────────────

def _count_lines(path: Path) -> int:
    n = 0
    with path.open("rb") as f:
        for _ in f:
            n += 1
    return n


# ── Main import ───────────────────────────────────────────────────────────────

def run(
    input_path: Path,
    db_path: str,
    collection_name: str,
    batch_size: int,
    reset: bool,
) -> None:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    log.info("ChromaDB 연결: %s", db_path)
    client = chromadb.PersistentClient(
        path=db_path,
        settings=ChromaSettings(anonymized_telemetry=False),
    )

    if reset:
        try:
            client.delete_collection(collection_name)
            log.info("기존 컬렉션 삭제: %s", collection_name)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    log.info("컬렉션: %s | 현재 벡터 수: %d", collection_name, collection.count())

    # Count total for progress
    log.info("총 줄 수 계산 중...")
    total = _count_lines(input_path)
    log.info("총 %d줄", total)

    start_idx = 0 if reset else _load_checkpoint(input_path)

    ids:        list[str]        = []
    embeddings: list[list[float]] = []
    documents:  list[str]        = []
    metadatas:  list[dict]       = []

    t0 = time.time()
    flushed = 0     # records actually upserted to ChromaDB
    skipped = 0     # malformed / empty records

    def _flush() -> None:
        nonlocal flushed
        if not ids:
            return
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        flushed += len(ids)
        ids.clear()
        embeddings.clear()
        documents.clear()
        metadatas.clear()

    last_line_idx = start_idx  # track current file position for checkpoint

    with input_path.open(encoding="utf-8") as fh:
        for line_idx, raw in enumerate(fh):
            if line_idx < start_idx:
                continue

            last_line_idx = line_idx + 1  # next resume point

            raw = raw.strip()
            if not raw:
                continue

            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as e:
                log.warning("JSON 파싱 오류 line %d: %s", line_idx + 1, e)
                skipped += 1
                continue

            chunk_id  = rec.get("chunk_id")
            text      = rec.get("text", "")
            embedding = rec.get("embedding")

            # Skip malformed records
            if not chunk_id or not embedding or len(embedding) != 1024:
                log.warning("line %d 건너뜀 — chunk_id=%s, emb_len=%s",
                            line_idx + 1, chunk_id,
                            len(embedding) if embedding else "None")
                skipped += 1
                continue

            ids.append(str(chunk_id))
            embeddings.append(embedding)
            documents.append(text)
            metadatas.append(_build_metadata(rec))

            if len(ids) >= batch_size:
                _flush()
                elapsed = time.time() - t0
                rate = flushed / elapsed if elapsed > 0 else 0
                eta = (total - last_line_idx) / rate if rate > 0 else 0
                log.info(
                    "[%d/%d] %.1f%% | %.0f청크/s | ETA %.1fm | DB 총 %d",
                    last_line_idx, total,
                    last_line_idx / total * 100,
                    rate,
                    eta / 60,
                    collection.count(),
                )
                _save_checkpoint(input_path, last_line_idx, total)

    # Final flush
    _flush()
    _save_checkpoint(input_path, total, total)

    elapsed = time.time() - t0
    final_count = collection.count()
    log.info(
        "완료: upserted=%d | skipped=%d | %.1fs | %.0f청크/s",
        flushed,
        skipped,
        elapsed,
        flushed / elapsed if elapsed > 0 else 0,
    )
    log.info("컬렉션 '%s' 총 벡터: %d", collection_name, final_count)
    log.info("DB 경로: %s", db_path)


# ── Verification mode ─────────────────────────────────────────────────────────

def verify(db_path: str, collection_name: str) -> None:
    """Quick sanity check — count and sample query."""
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    import json

    client = chromadb.PersistentClient(
        path=db_path,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    try:
        col = client.get_collection(collection_name)
    except Exception as e:
        print(f"컬렉션 없음: {e}")
        return

    count = col.count()
    print(f"컬렉션: {collection_name}")
    print(f"총 벡터: {count:,}")

    if count == 0:
        print("벡터 없음 — 임포트 실패")
        return

    # Sample first 3 records
    sample = col.get(limit=3, include=["documents", "metadatas"])
    print("\n샘플 레코드:")
    for i, (doc, meta) in enumerate(zip(sample["documents"], sample["metadatas"])):
        print(f"  [{i+1}] company={meta.get('company_name')} "
              f"chunk_type={meta.get('chunk_type')} "
              f"text_len={len(doc)}")

    # Sample query with a dummy 1024-dim zero vector
    dummy = [0.0] * 1024
    dummy[0] = 1.0
    results = col.query(query_embeddings=[dummy], n_results=3, include=["metadatas"])
    print("\n더미 쿼리 응답 OK — 벡터 인덱스 정상")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="JSONL embeddings → ChromaDB import",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--input", type=Path, required=False,
        help="embeddings_v7b.jsonl path",
    )
    p.add_argument(
        "--db-path", type=str,
        default="C:/Users/hibou/Omega_CivicFlow_v4_DB/chroma_db",
        help="ChromaDB PersistentClient path",
    )
    p.add_argument(
        "--collection", type=str,
        default="omega_documents_v7",
        help="ChromaDB collection name",
    )
    p.add_argument(
        "--batch-size", type=int, default=1000,
        help="Upsert batch size (default 1000)",
    )
    p.add_argument(
        "--reset", action="store_true",
        help="Delete collection before importing (full re-import)",
    )
    p.add_argument(
        "--verify", action="store_true",
        help="Only verify existing collection, no import",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.verify:
        verify(args.db_path, args.collection)
        sys.exit(0)

    if not args.input:
        print("오류: --input 경로 필요 (--verify 모드가 아닌 경우)")
        sys.exit(1)

    if not args.input.exists():
        print(f"오류: 파일 없음 — {args.input}")
        sys.exit(1)

    run(
        input_path=args.input,
        db_path=args.db_path,
        collection_name=args.collection,
        batch_size=args.batch_size,
        reset=args.reset,
    )
