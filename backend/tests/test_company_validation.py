"""
회사명 검증 함수 테스트 — _validate_company_name()
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from services.llm_service import _validate_company_name
from services.pdf_report_service import _sanitize_company_for_pdf

passed = 0
failed = 0

def test(label, input_val, expected, func=_validate_company_name):
    global passed, failed
    result = func(input_val)
    ok = result == expected
    status = "PASS" if ok else "FAIL"
    if not ok:
        print(f"  [{status}] {label}: '{input_val}' -> '{result}' (expected: '{expected}')")
        failed += 1
    else:
        passed += 1
    return ok

print("=== _validate_company_name() ===")
print()

print("[Reject: numbers]")
test("pure digits", "4000000", "미확인")
test("comma digits", "4,000,000", "미확인")
test("large number", "23,418,736", "미확인")
test("shares", "4,000,000 주", "미확인")
test("amount", "1,234,567 원", "미확인")
test("receipt no", "20260313000587", "미확인")
test("date dash", "2026-03-12", "미확인")
test("date kr", "2026년", "미확인")
test("empty", "", "미확인")
test("none", None, "미확인")
test("spaces", "   ", "미확인")

print()
print("[Reject: doc types / system strings]")
test("doc type 1", "유상증자결정", "미확인")
test("doc type 2", "주요사항보고서", "미확인")
test("doc type 3", "재무제표", "미확인")
test("filename", "doc_id_123.pdf", "미확인")
test("rendered", "report_rendered.txt", "미확인")

print()
print("[Accept: valid company names]")
test("corp kr", "주식회사 에이텀", "주식회사 에이텀")
test("samsung", "삼성전자", "삼성전자")
test("kakao", "(주)카카오", "(주)카카오")
test("naver", "네이버", "네이버")
test("lg", "LG에너지솔루션", "LG에너지솔루션")
test("sk", "SK텔레콤", "SK텔레콤")
test("hyundai", "현대자동차", "현대자동차")
test("atem", "에이텀", "에이텀")

print()
print("=== _sanitize_company_for_pdf() ===")
print()
test("pdf block num", "4,000,000", "미확인", _sanitize_company_for_pdf)
test("pdf block large", "23,418,736", "미확인", _sanitize_company_for_pdf)
test("pdf pass corp", "주식회사 에이텀", "주식회사 에이텀", _sanitize_company_for_pdf)
test("pdf pass name", "삼성전자", "삼성전자", _sanitize_company_for_pdf)
test("pdf block empty", "", "미확인", _sanitize_company_for_pdf)
test("pdf block pure", "12345", "미확인", _sanitize_company_for_pdf)

print()
print(f"=== Result: {passed} passed, {failed} failed ===")
if failed > 0:
    sys.exit(1)
else:
    print("All tests passed!")
