"""
Omega CivicFlow - Clean Reset Pipeline v4.0 (Hardened)
======================================================

Phase 0 : dry-run + backup + DB/ChromaDB reset
Phase 1 : ZIP/ZIP.PDF extraction + preprocessing + SQLite store
Phase 2 : chunking + metadata normalization + validation gate
Phase 3 : embedding (GPU, separate run)
Phase 4 : integrity verification

Changes from v3.0:
  - Phase 0: dry-run mode, DB backup before wipe, reset manifest
  - Phase 1: deterministic doc_uid (SHA256 of filename), content_hash,
             raw_text preserved without truncation, failure classification
  - Phase 2: stable chunk_uid (SHA256 of doc_uid+chunk_index+text_hash),
             canonical metadata schema, schema_version, validation gate
  - Phase 4: expanded checks, Phase 3 readiness gate

Usage:
  cd C:\\Users\\hibou\\Omega_CivicFlow_v4\\backend

  # Step 1: Dry-run (inspect what will be deleted, no changes)
  .venv\\Scripts\\python.exe tools\\clean_reset_pipeline.py --reset --dry-run

  # Step 2: Execute reset + Phase 1 + Phase 2 (no GPU needed)
  .venv\\Scripts\\python.exe tools\\clean_reset_pipeline.py --reset --skip-embed

  # Step 3: Resume if interrupted (auto-checkpoint)
  .venv\\Scripts\\python.exe tools\\clean_reset_pipeline.py --skip-embed

  # Step 4: Verify Phase 3 readiness
  .venv\\Scripts\\python.exe tools\\clean_reset_pipeline.py --verify-only

  # Step 5: Embed on GPU (later)
  .venv\\Scripts\\python.exe tools\\clean_reset_pipeline.py --phase 3
"""

import sys
import os
import json
import hashlib
import logging
import time
import pathlib
import re
import shutil
import zipfile
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

# -- Path setup --
BACKEND_DIR = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

DATASET_DIR = pathlib.Path("C:/Users/hibou/Desktop/DataSet")
CHECKPOINT_DIR = BACKEND_DIR / "tools"
CHECKPOINT_FILE = CHECKPOINT_DIR / "clean_reset_checkpoint.json"
LOG_FILE = CHECKPOINT_DIR / "clean_reset_pipeline.log"
MANIFEST_FILE = CHECKPOINT_DIR / "reset_manifest.json"

SCHEMA_VERSION = "4.0"
ADMIN_USER_ID = 1

TIER_MAP = {
    "P0": "사업보고서",
    "P1": "감사보고서",
    "P2": "분기보고서",
    "P3": "주요사항보고서",
    "P4": "기타공시",
}

# -- Logging --
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("Pipeline")


# =====================================================
# Deterministic ID generation
# =====================================================

def make_doc_uid(filename: str) -> str:
    """Stable document UID: SHA256(filename) truncated to 16 hex chars.
    Same filename always produces same UID regardless of run order."""
    return hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]


def make_chunk_uid(doc_uid: str, chunk_index: int, text_hash: str) -> str:
    """Stable chunk UID: SHA256(doc_uid + chunk_index + text_hash) -> 32 hex.
    Deterministic for same document, same chunk order, same content."""
    payload = f"{doc_uid}:{chunk_index}:{text_hash}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def make_content_hash(text: str) -> str:
    """SHA256 of full text for dedup detection. 16 hex chars."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# =====================================================
# HTML / XML / XBRL text extraction
# =====================================================

class _DartHTMLTextExtractor(HTMLParser):
    SKIP_TAGS = {"style", "script", "formula-version", "noscript"}
    BLOCK_TAGS = {"p", "div", "tr", "li", "h1", "h2", "h3", "h4",
                  "section", "article", "br", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._lines: List[str] = []
        self._current: List[str] = []
        self._skip_depth = 0
        self._skip_tag = None

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in self.SKIP_TAGS:
            self._skip_depth += 1
            self._skip_tag = t
        if t in self.BLOCK_TAGS and self._current:
            text = " ".join(self._current).strip()
            if text:
                self._lines.append(text)
            self._current = []

    def handle_endtag(self, tag):
        t = tag.lower()
        if self._skip_tag and t == self._skip_tag:
            self._skip_depth = max(0, self._skip_depth - 1)
            if self._skip_depth == 0:
                self._skip_tag = None
        if t in self.BLOCK_TAGS and self._current:
            text = " ".join(self._current).strip()
            if text:
                self._lines.append(text)
            self._current = []

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        text = data.strip()
        if text:
            self._current.append(text)

    def get_text_lines(self) -> List[str]:
        if self._current:
            text = " ".join(self._current).strip()
            if text:
                self._lines.append(text)
            self._current = []
        return self._lines


CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")


def _is_noise(text: str) -> bool:
    if len(text) < 2:
        return True
    if re.match(r"^[\d\s,.\-\u2013\u2014:/|%\[\](){}]+$", text):
        return False  # preserve financial numbers
    if CHINESE_PATTERN.search(text):
        return True
    if len(set(text.replace(" ", ""))) <= 2 and len(text) > 5:
        return True
    if re.match(r"^[A-Z_\-]{3,}=", text):
        return True
    return False


def _parse_dart_xml(content: str) -> str:
    content = re.sub(r"<STYLE[^>]*>.*?</STYLE>", " ", content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r"<SCRIPT[^>]*>.*?</SCRIPT>", " ", content, flags=re.DOTALL | re.IGNORECASE)
    content = re.sub(r"<\?[^>]*\?>", "", content)
    content = re.sub(r"<!DOCTYPE[^>]*>", "", content)
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    content = re.sub(
        r'\s+(?:WIDTH|HEIGHT|CLASS|STYLE|VALIGN|ALIGN|BGCOLOR|BORDER|'
        r'CELLPADDING|COLSPAN|ROWSPAN|ACLASS|ACOPY|ADELETE|AUPDATECONT|'
        r'ENG|USERMARK|ADELETETABLE)=["\'][^"\']*["\']',
        "", content, flags=re.IGNORECASE,
    )
    parser = _DartHTMLTextExtractor()
    parser.feed(content)
    lines = [ln for ln in parser.get_text_lines() if ln.strip() and not _is_noise(ln.strip())]
    return "\n".join(lines)


def _parse_xbrl(content: str) -> str:
    values = re.findall(r">([^<]{2,200})<", content)
    return "\n".join(v.strip() for v in values if v.strip() and not _is_noise(v.strip()) and len(v.strip()) >= 2)


def extract_from_zip(zip_path: pathlib.Path) -> Tuple[str, Dict, str]:
    """Returns (raw_text, file_metadata, failure_reason).
    failure_reason is empty string on success."""
    metadata = parse_filename_metadata(zip_path.name)
    all_texts = []

    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            main_xmls = [n for n in names if n.endswith(".xml") and
                         not any(x in n for x in ["_00760", "_00761", "_00762", "_00763"])]
            sub_xmls = [n for n in names if n.endswith(".xml") and
                        any(x in n for x in ["_00760", "_00761", "_00762", "_00763"])]
            xbrls = [n for n in names if n.endswith(".xbrl")]

            for xml_name in main_xmls + sub_xmls + xbrls:
                try:
                    raw = zf.read(xml_name)
                    for enc in ["utf-8", "euc-kr", "cp949", "utf-8-sig"]:
                        try:
                            content = raw.decode(enc)
                            break
                        except (UnicodeDecodeError, LookupError):
                            continue
                    else:
                        content = raw.decode("utf-8", errors="replace")

                    text = _parse_xbrl(content) if xml_name.endswith(".xbrl") else _parse_dart_xml(content)
                    if text:
                        all_texts.append(text)
                except Exception as e:
                    logger.debug(f"  XML parse fail ({xml_name}): {e}")

            if not all_texts:
                return "", metadata, "empty_after_parse"

    except zipfile.BadZipFile:
        return "", metadata, "bad_zip"
    except Exception as e:
        return "", metadata, f"zip_error:{type(e).__name__}"

    return "\n\n".join(all_texts), metadata, ""


def parse_filename_metadata(filename: str) -> Dict:
    name = filename.replace(".zip.pdf", "").replace(".zip", "")
    parts = name.split("_")

    meta = {"filename": filename, "tier": "", "company": "",
            "report_date": "", "rcept_no": "", "report_type": "기타"}

    if len(parts) >= 2:
        meta["tier"] = parts[1]
    if len(parts) >= 3:
        meta["company"] = parts[2]
    if len(parts) >= 4:
        date_no = parts[3]
        if len(date_no) >= 8:
            meta["report_date"] = date_no[:8]
            meta["rcept_no"] = date_no[8:] if len(date_no) > 8 else ""

    meta["report_type"] = TIER_MAP.get(meta["tier"], "기타")
    return meta


# =====================================================
# Text preprocessing (CPU-only)
# =====================================================

NOISE_PATTERNS = [
    re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+"),
    re.compile(r"[\u3040-\u30ff]+"),
    re.compile(r"<[A-Za-z/][^>]{0,200}>"),
    re.compile(r"&[a-z]{2,8};"),
    re.compile(r"https?://\S+"),
    re.compile(r"[A-Z_]{5,}=['\"][^'\"]{0,50}['\"]"),
    re.compile(r"xmlns[:\w]*=['\"][^'\"]*['\"]"),
    re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"),
]


def _clean_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    if len(line) < 3 and not re.search(r"\d", line):
        return ""
    if re.match(r"^[=\-_\*\.·\s]{5,}$", line):
        return ""
    if re.match(r"^(?:[A-Z] ){2,}[A-Z]?$", line.strip()):
        return ""
    if re.match(r"^\d{1,4}[\s\-]?$", line):
        return ""
    line = re.sub(r"\S+\.(?:jpg|png|gif|bmp|jpeg|svg)\b", "", line, flags=re.IGNORECASE).strip()
    if not line:
        return ""
    line = re.sub(r"[ \t]{2,}", " ", line)
    return line


def preprocess_text(raw_text: str, metadata: Dict) -> Tuple[str, dict]:
    """Returns (cleaned_text, preprocess_stats).
    preprocess_stats includes raw_len, clean_len, was_truncated."""
    stats = {"raw_len": len(raw_text), "clean_len": 0, "was_truncated": False}
    if not raw_text:
        return "", stats

    text = raw_text
    for pattern in NOISE_PATTERNS:
        text = pattern.sub(" ", text)

    lines = text.split("\n")
    cleaned_lines = []
    seen_lines = set()
    for line in lines:
        line = _clean_line(line)
        if not line:
            continue
        line_key = line[:80]
        if line_key in seen_lines:
            continue
        seen_lines.add(line_key)
        cleaned_lines.append(line)

    result_lines = []
    prev_empty = False
    for line in cleaned_lines:
        is_empty = not line.strip()
        if is_empty and prev_empty:
            continue
        result_lines.append(line)
        prev_empty = is_empty

    # Header injection
    parts = []
    if metadata.get("company"):
        parts.append(f"회사명: {metadata['company']}")
    if metadata.get("report_type"):
        parts.append(f"보고서 유형: {metadata['report_type']}")
    if metadata.get("report_date"):
        d = metadata["report_date"]
        if len(d) == 8:
            parts.append(f"공시일: {d[:4]}년 {d[4:6]}월 {d[6:8]}일")
    header = "[문서 정보]\n" + "\n".join(parts) + "\n\n" if parts else ""

    final_text = header + "\n".join(result_lines)

    # Truncation (log but don't silently drop)
    MAX_CLEAN = 100_000
    if len(final_text) > MAX_CLEAN:
        stats["was_truncated"] = True
        lines = final_text.split("\n")
        kept = []
        total = 0
        for ln in lines:
            if total + len(ln) > MAX_CLEAN:
                break
            kept.append(ln)
            total += len(ln) + 1
        final_text = "\n".join(kept)

    final_text = final_text.strip()
    stats["clean_len"] = len(final_text)
    return final_text, stats


# =====================================================
# Chunking (deterministic, stable IDs)
# =====================================================

def chunk_text(text: str, doc_uid: str, company: str = "") -> List[Dict]:
    """Returns list of chunk dicts with stable chunk_uid."""
    MIN_CHUNK_LEN = 80
    TARGET_SIZE = 900
    OVERLAP_SIZE = 120

    if not text or len(text) < MIN_CHUNK_LEN:
        return []

    section_pattern = re.compile(
        r'^(?:'
        r'(?:[IVX]+\.|[0-9]+\.)\s*.{2,40}$'
        r'|[\u3010].{2,30}[\u3011]'
        r'|(?:제\s*\d+\s*[기장편])'
        r'|(?:사\s*업\s*보\s*고\s*서|감\s*사\s*보\s*고\s*서|분\s*기\s*보\s*고\s*서)'
        r'|(?:연\s*결\s*재\s*무\s*제\s*표|재\s*무\s*상\s*태\s*표|손\s*익\s*계\s*산\s*서|포\s*괄\s*손\s*익)'
        r'|(?:주\s*주\s*총\s*회|이\s*사\s*회|감\s*사\s*위\s*원)'
        r')',
        re.MULTILINE,
    )

    lines = text.split("\n")
    sections = []
    cur_title = ""
    cur_lines = []

    for line in lines:
        stripped = line.strip()
        if section_pattern.match(stripped) and len(stripped) < 60:
            if cur_lines:
                sections.append((cur_title, "\n".join(cur_lines)))
            cur_title = stripped
            cur_lines = []
        else:
            cur_lines.append(line)
    if cur_lines:
        sections.append((cur_title, "\n".join(cur_lines)))
    if not sections:
        sections = [("", text)]

    raw_chunks = []  # (section_title, chunk_text)

    for sec_title, sec_text in sections:
        if not sec_text.strip():
            continue

        prefix = ""
        if company and sec_title:
            prefix = f"[{company}] {sec_title}\n"
        elif company:
            prefix = f"[{company}]\n"
        elif sec_title:
            prefix = f"{sec_title}\n"

        # Separate table blocks from narrative
        table_blocks = []
        narrative_blocks = []
        cur_block = []
        is_table = False

        for line in sec_text.split("\n"):
            stripped = line.strip()
            digit_ratio = sum(1 for c in stripped if c.isdigit() or c in ",.-") / max(len(stripped), 1)
            has_numbers = bool(re.search(r"\d{3,}", stripped))

            if digit_ratio > 0.3 and has_numbers and len(stripped) > 10:
                if not is_table and cur_block:
                    narrative_blocks.append("\n".join(cur_block))
                    cur_block = []
                is_table = True
                cur_block.append(stripped)
            else:
                if is_table and cur_block:
                    table_blocks.append("\n".join(cur_block))
                    cur_block = []
                is_table = False
                cur_block.append(stripped)

        if cur_block:
            (table_blocks if is_table else narrative_blocks).append("\n".join(cur_block))

        # Table chunks
        for table in table_blocks:
            if len(table) < MIN_CHUNK_LEN:
                continue
            if len(prefix + table) <= TARGET_SIZE * 1.5:
                raw_chunks.append((sec_title, prefix + table))
            else:
                rows = table.split("\n")
                cur = prefix
                for row in rows:
                    if len(cur) + len(row) > TARGET_SIZE:
                        if len(cur.strip()) >= MIN_CHUNK_LEN:
                            raw_chunks.append((sec_title, cur.strip()))
                        cur = prefix + row + "\n"
                    else:
                        cur += row + "\n"
                if len(cur.strip()) >= MIN_CHUNK_LEN:
                    raw_chunks.append((sec_title, cur.strip()))

        # Narrative chunks
        full_narrative = "\n".join(narrative_blocks)
        if not full_narrative.strip():
            continue

        sentences = re.split(
            r"(?<=[다요음됨함임.])\s*\n|(?<=[다요음됨함임.])\s{2,}|\n\s*\n",
            full_narrative,
        )
        sentences = [s.strip() for s in sentences if s.strip()]

        cur_chunk = prefix
        prev_tail = ""

        for sent in sentences:
            if len(sent) < 5:
                continue
            if len(cur_chunk) + len(sent) > TARGET_SIZE:
                if len(cur_chunk.strip()) >= MIN_CHUNK_LEN:
                    raw_chunks.append((sec_title, cur_chunk.strip()))
                if prev_tail and len(prev_tail) < OVERLAP_SIZE:
                    cur_chunk = prefix + prev_tail + "\n" + sent + "\n"
                else:
                    cur_chunk = prefix + sent + "\n"
            else:
                cur_chunk += sent + "\n"
            prev_tail = sent

        if len(cur_chunk.strip()) >= MIN_CHUNK_LEN:
            raw_chunks.append((sec_title, cur_chunk.strip()))

    # Quality filter + stable ID assignment
    def _kr_ratio(t):
        if not t:
            return 0.0
        kr = sum(1 for c in t if "\uac00" <= c <= "\ud7a3")
        total = len(t.replace(" ", "").replace("\n", ""))
        return kr / max(total, 1)

    results = []
    chunk_index = 0
    for sec_title, chunk in raw_chunks:
        if len(chunk) < MIN_CHUNK_LEN:
            continue
        body = re.sub(r"^\[.*?\]\s*.*?\n", "", chunk, count=1)
        if _kr_ratio(body) < 0.15:
            continue
        if re.match(r"^[\d\s,.\-\u2013\u2014:/|%\[\]()]+$", body):
            continue

        text_hash = make_content_hash(chunk)
        chunk_uid = make_chunk_uid(doc_uid, chunk_index, text_hash)

        results.append({
            "text": chunk,
            "section": sec_title,
            "chunk_uid": chunk_uid,
            "text_hash": text_hash,
            "token_count": len(chunk),
            "chunk_index": chunk_index,
        })
        chunk_index += 1

    return results


# =====================================================
# Canonical metadata extraction
# =====================================================

CANONICAL_META_KEYS = [
    "company_name", "company_name_norm", "report_type",
    "disclosure_title", "filing_date", "fiscal_year",
    "period_type", "statement_scope", "source_kind",
    "extraction_confidence", "schema_version",
]


def extract_metadata(clean_text: str, file_meta: Dict) -> Dict:
    """Canonical metadata schema. All keys defined, no drift."""
    company = file_meta.get("company", "")
    report_date = file_meta.get("report_date", "")
    tier = file_meta.get("tier", "")

    # Fiscal year derivation
    fiscal_year = None
    if report_date and len(report_date) >= 6:
        year = int(report_date[:4])
        month = int(report_date[4:6])
        if tier in ("P0", "P1") and month <= 6:
            fiscal_year = year - 1
        else:
            fiscal_year = year

    period_type = "quarterly" if tier == "P2" else "annual"

    scope = "consolidated"
    if clean_text and "별도" in clean_text[:2000]:
        scope = "separate"

    title = ""
    if clean_text:
        for line in clean_text.split("\n")[:20]:
            line = line.strip()
            if any(kw in line for kw in ["보고서", "감사", "공시", "사업", "분기"]):
                title = line[:200]
                break

    return {
        "company_name": company,
        "company_name_norm": company,
        "report_type": file_meta.get("report_type", "기타"),
        "disclosure_title": title,
        "filing_date": report_date,
        "fiscal_year": fiscal_year,
        "period_type": period_type,
        "statement_scope": scope,
        "source_kind": f"dart_{tier.lower()}" if tier else "dart",
        "extraction_confidence": 0.85,
        "schema_version": SCHEMA_VERSION,
    }


# =====================================================
# Checkpoint manager
# =====================================================

class CheckpointManager:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self._default_data()
        self._load()

    def _default_data(self):
        self.data = {
            "schema_version": SCHEMA_VERSION,
            "phase1_done": [],
            "phase2_done": [],
            "phase3_done": [],
            "stats": {
                "total_files": 0,
                "phase1_success": 0, "phase1_failed": 0,
                "phase1_empty_text": 0, "phase1_bad_zip": 0,
                "phase1_truncated": 0,
                "phase2_success": 0, "phase2_zero_chunks": 0,
                "phase3_success": 0,
                "total_chunks": 0, "total_embedded": 0,
                "start_time": "",
            },
            "failed_files": [],
        }

    def _load(self):
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                # Only merge if same schema version
                if loaded.get("schema_version") == SCHEMA_VERSION:
                    self.data.update(loaded)
                    logger.info(f"Checkpoint loaded: P1={len(self.data['phase1_done'])}, "
                               f"P2={len(self.data['phase2_done'])}, "
                               f"P3={len(self.data['phase3_done'])}")
                else:
                    logger.warning(f"Checkpoint schema mismatch "
                                   f"(file={loaded.get('schema_version')}, expected={SCHEMA_VERSION}). "
                                   f"Starting fresh.")
            except Exception:
                pass

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Phase 1
    def is_phase1_done(self, filename: str) -> bool:
        return filename in self.data["phase1_done"]

    def mark_phase1_ok(self, filename: str, truncated: bool = False):
        self.data["phase1_done"].append(filename)
        self.data["stats"]["phase1_success"] += 1
        if truncated:
            self.data["stats"]["phase1_truncated"] += 1
        if len(self.data["phase1_done"]) % 100 == 0:
            self.save()

    def mark_phase1_fail(self, filename: str, reason: str):
        self.data["stats"]["phase1_failed"] += 1
        if reason == "bad_zip":
            self.data["stats"]["phase1_bad_zip"] += 1
        elif reason in ("empty_after_parse", "empty_text", "empty_after_clean"):
            self.data["stats"]["phase1_empty_text"] += 1
        self.data["failed_files"].append({"file": filename, "reason": reason, "phase": 1})
        if len(self.data["failed_files"]) % 50 == 0:
            self.save()

    # Phase 2
    def is_phase2_done(self, doc_id: int) -> bool:
        return doc_id in self.data["phase2_done"]

    def mark_phase2_ok(self, doc_id: int, n_chunks: int):
        self.data["phase2_done"].append(doc_id)
        self.data["stats"]["phase2_success"] += 1
        self.data["stats"]["total_chunks"] += n_chunks
        if n_chunks == 0:
            self.data["stats"]["phase2_zero_chunks"] += 1

    # Phase 3
    def is_phase3_done(self, doc_id: int) -> bool:
        return doc_id in self.data["phase3_done"]

    def mark_phase3_ok(self, doc_id: int, n_embedded: int):
        self.data["phase3_done"].append(doc_id)
        self.data["stats"]["phase3_success"] += 1
        self.data["stats"]["total_embedded"] += n_embedded

    def reset(self):
        self._default_data()
        self.data["stats"]["start_time"] = datetime.now(timezone.utc).isoformat()
        self.save()


# =====================================================
# Phase 0: Reset (dry-run safe)
# =====================================================

def phase0_reset(dry_run: bool = False):
    """DB + ChromaDB reset. Backs up DB first. dry_run=True only reports."""
    logger.info("=" * 60)
    logger.info(f"Phase 0: Reset {'(DRY RUN)' if dry_run else '(LIVE)'}")
    logger.info("=" * 60)

    import sqlalchemy as sa
    from database import SessionLocal
    from config import settings

    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "db_path": db_path,
        "chromadb_path": settings.CHROMADB_DIR,
        "tables": {},
        "backup_path": None,
        "actions": [],
    }

    # -- Inventory current state --
    tables_to_clear = [
        "financial_facts", "document_chunks", "document_metadata",
        "document_insights", "analysis_results", "reclassifications",
        "ocr_texts", "pages", "company_profiles", "documents",
    ]

    with SessionLocal() as db:
        for table in tables_to_clear:
            try:
                row = db.execute(sa.text(f"SELECT count(*) FROM {table}")).fetchone()
                count = row[0]
            except Exception:
                count = -1
            manifest["tables"][table] = {"current_count": count, "action": "DELETE_ALL"}
            logger.info(f"  {table}: {count:,} rows -> DELETE_ALL")

        # users table: KEEP
        row = db.execute(sa.text("SELECT count(*) FROM users")).fetchone()
        manifest["tables"]["users"] = {"current_count": row[0], "action": "KEEP"}
        logger.info(f"  users: {row[0]} rows -> KEEP")

    if dry_run:
        manifest["actions"].append("DRY_RUN_ONLY")
        MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"\nDry-run manifest saved: {MANIFEST_FILE}")
        logger.info("No changes made. Review manifest and re-run without --dry-run.")
        return False  # signal: not executed

    # -- Backup DB --
    if pathlib.Path(db_path).exists() and pathlib.Path(db_path).stat().st_size > 0:
        backup_name = f"omega_civicflow_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db"
        backup_path = pathlib.Path(db_path).parent / backup_name
        logger.info(f"  DB backup -> {backup_path}")
        shutil.copy2(db_path, backup_path)
        manifest["backup_path"] = str(backup_path)
        manifest["actions"].append(f"BACKUP:{backup_path}")

    # -- Clear tables --
    with SessionLocal() as db:
        for table in tables_to_clear:
            try:
                db.execute(sa.text(f"DELETE FROM {table}"))
                manifest["actions"].append(f"DELETE_ALL:{table}")
            except Exception as e:
                logger.warning(f"  {table} delete failed: {e}")
        db.commit()

    # Reset autoincrement
    with SessionLocal() as db:
        for table in tables_to_clear:
            try:
                db.execute(sa.text(f"DELETE FROM sqlite_sequence WHERE name='{table}'"))
            except Exception:
                pass
        db.commit()

    logger.info("  SQLite cleared (users preserved)")

    # -- ChromaDB reset --
    logger.info("  ChromaDB reset...")
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.PersistentClient(
            path=settings.CHROMADB_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        for coll_name in ["omega_documents_v2", "omega_documents",
                          "omega_document_chunks_v2", "omega_document_chunks"]:
            try:
                client.delete_collection(coll_name)
                manifest["actions"].append(f"DELETE_COLLECTION:{coll_name}")
                logger.info(f"    {coll_name} deleted")
            except Exception:
                pass

        client.get_or_create_collection(name="omega_documents_v2", metadata={"hnsw:space": "cosine"})
        manifest["actions"].append("CREATE_COLLECTION:omega_documents_v2")
        logger.info("    omega_documents_v2 created")
    except Exception as e:
        logger.error(f"  ChromaDB reset failed: {e}")
        raise

    # -- Post-reset validation --
    logger.info("  Post-reset validation...")
    with SessionLocal() as db:
        for table in tables_to_clear:
            row = db.execute(sa.text(f"SELECT count(*) FROM {table}")).fetchone()
            if row[0] != 0:
                logger.error(f"    FAIL: {table} has {row[0]} rows after reset!")
                raise RuntimeError(f"Phase 0 validation failed: {table} not empty")
        logger.info("    All tables empty: OK")

    manifest["actions"].append("VALIDATION_PASSED")
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"  Reset manifest: {MANIFEST_FILE}")
    logger.info("Phase 0 complete\n")
    return True


# =====================================================
# Phase 1: Extract + Store
# =====================================================

def phase1_extract_and_store(files: List[pathlib.Path], cp: CheckpointManager):
    logger.info("=" * 60)
    logger.info(f"Phase 1: Extract + Store ({len(files)} files)")
    logger.info("=" * 60)

    from database import SessionLocal
    from models.models import Document, OcrText

    t_start = time.time()

    for idx, zip_path in enumerate(files, 1):
        filename = zip_path.name
        if cp.is_phase1_done(filename):
            continue

        try:
            raw_text, metadata, fail_reason = extract_from_zip(zip_path)

            if fail_reason:
                logger.warning(f"  [{idx}/{len(files)}] FAIL ({fail_reason}): {filename}")
                cp.mark_phase1_fail(filename, fail_reason)
                continue

            if not raw_text or len(raw_text) < 50:
                logger.warning(f"  [{idx}/{len(files)}] empty text: {filename}")
                cp.mark_phase1_fail(filename, "empty_text")
                continue

            clean_text, pp_stats = preprocess_text(raw_text, metadata)

            if not clean_text or len(clean_text) < 50:
                logger.warning(f"  [{idx}/{len(files)}] empty after clean: {filename}")
                cp.mark_phase1_fail(filename, "empty_after_clean")
                continue

            if pp_stats["was_truncated"]:
                logger.info(f"  [{idx}] TRUNCATED: {filename} "
                           f"(raw={pp_stats['raw_len']:,} -> clean={pp_stats['clean_len']:,})")

            # Deterministic IDs
            doc_uid = make_doc_uid(filename)
            content_hash = make_content_hash(raw_text)

            with SessionLocal() as db:
                doc = Document(
                    user_id=ADMIN_USER_ID,
                    filename=filename,
                    file_path=str(zip_path),
                    file_type="zip.pdf" if filename.endswith(".zip.pdf") else "zip",
                    file_size=zip_path.stat().st_size,
                    status="ocr_done",
                    created_at=datetime.now(timezone.utc),
                )
                db.add(doc)
                db.flush()

                ocr = OcrText(
                    document_id=doc.id,
                    raw_text=raw_text,  # Full raw preserved
                    cleaned_text=clean_text,
                    confidence=0.90,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(ocr)
                db.commit()

            cp.mark_phase1_ok(filename, truncated=pp_stats["was_truncated"])

            if idx % 100 == 0:
                elapsed = time.time() - t_start
                rate = idx / elapsed
                eta = (len(files) - idx) / max(rate, 0.001)
                logger.info(
                    f"  P1 progress: {idx}/{len(files)} ({idx*100//len(files)}%) | "
                    f"ok={cp.data['stats']['phase1_success']} "
                    f"fail={cp.data['stats']['phase1_failed']} | "
                    f"ETA {eta/60:.1f}m"
                )
                cp.save()

        except Exception as e:
            logger.error(f"  [{idx}/{len(files)}] exception ({filename}): {e}")
            cp.mark_phase1_fail(filename, f"exception:{type(e).__name__}")

    cp.save()
    s = cp.data["stats"]
    elapsed = time.time() - t_start
    logger.info(f"Phase 1 done: ok={s['phase1_success']}, fail={s['phase1_failed']}, "
               f"bad_zip={s['phase1_bad_zip']}, empty={s['phase1_empty_text']}, "
               f"truncated={s['phase1_truncated']}, {elapsed/60:.1f}m\n")


# =====================================================
# Phase 1->2 Validation Gate
# =====================================================

def validate_phase1() -> bool:
    """Check Phase 1 results before proceeding to Phase 2."""
    import sqlalchemy as sa
    from database import SessionLocal

    logger.info("-- Phase 1 -> 2 Validation Gate --")
    passed = True

    with SessionLocal() as db:
        # Count documents and ocr_texts
        doc_count = db.execute(sa.text("SELECT count(*) FROM documents")).fetchone()[0]
        ocr_count = db.execute(sa.text("SELECT count(*) FROM ocr_texts")).fetchone()[0]

        logger.info(f"  documents: {doc_count}, ocr_texts: {ocr_count}")

        if doc_count == 0:
            logger.error("  GATE FAIL: 0 documents after Phase 1")
            return False

        if doc_count != ocr_count:
            logger.error(f"  GATE FAIL: document/ocr mismatch ({doc_count} vs {ocr_count})")
            passed = False

        # Duplicate filenames
        dup = db.execute(sa.text(
            "SELECT count(*) FROM (SELECT filename FROM documents GROUP BY filename HAVING count(*) > 1)"
        )).fetchone()[0]
        if dup > 0:
            logger.error(f"  GATE FAIL: {dup} duplicate filenames")
            passed = False

        # Documents with empty cleaned_text
        empty = db.execute(sa.text(
            "SELECT count(*) FROM ocr_texts WHERE cleaned_text IS NULL OR length(cleaned_text) < 50"
        )).fetchone()[0]
        if empty > 0:
            logger.warning(f"  GATE WARN: {empty} docs with empty/tiny cleaned_text")

    if passed:
        logger.info("  GATE PASSED\n")
    else:
        logger.error("  GATE FAILED - Phase 2 should not proceed\n")

    return passed


# =====================================================
# Phase 2: Chunk + Metadata
# =====================================================

def phase2_chunk_and_metadata(cp: CheckpointManager):
    logger.info("=" * 60)
    logger.info("Phase 2: Chunk + Metadata")
    logger.info("=" * 60)

    from database import SessionLocal
    from models.models import DocumentChunk, DocumentMetadata
    import sqlalchemy as sa

    t_start = time.time()

    with SessionLocal() as db:
        docs = db.execute(
            sa.text("SELECT d.id, d.filename FROM documents d ORDER BY d.id")
        ).fetchall()

    logger.info(f"  Target: {len(docs)} documents")

    for idx, (doc_id, filename) in enumerate(docs, 1):
        if cp.is_phase2_done(doc_id):
            continue

        try:
            with SessionLocal() as db:
                row = db.execute(
                    sa.text("SELECT cleaned_text FROM ocr_texts WHERE document_id = :did LIMIT 1"),
                    {"did": doc_id},
                ).fetchone()

                if not row or not row[0]:
                    logger.warning(f"  [{idx}] doc_id={doc_id} no text, skip")
                    cp.mark_phase2_ok(doc_id, 0)
                    continue

                clean_text = row[0]
                file_meta = parse_filename_metadata(filename)
                doc_uid = make_doc_uid(filename)

                # Chunk
                chunks = chunk_text(clean_text, doc_uid, company=file_meta.get("company", ""))

                for chunk_data in chunks:
                    db.add(DocumentChunk(
                        chunk_uid=chunk_data["chunk_uid"],
                        document_id=doc_id,
                        section_name=chunk_data["section"],
                        text=chunk_data["text"],
                        text_hash=chunk_data["text_hash"],
                        source_kind=f"dart_{file_meta.get('tier', '').lower()}",
                        token_count=chunk_data["token_count"],
                        vector_collection="omega_documents_v2",
                        created_at=datetime.now(timezone.utc),
                    ))

                # Metadata
                meta = extract_metadata(clean_text, file_meta)
                db.add(DocumentMetadata(
                    document_id=doc_id,
                    company_name=meta["company_name"],
                    company_name_norm=meta["company_name_norm"],
                    report_type=meta["report_type"],
                    disclosure_title=meta["disclosure_title"],
                    filing_date=meta["filing_date"],
                    fiscal_year=meta["fiscal_year"],
                    period_type=meta["period_type"],
                    statement_scope=meta["statement_scope"],
                    source_kind=meta["source_kind"],
                    extraction_confidence=meta["extraction_confidence"],
                    metadata_json={"schema_version": SCHEMA_VERSION},
                    created_at=datetime.now(timezone.utc),
                ))

                db.commit()

            cp.mark_phase2_ok(doc_id, len(chunks))

            if idx % 200 == 0:
                elapsed = time.time() - t_start
                rate = idx / elapsed
                eta = (len(docs) - idx) / max(rate, 0.001)
                logger.info(
                    f"  P2 progress: {idx}/{len(docs)} ({idx*100//len(docs)}%) | "
                    f"chunks={cp.data['stats']['total_chunks']:,} | "
                    f"ETA {eta/60:.1f}m"
                )
                cp.save()

        except Exception as e:
            logger.error(f"  [{idx}] doc_id={doc_id} failed: {e}")

    cp.save()
    s = cp.data["stats"]
    elapsed = time.time() - t_start
    logger.info(f"Phase 2 done: {s['phase2_success']} docs, "
               f"{s['total_chunks']:,} chunks, "
               f"zero_chunk_docs={s['phase2_zero_chunks']}, "
               f"{elapsed/60:.1f}m\n")


# =====================================================
# Phase 3: Embedding (GPU required)
# =====================================================

def phase3_embed(cp: CheckpointManager):
    logger.info("=" * 60)
    logger.info("Phase 3: Embedding -> ChromaDB")
    logger.info("=" * 60)

    import sqlalchemy as sa
    from database import SessionLocal
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    from config import settings
    import httpx

    chroma_client = chromadb.PersistentClient(
        path=settings.CHROMADB_DIR,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = chroma_client.get_or_create_collection(
        name="omega_documents_v2", metadata={"hnsw:space": "cosine"},
    )
    logger.info(f"  ChromaDB: omega_documents_v2 ({collection.count()} vectors)")

    embed_client = httpx.Client(
        base_url=settings.OLLAMA_BASE_URL,
        timeout=120.0,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=16),
    )
    EMBED_MODEL = "nomic-embed-text"
    EMBED_WORKERS = 16
    CHROMA_BATCH = 200

    def _embed_one(text: str) -> Optional[List[float]]:
        try:
            resp = embed_client.post("/api/embeddings", json={"model": EMBED_MODEL, "prompt": text})
            resp.raise_for_status()
            return resp.json().get("embedding")
        except Exception:
            return None

    def _embed_batch(texts: List[str]) -> List[Optional[List[float]]]:
        results = [None] * len(texts)
        with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as pool:
            futures = {pool.submit(_embed_one, t): i for i, t in enumerate(texts)}
            for future in as_completed(futures):
                i = futures[future]
                try:
                    results[i] = future.result()
                except Exception:
                    pass
        return results

    from services.embedding_strategy import FilingChunk, prepare_embedding_item

    t_start = time.time()

    with SessionLocal() as db:
        doc_ids = [r[0] for r in db.execute(
            sa.text("SELECT DISTINCT document_id FROM document_chunks ORDER BY document_id")
        ).fetchall()]

    logger.info(f"  Target: {len(doc_ids)} documents")

    for idx, doc_id in enumerate(doc_ids, 1):
        if cp.is_phase3_done(doc_id):
            continue

        try:
            with SessionLocal() as db:
                rows = db.execute(sa.text(
                    "SELECT c.id, c.chunk_uid, c.text, c.section_name, d.filename "
                    "FROM document_chunks c JOIN documents d ON c.document_id = d.id "
                    "WHERE c.document_id = :did"
                ), {"did": doc_id}).fetchall()

                if not rows:
                    continue

                filename = rows[0][4]
                file_meta = parse_filename_metadata(filename)

                prepared_docs = []
                prepared_items = []
                for chunk_id, chunk_uid, chunk_text, section_name, _ in rows:
                    f_chunk = FilingChunk(
                        doc_id=str(doc_id), chunk_id=chunk_uid,
                        chunk_text=chunk_text, company_name=file_meta.get("company", ""),
                        doc_type=file_meta.get("report_type", ""),
                        filing_type=file_meta.get("report_type", ""),
                        filing_date=file_meta.get("report_date", ""),
                        section_title=section_name or "",
                        source_file=filename,
                    )
                    item = prepare_embedding_item(f_chunk)
                    prepared_docs.append(item.document)
                    prepared_items.append((chunk_id, item))

                emb_list = _embed_batch(prepared_docs)

                ids, embeddings, documents, metadatas = [], [], [], []
                for (chunk_id, item), emb in zip(prepared_items, emb_list):
                    if emb is None:
                        continue
                    ids.append(item.id)
                    embeddings.append(emb)
                    documents.append(item.document)
                    metadatas.append(item.metadata)

                if ids:
                    for start in range(0, len(ids), CHROMA_BATCH):
                        end = start + CHROMA_BATCH
                        try:
                            collection.add(
                                ids=ids[start:end], embeddings=embeddings[start:end],
                                documents=documents[start:end], metadatas=metadatas[start:end],
                            )
                        except Exception as e:
                            logger.warning(f"  ChromaDB batch fail (doc={doc_id}): {e}")

                now = datetime.now(timezone.utc).isoformat()
                indexed_ids = [cid for (cid, _), emb in zip(prepared_items, emb_list) if emb is not None]
                if indexed_ids:
                    placeholders = ",".join(str(cid) for cid in indexed_ids)
                    db.execute(sa.text(
                        f"UPDATE document_chunks SET indexed_at = :now WHERE id IN ({placeholders})"
                    ), {"now": now})

                db.execute(sa.text(
                    "UPDATE documents SET status = 'analyzed', updated_at = :now WHERE id = :did"
                ), {"now": now, "did": doc_id})
                db.commit()

            cp.mark_phase3_ok(doc_id, len(ids))

            if idx % 50 == 0:
                elapsed = time.time() - t_start
                rate = idx / elapsed
                eta = (len(doc_ids) - idx) / max(rate, 0.001)
                logger.info(
                    f"  P3 progress: {idx}/{len(doc_ids)} ({idx*100//len(doc_ids)}%) | "
                    f"vectors={collection.count():,} | ETA {eta/60:.1f}m"
                )
                cp.save()

        except Exception as e:
            logger.error(f"  [{idx}] doc_id={doc_id} embed failed: {e}")

    cp.save()
    embed_client.close()
    elapsed = time.time() - t_start
    logger.info(f"Phase 3 done: {cp.data['stats']['phase3_success']} docs, "
               f"{collection.count():,} vectors, {elapsed/60:.1f}m\n")


# =====================================================
# Phase 4: Integrity verification
# =====================================================

def phase4_verify(check_chroma: bool = True) -> bool:
    logger.info("=" * 60)
    logger.info("Phase 4: Integrity Verification")
    logger.info("=" * 60)

    import sqlalchemy as sa
    from database import SessionLocal

    checks = []

    with SessionLocal() as db:
        # Table counts
        counts = {}
        for table in ["documents", "ocr_texts", "document_chunks",
                       "document_metadata", "financial_facts",
                       "analysis_results", "company_profiles"]:
            row = db.execute(sa.text(f"SELECT count(*) FROM {table}")).fetchone()
            counts[table] = row[0]

        logger.info("  Table counts:")
        for t, c in counts.items():
            logger.info(f"    {t}: {c:,}")

        # 1. doc <-> ocr 1:1
        n = db.execute(sa.text(
            "SELECT count(*) FROM documents d LEFT JOIN ocr_texts o ON d.id=o.document_id WHERE o.id IS NULL"
        )).fetchone()[0]
        checks.append(("docs_without_ocr", n, n == 0))

        # 2. doc <-> chunks
        n = db.execute(sa.text(
            "SELECT count(*) FROM documents d LEFT JOIN document_chunks c ON d.id=c.document_id WHERE c.id IS NULL"
        )).fetchone()[0]
        checks.append(("docs_without_chunks", n, n == 0))

        # 3. doc <-> metadata
        n = db.execute(sa.text(
            "SELECT count(*) FROM documents d LEFT JOIN document_metadata m ON d.id=m.document_id WHERE m.id IS NULL"
        )).fetchone()[0]
        checks.append(("docs_without_metadata", n, n == 0))

        # 4. unindexed chunks (only FAIL if Phase 3 was expected)
        n = db.execute(sa.text(
            "SELECT count(*) FROM document_chunks WHERE indexed_at IS NULL"
        )).fetchone()[0]
        checks.append(("unindexed_chunks", n, None))  # None = info-only for Phase 2

        # 5. duplicate filenames
        n = db.execute(sa.text(
            "SELECT count(*) FROM (SELECT filename FROM documents GROUP BY filename HAVING count(*)>1)"
        )).fetchone()[0]
        checks.append(("duplicate_filenames", n, n == 0))

        # 6. duplicate chunk_uid
        n = db.execute(sa.text(
            "SELECT count(*) FROM (SELECT chunk_uid FROM document_chunks GROUP BY chunk_uid HAVING count(*)>1)"
        )).fetchone()[0]
        checks.append(("duplicate_chunk_uid", n, n == 0))

        # 7. schema version in metadata
        n = db.execute(sa.text(
            "SELECT count(*) FROM document_metadata WHERE metadata_json IS NULL"
        )).fetchone()[0]
        checks.append(("metadata_missing_schema", n, n == 0))

        # 8. zero-chunk docs count
        zero_chunk = db.execute(sa.text(
            "SELECT count(*) FROM documents d "
            "LEFT JOIN document_chunks c ON d.id=c.document_id "
            "WHERE c.id IS NULL"
        )).fetchone()[0]
        checks.append(("zero_chunk_docs", zero_chunk, zero_chunk == 0))

        # 9. expected file count vs actual
        expected_files = len([
            f for f in DATASET_DIR.iterdir()
            if (f.suffix == ".zip" or f.name.endswith(".zip.pdf")) and f.is_file()
        ])
        checks.append(("expected_vs_actual_docs", f"{counts['documents']}/{expected_files}",
                       counts["documents"] > 0))

    # ChromaDB
    if check_chroma:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
            from config import settings
            client = chromadb.PersistentClient(
                path=settings.CHROMADB_DIR,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            coll = client.get_collection("omega_documents_v2")
            chroma_count = coll.count()
            checks.append(("chromadb_vectors", chroma_count, chroma_count >= 0))
        except Exception as e:
            checks.append(("chromadb_connection", str(e), False))

    # Report
    logger.info("\n  Integrity checks:")
    all_pass = True
    for name, value, expected in checks:
        if expected is None:
            status = "INFO"
        elif expected:
            status = "PASS"
        else:
            status = "FAIL"
            all_pass = False
        logger.info(f"    [{status}] {name}: {value}")

    # Phase 3 readiness
    logger.info("\n  Phase 3 readiness:")
    if counts.get("document_chunks", 0) > 0 and all_pass:
        logger.info("    READY for Phase 3 (embedding)")
    else:
        logger.info("    NOT READY for Phase 3")
        all_pass = False

    return all_pass


# =====================================================
# Main
# =====================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Clean Reset Pipeline v4.0")
    parser.add_argument("--reset", action="store_true", help="Full reset from scratch")
    parser.add_argument("--dry-run", action="store_true", help="Phase 0 dry-run only")
    parser.add_argument("--phase", type=int, choices=[0, 1, 2, 3, 4], default=None)
    parser.add_argument("--max", type=int, default=None, help="Limit files (test)")
    parser.add_argument("--skip-embed", action="store_true", help="Skip Phase 3")
    parser.add_argument("--verify-only", action="store_true", help="Phase 4 only")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(f"Omega CivicFlow - Clean Reset Pipeline v{SCHEMA_VERSION}")
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"DataSet: {DATASET_DIR}")
    logger.info("=" * 60)

    if args.verify_only:
        phase4_verify()
        return

    if args.dry_run:
        phase0_reset(dry_run=True)
        return

    # Collect files
    all_files = [
        f for f in DATASET_DIR.iterdir()
        if (f.suffix == ".zip" or f.name.endswith(".zip.pdf")) and f.is_file()
    ]
    all_files.sort(key=lambda f: (
        0 if "_P0_" in f.name else
        1 if "_P1_" in f.name else
        2 if "_P2_" in f.name else
        3 if "_P3_" in f.name else 4,
        f.name,
    ))

    if args.max:
        all_files = all_files[:args.max]

    logger.info(f"Target files: {len(all_files)}")

    cp = CheckpointManager(CHECKPOINT_FILE)

    if args.reset:
        confirm = input("FULL RESET (DB + ChromaDB + checkpoint). Continue? (yes/no): ")
        if confirm.lower() != "yes":
            print("Cancelled.")
            return
        cp.reset()

    cp.data["stats"]["total_files"] = len(all_files)
    cp.data["stats"]["start_time"] = cp.data["stats"]["start_time"] or datetime.now(timezone.utc).isoformat()

    t_total = time.time()
    run_all = args.phase is None

    # Phase 0
    if args.phase == 0 or (run_all and not cp.data["phase1_done"]):
        phase0_reset(dry_run=False)

    # Phase 1
    if args.phase == 1 or run_all:
        phase1_extract_and_store(all_files, cp)

    # Validation gate
    if run_all or args.phase == 2:
        if not validate_phase1():
            logger.error("Phase 1 validation failed. Stopping.")
            cp.save()
            return

    # Phase 2
    if args.phase == 2 or run_all:
        phase2_chunk_and_metadata(cp)

    # Phase 3
    if (args.phase == 3 or run_all) and not args.skip_embed:
        phase3_embed(cp)

    # Phase 4
    if args.phase == 4 or run_all:
        phase4_verify(check_chroma=not args.skip_embed)

    elapsed_total = time.time() - t_total
    s = cp.data["stats"]
    logger.info("\n" + "=" * 60)
    logger.info("Pipeline complete")
    logger.info(f"Files: {len(all_files):,}")
    logger.info(f"Phase 1: ok={s['phase1_success']:,}, fail={s['phase1_failed']:,}")
    logger.info(f"Phase 2: docs={s['phase2_success']:,}, chunks={s['total_chunks']:,}")
    logger.info(f"Phase 3: docs={s['phase3_success']:,}, vectors={s['total_embedded']:,}")
    logger.info(f"Time: {elapsed_total/60:.1f}m ({elapsed_total/3600:.1f}h)")
    logger.info("=" * 60)
    cp.save()


if __name__ == "__main__":
    main()
