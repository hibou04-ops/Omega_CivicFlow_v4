"""전체 1,073 PDF 파일 CJK 잔존 전수 검사"""
import sys, os, glob, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import fitz  # PyMuPDF
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings

report_dir = os.path.join(settings.UPLOAD_DIR, 'reports')
pdfs = sorted(glob.glob(os.path.join(report_dir, '*.pdf')))
total = len(pdfs)
print(f"═══ PDF CJK 전수 스캔 — {total}건 ═══")

contaminated = []
start = time.time()

for idx, pdf_path in enumerate(pdfs, 1):
    try:
        doc = fitz.open(pdf_path)
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()

        cn_chars = [c for c in full_text if '\u4e00' <= c <= '\u9fff']
        jp_chars = [c for c in full_text if '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff']

        if cn_chars or jp_chars:
            # 오염 컨텍스트 추출
            sample = ""
            for c in cn_chars[:3]:
                i = full_text.index(c)
                sample += f"  ...{full_text[max(0,i-10):i+15]}...\n"
            contaminated.append({
                "file": os.path.basename(pdf_path),
                "cn": len(cn_chars),
                "jp": len(jp_chars),
                "sample": sample.strip(),
            })
    except Exception as e:
        print(f"  ❌ {os.path.basename(pdf_path)}: {e}")

    if idx % 200 == 0 or idx == total:
        elapsed = time.time() - start
        rate = idx / max(elapsed, 0.1)
        print(f"  [{idx:>4}/{total}] {elapsed:.0f}s ({rate:.0f}/s) | 오염: {len(contaminated)}건")

print()
print("═" * 55)
if contaminated:
    print(f"  ❌ CJK 잔존 PDF: {len(contaminated)}건")
    for c in contaminated:
        print(f"    {c['file']} | CN={c['cn']} JP={c['jp']}")
        print(f"    {c['sample']}")
else:
    print(f"  ✅ 전체 {total}건 CLEAN — CJK 0건!")
print("═" * 55)
