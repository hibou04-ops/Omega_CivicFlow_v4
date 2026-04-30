"""QWEN 모델 CJK 오염률 분석"""
import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DB = r'omega_civicflow.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute('''
    SELECT ar.id, ar.document_id, ar.raw_response, ar.model_name, d.filename
    FROM analysis_results ar
    JOIN documents d ON d.id = ar.document_id
    WHERE d.status = 'analyzed'
''')
rows = cur.fetchall()

def count_cjk(text):
    if not text: return 0, 0, 0
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    hira = sum(1 for c in text if '\u3040' <= c <= '\u309f')
    kata = sum(1 for c in text if '\u30a0' <= c <= '\u30ff')
    return cn, hira, kata

def extract_field(raw, field):
    if not isinstance(raw, dict): return ''
    val = raw.get(field, '')
    if isinstance(val, str): return val
    if isinstance(val, list): return ' '.join(str(x) for x in val)
    if isinstance(val, dict): return json.dumps(val, ensure_ascii=False)
    return str(val) if val else ''

fields = ['summary', 'evidence', 'key_points', 'risk_notes', 'company_name']
stats = {f: {'total': 0, 'cn_docs': 0, 'jp_docs': 0, 'cn_chars': 0, 'jp_chars': 0} for f in fields}
overall_cn = 0
overall_jp = 0
total = len(rows)

for ar_id, doc_id, raw_resp, model, fname in rows:
    raw = {}
    if raw_resp:
        try:
            raw = json.loads(raw_resp) if isinstance(raw_resp, str) else raw_resp
            if isinstance(raw, str): raw = json.loads(raw)
        except: continue
    if not isinstance(raw, dict): continue

    doc_cn = False
    doc_jp = False

    for field in fields:
        text = extract_field(raw, field)
        if not text: continue
        stats[field]['total'] += 1
        cn, hira, kata = count_cjk(text)
        if cn > 0:
            stats[field]['cn_docs'] += 1
            stats[field]['cn_chars'] += cn
            doc_cn = True
        if (hira + kata) > 0:
            stats[field]['jp_docs'] += 1
            stats[field]['jp_chars'] += (hira + kata)
            doc_jp = True

    if doc_cn: overall_cn += 1
    if doc_jp: overall_jp += 1

conn.close()

clean = total - max(overall_cn, overall_jp)
lines = []
lines.append("=" * 65)
lines.append("  QWEN 모델 CJK 오염률 분석 (현재 DB — 후처리 적용 후)")
lines.append(f"  총 문서: {total}건")
lines.append("=" * 65)
lines.append("")
lines.append("  전체 오염률:")
lines.append(f"    중국어 포함: {overall_cn}/{total} ({overall_cn*100/max(total,1):.2f}%)")
lines.append(f"    일본어 포함: {overall_jp}/{total} ({overall_jp*100/max(total,1):.2f}%)")
lines.append(f"    클린:       {clean}/{total} ({clean*100/max(total,1):.2f}%)")
lines.append("")
lines.append("-" * 65)
lines.append("  필드별 오염률:")
lines.append("-" * 65)
header = f"  {'필드':<20} {'총건':>6} {'CN문서':>6} {'CN률':>7} {'JP문서':>6} {'JP률':>7} {'CN글자':>7} {'JP글자':>7}"
lines.append(header)
lines.append("  " + "-" * 63)

for field in fields:
    s = stats[field]
    t = max(s['total'], 1)
    row = f"  {field:<20} {s['total']:>6} {s['cn_docs']:>6} {s['cn_docs']*100/t:>6.2f}% {s['jp_docs']:>6} {s['jp_docs']*100/t:>6.2f}% {s['cn_chars']:>7} {s['jp_chars']:>7}"
    lines.append(row)

lines.append("")
lines.append("=" * 65)

output = "\n".join(lines)
print(output)
with open(r'tests\qwen_contamination_rate.txt', 'w', encoding='utf-8') as f:
    f.write(output)
