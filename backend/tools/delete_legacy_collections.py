# -*- coding: utf-8 -*-
"""
Legacy collection deletion + audit + validation script.
Deletes omega_documents and omega_document_chunks (contaminated legacy).
Preserves audit evidence. Validates clean path.
"""
import sys
import json
from pathlib import Path

# --- Add backend to path ---
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb
from chromadb.config import Settings as ChromaSettings

CHROMA_PATH = "C:/Users/hibou/Omega_CivicFlow_v4_DB/chroma_db"
LEGACY_COLLECTIONS = ["omega_documents", "omega_document_chunks"]
CLEAN_COLLECTION = "omega_documents_v2"
DEAD_COLLECTION = "omega_document_chunks_v2"

def main():
    client = chromadb.PersistentClient(
        path=CHROMA_PATH,
        settings=ChromaSettings(anonymized_telemetry=False),
    )

    # --- Phase 1: Audit (preserve evidence) ---
    print("=" * 60)
    print("PHASE 1: Legacy Collection Audit")
    print("=" * 60)
    audit = {}
    for name in LEGACY_COLLECTIONS + [CLEAN_COLLECTION, DEAD_COLLECTION]:
        try:
            col = client.get_collection(name)
            count = col.count()
            audit[name] = {"count": count, "status": "exists"}
            print(f"  {name}: {count} documents")
        except Exception as e:
            audit[name] = {"count": 0, "status": f"not_found: {e}"}
            print(f"  {name}: NOT FOUND ({e})")

    # Save audit to file
    audit_path = Path(__file__).parent / "legacy_audit_evidence.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
    print(f"\n  Audit saved to: {audit_path}")

    # --- Phase 2: Delete legacy collections ---
    print("\n" + "=" * 60)
    print("PHASE 2: Deleting Legacy Contaminated Collections")
    print("=" * 60)
    for name in LEGACY_COLLECTIONS:
        try:
            client.delete_collection(name)
            print(f"  DELETED: {name}")
        except Exception as e:
            print(f"  SKIP (already gone?): {name} — {e}")

    # Also delete the dead empty collection
    try:
        client.delete_collection(DEAD_COLLECTION)
        print(f"  DELETED (dead/empty): {DEAD_COLLECTION}")
    except Exception as e:
        print(f"  SKIP: {DEAD_COLLECTION} — {e}")

    # --- Phase 3: Verify clean state ---
    print("\n" + "=" * 60)
    print("PHASE 3: Post-Deletion Verification")
    print("=" * 60)
    remaining = client.list_collections()
    print(f"  Remaining collections: {len(remaining)}")
    for col in remaining:
        print(f"    {col.name}: {col.count()} documents")

    # Verify clean collection is intact
    try:
        clean = client.get_collection(CLEAN_COLLECTION)
        clean_count = clean.count()
        print(f"\n  ✓ CLEAN collection '{CLEAN_COLLECTION}' is active with {clean_count} documents")

        # Quick metadata key verification
        sample = clean.get(limit=1, include=["metadatas"])
        if sample and sample["metadatas"]:
            keys = sorted(sample["metadatas"][0].keys())
            print(f"  ✓ Metadata keys: {keys}")
            has_company_name = "company_name" in keys
            print(f"  ✓ Has 'company_name' key: {has_company_name}")
        
        # Verify legacy collections are gone
        for name in LEGACY_COLLECTIONS + [DEAD_COLLECTION]:
            try:
                client.get_collection(name)
                print(f"  ✗ WARNING: '{name}' still exists!")
            except Exception:
                print(f"  ✓ '{name}' confirmed deleted")
    except Exception as e:
        print(f"\n  ✗ CLEAN collection ERROR: {e}")

    print("\n" + "=" * 60)
    print("Legacy DB cleanup complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
