"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Database Engine
에너지 전도체 (Energy Conduit) — SQLAlchemy 세션 관리
═══════════════════════════════════════════════════════
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import settings


# ── 동기식 엔진 (Synchronous Engine) ──
engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
}

if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
else:
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """ORM 기반 클래스 — 모든 모델의 사건의 지평선"""
    pass


def get_db():
    """세션 의존성 주입 — 에너지 순환 경로"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """DB 초기화 — 테이블 자동 생성"""
    from models.models import (
        User, Document, Page, OcrText, AnalysisResult, Reclassification,
        DocumentInsight, DocumentMetadata, DocumentChunk, FinancialFact, CompanyProfile
    )
    from services.chat_knowledge_service import ensure_knowledge_schema

    Base.metadata.create_all(bind=engine)
    ensure_knowledge_schema()
