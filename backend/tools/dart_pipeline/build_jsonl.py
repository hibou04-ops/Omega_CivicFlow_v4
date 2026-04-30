"""
build_jsonl.py
==============
Stream ChunkRecord -> JSONL with resume support.

Output format (one JSON object per line):
  {"chunk_id": ..., "text": ..., "company_name": ..., ...all 23 fields}

Resume: {output}.checkpoint.json tracks completed rcept_nos.
Append mode: safe to restart — duplicates deduplicated downstream by chunk_id.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import IO, Iterable, Optional, Set

from chunk_dart_documents import ChunkRecord

log = logging.getLogger(__name__)

CHECKPOINT_EVERY_DEFAULT = 10  # flush checkpoint every N completed rcept_nos


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def _checkpoint_path(out_path: Path) -> Path:
    return out_path.with_suffix(".checkpoint.json")


def load_checkpoint(out_path: Path) -> Set[str]:
    """Return set of rcept_nos already written. Empty set if no checkpoint."""
    cp = _checkpoint_path(out_path)
    if not cp.exists():
        return set()
    try:
        data = json.loads(cp.read_text(encoding="utf-8"))
        completed: Set[str] = set(data.get("completed_rcept_nos", []))
        log.info("Checkpoint loaded: %d completed rcept_nos", len(completed))
        return completed
    except Exception as exc:
        log.warning("Checkpoint read failed (%s) — starting fresh", exc)
        return set()


def _save_checkpoint(out_path: Path, completed: Set[str]) -> None:
    """Atomic checkpoint write: write to .tmp then rename."""
    cp = _checkpoint_path(out_path)
    tmp = cp.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(
                {"completed_rcept_nos": sorted(completed)},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        tmp.replace(cp)  # atomic on NTFS and POSIX
    except Exception as exc:
        log.warning("Checkpoint save failed: %s", exc)


def _serialize_record(record: ChunkRecord) -> str:
    """Convert ChunkRecord to JSON line. Enum values -> .value strings."""
    d = asdict(record)
    d["chunk_type"]       = record.chunk_type.value
    d["statement_scope"]  = record.statement_scope.value
    return json.dumps(d, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ChunkWriter: streaming JSONL with checkpoint
# ---------------------------------------------------------------------------

class ChunkWriter:
    """
    Streaming JSONL writer with resume support.

    Usage pattern:
        writer = ChunkWriter(out_path)
        with writer:
            for entry in archive_entries:
                if writer.is_done(entry.rcept_no):
                    continue
                chunks = chunk_document(...)
                for chunk in chunks:
                    writer.write(chunk)
                writer.complete_rcept_no(entry.rcept_no)
        # checkpoint is saved on __exit__
    """

    def __init__(
        self,
        out_path: Path,
        checkpoint_every: int = CHECKPOINT_EVERY_DEFAULT,
    ) -> None:
        self.out_path = out_path
        self.checkpoint_every = checkpoint_every

        self._completed: Set[str] = load_checkpoint(out_path)
        self._fh: Optional[IO[str]] = None
        self._total_written: int = 0
        self._since_last_cp: int = 0

    # ------------------------------------------------------------------
    # Properties

    @property
    def completed_rcept_nos(self) -> frozenset[str]:
        return frozenset(self._completed)

    @property
    def total_written(self) -> int:
        return self._total_written

    def is_done(self, rcept_no: str) -> bool:
        return rcept_no in self._completed

    # ------------------------------------------------------------------
    # Context manager

    def __enter__(self) -> "ChunkWriter":
        # Append mode: safe for resume — existing content preserved
        self._fh = open(self.out_path, "a", encoding="utf-8", buffering=1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._fh:
            self._fh.flush()
            self._fh.close()
            self._fh = None
        _save_checkpoint(self.out_path, self._completed)
        log.info(
            "ChunkWriter closed: %d chunks written, %d docs completed",
            self._total_written,
            len(self._completed),
        )
        return False  # do not suppress exceptions

    # ------------------------------------------------------------------
    # Write operations

    def write(self, record: ChunkRecord) -> None:
        """Write one ChunkRecord as a JSONL line."""
        if self._fh is None:
            raise RuntimeError("ChunkWriter not open. Use as context manager.")
        self._fh.write(_serialize_record(record) + "\n")
        self._total_written += 1

    def complete_rcept_no(self, rcept_no: str) -> None:
        """
        Mark a rcept_no as fully written.
        Call AFTER all chunks for this document have been written.
        Checkpoint is flushed every `checkpoint_every` completions.
        """
        self._completed.add(rcept_no)
        self._since_last_cp += 1

        if self._since_last_cp >= self.checkpoint_every:
            if self._fh:
                self._fh.flush()
            _save_checkpoint(self.out_path, self._completed)
            self._since_last_cp = 0
            log.debug("Checkpoint saved: %d completed", len(self._completed))

    def force_checkpoint(self) -> None:
        """Force immediate checkpoint flush (e.g., before a known slow operation)."""
        if self._fh:
            self._fh.flush()
        _save_checkpoint(self.out_path, self._completed)
        self._since_last_cp = 0


# ---------------------------------------------------------------------------
# Convenience function for single-doc or testing usage
# ---------------------------------------------------------------------------

def write_chunks(
    records: Iterable[ChunkRecord],
    out_path: Path,
    rcept_no: str,
    writer: Optional[ChunkWriter] = None,
) -> int:
    """
    Write all records for one rcept_no.
    Returns count of chunks written (0 if already in checkpoint).

    If writer is provided, uses it (for batch use).
    Otherwise opens a one-shot writer.
    """
    if writer is not None:
        if writer.is_done(rcept_no):
            log.debug("Skipping %s (already completed)", rcept_no)
            return 0
        n = 0
        for rec in records:
            writer.write(rec)
            n += 1
        writer.complete_rcept_no(rcept_no)
        return n
    else:
        with ChunkWriter(out_path) as w:
            if w.is_done(rcept_no):
                return 0
            n = 0
            for rec in records:
                w.write(rec)
                n += 1
            w.complete_rcept_no(rcept_no)
            return n


# ---------------------------------------------------------------------------
# CLI: inspect output and checkpoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python build_jsonl.py <output.jsonl>")
        sys.exit(1)

    out = Path(sys.argv[1])

    # Show checkpoint state
    completed = load_checkpoint(out)
    print(f"Checkpoint: {len(completed)} completed rcept_nos")

    # Count output lines
    if out.exists():
        n_lines = sum(1 for _ in out.open(encoding="utf-8"))
        print(f"Output: {n_lines:,} lines in {out.name}")

        # Sample first 3 records
        print("\nSample records:")
        with out.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= 3:
                    break
                try:
                    rec = json.loads(line)
                    print(f"  {rec.get('chunk_id')} | {rec.get('chunk_type')} "
                          f"| {len(rec.get('text', ''))}c")
                except json.JSONDecodeError:
                    print(f"  [invalid JSON on line {i+1}]")
    else:
        print(f"Output file not found: {out}")
