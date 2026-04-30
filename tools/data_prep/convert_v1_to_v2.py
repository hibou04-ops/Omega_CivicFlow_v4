# ============================================================
# 📦 DART JSONL v1 → v2 스키마 자동 변환기
# 기존 866건 학습 데이터를 llm_service.py 스키마에 맞게 변환
#
# 실행: python convert_v1_to_v2.py
# ============================================================

import json, os, re

INPUT_TRAIN = r"C:\Users\hibou\Omega_CivicFlow_v3\datasets\dart_train.jsonl"
INPUT_VALID = r"C:\Users\hibou\Omega_CivicFlow_v3\datasets\dart_valid.jsonl"
OUTPUT_TRAIN = r"C:\Users\hibou\Omega_CivicFlow_v3\datasets\dart_train_v2.jsonl"
OUTPUT_VALID = r"C:\Users\hibou\Omega_CivicFlow_v3\datasets\dart_valid_v2.jsonl"

# v2 시스템 프롬프트 (llm_service.py와 동일)
SYSTEM_V2 = """당신은 한국 DART 공시문서 분석 전문 AI입니다.

[핵심 규칙]
1. 반드시 JSON 형식으로만 응답하세요. 마크다운/인사말/설명 금지.
2. 문서에 명시되지 않은 숫자는 절대 생성하지 마세요.
3. 재무제표가 아닌 문서에 자산총계/매출액/영업이익을 넣지 마세요.
4. 숫자는 원문 기준으로 유지하세요 (단위 포함).
5. 불명확한 항목은 null 또는 "해당 없음"으로 표기.
6. 정정 전/정정 후가 존재하면 반드시 비교 데이터를 포함.
7. JSON 외에 어떤 텍스트도 출력하지 마세요.
8. 모든 출력은 반드시 한국어로 작성하세요."""


# 문서유형 매핑 (v1 doc_type → v2 primary/secondary)
DOC_TYPE_MAP = {
    "감사보고서": ("감사보고서", "재무제표"),
    "사업보고서": ("사업보고서", ""),
    "반기보고서": ("반기보고서", "재무제표"),
    "분기보고서": ("분기보고서", "재무제표"),
    "주요사항보고서": ("주요사항보고서", ""),
    "유상증자결정": ("유상증자결정", ""),
    "정정신고": ("정정신고(보고)", ""),
    "재무제표": ("재무제표", ""),
    "기타공시": ("기타공시", ""),
    "대량보유": ("대량보유보고서", ""),
    "배당": ("배당", ""),
}

FINANCIAL_TYPES = {"재무제표", "사업보고서", "감사보고서", "반기보고서", "분기보고서"}


def parse_financial_highlights(text):
    """financial_highlights 문자열 → financial_metrics dict 변환"""
    if not text or text == "null" or text == "해당 없음":
        return "해당 없음"

    metrics = {
        "assets_total": None,
        "liabilities_total": None,
        "equity_total": None,
        "revenue": None,
        "operating_income": None,
        "net_income": None,
    }

    patterns = {
        "assets_total": [r"자산총계[:\s]*([^\s,|]+)", r"자산총계\s*([0-9,]+[^\s,|]*)"],
        "liabilities_total": [r"부채총계[:\s]*([^\s,|]+)", r"부채총계\s*([0-9,]+[^\s,|]*)"],
        "equity_total": [r"자본총계[:\s]*([^\s,|]+)", r"자본총계\s*([0-9,]+[^\s,|]*)"],
        "revenue": [r"매출액[:\s]*([^\s,|]+)", r"매출\s*([0-9,]+[^\s,|]*)"],
        "operating_income": [r"영업이익[:\s]*([^\s,|]+)", r"영업이익\s*([0-9,]+[^\s,|]*)"],
        "net_income": [r"당기순이익[:\s]*([^\s,|]+)", r"당기순이익\s*([0-9,]+[^\s,|]*)"],
    }

    for key, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, text)
            if m:
                metrics[key] = m.group(1).strip()
                break

    # 모든 값이 None이면 원본 문자열 반환
    if all(v is None for v in metrics.values()):
        return "해당 없음"

    return metrics


def convert_v1_to_v2(v1_assistant):
    """v1 JSON → v2 JSON 변환"""
    try:
        d = json.loads(v1_assistant)
    except json.JSONDecodeError:
        return None

    doc_type = d.get("doc_type", "기타공시")
    primary, secondary = DOC_TYPE_MAP.get(doc_type, (doc_type, ""))

    # financial_metrics 변환
    fh = d.get("financial_highlights", "해당 없음")
    if doc_type in FINANCIAL_TYPES and fh and fh not in ("null", "해당 없음"):
        financial_metrics = parse_financial_highlights(str(fh))
    else:
        financial_metrics = "해당 없음"

    # risk_factors → risk_notes (string → list)
    rf = d.get("risk_factors", "")
    if isinstance(rf, str) and rf and rf not in ("null", "해당 없음"):
        risk_notes = [rf]
    elif isinstance(rf, list):
        risk_notes = rf
    else:
        risk_notes = []

    # key_points 보존
    kp = d.get("key_points", [])
    if isinstance(kp, str):
        kp = [kp]

    # evidence: key_points 첫번째 또는 summary에서 추출
    evidence = ""
    if kp:
        evidence = kp[0] if isinstance(kp[0], str) else ""
    if not evidence:
        summary = d.get("summary", "")
        if summary:
            first_sent = summary.split(".")[0].strip()
            if len(first_sent) > 10:
                evidence = first_sent + "."

    v2 = {
        "document_type": {"primary": primary, "secondary": secondary},
        "company_name": d.get("company_name", "미확인"),
        "disclosure_title": "미확인",
        "summary": d.get("summary", ""),
        "category": primary,
        "key_points": kp,
        "financial_metrics": financial_metrics,
        "risk_notes": risk_notes,
        "evidence": evidence,
    }

    return json.dumps(v2, ensure_ascii=False)


def convert_user_prompt(v1_user):
    """v1 user 프롬프트를 v2 스타일로 경량 수정"""
    # "요약하고 분류하라" → "분석하고 JSON으로만 응답하라"
    text = v1_user.replace(
        "다음 DART 공시 문서를 요약하고 분류하라.",
        "다음 DART 공시 문서를 분석하고 JSON으로만 응답하라."
    )
    return text


def convert_file(input_path, output_path):
    if not os.path.exists(input_path):
        print(f"❌ 파일 없음: {input_path}")
        return 0

    converted = 0
    failed = 0

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue

            sample = json.loads(line)
            msgs = sample["messages"]

            # assistant 응답 변환
            asst_content = msgs[2]["content"]
            v2_content = convert_v1_to_v2(asst_content)

            if not v2_content:
                failed += 1
                continue

            new_sample = {
                "messages": [
                    {"role": "system", "content": SYSTEM_V2},
                    {"role": "user", "content": convert_user_prompt(msgs[1]["content"])},
                    {"role": "assistant", "content": v2_content},
                ]
            }

            fout.write(json.dumps(new_sample, ensure_ascii=False) + "\n")
            converted += 1

    print(f"  ✅ {os.path.basename(input_path)} → {os.path.basename(output_path)}: "
          f"{converted}건 변환, {failed}건 실패")
    return converted


if __name__ == "__main__":
    print("📦 DART JSONL v1 → v2 스키마 변환")
    print("=" * 50)

    t = convert_file(INPUT_TRAIN, OUTPUT_TRAIN)
    v = convert_file(INPUT_VALID, OUTPUT_VALID)

    print(f"\n🎉 완료! Train: {t}건, Valid: {v}건")
    print(f"  → {OUTPUT_TRAIN}")
    print(f"  → {OUTPUT_VALID}")

    # 변환 결과 검증
    print("\n📋 변환 결과 검증:")
    with open(OUTPUT_TRAIN, "r", encoding="utf-8") as f:
        first = json.loads(f.readline())
        asst = json.loads(first["messages"][2]["content"])
        print(f"  document_type: {asst.get('document_type')}")
        print(f"  company_name: {asst.get('company_name')}")
        print(f"  summary (길이): {len(asst.get('summary', ''))}")
        print(f"  financial_metrics 타입: {type(asst.get('financial_metrics')).__name__}")
        print(f"  risk_notes: {asst.get('risk_notes')}")
        print(f"  evidence: {asst.get('evidence', '')[:100]}")
