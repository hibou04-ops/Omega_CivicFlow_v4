"""
═══════════════════════════════════════════════════════════════════════════════
Phase 3: Embedding Pipeline — CPU Mode (bge-m3)
═══════════════════════════════════════════════════════════════════════════════

Deterministic embedding pipeline for pre-processed chunks (Phase 1+2 output).
CPU-only mode (RTX 5070 sm_120 PyTorch incompatibility workaround).

Flow:
  1. Load bge-m3 from HuggingFace with device=cpu
  2. Batch-process document_chunks from SQLite DB
  3. Generate 1024-dim embeddings via encode()
  4. Persist to ChromaDB omega_documents_v2 collection
  5. Update indexed_at timestamp in DB
  6. Checkpoint after each batch (resumption-safe)
  7. Final: validation metrics and timing report

Performance: ~284,149 chunks @ batch_size=8 = ~2-3 hours CPU
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import sys
import os
from collections import namedtuple

# CPU optimization - GENTLE MODE (low CPU usage)
os.environ["OMP_NUM_THREADS"] = "2"  # Reduced from 8 for less CPU load
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import torch
import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb
import time

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

CHECKPOINT_FILE = Path(__file__).parent / "phase3_embedding_checkpoint.json"
DB_PATH = r"C:\Users\hibou\Omega_CivicFlow_v4_DB\omega_civicflow.db"
CHROMA_PATH = r"C:\Users\hibou\Omega_CivicFlow_v4_DB\chroma_db"
COLLECTION_NAME = "omega_documents_v2"

EMBEDDING_MODEL = "BAAI/bge-m3"  # Multilingual, 1024-dim output
BATCH_SIZE = 4  # Reduced from 8 for gentle CPU usage
MAX_SEQ_LENGTH = 512  # bge-m3 recommendation
DEVICE = "cpu"
INTER_BATCH_DELAY_SEC = 0.5  # 500ms delay between batches

# Minimal ORM substitute
DocumentChunk = namedtuple("DocumentChunk", ["id", "document_id", "chunk_uid", "text", "created_at"])

# ═══════════════════════════════════════════════════════════════════════════════
# Checkpoint Management
# ═══════════════════════════════════════════════════════════════════════════════

class EmbeddingCheckpoint:
    """Manages Phase 3 resumption state."""

    def __init__(self, checkpoint_path: Path = CHECKPOINT_FILE):
        self.path = checkpoint_path
        self.data = self._load() if checkpoint_path.exists() else self._init()

    def _init(self) -> Dict[str, Any]:
        return {
            "schema_version": "4.0",
            "phase": "phase3_embedding",
            "model": EMBEDDING_MODEL,
            "device": DEVICE,
            "batch_size": BATCH_SIZE,
            "max_seq_length": MAX_SEQ_LENGTH,
            "started_at": None,
            "completed_at": None,
            "status": "pending",
            "last_processed_chunk_id": 0,
            "chunks_processed": 0,
            "chunks_total": 0,
            "chunks_failed": 0,
            "embeddings_stored": 0,
            "batches_completed": 0,
            "total_duration_sec": 0.0,
            "failed_chunks": [],
            "stats": {
                "mean_embedding_time_ms": 0.0,
                "model_load_time_sec": 0.0,
            }
        }

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"ERROR: Failed to load checkpoint: {e}")
            return self._init()

    def save(self):
        """Persist checkpoint to disk."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"ERROR: Failed to save checkpoint: {e}")

    def mark_started(self, total_chunks: int):
        self.data["started_at"] = datetime.now(timezone.utc).isoformat()
        self.data["status"] = "in_progress"
        self.data["chunks_total"] = total_chunks
        self.save()

    def mark_batch_complete(self, chunk_ids: list, embeddings_count: int, batch_time_sec: float):
        self.data["last_processed_chunk_id"] = max(chunk_ids) if chunk_ids else self.data["last_processed_chunk_id"]
        self.data["chunks_processed"] += len(chunk_ids)
        self.data["embeddings_stored"] += embeddings_count
        self.data["batches_completed"] += 1
        self.save()

    def mark_completed(self, total_duration_sec: float):
        self.data["completed_at"] = datetime.now(timezone.utc).isoformat()
        self.data["status"] = "completed"
        self.data["total_duration_sec"] = total_duration_sec
        self.save()

# ═══════════════════════════════════════════════════════════════════════════════
# Database Operations
# ═══════════════════════════════════════════════════════════════════════════════

def get_pending_chunks() -> List[DocumentChunk]:
    """Fetch all chunks not yet embedded."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, document_id, chunk_uid, text, created_at
            FROM document_chunks
            WHERE indexed_at IS NULL
            ORDER BY id
        """)
        rows = cursor.fetchall()
        conn.close()

        chunks = [DocumentChunk(*row) for row in rows]
        return chunks
    except Exception as e:
        print(f"ERROR: Failed to fetch pending chunks: {e}")
        return []

def update_indexed_timestamps(chunk_ids: List[int]) -> bool:
    """Mark chunks as indexed in DB."""
    if not chunk_ids:
        return True

    try:
        now_utc = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        placeholders = ",".join(["?" for _ in chunk_ids])
        cursor.execute(f"""
            UPDATE document_chunks
            SET indexed_at = ?
            WHERE id IN ({placeholders})
        """, [now_utc] + chunk_ids)

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"ERROR: Failed to update indexed_at: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# Embedding Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class EmbeddingPipeline:
    """Phase 3: Generate and persist embeddings."""

    def __init__(self, checkpoint: EmbeddingCheckpoint):
        self.checkpoint = checkpoint
        self.model = None
        self.collection = None

    def initialize(self) -> bool:
        """Load model and connect to ChromaDB."""
        try:
            print(f"\n[Phase 3] Initializing embedding pipeline...")
            print(f"  Device: {DEVICE}")
            print(f"  Model: {EMBEDDING_MODEL}")
            print(f"  Batch size: {BATCH_SIZE}")

            # Load model
            print("  Loading SentenceTransformer model...")
            model_start = datetime.now()
            self.model = SentenceTransformer(
                EMBEDDING_MODEL,
                device=DEVICE,
                trust_remote_code=True,
            )
            self.model.max_seq_length = MAX_SEQ_LENGTH
            model_load_time = (datetime.now() - model_start).total_seconds()
            print(f"  Model loaded in {model_load_time:.2f}s")
            self.checkpoint.data["stats"]["model_load_time_sec"] = model_load_time

            # Initialize ChromaDB
            print("  Connecting to ChromaDB...")
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            self.collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            collection_count = self.collection.count()
            print(f"  ChromaDB ready. Collection: {COLLECTION_NAME} (current: {collection_count} vectors)")

            return True

        except Exception as e:
            print(f"ERROR: Failed to initialize: {e}")
            return False

    def encode_batch(self, texts: list) -> Optional[np.ndarray]:
        """Generate embeddings for batch of texts."""
        try:
            # Use smaller internal batch size for gentler CPU usage
            embeddings = self.model.encode(
                texts,
                batch_size=2,  # Internal batch size (gentler than the outer batch_size)
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            return embeddings
        except Exception as e:
            print(f"ERROR: Encoding failed: {e}")
            return None

    def store_embeddings_batch(self, chunks: List[DocumentChunk], embeddings: np.ndarray) -> Tuple[int, list]:
        """Store embeddings in ChromaDB and update DB timestamps."""
        stored_count = 0
        failed_chunk_ids = []

        try:
            ids = []
            vectors = []
            metadatas = []
            documents = []

            for i, chunk in enumerate(chunks):
                chunk_id = f"chunk_{chunk.id}"
                ids.append(chunk_id)
                vectors.append(embeddings[i].tolist())
                metadatas.append({
                    "document_id": str(chunk.document_id),
                    "chunk_uid": chunk.chunk_uid,
                    "created_at": chunk.created_at if chunk.created_at else "",
                })
                documents.append(chunk.text[:1000])

            # Store to ChromaDB
            self.collection.upsert(
                ids=ids,
                embeddings=vectors,
                metadatas=metadatas,
                documents=documents,
            )

            # Update database timestamps
            chunk_ids_to_update = [chunk.id for chunk in chunks]
            success = update_indexed_timestamps(chunk_ids_to_update)

            if success:
                stored_count = len(chunks)
            else:
                failed_chunk_ids = chunk_ids_to_update

        except Exception as e:
            print(f"ERROR: Failed to store embeddings batch: {e}")
            failed_chunk_ids = [chunk.id for chunk in chunks]

        return stored_count, failed_chunk_ids

    def run(self) -> bool:
        """Execute full embedding pipeline."""
        if not self.initialize():
            return False

        start_time = datetime.now()

        try:
            # Fetch pending chunks
            pending_chunks = get_pending_chunks()
            if not pending_chunks:
                print("\nNo pending chunks to embed.")
                return True

            total_chunks = len(pending_chunks)
            print(f"\n[Phase 3] Processing {total_chunks:,} pending chunks...")
            self.checkpoint.mark_started(total_chunks)

            # Process in batches
            batch_count = 0
            total_embeddings = 0
            failed_chunks = []

            for batch_start in range(0, total_chunks, BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, total_chunks)
                batch_chunks = pending_chunks[batch_start:batch_end]
                batch_size = len(batch_chunks)

                batch_num = (batch_start // BATCH_SIZE) + 1
                total_batches = (total_chunks + BATCH_SIZE - 1) // BATCH_SIZE

                # Encode batch
                texts = [chunk.text for chunk in batch_chunks]
                batch_start_time = datetime.now()
                embeddings = self.encode_batch(texts)
                batch_duration = (datetime.now() - batch_start_time).total_seconds()

                if embeddings is None:
                    print(f"  ERROR: Batch {batch_num}/{total_batches} encoding failed, skipping...")
                    failed_chunks.extend([c.id for c in batch_chunks])
                    continue

                # Store embeddings
                stored_count, failed_ids = self.store_embeddings_batch(batch_chunks, embeddings)
                failed_chunks.extend(failed_ids)
                total_embeddings += stored_count

                # Progress report
                progress_pct = (batch_end / total_chunks) * 100
                print(f"  Batch {batch_num:4d}/{total_batches:4d} | "
                      f"{batch_end:7d}/{total_chunks:7d} ({progress_pct:5.1f}%) | "
                      f"{batch_duration:6.2f}s")

                # Checkpoint every batch
                self.checkpoint.mark_batch_complete(
                    [c.id for c in batch_chunks],
                    stored_count,
                    batch_duration,
                )

                # Gentle delay between batches to reduce CPU load
                if batch_count < total_batches - 1:
                    time.sleep(INTER_BATCH_DELAY_SEC)

                batch_count += 1

            # Final report
            total_duration = (datetime.now() - start_time).total_seconds()
            self.checkpoint.mark_completed(total_duration)

            print(f"\n[Phase 3] Embedding pipeline completed!")
            print(f"  Total duration: {total_duration:.2f}s ({total_duration/60:.1f}m)")
            print(f"  Embeddings stored: {total_embeddings:,} / {total_chunks:,}")
            print(f"  Batches completed: {batch_count}")
            print(f"  Failed chunks: {len(failed_chunks)}")

            if failed_chunks:
                self.checkpoint.data["failed_chunks"] = failed_chunks
                self.checkpoint.save()

            return len(failed_chunks) == 0

        except Exception as e:
            print(f"FATAL ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False

# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("Phase 3: Embedding Pipeline (CPU Mode + bge-m3)")
    print("=" * 80)

    checkpoint = EmbeddingCheckpoint()

    # Check for existing progress
    if checkpoint.data["status"] == "completed":
        print("\nPhase 3 already completed.")
        print(f"  Embeddings stored: {checkpoint.data['embeddings_stored']:,}")
        print(f"  Completed at: {checkpoint.data['completed_at']}")
        print(f"  Total duration: {checkpoint.data['total_duration_sec']:.2f}s ({checkpoint.data['total_duration_sec']/60:.1f}m)")
        sys.exit(0)

    if checkpoint.data["status"] == "in_progress":
        print("\nResuming interrupted Phase 3 embedding...")
        print(f"  Last processed chunk ID: {checkpoint.data['last_processed_chunk_id']}")
        print(f"  Progress: {checkpoint.data['chunks_processed']} / {checkpoint.data['chunks_total']}")

    pipeline = EmbeddingPipeline(checkpoint)
    success = pipeline.run()

    sys.exit(0 if success else 1)
