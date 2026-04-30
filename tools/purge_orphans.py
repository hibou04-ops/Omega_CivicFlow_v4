"""분석결과 없는 410건 유령 Document 제거"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import SessionLocal
from models.models import Document, AnalysisResult, OcrText, Page

db = SessionLocal()

# AnalysisResult 없는 문서 찾기
all_docs = db.query(Document).all()
orphans = []
for doc in all_docs:
    ar = db.query(AnalysisResult).filter(AnalysisResult.document_id == doc.id).first()
    if not ar:
        orphans.append(doc)

print(f"전체 문서: {len(all_docs)}건")
print(f"유령 문서 (분석 없음): {len(orphans)}건")
print(f"정상 문서: {len(all_docs) - len(orphans)}건")

deleted = 0
for doc in orphans:
    try:
        db.query(OcrText).filter(OcrText.document_id == doc.id).delete()
        db.query(Page).filter(Page.document_id == doc.id).delete()
        if doc.file_path and os.path.exists(doc.file_path):
            try: os.remove(doc.file_path)
            except: pass
        if doc.report_path and os.path.exists(doc.report_path):
            try: os.remove(doc.report_path)
            except: pass
        db.delete(doc)
        deleted += 1
    except:
        db.rollback()
    if deleted % 100 == 0 and deleted > 0:
        db.commit()

db.commit()
remaining = db.query(Document).count()
db.close()
print(f"\n✅ {deleted}건 삭제 → 남은 문서: {remaining}건 (전부 무결)")
