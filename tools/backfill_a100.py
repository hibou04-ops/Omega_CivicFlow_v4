"""
A100 주입 문서 보강 — ocr_texts 채운 후 backfill로 지식 테이블 전부 생성
순수 SQLite 작업 (CPU/GPU 사용 없음)
"""
import sys, os, json

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend')
sys.path.insert(0, BACKEND)

from database import SessionLocal
from models.models import Document, OcrText, AnalysisResult
from services.chat_knowledge_service import upsert_document_knowledge, ensure_knowledge_schema

JSONL_PATH = r"C:\Users\hibou\Omega_CivicFlow_v4_DB\chatbot_training_data.jsonl"


def main():
    if not os.path.exists(JSONL_PATH):
        print(f"❌ JSONL 파일 없음: {JSONL_PATH}")
        return

    db = SessionLocal()
    ensure_knowledge_schema()

    # Step 1: JSONL에서 filename → raw_text 맵 구성
    print("=== Step 1: JSONL 로드 ===")
    jsonl_map = {}
    with open(JSONL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            fname = data.get("file_name", "")
            raw_text = data.get("raw_text", "")
            if fname and raw_text:
                jsonl_map[fname] = raw_text
    print(f"   JSONL 문서 수: {len(jsonl_map)}")

    # Step 2: A100 문서 중 ocr_texts가 없는 것에 raw_text 삽입
    print("=== Step 2: ocr_texts 채우기 ===")
    a100_docs = db.query(Document).filter(
        Document.file_path.contains('A100_Cloud')
    ).all()
    print(f"   A100 문서 수: {len(a100_docs)}")

    ocr_inserted = 0
    for doc in a100_docs:
        existing = db.query(OcrText).filter(OcrText.document_id == doc.id).first()
        if existing:
            continue
        raw_text = jsonl_map.get(doc.filename, "")
        if not raw_text:
            continue

        # 텍스트를 페이지 단위로 분할 (대략 2000자씩)
        page_size = 2000
        pages = []
        for i in range(0, len(raw_text), page_size):
            pages.append(raw_text[i:i+page_size])

        for idx, page_text in enumerate(pages, start=1):
            ocr = OcrText(
                document_id=doc.id,
                page_id=None,
                raw_text=page_text,
                cleaned_text=page_text,
                confidence=0.95,
            )
            db.add(ocr)

        ocr_inserted += 1
        if ocr_inserted % 200 == 0:
            db.commit()
            print(f"   ├─ {ocr_inserted}건 ocr_texts 삽입 완료")

    db.commit()
    print(f"   ✅ 총 {ocr_inserted}건 ocr_texts 삽입 완료")

    # Step 3: backfill — metadata, chunks, facts 생성 (reindex_chroma=False)
    print("=== Step 3: 지식 테이블 백필 ===")
    success = 0
    failed = 0
    for idx, doc in enumerate(a100_docs):
        try:
            analysis = db.query(AnalysisResult).filter(
                AnalysisResult.document_id == doc.id
            ).order_by(AnalysisResult.id.desc()).first()

            if not analysis:
                continue

            result = upsert_document_knowledge(
                db, doc,
                latest_analysis=analysis,
                reindex_chroma=False,  # Ollama 임베딩 안 함
            )
            db.commit()
            success += 1
            if success % 100 == 0 or success <= 3:
                print(f"   ├─ [{success}/{len(a100_docs)}] doc#{doc.id} → chunks={result.get('chunk_count',0)} facts={result.get('fact_count',0)}")
        except Exception as e:
            db.rollback()
            failed += 1
            if failed <= 5:
                print(f"   ❌ doc#{doc.id} 실패: {e}")

    db.close()
    print("===================================================================")
    print(f"🎉 보강 완료!")
    print(f"   ✅ 성공: {success}건")
    print(f"   ❌ 실패: {failed}건")
    print("===================================================================")


if __name__ == "__main__":
    main()
