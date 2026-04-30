"""모델별 분석 현황 확인"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from database import SessionLocal
from models.models import Document, AnalysisResult
from sqlalchemy import func

db = SessionLocal()

# 모델별 분석 현황
models = db.query(
    AnalysisResult.model_name,
    func.count(AnalysisResult.id),
    func.avg(AnalysisResult.processing_time)
).group_by(AnalysisResult.model_name).all()

print("=== 모델별 분석 현황 ===")
for m, cnt, avg_t in models:
    avg_t = avg_t or 0
    print(f"  {m or 'N/A'}: {cnt}건 (평균 {avg_t:.1f}s)")

# gemini-2.5-flash 플레이스홀더
flash = db.query(AnalysisResult).filter(
    AnalysisResult.model_name == "gemini-2.5-flash"
).all()
placeholder = 0
for a in flash:
    s = a.summary or ""
    t = a.processing_time or 0
    if "텍스트 주입 완료" in s or t < 0.1:
        placeholder += 1

print(f"\ngemini-2.5-flash 총: {len(flash)}건")
print(f"  플레이스홀더: {placeholder}건")
print(f"  정상: {len(flash) - placeholder}건")

# 전체 재분석 대상
all_bad = db.query(AnalysisResult).filter(
    AnalysisResult.processing_time < 0.1
).count()
print(f"\n전체 처리시간 <0.1s (재분석 필요): {all_bad}건")

# OCR 텍스트 보유 현황 (재분석 가능 여부)
from models.models import OcrText
has_ocr = db.query(func.count(func.distinct(OcrText.document_id))).scalar()
print(f"OCR 텍스트 보유 문서: {has_ocr}건")

db.close()
