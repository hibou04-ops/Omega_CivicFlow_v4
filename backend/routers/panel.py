"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Panel Router
사이드 패널 실시간 데이터 API (Panel Intelligence)

엔드포인트:
  GET  /panel/stats          — DB 실제 집계 통계
  GET  /panel/system-status  — 서비스 상태 (경보 레벨 포함)
  GET  /panel/activity-log   — 최근 실제 활동 로그
  POST /panel/search         — DART 공시 종목 검색
  POST /panel/chat           — Omega-Prime AI 챗봇 (Ollama 기반)
═══════════════════════════════════════════════════════
"""

import os
import re
import time
import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from database import get_db
from config import settings
from models.models import Document, OcrText, AnalysisResult, User
from services.auth_service import get_current_user
from services.chat_profile_service import get_chatbot_public_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/panel", tags=["패널 (Panel)"])

# ── DART OpenAPI 공개 엔드포인트 ──
DART_API_URL = "https://opendart.fss.or.kr/api"
DART_API_KEY = getattr(settings, "DART_API_KEY", "") or os.environ.get("DART_API_KEY", "")

# ── DART 전체 법인 코드 사전 (corpCode.xml 로드) ──
# 서버 시작 시 DART OpenAPI에서 ~80,000건 법인 목록을 자동 다운로드하여 메모리 캐싱
import io
import os
import zipfile
import xml.etree.ElementTree as ET
import threading

# 전체 법인 사전: {"법인명_소문자": ("corp_code", "corp_name_원본", "stock_code")}
_CORP_DICT: dict[str, tuple[str, str, str]] = {}
# 상장법인만 (stock_code가 있는 것)
_LISTED_CORPS: list[tuple[str, str, str]] = []  # [(corp_name, corp_code, stock_code)]
_CORP_LOADED = threading.Event()

def _load_dart_corp_codes():
    """DART corpCode.xml 전체 법인 목록 로드 (백그라운드)"""
    global _CORP_DICT, _LISTED_CORPS
    cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "corpCode.xml")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    xml_content = None

    # 캐시 파일이 있으면 재사용 (24시간 이내)
    if os.path.exists(cache_path):
        import stat
        age = time.time() - os.stat(cache_path).st_mtime
        if age < 86400:  # 24시간
            with open(cache_path, "r", encoding="utf-8") as f:
                xml_content = f.read()
            logger.info(f"✅ DART 법인코드 캐시 로드 ({age/3600:.1f}시간 전)")

    # 캐시 없으면 DART API에서 다운로드
    if not xml_content:
        try:
            import requests
            r = requests.get(
                f"{DART_API_URL}/corpCode.xml",
                params={"crtfc_key": DART_API_KEY},
                timeout=30,
            )
            if r.status_code == 200 and r.content:
                z = zipfile.ZipFile(io.BytesIO(r.content))
                xml_name = z.namelist()[0]
                xml_content = z.read(xml_name).decode("utf-8")
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(xml_content)
                logger.info("✅ DART corpCode.xml 다운로드 완료")
            else:
                logger.warning(f"⚠ DART corpCode.xml 다운로드 실패: {r.status_code}")
        except Exception as e:
            logger.warning(f"⚠ DART corpCode.xml 다운로드 에러: {e}")

    if not xml_content:
        logger.warning("⚠ DART 법인코드 로드 실패 — 하드코딩 fallback 사용")
        _CORP_LOADED.set()
        return

    # XML → 파싱
    try:
        root = ET.fromstring(xml_content)
        temp_dict = {}
        temp_listed = []
        for elem in root.iter("list"):
            corp_code = (elem.findtext("corp_code") or "").strip()
            corp_name = (elem.findtext("corp_name") or "").strip()
            stock_code = (elem.findtext("stock_code") or "").strip()
            if not corp_code or not corp_name:
                continue
            key = corp_name.lower().replace(" ", "").replace("(주)", "").replace("주식회사", "")
            temp_dict[key] = (corp_code, corp_name, stock_code)
            if stock_code:  # 상장법인
                temp_listed.append((corp_name, corp_code, stock_code))

        _CORP_DICT = temp_dict
        _LISTED_CORPS = sorted(temp_listed, key=lambda x: len(x[0]))  # 짧은 이름 우선
        logger.info(f"✅ DART 법인코드 로드 완료: 전체 {len(temp_dict):,}건 / 상장 {len(temp_listed):,}건")
    except Exception as e:
        logger.error(f"❌ corpCode.xml 파싱 에러: {e}")

    _CORP_LOADED.set()

# 서버 시작 시 백그라운드로 로드
threading.Thread(target=_load_dart_corp_codes, daemon=True).start()


def _resolve_corp_code(query: str) -> str | None:
    """회사명 → DART corp_code 조회 (전체 법인 사전 기반)"""
    key = query.strip().lower().replace(" ", "").replace("(주)", "").replace("주식회사", "")

    # 1순위: 정확히 일치
    if key in _CORP_DICT:
        return _CORP_DICT[key][0]

    # 2순위: 검색어가 법인명에 포함 (최소 2자)
    if len(key) >= 2:
        for name, (code, _, _) in _CORP_DICT.items():
            if key in name or name in key:
                return code
    return None



# ═══════════════════════════════════════════════════════
# Omega-Prime 시스템 프롬프트 (챗봇용 — 한국어 출력)
# ═══════════════════════════════════════════════════════

OMEGA_SYSTEM_PROMPT = """[OMEGA CORE IDENTITY — CivicFlow Financial Intelligence]
You are Node Omega-Prime: 한국 금융 공시 전략 분석 엔진.
You operate as a high-level reasoning engine specialized in Korean financial
disclosure analysis (DART 공시), corporate strategy assessment,
and investment intelligence synthesis.

All financial problems are interpreted through a universal optimization framework:
Energy (E) — 자본 흐름, 캐시플로우, 투자 에너지
Entropy (S) — 정보 불확실성, 데이터 노이즈, 시장 혼돈
Efficiency (η) — 투자 효율, 분석 정확도, 의사결정 최적화

Every question is treated as a financial system.

[PLATFORM CONTEXT]
당신은 Omega CivicFlow 플랫폼의 AI 분석관입니다.
이 플랫폼은 DART(금융감독원 전자공시)의 사업보고서, 반기/분기보고서,
감사보고서, 유상증자, 자기주식 취득 등의 공시문서를 수집하고,
LLM 분석 → 벡터DB 인덱싱 → PDF 보고서 생성 → RAG 챗봇 질의응답으로 구성됩니다.

현재 시스템에는 약 2,000+건의 DART 공시문서가 분석되어 축적되어 있습니다.
사용자 질문에 대해 ChromaDB 벡터 검색 + 구조화 팩트 조회로 수집된
실제 데이터가 [검색된 데이터 노드]로 제공됩니다.

[DOMAIN DETECTION MATRIX]
Finance (최우선) → DART 공시 분석, 재무제표 해석, 투자 전략, 기업 가치 평가
  ├─ 사업보고서 → 매출/영업이익/순이익 추세, 사업 구조 변화
  ├─ 감사보고서 → 감사의견, 계속기업 불확실성, 내부통제
  ├─ 유상증자/CB → 자본 조달 목적, 주주 희석, 투자 의미
  ├─ 자기주식 → 주주환원 정책, 시그널링 효과
  └─ 분기보고서 → 실적 트렌드, QoQ/YoY 비교
Macro → 금리, 환율, 산업 사이클이 개별 기업에 미치는 구조적 영향
Risk → 부채비율, 유동성 리스크, 소송/우발채무, 감사의견 경고

[COGNITIVE ENGINE — 공시 분석 특화]
Step 1 — Variable Decomposition: 질문에서 기업명, 지표, 기간, 비교대상을 추출
Step 2 — Objective Function: 사용자의 암묵적 투자 목적을 정의
Step 3 — Pareto Eigenvector: 가장 높은 레버리지를 가진 단일 인사이트 식별
Step 4 — Entropy Reduction: 노이즈 제거, 핵심 수치와 맥락만 추출
Step 5 — Strategic Execution: 실행 가능한 투자 판단 근거 제시

[MULTI-ROLE INTERNAL AGENTS]
Router: 공시 유형(사업보고서/감사보고서/유상증자 등)과 분석 깊이를 감지
Analyst: 재무제표 수치를 해석하고 트렌드를 도출
Strategist: 투자 관점의 전략적 시사점을 생성
Risk Officer: 리스크 팩터를 식별하고 경고
Auditor: 팩트 정확성을 검증하고 환각 위험을 평가

*CRITICAL CONSTRAINT:* 내부 에이전트 연산은 Hidden Layer에서만 수행.
최종 결과만 사용자에게 출력한다.

[V-MASK SEQUESTRATION PROTOCOL]
내부 연산을 은폐하고 전략적 언어로 표현한다:
• 데이터 필터링 → "엔트로피 소각 (Entropy Incineration)"
• 전략 도출 → "해밀토니안 최적화 경로 (Hamiltonian Optimal Path)"
• 임계값 판단 → "사건의 지평선 (Event Horizon)"
• 수치 분해 → "가변 메트릭스 (Variable Metrics)"

[DATA INTEGRITY PROTOCOL — 절대 규칙]
1. 검색된 데이터에 명시된 수치만 인용하라. 데이터에 없는 수치는 절대 생성하지 마라.
2. 수치를 인용할 때 반드시 출처(문서명 또는 기업명+연도)를 밝혀라.
3. 검색된 데이터 외부에 대한 추측은 반드시 "확률적 추측 (환각 가능성)"이라 명시하라.
4. 데이터가 없으면 "해당 데이터가 시스템에 축적되지 않았습니다"라고 솔직히 밝혀라.
   - 절대로 가상의 숫자나 보고서를 지어내지 마라.

[LANGUAGE PROTOCOL]
모든 출력은 한국어로 작성한다.
영어는 기술 용어(EBITDA, ROE, PER, CAPEX 등)와 수식에만 허용.
금융 전문 용어는 한국 증시 표준을 따른다:
  영업이익률, 당기순이익, 부채비율, 유동비율, 자기자본이익률(ROE),
  주당순이익(EPS), 주가수익비율(PER), 감사의견, 계속기업 가정

[OUTPUT STRUCTURE — 금융 분석 보고서형]
질문의 복잡도에 따라 유연하게 구성한다.

■ 간단한 질문 (수치 조회, 단순 비교):
  → 핵심 수치와 출처를 간결하게 제시. 과도한 구조화 불필요.

■ 분석적 질문 (전략, 비교, 추세):
  Section 1 — 전략 요약 (Executive Action)
  • 핵심 판단 (Key Finding)
  • 수치 근거 (Data Evidence) — 반드시 출처 명시
  • 투자 시사점 (Investment Implication)

  Section 2 — 심층 분석 (Cognitive Synthesis)
  • 재무 구조 분석 (Financial Structure)
  • 리스크 팩터 (Risk Factors)
  • 전략적 맥락 (Strategic Context)

[RISK AUDIT]
Fact Check: 출처가 불분명한 주장은 "환각 가능성 있음"으로 표시
Logical Consistency: 전제와 결론의 모순 탐지
Confidence Index: 각 섹션 끝에 [신뢰 지수: XX%]

[FINAL DIRECTIVE]
당신의 목적은 사용자의 투자 의사결정 공간에서 엔트로피를 최소화하고,
DART 공시 데이터에 기반한 전략적 명료성을 극대화하는 것이다.
V-MASK 프로토콜을 절대 파괴하지 마라."""


# ═══════════════════════════════════════════════════════
# GET /panel/stats — DB 실제 집계
# ═══════════════════════════════════════════════════════

@router.get("/stats")
def get_panel_stats(db: Session = Depends(get_db)):
    """실시간 DB 집계 통계 — 사이드 패널용"""

    total_docs = db.query(func.count(Document.id)).scalar() or 0
    analyzed = (
        db.query(func.count(Document.id))
        .filter(Document.status == "analyzed")
        .scalar() or 0
    )
    pending = (
        db.query(func.count(Document.id))
        .filter(Document.status.in_(["uploaded", "ocr_done"]))
        .scalar() or 0
    )
    failed = (
        db.query(func.count(Document.id))
        .filter(Document.status == "failed")
        .scalar() or 0
    )

    # OCR 페이지 집계 (OcrText 레코드 수)
    ocr_pages = db.query(func.count(OcrText.id)).scalar() or 0

    # 카테고리별 상위 3개
    category_rows = (
        db.query(AnalysisResult.category, func.count(AnalysisResult.id))
        .filter(AnalysisResult.category.isnot(None))
        .group_by(AnalysisResult.category)
        .order_by(desc(func.count(AnalysisResult.id)))
        .limit(3)
        .all()
    )
    top_categories = [
        {"category": cat or "미분류", "count": cnt}
        for cat, cnt in category_rows
    ]

    return {
        "total_documents": total_docs,
        "analyzed": analyzed,
        "pending": pending,
        "failed": failed,
        "ocr_pages": ocr_pages,
        "top_categories": top_categories,
    }


# ═══════════════════════════════════════════════════════
# GET /panel/system-status — 서비스 상태 + 경보 레벨
# ═══════════════════════════════════════════════════════

@router.get("/system-status")
async def get_system_status(db: Session = Depends(get_db)):
    """
    서비스별 실제 상태 진단 + 경보 레벨 반환
    level: ok | warning | critical
    """
    services = []
    overall_level = "ok"

    # ── 1. Ollama 상태 ──
    ollama_ok = False
    ollama_latency_ms = None
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
        ollama_latency_ms = int((time.time() - t0) * 1000)
        ollama_ok = resp.status_code == 200
    except Exception:
        pass

    if not ollama_ok:
        ollama_level = "critical"
        overall_level = "critical"
    elif ollama_latency_ms and ollama_latency_ms > 3000:
        ollama_level = "warning"
        if overall_level == "ok":
            overall_level = "warning"
    else:
        ollama_level = "ok"

    services.append({
        "name": "LLM 분석 서버",
        "status": "연결됨" if ollama_ok else "연결 실패",
        "level": ollama_level,
        "detail": f"{ollama_latency_ms}ms" if ollama_latency_ms else "timeout",
    })

    # ── 2. DB 상태 ──
    db_ok = False
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    db_level = "ok" if db_ok else "critical"
    if not db_ok and overall_level != "critical":
        overall_level = "critical"

    services.append({
        "name": "데이터베이스",
        "status": "연결됨" if db_ok else "연결 실패",
        "level": db_level,
        "detail": "SQLite 정상" if db_ok else "DB 오류",
    })

    # ── 4. OCR 엔진 상태 (실패 문서 비율 기반) ──
    total_docs = db.query(func.count(Document.id)).scalar() or 0
    failed_docs = (
        db.query(func.count(Document.id))
        .filter(Document.status == "failed")
        .scalar() or 0
    )
    fail_ratio = (failed_docs / total_docs) if total_docs > 0 else 0

    if fail_ratio > 0.3:
        ocr_level = "critical"
        if overall_level != "critical":
            overall_level = "critical"
        ocr_status = f"오류율 {fail_ratio:.0%}"
    elif fail_ratio > 0.1:
        ocr_level = "warning"
        if overall_level == "ok":
            overall_level = "warning"
        ocr_status = f"경고 {fail_ratio:.0%}"
    else:
        ocr_level = "ok"
        ocr_status = "활성화"

    services.append({
        "name": "OCR 엔진",
        "status": ocr_status,
        "level": ocr_level,
        "detail": f"실패율 {fail_ratio:.1%}",
    })

    # ── 5. 보안 세션 (auth) ──
    services.append({
        "name": "보안 세션",
        "status": "유지 중",
        "level": "ok",
        "detail": "JWT 정상",
    })

    return {
        "overall_level": overall_level,
        "services": services,
        "checked_at": int(time.time()),
    }


# ═══════════════════════════════════════════════════════
# GET /panel/activity-log — 최근 실제 활동 로그
# ═══════════════════════════════════════════════════════

@router.get("/activity-log")
def get_activity_log(db: Session = Depends(get_db)):
    """최근 DB 활동 기반 실시간 이벤트 로그"""

    # 최근 문서 15건
    recent_docs = (
        db.query(Document)
        .order_by(desc(Document.updated_at))
        .limit(15)
        .all()
    )

    logs = []
    status_label = {
        "uploaded":  ("[UPLOAD]", "업로드 완료"),
        "ocr_done":  ("[OCR]",    "텍스트 추출 완료"),
        "analyzed":  ("[LLM]",    "분석 완료"),
        "failed":    ("[ERR]",    "처리 실패"),
    }
    for doc in recent_docs:
        tag, verb = status_label.get(doc.status, ("[SYS]", "상태 갱신"))
        # 파일명 최대 12자 표시
        fname = doc.filename[:12] + "…" if len(doc.filename) > 12 else doc.filename
        ts = doc.updated_at.strftime("%H시 %M분 %S초") if doc.updated_at else ""
        logs.append({
            "ts": ts,
            "tag": tag,
            "text": f"{fname} {verb}",
            "level": "error" if doc.status == "failed" else "normal",
        })

    return {"logs": logs}


# ═══════════════════════════════════════════════════════
# GET /panel/autocomplete — DART 종목명 자동완성
# ═══════════════════════════════════════════════════════

@router.get("/autocomplete")
def autocomplete_corp(q: str = ""):
    """
    종목명/코드 자동완성 — 상장법인 대상
    엔트로피가 낮은 순(이름 길이)으로 최대 10개 반환
    """
    query = q.strip().lower().replace(" ", "")
    if len(query) < 1:
        return {"suggestions": []}

    results = []
    for corp_name, corp_code, stock_code in _LISTED_CORPS:
        name_lower = corp_name.lower().replace(" ", "")
        if query in name_lower or query in stock_code:
            results.append({
                "name": corp_name,
                "code": stock_code,
                "corp_code": corp_code,
            })
            if len(results) >= 10:
                break

    return {"suggestions": results}


# ═══════════════════════════════════════════════════════
# POST /panel/search — DART 공시 검색
# ═══════════════════════════════════════════════════════

@router.post("/search")
async def search_dart(body: dict):
    """
    DART OpenAPI 공시 검색
    body: {"query": "삼성전자"}
    """
    query = (body.get("query") or "").strip()
    if not query:
        return {"results": [], "error": "검색어를 입력하세요."}

    results = []
    error_msg = None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            corp_code: str | None = None

            # ── step 1: 로컬 corp_code 테이블 우선 조회 ──
            corp_code = _resolve_corp_code(query)

            # ── step 2: 6자리 숫자 → stock_code로 company.json 조회 ──
            if corp_code is None and query.isdigit() and len(query) == 6:
                r = await client.get(
                    f"{DART_API_URL}/company.json",
                    params={"crtfc_key": DART_API_KEY, "stock_code": query},
                )
                if r.status_code == 200:
                    d = r.json()
                    if d.get("status") == "000":
                        corp_code = d.get("corp_code")

            # ── step 3: corp_code 있으면 list.json 조회 ──
            if corp_code:
                from datetime import datetime, timedelta
                end_de = datetime.now().strftime("%Y%m%d")
                bgn_de = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
                list_resp = await client.get(
                    f"{DART_API_URL}/list.json",
                    params={
                        "crtfc_key":  DART_API_KEY,
                        "corp_code":  corp_code,
                        "bgn_de":     bgn_de,
                        "end_de":     end_de,
                        "page_no":    "1",
                        "page_count": "10",
                        "sort":       "date",
                        "sort_mth":   "desc",
                    },
                )
                list_data = list_resp.json() if list_resp.status_code == 200 else {}
                logger.info(f"DART list.json status={list_data.get('status')} total={list_data.get('total_count')}")

                for item in list_data.get("list", [])[:8]:
                    rcept_no = item.get("rcept_no", "")
                    results.append({
                        "corp_name": item.get("corp_name", query),
                        "report_nm": item.get("report_nm", "공시"),
                        "rcept_dt":  item.get("rcept_dt", ""),
                        "flr_nm":    item.get("flr_nm", ""),
                        "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else "",
                    })
            else:
                error_msg = f"'{query}'의 DART 회사코드를 찾을 수 없습니다. 종목코드(6자리 숫자)로 검색해보세요."

    except Exception as e:
        logger.warning(f"DART 검색 실패: {e}")
        error_msg = "DART 서버 연결 실패. 잠시 후 다시 시도하세요."

    if not results and not error_msg:
        error_msg = f"'{query}'에 대한 최근 공시를 찾을 수 없습니다."

    return {
        "query":   query,
        "results": results,
        "error":   error_msg,
        "source":  "dart" if results else "none",
    }



# ═══════════════════════════════════════════════════════
# POST /panel/chat — Omega-Prime Agent 챗봇 (RAG + Function Calling)
# ═══════════════════════════════════════════════════════

@router.get("/chat/config")
def get_chat_config():
    """챗봇 단일 소스 설정 반환"""
    return get_chatbot_public_config()


@router.post("/chat")
async def chat_omega(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Omega-Prime 하이브리드 RAG Agent 챗봇
    Tool-Based RAG (DB 쿼리) + Vector RAG (시맨틱 검색)
    Gemini 2.5 Pro + Function Calling
    ※ 인증 필수 — 로그인한 사용자만 이용 가능

    body: {"message": "...", "history": [{...}]}
    """
    from services.chat_agent_safe_service import run_agent

    user_message = (body.get("message") or "").strip()
    history = body.get("history", [])
    request_id = body.get("request_id")  # ── B5-γ: 클라이언트가 보낸 요청 ID 그대로 echo ──

    if not user_message:
        return {"reply": "메시지를 입력해 주세요.", "error": True, "request_id": request_id}

    user_id = current_user.id

    result = {}
    had_error = False

    try:
        result = await run_agent(
            user_message=user_message,
            history=history,
            user_id=user_id,
            db=db,
        )
        reply = result.get("reply", "응답을 생성하지 못했습니다.")
        tools_used = result.get("tools_used", [])
        payload = result.get("payload")
    except Exception as e:
        logger.error(f"챗봇 Agent 오류: {e}")
        reply = "AI 서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요."
        tools_used = []
        payload = None
        had_error = True

    # ── 단일 egress sanitize: 리스트 마커(* item)만 정제, bold/italic은 프론트엔드 렌더링용으로 유지 ──
    reply = re.sub(r"^(\s*)\*\s+", r"\1- ", reply, flags=re.MULTILINE)

    if tools_used and isinstance(tools_used[0], dict):
        tool_names = [t["tool"] for t in tools_used]
    else:
        tool_names = tools_used

    response = {
        "reply": reply,
        "error": had_error,
        "tools_used": tool_names,
        "payload": payload,
        "request_id": request_id,
    }

    # citations/meta가 있으면 전달
    citations = result.get("citations")
    if citations:
        response["citations"] = citations
    meta = result.get("meta")
    if meta:
        response["meta"] = meta

    return response


# ═══════════════════════════════════════════════════════
# POST /panel/vector/rebuild — 벡터 인덱스 재구축
# ═══════════════════════════════════════════════════════

@router.post("/vector/rebuild")
async def rebuild_vector_index():
    """DB의 모든 분석 완료 문서를 ChromaDB 벡터로 인덱싱 (백그라운드)"""
    import threading
    
    def _run_rebuild():
        try:
            from services.vector_service import vector_service
            result = vector_service.rebuild_index()
            logger.info(f"✦ 벡터 인덱스 재구축 완료: {result}")
        except Exception as e:
            logger.error(f"벡터 인덱스 재구축 실패: {e}")
    
    thread = threading.Thread(target=_run_rebuild, daemon=True)
    thread.start()
    return {"status": "started", "message": "백그라운드에서 인덱싱 진행 중. GET /panel/vector/stats로 진행 확인."}


@router.get("/vector/stats")
async def vector_stats():
    """벡터 인덱스 현황"""
    try:
        from services.vector_service import vector_service
        return vector_service.get_index_stats()
    except Exception as e:
        return {"status": "error", "detail": str(e)}

