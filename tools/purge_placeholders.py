"""
플레이스홀더 문서 1,689건 DB 삭제
gemini-2.5-flash로 분석된 processing_time < 0.1초 문서들
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import SessionLocal
from models.models import Document, AnalysisResult, OcrText, Page

db = SessionLocal()

# 플레이스홀더 찾기: processing_time < 0.1
placeholders = (
    db.query(AnalysisResult)
    .filter(AnalysisResult.processing_time < 0.1)
    .all()
)

doc_ids = [p.document_id for p in placeholders]
print(f"플레이스홀더: {len(doc_ids)}건")

# 정상 문서 수 확인
good = (
    db.query(AnalysisResult)
    .filter(AnalysisResult.processing_time >= 0.1)
    .count()
)
print(f"정상 문서: {good}건")
print(f"삭제 후 남을 문서: {good}건")

confirm = input("\n정말 삭제? (yes 입력): ")
if confirm.strip().lower() != "yes":
    print("취소")
    db.close()
    exit()

deleted = 0
for i, doc_id in enumerate(doc_ids):
    try:
        # 관련 데이터 삭제
        db.query(AnalysisResult).filter(AnalysisResult.document_id == doc_id).delete()
        db.query(OcrText).filter(OcrText.document_id == doc_id).delete()
        db.query(Page).filter(Page.document_id == doc_id).delete()
        
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            # 파일 삭제
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
    
    if (i+1) % 100 == 0:
        db.commit()
        print(f"  [{i+1}/{len(doc_ids)}] 삭제됨: {deleted}")

db.commit()
db.close()
print(f"\n✅ 완료! {deleted}건 삭제. 정상 문서 {good}건 유지.")
