import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
sys.stdout.reconfigure(encoding='utf-8')

# Services
svc_dir = 'services'
svcs = [f for f in os.listdir(svc_dir) if f.endswith('.py') and f != '__init__.py']
print(f'Services: {len(svcs)}')
for s in sorted(svcs): print(f'  {s}')

# Routers
rt_dir = 'routers'
rts = [f for f in os.listdir(rt_dir) if f.endswith('.py') and f != '__init__.py']
print(f'\nRouters: {len(rts)}')
for r in sorted(rts): print(f'  {r}')

# Frontend pages
fe_dir = os.path.join('..', 'frontend', 'src', 'pages')
if os.path.exists(fe_dir):
    pages = [f for f in os.listdir(fe_dir) if f.endswith('.jsx') or f.endswith('.tsx')]
    print(f'\nPages: {len(pages)}')
    for p in sorted(pages): print(f'  {p}')

# Frontend components
comp_dir = os.path.join('..', 'frontend', 'src', 'components')
if os.path.exists(comp_dir):
    comps = [f for f in os.listdir(comp_dir) if f.endswith('.jsx') or f.endswith('.tsx')]
    print(f'\nComponents: {len(comps)}')
    for c in sorted(comps): print(f'  {c}')

# Tables
from database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
tables = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")).fetchall()
print(f'\nTables: {len(tables)}')
for t in tables: print(f'  {t[0]}')

# Doc stats
from models.models import Document
total = db.query(Document).count()
analyzed = db.query(Document).filter(Document.status=='analyzed').count()
ocr_done = db.query(Document).filter(Document.status=='ocr_done').count()
print(f'\nDocs: total={total} analyzed={analyzed} ocr_done={ocr_done}')
db.close()
