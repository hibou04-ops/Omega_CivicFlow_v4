# Phase 1-B: ocr_texts가 비어있는 문서에 DartXmlExtractor로 텍스트 채우기
# 이미 DB에 등록된 1,700개 문서의 텍스트를 추출하여 업데이트

import sys
import os
import json
import time
import logging
import pathlib
from datetime import datetime

BACKEND_DIR = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "tools"))

DATASET_DIR = pathlib.Path(r"C:\Users\hibou\Desktop\DataSet")
LOG_FILE = BACKEND_DIR / "tools" / "batch_fill_text.log"
CHECKPOINT_FILE = BACKEND_DIR / "tools" / "batch_fill_checkpoint.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("BatchFillText")


def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"completed_ids": [], "stats": {"success": 0, "failed": 0, "total_chars": 0}}


def save_checkpoint(data):
    CHECKPOINT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    logger.info("=" * 60)
    logger.info("Batch Fill Text - DartXmlExtractor + ExaonePreprocessor")
    logger.info(f"Start: {datetime.now()}")
    logger.info("=" * 60)

    from database import SessionLocal
    from models.models import Document, OcrText
    from dart_batch_pipeline import DartXmlExtractor, ExaonePreprocessor

    db = SessionLocal()
    extractor = DartXmlExtractor()
    preprocessor = ExaonePreprocessor()

    # ocr_texts가 비어있거나 텍스트가 없는 문서 찾기
    empty_docs = db.query(Document).filter(Document.status == "ocr_done").all()
    targets = []
    for doc in empty_docs:
        ocr = db.query(OcrText).filter(OcrText.document_id == doc.id).first()
        if ocr and (not ocr.cleaned_text or len(ocr.cleaned_text.strip()) == 0):
            targets.append(doc)
        elif not ocr:
            targets.append(doc)

    logger.info(f"Empty text documents: {len(targets)}")

    # DataSet 파일 인덱스 (접수번호 -> 파일 경로)
    import re
    ds_index = {}
    for f in DATASET_DIR.iterdir():
        if f.is_file():
            m = re.search(r'(\d{14})', f.name)
            if m:
                ds_index[m.group(1)] = f

    logger.info(f"DataSet index: {len(ds_index)} files")

    ckpt = load_checkpoint()
    completed_set = set(ckpt["completed_ids"])
    t_start = time.time()
    total = len(targets)

    for idx, doc in enumerate(targets, 1):
        if doc.id in completed_set:
            continue

        # 접수번호로 원본 파일 찾기
        m = re.search(r'(\d{14})', doc.filename)
        if not m or m.group(1) not in ds_index:
            logger.warning(f"[{idx}/{total}] No source file for: {doc.filename}")
            ckpt["stats"]["failed"] += 1
            continue

        src_path = ds_index[m.group(1)]
        logger.info(f"[{idx}/{total}] doc #{doc.id} {doc.filename}")

        try:
            # DartXmlExtractor로 텍스트 추출
            raw_text, metadata = extractor.extract_from_zip(src_path)

            if not raw_text or len(raw_text) < 50:
                logger.warning(f"  Text too short: {len(raw_text) if raw_text else 0}")
                ckpt["stats"]["failed"] += 1
                ckpt["completed_ids"].append(doc.id)
                continue

            # ExaonePreprocessor로 정제
            cleaned = preprocessor.preprocess(raw_text, metadata)
            if not cleaned:
                cleaned = raw_text

            # ocr_texts 업데이트
            ocr = db.query(OcrText).filter(OcrText.document_id == doc.id).first()
            if ocr:
                ocr.raw_text = raw_text[:50000]
                ocr.cleaned_text = cleaned[:50000]
                ocr.confidence = 0.95
            else:
                from models.models import Page
                page = db.query(Page).filter(Page.document_id == doc.id).first()
                if not page:
                    page = Page(document_id=doc.id, page_number=1, image_path=doc.file_path)
                    db.add(page)
                    db.flush()
                ocr = OcrText(
                    document_id=doc.id, page_id=page.id,
                    raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95,
                )
                db.add(ocr)

            db.commit()

            text_len = len(cleaned)
            logger.info(f"  -> {text_len:,} chars (raw: {len(raw_text):,})")

            ckpt["completed_ids"].append(doc.id)
            ckpt["stats"]["success"] += 1
            ckpt["stats"]["total_chars"] += text_len

        except Exception as e:
            logger.error(f"  FAILED: {e}", exc_info=True)
            ckpt["stats"]["failed"] += 1
            ckpt["completed_ids"].append(doc.id)
            try:
                db.rollback()
            except Exception:
                pass

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
    logger.info(f"DONE! OK: {ckpt['stats']['success']} | FAIL: {ckpt['stats']['failed']}")
    logger.info(f"Total chars: {ckpt['stats']['total_chars']:,}")
    logger.info(f"Time: {elapsed:.0f}s ({elapsed/3600:.1f}h)")
    logger.info("=" * 60)
    db.close()


if __name__ == "__main__":
    main()
