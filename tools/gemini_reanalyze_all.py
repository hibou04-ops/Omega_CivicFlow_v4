"""
Omega CivicFlow — Gemini 2.5 Flash 로컬 재분석
Colab 불필요! 4개 API 키 로테이션으로 전체 문서 분석.

사용법:
  cd backend
  python ..\tools\gemini_reanalyze_all.py
"""
import sys, os, json, time, re, asyncio

BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

# === 설정 ===
API_KEYS = [
    "AIzaSyCoaCgliX2TJ5tmwo7KzRwZkMONSf0x4ic",
    "AIzaSyCSiVRIlhKNlG221_I0JUPrHsZRA_U7Sl0",
    "AIzaSyCeu3KXkX2s5ZeT9dKITvQMEZrS8ZuYwgk",
    "AIzaSyCKIAiDCICtr8vPGDQQlavtE5XMNiUr8uA",
]
MODEL = "gemini-2.0-flash"
CONCURRENT = 1          # 1개씩 안전하게
SAVE_EVERY = 20
INPUT_FILE = r"C:\Users\hibou\Downloads\pending_docs_all.json"
RESULT_FILE = r"C:\Users\hibou\Downloads\analysis_results_gemini.json"

PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.
아래 공시문서 전체를 꼼꼼히 분석하여 반드시 아래 JSON 형식으로만 출력하세요.
중국어 사용 금지. 반드시 한국어로만 작성하세요.

[공시문서 전체 내용]
{text}

[출력 JSON 형식]
{{
  "summary": "핵심 요약 (300자 이상, 재무수치 반드시 포함. 매출액, 영업이익, 당기순이익, 자산총계 등)",
  "category": "사업보고서|반기보고서|분기보고서|재무제표|감사보고서|주석|정정신고|주요사항보고서|유상증자결정|대량보유보고서|임원주요주주변동|자기주식|합병분할|배당|기타공시",
  "evidence": "분석 근거가 되는 원문 문장 3개 이상",
  "financial_metrics": "주요 재무지표 종합 (매출, 이익, 자산, 부채비율 등)",
  "insight_vectors": "투자자 관점에서의 핵심 인사이트",
  "company_name": "회사명",
  "disclosure_title": "공시명",
  "key_points": ["핵심포인트1", "핵심포인트2", "핵심포인트3"],
  "risk_notes": ["리스크1", "리스크2"]
}}

[필수 규칙]
1. 300자 이상 상세 요약
2. 재무수치 반드시 포함
3. 한국어만 사용 (중국어 절대 금지)
4. JSON만 출력 (다른 텍스트 금지)
5. 없는 숫자 절대 생성 금지"""


def extract_company(fn):
    m = re.search(r'DART_P\d+_(.+?)_\d{13,14}', fn)
    return m.group(1) if m else "미확인"


def parse_json_safe(text):
    if not text or not text.strip():
        return {"summary": "응답없음", "category": "기타공시", "_error": True}
    text = text.strip()
    
    # Remove markdown
    m = re.search(r'```(?:json)?\s*(\{.+?\})\s*```', text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m = re.search(r'\{.+\}', text, re.DOTALL)
        if m:
            text = m.group(0)
    
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    
    try:
        return json.loads(text)
    except:
        pass
    
    try:
        fixed = re.sub(r',\s*}', '}', text)
        fixed = re.sub(r',\s*]', ']', fixed)
        return json.loads(fixed)
    except:
        pass
    
    return {"summary": text[:2000], "category": "기타공시", "_parse_failed": True}


class KeyRotator:
    def __init__(self, keys):
        self.keys = keys
        self.idx = 0
        self.locks = {k: asyncio.Semaphore(1) for k in keys}
    
    async def get_key(self):
        key = self.keys[self.idx % len(self.keys)]
        self.idx += 1
        return key


async def call_gemini(client, rotator, text, max_retries=3):
    for attempt in range(max_retries):
        key = await rotator.get_key()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}"
        
        body = {
            "contents": [{"parts": [{"text": PROMPT.format(text=text)}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096,
                "responseMimeType": "application/json",
            },
        }
        
        try:
            r = await client.post(url, json=body, timeout=120.0)
            
            if r.status_code == 200:
                data = r.json()
                if "candidates" in data and data["candidates"]:
                    content = data["candidates"][0].get("content", {})
                    parts = content.get("parts", [])
                    if parts and parts[0].get("text"):
                        return parts[0]["text"]
            
            elif r.status_code == 429:
                # Rate limited — wait and retry with different key
                wait = 5 + attempt * 5
                print(f"    ⏳ 429 rate limit, {wait}초 대기...")
                await asyncio.sleep(wait)
                continue
            
            elif r.status_code == 400:
                error_msg = r.text[:200]
                print(f"    ⚠ 400 에러: {error_msg}")
                return None
            
            else:
                print(f"    ⚠ HTTP {r.status_code}")
                await asyncio.sleep(2)
        
        except Exception as e:
            print(f"    ⚠ 오류: {str(e)[:80]}")
            await asyncio.sleep(2)
    
    return None


async def main():
    # Load data
    if not os.path.exists(INPUT_FILE):
        print(f"❌ 파일 없음: {INPUT_FILE}")
        return
    
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        docs = json.load(f)
    
    # Resume
    all_results = []
    completed_ids = set()
    if os.path.exists(RESULT_FILE):
        try:
            with open(RESULT_FILE, "r", encoding="utf-8") as f:
                all_results = json.load(f)
            completed_ids = {r["doc_id"] for r in all_results}
            print(f"복원: {len(completed_ids)}건")
        except:
            all_results = []
    
    remaining = [d for d in docs if d["doc_id"] not in completed_ids]
    total = len(remaining)
    
    if total == 0:
        print("✅ 모든 문서 분석 완료!")
        return
    
    print(f"{'='*55}")
    print(f"  Ω Gemini 2.5 Flash — 로컬 전체 분석")
    print(f"  대상: {total}건 (API 키 {len(API_KEYS)}개)")
    print(f"  모델: {MODEL}")
    print(f"  전체 텍스트 전송 (최대 100만 토큰)")
    print(f"{'='*55}")
    
    rotator = KeyRotator(API_KEYS)
    sem = asyncio.Semaphore(CONCURRENT)
    ok = [0]
    err = [0]
    t0 = time.time()
    
    async def process_one(client, doc):
        async with sem:
            # Gemini 2.0 Flash — 전체 텍스트
            text = doc["text"][:100000]
            
            # 보수적: 2초 간격
            await asyncio.sleep(2.0)
            
            result_text = await call_gemini(client, rotator, text)
            
            if result_text:
                result = parse_json_safe(result_text)
                result["_model"] = f"gemini-{MODEL}"
                result["company_name"] = result.get("company_name", extract_company(doc["filename"]))
                
                if not result.get("_error") and not result.get("_parse_failed"):
                    ok[0] += 1
                else:
                    err[0] += 1
            else:
                result = {
                    "summary": "분석실패", "category": "기타공시",
                    "_error": True, "_model": f"gemini-{MODEL}"
                }
                err[0] += 1
            
            all_results.append({
                "doc_id": doc["doc_id"],
                "filename": doc["filename"],
                "result": result,
            })
            
            done = ok[0] + err[0]
            if done % 10 == 0 or done == total:
                el = time.time() - t0
                rate = done / (el / 60) if el > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  ⚡ [{done}/{total}] ok={ok[0]} err={err[0]} | "
                      f"{el/60:.1f}분 | ETA:{eta:.0f}분 | {rate:.0f}건/분")
            
            if done % SAVE_EVERY == 0:
                with open(RESULT_FILE, "w", encoding="utf-8") as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=1)
    
    async with httpx.AsyncClient() as client:
        # 배치 단위 처리 (메모리 관리)
        BATCH = 20
        for bi in range(0, len(remaining), BATCH):
            batch = remaining[bi:bi + BATCH]
            await asyncio.gather(*[process_one(client, d) for d in batch])
    
    # 최종 저장
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=1)
    
    el = time.time() - t0
    print(f"\n{'='*55}")
    print(f"  ✅ 완료! {el/60:.1f}분")
    print(f"  성공: {ok[0]} | 오류: {err[0]}")
    print(f"  결과: {RESULT_FILE}")
    print(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
