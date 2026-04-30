import sqlite3, os

db = sqlite3.connect(r'C:\Users\hibou\Omega_CivicFlow_v4_DB\omega_civicflow.db')
rows = db.execute('SELECT file_path FROM documents LIMIT 10').fetchall()
for r in rows:
    path = r[0]
    exists = os.path.exists(path) if path else False
    print(f'  {"✅" if exists else "❌"} {path}')

# 존재하는 파일 수
all_paths = db.execute('SELECT file_path FROM documents').fetchall()
exist_count = sum(1 for r in all_paths if r[0] and os.path.exists(r[0]))
print(f'\n존재: {exist_count} / {len(all_paths)}')
db.close()
