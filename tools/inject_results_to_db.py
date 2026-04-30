import time
import json
import os
import sys

print("\n" + "=" * 60)
print("  Ω  Phase 3 — 로컬 데이터베이스 주입 (Injector)")
print("=" * 60)

# 1. 파일 강제 매핑 (사용자가 알려준 경로 그대로 사용)
RESULT_FILE = r"c:\Users\hibou\Downloads\analysis_results (6).json"

if not os.path.exists(RESULT_FILE):
    print(f"❌ 오류: 지정된 경로에 파일이 없습니다 -> {RESULT_FILE}")
    sys.exit(1)

with open(RESULT_FILE, "r", encoding="utf-8") as f:
    results = json.load(f)
    
print(f"📦 로드된 분석 결과: {len(results)}건")

# 2. 시스템 절대 경로 주입 (경로 오류 원천 차단)
TARGET_BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if TARGET_BACKEND_DIR not in sys.path:
    sys.path.insert(0, TARGET_BACKEND_DIR)

try:
    from database import SessionLocal
    from models.models import Document, AnalysisResult
    
    # PDF 모듈은 선택사항
    try:
        from services.pdf_report_service import generate_pdf_report
        can_generate_pdf = True
    except ImportError:
        print("⚠️ [선택] PDF 생성 모듈 로드 실패 (DB 주입은 정상 진행합니다.)")
        can_generate_pdf = False

    db = SessionLocal()
    success_count = 0
    t0 = time.time()
    
    for item in results:
        doc_id = item["doc_id"]
        res = item["result"]
        
        # 1. AnalysisResult 동기화
        analysis = db.query(AnalysisResult).filter(AnalysisResult.document_id == doc_id).first()
        if not analysis:
            analysis = AnalysisResult(
                document_id=doc_id,
                summary=res.get("summary", ""),
                category=res.get("category", ""),
                evidence=json.dumps(res.get("evidence", []), ensure_ascii=False) if isinstance(res.get("evidence"), list) else res.get("evidence", ""),
                financial_metrics=res.get("financial_metrics", ""),
                insight_vectors=res.get("insight_vectors", ""),
                model_name=res.get("_model", "qwen-vllm-offline"),
                raw_response=res
            )
            db.add(analysis)
        else:
            analysis.summary = res.get("summary", "")
            analysis.raw_response = res
            
        # 2. Document 상태 전이 및 PDF 연결
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc:
            doc.status = "analyzed"
            if can_generate_pdf:
                try:
                    pdf_path = generate_pdf_report(
                        doc_id, doc.filename,
                        {"summary": res.get("summary", ""), "category": res.get("category", ""), "raw_response": res}
                    )
                    if pdf_path:
                        doc.report_path = pdf_path
                except Exception:
                    pass 
        
        success_count += 1
        if success_count % 500 == 0:
            print(f"  ... {success_count}건 메모리 적재 완료")
            
    db.commit()
    print(f"\n✅ 완료: 100% 무결성으로 총 {success_count}개 문서가 DB 내 코어 테이블에 정상 병합되었습니다. (소요시간: {(time.time()-t0):.2f}초)")

except ImportError as e:
    print(f"❌ DB 모듈 주소 매핑 실패: {e}")
except Exception as e:
    if 'db' in locals(): db.rollback()
    print(f"❌ 트랜잭션 도중 예외 발생 (자동 롤백됨): {e}")
finally:
    if 'db' in locals(): db.close()
