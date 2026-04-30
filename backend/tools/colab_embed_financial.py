# -*- coding: utf-8 -*-
"""
colab_embed_financial.py — STEP 2: 콜랩 A100에서 BGE-M3 임베딩.

Workflow:
  STEP 1 (로컬): export_financial_chunks_jsonl.py → financial_chunks.jsonl
  STEP 2 (콜랩 A100, 이 스크립트): JSONL → BGE-M3 → embeddings JSONL
  STEP 3 (로컬): import_financial_embeddings.py → ChromaDB add

콜랩 사용 예시:
  !pip install sentence-transformers FlagEmbedding
  !python colab_embed_financial.py --input financial_chunks.jsonl --output financial_embeddings.jsonl

Output: financial_embeddings.jsonl
  {"chunk_uid": "...", "embedding": [0.123, ...], "metadata": {...}, "text": "..."}
"""
import argparse
import json
import time
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="financial_chunks.jsonl path")
    parser.add_argument("--output", required=True, help="Output embeddings JSONL path")
    parser.add_argument("--batch-size", type=int, default=64, help="Embedding batch size (A100: 64~128)")
    parser.add_argument("--model", default="BAAI/bge-m3", help="Embedding model")
    args = parser.parse_args()

    print(f"[1/4] Loading model: {args.model}")
    from sentence_transformers import SentenceTransformer
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"      device: {device}")
    if device == "cuda":
        print(f"      gpu: {torch.cuda.get_device_name(0)}")
        print(f"      vram: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

    model = SentenceTransformer(args.model, device=device)
    # max_seq_length=1024: 실측 결과 평균 549 tokens, p99 636 tokens.
    # 512로 두면 93% 청크가 silent truncation. 1024로 모든 청크 손실 없이 커버.
    # BGE-M3는 native 8192 지원, A100 40GB에서 batch=64 × 1024 seq → ~6GB VRAM.
    model.max_seq_length = 1024
    print(f"      embedding dim: {model.get_sentence_embedding_dimension()}")
    print(f"      max_seq_length: {model.max_seq_length}")

    print(f"[2/4] Loading chunks: {args.input}")
    chunks = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    print(f"      total chunks: {len(chunks):,}")

    print(f"[3/4] Embedding (batch_size={args.batch_size})...")
    start = time.time()
    texts = [c["text"] for c in chunks]
    embeddings = model.encode(
        texts,
        batch_size=args.batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    elapsed = time.time() - start
    print(f"      done in {elapsed:.1f}s ({len(chunks)/elapsed:.0f} chunks/s)")

    print(f"[4/4] Writing output: {args.output}")
    with open(args.output, "w", encoding="utf-8") as f:
        for c, emb in zip(chunks, embeddings):
            record = {
                "chunk_uid": c["chunk_uid"],
                "text": c["text"],
                "metadata": c["metadata"],
                "embedding": emb.tolist(),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    size_mb = os.path.getsize(args.output) / 1024 / 1024
    print(f"      output size: {size_mb:.1f} MB")
    print()
    print("=" * 60)
    print(f"DONE. Download {args.output} → 로컬에서 import_financial_embeddings.py 실행")


if __name__ == "__main__":
    main()
