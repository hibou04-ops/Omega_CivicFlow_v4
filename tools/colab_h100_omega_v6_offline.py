###############################################################
# ═══════════════════════════════════════════════════════════
#  Omega CivicFlow — Colab H100 vLLM 오프라인 일괄 처리 (v6)
# ═══════════════════════════════════════════════════════════
#  HTTP 서버 타임아웃/병목 문제를 원천 차단하고 H100의 
#  LLM 네이티브 스피드를 100% 끌어내는 초고속 배치 스크립트.
###############################################################

# %%
import subprocess, sys

print("=" * 60)
print("  Ω  Phase 0 — 환경 설치 (vLLM 오프라인 엔진)")
print("=" * 60)

subprocess.run([
    sys.executable, "-m", "pip", "install", "-q",
    "vllm", "transformers", "accelerate"
], check=True)

# %%
import json, re, time, os
from vllm import LLM, SamplingParams

print("=" * 60)
print("  Ω  Phase 1 — 데이터 로드 및 초기화")
print("=" * 60)

MODEL = "Qwen/Qwen2.5-7B-Instruct-AWQ"
CHUNK_THRESHOLD = 14000
CHUNK_SIZE = 12000
RESULT_FILE = "analysis_results.json"
INPUT_FILE = "pending_docs_all.json"

# ── 데이터 로드 ──────────────────────────────────────────

# 이전 결과 불러와서 이미 완료된 것 안전 보존 (사용자 요청 사항)
completed_ids = set()
all_results = []
if os.path.exists(RESULT_FILE):
    try:
        with open(RESULT_FILE, "r", encoding="utf-8") as f:
            all_results = json.load(f)
        completed_ids = {r["doc_id"] for r in all_results}
        print(f"📋 이전 스크립트에서 완료된 결과 보존: {len(completed_ids)}건")
    except Exception as e:
        print(f"⚠️ 기존 결과 파일 파싱 실패: {e}")

docs = []
if os.path.exists("pending_docs_all.json"):
    INPUT_FILE = "pending_docs_all.json"
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        docs = json.load(f)
elif os.path.exists("pending_docs.jsonl"):
    INPUT_FILE = "pending_docs.jsonl"
    for enc in ["utf-8", "cp949", "latin-1"]:
        try:
            with open(INPUT_FILE, "r", encoding=enc) as f:
                f.readline()
            print(f"  📄 JSONL 인코딩 자동 탐지: {enc}")
            with open(INPUT_FILE, "r", encoding=enc, errors="replace") as f2:
                for line in f2:
                    line = line.strip().lstrip("\ufeff")
                    if line:
                        docs.append(json.loads(line))
            break
        except Exception:
            continue
else:
    raise FileNotFoundError("입력 파일(pending_docs_all.json)이 없습니다.")

remaining_docs = [d for d in docs if d["doc_id"] not in completed_ids]

if not remaining_docs:
    print("✅ 모든 문서 분석이 완료되어 있습니다!")
    sys.exit(0)

print(f"🚀 오프라인 배치 처리 대상 문서: {len(remaining_docs)}건")

# ── 프롬프트 설정 ────────────────────────────────────────
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

def split_chunks(text, size=CHUNK_SIZE):
    paras = re.split(r'\n\s*\n', text)
    chunks, cur, clen = [], [], 0
    for p in paras:
        p = p.strip()
        if not p: continue
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
    if not text or not text.strip(): return {"summary": "응답 없음"}
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
        f = text.replace('\r\n', '\\n').replace('\n', '\\n').replace('\t', '\\t')
        f = re.sub(r',\s*}', '}', f)
        f = re.sub(r',\s*]', ']', f)
        return json.loads(f)
    except: pass
    return {"summary": text[:2000], "_parse_failed": True}

def is_valid_result(result):
    if result.get("_error") or result.get("_parse_failed"): return False
    summary = result.get("summary", "")
    if not summary or len(summary) < 100: return False
    return True

# %%
print("\n" + "=" * 60)
print("  Ω  Phase 2 — vLLM 메인 엔진 구동 (VRAM 95% 사용)")
print("=" * 60)

# 이 엔진이 로드되면서 GPU 메모리를 싹 잡아먹고 초고속 생성 준비를 합니다.
llm = LLM(
    model=MODEL,
    tensor_parallel_size=1,
    gpu_memory_utilization=0.95, 
    quantization="awq",
    trust_remote_code=True
)
sampling_params = SamplingParams(
    temperature=0.1,
    top_p=0.9,
    repetition_penalty=1.05,
    max_tokens=2048
)

MAX_ROUNDS = 3

for round_idx in range(MAX_ROUNDS + 1):
    round_docs = [d for d in remaining_docs if d["doc_id"] not in completed_ids]
    if not round_docs:
        print("✅ 모든 미처리 문서 완료됨!")
        break
        
    print(f"\n[{'='*50}]")
    print(f" 🟢 실행 라운드 {round_idx} / 잔여 문서: {len(round_docs)}건 (가로/세로 전체 썰기 모드)")
    print(f"[{'='*50}]")
    
    # ── 1단계: 전체 텍스트 CPU 청킹 및 선형 프롬프트 구조화 ──
    prompts_A = []
    mapping_A = []  # (doc_idx, is_short, chunk_idx, total_chunks)
    
    t_chunk = time.time()
    for idx, doc in enumerate(round_docs):
        text = doc["text"]
        company = extract_company(doc["filename"])
        if len(text) <= CHUNK_THRESHOLD:
            # 하나짜리는 바로 JSON 생성 프롬프트
            # 메시지 템플릿 우회 (Qwen-Instruct 용 수동 포맷)
            p = f"<|im_start|>user\n{ANALYSIS_PROMPT.format(text=text[:14000])}<|im_end|>\n<|im_start|>assistant\n"
            prompts_A.append(p)
            mapping_A.append((idx, True, -1, 1))
        else:
            # 긴 문서 가로/세로 썰기
            chunks = split_chunks(text, CHUNK_SIZE)
            tc = len(chunks)
            for ci, c in enumerate(chunks):
                p = f"<|im_start|>user\n{CHUNK_PROMPT.format(company=company, ci=ci+1, tc=tc, chunk=c)}<|im_end|>\n<|im_start|>assistant\n"
                prompts_A.append(p)
                mapping_A.append((idx, False, ci, tc))
                
    print(f"  [CPU] 전체 프롬프트 분할 완료: 총 {len(prompts_A)} 조각 ({(time.time()-t_chunk):.2f}초 마킹)")
    
    # ── 2단계: GPU 네이티브 한방 처리 (HTTP 통신 파이프라인 우회) ──
    t_gen_A = time.time()
    outputs_A = llm.generate(prompts_A, sampling_params)
    print(f"  [vLLM] 스텝 1 (청크 추론) 전면 완료! / 소요 시간: {(time.time()-t_gen_A)/60:.1f}분")
    
    # 처리 결과 취합을 위한 버퍼 메모리
    doc_buffers = {idx: {"is_short": False, "chunks": {}, "result": None} for idx in range(len(round_docs))}
    
    for (idx, is_short, chunk_idx, tc), out in zip(mapping_A, outputs_A):
        text_out = out.outputs[0].text.strip()
        doc_buffers[idx]["is_short"] = is_short
        if is_short:
            doc_buffers[idx]["result"] = text_out
        else:
            doc_buffers[idx]["chunks"][chunk_idx] = text_out
            doc_buffers[idx]["tc"] = tc
            
    # ── 3단계: 장문 문서 병합(Merge) 프롬프트 구조화 ──
    prompts_B = []
    mapping_B = []
    
    for idx, buf in doc_buffers.items():
        if not buf["is_short"] and buf["chunks"]:
            tc = buf["tc"]
            partials = []
            for ci in range(tc):
                r = buf["chunks"].get(ci, "")
                if r: partials.append(f"[파트 {ci+1}/{tc}]\n{r}")
            merged = "\n\n".join(partials)
            if len(merged) > 14000: merged = merged[:14000]
            
            p = f"<|im_start|>user\n{MERGE_PROMPT.format(partials=merged)}<|im_end|>\n<|im_start|>assistant\n"
            prompts_B.append(p)
            mapping_B.append(idx)
            
    if prompts_B:
        print(f"  [CPU] 복원된 조각의 병합 프롬프트 구성 완료: {len(prompts_B)}건")
        t_gen_B = time.time()
        outputs_B = llm.generate(prompts_B, sampling_params)
        print(f"  [vLLM] 스텝 2 (병합 추론) 전면 완료! / 소요 시간: {(time.time()-t_gen_B)/60:.1f}분")
        
        for idx, out in zip(mapping_B, outputs_B):
            doc_buffers[idx]["result"] = out.outputs[0].text.strip()
            
    # ── 4단계: 검증 및 저장 ──
    success_count = 0
    for idx, doc in enumerate(round_docs):
        res_text = doc_buffers[idx].get("result")
        if not res_text:
            continue
            
        parsed = parse_json_safe(res_text)
        company = extract_company(doc["filename"])
        parsed["company_name"] = parsed.get("company_name", company)
        parsed["_model"] = MODEL
        
        if is_valid_result(parsed):
            all_results.append({
                "doc_id": doc["doc_id"],
                "filename": doc["filename"],
                "result": parsed
            })
            completed_ids.add(doc["doc_id"])
            success_count += 1
            
    print(f"  ✓ 결산: 이번 라운드 {success_count}/{len(round_docs)} 개 통과 (오류문서 재시도 큐 이관)")
    
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=1)
    print(f"  💾 물리적 중간 저장 완료: {RESULT_FILE} (+{success_count}건 합산)")
    
print("\n🎉 모든 오프라인 일괄 처리가 끝났습니다!")
