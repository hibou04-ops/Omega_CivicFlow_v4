"""
═══════════════════════════════════════════════════════════════════════════════
Phase 3: Embedding Pipeline — RTX 5070 Optimized (bge-m3)
═══════════════════════════════════════════════════════════════════════════════

Deterministic embedding pipeline for pre-processed chunks (Phase 1+2 output).
RTX 5070 optimized: batch_size=16, max_seq_length=512, bge-m3 model.

Flow:
  1. Load bge-m3 from HuggingFace with device=cuda:0 (RTX 5070)
  2. Batch-process document_chunks from DB (ordered by id for resumption)
  3. Generate 1024-dim embeddings via encode()
  4. Persist to ChromaDB omega_documents_v2 collection
  5. Update indexed_at timestamp in DB
  6. Checkpoint after each batch (resumption-safe)
  7. Final: validation metrics and timing report
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import sys
import os

# CPU optimization (RTX 5070 PyTorch compatibility issue - use CPU mode)
os.environ["OMP_NUM_THREADS"] = "8"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
# Force CPU mode due to RTX 5070 sm_120 kernel unavailability in PyTorch 2.5
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import torch
import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import sessionmaker

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Direct imports without 'backend' prefix
import importlib.util
models_path = project_root / "backend" / "models" / "models.py"
config_path = project_root / "backend" / "config.py"

spec_models = importlib.util.spec_from_file_location("models", models_path)
models_module = importlib.util.module_from_spec(spec_models)
spec_models.loader.exec_module(models_module)
DocumentChunk = models_module.DocumentChunk
Document = models_module.Document

spec_config = importlib.util.spec_from_file_location("config", config_path)
config_module = importlib.util.module_from_spec(spec_config)
spec_config.loader.exec_module(config_module)
settings = config_module.settings

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

CHECKPOINT_FILE = Path(__file__).parent / "phase3_embedding_checkpoint.json"
EMBEDDING_MODEL = "BAAI/bge-m3"  # Multilingual, 1024-dim output
BATCH_SIZE = 8  # CPU mode: smaller batch size (~512MB RAM per batch)
MAX_SEQ_LENGTH = 512  # bge-m3 recommendation
DEVICE = "cpu"  # Force CPU mode (RTX 5070 sm_120 not supported in PyTorch 2.5+cu121)

# ChromaDB configuration
CHROMA_PATH = settings.CHROMADB_DIR
COLLECTION_NAME = "omega_documents_v2"

# Database configuration
DB_URL = settings.DATABASE_URL
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

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
            "note": "CPU mode due to RTX 5070 sm_120 PyTorch incompatibility. Est. 2-3 hours for 284K chunks.",
            "started_at": None,
            "completed_at": None,
            "status": "pending",  # pending → in_progress → completed
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
                "mean_batch_size": 0,
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

    def mark_batch_complete(self, chunk_ids: list, embeddings_count: int, batch_time_sec: float, vram_mb: int):
        self.data["last_processed_chunk_id"] = max(chunk_ids) if chunk_ids else self.data["last_processed_chunk_id"]
        self.data["chunks_processed"] += len(chunk_ids)
        self.data["embeddings_stored"] += embeddings_count
        self.data["batches_completed"] += 1
        self.data["vram_peak_mb"] = max(self.data["vram_peak_mb"], vram_mb)
        self.save()

    def mark_completed(self, total_duration_sec: float):
        self.data["completed_at"] = datetime.now(timezone.utc).isoformat()
        self.data["status"] = "completed"
        self.data["total_duration_sec"] = total_duration_sec
        self.save()

# ═══════════════════════════════════════════════════════════════════════════════
# GPU/Memory Management
# ═══════════════════════════════════════════════════════════════════════════════

def get_vram_usage() -> Tuple[float, float]:
    """Returns (current_mb, peak_mb) VRAM usage."""
    if torch.cuda.is_available():
        current = torch.cuda.memory_allocated() / 1024 / 1024
        peak = torch.cuda.max_memory_allocated() / 1024 / 1024
        return current, peak
    return 0.0, 0.0

def cleanup_gpu():
    """Clear GPU cache."""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

# ═══════════════════════════════════════════════════════════════════════════════
# Embedding Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class EmbeddingPipeline:
    """Phase 3: Generate and persist embeddings."""

    def __init__(self, checkpoint: EmbeddingCheckpoint):
        self.checkpoint = checkpoint
        self.model = None
        self.chroma_client = None
        self.collection = None
        self.session = None

    def initialize(self) -> bool:
        """Load model and connect to storage."""
        try:
            print(f"\n[Phase 3] Initializing embedding pipeline on {DEVICE}...")
            print(f"  Model: {EMBEDDING_MODEL}")
            print(f"  Batch size: {BATCH_SIZE}")
            print(f"  Max sequence length: {MAX_SEQ_LENGTH}")

            # Load model with RTX 5070 optimizations
            print("  Loading SentenceTransformer model...")
            model_start = datetime.now()
            self.model = SentenceTransformer(
                EMBEDDING_MODEL,
                device=DEVICE,
                trust_remote_code=True,
                cache_folder=str(Path(settings.DATASET_DIR) / "models"),
            )
            # Configure for inference
            self.model.max_seq_length = MAX_SEQ_LENGTH
            model_load_time = (datetime.now() - model_start).total_seconds()
            print(f"  Model loaded in {model_load_time:.2f}s")
            self.checkpoint.data["stats"]["model_load_time_sec"] = model_load_time

            # Initialize ChromaDB
            print("  Connecting to ChromaDB...")
            self.chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            self.collection = self.chroma_client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            collection_count = self.collection.count()
            print(f"  ChromaDB collection '{COLLECTION_NAME}' ready (current size: {collection_count})")

            # Initialize database session
            self.session = Session()
            print("  Database connection established")

            return True

        except Exception as e:
            print(f"ERROR: Failed to initialize pipeline: {e}")
            return False

    def fetch_pending_chunks(self) -> list:
        """Get chunks not yet embedded, ordered for resumption."""
        try:
            query = (
                select(DocumentChunk)
                .where(DocumentChunk.indexed_at.is_(None))
                .order_by(DocumentChunk.id)
            )
            chunks = self.session.execute(query).scalars().all()
            return chunks
        except Exception as e:
            print(f"ERROR: Failed to fetch pending chunks: {e}")
            return []

    def encode_batch(self, texts: list) -> Optional[np.ndarray]:
        """Generate embeddings for batch of texts."""
        try:
            embeddings = self.model.encode(
                texts,
                batch_size=BATCH_SIZE,
                show_progress_bar=False,
                normalize_embeddings=True,  # L2 normalization for cosine distance
                convert_to_numpy=True,
            )
            return embeddings
        except Exception as e:
            print(f"ERROR: Encoding failed: {e}")
            return None

    def store_embeddings_batch(self, chunks: list, embeddings: np.ndarray) -> Tuple[int, list]:
        """Store embeddings in ChromaDB and update DB timestamps."""
        stored_count = 0
        failed_chunk_ids = []
        now_utc = datetime.now(timezone.utc).isoformat()

        try:
            # Prepare ChromaDB batch
            ids = []
            vectors = []
            metadatas = []
            documents = []

            for i, chunk in enumerate(chunks):
                chunk_id = f"chunk_{chunk.id}"
                ids.append(chunk_id)
                vectors.append(embeddings[i].tolist())
                metadatas.append({
                    "document_id": chunk.document_id,
                    "chunk_index": str(chunk.chunk_index),
                    "created_at": chunk.created_at.isoformat() if chunk.created_at else "",
                })
                documents.append(chunk.text[:1000])  # Store first 1000 chars for search

            # Store to ChromaDB
            self.collection.upsert(
                ids=ids,
                embeddings=vectors,
                metadatas=metadatas,
                documents=documents,
            )

            # Update database indexed_at timestamps
            chunk_ids_to_update = [chunk.id for chunk in chunks]
            update_stmt = (
                text("""
                    UPDATE document_chunks
                    SET indexed_at = :now
                    WHERE id IN ({})
                """.format(",".join(["?" for _ in chunk_ids_to_update])))
            )
            # Use raw SQL for better control
            conn = sqlite3.connect(DB_URL.replace("sqlite:///", ""))
            cursor = conn.cursor()
            placeholders = ",".join(["?" for _ in chunk_ids_to_update])
            cursor.execute(f"UPDATE document_chunks SET indexed_at = ? WHERE id IN ({placeholders})",
                          [now_utc] + chunk_ids_to_update)
            conn.commit()
            conn.close()

            stored_count = len(chunks)

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
            # Fetch all pending chunks
            pending_chunks = self.fetch_pending_chunks()
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
                    print(f"ERROR: Batch {batch_num}/{total_batches} encoding failed, skipping...")
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
                print(f"  Batch {batch_num:4d}/{total_batches} | "
                      f"{batch_end:7d}/{total_chunks:7d} chunks ({progress_pct:5.1f}%) | "
                      f"{batch_duration:6.2f}s | "
                      f"VRAM: {current_vram:6.1f}MB (peak: {peak_vram:6.1f}MB)")

                # Checkpoint every batch
                self.checkpoint.mark_batch_complete(
                    [c.id for c in batch_chunks],
                    stored_count,
                    batch_duration,
                    int(peak_vram)
                )

                cleanup_gpu()
                batch_count += 1

            # Final report
            total_duration = (datetime.now() - start_time).total_seconds()
            self.checkpoint.mark_completed(total_duration)

            print(f"\n[Phase 3] Embedding pipeline completed!")
            print(f"  Total duration: {total_duration:.2f}s ({total_duration/60:.1f}m)")
            print(f"  Embeddings stored: {total_embeddings:,} / {total_chunks:,}")
            print(f"  Batches completed: {batch_count}")
            print(f"  Failed chunks: {len(failed_chunks)}")
            print(f"  Peak VRAM: {self.checkpoint.data['vram_peak_mb']} MB")

            if failed_chunks:
                print(f"  Failed chunk IDs: {failed_chunks[:10]}...")
                self.checkpoint.data["failed_chunks"] = failed_chunks
                self.checkpoint.save()

            return len(failed_chunks) == 0

        except Exception as e:
            print(f"FATAL ERROR: {e}")
            return False

        finally:
            if self.session:
                self.session.close()

# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("Phase 3: Embedding Pipeline (RTX 5070 + bge-m3)")
    print("=" * 80)

    checkpoint = EmbeddingCheckpoint()

    # Check for existing progress
    if checkpoint.data["status"] == "completed":
        print("\nPhase 3 already completed.")
        print(f"  Embeddings stored: {checkpoint.data['embeddings_stored']:,}")
        print(f"  Completed at: {checkpoint.data['completed_at']}")
        print(f"  Total duration: {checkpoint.data['total_duration_sec']:.2f}s")
        sys.exit(0)

    if checkpoint.data["status"] == "in_progress":
        print("\nResuming interrupted Phase 3 embedding...")
        print(f"  Last processed chunk ID: {checkpoint.data['last_processed_chunk_id']}")
        print(f"  Progress: {checkpoint.data['chunks_processed']} / {checkpoint.data['chunks_total']}")

    pipeline = EmbeddingPipeline(checkpoint)
    success = pipeline.run()

    sys.exit(0 if success else 1)
