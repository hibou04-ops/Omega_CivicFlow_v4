"""
detect_archives.py
==================
Scan DataSet directory -> ArchiveEntry generator.

Handles:
  - .zip            standard DART archives
  - .zip.pdf        double-extension archives (actually ZIP containers)

Deduplication:
  - Key = rcept_no (14-digit substring from filename)
  - If same rcept_no has both .zip and .zip.pdf, prefer .zip
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

log = logging.getLogger(__name__)

_RCEPT_NO_RE = re.compile(r'(\d{14})')
# DART_P{n}_{company}_{rcept_no}.zip[.pdf]  (P0~P4 모두 처리)
_DART_NAME_RE = re.compile(r'DART_P\d+_(.+?)_(\d{14})')


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

@dataclass
class ArchiveEntry:
    path: Path
    rcept_no: str       # 14-digit
    file_type: str      # "zip" | "zip.pdf"
    size_bytes: int
    company_name: str = ""   # parsed from filename


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_rcept_no(filename: str) -> Optional[str]:
    """Extract 14-digit rcept_no from filename. Returns None if not found."""
    m = _RCEPT_NO_RE.search(filename)
    return m.group(1) if m else None


def _parse_dart_filename(filename: str) -> tuple[str, str]:
    """Returns (company_name, rcept_no) from DART_P0_{company}_{rcept_no}.zip"""
    m = _DART_NAME_RE.search(filename)
    if m:
        return m.group(1), m.group(2)
    rcept_no = extract_rcept_no(filename) or ""
    return "", rcept_no


def _file_type(path: Path) -> Optional[str]:
    name = path.name.lower()
    if name.endswith(".zip.pdf"):
        return "zip.pdf"
    if name.endswith(".zip"):
        return "zip"
    return None


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def iter_archives(dataset_dir: Path) -> Generator[ArchiveEntry, None, None]:
    """
    Yield one ArchiveEntry per unique rcept_no.

    Priority: .zip over .zip.pdf for the same rcept_no.
    Logs stats at end: total files, skipped duplicates, unknown files.
    """
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    # First pass: collect all candidates
    # key = rcept_no, value = best ArchiveEntry seen so far
    best: dict[str, ArchiveEntry] = {}
    total_files = 0
    unknown_files = 0

    for path in sorted(dataset_dir.iterdir()):
        if not path.is_file():
            continue
        total_files += 1

        ftype = _file_type(path)
        if ftype is None:
            unknown_files += 1
            continue

        company_name, rcept_no = _parse_dart_filename(path.name)
        if not rcept_no:
            log.warning("No rcept_no in filename: %s", path.name)
            unknown_files += 1
            continue

        entry = ArchiveEntry(
            path=path,
            rcept_no=rcept_no,
            file_type=ftype,
            size_bytes=path.stat().st_size,
            company_name=company_name,
        )

        # Prefer .zip over .zip.pdf
        if rcept_no not in best:
            best[rcept_no] = entry
        elif best[rcept_no].file_type == "zip.pdf" and ftype == "zip":
            log.debug("Replacing %s .zip.pdf with .zip for %s", rcept_no, path.name)
            best[rcept_no] = entry
        # else: keep existing (zip beats zip.pdf, or first-seen wins)

    skipped = total_files - unknown_files - len(best)
    log.info(
        "Dataset scan: %d total, %d unique rcept_nos, %d skipped (dup), %d unknown",
        total_files, len(best), skipped, unknown_files,
    )

    for entry in sorted(best.values(), key=lambda e: e.rcept_no):
        yield entry


# ---------------------------------------------------------------------------
# CLI: inspect dataset
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python detect_archives.py <dataset_dir> [--sample N]")
        sys.exit(1)

    dataset_dir = Path(sys.argv[1])
    sample_n = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--sample" else None

    type_counts: dict[str, int] = {}
    size_total = 0
    n = 0

    for entry in iter_archives(dataset_dir):
        type_counts[entry.file_type] = type_counts.get(entry.file_type, 0) + 1
        size_total += entry.size_bytes
        n += 1
        if sample_n and n <= sample_n:
            print(f"  {entry.rcept_no} | {entry.file_type} | {entry.size_bytes//1024}KB | {entry.path.name}")
        if sample_n and n >= sample_n:
            print(f"  ... (showing first {sample_n})")
            break

    print(f"\nTotal unique rcept_nos: {n}")
    for ft, cnt in sorted(type_counts.items()):
        print(f"  {ft}: {cnt}")
    print(f"Total size: {size_total / 1024 / 1024:.1f} MB")
