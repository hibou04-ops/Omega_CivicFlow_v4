# ============================================================
# 📦 DART JSONL 생성기 v2 — llm_service.py 스키마 일치
# pip install google-genai
#
# 변경점 (v1 → v2):
#   - assistant 출력 스키마를 llm_service.py 프롬프트와 완벽 일치
#   - 문서유형별 3종 프롬프트 (재무/이벤트/일반) 분기
#   - user 프롬프트도 llm_service SYSTEM_PROMPT 반영
# ============================================================

import os, json, time, random, glob, re
from google import genai
from google.genai import types

# ╔══════════════════════════════════════════════════════╗
# ║  ▶ Gemini API 키 (AI Studio에서 발급받은 키 입력)   ║
GEMINI_API_KEY   = "AIzaSyDeugPGb6TqvC_hXiCnkDIuW1SYv8Pzw0I"
# ╚══════════════════════════════════════════════════════╝

MODEL_NAME       = "models/gemini-2.5-pro"

EXTRACTED_DIR    = r"C:\Users\hibou\Documents\extracted_texts"
OUTPUT_DIR       = r"C:\Users\hibou\Omega_CivicFlow_v3\datasets"
OUTPUT_TRAIN     = os.path.join(OUTPUT_DIR, "dart_train_v2.jsonl")
OUTPUT_VALID     = os.path.join(OUTPUT_DIR, "dart_valid_v2.jsonl")

SKIP_TIERS       = {"P3", "P4"}
MIN_TEXT_LEN     = 3000
MAX_TEXT_LEN     = 8000
VALID_RATIO      = 0.1
DELAY_BETWEEN    = 2.0

# ── Gemini 초기화 ─────────────────────────────────────────
client = genai.Client(api_key=GEMINI_API_KEY)

# ═══════════════════════════════════════════════════════
# llm_service.py와 동일한 시스템 프롬프트
# ═══════════════════════════════════════════════════════

SYSTEM_INSTRUCTION = """당신은 한국 DART 공시문서 분석 전문 AI입니다.

[핵심 규칙]
1. 반드시 JSON 형식으로만 응답하세요. 마크다운/인사말/설명 금지.
2. 문서에 명시되지 않은 숫자는 절대 생성하지 마세요.
3. 재무제표가 아닌 문서에 자산총계/매출액/영업이익을 넣지 마세요.
4. 숫자는 원문 기준으로 유지하세요 (단위 포함).
5. 불명확한 항목은 null 또는 "해당 없음"으로 표기.
6. 정정 전/정정 후가 존재하면 반드시 비교 데이터를 포함.
7. JSON 외에 어떤 텍스트도 출력하지 마세요.
8. 모든 출력은 반드시 한국어로 작성하세요."""


# ═══════════════════════════════════════════════════════
# 문서유형 분류 (키워드 기반)
# ═══════════════════════════════════════════════════════

DOC_TYPE_KEYWORDS = {
    "정정신고(보고)": ["정정신고", "정정 전", "정정 후", "정정보고", "기재정정"],
    "주요사항보고서": ["주요사항보고서", "주요경영사항", "전환사채", "신주인수권부사채"],
    "유상증자결정": ["유상증자", "신주발행", "제3자배정", "증자결정"],
    "사업보고서": ["사업보고서", "사업의 내용", "임원 및 직원", "회사의 개요"],
    "반기보고서": ["반기보고서", "반기검토", "반기재무"],
    "분기보고서": ["분기보고서", "분기검토", "분기재무"],
    "재무제표": ["재무상태표", "손익계산서", "포괄손익계산서", "현금흐름표", "자본변동표"],
    "감사보고서": ["감사보고서", "감사의견", "적정의견", "한정의견"],
    "주석": ["주석", "재무제표에 대한 주석", "유의적인 회계정책"],
    "대량보유보고서": ["대량보유", "주식등의 대량보유", "5% 보고"],
    "임원·주요주주변동": ["임원변동", "주요주주", "특정증권등 소유"],
    "자기주식": ["자기주식", "자사주", "자기주식처분"],
    "합병·분할": ["합병", "분할합병", "분할", "영업양수도"],
    "배당": ["배당", "현금배당", "주식배당", "배당금"],
}

FINANCIAL_TYPES = {"재무제표", "사업보고서", "감사보고서", "반기보고서", "분기보고서", "주석"}
EVENT_TYPES = {"정정신고(보고)", "유상증자결정", "주요사항보고서", "합병·분할", "자기주식"}


def classify_doc_type(text):
    """키워드 기반 문서유형 분류"""
    text_head = text[:5000].lower()
    scores = {}
    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_head)
        if score > 0:
            scores[doc_type] = score
    if not scores:
        return "기타공시", ""
    sorted_types = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_types[0][0]
    secondary = sorted_types[1][0] if len(sorted_types) > 1 else ""
    return primary, secondary


# ═══════════════════════════════════════════════════════
# 3종 프롬프트 — llm_service.py와 동일 스키마
# ═══════════════════════════════════════════════════════

FINANCIAL_TEMPLATE = """다음 DART 공시 문서를 분석하고 반드시 아래 JSON 형식으로만 답하라.
문서에 없는 숫자를 지어내지 마세요.

[문서 텍스트]
{text}

---
출력 (반드시 이 JSON 구조만 사용):
{{"document_type": {{"primary": "{doc_type}", "secondary": "{doc_secondary}"}},
"company_name": "회사명 (한글 법인명만, 확인 불가 시 '미확인')",
"disclosure_title": "공시 제목 (확인 불가 시 '미확인')",
"summary": "【필수: 5가지 항목 모두 포함, 최소 5문장】 1) 문서 목적 및 검토 기간 2) 회사 및 사업 현황 3) 핵심 재무 지표 4) 주요 위험 요인 5) 종합 평가",
"category": "{doc_type}",
"key_points": ["투자자 주목 포인트 1", "포인트 2", "포인트 3"],
"financial_metrics": {{
  "assets_total": "자산총계 (원문 그대로, 없으면 null)",
  "liabilities_total": "부채총계 (원문 그대로, 없으면 null)",
  "equity_total": "자본총계 (원문 그대로, 없으면 null)",
  "revenue": "매출액 (원문 그대로, 없으면 null)",
  "operating_income": "영업이익 (원문 그대로, 없으면 null)",
  "net_income": "당기순이익 (원문 그대로, 없으면 null)"
}},
"risk_notes": ["리스크 1", "리스크 2"],
"evidence": "문서에서 핵심 근거 문장을 원문 그대로 인용 (반드시 작성)"
}}"""

EVENT_TEMPLATE = """다음 DART 공시 문서를 분석하고 반드시 아래 JSON 형식으로만 답하라.
재무제표 숫자(자산총계/매출액 등)를 지어내지 마세요. 이 문서는 재무제표가 아닙니다.

[문서 텍스트]
{text}

---
출력 (반드시 이 JSON 구조만 사용):
{{"document_type": {{"primary": "{doc_type}", "secondary": "{doc_secondary}"}},
"company_name": "회사명 (한글 법인명만, 확인 불가 시 '미확인')",
"disclosure_title": "공시 제목 (확인 불가 시 '미확인')",
"initial_filing_date": "최초 제출일 (없으면 null)",
"amendment_date": "정정일 (없으면 null)",
"summary": "【필수: 5가지 항목 모두 포함, 최소 5문장】 1) 공시 사건 종류 및 배경 2) 주요 변경 내용 3) 발행 조건 또는 핵심 계약 4) 자금 사용 목적 5) 투자자 관점 위험/기회",
"category": "{doc_type}",
"event_type": "정정신고/유상증자/주요사항 등",
"key_points": ["핵심 포인트 1", "포인트 2", "포인트 3"],
"key_changes": [
  {{"field": "변경 항목명", "before": "정정 전", "after": "정정 후", "meaning": "변경 의미"}}
],
"offering_terms": {{
  "share_type": "신주 종류 (없으면 null)",
  "new_shares": "신주 수 (없으면 null)",
  "fund_use": "자금조달 목적 (없으면 null)",
  "offering_method": "증자 방식 (없으면 null)",
  "issue_price": "발행가액 (없으면 null)",
  "payment_date": "납입일 (없으면 null)"
}},
"financial_metrics": "해당 없음",
"risk_notes": ["리스크 1", "리스크 2"],
"evidence": "공시 핵심 내용의 원문 근거 문장 (반드시 작성)"
}}"""

GENERAL_TEMPLATE = """다음 DART 공시 문서를 분석하고 반드시 아래 JSON 형식으로만 답하라.
문서에 없는 정보를 만들지 마세요.

[문서 텍스트]
{text}

---
출력 (반드시 이 JSON 구조만 사용):
{{"document_type": {{"primary": "{doc_type}", "secondary": "{doc_secondary}"}},
"company_name": "회사명 (한글 법인명만, 확인 불가 시 '미확인')",
"disclosure_title": "공시 제목 (확인 불가 시 '미확인')",
"summary": "【필수: 5가지 항목 모두 포함, 최소 5문장】 1) 문서 목적 및 공시 배경 2) 주요 내용 요약 3) 공시 대상 회사 현황 4) 이해관계자 영향 5) 유의사항",
"category": "{doc_type}",
"key_points": ["핵심 포인트 1", "포인트 2", "포인트 3"],
"financial_metrics": "해당 없음",
"risk_notes": [],
"evidence": "문서 핵심 결론의 근거 원문 문장 (반드시 작성)"
}}"""


def get_tier(filename):
    base = os.path.basename(filename)
    if "_P" in base:
        idx = base.index("_P")
        return base[idx+1:idx+3]
    return "P0"


def load_text(filepath):
    for enc in ["utf-8", "cp949", "euc-kr"]:
        try:
            with open(filepath, "r", encoding=enc) as f:
                return f.read()
        except Exception:
            continue
    return ""


_debug_count = 0

def call_gemini(text, doc_type, doc_secondary):
    """문서유형에 맞는 프롬프트로 Gemini 호출"""
    global _debug_count

    context = {
        "text": text[:MAX_TEXT_LEN],
        "doc_type": doc_type,
        "doc_secondary": doc_secondary or "",
    }

    if doc_type in FINANCIAL_TYPES:
        prompt = FINANCIAL_TEMPLATE.format(**context)
    elif doc_type in EVENT_TYPES:
        prompt = EVENT_TEMPLATE.format(**context)
    else:
        prompt = GENERAL_TEMPLATE.format(**context)

    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.1,
                    max_output_tokens=4096,
                ),
            )
            raw = resp.text.strip()

            if _debug_count < 3:
                print(f"\n[DEBUG RAW] {repr(raw[:300])}\n", flush=True)
                _debug_count += 1

            # JSON 추출
            try:
                json.loads(raw)
                return raw
            except Exception:
                pass

            if "```" in raw:
                for chunk in raw.split("```"):
                    c = chunk.strip()
                    if c.startswith("json"):
                        c = c[4:].strip()
                    if c.startswith("{"):
                        try:
                            json.loads(c)
                            return c
                        except Exception:
                            pass

            if "{" in raw and "}" in raw:
                s = raw.index("{")
                e = raw.rindex("}") + 1
                candidate = raw[s:e]
                try:
                    json.loads(candidate)
                    return candidate
                except Exception:
                    pass

            return raw
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                wait = 60 * (attempt + 1)
                print(f"\n  ⏳ 한도 초과 — {wait}초 대기...", flush=True)
                time.sleep(wait)
            else:
                print(f"⚠️  오류: {err[:100]}")
                return None
    return None


def validate_schema(json_str):
    """v2 스키마 필수 키 검증"""
    try:
        d = json.loads(json_str)
    except Exception:
        return False

    required = ["document_type", "company_name", "summary", "category", "evidence"]
    for key in required:
        if key not in d:
            return False

    if not isinstance(d.get("document_type"), dict):
        return False
    if "primary" not in d["document_type"]:
        return False

    return True


def build_sample(txt_path, analysis_json_str, doc_type, doc_secondary):
    filename = os.path.basename(txt_path)
    text = load_text(txt_path)
    if not text:
        return None

    # user 프롬프트: llm_service.py의 focused_text와 유사한 구조
    user_content = (
        f"다음 DART 공시 문서를 분석하고 JSON으로만 응답하라.\n\n"
        f"[문서명]: {filename}\n"
        f"[문서유형]: {doc_type}"
        + (f" / {doc_secondary}" if doc_secondary else "")
        + f"\n\n[본문]:\n{text[:MAX_TEXT_LEN]}"
    )

    return {
        "messages": [
            {"role": "system",    "content": SYSTEM_INSTRUCTION},
            {"role": "user",      "content": user_content},
            {"role": "assistant", "content": analysis_json_str},
        ]
    }


def get_processed_files(jsonl_path):
    processed = set()
    if not os.path.exists(jsonl_path):
        return processed
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                sample = json.loads(line)
                for msg in sample.get("messages", []):
                    if msg["role"] == "user":
                        content = msg["content"]
                        if "[문서명]:" in content:
                            fname = content.split("[문서명]:")[1].split("\n")[0].strip()
                            processed.add(fname)
            except Exception:
                pass
    return processed


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"\n🤖 모델: {MODEL_NAME}")
    print(f"📋 스키마: v2 (llm_service.py 일치)")

    all_files = sorted(glob.glob(os.path.join(EXTRACTED_DIR, "*.txt")))
    print(f"📂 전체 파일: {len(all_files)}개")

    filtered = []
    for f in all_files:
        if get_tier(f) in SKIP_TIERS:
            continue
        if len(load_text(f)) < MIN_TEXT_LEN:
            continue
        filtered.append(f)

    print(f"✅ 처리 대상: {len(filtered)}개\n")

    random.seed(42)
    random.shuffle(filtered)
    n_valid     = max(1, int(len(filtered) * VALID_RATIO))
    valid_files  = filtered[:n_valid]
    train_files  = filtered[n_valid:]
    print(f"  Train: {len(train_files)}개 | Valid: {len(valid_files)}개\n")

    errors = []

    for split_name, file_list, out_path in [
        ("TRAIN", train_files, OUTPUT_TRAIN),
        ("VALID", valid_files, OUTPUT_VALID),
    ]:
        processed = get_processed_files(out_path)
        if processed:
            print(f"  ♻️  {split_name}: 이미 처리된 {len(processed)}개 건너뜀")

        count = len(processed)
        print(f"{'='*55}")
        print(f"🔄 {split_name} 처리 중... (남은 파일: {len(file_list) - len(processed)}개)")

        with open(out_path, "a", encoding="utf-8") as out_f:
            for i, fpath in enumerate(file_list, 1):
                fname = os.path.basename(fpath)

                if fname in processed:
                    continue

                text = load_text(fpath)
                doc_type, doc_secondary = classify_doc_type(text)

                print(f"  [{i:4d}/{len(file_list)}] {fname[:40]:<40} [{doc_type}]", end=" ... ", flush=True)

                analysis_str = call_gemini(text, doc_type, doc_secondary)

                if not analysis_str:
                    print("❌ SKIP"); errors.append(fname); continue

                if not validate_schema(analysis_str):
                    print("⚠️  스키마 불일치"); errors.append(fname)
                    time.sleep(DELAY_BETWEEN); continue

                sample = build_sample(fpath, analysis_str, doc_type, doc_secondary)
                if sample:
                    out_f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    out_f.flush()
                    count += 1
                    print(f"✅  ({count}번째)")
                else:
                    print("⚠️  SKIP"); errors.append(fname)

                time.sleep(DELAY_BETWEEN)

        sz = os.path.getsize(out_path) / 1024 / 1024 if os.path.exists(out_path) else 0
        print(f"\n✅ {split_name}: {out_path} ({count}개, {sz:.1f}MB)")

    print(f"\n🎉 완료!")
    if errors:
        print(f"⚠️  오류 {len(errors)}개: {errors[:10]}")


if __name__ == "__main__":
    main()
