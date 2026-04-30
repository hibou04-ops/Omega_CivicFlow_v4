#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════
 Omega CivicFlow — 청킹 전용 일괄 처리 v5 (87점 목표)
 ─────────────────────────────────────────────────────
 v4 대비 변경:
   1) DART4 XML 구조 파서 — SECTION-1/2, TABLE 계층 보존
      (기존 flat tag 추출 완전 교체)
   2) TABLE_TARGET_SIZE 1800 → 2500
   3) 연도(YYYY) → chunk prefix 주입 [회사명 2026년]
   4) 복수 XML 파일 처리 (main + _00760 sub-reports)
 GPU 불필요 · 임베딩 없음 · 순수 CPU 작업
═══════════════════════════════════════════════════════
 실행: python tools/chunk_only_v5_87target.py
 결과: tools/_chunks_v5_output.jsonl
═══════════════════════════════════════════════════════
"""

import sys, os, json, re, time, signal, zipfile, io, hashlib, logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("chunk_v5")

DATASET_DIR    = Path(r"C:\Users\hibou\Desktop\DataSet")
OUTPUT_FILE    = BACKEND_DIR / "tools" / "_chunks_v5_output.jsonl"
CHECKPOINT_FILE = BACKEND_DIR / "tools" / "_chunk_v5_checkpoint.json"

MIN_TEXT_LENGTH   = 100
MIN_CHUNK_LENGTH  = 150
NARRATIVE_TARGET  = 900
TABLE_TARGET      = 2500   # v5: 1800 → 2500
OVERLAP_SIZE      = 150    # v5: 120 → 150

_shutdown = False
def _sig_handler(sig, frame):
    global _shutdown
    if _shutdown:
        sys.exit(1)
    _shutdown = True
    log.info("안전 중단 요청 — 현재 문서 완료 후 중지합니다...")
signal.signal(signal.SIGINT, _sig_handler)


# ══════════════════════════════════════════════════════════════════
# DART4 XML 구조 추출 (v5 핵심)
# ══════════════════════════════════════════════════════════════════

def _table_to_text(table_el) -> str:
    """DART4 TABLE 요소 → 공백 구분 텍스트 (행 구조 보존)"""
    rows = []

    def _process_tr(tr):
        cells = [
            td.get_text(separator=" ", strip=True)
            for td in tr.find_all(["TH", "TD", "TU", "TE"], recursive=False)
        ]
        cells = [c for c in cells if c]
        if cells:
            rows.append("  ".join(cells))

    thead = table_el.find("THEAD", recursive=False)
    if thead:
        for tr in thead.find_all("TR"):
            _process_tr(tr)

    for tbody in table_el.find_all("TBODY", recursive=False):
        for tr in tbody.find_all("TR"):
            _process_tr(tr)

    if not rows:
        for tr in table_el.find_all("TR"):
            _process_tr(tr)

    return "\n".join(rows)


def _process_element(element, parts: List[str]):
    """DART4 XML 요소 재귀 처리 — SECTION/P/TABLE 계층 보존"""
    for child in element.children:
        if not hasattr(child, "name") or not child.name:
            continue
        tag = child.name

        if tag in ("SECTION-1", "SECTION-2"):
            title_tag = child.find("TITLE", recursive=False)
            if title_tag:
                t = title_tag.get_text(strip=True)
                if t:
                    parts.append(t)
            _process_element(child, parts)

        elif tag == "TITLE":
            t = child.get_text(strip=True)
            if t:
                parts.append(t)

        elif tag == "P":
            t = child.get_text(separator=" ", strip=True)
            if t and len(t) > 5:
                parts.append(t)

        elif tag in ("TABLE", "TABLE-GROUP"):
            tt = _table_to_text(child)
            if tt:
                parts.append(tt)


def extract_dart4_xml(raw_bytes: bytes) -> str:
    """
    DART4 XML → 구조화 텍스트
    SECTION-1/2 계층 + TABLE 행 구조 보존
    """
    from bs4 import BeautifulSoup

    text = raw_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "lxml-xml")

    parts: List[str] = []

    cover = soup.find("COVER")
    if cover:
        ct = cover.find("COVER-TITLE")
        if ct:
            parts.append(ct.get_text(strip=True))

    cn = soup.find("COMPANY-NAME")
    if cn:
        parts.append(f"회사명: {cn.get_text(strip=True)}")

    body = soup.find("BODY")
    if body:
        _process_element(body, parts)
    else:
        for s1 in soup.find_all("SECTION-1"):
            _process_element(s1, parts)
        if not parts:
            for tag in soup.find_all(True):
                if tag.string and tag.string.strip() and len(tag.string.strip()) > 5:
                    s = tag.string.strip()
                    ko = sum(1 for c in s if "\uac00" <= c <= "\ud7a3")
                    if ko > 0 or re.search(r"\d{3,}", s):
                        parts.append(s)

    return "\n\n".join(p for p in parts if p.strip())


def extract_from_dart_zip(content: bytes, filename: str) -> str:
    """ZIP 내 모든 XML 파일을 DART4 구조 파서로 처리"""
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
    except Exception as e:
        log.debug(f"ZIP 열기 실패 {filename}: {e}")
        return ""

    names = z.namelist()
    xml_files = [n for n in names if n.endswith(".xml")]

    if not xml_files:
        return ""

    main_xml = []
    sub_xml  = []
    for n in xml_files:
        if re.search(r"_\d{5,}\.xml$", n):
            sub_xml.append(n)
        else:
            main_xml.append(n)

    ordered = main_xml + sorted(sub_xml)

    all_parts: List[str] = []
    for xf in ordered:
        try:
            raw = z.read(xf)
            text = extract_dart4_xml(raw)
            if text and len(text) > 50:
                all_parts.append(text)
        except Exception as e:
            log.debug(f"  XML 처리 실패 {xf}: {e}")

    combined = "\n\n".join(all_parts)

    # 연속 중복 라인 제거 (목차 + 본문에서 섹션 제목 이중 출력 방지)
    seen: set = set()
    dedup_lines = []
    for line in combined.split("\n"):
        s = line.strip()
        if s and s in seen and len(s) < 80:
            continue
        if s:
            seen.add(s)
        dedup_lines.append(line)
    return "\n".join(dedup_lines)


# ══════════════════════════════════════════════════════════════════
# 텍스트 정제
# ══════════════════════════════════════════════════════════════════

def _korean_ratio(text: str) -> float:
    if not text:
        return 0.0
    ko = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
    total = len(text.replace(" ", "").replace("\n", ""))
    return ko / max(total, 1)


def deep_clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"(?:전자공시시스템|dart\.fss\.or\.kr)[\s\S]{0,50}", " ", text)
    text = re.sub(r"[A-Fa-f0-9]{32,}", " ", text)
    text = re.sub(r"[\u4e00-\u9fff]{3,}", " ", text)
    text = re.sub(r"[\u3040-\u309f\u30a0-\u30ff]{3,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n\s*-?\s*\d{1,3}\s*-?\s*\n", "\n", text)
    lines = [l for l in text.split("\n") if len(l.strip()) >= 2 or l.strip() == ""]
    return "\n".join(lines).strip()


# ══════════════════════════════════════════════════════════════════
# 메타데이터
# ══════════════════════════════════════════════════════════════════

def _extract_rcept_no(filename: str) -> str:
    m = re.search(r"(\d{14})", filename)
    return m.group(1) if m else hashlib.md5(filename.encode()).hexdigest()[:14]


def _extract_year(filename: str) -> str:
    m = re.search(r"_(\d{4})\d{10}", filename)
    return m.group(1) if m else ""


def extract_metadata(filename: str, text: str) -> Dict:
    company = "미확인"
    m = re.search(r"DART_P\d+_(.+?)_\d{14}", filename)
    if m:
        company = m.group(1)

    year = _extract_year(filename)

    category = "기타"
    # 공백 정규화 후 매칭 (사 업 보 고 서 → 사업보고서)
    text_norm = re.sub(r"\s+", "", text[:2000])
    kws = {
        "사업보고서": "사업보고서", "분기보고서": "분기보고서", "반기보고서": "반기보고서",
        "감사보고서": "감사보고서", "주요사항보고서": "주요사항보고서",
        "기타공시": "기타공시",
        "자기주식": "자기주식", "임원": "임원관련", "합병": "M&A",
        "증권신고서": "증권신고서", "공개매수": "공개매수",
    }
    for kw, cat in kws.items():
        if kw in text_norm or kw in filename:
            category = cat
            break

    return {
        "company_name": company,
        "year": year,
        "category": category,
        "rcept_no": _extract_rcept_no(filename),
    }


# ══════════════════════════════════════════════════════════════════
# v5 청킹 (v4 3-phase tagger + TABLE_TARGET=2500 + year prefix)
# ══════════════════════════════════════════════════════════════════

SECTION_PATTERN = re.compile(
    r"^(?:"
    r"(?:[IVX]+\.|[0-9]+\.)\s*.{2,40}$"
    r"|【.{2,30}】"
    r"|(?:제\s*\d+\s*[기장편])"
    r"|(?:사\s*업\s*보\s*고\s*서|감\s*사\s*보\s*고\s*서|분\s*기\s*보\s*고\s*서)"
    r"|(?:연\s*결\s*재\s*무\s*제\s*표|재\s*무\s*상\s*태\s*표|손\s*익\s*계\s*산\s*서|포\s*괄\s*손\s*익)"
    r"|(?:주\s*주\s*총\s*회|이\s*사\s*회|감\s*사\s*위\s*원)"
    r"|(?:독립된\s*감사인)"
    r"|(?:[가나다라마바사아자차카타파하]\.\s*.{2,30})"
    r"|(?:\(\d+\)\s*.{2,30})"
    r")",
    re.MULTILINE,
)


def chunk_text_v5(text: str, meta: Dict) -> List[str]:
    if not text or len(text) < MIN_CHUNK_LENGTH:
        return []

    company = meta.get("company_name", "")
    year    = meta.get("year", "")
    company_label = f"{company} {year}년" if year else company

    # ── 1단계: 섹션 분리 ──
    lines = text.split("\n")
    sections: List[Tuple[str, str]] = []
    cur_title = ""
    cur_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if SECTION_PATTERN.match(stripped) and len(stripped) < 60:
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

    all_chunks: List[str] = []

    for sec_title, sec_text in sections:
        if not sec_text.strip():
            continue

        if company_label and sec_title:
            prefix = f"[{company_label}] {sec_title}\n"
        elif company_label:
            prefix = f"[{company_label}]\n"
        elif sec_title:
            prefix = f"{sec_title}\n"
        else:
            prefix = ""

        # ── 2단계: 3-Phase 라인 태깅 ──
        tagged = []
        for line in sec_text.split("\n"):
            s = line.strip()
            if not s:
                tagged.append({"text": "", "type": "blank"})
                continue
            digit_count  = sum(1 for c in s if c.isdigit())
            digit_ratio  = digit_count / max(len(s), 1)
            wide_gaps    = len(re.findall(r"  +", s))
            numeric_toks = len(re.findall(r"\d+(?:[.,]\d+)*%?", s))

            is_numeric = (
                len(s) > 8
                and numeric_toks >= 2
                and (digit_ratio > 0.3 or wide_gaps >= 2)
            )

            if is_numeric:
                tagged.append({"text": s, "type": "numeric"})
            elif len(s) <= 30 and digit_count <= 3:
                tagged.append({"text": s, "type": "label_candidate"})
            else:
                tagged.append({"text": s, "type": "narrative"})

        # label_candidate → 인접 numeric 흡수
        def _nearest(idx, direction, window=3):
            i = idx + direction
            steps = 0
            while 0 <= i < len(tagged) and steps < window:
                if tagged[i]["type"] != "blank":
                    return tagged[i]["type"]
                i += direction
                steps += 1
            return None

        for i, t in enumerate(tagged):
            if t["type"] == "label_candidate":
                if _nearest(i, +1) == "numeric" or _nearest(i, -1) == "numeric":
                    tagged[i]["type"] = "numeric"
                else:
                    tagged[i]["type"] = "narrative"

        # 연속 동일 type 블록 그룹핑
        table_blocks: List[str] = []
        narrative_blocks: List[str] = []
        cur_buf: List[str] = []
        cur_type: Optional[str] = None

        for t in tagged:
            if t["type"] == "blank":
                if cur_buf:
                    cur_buf.append("")
                continue
            if cur_type is None:
                cur_type = t["type"]
                cur_buf = [t["text"]]
            elif t["type"] == cur_type:
                cur_buf.append(t["text"])
            else:
                joined = "\n".join(cur_buf).strip()
                if joined:
                    (table_blocks if cur_type == "numeric" else narrative_blocks).append(joined)
                cur_type = t["type"]
                cur_buf = [t["text"]]

        if cur_buf:
            joined = "\n".join(cur_buf).strip()
            if joined:
                (table_blocks if cur_type == "numeric" else narrative_blocks).append(joined)

        # ── 테이블 청킹 (TABLE_TARGET=2500, 헤더 복제) ──
        for table in table_blocks:
            full = prefix + table
            if len(full) < MIN_CHUNK_LENGTH:
                continue
            if len(full) <= TABLE_TARGET * 1.2:
                all_chunks.append(full)
            else:
                rows = table.split("\n")
                if len(rows) > 4:
                    header = "\n".join(rows[:2]) + "\n"
                    data_rows = rows[2:]
                else:
                    header = ""
                    data_rows = rows

                sub_prefix = prefix + header
                current = sub_prefix
                for row in data_rows:
                    if len(current) + len(row) > TABLE_TARGET:
                        if len(current.strip()) >= MIN_CHUNK_LENGTH:
                            all_chunks.append(current.strip())
                        current = sub_prefix + row + "\n"
                    else:
                        current += row + "\n"
                if len(current.strip()) >= MIN_CHUNK_LENGTH:
                    all_chunks.append(current.strip())

        # ── 서술형 청킹 (오버랩 150) ──
        full_narrative = "\n".join(narrative_blocks)
        if not full_narrative.strip():
            continue

        sentences = re.split(
            r"(?<=[다요음됨함임.])\s*\n|"
            r"(?<=[다요음됨함임.])\s{2,}|"
            r"\n\s*\n",
            full_narrative,
        )
        sentences = [s.strip() for s in sentences if s.strip()]

        current_chunk = prefix
        prev_tail = ""

        for sent in sentences:
            if len(sent) < 5:
                continue
            if len(current_chunk) + len(sent) > NARRATIVE_TARGET:
                if len(current_chunk.strip()) >= MIN_CHUNK_LENGTH:
                    all_chunks.append(current_chunk.strip())
                if prev_tail and len(prev_tail) < OVERLAP_SIZE:
                    current_chunk = prefix + prev_tail + "\n" + sent + "\n"
                else:
                    current_chunk = prefix + sent + "\n"
            else:
                current_chunk += sent + "\n"
            prev_tail = sent

        if len(current_chunk.strip()) >= MIN_CHUNK_LENGTH:
            all_chunks.append(current_chunk.strip())

    # ── 3단계: 품질 필터 ──
    quality: List[str] = []
    for chunk in all_chunks:
        if len(chunk) < MIN_CHUNK_LENGTH:
            continue
        body = re.sub(r"^\[.*?\]\s*.*?\n", "", chunk, count=1)
        if _korean_ratio(body) < 0.12:   # v5: 0.15 → 0.12 (숫자 중심 청크 허용)
            continue
        if re.match(r"^[\d\s,.\-\u2013\u2014:/|%\[\]()]+$", body):
            continue
        quality.append(chunk)

    return quality


# ══════════════════════════════════════════════════════════════════
# 체크포인트
# ══════════════════════════════════════════════════════════════════

def load_checkpoint() -> set:
    if CHECKPOINT_FILE.exists():
        data = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        return set(data.get("done", []))
    return set()


def save_checkpoint(done: set):
    CHECKPOINT_FILE.write_text(
        json.dumps({"done": list(done)}, ensure_ascii=False),
        encoding="utf-8",
    )


# ══════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════

def main():
    log.info("╔═══════════════════════════════════════════════════╗")
    log.info("║  Omega CivicFlow v5 청킹 — 87점 목표             ║")
    log.info("║  DART4 XML 구조 파서 + TABLE_TARGET=2500         ║")
    log.info("╚═══════════════════════════════════════════════════╝")

    zip_files = sorted([f for f in DATASET_DIR.glob("*.zip") if not f.name.endswith(".zip.pdf")])
    pdf_files = sorted(DATASET_DIR.glob("*.zip.pdf"))
    all_files = zip_files + pdf_files
    log.info(f"  데이터셋: {len(all_files)}건 (.zip={len(zip_files)} + .zip.pdf={len(pdf_files)})")

    # rcept_no 기준 중복 제거 (.zip 우선)
    rcept_map: Dict = {}
    for f in all_files:
        rno = _extract_rcept_no(f.name)
        rcept_map.setdefault(rno, []).append(f)

    unique_files: List[Path] = []
    for rno, files in rcept_map.items():
        pure = [f for f in files if f.name.endswith(".zip") and not f.name.endswith(".zip.pdf")]
        unique_files.append(pure[0] if pure else files[0])

    log.info(f"  유일 문서: {len(unique_files)}건")

    done = load_checkpoint()
    remaining = [f for f in unique_files if _extract_rcept_no(f.name) not in done]
    log.info(f"  완료: {len(done)}건 | 남은 문서: {len(remaining)}건")

    if not remaining:
        log.info("  모든 문서 청킹 완료!")
        return

    out_f = open(OUTPUT_FILE, "a", encoding="utf-8")
    stats = {"success": 0, "skip": 0, "error": 0}
    t_start = time.time()

    for idx, filepath in enumerate(remaining, 1):
        if _shutdown:
            log.info(f"안전 중단 — {idx-1}/{len(remaining)}에서 중지")
            break

        rcept_no = _extract_rcept_no(filepath.name)

        try:
            content = filepath.read_bytes()
            raw_text = extract_from_dart_zip(content, filepath.name)

            if not raw_text or len(raw_text) < 20:
                stats["skip"] += 1
                done.add(rcept_no)
                if idx % 100 == 0:
                    save_checkpoint(done)
                continue

            cleaned = deep_clean_text(raw_text)
            if len(cleaned) < MIN_TEXT_LENGTH:
                stats["skip"] += 1
                done.add(rcept_no)
                if idx % 100 == 0:
                    save_checkpoint(done)
                continue

            meta   = extract_metadata(filepath.name, cleaned)
            chunks = chunk_text_v5(cleaned, meta)

            record = {
                "rcept_no":   rcept_no,
                "filename":   filepath.name,
                "company":    meta["company_name"],
                "year":       meta["year"],
                "category":   meta["category"],
                "text_length": len(cleaned),
                "chunk_count": len(chunks),
                "chunks":     chunks,
            }
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

            stats["success"] += 1
            done.add(rcept_no)

            if idx % 50 == 0:
                elapsed = time.time() - t_start
                rate    = idx / max(elapsed, 1)
                eta     = (len(remaining) - idx) / max(rate, 0.01)
                log.info(
                    f"  [{idx}/{len(remaining)}] "
                    f"성공={stats['success']} 스킵={stats['skip']} 에러={stats['error']} | "
                    f"속도={rate:.1f}건/초 | ETA={eta/60:.1f}분"
                )
                save_checkpoint(done)

        except Exception as e:
            stats["error"] += 1
            log.error(f"  [{idx}] {filepath.name[:40]}: {e}")
            done.add(rcept_no)

    out_f.close()
    save_checkpoint(done)

    elapsed = time.time() - t_start
    log.info("=" * 52)
    log.info(f"  완료: 성공={stats['success']} 스킵={stats['skip']} 에러={stats['error']}")
    log.info(f"  소요: {elapsed/60:.1f}분 | 출력: {OUTPUT_FILE}")

    if OUTPUT_FILE.exists():
        total_chunks = 0
        doc_count    = 0
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    total_chunks += rec.get("chunk_count", 0)
                    doc_count    += 1
                except Exception:
                    pass
        log.info(f"  총 문서: {doc_count}건 | 총 청크: {total_chunks:,}개")
        if doc_count > 0:
            log.info(f"  평균 청크/문서: {total_chunks/doc_count:.0f}개")


if __name__ == "__main__":
    main()
