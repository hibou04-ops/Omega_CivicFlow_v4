"""
═══════════════════════════════════════════════════════════════════════════════
Phase 3: Embedding Pipeline — A100 40GB GPU Optimized
═══════════════════════════════════════════════════════════════════════════════

Deterministic embedding pipeline for pre-processed chunks (Phase 1+2 output).
A100 40GB optimized: batch_size=64, max_seq_length=512, bge-m3 model.

Expected runtime: 10-15 minutes for 284,149 chunks
Memory usage: ~35GB (safe on A100 40GB)

Setup:
  1. Deploy on RunPod/Lambda Labs with A100 40GB GPU + 64GB RAM
  2. Upload database file or mount via NFS
  3. Run this script
  4. Download results back to local machine

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

# GPU optimization for A100
os.environ["OMP_NUM_THREADS"] = "8"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"

import torch
import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration — MODIFY THESE FOR YOUR ENVIRONMENT
# ═══════════════════════════════════════════════════════════════════════════════

# Database path (on A100 GPU instance — mount or upload your database here)
DB_PATH = "/root/omega_civicflow.db"  # Modify this path for your deployment
CHROMA_PATH = "/root/chroma_db"  # Modify for your deployment

CHECKPOINT_FILE = Path("/root/phase3_embedding_checkpoint.json")
COLLECTION_NAME = "omega_documents_v2"

EMBEDDING_MODEL = "BAAI/bge-m3"
BATCH_SIZE = 64  # A100 40GB can handle large batches efficiently
MAX_SEQ_LENGTH = 512
DEVICE = "cuda:0"  # Use first GPU (A100)

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
            "phase": "phase3_embedding_a100",
            "model": EMBEDDING_MODEL,
            "device": DEVICE,
            "batch_size": BATCH_SIZE,
            "max_seq_length": MAX_SEQ_LENGTH,
            "gpu_type": "A100 40GB",
            "started_at": None,
            "completed_at": None,
            "status": "pending",
            "last_processed_chunk_id": 0,
            "chunks_processed": 0,
            "chunks_total": 0,
            "chunks_failed": 0,
            "embeddings_stored": 0,
            "batches_completed": 0,
            "vram_peak_mb": 0,
            "total_duration_sec": 0.0,
            "failed_chunks": [],
            "stats": {
                "mean_embedding_time_ms": 0.0,
                "model_load_time_sec": 0.0,
                "throughput_chunks_per_sec": 0.0,
            }
        }

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[ERROR] Failed to load checkpoint: {e}")
            return self._init()

    def save(self):
        """Persist checkpoint to disk."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] Failed to save checkpoint: {e}")

    def mark_started(self, total_chunks: int):
        self.data["started_at"] = datetime.now(timezone.utc).isoformat()
        self.data["status"] = "in_progress"
        self.data["chunks_total"] = total_chunks
        self.save()

    def mark_batch_complete(self, chunk_ids: list, embeddings_count: int, batch_time_sec: float, vram_mb: int):
        self.data["last_processed_chunk_id"] = max(chunk_ids) if chunk_ids else self.data["last_processed_chunk_id"]
        self.data["chunks_processed"] += len(chunk_ids)
        self.data["embeddings_stored"] += embeddings_count
        self.data["batches_completed"] += 1
        self.data["vram_peak_mb"] = max(self.data["vram_peak_mb"], vram_mb)
        self.save()

    def mark_completed(self, total_duration_sec: float, throughput: float):
        self.data["completed_at"] = datetime.now(timezone.utc).isoformat()
        self.data["status"] = "completed"
        self.data["total_duration_sec"] = total_duration_sec
        self.data["stats"]["throughput_chunks_per_sec"] = throughput
        self.save()

# ═══════════════════════════════════════════════════════════════════════════════
# GPU Utilities
# ═══════════════════════════════════════════════════════════════════════════════

def get_vram_usage() -> Tuple[float, float]:
    """Returns (current_mb, peak_mb) VRAM usage."""
    if torch.cuda.is_available():
        current = torch.cuda.memory_allocated() / 1024 / 1024
        peak = torch.cuda.max_memory_allocated() / 1024 / 1024
        return current, peak
    return 0.0, 0.0

def print_gpu_info():
    """Print GPU info for debugging."""
    if torch.cuda.is_available():
        print(f"[GPU] Device: {torch.cuda.get_device_name(0)}")
        print(f"[GPU] CUDA Version: {torch.version.cuda}")
        print(f"[GPU] cuDNN Version: {torch.backends.cudnn.version()}")
        total_memory = torch.cuda.get_device_properties(0).total_memory / 1024 / 1024 / 1024
        print(f"[GPU] Total VRAM: {total_memory:.1f}GB")

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
        print(f"[ERROR] Failed to fetch pending chunks: {e}")
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
        print(f"[ERROR] Failed to update indexed_at: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# Embedding Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class EmbeddingPipeline:
    """Phase 3: Generate and persist embeddings on A100."""

    def __init__(self, checkpoint: EmbeddingCheckpoint):
        self.checkpoint = checkpoint
        self.model = None
        self.collection = None

    def initialize(self) -> bool:
        """Load model and connect to ChromaDB."""
        try:
            print(f"\n{'='*80}")
            print("Phase 3: Embedding Pipeline (A100 40GB Optimized)")
            print(f"{'='*80}")

            print_gpu_info()

            print(f"\n[INIT] Configuration:")
            print(f"  Device: {DEVICE}")
            print(f"  Model: {EMBEDDING_MODEL}")
            print(f"  Batch size: {BATCH_SIZE}")
            print(f"  Max seq length: {MAX_SEQ_LENGTH}")
            print(f"  Database: {DB_PATH}")

            # Load model
            print(f"\n[LOAD] Loading SentenceTransformer model...")
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

            # Check VRAM after model load
            current_vram, peak_vram = get_vram_usage()
            print(f"  Current VRAM: {current_vram:.0f}MB, Peak: {peak_vram:.0f}MB")

            # Initialize ChromaDB
            print(f"\n[CHROMA] Connecting to ChromaDB...")
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            self.collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            collection_count = self.collection.count()
            print(f"  Collection: {COLLECTION_NAME}")
            print(f"  Current vectors: {collection_count:,}")

            return True

        except Exception as e:
            print(f"[FATAL] Failed to initialize: {e}")
            import traceback
            traceback.print_exc()
            return False

    def encode_batch(self, texts: list) -> Optional[np.ndarray]:
        """Generate embeddings for batch of texts."""
        try:
            embeddings = self.model.encode(
                texts,
                batch_size=BATCH_SIZE,
                show_progress_bar=False,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            return embeddings
        except Exception as e:
            print(f"[ERROR] Encoding failed: {e}")
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
            print(f"[ERROR] Failed to store embeddings batch: {e}")
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
                print("\n[INFO] No pending chunks to embed.")
                return True

            total_chunks = len(pending_chunks)
            print(f"\n[START] Processing {total_chunks:,} pending chunks...")
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
                    print(f"[ERROR] Batch {batch_num}/{total_batches} encoding failed, skipping...")
                    failed_chunks.extend([c.id for c in batch_chunks])
                    continue

                # Store embeddings
                stored_count, failed_ids = self.store_embeddings_batch(batch_chunks, embeddings)
                failed_chunks.extend(failed_ids)
                total_embeddings += stored_count

                # GPU memory monitoring
                current_vram, peak_vram = get_vram_usage()

                # Progress report
                progress_pct = (batch_end / total_chunks) * 100
                throughput = batch_size / batch_duration if batch_duration > 0 else 0
                print(f"[BATCH] {batch_num:4d}/{total_batches:4d} | "
                      f"{batch_end:7d}/{total_chunks:7d} ({progress_pct:5.1f}%) | "
                      f"{batch_duration:6.2f}s | "
                      f"{throughput:6.0f} chunks/s | "
                      f"VRAM: {current_vram:6.0f}MB")

                # Checkpoint every batch
                self.checkpoint.mark_batch_complete(
                    [c.id for c in batch_chunks],
                    stored_count,
                    batch_duration,
                    int(peak_vram)
                )

                batch_count += 1

            # Final report
            total_duration = (datetime.now() - start_time).total_seconds()
            throughput = total_chunks / total_duration if total_duration > 0 else 0
            self.checkpoint.mark_completed(total_duration, throughput)

            print(f"\n{'='*80}")
            print(f"Phase 3: Embedding Complete!")
            print(f"{'='*80}")
            print(f"Total duration: {total_duration:.2f}s ({total_duration/60:.1f}m)")
            print(f"Embeddings stored: {total_embeddings:,} / {total_chunks:,}")
            print(f"Batches completed: {batch_count}")
            print(f"Throughput: {throughput:.0f} chunks/s")
            print(f"Peak VRAM: {self.checkpoint.data['vram_peak_mb']} MB")
            print(f"Failed chunks: {len(failed_chunks)}")

            if failed_chunks:
                print(f"Failed chunk IDs (first 20): {failed_chunks[:20]}")
                self.checkpoint.data["failed_chunks"] = failed_chunks
                self.checkpoint.save()

            return len(failed_chunks) == 0

        except Exception as e:
            print(f"[FATAL] {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            torch.cuda.empty_cache()

# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    checkpoint = EmbeddingCheckpoint()

    # Check for existing progress
    if checkpoint.data["status"] == "completed":
        print("\n[INFO] Phase 3 already completed.")
        print(f"  Embeddings: {checkpoint.data['embeddings_stored']:,}")
        print(f"  Duration: {checkpoint.data['total_duration_sec']:.2f}s")
        sys.exit(0)

    if checkpoint.data["status"] == "in_progress":
        print("\n[INFO] Resuming Phase 3 (interrupted)...")
        print(f"  Last chunk: {checkpoint.data['last_processed_chunk_id']}")
        print(f"  Progress: {checkpoint.data['chunks_processed']} / {checkpoint.data['chunks_total']}")

    pipeline = EmbeddingPipeline(checkpoint)
    success = pipeline.run()

    sys.exit(0 if success else 1)
