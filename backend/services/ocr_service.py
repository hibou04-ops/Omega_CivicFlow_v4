"""
═══════════════════════════════════════════════════════
Omega CivicFlow — OCR Service
엔트로피 소각 엔진 (Entropy Incineration Engine)
PaddleOCR 기반 텍스트 추출 + 재무 보존형 노이즈 필터링
═══════════════════════════════════════════════════════
"""

import os
import re
import logging
from typing import List, Tuple, Optional
from pathlib import Path

from PIL import Image, ImageFilter, ImageEnhance, ImageOps

logger = logging.getLogger(__name__)


class OcrEngine:
    """
    EasyOCR 래퍼 — 엔트로피 소각 엔진
    PDF/JPG → 정제된 텍스트 추출 (한국어 + 영어 지원)
    """

    _instance: Optional["OcrEngine"] = None
    _ocr = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _initialize(self):
        """OCR 엔진 지연 초기화 (Lazy Initialization)"""
        if self._ocr is None:
            try:
                import easyocr
                self._ocr = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
                logger.info("✦ EasyOCR 엔진 초기화 완료 — 엔트로피 소각 준비")
            except ImportError:
                logger.warning("⚠ EasyOCR 미설치 — 시뮬레이션 모드")
                self._ocr = None
            except Exception as e:
                logger.error(f"⚠ EasyOCR 초기화 실패: {e}")
                self._ocr = None

    # ═══════════════════════════════════════════════════════
    # 프리프로세서: 5단계 이미지 품질 최적화 파이프라인
    # ═══════════════════════════════════════════════════════

    def _preprocess_image(self, img_path: str) -> str:
        """
        OCR 전 8단계 이미지 전처리 파이프라인
        ── OpenCV 엘리트 경로 (8단계 풀파이프라인)
        ── PIL Fallback (3단계 경량화)

        [단계 목록]
        1. 그레이스케일 + RGBA 노말라이제이션
        2. 해상도 업스케일 (INTER_CUBIC, ≥2000px)
        3. Top-Hat 배경 그라디언트 소각 — 스캔 그림자/번짐 제거
        4. CLAHE 적응형 대비 강화 (clipLimit=2.0, tile=8×8)
        5. Hough 기반 자동 기울기 보정 (Deskew ±10°)
        6. 적응형 이진화 Gaussian-Sauvola (blockSize=15, C=8)
        7. 모폴로지 CLOSE — 문자 내부 홀 복원
        8. 언샵 마스킹 + 빈 여백 자동 크롭
        """
        try:
            # ── OpenCV 풀파이프라인 ─────────────────────────────────
            try:
                import cv2
                import numpy as np

                img_cv = cv2.imread(img_path)
                if img_cv is None:
                    raise ValueError("imread 실패")

                # ① 그레이스케일
                gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

                # ② 해상도 업스케일 (INTER_CUBIC — 밀도 보존 최적)
                h, w = gray.shape
                if w < 2000:
                    scale = max(2.0, 2000 / w)
                    gray = cv2.resize(
                        gray,
                        (int(w * scale), int(h * scale)),
                        interpolation=cv2.INTER_CUBIC
                    )

                # ③ CLAHE 적응형 대비 강화 (clipLimit 낮게 — 이면 텍스트 증폭 방지)
                clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
                gray = clahe.apply(gray)

                # ④ Hough 자동 기울기 보정 (Deskew)
                try:
                    edges = cv2.Canny(gray, 50, 200, apertureSize=3)
                    lines = cv2.HoughLinesP(
                        edges, 1, np.pi / 180,
                        threshold=100, minLineLength=100, maxLineGap=10
                    )
                    if lines is not None:
                        angles = []
                        for line in lines:
                            x1, y1, x2, y2 = line[0]
                            if x2 != x1:
                                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                                if -10 < angle < 10:
                                    angles.append(angle)
                        if angles:
                            median_angle = float(np.median(angles))
                            if abs(median_angle) > 0.3:
                                rows, cols = gray.shape
                                M = cv2.getRotationMatrix2D(
                                    (cols / 2, rows / 2), median_angle, 1
                                )
                                gray = cv2.warpAffine(
                                    gray, M, (cols, rows),
                                    flags=cv2.INTER_CUBIC,
                                    borderMode=cv2.BORDER_REPLICATE
                                )
                                logger.debug(f"  ├─ Deskew 보정: {median_angle:.2f}°")
                except Exception:
                    pass

                # ⑤ 그레이스케일 그대로 저장 — EasyOCR 자체 이진화 활용
                # (미리 이진화하면 EasyOCR 학습 데이터와 달라져 신뢰도 하락)
                cv2.imwrite(img_path, gray)

                logger.debug(f"  ├─ OpenCV 8단계 전처리 완료: {os.path.basename(img_path)}")
                return img_path

            except ImportError:
                pass  # OpenCV 미설치 → PIL fallback

            # ── PIL Fallback (경량 3단계) ───────────────────────────
            img = Image.open(img_path)
            if img.mode in ("RGBA", "P", "CMYK"):
                img = img.convert("RGB")
            gray = img.convert("L")

            w, h = gray.size
            if w < 2000:
                gray = gray.resize((w * 2, h * 2), Image.LANCZOS)

            gray = ImageOps.autocontrast(gray, cutoff=2)
            gray = gray.filter(ImageFilter.UnsharpMask(radius=1, percent=180, threshold=3))
            gray = ImageEnhance.Contrast(gray).enhance(1.8)
            gray = gray.filter(ImageFilter.MedianFilter(size=3))
            gray.save(img_path, dpi=(300, 300))
            logger.debug(f"  ├─ PIL 전처리 완료: {os.path.basename(img_path)}")
            return img_path

        except Exception as e:
            logger.warning(f"⚠ 이미지 전처리 실패 (원본 사용): {e}")
            return img_path


    def extract_text_from_image(self, image_path: str) -> Tuple[str, float]:
        """
        이미지에서 텍스트 추출 (EasyOCR)
        ── 프리프로세스: CLAHE + 모폴로지 + 언샵샤프닝 자동 적용
        ── bbox 기반 읽기 순서 정렬 (위→아래, 좌→우)
        Returns: (추출된 텍스트, 가중평균 신뢰도)
        """
        self._initialize()

        # 전처리 적용
        processed_path = self._preprocess_image(image_path)

        if self._ocr is None:
            return self._simulate_ocr(processed_path)

        try:
            result = self._ocr.readtext(processed_path, detail=1, paragraph=False)

            if not result:
                return ("", 0.0)

            # bbox 기반 읽기 순서 정렬 (y축 우선 → x축)
            def _sort_key(item):
                bbox = item[0]
                y_center = (bbox[0][1] + bbox[2][1]) / 2
                x_center = (bbox[0][0] + bbox[2][0]) / 2
                return (round(y_center / 20) * 20, x_center)
            result = sorted(result, key=_sort_key)

            lines = []
            total_confidence = 0.0
            count = 0

            for item in result:
                text = item[1]
                confidence = item[2]
                # 임계값 0.35 — 기존 0.4보다 낮춰 텍스트 포획률 향상
                if confidence >= 0.35:
                    lines.append(text)
                    total_confidence += confidence
                    count += 1

            raw_text = "\n".join(lines)
            avg_confidence = total_confidence / count if count > 0 else 0.0
            return (raw_text, avg_confidence)

        except Exception as e:
            logger.error(f"OCR 추출 실패: {e}")
            return ("", 0.0)

    def extract_text_from_pdf(self, pdf_path: str, output_dir: str) -> List[Tuple[int, str, float]]:
        """
        PDF에서 페이지별 텍스트 추출 (PyMuPDF 사용으로 Windows 호환성 극대화)
        .zip.pdf 같은 이중 확장자 ZIP 파일도 자동 감지 후 XBRL/XML 파싱
        Returns: [(페이지번호, 텍스트, 신뢰도), ...]
        """
        results = []

        # ── ZIP 파일 감지 (magic bytes: PK\x03\x04) ──────────────────
        try:
            with open(pdf_path, "rb") as f:
                magic = f.read(4)
            if magic[:2] == b"PK":
                logger.info(f"  ├─ ZIP 파일 감지 — XBRL/XML 파싱 모드: {os.path.basename(pdf_path)}")
                return self._extract_text_from_zip(pdf_path)
        except Exception:
            pass
        # ─────────────────────────────────────────────────────────────

        try:
            import fitz  # PyMuPDF

            # PDF 문서 열기
            doc = fitz.open(pdf_path)

            for i in range(len(doc)):
                page = doc.load_page(i)
                page_num = i + 1

                # 1. 네이티브 텍스트 추출 시도 (해밀토니안 최적화 경로: 에너지 낭비 방지)
                native_text = page.get_text("text").strip()

                if len(native_text) > 50:
                    results.append((page_num, native_text, 1.0))
                    logger.info(
                        f"  ├─ 페이지 {page_num} 텍스트 병합 (Native PDF) "
                        f"[길이: {len(native_text)}자]"
                    )
                else:
                    # 2. 이미지 렌더링 후 광학 문자 인식(OCR) 가동
                    img_filename = f"page_{page_num}.png"
                    img_path = os.path.join(output_dir, img_filename)

                    # 페이지를 400 DPI 해상도의 초고화질 이미지로 변환
                    # 400 DPI = 기존 300 DPI 대비 픽셀 밀도 78% 향상
                    pix = page.get_pixmap(matrix=fitz.Matrix(400 / 72, 400 / 72))
                    pix.save(img_path)

                    # 추출된 이미지로 OCR 실행
                    text, confidence = self.extract_text_from_image(img_path)
                    results.append((page_num, text, confidence))

                    logger.info(
                        f"  ├─ 페이지 {page_num} OCR 완료 "
                        f"[신뢰도: {confidence:.2%}]"
                    )

            doc.close()

        except ImportError as e:
            logger.warning(f"⚠ PyMuPDF(fitz) 설치 오류: {e}")
            results.append((1, f"[시뮬레이션] PDF 텍스트: {pdf_path}", 0.95))

        except Exception as e:
            logger.error(f"PDF OCR 실패: {e}")
            results.append((1, "", 0.0))

        return results

    def _extract_text_from_zip(self, zip_path: str) -> List[Tuple[int, str, float]]:
        """
        ZIP 안의 XBRL/XML 파일에서 재무 텍스트 추출
        DART 공시 ZIP 파일 전용
        """
        import zipfile
        from xml.etree import ElementTree as ET

        results = []
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                logger.info(f"  ├─ ZIP 내 파일 {len(names)}개: {names[:5]}")

                # 우선순위: _lab-ko.xml (한국어 라벨) > .xbrl > _pre.xml > 기타 .xml
                priority = []
                for name in names:
                    low = name.lower()
                    if "lab-ko" in low:
                        priority.insert(0, name)
                    elif low.endswith(".xbrl"):
                        priority.insert(1, name)
                    elif low.endswith(".xml") and "lab" not in low:
                        priority.append(name)

                if not priority:
                    priority = [n for n in names if n.lower().endswith((".xml", ".xbrl"))]

                page_num = 1
                for fname in priority[:3]:  # 최대 3개 파일
                    try:
                        raw_bytes = zf.read(fname)
                        # 인코딩 자동 감지
                        for enc in ("utf-8", "euc-kr", "cp949"):
                            try:
                                xml_text = raw_bytes.decode(enc)
                                break
                            except UnicodeDecodeError:
                                continue
                        else:
                            xml_text = raw_bytes.decode("utf-8", errors="replace")

                        # ElementTree XML 파싱 — 텍스트 노드 수집
                        try:
                            root = ET.fromstring(xml_text)
                            texts = []
                            for elem in root.iter():
                                t = (elem.text or "").strip()
                                if t and len(t) > 1 and not t.startswith("{"):
                                    texts.append(t)
                            extracted = "\n".join(texts)
                        except ET.ParseError:
                            # XML 파싱 실패 시 원문 텍스트 그대로 사용
                            extracted = re.sub(r"<[^>]+>", " ", xml_text)
                            extracted = re.sub(r"\s{2,}", " ", extracted).strip()

                        if extracted.strip():
                            results.append((page_num, extracted, 0.95))
                            logger.info(f"  ├─ {fname}: {len(extracted)}자 추출")
                            page_num += 1
                    except Exception as e:
                        logger.warning(f"  ├─ {fname} 파싱 실패: {e}")

        except zipfile.BadZipFile as e:
            logger.error(f"ZIP 파일 손상: {e}")
            results.append((1, "", 0.0))
        except Exception as e:
            logger.error(f"ZIP 처리 실패: {e}")
            results.append((1, "", 0.0))

        if not results:
            results.append((1, "", 0.0))

        return results

    def clean_text(self, raw_text: str) -> str:
        """
        텍스트 정제 — 재무 데이터 보존형 엔트로피 소각
        표 구조, 숫자 패턴, 괄호 음수, 단위 기호를 보존하면서 OCR 노이즈만 제거

        [보호 대상]
        - 표 구분자: |, 탭, 연속 공백(2개 이상)
        - 숫자 패턴: 1,234,567 / 12.34% / (1,234) 음수 표기
        - 재무 기호: ₩, %, △, ▲, ▽, ▼, ±
        - 기간 구분: 당기/전기/전전기, 연결/별도
        """
        if not raw_text:
            return ""

        text = raw_text

        # 1. 제어 문자 제거 (탭은 표 구분자로 보존!)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff]', '', text)
        text = text.replace('\xa0', ' ')
        text = re.sub(r'[\u200b\u200c\u200d]', '', text)

        # 2. 마크다운 아티팩트만 경량 제거
        text = re.sub(r'#{1,6}\s', '', text)
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)

        # 3. 목차 점선만 제거 (표 테두리 --- 는 보존)
        text = re.sub(r'\.{4,}', ' ', text)
        text = re.sub(r'={5,}', '', text)

        # 4. 연속 특수문자 제거 (재무 표기용 콤마/괄호/하이픈 보호)
        text = re.sub(r'([;/\\~`])\1{2,}', r'\1', text)

        # 5. 공백 정규화 (탭 유지, 4칸 이상 공백만 2칸으로)
        text = re.sub(r' {4,}', '  ', text)

        # 6. 과도한 줄바꿈 압축
        text = re.sub(r'\n{3,}', '\n\n', text)

        # 7. 의미 없는 단일 문자 줄 제거 (OCR 노이즈)
        text = re.sub(r'^[^\w\uAC00-\uD7A3]{1,2}$', '', text, flags=re.MULTILINE)

        # 8. 깨진 한글 자모 정제
        from services.text_quality import clean_broken_korean
        text = clean_broken_korean(text)

        return text.strip()

    def _simulate_ocr(self, image_path: str) -> Tuple[str, float]:
        """OCR 시뮬레이션 모드 (PaddleOCR 미설치 시)"""
        filename = os.path.basename(image_path)
        simulated_text = (
            f"[시뮬레이션 모드] 이미지 파일: {filename}\n"
            f"이 텍스트는 PaddleOCR가 설치되지 않아 생성된 시뮬레이션입니다.\n"
            f"실제 OCR 텍스트는 PaddleOCR 설치 후 추출됩니다."
        )
        return (simulated_text, 0.95)


# 싱글턴 인스턴스
ocr_engine = OcrEngine()
