"""
═══════════════════════════════════════════════════════
Omega CivicFlow — 통합 무결성 검증 (Integrity Audit)
═══════════════════════════════════════════════════════

실행: python -m tests.test_integrity
       (backend/ 디렉토리에서 실행)

검증 영역:
  1. DB 연결 & 기본 무결성
  2. raw_response 이중 인코딩 탐지 & 필드 추출 검증
  3. LLM 분석 품질 (빈 요약, 에러 요약, 중국어 혼입)
  4. PDF 렌더링 품질 (페이지 수, 빈 페이지, 섹션 연속성)
  5. 서비스 연결 (Ollama, DART API)
  6. 설정 무결성 (.env 필수 키)
"""

import os
import sys
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 path에 추가
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Windows cp949 인코딩 문제 방지
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = BACKEND_DIR / "omega_civicflow.db"

# ═══ 결과 수집 ═══
_results = []

def _log(level: str, msg: str):
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "INFO": "ℹ️"}.get(level, "  ")
    tag = f"[{level}]"
    print(f"  {icon} {tag:6s} {msg}")
    _results.append((level, msg))


def _header(title: str):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


# ═══════════════════════════════════════════════════════
# 1. DB 연결 & 기본 무결성
# ═══════════════════════════════════════════════════════

def check_db_connection():
    _header("1. DB 연결 & 기본 무결성")
    if not DB_PATH.exists():
        _log("FAIL", f"DB 파일 없음: {DB_PATH}")
        return None

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # 테이블 존재 확인
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    required = ["documents", "analysis_results", "users", "ocr_texts", "pages"]
    for t in required:
        if t in tables:
            _log("PASS", f"테이블 '{t}' 존재")
        else:
            _log("FAIL", f"테이블 '{t}' 누락")

    # 문서 수 집계
    cur.execute("SELECT COUNT(*) FROM documents")
    total_docs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM documents WHERE status='analyzed'")
    analyzed = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM documents WHERE status='failed'")
    failed = cur.fetchone()[0]
    _log("INFO", f"문서 총 {total_docs}건 (분석 완료: {analyzed}, 실패: {failed})")

    # 분석 결과 없는 analyzed 문서 탐지
    cur.execute("""
        SELECT d.id FROM documents d
        LEFT JOIN analysis_results a ON d.id = a.document_id
        WHERE d.status = 'analyzed' AND a.id IS NULL
    """)
    orphans = cur.fetchall()
    if orphans:
        _log("FAIL", f"분석 결과 누락된 analyzed 문서 {len(orphans)}건: {[r[0] for r in orphans[:5]]}")
    else:
        _log("PASS", "모든 analyzed 문서에 분석 결과 존재")

    return conn


# ═══════════════════════════════════════════════════════
# 2. raw_response 이중 인코딩 탐지
# ═══════════════════════════════════════════════════════

def check_double_encoding(conn):
    _header("2. raw_response 인코딩 무결성")
    cur = conn.cursor()
    cur.execute("SELECT document_id, raw_response FROM analysis_results WHERE raw_response IS NOT NULL")

    total = 0
    double_encoded = 0
    decode_fail = 0
    missing_fields = 0

    REQUIRED_FIELDS = ["summary", "category", "document_type"]

    for doc_id, raw in cur.fetchall():
        total += 1
        try:
            decoded = json.loads(raw)

            # 이중 인코딩 감지
            if isinstance(decoded, str):
                double_encoded += 1
                try:
                    decoded = json.loads(decoded)
                except:
                    decode_fail += 1
                    continue

            if isinstance(decoded, dict):
                for field in REQUIRED_FIELDS:
                    if field not in decoded:
                        missing_fields += 1
                        break
        except (json.JSONDecodeError, TypeError):
            decode_fail += 1

    if double_encoded > 0:
        _log("WARN", f"이중 인코딩 문서 {double_encoded}/{total}건 (pdf_report_service에서 자동 보정)")
    else:
        _log("PASS", f"이중 인코딩 없음 ({total}건 검증)")

    if decode_fail > 0:
        _log("FAIL", f"JSON 디코딩 실패 {decode_fail}건")
    else:
        _log("PASS", "모든 raw_response JSON 파싱 정상")

    if missing_fields > 0:
        _log("WARN", f"필수 필드 누락 {missing_fields}건")
    else:
        _log("PASS", "모든 분석 결과 필수 필드 존재")


# ═══════════════════════════════════════════════════════
# 3. LLM 분석 품질
# ═══════════════════════════════════════════════════════

def _has_chinese(text: str) -> bool:
    """CJK Unified Ideographs 비율이 5% 이상이면 중국어 혼입 판정"""
    if not text:
        return False
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total = len(text.replace(" ", ""))
    return total > 0 and (cjk / total) > 0.05


def check_llm_quality(conn):
    _header("3. LLM 분석 품질 검증")
    cur = conn.cursor()
    cur.execute("SELECT document_id, summary, category, raw_response FROM analysis_results")

    total = 0
    empty_summary = 0
    error_summary = 0
    chinese_detected = []
    invalid_category = 0

    ERROR_PREFIXES = ("분석 중 오류", "LLM 분석 실패", "All connection", "분석할 텍스트")
    VALID_CATEGORIES = {
        "재무제표", "사업보고서", "감사보고서", "주요사항보고서",
        "유상증자결정", "공개매수", "합병", "분할", "자기주식",
        "정정신고(보고)", "기타공시", "기타",
    }

    for doc_id, summary, category, raw_resp in cur.fetchall():
        total += 1

        # 빈 요약
        if not summary or len(summary.strip()) < 10:
            empty_summary += 1

        # 에러 요약
        if summary and any(summary.startswith(p) for p in ERROR_PREFIXES):
            error_summary += 1

        # 중국어 혼입 (summary + evidence)
        if _has_chinese(summary or ""):
            chinese_detected.append(("summary", doc_id))

        # raw_response 내 evidence 중국어 체크
        if raw_resp:
            try:
                d = json.loads(raw_resp)
                if isinstance(d, str):
                    d = json.loads(d)
                ev = d.get("evidence", "")
                if isinstance(ev, str) and _has_chinese(ev):
                    chinese_detected.append(("evidence", doc_id))
                elif isinstance(ev, list):
                    for item in ev:
                        txt = item.get("quote", "") if isinstance(item, dict) else str(item)
                        if _has_chinese(txt):
                            chinese_detected.append(("evidence_item", doc_id))
                            break
            except:
                pass

        # 카테고리 유효성
        if category and category not in VALID_CATEGORIES:
            invalid_category += 1

    if empty_summary > 0:
        _log("WARN", f"빈/짧은 요약 {empty_summary}/{total}건")
    else:
        _log("PASS", f"모든 요약 10자 이상 ({total}건)")

    if error_summary > 0:
        _log("WARN", f"에러 요약 {error_summary}건 (재분석 필요)")
    else:
        _log("PASS", "에러 요약 없음")

    if chinese_detected:
        _log("WARN", f"중국어 혼입 감지 {len(chinese_detected)}건: "
             f"{chinese_detected[:3]}")
    else:
        _log("PASS", "중국어 혼입 없음")

    if invalid_category > 0:
        _log("WARN", f"비표준 카테고리 {invalid_category}건")
    else:
        _log("PASS", "모든 카테고리 유효")


# ═══════════════════════════════════════════════════════
# 4. PDF 렌더링 품질 (샘플링)
# ═══════════════════════════════════════════════════════

def check_pdf_quality(conn):
    _header("4. PDF 렌더링 품질 (샘플 검증)")
    cur = conn.cursor()

    # 최근 분석 완료 문서 5건 샘플
    cur.execute("""
        SELECT d.id, d.filename, a.summary, a.category, a.raw_response
        FROM documents d
        JOIN analysis_results a ON d.id = a.document_id
        WHERE d.status = 'analyzed'
        ORDER BY d.id DESC LIMIT 5
    """)
    samples = cur.fetchall()

    if not samples:
        _log("WARN", "분석 완료 문서 없음 — PDF 검증 skip")
        return

    try:
        from services.pdf_report_service import generate_pdf_report
    except ImportError as e:
        _log("FAIL", f"pdf_report_service import 실패: {e}")
        return

    try:
        import fitz  # PyMuPDF
    except ImportError:
        _log("WARN", "PyMuPDF 미설치 — 페이지 검증 skip (pip install PyMuPDF)")
        return

    issues = []
    for doc_id, fname, summary, category, raw_resp in samples:
        analysis_data = {
            "summary": summary, "category": category,
            "raw_response": raw_resp,
            "financial_metrics": "", "insight_vectors": "", "evidence": "",
        }
        try:
            path = generate_pdf_report(doc_id, fname, analysis_data)
            if not path:
                issues.append((doc_id, "PDF 생성 실패"))
                continue

            doc = fitz.open(path)
            page_count = len(doc)
            empty_pages = 0
            for page in doc:
                text = page.get_text().strip()
                # 헤더+푸터만 있는 페이지 = 빈 페이지 (~60자 이하)
                if len(text) < 60:
                    empty_pages += 1
            doc.close()

            if page_count > 4:
                issues.append((doc_id, f"페이지 과다: {page_count}p"))
            if empty_pages > 0:
                issues.append((doc_id, f"빈 페이지 {empty_pages}개"))

            # 테스트 PDF 삭제
            try:
                os.remove(path)
            except:
                pass

        except Exception as e:
            issues.append((doc_id, f"PDF 생성 에러: {str(e)[:60]}"))

    if issues:
        for doc_id, msg in issues:
            _log("FAIL" if "실패" in msg or "에러" in msg else "WARN", f"문서 #{doc_id}: {msg}")
    else:
        _log("PASS", f"PDF 렌더링 정상 ({len(samples)}건 샘플 검증)")


# ═══════════════════════════════════════════════════════
# 5. 서비스 연결 확인
# ═══════════════════════════════════════════════════════

def check_services():
    _header("5. 외부 서비스 연결")

    import urllib.request

    # Ollama
    try:
        req = urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
        if req.status == 200:
            _log("PASS", "Ollama 연결 정상")
        else:
            _log("WARN", f"Ollama 응답 비정상: {req.status}")
    except Exception as e:
        _log("WARN", f"Ollama 미연결 (LLM 분석 불가): {str(e)[:40]}")

    # DART API
    try:
        req = urllib.request.urlopen("https://opendart.fss.or.kr", timeout=5)
        if req.status < 500:
            _log("PASS", "DART API 연결 정상")
        else:
            _log("WARN", f"DART API 응답 비정상: {req.status}")
    except Exception as e:
        _log("WARN", f"DART API 연결 실패: {str(e)[:40]}")

    # Backend API
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8000/docs", timeout=3)
        if req.status == 200:
            _log("PASS", "Backend API (FastAPI) 실행 중")
        else:
            _log("WARN", f"Backend API 상태: {req.status}")
    except Exception as e:
        _log("WARN", f"Backend API 미실행: {str(e)[:40]}")


# ═══════════════════════════════════════════════════════
# 6. 설정 무결성
# ═══════════════════════════════════════════════════════

def check_config():
    _header("6. 설정 (.env) 무결성")
    env_path = BACKEND_DIR / ".env"

    if not env_path.exists():
        _log("FAIL", ".env 파일 없음")
        return

    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()

    required_keys = [
        "JWT_SECRET_KEY", "OLLAMA_BASE_URL", "OLLAMA_MODEL",
        "GCP_PROJECT_ID", "GCP_KEY_PATH",
        "DART_API_KEY",
    ]

    for key in required_keys:
        pattern = rf"^{key}=.+"
        if re.search(pattern, content, re.MULTILINE):
            _log("PASS", f"{key} 설정됨")
        else:
            _log("FAIL", f"{key} 누락 또는 빈 값")

    # GCP 키 파일 존재 확인
    for line in content.split("\n"):
        if line.startswith("GCP_KEY_PATH=") or line.startswith("CHAT_GCP_KEY_PATH="):
            key_path = line.split("=", 1)[1].strip()
            if key_path and os.path.exists(key_path):
                _log("PASS", f"GCP 키 파일 존재: {Path(key_path).name}")
            elif key_path:
                _log("FAIL", f"GCP 키 파일 없음: {key_path}")


# ═══════════════════════════════════════════════════════
# 실행
# ═══════════════════════════════════════════════════════

def main():
    print()
    print("═" * 54)
    print("  Ω  OMEGA CIVICFLOW — QC/QA 무결성 검증")
    print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 54)

    t0 = time.time()

    # 1. DB
    conn = check_db_connection()
    if not conn:
        print("\n❌ DB 연결 실패 — 검증 중단")
        return 1

    # 2. 인코딩
    check_double_encoding(conn)

    # 3. LLM 품질
    check_llm_quality(conn)

    # 4. PDF 렌더링
    check_pdf_quality(conn)

    conn.close()

    # 5. 서비스
    check_services()

    # 6. 설정
    check_config()

    # ── 결과 요약 ──
    elapsed = time.time() - t0
    pass_count = sum(1 for r in _results if r[0] == "PASS")
    fail_count = sum(1 for r in _results if r[0] == "FAIL")
    warn_count = sum(1 for r in _results if r[0] == "WARN")
    info_count = sum(1 for r in _results if r[0] == "INFO")

    print()
    print("═" * 54)
    print(f"  총 검증: {len(_results)}  |  "
          f"✅ PASS: {pass_count}  |  "
          f"⚠️ WARN: {warn_count}  |  "
          f"❌ FAIL: {fail_count}")
    print(f"  소요 시간: {elapsed:.1f}초")
    print("═" * 54)

    if fail_count > 0:
        print("\n  ❌ 무결성 검증 실패 — 위 FAIL 항목을 확인하세요.")
        return 1
    elif warn_count > 0:
        print("\n  ⚠️ 경고 항목 존재 — 정상 동작하나 개선 필요")
        return 0
    else:
        print("\n  ✅ 전체 무결성 검증 통과!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
