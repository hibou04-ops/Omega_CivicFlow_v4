"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Configuration Module
가변 메트릭스 (Variable Metrics) 관리 시스템
═══════════════════════════════════════════════════════
"""

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    """시스템 전역 설정 — 해밀토니안 최적화 파라미터"""

    # --- Database ---
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/civicflow"

    # --- JWT Auth ---
    JWT_SECRET_KEY: str = ""  # REQUIRED: set in .env
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24시간

    # --- Ollama LLM ---
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "exaone3.5:7.8b"
    OLLAMA_ANALYSIS_MODEL: str = "exaone3.5:7.8b"
    OLLAMA_AGENT_MODEL: str = "exaone3.5:7.8b"

    # --- vLLM (RunPod 파인튜닝 모델) ---
    VLLM_BASE_URL: str = ""  # 비어있으면 비활성화, .env에서 설정
    VLLM_MODEL: str = "civicflow"  # LoRA 모듈 이름

    # --- Upload & Data Directories ---
    # .env 에서 절대 경로로 오버라이드 권장. 기본값은 프로젝트 상대 경로.
    UPLOAD_DIR: str = "./data/uploads"
    CHROMADB_DIR: str = "./data/chroma_db"
    CHROMA_COLLECTION_NAME: str = "omega_documents_v3"
    DATASET_DIR: str = "./data/datasets"
    MAX_FILE_SIZE_MB: int = 700  # 600MB 대용량 문서 번들 지원

    # --- Email (SMTP) ---
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    FRONTEND_URL: str = "http://localhost:5173"

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- App ---
    APP_TITLE: str = "Omega CivicFlow"
    APP_VERSION: str = "1.0.0"
    APP_DESCRIPTION: str = "OCR → LLM 공공 민원 문서 자동 분석 시스템"
    DEV_MODE: bool = False  # True 시 인증 스킵 (개발/테스트용)

    # --- Vertex AI (The-Absolute Insight) ---
    GCP_PROJECT_ID: str = ""       # .env 에서 설정
    GCP_LOCATION: str = "us-central1"
    GCP_KEY_PATH: str = ""         # 서비스 계정 키 JSON 경로
    GEMINI_MODEL: str = "gemini-2.5-pro"
    INSIGHT_ENCRYPTION_KEY: str = ""

    # --- Omega-Prime Supervisor (Insight 감독 레이어, 별도 GCP 프로젝트 권장) ---
    SUPERVISOR_MODEL: str = "gemini-2.5-flash"
    SUPERVISOR_GCP_PROJECT_ID: str = ""
    SUPERVISOR_GCP_LOCATION: str = "us-central1"
    SUPERVISOR_GCP_KEY_PATH: str = ""

    # --- DART OpenAPI (한국 금융 공시 검색) ---
    DART_API_KEY: str = ""

    class Config:
        env_file = str(Path(__file__).parent / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"  # legacy .env 필드는 조용히 무시 → validation error 방지 (API 키 노출 차단)


settings = Settings()
