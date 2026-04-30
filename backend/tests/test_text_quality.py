"""
text_quality.py 테스트 — 깨진 한글 정제, 품질 점수, 태깅, 요약문 정제
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from services.text_quality import (
    compute_readability_score,
    clean_broken_korean,
    tag_text_by_quality,
    sanitize_summary_text,
)

passed = 0
failed = 0

def test(label, actual, expected):
    global passed, failed
    ok = actual == expected
    if not ok:
        print(f"  [FAIL] {label}: got {repr(actual)}, expected {repr(expected)}")
        failed += 1
    else:
        passed += 1

print("=== 1. clean_broken_korean ===")
# 연속 자모 제거
test("jamo strip", "사석 ㅎㅏㄴ 엣속을" in clean_broken_korean("사석 ㅎㅏㄴ 엣속을"), False)
# 반복 문자 축약
test("repeat", "aaaa" not in clean_broken_korean("aaaaaaaa"), True)
# 정상 한글 보존
test("normal preserved", clean_broken_korean("삼성전자 주식회사"), "삼성전자 주식회사")
# 빈 문자열
test("empty", clean_broken_korean(""), "")

print()
print("=== 2. compute_readability_score ===")
good_text = "주식회사 에이텀은 유상증자를 결정하였습니다. 신주의 종류는 보통주이며, 발행 주식수는 4,000,000주입니다."
bad_text = "ㅎㅏㄱ ㅇㅣ ㄷㅏ ㅁㅏ ㅎㅏ ㅈㅏ ㅅㅓ ㅇㅏ ㅁㅏ"
garbage = "###@@!!$$%%^^&&**()()()()!!!!"

good_score = compute_readability_score(good_text)
bad_score = compute_readability_score(bad_text)
garbage_score = compute_readability_score(garbage)

test("good > 0.5", good_score > 0.5, True)
test("bad < 0.5", bad_score < 0.5, True)
test("garbage < 0.5", garbage_score < 0.5, True)
test("empty = 0", compute_readability_score(""), 0.0)

print(f"  Scores: good={good_score:.2f}, bad={bad_score:.2f}, garbage={garbage_score:.2f}")

print()
print("=== 3. tag_text_by_quality ===")
pages = [
    {"page_number": 1, "text": good_text, "confidence": 0.95},
    {"page_number": 2, "text": bad_text, "confidence": 0.3},
    {"page_number": 3, "text": "", "confidence": 0.0},
]
tagged, enriched = tag_text_by_quality(pages)
test("page 1 good", enriched[0].get("quality_tag"), "good")
test("page 3 empty", enriched[2].get("quality_tag"), "empty")
test("tagged has page 1", "[페이지 1]" in tagged, True)
# Low quality pages get warning tag
low_pages = [p for p in enriched if p.get("quality_tag") in ("low", "very_low")]
test("bad page tagged", len(low_pages) >= 1, True)

print()
print("=== 4. sanitize_summary_text ===")
dirty = "주식회사 에이텀ㅎㅏㄴ은 유상증자ㅏㅓㅣ를 결정했습니다.\ufffd\ufffd"
clean = sanitize_summary_text(dirty)
test("jamo removed", "ㅎㅏㄴ" not in clean, True)
test("replacement char removed", "\ufffd" not in clean, True)
test("content preserved", "에이텀" in clean, True)
test("content preserved 2", "유상증자" in clean, True)

# 깨진 공시명 같은 패턴
broken_title = "사석 엣속을 총해약안 주장의 동고시울세요"
sanitized = sanitize_summary_text(broken_title)
test("broken passes through (no jamo)", sanitized, broken_title)  # 자모가 없으므로 통과 (이건 LLM 환각이므로 별도 처리)

print()
print(f"=== Result: {passed} passed, {failed} failed ===")
if failed > 0:
    sys.exit(1)
else:
    print("All tests passed!")
