"""
DataSet 폴더의 파일을 DB에 있는 것 / 없는 것으로 분류
바탕화면에 폴더 생성:
  - DB에_있음/ (423건 중 매칭되는 것)
  - DB에_없음/ (나머지)
"""
import sys, os, re, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import SessionLocal
from models.models import Document

# 경로
DATASET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "DataSet")
DESKTOP = os.path.expanduser(r"~\Desktop")
OUT_EXISTS = os.path.join(DESKTOP, "DataSet_분류", "DB에_있음")
OUT_MISSING = os.path.join(DESKTOP, "DataSet_분류", "DB에_없음")

os.makedirs(OUT_EXISTS, exist_ok=True)
os.makedirs(OUT_MISSING, exist_ok=True)

# DB에서 현재 문서 파일명 가져오기
db = SessionLocal()
docs = db.query(Document).all()
db_filenames = set()
for doc in docs:
    fn = doc.filename or ""
    # 앞쪽 UUID 접두사 제거해서 원본 파일명 추출
    # 예: "0a16bcc8_DART_P0_한미반도체_2024..." → "DART_P0_한미반도체_2024..."
    clean = re.sub(r'^[a-f0-9]{8}_', '', fn)
    db_filenames.add(clean)
    db_filenames.add(fn)
db.close()

print(f"DB 문서: {len(docs)}건")
print(f"DB 파일명 패턴: {len(db_filenames)}개")

# DataSet 폴더 파일 순회
if not os.path.exists(DATASET_DIR):
    print(f"❌ DataSet 폴더 없음: {DATASET_DIR}")
    exit()

dataset_files = []
for root, dirs, files in os.walk(DATASET_DIR):
    for f in files:
        dataset_files.append(os.path.join(root, f))

print(f"DataSet 파일: {len(dataset_files)}개")

exists_count = 0
missing_count = 0

for filepath in dataset_files:
    basename = os.path.basename(filepath)
    
    # DB에 있는지 확인 (부분 매칭)
    found = False
    for db_fn in db_filenames:
        # 파일명이 포함되어 있으면 매칭
        if basename in db_fn or db_fn in basename:
            found = True
            break
        # DART 패턴 추출 비교
        m1 = re.search(r'DART_P\d+_.+?_\d{13,14}', basename)
        m2 = re.search(r'DART_P\d+_.+?_\d{13,14}', db_fn)
        if m1 and m2 and m1.group() == m2.group():
            found = True
            break
    
    if found:
        # 심볼릭 링크 대신 복사 (안전)
        dst = os.path.join(OUT_EXISTS, basename)
        if not os.path.exists(dst):
            shutil.copy2(filepath, dst)
        exists_count += 1
    else:
        dst = os.path.join(OUT_MISSING, basename)
        if not os.path.exists(dst):
            shutil.copy2(filepath, dst)
        missing_count += 1

print(f"\n{'='*50}")
print(f"  분류 완료!")
print(f"  DB에 있음: {exists_count}개 → {OUT_EXISTS}")
print(f"  DB에 없음: {missing_count}개 → {OUT_MISSING}")
print(f"{'='*50}")
