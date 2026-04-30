"""
833개 문서 중 청킹 제한으로 분석이 잘린 문서 식별
판단 기준: 
  - raw_response에 _chunk_mode=True인 문서 중
  - _chunk_count * 평균요약(400자) > 12000자 → 잘림 가능성
  - 또는 OCR텍스트 > 400K자 → 잘림 가능성 높음
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import SessionLocal
from models.models import Document, AnalysisResult, OcrText

db = SessionLocal()

docs = db.query(Document).filter(Document.status == "analyzed").all()

results = {
    "완전무결": [],       # 14K 이하 or 청킹했지만 잘리지 않음
    "청킹_잘림가능": [],   # 청킹 후 요약 합계 > 12K → 잘림 가능성
    "알수없음": [],       # chunk 정보 없음
}

for doc in docs:
    ar = db.query(AnalysisResult).filter(
        AnalysisResult.document_id == doc.id
    ).order_by(AnalysisResult.id.desc()).first()
    
    if not ar:
        continue
    
    # OCR 텍스트 길이 계산
    ocr_rows = db.query(OcrText).filter(OcrText.document_id == doc.id).all()
    ocr_len = sum(len(r.cleaned_text or r.raw_text or "") for r in ocr_rows)
    
    # raw_response에서 청크 정보 확인
    raw = ar.raw_response
    if isinstance(raw, str):
        try: raw = json.loads(raw)
        except: raw = {}
    if not isinstance(raw, dict):
        raw = {}
    
    chunk_mode = raw.get("_chunk_mode", False)
    chunk_count = raw.get("_chunk_count", 0)
    
    info = {
        "doc_id": doc.id,
        "filename": doc.filename[:60],
        "ocr_길이": ocr_len,
        "chunk_mode": chunk_mode,
        "chunk_count": chunk_count,
        "summary_len": len(ar.summary or ""),
    }
    
    if not chunk_mode:
        if ocr_len <= 14000:
            # 단문 → 전체 분석
            results["완전무결"].append(info)
        elif ocr_len > 14000:
            # 14K 초과인데 chunk_mode가 False → 14K만 분석됨
            info["이유"] = f"14K 초과({ocr_len:,}자)인데 비청킹 → 앞부분만 분석"
            results["청킹_잘림가능"].append(info)
        else:
            results["알수없음"].append(info)
    else:
        # 청크 모드 → 요약 합계 추정
        estimated_merged = chunk_count * 400  # 평균 400자/청크
        if estimated_merged > 12000:
            info["이유"] = f"{chunk_count}청크×400자={estimated_merged:,}자 > 12K → 뒤쪽 잘림"
            results["청킹_잘림가능"].append(info)
        else:
            results["완전무결"].append(info)

db.close()

# 출력
print("=" * 60)
print(f"  총 문서: {len(docs)}건")
print(f"  ✅ 완전무결: {len(results['완전무결'])}건")
print(f"  ⚠ 청킹 잘림 가능: {len(results['청킹_잘림가능'])}건")
print(f"  ❓ 알수없음: {len(results['알수없음'])}건")
print("=" * 60)

# 잘림 가능 문서 상세
if results["청킹_잘림가능"]:
    print(f"\n⚠ 잘림 가능 문서 ({len(results['청킹_잘림가능'])}건):")
    for item in sorted(results["청킹_잘림가능"], key=lambda x: x["ocr_길이"], reverse=True)[:30]:
        print(f"  #{item['doc_id']:>4} | {item['ocr_길이']:>10,}자 | 청크:{item['chunk_count']:>3} | {item.get('이유','')}")

# 결과 파일 저장
output = {
    "완전무결_count": len(results["완전무결"]),
    "잘림가능_count": len(results["청킹_잘림가능"]),
    "잘림가능_doc_ids": [x["doc_id"] for x in results["청킹_잘림가능"]],
}
with open(r"C:\Users\hibou\Downloads\chunk_analysis.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n결과 저장: C:\\Users\\hibou\\Downloads\\chunk_analysis.json")
