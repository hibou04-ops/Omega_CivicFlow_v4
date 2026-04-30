"""
Enrich ChromaDB omega_documents_v3 metadata with company_name.

현재 v3 컬렉션 메타데이터: {chunk_uid, document_id, source_kind}
→ company_name 추가 → 회사별 pre-filter retrieval 가능

source: omega_civicflow.db.document_metadata (document_id → company_name, company_name_norm)

Non-destructive: collection.update()로 기존 embedding은 유지, metadata만 갱신.
"""
import sys
import sqlite3
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import chromadb

DB_PATH = "C:/Users/hibou/Omega_CivicFlow_v4_DB/omega_civicflow.db"
CHROMA_PATH = "C:/Users/hibou/Omega_CivicFlow_v4_DB/chroma_db"
COLLECTION = "omega_documents_v3"
BATCH_SIZE = 1000


def main():
    print(f"[1] SQL metadata 로드: {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("""
        SELECT document_id,
               COALESCE(NULLIF(TRIM(company_name_norm), ''), company_name)
        FROM document_metadata
        WHERE document_id IS NOT NULL
    """)
    doc_to_company = {}
    for doc_id, company in cur.fetchall():
        if company:
            doc_to_company[str(doc_id)] = company
    conn.close()
    print(f"    {len(doc_to_company):,} documents with company_name")

    print(f"\n[2] ChromaDB 연결: {CHROMA_PATH}")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    col = client.get_collection(COLLECTION)
    total = col.count()
    print(f"    {COLLECTION}: {total:,} vectors")

    print(f"\n[3] 전량 metadata 갱신 (batch={BATCH_SIZE})")
    t0 = time.time()
    updated = 0
    missing_company = 0
    offset = 0

    while offset < total:
        got = col.get(
            limit=BATCH_SIZE,
            offset=offset,
            include=["metadatas"],
        )
        ids = got["ids"]
        metas = got["metadatas"]
        if not ids:
            break

        new_metas = []
        for md in metas:
            doc_id = str(md.get("document_id", ""))
            company = doc_to_company.get(doc_id)
            new_md = dict(md)
            if company:
                new_md["company_name"] = company
                updated += 1
            else:
                missing_company += 1
            new_metas.append(new_md)

        col.update(ids=ids, metadatas=new_metas)
        offset += len(ids)

        if offset % 10000 == 0 or offset >= total:
            elapsed = time.time() - t0
            rate = offset / max(elapsed, 1)
            eta = (total - offset) / max(rate, 1)
            print(f"    {offset:,}/{total:,} ({rate:.0f}/s, ETA {eta:.0f}s)")

    elapsed = time.time() - t0
    print(f"\n[4] 완료: {elapsed:.1f}s")
    print(f"    company_name 주입: {updated:,}")
    print(f"    document_id 매칭 실패: {missing_company:,}")

    print(f"\n[5] 검증 — 샘플 5개")
    sample = col.get(limit=5, include=["metadatas"])
    for i, md in enumerate(sample["metadatas"], 1):
        print(f"    #{i}: {md}")

    print(f"\n[6] 회사별 pre-filter 동작 검증")
    test_company = "삼성전자"
    result = col.get(
        where={"company_name": test_company},
        limit=3,
        include=["metadatas"],
    )
    print(f"    where={{company_name: '{test_company}'}} → {len(result['ids'])} hits")
    for i, md in enumerate(result["metadatas"], 1):
        print(f"      #{i}: doc_id={md.get('document_id')} company={md.get('company_name')}")


if __name__ == "__main__":
    main()
