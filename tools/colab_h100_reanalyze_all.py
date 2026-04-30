###############################################################
# ═══════════════════════════════════════════════════════════
#  Omega CivicFlow — Colab H100 전체 재분석 v3
#  2,517건 전체 LLM 재분석 + 결과 JSON 다운로드
#
#  준비물: pending_docs_all.json (397MB, 로컬에서 export)
#
#  사용법:
#  1. 런타임 → 런타임 유형 변경 → GPU → H100 (또는 A100)
#  2. 좌측 파일 패널에 pending_docs_all.json 업로드
#  3. 셀 1 → 2 → 3 → 4 순서로 실행
#  4. 완료 후 analysis_results.json 다운로드
#  5. 로컬에서 import_colab_results.py 실행
# ═══════════════════════════════════════════════════════════
###############################################################


###############################################################
# 셀 1: 설치 + vLLM 서버 시작 (약 3~5분)
###############################################################

# %%
!pip install -q vllm httpx

import subprocess, time, json, urllib.request, os

MODEL = "Qwen/Qwen2.5-32B-Instruct-AWQ"
PORT = 8100

# 기존 프로세스 정리
!pkill -f "vllm.entrypoints" 2>/dev/null || true
time.sleep(2)

# GPU 확인
!nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

# vLLM 서버 시작 — H100 최적화
proc = subprocess.Popen([
    "python", "-m", "vllm.entrypoints.openai.api_server",
    "--model", MODEL,
    "--quantization", "awq",
    "--max-model-len", "8192",
    "--gpu-memory-utilization", "0.92",
    "--port", str(PORT),
    "--dtype", "float16",
    "--disable-log-requests",
    "--max-num-seqs", "16",          # H100: 동시 시퀀스 16개
    "--enable-chunked-prefill",       # H100: 청크드 프리필 활성화
], stdout=open("vllm.log", "w"), stderr=subprocess.STDOUT)

print("⏳ vLLM 서버 시작 대기...")
ready = False
for i in range(90):
    time.sleep(5)
    try:
        r = urllib.request.urlopen(f"http://localhost:{PORT}/v1/models", timeout=5)
        data = json.loads(r.read())
        model_ids = [m["id"] for m in data.get("data", [])]
        print(f"\n✅ vLLM 준비 완료! ({(i+1)*5}초)")
        print(f"   모델: {model_ids}")
        ready = True
        break
    except Exception:
        if (i+1) % 12 == 0:
            print(f"   ... {(i+1)*5}초 경과")
            try:
                with open("vllm.log") as f:
                    lines = f.readlines()
                    if lines:
                        print(f"   최근 로그: {lines[-1].strip()[:100]}")
            except:
                pass

if not ready:
    print("❌ vLLM 시작 실패! 로그 확인:")
    with open("vllm.log") as f:
        print(f.read()[-3000:])
    raise RuntimeError("vLLM 시작 실패")

# 워밍업
try:
    import httpx
    with httpx.Client(timeout=60) as c:
        r = c.post(f"http://localhost:{PORT}/v1/chat/completions", json={
            "model": MODEL,
            "messages": [{"role": "user", "content": "안녕하세요"}],
            "max_tokens": 10,
        })
        print(f"   워밍업 완료: {r.status_code}")
except Exception as e:
    print(f"   워밍업 스킵: {e}")

print("\n🟢 셀 2를 실행하세요!")


###############################################################
# 셀 2: 데이터 로드 + 통계 확인
###############################################################

# %%
import json, os

INPUT_FILE = "pending_docs_all.json"

if not os.path.exists(INPUT_FILE):
    # Google Drive에서 로드 시도
    from google.colab import drive
    drive.mount('/content/drive')
    INPUT_FILE = "/content/drive/MyDrive/pending_docs_all.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    docs = json.load(f)

total = len(docs)
total_chars = sum(d["text_len"] for d in docs)
short = sum(1 for d in docs if d["text_len"] <= 14000)
long_docs = total - short

print(f"═══════════════════════════════════════")
print(f"  Ω  데이터 로드 완료")
print(f"  총 문서: {total:,}건")
print(f"  총 텍스트: {total_chars:,}자")
print(f"  단문 (≤14K): {short:,}건")
print(f"  장문 (>14K): {long_docs:,}건")
print(f"  예상 소요: ~{total * 2 / 60:.0f}분 (H100 기준)")
print(f"═══════════════════════════════════════")
print(f"\n🟢 셀 3을 실행하세요!")


###############################################################
# 셀 3: 전체 재분석 실행 (메인)
###############################################################

# %%
import json, re, time, asyncio, os
import httpx

MODEL = "Qwen/Qwen2.5-32B-Instruct-AWQ"
BASE = "http://localhost:8100"
CHUNK_THRESHOLD = 14000
CHUNK_SIZE = 12000
WORKERS = 10           # H100: 동시 10문서
CHUNK_WORKERS = 8      # 장문 내부 청크 동시 8개
SAVE_EVERY = 50        # 50건마다 중간 저장
RESULT_FILE = "analysis_results.json"

# ── 프롬프트 ──────────────────────────────────────────────

ANALYSIS_PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.
아래 공시문서를 분석하여 **반드시 JSON 형식**으로 출력하세요.

[문서 내용]
{text}

[출력 JSON — 아래 형식을 정확히 지켜주세요]
{{
  "summary": "핵심 요약 (반드시 300자 이상. 매출액/영업이익/자산/부채 등 재무 수치 필수 포함)",
  "category": "사업보고서 | 반기보고서 | 분기보고서 | 재무제표 | 감사보고서 | 주석 | 정정신고 | 주요사항보고서 | 유상증자결정 | 대량보유보고서 | 임원·주요주주변동 | 자기주식 | 합병·분할 | 배당 | 기타공시",
  "evidence": "요약 근거 핵심 문장 3개 이상 (원문 인용)",
  "financial_metrics": "주요 재무지표 종합 (매출액, 영업이익, 자산총계, 부채총계 등)",
  "insight_vectors": "투자자 관점: 핵심 리스크와 기회",
  "company_name": "회사명",
  "disclosure_title": "공시명",
  "document_type": {{
    "primary": "문서 유형 (위 category 중 하나)",
    "secondary": "세부 유형 (해당 시)"
  }},
  "key_points": ["핵심 포인트 1", "핵심 포인트 2", "핵심 포인트 3"],
  "risk_notes": ["리스크 1", "리스크 2"],
  "key_changes": [],
  "offering_terms": {{}},
  "key_audit_matters": [],
  "footnote_risks": []
}}

[절대 규칙]
1. summary는 반드시 300자 이상, 모든 재무 수치 포함
2. 반드시 한국어로 작성 (중국어/일본어 문자 사용 금지)
3. JSON만 출력. 다른 텍스트 절대 금지
4. 문서에 없는 숫자를 만들지 마라"""

CHUNK_PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.
다음은 '{company}' 공시문서의 일부(파트 {ci}/{tc})입니다.
핵심 내용을 300~600자로 한국어 요약하세요.
재무 수치(매출, 이익, 자산 등)가 있으면 반드시 정확히 포함하세요.

[파트 {ci}/{tc}]
{chunk}

핵심 요약:"""

MERGE_PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.
다음은 하나의 공시문서를 여러 파트로 나누어 요약한 결과입니다.
이 부분 요약들을 통합하여 하나의 완전한 분석 JSON을 작성하세요.

{partials}

[출력 JSON]
{{
  "summary": "전체 통합 요약 (500자 이상, 모든 파트의 재무 수치 포함)",
  "category": "사업보고서 | 반기보고서 | 분기보고서 | 재무제표 | 감사보고서 | 주석 | 정정신고 | 주요사항보고서 | 유상증자결정 | 대량보유보고서 | 임원·주요주주변동 | 자기주식 | 합병·분할 | 배당 | 기타공시",
  "evidence": "핵심 근거 문장 종합",
  "financial_metrics": "모든 파트의 재무지표 종합",
  "insight_vectors": "투자자 관점 종합",
  "company_name": "회사명",
  "disclosure_title": "공시명",
  "document_type": {{"primary": "유형", "secondary": ""}},
  "key_points": ["핵심 포인트들"],
  "risk_notes": ["리스크들"],
  "key_changes": [],
  "offering_terms": {{}},
  "key_audit_matters": [],
  "footnote_risks": []
}}

[규칙] 한국어만, JSON만 출력."""

# ── 유틸리티 ──────────────────────────────────────────────

def split_chunks(text, size=CHUNK_SIZE):
    paras = re.split(r'\n\s*\n', text)
    chunks, cur, clen = [], [], 0
    for p in paras:
        p = p.strip()
        if not p:
            continue
        pl = len(p)
        if pl > size:
            if cur:
                chunks.append("\n\n".join(cur))
                cur, clen = [], 0
            for s in range(0, pl, size):
                chunks.append(p[s:s + size])
            continue
        if clen + pl + 2 > size and cur:
            chunks.append("\n\n".join(cur))
            cur, clen = [], 0
        cur.append(p)
        clen += pl + 2
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks if chunks else [text[:size]]


def extract_company(filename):
    m = re.search(r'DART_P\d+_(.+?)_\d{13,14}', filename)
    return m.group(1) if m else "미확인"


def parse_json_safe(text):
    if not text or not text.strip():
        return {"summary": "응답 없음", "category": "기타공시"}

    text = text.strip()

    # 코드블록 내 JSON
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
    except json.JSONDecodeError:
        pass

    try:
        fixed = text.replace('\r\n', '\\n').replace('\n', '\\n').replace('\t', '\\t')
        fixed = re.sub(r',\s*}', '}', fixed)
        fixed = re.sub(r',\s*]', ']', fixed)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    return {
        "summary": text[:2000] if len(text) > 50 else "파싱 실패",
        "category": "기타공시",
        "_parse_failed": True,
    }


async def call_vllm(client, prompt, max_retries=4, timeout=180.0):
    for attempt in range(max_retries):
        try:
            r = await client.post(
                f"{BASE}/v1/chat/completions",
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2048,
                    "top_p": 0.9,
                    "repetition_penalty": 1.05,
                },
                timeout=timeout,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            if content and content.strip():
                return content.strip()
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
        except httpx.ReadTimeout:
            if attempt < max_retries - 1:
                print(f"      ⏳ 타임아웃, 재시도 {attempt+2}/{max_retries}")
                await asyncio.sleep(3)
                continue
            return ""
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"      ⏳ 서버 과부하, {wait}s 대기")
                await asyncio.sleep(wait)
                continue
            if attempt < max_retries - 1:
                await asyncio.sleep(5)
                continue
            return ""
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(3)
                continue
            return ""
    return ""


# ── 분석 파이프라인 ──────────────────────────────────────

async def analyze_doc(client, doc_id, filename, text):
    company = extract_company(filename)
    text_len = len(text)

    if text_len <= CHUNK_THRESHOLD:
        raw = await call_vllm(client, ANALYSIS_PROMPT.format(text=text[:14000]))
        if not raw:
            return {"summary": "분석 실패", "category": "기타공시", "_error": True}
        result = parse_json_safe(raw)
        result["company_name"] = result.get("company_name", company)
        return result

    # 장문: 청크 분할 → 병렬 요약 → 통합
    chunks = split_chunks(text, CHUNK_SIZE)
    tc = len(chunks)
    chunk_sem = asyncio.Semaphore(CHUNK_WORKERS)

    async def _sum_chunk(i, c):
        async with chunk_sem:
            prompt = CHUNK_PROMPT.format(company=company, ci=i+1, tc=tc, chunk=c)
            return (i, await call_vllm(client, prompt, timeout=120.0))

    tasks = [_sum_chunk(i, c) for i, c in enumerate(chunks)]
    chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

    partials = []
    for result in chunk_results:
        if isinstance(result, Exception):
            continue
        i, text_r = result
        if text_r and text_r.strip():
            partials.append(f"[파트 {i+1}/{tc}]\n{text_r.strip()}")

    if not partials:
        raw = await call_vllm(client, ANALYSIS_PROMPT.format(text=text[:14000]))
        if not raw:
            return {"summary": "분석 실패", "category": "기타공시", "_error": True}
        return parse_json_safe(raw)

    merged = "\n\n".join(partials)
    if len(merged) > 14000:
        merged = merged[:14000]

    raw = await call_vllm(client, MERGE_PROMPT.format(partials=merged), timeout=240.0)
    if not raw:
        return {"summary": partials[0][:2000], "category": "기타공시", "_partial": True}

    parsed = parse_json_safe(raw)
    parsed["_chunk_count"] = tc
    parsed["_success_chunks"] = len(partials)
    parsed["company_name"] = parsed.get("company_name", company)
    return parsed


# ── 메인 실행 ────────────────────────────────────────────

async def run_all():
    # 이전 결과 복원 (자동 resume)
    completed_ids = set()
    all_results = []
    if os.path.exists(RESULT_FILE):
        try:
            with open(RESULT_FILE, "r", encoding="utf-8") as f:
                all_results = json.load(f)
            completed_ids = {r["doc_id"] for r in all_results}
            print(f"📋 이전 진행 복원: {len(completed_ids)}건 완료됨")
        except:
            pass

    remaining = [d for d in docs if d["doc_id"] not in completed_ids]
    total = len(remaining)

    if total == 0:
        print("✅ 모든 문서 분석 완료!")
        return

    total_chars = sum(d["text_len"] for d in remaining)
    short = sum(1 for d in remaining if d["text_len"] <= CHUNK_THRESHOLD)

    print(f"{'═'*60}")
    print(f"  Ω  Colab H100 vLLM 전체 재분석")
    print(f"  모델: {MODEL}")
    print(f"  대상: {total}건 (단문 {short} + 장문 {total - short})")
    print(f"  총 텍스트: {total_chars:,}자")
    print(f"  동시 처리: 문서 {WORKERS}개, 청크 {CHUNK_WORKERS}개")
    print(f"{'═'*60}\n")

    doc_sem = asyncio.Semaphore(WORKERS)
    done_count = [0]
    error_count = [0]
    start_time = time.time()

    async def _process(doc):
        async with doc_sem:
            doc_id = doc["doc_id"]
            filename = doc["filename"]
            text = doc["text"]
            t0 = time.time()

            try:
                result = await analyze_doc(client, doc_id, filename, text)
                result["_model"] = MODEL
                elapsed = time.time() - t0

                all_results.append({
                    "doc_id": doc_id,
                    "filename": filename,
                    "result": result,
                })
                done_count[0] += 1

                is_error = result.get("_error") or result.get("_parse_failed")
                if is_error:
                    error_count[0] += 1

                # 진행 출력 (100건마다)
                if done_count[0] % 100 == 0 or done_count[0] == total:
                    elapsed_total = time.time() - start_time
                    rate = done_count[0] / (elapsed_total / 60)
                    eta = (total - done_count[0]) / rate if rate > 0 else 0
                    print(
                        f"  ⚡ [{done_count[0]}/{total}] "
                        f"성공={done_count[0]-error_count[0]} 오류={error_count[0]} "
                        f"| {elapsed_total/60:.1f}분 경과 "
                        f"| ETA: {eta:.0f}분 "
                        f"| {rate:.1f}건/분"
                    )

                # 중간 저장
                if done_count[0] % SAVE_EVERY == 0:
                    with open(RESULT_FILE, "w", encoding="utf-8") as f:
                        json.dump(all_results, f, ensure_ascii=False, indent=1)

            except Exception as e:
                error_count[0] += 1
                done_count[0] += 1
                all_results.append({
                    "doc_id": doc_id,
                    "filename": filename,
                    "result": {
                        "summary": f"처리 오류: {str(e)[:200]}",
                        "category": "기타공시",
                        "_error": True,
                        "_model": MODEL,
                    }
                })

    async with httpx.AsyncClient() as client:
        tasks = [_process(d) for d in remaining]
        await asyncio.gather(*tasks)

    # 최종 저장
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=1)

    elapsed = time.time() - start_time
    success = done_count[0] - error_count[0]

    print(f"\n{'═'*60}")
    print(f"  ✅ 전체 완료! {elapsed/60:.1f}분 소요")
    print(f"  성공: {success} | 오류: {error_count[0]} | 총: {done_count[0]}")
    print(f"  평균: {elapsed/max(done_count[0],1):.1f}초/문서")
    print(f"  결과 파일: {RESULT_FILE}")
    print(f"{'═'*60}")

await run_all()


###############################################################
# 셀 4: 결과 다운로드
###############################################################

# %%
import os, json

# 최종 통계
with open("analysis_results.json", "r", encoding="utf-8") as f:
    results = json.load(f)

total = len(results)
errors = sum(1 for r in results if r["result"].get("_error") or r["result"].get("_parse_failed"))
success = total - errors

print(f"═══════════════════════════════════════")
print(f"  📊 최종 결과")
print(f"  총: {total} | 성공: {success} | 오류: {errors}")
print(f"  파일 크기: {os.path.getsize('analysis_results.json')/1024/1024:.1f} MB")
print(f"═══════════════════════════════════════")

from google.colab import files
files.download("analysis_results.json")
print("\n✅ 다운로드 시작! 로컬에서 import_colab_results.py 를 실행하세요.")
