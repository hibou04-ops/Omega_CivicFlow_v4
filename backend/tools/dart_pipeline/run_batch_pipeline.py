"""
run_batch_pipeline.py
=====================
Orchestrator: wire all modules, drive the 3,138-file batch.

Pipeline:
  detect_archives -> extract_dart_xml -> chunk_dart_documents
  -> validate_chunks -> build_jsonl

Usage:
  python run_batch_pipeline.py \
    --dataset-dir  C:/Users/hibou/Desktop/DataSet \
    --output       C:/Users/hibou/Desktop/chunks_v7.jsonl \
    --company-meta C:/Users/hibou/Desktop/company_meta.json \
    [--sample 10]  \
    [--dry-run]    \
    [--log-level DEBUG]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Inline metadata extraction (no company_meta.json required)
# ---------------------------------------------------------------------------

_REPORT_TYPE_KEYWORDS = [
    "사업보고서", "분기보고서", "반기보고서",
    "감사보고서", "주요사항보고서", "기타공시",
]
_QUARTER_RE   = re.compile(r'제\s*(\d)\s*분기')
_FY_RE        = re.compile(r'(?:회계연도|사업연도|보고기간).*?(\d{4})년')

# Pipeline modules
from detect_archives     import iter_archives, ArchiveEntry
from extract_dart_xml    import extract_from_dart_zip
from chunk_dart_documents import ChunkMeta, chunk_document
from validate_chunks     import validate_chunks, ValidationReport
from build_jsonl         import ChunkWriter

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Company meta loader
# ---------------------------------------------------------------------------

def load_company_meta(path: Optional[Path]) -> dict[str, dict]:
    """
    Load rcept_no -> {company_name, fiscal_year, report_type, quarter} mapping.

    Format (JSON):
      {
        "20240101000001": {
          "company_name": "삼성전자",
          "fiscal_year":  "2024",
          "report_type":  "사업보고서",
          "quarter":      null
        },
        ...
      }

    If path is None or file not found, returns empty dict.
    In that case, company_name falls back to "UNKNOWN".
    """
    if path is None or not path.exists():
        log.warning("Company meta file not found: %s — company_name will be UNKNOWN", path)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("Failed to load company meta: %s", exc)
        return {}


def _detect_report_type(text: str) -> str:
    norm = re.sub(r"\s+", "", text[:3000])
    for kw in _REPORT_TYPE_KEYWORDS:
        if kw in norm:
            return kw
    return "기타공시"


def _detect_fiscal_year(text: str, rcept_no: str) -> str:
    m = _FY_RE.search(text[:3000])
    if m:
        return m.group(1)
    # fallback: filing year from rcept_no prefix
    return rcept_no[:4]


def _detect_quarter(text: str, report_type: str) -> Optional[str]:
    if report_type not in ("분기보고서", "반기보고서"):
        return None
    m = _QUARTER_RE.search(text[:2000])
    if m:
        n = m.group(1)
        return {"1": "1Q", "2": "2Q", "3": "3Q"}.get(n)
    return "2H" if report_type == "반기보고서" else None


def _build_chunk_meta(entry: ArchiveEntry, raw_text: str, company_name: str) -> ChunkMeta:
    report_type = _detect_report_type(raw_text)
    fiscal_year = _detect_fiscal_year(raw_text, entry.rcept_no)
    quarter     = _detect_quarter(raw_text, report_type)
    return ChunkMeta(
        rcept_no     = entry.rcept_no,
        company_name = company_name,
        fiscal_year  = fiscal_year,
        report_type  = report_type,
        quarter      = quarter,
        source_path  = str(entry.path),
    )


# ---------------------------------------------------------------------------
# Progress logger
# ---------------------------------------------------------------------------

class Progress:
    def __init__(self, total: int, log_every: int = 50) -> None:
        self.total     = total
        self.log_every = log_every
        self.processed = 0
        self.chunks    = 0
        self.errors    = 0
        self.start     = time.time()
        self._last_log = 0

    def tick(self, n_chunks: int, error: bool = False) -> None:
        self.processed += 1
        self.chunks    += n_chunks
        if error:
            self.errors += 1
        if self.processed - self._last_log >= self.log_every:
            self._print()
            self._last_log = self.processed

    def _print(self) -> None:
        elapsed = time.time() - self.start
        rate = self.processed / elapsed if elapsed > 0 else 0
        pct  = self.processed / self.total * 100 if self.total else 0
        eta  = (self.total - self.processed) / rate if rate > 0 else 0
        log.info(
            "[%d/%d] %.1f%% | %.1f docs/s | ETA %.0fm | chunks=%d errors=%d",
            self.processed, self.total, pct, rate, eta / 60,
            self.chunks, self.errors,
        )

    def final(self) -> None:
        elapsed = time.time() - self.start
        log.info(
            "Done: %d/%d docs | %d chunks | %d errors | %.1fs",
            self.processed, self.total, self.chunks, self.errors, elapsed,
        )


# ---------------------------------------------------------------------------
# Main batch loop
# ---------------------------------------------------------------------------

def run(
    dataset_dir: Path,
    output_path: Path,
    sample_n: Optional[int],
    dry_run: bool,
) -> None:
    log.info("Scanning dataset: %s", dataset_dir)
    all_entries = list(iter_archives(dataset_dir))
    if sample_n:
        all_entries = all_entries[:sample_n]
        log.info("Sample mode: %d files", sample_n)

    total = len(all_entries)
    log.info("Total: %d archives", total)

    if dry_run:
        log.info("[DRY RUN] extract+chunk only, no write")

    progress   = Progress(total=total)
    agg_report = ValidationReport()

    with ChunkWriter(output_path) as writer:
        for entry in all_entries:
            if writer.is_done(entry.rcept_no):
                progress.tick(0)
                continue

            try:
                raw = entry.path.read_bytes()
                extracted_docs = extract_from_dart_zip(raw, entry.path.name, entry.rcept_no)

                if not extracted_docs:
                    log.warning("[%s] No XML extracted", entry.rcept_no)
                    writer.complete_rcept_no(entry.rcept_no)
                    progress.tick(0, error=True)
                    continue

                # Use MAIN XML for metadata detection
                main_doc = next(
                    (x for x in extracted_docs if x.xml_role == "MAIN"),
                    extracted_docs[0],
                )
                # company_name: XML <COMPANY-NAME> 우선, 없으면 파일명 fallback
                xml_company = main_doc.company_name or entry.company_name or "UNKNOWN"
                chunk_meta = _build_chunk_meta(entry, main_doc.raw_text, xml_company)
                total_chunks = 0

                for ext_xml in extracted_docs:
                    chunk_meta.xml_role = ext_xml.xml_role
                    records = chunk_document(ext_xml.raw_text, chunk_meta)
                    passing, doc_report = validate_chunks(records)

                    agg_report.total   += doc_report.total
                    agg_report.passed  += doc_report.passed
                    agg_report.failed  += doc_report.failed
                    agg_report.violations.extend(doc_report.violations)

                    if not dry_run:
                        for rec in passing:
                            writer.write(rec)

                    total_chunks += len(passing)

                if not dry_run:
                    writer.complete_rcept_no(entry.rcept_no)

                progress.tick(total_chunks)

            except Exception as exc:
                log.error("[%s] Fatal error: %s", entry.rcept_no, exc, exc_info=True)
                progress.tick(0, error=True)
                continue

    progress.final()
    log.info("Aggregate validation: %s", agg_report.summary())

    if not dry_run:
        log.info("Output: %s", output_path)
        log.info("Checkpoint: %s", output_path.with_suffix(".checkpoint.json"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="DART batch chunking pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--dataset-dir",  required=True, type=Path,
                   help="Directory containing .zip and .zip.pdf DART archives")
    p.add_argument("--output",       required=True, type=Path,
                   help="Output JSONL file path")
    p.add_argument("--sample",       type=int, default=None,
                   help="Process only first N files (for testing)")
    p.add_argument("--dry-run",      action="store_true",
                   help="Extract and chunk but do not write output")
    p.add_argument("--log-level",    default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    run(
        dataset_dir = args.dataset_dir,
        output_path = args.output,
        sample_n    = args.sample,
        dry_run     = args.dry_run,
    )
