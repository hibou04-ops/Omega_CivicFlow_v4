# DataSet 폴더에 없는 문서의 청크를 삭제하는 스크립트.
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text
from pathlib import Path

DATASET_DIR = Path(r"C:\Users\hibou\Desktop\DataSet")
DB_PATH = r"C:\Users\hibou\Omega_CivicFlow_v4_DB\omega_civicflow.db"

engine = create_engine(f"sqlite:///{DB_PATH}")

# 1. DataSet 폴더의 파일명 수집
dataset_files = set(f.name for f in DATASET_DIR.iterdir() if f.is_file())
print(f"DataSet 파일 수: {len(dataset_files)}")

with engine.connect() as conn:
    # 2. 현재 상태 확인
    total_chunks = conn.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar()
    total_docs = conn.execute(text("SELECT COUNT(*) FROM documents")).scalar()
    print(f"현재 document_chunks: {total_chunks}")
    print(f"현재 documents: {total_docs}")

    # 3. DataSet에 없는 document_id 찾기
    rows = conn.execute(text("SELECT id, filename FROM documents")).fetchall()

    keep_ids = set()
    delete_ids = set()
    for doc_id, filename in rows:
        if filename in dataset_files:
            keep_ids.add(doc_id)
        else:
            delete_ids.add(doc_id)

    print(f"\n유지할 documents: {len(keep_ids)}")
    print(f"삭제할 documents: {len(delete_ids)}")

    # 4. 삭제 대상 청크 수 확인
    if delete_ids:
        placeholders = ",".join(str(i) for i in delete_ids)
        del_chunk_count = conn.execute(
            text(f"SELECT COUNT(*) FROM document_chunks WHERE document_id IN ({placeholders})")
        ).scalar()
        keep_chunk_count = total_chunks - del_chunk_count
        print(f"삭제할 chunks: {del_chunk_count}")
        print(f"남을 chunks: {keep_chunk_count}")

        confirm = input("\n삭제를 진행하시겠습니까? (yes/no): ")
        if confirm.strip().lower() == "yes":
            # 청크 삭제
            conn.execute(
                text(f"DELETE FROM document_chunks WHERE document_id IN ({placeholders})")
            )
            conn.commit()

            remaining = conn.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar()
            print(f"\n삭제 완료! 남은 chunks: {remaining}")
        else:
            print("취소됨.")
    else:
        print("삭제할 문서가 없습니다.")
