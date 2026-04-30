"""
═══════════════════════════════════════════════════════
Omega CivicFlow — 초-하이엔드 QC/QA 검증 시스템
DB 내 analysis_results의 품질 결함을 체계적으로 감지/분류

감지 패턴:
  CRITICAL-01: 요약 = 근거 동일 (copy-paste 문제)
  CRITICAL-02: "근거 없음" (evidence 없음)
  CRITICAL-03: 허위 숫자/환각 (round number hallucination)
  CRITICAL-04: 핵심 재무지표 비정상 (영업이익: 1원 등)
  CRITICAL-05: summary 길이 부족 (<100자)
  WARNING-01:  summary에만 숫자 있고 OCR 원본에 없음
  WARNING-02:  generic template 패턴 (A, B, C / 1,200억 등)
  WARNING-03:  모든 숫자가 정수 반올림 (실제 DART 숫자와 불일치)
  INFO-01:     모델별 품질 통계
═══════════════════════════════════════════════════════
"""
import sys
import os
import re
import json
import time
import logging
from collections import defaultdict, Counter

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from database import SessionLocal
from models.models import AnalysisResult, Document

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# 결함 패턴 정의
# ═══════════════════════════════════════════════════════

# 허위 숫자 패턴 — 완벽히 라운드된 숫자 (실제 DART 숫자는 보통 비정수)
ROUND_NUMBER_PATTERN = re.compile(
    r'(\d{1,3})(,000)+(억|백만|천만|만)?\s*원'
)

# 템플릿 패턴 — LLM이 자주 사용하는 placeholder/generic 패턴
TEMPLATE_PATTERNS = [
    r'주요\s*제품은\s*A,?\s*B,?\s*C',
    r'주요\s*사업분야는\s*[A-Z],?\s*[A-Z],?\s*[A-Z]',
    r'주요\s*이벤트로는\s*신규\s*시장\s*진입',
    r'최근\s*주요\s*이벤트로는',
    r'인수합병\s*등이?\s*포함',
    r'COO가?\s*\d+억원,?\s*CFO가?\s*\d+억원',
    r'연봉은\s*COO',
    r'\[.*미제공.*\]',
    r'\[.*참고.*문서.*\]',
    r'\[.*데이터.*없.*\]',
]

# 핵심 재무지표 비정상 패턴 (영업이익: 1원, 당기순이익: 2원 등)
ABSURD_METRICS_PATTERN = re.compile(
    r'(영업이익|당기순이익|매출액|자산총계|부채총계|자본총계)[:\s]*(\d{1,2})\s*원'
)


def extract_numbers(text: str) -> list:
    """텍스트에서 숫자 추출"""
    return re.findall(r'[\d,]+(?:\.\d+)?', text)


def check_summary_evidence_duplicate(summary: str, evidence: str) -> bool:
    """요약과 근거가 동일/유사한지 체크"""
    if not summary or not evidence:
        return False

    s_clean = re.sub(r'\s+', '', summary)
    e_clean = re.sub(r'\s+', '', evidence)

    if not s_clean or not e_clean:
        return False

    # 완전 동일
    if s_clean == e_clean:
        return True

    # 80% 이상 겹침 (부분집합)
    shorter = min(s_clean, e_clean, key=len)
    longer = max(s_clean, e_clean, key=len)
    if len(shorter) > 50 and shorter in longer:
        return True

    # Jaccard 유사도 — 문장 단위
    s_sents = set(re.split(r'[.。!?\n]', summary))
    e_sents = set(re.split(r'[.。!?\n]', evidence))
    s_sents.discard('')
    e_sents.discard('')
    if s_sents and e_sents:
        overlap = len(s_sents & e_sents)
        total = len(s_sents | e_sents)
        if total > 0 and overlap / total > 0.6:
            return True

    return False


def check_no_evidence(evidence: str) -> bool:
    """근거가 없는지 체크"""
    if not evidence:
        return True
    e = evidence.strip()
    no_evidence_marks = [
        "근거 없음", "근거없음", "해당 없음", "해당없음",
        "없음", "N/A", "null", "정보 없음", "분석 실패",
        "응답 없음", "파싱 실패",
    ]
    return e in no_evidence_marks or len(e) < 10


def check_hallucinated_numbers(summary: str) -> dict:
    """허위 숫자 감지"""
    result = {"round_only": False, "absurd_metrics": [], "template_numbers": False}

    if not summary:
        return result

    # 1. 모든 숫자가 round number인지
    numbers = re.findall(r'([\d,]+)\s*(억|백만|천만|만)?\s*원', summary)
    if numbers:
        round_count = 0
        for num_str, _ in numbers:
            num = num_str.replace(',', '')
            if num.isdigit() and len(num) >= 2:
                # 100, 200, 500, 1000 등 깔끔한 숫자
                if int(num) % 100 == 0 or int(num) % 50 == 0:
                    round_count += 1
        if len(numbers) >= 3 and round_count / len(numbers) > 0.8:
            result["round_only"] = True

    # 2. 비정상 소액 재무지표 (영업이익: 1원)
    for m in ABSURD_METRICS_PATTERN.finditer(summary):
        result["absurd_metrics"].append(f"{m.group(1)}: {m.group(2)}원")

    return result


def check_template_patterns(summary: str) -> list:
    """템플릿/placeholder 감지"""
    found = []
    for pat in TEMPLATE_PATTERNS:
        if re.search(pat, summary, re.IGNORECASE):
            found.append(pat[:40])
    return found


def main():
    db = SessionLocal()
    try:
        all_records = db.query(AnalysisResult).all()
        total = len(all_records)

        logger.info(f"{'='*70}")
        logger.info(f"  Ω  초-하이엔드 QC/QA 검증 시스템")
        logger.info(f"  대상: {total}건")
        logger.info(f"{'='*70}\n")

        # 결함 분류 카운터
        defects = defaultdict(list)  # defect_code -> [ar_id, ...]
        model_stats = defaultdict(lambda: {"total": 0, "critical": 0, "warning": 0})
        severity_counts = {"CRITICAL": 0, "WARNING": 0, "PASS": 0}

        t0 = time.time()

        for ar in all_records:
            model = ar.model_name or "unknown"
            model_stats[model]["total"] += 1

            summary = ar.summary or ""
            evidence = ar.evidence or ""
            financial = ar.financial_metrics or ""
            has_critical = False
            has_warning = False

            # raw_response에서 evidence 추출 (플랫 필드가 비어있을 수 있음)
            if not evidence and ar.raw_response:
                raw = ar.raw_response
                if isinstance(raw, dict):
                    evidence = raw.get("evidence", "")
                    if isinstance(evidence, list):
                        evidence = " ".join(str(e) for e in evidence)

            # ─── CRITICAL-01: 요약 = 근거 동일 ───
            if check_summary_evidence_duplicate(summary, evidence):
                defects["CRITICAL-01"].append(ar.id)
                has_critical = True

            # ─── CRITICAL-02: 근거 없음 ───
            if check_no_evidence(evidence):
                defects["CRITICAL-02"].append(ar.id)
                has_critical = True

            # ─── CRITICAL-03: 허위 숫자 ───
            halluc = check_hallucinated_numbers(summary)
            if halluc["round_only"]:
                defects["CRITICAL-03"].append(ar.id)
                has_critical = True

            # ─── CRITICAL-04: 비정상 재무지표 ───
            if halluc["absurd_metrics"]:
                defects["CRITICAL-04"].append(ar.id)
                has_critical = True

            # ─── CRITICAL-05: summary 길이 부족 ───
            if len(summary) < 100:
                defects["CRITICAL-05"].append(ar.id)
                has_critical = True

            # ─── CRITICAL-06: summary = 오류 메시지 ───
            error_marks = ["분석 실패", "응답 없음", "파싱 실패", "처리 오류"]
            if any(m in summary for m in error_marks):
                defects["CRITICAL-06"].append(ar.id)
                has_critical = True

            # ─── WARNING-01: 템플릿 패턴 ───
            templates = check_template_patterns(summary)
            if templates:
                defects["WARNING-01"].append(ar.id)
                has_warning = True

            # ─── WARNING-02: financial_metrics 비정상 ───
            fm = financial.strip()
            if fm and ABSURD_METRICS_PATTERN.search(fm):
                defects["WARNING-02"].append(ar.id)
                has_warning = True

            # ─── WARNING-03: summary 내 숫자 밀도 부족 ───
            nums_in_summary = extract_numbers(summary)
            if len(summary) > 200 and len(nums_in_summary) < 3:
                defects["WARNING-03"].append(ar.id)
                has_warning = True

            # 통계
            if has_critical:
                model_stats[model]["critical"] += 1
                severity_counts["CRITICAL"] += 1
            elif has_warning:
                model_stats[model]["warning"] += 1
                severity_counts["WARNING"] += 1
            else:
                severity_counts["PASS"] += 1

        elapsed = time.time() - t0

        # ═══════════════════════════════════════════════════════
        # 결과 출력
        # ═══════════════════════════════════════════════════════

        lines = []
        def p(s=""):
            lines.append(s)
            logger.info(s)

        p(f"\n{'='*70}")
        p(f"  QC/QA 검증 결과 리포트")
        p(f"  검증 시간: {elapsed:.2f}초 | 대상: {total}건")
        p(f"{'='*70}")

        p(f"\n[종합 판정]")
        p(f"  ✅ PASS:     {severity_counts['PASS']:>5}건 ({severity_counts['PASS']/total*100:.1f}%)")
        p(f"  ⚠️  WARNING:  {severity_counts['WARNING']:>5}건 ({severity_counts['WARNING']/total*100:.1f}%)")
        p(f"  🔴 CRITICAL: {severity_counts['CRITICAL']:>5}건 ({severity_counts['CRITICAL']/total*100:.1f}%)")

        p(f"\n[결함 상세]")
        defect_desc = {
            "CRITICAL-01": "요약 ≈ 근거 동일 (copy-paste)",
            "CRITICAL-02": "근거 없음 / 비어있음",
            "CRITICAL-03": "허위 round number 환각",
            "CRITICAL-04": "재무지표 비정상 (1원, 2원 등)",
            "CRITICAL-05": "요약 100자 미만",
            "CRITICAL-06": "오류 메시지가 요약에 포함",
            "WARNING-01": "템플릿/placeholder 패턴",
            "WARNING-02": "재무지표 필드 비정상",
            "WARNING-03": "숫자 밀도 부족 (<3개)",
        }
        for code in sorted(defects.keys()):
            count = len(defects[code])
            desc = defect_desc.get(code, "")
            p(f"  {code}: {count:>5}건 — {desc}")

        p(f"\n[모델별 품질 분포]")
        p(f"  {'모델명':<35} {'전체':>6} {'CRITICAL':>10} {'경고':>6} {'합격률':>8}")
        p(f"  {'-'*35} {'-'*6} {'-'*10} {'-'*6} {'-'*8}")
        for model, stats in sorted(model_stats.items(), key=lambda x: -x[1]["total"]):
            total_m = stats["total"]
            crit = stats["critical"]
            warn = stats["warning"]
            pass_rate = (total_m - crit - warn) / total_m * 100 if total_m > 0 else 0
            p(f"  {model:<35} {total_m:>6} {crit:>10} {warn:>6} {pass_rate:>7.1f}%")

        # CRITICAL 샘플 출력
        p(f"\n[CRITICAL 결함 샘플]")
        for code in ["CRITICAL-01", "CRITICAL-04", "CRITICAL-03"]:
            if code in defects and defects[code]:
                samples = defects[code][:3]
                p(f"\n  --- {code}: {defect_desc.get(code, '')} ---")
                for ar_id in samples:
                    ar = db.query(AnalysisResult).filter(AnalysisResult.id == ar_id).first()
                    if ar:
                        doc = db.query(Document).filter(Document.id == ar.document_id).first()
                        fname = doc.filename[:50] if doc else "N/A"
                        p(f"  AR#{ar.id} | doc#{ar.document_id} | {fname}")
                        p(f"    요약: {(ar.summary or '')[:120]}...")
                        ev = ar.evidence or ""
                        if isinstance(ar.raw_response, dict):
                            ev = ar.raw_response.get("evidence", ev)
                            if isinstance(ev, list):
                                ev = " | ".join(str(e) for e in ev)
                        p(f"    근거: {str(ev)[:120]}...")
                        p(f"    재무: {(ar.financial_metrics or '')[:80]}")

        # ═══ 리포트 파일 저장 ═══
        report_path = os.path.join(BACKEND_DIR, "_qc_report.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        p(f"\n  📄 리포트 저장: {report_path}")

        # ═══ CRITICAL ID 목록 저장 (재처리용) ═══
        critical_ids = set()
        for code, ids in defects.items():
            if code.startswith("CRITICAL"):
                critical_ids.update(ids)

        critical_data = {
            "total_critical": len(critical_ids),
            "defect_counts": {code: len(ids) for code, ids in defects.items()},
            "critical_ids": sorted(critical_ids),
            "critical_doc_ids": [],
        }
        # doc_id 매핑
        for ar_id in critical_ids:
            ar = db.query(AnalysisResult).filter(AnalysisResult.id == ar_id).first()
            if ar:
                critical_data["critical_doc_ids"].append(ar.document_id)
        critical_data["critical_doc_ids"] = sorted(set(critical_data["critical_doc_ids"]))

        critical_path = os.path.join(BACKEND_DIR, "_qc_critical_ids.json")
        with open(critical_path, "w", encoding="utf-8") as f:
            json.dump(critical_data, f, ensure_ascii=False, indent=2)
        p(f"  📄 CRITICAL ID 목록: {critical_path}")
        p(f"     재처리 필요 문서: {len(critical_data['critical_doc_ids'])}건")

        p(f"\n{'='*70}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
