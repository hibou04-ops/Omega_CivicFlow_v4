# DART Batch Pipeline — Implementation Plan
**Target: 87+ RAGAS | 3,138 filings | Python 3.11**

---

## SECTION 1 — File-by-File Code Plan

### `detect_archives.py`
**Job**: scan DataSet dir, emit one `ArchiveEntry` per unique rcept_no.

Key logic:
- Walk directory, collect all `.zip` and `.zip.pdf` paths
- Extract rcept_no: 14-digit substring from filename (`r'\d{14}'`)
- Dedup: if same rcept_no has both `.zip` and `.zip.pdf`, prefer `.zip`
- Yield generator (never loads all paths into memory at once)
- Track stats: total files, skipped (dup), unknown

Inputs: `dataset_dir: Path`
Outputs: `Generator[ArchiveEntry, None, None]`

```python
@dataclass
class ArchiveEntry:
    path: Path
    rcept_no: str       # 14-digit
    file_type: str      # "zip" | "zip.pdf"
    size_bytes: int
```

---

### `extract_dart_xml.py`
**Job**: ZIP bytes → `List[ExtractedXML]` (one per XML role).

Key logic:
- Open ZIP in-memory with `zipfile.ZipFile(io.BytesIO(content))`
- Classify each XML: MAIN / CONSOL (`_00760`) / SEP (`_00761`)
- Parse DART4 XML with BeautifulSoup `lxml-xml` (fastest for 8MB XMLs)
- Traverse: `SECTION-1 > SECTION-2 > TITLE/P/TABLE`
- TABLE → row text: each TR as one line, cells joined with `"  "`
- Dedup: remove repeated short lines (TOC titles re-appear in body)
- Encoding: detect from XML declaration, fallback cp949 → latin-1

Inputs: `content: bytes, filename: str, rcept_no: str`
Outputs: `List[ExtractedXML]`

```python
@dataclass
class ExtractedXML:
    rcept_no: str
    xml_role: str       # "MAIN" | "CONSOL" | "SEP"
    raw_text: str       # structured text output
    xml_filename: str
    char_count: int
```

---

### `classify_xml_roles.py`
**Job**: augment/verify xml_role from filename suffix + content signals.

This is thin — most classification happens inside `extract_dart_xml.py`. This module handles edge cases:
- XML filename doesn't contain rcept_no as expected
- Verify audit report type from `<COVER-TITLE>` content
- Emit warnings for unclassifiable XMLs

In practice, this can be a single function called by `extract_dart_xml.py`:

```python
def classify_xml_role(xml_name: str, rcept_no: str) -> str:
    ...
```

---

### `chunk_dart_documents.py`
**Job**: structured text + `ChunkMeta` → `List[ChunkRecord]`.

Key logic:
1. Parse `##`/`###` headers to identify L1/L2 section boundaries
2. Per block: classify `ChunkType` from L1 keyword match
3. Detect `StatementScope` (연결/별도) from first 200 chars of L1+content
4. Extract unit annotation `(단위: N원)` for table header injection
5. Split via budget-aware splitters:
   - Tables: split on row boundaries, repeat header row (FR-02)
   - Narratives: split on paragraph boundaries `\n\n`, add overlap
6. Build breadcrumb prefix per policy format
7. Wrap into `ChunkRecord` (23 fields), enforce `korean_ratio >= 0.12`

Budget table (from Chunking Policy vFinal):

| ChunkType        | target | hard_cap | overlap |
|-----------------|--------|----------|---------|
| NARRATIVE        | 800    | 1200     | 100     |
| FINANCIAL_TABLE  | 1800   | 2800     | 0 (FR)  |
| NOTE_TABLE       | 500    | 700      | 0 (FR)  |
| NOTE_NARRATIVE   | 500    | 700      | 80      |
| AUDIT_OPINION    | 1800   | 3500     | 0 (FR)  |
| FACT_SUMMARY     | 300    | 400      | N/A     |

---

### `build_jsonl.py`
**Job**: stream `ChunkRecord` → JSONL with resume support.

Key logic:
- Open output file in **append mode** (resume-safe)
- Load checkpoint on init: `Set[str]` of completed rcept_nos
- `is_done(rcept_no)` → skip already-processed docs
- Write one JSON line per ChunkRecord (enum values → `.value`)
- `complete_rcept_no()`: add to completed set, flush checkpoint every N docs
- Checkpoint is **atomic write** via tmp file → rename (prevents corruption)
- `ChunkWriter` class usable as context manager

---

### `validate_chunks.py`
**Job**: check FR-01 through FR-13 on a `List[ChunkRecord]`.

Key checks:

| Rule  | Check |
|-------|-------|
| FR-01 | Numeric-only chunk (no Korean label nearby) → flag |
| FR-02 | TABLE chunk without header row in text → `is_broken_table = True` |
| FR-03 | Mixed scope in single chunk (연결 + 별도 markers) → flag |
| FR-07 | Chunk text doesn't start with breadcrumb → flag |
| FR-08 | Any of 7 required metadata fields is empty/None → reject |
| FR-11 | `token_estimate > 6000` → flag (BGE-M3 silent truncation risk) |
| FR-12 | TABLE chunk ends with 합계/소계 row without prior component rows → flag |

Returns: `ValidationReport` with counts and per-chunk issues.

---

### `run_batch_pipeline.py`
**Job**: wire all modules, drive the 3,138-file batch.

Key logic:
1. Parse CLI args: `--dataset-dir`, `--output`, `--company-db`, `--log-level`
2. Load `CompanyMeta` lookup (rcept_no → company_name, fiscal_year, report_type)
3. Init `ChunkWriter` with checkpoint
4. For each `ArchiveEntry` from `detect_archives`:
   - Skip if `writer.is_done(entry.rcept_no)`
   - Read bytes
   - Call `extract_from_dart_zip` → `List[ExtractedXML]`
   - For each ExtractedXML: `chunk_document` → `List[ChunkRecord]`
   - `validate_chunks` → filter FR violations
   - `writer.write(rec)` for each passing chunk
   - `writer.complete_rcept_no(rcept_no)`
5. Print final stats: files, chunks, FR violations, elapsed

Progress: `tqdm` over ArchiveEntry generator.

---

## SECTION 2 — Data Flow

```
DataSet/
  *.zip, *.zip.pdf
       │
       ▼
 detect_archives.py
  → ArchiveEntry(path, rcept_no, file_type, size_bytes)
       │
       ▼ [skip if rcept_no in checkpoint]
       │
  read bytes (Path.read_bytes())
       │
       ▼
 extract_dart_xml.py
  → ExtractedXML(rcept_no, xml_role, raw_text, xml_filename, char_count)
       │
       ▼ [one or more per ZIP: MAIN + CONSOL + SEP]
       │
 chunk_dart_documents.py  ← ChunkMeta from company DB
  → List[ChunkRecord]  (23 fields each)
       │
       ▼
 validate_chunks.py
  → filter FR violations, tag is_broken_table
       │
       ▼
 build_jsonl.py  →  output.jsonl  (append mode)
                 →  output.checkpoint.json  (atomic, every 50 docs)
```

State carried between steps:
- `rcept_no` ties everything together (14-digit key)
- `xml_role` scopes MAIN/CONSOL/SEP per XML file
- `ChunkMeta` carries company_name, fiscal_year, report_type from company DB lookup
- `ChunkWriter.completed_rcept_nos` drives skip logic

---

## SECTION 3 — State and Resume Design

### Checkpoint file: `{output}.checkpoint.json`
```json
{
  "completed_rcept_nos": [
    "20240101000001",
    "20240101000002"
  ]
}
```

### Resume flow on restart:
1. `ChunkWriter.__init__` calls `load_checkpoint()` → `completed: Set[str]`
2. `detect_archives` scans all 3,138 files (fast — just stat calls)
3. `writer.is_done(rcept_no)` → `True` → skip
4. Continue from first incomplete rcept_no

### Crash-safe invariant:
- `complete_rcept_no(rcept_no)` called **only after** all chunks for that rcept_no are written
- If crash mid-document: rcept_no NOT in checkpoint → reprocessed on restart → chunks re-appended (duplicates)
- Downstream dedup: embedding pipeline deduplicates by `chunk_id` (cheap set lookup)
- This is simpler than per-chunk checkpointing and acceptable for a batch job

### Checkpoint flush cadence:
- Every 50 completed rcept_nos (configurable via `ChunkWriter.checkpoint_every`)
- On `ChunkWriter.__exit__` (context manager close)
- Write is atomic: write to `.tmp` then `Path.replace()` (POSIX-atomic, works on Windows NTFS)

---

## SECTION 4 — Memory-Safe Design

### Peak memory per file:
| Phase | Size |
|-------|------|
| Raw ZIP bytes | ≤ 8 MB (Samsung-class), median ~558 KB |
| Decoded XML string | 1–3× ZIP size |
| BeautifulSoup parse tree | 3–10× XML size |
| Extracted text | 50–200 KB |
| ChunkRecord list | 200 chunks × ~2 KB = ~400 KB |
| **Total peak** | ~15 MB |

15 MB peak per file is fine on any modern machine. The risk is NOT per-file memory.

### Risks that *are* real:
1. **BeautifulSoup tree held in memory while iterating chunks** — fix: call `soup.decompose()` after extraction
2. **Accumulating all ChunkRecords for all files before writing** — fix: write per-document, don't batch across docs
3. **tqdm + large stdout buffers on Windows** — fix: `tqdm(file=sys.stderr)` not stdout

### Generator discipline:
- `detect_archives` → generator (never materializes all 3,138 paths)
- `extract_from_dart_zip` → returns List (per-ZIP, bounded)
- `chunk_document` → returns List (per-doc, bounded)
- `build_jsonl.ChunkWriter` → streaming write, no in-memory accumulation

### CPU temperature guard:
- This pipeline runs locally. Monitor: `psutil.sensors_battery()` or Windows WMI
- If CPU > 75°C → sleep 30s (see memory: local_cpu_temp_limit.md)
- Alternatively: run full batch on Colab after testing locally on 50-file sample

---

## SECTION 6 — Recommended Support Structures

### `constants.py`
```python
# Chunk budget (from Chunking Policy vFinal)
NARRATIVE_TARGET       = 800
NARRATIVE_HARD_CAP     = 1200
NARRATIVE_OVERLAP      = 100

FINANCIAL_TABLE_TARGET   = 1800
FINANCIAL_TABLE_HARD_CAP = 2800

NOTE_TABLE_TARGET        = 500
NOTE_TABLE_HARD_CAP      = 700

NOTE_NARRATIVE_TARGET    = 500
NOTE_NARRATIVE_HARD_CAP  = 700
NOTE_NARRATIVE_OVERLAP   = 80

AUDIT_OPINION_TARGET     = 1800
AUDIT_OPINION_HARD_CAP   = 3500

FACT_SUMMARY_TARGET      = 300
FACT_SUMMARY_HARD_CAP    = 400

# Quality filters
MIN_CHUNK_LENGTH   = 150      # chars
KOREAN_RATIO_MIN   = 0.12     # Korean chars / total chars
TOKEN_RATIO        = 1.8      # chars × 1.8 ≈ BGE-M3 tokens
MAX_TOKEN_ESTIMATE = 6000     # FR-11 hard ceiling

# Pipeline
CHUNK_VERSION         = "v7"
CHECKPOINT_EVERY      = 50    # rcept_nos between checkpoint flushes
```

### `config.py`
```python
@dataclass
class PipelineConfig:
    dataset_dir: Path
    output_path: Path
    company_db_path: Path      # SQLite with company metadata
    log_level: str = "INFO"
    checkpoint_every: int = 50
    sample_n: Optional[int] = None   # for dev: process only first N files
    dry_run: bool = False            # extract + chunk but don't write
```

### `logging_setup.py`
```python
def setup_logging(level: str, log_file: Optional[Path] = None) -> None:
    # Console: INFO+, format = "HH:MM:SS LEVEL msg"
    # File: DEBUG+, rotating 10MB × 3
```

### `path_utils.py`
```python
RCEPT_NO_RE = re.compile(r'(\d{14})')

def extract_rcept_no(filename: str) -> Optional[str]:
    m = RCEPT_NO_RE.search(filename)
    return m.group(1) if m else None

def is_dart_archive(path: Path) -> bool:
    return path.suffix == ".zip" or path.name.endswith(".zip.pdf")
```

---

## SECTION 7 — Final Recommended Build Order

Build and test **incrementally** — each module testable alone before wiring.

```
Step 1: constants.py + path_utils.py
        → no dependencies, immediate
        → test: python path_utils.py DataSet/ (prints file count)

Step 2: detect_archives.py
        → depends on path_utils
        → test: python detect_archives.py DataSet/ --sample 10
        → verify: rcept_no dedup, .zip preference, stats printout

Step 3: extract_dart_xml.py
        → depends on bs4[lxml]
        → test: python extract_dart_xml.py DataSet/some_file.zip RCEPT_NO
        → verify: Korean chars present, table rows extracted, no dupes

Step 4: build_jsonl.py
        → depends on chunk_dart_documents (for ChunkRecord type)
        → write stub ChunkRecord, test checkpoint round-trip
        → test: python build_jsonl.py output.jsonl

Step 5: chunk_dart_documents.py
        → depends on constants
        → test: pipe extract output → chunk → print stats
        → verify: chunk types, budget compliance, breadcrumb format

Step 6: validate_chunks.py
        → depends on chunk_dart_documents
        → test: inject known FR violations, verify detection

Step 7: run_batch_pipeline.py
        → wires all modules
        → test: --sample 10 on local machine
        → full run: Colab (embed tier uses A100, but chunk tier is CPU-only)
```

**Expected outputs for 10-file smoke test**:
- ~500–2,000 chunks
- FR violation rate < 5%
- No `token_estimate > 6000`
- Korean ratio > 0.12 on all chunks
- Checkpoint file written correctly (restart from mid-run)
