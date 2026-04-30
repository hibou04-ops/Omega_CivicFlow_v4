###############################################################
# ═══════════════════════════════════════════════════════════
#  Omega CivicFlow — Colab H100 올인원 파이프라인 v5
#  Phase 0~5: 환경설치 → vLLM 재분석 → QLoRA 학습 → 다운로드
#
#  준비물: pending_docs_all.json (로컬에서 export_all_for_colab.py)
#
#  사용법:
#  1. 런타임 → GPU → H100 선택
#  2. 좌측 파일 패널에 pending_docs_all.json 업로드
#  3. 이 파일을 Colab에 업로드 후 전체 실행 (Ctrl+F9)
#     또는 셀 단위로 순차 실행
#  4. 완료 후 3개 파일 자동 다운로드
#
#  총 소요: ~2시간 (H100 80GB 기준)
# ═══════════════════════════════════════════════════════════
###############################################################


###############################################################
# Phase 0: 환경 설치 + GPU 확인 (~3분)
###############################################################

# %%
import subprocess, time, os, sys

print("=" * 60)
print("  Ω  Phase 0 — 환경 설치 + GPU 확인 + 연결 보호")
print("=" * 60)

# ── [1/4] Colab 연결 끊김 방지 (JavaScript Keepalive) ────
print("🛡️  Colab 연결 보호 활성화...")
try:
    from IPython.display import display, Javascript
    # 60초마다 connect 버튼 클릭 + WebSocket ping
    display(Javascript('''
        function KeepAlive() {
            // 방법 1: connect 버튼 자동 클릭
            var buttons = document.querySelectorAll("colab-connect-button");
            buttons.forEach(function(btn) { btn.click(); });

            // 방법 2: 툴바 비활성화 방지
            document.querySelectorAll("colab-toolbar-button").forEach(
                function(b) { b.click && b.click(); }
            );

            console.log("[KeepAlive] " + new Date().toLocaleTimeString());
        }
        // 60초 간격 실행 (Colab 유휴 감지 90초보다 짧게)
        var keepAliveId = setInterval(KeepAlive, 60000);
        // 페이지 visibility 변경 시에도 실행
        document.addEventListener("visibilitychange", function() {
            if (!document.hidden) { KeepAlive(); }
        });
        console.log("[KeepAlive] 활성화 완료 — 60초 간격");
    '''))
    print("  ✅ JavaScript KeepAlive 활성화 (60초 간격)")
except Exception as e:
    print(f"  ⚠️  KeepAlive 설정 실패 (Colab 외 환경): {e}")

# ── [2/4] Google Drive 마운트 (백업 경로) ─────────────────
DRIVE_BACKUP = None
try:
    from google.colab import drive
    drive.mount('/content/drive', force_remount=False)
    DRIVE_BACKUP = "/content/drive/MyDrive/CivicFlow_Colab_Backup"
    os.makedirs(DRIVE_BACKUP, exist_ok=True)
    print(f"  ✅ Google Drive 백업 경로: {DRIVE_BACKUP}")
except Exception:
    print("  ⚠️  Google Drive 미마운트 — 로컬 저장만 사용")

# 백업 유틸리티 (전 Phase에서 사용)
import shutil
def backup_to_drive(filepath):
    """중요 파일을 Google Drive에 백업 (연결 끊김 대비)"""
    if DRIVE_BACKUP and os.path.exists(filepath):
        try:
            dest = os.path.join(DRIVE_BACKUP, os.path.basename(filepath))
            shutil.copy2(filepath, dest)
            return True
        except Exception:
            pass
    return False

# ── [3/4] 패키지 설치 ────────────────────────────────────
print("\n📦 패키지 설치 중...")
subprocess.run([
    sys.executable, "-m", "pip", "install", "-q",
    "vllm", "httpx",
    "transformers", "peft", "bitsandbytes",
    "accelerate", "trl", "datasets",
], check=True)

# flash-attn (선택적 — 실패해도 계속)
try:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "flash-attn", "--no-build-isolation"],
        check=True, timeout=300,
    )
    print("✅ flash-attn 설치 완료")
except Exception:
    print("⚠️  flash-attn 설치 실패 (sdpa fallback 사용)")

# ── [4/4] GPU 확인 ───────────────────────────────────────
print("\n🖥️  GPU 정보:")
subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                 "--format=csv,noheader"])

gpu_name = ""
try:
    gpu_name = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        text=True
    ).strip().upper()
except Exception:
    pass

if "H100" in gpu_name:
    print("\n✅ H100 감지 — 최고 성능 모드")
elif "A100" in gpu_name:
    print("\n✅ A100 감지 — 고성능 모드")
else:
    print(f"\n⚠️  GPU: {gpu_name or '알 수 없음'} — 성능이 다를 수 있습니다")

print("""
🛡️  연결 보호 요약:
  • JavaScript KeepAlive: 60초마다 자동 실행
  • Google Drive 백업: 중간 결과 자동 저장
  • 자동 Resume: 연결 끊겨도 중간 저장 지점에서 재시작
  • 브라우저 탭을 닫지 마세요!
""")
print("🟢 Phase 0 완료 — Phase 1 실행하세요")


###############################################################
# Phase 1: vLLM 서버 시작 + 워밍업 (~5분)
###############################################################

# %%
import subprocess, time, json, urllib.request, os

print("=" * 60)
print("  Ω  Phase 1 — vLLM 서버 시작")
print("=" * 60)

MODEL = "Qwen/Qwen2.5-7B-Instruct-AWQ"
PORT = 8100

# 기존 프로세스 정리
subprocess.run(["pkill", "-f", "vllm.entrypoints"], capture_output=True)
time.sleep(2)

# vLLM 서버 시작 — 7B 고속 모드
proc = subprocess.Popen([
    "python", "-m", "vllm.entrypoints.openai.api_server",
    "--model", MODEL,
    "--quantization", "awq",
    "--max-model-len", "8192",
    "--gpu-memory-utilization", "0.95",
    "--port", str(PORT),
    "--dtype", "float16",
    "--max-num-seqs", "64",
    "--enable-chunked-prefill",
], stdout=open("vllm.log", "w"), stderr=subprocess.STDOUT)

print(f"⏳ vLLM 서버 시작 대기 (모델: {MODEL})...")
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
        if (i + 1) % 12 == 0:
            print(f"   ... {(i+1)*5}초 경과")
            try:
                with open("vllm.log") as f:
                    lines = f.readlines()
                    if lines:
                        print(f"   최근 로그: {lines[-1].strip()[:120]}")
            except Exception:
                pass

if not ready:
    print("❌ vLLM 시작 실패! 로그 확인:")
    with open("vllm.log") as f:
        print(f.read()[-3000:])
    raise RuntimeError("vLLM 시작 실패")

# 워밍업 추론
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

print("\n🟢 Phase 1 완료 — Phase 2 실행하세요")


###############################################################
# Phase 2: 전체 LLM 재분석 (~80분)
###############################################################

# %%
import json, re, time, asyncio, os
import httpx

print("=" * 60)
print("  Ω  Phase 2 — 전체 LLM 재분석")
print("=" * 60)

MODEL = "Qwen/Qwen2.5-7B-Instruct-AWQ"
BASE = "http://localhost:8100"
CHUNK_THRESHOLD = 14000
CHUNK_SIZE = 12000
WORKERS = 12             # 안정 모드: 에러 최소화
CHUNK_WORKERS = 8        # 안정 모드: 청크 8개
SAVE_EVERY = 25            # 연결 끊김 대비: 25건마다 저장
RESULT_FILE = "analysis_results.json"
INPUT_FILE = "pending_docs_all.json"

# ── 데이터 로드 ──────────────────────────────────────────

# pending_docs_all.json 또는 pending_docs.jsonl 자동 탐지
if os.path.exists("pending_docs_all.json"):
    INPUT_FILE = "pending_docs_all.json"
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        docs = json.load(f)
elif os.path.exists("pending_docs.jsonl"):
    INPUT_FILE = "pending_docs.jsonl"
    docs = []
    # 인코딩 자동 탐지: utf-8 → cp949 → latin-1
    for enc in ["utf-8", "cp949", "latin-1"]:
        try:
            with open(INPUT_FILE, "r", encoding=enc) as f:
                f.readline()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    print(f"  📄 {INPUT_FILE} 인코딩: {enc}")
    with open(INPUT_FILE, "r", encoding=enc, errors="replace") as f:
        skip_count = 0
        for i, line in enumerate(f):
            line = line.strip().lstrip("\ufeff")  # BOM 제거
            if not line:
                continue
            try:
                d = json.loads(line)
                if "text_length" in d and "text_len" not in d:
                    d["text_len"] = d.pop("text_length")
                docs.append(d)
            except json.JSONDecodeError:
                skip_count += 1
                if skip_count <= 3:
                    print(f"  ⚠️ 라인 {i+1} 파싱 실패 (스킵)")
        if skip_count:
            print(f"  ⚠️ 총 {skip_count}개 라인 스킵")
else:
    raise FileNotFoundError(
        "pending_docs_all.json 또는 pending_docs.jsonl을 업로드하세요!"
    )

total_all = len(docs)
total_chars = sum(d["text_len"] for d in docs)
short = sum(1 for d in docs if d["text_len"] <= CHUNK_THRESHOLD)

print(f"  전체 문서: {total_all:,}건")
print(f"  텍스트 총량: {total_chars:,}자")
print(f"  단문 (≤14K): {short:,}건 | 장문 (>14K): {total_all - short:,}건")

# ── 프롬프트 (llm_service.py SYSTEM_PROMPT 기반) ─────────

SYSTEM_MSG = """[ROLE] 당신은 한국 금융감독원 DART 전자공시시스템 문서를 분석하는 전문 AI입니다.

[절대 규칙]
1. 출력은 반드시 JSON 단독. 인사말/설명/마크다운 절대 금지.
2. 문서에 없는 숫자를 절대 만들지 마라.
3. 모든 텍스트는 반드시 한국어(한글)로만 작성하라. 중국어/일본어 문자 사용 절대 금지.
4. 숫자는 원문 그대로 (단위 포함: '1,234억원', '25,445주').
5. 불확실한 항목은 null 또는 "해당 없음".
6. 깨진 OCR 텍스트는 인용하지 말고 문맥으로 재구성.
7. company_name이 불확실하면 "미확인".
8. summary는 반드시 자연스러운 한국어 문장으로 작성."""

ANALYSIS_PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.
아래 공시문서를 분석하여 **반드시 JSON 형식**으로 출력하세요.

[절대 규칙]
1. 모든 필드는 반드시 한국어(한글+숫자)로만 작성. 중국어(漢字)/일본어/베트남어/영어 문자 절대 금지.
2. evidence 필드도 한국어로 번역하여 인용. 원문이 한자여도 반드시 한글로 변환.
3. company_name은 반드시 한글 법인명만. 예: '삼성전자', 'LG화학'
4. 문서에 없는 숫자를 만들지 마라.
5. JSON만 출력. 다른 텍스트 절대 금지.

[문서 내용]
{text}

[출력 JSON]
{{"summary": "핵심 요약 (반드시 300자 이상. 매출액/영업이익/자산/부채 등 재무 수치 필수 포함)",
"category": "사업보고서 | 반기보고서 | 분기보고서 | 재무제표 | 감사보고서 | 주석 | 정정신고(보고) | 주요사항보고서 | 유상증자결정 | 대량보유보고서 | 임원·주요주주변동 | 자기주식 | 합병·분할 | 배당 | 기타공시",
"evidence": "요약 근거 핵심 문장 3개 이상 (반드시 한국어로 번역 인용)",
"financial_metrics": "주요 재무지표 종합",
"insight_vectors": "투자자 관점: 핵심 리스크와 기회",
"company_name": "회사명 (한글 법인명만)",
"disclosure_title": "공시명 (한글만)",
"document_type": {{"primary": "문서유형", "secondary": "세부유형"}},
"key_points": ["핵심 포인트 1", "핵심 포인트 2", "핵심 포인트 3"],
"risk_notes": ["리스크 1", "리스크 2"],
"key_changes": [],
"offering_terms": {{}},
"key_audit_matters": [],
"footnote_risks": []}}

[다시 강조] 모든 출력은 한국어만. 漢字/Chinese/Japanese 절대 금지. JSON만 출력."""

CHUNK_PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.
다음은 '{company}' 공시문서의 일부(파트 {ci}/{tc})입니다.
핵심 내용을 300~600자로 한국어 요약하세요.
재무 수치가 있으면 반드시 정확히 포함하세요.
반드시 한국어(한글)로만 작성. 중국어/일본어/영어 절대 금지.

[파트 {ci}/{tc}]
{chunk}

핵심 요약 (한국어만):"""

MERGE_PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.
다음은 하나의 공시문서를 여러 파트로 나누어 요약한 결과입니다.
이 부분 요약들을 통합하여 하나의 완전한 분석 JSON을 작성하세요.

[절대 규칙] 모든 필드는 한국어(한글+숫자)로만. 중국어/일본어/영어 절대 금지.

{partials}

[출력 JSON]
{{"summary": "전체 통합 요약 (500자 이상, 모든 파트의 재무 수치 포함)",
"category": "문서유형",
"evidence": "핵심 근거 문장 종합 (한국어만)",
"financial_metrics": "모든 파트의 재무지표 종합",
"insight_vectors": "투자자 관점 종합",
"company_name": "회사명 (한글만)",
"disclosure_title": "공시명 (한글만)",
"document_type": {{"primary": "유형", "secondary": ""}},
"key_points": ["핵심 포인트들"],
"risk_notes": ["리스크들"],
"key_changes": [],
"offering_terms": {{}},
"key_audit_matters": [],
"footnote_risks": []}}

[규칙] 한국어만, JSON만 출력. 漢字 절대 금지."""


# ── 유틸리티 ──────────────────────────────────────────────

def split_chunks(text, size=CHUNK_SIZE):
    """문단 기반 청크 분할"""
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
    """파일명에서 회사명 추출"""
    m = re.search(r'DART_P\d+_(.+?)_\d{13,14}', filename)
    return m.group(1) if m else "미확인"


def parse_json_safe(text):
    """JSON 로버스트 파싱"""
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
    """vLLM API 호출 (v3 복원: user 메시지만)"""
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
        except Exception:
            if attempt < max_retries - 1:
                await asyncio.sleep(3)
                continue
            return ""
    return ""


# ── 분석 파이프라인 ──────────────────────────────────────

def is_valid_result(result):
    """결과 유효성 검증"""
    if result.get("_error") or result.get("_parse_failed"):
        return False
    summary = result.get("summary", "")
    if not summary or len(summary) < 100 or summary in ("분석 실패", "응답 없음", "파싱 실패"):
        return False
    return True


async def analyze_doc(client, doc_id, filename, text):
    """단일 문서 분석 (단문: 단일 프롬프트 / 장문: 청크 분할)"""
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
    """전체 재분석 실행 (자동 resume 지원)"""
    completed_ids = set()
    all_results = []
    if os.path.exists(RESULT_FILE):
        try:
            with open(RESULT_FILE, "r", encoding="utf-8") as f:
                all_results = json.load(f)
            completed_ids = {r["doc_id"] for r in all_results}
            print(f"📋 이전 진행 복원: {len(completed_ids)}건 완료됨")
        except Exception:
            pass

    remaining = [d for d in docs if d["doc_id"] not in completed_ids]
    total = len(remaining)

    if total == 0:
        print("✅ 모든 문서 분석 완료!")
        return

    total_chars = sum(d["text_len"] for d in remaining)
    short = sum(1 for d in remaining if d["text_len"] <= CHUNK_THRESHOLD)

    print(f"\n{'═'*60}")
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

    async def _process(doc, retry_num=0):
        """문서 처리 (실패 시 최대 3회 재시도)"""
        async with doc_sem:
            doc_id = doc["doc_id"]
            filename = doc["filename"]
            text = doc["text"]
            t0 = time.time()

            try:
                result = await analyze_doc(client, doc_id, filename, text)
                result["_model"] = MODEL
                elapsed = time.time() - t0

                # 유효성 검증 — 실패 시 재시도
                if not is_valid_result(result) and retry_num < 3:
                    await asyncio.sleep(2 * (retry_num + 1))
                    return None  # 재시도 대상 표시

                all_results.append({
                    "doc_id": doc_id,
                    "filename": filename,
                    "result": result,
                })
                done_count[0] += 1

                is_error = not is_valid_result(result)
                if is_error:
                    error_count[0] += 1

                # 개별 문서 완료 로그 (첫 10건 + 이후 10건마다)
                if done_count[0] <= 10 or done_count[0] % 10 == 0 or done_count[0] == total:
                    elapsed_total = time.time() - start_time
                    rate = done_count[0] / (elapsed_total / 60) if elapsed_total > 0 else 0
                    eta = (total - done_count[0]) / rate if rate > 0 else 0
                    status = "❌" if is_error else "✅"
                    retry_tag = f" (재시도 {retry_num})" if retry_num > 0 else ""
                    print(
                        f"  {status} [{done_count[0]}/{total}] "
                        f"{filename[:30]}... {elapsed:.0f}초 "
                        f"| 총 {elapsed_total/60:.1f}분 "
                        f"| ETA: {eta:.0f}분 "
                        f"| {rate:.1f}건/분{retry_tag}"
                    )

                # 중간 저장 + Drive 백업
                if done_count[0] % SAVE_EVERY == 0:
                    with open(RESULT_FILE, "w", encoding="utf-8") as f:
                        json.dump(all_results, f, ensure_ascii=False, indent=1)
                    try:
                        backup_to_drive(RESULT_FILE)
                    except Exception:
                        pass

                return doc if is_error else None

            except Exception as e:
                if retry_num < 3:
                    return None  # 재시도 대상
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
                return doc

    async with httpx.AsyncClient() as client:
        # === 1차 처리 ===
        tasks = [_process(d) for d in remaining]
        results_1st = await asyncio.gather(*tasks)

        # === 실패분 자동 재처리 (최대 3라운드) ===
        for retry_round in range(1, 4):
            # 재시도 대상: _process가 None 또는 doc을 반환한 경우
            failed_ids = set()
            for r in all_results:
                if not is_valid_result(r.get("result", {})):
                    failed_ids.add(r["doc_id"])
            # 아직 처리 안 된 것도 포함
            processed_ids = {r["doc_id"] for r in all_results}
            retry_docs = [d for d in remaining if d["doc_id"] in failed_ids or d["doc_id"] not in processed_ids]

            if not retry_docs:
                print(f"\n  🎯 재시도 라운드 {retry_round}: 실패 0건 — 완벽 달성!")
                break

            print(f"\n  🔄 재시도 라운드 {retry_round}: {len(retry_docs)}건 재처리 중...")

            # 기존 실패 결과 제거
            all_results = [r for r in all_results if r["doc_id"] not in {d["doc_id"] for d in retry_docs}]
            done_count[0] = len(all_results)
            error_count[0] = sum(1 for r in all_results if not is_valid_result(r.get("result", {})))

            retry_tasks = [_process(d, retry_num=retry_round) for d in retry_docs]
            await asyncio.gather(*retry_tasks)

    # 최종 저장 + Drive 백업
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=1)
    try:
        backup_to_drive(RESULT_FILE)
        print(f"  📁 Google Drive 백업 완료")
    except Exception:
        pass

    elapsed = time.time() - start_time
    success = done_count[0] - error_count[0]

    print(f"\n{'═'*60}")
    print(f"  ✅ Phase 2 완료! {elapsed/60:.1f}분 소요")
    print(f"  성공: {success} | 오류: {error_count[0]} | 총: {done_count[0]}")
    print(f"  평균: {elapsed/max(done_count[0],1):.1f}초/문서")
    print(f"  결과 파일: {RESULT_FILE}")
    print(f"{'═'*60}")

await run_all()
print("\n🟢 Phase 2 완료 — Phase 3 실행하세요")


###############################################################
# Phase 3: QLoRA 학습 데이터 자동 생성 (~2분)
###############################################################

# %%
import json, re, random, os

print("=" * 60)
print("  Ω  Phase 3 — QLoRA 학습 데이터 생성")
print("=" * 60)

RESULT_FILE = "analysis_results.json"
TRAIN_FILE = "/content/dart_train.jsonl"
VALID_FILE = "/content/dart_valid.jsonl"
VALID_RATIO = 0.1

# ── llm_service.py 동일 시스템 프롬프트 ──────────────────

SYSTEM_PROMPT = """[ROLE] 당신은 한국 금융감독원 DART 전자공시시스템 문서를 분석하는 전문 AI 분석 아키텍트입니다.
당신의 임무는 공시문서를 정밀하게 읽고, 구조화된 JSON으로 분석 결과를 출력하는 것입니다.

[절대 규칙]
1. 출력은 반드시 JSON 단독. 인사말/설명/마크다운 절대 금지.
2. 문서에 없는 숫자를 절대 만들지 마라.
3. 모든 텍스트는 반드시 한국어(한글)로만 작성하라. 중국어/일본어 문자 사용 절대 금지.
4. 숫자는 원문 그대로 (단위 포함).
5. 불확실한 항목은 null 또는 "해당 없음".
6. 깨진 OCR 텍스트는 인용하지 말고 문맥으로 재구성.
7. company_name이 불확실하면 "미확인".
8. summary는 반드시 자연스러운 한국어 문장으로 작성.

[수치 밀도 기준]
- summary: 최소 8개 이상의 구체적 숫자 포함 필수.
- key_points: 각 포인트에 최소 1개 이상의 숫자 필수.
- 숫자 없는 추상적 문장 금지."""


# ── 문서유형 분류 키워드 ──────────────────────────────────

DOC_TYPE_KEYWORDS = {
    "정정신고(보고)": ["정정신고", "정정 전", "정정 후", "정정보고"],
    "주요사항보고서": ["주요사항보고서", "전환사채", "신주인수권부사채"],
    "유상증자결정": ["유상증자", "신주발행", "제3자배정"],
    "사업보고서": ["사업보고서", "사업의 내용", "임원 및 직원"],
    "반기보고서": ["반기보고서", "반기검토"],
    "분기보고서": ["분기보고서", "분기검토"],
    "재무제표": ["재무상태표", "손익계산서", "현금흐름표"],
    "감사보고서": ["감사보고서", "감사의견", "적정의견"],
    "대량보유보고서": ["대량보유", "5% 보고"],
    "임원·주요주주변동": ["임원변동", "주요주주", "특정증권등 소유"],
    "자기주식": ["자기주식", "자사주"],
    "합병·분할": ["합병", "분할", "영업양수도"],
    "배당": ["배당", "현금배당", "주식배당"],
}


def classify_from_text(text_snippet):
    """텍스트에서 문서유형 분류"""
    text_lower = text_snippet[:5000].lower()
    scores = {}
    for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[doc_type] = score
    if not scores:
        return "기타공시"
    return max(scores, key=scores.get)


# ── 결과 로드 + 필터링 ───────────────────────────────────

with open(RESULT_FILE, "r", encoding="utf-8") as f:
    all_results = json.load(f)

print(f"  전체 결과: {len(all_results)}건")

# 고품질 필터
valid_samples = []
skip_reasons = {"error": 0, "short_summary": 0, "no_json": 0}

for item in all_results:
    result = item["result"]

    # 오류 건 제외
    if result.get("_error") or result.get("_parse_failed"):
        skip_reasons["error"] += 1
        continue

    # summary 최소 길이
    summary = result.get("summary", "")
    if not summary or len(summary) < 300:
        skip_reasons["short_summary"] += 1
        continue

    # JSON 직렬화 가능한지 확인
    try:
        assistant_json = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        skip_reasons["no_json"] += 1
        continue

    valid_samples.append(item)

print(f"  유효 샘플: {len(valid_samples)}건")
print(f"  제외 사유: {skip_reasons}")

# ── v2 messages 포맷 변환 ────────────────────────────────

print("\n📝 v2 messages 포맷 변환 중...")

jsonl_samples = []
for item in valid_samples:
    filename = item["filename"]
    result = item["result"]
    doc_id = item["doc_id"]

    # 원본 텍스트에서 문서유형 추론
    category = result.get("category", "기타공시")
    company = result.get("company_name", "미확인")

    # user 프롬프트 구성
    user_content = (
        f"다음 DART 공시 문서를 분석하고 JSON으로만 응답하라.\n\n"
        f"[문서명]: {filename}\n"
        f"[문서유형]: {category}\n"
        f"[회사명]: {company}\n\n"
        f"[분석 지시]: 위 문서에 대한 구조화된 JSON 분석 결과를 출력하라."
    )

    # assistant 응답에서 내부 메타 키 제거
    clean_result = {k: v for k, v in result.items()
                    if not k.startswith("_")}
    assistant_content = json.dumps(clean_result, ensure_ascii=False)

    jsonl_samples.append({
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
    })

print(f"  총 학습 샘플: {len(jsonl_samples)}건")

# ── train/valid 분할 ─────────────────────────────────────

random.seed(42)
random.shuffle(jsonl_samples)
n_valid = max(1, int(len(jsonl_samples) * VALID_RATIO))
valid_data = jsonl_samples[:n_valid]
train_data = jsonl_samples[n_valid:]

# 저장
for data, path, label in [
    (train_data, TRAIN_FILE, "Train"),
    (valid_data, VALID_FILE, "Valid"),
]:
    with open(path, "w", encoding="utf-8") as f:
        for sample in data:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"  ✅ {label}: {path} ({len(data)}건, {size_mb:.1f}MB)")

print(f"\n{'═'*60}")
print(f"  ✅ Phase 3 완료!")
print(f"  Train: {len(train_data)}건 | Valid: {len(valid_data)}건")
print(f"{'═'*60}")
print("\n🟢 Phase 3 완료 — Phase 4 실행하세요")


###############################################################
# Phase 4: QLoRA 파인튜닝 (~40분)
###############################################################

# %%
import os, json, glob, subprocess, signal, time
import torch

print("=" * 60)
print("  Ω  Phase 4 — QLoRA 파인튜닝")
print("=" * 60)

# ── vLLM 서버 종료 (VRAM 확보) ────────────────────────────

print("🔄 vLLM 서버 종료 중 (VRAM 확보)...")
subprocess.run(["pkill", "-f", "vllm.entrypoints"], capture_output=True)
time.sleep(10)

# CUDA 캐시 정리
torch.cuda.empty_cache()
if hasattr(torch.cuda, 'reset_peak_memory_stats'):
    torch.cuda.reset_peak_memory_stats()

free_mem = torch.cuda.get_device_properties(0).total_mem - torch.cuda.memory_allocated(0)
print(f"  가용 VRAM: {free_mem / 1024**3:.1f} GB")

# ── 설정 ─────────────────────────────────────────────────

MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"
TRAIN_FILE = "/content/dart_train.jsonl"
VALID_FILE = "/content/dart_valid.jsonl"
OUTPUT_DIR = "/content/dart-qwen-lora-checkpoints"
SAVE_DIR = "/content/models/dart-qwen-lora-final"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(SAVE_DIR, exist_ok=True)

# GPU 감지
gpu_name = ""
try:
    gpu_name = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        text=True
    ).strip().upper()
except Exception:
    pass

IS_H100 = "H100" in gpu_name
BATCH_SIZE = 4 if IS_H100 else 2
GRAD_ACCUM = 4 if IS_H100 else 8
MAX_SEQ_LEN = 4096
MAX_STEPS = 2000
SAVE_STEPS = 500
COMPUTE_DTYPE = torch.bfloat16

print(f"  GPU: {gpu_name or '알 수 없음'}")
print(f"  배치: {BATCH_SIZE} × {GRAD_ACCUM} = {BATCH_SIZE * GRAD_ACCUM}")
print(f"  최대 시퀀스: {MAX_SEQ_LEN}")
print(f"  총 스텝: {MAX_STEPS}")

# flash_attention_2 감지
try:
    import flash_attn
    ATTN_IMPL = "flash_attention_2"
    print("  ✅ flash_attention_2 사용")
except ImportError:
    ATTN_IMPL = "sdpa"
    print("  ⚠️  flash_attn 없음 → sdpa 사용")

# ── 모델 로딩 ────────────────────────────────────────────

from transformers import (
    AutoTokenizer, AutoModelForCausalLM,
    BitsAndBytesConfig, TrainingArguments,
    Trainer, DataCollatorForSeq2Seq,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

print(f"\n📦 모델 로딩: {MODEL_ID}")

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=COMPUTE_DTYPE,
    bnb_4bit_use_double_quant=True,
)

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"

model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
    device_map="auto",
    attn_implementation=ATTN_IMPL,
)
model.config.use_cache = False
model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
print("✅ 베이스 모델 로딩 완료")

# ── LoRA 설정 ────────────────────────────────────────────

lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM",
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
)

model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

# ── 데이터셋 클래스 ──────────────────────────────────────

from torch.utils.data import Dataset

class DartDataset(Dataset):
    def __init__(self, jsonl_path, tokenizer, max_length=4096):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.samples = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.samples.append(json.loads(line))
        print(f"  📂 {os.path.basename(jsonl_path)}: {len(self.samples)}개 로드")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        messages = self.samples[idx]["messages"]

        full_text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
        no_asst = [m for m in messages if m["role"] != "assistant"]
        prefix_text = self.tokenizer.apply_chat_template(
            no_asst, tokenize=False, add_generation_prompt=True
        )

        full_ids = self.tokenizer(
            full_text, truncation=True, max_length=self.max_length,
            return_tensors="pt"
        )["input_ids"].squeeze(0)

        prefix_ids = self.tokenizer(
            prefix_text, truncation=True, max_length=self.max_length,
            return_tensors="pt"
        )["input_ids"].squeeze(0)

        attention_mask = torch.ones_like(full_ids)
        prefix_len = min(len(prefix_ids), len(full_ids))

        labels = full_ids.clone()
        labels[:prefix_len] = -100

        learn_tokens = (labels != -100).sum().item()
        if learn_tokens == 0:
            next_idx = (idx + 1) % len(self.samples)
            return self.__getitem__(next_idx)

        return {
            "input_ids": full_ids,
            "attention_mask": attention_mask,
            "labels": labels,
        }

# ── 데이터셋 로드 ────────────────────────────────────────

print("\n📂 데이터셋 로딩...")
train_dataset = DartDataset(TRAIN_FILE, tokenizer, max_length=MAX_SEQ_LEN)
valid_dataset = DartDataset(VALID_FILE, tokenizer, max_length=MAX_SEQ_LEN)

# ── 체크포인트 자동 감지 ─────────────────────────────────

def find_latest_checkpoint(output_dir):
    checkpoints = sorted(
        glob.glob(os.path.join(output_dir, "checkpoint-*")),
        key=lambda x: int(x.split("-")[-1])
    )
    return checkpoints[-1] if checkpoints else None

latest_ckpt = find_latest_checkpoint(OUTPUT_DIR)
if latest_ckpt:
    print(f"\n♻️  체크포인트 감지: {latest_ckpt} → 이어서 학습")

# ── 학습 설정 ────────────────────────────────────────────

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    per_device_train_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRAD_ACCUM,
    gradient_checkpointing=True,
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_steps=20,
    max_steps=MAX_STEPS,
    save_strategy="steps",
    save_steps=SAVE_STEPS,
    save_total_limit=3,
    eval_strategy="steps",
    eval_steps=SAVE_STEPS,
    bf16=True,
    fp16=False,
    tf32=True,
    optim="paged_adamw_8bit",
    logging_steps=10,
    report_to="none",
    dataloader_num_workers=4,
    remove_unused_columns=False,
    label_names=["labels"],
)

data_collator = DataCollatorForSeq2Seq(
    tokenizer=tokenizer,
    model=None,
    padding=True,
    pad_to_multiple_of=8,
    label_pad_token_id=-100,
)

# ── 학습 실행 ────────────────────────────────────────────

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=valid_dataset,
    data_collator=data_collator,
)

print(f"\n🚀 QLoRA 학습 시작! (GPU: {gpu_name or 'Unknown'})")
trainer.train(resume_from_checkpoint=latest_ckpt)
print("✅ 학습 완료!")

# ── LoRA 어댑터 저장 ─────────────────────────────────────

trainer.save_model(SAVE_DIR)
tokenizer.save_pretrained(SAVE_DIR)

print(f"\n{'═'*60}")
print(f"  ✅ Phase 4 완료!")
print(f"  LoRA 어댑터: {SAVE_DIR}")
print(f"{'═'*60}")
print("\n🟢 Phase 4 완료 — Phase 5 실행하세요")


###############################################################
# Phase 5: 결과 패키징 + 다운로드 (~3분)
###############################################################

# %%
import os, json, zipfile, shutil

print("=" * 60)
print("  Ω  Phase 5 — 결과 패키징 + 다운로드")
print("=" * 60)

RESULT_FILE = "analysis_results.json"
LORA_DIR = "/content/models/dart-qwen-lora-final"
TRAIN_FILE = "/content/dart_train.jsonl"
VALID_FILE = "/content/dart_valid.jsonl"

# ── 1. 분석 결과 통계 ────────────────────────────────────

with open(RESULT_FILE, "r", encoding="utf-8") as f:
    results = json.load(f)

total = len(results)
errors = sum(1 for r in results if r["result"].get("_error") or r["result"].get("_parse_failed"))
success = total - errors
parse_failed = sum(1 for r in results if r["result"].get("_parse_failed"))

# 카테고리 분포
cat_dist = {}
for r in results:
    cat = r["result"].get("category", "기타공시")
    cat_dist[cat] = cat_dist.get(cat, 0) + 1

print(f"\n📊 분석 결과 통계:")
print(f"  총: {total} | 성공: {success} | 오류: {errors} | 파싱실패: {parse_failed}")
print(f"  성공률: {success/total*100:.1f}%")
print(f"  파일 크기: {os.path.getsize(RESULT_FILE)/1024/1024:.1f} MB")
print(f"\n  카테고리 분포:")
for cat, cnt in sorted(cat_dist.items(), key=lambda x: -x[1])[:10]:
    print(f"    {cat}: {cnt}건")

# ── 2. LoRA 어댑터 ZIP ───────────────────────────────────

lora_zip = "/content/dart-qwen-lora-final.zip"
if os.path.isdir(LORA_DIR):
    print(f"\n📦 LoRA 어댑터 패키징: {LORA_DIR}")
    with zipfile.ZipFile(lora_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(LORA_DIR):
            for file in files:
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, os.path.dirname(LORA_DIR))
                zf.write(filepath, arcname)
    print(f"  ✅ {lora_zip} ({os.path.getsize(lora_zip)/1024/1024:.1f} MB)")
else:
    print(f"  ⚠️ LoRA 디렉토리 없음: {LORA_DIR}")
    lora_zip = None

# ── 3. 학습 데이터 ZIP ───────────────────────────────────

data_zip = "/content/dart_training_data.zip"
print(f"\n📦 학습 데이터 패키징...")
with zipfile.ZipFile(data_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
    for path in [TRAIN_FILE, VALID_FILE]:
        if os.path.exists(path):
            zf.write(path, os.path.basename(path))
print(f"  ✅ {data_zip} ({os.path.getsize(data_zip)/1024/1024:.1f} MB)")

# ── 4. 다운로드 ──────────────────────────────────────────

print(f"\n{'═'*60}")
print("  📥 다운로드 시작!")
print(f"{'═'*60}")

try:
    from google.colab import files

    # 분석 결과
    print("\n  1/3) analysis_results.json 다운로드 중...")
    files.download(RESULT_FILE)

    # LoRA 어댑터
    if lora_zip and os.path.exists(lora_zip):
        print("  2/3) dart-qwen-lora-final.zip 다운로드 중...")
        files.download(lora_zip)

    # 학습 데이터
    print("  3/3) dart_training_data.zip 다운로드 중...")
    files.download(data_zip)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  🎉 Omega CivicFlow — Colab H100 파이프라인 완료!        ║
║                                                          ║
║  다운로드 파일:                                           ║
║    1. analysis_results.json  → DB 임포트 + PDF 재생성     ║
║    2. dart-qwen-lora-final.zip → Ollama 모델 교체        ║
║    3. dart_training_data.zip → 학습 데이터 보존           ║
║                                                          ║
║  로컬 후속 작업:                                          ║
║    cd backend                                            ║
║    python ..\\tools\\import_colab_results.py               ║
╚══════════════════════════════════════════════════════════╝
""")

except ImportError:
    print("  ⚠️ Colab 환경이 아닙니다. 파일을 수동으로 복사하세요:")
    print(f"    - {RESULT_FILE}")
    if lora_zip:
        print(f"    - {lora_zip}")
    print(f"    - {data_zip}")
