import sqlite3
db = sqlite3.connect(r'C:\Users\hibou\Omega_CivicFlow_v4_DB\omega_civicflow.db')
total = db.execute('SELECT count(*) FROM documents').fetchone()[0]
print(f'DB 총: {total}')
statuses = db.execute('SELECT status, count(*) FROM documents GROUP BY status').fetchall()
for s, c in statuses:
    print(f'  {s}: {c}')
db.close()
