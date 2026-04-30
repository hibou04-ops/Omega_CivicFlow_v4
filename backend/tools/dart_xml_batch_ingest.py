"""
═══════════════════════════════════════════════════════════════
Omega CivicFlow — DART XML 이중압축 배치 인제스트
   (로컬 + RunPod H200 병렬 분산 처리 지원)
═══════════════════════════════════════════════════════════════

DataSet_Cleaned.zip (외부) → DART_P0_회사명_날짜.zip (내부) → *.xml

처리 파이프라인:
  1. 외부 zip → 내부 zip 순회 (샤딩으로 분산 가능)
  2. 내부 zip → 메인 XML 추출 (접수번호.xml — 숫자만인 파일명)
  3. XML 태그 제거 → 순수 텍스트 추출 (DART 4.0 구조 파싱)
  4. Gemini 비동기 분석 (14K+ 자동 청킹 포함)
  5. [로컬 모드] SQLite 저장 + Chroma 인덱싱 + PDF 생성
     [RunPod 모드] JSONL 파일 출력 → 나중에 rag_injector.py로 로컬 주입

━━━ 로컬 단독 실행 ━━━
  python tools/dart_xml_batch_ingest.py --zip DataSet_Cleaned.zip
  python tools/dart_xml_batch_ingest.py --zip DataSet_Cleaned.zip --resume
  python tools/dart_xml_batch_ingest.py --zip DataSet_Cleaned.zip --limit 50  # 테스트

━━━ 로컬 + RunPod 병렬 분산 (샤드 2분할) ━━━
  # 로컬 Windows (샤드 0)
  python tools/dart_xml_batch_ingest.py --zip DataSet_Cleaned.zip --shard-id 0 --total-shards 2

  # RunPod H200 (샤드 1) — JSONL 출력 모드
  python dart_xml_batch_ingest.py --zip DataSet_Cleaned.zip \\
      --shard-id 1 --total-shards 2 \\
      --output-jsonl /workspace/results_shard1.jsonl \\
      --skip-chroma --workers 8

  # RunPod 완료 후 로컬에서 JSONL 주입
  python backend/scripts/rag_injector.py /path/to/results_shard1.jsonl

━━━ 전체 옵션 ━━━
  --shard-id N      이 머신의 샤드 번호 (0부터 시작, 기본: 0)
  --total-shards N  전체 머신 수 (기본: 1 = 분산 없음)
  --output-jsonl P  결과를 JSONL 파일로 저장 (RunPod 모드, SQLite/Chroma 스킵)
  --workers N       동시 Gemini 호출 수 (기본: 3, RunPod: 8~12 권장)
  --limit N         처음 N개만 처리 (테스트용)
  --resume          이전 진행 상태에서 재개
  --skip-gemini     Gemini 분석 건너뜀 (텍스트 주입만)
  --skip-chroma     Chroma 인덱싱 건너뜀
"""

import sys
import os
import re
import json
import time
import gc
import asyncio
import hashlib
import argparse
import traceback
import zipfile
import io
from datetime import datetime

try:
    import aiohttp
    _AIOHTTP_OK = True
except ImportError:
    _AIOHTTP_OK = False
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from google import genai
from google.genai import types
from google.oauth2 import service_account

# ── 로컬 전용 import (RunPod --output-jsonl 모드에서는 불필요) ──
_LOCAL_IMPORTS_OK = False
try:
    from database import SessionLocal
    from models.models import Document, AnalysisResult, OcrText, DocumentMetadata, DocumentChunk
    from services.pdf_report_service import generate_pdf_report
    from config import settings
    _LOCAL_IMPORTS_OK = True
except ImportError:
    # RunPod 환경: config 없어도 동작 (--output-jsonl 모드 전용)
    settings = None

# ── 설정 (config 없으면 환경변수 폴백) ──
VERTEX_KEY_PATH = getattr(settings, 'GCP_KEY_PATH', os.environ.get('GCP_KEY_PATH', ''))
VERTEX_PROJECT  = getattr(settings, 'GCP_PROJECT_ID', os.environ.get('GCP_PROJECT_ID', ''))
VERTEX_LOCATION = getattr(settings, 'GCP_LOCATION', os.environ.get('GCP_LOCATION', 'us-central1'))

# Gemini API 키 목록
# 환경변수 GEMINI_API_KEYS (콤마 구분) 에서 로드. 하드코딩 금지.
_HARDCODED_KEYS: list[str] = []

def _load_api_keys(extra_keys: list = None) -> list:
    """환경변수 > 하드코딩 순으로 키 목록 로드"""
    keys = []
    # 환경변수에서 로드 (콤마/줄바꿈 구분)
    env_keys = os.environ.get("GEMINI_API_KEYS", "")
    if env_keys:
        keys = [k.strip() for k in re.split(r'[,\n]', env_keys) if k.strip()]
    if not keys:
        keys = [k for k in _HARDCODED_KEYS if k]
    # CLI로 추가된 키 병합
    if extra_keys:
        for k in extra_keys:
            if k and k not in keys:
                keys.append(k)
    return keys

GEMINI_MODEL = "gemini-2.5-flash"
CHUNK_THRESHOLD = 14000
CHUNK_SIZE = 12000
# AI Studio billing 활성화 계정: 1000 RPM / 키
# 무료 계정일 경우 --rpm 10 옵션으로 실행
MAX_RPM_PER_KEY = 1000
MAX_CONCURRENT = 20
PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".dart_ingest_progress.json")

# ── Gemini 키 Rate Limiter ──
class KeyRateLimiter:
    def __init__(self, key_name: str, max_rpm: int = 10):
        self.key_name = key_name
        self.max_rpm = max_rpm
        self.requests = []
        self.backoff_until = 0
        self.consecutive_429 = 0
        self.total_calls = 0
        self.total_errors = 0
        self.lock = asyncio.Lock()

    async def _prune(self):
        now = time.time()
        self.requests = [t for t in self.requests if t > now - 60]

    async def is_available(self) -> bool:
        async with self.lock:
            now = time.time()
            if now < self.backoff_until:
                return False
            await self._prune()
            return len(self.requests) < self.max_rpm

    async def wait_time(self) -> float:
        async with self.lock:
            now = time.time()
            if now < self.backoff_until:
                return self.backoff_until - now
            await self._prune()
            if len(self.requests) >= self.max_rpm:
                oldest = min(self.requests)
                return 60 - (now - oldest) + 1
            return 0

    async def record_success(self):
        async with self.lock:
            self.requests.append(time.time())
            self.total_calls += 1
            self.consecutive_429 = 0

    async def record_429(self):
        async with self.lock:
            self.consecutive_429 += 1
            self.total_errors += 1
            backoff = min(30 * (2 ** (self.consecutive_429 - 1)), 300)
            self.backoff_until = time.time() + backoff
            print(f"    ⚠️ [{self.key_name}] 429! 백오프 {backoff}초")
            return backoff


class GeminiClientPool:
    def __init__(self):
        self.clients = []
        self.next_idx = 0
        self.lock = asyncio.Lock()

    def add_api_key_client(self, api_key, name="", rpm: int = MAX_RPM_PER_KEY):
        try:
            client = genai.Client(api_key=api_key)
            limiter = KeyRateLimiter(f"api_{name or api_key[:8]}", rpm)
            self.clients.append((client, limiter, "api"))
            print(f"  ✅ API 키: {name or api_key[:8]}... ({rpm} RPM)")
        except Exception as e:
            print(f"  ❌ API 키 실패: {e}")

    async def get_next_client(self):
        if not self.clients:
            raise RuntimeError("사용 가능한 클라이언트 없음")
        while True:
            async with self.lock:
                for _ in range(len(self.clients)):
                    idx = self.next_idx % len(self.clients)
                    self.next_idx += 1
                    client, limiter, _ = self.clients[idx]
                    if await limiter.is_available():
                        return client, limiter
                min_wait = float('inf')
                best_idx = 0
                for i, (_, limiter, _) in enumerate(self.clients):
                    w = await limiter.wait_time()
                    if w < min_wait:
                        min_wait = w
                        best_idx = i
                _, best_limiter, _ = self.clients[best_idx]
            if min_wait > 0:
                print(f"  ⏳ 모든 키 한도 도달. {min_wait:.0f}초 대기... ({best_limiter.key_name})")
                await asyncio.sleep(min_wait + 0.1)

    def stats(self) -> str:
        parts = []
        for _, limiter, _ in self.clients:
            parts.append(f"{limiter.key_name}: {limiter.total_calls}건/{limiter.total_errors}err")
        return " | ".join(parts)


# ── XML → 텍스트 추출 ──
_DART_TAG_PATTERN = re.compile(r'<[^>]+>', re.DOTALL)
_WHITESPACE_PATTERN = re.compile(r'\s+')
_EXTRACT_COMPANY = re.compile(r'<COMPANY-NAME[^>]*AREGCIK="([^"]*)"[^>]*>([^<]+)</COMPANY-NAME>', re.IGNORECASE)
_EXTRACT_DOC_NAME = re.compile(r'<DOCUMENT-NAME[^>]*ACODE="([^"]*)"[^>]*>([^<]+)</DOCUMENT-NAME>', re.IGNORECASE)
_EXTRACT_PERIOD = re.compile(r'AUNIT(?:VALUE)?="(\d{8})"', re.IGNORECASE)


def extract_dart_xml_text(xml_bytes: bytes) -> tuple[str, dict]:
    """
    DART XML에서 순수 텍스트 + 메타데이터 추출.
    반환: (text, meta_dict)
    meta_dict: company_name, corp_code, doc_type, filing_date 등
    """
    try:
        # 인코딩 감지 (utf-8 → euc-kr 폴백)
        for enc in ("utf-8", "euc-kr", "cp949", "utf-16"):
            try:
                xml_str = xml_bytes.decode(enc, errors="replace")
                break
            except Exception:
                continue
        else:
            xml_str = xml_bytes.decode("utf-8", errors="replace")
    except Exception:
        xml_str = xml_bytes.decode("utf-8", errors="replace")

    meta = {
        "company_name": "",
        "corp_code": "",
        "doc_type": "",
        "acode": "",
        "period_from": "",
        "period_to": "",
    }

    # 회사명 + corp_code
    m = _EXTRACT_COMPANY.search(xml_str[:5000])
    if m:
        meta["corp_code"] = m.group(1).strip()
        meta["company_name"] = m.group(2).strip()[:100]

    # 문서 유형
    m = _EXTRACT_DOC_NAME.search(xml_str[:5000])
    if m:
        meta["acode"] = m.group(1).strip()
        meta["doc_type"] = m.group(2).strip()[:100]

    # 기간
    periods = _EXTRACT_PERIOD.findall(xml_str[:10000])
    if len(periods) >= 2:
        meta["period_from"] = periods[0]
        meta["period_to"] = periods[1]
    elif len(periods) == 1:
        meta["period_to"] = periods[0]

    # 태그 제거 → 텍스트
    text = _DART_TAG_PATTERN.sub(" ", xml_str)
    text = _WHITESPACE_PATTERN.sub(" ", text).strip()

    # 너무 짧은 노이즈 제거
    lines = [line.strip() for line in text.split(" ") if len(line.strip()) > 1]
    clean_text = " ".join(lines)

    return clean_text, meta


def parse_filename_meta(outer_filename: str) -> dict:
    """
    DART_P0_DB손해보험_20240314001788.zip 형태에서 메타데이터 추출
    """
    meta = {"company_hint": "", "filing_date": "", "rcept_no": ""}
    # DART_P0_회사명_날짜.zip
    m = re.match(r'DART_P\d+_(.+?)_(\d{8})(\d+)\.zip', os.path.basename(outer_filename))
    if m:
        meta["company_hint"] = m.group(1)
        date_str = m.group(2)
        meta["filing_date"] = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        meta["rcept_no"] = m.group(2) + m.group(3)
    return meta


def extract_fiscal_year(text: str, filing_date: str) -> Optional[int]:
    """텍스트 또는 파일명에서 회계연도 추출"""
    matches = re.findall(r'(20\d{2})년', text[:3000])
    if matches:
        # 가장 많이 등장하는 연도
        from collections import Counter
        year_counts = Counter(int(y) for y in matches if 2010 <= int(y) <= 2030)
        if year_counts:
            return year_counts.most_common(1)[0][0]
    if filing_date and len(filing_date) >= 4:
        try:
            return int(filing_date[:4]) - 1  # 공시일 전년도 = 회계연도
        except Exception:
            pass
    return None


# ── 청킹 ──
def split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE) -> list:
    paragraphs = re.split(r'\n\s*\n|\s{4,}', text)
    chunks = []
    current_chunk = []
    current_length = 0
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_len = len(para)
        if para_len > chunk_size:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_length = 0
            for start in range(0, para_len, chunk_size):
                chunks.append(para[start:start + chunk_size])
            continue
        if current_length + para_len + 1 > chunk_size and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_length = 0
        current_chunk.append(para)
        current_length += para_len + 1
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks


def parse_gemini_json(text: str) -> dict:
    text = text.strip()
    json_match = re.search(r'```(?:json)?\s*(\{.+\})\s*```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        brace_match = re.search(r'\{.+\}', text, re.DOTALL)
        if brace_match:
            text = brace_match.group(0)
    try:
        return json.loads(text)
    except Exception:
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
        try:
            return json.loads(cleaned)
        except Exception:
            return {
                "summary": text[:800] if text else "파싱 실패",
                "category": "기타공시",
                "evidence": "",
                "financial_metrics": "",
                "insight_vectors": "",
            }


ANALYSIS_PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.

다음 공시문서를 분석하여 **반드시 아래 JSON 형식**으로 출력하세요.

문서 내용:
{document_text}

출력 JSON:
{{
  "summary": "핵심 요약 (반드시 300자 이상, 재무 수치 포함. 매출액, 영업이익, 자산총계, 부채총계, 순이익 등 정확한 숫자를 포함해야 합니다)",
  "category": "재무제표 | 사업보고서 | 감사보고서 | 주요사항보고서 | 정정신고 | 기타공시 중 하나",
  "evidence": "요약의 근거가 되는 핵심 문장 (원문 인용)",
  "financial_metrics": "주요 재무지표 요약 (매출액, 영업이익률 등)",
  "insight_vectors": "투자자 관점: 핵심 리스크와 기회",
  "company_name": "회사명",
  "disclosure_title": "공시명"
}}

규칙:
1. summary는 반드시 300자 이상. 재무 수치를 빠짐없이 포함
2. 숫자는 정확하게, 단위(백만원, 억원) 포함
3. JSON만 출력, 다른 텍스트 없이"""

CHUNK_SUMMARY_PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.

다음은 공시문서의 일부(파트 {chunk_idx}/{total_chunks})입니다.
핵심 내용을 300~600자로 요약하세요. 재무 수치가 있으면 반드시 포함하세요.

[파트 {chunk_idx}/{total_chunks}]
{chunk_text}

위 내용의 핵심 요약:"""

MERGE_PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.

다음은 하나의 공시문서를 여러 파트로 나누어 요약한 결과입니다.
이 부분 요약들을 통합하여 **하나의 완전한 분석 JSON**을 작성하세요.

{partial_summaries}

출력 JSON:
{{
  "summary": "전체 문서의 통합 요약 (반드시 500자 이상, 모든 파트의 핵심 재무 수치를 포함)",
  "category": "재무제표 | 사업보고서 | 감사보고서 | 주요사항보고서 | 정정신고 | 기타공시 중 하나",
  "evidence": "각 파트에서 가장 중요한 근거 문장들 종합",
  "financial_metrics": "모든 파트의 재무지표 종합 (매출액, 영업이익, 자산, 부채 등)",
  "insight_vectors": "투자자 관점: 전체 문서의 핵심 리스크와 기회",
  "company_name": "회사명",
  "disclosure_title": "공시명"
}}

규칙:
1. 모든 파트의 재무 수치를 빠짐없이 통합
2. summary는 반드시 500자 이상
3. JSON만 출력"""


async def call_gemini_async(pool: GeminiClientPool, prompt: str) -> str:
    max_retries = 8
    for attempt in range(max_retries):
        client, limiter = await pool.get_next_client()
        try:
            # 전체 호출에 60초 하드 타임아웃 (Vertex AI hang 방지)
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=4096,
                        top_p=0.9,
                    ),
                ),
                timeout=90,  # 90초 초과 시 강제 취소
            )
            result_text = response.text or ""
            await limiter.record_success()
            return result_text
        except asyncio.TimeoutError:
            print(f"    ⏱️ [{limiter.key_name}] 90초 타임아웃 → 재시도")
            await asyncio.sleep(3)
            continue
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                backoff = await limiter.record_429()
                await asyncio.sleep(min(backoff, 5))
                continue
            elif "500" in err_str or "503" in err_str:
                wait = 5 * (attempt + 1)
                await asyncio.sleep(wait)
                continue
            elif "API_KEY_INVALID" in err_str or "PERMISSION_DENIED" in err_str:
                async with limiter.lock:
                    limiter.backoff_until = time.time() + 999999
                continue
            else:
                raise
    raise RuntimeError(f"Gemini 호출 {max_retries}회 실패")


async def call_local_llm_async(prompt: str, llm_url: str) -> str:
    """vLLM OpenAI-compatible API 호출 (GPU 로컬 추론, API 제한 없음)"""
    url = f"{llm_url}/v1/chat/completions"
    payload = {
        "model": "Qwen/Qwen2.5-32B-Instruct-AWQ",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096,
        "top_p": 0.9,
    }
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Local LLM error {resp.status}: {text[:200]}")
            data = await resp.json()
            return data["choices"][0]["message"]["content"]


async def _call_llm(pool, prompt, llm_url=None):
    """Gemini 또는 로컬 LLM 중 하나를 호출하는 통합 래퍼"""
    if llm_url:
        return await call_local_llm_async(prompt, llm_url)
    else:
        return await call_gemini_async(pool, prompt)


async def async_analyze_document(pool: GeminiClientPool, ocr_text: str, llm_url: str = None) -> dict:
    text_len = len(ocr_text)
    if text_len <= CHUNK_THRESHOLD:
        prompt = ANALYSIS_PROMPT.format(document_text=ocr_text[:14000])
        result = await _call_llm(pool, prompt, llm_url)
        return parse_gemini_json(result)

    chunks = split_into_chunks(ocr_text, CHUNK_SIZE)
    total_chunks = len(chunks)
    partial_summaries = []
    print(f"      [청크 시작] 총 {total_chunks}개 조각으로 나누어 분석합니다...")
    for i, chunk in enumerate(chunks):
        prompt = CHUNK_SUMMARY_PROMPT.format(
            chunk_idx=i + 1, total_chunks=total_chunks, chunk_text=chunk
        )
        try:
            partial = (await _call_llm(pool, prompt, llm_url)).strip()
            if partial:
                partial_summaries.append(f"[파트 {i+1}/{total_chunks}]\n{partial}")
                print(f"        - 조각 {i+1}/{total_chunks} 분석 완료")
        except Exception as e:
            print(f"    ✗ 청크 {i+1}/{total_chunks} 실패: {str(e)[:50]}")

    if not partial_summaries:
        prompt = ANALYSIS_PROMPT.format(document_text=ocr_text[:14000])
        return parse_gemini_json(await _call_llm(pool, prompt, llm_url))

    merged = "\n\n".join(partial_summaries)
    if len(merged) > 14000:
        merged = merged[:14000]
    result = await _call_llm(pool, MERGE_PROMPT.format(partial_summaries=merged), llm_url)
    parsed = parse_gemini_json(result)
    parsed["_chunk_count"] = total_chunks
    parsed["_chunk_mode"] = True
    return parsed


def index_to_chroma(doc_id: int, filename: str, company: str, report_type: str,
                    fiscal_year: Optional[int], text: str):
    """Chroma omega_document_chunks 컬렉션에 청크 인덱싱"""
    try:
        from services.vector_service import _get_collection, _get_embedding, CHAT_CHUNK_COLLECTION_NAME
        collection = _get_collection(CHAT_CHUNK_COLLECTION_NAME)
        if collection is None:
            return 0

        # 기존 벡터 삭제
        try:
            existing = collection.get(where={"doc_id": doc_id})
            if existing and existing.get("ids"):
                collection.delete(ids=existing["ids"])
        except Exception:
            pass

        chunks = split_into_chunks(text, 1000)
        if not chunks:
            return 0

        ids, embeddings, documents, metadatas = [], [], [], []
        for i, chunk_text in enumerate(chunks):
            emb = _get_embedding(chunk_text)
            if emb is None:
                continue
            chunk_uid = hashlib.md5(f"{doc_id}_dart_xml_{i}_{chunk_text[:50]}".encode()).hexdigest()
            ids.append(chunk_uid)
            embeddings.append(emb)
            documents.append(chunk_text)
            metadatas.append({
                "doc_id": doc_id,
                "filename": filename,
                "company": company,
                "company_norm": company,
                "report_type": report_type,
                "category": report_type,
                "page_no": 0,
                "section_name": "",
                "fiscal_year": fiscal_year or 0,
                "period_type": "annual",
                "statement_scope": "consolidated",
                "source": "dart_xml",
            })

        if ids:
            batch_size = 5000
            for b in range(0, len(ids), batch_size):
                collection.add(
                    ids=ids[b:b+batch_size],
                    embeddings=embeddings[b:b+batch_size],
                    documents=documents[b:b+batch_size],
                    metadatas=metadatas[b:b+batch_size],
                )
            return len(ids)
    except Exception as e:
        print(f"    ⚠️ Chroma 인덱싱 실패 (무시): {e}")
    return 0


async def process_one(entry_name: str, inner_zip_bytes: bytes, pool: GeminiClientPool,
                      semaphore: asyncio.Semaphore, stats: dict,
                      skip_gemini: bool, skip_chroma: bool,
                      jsonl_writer=None, llm_url: str = None):
    """단일 내부 zip 처리"""
    async with semaphore:
        start_t = time.time()
        fn_meta = parse_filename_meta(entry_name)
        company_hint = fn_meta["company_hint"]
        filing_date = fn_meta["filing_date"]

        try:
            # 내부 zip 열기
            inner_buf = io.BytesIO(inner_zip_bytes)
            with zipfile.ZipFile(inner_buf, 'r') as inner_zip:
                xml_entries = [e for e in inner_zip.namelist() if e.lower().endswith('.xml')]
                if not xml_entries:
                    stats["skip"] += 1
                    return

                # 메인 XML 선택: 접수번호.xml (숫자로만 된 파일명)
                main_xml = None
                for xml_name in xml_entries:
                    base = os.path.splitext(os.path.basename(xml_name))[0]
                    if re.match(r'^\d+$', base):
                        main_xml = xml_name
                        break
                # 없으면 가장 큰 XML
                if not main_xml:
                    sizes = [(inner_zip.getinfo(n).file_size, n) for n in xml_entries]
                    main_xml = max(sizes)[1]

                xml_bytes = inner_zip.read(main_xml)

            # XML → 텍스트 + 메타
            text, xml_meta = extract_dart_xml_text(xml_bytes)
            if not text or len(text.strip()) < 100:
                stats["skip"] += 1
                return

            # 메타데이터 병합 (XML > 파일명)
            company_name = xml_meta.get("company_name") or company_hint
            corp_code = xml_meta.get("corp_code", "")
            doc_type = xml_meta.get("doc_type", "기타공시")
            fiscal_year = extract_fiscal_year(text, filing_date)

            # 파일명 생성 (DB 중복 방지용 고유 키)
            outer_basename = os.path.basename(entry_name)
            filename = outer_basename  # DART_P0_회사명_날짜.zip

            # ── RunPod 모드: DB 없이 처리 ──
            if jsonl_writer is not None:
                doc_id = int(hashlib.md5(filename.encode()).hexdigest()[:8], 16)

            # ── 로컬 모드: SQLite 저장 ──
            else:
                if not _LOCAL_IMPORTS_OK:
                    print("  ❌ 로컬 모드인데 DB import 실패. --output-jsonl 옵션을 사용하세요.")
                    stats["failed"] += 1
                    return

                db = SessionLocal()
                try:
                    existing_doc = db.query(Document).filter(
                        Document.filename == filename
                    ).first()

                    if existing_doc:
                        stats["skip"] += 1
                        print(f"  ⏭️ 이미 존재: {filename[:50]}")
                        return

                    doc = Document(
                        user_id=_get_admin_user_id(db),
                        filename=filename,
                        file_path=f"DART_XML_Ingest/{filename}",
                        file_type="xml",
                        file_size=len(text),
                        status="ocr_done",
                    )
                    db.add(doc)
                    db.commit()
                    db.refresh(doc)
                    doc_id = doc.id

                    ocr = OcrText(
                        document_id=doc_id,
                        raw_text=text,
                        cleaned_text=text,
                        confidence=0.95,
                    )
                    db.add(ocr)
                    db.commit()
                finally:
                    db.close()


            # ── Gemini 분석 ──
            result = None
            if not skip_gemini:
                try:
                    result = await async_analyze_document(pool, text, llm_url=llm_url)
                    chunk_info = f" [{result.get('_chunk_count', 1)}청크]" if result.get('_chunk_mode') else ""
                    elapsed = time.time() - start_t
                    print(f"  ✅ [{stats['success']+1}] {company_name[:15]} | {doc_type}{chunk_info} ({elapsed:.1f}s)")
                except Exception as e:
                    print(f"  ⚠️ Gemini 실패: {str(e)[:60]}")
                    result = None

            if result is None:
                result = {
                    "summary": f"{company_name} {doc_type} — 텍스트 주입 완료",
                    "category": doc_type,
                    "company_name": company_name,
                    "disclosure_title": doc_type,
                    "evidence": "", "financial_metrics": "", "insight_vectors": "",
                }

            # ── RunPod 모드: JSONL 출력 (SQLite/Chroma 스킵) ──
            if jsonl_writer is not None:
                record = {
                    "file_name": filename,
                    "raw_text": text,
                    "insight": result.get("summary", ""),
                    "company_name": company_name,
                    "corp_code": corp_code,
                    "doc_type": doc_type,
                    "fiscal_year": fiscal_year,
                    "filing_date": filing_date,
                    "gemini_result": result,
                }
                line = json.dumps(record, ensure_ascii=False)
                # 스레드-세이프 write (asyncio에서는 동일 이벤트루프 = 순차)
                jsonl_writer.write(line + "\n")
                jsonl_writer.flush()

            # ── 로컬 모드: SQLite + Chroma + PDF ──
            else:
                db = SessionLocal()
                try:
                    analysis = AnalysisResult(
                        document_id=doc_id,
                        summary=result.get("summary", ""),
                        category=result.get("category", doc_type),
                        evidence=result.get("evidence", ""),
                        financial_metrics=result.get("financial_metrics", ""),
                        insight_vectors=result.get("insight_vectors", ""),
                        model_name="gemini-2.5-flash" if not skip_gemini else "dart_xml_ingest",
                        raw_response=result,
                    )
                    db.add(analysis)
                    db.query(Document).filter(Document.id == doc_id).update({"status": "analyzed"})

                    existing_meta = db.query(DocumentMetadata).filter(
                        DocumentMetadata.document_id == doc_id
                    ).first()
                    if not existing_meta:
                        dm = DocumentMetadata(
                            document_id=doc_id,
                            company_name=company_name,
                            company_name_norm=company_name,
                            corp_code=corp_code or None,
                            report_type=doc_type,
                            disclosure_title=result.get("disclosure_title", doc_type),
                            filing_date=filing_date,
                            fiscal_year=fiscal_year,
                            period_type="annual",
                            statement_scope="consolidated",
                            source_kind="dart_xml",
                            extraction_confidence=0.85,
                        )
                        db.add(dm)

                    try:
                        report_path = generate_pdf_report(
                            doc_id, filename,
                            {"summary": result.get("summary", ""),
                             "category": result.get("category", ""),
                             "raw_response": result}
                        )
                        if report_path:
                            db.query(Document).filter(Document.id == doc_id).update(
                                {"report_path": report_path}
                            )
                    except Exception:
                        pass

                    db.commit()
                finally:
                    db.close()

                # Chroma 인덱싱
                if not skip_chroma:
                    chroma_chunks = index_to_chroma(
                        doc_id, filename, company_name, doc_type, fiscal_year, text
                    )
                    if chroma_chunks > 0:
                        stats["chroma_chunks"] += chroma_chunks

            stats["success"] += 1
            stats["completed"].add(entry_name)

            # 진행상태 저장 (10건마다)
            if stats["success"] % 10 == 0:
                with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                    json.dump({"completed": list(stats["completed"])}, f)

        except Exception as e:
            stats["failed"] += 1
            print(f"  ❌ {entry_name[:50]} 실패: {str(e)[:80]}")
            traceback.print_exc()


def _get_admin_user_id(db) -> int:
    from models.models import User
    admin = db.query(User).filter(User.role == "admin").first()
    if not admin:
        admin = db.query(User).first()
    if not admin:
        raise RuntimeError("DB에 사용자가 없습니다.")
    return admin.id


async def async_main():
    parser = argparse.ArgumentParser(description="DART XML 이중압축 배치 인제스트 (로컬/RunPod 분산 지원)")
    parser.add_argument("--zip", required=True, help="DataSet_Cleaned.zip 경로")
    parser.add_argument("--limit", type=int, default=0, help="처음 N개만 처리 (0=전체)")
    parser.add_argument("--resume", action="store_true", help="이전 진행 상태에서 재개")
    parser.add_argument("--skip-gemini", action="store_true", help="Gemini 분석 건너뜀")
    parser.add_argument("--skip-chroma", action="store_true", help="Chroma 인덱싱 건너뜀")
    parser.add_argument("--workers", type=int, default=MAX_CONCURRENT,
                        help=f"동시 Gemini 호출 수 (기본: {MAX_CONCURRENT}, RunPod 권장: 8~12)")
    # ── 분산 처리 옵션 ──
    parser.add_argument("--shard-id", type=int, default=0,
                        help="이 머신의 샤드 번호 (0부터 시작, 기본: 0)")
    parser.add_argument("--total-shards", type=int, default=1,
                        help="전체 머신 수 (기본: 1 = 분산 없음)")
    parser.add_argument("--output-jsonl", type=str, default="",
                        help="결과를 JSONL 파일로 저장 (RunPod 모드 — SQLite/Chroma 스킵)")
    parser.add_argument("--reprocess-failed", action="store_true",
                        help="status=ocr_done인 DART 문서도 분석 재시도")
    parser.add_argument("--api-keys", type=str, default="",
                        help="추가 Gemini API 키 (콤마 구분)")
    parser.add_argument("--rpm", type=int, default=MAX_RPM_PER_KEY,
                        help=f"키당 RPM 한도 (기본: {MAX_RPM_PER_KEY})")
    # ── 로컬 GPU LLM (vLLM) 옵션 ──
    parser.add_argument("--use-local-llm", action="store_true",
                        help="Gemini 대신 로컬 vLLM 서버 사용 (API 제한 없음)")
    parser.add_argument("--llm-url", type=str, default="http://localhost:8000",
                        help="vLLM 서버 URL (기본: http://localhost:8000)")
    args = parser.parse_args()
    
    # ── 사용자 요청: 어떤 경우에도 배치단에서 Gemini를 호출하지 않도록 강제 ──
    args.skip_gemini = True

    # RunPod 모드: output-jsonl 지정 시 SQLite 불필요 → Chroma도 스킵
    if args.output_jsonl:
        args.skip_chroma = True
        print(f"  🚀 RunPod JSONL 출력 모드 → {args.output_jsonl}")

    if not os.path.exists(args.zip):
        print(f"❌ 파일을 찾을 수 없습니다: {args.zip}")
        return

    # 진행상태 로드
    completed_set = set()
    if args.resume and os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            completed_set = set(json.load(f).get("completed", []))
        print(f"  📋 이전 진행 상태 로드: {len(completed_set)}건 완료됨")

    # LLM 모드 결정
    llm_url = None
    pool = GeminiClientPool()
    if args.use_local_llm:
        llm_url = args.llm_url
        print(f"  🖥️ 로컬 GPU LLM 모드: {llm_url}")
        print(f"  ⚡ API 제한 없음 — 전속력 처리")
    elif not args.skip_gemini:
        extra_keys = [k.strip() for k in args.api_keys.split(",") if k.strip()] if args.api_keys else []
        api_keys = _load_api_keys(extra_keys)
        rpm_limit = args.rpm
        print(f"  🔑 API 키: {len(api_keys)}개 | 키당 {rpm_limit} RPM | 최대 {len(api_keys) * rpm_limit} RPM")
        for i, key in enumerate(api_keys):
            pool.add_api_key_client(key, f"key{i+1}", rpm=rpm_limit)
        if not pool.clients:
            print("⚠️ Gemini 클라이언트 없음 → --skip-gemini 모드로 전환")
            args.skip_gemini = True

    print("═" * 62)
    print(f"  Ω  DART XML 배치 인제스트")
    print(f"  파일: {os.path.basename(args.zip)}")
    print(f"  Gemini: {'건너뜀' if args.skip_gemini else '활성'} | Chroma: {'건너뜀' if args.skip_chroma else '활성'}")
    print(f"  동시 처리: {args.workers}건")
    if args.total_shards > 1:
        print(f"  ✂️  샤드: {args.shard_id + 1} / {args.total_shards} (이 머신이 처리할 구간)")
    if args.output_jsonl:
        print(f"  📤 JSONL 출력: {args.output_jsonl}")
    print("═" * 62)

    # 외부 zip 순회하여 작업 목록 생성 (샤딩 적용)
    tasks_to_run = []
    with zipfile.ZipFile(args.zip, 'r') as outer_zip:
        inner_entries = [e for e in outer_zip.namelist() if e.lower().endswith('.zip')]
        total_entries = len(inner_entries)
        print(f"  총 내부 zip: {total_entries}개")

        # 샤딩: 전체 목록에서 이 머신이 담당하는 항목만 선택
        # shard_id=0, total_shards=2 → 짝수 인덱스 (0,2,4,...)
        # shard_id=1, total_shards=2 → 홀수 인덱스 (1,3,5,...)
        sharded_entries = [
            e for i, e in enumerate(inner_entries)
            if i % args.total_shards == args.shard_id
        ]
        if args.total_shards > 1:
            print(f"  샤드 {args.shard_id}: {len(sharded_entries)}개 담당")

        for entry_name in sharded_entries:
            if entry_name in completed_set:
                continue
            inner_bytes = outer_zip.read(entry_name)
            tasks_to_run.append((entry_name, inner_bytes))
            if args.limit and len(tasks_to_run) >= args.limit:
                break

    remaining = len(tasks_to_run)
    print(f"  처리 대상: {remaining}개 (완료 제외)")
    print("═" * 62)

    if not tasks_to_run:
        print("  ✅ 모두 완료됨!")
        return

    # RunPod 모드: output_jsonl 파일 미리 열기
    jsonl_writer = None
    if args.output_jsonl:
        jsonl_writer = open(args.output_jsonl, 'a', encoding='utf-8')
        print(f"  📂 JSONL 파일 열림: {args.output_jsonl}")

    stats = {
        "success": 0,
        "failed": 0,
        "skip": 0,
        "chroma_chunks": 0,
        "completed": completed_set,
    }

    semaphore = asyncio.Semaphore(args.workers)
    start_time = time.time()

    cors = [
        process_one(entry_name, inner_bytes, pool, semaphore, stats,
                    args.skip_gemini, args.skip_chroma, jsonl_writer, llm_url=llm_url)
        for entry_name, inner_bytes in tasks_to_run
    ]
    await asyncio.gather(*cors)

    # RunPod JSONL 파일 닫기
    if jsonl_writer is not None:
        jsonl_writer.close()
        size_mb = os.path.getsize(args.output_jsonl) / 1024 / 1024
        print(f"  💾 JSONL 저장 완료: {args.output_jsonl} ({size_mb:.1f} MB)")
        print(f"  ▶  로컬에서 주입: python backend/scripts/rag_injector.py {args.output_jsonl}")

    elapsed = time.time() - start_time
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

    print("═" * 62)
    print(f"  ✅ 완료! {elapsed/60:.1f}분 소요")
    print(f"  성공: {stats['success']} | 실패: {stats['failed']} | 스킵: {stats['skip']}")
    if not args.output_jsonl:
        print(f"  Chroma 청크: {stats['chroma_chunks']}개")
    if not args.skip_gemini:
        print(f"  키 현황: {pool.stats()}")
    print("═" * 62)


if __name__ == "__main__":
    asyncio.run(async_main())
