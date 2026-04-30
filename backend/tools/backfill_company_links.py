import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal
from models.models import AnalysisResult, CompanyProfile, Document, DocumentMetadata, OcrText
from services.chat_knowledge_service import _filename_company_candidates, _guess_company_name, normalize_company_name_for_storage


def main() -> None:
    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .order_by(Document.id.asc())
            .all()
        )

        updated = 0
        unresolved = 0
        for doc in docs:
            metadata = db.query(DocumentMetadata).filter(DocumentMetadata.document_id == doc.id).first()
            latest_analysis = (
                db.query(AnalysisResult)
                .filter(AnalysisResult.document_id == doc.id)
                .order_by(AnalysisResult.id.desc())
                .first()
            )
            ocr_rows = (
                db.query(OcrText)
                .filter(OcrText.document_id == doc.id)
                .order_by(OcrText.id.asc())
                .all()
            )

            company_name, source, confidence = _guess_company_name(db, doc, latest_analysis, ocr_rows)
            if not company_name:
                unresolved += 1
                continue

            metadata = metadata or DocumentMetadata(document_id=doc.id)
            metadata.company_name = company_name
            metadata.company_name_norm = normalize_company_name_for_storage(company_name)
            metadata.source_kind = source
            metadata.extraction_confidence = confidence
            metadata.metadata_json = {
                **(metadata.metadata_json or {}),
                "_company_link": {
                    "source": source,
                    "confidence": confidence,
                    "filename_candidates": _filename_company_candidates(doc.filename),
                },
            }
            db.add(metadata)

            if metadata.company_name_norm:
                profile = (
                    db.query(CompanyProfile)
                    .filter(CompanyProfile.company_name_norm == metadata.company_name_norm)
                    .first()
                    or CompanyProfile(company_name_norm=metadata.company_name_norm)
                )
                profile.display_name = metadata.company_name
                if metadata.corp_code:
                    profile.corp_code = metadata.corp_code
                db.add(profile)

            updated += 1

        db.commit()
        print(f"updated={updated}")
        print(f"unresolved={unresolved}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
