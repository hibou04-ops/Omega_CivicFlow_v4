import sys
import os
import pathlib
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

# 경로 설정
BACKEND_DIR = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 필수 모듈 임포트
from tools.dart_batch_pipeline import DartXmlExtractor, ExaonePreprocessor
import services.vector_service as vector_service

DATASET_DIR = pathlib.Path(os.environ.get("OMEGA_DATASET_DIR", str(BACKEND_DIR.parent / "DataSet")))
REPORT_FILE = BACKEND_DIR / "tools" / "reindex_v2_report.json"
MANIFEST_FILE = BACKEND_DIR / "tools" / "reindex_v2_manifest.json"
FAILED_LOG = BACKEND_DIR / "tools" / "reindex_v2_failed.json"

TARGET_COLLECTION = "omega_documents_v2"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(BACKEND_DIR / "tools" / "reindex_v2_run.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("ReindexV2")


def build_manifest() -> List[Dict]:
    """전체 원천 문서(Manifest) 생성"""
    manifest = []
    
    all_files = [
        f for f in DATASET_DIR.iterdir()
        if f.is_file() and (f.suffix == ".zip" or f.name.endswith(".zip.pdf"))
    ]
    
    # 안정적인 정렬 (P0 → P1 → P2 순)
    all_files.sort(key=lambda f: (
        0 if "_P0_" in f.name else (1 if "_P1_" in f.name else 2),
        f.name
    ))

    extractor = DartXmlExtractor()
    for f in all_files:
        meta = extractor._parse_filename_metadata(f.name)
        manifest.append({
            "source_file": f.name,
            "source_path": str(f),
            "doc_id": abs(hash(f.name)) % (10 ** 9),
            "company_name": meta.get("company", ""),
            "filing_type": meta.get("report_type", ""),
            "status": "pending",  # pending, success, failed
            "chunks_upserted": 0,
            "error_reason": ""
        })
    
    with open(MANIFEST_FILE, "w", encoding="utf-8") as out:
        json.dump(manifest, out, ensure_ascii=False, indent=2)
    
    return manifest


def _save_state(stats: Dict, manifest: List[Dict]):
    with open(REPORT_FILE, "w", encoding="utf-8") as out:
        json.dump(stats, out, ensure_ascii=False, indent=2)
    
    with open(MANIFEST_FILE, "w", encoding="utf-8") as out:
        json.dump(manifest, out, ensure_ascii=False, indent=2)

    fails = [m for m in manifest if m["status"] == "failed"]
    with open(FAILED_LOG, "w", encoding="utf-8") as out:
        json.dump(fails, out, ensure_ascii=False, indent=2)


def run_reindex_v2():
    logger.info("=" * 60)
    logger.info(f"Omega CivicFlow - Reindexing V2 START ({TARGET_COLLECTION})")
    logger.info("=" * 60)

    # 매니페스트 초기화 혹은 로드
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, "r", encoding="utf-8") as inf:
            manifest = json.load(inf)
        logger.info(f"기존 Manifest 로드 완료 (총 {len(manifest)}건)")
    else:
        manifest = build_manifest()
        logger.info(f"신규 Manifest 생성 완료 (총 {len(manifest)}건)")

    stats = {
        "start_time": datetime.now().isoformat(),
        "total_documents": len(manifest),
        "parsed_success": 0,
        "parsed_failed": 0,
        "total_chunks_upserted": 0,
        "target_collection": TARGET_COLLECTION
    }
    
    # 이전 통계 스냅샷 유지
    if REPORT_FILE.exists():
        with open(REPORT_FILE, "r", encoding="utf-8") as inf:
            old_stats = json.load(inf)
            stats["parsed_success"] = old_stats.get("parsed_success", 0)
            stats["parsed_failed"] = old_stats.get("parsed_failed", 0)
            stats["total_chunks_upserted"] = old_stats.get("total_chunks_upserted", 0)

    extractor = DartXmlExtractor()
    preprocessor = ExaonePreprocessor()

    t_start = time.time()
    for idx, item in enumerate(manifest, 1):
        if item["status"] == "success":
            continue

        filename = item["source_file"]
        zip_path = pathlib.Path(item["source_path"])
        doc_id = item["doc_id"]

        logger.info(f"[{idx}/{len(manifest)}] 처리 중: {filename}")

        try:
            raw_text, metadata = extractor.extract_from_zip(zip_path)
            
            if not raw_text or len(raw_text) < 100:
                item["status"] = "failed"
                item["error_reason"] = "Text extraction failed or too short"
                stats["parsed_failed"] += 1
                logger.warning(f"  ⚠ 텍스트 추출 실패: {filename}")
                continue

            clean_text = preprocessor.preprocess(raw_text, metadata)
            if not clean_text or len(clean_text) < 100:
                item["status"] = "failed"
                item["error_reason"] = "Text too short after preprocessing"
                stats["parsed_failed"] += 1
                logger.warning(f"  ⚠ 전처리 후 텍스트 부족: {filename}")
                continue

            # 인덱싱 (기존 vector_service 활용)
            count = vector_service.index_document(
                doc_id=doc_id,
                filename=metadata.get("filename", ""),
                text=clean_text,
                category=metadata.get("report_type", ""),
                company=metadata.get("company", ""),
                source="dart_xml",
                clear_existing=True,
                filing_date=metadata.get("report_date", ""),
                period=metadata.get("period", ""),
                collection_name=TARGET_COLLECTION
            )

            if count > 0:
                item["status"] = "success"
                item["chunks_upserted"] = count
                stats["parsed_success"] += 1
                stats["total_chunks_upserted"] += count
                logger.info(f"  └─ 성공: {count}청크 업서트")
            else:
                item["status"] = "failed"
                item["error_reason"] = "Upsert returned 0 chunks"
                stats["parsed_failed"] += 1
                logger.warning(f"  ⚠ 업서트 실패 (0 chunks): {filename}")

        except Exception as e:
            item["status"] = "failed"
            item["error_reason"] = str(e)
            stats["parsed_failed"] += 1
            logger.error(f"  ✗ 시스템 에러 ({filename}): {e}")

        if idx % 50 == 0:
            _save_state(stats, manifest)
            elapsed = time.time() - t_start
            logger.info(f"--- 중간 저장 완료 ({idx}/{len(manifest)}, 경과: {elapsed:.1f}초) ---")

    _save_state(stats, manifest)
    elapsed_total = time.time() - t_start
    
    logger.info("=" * 60)
    logger.info(f"재인덱싱 전체 완료! 소요시간: {elapsed_total:.1f}초")
    logger.info(f"총 문서: {stats['total_documents']}")
    logger.info(f"성공: {stats['parsed_success']} | 실패: {stats['parsed_failed']}")
    logger.info(f"총 청크: {stats['total_chunks_upserted']}")
    logger.info("=" * 60)

if __name__ == "__main__":
    run_reindex_v2()
