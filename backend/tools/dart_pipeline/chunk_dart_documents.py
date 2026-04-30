"""
chunk_dart_documents.py
=======================
Structured text + ChunkMeta -> List[ChunkRecord]

Chunk types (6):
  NARRATIVE, FINANCIAL_TABLE, NOTE_TABLE, NOTE_NARRATIVE,
  AUDIT_OPINION, FACT_SUMMARY

Token budget (from Chunking Policy vFinal):
  NARRATIVE:        target=800,  hard_cap=1200, overlap=100
  FINANCIAL_TABLE:  target=1800, hard_cap=2800, overlap=0 (FORBIDDEN)
  NOTE_TABLE:       target=500,  hard_cap=700,  overlap=0 (FORBIDDEN)
  NOTE_NARRATIVE:   target=500,  hard_cap=700,  overlap=80
  AUDIT_OPINION:    target=1800, hard_cap=3500, overlap=0 (FORBIDDEN)
  FACT_SUMMARY:     target=300,  hard_cap=400,  N/A
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ChunkType(str, Enum):
    NARRATIVE        = "NARRATIVE"
    FINANCIAL_TABLE  = "FINANCIAL_TABLE"
    NOTE_TABLE       = "NOTE_TABLE"
    NOTE_NARRATIVE   = "NOTE_NARRATIVE"
    AUDIT_OPINION    = "AUDIT_OPINION"
    FACT_SUMMARY     = "FACT_SUMMARY"


class StatementScope(str, Enum):
    CONSOLIDATED = "CONSOLIDATED"   # 연결
    SEPARATE     = "SEPARATE"       # 별도
    UNKNOWN      = "UNKNOWN"


# ---------------------------------------------------------------------------
# Budget specs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BudgetSpec:
    target: int
    hard_cap: int
    overlap: int    # 0 = FORBIDDEN per policy


_BUDGETS: dict[ChunkType, BudgetSpec] = {
    ChunkType.NARRATIVE:       BudgetSpec(target=800,  hard_cap=1200, overlap=100),
    ChunkType.FINANCIAL_TABLE: BudgetSpec(target=1800, hard_cap=2800, overlap=0),
    ChunkType.NOTE_TABLE:      BudgetSpec(target=500,  hard_cap=700,  overlap=0),
    ChunkType.NOTE_NARRATIVE:  BudgetSpec(target=500,  hard_cap=700,  overlap=80),
    ChunkType.AUDIT_OPINION:   BudgetSpec(target=1800, hard_cap=3500, overlap=0),
    ChunkType.FACT_SUMMARY:    BudgetSpec(target=300,  hard_cap=400,  overlap=0),
}

MIN_CHUNK_LENGTH = 150
KOREAN_RATIO_MIN = 0.12
TOKEN_RATIO      = 1.8
CHUNK_VERSION    = "v7"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ChunkMeta:
    """Document-level metadata supplied by the pipeline."""
    rcept_no: str
    company_name: str
    fiscal_year: str               # "2024"
    report_type: str               # "사업보고서" | "분기보고서" | ...
    quarter: Optional[str] = None  # "1Q" | "2Q" | "3Q" | None
    xml_role: str = "MAIN"         # "MAIN" | "CONSOL" | "SEP"
    source_path: str = ""


@dataclass
class ChunkRecord:
    """One chunk: 23 required fields for vector DB and validation."""
    # Identity
    chunk_id: str
    chunk_idx: int
    rcept_no: str

    # Document metadata
    company_name: str
    fiscal_year: str
    report_type: str
    quarter: Optional[str]
    xml_role: str

    # Classification
    chunk_type: ChunkType
    statement_scope: StatementScope

    # Content
    text: str           # breadcrumb prefix + content
    text_raw: str       # content without breadcrumb (for debug/eval)
    breadcrumb: str     # full breadcrumb string

    # Section hierarchy
    l1_section: str
    l2_section: str

    # Quality signals
    char_count: int
    token_estimate: int     # round(char_count * 1.8)
    korean_ratio: float
    contains_table: bool
    is_broken_table: bool   # True if table was split mid-row (validate_chunks sets this)
    has_unit_annotation: bool   # True if (단위: ...) found

    # Pipeline
    chunk_version: str = CHUNK_VERSION
    source_path: str = ""


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_KOREAN_RE = re.compile(r'[\uAC00-\uD7A3]')


def _korean_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(_KOREAN_RE.findall(text)) / len(text)


def _token_estimate(chars: int) -> int:
    return round(chars * TOKEN_RATIO)


def _make_chunk_id(rcept_no: str, xml_role: str, idx: int) -> str:
    role_code = {"MAIN": "M", "CONSOL": "C", "SEP": "S"}.get(xml_role, "X")
    return f"{rcept_no}-{role_code}-{idx:06d}"


# ---------------------------------------------------------------------------
# Unit annotation helpers
# ---------------------------------------------------------------------------

_UNIT_RE = re.compile(r'단위\s*:\s*[^\n)]{1,20}[원만억조]')


def _extract_unit_annotation(text: str) -> Optional[str]:
    m = _UNIT_RE.search(text)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# Scope detection
# ---------------------------------------------------------------------------

_CONSOL_KEYWORDS = {"연결재무", "연결포괄", "연결손익", "연결현금", "연결자본"}
_SEP_KEYWORDS    = {"별도재무", "별도포괄", "별도손익", "별도현금", "별도자본"}


def _detect_scope(text: str) -> StatementScope:
    norm = re.sub(r"\s+", "", text[:500])
    if any(kw in norm for kw in _CONSOL_KEYWORDS):
        return StatementScope.CONSOLIDATED
    if any(kw in norm for kw in _SEP_KEYWORDS):
        return StatementScope.SEPARATE
    return StatementScope.UNKNOWN


# ---------------------------------------------------------------------------
# Chunk type classification
# ---------------------------------------------------------------------------

_AUDIT_L1  = {"감사보고서", "감사의견", "검토보고서", "내부회계"}
_FACT_L1   = {"표지", "회사의개요", "핵심투자위험", "요약재무"}
_NOTE_L1   = {"주석", "재무제표주석"}
_FIN_L1    = {"재무상태표", "손익계산서", "포괄손익", "자본변동표",
              "현금흐름표", "재무제표", "연결재무", "별도재무"}


def _classify_chunk_type(l1: str, content: str) -> ChunkType:
    l1n = re.sub(r"\s+", "", l1)
    has_table = "[TABLE]" in content

    if any(kw in l1n for kw in _AUDIT_L1):
        return ChunkType.AUDIT_OPINION
    if any(kw in l1n for kw in _FACT_L1):
        return ChunkType.FACT_SUMMARY
    if any(kw in l1n for kw in _NOTE_L1):
        return ChunkType.NOTE_TABLE if has_table else ChunkType.NOTE_NARRATIVE
    if any(kw in l1n for kw in _FIN_L1) and has_table:
        return ChunkType.FINANCIAL_TABLE
    return ChunkType.NARRATIVE


# ---------------------------------------------------------------------------
# Breadcrumb builder
# ---------------------------------------------------------------------------

def _make_breadcrumb(
    meta: ChunkMeta,
    scope: StatementScope,
    l1_section: str,
    l2_section: str = "",
) -> str:
    """
    Format:
      [{company} {year}년[ {quarter}] {report_type}][ [연결]|[별도]] {L1}[ > {L2}]
    """
    year_label = f"{meta.fiscal_year}년"
    if meta.quarter:
        year_label += f" {meta.quarter}"

    scope_tag = ""
    if scope == StatementScope.CONSOLIDATED:
        scope_tag = " [연결]"
    elif scope == StatementScope.SEPARATE:
        scope_tag = " [별도]"

    header = f"[{meta.company_name} {year_label} {meta.report_type}]{scope_tag}"

    trail = l1_section
    if l2_section:
        trail += f" > {l2_section}"

    return f"{header} {trail}"


# ---------------------------------------------------------------------------
# Table splitter (FR-02: header repeat; FR-12: 합계 boundary)
# ---------------------------------------------------------------------------

_TOTAL_ROW_RE = re.compile(r'(합계|소계|계\b)', re.IGNORECASE)


def _split_table_content(
    inner: str,
    budget: BudgetSpec,
    breadcrumb: str,
    unit_ann: Optional[str],
) -> list[str]:
    """
    Split table inner text (no [TABLE] markers) into budget-sized chunks.
    Header row (first row) is repeated at top of each split chunk (FR-02).
    합계/소계 rows are kept with their preceding rows (FR-12).
    """
    rows = inner.strip().split("\n")
    if not rows:
        return []

    header_row = rows[0]
    data_rows  = rows[1:]
    unit_prefix = f"({unit_ann})\n" if unit_ann else ""

    chunks: list[str] = []
    current: list[str] = [header_row]
    cur_len = len(header_row)

    def _emit() -> None:
        if len(current) <= 1:
            return
        body = "[TABLE]\n" + "\n".join(current) + "\n[/TABLE]"
        chunk_text = breadcrumb + "\n" + unit_prefix + body
        chunks.append(chunk_text)
        current.clear()
        current.append(header_row)

    for i, row in enumerate(data_rows):
        row_len = len(row) + 1
        projected = cur_len + row_len
        is_total = bool(_TOTAL_ROW_RE.search(row))

        if projected > budget.hard_cap:
            if is_total:
                # Keep total row with current batch even if slightly over cap
                log.debug("합계 row kept with batch (over budget by %d chars)",
                          projected - budget.hard_cap)
            else:
                _emit()
                cur_len = len(header_row)

        current.append(row)
        cur_len += row_len

    _emit()
    return chunks


# ---------------------------------------------------------------------------
# Narrative splitter (paragraph-boundary, with overlap)
# ---------------------------------------------------------------------------

def _split_narrative_content(
    text: str,
    budget: BudgetSpec,
    breadcrumb: str,
) -> list[str]:
    """
    Split narrative text into budget-sized chunks.
    Split on paragraph boundaries (\n\n preferred over mid-paragraph).
    Overlap = tail of previous chunk prepended as context.
    """
    if len(text) <= budget.hard_cap:
        full = breadcrumb + "\n" + text
        if len(full) >= MIN_CHUNK_LENGTH and _korean_ratio(text) >= KOREAN_RATIO_MIN:
            return [full]
        return []

    # 단락 경계 없는 거대 단락 하드컷 (CORRECTION 등 컨테이너 잔재)
    def _hard_cut(blob: str) -> list[str]:
        pieces: list[str] = []
        while len(blob) > budget.hard_cap:
            cut = budget.hard_cap
            # 문장 부호 기준으로 자르기 시도
            for punct in ('다.\n', '다. ', '. ', '\n', ' '):
                idx = blob.rfind(punct, budget.hard_cap // 2, budget.hard_cap)
                if idx > 0:
                    cut = idx + len(punct)
                    break
            pieces.append(blob[:cut].strip())
            blob = blob[cut:].strip()
        if blob.strip():
            pieces.append(blob.strip())
        return pieces

    raw_paragraphs = re.split(r'\n{2,}', text)
    # 하드컷 적용: hard_cap 초과 단락은 먼저 분해
    paragraphs: list[str] = []
    for p in raw_paragraphs:
        if len(p) > budget.hard_cap:
            paragraphs.extend(_hard_cut(p))
        else:
            paragraphs.append(p)

    chunks: list[str] = []
    current_parts: list[str] = []
    cur_len = 0
    overlap_ctx = ""

    def _emit_narr() -> None:
        if not current_parts:
            return
        body = "\n\n".join(current_parts)
        full = breadcrumb + "\n" + overlap_ctx + body
        if len(full) >= MIN_CHUNK_LENGTH and _korean_ratio(body) >= KOREAN_RATIO_MIN:
            chunks.append(full)

    for para in paragraphs:
        para_len = len(para) + 2

        if cur_len + para_len > budget.target and current_parts:
            body = "\n\n".join(current_parts)
            full = breadcrumb + "\n" + overlap_ctx + body
            if len(full) >= MIN_CHUNK_LENGTH and _korean_ratio(body) >= KOREAN_RATIO_MIN:
                chunks.append(full)

            if budget.overlap > 0:
                tail = body[-budget.overlap:] if len(body) > budget.overlap else body
                overlap_ctx = "[이전 내용 계속]\n" + tail + "\n"
            else:
                overlap_ctx = ""

            current_parts = []
            cur_len = 0

        current_parts.append(para)
        cur_len += para_len

    _emit_narr()
    return chunks


# ---------------------------------------------------------------------------
# ChunkRecord builder
# ---------------------------------------------------------------------------

def _make_record(
    chunk_text: str,
    ctype: ChunkType,
    meta: ChunkMeta,
    scope: StatementScope,
    l1: str,
    l2: str,
    breadcrumb: str,
    idx: int,
    contains_table: bool,
    unit_ann: Optional[str],
) -> Optional[ChunkRecord]:
    if len(chunk_text) < MIN_CHUNK_LENGTH:
        return None
    # Strip breadcrumb prefix to get raw content
    prefix_len = len(breadcrumb)
    raw = chunk_text[prefix_len:].lstrip("\n") if chunk_text.startswith(breadcrumb) else chunk_text
    if _korean_ratio(raw) < KOREAN_RATIO_MIN:
        return None

    return ChunkRecord(
        chunk_id=_make_chunk_id(meta.rcept_no, meta.xml_role, idx),
        chunk_idx=idx,
        rcept_no=meta.rcept_no,
        company_name=meta.company_name,
        fiscal_year=meta.fiscal_year,
        report_type=meta.report_type,
        quarter=meta.quarter,
        xml_role=meta.xml_role,
        chunk_type=ctype,
        statement_scope=scope,
        text=chunk_text,
        text_raw=raw,
        breadcrumb=breadcrumb,
        l1_section=l1,
        l2_section=l2,
        char_count=len(chunk_text),
        token_estimate=_token_estimate(len(chunk_text)),
        korean_ratio=round(_korean_ratio(raw), 4),
        contains_table=contains_table,
        is_broken_table=False,
        has_unit_annotation=bool(unit_ann),
        source_path=meta.source_path,
    )


# ---------------------------------------------------------------------------
# Section parser
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r'^(#{2,3})\s+(.+)$')


def chunk_document(raw_text: str, meta: ChunkMeta) -> List[ChunkRecord]:
    """
    Top-level entry point.
    Parses ##/### headers into L1/L2 blocks, classifies each block,
    splits per budget, returns List[ChunkRecord].
    """
    records: List[ChunkRecord] = []
    chunk_idx = 0

    current_l1 = "전체"
    current_l2 = ""
    current_lines: list[str] = []

    def _flush(l1: str, l2: str, block_lines: list[str]) -> None:
        nonlocal chunk_idx

        content = "\n".join(block_lines).strip()
        if not content or len(content) < MIN_CHUNK_LENGTH:
            return

        scope = _detect_scope(l1 + " " + content[:200])
        ctype = _classify_chunk_type(l1, content)
        budget = _BUDGETS[ctype]
        unit_ann = _extract_unit_annotation(content)
        breadcrumb = _make_breadcrumb(meta, scope, l1, l2)

        # Separate table and narrative portions
        parts = re.split(r'(\[TABLE\].*?\[/TABLE\])', content, flags=re.DOTALL)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            if part.startswith("[TABLE]"):
                # Strip markers for splitter
                inner = re.sub(r'^\[TABLE\]\n?', '', part)
                inner = re.sub(r'\n?\[/TABLE\]$', '', inner)
                split_chunks = _split_table_content(inner, budget, breadcrumb, unit_ann)
                for ct in split_chunks:
                    rec = _make_record(ct, ctype, meta, scope, l1, l2,
                                       breadcrumb, chunk_idx, True, unit_ann)
                    if rec:
                        records.append(rec)
                        chunk_idx += 1
            else:
                # Narrative portion: use narrative budget if ctype is table-based
                narr_budget = (budget if ctype in (ChunkType.NARRATIVE,
                                                   ChunkType.NOTE_NARRATIVE,
                                                   ChunkType.FACT_SUMMARY,
                                                   ChunkType.AUDIT_OPINION)
                               else _BUDGETS[ChunkType.NARRATIVE])
                split_chunks = _split_narrative_content(part, narr_budget, breadcrumb)
                for ct in split_chunks:
                    rec = _make_record(ct, ctype, meta, scope, l1, l2,
                                       breadcrumb, chunk_idx, False, unit_ann)
                    if rec:
                        records.append(rec)
                        chunk_idx += 1

    for line in raw_text.split("\n"):
        m = _HEADER_RE.match(line)
        if m:
            _flush(current_l1, current_l2, current_lines)
            current_lines = []
            level, title = m.group(1), m.group(2).strip()
            if len(level) == 2:   # "##" -> L1
                current_l1 = title
                current_l2 = ""
            else:                  # "###" -> L2
                current_l2 = title
        else:
            current_lines.append(line)

    _flush(current_l1, current_l2, current_lines)
    return records


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

    if len(sys.argv) < 4:
        print("Usage: python chunk_dart_documents.py <text_file> <rcept_no> <company_name>")
        sys.exit(1)

    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    meta = ChunkMeta(
        rcept_no=sys.argv[2],
        company_name=sys.argv[3],
        fiscal_year="2024",
        report_type="사업보고서",
    )

    records = chunk_document(text, meta)
    print(f"Produced {len(records)} chunks")

    type_counts: dict[str, int] = {}
    for r in records:
        type_counts[r.chunk_type.value] = type_counts.get(r.chunk_type.value, 0) + 1

    for ct, n in sorted(type_counts.items()):
        print(f"  {ct}: {n}")

    print("\nSample chunks:")
    for r in records[:3]:
        print(f"  {r.chunk_id} | {r.chunk_type.value} | {r.char_count}c "
              f"| k={r.korean_ratio:.2f} | scope={r.statement_scope.value}")
        print(f"    {r.text[:120]}...")
