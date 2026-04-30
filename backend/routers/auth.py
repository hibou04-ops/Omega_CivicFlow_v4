"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Auth Router
사건의 지평선 (Event Horizon) — 인증 API 게이트웨이
═══════════════════════════════════════════════════════
"""

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from database import get_db
from models.models import User
from schemas.schemas import (
    UserCreate, UserLogin, Token, UserResponse,
    UserUpdate, MessageResponse, VerifyEmailRequest,
    ForgotPasswordRequest, ResetPasswordRequest, MasterRegisterRequest,
    PasswordChangeRequest, ConfirmPasswordChangeRequest,
    WithdrawRequest, ConfirmWithdrawRequest,
)
from services.auth_service import (
    hash_password, verify_password,
    create_access_token, get_current_user,
    create_verification_token, verify_email_token,
    create_password_reset_token, verify_password_reset_token,
    create_password_change_token, verify_password_change_token,
    create_withdraw_token, verify_withdraw_token,
)
from services.email_service import (
    send_verification_email, send_password_reset_email,
    send_password_change_email, send_withdraw_confirmation_email,
)

router = APIRouter(prefix="/auth", tags=["인증 (Authentication)"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    회원가입 — 새로운 노드 등록
    이메일 중복 검사 + bcrypt 해싱 + 검증 이메일 발송
    """
    # 이메일 중복 검사
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 등록된 이메일 주소입니다."
        )

    # 유저 생성 (초기 위상은 is_verified=False)
    new_user = User(
        email=user_data.email,
        username=user_data.username,
        password_hash=hash_password(user_data.password),
        role="user",
        is_active=True,
        is_verified=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 이메일 전송용 토큰 생성 및 백그라운드 발송 처리 (.env 세팅이 없으면 터미널에 Mocking 출력)
    token = create_verification_token(new_user.email)
    background_tasks.add_task(send_verification_email, new_user.email, token)

    return new_user


@router.post("/master-register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def master_register(data: MasterRegisterRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    마스터 계정 생성 (Admin 도메인 전용 게이트웨이)
    마스터 키가 일치해야만 role='admin'으로 즉시 생성됩니다.
    """
    if data.master_key != "OMEGA_PRIME_2026":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="마스터 키가 일치하지 않습니다. 접근이 거부되었습니다."
        )

    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 등록된 이메일 주소입니다."
        )

    new_admin = User(
        email=data.email,
        username=data.username,
        password_hash=hash_password(data.password),
        role="admin",
        is_active=True,
        is_verified=False,
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)

    token = create_verification_token(new_admin.email)
    background_tasks.add_task(send_verification_email, new_admin.email, token)

    return new_admin


@router.post("/verify-email", response_model=MessageResponse)
def verify_email(data: VerifyEmailRequest, db: Session = Depends(get_db)):
    """이메일 검증 — 파동 함수 붕괴(활성화)"""
    email = verify_email_token(data.token)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if user.is_verified:
        return {"message": "이미 이메일 인증이 완료되었습니다."}
    
    user.is_verified = True
    db.commit()
    return {"message": "이메일 인증이 성공적으로 완료되었습니다."}


@router.post("/login", response_model=Token)
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    """
    로그인 — JWT 액세스 토큰 발급
    에너지 토큰 생성 (Energy Token Emission)
    """
    user = db.query(User).filter(User.email == login_data.email).first()

    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다. 관리자에게 문의하세요."
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="이메일 인증이 완료되지 않았습니다. 이메일을 확인해주세요."
        )

    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role}
    )

    return Token(access_token=token)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """현재 로그인 사용자 정보"""
    return current_user


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(data: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """비밀번호 찾기 — 재설정 링크 이메일 발송"""
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        # 보안을 위해 유저 존재 여부를 명시적으로 알리지 않고 항상 성공 반환
        return {"message": "입력하신 이메일로 비밀번호 재설정 링크를 전송했습니다. (가입된 계정인 경우)"}
    
    token = create_password_reset_token(user.email)
    background_tasks.add_task(send_password_reset_email, user.email, token)
    
    return {"message": "입력하신 이메일로 비밀번호 재설정 링크를 전송했습니다. (가입된 계정인 경우)"}


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """새 비밀번호 설정 — 해시 업데이트"""
    email = verify_password_reset_token(data.token)
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"message": "비밀번호가 성공적으로 변경되었습니다. 새로운 비밀번호로 로그인해주세요."}



@router.patch("/me", response_model=UserResponse)
def update_me(
    update_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    내 정보 수정 — 닉네임만 변경 가능
    비밀번호 변경은 이메일 인증을 통해 별도 처리합니다.
    """
    if update_data.username is not None:
        current_user.username = update_data.username

    # 비밀번호는 이메일 인증 흐름으로 변경 (직접 변경 차단)
    if update_data.password is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="비밀번호는 이메일 인증을 통해 변경해야 합니다. /auth/request-password-change를 사용하세요."
        )

    db.commit()
    db.refresh(current_user)

    return current_user


@router.post("/request-password-change", response_model=MessageResponse)
def request_password_change(
    data: PasswordChangeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    비밀번호 변경 요청 — 이메일 인증 링크 발송
    새 비밀번호를 해싱하여 토큰에 포함, 이메일 인증 후 적용
    """
    new_hash = hash_password(data.new_password)
    token = create_password_change_token(current_user.email, new_hash)
    background_tasks.add_task(send_password_change_email, current_user.email, token)

    return {
        "message": f"비밀번호 변경 인증 메일이 {current_user.email}으로 전송되었습니다. 15분 내에 인증해주세요."
    }


@router.post("/confirm-password-change", response_model=MessageResponse)
def confirm_password_change(
    data: ConfirmPasswordChangeRequest,
    db: Session = Depends(get_db),
):
    """
    비밀번호 변경 확인 — 이메일 인증 토큰 검증 후 비밀번호 적용
    """
    result = verify_password_change_token(data.token)
    user = db.query(User).filter(User.email == result["email"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    user.password_hash = result["new_hash"]
    db.commit()

    return {"message": "비밀번호가 성공적으로 변경되었습니다. 새로운 비밀번호로 로그인해주세요."}


WITHDRAW_CONFIRM_PHRASE = "탈퇴합니다"


@router.post("/request-withdraw", response_model=MessageResponse)
def request_withdraw(
    data: WithdrawRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    회원탈퇴 1단계 — 비밀번호 + 확인 문구 검증 후 인증 메일 발송
    실제 탈퇴는 메일의 링크를 클릭한 시점에 처리됩니다 (15분 토큰).
    """
    if current_user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 계정은 셀프 탈퇴할 수 없습니다. 다른 관리자에게 권한 이전을 요청하세요."
        )

    if not verify_password(data.password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비밀번호가 일치하지 않습니다."
        )

    if data.confirm_text.strip() != WITHDRAW_CONFIRM_PHRASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"확인 문구가 일치하지 않습니다. '{WITHDRAW_CONFIRM_PHRASE}'를 정확히 입력해주세요."
        )

    token = create_withdraw_token(current_user.email, current_user.id)
    background_tasks.add_task(send_withdraw_confirmation_email, current_user.email, token)

    return {
        "message": f"회원탈퇴 인증 메일이 {current_user.email}으로 전송되었습니다. 15분 내에 메일의 링크를 클릭해 최종 확정해주세요."
    }


@router.post("/confirm-withdraw", response_model=MessageResponse)
def confirm_withdraw(
    data: ConfirmWithdrawRequest,
    db: Session = Depends(get_db),
):
    """
    회원탈퇴 2단계 — 이메일 토큰 검증 후 PII 익명화 + 비활성화
    PIPA(개인정보보호법) 준수: 이메일/사용자명/비밀번호 해시 즉시 익명화, 복구 불가.
    문서/분석 결과는 익명화된 계정에 연결된 채로 보존됩니다.
    """
    payload = verify_withdraw_token(data.token)
    user = db.query(User).filter(User.id == payload["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    if not user.is_active:
        return {"message": "이미 탈퇴 처리된 계정입니다."}

    if user.email != payload["email"]:
        raise HTTPException(
            status_code=400,
            detail="토큰의 이메일과 계정의 이메일이 일치하지 않습니다. 이미 다른 작업이 진행되었을 수 있습니다."
        )

    if user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 계정은 셀프 탈퇴할 수 없습니다."
        )

    user_id = user.id
    timestamp = int(datetime.utcnow().timestamp())
    user.email = f"withdrawn_{user_id}_{timestamp}@deleted.local"
    user.username = f"탈퇴회원_{user_id}"
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.is_active = False
    user.is_verified = False

    db.commit()

    return {"message": "회원탈퇴가 완료되었습니다. 그동안 이용해주셔서 감사합니다."}

