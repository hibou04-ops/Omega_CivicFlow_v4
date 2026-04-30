###############################################################
# ═══════════════════════════════════════════════════════════
#  Omega CivicFlow — Colab A100 전체 파이프라인 v5
#  DataSet.zip → 텍스트 추출 → vLLM 분석 → 결과 다운로드
#
#  ■ A100 (40GB/80GB) 최적화
#  ■ 청크 12000자 / 호출 제한 없음 / 무제한 동시 처리
#
#  준비:
#    1) DataSet.zip을 Google Drive 루트에 업로드
#    2) Colab에서 이 스크립트의 각 셀을 순서대로 실행
#
#  셀 1: 설치 + Drive 마운트 + 텍스트 추출
#  셀 2: vLLM 서버 시작 (A100 최적화)
#  셀 3: 전체 LLM 분석 실행
#  셀 4: 결과 다운로드
# ═══════════════════════════════════════════════════════════
###############################################################


###############################################################
# 셀 1: 설치 + Drive에서 DataSet 복사 + 텍스트 추출
###############################################################

# %%
!pip install -q vllm httpx beautifulsoup4 lxml pdfplumber

import os, zipfile, json, re, time, glob
from bs4 import BeautifulSoup

# Google Drive 마운트
from google.colab import drive
drive.mount('/content/drive')

# Drive에서 DataSet.zip 복사 (로컬 디스크가 빠르니까)
DRIVE_ZIP = "/content/drive/MyDrive/DataSet.zip"
LOCAL_ZIP = "/content/DataSet.zip"
EXTRACT_DIR = "/content/DataSet"
PENDING_FILE = "/content/pending_docs.json"

if os.path.exists(DRIVE_ZIP):
    print("📥 Google Drive → 로컬 복사...")
    t0 = time.time()
    !cp "{DRIVE_ZIP}" "{LOCAL_ZIP}"
    print(f"   완료! ({time.time()-t0:.1f}초)")
elif os.path.exists(LOCAL_ZIP):
    print("📦 로컬 DataSet.zip 사용")
else:
    print("❌ DataSet.zip 없음!")
    print("   1) Drive 루트에 업로드하거나")
    print("   2) Colab에 직접 업로드하세요")
    raise FileNotFoundError("DataSet.zip")

# 압축 해제
print("📦 DataSet.zip 압축 해제...")
t0 = time.time()
with zipfile.ZipFile(LOCAL_ZIP, 'r') as z:
    z.extractall("/content/")
print(f"   완료! ({time.time()-t0:.1f}초)")

# 실제 폴더 확인
if not os.path.exists(EXTRACT_DIR):
    dirs = [d for d in os.listdir("/content/") if os.path.isdir(f"/content/{d}") and "Data" in d]
    if dirs:
        EXTRACT_DIR = f"/content/{dirs[0]}"
    print(f"   추출 폴더: {EXTRACT_DIR}")

# 파일 수집
all_files = []
for root, dirs, files in os.walk(EXTRACT_DIR):
    # .tmp 폴더 제외
    dirs[:] = [d for d in dirs if not d.startswith('.tmp')]
    for f in files:
        fp = os.path.join(root, f)
        try:
            if os.path.getsize(fp) > 100:
                all_files.append(fp)
        except:
            continue

print(f"   총 파일: {len(all_files)}개\n")


# ── 텍스트 추출 함수 ──────────────────────────────────────

def extract_text_from_dart_zip(filepath):
    """DART ZIP 파일에서 XML/HTML 텍스트 추출"""
    try:
        with zipfile.ZipFile(filepath, 'r') as z:
            texts = []
            xml_files = sorted([
                n for n in z.namelist()
                if n.lower().endswith(('.xml', '.html', '.htm', '.xhtml'))
                and not n.startswith('__MACOSX')
                and not n.startswith('.')
            ])
            if not xml_files:
                xml_files = [n for n in z.namelist() if not n.endswith('/')]

            for xf in xml_files:
                try:
                    raw = z.read(xf)
                    for enc in ['utf-8', 'euc-kr', 'cp949', 'latin-1']:
                        try:
                            content = raw.decode(enc)
                            break
                        except:
                            continue
                    else:
                        content = raw.decode('utf-8', errors='replace')

                    soup = BeautifulSoup(content, 'lxml')
                    for tag in soup.find_all(['script', 'style', 'meta', 'link']):
                        tag.decompose()
                    text = soup.get_text(separator=' ', strip=True)
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
            for page in pdf.pages[:100]:
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
    text = ""

    if fname.endswith('.zip') and not fname.endswith('.zip.pdf'):
        text = extract_text_from_dart_zip(fp)
    elif fname.endswith('.pdf') or fname.endswith('.zip.pdf'):
        text = extract_text_from_pdf(fp)
        if not text and fname.endswith('.zip.pdf'):
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
# 셀 2: vLLM 서버 시작 — A100 최적화 (약 3~5분)
###############################################################

# %%
import subprocess, time, json, urllib.request

MODEL = "Qwen/Qwen2.5-32B-Instruct-AWQ"
PORT = 8100

# 기존 프로세스 정리
!pkill -f "vllm.entrypoints" 2>/dev/null || true
time.sleep(2)

# GPU 확인
print("🖥️ GPU 정보:")
!nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader

# A100 메모리 감지 — 40GB vs 80GB
gpu_mem = 40
try:
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
        capture_output=True, text=True
    )
    gpu_mem = int(r.stdout.strip()) // 1024
except:
    pass

# A100 최적 설정
if gpu_mem >= 70:
    # A100 80GB — 풀파워
    MAX_MODEL_LEN = "16384"
    GPU_UTIL = "0.94"
    MAX_SEQS = "24"
    print(f"\n⚡ A100 80GB 감지 — 풀파워 모드")
else:
    # A100 40GB
    MAX_MODEL_LEN = "8192"
    GPU_UTIL = "0.92"
    MAX_SEQS = "16"
    print(f"\n⚡ A100 40GB 감지 — 최적 모드")

# vLLM 서버 시작
proc = subprocess.Popen([
    "python", "-m", "vllm.entrypoints.openai.api_server",
    "--model", MODEL,
    "--quantization", "awq",
    "--max-model-len", MAX_MODEL_LEN,
    "--gpu-memory-utilization", GPU_UTIL,
    "--port", str(PORT),
    "--dtype", "float16",
    "--max-num-seqs", MAX_SEQS,
    "--enable-chunked-prefill",
], stdout=open("vllm.log", "w"), stderr=subprocess.STDOUT)

print("⏳ vLLM 서버 시작 대기...")
ready = False
for i in range(120):  # 최대 10분 대기
    time.sleep(5)
    try:
        r = urllib.request.urlopen(f"http://localhost:{PORT}/v1/models", timeout=5)
        data = json.loads(r.read())
        model_ids = [m["id"] for m in data.get("data", [])]
        print(f"\n✅ vLLM 준비 완료! ({(i+1)*5}초)")
        print(f"   모델: {model_ids}")
        print(f"   max_model_len: {MAX_MODEL_LEN}")
        print(f"   max_num_seqs: {MAX_SEQS}")
        ready = True
        break
    except Exception:
        if (i+1) % 12 == 0:
            print(f"   ... {(i+1)*5}초 경과")
            try:
                with open("vllm.log") as f:
                    lines = f.readlines()
                    if lines:
                        print(f"   로그: {lines[-1].strip()[:120]}")
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
# 셀 3: 전체 LLM 분석 — 호출 제한 없음
###############################################################

# %%
import json, re, time, asyncio, os
import httpx

MODEL = "Qwen/Qwen2.5-32B-Instruct-AWQ"
BASE = "http://localhost:8100"

# ═══ 핵심 설정 ═══
CHUNK_THRESHOLD = 14000    # 이 이상이면 청크 분할
CHUNK_SIZE = 12000         # 청크 크기 12000자
WORKERS = 16               # 동시 문서 처리 (제한 없음 — A100 풀파워)
CHUNK_WORKERS = 12         # 동시 청크 처리
SAVE_EVERY = 50            # 50건마다 자동 저장
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
    """텍스트를 size 단위로 청크 분할 (문단 경계 우선)"""
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

async def call_vllm(client, prompt, max_retries=5, timeout=300.0):
    """vLLM API 호출 — 재시도 무제한 스타일, 타임아웃 넉넉하게"""
    for attempt in range(max_retries):
        try:
            r = await client.post(f"{BASE}/v1/chat/completions", json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 2048,
                "top_p": 0.9,
                "repetition_penalty": 1.05,
            }, timeout=timeout)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            if content and content.strip():
                return content.strip()
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
        except httpx.ReadTimeout:
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            return ""
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                # 429는 짧게 대기 후 즉시 재시도 (제한 없음)
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if attempt < max_retries - 1:
                await asyncio.sleep(3)
                continue
            return ""
        except Exception:
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            return ""
    return ""

async def analyze_doc(client, doc_id, filename, text):
    company = extract_company(filename)

    # 단문 — 한 번에 분석
    if len(text) <= CHUNK_THRESHOLD:
        raw = await call_vllm(client, ANALYSIS_PROMPT.format(text=text[:14000]))
        if not raw:
            return {"summary": "분석 실패", "category": "기타공시", "_error": True}
        r = parse_json_safe(raw)
        r["company_name"] = r.get("company_name", company)
        return r

    # 장문 — 12000자 청크 분할
    chunks = split_chunks(text, CHUNK_SIZE)
    tc = len(chunks)
    chunk_sem = asyncio.Semaphore(CHUNK_WORKERS)

    async def _process_chunk(i, c):
        async with chunk_sem:
            return (i, await call_vllm(
                client,
                CHUNK_PROMPT.format(company=company, ci=i+1, tc=tc, chunk=c),
                timeout=180.0
            ))

    results = await asyncio.gather(
        *[_process_chunk(i, c) for i, c in enumerate(chunks)],
        return_exceptions=True
    )

    partials = []
    for r in results:
        if isinstance(r, Exception):
            continue
        i, t = r
        if t and t.strip():
            partials.append(f"[파트 {i+1}/{tc}]\n{t.strip()}")

    if not partials:
        # 청크 모두 실패 → 앞부분만으로 분석
        raw = await call_vllm(client, ANALYSIS_PROMPT.format(text=text[:14000]))
        if not raw:
            return {"summary": "분석 실패", "category": "기타공시", "_error": True}
        return parse_json_safe(raw)

    # 파트 요약 병합
    merged = "\n\n".join(partials)[:14000]
    raw = await call_vllm(client, MERGE_PROMPT.format(partials=merged), timeout=300.0)
    if not raw:
        return {"summary": partials[0][:2000], "category": "기타공시", "_partial": True}

    p = parse_json_safe(raw)
    p["_chunk_count"] = tc
    p["_success_chunks"] = len(partials)
    p["company_name"] = p.get("company_name", company)
    return p


# ── 메인 실행 ─────────────────────────────────────────────

async def run_all():
    completed_ids = set()
    all_results = []

    # 이전 진행 복원
    if os.path.exists(RESULT_FILE):
        try:
            with open(RESULT_FILE, "r", encoding="utf-8") as f:
                all_results = json.load(f)
            completed_ids = {r["doc_id"] for r in all_results}
            print(f"📋 이전 진행 복원: {len(completed_ids)}건")
        except:
            pass

    remaining = [d for d in docs if d["doc_id"] not in completed_ids]
    total = len(remaining)
    if total == 0:
        print("✅ 이미 모두 완료!")
        return

    short = sum(1 for d in remaining if d["text_len"] <= CHUNK_THRESHOLD)

    print(f"{'═'*60}")
    print(f"  Ω  Colab A100 — 전체 분석 파이프라인 v5")
    print(f"  모델: {MODEL}")
    print(f"  대상: {total}건 (단문 {short} + 장문 {total-short})")
    print(f"  청크: {CHUNK_SIZE:,}자 | 동시: 문서{WORKERS} 청크{CHUNK_WORKERS}")
    print(f"  호출 제한: 없음 | 자동저장: {SAVE_EVERY}건마다")
    print(f"{'═'*60}\n")

    doc_sem = asyncio.Semaphore(WORKERS)
    done = [0]
    errs = [0]
    t_start = time.time()

    async def _proc(doc):
        async with doc_sem:
            try:
                result = await analyze_doc(client, doc["doc_id"], doc["filename"], doc["text"])
                result["_model"] = MODEL
                all_results.append({
                    "doc_id": doc["doc_id"],
                    "filename": doc["filename"],
                    "result": result,
                })
                done[0] += 1

                if result.get("_error") or result.get("_parse_failed"):
                    errs[0] += 1

                # 진행 상황 출력
                if done[0] % 50 == 0 or done[0] == total:
                    el = time.time() - t_start
                    rate = done[0] / (el / 60) if el > 0 else 0
                    eta = (total - done[0]) / rate if rate > 0 else 0
                    print(f"  ⚡ [{done[0]}/{total}] ok={done[0]-errs[0]} err={errs[0]} | "
                          f"{el/60:.1f}분 | ETA:{eta:.0f}분 | {rate:.0f}건/분")

                # 자동 저장
                if done[0] % SAVE_EVERY == 0:
                    with open(RESULT_FILE, "w", encoding="utf-8") as f:
                        json.dump(all_results, f, ensure_ascii=False, indent=1)

            except Exception as e:
                errs[0] += 1
                done[0] += 1
                all_results.append({
                    "doc_id": doc["doc_id"],
                    "filename": doc["filename"],
                    "result": {
                        "summary": f"오류: {str(e)[:200]}",
                        "category": "기타공시",
                        "_error": True,
                        "_model": MODEL,
                    },
                })

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[_proc(d) for d in remaining])

    # 최종 저장
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=1)

    # Drive에도 백업
    try:
        import shutil
        shutil.copy(RESULT_FILE, "/content/drive/MyDrive/analysis_results.json")
        print("  💾 Drive 백업 완료")
    except:
        pass

    el = time.time() - t_start
    print(f"\n{'═'*60}")
    print(f"  ✅ 전체 분석 완료! {el/60:.1f}분")
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
chunks_used = sum(1 for r in results if r["result"].get("_chunk_count"))

print(f"{'═'*55}")
print(f"  📊 분석 결과 요약")
print(f"  총: {total} | 성공: {total-errs} | 오류: {errs}")
print(f"  청크 분할 사용: {chunks_used}건")
print(f"  파일 크기: {os.path.getsize('analysis_results.json')/1048576:.1f} MB")
print(f"{'═'*55}")

from google.colab import files
files.download("analysis_results.json")
print("\n✅ 다운로드 완료!")
print("📋 다음 단계: 로컬에서 import_colab_results.py 실행")
print("   cd backend")
print("   python ..\\tools\\import_colab_results.py")
