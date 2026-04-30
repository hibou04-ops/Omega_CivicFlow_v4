import sqlite3, json, os, zipfile, re

db = sqlite3.connect(r'C:\Users\hibou\Omega_CivicFlow_v4_DB\omega_civicflow.db')
rows = db.execute('SELECT id, filename, file_path FROM documents').fetchall()
print(f'DB 문서: {len(rows)}건')

docs = []
errors = 0
for doc_id, filename, file_path in rows:
    if not file_path or not os.path.exists(file_path):
        errors += 1
        continue
    
    try:
        text = ""
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == '.zip':
            with zipfile.ZipFile(file_path, 'r') as zf:
                for name in zf.namelist():
                    try:
                        raw = zf.read(name)
                        for enc in ['utf-8', 'cp949', 'euc-kr', 'latin-1']:
                            try:
                                text += raw.decode(enc)
                                break
                            except:
                                continue
                    except:
                        continue
        else:
            # xml, html, txt 등 텍스트 파일
            for enc in ['utf-8', 'cp949', 'euc-kr', 'latin-1']:
                try:
                    with open(file_path, 'r', encoding=enc) as f:
                        text = f.read()
                    break
                except:
                    continue
        
        # 태그 제거
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'&[a-zA-Z]+;', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        if len(text) > 100:
            docs.append({
                'doc_id': doc_id,
                'filename': filename,
                'text': text,
                'text_len': len(text)
            })
            
        if len(docs) % 500 == 0 and len(docs) > 0:
            print(f'  진행: {len(docs)}건...')
            
    except Exception as e:
        errors += 1

print(f'추출 성공: {len(docs)}건, 실패: {errors}건')

out = r'C:\Users\hibou\Omega_CivicFlow_v4_DB\pending_docs_all.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(docs, f, ensure_ascii=False)
size = os.path.getsize(out)
print(f'저장: {out} ({size//1048576}MB)')
db.close()
