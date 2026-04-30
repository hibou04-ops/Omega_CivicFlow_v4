"""
validate_chunks.py
==================
Check List[ChunkRecord] against FR-01 through FR-13.

Returns ValidationReport with per-violation counts and optionally
filters bad chunks from the output list.

FR Rules enforced here:
  FR-01: No numeric-only chunk (no Korean label nearby)
  FR-02: TABLE chunk must have header row in text
  FR-03: No mixed scope in single chunk
  FR-07: Chunk text must start with breadcrumb
  FR-08: All 7 required metadata fields must be non-empty
  FR-11: token_estimate must not exceed 6000
  FR-12: TABLE chunk must not end on 합계/소계 without prior component rows
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import List, Tuple

from chunk_dart_documents import ChunkRecord, ChunkType, StatementScope

log = logging.getLogger(__name__)

MAX_TOKEN_ESTIMATE = 6000

_NUMERIC_LINE_RE = re.compile(r'^[\d,.()\-+\s]{5,}$')
_KOREAN_RE        = re.compile(r'[\uAC00-\uD7A3]')
_TOTAL_ROW_RE     = re.compile(r'(합계|소계|계\b)')

_CONSOL_MARKERS   = re.compile(r'(연결재무|연결포괄|연결손익)')
_SEP_MARKERS      = re.compile(r'(별도재무|별도포괄|별도손익)')

# 7 required metadata fields (FR-08)
_REQUIRED_FIELDS = (
    "chunk_id", "company_name", "rcept_no",
    "fiscal_year", "statement_scope", "chunk_type", "breadcrumb",
)


# ---------------------------------------------------------------------------
# Violation types
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    chunk_id: str
    rule: str       # "FR-01", "FR-02", ...
    detail: str


@dataclass
class ValidationReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    violations: list[Violation] = field(default_factory=list)

    def add_violation(self, chunk_id: str, rule: str, detail: str) -> None:
        self.violations.append(Violation(chunk_id=chunk_id, rule=rule, detail=detail))
        self.failed += 1

    def summary(self) -> str:
        rate = self.failed / self.total * 100 if self.total else 0
        by_rule: dict[str, int] = {}
        for v in self.violations:
            by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
        rule_str = ", ".join(f"{r}={n}" for r, n in sorted(by_rule.items()))
        return (f"Validation: {self.total} total, {self.passed} passed, "
                f"{self.failed} failed ({rate:.1f}%) [{rule_str}]")


# ---------------------------------------------------------------------------
# Individual rule checks
# ---------------------------------------------------------------------------

def _check_fr01(rec: ChunkRecord) -> bool:
    """FR-01: Numeric-only lines with no Korean label."""
    lines = rec.text_raw.split("\n")
    numeric_only = sum(1 for ln in lines if _NUMERIC_LINE_RE.match(ln.strip()))
    total_lines = max(len(lines), 1)
    # Flag if > 80% of lines are purely numeric
    return (numeric_only / total_lines) > 0.8


def _check_fr02(rec: ChunkRecord) -> bool:
    """FR-02: TABLE chunk without header row."""
    if not rec.contains_table:
        return False
    # Simple heuristic: [TABLE] block should have at least 2 rows
    # (header + at least one data row). One-row tables are likely broken.
    table_match = re.search(r'\[TABLE\](.*?)\[/TABLE\]', rec.text, re.DOTALL)
    if not table_match:
        return rec.chunk_type in (
            ChunkType.FINANCIAL_TABLE, ChunkType.NOTE_TABLE
        )
    inner = table_match.group(1).strip()
    rows = [ln for ln in inner.split("\n") if ln.strip()]
    return len(rows) < 2


def _check_fr03(rec: ChunkRecord) -> bool:
    """FR-03: Mixed scope markers in single chunk."""
    has_consol = bool(_CONSOL_MARKERS.search(rec.text_raw[:300]))
    has_sep    = bool(_SEP_MARKERS.search(rec.text_raw[:300]))
    return has_consol and has_sep


def _check_fr07(rec: ChunkRecord) -> bool:
    """FR-07: Chunk text does not start with breadcrumb."""
    return not rec.text.startswith(rec.breadcrumb)


def _check_fr08(rec: ChunkRecord) -> list[str]:
    """FR-08: Required metadata fields missing or empty. Returns list of missing fields."""
    missing: list[str] = []
    for fname in _REQUIRED_FIELDS:
        val = getattr(rec, fname, None)
        if val is None or val == "" or (isinstance(val, str) and not val.strip()):
            missing.append(fname)
    return missing


def _check_fr11(rec: ChunkRecord) -> bool:
    """FR-11: token_estimate exceeds BGE-M3 safe ceiling."""
    return rec.token_estimate > MAX_TOKEN_ESTIMATE


def _check_fr12(rec: ChunkRecord) -> bool:
    """
    FR-12: TABLE chunk ends on 합계/소계 row without prior component rows.
    Conservative check: if last data row is 합계 and there's only 1 data row,
    it was likely detached from its components.
    """
    if not rec.contains_table:
        return False
    table_match = re.search(r'\[TABLE\](.*?)\[/TABLE\]', rec.text, re.DOTALL)
    if not table_match:
        return False
    inner = table_match.group(1).strip()
    rows = [ln for ln in inner.split("\n") if ln.strip()]
    if len(rows) < 2:
        return False
    last_row = rows[-1]
    data_rows = rows[1:]  # skip header
    return len(data_rows) == 1 and bool(_TOTAL_ROW_RE.search(last_row))


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

def validate_chunks(
    records: List[ChunkRecord],
    tag_broken: bool = True,
) -> Tuple[List[ChunkRecord], ValidationReport]:
    """
    Validate all records against FR rules.

    Args:
        records:     List of ChunkRecord to validate
        tag_broken:  If True, set is_broken_table=True on FR-02 violations
                     instead of filtering them out

    Returns:
        (passing_records, report)
        passing_records: records that passed all hard rules (FR-08, FR-11)
        report: full ValidationReport including soft rule violations
    """
    report = ValidationReport(total=len(records))
    passing: list[ChunkRecord] = []

    for rec in records:
        violations: list[str] = []

        # --- Soft rules (flag but don't filter) ---
        if _check_fr01(rec):
            report.add_violation(rec.chunk_id, "FR-01",
                                  "Numeric-only chunk (>80% numeric lines)")
            violations.append("FR-01")

        if _check_fr02(rec):
            if tag_broken:
                object.__setattr__(rec, "is_broken_table", True)
            report.add_violation(rec.chunk_id, "FR-02",
                                  "TABLE chunk missing header row")
            violations.append("FR-02")

        if _check_fr03(rec):
            report.add_violation(rec.chunk_id, "FR-03",
                                  "Mixed 연결/별도 scope markers in single chunk")
            violations.append("FR-03")

        if _check_fr07(rec):
            report.add_violation(rec.chunk_id, "FR-07",
                                  "Chunk text does not start with breadcrumb")
            violations.append("FR-07")

        if _check_fr12(rec):
            report.add_violation(rec.chunk_id, "FR-12",
                                  "합계/소계 row detached from component rows")
            violations.append("FR-12")

        # --- Hard rules (filter out) ---
        missing_fields = _check_fr08(rec)
        if missing_fields:
            report.add_violation(rec.chunk_id, "FR-08",
                                  f"Required fields missing: {missing_fields}")
            log.warning("FR-08 filter: %s missing fields %s", rec.chunk_id, missing_fields)
            continue  # FILTER OUT

        if _check_fr11(rec):
            report.add_violation(rec.chunk_id, "FR-11",
                                  f"token_estimate={rec.token_estimate} > {MAX_TOKEN_ESTIMATE}")
            log.warning("FR-11 filter: %s tokens=%d", rec.chunk_id, rec.token_estimate)
            continue  # FILTER OUT

        passing.append(rec)
        if not violations:
            report.passed += 1

    log.info(report.summary())
    return passing, report


# ---------------------------------------------------------------------------
# CLI: validate an existing JSONL file
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path
    from chunk_dart_documents import ChunkType, StatementScope, ChunkRecord

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python validate_chunks.py <output.jsonl>")
        sys.exit(1)

    jsonl_path = Path(sys.argv[1])
    if not jsonl_path.exists():
        print(f"File not found: {jsonl_path}")
        sys.exit(1)

    records: list[ChunkRecord] = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                # Reconstruct enums
                d["chunk_type"]      = ChunkType(d["chunk_type"])
                d["statement_scope"] = StatementScope(d["statement_scope"])
                records.append(ChunkRecord(**d))
            except Exception as exc:
                print(f"  Parse error: {exc}")

    print(f"Loaded {len(records)} records from {jsonl_path.name}")
    _, report = validate_chunks(records)
    print(report.summary())

    if report.violations:
        print("\nFirst 10 violations:")
        for v in report.violations[:10]:
            print(f"  {v.rule} | {v.chunk_id} | {v.detail}")
