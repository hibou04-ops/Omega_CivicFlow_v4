"""
extract_dart_xml.py
===================
ZIP bytes -> List[ExtractedXML]

DART4 XML tag set:
  COVER-TITLE, BODY, SECTION-1, SECTION-2, TITLE, P,
  TABLE, TR, TH, TD, TU, TE, PGBRK
"""
from __future__ import annotations

import io
import re
import zipfile
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XML role constants
# ---------------------------------------------------------------------------

XML_ROLE_MAIN   = "MAIN"    # {rcept_no}.xml
XML_ROLE_CONSOL = "CONSOL"  # {rcept_no}_00760.xml  연결 감사보고서
XML_ROLE_SEP    = "SEP"     # {rcept_no}_00761.xml  별도 감사보고서

_AUDIT_SUFFIX_MAP: dict[str, str] = {
    "_00760": XML_ROLE_CONSOL,
    "_00761": XML_ROLE_SEP,
}

_ENC_RE = re.compile(rb'encoding=["\']([^"\']+)["\']', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

@dataclass
class ExtractedXML:
    rcept_no: str
    xml_role: str           # "MAIN" | "CONSOL" | "SEP"
    raw_text: str           # structured text output
    xml_filename: str       # original name inside ZIP
    company_name: str = ""  # from <COMPANY-NAME> tag
    char_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.char_count = len(self.raw_text)


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------

def _detect_encoding(raw: bytes) -> str:
    """Read encoding from XML declaration; fall back to UTF-8."""
    m = _ENC_RE.search(raw[:200])
    if m:
        return m.group(1).decode("ascii", errors="replace").lower()
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    return "utf-8"


def _safe_decode(raw: bytes) -> str:
    enc = _detect_encoding(raw)
    for fallback in (enc, "cp949", "latin-1"):
        try:
            return raw.decode(fallback)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# DART4 XML -> structured text
# ---------------------------------------------------------------------------

def _table_to_text(table_el: Tag) -> str:
    """
    DART4 TABLE -> row-per-line text.
    TH (header), TD (data), TU (unit annotation), TE (empty/spacer).
    Cells joined with two spaces so label-value stays on the same line.
    """
    rows: list[str] = []
    for tr in table_el.find_all("TR", recursive=False):
        cells: list[str] = []
        for cell in tr.find_all(["TH", "TD", "TU", "TE"], recursive=False):
            txt = cell.get_text(separator=" ", strip=True)
            if txt:
                cells.append(txt)
        if cells:
            rows.append("  ".join(cells))
    return "\n".join(rows)


def _process_element(el: Tag, parts: list[str], depth: int = 0) -> None:
    """
    Recursive DART4 XML traversal.
    Appends structured text lines to `parts`.
    """
    tag = el.name or ""

    # Transparent container tags: recurse into children
    _RECURSE_TAGS = {
        "SECTION-1", "SECTION-2", "BODY", "COVER",
        "LIBRARY", "CORRECTION", "ATTACHMENT", "REFERENCE",
        "TABLE-GROUP", "TBODY", "COLGROUP",
    }

    if tag in _RECURSE_TAGS:
        level_inc = 1 if tag in ("SECTION-1", "SECTION-2") else 0
        for child in el.children:
            if hasattr(child, "name") and child.name:
                _process_element(child, parts, depth + level_inc)

    elif tag == "TITLE":
        title = el.get_text(separator=" ", strip=True)
        if title:
            marker = "##" if depth <= 1 else "###"
            parts.append(f"\n{marker} {title}")

    elif tag == "P":
        para = el.get_text(separator=" ", strip=True)
        if para:
            parts.append(para)

    elif tag == "TABLE":
        tbl = _table_to_text(el)
        if tbl.strip():
            parts.append(f"[TABLE]\n{tbl}\n[/TABLE]")

    elif tag == "PGBRK":
        parts.append("")

    else:
        # Unknown leaf tag: recurse if it has child elements,
        # otherwise extract text (prevents get_text() on container nodes)
        child_tags = [c for c in el.children if hasattr(c, "name") and c.name]
        if child_tags:
            for child in child_tags:
                _process_element(child, parts, depth)
        else:
            txt = el.get_text(separator=" ", strip=True)
            if txt and len(txt) > 5:
                parts.append(txt)


# 주식회사/(주) 접미사 제거: '네이버 주식회사' → '네이버'
_CORP_SUFFIX_RE  = re.compile(r'\s*(?:주식회사|㈜|\(주\)|\(株\))\s*$', re.IGNORECASE)
_CORP_PREFIX_RE  = re.compile(r'^\s*(?:주식회사|㈜|\(주\)|\(株\))\s*', re.IGNORECASE)


def _extract_company_name_from_soup(soup: BeautifulSoup) -> str:
    """
    <COMPANY-NAME> 태그에서 공식 한국어 회사명 추출.
    파일명의 NAVER/F&F 같은 영문 ticker 대신 등록 법인명 사용.
    """
    cn = soup.find("COMPANY-NAME")
    if cn:
        name = cn.get_text(strip=True)
        name = _CORP_SUFFIX_RE.sub("", name).strip()
        name = _CORP_PREFIX_RE.sub("", name).strip()
        if name:
            return name
    return ""


def extract_dart4_xml(raw_bytes: bytes) -> tuple[str, str]:
    """
    Parse DART4 XML bytes -> (structured_text, company_name).

    company_name: from <COMPANY-NAME> tag (official Korean registered name).
    Steps:
      1. Detect encoding, decode
      2. Parse with lxml-xml
      3. Extract company_name from <COMPANY-NAME>
      4. Traverse BODY -> SECTION-1 -> SECTION-2 -> TITLE/P/TABLE
      5. Deduplicate short repeated titles
    """
    xml_str = _safe_decode(raw_bytes)
    xml_str = re.sub(r'<\?xml[^>]*\?>', '', xml_str, count=1)

    try:
        soup = BeautifulSoup(xml_str, "lxml-xml")
    except Exception as exc:
        log.warning("lxml-xml parse failed, falling back to html.parser: %s", exc)
        soup = BeautifulSoup(xml_str, "html.parser")

    # Extract company name before decomposing soup
    company_name = _extract_company_name_from_soup(soup)

    parts: list[str] = []

    # Cover title
    ct = soup.find("COVER-TITLE")
    if ct:
        title = re.sub(r"\s+", "", ct.get_text(strip=True))
        if title:
            parts.append(f"## {title}")

    # Main body
    body = soup.find("BODY")
    if body:
        _process_element(body, parts, depth=0)
    else:
        for sec in soup.find_all(["SECTION-1", "SECTION-2"], recursive=False):
            _process_element(sec, parts, depth=0)

    try:
        soup.decompose()
    except Exception:
        pass

    combined = "\n\n".join(parts)

    # Deduplicate: TOC titles appear as TITLE elements AND as table rows.
    # Remove second occurrence of any line shorter than 80 chars.
    seen: set[str] = set()
    dedup_lines: list[str] = []
    for line in combined.split("\n"):
        stripped = line.strip()
        if stripped and stripped in seen and len(stripped) < 80:
            continue
        if stripped:
            seen.add(stripped)
        dedup_lines.append(line)

    return "\n".join(dedup_lines), company_name


# ---------------------------------------------------------------------------
# ZIP extraction
# ---------------------------------------------------------------------------

def _classify_xml_role(xml_name: str, rcept_no: str) -> str:
    """
    Determine XML role from filename.
      {rcept_no}.xml       -> MAIN
      {rcept_no}_00760.xml -> CONSOL
      {rcept_no}_00761.xml -> SEP
    """
    base = xml_name.lower().replace(".xml", "")
    for suffix, role in _AUDIT_SUFFIX_MAP.items():
        if base.endswith(suffix):
            return role
    return XML_ROLE_MAIN


def extract_from_dart_zip(
    content: bytes,
    filename: str,
    rcept_no: str,
) -> List[ExtractedXML]:
    """
    Open ZIP bytes, extract all XML files, return ExtractedXML list.

    Order: MAIN first (no suffix), then CONSOL (_00760), then SEP (_00761).
    Skips: XML files < 500 bytes (empty placeholder files).
    """
    results: List[ExtractedXML] = []

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if not xml_names:
                log.warning("[%s] No XML files found in ZIP", filename)
                return results

            # Sort: MAIN first, then by name ascending
            def _sort_key(name: str) -> tuple[int, str]:
                low = name.lower()
                if low.endswith(f"{rcept_no}.xml"):
                    return (0, name)
                for suffix in _AUDIT_SUFFIX_MAP:
                    if low.endswith(f"{suffix}.xml"):
                        return (1, name)
                return (2, name)

            xml_names.sort(key=_sort_key)

            for xml_name in xml_names:
                try:
                    raw = zf.read(xml_name)
                    if len(raw) < 500:
                        log.debug("[%s] Skipping tiny XML: %s (%d bytes)",
                                  filename, xml_name, len(raw))
                        continue

                    role = _classify_xml_role(xml_name, rcept_no)
                    text, cname = extract_dart4_xml(raw)

                    if len(text.strip()) < 100:
                        log.warning("[%s/%s] Extracted text too short (%d chars)",
                                    filename, xml_name, len(text))
                        continue

                    results.append(ExtractedXML(
                        rcept_no=rcept_no,
                        xml_role=role,
                        raw_text=text,
                        xml_filename=xml_name,
                        company_name=cname,
                    ))
                    log.debug("[%s] %s extracted: %d chars, company=%s",
                              filename, role, len(text), cname or "(none)")

                except Exception as exc:
                    log.error("[%s/%s] XML extraction failed: %s", filename, xml_name, exc)
                    continue

    except zipfile.BadZipFile as exc:
        log.error("[%s] Bad ZIP: %s", filename, exc)
    except Exception as exc:
        log.error("[%s] Unexpected error during ZIP extraction: %s", filename, exc)

    return results


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

    if len(sys.argv) < 3:
        print("Usage: python extract_dart_xml.py <zip_path> <rcept_no>")
        sys.exit(1)

    zip_path = Path(sys.argv[1])
    rcept_no = sys.argv[2]

    raw = zip_path.read_bytes()
    results = extract_from_dart_zip(raw, zip_path.name, rcept_no)

    if not results:
        print("No results extracted.")
        sys.exit(1)

    for r in results:
        print(f"\n{'='*60}")
        print(f"Role: {r.xml_role} | File: {r.xml_filename} | Chars: {r.char_count:,}")
        print("-" * 60)
        print(r.raw_text[:800])
        print("...")
