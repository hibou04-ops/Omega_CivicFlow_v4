"""
코랩 결과 정석 주입 스크립트
omega_full_analysis.jsonl → 로컬 DB 정석 파이프라인 주입

사용법:
  cd backend
  python ..\tools\inject_full.py "C:\Users\hibou\Omega_CivicFlow_v4_DB\omega_full_analysis.jsonl"
"""
import sys, os, json, time, logging

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend')
sys.path.insert(0, BACKEND)

logging.basicConfig(level=logging.WARNING, format='%(message)s')

from database import SessionLocal
from models.models import Document, OcrText, AnalysisResult
from services.chat_knowledge_service import upsert_document_knowledge, ensure_knowledge_schema


def main():
    if len(sys.argv) < 2:
        print("사용법: python inject_full.py <omega_full_analysis.jsonl 경로>")
        return

    jsonl_path = sys.argv[1]
    if not os.path.exists(jsonl_path):
        print(f"❌ 파일 없음: {jsonl_path}")
        return

    db = SessionLocal()
    ensure_knowledge_schema()

    # JSONL 로드
    print("=== JSONL 로드 ===")
    entries = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    print(f"   {len(entries)}건 로드")

    print("=== 정석 주입 시작 ===")
    success = 0
    failed = 0
    t0 = time.time()

    for idx, entry in enumerate(entries):
        fname = entry.get("file_name", "")
        raw_text = entry.get("raw_text", "")
        raw_response = entry.get("raw_response", {})
        summary = entry.get("summary", "")
        category = entry.get("category", "")
        company_name = entry.get("company_name", "")
        financial_metrics = entry.get("financial_metrics", "")
        insight_vectors = entry.get("insight_vectors", "")
        evidence = entry.get("evidence", "")
        proc_time = entry.get("processing_time", 0)

        if not fname or not raw_text:
            failed += 1
            continue

        try:
            # 1. Document 생성
            doc = Document(
                filename=fname,
                file_type="xml",
                file_path=f"A100_Full_Analyzed/{fname}",
                status="analyzed",
                user_id=1,
            )
            db.add(doc)
            db.flush()

            # 2. OcrText 생성 (페이지 단위 분할)
            page_size = 2000
            for i in range(0, max(len(raw_text), 1), page_size):
                page_text = raw_text[i:i+page_size]
                if page_text.strip():
                    ocr = OcrText(
                        document_id=doc.id,
                        page_id=None,
                        raw_text=page_text,
                        cleaned_text=page_text,
                        confidence=0.95,
                    )
                    db.add(ocr)

            # 3. AnalysisResult 생성 (정석 — raw_response 포함)
            ar = AnalysisResult(
                document_id=doc.id,
                summary=summary,
                category=category,
                financial_metrics=financial_metrics if isinstance(financial_metrics, str) else json.dumps(financial_metrics, ensure_ascii=False),
                insight_vectors=insight_vectors,
                evidence=evidence,
                raw_response=raw_response,
                model_name="qwen2.5-coder:7b",
                processing_time=proc_time,
            )
            db.add(ar)
            db.flush()

            # 4. 지식 테이블 upsert (metadata, chunks, facts)
            result = upsert_document_knowledge(
                db, doc,
                latest_analysis=ar,
                reindex_chroma=False,  # 벡터는 나중에 rebuild
            )
            db.commit()

            success += 1
            if success % 100 == 0 or success <= 3:
                elapsed = time.time() - t0
                avg = elapsed / max(success, 1)
                remaining = avg * (len(entries) - idx - 1)
                facts = result.get('fact_count', 0)
                chunks = result.get('chunk_count', 0)
                print(
                    f"   ├─ [{success}/{len(entries)}] {company_name} | "
                    f"chunks={chunks} facts={facts} | "
                    f"남은: {remaining/60:.0f}분"
                )

        except Exception as e:
            db.rollback()
            failed += 1
            if failed <= 5:
                print(f"   ❌ {fname}: {str(e)[:100]}")

    db.close()
    elapsed = time.time() - t0
    print("=" * 60)
    print(f"🎉 정석 주입 완료!")
    print(f"   ✅ 성공: {success} / ❌ 실패: {failed}")
    print(f"   ⏱️ 소요: {elapsed:.1f}초")
    print()
    print("다음 단계: 벡터 인덱스 재구축")
    print("  POST http://localhost:8000/panel/vector/rebuild")
    print("=" * 60)


if __name__ == "__main__":
    main()
