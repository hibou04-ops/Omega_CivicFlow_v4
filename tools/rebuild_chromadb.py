"""ChromaDB 완전 초기화 + 423건 정상 데이터로 재구축"""
import sys, os, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import settings

# 1) ChromaDB 완전 삭제
chroma_path = settings.CHROMADB_DIR
if os.path.exists(chroma_path):
    shutil.rmtree(chroma_path)
    print(f"✅ ChromaDB 삭제: {chroma_path}")
else:
    print(f"ChromaDB 경로 없음 (신규 생성)")

os.makedirs(chroma_path, exist_ok=True)

# 2) 재구축
from services.vector_service import rebuild_index_from_db
print("\n🔧 ChromaDB 재구축 시작 (423건)...")
result = rebuild_index_from_db()
print(f"\n{'='*50}")
print(f"  ✅ 재구축 완료!")
print(f"  문서: {result['documents']}건")
print(f"  LLM 청크: {result['llm_chunks']}개")
print(f"  OCR 청크: {result['ocr_chunks']}개")
print(f"  총 벡터: {result['total_chunks']}개")
print(f"{'='*50}")
