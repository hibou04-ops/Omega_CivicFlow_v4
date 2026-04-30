###############################################################
# ═══════════════════════════════════════════════════════════
#  Omega CivicFlow — Colab H100 완전 재처리 v4
#  DataSet.zip → 텍스트 추출 → vLLM 분석 → 결과 다운로드
#
#  준비물: DataSet.zip (Colab에 업로드 완료)
#
#  셀 1: 설치 + DataSet 압축 해제 + 텍스트 추출
#  셀 2: vLLM 서버 시작
#  셀 3: 전체 LLM 분석 실행
#  셀 4: 결과 다운로드
# ═══════════════════════════════════════════════════════════
###############################################################


###############################################################
# 셀 1: 설치 + DataSet 압축 해제 + 텍스트 추출
###############################################################

# %%
!pip install -q vllm httpx beautifulsoup4 lxml pdfplumber

import os, zipfile, json, re, time, glob
from bs4 import BeautifulSoup

DATASET_ZIP = "/content/DataSet.zip"
EXTRACT_DIR = "/content/DataSet"
PENDING_FILE = "/content/pending_docs.json"

# 1) 압축 해제
print("📦 DataSet.zip 압축 해제...")
t0 = time.time()
with zipfile.ZipFile(DATASET_ZIP, 'r') as z:
    z.extractall("/content/")
print(f"   완료! ({time.time()-t0:.1f}초)")

# 실제 파일 위치 확인
if not os.path.exists(EXTRACT_DIR):
    # 다른 폴더명으로 추출된 경우
    dirs = [d for d in os.listdir("/content/") if os.path.isdir(f"/content/{d}") and "Data" in d]
    if dirs:
        EXTRACT_DIR = f"/content/{dirs[0]}"
    print(f"   추출 폴더: {EXTRACT_DIR}")

all_files = []
for root, dirs, files in os.walk(EXTRACT_DIR):
    for f in files:
        fp = os.path.join(root, f)
        if os.path.getsize(fp) > 100:  # 100바이트 이상만
            all_files.append(fp)

print(f"   총 파일: {len(all_files)}개\n")


# 2) DART 파일에서 텍스트 추출
def extract_text_from_dart_zip(filepath):
    """DART ZIP 파일에서 XML/HTML 텍스트 추출"""
    try:
        with zipfile.ZipFile(filepath, 'r') as z:
            texts = []
            # XML/HTML 파일 찾기
            xml_files = sorted([
                n for n in z.namelist()
                if n.lower().endswith(('.xml', '.html', '.htm', '.xhtml'))
                and not n.startswith('__MACOSX')
                and not n.startswith('.')
            ])
            if not xml_files:
                # 모든 파일 시도
                xml_files = [n for n in z.namelist() if not n.endswith('/')]

            for xf in xml_files:
                try:
                    raw = z.read(xf)
                    # 인코딩 시도
                    for enc in ['utf-8', 'euc-kr', 'cp949', 'latin-1']:
                        try:
                            content = raw.decode(enc)
                            break
                        except:
                            continue
                    else:
                        content = raw.decode('utf-8', errors='replace')

                    # HTML/XML 태그 제거
                    soup = BeautifulSoup(content, 'lxml')

                    # 스크립트/스타일 제거
                    for tag in soup.find_all(['script', 'style', 'meta', 'link']):
                        tag.decompose()

                    text = soup.get_text(separator=' ', strip=True)

                    # 공백 정리
                    text = re.sub(r'\s+', ' ', text).strip()

                    if len(text) > 50:
                        texts.append(text)
                except:
                    continue

            return "\n\n".join(texts)
    except zipfile.BadZipFile:
        return ""
    except Exception:
        return ""


def extract_text_from_pdf(filepath):
    """PDF 파일에서 텍스트 추출"""
    try:
        import pdfplumber
        texts = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages[:100]:  # 최대 100페이지
                text = page.extract_text() or ""
                if text.strip():
                    texts.append(text.strip())
        return "\n\n".join(texts)
    except Exception:
        return ""


print("📄 텍스트 추출 시작...")
t0 = time.time()
docs_out = []
skip = 0

for i, fp in enumerate(all_files):
    fname = os.path.basename(fp)

    # 파일 유형 판별
    text = ""
    if fname.endswith('.zip') and not fname.endswith('.zip.pdf'):
        text = extract_text_from_dart_zip(fp)
    elif fname.endswith('.pdf') or fname.endswith('.zip.pdf'):
        # .zip.pdf는 실제로 PDF인 경우가 많음
        text = extract_text_from_pdf(fp)
        if not text and fname.endswith('.zip.pdf'):
            # ZIP으로도 시도
            text = extract_text_from_dart_zip(fp)

    if not text or len(text.strip()) < 50:
        skip += 1
        continue

    docs_out.append({
        "doc_id": i + 1,
        "filename": fname,
        "text": text,
        "text_len": len(text),
        "source_path": fp,
    })

    if (i + 1) % 500 == 0:
        elapsed = time.time() - t0
        print(f"   추출: {i+1}/{len(all_files)} ({len(docs_out)}건 성공, {skip}건 스킵) [{elapsed:.0f}s]")

# 저장
with open(PENDING_FILE, "w", encoding="utf-8") as f:
    json.dump(docs_out, f, ensure_ascii=False)

elapsed = time.time() - t0
total_chars = sum(d["text_len"] for d in docs_out)
short = sum(1 for d in docs_out if d["text_len"] <= 14000)

print(f"\n{'═'*55}")
print(f"  ✅ 텍스트 추출 완료! ({elapsed:.0f}초)")
print(f"  성공: {len(docs_out)}건 | 스킵: {skip}건")
print(f"  총 텍스트: {total_chars:,}자")
print(f"  단문 (≤14K): {short}건 | 장문: {len(docs_out)-short}건")
print(f"  파일 크기: {os.path.getsize(PENDING_FILE)/1024/1024:.1f} MB")
print(f"{'═'*55}")
print(f"\n🟢 셀 2를 실행하세요!")


###############################################################
# 셀 2: vLLM 서버 시작 (약 3~5분)
###############################################################

# %%
import subprocess, time, json, urllib.request

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
    "--max-num-seqs", "16",
    "--enable-chunked-prefill",
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
                        print(f"   로그: {lines[-1].strip()[:100]}")
            except:
                pass

if not ready:
    print("❌ vLLM 시작 실패!")
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
        print(f"   워밍업: {r.status_code}")
except Exception as e:
    print(f"   워밍업 스킵: {e}")

print("\n🟢 셀 3을 실행하세요!")


###############################################################
# 셀 3: 전체 LLM 분석 실행
###############################################################

# %%
import json, re, time, asyncio, os
import httpx

MODEL = "Qwen/Qwen2.5-32B-Instruct-AWQ"
BASE = "http://localhost:8100"
CHUNK_THRESHOLD = 14000
CHUNK_SIZE = 12000
WORKERS = 10
CHUNK_WORKERS = 8
SAVE_EVERY = 50
RESULT_FILE = "analysis_results.json"
PENDING_FILE = "/content/pending_docs.json"

# 데이터 로드
with open(PENDING_FILE, "r", encoding="utf-8") as f:
    docs = json.load(f)

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
    "primary": "문서 유형",
    "secondary": "세부 유형"
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
재무 수치가 있으면 반드시 정확히 포함하세요.

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
        if not p: continue
        pl = len(p)
        if pl > size:
            if cur:
                chunks.append("\n\n".join(cur)); cur, clen = [], 0
            for s in range(0, pl, size):
                chunks.append(p[s:s + size])
            continue
        if clen + pl + 2 > size and cur:
            chunks.append("\n\n".join(cur)); cur, clen = [], 0
        cur.append(p); clen += pl + 2
    if cur: chunks.append("\n\n".join(cur))
    return chunks if chunks else [text[:size]]

def extract_company(filename):
    m = re.search(r'DART_P\d+_(.+?)_\d{13,14}', filename)
    return m.group(1) if m else "미확인"

def parse_json_safe(text):
    if not text or not text.strip():
        return {"summary": "응답 없음", "category": "기타공시"}
    text = text.strip()
    m = re.search(r'```(?:json)?\s*(\{.+?\})\s*```', text, re.DOTALL)
    if m: text = m.group(1)
    else:
        m = re.search(r'\{.+\}', text, re.DOTALL)
        if m: text = m.group(0)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    try: return json.loads(text)
    except: pass
    try:
        fixed = text.replace('\r\n','\\n').replace('\n','\\n').replace('\t','\\t')
        fixed = re.sub(r',\s*}', '}', fixed)
        fixed = re.sub(r',\s*]', ']', fixed)
        return json.loads(fixed)
    except: pass
    return {"summary": text[:2000] if len(text)>50 else "파싱 실패", "category": "기타공시", "_parse_failed": True}

async def call_vllm(client, prompt, max_retries=4, timeout=180.0):
    for attempt in range(max_retries):
        try:
            r = await client.post(f"{BASE}/v1/chat/completions", json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1, "max_tokens": 2048,
                "top_p": 0.9, "repetition_penalty": 1.05,
            }, timeout=timeout)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            if content and content.strip(): return content.strip()
            if attempt < max_retries - 1: await asyncio.sleep(2); continue
        except httpx.ReadTimeout:
            if attempt < max_retries - 1: await asyncio.sleep(3); continue
            return ""
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                await asyncio.sleep(10*(attempt+1)); continue
            if attempt < max_retries - 1: await asyncio.sleep(5); continue
            return ""
        except:
            if attempt < max_retries - 1: await asyncio.sleep(3); continue
            return ""
    return ""

async def analyze_doc(client, doc_id, filename, text):
    company = extract_company(filename)
    if len(text) <= CHUNK_THRESHOLD:
        raw = await call_vllm(client, ANALYSIS_PROMPT.format(text=text[:14000]))
        if not raw: return {"summary": "분석 실패", "category": "기타공시", "_error": True}
        r = parse_json_safe(raw); r["company_name"] = r.get("company_name", company); return r

    chunks = split_chunks(text, CHUNK_SIZE); tc = len(chunks)
    chunk_sem = asyncio.Semaphore(CHUNK_WORKERS)
    async def _s(i, c):
        async with chunk_sem:
            return (i, await call_vllm(client, CHUNK_PROMPT.format(company=company, ci=i+1, tc=tc, chunk=c), timeout=120.0))
    results = await asyncio.gather(*[_s(i,c) for i,c in enumerate(chunks)], return_exceptions=True)
    partials = []
    for r in results:
        if isinstance(r, Exception): continue
        i, t = r
        if t and t.strip(): partials.append(f"[파트 {i+1}/{tc}]\n{t.strip()}")
    if not partials:
        raw = await call_vllm(client, ANALYSIS_PROMPT.format(text=text[:14000]))
        if not raw: return {"summary": "분석 실패", "category": "기타공시", "_error": True}
        return parse_json_safe(raw)
    merged = "\n\n".join(partials)[:14000]
    raw = await call_vllm(client, MERGE_PROMPT.format(partials=merged), timeout=240.0)
    if not raw: return {"summary": partials[0][:2000], "category": "기타공시", "_partial": True}
    p = parse_json_safe(raw); p["_chunk_count"] = tc; p["_success_chunks"] = len(partials)
    p["company_name"] = p.get("company_name", company); return p

# ── 메인 ──────────────────────────────────────────────────

async def run_all():
    completed_ids = set(); all_results = []
    if os.path.exists(RESULT_FILE):
        try:
            with open(RESULT_FILE, "r", encoding="utf-8") as f:
                all_results = json.load(f)
            completed_ids = {r["doc_id"] for r in all_results}
            print(f"📋 복원: {len(completed_ids)}건")
        except: pass

    remaining = [d for d in docs if d["doc_id"] not in completed_ids]
    total = len(remaining)
    if total == 0: print("✅ 완료!"); return

    short = sum(1 for d in remaining if d["text_len"] <= CHUNK_THRESHOLD)
    print(f"{'═'*60}")
    print(f"  Ω  Colab H100 — 전체 재분석 (원본 DataSet)")
    print(f"  모델: {MODEL}")
    print(f"  대상: {total}건 (단문 {short} + 장문 {total-short})")
    print(f"  동시: 문서 {WORKERS}개, 청크 {CHUNK_WORKERS}개")
    print(f"{'═'*60}\n")

    doc_sem = asyncio.Semaphore(WORKERS)
    done = [0]; errs = [0]; t_start = time.time()

    async def _proc(doc):
        async with doc_sem:
            t0 = time.time()
            try:
                result = await analyze_doc(client, doc["doc_id"], doc["filename"], doc["text"])
                result["_model"] = MODEL
                all_results.append({"doc_id": doc["doc_id"], "filename": doc["filename"], "result": result})
                done[0] += 1
                if result.get("_error") or result.get("_parse_failed"): errs[0] += 1
                if done[0] % 100 == 0 or done[0] == total:
                    el = time.time()-t_start; rate = done[0]/(el/60); eta = (total-done[0])/rate if rate>0 else 0
                    print(f"  ⚡ [{done[0]}/{total}] ok={done[0]-errs[0]} err={errs[0]} | {el/60:.1f}분 | ETA:{eta:.0f}분 | {rate:.0f}건/분")
                if done[0] % SAVE_EVERY == 0:
                    with open(RESULT_FILE, "w", encoding="utf-8") as f:
                        json.dump(all_results, f, ensure_ascii=False, indent=1)
            except Exception as e:
                errs[0] += 1; done[0] += 1
                all_results.append({"doc_id": doc["doc_id"], "filename": doc["filename"],
                    "result": {"summary": f"오류: {str(e)[:200]}", "category": "기타공시", "_error": True, "_model": MODEL}})

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[_proc(d) for d in remaining])

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=1)

    el = time.time()-t_start
    print(f"\n{'═'*60}")
    print(f"  ✅ 완료! {el/60:.1f}분")
    print(f"  성공: {done[0]-errs[0]} | 오류: {errs[0]} | 총: {done[0]}")
    print(f"  평균: {el/max(done[0],1):.1f}초/문서")
    print(f"{'═'*60}")

await run_all()


###############################################################
# 셀 4: 결과 다운로드
###############################################################

# %%
import os, json

with open("analysis_results.json", "r", encoding="utf-8") as f:
    results = json.load(f)
total = len(results)
errs = sum(1 for r in results if r["result"].get("_error") or r["result"].get("_parse_failed"))
print(f"📊 총: {total} | 성공: {total-errs} | 오류: {errs}")
print(f"   크기: {os.path.getsize('analysis_results.json')/1048576:.1f} MB")

from google.colab import files
files.download("analysis_results.json")
print("\n✅ 다운로드! → 로컬에서 import_colab_results.py 실행")
