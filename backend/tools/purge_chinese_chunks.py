"""
═══════════════════════════════════════════════════════
Omega CivicFlow — ChromaDB 중국어 오염 청크 외과적 제거
═══════════════════════════════════════════════════════
실행: python tools/purge_chinese_chunks.py [--dry-run]

--dry-run : 실제 삭제 없이 오염 현황만 출력
"""

import sys
import re
import argparse
import chromadb
from chromadb.config import Settings

DB_PATH = "C:/Users/hibou/Omega_CivicFlow_v4_DB/chroma_db"
COLLECTIONS = ["omega_documents", "omega_document_chunks"]
CN_PATTERN = re.compile(r"[\u4e00-\u9fff]")
BATCH_SIZE = 500


def has_chinese(text: str) -> bool:
    return bool(CN_PATTERN.search(text or ""))


def purge_collection(col, dry_run: bool) -> dict:
    total = col.count()
    if total == 0:
        print(f"  └─ 비어있음, 스킵")
        return {"total": 0, "contaminated": 0, "deleted": 0, "affected_doc_ids": set()}

    print(f"  └─ 총 {total}건 스캔 중...")

    # 페이징으로 전체 조회
    contaminated_ids = []
    affected_doc_ids = set()
    offset = 0

    while offset < total:
        batch = col.get(
            limit=BATCH_SIZE,
            offset=offset,
            include=["documents", "metadatas"],
        )
        if not batch["ids"]:
            break

        for chunk_id, doc, meta in zip(batch["ids"], batch["documents"], batch["metadatas"]):
            if has_chinese(doc):
                contaminated_ids.append(chunk_id)
                doc_id = (meta or {}).get("doc_id")
                if doc_id is not None:
                    affected_doc_ids.add(doc_id)

        offset += BATCH_SIZE

    contaminated_count = len(contaminated_ids)
    print(f"  ├─ 오염 청크: {contaminated_count}건 / {total}건 ({contaminated_count/max(total,1)*100:.1f}%)")
    print(f"  ├─ 영향받은 문서 doc_id: {sorted(affected_doc_ids)}")

    if contaminated_count == 0:
        print(f"  └─ ✅ 오염 없음")
        return {"total": total, "contaminated": 0, "deleted": 0, "affected_doc_ids": affected_doc_ids}

    if dry_run:
        print(f"  └─ [DRY-RUN] 삭제 대상 ID 예시: {contaminated_ids[:3]}")
        return {"total": total, "contaminated": contaminated_count, "deleted": 0, "affected_doc_ids": affected_doc_ids}

    # 배치 삭제
    deleted = 0
    for i in range(0, len(contaminated_ids), BATCH_SIZE):
        batch_ids = contaminated_ids[i : i + BATCH_SIZE]
        col.delete(ids=batch_ids)
        deleted += len(batch_ids)
        print(f"  ├─ 삭제 진행: {deleted}/{contaminated_count}건")

    print(f"  └─ ✅ {deleted}건 삭제 완료")
    return {"total": total, "contaminated": contaminated_count, "deleted": deleted, "affected_doc_ids": affected_doc_ids}


def main():
    parser = argparse.ArgumentParser(description="ChromaDB 중국어 오염 청크 제거")
    parser.add_argument("--dry-run", action="store_true", help="삭제 없이 현황만 출력")
    args = parser.parse_args()

    mode = "DRY-RUN" if args.dry_run else "실제 삭제"
    print(f"\n{'='*55}")
    print(f"  Omega CivicFlow — 중국어 오염 청크 제거 ({mode})")
    print(f"{'='*55}")

    client = chromadb.PersistentClient(
        path=DB_PATH,
        settings=Settings(anonymized_telemetry=False),
    )

    all_affected = set()
    total_deleted = 0

    for col_name in COLLECTIONS:
        print(f"\n[컬렉션: {col_name}]")
        try:
            col = client.get_collection(col_name)
            result = purge_collection(col, dry_run=args.dry_run)
            all_affected.update(result["affected_doc_ids"])
            total_deleted += result["deleted"]
        except Exception as e:
            print(f"  └─ 오류: {e}")

    print(f"\n{'='*55}")
    print(f"  총 삭제: {total_deleted}건")
    print(f"  재인덱싱 필요 doc_id: {sorted(all_affected)}")
    print(f"\n  ⚡ 다음 단계: 위 doc_id 문서들을 관리자 UI에서")
    print(f"     '재분석' 실행하면 EXAONE으로 깨끗하게 재인덱싱됩니다.")
    print(f"{'='*55}\n")

    if all_affected and not args.dry_run:
        # 재인덱싱 대상을 파일로 저장
        with open("reindex_targets.txt", "w", encoding="utf-8") as f:
            for doc_id in sorted(all_affected):
                f.write(f"{doc_id}\n")
        print(f"  📋 재인덱싱 대상 doc_id → reindex_targets.txt 저장됨")


if __name__ == "__main__":
    main()
