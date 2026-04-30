"""
잘림 가능 29건 DB 제거 + ChromaDB 재구축 (394건 무결 데이터만)
"""
import sys, os, json, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import SessionLocal
from models.models import Document, AnalysisResult, OcrText, Page
from config import settings

# 잘림 가능 doc_ids
TRUNCATED_IDS = [3,85,290,393,421,422,423,424,425,426,427,428,429,430,431,432,433,3227,3238,3240,3241,3242,3245,3246,3247,3248,3252,3254,3256]

db = SessionLocal()

# 0단계: 잘림 문서 파일을 바탕화면에 복사
DESKTOP = os.path.expanduser(r"~\Desktop")
TRUNCATED_DIR = os.path.join(DESKTOP, "잘림_문서_29건")
os.makedirs(TRUNCATED_DIR, exist_ok=True)

print(f"📁 잘림 문서 백업 → {TRUNCATED_DIR}")
for doc_id in TRUNCATED_IDS:
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if doc and doc.file_path and os.path.exists(doc.file_path):
        import shutil as _sh
        dst = os.path.join(TRUNCATED_DIR, os.path.basename(doc.file_path))
        if not os.path.exists(dst):
            _sh.copy2(doc.file_path, dst)
            print(f"  ✅ #{doc_id} → {os.path.basename(doc.file_path)}")

# 1단계: 잘림 문서 제거
print(f"\n🗑 잘림 가능 {len(TRUNCATED_IDS)}건 DB 제거...")
deleted = 0
for doc_id in TRUNCATED_IDS:
    try:
        db.query(AnalysisResult).filter(AnalysisResult.document_id == doc_id).delete()
        db.query(OcrText).filter(OcrText.document_id == doc_id).delete()
        db.query(Page).filter(Page.document_id == doc_id).delete()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            if doc.file_path and os.path.exists(doc.file_path):
                try: os.remove(doc.file_path)
                except: pass
            if doc.report_path and os.path.exists(doc.report_path):
                try: os.remove(doc.report_path)
                except: pass
            db.delete(doc)
            deleted += 1
    except Exception as e:
        print(f"  ❌ #{doc_id}: {e}")
        db.rollback()

db.commit()
remaining = db.query(Document).filter(Document.status == "analyzed").count()
print(f"✅ {deleted}건 삭제 → 남은 문서: {remaining}건")

db.close()

# 2단계: ChromaDB 완전 초기화
chroma_path = settings.CHROMADB_DIR
if os.path.exists(chroma_path):
    shutil.rmtree(chroma_path)
    print(f"\n✅ ChromaDB 삭제: {chroma_path}")
os.makedirs(chroma_path, exist_ok=True)

# 3단계: 무결 데이터만으로 재구축
print(f"\n🔧 ChromaDB 재구축 시작 ({remaining}건 무결 데이터)...")
from services.vector_service import rebuild_index_from_db
result = rebuild_index_from_db()

print(f"\n{'='*55}")
print(f"  ✅ 완전무결 ChromaDB 재구축 완료!")
print(f"  문서: {result['documents']}건 (무결 검증됨)")
print(f"  LLM 청크: {result['llm_chunks']}개")
print(f"  OCR 청크: {result['ocr_chunks']}개")
print(f"  총 벡터: {result['total_chunks']}개")
print(f"{'='*55}")
