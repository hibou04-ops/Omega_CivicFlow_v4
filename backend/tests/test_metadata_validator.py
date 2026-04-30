"""
메타데이터 앵커 링킹 시스템 테스트
MetadataValidator + SafeRenderContext + 기존 검증 호환성
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from services.metadata_validator import (
    MetadataValidator, SafeRenderContext, AnchoredField, metadata_validator
)
from services.llm_service import _validate_company_name
from services.pdf_report_service import _sanitize_company_for_pdf

passed = 0
failed = 0

def test(label, actual, expected):
    global passed, failed
    ok = actual == expected
    if not ok:
        print(f"  [FAIL] {label}: got '{actual}', expected '{expected}'")
        failed += 1
    else:
        passed += 1

print("=== 1. MetadataValidator 필드별 검증 ===")
print()

mv = MetadataValidator()

# 회사명 검증
print("[Company Name Validation]")
test("pure number", mv._validate_company_name("4,000,000"), "미확인")
test("large number", mv._validate_company_name("23,418,736"), "미확인")
test("sentence fragment", mv._validate_company_name("재무제표에 대한"), "미확인")
test("doc type", mv._validate_company_name("유상증자결정"), "미확인")
test("report name", mv._validate_company_name("주요사항보고서"), "미확인")
test("date", mv._validate_company_name("2026-03-12"), "미확인")
test("receipt no", mv._validate_company_name("20260313000587"), "미확인")
test("valid corp 1", mv._validate_company_name("주식회사 에이텀"), "주식회사 에이텀")
test("valid corp 2", mv._validate_company_name("삼성전자"), "삼성전자")
test("valid corp 3", mv._validate_company_name("(주)카카오"), "(주)카카오")
test("valid corp 4", mv._validate_company_name("LG에너지솔루션"), "LG에너지솔루션")

print()

# 공시명 검증
print("[Filing Title Validation]")
test("valid title", mv._validate_filing_title("정정신고서(주요사항보고서)"), "정정신고서(주요사항보고서)")
test("valid title 2", mv._validate_filing_title("사업보고서"), "사업보고서")
test("number reject", mv._validate_filing_title("12345678"), "미확인")
test("empty", mv._validate_filing_title(""), "미확인")

print()

# 카테고리 검증
print("[Category Validation]")
test("exact match", mv.validate_category("유상증자결정"), "유상증자결정")
test("exact match 2", mv.validate_category("사업보고서"), "사업보고서")
test("partial", mv.validate_category("유상증자"), "유상증자결정")
test("empty", mv.validate_category(""), "기타")

print()

# 날짜 검증
print("[Date Validation]")
test("valid date", mv._validate_date("2026-03-12"), "2026-03-12")
test("dot date", mv._validate_date("2026.03.12"), "2026.03.12")
test("invalid", mv._validate_date("not a date"), "미확인")

print()
print("=== 2. 앵커 기반 추출 테스트 ===")
print()

# 실제 DART 문서 패턴 시뮬레이션
test_text = """
주요사항보고서(유상증자결정)

회사명 : 주식회사 에이텀
접수일 : 2026-03-12
보고서명 : 주요사항보고서(유상증자결정)

1. 신주의 종류와 수 : 보통주 4,000,000 주
2. 1주당 신주 발행가액 : 5,000 원
"""

result = mv.extract_anchored_metadata(test_text)

test("company extracted", result["company_name"].value, "주식회사 에이텀")
test("company confirmed", result["company_name"].is_confirmed, True)
test("company confidence > 0.5", result["company_name"].confidence > 0.5, True)
test("filing title extracted", result["filing_title"].value, "주요사항보고서(유상증자결정)")
test("filing date extracted", result["filing_date"].value, "2026-03-12")

# 숫자만 있는 텍스트에서 회사명 추출 불가 테스트
bad_text = """
4,000,000 주
23,418,736 원
접수번호 20260313000587
"""
bad_result = mv.extract_anchored_metadata(bad_text)
test("no company from numbers", bad_result["company_name"].value, "미확인")
test("no company = not confirmed", bad_result["company_name"].is_confirmed, False)

print()
print("=== 3. SafeRenderContext 생성 테스트 ===")
print()

ctx = mv.build_safe_render_context(
    anchored=result,
    doc_type="유상증자결정",
    category="유상증자결정",
    llm_company="주식회사 에이텀",
)

test("safe company", ctx.safe_company_name, "주식회사 에이텀")
test("safe doc type", ctx.safe_document_type, "유상증자결정")
test("safe category", ctx.safe_category, "유상증자결정")
test("safe subject includes company", "에이텀" in ctx.safe_subject_for_summary, True)

# 회사명 없는 경우
bad_ctx = mv.build_safe_render_context(
    anchored=bad_result,
    doc_type="기타공시",
)
test("fallback company", bad_ctx.safe_company_name, "미확인")
test("fallback subject", bad_ctx.safe_subject_for_summary, "해당 공시는")

# to_dict() 직렬화 테스트
d = ctx.to_dict()
test("serializable", isinstance(d, dict), True)
test("has safe fields", "safe_company_name" in d, True)
test("has anchored fields", "company_name" in d, True)

print()
print("=== 4. 기존 함수 호환성 ===")
print()

test("old validate compat", _validate_company_name("4,000,000"), "미확인")
test("old validate valid", _validate_company_name("에이텀"), "에이텀")
test("old pdf sanitize", _sanitize_company_for_pdf("23,418,736"), "미확인")
test("old pdf valid", _sanitize_company_for_pdf("삼성전자"), "삼성전자")

print()
print(f"=== Result: {passed} passed, {failed} failed ===")
if failed > 0:
    sys.exit(1)
else:
    print("All tests passed!")
