"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Auth Service
사건의 지평선 (Event Horizon) — 인증 경계 관리 시스템
JWT + bcrypt 기반 해밀토니안 인증 경로
═══════════════════════════════════════════════════════
"""

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

try:
    from jose import jwt, JWTError
except ImportError:
    class JWTError(Exception):
        pass

    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    def _b64url_decode(data: str) -> bytes:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(data + padding)

    class _FallbackJWT:
        @staticmethod
        def encode(payload: dict, secret: str, algorithm: str = "HS256") -> str:
            if algorithm != "HS256":
                raise JWTError(f"Unsupported algorithm: {algorithm}")
            normalized = {}
            for key, value in payload.items():
                if isinstance(value, datetime):
                    normalized[key] = int(value.timestamp())
                else:
                    normalized[key] = value
            header = {"alg": algorithm, "typ": "JWT"}
            signing_input = ".".join(
                [
                    _b64url_encode(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
                    _b64url_encode(json.dumps(normalized, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
                ]
            )
            signature = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
            return f"{signing_input}.{_b64url_encode(signature)}"

        @staticmethod
        def decode(token: str, secret: str, algorithms: list[str] | None = None) -> dict:
            if algorithms and "HS256" not in algorithms:
                raise JWTError("Unsupported algorithms")
            parts = token.split(".")
            if len(parts) != 3:
                raise JWTError("Malformed token")
            signing_input = ".".join(parts[:2])
            expected_sig = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
            actual_sig = _b64url_decode(parts[2])
            if not hmac.compare_digest(expected_sig, actual_sig):
                raise JWTError("Invalid signature")
            payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
            exp = payload.get("exp")
            if exp is not None and float(exp) < datetime.now(timezone.utc).timestamp():
                raise JWTError("Token expired")
            return payload

    jwt = _FallbackJWT()

try:
    from passlib.context import CryptContext
except ImportError:
    try:
        import bcrypt
    except ImportError:
        bcrypt = None

    class CryptContext:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def hash(self, password: str) -> str:
            if bcrypt is not None:
                return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            salt = _b64url_encode(os.urandom(16))
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 390000)
            return f"pbkdf2_sha256${salt}${_b64url_encode(digest)}"

        def verify(self, plain_password: str, hashed_password: str) -> bool:
            if hashed_password.startswith("$2") and bcrypt is not None:
                return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
            if hashed_password.startswith("pbkdf2_sha256$"):
                try:
                    _, salt, digest = hashed_password.split("$", 2)
                    candidate = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), 390000)
                    return hmac.compare_digest(_b64url_encode(candidate), digest)
                except Exception:
                    return False
            return False

from config import settings
from database import get_db
from models.models import User
from schemas.schemas import TokenData


# ── 암호화 컨텍스트 (Encryption Context) ──
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Bearer 토큰 스키마 ──
security = HTTPBearer(auto_error=not settings.DEV_MODE)


# ═══════════════════════════════════════════════════════
# 비밀번호 해싱 유틸리티
# ═══════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """비밀번호 → bcrypt 해시 변환 (에너지 캡슐화)"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """비밀번호 검증 — 임계점(Critical Point) 인증"""
    return pwd_context.verify(plain_password, hashed_password)


# ═══════════════════════════════════════════════════════
# JWT 토큰 관리
# ═══════════════════════════════════════════════════════

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """JWT 액세스 토큰 생성 — 에너지 토큰 발행"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> TokenData:
    """JWT 토큰 디코딩 — 에너지 토큰 해독"""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        raw_user_id = payload.get("sub")
        email: str = payload.get("email")
        role: str = payload.get("role")
        try:
            user_id = int(raw_user_id) if raw_user_id is not None else None
        except (TypeError, ValueError):
            user_id = None

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="유효하지 않은 인증 토큰입니다."
            )

        return TokenData(user_id=user_id, email=email, role=role)

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰이 만료되었거나 유효하지 않습니다."
        )


def create_verification_token(email: str) -> str:
    """이메일 인증을 위한 시공간 제한 토큰 방출 (24시간)"""
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    to_encode = {"email": email, "type": "verification", "exp": expire}
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_email_token(token: str) -> str:
    """검증 토큰 해독 및 이메일 위상 추출"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "verification":
            raise HTTPException(status_code=400, detail="유효하지 않은 토큰 유형입니다.")
        email = payload.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="토큰 정보가 변질되었습니다.")
        return email
    except JWTError:
        raise HTTPException(status_code=400, detail="인증 토큰이 만료되었거나 유효하지 않습니다.")


def create_password_reset_token(email: str) -> str:
    """비밀번호 재설정을 위한 15분 임계점 토큰 방출"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode = {"email": email, "type": "password_reset", "exp": expire}
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_password_reset_token(token: str) -> str:
    """재설정 토큰 해독 및 이메일 위상 추출"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "password_reset":
            raise HTTPException(status_code=400, detail="유효하지 않은 토큰 유형입니다.")
        email = payload.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="토큰 정보가 변질되었습니다.")
        return email
    except JWTError:
        raise HTTPException(status_code=400, detail="토큰이 만료되었습니다. 다시 요청하십시오.")


def create_password_change_token(email: str, new_password_hash: str) -> str:
    """비밀번호 변경 인증용 15분 토큰 — 해싱된 새 비밀번호 포함"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode = {
        "email": email,
        "type": "password_change",
        "new_hash": new_password_hash,
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_password_change_token(token: str) -> dict:
    """비밀번호 변경 토큰 해독 — email + new_hash 반환"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "password_change":
            raise HTTPException(status_code=400, detail="유효하지 않은 토큰 유형입니다.")
        email = payload.get("email")
        new_hash = payload.get("new_hash")
        if not email or not new_hash:
            raise HTTPException(status_code=400, detail="토큰 정보가 변질되었습니다.")
        return {"email": email, "new_hash": new_hash}
    except JWTError:
        raise HTTPException(status_code=400, detail="인증 링크가 만료되었습니다. 비밀번호 변경을 다시 요청해주세요.")


def create_withdraw_token(email: str, user_id: int) -> str:
    """회원탈퇴 인증용 15분 토큰 — email + user_id 포함"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode = {
        "email": email,
        "user_id": user_id,
        "type": "withdraw",
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_withdraw_token(token: str) -> dict:
    """회원탈퇴 토큰 해독 — email + user_id 반환"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "withdraw":
            raise HTTPException(status_code=400, detail="유효하지 않은 토큰 유형입니다.")
        email = payload.get("email")
        user_id = payload.get("user_id")
        if not email or user_id is None:
            raise HTTPException(status_code=400, detail="토큰 정보가 변질되었습니다.")
        return {"email": email, "user_id": int(user_id)}
    except JWTError:
        raise HTTPException(status_code=400, detail="인증 링크가 만료되었습니다. 회원탈퇴를 다시 요청해주세요.")


# ═══════════════════════════════════════════════════════
# 의존성 주입 (FastAPI Depends)
# ═══════════════════════════════════════════════════════

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """현재 인증된 사용자 반환 — 사건의 지평선 통과"""

    # ── DEV_MODE: 인증 스킵 ──
    if settings.DEV_MODE:
        user = db.query(User).first()
        if user is None:
            # 개발용 사용자 자동 생성
            user = User(
                email="dev@civicflow.local",
                username="dev_user",
                password_hash=hash_password("dev1234"),
                role="admin",
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    # ── 정상 인증 경로 ──
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 필요합니다."
        )

    token_data = decode_token(credentials.credentials)

    user = db.query(User).filter(User.id == token_data.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자를 찾을 수 없습니다."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다."
        )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """관리자 역할 검증 — 상위 사건의 지평선"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다."
        )
    return current_user
