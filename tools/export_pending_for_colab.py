"""
Omega CivicFlow — 재분석 대상 문서를 pending_docs.json으로 추출
gemini-2.5-flash 플레이스홀더 (processing_time < 0.1s) 문서의
OCR 텍스트를 JSON으로 추출하여 Colab에 업로드할 수 있게 합니다.

사용법:
  cd backend
  python ..\tools\export_pending_for_colab.py
  → pending_docs.json 생성 (Downloads 폴더)
"""
import sys, os, json

BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from database import SessionLocal
from models.models import Document, AnalysisResult, OcrText

OUTPUT = r"C:\Users\hibou\Downloads\pending_docs.json"

db = SessionLocal()

# 재분석 대상: processing_time < 0.1s
pairs = (
    db.query(Document, AnalysisResult)
    .join(AnalysisResult, AnalysisResult.document_id == Document.id)
    .filter(AnalysisResult.processing_time < 0.1)
    .order_by(Document.id)
    .all()
)

print(f"재분석 대상: {len(pairs)}건")

docs_out = []
for i, (doc, ar) in enumerate(pairs):
    # OCR 텍스트 로드
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
        continue

    docs_out.append({
        "doc_id": doc.id,
        "filename": doc.filename,
        "text": text,
        "text_len": len(text),
    })

    if (i + 1) % 200 == 0:
        print(f"  추출: {i+1}/{len(pairs)}...")

db.close()

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(docs_out, f, ensure_ascii=False)

total_chars = sum(d["text_len"] for d in docs_out)
total_mb = os.path.getsize(OUTPUT) / 1024 / 1024

print(f"\n=== 추출 완료 ===")
print(f"  문서 수: {len(docs_out)}건")
print(f"  총 텍스트: {total_chars:,}자")
print(f"  파일 크기: {total_mb:.1f} MB")
print(f"  저장: {OUTPUT}")
print(f"\n  → 이 파일을 Colab에 업로드 후 재분석 스크립트를 실행하세요.")
