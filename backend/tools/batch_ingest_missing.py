# DataSet에서 DB에 없는 파일만 찾아서 전처리(DB등록 + OCR + 텍스트추출)만 실행
# LLM 분석 / 임베딩 / 청킹은 별도 단계에서 전체 3,135개 대상으로 진행

import sys
import os
import re
import shutil
import json
import time
import logging
import pathlib
import uuid
from datetime import datetime

BACKEND_DIR = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

DATASET_DIR = pathlib.Path(r"C:\Users\hibou\Desktop\DataSet")
CHECKPOINT_FILE = BACKEND_DIR / "tools" / "batch_ingest_checkpoint.json"
LOG_FILE = BACKEND_DIR / "tools" / "batch_ingest.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("BatchIngest")


def extract_receipt(name):
    m = re.search(r'(\d{14})', name)
    return m.group(1) if m else None


def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"completed": [], "failed": [], "stats": {"success": 0, "failed": 0, "total_chars": 0}}


def save_checkpoint(data):
    CHECKPOINT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    logger.info("=" * 60)
    logger.info("Batch Ingest - Phase 1: Preprocessing Only")
    logger.info("(DB Register + OCR + Text Extract, NO LLM/Embedding)")
    logger.info(f"Start: {datetime.now()}")
    logger.info("=" * 60)

    from database import SessionLocal
    from models.models import Document, Page, OcrText
    from services.ocr_service import OcrEngine
    from config import settings
    from pathlib import Path

    db = SessionLocal()
    ocr_engine = OcrEngine()
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 1. DB에 이미 있는 접수번호 수집
    existing_receipts = set()
    for (fn,) in db.query(Document.filename).all():
        r = extract_receipt(fn)
        if r:
            existing_receipts.add(r)
    logger.info(f"DB existing: {len(existing_receipts)} receipts")

    # 2. 미처리 파일 수집
    all_files = sorted([
        f for f in DATASET_DIR.iterdir()
        if f.is_file() and (f.suffix == ".zip" or f.name.endswith(".zip.pdf"))
    ])
    missing_files = [f for f in all_files if extract_receipt(f.name) and extract_receipt(f.name) not in existing_receipts]
    logger.info(f"DataSet: {len(all_files)} total, {len(missing_files)} missing")

    if not missing_files:
        logger.info("Nothing to process!")
        db.close()
        return

    # 3. 체크포인트
    ckpt = load_checkpoint()
    completed_set = set(ckpt["completed"])

    t_start = time.time()
    total = len(missing_files)

    for idx, src_path in enumerate(missing_files, 1):
        filename = src_path.name

        if filename in completed_set:
            continue

        logger.info(f"[{idx}/{total}] {filename}")

        try:
            # A. 파일 복사 -> uploads
            safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
            dest_path = os.path.join(settings.UPLOAD_DIR, safe_name)
            shutil.copy2(str(src_path), dest_path)

            # B. Document 등록
            if filename.endswith(".zip.pdf"):
                file_type = "pdf"
            elif filename.endswith(".zip"):
                file_type = "zip"
            else:
                file_type = filename.rsplit(".", 1)[-1].lower()

            doc = Document(
                user_id=1,
                filename=filename,
                file_path=dest_path,
                file_type=file_type,
                file_size=os.path.getsize(dest_path),
                status="uploaded",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            # C. OCR / 텍스트 추출
            full_text = ""

            if file_type == "pdf":
                page_dir = upload_dir / f"pages_{doc.id}"
                page_dir.mkdir(parents=True, exist_ok=True)
                ocr_results = ocr_engine.extract_text_from_pdf(dest_path, str(page_dir))

                all_text_parts = []
                for page_num, text, confidence in ocr_results:
                    page = Page(document_id=doc.id, page_number=page_num,
                                image_path=str(page_dir / f"page_{page_num}.png"))
                    db.add(page)
                    db.flush()
                    cleaned = ocr_engine.clean_text(text)
                    ocr_text = OcrText(
                        document_id=doc.id, page_id=page.id,
                        raw_text=text, cleaned_text=cleaned, confidence=confidence,
                    )
                    db.add(ocr_text)
                    all_text_parts.append(cleaned)

                full_text = "\n\n".join(all_text_parts)

            elif file_type == "zip":
                from services.dart_file_parser import extract_text_from_dart_zip
                with open(dest_path, "rb") as f:
                    raw_bytes = f.read()
                raw_text = extract_text_from_dart_zip(raw_bytes, filename)
                if not raw_text:
                    raw_text = ""
                cleaned = ocr_engine.clean_text(raw_text)
                page = Page(document_id=doc.id, page_number=1, image_path=dest_path)
                db.add(page)
                db.flush()
                ocr_text = OcrText(
                    document_id=doc.id, page_id=page.id,
                    raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95,
                )
                db.add(ocr_text)
                full_text = cleaned

            doc.status = "ocr_done"
            db.commit()

            text_len = len(full_text)
            logger.info(f"  -> doc #{doc.id} | {file_type} | {text_len:,} chars")

            ckpt["completed"].append(filename)
            ckpt["stats"]["success"] += 1
            ckpt["stats"]["total_chars"] += text_len

        except Exception as e:
            logger.error(f"  FAILED: {e}", exc_info=True)
            ckpt["failed"].append(filename)
            ckpt["stats"]["failed"] += 1
            try:
                db.rollback()
            except Exception:
                pass

        # 체크포인트 (50개마다)
        if idx % 50 == 0:
            save_checkpoint(ckpt)
            elapsed = time.time() - t_start
            rate = idx / elapsed if elapsed > 0 else 0
            eta = (total - idx) / rate if rate > 0 else 0
            logger.info(
                f"  --- Progress: {idx}/{total} ({idx*100//total}%) | "
                f"OK: {ckpt['stats']['success']} | FAIL: {ckpt['stats']['failed']} | "
                f"Elapsed: {elapsed:.0f}s | ETA: {eta:.0f}s ---"
            )

    save_checkpoint(ckpt)
    elapsed = time.time() - t_start

    logger.info("=" * 60)
    logger.info(f"Phase 1 DONE!")
    logger.info(f"Success: {ckpt['stats']['success']} | Failed: {ckpt['stats']['failed']}")
    logger.info(f"Total chars extracted: {ckpt['stats']['total_chars']:,}")
    logger.info(f"Time: {elapsed:.0f}s ({elapsed/3600:.1f}h)")
    logger.info("=" * 60)

    db.close()


if __name__ == "__main__":
    main()
