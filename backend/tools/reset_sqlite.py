# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from models.models import Document, CompanyProfile

def reset_db():
    db = SessionLocal()
    try:
        count = db.query(Document).count()
        print(f"Deleting {count} documents from SQLite db...")
        db.query(Document).delete()
        db.query(CompanyProfile).delete() # Also clear cached profiles
        db.commit()
        print("SQLite documents and associated metadata completely wiped.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    reset_db()
