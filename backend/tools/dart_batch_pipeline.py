"""
═══════════════════════════════════════════════════════════════════
Omega CivicFlow — DART Batch Pipeline v2.0 (EXAONE 3.5 최적화)
═══════════════════════════════════════════════════════════════════

실행 순서:
  Phase 0 : ChromaDB 초기화 여부 선택
  Phase 1 : ZIP/ZIP.PDF 압축 해제 → XML 파싱 → 텍스트 추출
  Phase 2 : EXAONE 전처리 (노이즈 제거, 중국어 완전 배제, 압축)
  Phase 3 : 임베딩 → ChromaDB 벡터 저장
  Phase 4 : PDF 요약 리포트 생성 (선택)

실행 방법:
  cd <project-root>/backend
  .venv/Scripts/python tools/dart_batch_pipeline.py

체크포인트:
  - tools\\pipeline_checkpoint.json : 완료된 파일 목록 (중간 재시작 지원)
═══════════════════════════════════════════════════════════════════
"""

import sys
import os
import zipfile
import json
import re
import hashlib
import logging
import time
import pathlib
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple
from datetime import datetime

# ── 경로 설정 ──
BACKEND_DIR = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

DATASET_DIR = pathlib.Path(os.environ.get("OMEGA_DATASET_DIR", str(BACKEND_DIR.parent / "DataSet")))
CHECKPOINT_FILE = BACKEND_DIR / "tools" / "pipeline_checkpoint.json"
LOG_FILE = BACKEND_DIR / "tools" / "pipeline_run.log"

# ── 로깅 설정 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("DARTPipeline")


# ═══════════════════════════════════════════════════════
# HTML 텍스트 추출 헬퍼 (html.parser 기반)
# ═══════════════════════════════════════════════════════

class _DartHTMLTextExtractor(HTMLParser):
    """
    DART 전자공시 XML/HTML 혼재 포맷 전용 텍스트 추출기
    
    html.parser는 비정형 HTML도 관대하게 처리하므로
    DART XML의 비표준 구조에 적합
    """

    # 텍스트를 수집하지 않는 태그
    SKIP_TAGS = {"style", "script", "formula-version", "noscript"}

    # 블록 레벨 태그 (개행 처리)
    BLOCK_TAGS = {"p", "div", "tr", "li", "h1", "h2", "h3", "h4",
                  "section", "article", "br", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._lines: List[str] = []
        self._current: List[str] = []
        self._skip_depth = 0
        self._skip_tag = None

    def handle_starttag(self, tag: str, attrs):
        tag_lower = tag.lower()
        if tag_lower in self.SKIP_TAGS:
            self._skip_depth += 1
            self._skip_tag = tag_lower
        if tag_lower in self.BLOCK_TAGS and self._current:
            text = " ".join(self._current).strip()
            if text:
                self._lines.append(text)
            self._current = []

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if self._skip_tag and tag_lower == self._skip_tag:
            self._skip_depth = max(0, self._skip_depth - 1)
            if self._skip_depth == 0:
                self._skip_tag = None
        if tag_lower in self.BLOCK_TAGS and self._current:
            text = " ".join(self._current).strip()
            if text:
                self._lines.append(text)
            self._current = []

    def handle_data(self, data: str):
        if self._skip_depth > 0:
            return
        text = data.strip()
        if text:
            self._current.append(text)

    def get_text_lines(self) -> List[str]:
        # 마지막 잔여 텍스트 처리
        if self._current:
            text = " ".join(self._current).strip()
            if text:
                self._lines.append(text)
        return self._lines


# ═══════════════════════════════════════════════════════
# Phase 1: XML 파서 — DART 전자공시 XML/XBRL 텍스트 추출
# ═══════════════════════════════════════════════════════

class DartXmlExtractor:
    """
    DART 전자공시 XML (HTML 태그 혼재) → 순수 텍스트 변환
    
    특징:
    - XML/XBRL 두 포맷 모두 처리
    - HTML 태그 완전 제거
    - 표 구조 보존 (탭 구분 텍스트로)
    - 메타데이터 추출 (회사명, 보고서 유형, 연도)
    """

    # DART XML 핵심 태그들
    TEXT_TAGS = {"P", "TD", "TH", "SPAN", "DIV", "SECTION", "TITLE",
                 "COMPANY-NAME", "REPORT-NAME", "PERIOD"}

    # 제거할 태그 (버리는 것이 좋은 태그)
    SKIP_TAGS = {"STYLE", "SCRIPT", "FORMULA-VERSION", "TABLE-GROUP"}

    # 중국어 범위 (완전 제거)
    CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")

    def extract_from_zip(self, zip_path: pathlib.Path) -> Tuple[str, Dict]:
        """
        ZIP(또는 ZIP.PDF) 파일에서 텍스트와 메타데이터 추출
        Returns: (extracted_text, metadata_dict)
        """
        metadata = self._parse_filename_metadata(zip_path.name)
        all_texts = []

        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()

                # 메인 XML 우선, 서브 XML 후 처리
                main_xmls = [n for n in names if n.endswith(".xml") and
                             not any(x in n for x in ["_00760", "_00761", "_00762", "_00763"])]
                sub_xmls = [n for n in names if n.endswith(".xml") and
                            any(x in n for x in ["_00760", "_00761", "_00762", "_00763"])]
                xbrls = [n for n in names if n.endswith(".xbrl")]

                for xml_name in main_xmls + sub_xmls + xbrls:
                    try:
                        raw = zf.read(xml_name)
                        text = self._parse_xml_content(raw, xml_name)
                        if text:
                            all_texts.append(text)
                    except Exception as e:
                        logger.debug(f"  XML 파싱 실패 ({xml_name}): {e}")

        except zipfile.BadZipFile:
            logger.warning(f"  손상된 ZIP: {zip_path.name}")
            return "", metadata
        except Exception as e:
            logger.warning(f"  ZIP 읽기 실패 ({zip_path.name}): {e}")
            return "", metadata

        combined = "\n\n".join(all_texts)
        return combined, metadata

    def _parse_xml_content(self, raw: bytes, filename: str) -> str:
        """XML/HTML 혼재 바이트 → 순수 텍스트"""
        # 인코딩 감지
        for enc in ["utf-8", "euc-kr", "cp949", "utf-8-sig"]:
            try:
                content = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            content = raw.decode("utf-8", errors="replace")

        # XBRL 처리 (다른 파싱 전략)
        if filename.endswith(".xbrl"):
            return self._parse_xbrl(content)

        # XML/HTML 혼재 처리
        return self._parse_dart_xml(content)

    def _parse_dart_xml(self, content: str) -> str:
        """
        DART XML (HTML 태그 혼재) 파싱
        html.parser 사용 — DART의 비정형 XML/HTML 혼합 포맷에 최적
        """
        # STYLE/SCRIPT 블록 사전 제거 (텍스트 오염 방지)
        content = re.sub(r"<STYLE[^>]*>.*?</STYLE>", " ", content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r"<SCRIPT[^>]*>.*?</SCRIPT>", " ", content, flags=re.DOTALL | re.IGNORECASE)
        # XML 처리 지시자, DOCTYPE 제거
        content = re.sub(r"<\?[^>]*\?>", "", content)
        content = re.sub(r"<!DOCTYPE[^>]*>", "", content)
        content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)

        # HTML 속성들 제거 (태그는 유지, 속성만 제거 → 텍스트 흐름 보존)
        # DART XML 속성 패턴: WIDTH="211" HEIGHT="23" CLASS="NORMAL" 등
        content = re.sub(r'\s+(?:WIDTH|HEIGHT|CLASS|STYLE|VALIGN|ALIGN|BGCOLOR|BORDER|CELLPADDING|COLSPAN|ROWSPAN|ACLASS|ACOPY|ADELETE|AUPDATECONT|ENG|USERMARK|ACLASS|ADELETETABLE)=["\'][^"\']*["\']', "", content, flags=re.IGNORECASE)

        # html.parser 기반 텍스트 추출
        parser = _DartHTMLTextExtractor()
        parser.feed(content)
        texts = parser.get_text_lines()

        # 노이즈 필터
        lines = [l for l in texts if l.strip() and not self._is_noise(l.strip())]
        return "\n".join(lines)

    def _parse_xbrl(self, content: str) -> str:
        """XBRL 파싱 — 태그명=값 형식으로 추출"""
        # XBRL은 네임스페이스 태그: {ns}TagName>value</
        # 정규식으로 값만 빠르게 추출
        values = re.findall(r">([^<]{2,200})<", content)
        lines = []
        for v in values:
            v = v.strip()
            if v and not self._is_noise(v) and len(v) >= 2:
                lines.append(v)
        return "\n".join(lines)

    def _is_noise(self, text: str) -> bool:
        """노이즈 텍스트 판별"""
        if len(text) < 2:
            return True
        # 순수 숫자/기호만
        if re.match(r"^[\d\s,.\-–—:/|%\[\](){}]+$", text):
            return False  # 재무 숫자는 유지
        # 중국어 포함
        if self.CHINESE_PATTERN.search(text):
            return True
        # 반복 문자
        if len(set(text.replace(" ", ""))) <= 2 and len(text) > 5:
            return True
        # HTML 속성값 잔여물
        if re.match(r"^[A-Z_\-]{3,}=", text):
            return True
        return False

    def _parse_filename_metadata(self, filename: str) -> Dict:
        """
        파일명에서 메타데이터 추출
        패턴: DART_P{tier}_{company}_{date}{rcept_no}.zip(.pdf)
        """
        name = filename.replace(".zip.pdf", "").replace(".zip", "")
        parts = name.split("_")

        metadata = {
            "filename": filename,
            "tier": "",
            "company": "",
            "report_date": "",
            "rcept_no": "",
            "report_type": "사업보고서",
        }

        if len(parts) >= 2:
            metadata["tier"] = parts[1]  # P0, P1, P2

        if len(parts) >= 3:
            metadata["company"] = parts[2]

        if len(parts) >= 4:
            date_no = parts[3]
            if len(date_no) >= 8:
                metadata["report_date"] = date_no[:8]  # YYYYMMDD
                metadata["rcept_no"] = date_no[8:] if len(date_no) > 8 else ""

        # P0 = 사업보고서, P1 = 감사보고서, P2 = 분기/반기
        tier_map = {"P0": "사업보고서", "P1": "감사보고서", "P2": "분기보고서"}
        metadata["report_type"] = tier_map.get(metadata["tier"], "기타")

        return metadata


# ═══════════════════════════════════════════════════════
# Phase 2: EXAONE 전용 전처리 (노이즈 최소화)
# ═══════════════════════════════════════════════════════

class ExaonePreprocessor:
    """
    EXAONE 3.5 7.8B 모델 전용 전처리
    
    핵심 원칙:
    1. 중국어 완전 제거 (Qwen 오염 방지)
    2. HTML/XML 잔여물 제거
    3. 반복·중복 라인 제거
    4. 재무 수치 보존 (숫자 파괴 금지)
    5. 섹션 구조 최대 보존
    6. 압축: 불필요 공백·빈줄 정리
    """

    # 제거 패턴 목록
    NOISE_PATTERNS = [
        re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+"),  # 중국어
        re.compile(r"[\u3040-\u30ff]+"),                              # 일본어
        re.compile(r"<[A-Za-z/][^>]{0,200}>"),                       # HTML 잔여 태그
        re.compile(r"&[a-z]{2,8};"),                                  # HTML 엔티티
        re.compile(r"https?://\S+"),                                  # URL
        re.compile(r"[A-Z_]{5,}=['\"][^'\"]{0,50}['\"]"),           # XML 속성
        re.compile(r"xmlns[:\w]*=['\"][^'\"]*['\"]"),                 # XML 네임스페이스
        re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"),           # 제어문자
    ]

    # 한글 밀도 최소 임계값 (EXAONE 최적화 — 중국어 없으므로 더 엄격하게)
    MIN_KOREAN_RATIO = 0.10  # 10% 이상 한글이어야 유효 라인

    def preprocess(self, raw_text: str, metadata: Dict) -> str:
        """전체 전처리 파이프라인"""
        if not raw_text:
            return ""

        text = raw_text

        # 1. 노이즈 패턴 제거
        for pattern in self.NOISE_PATTERNS:
            text = pattern.sub(" ", text)

        # 2. 라인 단위 처리
        lines = text.split("\n")
        cleaned_lines = []
        seen_lines = set()

        for line in lines:
            line = self._clean_line(line)
            if not line:
                continue

            # 중복 라인 제거 (완전 동일한 라인)
            line_key = line[:80]
            if line_key in seen_lines:
                continue
            seen_lines.add(line_key)

            cleaned_lines.append(line)

        # 3. 연속 빈줄 단일화
        result_lines = []
        prev_empty = False
        for line in cleaned_lines:
            is_empty = not line.strip()
            if is_empty and prev_empty:
                continue
            result_lines.append(line)
            prev_empty = is_empty

        # 4. 회사명·보고서 유형 헤더 추가
        header = self._build_header(metadata)
        final_text = header + "\n".join(result_lines)

        # 5. 길이 압축 (최대 100,000자 — EXAONE 7.8B 컨텍스트 고려)
        if len(final_text) > 100_000:
            final_text = self._smart_truncate(final_text, 100_000)

        return final_text.strip()

    def _clean_line(self, line: str) -> str:
        """단일 라인 정제 (DART 아티팩트 포함)"""
        line = line.strip()
        if not line:
            return ""

        # 너무 짧은 라인 (의미 없는 단일 문자/기호)
        if len(line) < 3 and not re.search(r"\d", line):
            return ""

        # 순수 기호/특수문자 라인
        if re.match(r"^[=\-_\*\.·•○●◆◇▶▷►\s]{5,}$", line):
            return ""

        # DART OCR 아티팩트: 단일 대문자 공백 나열 ("C Z Y", "A B C")
        if re.match(r"^(?:[A-Z] ){2,}[A-Z]?$", line.strip()):
            return ""

        # 페이지 번호만 있는 라인
        if re.match(r"^\d{1,4}[\s\-─]?$", line):
            return ""

        # 이미지 파일명 잔여물 제거
        line = re.sub(r"\S+\.(?:jpg|png|gif|bmp|jpeg|svg)\b", "", line, flags=re.IGNORECASE).strip()
        if not line:
            return ""

        # 공백 정규화
        line = re.sub(r"[ \t]{2,}", " ", line)

        return line


    def _build_header(self, metadata: Dict) -> str:
        """문서 헤더 생성 (LLM 컨텍스트 주입)"""
        parts = []
        if metadata.get("company"):
            parts.append(f"회사명: {metadata['company']}")
        if metadata.get("report_type"):
            parts.append(f"보고서 유형: {metadata['report_type']}")
        if metadata.get("report_date"):
            d = metadata["report_date"]
            if len(d) == 8:
                parts.append(f"공시일: {d[:4]}년 {d[4:6]}월 {d[6:8]}일")
        if not parts:
            return ""
        return "[문서 정보]\n" + "\n".join(parts) + "\n\n"

    def _smart_truncate(self, text: str, max_len: int) -> str:
        """
        섹션 구조를 보존하며 스마트 트런케이션
        재무제표 섹션은 최대한 보존
        """
        if len(text) <= max_len:
            return text

        # 섹션 헤더 위치 탐지
        priority_sections = ["재무상태표", "손익계산서", "현금흐름표", "감사보고서", "사업의 내용"]
        lines = text.split("\n")

        # 우선 섹션 구간 보존
        kept = []
        total = 0
        for line in lines:
            if total + len(line) > max_len:
                break
            kept.append(line)
            total += len(line) + 1

        return "\n".join(kept)


# ═══════════════════════════════════════════════════════
# Phase 3: ChromaDB 임베딩 저장
# ═══════════════════════════════════════════════════════

def embed_and_store(
    text: str,
    metadata: Dict,
    doc_id: int,
    vector_service,
    collection_name: str = "omega_documents"
) -> int:
    """전처리된 텍스트를 임베딩하여 ChromaDB에 저장"""
    try:
        count = vector_service.index_document(
            doc_id=doc_id,
            filename=metadata.get("filename", ""),
            text=text,
            category=metadata.get("report_type", ""),
            company=metadata.get("company", ""),
            source="dart_xml",
            clear_existing=True,
            filing_date=metadata.get("report_date", ""),
            period=metadata.get("period", ""), # 만약 있으면
        )
        return count
    except Exception as e:
        logger.error(f"  임베딩 저장 실패 (doc_id={doc_id}): {e}")
        return 0


# ═══════════════════════════════════════════════════════
# 체크포인트 관리
# ═══════════════════════════════════════════════════════

class CheckpointManager:
    """처리된 파일 목록을 JSON으로 저장/복구"""

    def __init__(self, checkpoint_path: pathlib.Path):
        self.path = checkpoint_path
        self.completed: set = set()
        self.stats = {
            "total": 0, "success": 0, "failed": 0,
            "total_chunks": 0, "start_time": datetime.now().isoformat()
        }
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.completed = set(data.get("completed", []))
                self.stats = data.get("stats", self.stats)
                logger.info(f"체크포인트 복구: {len(self.completed)}개 이미 완료")
            except Exception:
                pass

    def save(self):
        data = {
            "completed": list(self.completed),
            "stats": self.stats,
            "updated": datetime.now().isoformat()
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def mark_done(self, filename: str, chunks: int):
        self.completed.add(filename)
        self.stats["success"] += 1
        self.stats["total_chunks"] += chunks
        if len(self.completed) % 50 == 0:
            self.save()  # 50개마다 자동 저장

    def mark_failed(self, filename: str):
        self.completed.add(filename + "_FAILED")
        self.stats["failed"] += 1

    def is_done(self, filename: str) -> bool:
        return filename in self.completed


# ═══════════════════════════════════════════════════════
# 메인 파이프라인 실행
# ═══════════════════════════════════════════════════════

def run_pipeline(
    reset_db: bool = False,
    max_files: Optional[int] = None,
    tier_filter: Optional[str] = None,
    skip_embed: bool = False,
):
    """
    전체 파이프라인 실행

    Args:
        reset_db: True면 ChromaDB 기존 데이터 전체 삭제 후 시작
        max_files: 테스트용 파일 수 제한 (None = 전체)
        tier_filter: "P0", "P1", "P2" 중 하나 (None = 전체)
        skip_embed: True면 임베딩 스킵 (텍스트 추출만)
    """
    logger.info("=" * 60)
    logger.info("Omega CivicFlow DART Batch Pipeline v2.0")
    logger.info(f"시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # ── 모듈 임포트 (가상환경 내) ──
    if not skip_embed:
        try:
            import services.vector_service as vector_service
            logger.info("✅ vector_service 임포트 성공")
        except ImportError as e:
            logger.error(f"vector_service 임포트 실패: {e}")
            logger.error("백엔드 디렉터리에서 실행하세요: cd backend && .venv/Scripts/python.exe ...")
            return

    # ── ChromaDB 초기화 (선택) ──
    if reset_db and not skip_embed:
        logger.info("⚠  ChromaDB 초기화 중...")
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
            from config import settings as app_settings
            client = chromadb.PersistentClient(
                path=app_settings.CHROMADB_DIR,
                settings=ChromaSettings(anonymized_telemetry=False)
            )
            for coll_name in ["omega_documents", "omega_document_chunks"]:
                try:
                    client.delete_collection(coll_name)
                    logger.info(f"  ✓ {coll_name} 삭제 완료")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"ChromaDB 초기화 실패: {e}")

    # ── 파일 목록 수집 ──
    all_files = [
        f for f in DATASET_DIR.iterdir()
        if f.suffix == ".zip" or f.name.endswith(".zip.pdf")
    ]
    # .tmp 폴더 제외
    all_files = [f for f in all_files if f.is_file()]

    if tier_filter:
        all_files = [f for f in all_files if f"_P{tier_filter[-1]}_" in f.name or f"DART_{tier_filter}_" in f.name]

    # 안정적인 정렬 (P0 → P1 → P2 순)
    all_files.sort(key=lambda f: (
        0 if "_P0_" in f.name else (1 if "_P1_" in f.name else 2),
        f.name
    ))

    if max_files:
        all_files = all_files[:max_files]

    logger.info(f"처리 대상: {len(all_files)}개 파일")

    # ── 컴포넌트 초기화 ──
    extractor = DartXmlExtractor()
    preprocessor = ExaonePreprocessor()
    checkpoint = CheckpointManager(CHECKPOINT_FILE)
    checkpoint.stats["total"] = len(all_files)

    # ── 메인 루프 ──
    t_start = time.time()

    for idx, zip_path in enumerate(all_files, 1):
        filename = zip_path.name

        # 체크포인트 확인
        if checkpoint.is_done(filename):
            logger.debug(f"[{idx}/{len(all_files)}] SKIP (완료됨): {filename}")
            continue

        logger.info(f"[{idx}/{len(all_files)}] 처리 중: {filename}")

        try:
            # Phase 1: 텍스트 추출
            raw_text, metadata = extractor.extract_from_zip(zip_path)

            if not raw_text or len(raw_text) < 100:
                logger.warning(f"  ⚠ 텍스트 부족 또는 빈 파일: {filename}")
                checkpoint.mark_failed(filename)
                continue

            logger.info(f"  ├─ 추출: {len(raw_text):,}자")

            # Phase 2: EXAONE 전처리
            clean_text = preprocessor.preprocess(raw_text, metadata)

            if not clean_text or len(clean_text) < 100:
                logger.warning(f"  ⚠ 전처리 후 텍스트 없음: {filename}")
                checkpoint.mark_failed(filename)
                continue

            logger.info(f"  ├─ 전처리: {len(clean_text):,}자 (압축률: {100-len(clean_text)*100//max(len(raw_text),1)}%)")

            # Phase 3: 임베딩 저장
            if skip_embed:
                chunks = 0
                logger.info(f"  └─ 임베딩 스킵 (skip_embed=True)")
            else:
                doc_id = abs(hash(filename)) % (10 ** 9)  # 파일명 기반 고유 ID
                chunks = embed_and_store(
                    clean_text, metadata, doc_id, vector_service
                )
                logger.info(f"  └─ 임베딩: {chunks}청크 저장")

            checkpoint.mark_done(filename, chunks)

        except Exception as e:
            logger.error(f"  ✗ 처리 실패 ({filename}): {e}", exc_info=True)
            checkpoint.mark_failed(filename)

        # 진행률 출력 (100개마다)
        if idx % 100 == 0:
            elapsed = time.time() - t_start
            rate = idx / elapsed
            eta = (len(all_files) - idx) / max(rate, 0.001)
            logger.info(
                f"\n{'='*40}\n"
                f"진행: {idx}/{len(all_files)} ({idx*100//len(all_files)}%)\n"
                f"완료: {checkpoint.stats['success']} | 실패: {checkpoint.stats['failed']}\n"
                f"총 청크: {checkpoint.stats['total_chunks']:,}\n"
                f"경과: {elapsed:.0f}초 | ETA: {eta:.0f}초\n"
                f"{'='*40}"
            )

    # ── 최종 저장 및 요약 ──
    checkpoint.save()
    elapsed_total = time.time() - t_start

    logger.info("\n" + "=" * 60)
    logger.info("파이프라인 완료")
    logger.info(f"총 파일: {checkpoint.stats['total']:,}")
    logger.info(f"성공: {checkpoint.stats['success']:,}")
    logger.info(f"실패: {checkpoint.stats['failed']:,}")
    logger.info(f"총 청크: {checkpoint.stats['total_chunks']:,}")
    logger.info(f"소요 시간: {elapsed_total:.1f}초 ({elapsed_total/60:.1f}분)")
    logger.info("=" * 60)


# ═══════════════════════════════════════════════════════
# 진단 모드 (테스트용)
# ═══════════════════════════════════════════════════════

def run_diagnostic(n_samples: int = 5):
    """소수 파일로 추출 품질 확인 (임베딩 없이)"""
    logger.info("=== 진단 모드 (임베딩 없이 텍스트 추출 확인) ===")

    files = [
        f for f in DATASET_DIR.iterdir()
        if (f.suffix == ".zip" or f.name.endswith(".zip.pdf")) and f.is_file()
    ][:n_samples]

    extractor = DartXmlExtractor()
    preprocessor = ExaonePreprocessor()

    for f in files:
        print(f"\n{'─'*50}")
        print(f"파일: {f.name}")
        raw, meta = extractor.extract_from_zip(f)
        clean = preprocessor.preprocess(raw, meta)
        print(f"메타: {meta}")
        print(f"원문: {len(raw):,}자 → 전처리: {len(clean):,}자")
        print("--- 텍스트 미리보기 (앞 500자) ---")
        print(clean[:500])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DART Batch Pipeline v2.0")
    parser.add_argument("--mode", choices=["full", "diag", "test"],
                        default="full", help="실행 모드")
    parser.add_argument("--reset", action="store_true",
                        help="ChromaDB 전체 초기화 후 시작")
    parser.add_argument("--tier", choices=["P0", "P1", "P2"],
                        default=None, help="처리할 티어 (기본: 전체)")
    parser.add_argument("--max", type=int, default=None,
                        help="최대 파일 수 (테스트용)")
    parser.add_argument("--skip-embed", action="store_true",
                        help="임베딩 스킵 (추출·전처리만)")
    args = parser.parse_args()

    if args.mode == "diag":
        run_diagnostic(n_samples=args.max or 5)
    elif args.mode == "test":
        run_pipeline(
            reset_db=False,
            max_files=args.max or 10,
            tier_filter=args.tier,
            skip_embed=True,
        )
    else:
        if args.reset:
            confirm = input("⚠  ChromaDB를 전체 초기화합니다. 계속? (yes/no): ")
            if confirm.lower() != "yes":
                print("취소됨.")
                sys.exit(0)
        run_pipeline(
            reset_db=args.reset,
            max_files=args.max,
            tier_filter=args.tier,
            skip_embed=args.skip_embed,
        )
