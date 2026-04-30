# ═══════════════════════════════════════════════════════════════
# Omega CivicFlow — Colab A100 정석 LLM 재분석 스크립트
# 
# 코랩에서 실행:
# 1. 런타임 → 런타임 유형 변경 → GPU (A100)
# 2. 이 셀 전체 복사 후 실행
# 3. 완료 후 result JSONL을 다운로드
# 4. 로컬에서 inject_full.py 실행
# ═══════════════════════════════════════════════════════════════

# === Cell 1: Ollama 설치 + 모델 로드 ===
# 이전에 이미 올라마가 설치되어 있으면 이 셀 스킵 가능

!curl -fsSL https://ollama.com/install.sh | sh
import subprocess, time, threading

def run_ollama():
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

threading.Thread(target=run_ollama, daemon=True).start()
time.sleep(3)
!ollama pull qwen2.5-coder:7b
print("✅ Ollama + qwen2.5-coder:7b 준비 완료")


# === Cell 2: 정석 LLM 분석 실행 ===
import json, re, time, requests
from pathlib import Path

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "qwen2.5-coder:7b"

# ── 입력/출력 파일 ──
INPUT_JSONL = "/content/chatbot_training_data.jsonl"  # 기존 1차 추출 결과
OUTPUT_JSONL = "/content/omega_full_analysis.jsonl"    # 정석 분석 결과

# ══════════════════════════════════════════════════════
# 시스템 프롬프트 (로컬 llm_service.py와 동일)
# ══════════════════════════════════════════════════════
SYSTEM_PROMPT = """[ROLE] 당신은 한국 금융감독원 DART 전자공시시스템 문서를 분석하는 전문 AI 분석 아키텍트입니다.
당신의 임무는 공시문서를 정밀하게 읽고, 구조화된 JSON으로 분석 결과를 출력하는 것입니다.

[절대 규칙 — 위반 시 분석 실패로 간주]
1. 출력은 반드시 JSON 단독. 인사말/설명/마크다운 절대 금지.
2. 문서에 없는 숫자를 절대 만들지 마라.
3. ★★★ 최우선 규칙: 모든 텍스트는 반드시 한국어(한글)로만 작성하라. ★★★
   - 중국어(汉字/简体/繁体) 문자 사용 절대 금지. 단 한 글자도 허용하지 않는다.
   - 일본어(ひらがな/カタカナ) 문자 사용 절대 금지.
   - 영어는 고유명사나 약어(CEO, PER, ROE 등)에만 허용.
   - 이 규칙을 1건이라도 위반하면 전체 분석이 실패로 처리된다.
4. 숫자는 원문 그대로 (단위 포함: '1,234억원', '25,445주').
5. 불확실한 항목은 null 또는 "해당 없음".
6. 깨진 OCR 텍스트는 인용하지 말고 문맥으로 재구성.
7. company_name이 불확실하면 "미확인".
8. summary는 반드시 자연스러운 한국어 문장으로 작성."""

# ══════════════════════════════════════════════════════
# 문서유형 분류 키워드
# ══════════════════════════════════════════════════════
DOC_TYPE_KEYWORDS = {
    "정정신고(보고)": ["정정신고", "정정 전", "정정 후", "정정보고", "기재정정"],
    "주요사항보고서": ["주요사항보고서", "주요경영사항", "전환사채", "신주인수권부사채"],
    "유상증자결정": ["유상증자", "신주발행", "제3자배정", "증자결정"],
    "사업보고서": ["사업보고서", "사업의 내용", "임원 및 직원", "회사의 개요"],
    "반기보고서": ["반기보고서", "반기검토", "반기재무"],
    "분기보고서": ["분기보고서", "분기검토", "분기재무"],
    "재무제표": ["재무상태표", "손익계산서", "포괄손익계산서", "현금흐름표", "자본변동표", "연결재무제표"],
    "감사보고서": ["감사보고서", "감사의견", "적정의견"],
    "대량보유보고서": ["대량보유", "주식등의 대량보유", "5% 보고"],
    "임원·주요주주변동": ["임원변동", "주요주주", "특정증권등 소유"],
    "자기주식": ["자기주식", "자사주", "자기주식처분", "자기주식취득"],
    "배당": ["배당", "현금배당", "주식배당", "배당금"],
}

def classify_doc_type(text):
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

def extract_company_name(text):
    patterns = [
        r'회사명\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
        r'법인명\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
        r'상호\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
        r'발행회사\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
        r'제출인\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
        r'주식회사\s+(.+?)(?:\s*[\(\[]|\s{2,}|\n|$)',
        r'㈜\s*(.+?)(?:\s{2,}|\n|$)',
        r'\(주\)\s*(.+?)(?:\s{2,}|\n|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text[:3000])
        if match:
            candidate = match.group(1).strip()[:50]
            if len(candidate) >= 2 and re.search(r'[가-힣a-zA-Z]', candidate):
                return candidate
    return "미확인"

# ══════════════════════════════════════════════════════
# 유형별 프롬프트 선택
# ══════════════════════════════════════════════════════
def build_analysis_prompt(text, doc_type, doc_secondary, company_name):
    focused = text[:14000]

    financial_types = {"재무제표", "사업보고서", "감사보고서", "반기보고서", "분기보고서", "주석"}
    event_types = {"정정신고(보고)", "유상증자결정", "주요사항보고서", "합병·분할", "자기주식"}

    if doc_type in financial_types:
        return f"""당신은 한국 DART 재무제표를 분석하는 전문가입니다.

[문서 텍스트]
{focused}

[출력 규칙] 반드시 아래 JSON만 출력. 숫자를 절대 생략하지 마라.
{{"document_type": {{"primary": "{doc_type}", "secondary": "{doc_secondary}"}},
"company_name": "{company_name}",
"disclosure_title": "공시 제목",
"summary": "최소 10문장. 모든 재무수치(매출액, 영업이익, 당기순이익, 자산총계, 부채총계, 자본총계 등) 포함 필수.",
"category": "{doc_type}",
"key_points": ["핵심 사실 5개 이상 — 각 포인트에 구체적 숫자 필수"],
"financial_metrics": {{"assets_total": "자산총계 (원문 그대로)", "liabilities_total": "부채총계", "equity_total": "자본총계", "revenue": "매출액", "operating_income": "영업이익", "net_income": "당기순이익", "debt_ratio": "부채비율", "operating_margin": "영업이익률"}},
"insight_vectors": "투자 시사점 (구체적 수치 근거 포함)",
"risk_notes": ["리스크 사항"],
"evidence": "핵심 근거 문장 3개 이상 원문 인용"}}"""

    elif doc_type in event_types:
        return f"""당신은 한국 공시 이벤트 분석 전문가입니다.

[문서 텍스트]
{focused}

[출력 규칙] 반드시 아래 JSON만 출력.
{{"document_type": {{"primary": "{doc_type}", "secondary": "{doc_secondary}"}},
"company_name": "{company_name}",
"disclosure_title": "공시 제목",
"summary": "최소 7문장. 정정 전/후, 발행조건, 자금용도 등 구체적 숫자 포함.",
"category": "{doc_type}",
"event_type": "정정신고/유상증자/주요사항 등",
"key_points": ["핵심 사실 5개 이상"],
"key_changes": [{{"field": "변경항목", "before": "정정 전", "after": "정정 후", "delta": "변동분", "impact": "영향도"}}],
"financial_metrics": "해당 없음",
"insight_vectors": "투자자 관점 영향 평가",
"risk_notes": ["리스크"],
"evidence": "핵심 근거 문장 3개 이상"}}"""

    else:
        return f"""당신은 한국 DART 공시문서를 분석하는 금융 전문가입니다.

[문서 텍스트]
{focused}

[출력 규칙] 반드시 JSON만 출력. 숫자를 생략하면 분석 실패.
{{"document_type": {{"primary": "{doc_type}", "secondary": "{doc_secondary}"}},
"company_name": "{company_name}",
"disclosure_title": "공시 제목",
"summary": "최소 10문장. 모든 주요 숫자 포함.",
"category": "{doc_type}",
"key_points": ["핵심 사실 5개 이상"],
"financial_metrics": "발행주식수, 지분율, 금액 등 모든 재무 수치",
"insight_vectors": "투자 시사점",
"risk_notes": ["리스크"],
"evidence": "핵심 근거 문장 3개 이상"}}"""


# ══════════════════════════════════════════════════════
# 중국어 방어 후처리
# ══════════════════════════════════════════════════════
CJK_DICT = {
    "营业": "영업", "利润": "이익", "收入": "수입", "资产": "자산",
    "负债": "부채", "净利润": "순이익", "增长": "증가", "下降": "하락",
    "股东": "주주", "报告": "보고서", "公司": "회사", "投资": "투자",
    "分析": "분석", "财务": "재무", "经营": "경영", "管理": "관리",
    "市场": "시장", "风险": "위험", "因此": "따라서", "但是": "그러나",
    "然而": "그러나", "同时": "동시에", "由于": "인해", "根据": "근거",
    "目前": "현재", "预计": "예상", "表明": "나타내", "显示": "표시",
}

def clean_cjk(text):
    if not text or not isinstance(text, str):
        return text
    for cn, kr in CJK_DICT.items():
        text = text.replace(cn, kr)
    # 남은 중국어 한자 제거
    text = re.sub(r'[\u4e00-\u9fff]+', '', text)
    # 일본어 제거
    text = re.sub(r'[\u3040-\u309f\u30a0-\u30ff]+', '', text)
    return text.strip()

def clean_result(result):
    for key in ["summary", "evidence", "insight_vectors"]:
        if key in result and isinstance(result[key], str):
            result[key] = clean_cjk(result[key])
    if "key_points" in result and isinstance(result["key_points"], list):
        result["key_points"] = [clean_cjk(p) if isinstance(p, str) else p for p in result["key_points"]]
    if "risk_notes" in result and isinstance(result["risk_notes"], list):
        result["risk_notes"] = [clean_cjk(r) if isinstance(r, str) else r for r in result["risk_notes"]]
    return result


# ══════════════════════════════════════════════════════
# Ollama 호출
# ══════════════════════════════════════════════════════
def call_ollama(prompt, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL,
                    "prompt": prompt,
                    "system": SYSTEM_PROMPT,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 4096},
                },
                timeout=300,
            )
            if resp.status_code == 200:
                return resp.json().get("response", "")
        except Exception as e:
            if attempt < retries:
                time.sleep(2)
            else:
                raise e
    return ""

def parse_json_response(text):
    # JSON 추출
    text = text.strip()
    # ```json ... ``` 블록 제거
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        text = m.group(1).strip()
    # { ... } 추출
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        json_str = text[start:end+1]
        try:
            return json.loads(json_str)
        except:
            # 흔한 JSON 오류 수정 시도
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            try:
                return json.loads(json_str)
            except:
                pass
    return {}


# ══════════════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════════════
print("📂 JSONL 로드 중...")
entries = []
with open(INPUT_JSONL, 'r', encoding='utf-8') as f:
    for line in f:
        if line.strip():
            entries.append(json.loads(line))
print(f"   총 {len(entries)}건")

print(f"\n🔬 LLM 정석 분석 시작 (모델: {MODEL})")
print("=" * 60)

results = []
success = 0
failed = 0
start_time = time.time()

with open(OUTPUT_JSONL, 'w', encoding='utf-8') as out:
    for idx, entry in enumerate(entries):
        fname = entry.get("file_name", f"unknown_{idx}")
        raw_text = entry.get("raw_text", "")

        if not raw_text or len(raw_text.strip()) < 50:
            failed += 1
            continue

        try:
            # 1. 문서유형 분류
            doc_type, doc_secondary = classify_doc_type(raw_text)
            company_name = extract_company_name(raw_text)

            # 2. 프롬프트 생성 + LLM 호출
            prompt = build_analysis_prompt(raw_text, doc_type, doc_secondary, company_name)
            t0 = time.time()
            response = call_ollama(prompt)
            proc_time = time.time() - t0

            # 3. JSON 파싱
            parsed = parse_json_response(response)
            if not parsed:
                parsed = {"summary": raw_text[:500], "category": doc_type}

            # 4. 중국어 후처리
            parsed = clean_result(parsed)

            # 5. 필수 필드 보장
            parsed.setdefault("company_name", company_name)
            parsed.setdefault("category", doc_type)
            parsed.setdefault("document_type", {"primary": doc_type, "secondary": doc_secondary})
            parsed.setdefault("summary", "")
            parsed.setdefault("financial_metrics", "해당 없음")
            parsed.setdefault("insight_vectors", "")
            parsed.setdefault("evidence", "")
            parsed.setdefault("key_points", [])
            parsed.setdefault("risk_notes", [])

            # financial_metrics가 dict면 문자열로 변환
            fm = parsed.get("financial_metrics", "")
            if isinstance(fm, dict):
                parts = []
                labels = {
                    "assets_total": "자산총계", "liabilities_total": "부채총계",
                    "equity_total": "자본총계", "revenue": "매출액",
                    "operating_income": "영업이익", "net_income": "당기순이익",
                    "debt_ratio": "부채비율", "operating_margin": "영업이익률",
                    "operating_cash_flow": "영업활동현금흐름", "cash_end": "기말현금",
                }
                for k, v in fm.items():
                    if v and v != "null" and v != "해당 없음" and v is not None:
                        label = labels.get(k, k)
                        parts.append(f"{label}: {v}")
                parsed["financial_metrics"] = " | ".join(parts) if parts else "해당 없음"

            # 6. 출력 JSONL 기록
            output_record = {
                "file_name": fname,
                "raw_text": raw_text,
                "raw_response": parsed,
                "summary": parsed.get("summary", ""),
                "category": parsed.get("category", doc_type),
                "company_name": parsed.get("company_name", company_name),
                "financial_metrics": parsed.get("financial_metrics", ""),
                "insight_vectors": parsed.get("insight_vectors", ""),
                "evidence": parsed.get("evidence", ""),
                "processing_time": proc_time,
            }
            out.write(json.dumps(output_record, ensure_ascii=False) + "\n")
            out.flush()

            success += 1
            elapsed = time.time() - start_time
            avg = elapsed / max(success, 1)
            remaining = avg * (len(entries) - idx - 1)

            if success % 50 == 0 or success <= 3:
                print(
                    f"   ├─ [{success}/{len(entries)}] {fname} | "
                    f"{parsed.get('company_name','?')} | {doc_type} | "
                    f"{proc_time:.1f}s | 남은: {remaining/60:.0f}분"
                )

        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"   ❌ {fname}: {str(e)[:80]}")

elapsed_total = time.time() - start_time
print("=" * 60)
print(f"🎉 완료! 성공: {success} / 실패: {failed}")
print(f"⏱️ 소요: {elapsed_total/60:.1f}분 ({elapsed_total/3600:.1f}시간)")
print(f"📦 결과: {OUTPUT_JSONL}")

# === Cell 3: 다운로드 ===
from google.colab import files
files.download(OUTPUT_JSONL)
