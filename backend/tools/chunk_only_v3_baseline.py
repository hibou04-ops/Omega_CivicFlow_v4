#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════
 Omega CivicFlow — 청킹 전용 일괄 처리 스크립트
 GPU 불필요 · 임베딩 없음 · 순수 CPU 작업
═══════════════════════════════════════════════════════
 실행: python tools/chunk_only.py
 결과: tools/_chunks_output.jsonl  (문서별 1줄)
═══════════════════════════════════════════════════════
"""

import sys, os, json, re, time, signal, zipfile, io, hashlib, logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict

# 프로젝트 루트 설정
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from services.dart_file_parser import extract_text_from_dart_zip

# ── 로거 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("chunk_only")

# ── 상수 ──
DATASET_DIR = Path(r"C:\Users\hibou\Desktop\DataSet")
OUTPUT_FILE = BACKEND_DIR / "tools" / "_chunks_output.jsonl"
CHECKPOINT_FILE = BACKEND_DIR / "tools" / "_chunk_checkpoint.json"
MIN_TEXT_LENGTH = 100
MIN_CHUNK_LENGTH = 80

# ── Graceful Shutdown ──
_shutdown = False
def _sig_handler(sig, frame):
    global _shutdown
    if _shutdown:
        log.warning("⛔ 강제 종료!")
        sys.exit(1)
    _shutdown = True
    log.info("🛑 안전 중단 요청 — 현재 문서 완료 후 중지합니다...")
signal.signal(signal.SIGINT, _sig_handler)


# ═══════════════════════════════════════════════════════
# special_batch_ingest.py에서 가져온 핵심 함수들
# ═══════════════════════════════════════════════════════

def _korean_ratio(text: str) -> float:
    if not text:
        return 0.0
    korean = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
    total = len(text.replace(" ", "").replace("\n", ""))
    return korean / max(total, 1)


def deep_clean_text(raw_text) -> str:
    """10단계 텍스트 정제 파이프라인 (경량 버전)"""
    if isinstance(raw_text, dict):
        raw_text = json.dumps(raw_text, ensure_ascii=False)
    elif isinstance(raw_text, (list, tuple)):
        raw_text = "\n".join(str(x) for x in raw_text)
    elif raw_text is not None:
        raw_text = str(raw_text)
    if not raw_text:
        return ""

    text = raw_text
    # 1) XML 태그 제거
    text = re.sub(r'<[^>]+>', ' ', text)
    # 2) HTML 엔티티
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'&#\d+;', ' ', text)
    # 3) DART 보일러플레이트
    text = re.sub(r'(?:전자공시시스템|dart\.fss\.or\.kr|금융감독원|DART)[\s\S]{0,50}', ' ', text)
    # 4) 기계 코드 / 해시
    text = re.sub(r'[A-Fa-f0-9]{32,}', ' ', text)
    text = re.sub(r'(?:[A-Z0-9]{2}[:\-]){5,}[A-Z0-9]{2}', ' ', text)
    # 5) 외국어 잔여물 (중국어, 일본어)
    text = re.sub(r'[\u4e00-\u9fff]{3,}', ' ', text)
    text = re.sub(r'[\u3040-\u309f\u30a0-\u30ff]{3,}', ' ', text)
    # 6) 반복 공백/줄바꿈 정리
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{3,}', '  ', text)
    # 7) 페이지 번호 패턴
    text = re.sub(r'\n\s*-?\s*\d{1,3}\s*-?\s*\n', '\n', text)
    # 8) 의미없는 짧은 줄 제거 (5자 미만 단독 줄)
    lines = text.split('\n')
    lines = [l for l in lines if len(l.strip()) >= 2 or l.strip() == '']
    text = '\n'.join(lines)

    return text.strip()


def _extract_rcept_no(filename: str) -> str:
    m = re.search(r'(\d{14})', filename)
    return m.group(1) if m else hashlib.md5(filename.encode()).hexdigest()[:14]


def extract_metadata(filename: str, text: str) -> Dict:
    """파일명에서 메타데이터 추출"""
    company = "미확인"
    m = re.search(r'DART_P\d+_(.+?)_\d{14}', filename)
    if m:
        company = m.group(1)

    # 카테고리 추론
    category = "기타"
    category_keywords = {
        "사업보고서": "사업보고서", "분기보고서": "분기보고서", "반기보고서": "반기보고서",
        "감사보고서": "감사보고서", "주요사항보고서": "주요사항보고서",
        "자기주식": "자기주식", "임원": "임원관련", "합병": "M&A",
        "증권신고서": "증권신고서", "공개매수": "공개매수",
    }
    for kw, cat in category_keywords.items():
        if kw in text[:2000] or kw in filename:
            category = cat
            break

    return {
        "company_name": company,
        "category": category,
        "rcept_no": _extract_rcept_no(filename),
    }


def chunk_text_quality(text: str, meta: Dict = None) -> List[str]:
    """
    초-하이엔드 금융 공시문서 청킹 v3
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1) 섹션 헤더 기반 의미 경계 분할
    2) 재무표 행 보존
    3) 계층 컨텍스트 주입
    4) 한글 문장 경계 존중
    5) 품질 필터
    """
    if not text or len(text) < MIN_CHUNK_LENGTH:
        return []

    company = (meta or {}).get("company_name", "")

    # ── 1단계: 섹션 분리 ──
    section_pattern = re.compile(
        r'^(?:'
        r'(?:[IVX]+\.|[0-9]+\.)\s*.{2,40}$'
        r'|【.{2,30}】'
        r'|(?:제\s*\d+\s*[기장편])'
        r'|(?:사\s*업\s*보\s*고\s*서|감\s*사\s*보\s*고\s*서|분\s*기\s*보\s*고\s*서)'
        r'|(?:연\s*결\s*재\s*무\s*제\s*표|재\s*무\s*상\s*태\s*표|손\s*익\s*계\s*산\s*서|포\s*괄\s*손\s*익)'
        r'|(?:주\s*주\s*총\s*회|이\s*사\s*회|감\s*사\s*위\s*원)'
        r')',
        re.MULTILINE
    )

    lines = text.split('\n')
    sections = []
    current_title = ""
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if section_pattern.match(stripped) and len(stripped) < 60:
            if current_lines:
                sections.append((current_title, '\n'.join(current_lines)))
            current_title = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, '\n'.join(current_lines)))
    if not sections:
        sections = [("", text)]

    # ── 2단계: 각 섹션 분할 ──
    TARGET_SIZE = 900
    OVERLAP_SIZE = 120
    all_chunks = []

    for section_title, section_text in sections:
        if not section_text.strip():
            continue

        prefix = ""
        if company and section_title:
            prefix = f"[{company}] {section_title}\n"
        elif company:
            prefix = f"[{company}]\n"
        elif section_title:
            prefix = f"{section_title}\n"

        # 재무표 감지 & 보존
        table_blocks = []
        narrative_blocks = []
        current_block = []
        is_table = False

        for line in section_text.split('\n'):
            stripped = line.strip()
            digit_ratio = sum(1 for c in stripped if c.isdigit() or c in ',.-') / max(len(stripped), 1)
            has_numbers = bool(re.search(r'\d{3,}', stripped))

            if digit_ratio > 0.3 and has_numbers and len(stripped) > 10:
                if not is_table and current_block:
                    narrative_blocks.append('\n'.join(current_block))
                    current_block = []
                is_table = True
                current_block.append(stripped)
            else:
                if is_table and current_block:
                    table_blocks.append('\n'.join(current_block))
                    current_block = []
                is_table = False
                current_block.append(stripped)

        if current_block:
            if is_table:
                table_blocks.append('\n'.join(current_block))
            else:
                narrative_blocks.append('\n'.join(current_block))

        # 테이블 청킹
        for table in table_blocks:
            if len(table) < MIN_CHUNK_LENGTH:
                continue
            if len(prefix + table) <= TARGET_SIZE * 1.5:
                all_chunks.append(prefix + table)
            else:
                rows = table.split('\n')
                current = prefix
                for row in rows:
                    if len(current) + len(row) > TARGET_SIZE:
                        if len(current.strip()) >= MIN_CHUNK_LENGTH:
                            all_chunks.append(current.strip())
                        current = prefix + row + '\n'
                    else:
                        current += row + '\n'
                if len(current.strip()) >= MIN_CHUNK_LENGTH:
                    all_chunks.append(current.strip())

        # 서술형 청킹
        full_narrative = '\n'.join(narrative_blocks)
        if not full_narrative.strip():
            continue

        sentences = re.split(
            r'(?<=[다요음됨함임.])\s*\n|'
            r'(?<=[다요음됨함임.])\s{2,}|'
            r'\n\s*\n',
            full_narrative
        )
        sentences = [s.strip() for s in sentences if s.strip()]

        current_chunk = prefix
        prev_tail = ""

        for sent in sentences:
            if len(sent) < 5:
                continue
            if len(current_chunk) + len(sent) > TARGET_SIZE:
                if len(current_chunk.strip()) >= MIN_CHUNK_LENGTH:
                    all_chunks.append(current_chunk.strip())
                if prev_tail and len(prev_tail) < OVERLAP_SIZE:
                    current_chunk = prefix + prev_tail + '\n' + sent + '\n'
                else:
                    current_chunk = prefix + sent + '\n'
            else:
                current_chunk += sent + '\n'
            prev_tail = sent

        if len(current_chunk.strip()) >= MIN_CHUNK_LENGTH:
            all_chunks.append(current_chunk.strip())

    # ── 3단계: 품질 필터 ──
    quality_chunks = []
    for chunk in all_chunks:
        if len(chunk) < MIN_CHUNK_LENGTH:
            continue
        body = re.sub(r'^\[.*?\]\s*.*?\n', '', chunk, count=1)
        if _korean_ratio(body) < 0.15:
            continue
        if re.match(r'^[\d\s,.\-–—:/|%\[\]()]+$', body):
            continue
        quality_chunks.append(chunk)

    return quality_chunks


# ═══════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════

def load_checkpoint() -> set:
    if CHECKPOINT_FILE.exists():
        data = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        return set(data.get("done", []))
    return set()

def save_checkpoint(done: set):
    CHECKPOINT_FILE.write_text(
        json.dumps({"done": list(done)}, ensure_ascii=False),
        encoding="utf-8"
    )


def main():
    log.info("╔═══════════════════════════════════════════════╗")
    log.info("║  청킹 전용 일괄 처리 (GPU 불필요)            ║")
    log.info("║  추출 → 정제 → 초-하이엔드 청킹 → JSON 저장 ║")
    log.info("╚═══════════════════════════════════════════════╝")

    # 파일 수집 (.zip + .zip.pdf 모두 포함)
    zip_files = sorted([f for f in DATASET_DIR.glob("*.zip") if not f.name.endswith(".zip.pdf")])
    pdf_files = sorted(DATASET_DIR.glob("*.zip.pdf"))
    all_files = zip_files + pdf_files
    log.info(f"  데이터셋: {len(all_files)}건 (.zip={len(zip_files)} + .zip.pdf={len(pdf_files)})")

    # rcept_no 기준 중복 제거 (.zip 우선)
    rcept_map = {}
    for f in all_files:
        rno = _extract_rcept_no(f.name)
        rcept_map.setdefault(rno, []).append(f)

    unique_files = []
    for rno, files in rcept_map.items():
        # .zip 파일 우선, 없으면 .zip.pdf
        pure_zips = [f for f in files if f.name.endswith(".zip") and not f.name.endswith(".zip.pdf")]
        unique_files.append(pure_zips[0] if pure_zips else files[0])

    log.info(f"  유일 문서: {len(unique_files)}건")

    # 체크포인트
    done = load_checkpoint()
    remaining = [f for f in unique_files if _extract_rcept_no(f.name) not in done]
    log.info(f"  이미 완료: {len(done)}건 | 남은 문서: {len(remaining)}건")

    if not remaining:
        log.info("  ✅ 이미 모든 문서 청킹 완료!")
        return

    # 출력 파일 (Append 모드)
    out_f = open(OUTPUT_FILE, "a", encoding="utf-8")

    stats = {"success": 0, "skip": 0, "error": 0}
    t_start = time.time()

    for idx, filepath in enumerate(remaining, 1):
        if _shutdown:
            log.info(f"🛑 안전 중단 — {idx-1}/{len(remaining)}에서 중지")
            break

        rcept_no = _extract_rcept_no(filepath.name)

        try:
            # ── 1. 텍스트 추출 ──
            content = filepath.read_bytes()
            raw_text = extract_text_from_dart_zip(content, filepath.name)

            # 타입 방어
            if isinstance(raw_text, dict):
                raw_text = json.dumps(raw_text, ensure_ascii=False)
            elif isinstance(raw_text, (list, tuple)):
                raw_text = "\n".join(str(x) for x in raw_text)
            elif raw_text is not None:
                raw_text = str(raw_text)
            else:
                raw_text = ""

            if not raw_text or len(raw_text) < 20:
                # fallback: XML 파싱
                try:
                    z = zipfile.ZipFile(io.BytesIO(content))
                    from bs4 import BeautifulSoup
                    texts = []
                    for name in z.namelist():
                        if name.endswith(('.xml', '.xbrl')):
                            xml_data = z.read(name).decode('utf-8', errors='replace')
                            soup = BeautifulSoup(xml_data, "lxml-xml")
                            for tag in soup.find_all(True):
                                if tag.string and tag.string.strip() and len(tag.string.strip()) > 5:
                                    texts.append(tag.string.strip())
                    raw_text = "\n".join(texts)
                except Exception:
                    pass

            if not raw_text or len(raw_text) < 20:
                stats["skip"] += 1
                done.add(rcept_no)
                if idx % 100 == 0:
                    save_checkpoint(done)
                continue

            # ── 2. 텍스트 정제 ──
            cleaned = deep_clean_text(raw_text)
            if len(cleaned) < MIN_TEXT_LENGTH:
                stats["skip"] += 1
                done.add(rcept_no)
                if idx % 100 == 0:
                    save_checkpoint(done)
                continue

            # ── 3. 메타데이터 ──
            meta = extract_metadata(filepath.name, cleaned)

            # ── 4. 청킹 ──
            chunks = chunk_text_quality(cleaned, meta)

            # ── 5. JSONL 저장 ──
            record = {
                "rcept_no": rcept_no,
                "filename": filepath.name,
                "company": meta["company_name"],
                "category": meta["category"],
                "text_length": len(cleaned),
                "chunk_count": len(chunks),
                "chunks": chunks,
            }
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

            stats["success"] += 1
            done.add(rcept_no)

            # 진행률 (매 50건)
            if idx % 50 == 0:
                elapsed = time.time() - t_start
                rate = idx / max(elapsed, 1)
                eta = (len(remaining) - idx) / max(rate, 0.01)
                total_chunks = stats["success"]  # 로그용
                log.info(
                    f"  [{idx}/{len(remaining)}] "
                    f"성공={stats['success']} 스킵={stats['skip']} 에러={stats['error']} | "
                    f"속도={rate:.1f}건/초 | ETA={eta/60:.1f}분"
                )
                save_checkpoint(done)

        except Exception as e:
            stats["error"] += 1
            log.error(f"  ❌ [{idx}] {filepath.name[:40]}: {e}")
            done.add(rcept_no)

    # 최종 저장
    out_f.close()
    save_checkpoint(done)

    elapsed = time.time() - t_start
    log.info(f"\n{'='*50}")
    log.info(f"  완료!")
    log.info(f"  성공: {stats['success']} | 스킵: {stats['skip']} | 에러: {stats['error']}")
    log.info(f"  소요: {elapsed:.1f}초 ({elapsed/60:.1f}분)")
    log.info(f"  출력: {OUTPUT_FILE}")
    log.info(f"  체크포인트: {CHECKPOINT_FILE}")

    # 통계
    if OUTPUT_FILE.exists():
        total_chunks = 0
        doc_count = 0
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    total_chunks += rec.get("chunk_count", 0)
                    doc_count += 1
                except:
                    pass
        log.info(f"  총 문서: {doc_count}건 | 총 청크: {total_chunks:,}개")
        if doc_count > 0:
            log.info(f"  평균 청크/문서: {total_chunks/doc_count:.0f}개")


if __name__ == "__main__":
    main()
