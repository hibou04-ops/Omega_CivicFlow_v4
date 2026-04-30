"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Admin Router
상위 사건의 지평선 (Superior Event Horizon)
관리자 전용 API — 대시보드 · 회원관리 · 재분류
═══════════════════════════════════════════════════════
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models.models import User, Document, AnalysisResult, Reclassification
from schemas.schemas import (
    UserResponse, UserActiveUpdate,
    DashboardResponse, CategoryStat, DocumentResponse,
    DocumentListResponse, ReclassifyRequest,
    ReclassificationResponse, MessageResponse
)
from services.auth_service import require_admin

router = APIRouter(prefix="/admin", tags=["관리자 (Admin)"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    관리자 대시보드 — 시스템 위상 모니터링
    전체 문서 현황, 카테고리 분포, 최근 업로드
    """
    total_documents = db.query(func.count(Document.id)).scalar() or 0
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_analyzed = (
        db.query(func.count(Document.id))
        .filter(Document.status == "analyzed")
        .scalar() or 0
    )
    total_pending = (
        db.query(func.count(Document.id))
        .filter(Document.status.in_(["uploaded", "ocr_done"]))
        .scalar() or 0
    )

    # 카테고리별 통계
    category_rows = (
        db.query(AnalysisResult.category, func.count(AnalysisResult.id))
        .group_by(AnalysisResult.category)
        .all()
    )
    category_stats = [
        CategoryStat(category=cat or "미분류", count=cnt)
        for cat, cnt in category_rows
    ]

    # 최근 업로드 10건
    recent_docs = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .limit(10)
        .all()
    )

    return DashboardResponse(
        total_documents=total_documents,
        total_users=total_users,
        total_analyzed=total_analyzed,
        total_pending=total_pending,
        category_stats=category_stats,
        recent_documents=recent_docs,
    )


@router.get("/documents", response_model=DocumentListResponse)
def list_all_documents(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """전체 문서 목록 — 관리자 전수 조회"""
    docs = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .all()
    )
    return DocumentListResponse(documents=docs, total=len(docs))


@router.get("/documents/by-category")
def list_documents_by_category(
    category: str = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """카테고리별 문서 목록 — 관리자 전체 조회 (카테고리 포함)"""
    if not category or category == "전체":
        docs = (
            db.query(Document)
            .order_by(Document.created_at.desc())
            .all()
        )
    else:
        docs = (
            db.query(Document)
            .join(AnalysisResult, AnalysisResult.document_id == Document.id)
            .filter(AnalysisResult.category == category)
            .order_by(Document.created_at.desc())
            .all()
        )

    # 각 문서의 카테고리를 AnalysisResult에서 조회
    doc_ids = [d.id for d in docs]
    if doc_ids:
        categories = dict(
            db.query(AnalysisResult.document_id, AnalysisResult.category)
            .filter(AnalysisResult.document_id.in_(doc_ids))
            .all()
        )
    else:
        categories = {}

    result = []
    for doc in docs:
        d = {
            "id": doc.id, "user_id": doc.user_id,
            "filename": doc.filename, "file_type": doc.file_type,
            "file_size": doc.file_size, "status": doc.status,
            "report_path": doc.report_path,
            "created_at": doc.created_at, "updated_at": doc.updated_at,
            "category": categories.get(doc.id, category if category != "전체" else None),
        }
        result.append(d)

    return {"documents": result, "total": len(result)}


@router.get("/users", response_model=list[UserResponse])
def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """전체 회원 목록 — 관리자 전용"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return users


@router.patch("/users/{user_id}/active", response_model=UserResponse)
def update_user_active(
    user_id: int,
    active_data: UserActiveUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """계정 활성/비활성화"""
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    if target_user.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="자신의 계정 상태는 변경할 수 없습니다."
        )

    target_user.is_active = active_data.is_active
    db.commit()
    db.refresh(target_user)

    return target_user


@router.post("/documents/{document_id}/reclassify", response_model=ReclassificationResponse)
def reclassify_document(
    document_id: int,
    request: ReclassifyRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    수동 재분류 — 위상 보정 (Topological Correction)
    관리자가 LLM 분류 결과를 수정
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

    # 현재 분석 결과 조회
    current_analysis = (
        db.query(AnalysisResult)
        .filter(AnalysisResult.document_id == document_id)
        .order_by(AnalysisResult.created_at.desc())
        .first()
    )

    previous_category = current_analysis.category if current_analysis else None

    # 재분류 이력 기록
    reclassification = Reclassification(
        document_id=document_id,
        reclassified_by=admin.id,
        previous_category=previous_category,
        new_category=request.new_category,
        reason=request.reason,
    )
    db.add(reclassification)

    # 분석 결과 갱신
    if current_analysis:
        current_analysis.category = request.new_category

    db.commit()
    db.refresh(reclassification)

    return reclassification


@router.get(
    "/documents/{document_id}/reclassifications",
    response_model=list[ReclassificationResponse],
)
def get_reclassification_history(
    document_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """재분류 이력 조회"""
    records = (
        db.query(Reclassification)
        .filter(Reclassification.document_id == document_id)
        .order_by(Reclassification.created_at.desc())
        .all()
    )
    return records
