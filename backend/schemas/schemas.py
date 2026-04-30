"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Pydantic Schemas
인터페이스 경계 정의 (Interface Boundary Definition)
═══════════════════════════════════════════════════════
"""

import re
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field, field_validator


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

_PW_PATTERN = re.compile(
    r'^(?=.*[A-Za-z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>_\-+=/\\\[\];\'`~]).+$'
)


def _validate_password(v: str) -> str:
    if not _PW_PATTERN.match(v):
        raise ValueError(
            '비밀번호는 영문자·숫자·특수문자를 각각 1개 이상 포함해야 합니다.'
        )
    return v


# ═══════════════════════════════════════════════════════
# Auth Schemas
# ═══════════════════════════════════════════════════════

class UserCreate(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    username: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8, max_length=100)

    @field_validator('password')
    @classmethod
    def _pw(cls, v):
        return _validate_password(v)


class UserLogin(BaseModel):
    email: str
    password: str

class MasterRegisterRequest(BaseModel):
    email: str = Field(..., pattern=EMAIL_PATTERN, min_length=5, max_length=255)
    username: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8, max_length=100)
    master_key: str

    @field_validator('password')
    @classmethod
    def _pw(cls, v):
        return _validate_password(v)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None
    email: Optional[str] = None
    role: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None


class UserRoleUpdate(BaseModel):
    role: str = Field(..., pattern="^(user|admin)$")


class UserActiveUpdate(BaseModel):
    is_active: bool


# ═══════════════════════════════════════════════════════
# Email / Password Recovery Schemas
# ═══════════════════════════════════════════════════════

class VerifyEmailRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., pattern=EMAIL_PATTERN, min_length=5, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=100)

    @field_validator('new_password')
    @classmethod
    def _pw(cls, v):
        return _validate_password(v)


class PasswordChangeRequest(BaseModel):
    """개인정보수정 — 비밀번호 변경 요청 (이메일 인증 필요)"""
    new_password: str = Field(..., min_length=8, max_length=100)

    @field_validator('new_password')
    @classmethod
    def _pw(cls, v):
        return _validate_password(v)


class ConfirmPasswordChangeRequest(BaseModel):
    """이메일 인증 후 비밀번호 변경 확인"""
    token: str


class WithdrawRequest(BaseModel):
    """회원탈퇴 요청 — 비밀번호 재확인 + 확인 문구 입력 필수 → 이메일 인증 메일 발송"""
    password: str = Field(..., min_length=1, max_length=100)
    confirm_text: str = Field(..., min_length=1, max_length=50)


class ConfirmWithdrawRequest(BaseModel):
    """이메일 인증 후 회원탈퇴 최종 확인 — 토큰만 필요"""
    token: str


# ═══════════════════════════════════════════════════════
# Document Schemas
# ═══════════════════════════════════════════════════════

class DocumentResponse(BaseModel):
    id: int
    user_id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    report_path: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocumentUploadResponse(BaseModel):
    """업로드 + 분석 완료 응답 — 분석 결과 포함"""
    id: int
    user_id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    # 분석 결과 필드
    summary: Optional[str] = None
    category: Optional[str] = None
    financial_metrics: Optional[Any] = None
    insight_vectors: Optional[Any] = None
    evidence: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int


class BatchUploadResponse(BaseModel):
    """다중 파일 업로드 결과 (비동기)"""
    documents: List[dict]       # [{id, filename, status, task_id}]
    total: int
    task_ids: List[str] = []    # Celery 태스크 ID
    send_email: bool = False


# ═══════════════════════════════════════════════════════
# OCR Schemas
# ═══════════════════════════════════════════════════════

class OcrTextResponse(BaseModel):
    id: int
    page_number: Optional[int] = None
    raw_text: Optional[str] = None
    cleaned_text: Optional[str] = None
    confidence: float

    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════
# Analysis Schemas
# ═══════════════════════════════════════════════════════

class AnalysisResultResponse(BaseModel):
    id: int
    document_id: int
    summary: Optional[str] = None
    category: Optional[str] = None
    financial_metrics: Optional[str] = None
    insight_vectors: Optional[str] = None
    evidence: Optional[str] = None
    model_name: Optional[str] = None
    processing_time: float
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentDetailResponse(BaseModel):
    document: DocumentResponse
    ocr_texts: List[OcrTextResponse] = []
    analysis: Optional[AnalysisResultResponse] = None
    owner_username: Optional[str] = None
    company_name: Optional[str] = None  # raw_response에서 추출한 교정 회사명


# ═══════════════════════════════════════════════════════
# Reclassification Schemas
# ═══════════════════════════════════════════════════════

class ReclassifyRequest(BaseModel):
    new_category: str = Field(..., min_length=1, max_length=200)
    reason: Optional[str] = None


class ReclassificationResponse(BaseModel):
    id: int
    document_id: int
    reclassified_by: int
    previous_category: Optional[str] = None
    new_category: str
    reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════
# Dashboard Schemas
# ═══════════════════════════════════════════════════════

class CategoryStat(BaseModel):
    category: str
    count: int


class DashboardResponse(BaseModel):
    total_documents: int
    total_users: int
    total_analyzed: int
    total_pending: int
    category_stats: List[CategoryStat] = []
    recent_documents: List[DocumentResponse] = []


class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None
