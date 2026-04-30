"""
═══════════════════════════════════════════════════════
Omega CivicFlow — QC/QA 무결성 검증 스크립트 v2
엔트로피 소각 검증 엔진 — 전수 데이터 무결성 검사

검증 항목:
  1. 중국어 잔존 검출 (summary, raw_response 전 필드)
  2. 회사명 무결성 (숫자형, 주소형, 문서유형 overkill)
  3. 요약문 품질 (너무 짧거나 빈 summary)
  4. 카테고리 정합성 (빈 카테고리, "기타" 과다)
  5. PDF 보고서 누락 (report_path 없는 문서)
  6. 분석 결과 누락 (analyzed인데 AnalysisResult 없음)
  7. raw_response JSON 구조 검증
  8. 파일 경로 존재 여부 (report_path 실제 파일)
═══════════════════════════════════════════════════════
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import json
import csv
import logging
from datetime import datetime
from collections import Counter, defaultdict
from pathlib import Path

from database import SessionLocal
from models.models import Document, AnalysisResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
# 검사 규칙
# ═══════════════════════════════════════════════════════

# 중국어 범위 (CJK Unified Ideographs)
CJK_RANGE = re.compile(r'[\u4e00-\u9fff]')

# 카테고리 자동 수정 매핑 (간체/번체/깨진 이름 → 정상)
CATEGORY_FIX_MAP = {
    "事业报告书": "사업보고서", "事業報告書": "사업보고서",
    "财务报表": "재무제표", "財務報表": "재무제표",
    "审计报告": "감사보고서", "審計報告": "감사보고서",
    "重大事项报告书": "주요사항보고서",
    "更正申报": "정정신고(보고)",
    "有偿增资决定": "유상증자결정",
    "大量保有报告书": "대량보유보고서",
    "自己股票": "자기주식",
    "合并分割": "합병·분할",
    "배당금": "배당",
    "감자 결정": "감자결정",
}

# 숫자형 회사명 패턴
NUMERIC_COMPANY_PATTERNS = [
    re.compile(r'^[\d,.\s]+$'),                     # 순수 숫자
    re.compile(r'^[\d,]+(?:\s*주)?$'),               # 주식수
    re.compile(r'^[\d,]+(?:\s*원)?$'),               # 금액
    re.compile(r'^\d{8,}$'),                         # 접수번호
    re.compile(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}'),  # 날짜
    re.compile(r'\d{4}년'),                          # 연도
]

# 문서유형을 회사명으로 잘못 넣은 경우
DOC_TYPE_AS_COMPANY = [
    "주요사항보고서", "유상증자결정", "사업보고서", "감사보고서",
    "정정신고", "재무제표", "현금흐름표", "손익계산서", "재무상태표",
    "기타공시", "주석", "반기보고서", "분기보고서", "대량보유보고서",
    "자기주식", "합병", "분할", "배당",
]


# ═══════════════════════════════════════════════════════
# 검증 함수
# ═══════════════════════════════════════════════════════

def count_chinese(text: str) -> int:
    """텍스트 내 중국어 문자 수"""
    if not text:
        return 0
    return len(CJK_RANGE.findall(text))


def extract_chinese_snippets(text: str, max_snippets: int = 3) -> list:
    """중국어가 포함된 부분을 컨텍스트와 함께 추출"""
    if not text:
        return []
    snippets = []
    for m in CJK_RANGE.finditer(text):
        start = max(0, m.start() - 15)
        end = min(len(text), m.end() + 15)
        snippet = text[start:end].replace('\n', ' ').strip()
        if snippet not in snippets:
            snippets.append(f"...{snippet}...")
        if len(snippets) >= max_snippets:
            break
    return snippets


def check_company_name(company: str) -> list:
    """회사명 무결성 검증 — 문제 목록 반환"""
    issues = []
    if not company or not company.strip():
        issues.append("EMPTY_COMPANY")
        return issues

    name = company.strip()

    if name == "미확인":
        issues.append("UNIDENTIFIED")
        return issues

    # 중국어 포함
    cn_count = count_chinese(name)
    if cn_count > 0:
        issues.append(f"CHINESE_IN_COMPANY({cn_count}자)")

    # 숫자형
    for pat in NUMERIC_COMPANY_PATTERNS:
        if pat.search(name):
            issues.append("NUMERIC_COMPANY")
            break

    # 숫자 비율 과다 (50% 이상)
    digits = sum(1 for c in name if c.isdigit())
    total = sum(1 for c in name if not c.isspace())
    if total > 0 and (digits / total) > 0.5:
        issues.append("DIGIT_HEAVY_COMPANY")

    # 문서유형이 회사명에
    for dt in DOC_TYPE_AS_COMPANY:
        if name.startswith(dt):
            issues.append(f"DOCTYPE_AS_COMPANY({dt})")
            break

    # 너무 길거나 짧음
    if len(name) > 30:
        issues.append(f"COMPANY_TOO_LONG({len(name)}자)")
    elif len(name) < 2:
        issues.append(f"COMPANY_TOO_SHORT({len(name)}자)")

    # 주소 패턴
    address_keywords = ['구 ', '동 ', '번지', '서울', '경기', '부산']
    for kw in address_keywords:
        if kw in name:
            issues.append(f"ADDRESS_IN_COMPANY({kw})")
            break

    return issues


def check_raw_response(raw) -> dict:
    """raw_response 전체 필드 중국어/무결성 검사"""
    result = {
        "chinese_fields": [],
        "chinese_total": 0,
        "summary_length": 0,
        "has_company": False,
        "company_name": "",
        "category": "",
        "has_key_points": False,
    }

    if not raw:
        return result

    # raw가 문자열이면 JSON 파싱
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, str):
                data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            # 파싱 실패 — 전체 텍스트로 중국어 체크
            cn = count_chinese(raw)
            if cn > 0:
                result["chinese_fields"].append(("raw_text", cn, extract_chinese_snippets(raw)))
                result["chinese_total"] = cn
            return result

    if not isinstance(data, dict):
        return result

    # 주요 필드별 중국어 검사
    text_fields = [
        "summary", "company_name", "disclosure_title", "category",
        "event_type", "insight_vectors", "evidence", "financial_metrics",
    ]
    for field in text_fields:
        val = data.get(field)
        if isinstance(val, str):
            cn = count_chinese(val)
            if cn > 0:
                result["chinese_fields"].append(
                    (field, cn, extract_chinese_snippets(val, 2))
                )
                result["chinese_total"] += cn

    # key_points 검사
    kp = data.get("key_points", [])
    if isinstance(kp, list):
        result["has_key_points"] = len(kp) > 0
        for i, pt in enumerate(kp):
            if isinstance(pt, str):
                cn = count_chinese(pt)
                if cn > 0:
                    result["chinese_fields"].append(
                        (f"key_points[{i}]", cn, extract_chinese_snippets(pt, 1))
                    )
                    result["chinese_total"] += cn

    # risk_notes 검사
    rn = data.get("risk_notes", [])
    if isinstance(rn, list):
        for i, note in enumerate(rn):
            if isinstance(note, str):
                cn = count_chinese(note)
                if cn > 0:
                    result["chinese_fields"].append(
                        (f"risk_notes[{i}]", cn, extract_chinese_snippets(note, 1))
                    )
                    result["chinese_total"] += cn

    # evidence_detailed 검사
    ev = data.get("evidence_detailed", data.get("evidence", []))
    if isinstance(ev, list):
        for i, item in enumerate(ev):
            if isinstance(item, dict):
                for k in ["quote", "why_it_matters"]:
                    val = item.get(k)
                    if isinstance(val, str):
                        cn = count_chinese(val)
                        if cn > 0:
                            result["chinese_fields"].append(
                                (f"evidence[{i}].{k}", cn, extract_chinese_snippets(val, 1))
                            )
                            result["chinese_total"] += cn

    # 메타 정보 추출
    summary = data.get("summary", "")
    result["summary_length"] = len(summary) if isinstance(summary, str) else 0
    result["company_name"] = data.get("company_name", "")
    result["category"] = data.get("category", "")
    result["has_company"] = bool(result["company_name"] and result["company_name"] != "미확인")

    return result


# ═══════════════════════════════════════════════════════
# 메인 검증 루프
# ═══════════════════════════════════════════════════════

def run_qc_verification():
    """전수 QC/QA 무결성 검증 실행"""
    db = SessionLocal()
    try:
        # 전체 문서 조회
        docs = db.query(Document).order_by(Document.id).all()
        total = len(docs)
        logger.info(f"{'='*70}")
        logger.info(f"  QC/QA 무결성 검증 시작 — 전체 {total}건")
        logger.info(f"{'='*70}")

        # 결과 집계
        issues_by_type = Counter()
        issue_docs = []  # (doc_id, filename, [issues])
        category_counter = Counter()
        company_counter = Counter()
        chinese_docs = []
        company_issue_docs = []
        summary_short_docs = []
        no_analysis_docs = []
        no_pdf_docs = []
        pdf_missing_file = []

        for i, doc in enumerate(docs, 1):
            doc_issues = []

            # 1. 분석결과 존재 여부
            analysis = (
                db.query(AnalysisResult)
                .filter(AnalysisResult.document_id == doc.id)
                .order_by(AnalysisResult.id.desc())
                .first()
            )

            if doc.status == "analyzed" and not analysis:
                doc_issues.append("NO_ANALYSIS_RESULT")
                no_analysis_docs.append(doc.id)
                issues_by_type["NO_ANALYSIS_RESULT"] += 1

            if not analysis:
                if doc_issues:
                    issue_docs.append((doc.id, doc.filename, doc_issues))
                continue

            # 2. raw_response 검사
            raw_check = check_raw_response(analysis.raw_response)

            # 3. 중국어 잔존 (summary + raw_response)
            summary_cn = count_chinese(analysis.summary or "")
            total_cn = summary_cn + raw_check["chinese_total"]

            if total_cn > 0:
                cn_detail = []
                if summary_cn > 0:
                    cn_detail.append(f"summary({summary_cn}자)")
                for field, cnt, snippets in raw_check["chinese_fields"]:
                    cn_detail.append(f"{field}({cnt}자)")
                doc_issues.append(f"CHINESE_FOUND: {', '.join(cn_detail)} [총 {total_cn}자]")
                chinese_docs.append({
                    "id": doc.id,
                    "filename": doc.filename,
                    "total_cn": total_cn,
                    "summary_cn": summary_cn,
                    "fields": raw_check["chinese_fields"],
                })
                issues_by_type["CHINESE_FOUND"] += 1

            # 4. 회사명 무결성
            company = raw_check["company_name"] or ""
            company_issues = check_company_name(company)
            if company_issues:
                doc_issues.extend(company_issues)
                company_issue_docs.append({
                    "id": doc.id,
                    "filename": doc.filename,
                    "company": company,
                    "issues": company_issues,
                })
                for ci in company_issues:
                    issue_key = ci.split("(")[0]  # 괄호 앞 키만
                    issues_by_type[issue_key] += 1
            else:
                company_counter[company] += 1

            # 5. 요약문 품질
            summary_len = raw_check["summary_length"]
            if summary_len == 0:
                doc_issues.append("EMPTY_SUMMARY")
                summary_short_docs.append((doc.id, summary_len))
                issues_by_type["EMPTY_SUMMARY"] += 1
            elif summary_len < 50:
                doc_issues.append(f"SHORT_SUMMARY({summary_len}자)")
                summary_short_docs.append((doc.id, summary_len))
                issues_by_type["SHORT_SUMMARY"] += 1

            # 6. 카테고리 정합성
            cat = raw_check["category"] or analysis.category or "미분류"
            category_counter[cat] += 1
            if cat in ("기타", "기타공시", "미분류", ""):
                doc_issues.append(f"WEAK_CATEGORY({cat})")
                issues_by_type["WEAK_CATEGORY"] += 1

            # 7. PDF 보고서 존재
            if not doc.report_path:
                doc_issues.append("NO_PDF_REPORT")
                no_pdf_docs.append(doc.id)
                issues_by_type["NO_PDF_REPORT"] += 1
            elif not os.path.exists(doc.report_path):
                doc_issues.append("PDF_FILE_MISSING")
                pdf_missing_file.append((doc.id, doc.report_path))
                issues_by_type["PDF_FILE_MISSING"] += 1

            # 집계
            if doc_issues:
                issue_docs.append((doc.id, doc.filename, doc_issues))

            if i % 200 == 0:
                logger.info(f"  ├─ 진행: {i}/{total} ({i/total*100:.0f}%)")

        # ═══════════════════════════════════════════════════════
        # 결과 출력
        # ═══════════════════════════════════════════════════════

        clean_count = total - len(issue_docs)
        logger.info(f"\n{'='*70}")
        logger.info(f"  QC/QA 무결성 검증 완료")
        logger.info(f"{'='*70}")
        logger.info(f"  ✅ 정상: {clean_count}건 ({clean_count/total*100:.1f}%)")
        logger.info(f"  ❌ 이슈: {len(issue_docs)}건 ({len(issue_docs)/total*100:.1f}%)")
        logger.info(f"{'='*70}")

        # 이슈 유형별 집계
        logger.info(f"\n  ── 이슈 유형별 집계 ──")
        for issue_type, count in issues_by_type.most_common():
            logger.info(f"    {issue_type}: {count}건")

        # 중국어 잔존 상세
        if chinese_docs:
            logger.info(f"\n  ── 중국어 잔존 상세 (총 {len(chinese_docs)}건) ──")
            for cd in sorted(chinese_docs, key=lambda x: x["total_cn"], reverse=True)[:20]:
                fields_str = ", ".join(f"{f}({c})" for f, c, _ in cd["fields"])
                logger.info(f"    #{cd['id']} [{cd['filename'][:40]}] — {cd['total_cn']}자 ({fields_str})")
                for field, cnt, snippets in cd["fields"]:
                    for s in snippets[:2]:
                        logger.info(f"      └─ {field}: {s}")

        # 회사명 이슈 상세
        if company_issue_docs:
            logger.info(f"\n  ── 회사명 이슈 상세 (총 {len(company_issue_docs)}건) ──")
            for cd in company_issue_docs[:30]:
                logger.info(f"    #{cd['id']} [{cd['filename'][:40]}] — 회사명: '{cd['company']}' → {cd['issues']}")

        # 짧은 요약
        if summary_short_docs:
            logger.info(f"\n  ── 짧은/빈 요약 (총 {len(summary_short_docs)}건) ──")
            for doc_id, slen in summary_short_docs[:10]:
                logger.info(f"    #{doc_id} — {slen}자")

        # 카테고리 분포
        logger.info(f"\n  ── 카테고리 분포 ──")
        for cat, count in category_counter.most_common():
            logger.info(f"    {cat}: {count}건")

        # 회사명 TOP 20
        logger.info(f"\n  ── 회사명 TOP 20 (정상 판정) ──")
        for name, count in company_counter.most_common(20):
            logger.info(f"    {name}: {count}건")

        # ═══════════════════════════════════════════════════════
        # CSV 리포트 저장
        # ═══════════════════════════════════════════════════════

        report_path = Path("integrity_report.csv")
        with open(report_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["doc_id", "filename", "issues", "severity"])
            for doc_id, filename, issues in sorted(issue_docs, key=lambda x: len(x[2]), reverse=True):
                severity = "CRITICAL" if any("CHINESE" in i for i in issues) else \
                          "HIGH" if any("COMPANY" in i or "NUMERIC" in i for i in issues) else \
                          "MEDIUM" if any("SUMMARY" in i for i in issues) else "LOW"
                writer.writerow([doc_id, filename, " | ".join(issues), severity])

        logger.info(f"\n  📄 상세 리포트 저장: {report_path.absolute()}")
        logger.info(f"{'='*70}")

        # 전체 요약 반환
        return {
            "total": total,
            "clean": clean_count,
            "issues": len(issue_docs),
            "chinese_count": len(chinese_docs),
            "company_issues": len(company_issue_docs),
            "summary_issues": len(summary_short_docs),
        }

    finally:
        db.close()


if __name__ == "__main__":
    run_qc_verification()
