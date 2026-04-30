#!/usr/bin/env python3
"""
한화솔루션 — 청킹 + ChromaDB 임베딩 (CPU 온도 관리 버전)
배치 16개 + 1초 sleep으로 CPU 온도 제어
"""
import sys, os, json, re, hashlib, logging, time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from tools.chunk_only import deep_clean_text, extract_metadata, chunk_text_quality
from services.dart_file_parser import extract_text_from_dart_zip

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("hanwha_ingest")

DATASET_DIR = Path(r"C:\Users\hibou\Desktop\DataSet")
CHROMADB_DIR = r"C:\Users\hibou\Omega_CivicFlow_v4_DB\chroma_db"
COLLECTION = "omega_document_chunks"

def main():
    files = sorted(DATASET_DIR.glob("*한화솔루션*.zip"))
    log.info(f"ZIP 파일: {len(files)}개")

    # 청킹
    all_chunks = []
    for filepath in files:
        log.info(f"처리: {filepath.name}")
        try:
            with open(str(filepath), 'rb') as f:
                content = f.read()
            text = extract_text_from_dart_zip(content, filepath.name)
        except Exception as e:
            log.warning(f"  추출 실패: {e}")
            continue
        if not text or len(text) < 100:
            log.warning(f"  텍스트 부족 ({len(text) if text else 0}자)")
            continue
        cleaned = deep_clean_text(text)
        meta = extract_metadata(filepath.name, cleaned)
        meta["company_name"] = "한화솔루션"
        chunks = chunk_text_quality(cleaned, meta)
        log.info(f"  {len(cleaned):,}자 → {len(chunks)}개 청크")
        rcept_no = meta["rcept_no"]
        for i, chunk in enumerate(chunks):
            all_chunks.append({
                "id": f"hanwha_sol_{rcept_no}_{i:04d}",
                "text": chunk,
                "metadata": {
                    "company": "한화솔루션",
                    "category": meta["category"],
                    "filename": filepath.name,
                    "rcept_no": rcept_no,
                    "chunk_index": i,
                    "source": "local_ingest",
                },
            })

    log.info(f"총 청크: {len(all_chunks)}개")
    if not all_chunks:
        return

    # 이미 적재된 청크 확인 (이전 중단분)
    import chromadb
    from chromadb.config import Settings
    db = chromadb.PersistentClient(path=CHROMADB_DIR, settings=Settings(anonymized_telemetry=False))
    col = db.get_collection(COLLECTION)

    existing_ids = set()
    try:
        r = col.get(where={"company": "한화솔루션"}, include=[])
        existing_ids = set(r["ids"])
        log.info(f"이미 적재: {len(existing_ids)}건")
    except:
        pass

    # 이미 적재된 건 스킵
    remaining = [c for c in all_chunks if c["id"] not in existing_ids]
    log.info(f"신규 적재 필요: {len(remaining)}건")

    if not remaining:
        log.info("모두 적재 완료!")
        return

    # GPU 호환성 문제 우회: CPU 강제 + 대형 배치로 빠르게
    import os
    os.environ["CUDA_VISIBLE_DEVICES"] = ""  # CPU 강제
    
    log.info("임베딩 모델 로드 (CPU)...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True, device="cpu")
    log.info("로드 완료")

    # 대형 배치 + sleep 없음
    BATCH = 64
    total = 0
    start = time.time()

    for i in range(0, len(remaining), BATCH):
        batch = remaining[i:i+BATCH]
        texts = [c["text"] for c in batch]
        ids = [c["id"] for c in batch]
        metas = [c["metadata"] for c in batch]

        embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        col.add(ids=ids, documents=texts, metadatas=metas, embeddings=embs.tolist())

        total += len(batch)
        elapsed = time.time() - start
        speed = total / elapsed if elapsed > 0 else 0
        eta = (len(remaining) - total) / speed if speed > 0 else 0
        log.info(f"  {total}/{len(remaining)} ({speed:.1f}/s, ETA {eta:.0f}s)")

    after = col.count()
    log.info(f"\n✅ 완료! ChromaDB: {after:,}건")

if __name__ == "__main__":
    main()
