"""Check DB and PDF for remaining 交換"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, '.')
from database import SessionLocal
from models.models import Document, AnalysisResult

db = SessionLocal()
for did in [1074, 1076]:
    ar = db.query(AnalysisResult).filter(
        AnalysisResult.document_id == did
    ).order_by(AnalysisResult.id.desc()).first()
    if not ar:
        continue
    raw = ar.raw_response
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except:
            pass
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except:
            pass
    raw_str = json.dumps(raw, ensure_ascii=False) if isinstance(raw, dict) else str(raw)

    cjk = [c for c in raw_str if '\u4e00' <= c <= '\u9fff']

    print(f'--- #{did} ---')
    print(f'  CJK in raw: {len(cjk)}')
    has_in_sum = '\u4ea4\u63db' in str(ar.summary or '')
    has_in_evi = '\u4ea4\u63db' in str(ar.evidence or '')
    print(f'  summary has: {has_in_sum}')
    print(f'  evidence has: {has_in_evi}')

    doc = db.query(Document).get(did)
    print(f'  report: {doc.report_path}')

    all_ars = db.query(AnalysisResult).filter(
        AnalysisResult.document_id == did
    ).all()
    print(f'  total AR records: {len(all_ars)}')
    for a in all_ars:
        rs = json.dumps(a.raw_response, ensure_ascii=False) if isinstance(a.raw_response, dict) else str(a.raw_response or '')
        cn = sum(1 for c in rs if '\u4e00' <= c <= '\u9fff')
        print(f'    AR#{a.id}: CJK={cn}')

db.close()
