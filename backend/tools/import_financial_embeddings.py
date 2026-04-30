# -*- coding: utf-8 -*-
"""
import_financial_embeddings.py — STEP 3: 콜랩 결과를 ChromaDB에 import.

Workflow:
  STEP 1 (로컬): export_financial_chunks_jsonl.py → financial_chunks.jsonl
  STEP 2 (콜랩 A100): colab_embed_financial.py → financial_embeddings.jsonl
  STEP 3 (로컬, 이 스크립트): financial_embeddings.jsonl → ChromaDB add

Idempotent: 기존 source_kind='financial_extract' chunks를 먼저 삭제 후 추가.
"""
import sys
import os
import json
import logging
import argparse

THIS_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(THIS_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.vector_service import _get_collection, COLLECTION_NAME

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

DEFAULT_INPUT = os.path.join(BACKEND_DIR, "..", "financial_embeddings.jsonl")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=DEFAULT_INPUT, help="financial_embeddings.jsonl path")
    parser.add_argument("--batch", type=int, default=500, help="ChromaDB add batch size")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        log.error(f"Input file not found: {args.input}")
        return

    collection = _get_collection(COLLECTION_NAME)
    if collection is None:
        log.error("ChromaDB collection 로드 실패")
        return

    # ── Idempotent: 기존 fin_extract chunks 삭제 ──
    try:
        existing = collection.get(where={"source_kind": "financial_extract"}, include=[])
        if existing and existing.get("ids"):
            collection.delete(ids=existing["ids"])
            log.info(f"기존 fin_extract 청크 삭제: {len(existing['ids'])}건")
    except Exception as e:
        log.warning(f"기존 fin_extract 조회 실패 (skip): {e}")

    before_count = collection.count()
    log.info(f"Collection 시작 count: {before_count}")

    # ── Load embeddings JSONL ──
    log.info(f"Loading: {args.input}")
    records = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    log.info(f"Records: {len(records):,}")

    # ── Batch add to ChromaDB ──
    added = 0
    for batch_start in range(0, len(records), args.batch):
        batch = records[batch_start:batch_start + args.batch]
        try:
            collection.add(
                ids=[r["chunk_uid"] for r in batch],
                embeddings=[r["embedding"] for r in batch],
                documents=[r["text"] for r in batch],
                metadatas=[r["metadata"] for r in batch],
            )
            added += len(batch)
            if (batch_start // args.batch) % 10 == 0:
                log.info(f"  진행: {added:,}/{len(records):,}")
        except Exception as e:
            log.warning(f"Batch add 실패 (start={batch_start}): {e}")

    after_count = collection.count()
    log.info("=" * 60)
    log.info(f"신규 추가: {added:,}건")
    log.info(f"Collection: {before_count:,} → {after_count:,} (+{after_count - before_count:,})")
    log.info("완료")


if __name__ == "__main__":
    main()
