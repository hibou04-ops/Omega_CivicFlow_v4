# dart_chunk_sample_test.py
# Policy v2 기반 DART 샘플 청킹 데모 스크립트
# 읽기: C:/Users/hibou/Desktop/DataSet/ 내 4개 ZIP 파일 (감사보고서 XML 전용, ~500KB~900KB)
# 쓰기: C:/Users/hibou/Omega_CivicFlow_v4/scripts/output/dart_chunks_sample.json
# 삭제/이동/덮어쓰기: 없음

import os
import sys
import re
import json
import zipfile
from lxml import etree
import tiktoken

# ─────────────────────────────────────────
# 설정
# ─────────────────────────────────────────

BASE_DIR = "C:/Users/hibou/Desktop/DataSet"
OUTPUT_DIR = "C:/Users/hibou/Omega_CivicFlow_v4/scripts/output"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "dart_chunks_sample.json")

# 샘플: 모두 _00760/_00761 (감사보고서 XML) — 500KB~900KB 범위, 빠른 처리
SAMPLES = [
    (
        "DART_P0_BGF리테일_20260318000829.zip",
        [
            ("20260318000829_00760.xml", "separate"),
            ("20260318000829_00761.xml", "consolidated"),
        ],
    ),
    (
        "DART_P0_DB손해보험_20240314001788.zip",
        [
            ("20240314001788_00760.xml", "separate"),
        ],
    ),
    (
        "DART_P0_CJ대한통운_20260316001417.zip",
        [
            ("20260316001417_00760.xml", "separate"),
        ],
    ),
]

# Token limits (Policy v2)
T1_MAX     = 370
T1_OVERLAP = 64
T2_MAX     = 400
T2_NOTE_FALLBACK_MAX = 480

# ─────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────

XML_PARSER = etree.XMLParser(recover=True, encoding="utf-8")
ENC        = tiktoken.get_encoding("cl100k_base")
NUMERIC_PAT = re.compile(r"[\d,]+")

SUPV_MAP = {
    "100000000000": "적정",
    "010000000000": "한정",
    "001000000000": "부적정",
    "000100000000": "의견거절",
}

# ── 토큰 캐시 (문자열 → 토큰 수) ─────────────────────────
_tok_cache: dict[str, int] = {}

def tok(text: str) -> int:
    """tiktoken 토큰 수 (캐시 적용으로 O(N²) 방지)"""
    if text not in _tok_cache:
        _tok_cache[text] = len(ENC.encode(text))
    return _tok_cache[text]


def extract_company_info(root):
    el = root.find("COMPANY-NAME")
    if el is None:
        return "?", ""
    return (el.text or "?").strip(), el.get("AREGCIK", "")


def get_summary_items(root) -> dict:
    summary = root.find("SUMMARY")
    if summary is None:
        return {}
    return {ex.get("ACODE", ""): (ex.text or "").strip()
            for ex in summary.findall("EXTRACTION")}


def get_section_title(el) -> str:
    title_el = el.find("TITLE")
    if title_el is not None:
        return "".join(title_el.itertext()).strip()
    return ""


def detect_fin_unit(text: str) -> str:
    m = re.search(r"단위\s*[:：]\s*([^\)\n]+)", text)
    return m.group(1).strip()[:20] if m else "?"


def detect_period(table_el) -> str:
    for row in table_el.findall(".//TR")[:6]:
        txt = "".join(row.itertext()).strip()
        m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*부터", txt)
        if m:
            return f"{m.group(1)}.{m.group(2).zfill(2)}.{m.group(3).zfill(2)}~"
    return ""


def detect_table_type(table_el) -> str:
    t = "".join(table_el.itertext())
    if any(k in t for k in ["재무상태표", "대차대조표"]):
        return "BS"
    if any(k in t for k in ["포괄손익", "손익계산서"]):
        return "IS"
    if "현금흐름" in t:
        return "CF"
    if "자본변동" in t:
        return "EQ"
    if "이익잉여금처분" in t:
        return "RE"
    return "NORMAL"


def classify_note_table(table_el) -> str:
    """수치 셀 비율 기준 분류 (Policy v2 §3-1)"""
    rows = table_el.findall(".//TR")
    if len(rows) < 3:
        return "T1-NOTE"
    total = numeric = 0
    for row in rows:
        for c in row.findall("TD") + row.findall("TH"):
            total += 1
            if NUMERIC_PAT.search("".join(c.itertext()).strip()):
                numeric += 1
    if total == 0:
        return "T1-NOTE"
    return "T2-NOTE" if (numeric / total) >= 0.5 else "T1-NOTE"


def table_to_markdown(table_el, max_rows: int = None) -> str:
    rows = table_el.findall(".//TR")
    lines = []
    for i, row in enumerate(rows):
        if max_rows and i > max_rows:
            lines.append("| ... | (이하 생략) |")
            break
        cells = row.findall("TD") + row.findall("TH")
        vals = []
        for c in cells:
            txt = "".join(c.itertext()).strip().replace("\n", " ")
            span = int(c.get("COLSPAN", "1"))
            vals.extend([txt] * span)
        if not any(v.strip() for v in vals):
            continue
        lines.append("| " + " | ".join(vals) + " |")
        if i == 0:
            lines.append("| " + " | ".join(["---"] * max(len(vals), 1)) + " |")
    return "\n".join(lines)


# ─────────────────────────────────────────
# 청킹 엔진
# ─────────────────────────────────────────

def chunk_xml(zip_path: str, xml_name: str, scope: str,
              rcept_no: str, report_date: str) -> list:

    with zipfile.ZipFile(zip_path, "r") as zf:
        content = zf.read(xml_name)
    root = etree.fromstring(content, XML_PARSER)
    body = root.find("BODY")

    company, reg_no = extract_company_info(root)
    summary_items   = get_summary_items(root)
    fiscal_year     = report_date[:4]

    chunks: list[dict] = []
    idx_counter = [0]

    def new_chunk(chunk_type, section_path, text, contains_table,
                  table_type=None, note_type=None,
                  fin_unit="?", period_cur="",
                  audit_source=None, audit_opinion=None, auditor=None,
                  fallback_applied=False, fallback_reason=None):
        idx = idx_counter[0]
        idx_counter[0] += 1
        chunks.append({
            "chunk_index":     idx,
            "chunk_type":      chunk_type,
            "note_type":       note_type,
            "company_name":    company,
            "company_reg_no":  reg_no,
            "rcept_no":        rcept_no,
            "report_date":     report_date,
            "fiscal_year":     fiscal_year,
            "source_xml":      xml_name,
            "section_path":    section_path,
            "statement_scope": scope,
            "table_type":      table_type,
            "fin_unit":        fin_unit,
            "period_current":  period_cur,
            "audit_source":    audit_source,
            "audit_opinion":   audit_opinion,
            "auditor":         auditor,
            "token_estimate":  tok(text),
            "contains_table":  contains_table,
            "fallback_applied": fallback_applied,
            "fallback_reason":  fallback_reason,
            "text":            text,
        })

    # ── T0: SUMMARY Fact Chunk ──────────────────────────────────
    opinion_raw = summary_items.get("SUPV_OPIN", "")
    opinion_str = SUPV_MAP.get(opinion_raw, "")
    lines = [f"[{company} | {fiscal_year} | 핵심재무요약]"]
    for code, label in [
        ("TOT_ASSETS", "총자산(백만원)"),
        ("TOT_DEBTS",  "총부채(백만원)"),
        ("TOT_SALES",  "매출액(백만원)"),
        ("TOT_EMPL",   "종업원수"),
        ("IFRS_YN",    "IFRS적용"),
        ("FIN_STAT",   "재무유형"),
    ]:
        if summary_items.get(code):
            lines.append(f"{label}: {summary_items[code]}")
    if opinion_str:
        lines.append(f"감사의견: {opinion_str}")
    new_chunk("fact", "SUMMARY", "\n".join(lines), False,
              audit_opinion=opinion_str or None)

    if body is None:
        return chunks

    # ── BODY 순회 ───────────────────────────────────────────────
    # nar_buf: (text, token_count) 튜플 리스트 — running_tok으로 O(1) 합산
    nar_buf: list[tuple[str, int]] = []
    running_tok  = 0   # nar_buf 전체 토큰 합 (캐시)
    nar_section  = ""

    def flush_narrative(section_path: str):
        nonlocal nar_buf, running_tok
        if not nar_buf:
            return

        while nar_buf:
            batch: list[tuple[str, int]] = []
            batch_tok = 0
            for item in nar_buf:
                if batch_tok + item[1] > T1_MAX and batch:
                    break
                batch.append(item)
                batch_tok += item[1]
            if not batch:
                batch = [nar_buf[0]]

            header = f"[{company} | {fiscal_year} | {section_path}]"
            full   = header + "\n" + "\n".join(t for t, _ in batch)
            new_chunk("narrative", section_path, full, False)

            # overlap: 마지막 T1_OVERLAP 토큰 유지 — running 합 사용
            overlap: list[tuple[str, int]] = []
            ov_tok = 0
            for item in reversed(batch):
                if ov_tok + item[1] > T1_OVERLAP:
                    break
                overlap.insert(0, item)
                ov_tok += item[1]

            consumed = len(batch)
            nar_buf  = overlap + nar_buf[consumed:]
            running_tok = sum(t for _, t in nar_buf)
            if len(nar_buf) == consumed:
                nar_buf     = []
                running_tok = 0
                break

    def process_el(el, section_path: str):
        nonlocal nar_buf, running_tok, nar_section
        tag = el.tag

        if tag == "P":
            txt = "".join(el.itertext()).strip()
            t   = tok(txt)
            if not txt or t < 10:
                return
            if section_path != nar_section:
                flush_narrative(nar_section)
                nar_buf      = []
                running_tok  = 0
                nar_section  = section_path
            nar_buf.append((txt, t))
            running_tok += t
            if running_tok > T1_MAX:
                flush_narrative(section_path)

        elif tag == "TABLE":
            flush_narrative(nar_section)
            nar_buf     = []
            running_tok = 0

            if el.get("ACLASS") == "EXTRACTION":
                return
            rows = el.findall(".//TR")
            if len(rows) < 2:
                return

            all_text = "".join(el.itertext())
            unit     = detect_fin_unit(all_text)
            period   = detect_period(el)
            ttype    = detect_table_type(el)
            is_note  = any(k in section_path for k in ["주석", "NOTE"])

            if is_note:
                note_cls = classify_note_table(el)
                if note_cls == "T2-NOTE":
                    header = (f"[{company} | {fiscal_year} | {section_path}"
                              f" | NOTE | 단위:{unit}]")
                    md   = table_to_markdown(el, max_rows=18)
                    full = header + "\n" + md
                    fb, fb_reason = False, None
                    if tok(full) > T2_NOTE_FALLBACK_MAX:
                        md   = table_to_markdown(el, max_rows=10)
                        full = header + "\n" + md + "\n| ... | (이하 생략) |"
                        fb, fb_reason = True, "note_table_truncated_at_10_rows"
                    new_chunk("table", section_path, full, True,
                              table_type="NOTE", note_type="tabular",
                              fin_unit=unit, period_cur=period,
                              fallback_applied=fb, fallback_reason=fb_reason)
                else:
                    header    = f"[{company} | {fiscal_year} | {section_path} | NOTE]"
                    row_texts = [
                        " ".join("".join(c.itertext()).strip()
                                 for c in r.findall("TD") + r.findall("TH"))
                        for r in rows
                    ]
                    full = header + "\n" + "\n".join(t for t in row_texts if t.strip())
                    new_chunk("narrative", section_path, full, True,
                              note_type="narrative")
            else:
                header = (f"[{company} | {fiscal_year} | {section_path}"
                          f" | {ttype} | 단위:{unit} | {period}]")
                md   = table_to_markdown(el, max_rows=20)
                full = header + "\n" + md
                fb, fb_reason = False, None
                if tok(full) > T2_MAX:
                    md   = table_to_markdown(el, max_rows=12)
                    full = header + "\n" + md + "\n| ... | (이하 생략) |"
                    fb, fb_reason = True, "table_truncated_at_12_rows"
                new_chunk("table", section_path, full, True,
                          table_type=ttype, fin_unit=unit, period_cur=period,
                          fallback_applied=fb, fallback_reason=fb_reason)

        elif tag.startswith("SECTION"):
            t = get_section_title(el)
            new_path = (f"{section_path} > {t}"
                        if section_path and t else (t or section_path))
            if nar_buf and nar_section != new_path:
                flush_narrative(nar_section)
                nar_buf     = []
                running_tok = 0
                nar_section = new_path
            for child in el:
                process_el(child, new_path)
            if nar_buf:
                flush_narrative(new_path)
                nar_buf     = []
                running_tok = 0

    for child in body:
        bc = get_section_title(child) or child.tag
        process_el(child, bc)

    if nar_buf:
        flush_narrative(nar_section)

    return chunks


# ─────────────────────────────────────────
# 실행
# ─────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_results: dict[str, list] = {}
    grand_total = 0

    for zip_name, xml_list in SAMPLES:
        zip_path = os.path.join(BASE_DIR, zip_name)
        m = re.match(r"DART_P0_(.+?)_(\d{14})\.zip", zip_name)
        rcept_no    = m.group(2) if m else "?"
        report_date = rcept_no[:8]

        for xml_name, scope in xml_list:
            key = f"{zip_name}|{xml_name}|{scope}"
            print(f"\n{'='*60}", flush=True)
            print(f"처리: {zip_name}", flush=True)
            print(f"  XML : {xml_name}", flush=True)
            print(f"  scope: {scope}", flush=True)

            chunks = chunk_xml(zip_path, xml_name, scope, rcept_no, report_date)
            all_results[key] = chunks
            grand_total += len(chunks)

            # 타입별 통계
            type_counts: dict[str, int] = {}
            for c in chunks:
                t = c["chunk_type"]
                if c.get("note_type"):
                    t += f"({c['note_type']})"
                type_counts[t] = type_counts.get(t, 0) + 1

            tokens = [c["token_estimate"] for c in chunks]
            over400 = sum(1 for t in tokens if t > 400)
            over480 = sum(1 for t in tokens if t > 480)
            fallbacks = sum(1 for c in chunks if c.get("fallback_applied"))

            print(f"  총 청크: {len(chunks)}", flush=True)
            for t, cnt in sorted(type_counts.items()):
                print(f"    {t}: {cnt}", flush=True)
            print(f"  토큰 분포: min={min(tokens)} max={max(tokens)}"
                  f" avg={sum(tokens)//len(tokens)}", flush=True)
            print(f"  400t 초과: {over400}건 / 480t 초과: {over480}건", flush=True)
            print(f"  Fallback 적용: {fallbacks}건", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"전체 청크 합계: {grand_total}", flush=True)
    print(f"결과 저장 → {OUTPUT_FILE}", flush=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print("완료.", flush=True)


if __name__ == "__main__":
    main()
