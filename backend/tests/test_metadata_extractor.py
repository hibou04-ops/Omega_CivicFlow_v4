"""
Quick test for document_metadata_extractor module.
"""
from services.document_metadata_extractor import (
    extract_document_metadata,
    build_metadata_prompt_block,
    normalize_lines,
    is_section_title,
    looks_like_company_name,
    score_company_candidate,
    extract_sections,
)


def test_section_title_detection():
    """섹션 제목 판별 테스트"""
    assert is_section_title("1. 일반사항") == True
    assert is_section_title("Ⅰ. 회사의 개요") == True
    assert is_section_title("II. 사업의 내용") == True
    assert is_section_title("가. 연결대상 종속회사") == True
    assert is_section_title("목차") == True
    assert is_section_title("주석") == True
    assert is_section_title("재무제표") == True
    assert is_section_title("감사보고서") == True
    assert is_section_title("사업보고서") == True

    # 회사명은 섹션 제목이 아님
    assert is_section_title("주식회사 동국생명과학") == False
    assert is_section_title("(주)삼성전자") == False
    assert is_section_title("동국생명과학㈜") == False

    print("[PASS] 섹션 제목 판별 테스트")


def test_company_name_detection():
    """회사명 후보 판별 테스트"""
    assert looks_like_company_name("주식회사 동국생명과학") == True
    assert looks_like_company_name("(주)삼성전자") == True
    assert looks_like_company_name("동국생명과학㈜") == True

    # 섹션 제목은 회사명이 아님
    assert looks_like_company_name("1. 일반사항") == False
    assert looks_like_company_name("목차") == False
    assert looks_like_company_name("재무제표") == False

    print("[PASS] 회사명 후보 판별 테스트")


def test_scoring():
    """스코어링 테스트"""
    # 회사명 + 앞부분 = 높은 점수
    score1 = score_company_candidate("주식회사 동국생명과학", 5)
    # 섹션 제목 = 강한 감점
    score2 = score_company_candidate("1. 일반사항", 5)

    assert score1 > score2, f"회사명({score1}) > 섹션제목({score2}) 이어야 함"
    print(f"[PASS] 스코어링 — 회사명: {score1}, 섹션제목: {score2}")


def test_full_extraction():
    """통합 추출 테스트"""
    test_text = (
        "사업보고서\n"
        "\n"
        "주식회사 동국생명과학\n"
        "\n"
        "목차\n"
        "\n"
        "1. 일반사항\n"
        "2. 재무에 관한 사항\n"
        "Ⅰ. 회사의 개요\n"
        "주석\n"
        "재무제표\n"
        "\n"
        "회사명 : 주식회사 동국생명과학\n"
        "법인명 : 동국생명과학\n"
        "\n"
        "3. 연결재무제표\n"
        "감사보고서\n"
    )

    result = extract_document_metadata(test_text)

    print(f"Company: {result.company_name}")
    print(f"Confidence: {result.company_confidence}")
    print(f"Doc Type Hint: {result.document_type_hint}")
    print(f"Sections ({len(result.sections)}):")
    for s in result.sections:
        title = s["title"]
        print(f"  - {title}")
    print(f"Candidates: {result.candidates_debug}")

    # 회사명이 섹션 제목이 아니어야 함
    assert result.company_name is not None, "회사명이 추출되어야 함"
    assert "일반사항" not in result.company_name, "섹션 제목이 회사명으로 오인되면 안됨"
    assert "목차" not in result.company_name, "목차가 회사명으로 오인되면 안됨"
    assert "동국생명과학" in result.company_name, f"'동국생명과학'이 포함되어야 함, got: {result.company_name}"

    print(f"[PASS] 통합 추출 — 회사명: {result.company_name}")

    # 프롬프트 블록 생성 테스트
    block = build_metadata_prompt_block(result)
    assert "동국생명과학" in block
    assert "IMMUTABLE" in block
    print("[PASS] 프롬프트 블록 생성")


if __name__ == "__main__":
    test_section_title_detection()
    test_company_name_detection()
    test_scoring()
    test_full_extraction()
    print("\n=== ALL TESTS PASSED ===")
