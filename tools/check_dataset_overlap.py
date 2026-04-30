"""DataSet 폴더와 DB 간 중복 확인"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from database import SessionLocal
from models.models import Document

DATASET = r"C:\Users\hibou\Desktop\DataSet"

db = SessionLocal()

# DB에 있는 파일명 세트
db_filenames = set()
for d in db.query(Document.filename).all():
    # 파일명에서 DART ID 추출 (DART_Px_회사명_숫자코드 패턴)
    fn = d.filename or ""
    # hex prefix 제거
    clean = re.sub(r'^[a-f0-9]+_', '', fn)
    # .zip.pdf → .zip 통일
    clean = clean.replace('.zip.pdf', '.zip')
    db_filenames.add(clean)
    db_filenames.add(fn)

# DataSet 파일 목록
dataset_files = []
for f in os.listdir(DATASET):
    if os.path.isfile(os.path.join(DATASET, f)):
        dataset_files.append(f)

# 중복 체크
overlapping = []
new_files = []

for f in dataset_files:
    clean = f.replace('.zip.pdf', '.zip')
    if f in db_filenames or clean in db_filenames:
        overlapping.append(f)
    else:
        new_files.append(f)

print(f"=== DataSet vs DB 비교 ===")
print(f"  DataSet 총 파일: {len(dataset_files)}")
print(f"  DB 기존 문서: {len(db_filenames)}")
print(f"  중복 (이미 DB에 있음): {len(overlapping)}")
print(f"  신규 (DB에 없음): {len(new_files)}")

# 신규 파일 크기
new_size = sum(os.path.getsize(os.path.join(DATASET, f)) for f in new_files)
print(f"  신규 파일 크기: {new_size / 1024 / 1024:.1f} MB")

# 신규 파일 유형 분류
p0 = sum(1 for f in new_files if '_P0_' in f)
p1 = sum(1 for f in new_files if '_P1_' in f)
p2 = sum(1 for f in new_files if '_P2_' in f)
p3 = sum(1 for f in new_files if '_P3_' in f)
p4 = sum(1 for f in new_files if '_P4_' in f)
print(f"\n  신규 파일 유형:")
print(f"    P0 (사업보고서): {p0}")
print(f"    P1 (외감): {p1}")
print(f"    P2 (분반기): {p2}")
print(f"    P3 (기타): {p3}")
print(f"    P4 (기타): {p4}")

db.close()
