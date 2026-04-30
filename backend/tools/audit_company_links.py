import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal
from models.models import Document, DocumentMetadata
from services.chat_knowledge_service import normalize_company_name_for_storage


def _infer_filename_company(filename: str) -> str:
    import re

    for pattern in (r"DART_[^_]+_([^_]+)_", r"^[^_]+_DART_[^_]+_([^_]+)_"):
        match = re.search(pattern, filename or "")
        if match:
            return normalize_company_name_for_storage(match.group(1))
    return ""


def main() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(Document, DocumentMetadata)
            .outerjoin(DocumentMetadata, DocumentMetadata.document_id == Document.id)
            .order_by(Document.id.desc())
            .all()
        )

        total = len(rows)
        linked = 0
        missing = []
        mismatch = []

        for document, metadata in rows:
            company_name = (getattr(metadata, "company_name", "") or "").strip()
            company_norm = (getattr(metadata, "company_name_norm", "") or "").strip()
            inferred = _infer_filename_company(document.filename)

            if company_norm:
                linked += 1
            else:
                missing.append(
                    {
                        "id": document.id,
                        "filename": document.filename,
                        "inferred_from_filename": inferred,
                    }
                )

            if company_norm and inferred and company_norm != inferred and company_name != inferred:
                mismatch.append(
                    {
                        "id": document.id,
                        "filename": document.filename,
                        "company_name": company_name,
                        "company_name_norm": company_norm,
                        "inferred_from_filename": inferred,
                    }
                )

        print(json.dumps({"total": total, "linked": linked, "missing": len(missing), "mismatch": len(mismatch)}, ensure_ascii=False))
        print("missing_samples")
        for item in missing[:50]:
            print(json.dumps(item, ensure_ascii=False))
        print("mismatch_samples")
        for item in mismatch[:50]:
            print(json.dumps(item, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
