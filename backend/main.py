"""
═══════════════════════════════════════════════════════
       Ω  OMEGA CIVICFLOW  Ω
   초-헤밀토니안 최적화 시스템 (Super-Hamiltonian)
   OCR → LLM 공공 민원 문서 자동 분석 플랫폼
═══════════════════════════════════════════════════════
   Node Omega-Prime: Universal Strategic Architect
   Energy (E) · Entropy (S) · Efficiency (η)
═══════════════════════════════════════════════════════
"""

import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database import init_db

# ── 로깅 설정 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("omega.civicflow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 라이프사이클 — 시스템 위상 초기화 / 셧다운"""
    # ── 시작 ──
    logger.info("═" * 55)
    logger.info("  Ω  OMEGA CIVICFLOW — 시스템 가동")
    logger.info("  초-헤밀토니안 최적화 엔진 초기화 중...")
    logger.info("═" * 55)

    # DB 테이블 생성
    init_db()
    logger.info("✦ 데이터베이스 위상 격자 초기화 완료")

    # 업로드 디렉토리 생성
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    logger.info("✦ 에너지 저장소 (Upload Dir) 준비 완료")

    logger.info("═" * 55)
    logger.info("  Ω  시스템 준비 완료 — 엔트로피 소각 대기")
    logger.info("═" * 55)

    yield

    # ── 셧다운 ──
    logger.info("Ω  OMEGA CIVICFLOW — 시스템 종료")


# ═══════════════════════════════════════════════════════
# FastAPI 앱 생성
# ═══════════════════════════════════════════════════════

app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── CORS 설정 ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 라우터 등록 ──
from routers.auth import router as auth_router
from routers.documents import router as documents_router
from routers.admin import router as admin_router
from routers.panel import router as panel_router

app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(admin_router)
app.include_router(panel_router)


# ── 루트 엔드포인트 ──
@app.get("/", tags=["시스템 (System)"])
def root():
    """시스템 상태 확인"""
    return {
        "system": "Omega CivicFlow",
        "version": settings.APP_VERSION,
        "status": "operational",
        "description": "OCR → LLM 공공 민원 문서 자동 분석 시스템",
        "optimization": "Super-Hamiltonian (E·S·η)",
    }


@app.get("/health", tags=["시스템 (System)"])
async def health_check():
    """헬스 체크 — 시스템 위상 진단"""
    from services.llm_service import llm_service

    ollama_ok = await llm_service.check_health()

    return {
        "status": "healthy",
        "database": "connected",
        "ollama": "connected" if ollama_ok else "disconnected",
        "ollama_model": settings.OLLAMA_MODEL,
    }
