from __future__ import annotations

import re
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# =========================================================
# 1) 기본 설정
# =========================================================

TEMPLATE_VERSION = "embedding_prompt_v1"
DEFAULT_SUB_TYPE = "일반 공시"

FINANCIAL_KEYWORDS = [
    "재무상태표", "손익계산서", "포괄손익계산서", "현금흐름표", "자본변동표",
    "주석", "차입금", "유동부채", "비유동부채", "우발부채", "리스",
    "충당부채", "파생상품", "감가상각", "매출채권", "재고자산",
    "손상차손", "현금및현금성자산", "영업활동현금흐름", "유형자산", "무형자산",
]

EVENT_KEYWORDS = [
    "유상증자", "무상증자", "전환사채", "신주인수권부사채", "교환사채",
    "합병", "분할", "정정신고", "주요사항보고서", "최대주주 변경",
    "타법인 주식 취득", "타법인 주식 처분", "주식취득결정", "주식처분결정",
    "신주 발행", "자금조달", "운영자금", "시설자금", "채무상환", "희석",
]

AUDIT_KEYWORDS = [
    "감사의견", "한정", "부적정", "의견거절", "강조사항", "핵심감사사항", "계속기업",
]

GOVERNANCE_KEYWORDS = [
    "지배구조", "최대주주", "특수관계인", "이사회", "감사위원회", "사외이사", "의결권",
]

FUNDING_KEYWORDS = [
    "운영자금", "시설자금", "채무상환", "타법인증권취득자금", "자금 사용 목적", "자금조달",
]

TAG_RULES: dict[str, list[str]] = {
    "유동성": ["유동성", "현금및현금성자산", "현금성자산", "유동부채", "운전자본"],
    "단기차입금": ["단기차입금"],
    "장기차입금": ["장기차입금"],
    "영업현금흐름": ["영업활동현금흐름", "영업현금흐름"],
    "CAPEX": ["설비투자", "시설투자", "유형자산 취득", "CAPEX"],
    "우발부채": ["우발부채", "소송", "보증채무"],
    "충당부채": ["충당부채"],
    "리스": ["리스", "사용권자산", "리스부채"],
    "파생상품": ["파생상품", "파생부채", "파생자산"],
    "감사의견": ["감사의견", "의견거절", "한정", "부적정"],
    "계속기업": ["계속기업"],
    "유상증자": ["유상증자"],
    "무상증자": ["무상증자"],
    "전환사채": ["전환사채", "CB"],
    "신주인수권부사채": ["신주인수권부사채", "BW"],
    "합병": ["합병"],
    "분할": ["분할"],
    "희석효과": ["희석", "희석효과", "신주 발행"],
    "운영자금": ["운영자금"],
    "시설자금": ["시설자금"],
    "채무상환": ["채무상환"],
    "지배구조": ["지배구조", "이사회", "감사위원회", "사외이사"],
    "최대주주": ["최대주주", "특수관계인"],
    "매출채권": ["매출채권"],
    "재고자산": ["재고자산"],
    "손상차손": ["손상차손"],
}

# =========================================================
# 2) 데이터 구조
# =========================================================

@dataclass
class FilingChunk:
    doc_id: str
    chunk_id: str
    chunk_text: str
    company_name: str = ""
    doc_type: str = ""
    filing_type: str = ""
    filing_date: str = ""
    period: str = ""
    section_title: str = ""
    sub_type: Optional[str] = None
    topic_tags: list[str] = field(default_factory=list)
    page: Optional[int] = None
    source_file: str = ""
    source_path: str = ""

@dataclass
class PreparedEmbeddingItem:
    id: str
    document: str
    metadata: dict[str, Any]

# =========================================================
# 3) 유틸리티
# =========================================================

def normalize_whitespace(text: str) -> str:
    if not text: return ""
    text = text.replace("\u00a0", " ")
    text = text.replace("\t", " ")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def one_line(text: str) -> str:
    if not text: return ""
    text = normalize_whitespace(text)
    text = text.replace("\n", " / ")
    return text.strip()

def dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        value = item.strip()
        if not value: continue
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

def safe_short(text: str, limit: int = 300) -> str:
    text = normalize_whitespace(text)
    return text[:limit]

# =========================================================
# 4) 세부유형 및 태그 추론
# =========================================================

def infer_sub_type(doc_type: str, filing_type: str, section_title: str, chunk_text: str) -> str:
    joined = " ".join([
        doc_type or "",
        filing_type or "",
        section_title or "",
        chunk_text[:2000] if chunk_text else "",
    ]).lower()

    if any(k.lower() in joined for k in AUDIT_KEYWORDS): return "감사/의견"
    if any(k.lower() in joined for k in GOVERNANCE_KEYWORDS): return "지배구조"
    if any(k.lower() in joined for k in EVENT_KEYWORDS):
        if any(k.lower() in joined for k in FUNDING_KEYWORDS): return "자금조달"
        return "공시 이벤트"
    if any(k.lower() in joined for k in FINANCIAL_KEYWORDS): return "재무제표/주석"
    return DEFAULT_SUB_TYPE

def infer_topic_tags(section_title: str, chunk_text: str, existing_tags: Optional[list[str]] = None, max_tags: int = 8) -> list[str]:
    existing_tags = existing_tags or []
    base_tags = dedupe_keep_order(existing_tags)
    joined = " ".join([section_title or "", chunk_text[:4000] if chunk_text else ""]).lower()
    inferred = []
    for tag, keywords in TAG_RULES.items():
        if any(k.lower() in joined for k in keywords):
            inferred.append(tag)
    merged = dedupe_keep_order(base_tags + inferred)
    return merged[:max_tags]

# =========================================================
# 5) 최종 가공 로직
# =========================================================

def build_embedding_text(chunk: FilingChunk) -> str:
    sub_type = chunk.sub_type or infer_sub_type(chunk.doc_type, chunk.filing_type, chunk.section_title, chunk.chunk_text)
    topic_tags = infer_topic_tags(chunk.section_title, chunk.chunk_text, chunk.topic_tags)

    fields = [
        ("문서유형", one_line(chunk.doc_type)),
        ("회사명", one_line(chunk.company_name)),
        ("공시종류", one_line(chunk.filing_type)),
        ("세부유형", one_line(sub_type)),
        ("공시일", one_line(chunk.filing_date)),
        ("보고기간", one_line(chunk.period)),
        ("섹션", one_line(chunk.section_title)),
        ("핵심태그", ", ".join(topic_tags)),
    ]
    header = "\n".join([f"{k}: {v}" for k, v in fields if v])
    body = normalize_whitespace(chunk.chunk_text)
    return f"{header}\n\n본문:\n{body}"

def build_metadata(chunk: FilingChunk) -> dict[str, Any]:
    sub_type = chunk.sub_type or infer_sub_type(chunk.doc_type, chunk.filing_type, chunk.section_title, chunk.chunk_text)
    topic_tags = infer_topic_tags(chunk.section_title, chunk.chunk_text, chunk.topic_tags)

    meta = {
        "doc_id": chunk.doc_id,
        "chunk_id": chunk.chunk_id,
        "company_name": one_line(chunk.company_name),
        "doc_type": one_line(chunk.doc_type),
        "filing_type": one_line(chunk.filing_type),
        "sub_type": one_line(sub_type),
        "filing_date": one_line(chunk.filing_date),
        "period": one_line(chunk.period),
        "section_title": one_line(chunk.section_title),
        "topic_tags": ", ".join(topic_tags),
        "template_version": TEMPLATE_VERSION,
        "text_preview": safe_short(chunk.chunk_text, limit=300),
    }
    if chunk.page is not None: meta["page"] = int(chunk.page)
    if chunk.source_file: meta["source_file"] = one_line(chunk.source_file)
    if chunk.source_path: meta["source_path"] = one_line(chunk.source_path)
    return meta

def prepare_embedding_item(chunk: FilingChunk) -> PreparedEmbeddingItem:
    document = build_embedding_text(chunk)
    metadata = build_metadata(chunk)
    item_id = chunk.chunk_id.strip() or str(uuid.uuid4())
    return PreparedEmbeddingItem(id=item_id, document=document, metadata=metadata)
