import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from database import SessionLocal
from models.models import Document, OcrText, AnalysisResult, DocumentMetadata, DocumentChunk, FinancialFact
db = SessionLocal()

total_docs = db.query(Document).count()
a100_docs = db.query(Document).filter(Document.file_path.contains('A100_Cloud')).count()
local_docs = total_docs - a100_docs

print("=== 문서 현황 ===")
print(f"전체 문서: {total_docs}")
print(f"  로컬 업로드: {local_docs}")
print(f"  A100 주입: {a100_docs}")

print()
print("=== 테이블별 레코드 수 ===")
print(f"ocr_texts: {db.query(OcrText).count()}")
print(f"analysis_results: {db.query(AnalysisResult).count()}")
print(f"document_metadata: {db.query(DocumentMetadata).count()}")
print(f"document_chunks: {db.query(DocumentChunk).count()}")
print(f"financial_facts: {db.query(FinancialFact).count()}")

# A100 문서 중 OCR이 있는 것
from sqlalchemy import exists
a100_with_ocr = db.query(Document).filter(
    Document.file_path.contains('A100_Cloud'),
    Document.id.in_(db.query(OcrText.document_id))
).count()
print(f"A100 문서 중 OCR 있는 것: {a100_with_ocr}")

# A100 문서 중 report_path 있는 것
a100_with_report = db.query(Document).filter(
    Document.file_path.contains('A100_Cloud'),
    Document.report_path.isnot(None)
).count()
print(f"A100 문서 중 PDF보고서 있는 것: {a100_with_report}")

# A100 문서 중 metadata 있는 것
a100_with_meta = db.query(Document).filter(
    Document.file_path.contains('A100_Cloud'),
    Document.id.in_(db.query(DocumentMetadata.document_id))
).count()
print(f"A100 문서 중 metadata 있는 것: {a100_with_meta}")

# A100 문서 중 chunks 있는 것
a100_with_chunks = db.query(Document).filter(
    Document.file_path.contains('A100_Cloud'),
    Document.id.in_(db.query(DocumentChunk.document_id))
).count()
print(f"A100 문서 중 document_chunks 있는 것: {a100_with_chunks}")

# A100 문서 중 financial_facts 있는 것
a100_with_facts = db.query(Document).filter(
    Document.file_path.contains('A100_Cloud'),
    Document.id.in_(db.query(FinancialFact.document_id))
).count()
print(f"A100 문서 중 financial_facts 있는 것: {a100_with_facts}")

# A100 analysis_results 샘플 확인
sample = db.query(AnalysisResult).join(
    Document, AnalysisResult.document_id == Document.id
).filter(Document.file_path.contains('A100_Cloud')).first()

if sample:
    summary = sample.summary or ""
    print()
    print("=== A100 분석결과 샘플 ===")
    print(f"summary 길이: {len(summary)}")
    print(f"summary 앞 300자: {summary[:300]}")
    print(f"category: {sample.category}")
    fm = sample.financial_metrics or ""
    print(f"financial_metrics: {fm[:100]}")
    print(f"raw_response type: {type(sample.raw_response)}")

db.close()
