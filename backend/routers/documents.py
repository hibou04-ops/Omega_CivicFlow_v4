"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Documents Router
에너지 캐리어 관리 (Energy Carrier Management)
문서 업로드 · OCR · LLM 분석 파이프라인
═══════════════════════════════════════════════════════
"""

import os
import re
import uuid
import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from typing import List
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.models import User, Document, Page, OcrText, AnalysisResult, DocumentInsight
from schemas.schemas import (
    DocumentResponse, DocumentUploadResponse, DocumentListResponse,
    BatchUploadResponse, DocumentDetailResponse, OcrTextResponse,
    AnalysisResultResponse, MessageResponse
)
from services.auth_service import get_current_user
from services.ocr_service import ocr_engine
from services.llm_service import llm_service
from services.vlm_service import vlm_service
from services.text_preprocessor import text_preprocessor
from services.email_service import send_analysis_result_email
from services.chat_knowledge_service import upsert_document_knowledge
from services.vector_service import vector_service

logger = logging.getLogger(__name__)


def _auto_embed_document(db, doc, analysis: dict):
    """분석 완료 문서를 자동 임베딩 (ChromaDB → Omega Cortex RAG)"""
    try:
        # 임베딩 대상 텍스트 조합: summary + key_points + evidence
        parts = []
        if analysis.get("summary"):
            parts.append(analysis["summary"])
        kp = analysis.get("key_points", [])
        if isinstance(kp, list):
            parts.extend(str(p) for p in kp)
        if analysis.get("evidence"):
            parts.append(str(analysis["evidence"]))
        if analysis.get("financial_metrics"):
            parts.append(str(analysis["financial_metrics"]))
        if analysis.get("insight_vectors"):
            parts.append(str(analysis["insight_vectors"]))

        embed_text = "\n".join(parts)
        if len(embed_text) < 30:
            return

        company = analysis.get("company_name", "")
        category = analysis.get("category", "")

        n = vector_service.index_document(
            doc_id=doc.id,
            filename=doc.filename,
            text=embed_text,
            category=category,
            company=company,
            user_id=getattr(doc, "user_id", 0),
        )
        if n > 0:
            logger.info(f"  └─ 🧠 자동 임베딩 완료: #{doc.id} → {n}청크")
    except Exception as e:
        logger.warning(f"  └─ 임베딩 실패 (무시): {e}")


def _sync_chat_knowledge(db, doc, analysis_record=None):
    """구조화 지식층 upsert + 청크 인덱싱"""
    try:
        latest_analysis = analysis_record
        if latest_analysis is None:
            latest_analysis = (
                db.query(AnalysisResult)
                .filter(AnalysisResult.document_id == doc.id)
                .order_by(AnalysisResult.id.desc())
                .first()
            )
        if latest_analysis is None:
            return
        ocr_rows = db.query(OcrText).filter(OcrText.document_id == doc.id).all()
        upsert_document_knowledge(db, doc, latest_analysis=latest_analysis, ocr_rows=ocr_rows)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"지식 계층 동기화 실패 — 문서 #{doc.id}: {e}")


async def _analyze_with_best_engine(text: str) -> dict:
    """
    분석 엔진: Qwen(로컬) → vLLM fallback
    분석 후 중국어 텍스트를 한국어로 자동 번역 (QLoRA 학습 데이터 수집 겸용)
    """
    result = None

    # 1순위: Ollama (로컬 Qwen — 빠르고 상세)
    try:
        logger.info("▶ Ollama 엔진 사용 (로컬 Qwen)")
        result = await llm_service.analyze_document(text)
        if result and result.get("_is_error"):
            result = None
            logger.warning("⚠ Ollama 분석 실패, vLLM fallback")
    except Exception as e:
        logger.warning(f"⚠ Ollama 예외, vLLM fallback: {e}")

    # 2순위: vLLM (파인튜닝 모델)
    if result is None and await vlm_service.check_health():
        logger.info("▶ vLLM 엔진 사용 (파인튜닝 모델)")
        result = await vlm_service.analyze_text(text)
        if result and result.get("_is_error"):
            result = None

    if result is None:
        return {"_is_error": True, "summary": "모든 분석 엔진 실패"}

    # ── 후처리: 텍스트 정제 + 종목명 정규화 ──
    result = _clean_and_normalize_result(result)
    return result


# ═══════════════════════════════════════════════════════════════
# 숫자 단위 교정 — financial_facts ground truth 기반
# LLM이 "47,812억원"이라 환각한 걸 → "478억원"으로 교정 (GT: 47,812,373,057원)
# ═══════════════════════════════════════════════════════════════

_KOREAN_UNITS = {'조': 1_000_000_000_000, '억': 100_000_000, '만': 10_000, '천': 1_000}

_METRIC_KW_TO_FACT = {
    '매출액': ['revenue', 'sales'],
    '영업이익': ['operating_profit', 'operating_income'],
    '영업손실': ['operating_profit', 'operating_loss'],
    '당기순이익': ['net_income', 'net_profit'],
    '당기순손실': ['net_income', 'net_loss'],
    '자산총계': ['total_assets'],
    '총자산': ['total_assets'],
    '부채총계': ['total_liabilities'],
    '총부채': ['total_liabilities'],
    '자본총계': ['equity', 'total_equity'],
    '총자본': ['equity', 'total_equity'],
}


def _parse_korean_amount(num_str: str, unit_str: str) -> float:
    """'47,812' + '억' → 4,781,200,000,000"""
    try:
        num = float(num_str.replace(',', '').replace(' ', ''))
    except (ValueError, AttributeError):
        return 0
    multiplier = _KOREAN_UNITS.get(unit_str, 1)
    return num * multiplier


def _format_krw_korean(value: float) -> str:
    """원화 → 한국 단위 (억/조). PDF 서비스 함수의 경량 복제."""
    if value is None:
        return "-"
    abs_v = abs(float(value))
    sign = "-" if value < 0 else ""
    if abs_v >= 1_000_000_000_000:
        return f"약 {sign}{abs_v / 1_000_000_000_000:.2f}조원"
    elif abs_v >= 100_000_000:
        return f"약 {sign}{abs_v / 100_000_000:,.0f}억원"
    elif abs_v >= 10_000:
        return f"약 {sign}{abs_v / 10_000:,.0f}만원"
    else:
        return f"{sign}{int(abs_v):,}원"


def correct_financial_numbers(result: dict, document_id: int) -> dict:
    """LLM 출력 summary의 재무 숫자를 financial_facts ground truth로 교정.

    사용 위치: upload_document, reanalyze_document 등 LLM 분석 직후.
    동작: summary 텍스트에서 '매출액 47,812억원' 같은 패턴을 찾고,
          financial_facts와 비교해 5배 이상 차이 나면 정확한 값으로 치환.
    """
    summary = result.get('summary', '')
    if not summary or not document_id:
        return result

    # financial_facts 조회
    try:
        from database import SessionLocal
        from sqlalchemy import text as sql_text
        db = SessionLocal()
        try:
            rows = db.execute(sql_text("""
                SELECT metric_name, metric_value_num FROM financial_facts
                WHERE document_id = :doc_id AND metric_value_num IS NOT NULL
            """), {"doc_id": document_id}).fetchall()
        finally:
            db.close()
    except Exception:
        return result

    if not rows:
        return result

    facts = {r[0]: float(r[1]) for r in rows}
    corrected = summary
    corrections_made = 0

    for keyword, metric_names in _METRIC_KW_TO_FACT.items():
        if keyword not in corrected:
            continue

        # ground truth 값 찾기
        gt_value = None
        for mn in metric_names:
            if mn in facts:
                gt_value = facts[mn]
                break
        if gt_value is None:
            continue

        # summary에서 "[keyword] ... [숫자][조/억/만]원" 패턴 찾기
        # 예: "매출액은 전년 대비 ... 47,812억원을 기록"
        pat = re.compile(
            rf'({re.escape(keyword)}[^.]*?)'    # keyword ~ 문장 중간
            rf'([+-]?\s*[\d,]+\.?\d*)\s*'       # 숫자 (콤마, 소수점 포함)
            rf'(조|억|만)\s*원',                   # 단위
        )

        for m in pat.finditer(corrected):
            num_str = m.group(2).replace(' ', '')
            unit_str = m.group(3)

            parsed_value = _parse_korean_amount(num_str, unit_str)
            if parsed_value == 0:
                continue

            # ground truth와 비교 (절대값 기준)
            gt_abs = abs(gt_value)
            parsed_abs = abs(parsed_value)

            if gt_abs == 0:
                continue

            ratio = parsed_abs / gt_abs

            if ratio > 5 or ratio < 0.2:
                # 5배 이상 차이 → 교정 필요
                correct_str = _format_krw_korean(gt_value)
                old_match = f"{num_str}{unit_str}원"
                corrected = corrected.replace(old_match, correct_str, 1)
                corrections_made += 1
                logger.info(
                    f"  ├─ 숫자 교정: '{keyword} {old_match}' → '{correct_str}' "
                    f"(GT: {gt_value:,.0f}, ratio: {ratio:.1f}x)"
                )

    if corrections_made > 0:
        result['summary'] = corrected
        result['_numbers_corrected'] = corrections_made
        logger.info(f"  └─ 총 {corrections_made}건 숫자 교정 완료")

    return result


# 메타텍스트 누출 패턴 — SYSTEM_PROMPT의 지시문/마커가 출력에 포함된 경우 제거
_META_TEXT_PATTERNS = [
    re.compile(r'【[^】]*?】\s*'),                                   # 【필수 구조 — 최소 10문장】
    re.compile(r'^\s*★\s*[^\n]*\n', re.MULTILINE),                 # ★로 시작하는 줄
    re.compile(r'\[(?:ROLE|규칙|지시|출력|JSON|절대 규칙|노이즈|수치 밀도|분석 절차)[^\]]*\]\s*[^\n]*'),  # [ROLE], [규칙] 등
    re.compile(r'^\s*\[[A-Z][A-Z\s]+\][^\n]*\n', re.MULTILINE),    # [STEP 1], [PHASE 2] 같은 영문 대문자 라벨
]

# 띄어쓰기/형식 깨짐 패턴 (OCR 잔재 + LLM 출력 형식 문제)
_SPACING_FIX_PATTERNS = [
    # 한국어 종결어미 — 모든 ~습니다/~습니까 케이스 (있습니, 했습니, 됐습니, 되었습니, 옵니, 갑니 등 모두)
    (re.compile(r'습니\s+다'), '습니다'),
    (re.compile(r'습니\s+까'), '습니까'),
    (re.compile(r'(?<=[가-힣])니\s+다(?=[\s.,!?)\]]|$)'), '니다'),  # 입니/합니/됩니 단독 케이스 ("입니 다.")
    # 숫자/단위 형식 깨짐
    (re.compile(r'(\d+)\.\s+(\d+)'), r'\1.\2'),     # "21. 6%" → "21.6%"
    (re.compile(r'(\d+),\s+(\d{3})'), r'\1,\2'),    # "1, 234" → "1,234"
    (re.compile(r'(\d+)\s+%'), r'\1%'),              # "10 %" → "10%"
    (re.compile(r'(\d+)\s+(원|억|조|만|천)'), r'\1\2'),  # "100 억" → "100억"
    # 구두점 앞 공백
    (re.compile(r'\s+([.,)])'), r'\1'),              # " ." → "."
    # 공백 정리
    (re.compile(r' {2,}'), ' '),                     # 이중 공백
    (re.compile(r'\n{3,}'), '\n\n'),                 # 3+ 개 줄바꿈
]


def _clean_llm_text(text: str) -> str:
    """LLM 출력에서 메타텍스트 누출 + 띄어쓰기 깨짐 정제."""
    if not text or not isinstance(text, str):
        return text
    for pat in _META_TEXT_PATTERNS:
        text = pat.sub('', text)
    for pat, repl in _SPACING_FIX_PATTERNS:
        text = pat.sub(repl, text)
    return text.strip()


def _clean_and_normalize_result(result: dict) -> dict:
    """LLM 분석 결과 후처리: 텍스트 정제 + 종목명 정규화.

    1. 메타텍스트 누출 제거 (【…】, ★, [ROLE] 등)
    2. 띄어쓰기/소수점 깨짐 수정
    3. 종목명 정규화 (에스케이하이닉스 → SK하이닉스)
    """
    try:
        from services.stock_name_normalizer import normalize_text_company_names, normalize_company_name
    except ImportError:
        normalize_text_company_names = lambda x: x
        normalize_company_name = lambda x: x

    text_fields = ["summary", "evidence", "insight_vectors", "financial_metrics"]
    for field in text_fields:
        v = result.get(field)
        if isinstance(v, str) and v:
            v = _clean_llm_text(v)
            v = normalize_text_company_names(v)
            result[field] = v

    kps = result.get("key_points", [])
    if isinstance(kps, list):
        new_kps = []
        for kp in kps:
            if isinstance(kp, str):
                kp = _clean_llm_text(kp)
                kp = normalize_text_company_names(kp)
            new_kps.append(kp)
        result["key_points"] = new_kps

    cn = result.get("company_name", "")
    if cn:
        result["company_name"] = normalize_company_name(cn)

    return result


router = APIRouter(prefix="/documents", tags=["문서 관리 (Documents)"])


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    문서 업로드 + OCR + LLM 분석 파이프라인
    ═══════════════════════════════════════════
    1. 파일 저장 (에너지 주입)
    2. OCR 텍스트 추출 (엔트로피 소각)
    3. LLM 분석 (해밀토니안 최적화)
    4. 결과 DB 저장
    """
    # 파일 형식 검증 — DART ZIP(.zip.pdf) 및 XBRL/XML 허용
    allowed_types = {
        "application/pdf", "image/jpeg", "image/png", "image/jpg",
        "application/xml", "text/xml", "application/zip",
        "application/x-zip-compressed", "application/octet-stream",
        "text/html", "application/xhtml+xml",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    # .zip.pdf 같은 이중 확장자를 브라우저가 application/pdf로 보낼 수 있음 → 통과
    # .html 파일은 DART 공시 원본 형태로 자주 사용됨
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"지원하지 않는 파일 형식입니다. (지원: PDF, HTML, JPG, PNG, XBRL, XML, ZIP)"
        )

    # 파일 확장자 추출
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
    file_type = (
        "pdf" if ext == "pdf"
        else "html" if ext in ("html", "htm")
        else "xml" if ext in ("xml", "xbrl", "xsd")
        else "xls" if ext in ("xls", "xlsx")
        else "zip" if ext == "zip"
        else ext
    )

    # 저장 경로 생성
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # ── 중복 업로드 감지 (같은 유저 + 같은 파일명 + analyzed 상태) ──
    existing_doc = (
        db.query(Document)
        .filter(
            Document.user_id == current_user.id,
            Document.filename == file.filename,
            Document.status == "analyzed",
        )
        .first()
    )
    if existing_doc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"이미 업로드되어 분석된 자료입니다. "
                f"(문서 ID: #{existing_doc.id}, "
                f"업로드일: {existing_doc.created_at.strftime('%Y-%m-%d %H:%M')})"
            ),
        )

    unique_id = str(uuid.uuid4())[:8]
    safe_filename = f"{unique_id}_{file.filename}"
    file_path = upload_dir / safe_filename

    # 파일 저장
    content = await file.read()
    file_size = len(content)

    max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"파일 크기가 {settings.MAX_FILE_SIZE_MB}MB를 초과합니다."
        )

    with open(file_path, "wb") as f:
        f.write(content)

    # DB에 문서 레코드 생성
    doc = Document(
        user_id=current_user.id,
        filename=file.filename,
        file_path=str(file_path),
        file_type=file_type,
        file_size=file_size,
        status="uploaded",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # ── OCR 파이프라인 (엔트로피 소각) ──
    try:
        if file_type == "pdf":
            page_dir = upload_dir / f"pages_{doc.id}"
            page_dir.mkdir(parents=True, exist_ok=True)

            ocr_results = ocr_engine.extract_text_from_pdf(
                str(file_path), str(page_dir)
            )

            all_text_parts = []
            pages_for_preprocess = []  # Phase 3: 전처리기용 (page_num, text) 수집
            for page_num, text, confidence in ocr_results:
                page = Page(
                    document_id=doc.id,
                    page_number=page_num,
                    image_path=str(page_dir / f"page_{page_num}.png"),
                )
                db.add(page)
                db.flush()

                cleaned = ocr_engine.clean_text(text)
                ocr_text = OcrText(
                    document_id=doc.id,
                    page_id=page.id,
                    raw_text=text,
                    cleaned_text=cleaned,
                    confidence=confidence,
                )
                db.add(ocr_text)
                all_text_parts.append(cleaned)
                pages_for_preprocess.append((page_num, cleaned))

            # Phase 3: 구조화 전처리 (섹션 태깅 + 표 구조 복원)
            try:
                full_text = text_preprocessor.preprocess(pages_for_preprocess)
            except Exception as preprocess_err:
                logger.warning(f"전처리 fallback — 원본 텍스트 사용: {preprocess_err}")
                full_text = "\n\n".join(all_text_parts)
        elif file_type == "html":
            # HTML 파일 — DART 공시 원본 텍스트 추출 (OCR 불필요)
            try:
                from bs4 import BeautifulSoup
                import re as _re
                # DART HTML은 euc-kr 인코딩 사용 → 자동 감지
                charset_match = _re.search(rb'charset=(["\']?)([a-zA-Z0-9_-]+)', content[:1000])
                encoding = charset_match.group(2).decode('ascii') if charset_match else 'utf-8'
                try:
                    html_content = content.decode(encoding, errors='replace')
                except (UnicodeDecodeError, LookupError):
                    html_content = content.decode('euc-kr', errors='replace')
                soup = BeautifulSoup(html_content, "html.parser")
                for tag in soup(["script", "style", "meta", "link"]):
                    tag.decompose()
                raw_text = soup.get_text(separator="\n", strip=True)
            except Exception:
                try:
                    raw_text = content.decode('euc-kr', errors='replace')
                except Exception:
                    raw_text = content.decode('utf-8', errors='replace')

            cleaned = ocr_engine.clean_text(raw_text)

            page = Page(
                document_id=doc.id,
                page_number=1,
                image_path=str(file_path),
            )
            db.add(page)
            db.flush()

            ocr_text_obj = OcrText(
                document_id=doc.id,
                page_id=page.id,
                raw_text=raw_text[:50000],
                cleaned_text=cleaned[:50000],
                confidence=0.99,
            )
            db.add(ocr_text_obj)
            full_text = cleaned
        elif file_type == "zip":
            # DART XBRL ZIP 번들 — 한국어 레이블 + 재무 데이터 추출
            from services.dart_file_parser import extract_text_from_dart_zip
            raw_text = extract_text_from_dart_zip(content, file.filename)
            if not raw_text:
                raw_text = "(ZIP 데이터 추출 실패)"
            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=str(file_path))
            db.add(page)
            db.flush()
            ocr_text_obj = OcrText(
                document_id=doc.id, page_id=page.id,
                raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95,
            )
            db.add(ocr_text_obj)
            full_text = cleaned
        elif file_type == "xls":
            # XLS/XLSX 재무제표 — Excel 파싱
            from services.dart_file_parser import extract_text_from_xls
            raw_text = extract_text_from_xls(content, file.filename)
            if not raw_text:
                raw_text = "(Excel 데이터 추출 실패)"
            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=str(file_path))
            db.add(page)
            db.flush()
            ocr_text_obj = OcrText(
                document_id=doc.id, page_id=page.id,
                raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95,
            )
            db.add(ocr_text_obj)
            full_text = cleaned
        elif file_type in ("xml", "xbrl", "xsd"):
            # XBRL/XSD/XML — 구조화 텍스트 추출
            try:
                from bs4 import BeautifulSoup
                try:
                    xml_content = content.decode('utf-8', errors='replace')
                except Exception:
                    xml_content = content.decode('euc-kr', errors='replace')
                soup = BeautifulSoup(xml_content, "lxml-xml")
                # XBRL: 의미있는 텍스트 노드만 추출
                texts = []
                for tag in soup.find_all(True):
                    if tag.string and tag.string.strip():
                        tag_name = tag.name.split(':')[-1] if ':' in tag.name else tag.name
                        texts.append(f"{tag_name}: {tag.string.strip()}")
                raw_text = "\n".join(texts) if texts else soup.get_text(separator="\n", strip=True)
            except Exception:
                raw_text = content.decode('utf-8', errors='replace')

            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=str(file_path))
            db.add(page)
            db.flush()
            ocr_text = OcrText(
                document_id=doc.id, page_id=page.id,
                raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95,
            )
            db.add(ocr_text)
            full_text = cleaned
        else:
            # 이미지 파일 직접 OCR
            text, confidence = ocr_engine.extract_text_from_image(str(file_path))
            cleaned = ocr_engine.clean_text(text)

            page = Page(
                document_id=doc.id,
                page_number=1,
                image_path=str(file_path),
            )
            db.add(page)
            db.flush()

            ocr_text = OcrText(
                document_id=doc.id,
                page_id=page.id,
                raw_text=text,
                cleaned_text=cleaned,
                confidence=confidence,
            )
            db.add(ocr_text)
            full_text = cleaned

        doc.status = "ocr_done"
        db.commit()

        logger.info(f"✦ OCR 완료 — 문서 #{doc.id} '{doc.filename}'")

    except Exception as e:
        doc.status = "failed"
        db.commit()
        logger.error(f"OCR 실패 — 문서 #{doc.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OCR 처리 중 오류가 발생했습니다: {str(e)}"
        )

    # ── LLM 분석 (vLLM 우선 / Ollama fallback) ──
    analysis = {}
    try:
        analysis = await _analyze_with_best_engine(full_text)
        # ── 숫자 단위 교정: financial_facts GT 기반 ──
        if not analysis.get("_is_error"):
            analysis = correct_financial_numbers(analysis, doc.id)
        if analysis.get("_is_error"):
            logger.warning(
                f"⚠ LLM 에러 결과 감지 — 문서 #{doc.id}: {analysis.get('summary', '')[:80]}"
            )
            # 에러 기록은 저장하되 status는 ocr_done 유지
            err_record = AnalysisResult(
                document_id=doc.id,
                summary=analysis.get("summary", "LLM 분석 실패"),
                category="기타",
                financial_metrics="해당 없음",
                insight_vectors="해당 없음",
                evidence="",
                raw_response=analysis,
                model_name=analysis.get("_model", settings.OLLAMA_MODEL),
                processing_time=analysis.get("_processing_time", 0.0),
            )
            db.add(err_record)
            doc.status = "ocr_done"  # analyzed 아님 — 재분석 가능 상태 유지
            db.commit()
            db.refresh(doc)
        else:
            analysis_record = AnalysisResult(
                document_id=doc.id,
                summary=analysis.get("summary", ""),
                category=analysis.get("category", "기타"),
                financial_metrics=analysis.get("financial_metrics", "데이터 불충분"),
                insight_vectors=analysis.get("insight_vectors", "데이터 불충분"),
                evidence=analysis.get("evidence", ""),
                raw_response=analysis,
                model_name=analysis.get("_model", settings.OLLAMA_MODEL),
                processing_time=analysis.get("_processing_time", 0.0),
            )
            db.add(analysis_record)
            doc.status = "analyzed"
            db.commit()
            db.refresh(doc)
            logger.info(
                f"✦ LLM 분석 완료 — 문서 #{doc.id} "
                f"[{analysis.get('category', 'N/A')}]"
            )
            # 자동 임베딩
            _auto_embed_document(db, doc, analysis)
            _sync_chat_knowledge(db, doc)

    except Exception as e:
        db.rollback()
        doc.status = "ocr_done"  # OCR은 성공했으므로 롤백하지 않음
        db.commit()
        logger.error(f"LLM 분석 실패 — 문서 #{doc.id}: {e}")
        analysis = {}  # LLM 실패 시 빈 dict — 나중에 재분석 가능

    return DocumentUploadResponse(
        id=doc.id,
        user_id=doc.user_id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=doc.status,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        summary=analysis.get("summary"),
        category=analysis.get("category"),
        financial_metrics=analysis.get("financial_metrics"),
        insight_vectors=analysis.get("insight_vectors"),
        evidence=analysis.get("evidence"),
    )


@router.get("")
def list_my_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 문서 목록 조회 — 소유권 기반 필터링 (카테고리 포함)"""
    docs = (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
        .all()
    )

    # 각 문서의 카테고리를 AnalysisResult에서 조회
    doc_ids = [d.id for d in docs]
    if doc_ids:
        analysis_rows = (
            db.query(AnalysisResult.document_id, AnalysisResult.category, AnalysisResult.raw_response)
            .filter(AnalysisResult.document_id.in_(doc_ids))
            .all()
        )
        categories = {r.document_id: r.category for r in analysis_rows}
        # raw_response에서 회사명 추출
        company_names = {}
        for r in analysis_rows:
            if r.raw_response and isinstance(r.raw_response, dict):
                safe_ctx = r.raw_response.get("_safe_context", {})
                cn = (safe_ctx.get("safe_company_name") if isinstance(safe_ctx, dict) else None) \
                     or r.raw_response.get("company_name")
                if cn:
                    company_names[r.document_id] = cn
        # 인사이트가 생성된 문서 ID 집합
        insight_rows = (
            db.query(DocumentInsight.document_id)
            .filter(DocumentInsight.document_id.in_(doc_ids))
            .all()
        )
        insight_ids = {r[0] for r in insight_rows}
    else:
        categories = {}
        company_names = {}
        insight_ids = set()

    result = []
    for doc in docs:
        d = {
            "id": doc.id, "user_id": doc.user_id,
            "filename": doc.filename, "file_type": doc.file_type,
            "file_size": doc.file_size, "status": doc.status,
            "report_path": doc.report_path,
            "created_at": doc.created_at, "updated_at": doc.updated_at,
            "category": categories.get(doc.id),
            "company_name": company_names.get(doc.id),
            "has_insight": doc.id in insight_ids,
        }
        result.append(d)

    return {"documents": result, "total": len(result)}


@router.get("/my-stats")
def get_my_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 문서 카테고리별 통계 — 일반 유저용 대시보드 데이터"""
    from sqlalchemy import func as sa_func

    total = (
        db.query(sa_func.count(Document.id))
        .filter(Document.user_id == current_user.id)
        .scalar() or 0
    )
    analyzed = (
        db.query(sa_func.count(Document.id))
        .filter(Document.user_id == current_user.id, Document.status == "analyzed")
        .scalar() or 0
    )
    pending = (
        db.query(sa_func.count(Document.id))
        .filter(
            Document.user_id == current_user.id,
            Document.status.in_(["uploaded", "ocr_done"]),
        )
        .scalar() or 0
    )

    category_rows = (
        db.query(AnalysisResult.category, sa_func.count(AnalysisResult.id))
        .join(Document, Document.id == AnalysisResult.document_id)
        .filter(Document.user_id == current_user.id)
        .group_by(AnalysisResult.category)
        .all()
    )
    category_stats = [
        {"category": cat or "미분류", "count": cnt}
        for cat, cnt in category_rows
    ]

    return {
        "total": total,
        "analyzed": analyzed,
        "pending": pending,
        "category_stats": category_stats,
    }


@router.get("/by-category")
def list_my_documents_by_category(
    category: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """카테고리별 내 문서 목록 — 소유권 기반 필터링 (관리자는 전체, 카테고리 포함)"""
    if current_user.role == "admin":
        base_query = db.query(Document)
    else:
        base_query = db.query(Document).filter(Document.user_id == current_user.id)

    if not category or category == "전체":
        docs = base_query.order_by(Document.created_at.desc()).all()
    else:
        docs = (
            base_query
            .join(AnalysisResult, AnalysisResult.document_id == Document.id)
            .filter(AnalysisResult.category == category)
            .order_by(Document.created_at.desc())
            .all()
        )

    # 각 문서의 카테고리와 회사명을 AnalysisResult에서 조회
    doc_ids = [d.id for d in docs]
    if doc_ids:
        analysis_rows = (
            db.query(AnalysisResult.document_id, AnalysisResult.category, AnalysisResult.raw_response)
            .filter(AnalysisResult.document_id.in_(doc_ids))
            .all()
        )
        categories = {r.document_id: r.category for r in analysis_rows}
        company_names = {}
        for r in analysis_rows:
            if r.raw_response and isinstance(r.raw_response, dict):
                safe_ctx = r.raw_response.get("_safe_context", {})
                cn = (safe_ctx.get("safe_company_name") if isinstance(safe_ctx, dict) else None) \
                     or r.raw_response.get("company_name")
                if cn:
                    company_names[r.document_id] = cn
        # 인사이트가 생성된 문서 ID 집합
        insight_rows = (
            db.query(DocumentInsight.document_id)
            .filter(DocumentInsight.document_id.in_(doc_ids))
            .all()
        )
        insight_ids = {r[0] for r in insight_rows}
    else:
        categories = {}
        company_names = {}
        insight_ids = set()

    result = []
    for doc in docs:
        d = {
            "id": doc.id, "user_id": doc.user_id,
            "filename": doc.filename, "file_type": doc.file_type,
            "file_size": doc.file_size, "status": doc.status,
            "report_path": doc.report_path,
            "created_at": doc.created_at, "updated_at": doc.updated_at,
            "category": categories.get(doc.id, category if category != "전체" else None),
            "company_name": company_names.get(doc.id),
            "has_insight": doc.id in insight_ids,
        }
        result.append(d)

    return {"documents": result, "total": len(result)}


@router.get("/download-report/{document_id}")
def download_report(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    PDF 요약 보고서 다운로드
    분석 완료된 문서의 PDF 보고서를 다운로드합니다.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

    if doc.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    if not doc.report_path or not os.path.exists(doc.report_path):
        # 보고서가 없으면 즉시 생성 시도
        if doc.status == "analyzed":
            analysis = db.query(AnalysisResult).filter(
                AnalysisResult.document_id == document_id
            ).first()
            if analysis:
                from services.pdf_report_service import generate_pdf_report
                report_path = generate_pdf_report(
                    document_id=doc.id,
                    filename=doc.filename,
                    analysis_data={
                        "summary": analysis.summary,
                        "category": analysis.category,
                        "financial_metrics": analysis.financial_metrics,
                        "insight_vectors": analysis.insight_vectors,
                        "evidence": analysis.evidence,
                        "raw_response": analysis.raw_response,
                    },
                )
                if report_path:
                    doc.report_path = report_path
                    db.commit()

    if not doc.report_path or not os.path.exists(doc.report_path):
        raise HTTPException(
            status_code=404,
            detail="PDF 보고서가 아직 생성되지 않았습니다. 분석이 완료된 후 다시 시도해주세요."
        )

    report_filename = f"{doc.filename.rsplit('.', 1)[0]}_요약보고서.pdf"
    return FileResponse(
        path=doc.report_path,
        filename=report_filename,
        media_type="application/pdf",
    )


@router.get("/preview-report/{document_id}")
def preview_report(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    PDF 요약 보고서 인라인 미리보기
    Content-Disposition: inline → 브라우저에서 바로 렌더링
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if doc.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    if not doc.report_path or not os.path.exists(doc.report_path):
        if doc.status == "analyzed":
            analysis = db.query(AnalysisResult).filter(
                AnalysisResult.document_id == document_id
            ).first()
            if analysis:
                from services.pdf_report_service import generate_pdf_report
                report_path = generate_pdf_report(
                    document_id=doc.id,
                    filename=doc.filename,
                    analysis_data={
                        "summary": analysis.summary,
                        "category": analysis.category,
                        "financial_metrics": analysis.financial_metrics,
                        "insight_vectors": analysis.insight_vectors,
                        "evidence": analysis.evidence,
                        "raw_response": analysis.raw_response,
                    },
                )
                if report_path:
                    doc.report_path = report_path
                    db.commit()

    if not doc.report_path or not os.path.exists(doc.report_path):
        raise HTTPException(status_code=404, detail="PDF 보고서가 아직 생성되지 않았습니다.")

    from starlette.responses import Response
    with open(doc.report_path, "rb") as f:
        content = f.read()
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


@router.get("/insight/{document_id}")
def get_insight(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """문서의 Gemini Insight 조회 (캐시된 결과)"""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if doc.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    insight = (
        db.query(DocumentInsight)
        .filter(DocumentInsight.document_id == document_id)
        .order_by(DocumentInsight.created_at.desc())
        .first()
    )
    if not insight:
        return {"exists": False, "insight": None}

    return {
        "exists": True,
        "insight": {
            "id": insight.id,
            "company_name": insight.company_name,
            "insight_text": insight.insight_text,
            "investment_thesis": insight.investment_thesis,
            "market_context": insight.market_context,
            "risk_factors": insight.risk_factors,
            "strategic_action": insight.strategic_action,
            "strategy_rating": insight.strategy_rating,
            "model_name": insight.model_name,
            "processing_time": insight.processing_time,
            "created_at": insight.created_at.isoformat() if insight.created_at else None,
            # ── Omega-Prime Supervisor 보강 메타데이터 ──
            "supervisor_decision": insight.supervisor_decision,
            "primary_axis": insight.primary_axis,
            "confidence_label": insight.confidence_label,
            "evidence_quality": insight.evidence_quality,
            "supervisor_text": insight.supervisor_text,
            "supervisor_model": insight.supervisor_model,
            "supervisor_time": insight.supervisor_time,
        },
    }


@router.get("/insight/{document_id}/download-pdf")
def download_insight_pdf(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Insight 전략 보고서 A4 PDF 다운로드"""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if doc.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    insight = (
        db.query(DocumentInsight)
        .filter(DocumentInsight.document_id == document_id)
        .order_by(DocumentInsight.created_at.desc())
        .first()
    )
    if not insight:
        raise HTTPException(status_code=404, detail="Insight가 아직 생성되지 않았습니다.")

    from services.pdf_report_service import generate_insight_pdf

    insight_dict = {
        "strategy_rating": insight.strategy_rating,
        "investment_thesis": insight.investment_thesis,
        "market_context": insight.market_context,
        "risk_factors": insight.risk_factors,
        "strategic_action": insight.strategic_action,
        "model_name": insight.model_name,
        "processing_time": insight.processing_time,
        "created_at": insight.created_at.isoformat() if insight.created_at else None,
        "supervisor_decision": insight.supervisor_decision,
        "primary_axis": insight.primary_axis,
        "confidence_label": insight.confidence_label,
        "evidence_quality": insight.evidence_quality,
        "supervisor_text": insight.supervisor_text,
        "supervisor_model": insight.supervisor_model,
        "supervisor_time": insight.supervisor_time or 0,
    }

    pdf_path = generate_insight_pdf(
        document_id=doc.id,
        filename=doc.filename,
        company_name=insight.company_name or "",
        insight_data=insight_dict,
    )

    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=500, detail="Insight PDF 생성에 실패했습니다.")

    report_filename = f"{doc.filename.rsplit('.', 1)[0]}_Insight보고서.pdf"
    return FileResponse(
        path=pdf_path,
        filename=report_filename,
        media_type="application/pdf",
    )


@router.post("/insight/{document_id}")
def generate_insight(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Gemini 2.5 Pro로 새 Insight 생성"""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if doc.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    if doc.status != "analyzed":
        raise HTTPException(status_code=400, detail="분석이 완료된 문서만 Insight를 생성할 수 있습니다.")

    # 분석 결과 가져오기
    analysis = (
        db.query(AnalysisResult)
        .filter(AnalysisResult.document_id == document_id)
        .first()
    )
    if not analysis:
        raise HTTPException(status_code=400, detail="분석 결과가 없습니다.")

    # raw_response에서 회사명/문서유형/변경사항 추출 (이중 인코딩 방어)
    raw = {}
    if analysis.raw_response:
        try:
            r = analysis.raw_response
            if isinstance(r, str):
                r = json.loads(r)
                if isinstance(r, str):  # 이중 인코딩
                    r = json.loads(r)
            if isinstance(r, dict):
                raw = r
        except Exception:
            raw = {}

    company_name = raw.get("company_name", raw.get("_company", "미확인"))
    doc_type = raw.get("_doc_type", analysis.category or "기타")
    key_changes_raw = raw.get("key_changes", [])
    key_changes_str = ""
    if isinstance(key_changes_raw, list):
        for ch in key_changes_raw:
            if isinstance(ch, dict):
                key_changes_str += f"- {ch.get('field','')}: {ch.get('before','')} -> {ch.get('after','')}\n"

    # ── 분석 요약 유효성 검사 — 에러 메시지로 Insight 생성 방지 ──
    ERROR_PREFIXES = ("분석 중 오류", "LLM 분석 실패", "All connection", "분석할 텍스트")
    summary_text = analysis.summary or ""
    if not summary_text.strip() or any(summary_text.startswith(p) for p in ERROR_PREFIXES):
        raise HTTPException(
            status_code=400,
            detail=(
                "이 문서의 LLM 분석이 실패했습니다. "
                "Ollama가 실행 중인지 확인하고, 문서를 재분석한 후 Insight를 생성해주세요. "
                f"(현재 분석 상태: '{summary_text[:60]}...' )" if len(summary_text) > 60
                else f"(현재 분석 상태: '{summary_text}')"
            )
        )

    # Gemini Insight 생성
    from services.insight_service import generate_company_insight

    result = generate_company_insight(
        company_name=company_name,
        doc_summary=summary_text,
        doc_type=doc_type,
        doc_category=analysis.category or "",
        key_changes=key_changes_str,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=f"Insight 생성 실패: {result.get('error', '알 수 없는 오류')}"
        )

    # DB 저장 — Primary Insight
    insight = DocumentInsight(
        document_id=document_id,
        company_name=result.get("company_name"),
        insight_text=result.get("insight_text"),
        investment_thesis=result.get("investment_thesis"),
        market_context=result.get("market_context"),
        risk_factors=result.get("risk_factors"),
        strategic_action=result.get("strategic_action"),
        strategy_rating=result.get("strategy_rating"),
        model_name=result.get("model_name"),
        processing_time=result.get("processing_time", 0.0),
    )

    # ── Omega-Prime Supervisor 보강 (병렬 유지 — 기존 Insight 사후 검증) ──
    try:
        from services.omega_supervisor import supervise_insight

        sv = supervise_insight(
            company_name=company_name,
            doc_summary=summary_text,
            doc_type=doc_type,
            doc_category=analysis.category or "",
            key_changes=key_changes_str,
            existing_insight={
                "investment_thesis": result.get("investment_thesis"),
                "market_context": result.get("market_context"),
                "risk_factors": result.get("risk_factors"),
                "strategic_action": result.get("strategic_action"),
                "strategy_rating": result.get("strategy_rating"),
            },
        )
        if sv.get("success"):
            insight.supervisor_decision = sv.get("supervisor_decision")
            insight.primary_axis = sv.get("primary_axis")
            insight.confidence_label = sv.get("confidence_label")
            insight.evidence_quality = sv.get("evidence_quality")
            insight.supervisor_text = sv.get("supervisor_text")
            insight.supervisor_json = sv.get("supervisor_json")
            insight.supervisor_model = sv.get("model_name")
            insight.supervisor_time = sv.get("processing_time", 0.0)
            logger.info(f"✅ Supervisor 보강 완료 — 문서 #{document_id} [{sv.get('confidence_label')}]")
        else:
            logger.warning(f"⚠ Supervisor 보강 실패 (무시): {sv.get('error')}")
    except Exception as e:
        logger.warning(f"⚠ Supervisor 보강 예외 (무시): {e}")

    db.add(insight)
    db.commit()
    db.refresh(insight)

    return {
        "success": True,
        "insight": {
            "id": insight.id,
            "company_name": insight.company_name,
            "insight_text": insight.insight_text,
            "investment_thesis": insight.investment_thesis,
            "market_context": insight.market_context,
            "risk_factors": insight.risk_factors,
            "strategic_action": insight.strategic_action,
            "strategy_rating": insight.strategy_rating,
            "model_name": insight.model_name,
            "processing_time": insight.processing_time,
            "created_at": insight.created_at.isoformat() if insight.created_at else None,
            # ── Supervisor 보강 결과 ──
            "supervisor_decision": insight.supervisor_decision,
            "primary_axis": insight.primary_axis,
            "confidence_label": insight.confidence_label,
            "evidence_quality": insight.evidence_quality,
            "supervisor_text": insight.supervisor_text,
            "supervisor_model": insight.supervisor_model,
            "supervisor_time": insight.supervisor_time,
        },
    }


@router.get("/batch-status")
def get_batch_status(
    doc_ids: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Batch 문서 상태 조회 (DB 직접 조회)
    ═══════════════════════════════════════════════════════
    """
    ids = [int(did.strip()) for did in doc_ids.split(",") if did.strip().isdigit()]
    results = []
    all_done = True

    for doc_id in ids:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            results.append({
                "id": doc_id, "filename": "unknown",
                "status": "not_found", "category": None, "summary": None,
            })
            all_done = False
            continue

        is_done = doc.status in ("analyzed", "failed")
        if not is_done:
            all_done = False

        analysis = None
        if doc.status == "analyzed":
            analysis = db.query(AnalysisResult).filter(
                AnalysisResult.document_id == doc_id
            ).first()

        results.append({
            "id": doc.id,
            "filename": doc.filename,
            "status": doc.status,
            "category": analysis.category if analysis else None,
            "summary": analysis.summary if analysis else None,
        })

    return {
        "documents": results,
        "all_done": all_done,
        "total": len(ids),
        "completed": sum(1 for r in results if r["status"] in ("analyzed", "failed")),
    }


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document_detail(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """문서 상세 조회 — OCR 텍스트 + LLM 분석 결과"""
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

    # 권한 검사: 본인 문서 또는 관리자만 조회 가능
    if doc.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")

    # OCR 텍스트 조회
    ocr_texts = db.query(OcrText).filter(OcrText.document_id == doc.id).all()
    ocr_responses = []
    for ot in ocr_texts:
        page = db.query(Page).filter(Page.id == ot.page_id).first() if ot.page_id else None
        ocr_responses.append(OcrTextResponse(
            id=ot.id,
            page_number=page.page_number if page else None,
            raw_text=ot.raw_text,
            cleaned_text=ot.cleaned_text,
            confidence=ot.confidence,
        ))

    # 분석 결과 조회
    analysis = (
        db.query(AnalysisResult)
        .filter(AnalysisResult.document_id == doc.id)
        .order_by(AnalysisResult.created_at.desc())
        .first()
    )

    # 소유자 이름
    owner = db.query(User).filter(User.id == doc.user_id).first()

    # ── 회사명 크로스체크: raw_response → 파일명 fallback ──
    import re as _re
    company_name = None
    if analysis and analysis.raw_response:
        raw = analysis.raw_response
        if isinstance(raw, dict):
            # 우선순위: _safe_context.safe_company_name → company_name
            safe_ctx = raw.get("_safe_context", {})
            if isinstance(safe_ctx, dict):
                company_name = safe_ctx.get("safe_company_name")
            if not company_name:
                company_name = raw.get("company_name")
    # fallback: 파일명에서 추출
    if not company_name:
        fn_match = _re.match(r'^[a-f0-9]+_DART_P\d+_(.+?)_\d{13,14}', doc.filename or '')
        if fn_match:
            company_name = fn_match.group(1)

    return DocumentDetailResponse(
        document=doc,
        ocr_texts=ocr_responses,
        analysis=analysis,
        owner_username=owner.username if owner else None,
        company_name=company_name,
    )



@router.post("/{document_id}/reanalyze")
async def reanalyze_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    문서 재분석 — OCR 텍스트를 재사용해 LLM 분석만 다시 실행
    ═══════════════════════════════════════════
    ocr_done 상태 또는 LLM 에러 요약을 가진 문서를 대상으로 함.
    Ollama가 실행 중이어야 합니다.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if doc.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    # 재분석 허용: analyzed, ocr_done, failed
    if doc.status not in ("ocr_done", "failed", "analyzed"):
        raise HTTPException(
            status_code=400,
            detail=f"재분석은 분석 완료/ocr_done/failed 상태 문서만 가능합니다. (현재 상태: {doc.status})"
        )

    # OCR 텍스트 재조합
    ocr_texts = db.query(OcrText).filter(OcrText.document_id == doc.id).all()
    if not ocr_texts:
        raise HTTPException(status_code=400, detail="OCR 텍스트가 없습니다. 문서를 다시 업로드해주세요.")

    pages_for_preprocess = []
    for ot in sorted(ocr_texts, key=lambda x: x.id):
        page = db.query(Page).filter(Page.id == ot.page_id).first() if ot.page_id else None
        page_num = page.page_number if page else 1
        text = ot.cleaned_text or ot.raw_text or ""
        if text.strip():
            pages_for_preprocess.append((page_num, text))

    if not pages_for_preprocess:
        raise HTTPException(status_code=400, detail="유효한 OCR 텍스트가 없습니다.")

    try:
        full_text = text_preprocessor.preprocess(pages_for_preprocess)
    except Exception:
        full_text = "\n\n".join(t for _, t in pages_for_preprocess)

    # LLM 재분석 (QLoRA 파인튜닝 모델)
    try:
        analysis = await llm_service.analyze_document(full_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 분석 실패 (Ollama 실행 여부 확인): {e}")

    # ── 숫자 단위 교정: financial_facts GT 기반 ──
    if not analysis.get("_is_error"):
        analysis = correct_financial_numbers(analysis, document_id)

    if analysis.get("_is_error"):
        raise HTTPException(
            status_code=503,
            detail=f"LLM 분석 실패: {analysis.get('summary', '')}. Ollama가 실행 중인지 확인해주세요."
        )

    # 기존 분석 결과 업데이트 또는 신규 저장
    existing_analysis = (
        db.query(AnalysisResult)
        .filter(AnalysisResult.document_id == document_id)
        .order_by(AnalysisResult.created_at.desc())
        .first()
    )
    if existing_analysis:
        existing_analysis.summary = analysis.get("summary", "")
        existing_analysis.category = analysis.get("category", "기타")
        existing_analysis.financial_metrics = analysis.get("financial_metrics", "해당 없음")
        existing_analysis.insight_vectors = analysis.get("insight_vectors", "해당 없음")
        existing_analysis.evidence = analysis.get("evidence", "")
        existing_analysis.raw_response = analysis
        existing_analysis.model_name = analysis.get("_model", settings.OLLAMA_MODEL)
        existing_analysis.processing_time = analysis.get("_processing_time", 0.0)
    else:
        new_analysis = AnalysisResult(
            document_id=doc.id,
            summary=analysis.get("summary", ""),
            category=analysis.get("category", "기타"),
            financial_metrics=analysis.get("financial_metrics", "해당 없음"),
            insight_vectors=analysis.get("insight_vectors", "해당 없음"),
            evidence=analysis.get("evidence", ""),
            raw_response=json.dumps(analysis, ensure_ascii=False, default=str),
            model_name=analysis.get("_model", settings.OLLAMA_MODEL),
            processing_time=analysis.get("_processing_time", 0.0),
        )
        db.add(new_analysis)

    doc.status = "analyzed"
    db.commit()
    db.refresh(doc)

    # PDF 보고서 재생성
    try:
        from services.pdf_report_service import generate_pdf_report
        report_path = generate_pdf_report(
            document_id=doc.id,
            filename=doc.filename,
            analysis_data={
                "summary": analysis.get("summary", ""),
                "category": analysis.get("category", "기타"),
                "financial_metrics": analysis.get("financial_metrics", "해당 없음"),
                "insight_vectors": analysis.get("insight_vectors", "해당 없음"),
                "evidence": analysis.get("evidence", ""),
                "raw_response": analysis,
            },
        )
        if report_path:
            doc.report_path = report_path
            db.commit()
    except Exception as e:
        logger.warning(f"PDF 재생성 실패 (무시): {e}")

    # 벡터 임베딩 갱신
    _auto_embed_document(db, doc, analysis)
    _sync_chat_knowledge(db, doc)

    logger.info(f"✅ 재분석 완료 — 문서 #{doc.id} [{analysis.get('category', 'N/A')}]")

    return {
        "success": True,
        "document_id": doc.id,
        "status": doc.status,
        "summary": analysis.get("summary", ""),
        "category": analysis.get("category", "기타"),
    }


@router.delete("/{document_id}", response_model=MessageResponse)
def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """문서 삭제 — 소유자만 가능 (관리자 포함)"""
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

    if doc.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="삭제 권한이 없습니다.")

    # 파일 삭제
    try:
        if os.path.exists(doc.file_path):
            os.remove(doc.file_path)
    except Exception:
        pass

    db.delete(doc)
    db.commit()

    return MessageResponse(message="문서가 삭제되었습니다.", detail=f"문서 ID: {document_id}")


# ── 문서 이름 변경 ──

class RenameRequest(PydanticBaseModel):
    filename: str

@router.patch("/{document_id}/rename", response_model=MessageResponse)
def rename_document(
    document_id: int,
    body: RenameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """문서 표시 이름 변경"""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if doc.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    new_name = body.filename.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="파일명은 비어있을 수 없습니다.")

    doc.filename = new_name
    db.commit()
    return MessageResponse(message="이름이 변경되었습니다.", detail=new_name)


# ── 중복 문서 감지 ──

@router.get("/duplicates/list")
def get_duplicates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """중복 문서 그룹 반환 (같은 회사_카테고리로 그룹화)"""
    import re

    def parse_display_name(filename, category=""):
        """DART 파일명에서 회사명 추출 → 회사명_카테고리 형식"""
        if not filename:
            return filename or ""
        m = re.match(r'^[a-f0-9]+_DART_P\d+_(.+?)_\d{13,14}', filename)
        if m:
            company = m.group(1)
            cat = category or "미분류"
            return f"{company}_{cat}"
        return filename
    docs = (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .order_by(Document.id.desc())
        .all()
    )

    # 분석 결과 조회 (카테고리 + 요약)
    analysis_map = {}
    summary_map = {}
    analysis_rows = db.query(AnalysisResult).filter(
        AnalysisResult.document_id.in_([d.id for d in docs])
    ).all()
    for a in analysis_rows:
        analysis_map[a.document_id] = a.category
        summary_map[a.document_id] = a.summary

    # 정규화된 이름으로 그룹핑
    groups = {}
    for doc in docs:
        category = analysis_map.get(doc.id, "")
        summary = summary_map.get(doc.id, "")
        display_name = parse_display_name(doc.filename, category)
        key = display_name.lower().strip()
        if key not in groups:
            groups[key] = {"display_name": display_name, "documents": []}
        groups[key]["documents"].append({
            "id": doc.id,
            "filename": doc.filename,
            "status": doc.status,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "category": category,
            "summary": (summary[:120] + "…") if summary and len(summary) > 120 else (summary or ""),
        })

    # 2건 이상인 그룹만 반환
    duplicates = [g for g in groups.values() if len(g["documents"]) > 1]
    duplicates.sort(key=lambda g: len(g["documents"]), reverse=True)

    return {
        "groups": duplicates,
        "total_groups": len(duplicates),
        "total_duplicates": sum(len(g["documents"]) for g in duplicates),
    }



# ═══════════════════════════════════════════════════════
# Batch Upload — 다중 파일 업로드 + 이메일 결과 전송
# ═══════════════════════════════════════════════════════

async def _process_single_file(
    file: UploadFile,
    current_user: User,
    db: Session,
) -> dict:
    """단일 파일 처리 내부 함수 — upload_batch에서 재사용"""
    allowed_types = {"application/pdf", "image/jpeg", "image/png", "image/jpg",
                     "text/html", "application/xhtml+xml", "application/octet-stream",
                     "application/xml", "text/xml", "application/zip",
                     "application/x-zip-compressed",
                     "application/vnd.ms-excel",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    if file.content_type not in allowed_types:
        return {"error": True, "filename": file.filename, "detail": "지원하지 않는 파일 형식"}

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "bin"
    file_type = (
        "pdf" if ext == "pdf"
        else "html" if ext in ("html", "htm")
        else "xml" if ext in ("xml", "xbrl", "xsd")
        else "xls" if ext in ("xls", "xlsx")
        else "zip" if ext == "zip"
        else ext
    )

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    unique_id = str(uuid.uuid4())[:8]
    safe_filename = f"{unique_id}_{file.filename}"
    file_path = upload_dir / safe_filename

    content = await file.read()
    file_size = len(content)

    max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_size:
        return {"error": True, "filename": file.filename, "detail": f"파일 크기 초과 ({settings.MAX_FILE_SIZE_MB}MB)"}

    with open(file_path, "wb") as f:
        f.write(content)

    doc = Document(
        user_id=current_user.id,
        filename=file.filename,
        file_path=str(file_path),
        file_type=file_type,
        file_size=file_size,
        status="uploaded",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # OCR
    try:
        if file_type == "pdf":
            page_dir = upload_dir / f"pages_{doc.id}"
            page_dir.mkdir(parents=True, exist_ok=True)
            ocr_results = ocr_engine.extract_text_from_pdf(str(file_path), str(page_dir))

            all_text_parts = []
            pages_for_preprocess = []
            for page_num, text, confidence in ocr_results:
                page = Page(document_id=doc.id, page_number=page_num,
                            image_path=str(page_dir / f"page_{page_num}.png"))
                db.add(page)
                db.flush()
                cleaned = ocr_engine.clean_text(text)
                ocr_text = OcrText(document_id=doc.id, page_id=page.id,
                                   raw_text=text, cleaned_text=cleaned, confidence=confidence)
                db.add(ocr_text)
                all_text_parts.append(cleaned)
                pages_for_preprocess.append((page_num, cleaned))

            try:
                full_text = text_preprocessor.preprocess(pages_for_preprocess)
            except Exception:
                full_text = "\n\n".join(all_text_parts)
        elif file_type == "html":
            # HTML 파일 — DART 공시 원본 텍스트 추출 (OCR 불필요)
            try:
                from bs4 import BeautifulSoup
                import re as _re
                # DART HTML은 euc-kr 인코딩 사용 → 자동 감지
                charset_match = _re.search(rb'charset=(["\']?)([a-zA-Z0-9_-]+)', content[:1000])
                encoding = charset_match.group(2).decode('ascii') if charset_match else 'utf-8'
                try:
                    html_content = content.decode(encoding, errors='replace')
                except (UnicodeDecodeError, LookupError):
                    html_content = content.decode('euc-kr', errors='replace')
                soup = BeautifulSoup(html_content, "html.parser")
                for tag in soup(["script", "style", "meta", "link"]):
                    tag.decompose()
                raw_text = soup.get_text(separator="\n", strip=True)
            except Exception:
                try:
                    raw_text = content.decode('euc-kr', errors='replace')
                except Exception:
                    raw_text = content.decode('utf-8', errors='replace')

            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=str(file_path))
            db.add(page)
            db.flush()
            ocr_text = OcrText(document_id=doc.id, page_id=page.id,
                               raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.99)
            db.add(ocr_text)
            full_text = cleaned
        elif file_type == "zip":
            from services.dart_file_parser import extract_text_from_dart_zip
            raw_text = extract_text_from_dart_zip(content, file.filename)
            if not raw_text:
                raw_text = "(ZIP 데이터 추출 실패)"
            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=str(file_path))
            db.add(page)
            db.flush()
            ocr_text = OcrText(document_id=doc.id, page_id=page.id,
                               raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95)
            db.add(ocr_text)
            full_text = cleaned
        elif file_type == "xls":
            from services.dart_file_parser import extract_text_from_xls
            raw_text = extract_text_from_xls(content, file.filename)
            if not raw_text:
                raw_text = "(Excel 데이터 추출 실패)"
            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=str(file_path))
            db.add(page)
            db.flush()
            ocr_text = OcrText(document_id=doc.id, page_id=page.id,
                               raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95)
            db.add(ocr_text)
            full_text = cleaned
        elif file_type in ("xml", "xbrl", "xsd"):
            # XBRL/XSD/XML — 구조화 텍스트 추출
            try:
                from bs4 import BeautifulSoup
                try:
                    xml_content = content.decode('utf-8', errors='replace')
                except Exception:
                    xml_content = content.decode('euc-kr', errors='replace')
                soup = BeautifulSoup(xml_content, "lxml-xml")
                # XBRL: 의미있는 텍스트 노드만 추출
                texts = []
                for tag in soup.find_all(True):
                    if tag.string and tag.string.strip():
                        tag_name = tag.name.split(':')[-1] if ':' in tag.name else tag.name
                        texts.append(f"{tag_name}: {tag.string.strip()}")
                raw_text = "\n".join(texts) if texts else soup.get_text(separator="\n", strip=True)
            except Exception:
                raw_text = content.decode('utf-8', errors='replace')

            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=str(file_path))
            db.add(page)
            db.flush()
            ocr_text = OcrText(document_id=doc.id, page_id=page.id,
                               raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95)
            db.add(ocr_text)
            full_text = cleaned
        else:
            text, confidence = ocr_engine.extract_text_from_image(str(file_path))
            cleaned = ocr_engine.clean_text(text)
            page = Page(document_id=doc.id, page_number=1, image_path=str(file_path))
            db.add(page)
            db.flush()
            ocr_text = OcrText(document_id=doc.id, page_id=page.id,
                               raw_text=text, cleaned_text=cleaned, confidence=confidence)
            db.add(ocr_text)
            full_text = cleaned

        doc.status = "ocr_done"
        db.commit()
    except Exception as e:
        doc.status = "failed"
        db.commit()
        return {"error": True, "filename": file.filename, "detail": f"OCR 실패: {str(e)}"}

    # LLM 분석 (vLLM 우선 / Ollama fallback)
    analysis = {}
    try:
        analysis = await _analyze_with_best_engine(full_text)

        if analysis.get("_is_error"):
            # 에러 결과는 ocr_done 상태 유지 (analyzed 아님)
            err_record = AnalysisResult(
                document_id=doc.id,
                summary=analysis.get("summary", "LLM 분석 실패"),
                category="기타",
                financial_metrics="해당 없음",
                insight_vectors="해당 없음",
                evidence="",
                raw_response=analysis,
                model_name=analysis.get("_model", settings.OLLAMA_MODEL),
                processing_time=analysis.get("_processing_time", 0.0),
            )
            db.add(err_record)
            doc.status = "ocr_done"
            db.commit()
        else:
            analysis_record = AnalysisResult(
                document_id=doc.id,
                summary=analysis.get("summary", ""),
                category=analysis.get("category", "기타"),
                financial_metrics=analysis.get("financial_metrics", "데이터 불충분"),
                insight_vectors=analysis.get("insight_vectors", "데이터 불충분"),
                evidence=analysis.get("evidence", ""),
                raw_response=analysis,
                model_name=analysis.get("_model", settings.OLLAMA_MODEL),
                processing_time=analysis.get("_processing_time", 0.0),
            )
            db.add(analysis_record)
            doc.status = "analyzed"

        db.commit()
        db.refresh(doc)
        # 자동 임베딩 (분석 성공 시)
        if doc.status == "analyzed":
            _auto_embed_document(db, doc, analysis)
            _sync_chat_knowledge(db, doc)
    except Exception as e:
        db.rollback()
        doc.status = "ocr_done"
        db.commit()
        logger.error(f"LLM 분석 실패 — 문서 #{doc.id}: {e}")

    return {
        "error": False,
        "response": DocumentUploadResponse(
            id=doc.id, user_id=doc.user_id, filename=doc.filename,
            file_type=doc.file_type, file_size=doc.file_size,
            status=doc.status, created_at=doc.created_at, updated_at=doc.updated_at,
            summary=analysis.get("summary"),
            category=analysis.get("category"),
            financial_metrics=analysis.get("financial_metrics"),
            insight_vectors=analysis.get("insight_vectors"),
            evidence=analysis.get("evidence"),
        ),
    }


@router.post("/upload-batch", response_model=BatchUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_batch(
    files: List[UploadFile] = File(...),
    send_email: bool = Form(False),
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    다중 파일 업로드 (최대 20개) — 즉시 응답 + 백그라운드 처리
    ═══════════════════════════════════════════════════════
    파일 저장 + DB 레코드 생성 후 즉시 응답.
    OCR + LLM 분석은 BackgroundTasks에서 비동기 처리.
    """
    MAX_FILES = 20
    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"한 번에 최대 {MAX_FILES}개 파일까지 업로드 가능합니다. (요청: {len(files)}개)"
        )

    documents = []
    doc_ids_to_process = []

    for file in files:
        # 파일 타입 검증 — DART ZIP(.zip.pdf), XBRL, XML 허용
        allowed = [".pdf", ".jpg", ".jpeg", ".png", ".xbrl", ".xml", ".xsd", ".zip", ".html", ".htm", ".xls", ".xlsx"]
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed:
            documents.append({
                "id": 0, "filename": file.filename,
                "status": "rejected", "task_id": None,
                "detail": f"지원하지 않는 형식: {ext}",
            })
            continue

        # 파일 저장
        try:
            content = await file.read()
            file_size = len(content)

            if file_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
                documents.append({
                    "id": 0, "filename": file.filename,
                    "status": "rejected", "task_id": None,
                    "detail": f"파일 크기 초과 ({file_size / 1048576:.1f}MB > {settings.MAX_FILE_SIZE_MB}MB)",
                })
                continue

            safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
            file_path = os.path.join(settings.UPLOAD_DIR, safe_name)
            os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

            with open(file_path, "wb") as f:
                f.write(content)

            # DB 레코드 생성 (status=pending)
            doc = Document(
                user_id=current_user.id,
                filename=file.filename,  # UUID 접두어가 없는 원본 파일명 저장
                file_path=file_path,
                file_type=ext.replace(".", ""),
                file_size=file_size,
                status="pending",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            doc_ids_to_process.append(doc.id)

            documents.append({
                "id": doc.id, "filename": file.filename,
                "status": "pending", "task_id": None,
            })

            logger.info(f"📤 파일 저장 완료 — #{doc.id} {file.filename}")

        except Exception as e:
            logger.error(f"파일 저장 실패 — {file.filename}: {e}")
            documents.append({
                "id": 0, "filename": file.filename,
                "status": "failed", "task_id": None,
                "detail": str(e),
            })

    # 백그라운드에서 OCR + LLM 분석 처리
    if doc_ids_to_process and background_tasks:
        background_tasks.add_task(
            _process_documents_background,
            doc_ids_to_process,
            send_email,
            current_user.email if send_email else None,
        )
        logger.info(f"🔄 백그라운드 처리 예약 — {len(doc_ids_to_process)}건")

    return BatchUploadResponse(
        documents=documents,
        total=len(files),
        task_ids=[],
        send_email=send_email,
    )


def _process_documents_background(doc_ids: list, send_email: bool, user_email: str = None):
    """
    백그라운드에서 문서 OCR + LLM 분석을 순차 처리
    별도 DB 세션을 사용하여 요청 세션과 격리
    """
    from database import SessionLocal

    db = SessionLocal()
    try:
        for doc_id in doc_ids:
            try:
                _process_single_document_bg(doc_id, db)
            except Exception as e:
                logger.error(f"백그라운드 처리 실패 — 문서 #{doc_id}: {e}")
                try:
                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.status = "failed"
                        db.commit()
                except Exception:
                    db.rollback()

        # 이메일 전송
        if send_email and user_email:
            try:
                from services.email_service import send_analysis_result_email
                results = []
                report_paths = []
                for doc_id in doc_ids:
                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    analysis = db.query(AnalysisResult).filter(
                        AnalysisResult.document_id == doc_id).first()
                    if doc and analysis:
                        results.append({
                            "filename": doc.filename,
                            "summary": analysis.summary or "요약 없음",
                            "category": analysis.category or "미분류",
                            "financial_metrics": analysis.financial_metrics or "해당 없음",
                            "insight_vectors": analysis.insight_vectors or "해당 없음",
                        })
                        # PDF 요약 보고서 경로 수집
                        if doc.report_path:
                            report_paths.append(doc.report_path)
                if results:
                    send_analysis_result_email(user_email, results, report_paths=report_paths)
                    logger.info(f"📧 이메일 발송 완료 → {user_email} (PDF {len(report_paths)}건 첨부)")
            except Exception as e:
                logger.error(f"이메일 발송 실패: {e}")
    finally:
        db.close()


def _process_single_document_bg(doc_id: int, db: Session):
    """단일 문서 OCR + LLM 분석 (백그라운드)"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return

    logger.info(f"🔄 처리 시작 — #{doc.id} {doc.filename}")

    full_text = ""

    # 1. OCR — 기존 _process_single_file과 동일한 패턴
    try:
        file_path = doc.file_path
        upload_dir = Path(settings.UPLOAD_DIR)

        if doc.file_type == "pdf":
            page_dir = upload_dir / f"pages_{doc.id}"
            page_dir.mkdir(parents=True, exist_ok=True)
            ocr_results = ocr_engine.extract_text_from_pdf(file_path, str(page_dir))

            all_text_parts = []
            pages_for_preprocess = []
            for page_num, text, confidence in ocr_results:
                page = Page(
                    document_id=doc.id,
                    page_number=page_num,
                    image_path=str(page_dir / f"page_{page_num}.png"),
                )
                db.add(page)
                db.flush()

                cleaned = ocr_engine.clean_text(text)
                ocr_text = OcrText(
                    document_id=doc.id,
                    page_id=page.id,
                    raw_text=text,
                    cleaned_text=cleaned,
                    confidence=confidence,
                )
                db.add(ocr_text)
                all_text_parts.append(cleaned)
                pages_for_preprocess.append((page_num, cleaned))

            try:
                from services.text_preprocessor import TextPreprocessor
                preprocessor = TextPreprocessor()
                full_text = preprocessor.preprocess(pages_for_preprocess)
            except Exception:
                full_text = "\n\n".join(all_text_parts)
        elif doc.file_type == "html":
            # HTML 파일 — DART 공시 원본 텍스트 추출 (OCR 불필요)
            import re as _re
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
            try:
                from bs4 import BeautifulSoup
                charset_match = _re.search(rb'charset=["\']?([a-zA-Z0-9_-]+)', raw_bytes[:1000])
                encoding = charset_match.group(1).decode('ascii') if charset_match else 'utf-8'
                try:
                    html_content = raw_bytes.decode(encoding, errors='replace')
                except (UnicodeDecodeError, LookupError):
                    html_content = raw_bytes.decode('euc-kr', errors='replace')
                soup = BeautifulSoup(html_content, "html.parser")
                for tag in soup(["script", "style", "meta", "link"]):
                    tag.decompose()
                raw_text = soup.get_text(separator="\n", strip=True)
            except Exception:
                try:
                    raw_text = raw_bytes.decode('euc-kr', errors='replace')
                except Exception:
                    raw_text = raw_bytes.decode('utf-8', errors='replace')

            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=file_path)
            db.add(page)
            db.flush()
            ocr_text = OcrText(
                document_id=doc.id,
                page_id=page.id,
                raw_text=raw_text[:50000],
                cleaned_text=cleaned[:50000],
                confidence=0.99,
            )
            db.add(ocr_text)
            full_text = cleaned
        elif doc.file_type == "zip":
            # DART XBRL ZIP 번들 — 한국어 레이블 + 재무 데이터 추출
            from services.dart_file_parser import extract_text_from_dart_zip
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
            raw_text = extract_text_from_dart_zip(raw_bytes, doc.filename)
            if not raw_text:
                raw_text = "(ZIP 데이터 추출 실패)"
            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=file_path)
            db.add(page)
            db.flush()
            ocr_text = OcrText(
                document_id=doc.id, page_id=page.id,
                raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95,
            )
            db.add(ocr_text)
            full_text = cleaned
        elif doc.file_type in ("xls", "xlsx"):
            # XLS/XLSX 재무제표 — Excel 파싱
            from services.dart_file_parser import extract_text_from_xls
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
            raw_text = extract_text_from_xls(raw_bytes, doc.filename)
            if not raw_text:
                raw_text = "(Excel 데이터 추출 실패)"
            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=file_path)
            db.add(page)
            db.flush()
            ocr_text = OcrText(
                document_id=doc.id, page_id=page.id,
                raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95,
            )
            db.add(ocr_text)
            full_text = cleaned
        elif doc.file_type in ("xml", "xbrl", "xsd"):
            # XBRL/XSD/XML — 구조화 텍스트 추출
            from services.dart_file_parser import _extract_xml_text
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
            raw_text = _extract_xml_text(raw_bytes.decode('utf-8', errors='replace'))
            if not raw_text:
                raw_text = raw_bytes.decode('utf-8', errors='replace')[:50000]
            cleaned = ocr_engine.clean_text(raw_text)
            page = Page(document_id=doc.id, page_number=1, image_path=file_path)
            db.add(page)
            db.flush()
            ocr_text = OcrText(
                document_id=doc.id, page_id=page.id,
                raw_text=raw_text[:50000], cleaned_text=cleaned[:50000], confidence=0.95,
            )
            db.add(ocr_text)
            full_text = cleaned
        else:
            # 이미지 파일
            text, confidence = ocr_engine.extract_text_from_image(file_path)
            cleaned = ocr_engine.clean_text(text)
            page = Page(document_id=doc.id, page_number=1, image_path=file_path)
            db.add(page)
            db.flush()
            ocr_text = OcrText(
                document_id=doc.id,
                page_id=page.id,
                raw_text=text,
                cleaned_text=cleaned,
                confidence=confidence,
            )
            db.add(ocr_text)
            full_text = cleaned

        doc.status = "ocr_done"
        db.commit()
        logger.info(f"📝 OCR 완료 — #{doc.id} [{len(full_text)}자]")
    except Exception as e:
        logger.error(f"OCR 실패 — #{doc.id}: {e}")
        doc.status = "failed"
        db.commit()
        return

    # 2. LLM 분석
    import asyncio
    import concurrent.futures
    try:
        # BackgroundTasks 내부에서 asyncio.run() 충돌 방지
        # 새 스레드에서 새 이벤트 루프를 만들어 async 함수 실행
        def _run_llm():
            return asyncio.run(_analyze_with_best_engine(full_text))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_llm)
            analysis = future.result(timeout=300)  # 5분 타임아웃

        analysis_record = AnalysisResult(
            document_id=doc.id,
            summary=analysis.get("summary", ""),
            category=analysis.get("category", "기타"),
            financial_metrics=str(analysis.get("financial_metrics", "")) if isinstance(analysis.get("financial_metrics"), dict) else analysis.get("financial_metrics", ""),
            insight_vectors=str(analysis.get("insight_vectors", "")) if isinstance(analysis.get("insight_vectors"), dict) else analysis.get("insight_vectors", ""),
            evidence=analysis.get("evidence", ""),
            raw_response=json.dumps(analysis, ensure_ascii=False, default=str),
            model_name=analysis.get("_model", settings.OLLAMA_MODEL),
            processing_time=analysis.get("_processing_time", 0.0),
        )
        db.add(analysis_record)
        doc.status = "analyzed"
        db.commit()
        logger.info(f"✅ 분석 완료 — #{doc.id} [{analysis.get('category', 'N/A')}]")
        # 자동 임베딩
        _auto_embed_document(db, doc, analysis)
        _sync_chat_knowledge(db, doc)

        # PDF 보고서 자동 생성
        try:
            from services.pdf_report_service import generate_pdf_report
            report_path = generate_pdf_report(
                document_id=doc.id,
                filename=doc.filename,
                analysis_data={
                    "summary": analysis_record.summary,
                    "category": analysis_record.category,
                    "financial_metrics": analysis_record.financial_metrics,
                    "insight_vectors": analysis_record.insight_vectors,
                    "evidence": analysis_record.evidence,
                    "raw_response": analysis_record.raw_response,
                },
            )
            if report_path:
                doc.report_path = report_path
                db.commit()
        except Exception as e:
            logger.warning(f"PDF 보고서 생성 실패 (무시): {e}")
    except Exception as e:
        db.rollback()
        doc.status = "ocr_done"
        db.commit()
        logger.error(f"LLM 분석 실패 — #{doc.id}: {e}")

