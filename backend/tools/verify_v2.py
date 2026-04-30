import sys
import os
import pathlib
import json
import logging
from typing import Dict, List

# 경로 설정
BACKEND_DIR = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import chromadb
from chromadb.config import Settings as ChromaSettings
from config import settings

from services.vector_service import cognitive_search

MANIFEST_FILE = BACKEND_DIR / "tools" / "reindex_v2_manifest.json"
REPORT_FILE = BACKEND_DIR / "tools" / "reindex_v2_report.json"
FAILED_LOG = BACKEND_DIR / "tools" / "reindex_v2_failed.json"
VERIFY_REPORT = BACKEND_DIR / "tools" / "reindex_v2_verify.json"
TARGET_COLLECTION = "omega_documents_v2"

logger = logging.getLogger("VerifyV2")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def verify_structural_integrity():
    logger.info("=" * 60)
    logger.info("무결성 및 유니크성 검증 시작")
    logger.info("=" * 60)
    
    # 1. 파일 점검
    if not MANIFEST_FILE.exists():
        logger.error("Manifest 파일을 찾을 수 없습니다.")
        return False
        
    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    total_docs = len(manifest)
    success_docs = [m for m in manifest if m["status"] == "success"]
    failed_docs = [m for m in manifest if m["status"] == "failed"]
    
    logger.info(f"Manifest 총 문서: {total_docs}")
    logger.info(f"파싱/업서트 성공: {len(success_docs)}")
    logger.info(f"파싱/업서트 실패: {len(failed_docs)}")
    
    # 2. ChromaDB 검증
    try:
        client = chromadb.PersistentClient(
            path=settings.CHROMADB_DIR,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        collection = client.get_collection(TARGET_COLLECTION)
    except Exception as e:
        logger.error(f"ChromaDB `{TARGET_COLLECTION}` 컬렉션 접근 실패: {e}")
        return False
        
    total_chunks = collection.count()
    logger.info(f"ChromaDB 총 등록된 Chunk 수: {total_chunks}")
    
    # 랜덤 샘플링으로 빈 메타데이터 확인 (비용 고려하여 앞에서 10건만 체크)
    sample_data = collection.peek(limit=50)
    empty_chunks = 0
    missing_meta = 0
    
    if sample_data and "documents" in sample_data and sample_data["documents"]:
        for doc, meta in zip(sample_data["documents"], sample_data["metadatas"]):
            if not doc or not str(doc).strip():
                empty_chunks += 1
            if not meta or "doc_id" not in meta or "sub_type" not in meta:
                missing_meta += 1
    
    logger.info(f"샘플(50건) 빈 Chunk 수: {empty_chunks}건")
    logger.info(f"샘플(50건) 필수 Meta 누락: {missing_meta}건")
    
    verify_results = {
        "manifest_total": total_docs,
        "manifest_success": len(success_docs),
        "manifest_failed": len(failed_docs),
        "chroma_total_chunks": total_chunks,
        "sample_empty_chunks": empty_chunks,
        "sample_missing_meta": missing_meta,
        "passed_integrity": (empty_chunks == 0 and missing_meta == 0)
    }
    return verify_results


def smoke_test_search():
    logger.info("\n" + "=" * 60)
    logger.info("검색 스모크 테스트 (Smoke Test) 시작")
    logger.info("=" * 60)
    
    test_queries = [
        "단기차입금 현황 및 유동성 리스크",
        "영업활동 현금흐름 요약",
        "우발부채 및 소송 현황",
        "자금조달 목적 (채무상환, 운영자금)",
        "감사의견 계속기업 관련 사항"
    ]
    
    smoke_results = []
    
    for query in test_queries:
        logger.info(f"\n[Q] {query}")
        
        # vector_service의 _get_collection에서 대상을 바꾸려면, 임시 몽키패치를 하거나
        # 여기서는 하드코딩해서 바로 _collection을 override하고 진행
        try:
            import services.vector_service as vs
            coll = vs._get_collection(TARGET_COLLECTION)
            vs._collection = coll
            
            results = vs.cognitive_search(query=query, top_k=3)
            
            summary = []
            for i, r in enumerate(results, 1):
                company = r.get("company", "-")
                score = r.get("composite_score", 0.0)
                pareto = r.get("pareto", False)
                head = (r.get("chunk", "")[:60]).replace("\n", " ") + "..."
                
                logger.info(f"  {i}. [회사: {company}] [Score: {score:.4f}] [Pareto: {pareto}] {head}")
                summary.append({"company": company, "score": score, "pareto": pareto})
                
            smoke_results.append({
                "query": query,
                "found_count": len(results),
                "top_results": summary
            })
            
        except Exception as e:
            logger.error(f"  검색 실패: {e}")
            smoke_results.append({"query": query, "error": str(e)})

    return smoke_results

def run_verify():
    res1 = verify_structural_integrity()
    res2 = smoke_test_search()
    
    final_report = {
        "integrity": res1,
        "smoke_tests": res2
    }
    
    with open(VERIFY_REPORT, "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)
        
    logger.info("\n" + "=" * 60)
    logger.info("검증 리포트 저장 완료: tools/reindex_v2_verify.json")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_verify()
