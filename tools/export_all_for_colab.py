"""
Omega CivicFlow — DB 전체 문서 OCR 텍스트 추출 (Colab H100용)
모든 문서의 OCR 텍스트를 pending_docs.json으로 export합니다.
"""
import sys, os, json

BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import SessionLocal
from models.models import Document, OcrText

OUTPUT = r"C:\Users\hibou\Downloads\pending_docs_all.json"

db = SessionLocal()

docs = (
    db.query(Document)
    .filter(Document.status.in_(["analyzed", "ocr_done"]))
    .order_by(Document.id)
    .all()
)

print(f"전체 대상: {len(docs)}건")

docs_out = []
skip = 0
for i, doc in enumerate(docs):
    ocr_rows = (
        db.query(OcrText)
        .filter(OcrText.document_id == doc.id)
        .order_by(OcrText.id)
        .all()
    )
    parts = []
    for r in ocr_rows:
        t = r.cleaned_text or r.raw_text or ""
        if t.strip():
            parts.append(t.strip())
    text = "\n".join(parts)

    if not text or len(text.strip()) < 50:
        skip += 1
        continue

    docs_out.append({
        "doc_id": doc.id,
        "filename": doc.filename,
        "text": text,
        "text_len": len(text),
    })

    if (i + 1) % 500 == 0:
        print(f"  추출: {i+1}/{len(docs)}...")

db.close()

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(docs_out, f, ensure_ascii=False)

total_chars = sum(d["text_len"] for d in docs_out)
total_mb = os.path.getsize(OUTPUT) / 1024 / 1024
short = sum(1 for d in docs_out if d["text_len"] <= 14000)
long_docs = len(docs_out) - short

print(f"\n=== 추출 완료 ===")
print(f"  추출: {len(docs_out)}건 (스킵: {skip}건)")
print(f"  단문(<=14K): {short}건")
print(f"  장문(>14K): {long_docs}건")
print(f"  총 텍스트: {total_chars:,}자")
print(f"  파일 크기: {total_mb:.1f} MB")
print(f"  저장: {OUTPUT}")
