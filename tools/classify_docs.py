"""804건 문서 정밀 분류"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import SessionLocal
from models.models import Document, AnalysisResult, OcrText

db = SessionLocal()
docs = db.query(Document).filter(Document.status == "analyzed").all()

무결 = []
잘림 = []
pt_null = []
no_ar = []

for doc in docs:
    ar = db.query(AnalysisResult).filter(
        AnalysisResult.document_id == doc.id
    ).order_by(AnalysisResult.id.desc()).first()
    
    if not ar:
        no_ar.append(doc.id)
        continue
    
    ocr = db.query(OcrText).filter(OcrText.document_id == doc.id).all()
    ocr_len = sum(len(r.cleaned_text or r.raw_text or "") for r in ocr)
    
    raw = ar.raw_response
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    
    chunk_mode = raw.get("_chunk_mode", False)
    chunk_count = raw.get("_chunk_count", 0)
    pt = ar.processing_time
    
    info = {
        "id": doc.id,
        "fn": (doc.filename or "")[:60],
        "ocr_len": ocr_len,
        "pt": pt,
        "model": ar.model_name,
        "chunk_mode": chunk_mode,
        "chunk_count": chunk_count,
        "summary": (ar.summary or "")[:80],
    }
    
    if pt is None or pt == 0.0:
        pt_null.append(info)
    elif not chunk_mode and ocr_len <= 14000:
        무결.append(info)
    elif chunk_mode and chunk_count * 400 <= 12000:
        무결.append(info)
    else:
        잘림.append(info)

db.close()

print("=" * 60)
print(f"  전체: {len(docs)}건")
print(f"  ✅ 무결: {len(무결)}건")
print(f"  ⚠ 잘림가능: {len(잘림)}건")
print(f"  ❓ processing_time=0/NULL: {len(pt_null)}건")
print(f"  ❌ 분석없음: {len(no_ar)}건")
print("=" * 60)

if pt_null:
    print(f"\n❓ pt=0/NULL 샘플 (처음 5건):")
    for x in pt_null[:5]:
        print(f"  #{x['id']} | model={x['model']} | pt={x['pt']} | ocr={x['ocr_len']:,}자")
        print(f"    summary: {x['summary']}")

# 결과 저장
result = {
    "무결_ids": [x["id"] for x in 무결],
    "무결_count": len(무결),
    "잘림_ids": [x["id"] for x in 잘림],
    "잘림_count": len(잘림),
    "pt_null_ids": [x["id"] for x in pt_null],
    "pt_null_count": len(pt_null),
}
with open(r"C:\Users\hibou\Downloads\doc_classification.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\n저장: C:\\Users\\hibou\\Downloads\\doc_classification.json")
