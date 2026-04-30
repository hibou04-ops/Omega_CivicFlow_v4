"""
삭제된 문서 DB 복구
uploads 폴더의 파일을 스캔하여 DB에 없는 것을 다시 등록
(OCR + 분석은 재분석 필요)
"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import SessionLocal
from models.models import Document

UPLOAD_DIR = r"C:\Users\hibou\Omega_CivicFlow_v4_DB\uploads"

db = SessionLocal()

# 현재 DB에 있는 file_path들
existing_paths = set()
for doc in db.query(Document).all():
    if doc.file_path:
        existing_paths.add(os.path.normpath(doc.file_path))

# uploads 폴더 스캔
all_files = []
for f in os.listdir(UPLOAD_DIR):
    fp = os.path.join(UPLOAD_DIR, f)
    if os.path.isfile(fp) and not f.startswith("."):
        all_files.append((f, fp))

print(f"uploads 폴더: {len(all_files)}개 파일")
print(f"현재 DB: {len(existing_paths)}개 문서")

# DB에 없는 파일 복구
restored = 0
for filename, filepath in all_files:
    norm = os.path.normpath(filepath)
    if norm in existing_paths:
        continue
    
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    file_type = (
        "pdf" if ext == "pdf"
        else "html" if ext in ("html", "htm")
        else "xml" if ext in ("xml", "xbrl", "xsd")
        else "zip" if ext == "zip"
        else "xls" if ext in ("xls", "xlsx")
        else ext
    )
    
    file_size = os.path.getsize(filepath)
    
    doc = Document(
        user_id=1,  # admin
        filename=filename,
        file_path=filepath,
        file_type=file_type,
        file_size=file_size,
        status="uploaded",  # OCR + 분석 재필요
    )
    db.add(doc)
    restored += 1
    
    if restored % 100 == 0:
        db.commit()
        print(f"  복구 중... {restored}건")

db.commit()

total = db.query(Document).count()
db.close()

print(f"\n{'='*50}")
print(f"  ✅ 복구 완료!")
print(f"  복구된 문서: {restored}건 (status=uploaded)")
print(f"  DB 전체: {total}건")
print(f"  → 프론트엔드에서 재분석 가능")
print(f"{'='*50}")
