# ============================================================
# 📦 DART 텍스트 전용 JSONL 생성기 (google-genai 신버전)
# pip install google-genai
# API 키: https://aistudio.google.com/app/apikey 에서 발급
# ============================================================

import os, json, time, random, glob
from google import genai
from google.genai import types

# ╔══════════════════════════════════════════════════════╗
# ║  ▶ Gemini API 키 (AI Studio에서 발급받은 키 입력)   ║
# ║    https://aistudio.google.com/app/apikey            ║
GEMINI_API_KEY   = "AIzaSyDeugPGb6TqvC_hXiCnkDIuW1SYv8Pzw0I"
# ╚══════════════════════════════════════════════════════╝

MODEL_NAME       = "models/gemini-2.5-pro"

EXTRACTED_DIR    = r"C:\Users\hibou\Documents\extracted_texts"
OUTPUT_DIR       = r"C:\Users\hibou\Omega_CivicFlow_v3\datasets"
OUTPUT_TRAIN     = os.path.join(OUTPUT_DIR, "dart_train.jsonl")
OUTPUT_VALID     = os.path.join(OUTPUT_DIR, "dart_valid.jsonl")

SKIP_TIERS       = {"P3", "P4"}
MIN_TEXT_LEN     = 3000
MAX_TEXT_LEN     = 8000
VALID_RATIO      = 0.1
DELAY_BETWEEN    = 2.0   # rate limit 방지용 딜레이

# ── Gemini 초기화 ─────────────────────────────────────────
client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = (
    "너는 한국 금융·회계 문서 분석 전문가다. "
    "DART 공시 문서를 읽고 핵심 내용을 정확하게 요약·분류하며 "
    "반드시 JSON 형식으로만 답변한다."
)

ANALYSIS_TEMPLATE = """다음 DART 공시 문서를 분석하고 JSON으로만 답하라:

{text}

---
출력 형식:
{{
  "company_name": "회사명",
  "doc_type": "사업보고서|반기보고서|분기보고서|감사보고서|주요사항보고서|기타공시",
  "fiscal_year": "회계연도 (예: 2024)",
  "industry": "제조업|금융업|IT|바이오|건설|유통|에너지|부동산|기타",
  "summary": "핵심 내용 3~5문장 요약",
  "key_points": ["포인트1", "포인트2", "포인트3"],
  "financial_highlights": "주요 재무 수치 (없으면 null)",
  "risk_factors": "주요 리스크 (없으면 null)"
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

def call_gemini(text):
    global _debug_count
    prompt = ANALYSIS_TEMPLATE.format(text=text[:MAX_TEXT_LEN])
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

            # 디버그: 처음 3개만 원문 출력
            if _debug_count < 3:
                print(f"\n[DEBUG RAW] {repr(raw[:300])}\n", flush=True)
                _debug_count += 1

            # ① 직접 JSON 파싱 시도
            try:
                json.loads(raw)
                return raw
            except Exception:
                pass

            # ② ```json ... ``` 블록 추출
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

            # ③ 첫 { ~ 마지막 } 추출
            if "{" in raw and "}" in raw:
                s = raw.index("{")
                e = raw.rindex("}") + 1
                candidate = raw[s:e]
                try:
                    json.loads(candidate)
                    return candidate
                except Exception:
                    pass

            return raw  # 파싱 실패해도 일단 반환 (메인에서 재파싱)
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


def build_sample(txt_path, analysis_json_str):
    filename = os.path.basename(txt_path)
    text = load_text(txt_path)
    if not text:
        return None
    user_content = (
        f"다음 DART 공시 문서를 요약하고 분류하라.\n\n"
        f"[문서명]: {filename}\n\n"
        f"[본문]:\n{text[:MAX_TEXT_LEN]}"
    )
    return {
        "messages": [
            {"role": "system",    "content": SYSTEM_INSTRUCTION},
            {"role": "user",      "content": user_content},
            {"role": "assistant", "content": analysis_json_str},
        ]
    }


def get_processed_files(jsonl_path):
    """이미 처리된 파일명 목록을 기존 JSONL에서 읽어옴 (재시작 시 건너뛰기용)"""
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
    total_train, total_valid = 0, 0

    for split_name, file_list, out_path in [
        ("TRAIN", train_files, OUTPUT_TRAIN),
        ("VALID", valid_files, OUTPUT_VALID),
    ]:
        # ── 이미 처리된 파일 목록 로드 (재시작 시 건너뛰기)
        processed = get_processed_files(out_path)
        if processed:
            print(f"  ♻️  {split_name}: 이미 처리된 {len(processed)}개 건너뜀")

        count = len(processed)
        print(f"{'='*55}")
        print(f"🔄 {split_name} 처리 중... (남은 파일: {len(file_list) - len(processed)}개)")

        # ── append 모드로 열어서 즉시 저장
        with open(out_path, "a", encoding="utf-8") as out_f:
            for i, fpath in enumerate(file_list, 1):
                fname = os.path.basename(fpath)

                # 이미 처리된 파일 건너뛰기
                if fname in processed:
                    continue

                print(f"  [{i:4d}/{len(file_list)}] {fname[:55]:<55}", end=" ... ", flush=True)

                text = load_text(fpath)
                analysis_str = call_gemini(text)

                if not analysis_str:
                    print("❌ SKIP"); errors.append(fname); continue

                try:
                    json.loads(analysis_str)
                except json.JSONDecodeError:
                    print("⚠️  JSON 오류"); errors.append(fname)
                    time.sleep(DELAY_BETWEEN); continue

                sample = build_sample(fpath, analysis_str)
                if sample:
                    # ✅ 처리 즉시 파일에 저장 (중단돼도 보존)
                    out_f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    out_f.flush()
                    count += 1
                    print(f"✅  ({count}번째)")
                else:
                    print("⚠️  SKIP"); errors.append(fname)

                time.sleep(DELAY_BETWEEN)

        sz = os.path.getsize(out_path) / 1024 / 1024 if os.path.exists(out_path) else 0
        print(f"\n✅ {split_name}: {out_path} ({count}개, {sz:.1f}MB)")
        if split_name == "TRAIN":
            total_train = count
        else:
            total_valid = count

    print(f"\n🎉 완료! Train={total_train}, Valid={total_valid}")
    if errors:
        print(f"⚠️  오류 {len(errors)}개")


if __name__ == "__main__":
    main()
