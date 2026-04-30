# DART Chunking Pipeline — Operational Control Specification
**v7 | 3,138 filings | Windows local batch | Colab embed tier**

---

## SECTION 1 — Validation Rules

### RULE-01: Token Cap Violation

**What**: `token_estimate` exceeds BGE-M3 safe operational ceiling.

**Why**: BGE-M3 max_seq=8192 tokens in theory, but at >6000 tokens the tail is silently
truncated during batch inference. Financial table tails (where 합계 rows live) are exactly
the content lost. The query "NH투자증권 당분기말 금액" retrieves a chunk where that number
was truncated. ctx_precision collapses on these cases.

**Detection signal**:
```python
CHAR_CEILING = 3334  # ceil(6000 / 1.8)
flag = len(chunk.text) > CHAR_CEILING
# equivalently: chunk.token_estimate > 6000
```

**Severity**: HARD — blocks indexing.

**Response**: Discard. Re-split at hard_cap level before this point reaches validation.
If a chunk arrives here overlong, the chunker has a bug. Log as `RULE01_TOKEN_CAP` with
`(chunk_id, char_count, token_estimate)`.

---

### RULE-02: Numeric-Label Separation

**What**: Chunk where the majority of lines are purely numeric with no co-located Korean label.

**Why**: A chunk `2,416,554\n3,120,000\n-890,000` is semantically unqueryable. BGE-M3 cannot
map "현금및현금성자산 금액" to a number-only chunk. These chunks also pollute precision because
they will spuriously match any financial-number query.

**Detection signal**:
```python
lines = [ln.strip() for ln in chunk.text_raw.split("\n") if ln.strip()]
numeric_lines = [
    ln for ln in lines
    if re.match(r'^[\d,.\-+\s()%]{5,}$', ln)
]
flag = len(lines) > 0 and len(numeric_lines) / len(lines) > 0.70
```

**Severity**: HARD — blocks indexing.

**Response**: Discard. Log as `RULE02_DETACHED_NUMERIC` with `(chunk_id, numeric_ratio)`.
Root cause is table splitting that broke the header row from its data rows — fix in chunker.

---

### RULE-03: Broken Table Chunk

**What**: `contains_table=True` but the table block has only one row (header with no data),
or the `[TABLE]` marker is present but the inner content is empty after stripping.

**Why**: A header-only table chunk cannot answer any retrieval query. It adds noise to the
index and degrades precision without contributing recall.

**Detection signal**:
```python
m = re.search(r'\[TABLE\](.*?)\[/TABLE\]', chunk.text, re.DOTALL)
if m:
    inner_rows = [ln for ln in m.group(1).strip().split("\n") if ln.strip()]
    flag = len(inner_rows) < 2
else:
    flag = chunk.contains_table  # marker claimed but absent
```

**Severity**: SOFT — does not block indexing. Sets `is_broken_table=True`.

**Response**: Tag `is_broken_table=True`. Allow indexing. Report count in post-run report.
If count > 3% of all table chunks, investigate chunker table-split logic.

---

### RULE-04: Missing Breadcrumb

**What**: `chunk.text` does not begin with the exact string in `chunk.breadcrumb`.

**Why**: The breadcrumb is the primary company+year+scope anchor injected at retrieval time.
Without it, the embedding vector has no company signal. A chunk about "삼성전자 2024년 연결
현금흐름표" that is missing its breadcrumb will contaminate queries for other companies.

**Detection signal**:
```python
flag = not chunk.text.startswith(chunk.breadcrumb)
```

**Severity**: HARD — blocks indexing.

**Response**: Attempt auto-repair: prepend `breadcrumb + "\n"` to `text`, re-check length
against RULE-01. If repair pushes over token cap, discard. Log as `RULE04_MISSING_BREADCRUMB`.

---

### RULE-05: Missing Statement Scope on Financial Chunk

**What**: `statement_scope == "UNKNOWN"` on a chunk whose `chunk_type` is `FINANCIAL_TABLE`,
`NOTE_TABLE`, or `NOTE_NARRATIVE`.

**Why**: ctx_precision failure mode: the retrieval returns a 연결 figure when the query asks
for 별도, because both chunks look identical except for the scope tag. With scope=UNKNOWN the
pre-filter cannot differentiate. The 이수페타시스 "임직원 주택마련 단기대여금" failure in v5
analysis was partly this.

**Detection signal**:
```python
FIN_TYPES = {ChunkType.FINANCIAL_TABLE, ChunkType.NOTE_TABLE, ChunkType.NOTE_NARRATIVE}
flag = (chunk.statement_scope == StatementScope.UNKNOWN
        and chunk.chunk_type in FIN_TYPES)
```

**Severity**: HARD for FINANCIAL_TABLE and NOTE_TABLE. SOFT for NOTE_NARRATIVE.

**Response**: Re-run `_detect_scope()` with a 1,000-char window instead of 500. If still
UNKNOWN, tag `scope_unresolved=True`, downgrade severity to SOFT, allow indexing. Log count.
These chunks will not participate in company+scope pre-filter retrieval.

---

### RULE-06: Missing Critical Metadata

**What**: Any of the 7 required fields is None, empty string, or the literal string `"UNKNOWN"`
for `company_name` or `rcept_no`.

**Required fields**:
```
chunk_id, company_name, rcept_no, fiscal_year,
statement_scope, chunk_type, breadcrumb
```

**Why**: Downstream ChromaDB metadata pre-filter uses `company_name` and `fiscal_year` as
equality filters. A missing or `"UNKNOWN"` company_name means the chunk is unretrievable via
pre-filter — it will only be retrieved by pure semantic match, which is exactly the
cross-contamination path.

**Detection signal**:
```python
REQUIRED = ("chunk_id", "company_name", "rcept_no",
            "fiscal_year", "statement_scope", "chunk_type", "breadcrumb")
missing = [f for f in REQUIRED
           if getattr(chunk, f) in (None, "", "UNKNOWN")]
flag = len(missing) > 0
```

**Severity**: HARD — blocks indexing.

**Response**: Discard. Log as `RULE06_MISSING_METADATA` with list of missing fields and
`rcept_no`. These indicate a gap in the `company_meta.json` input file. Collect all
`UNKNOWN` company_names post-run and back-fill from DART API before re-run.

---

### RULE-07: Malformed Chunk Text

**What**: `text` field contains XML residue, HTML entities, encoding artifacts, or structural
noise that was not cleaned during extraction.

**Detection signals** (any one triggers):
```python
XML_RESIDUE  = re.compile(r'<[A-Z\-]{2,}[^>]*>')        # <SECTION-1>, <TD>, etc.
HTML_ENTITY  = re.compile(r'&#\d+;|&amp;|&lt;|&gt;|&nbsp;')
NULL_BYTES   = re.compile(r'\x00|\ufffd')
EXCESS_WS    = re.compile(r'[ \t]{10,}')                 # 10+ consecutive spaces
MIXED_CRLF   = '\r\n' in chunk.text
```

**Severity**: SOFT — text is repairable.

**Response**: Clean in-place before write:
```python
text = re.sub(r'<[A-Z\-]{2,}[^>]*>', '', text)
text = re.sub(r'&#\d+;|&[a-z]+;', '', text)
text = re.sub(r'\x00|\ufffd', '', text)
text = re.sub(r'[ \t]{5,}', '  ', text)
text = text.replace('\r\n', '\n').replace('\r', '\n')
```
Log count as `RULE07_MALFORMED_TEXT`. If > 1% of chunks have XML residue, the extractor
has a systemic parse failure — investigate before full run.

---

### RULE-08: Empty or Near-Empty Chunk

**What**: `len(text_raw.strip()) < 150` OR `korean_ratio < 0.12`.

**Why**: Near-empty chunks pass through the embedding pipeline and create noise vectors that
match random queries. `korean_ratio < 0.12` typically means the chunk is mostly numbers,
punctuation, or English — not useful for Korean financial Q&A retrieval.

**Detection signal**:
```python
too_short  = len(chunk.text_raw.strip()) < 150
low_korean = chunk.korean_ratio < 0.12
flag = too_short or low_korean
```

**Severity**: HARD — blocks indexing.

**Response**: Discard silently. Log total count only — not per-chunk (too noisy). If > 5%
of chunks are discarded by this rule, the section parser is generating too many micro-chunks.

---

### RULE-09: Duplicate and Near-Duplicate Chunk Pollution

**What**:
- **Exact duplicate**: Same `chunk_id` appears more than once in the output file (crash-resume artifact).
- **Near-duplicate**: Two chunks with identical first 200 chars of `text`, same `rcept_no`.

**Why**: TOC sections in DART XMLs list all section titles. After extraction dedup, some
boilerplate sections (audit disclaimer paragraphs, standard risk disclosures) may appear in
both MAIN and CONSOL XML roles and produce semantically identical chunks. These inflate
recall falsely and degrade precision.

**Detection signal**:
```python
import hashlib
seen_ids:   set[str]  = set()
seen_fp:    set[str]  = set()  # fingerprint

for chunk in chunks:
    exact_dup = chunk.chunk_id in seen_ids
    fp = hashlib.md5(chunk.text[:200].encode()).hexdigest()
    near_dup  = fp in seen_fp and chunk.rcept_no == current_rcept_no
    seen_ids.add(chunk.chunk_id)
    seen_fp.add(fp)
```

**Severity**: SOFT — exact dups are hard-filtered; near-dups are flagged.

**Response**:
- Exact duplicate: keep first, discard subsequent. Log count.
- Near-duplicate: keep first occurrence, tag second with `near_duplicate=True`. Do not index
  tagged chunks. Log count as `RULE09_NEAR_DUP`.

---

### RULE-10: Retrieval-Risk Chunk

**What**: Chunk that is technically valid but likely to be retrieved for wrong queries due to
low semantic density.

**Criteria** (any two of three triggers):
```python
low_korean     = chunk.korean_ratio < 0.20
high_numeric   = chunk.contains_table and numeric_ratio > 0.60
short_unique   = len(set(chunk.text_raw.split())) < 30   # fewer than 30 unique tokens
```

**Why**: These chunks have valid metadata and pass all hard rules, but they are semantic
dead weight. They consume index slots and degrade precision without contributing meaningful
recall. The v5 analysis showed that 49% of ctx_precision failures had this profile.

**Severity**: WARNING only — never blocks indexing.

**Response**: Tag `retrieval_risk=True`. These chunks index normally but are excluded from
the RAGAS eval sample set. Monitor count: if > 15% of total chunks, rechunk that section type
with tighter budgets.

---

## SECTION 2 — Bad Chunk Taxonomy

### CAT-01: Detached Number Chunk

**Definition**: A chunk whose content consists primarily of raw numeric values without
co-located Korean label rows. The label row was split into a separate chunk by the table
splitter.

**Example**:
```
[삼성전자 2024년 사업보고서] [연결] 재무상태표
[TABLE]
  2,416,554  1,890,233
  3,120,000  2,750,000
  45,800     31,200
[/TABLE]
```
No column headers. No row labels. Pure numbers.

**Why it harms retrieval**: BGE-M3 encodes this as a number sequence. Any financial query
("현금 금액", "자산 합계") will either match or not match randomly. Precision collapses.

**Detection signal**: `numeric_ratio > 0.70` (RULE-02).

**Severity**: CRITICAL. **Blocks indexing**: YES.

**Remediation**: Fix table splitter to always include header row and at least one label column.
Root cause: `_split_table_content()` firing before first data+label row is accumulated.

---

### CAT-02: Broken Table Chunk

**Definition**: A chunk with `contains_table=True` but the `[TABLE]...[/TABLE]` block
contains only a header row (no data rows), or the markers exist but inner content is empty.

**Example**:
```
[표준전자 2024년 사업보고서] [연결] 재무상태표
(단위: 백만원)
[TABLE]
  구분  당기말  전기말
[/TABLE]
```

**Why it harms retrieval**: The header row alone does not answer any query. Provides one
false signal: the embedding will match "구분 당기말" without providing any financial value.

**Detection signal**: Inner row count < 2 (RULE-03).

**Severity**: MODERATE. **Blocks indexing**: NO (tagged `is_broken_table=True`).

**Remediation**: Table split boundary fell exactly at header row end. Fix: minimum 3 data rows
before first split is allowed.

---

### CAT-03: Ambiguous Scope Chunk

**Definition**: A chunk of type FINANCIAL_TABLE or NOTE_TABLE where `statement_scope=UNKNOWN`
AND the breadcrumb contains no [연결] or [별도] tag.

**Example**:
```
[이수페타시스 2024년 사업보고서] 재무상태표 > 비유동자산
[TABLE]
  구분  당분기말  전기말
  장기대여금  1,240  980
[/TABLE]
```
No scope signal. Could be 연결 or 별도.

**Why it harms retrieval**: The company metadata pre-filter cannot distinguish scope. A query
"이수페타시스 별도 장기대여금" will retrieve both 연결 and 별도 figures, reducing precision.

**Detection signal**: RULE-05 trigger on FIN_TYPES.

**Severity**: HIGH for FIN_TYPES. **Blocks indexing**: NO (tagged `scope_unresolved=True`).

**Remediation**: Expand scope detection window from 200 to 1,000 chars. If still unresolved,
default to `SEPARATE` for 사업보고서 with no 연결 signal (별도는 기본).

---

### CAT-04: Missing Breadcrumb Chunk

**Definition**: `chunk.text` does not begin with the exact `breadcrumb` field value.

**Example** (bad):
```
재무상태표 > 유동자산
[TABLE]
  현금및현금성자산  2,416,554  1,890,233
[/TABLE]
```
No company, no year, no report type prefix.

**Why it harms retrieval**: Without company+year anchor, this chunk has no pre-filter key.
It will appear in every company's retrieval results. Cross-company contamination guaranteed.

**Detection signal**: RULE-04.

**Severity**: CRITICAL. **Blocks indexing**: YES (auto-repair attempted first).

**Remediation**: Prepend breadcrumb from metadata. Re-validate token cap.

---

### CAT-05: Mixed-Section Chunk

**Definition**: A chunk whose content spans two distinct L1 sections (e.g., text from
"재무상태표" continues into "손익계산서" in the same chunk).

**Why it harms retrieval**: The chunk vector averages two section embeddings. Queries
specific to one section (현금흐름표) will retrieve this chunk for the wrong reason.

**Detection signal**:
```python
# Check if chunk.text_raw contains two or more ## level headers
header_count = len(re.findall(r'^## ', chunk.text_raw, re.MULTILINE))
flag = header_count >= 2
```

**Severity**: HIGH. **Blocks indexing**: YES.

**Remediation**: Section boundary was not honored by the parser. `_flush()` must always be
called before a new `##` header is processed. This is a parser bug, not a runtime variance.

---

### CAT-06: Boilerplate-Polluted Chunk

**Definition**: A chunk whose content is dominated by legal boilerplate, standard disclaimer
text, or repeated regulatory language that appears verbatim across all filings.

**Patterns**:
- "이 보고서는 자본시장과 금융투자업에 관한 법률..."
- "이 사업보고서에 기재된 내용 중..."
- Standard audit disclaimer paragraphs (identical across all Big4 firms)

**Detection signal**:
```python
BOILERPLATE_FINGERPRINTS = {
    md5("이 보고서는 자본시장과 금융투자업에 관한 법률").hexdigest(),
    md5("이 사업보고서에 기재된 내용 중 전망에 관한").hexdigest(),
    # ... add after first corpus scan
}
fp = md5(chunk.text_raw[:150].encode()).hexdigest()
flag = fp in BOILERPLATE_FINGERPRINTS
```

**Severity**: MODERATE. **Blocks indexing**: NO (tagged `is_boilerplate=True`).

**Remediation**: Tag and exclude from embedding. These consume index slots and produce
false-positive matches for disclaimer-language queries.

---

### CAT-07: Overlong Chunk

**Definition**: `token_estimate > 6000` (RULE-01). Already defined above.

**Severity**: CRITICAL. **Blocks indexing**: YES.

**Remediation**: Reduce TABLE hard_cap. Investigate which section type produced the overlong
chunk and adjust that type's splitter.

---

### CAT-08: Under-Informative Chunk

**Definition**: `len(text_raw.strip()) < 150` OR `korean_ratio < 0.12` OR fewer than 15
unique Korean words in the chunk.

**Example**:
```
[표준전자 2024년 분기보고서] 주석 > 18. 기타비용
해당사항 없음.
```
3 words. No financial data. No retrieval value.

**Detection signal**:
```python
too_short  = len(chunk.text_raw.strip()) < 150
low_korean = chunk.korean_ratio < 0.12
few_words  = len(set(re.findall(r'[\uAC00-\uD7A3]+', chunk.text_raw))) < 15
flag = too_short or low_korean or (few_words and len(chunk.text_raw) < 300)
```

**Severity**: HIGH. **Blocks indexing**: YES.

**Remediation**: Discard. These are legitimate short responses in the original document.
They cannot be chunked into something more informative — the source text is simply short.

---

### CAT-09: Duplicate-Evidence Chunk

**Definition**: Two chunks within the same `rcept_no` that share identical first 200 chars
of `text`. Caused by TOC re-listing or crash-resume double-write.

**Severity**: MODERATE. **Blocks indexing**: Second occurrence blocked.

**Remediation**: Keep first. Tag second `near_duplicate=True`. This is a known DART document
structure artifact (TOC titles appear again as body section headers). The extractor dedup
handles most cases; this catches stragglers.

---

## SECTION 3 — JSONL Output Standard

### Required Keys (must be present and non-null in every row)

| Key | Type | Constraint |
|-----|------|-----------|
| `chunk_id` | string | `{rcept_no}-{role_code}-{idx:06d}`, globally unique |
| `chunk_idx` | int | Sequential within one (rcept_no, xml_role) pair. Starts at 0. |
| `rcept_no` | string | Exactly 14 ASCII digits. No spaces. |
| `company_name` | string | UTF-8, max 50 chars, no leading/trailing whitespace |
| `fiscal_year` | string | Exactly 4 ASCII digits, e.g. `"2024"` |
| `report_type` | string | One of: 사업보고서, 분기보고서, 반기보고서, 감사보고서, 주요사항보고서, 기타공시 |
| `chunk_type` | string | One of 6 enum values. Stored as `.value` string, not int. |
| `statement_scope` | string | One of: `"CONSOLIDATED"`, `"SEPARATE"`, `"UNKNOWN"` |
| `text` | string | Starts with `breadcrumb`. Single newline-separated. No `\r`. |
| `breadcrumb` | string | Matches exact prefix of `text` field. |
| `l1_section` | string | Non-empty. Falls back to `"전체"` if unparseable. |
| `char_count` | int | `len(text)` at write time. |
| `token_estimate` | int | `round(char_count * 1.8)`. Must be ≤ 6000. |
| `korean_ratio` | float | Rounded to 4 decimal places. Must be ≥ 0.12. |
| `contains_table` | bool | `true` / `false` (JSON boolean, not string). |
| `is_broken_table` | bool | Set by validate_chunks.py after FR-02 check. |
| `has_unit_annotation` | bool | True if `(단위: ...)` found in chunk text. |
| `chunk_version` | string | `"v7"` for this pipeline. |
| `xml_role` | string | One of: `"MAIN"`, `"CONSOL"`, `"SEP"` |

### Optional Keys (may be absent or null)

| Key | Type | When present |
|-----|------|-------------|
| `quarter` | string or null | Present for 분기보고서/반기보고서. `"1Q"`, `"2Q"`, `"3Q"`, `"2H"`. Null otherwise. |
| `l2_section` | string | Present when L2 heading was detected. Empty string is acceptable. |
| `text_raw` | string | Content without breadcrumb prefix. Optional for storage; required for validation. May be omitted in production JSONL to save space. |
| `source_path` | string | Original archive file path. Useful for debugging. May be empty string. |
| `is_boilerplate` | bool | Set by boilerplate detector. Default absent (treat as false). |
| `near_duplicate` | bool | Set by RULE-09 dedup pass. Default absent. |
| `scope_unresolved` | bool | Set by RULE-05 when scope expanded but still UNKNOWN. |
| `retrieval_risk` | bool | Set by RULE-10. Default absent. |
| `validation_status` | string | `"PASS"` / `"WARN"` / `"FAIL"`. Set by validate_chunks.py. |

### Null Handling Policy

- Required keys: **never null**. If source data is unavailable, use defined fallback strings:
  - `fiscal_year`: `"UNKNOWN"` only if truly unextractable (log separately)
  - `l2_section`: empty string `""` not null
  - `quarter`: null (JSON null) is valid
- Optional keys: **absent is preferred over null** for boolean flags. Parsers should treat
  absent flag keys as `false`.
- `text_raw` may be omitted from production output to reduce file size.

### String Normalization Policy

Before writing any string field:
1. Strip leading/trailing whitespace: `str.strip()`
2. Normalize internal whitespace: `re.sub(r'[ \t]{3,}', '  ', s)` (max 2 consecutive spaces)
3. Remove `\r`: `s.replace('\r\n', '\n').replace('\r', '\n')`
4. Remove null bytes: `s.replace('\x00', '')`
5. Strip XML residue: `re.sub(r'<[A-Z\-]{2,}[^>]*>', '', s)`
6. Do NOT strip Korean punctuation or special financial symbols (%, ₩, ±)

### Newline and Escaping

- All newlines in JSON string values: `\n` (JSON escape), never literal newlines
- `json.dumps(d, ensure_ascii=False)` — Korean UTF-8 stored directly, not `\uXXXX` escaped
- Each JSONL row: one complete JSON object, terminated by `\n`
- No trailing comma. No wrapping array brackets.

### chunk_id Uniqueness Rule

`chunk_id = f"{rcept_no}-{role_code}-{idx:06d}"`

- `role_code`: `M` for MAIN, `C` for CONSOL, `S` for SEP
- `idx`: sequential within (rcept_no, role_code) pair, zero-padded to 6 digits
- Global uniqueness relies on rcept_no being globally unique (14-digit DART key)
- If a crash-resume creates duplicate chunk_ids: the downstream dedup pass removes the second
  occurrence. Do not regenerate IDs — the first write wins.

### statement_scope Encoding Rule

- Stored as string: `"CONSOLIDATED"`, `"SEPARATE"`, `"UNKNOWN"`
- Never stored as int or Korean string
- The values `"연결"` and `"별도"` are breadcrumb display strings only — not the stored value
- ChromaDB metadata filter key: `statement_scope`

### text Field Expectations

- First line: exact `breadcrumb` string
- Second character: `\n`
- Remainder: chunk content (narrative, table with markers, or mixed)
- `[TABLE]` and `[/TABLE]` markers preserved in text field
- No HTML, no XML tags, no markdown headers (those were section delimiters in the raw text,
  not carried into chunk content)

### Breadcrumb in text

**Required**: `text.startswith(breadcrumb)` must be `True` at write time.
This is validated by RULE-04. Auto-repair (prepend breadcrumb) is attempted before discard.

### token_estimate Storage

**Required**. Must be stored in every row. This is the downstream embedding pipeline's
primary safeguard against silent truncation. The Colab embedding script must check this
field before passing to BGE-M3:
```python
if row["token_estimate"] > 5500:
    log.warning("Near-limit chunk: %s (%d tokens)", row["chunk_id"], row["token_estimate"])
```

### Provenance Representation

Full provenance chain per chunk:
```json
{
  "rcept_no":    "20240115000001",   // DART 접수번호 — primary key
  "xml_role":    "MAIN",             // which XML file within the ZIP
  "source_path": "C:/Users/.../DataSet/20240115000001.zip",  // optional
  "chunk_version": "v7",             // pipeline version
  "chunk_idx":   42                  // position within this (rcept_no, xml_role)
}
```

---

## SECTION 4 — Example JSONL Rows

### Row 1: Narrative Business-Report Chunk

```json
{"chunk_id":"20240315000427-M-000023","chunk_idx":23,"rcept_no":"20240315000427","company_name":"이수페타시스","fiscal_year":"2024","report_type":"사업보고서","quarter":null,"xml_role":"MAIN","chunk_type":"NARRATIVE","statement_scope":"UNKNOWN","text":"[이수페타시스 2024년 사업보고서] I. 회사의 개요 > 1. 회사의 개요\n당사는 1975년 10월에 설립되어 인쇄회로기판(PCB) 제조 및 판매를 주요 사업으로 영위하고 있습니다. 주요 제품은 MLB(Multi Layer Board), HDI(High Density Interconnect), 기판 등이며, 전자, 통신, 자동차 및 의료 산업에 납품하고 있습니다.\n당사의 주요 고객사는 삼성전자, LG전자 등 국내 대형 전자업체와 해외 OEM 업체들이며, 매출의 약 65% 이상이 수출로 이루어지고 있습니다.","breadcrumb":"[이수페타시스 2024년 사업보고서] I. 회사의 개요 > 1. 회사의 개요","l1_section":"I. 회사의 개요","l2_section":"1. 회사의 개요","char_count":312,"token_estimate":562,"korean_ratio":0.7241,"contains_table":false,"is_broken_table":false,"has_unit_annotation":false,"chunk_version":"v7","source_path":"C:/Users/hibou/Desktop/DataSet/20240315000427.zip","validation_status":"PASS"}
```

### Row 2: Financial Statement Table Chunk

```json
{"chunk_id":"20231229001854-M-000108","chunk_idx":108,"rcept_no":"20231229001854","company_name":"NH투자증권","fiscal_year":"2023","report_type":"사업보고서","quarter":null,"xml_role":"MAIN","chunk_type":"FINANCIAL_TABLE","statement_scope":"SEPARATE","text":"[NH투자증권 2023년 사업보고서] [별도] IV. 재무에 관한 사항 > 재무상태표\n(단위: 백만원)\n[TABLE]\n구분  당기말  전기말\n현금및현금성자산  2,416,554  1,890,233\n당기손익-공정가치측정금융자산  45,812,330  41,203,880\n대출채권  3,120,445  2,750,120\n기타금융자산  980,210  870,450\n소계  52,329,539  46,714,683\n[/TABLE]","breadcrumb":"[NH투자증권 2023년 사업보고서] [별도] IV. 재무에 관한 사항 > 재무상태표","l1_section":"IV. 재무에 관한 사항","l2_section":"재무상태표","char_count":398,"token_estimate":716,"korean_ratio":0.3819,"contains_table":true,"is_broken_table":false,"has_unit_annotation":true,"chunk_version":"v7","source_path":"C:/Users/hibou/Desktop/DataSet/20231229001854.zip","validation_status":"PASS"}
```

### Row 3: Audit Opinion Chunk

```json
{"chunk_id":"20240315000427-C-000003","chunk_idx":3,"rcept_no":"20240315000427","company_name":"이수페타시스","fiscal_year":"2024","report_type":"사업보고서","quarter":null,"xml_role":"CONSOL","chunk_type":"AUDIT_OPINION","statement_scope":"CONSOLIDATED","text":"[이수페타시스 2024년 사업보고서] [연결] 감사보고서 > 감사의견\n우리는 이수페타시스 주식회사와 그 종속기업들의 2024년 12월 31일로 종료되는 회계연도의 연결재무제표에 대한 감사를 실시하였습니다. 해당 연결재무제표는 연결재무상태표, 연결손익계산서, 연결포괄손익계산서, 연결자본변동표, 연결현금흐름표 및 유의적인 회계정책의 요약을 포함한 주석으로 구성되어 있습니다.\n감사의견: 우리의 의견으로는, 위에서 언급된 연결재무제표는 이수페타시스 주식회사와 그 종속기업들의 2024년 12월 31일 현재의 재무상태와 동일로 종료되는 회계연도의 재무성과 및 현금흐름을 한국채택국제회계기준에 따라 중요성의 관점에서 적정하게 표시하고 있습니다.","breadcrumb":"[이수페타시스 2024년 사업보고서] [연결] 감사보고서 > 감사의견","l1_section":"감사보고서","l2_section":"감사의견","char_count":528,"token_estimate":950,"korean_ratio":0.8523,"contains_table":false,"is_broken_table":false,"has_unit_annotation":false,"chunk_version":"v7","source_path":"C:/Users/hibou/Desktop/DataSet/20240315000427.zip","validation_status":"PASS"}
```

---

## SECTION 5 — Batch Execution Rules

### Processing Unit Hierarchy

```
Level 1 — Archive (per rcept_no):
  Unit of checkpointing. One rcept_no = one atomic unit.
  If any XML within the archive fails, the rcept_no is NOT marked complete.
  Must complete all XMLs before calling complete_rcept_no().

Level 2 — XML file (per xml_role within archive):
  Unit of extraction and chunking. Failures at this level are logged but do not
  abort the archive — other XML roles continue processing.
  A MAIN XML failure = log WARN, mark xml_role="MAIN" as failed, continue.
  Zero chunks from MAIN = log ERROR, still complete archive (empty output is valid).

Level 3 — Chunk (individual ChunkRecord):
  Unit of validation. Failures at chunk level (hard rules) discard that chunk.
  Never propagates to archive or XML level.
```

### Checkpoint Frequency

- **Default**: every 50 completed rcept_nos
- **On exception**: write checkpoint before re-raising or continuing (in finally block)
- **On SIGINT** (Ctrl+C): catch signal, write checkpoint, exit cleanly
- **Never**: checkpoint mid-archive (partial rcept_no in checkpoint = skipped on resume)
- Checkpoint file: `{output_path}.checkpoint.json` — atomic write via tmp+rename

### Success Marking

A rcept_no is marked complete (`complete_rcept_no()` called) when:
1. All XML files in the archive have been processed (success or failure per-XML)
2. All resulting chunks have been written to the output file
3. The file handle has been flushed

### Failure Marking

Archive-level failure (rcept_no NOT marked complete):
- `zipfile.BadZipFile` — unreadable archive
- Unhandled exception during extraction or chunking
- All XML files return zero chunks AND `company_name == "UNKNOWN"`

XML-level failure (logged, does not propagate):
- `extract_dart4_xml()` returns text < 100 chars
- All chunks from this XML fail validation (zero passing chunks)

Failure log format (one JSON per line in `{output}.failures.jsonl`):
```json
{"ts":"2026-04-14T20:31:05Z","level":"ERROR","rcept_no":"20240115000001","xml_role":"MAIN","error_type":"BadZipFile","detail":"File is not a zip file","path":"C:/Users/.../20240115000001.zip.pdf"}
```

### Retry Strategy

- **No automatic retry** within the same run. Retry = resume from checkpoint.
- On resume, all non-completed rcept_nos are retried from scratch.
- If a rcept_no fails 3 consecutive runs: add to a permanent skip list (`{output}.skip.json`).
  The skip list is checked at the start of each archive iteration.
- Permanent skip threshold: 3 failures. Rationale: 3 failures across separate runs indicates
  a corrupt archive, not a transient error.

### Resume Strategy

On script start:
1. Load `completed_rcept_nos` from checkpoint
2. Load `skip_list` from skip.json (if exists)
3. `iter_archives()` yields all rcept_nos from DataSet
4. Per archive: `if rcept_no in completed or rcept_no in skip: continue`
5. Normal processing on remaining

No need to read the output JSONL to determine resume state.
The checkpoint is authoritative. The output file is append-only.

### Progress Log Format

Every 50 archives processed, emit one INFO line:
```
HH:MM:SS INFO [312/3138] 9.9% | 6.2 docs/s | ETA 44m | chunks=89,420 | FR_hard=234 | errors=3
```

Fields:
- `[processed/total]` — archive count
- `%` — completion percentage
- `docs/s` — archives per second (rolling 50-doc window)
- `ETA` — estimated time to completion
- `chunks` — cumulative chunks written to output
- `FR_hard` — cumulative hard-rule discards (RULE-01, RULE-02, RULE-06, RULE-08)
- `errors` — cumulative archive-level errors (rcept_nos not completed)

### Failure Log Format

Per-failure line in `{output}.failures.jsonl`:
```json
{"ts":"ISO8601","level":"ERROR|WARN","rcept_no":"14digits","xml_role":"MAIN|CONSOL|SEP|N/A","error_type":"ClassName","detail":"message","path":"archive_path"}
```

### Output Directory Expectations

All output files share the same stem as `--output`:
```
{stem}.jsonl              — main chunk output (append mode)
{stem}.checkpoint.json    — resume state
{stem}.failures.jsonl     — per-failure log
{stem}.skip.json          — permanent skip list
{stem}.run_report.json    — written at end of run (Section 6 fields)
```

If `--output` is `/tmp/chunks_v7.jsonl`, all four companion files land in `/tmp/`.
The output directory must exist before run start. The pipeline does not create directories.

### When to Stop the Pipeline

**Hard stop** (abort entire run, write checkpoint first):
- Disk free space < 500 MB
- Output file cannot be opened for append (permissions error)
- Checkpoint file cannot be written (disk full or locked)

**Continue with warnings**:
- Single archive BadZipFile
- Single XML extraction yields zero chunks
- FR hard-rule discard rate for a single archive > 50% (log ERROR, continue)

**Run is considered INVALID** (do not use output for embedding):
- > 10% of total rcept_nos ended in archive-level failure
- > 20% of total chunks discarded by hard rules
- checkpoint.json was not written (crash before first checkpoint)
- output.jsonl contains zero lines

---

## SECTION 6 — Inspection and Reporting Layer

The `{output}.run_report.json` file is written at end of every run.
If the run was interrupted, write a partial report anyway in the `finally` block.

### Mandatory Metrics

These fields are **required** in every run report. Without them, the run cannot be assessed:

```json
{
  "run_id":              "20260414-203105",
  "pipeline_version":    "v7",
  "completed_at":        "2026-04-14T21:15:33Z",
  "duration_seconds":    4468,
  "status":              "COMPLETE",

  "archives": {
    "total_in_dataset":   3138,
    "processed":          3138,
    "completed":          3124,
    "failed":             14,
    "skipped_checkpoint": 0,
    "skipped_skip_list":  0
  },

  "xml_files": {
    "total_extracted":    7821,
    "role_distribution":  {"MAIN": 3138, "CONSOL": 2412, "SEP": 2271}
  },

  "chunks": {
    "total_written":       487_230,
    "discarded_hard":       12_841,
    "discarded_soft_tagged":  8_920,
    "discard_rate_pct":      2.63,
    "type_distribution": {
      "NARRATIVE":       198_410,
      "FINANCIAL_TABLE":  89_320,
      "NOTE_TABLE":       91_200,
      "NOTE_NARRATIVE":   74_100,
      "AUDIT_OPINION":    18_900,
      "FACT_SUMMARY":     15_300
    },
    "avg_token_estimate_by_type": {
      "NARRATIVE":        640,
      "FINANCIAL_TABLE":  1520,
      "NOTE_TABLE":        480,
      "NOTE_NARRATIVE":    440,
      "AUDIT_OPINION":    1380,
      "FACT_SUMMARY":      290
    }
  },

  "scope_distribution": {
    "CONSOLIDATED":  201_440,
    "SEPARATE":      198_870,
    "UNKNOWN":        86_920
  },

  "validation": {
    "RULE01_TOKEN_CAP":        42,
    "RULE02_BROKEN_TABLE":    894,
    "RULE03_SCOPE_MIXED":      18,
    "RULE04_MISSING_BREADCRUMB": 6,
    "RULE05_SCOPE_UNKNOWN_FIN": 1_240,
    "RULE06_MISSING_METADATA": 103,
    "RULE07_MALFORMED_TEXT":   441,
    "RULE08_EMPTY":          9_812,
    "RULE09_DUPLICATE":        220,
    "RULE10_RETRIEVAL_RISK":  8_900
  },

  "quality_signals": {
    "avg_korean_ratio":       0.4821,
    "pct_chunks_with_table":  36.8,
    "pct_has_unit_annotation": 28.4,
    "pct_scope_resolved":     82.2,
    "pct_broken_table":        0.18
  }
}
```

**Why these are mandatory**:
- `archives.failed` > 0 triggers manual review before embedding
- `chunks.discard_rate_pct` > 5% triggers chunker investigation
- `scope_distribution.UNKNOWN` > 20% means pre-filter will miss 1 in 5 financial queries
- `validation.RULE01_TOKEN_CAP` > 0 means silent truncation will happen at embedding time
- `quality_signals.pct_broken_table` > 1% means table splitter needs fixing

### Optional Metrics

- Per-company chunk count distribution (useful for detecting companies with zero output)
- Per-report-type average chunk count
- Histogram of `char_count` values (detect bimodal distributions)
- Top-20 companies by chunk count (sanity check: Samsung should dominate)

---

## SECTION 7 — Go / No-Go Checklist

This checklist is evaluated **before launching the full 3,138-document run**.
Every item must be GREEN. A single RED is a NO-GO.

### 1. Metadata Completeness Readiness

```
[ ] company_meta.json covers >= 95% of rcept_nos in DataSet
    Verify: python detect_archives.py DataSet/ > /tmp/all_rcept.txt
            python check_meta_coverage.py company_meta.json /tmp/all_rcept.txt
    Threshold: < 5% UNKNOWN company_name in 10-file smoke test output
[ ] fiscal_year extractable for >= 95% of archives
    Verify: check smoke test run_report.json — no "UNKNOWN" in type_distribution keys
[ ] report_type classification correct
    Verify: manual spot-check 5 random entries from each report_type bucket
```

### 2. Validation Readiness

```
[ ] RULE-01 zero violations in 10-file smoke test
    Hard cap means chunker is buggy if any appear.
[ ] RULE-02 (broken table) < 2% in smoke test
    Acceptable to ship; > 5% = fix splitter first
[ ] RULE-06 (missing metadata) zero violations
    Zero tolerance. Any missing company_name = metadata gap = fix first
[ ] RULE-08 (empty chunk) discard rate < 5% in smoke test
    > 10% = section parser generating too many micro-chunks
[ ] validate_chunks.py imports cleanly, runs against smoke test output, produces report
```

### 3. Resume Readiness

```
[ ] Checkpoint file written correctly after 10-file smoke test
[ ] Resume test: delete last 3 entries from checkpoint, re-run, verify only those 3 re-processed
[ ] Duplicate chunk count = 0 after resume test
    (Downstream dedup handles crash-induced dups, but resume should not introduce dups)
[ ] ChunkWriter opens in append mode (verify: file size increases, not resets)
```

### 4. Logging Readiness

```
[ ] Progress log emitted every 50 archives during smoke test
[ ] failures.jsonl written for any BadZipFile in smoke test (inject one manually to test)
[ ] run_report.json written at end of smoke test, all mandatory fields present
[ ] Log level INFO shows doc/s and ETA; DEBUG shows per-XML chunk counts
```

### 5. Scope-Handling Readiness

```
[ ] CONSOL scope correctly detected for 연결 filings in smoke test
    Verify: at least one CONSOLIDATED chunk in run_report scope_distribution
[ ] SEP scope correctly detected for 별도 sections
[ ] UNKNOWN scope rate < 25% for FINANCIAL_TABLE chunks in smoke test
    > 25% = _detect_scope() window too narrow — expand to 1000 chars
[ ] Breadcrumb contains [연결] / [별도] tag when scope is resolved
    Spot-check 3 FINANCIAL_TABLE chunks manually
```

### 6. NOTE Handling Readiness

```
[ ] NOTE_TABLE chunks present in smoke test output (verify type_distribution)
[ ] NOTE_TABLE avg_token_estimate < 700 (within hard_cap)
[ ] NOTE_NARRATIVE overlap=80 working (check two adjacent NOTE_NARRATIVE chunks share tail)
[ ] Note section boundary not crossed (l1_section="주석" consistent within note chunks)
```

### 7. Table Handling Readiness

```
[ ] FINANCIAL_TABLE chunks contain [TABLE]...[/TABLE] markers
[ ] Header row present in every FINANCIAL_TABLE chunk (is_broken_table rate = 0 in smoke test)
[ ] 합계 rows not stranded alone (FR-12 count = 0 in smoke test)
[ ] unit_annotation (단위: 백만원) injected into table chunk prefix where available
[ ] pct_has_unit_annotation > 20% for FINANCIAL_TABLE chunks in smoke test
```

### 8. Bad-Chunk Detection Readiness

```
[ ] CAT-01 (detached number) = 0 in smoke test
    If > 0, fix table splitter before full run — this is a hard blocker
[ ] CAT-05 (mixed-section) = 0 in smoke test
    If > 0, section boundary flushing is broken — hard blocker
[ ] RULE-09 (duplicate) count = 0 on clean run (not resume test)
[ ] retrieval_risk tagging functional: at least some chunks tagged in smoke test
```

### 9. Local Resource Safety Readiness

```
[ ] 10-file smoke test CPU stays < 75°C throughout
    Monitor: Task Manager > Performance > CPU temperature
    If approaching 75°C: throttle with time.sleep(0.1) between archives
[ ] Peak RAM during smoke test < 2 GB
    A single 8MB ZIP should never push beyond 200 MB peak
[ ] Disk free space > 5 GB before full run
    Expected output size: 3138 archives × ~160 KB/archive = ~500 MB
    With safety margin: 5 GB minimum
[ ] No antivirus real-time scan on DataSet directory
    Windows Defender scanning 3,138 ZIPs = 3-4x slowdown. Exclude DataSet/ before run.
```

---

## SECTION 8 — Final Recommended Operating Defaults

### Token Budgets (chars)

```python
BUDGETS = {
    "NARRATIVE":       {"target": 800,  "hard_cap": 1200, "overlap": 100},
    "FINANCIAL_TABLE": {"target": 1800, "hard_cap": 2800, "overlap": 0},
    "NOTE_TABLE":      {"target": 500,  "hard_cap": 700,  "overlap": 0},
    "NOTE_NARRATIVE":  {"target": 500,  "hard_cap": 700,  "overlap": 80},
    "AUDIT_OPINION":   {"target": 1800, "hard_cap": 3500, "overlap": 0},
    "FACT_SUMMARY":    {"target": 300,  "hard_cap": 400,  "overlap": 0},
}
MIN_CHUNK_LENGTH   = 150
KOREAN_RATIO_MIN   = 0.12
TOKEN_RATIO        = 1.8
MAX_TOKEN_ESTIMATE = 6000   # FR-11 ceiling
CHAR_CEILING       = 3334   # ceil(6000 / 1.8)
```

### Metadata Minimum Set

Every chunk must carry these 7 fields at minimum:
```
chunk_id, company_name, rcept_no, fiscal_year,
statement_scope, chunk_type, breadcrumb
```

If any of these cannot be populated, the chunk does not index.

### Validation Thresholds

| Metric | Threshold | Action if exceeded |
|--------|-----------|-------------------|
| RULE-01 (token cap) | 0 violations | STOP — chunker bug |
| RULE-06 (missing meta) | 0 violations | STOP — metadata gap |
| RULE-08 (empty) discard rate | < 5% | WARN; > 10% = STOP |
| RULE-02 (broken table) rate | < 2% | WARN; > 5% = STOP |
| UNKNOWN scope on FIN_TYPES | < 25% | WARN; > 40% = STOP |
| Archive failure rate | < 1% | WARN; > 10% = STOP, run INVALID |
| Overall hard-discard rate | < 5% | WARN; > 20% = run INVALID |

### Duplicate Tolerance

- Exact duplicates (same chunk_id): zero tolerance. Dedup on write.
- Near-duplicates (same first-200-char fingerprint, same rcept_no): tag and skip second.
  Max acceptable rate: < 2% of chunks per rcept_no.
- Cross-rcept_no near-duplicates (boilerplate): tag `is_boilerplate=True`, do not index.

### Logging Granularity

```
INFO:  Progress every 50 archives. Start/end messages. Checkpoint events.
WARN:  Per-archive soft failures. RULE-02, RULE-05 triggers. High discard rates.
ERROR: Archive-level failures. RULE-01, RULE-06 triggers. Missing metadata batches.
DEBUG: Per-XML chunk counts. Scope detection results. Table split decisions.
```

Production run: `--log-level INFO`
Debugging: `--log-level DEBUG` on `--sample 10`

### Checkpoint Granularity

- Default: every 50 completed rcept_nos
- Minimum: 1 (every archive) — use only for debugging, halves throughput
- Maximum: 200 — only if disk I/O is a bottleneck (NAS, network drive)
- Recommended for Colab: 25 (Colab sessions disconnect without warning)

### Resume Behavior

On restart:
1. Load checkpoint — treat as authoritative
2. Never re-read output JSONL to infer state
3. Skip completed rcept_nos without processing
4. Skip skip-listed rcept_nos without processing
5. Append to existing output file (never overwrite)
6. Do not regenerate chunk_ids — use the same deterministic formula

### Failure Policy

| Failure type | Response |
|-------------|----------|
| BadZipFile | Log ERROR, write to failures.jsonl, mark failed, continue |
| XML parse error | Log WARN, skip that XML role, continue with other roles |
| Zero chunks from archive | Log WARN, complete_rcept_no() (empty output is valid) |
| Disk full | Checkpoint, abort run cleanly |
| Python exception (unhandled) | Checkpoint in finally, re-raise |
| 3rd consecutive failure for same rcept_no | Add to skip.json, never retry |

### Indexing Gate Policy

A chunk is indexed (written to JSONL) if and only if:
1. `token_estimate <= 6000` (RULE-01 PASS)
2. `korean_ratio >= 0.12` (RULE-08 PASS)
3. `len(text_raw.strip()) >= 150` (RULE-08 PASS)
4. `numeric_ratio <= 0.70` (RULE-02 PASS)
5. All 7 required metadata fields are non-empty and non-UNKNOWN (RULE-06 PASS)
6. `text.startswith(breadcrumb)` (RULE-04 PASS or auto-repaired)
7. `near_duplicate != True` (RULE-09 dedup)

Soft tags (`is_broken_table`, `retrieval_risk`, `scope_unresolved`, `is_boilerplate`) do not
block indexing. They are carried in the JSONL for downstream filtering decisions.

The embedding pipeline on Colab should apply one additional gate:
```python
# Skip chunks that are boilerplate or near-duplicate
if row.get("is_boilerplate") or row.get("near_duplicate"):
    continue
```

This is the only gate that should be re-applied at embed time. All other gates were enforced
at write time and are guaranteed by the chunk_version="v7" contract.
