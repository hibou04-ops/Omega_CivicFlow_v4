"""
classify_xml_roles.py
=====================
Verify and augment XML role classification.

Most classification is done inline in extract_dart_xml.py
(filename suffix -> MAIN/CONSOL/SEP).  This module handles
edge cases and provides a standalone audit tool.

Edge cases handled:
  - XML filename doesn't contain rcept_no in expected position
  - COVER-TITLE content contradicts suffix-based role
  - Unknown suffixes (non-00760/00761 audit attachments)
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# Known audit suffixes
_AUDIT_SUFFIX_ROLES = {
    "00760": "CONSOL",  # 연결 감사보고서
    "00761": "SEP",     # 별도 감사보고서
}

# Cover title keywords that signal audit reports
_AUDIT_COVER_KEYWORDS = {
    "감사보고서":    "AUDIT",
    "검토보고서":    "AUDIT",
    "내부회계관리제도": "AUDIT",
}

_CONSOL_COVER_KEYWORDS = {"연결재무제표", "연결감사"}
_SEP_COVER_KEYWORDS    = {"별도재무제표", "별도감사"}


@dataclass
class XmlRoleInfo:
    filename: str
    role: str                    # "MAIN" | "CONSOL" | "SEP" | "UNKNOWN"
    confidence: str              # "HIGH" | "LOW"
    cover_title: Optional[str]   # raw text from COVER-TITLE if available


def classify_xml_role(
    xml_name: str,
    rcept_no: str,
    cover_title: Optional[str] = None,
) -> XmlRoleInfo:
    """
    Determine XML role.

    Priority:
      1. Filename suffix (00760 / 00761) -> high confidence
      2. Filename is exactly {rcept_no}.xml -> MAIN, high confidence
      3. COVER-TITLE content -> MAIN or AUDIT, medium confidence
      4. Fallback -> UNKNOWN, low confidence
    """
    base = xml_name.lower().replace(".xml", "")

    # Check audit suffixes
    for suffix, role in _AUDIT_SUFFIX_ROLES.items():
        if base.endswith(f"_{suffix}"):
            return XmlRoleInfo(
                filename=xml_name,
                role=role,
                confidence="HIGH",
                cover_title=cover_title,
            )

    # Check if this is the main file
    if base == rcept_no.lower() or base.endswith(f"/{rcept_no.lower()}"):
        return XmlRoleInfo(
            filename=xml_name,
            role="MAIN",
            confidence="HIGH",
            cover_title=cover_title,
        )

    # COVER-TITLE fallback
    if cover_title:
        ct_norm = re.sub(r"\s+", "", cover_title)
        for kw, role_hint in _AUDIT_COVER_KEYWORDS.items():
            if kw in ct_norm:
                # Distinguish CONSOL vs SEP from cover title if possible
                if any(k in ct_norm for k in _CONSOL_COVER_KEYWORDS):
                    return XmlRoleInfo(xml_name, "CONSOL", "LOW", cover_title)
                if any(k in ct_norm for k in _SEP_COVER_KEYWORDS):
                    return XmlRoleInfo(xml_name, "SEP", "LOW", cover_title)
                return XmlRoleInfo(xml_name, "CONSOL", "LOW", cover_title)

        # Non-audit non-main -> probably MAIN (e.g., rcept_no with different prefix)
        return XmlRoleInfo(xml_name, "MAIN", "LOW", cover_title)

    log.warning("Cannot classify XML role for: %s (rcept_no=%s)", xml_name, rcept_no)
    return XmlRoleInfo(xml_name, "UNKNOWN", "LOW", cover_title)


# ---------------------------------------------------------------------------
# CLI: audit a directory of XML filenames
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import zipfile
    import io
    from pathlib import Path

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python classify_xml_roles.py <zip_path>")
        sys.exit(1)

    zip_path = Path(sys.argv[1])
    rcept_no = re.search(r'(\d{14})', zip_path.name)
    rcept_no = rcept_no.group(1) if rcept_no else "UNKNOWN"

    with zipfile.ZipFile(zip_path) as zf:
        xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]

    print(f"ZIP: {zip_path.name} | rcept_no: {rcept_no}")
    print(f"XML files found: {len(xml_names)}")
    for name in xml_names:
        info = classify_xml_role(name, rcept_no)
        flag = "" if info.confidence == "HIGH" else " [LOW CONFIDENCE]"
        print(f"  {info.role}{flag} <- {name}")
