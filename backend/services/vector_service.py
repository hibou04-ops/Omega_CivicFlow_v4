"""
═══════════════════════════════════════════════════════
Omega CivicFlow — Vector Service
Omega Cognitive Engine 통합 RAG 파이프라인

하이브리드 검색 (벡터 + BM25) + 리랭킹 + 엔트로피 소각
═══════════════════════════════════════════════════════
"""

import re
import math
import logging
import hashlib
from typing import List, Dict, Optional, Any
from pathlib import Path
from collections import Counter, defaultdict

from services.embedding_strategy import FilingChunk, prepare_embedding_item, build_embedding_text

import httpx

from config import settings

logger = logging.getLogger(__name__)

# ── ChromaDB 지연 로드 ──
_chroma_client = None
_collection = None
_collections = {}

COLLECTION_NAME = getattr(settings, "CHROMA_COLLECTION_NAME", "omega_documents")
CHAT_CHUNK_COLLECTION_NAME = "omega_document_chunks_v2"


def _user_collection(user_id: int) -> str:
    """계정별 메인 문서 컬렉션 이름"""
    return f"omega_u{user_id}" if user_id else COLLECTION_NAME


def _user_chunk_collection(user_id: int) -> str:
    """계정별 청크 컬렉션 이름"""
    return f"omega_u{user_id}_chunks" if user_id else CHAT_CHUNK_COLLECTION_NAME
EMBED_MODEL = "nomic-embed-text"

# ── 청크 설정 (금융 문서 최적화) ──
CHUNK_SIZE = 1000       # 500→1000: 한국어 금융 문서 맥락 보존
CHUNK_OVERLAP = 150     # 80→150: 문장 경계 유실 방지

# ── Cognitive Engine 상수 ──
VECTOR_WEIGHT = 0.40     # 벡터 유사도 가중치 (0.5→0.40)
KEYWORD_WEIGHT = 0.25    # BM25 키워드 가중치 (0.3→0.25)
META_WEIGHT = 0.35       # 메타데이터 일치 가중치 (0.2→0.35, 회사명/연도 매칭 강화)
ENTROPY_THRESHOLD = 0.10  # 노이즈 임계값 완화 (0.25→0.10, recall 우선)
DEDUP_THRESHOLD = 0.80   # 중복 임계값 약간 완화 (0.85→0.80, 유사 문서 더 허용)


def _get_collection(collection_name: str = COLLECTION_NAME):
    """ChromaDB 컬렉션 지연 초기화"""
    global _chroma_client, _collection, _collections
    if collection_name in _collections:
        return _collections[collection_name]

    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        db_path = settings.CHROMADB_DIR
        _chroma_client = chromadb.PersistentClient(
            path=db_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = _chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        _collections[collection_name] = collection
        if collection_name == COLLECTION_NAME:
            _collection = collection
        logger.info(f"✦ ChromaDB 초기화 — {collection_name} / {collection.count()}건 벡터 로드")
        return collection
    except ImportError:
        logger.error("chromadb가 설치되지 않았습니다: pip install chromadb")
        return None
    except Exception as e:
        logger.error(f"ChromaDB 초기화 실패: {e}")
        return None


# ── bge-m3 임베딩 (collection 차원 1024 호환) ──
_bge_m3_model = None
_BGE_M3_DIM = 1024


def _get_bge_m3_model():
    """BAAI/bge-m3 SentenceTransformer 지연 로드 (1024-dim, collection 호환)"""
    global _bge_m3_model
    if _bge_m3_model is None:
        try:
            import os
            import torch
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            from sentence_transformers import SentenceTransformer
            device = "cuda" if torch.cuda.is_available() else "cpu"
            _bge_m3_model = SentenceTransformer(
                "BAAI/bge-m3",
                device=device,
                local_files_only=True,
            )
            logger.info("✦ bge-m3 임베딩 모델 로드 완료 (dim=%d, device=%s)", _BGE_M3_DIM, device)
        except Exception as e:
            logger.error("bge-m3 로드 실패: %s", e)
            return None
    return _bge_m3_model


def _get_embedding_bge_m3(text: str) -> Optional[List[float]]:
    """bge-m3 모델로 1024-dim 임베딩 생성 (검색 쿼리용)"""
    model = _get_bge_m3_model()
    if model is None:
        return None
    try:
        emb = model.encode(text, normalize_embeddings=True)
        result = emb.tolist()
        if len(result) != _BGE_M3_DIM:
            logger.warning("bge-m3 dim mismatch: expected %d, got %d", _BGE_M3_DIM, len(result))
        return result
    except Exception as e:
        logger.warning("bge-m3 임베딩 실패: %s", e)
        return None


# ── HuggingFace CrossEncoder (리랭커) ──
_reranker_model = None

def _get_reranker_model():
    """SentenceTransformer CrossEncoder 지연 로드"""
    global _reranker_model
    if _reranker_model is None:
        try:
            from sentence_transformers import CrossEncoder
            import torch
            import os
            
            # 모델 캐시 폴더 (프로젝트 루트 상대 경로, env 로 override 가능)
            from pathlib import Path
            default_cache = Path(__file__).resolve().parent.parent.parent / "models" / "reranker"
            cache_dir = os.environ.get("RERANKER_CACHE_DIR", str(default_cache))
            os.makedirs(cache_dir, exist_ok=True)
            
            # RTX 5070 sm_120은 PyTorch CUDA 빌드와 비호환 — 기본 CPU.
            # 호환 GPU 환경에서는 RERANKER_DEVICE=cuda 로 override.
            device = os.environ.get("RERANKER_DEVICE", "cpu")
            _reranker_model = CrossEncoder(
                "dragonkue/bge-reranker-v2-m3-ko",
                device=device,
                cache_folder=cache_dir,
            )
            logger.info(f"✦ CrossEncoder (bge-reranker-v2-m3-ko) 로드 완료 (Device: {device})")
        except Exception as e:
            logger.error(f"CrossEncoder 로드 실패: {e}")
            return None
    return _reranker_model


# ── Ollama 임베딩 클라이언트 (배치 병렬 처리) ──
EMBED_WORKERS = 16   # 동시 요청 수 (CPU 코어 수에 맞게 조정)
EMBED_BATCH  = 64    # 한 번에 묶어서 처리할 청크 수

_embed_client = None

def _get_embed_client():
    global _embed_client
    if _embed_client is None:
        _embed_client = httpx.Client(
            base_url=settings.OLLAMA_BASE_URL,
            timeout=120.0,
            limits=httpx.Limits(
                max_connections=EMBED_WORKERS + 4,
                max_keepalive_connections=EMBED_WORKERS,
            ),
        )
    return _embed_client


def _get_embedding(text: str) -> Optional[List[float]]:
    """단일 텍스트 임베딩 — bge-m3 (1024-dim) 우선, Ollama fallback"""
    # 1차: bge-m3 (collection 호환 1024-dim)
    emb = _get_embedding_bge_m3(text)
    if emb is not None:
        return emb
    # 2차: Ollama fallback (768-dim — collection 불일치 가능)
    try:
        client = _get_embed_client()
        resp = client.post(
            "/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json().get("embedding")
    except Exception as e:
        logger.warning("임베딩 생성 실패 (both bge-m3 + Ollama): %s", e)
        return None


def _get_embeddings_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """청크 리스트를 ThreadPoolExecutor로 병렬 임베딩"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: List[Optional[List[float]]] = [None] * len(texts)

    def _embed_one(idx_text):
        idx, text = idx_text
        return idx, _get_embedding(text)

    with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as pool:
        futures = {pool.submit(_embed_one, (i, t)): i for i, t in enumerate(texts)}
        for future in as_completed(futures):
            idx, emb = future.result()
            results[idx] = emb

    return results


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP, company: str = "") -> List[str]:
    """
    초-하이엔드 금융 공시문서 청킹 v3 (Colab H100 동일)
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    1) 섹션 헤더 기반 의미 경계 분할
    2) 재무표 행 보존
    3) 계층 컨텍스트 주입
    4) 한글 문장 경계 존중
    5) 품질 필터
    """
    import re

    MIN_CHUNK_LEN = 80

    if not text or len(text) < MIN_CHUNK_LEN:
        return []

    # ── 1단계: 섹션 분리 ──
    section_pattern = re.compile(
        r'^(?:'
        r'(?:[IVX]+\.|[0-9]+\.)\s*.{2,40}$'
        r'|【.{2,30}】'
        r'|(?:제\s*\d+\s*[기장편])'
        r'|(?:사\s*업\s*보\s*고\s*서|감\s*사\s*보\s*고\s*서|분\s*기\s*보\s*고\s*서)'
        r'|(?:연\s*결\s*재\s*무\s*제\s*표|재\s*무\s*상\s*태\s*표|손\s*익\s*계\s*산\s*서|포\s*괄\s*손\s*익)'
        r'|(?:주\s*주\s*총\s*회|이\s*사\s*회|감\s*사\s*위\s*원)'
        r')',
        re.MULTILINE
    )

    lines = text.split('\n')
    sections = []
    current_title = ""
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if section_pattern.match(stripped) and len(stripped) < 60:
            if current_lines:
                sections.append((current_title, '\n'.join(current_lines)))
            current_title = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, '\n'.join(current_lines)))
    if not sections:
        sections = [("", text)]

    # ── 2단계: 각 섹션 분할 ──
    TARGET_SIZE = 900
    OVERLAP_SIZE = 120
    all_chunks = []

    for section_title, section_text in sections:
        if not section_text.strip():
            continue

        prefix = ""
        if company and section_title:
            prefix = f"[{company}] {section_title}\n"
        elif company:
            prefix = f"[{company}]\n"
        elif section_title:
            prefix = f"{section_title}\n"

        # 재무표 감지 & 보존
        table_blocks = []
        narrative_blocks = []
        current_block = []
        is_table = False

        for line in section_text.split('\n'):
            stripped = line.strip()
            digit_ratio = sum(1 for c in stripped if c.isdigit() or c in ',.-') / max(len(stripped), 1)
            has_numbers = bool(re.search(r'\d{3,}', stripped))

            if digit_ratio > 0.3 and has_numbers and len(stripped) > 10:
                if not is_table and current_block:
                    narrative_blocks.append('\n'.join(current_block))
                    current_block = []
                is_table = True
                current_block.append(stripped)
            else:
                if is_table and current_block:
                    table_blocks.append('\n'.join(current_block))
                    current_block = []
                is_table = False
                current_block.append(stripped)

        if current_block:
            if is_table:
                table_blocks.append('\n'.join(current_block))
            else:
                narrative_blocks.append('\n'.join(current_block))

        # 테이블 청킹
        for table in table_blocks:
            if len(table) < MIN_CHUNK_LEN:
                continue
            if len(prefix + table) <= TARGET_SIZE * 1.5:
                all_chunks.append(prefix + table)
            else:
                rows = table.split('\n')
                current = prefix
                for row in rows:
                    if len(current) + len(row) > TARGET_SIZE:
                        if len(current.strip()) >= MIN_CHUNK_LEN:
                            all_chunks.append(current.strip())
                        current = prefix + row + '\n'
                    else:
                        current += row + '\n'
                if len(current.strip()) >= MIN_CHUNK_LEN:
                    all_chunks.append(current.strip())

        # 서술형 청킹
        full_narrative = '\n'.join(narrative_blocks)
        if not full_narrative.strip():
            continue

        sentences = re.split(
            r'(?<=[다요음됨함임.])\s*\n|'
            r'(?<=[다요음됨함임.])\s{2,}|'
            r'\n\s*\n',
            full_narrative
        )
        sentences = [s.strip() for s in sentences if s.strip()]

        current_chunk = prefix
        prev_tail = ""

        for sent in sentences:
            if len(sent) < 5:
                continue
            if len(current_chunk) + len(sent) > TARGET_SIZE:
                if len(current_chunk.strip()) >= MIN_CHUNK_LEN:
                    all_chunks.append(current_chunk.strip())
                if prev_tail and len(prev_tail) < OVERLAP_SIZE:
                    current_chunk = prefix + prev_tail + '\n' + sent + '\n'
                else:
                    current_chunk = prefix + sent + '\n'
            else:
                current_chunk += sent + '\n'
            prev_tail = sent

        if len(current_chunk.strip()) >= MIN_CHUNK_LEN:
            all_chunks.append(current_chunk.strip())

    # ── 3단계: 품질 필터 ──
    def _kr_ratio(t):
        if not t: return 0.0
        kr = sum(1 for c in t if '\uac00' <= c <= '\ud7a3')
        total = len(t.replace(" ", "").replace("\n", ""))
        return kr / max(total, 1)

    quality_chunks = []
    for chunk in all_chunks:
        if len(chunk) < MIN_CHUNK_LEN:
            continue
        body = re.sub(r'^\[.*?\]\s*.*?\n', '', chunk, count=1)
        if _kr_ratio(body) < 0.15:
            continue
        if re.match(r'^[\d\s,.\-–—:/|%\[\]()]+$', body):
            continue
        quality_chunks.append(chunk)

    return quality_chunks


# ═══════════════════════════════════════════════════════
# BM25 키워드 검색 엔진 (경량 하드코딩)
# ═══════════════════════════════════════════════════════

# 한국어 불용어
_STOP_WORDS = frozenset([
    "이", "가", "은", "는", "을", "를", "의", "에", "에서", "으로", "로", "와", "과",
    "도", "만", "까지", "부터", "하고", "이나", "나", "며", "고", "지만", "그리고",
    "또는", "또한", "및", "등", "것", "수", "있다", "없다", "되다", "하다", "한",
    "된", "할", "위", "대한", "통해", "따라", "해당", "관련", "대해",
])


def _tokenize(text: str) -> List[str]:
    """한국어 + 영어 토크나이저 (간단한 형태소 분리)"""
    # 숫자+단위, 한글 2자 이상, 영어 단어 추출
    tokens = re.findall(r'[\d,]+(?:\.\d+)?(?:%|원|억|만|조|건|개|주|배)?|[가-힣]{2,}|[a-zA-Z]{2,}', text)
    return [t for t in tokens if t not in _STOP_WORDS and len(t) >= 2]


def _bm25_score(query_tokens: List[str], doc_tokens: List[str],
                avg_dl: float = 200, k1: float = 1.5, b: float = 0.75) -> float:
    """단일 문서의 BM25 점수 계산 (IDF 생략, TF 기반)"""
    if not query_tokens or not doc_tokens:
        return 0.0

    doc_len = len(doc_tokens)
    tf_counter = Counter(doc_tokens)
    score = 0.0

    for qt in query_tokens:
        tf = tf_counter.get(qt, 0)
        if tf == 0:
            continue
        # BM25 TF component (IDF is 1 for single-doc scoring)
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * (doc_len / max(avg_dl, 1)))
        score += numerator / denominator

    return score


def _keyword_overlap_score(query_tokens: List[str], doc_tokens: List[str]) -> float:
    """쿼리 토큰이 문서에 얼마나 포함되는지 비율"""
    if not query_tokens:
        return 0.0
    doc_set = set(doc_tokens)
    matches = sum(1 for qt in query_tokens if qt in doc_set)
    return matches / len(query_tokens)


def _chunks_similar(chunk_a: str, chunk_b: str) -> float:
    """두 청크 간 토큰 Jaccard 유사도 (중복 감지용)"""
    tokens_a = set(_tokenize(chunk_a[:300]))
    tokens_b = set(_tokenize(chunk_b[:300]))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


# ═══════════════════════════════════════════════════════
# Omega Cognitive Engine — 통합 검색 파이프라인
# ═══════════════════════════════════════════════════════

def cognitive_search(
    query: str,
    top_k: int = 5,
    category_filter: str = "",
    company_filter: str = "",
    domain: str = "",
    user_id: int = 0,
) -> List[Dict]:
    """
    Omega Cognitive Engine 통합 검색.

    Step 1: Variable Decomposition — 쿼리 토큰 분해
    Step 2: Objective Function — 벡터 + BM25 + 메타 복합 스코어
    Step 3: Pareto Eigenvector — 최고 레버리지 결과 태깅
    Step 4: Entropy Reduction — 임계점 컷오프 + 중복 제거
    Step 5: Strategic Execution — 정렬된 최종 결과 반환
    """
    collection = _get_collection(_user_collection(user_id))
    if collection is None:
        return []

    # ── Step 1: Variable Decomposition ──
    query_tokens = _tokenize(query)
    logger.info(f"Ω Cognitive [Step 1] 변수 분해: {query_tokens[:10]}")

    # ── 벡터 검색 (넉넉하게 가져옴) ──
    query_emb = _get_embedding(query)
    if query_emb is None:
        return []

    where = {}
    if category_filter:
        where["category"] = category_filter
    if company_filter:
        where["company_name"] = company_filter

    # 후처리(엔트로피 소각, 리랭킹)를 위해 3배수 가져옴
    fetch_k = min(top_k * 3, 30)

    try:
        results = collection.query(
            query_embeddings=[query_emb],
            n_results=fetch_k,
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        logger.warning(f"벡터 검색 실패: {e}")
        return []

    if not results or not results["ids"] or not results["ids"][0]:
        return []

    # ── Step 2: Objective Function — 복합 스코어링 ──
    candidates = []
    for i, chunk_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i] if results["metadatas"] else {}
        dist = results["distances"][0][i] if results["distances"] else 1.0
        chunk_text = results["documents"][0][i] if results["documents"] else ""

        vector_score = max(0, 1.0 - dist)  # 코사인 거리 → 유사도

        # BM25 키워드 점수
        doc_tokens = _tokenize(chunk_text)
        bm25 = _bm25_score(query_tokens, doc_tokens)
        # BM25 정규화 (0~1 범위)
        bm25_norm = min(bm25 / max(len(query_tokens) * 1.5, 1), 1.0)

        # 메타데이터 일치 점수
        meta_score = 0.0
        if company_filter and company_filter in meta.get("company_name", ""):
            meta_score += 0.5
        if category_filter and category_filter in meta.get("category", ""):
            meta_score += 0.5
        # 쿼리에 회사명이 포함되어 있고, 메타에도 있으면 보너스
        for qt in query_tokens:
            if qt in meta.get("company_name", ""):
                meta_score += 0.3
                break

        meta_score = min(meta_score, 1.0)

        # 복합 점수 = 가중합
        composite = (
            VECTOR_WEIGHT * vector_score +
            KEYWORD_WEIGHT * bm25_norm +
            META_WEIGHT * meta_score
        )

        # 도메인 부스트
        if domain == "risk":
            risk_keywords = {"감사의견", "계속기업", "부채비율", "리스크", "위험", "소송", "손실"}
            if any(rk in chunk_text for rk in risk_keywords):
                composite *= 1.15
        elif domain == "growth":
            growth_keywords = {"성장", "증가", "확대", "투자", "신규", "매출 증가"}
            if any(gk in chunk_text for gk in growth_keywords):
                composite *= 1.10

        candidates.append({
            "doc_id": meta.get("doc_id"),
            "filename": meta.get("filename", ""),
            "chunk": chunk_text,
            "vector_score": round(vector_score, 4),
            "bm25_score": round(bm25_norm, 4),
            "meta_score": round(meta_score, 4),
            "composite_score": round(composite, 4),
            "category": meta.get("category", ""),
            "company": meta.get("company_name", ""),
        })

    logger.info(f"Ω Cognitive [Step 2] 복합 스코어링: {len(candidates)}건")

    # ── Step 4: Entropy Reduction — 미분 기반 노이즈 경계 감지 ──
    # 4a: 기울기(gradient) 기반 컷오프
    sorted_cands = sorted(candidates, key=lambda x: x["composite_score"], reverse=True)

    if len(sorted_cands) > 2:
        # 인접 점수 간 기울기 계산 (1차 미분)
        gradients = []
        for j in range(len(sorted_cands) - 1):
            delta = sorted_cands[j]["composite_score"] - sorted_cands[j + 1]["composite_score"]
            gradients.append(delta)

        # 기울기 급락 지점 = 노이즈 경계 (변곡점)
        # 평균 기울기의 2배 이상 급락하면 경계로 판단
        avg_gradient = sum(gradients) / len(gradients) if gradients else 0
        gradient_threshold = max(avg_gradient * 2.0, 0.05)  # 최소 0.05

        cutoff_idx = len(sorted_cands)  # 기본값: 전부 유지
        for j, g in enumerate(gradients):
            if g > gradient_threshold and j >= 1:  # 최소 2개는 유지
                cutoff_idx = j + 1
                logger.info(
                    f"Ω Cognitive [미분] 변곡점 감지: idx={j}, "
                    f"∂score={g:.4f} > threshold={gradient_threshold:.4f}"
                )
                break

        filtered = sorted_cands[:cutoff_idx]
    else:
        filtered = sorted_cands

    # 최소 안전망: composite_score < 0.15 미만은 무조건 제거
    filtered = [c for c in filtered if c["composite_score"] >= 0.15]
    removed = len(candidates) - len(filtered)

    # 4b: 정보 밀도 미분 (Signal Concentration)
    # 청크 내 재무 키워드 밀도를 계산하여 보너스 부여
    _SIGNAL_KEYWORDS = {
        "전기 대비", "전년 동기", "증가", "감소", "전기", "당기",
        "영업이익", "매출", "순이익", "부채비율", "자산총계",
        "배당", "증자", "감사의견", "유상증자", "전환사채",
    }
    for c in filtered:
        chunk_lower = c["chunk"]
        signal_count = sum(1 for sk in _SIGNAL_KEYWORDS if sk in chunk_lower)
        # 정보 밀도 = signal 키워드 수 / 청크 길이(100자 단위)
        chunk_len_100 = max(len(c["chunk"]) / 100, 1)
        info_density = signal_count / chunk_len_100
        # 밀도 보너스 (최대 15%)
        density_boost = min(info_density * 0.05, 0.15)
        c["composite_score"] = round(c["composite_score"] + density_boost, 4)
        c["info_density"] = round(info_density, 4)

    # 4c: 중복 청크 제거 (Jaccard 유사도 기반)
    deduped = []
    for c in sorted(filtered, key=lambda x: x["composite_score"], reverse=True):
        is_dup = False
        for existing in deduped:
            if _chunks_similar(c["chunk"], existing["chunk"]) > DEDUP_THRESHOLD:
                is_dup = True
                break
        if not is_dup:
            deduped.append(c)

    dup_removed = len(filtered) - len(deduped)
    logger.info(f"Ω Cognitive [Step 4] 엔트로피 소각: 노이즈 {removed}건, 중복 {dup_removed}건 제거")

    # ── Step 4d: CrossEncoder Reranking ──
    # 같은 파일의 _get_reranker_model 을 호출하여 query-chunk pair 를 직접 평가.
    # cognitive_search_safe 와 동일 패턴 (rerank 0.75 + composite 0.25 가중합).
    try:
        reranker = _get_reranker_model()
        if reranker is not None and len(deduped) >= 2:
            pairs = [(query, (c.get("chunk") or "")[:512]) for c in deduped]
            rerank_scores = reranker.predict(pairs, show_progress_bar=False)
            for c, s in zip(deduped, rerank_scores):
                c["rerank_score"] = float(s)
            logger.info(f"Ω Cognitive [Step 4d] CrossEncoder reranked {len(deduped)} candidates")
        else:
            for c in deduped:
                c["rerank_score"] = 0.0
    except Exception as exc:
        logger.warning(f"CrossEncoder 리랭킹 실패: {exc}")
        for c in deduped:
            c["rerank_score"] = 0.0

    # ── Step 5: Strategic Execution — 최종 정렬 (rerank 0.75 + composite 0.25) ──
    final = sorted(
        deduped,
        key=lambda x: x.get("rerank_score", 0.0) * 0.75 + x.get("composite_score", 0.0) * 0.25,
        reverse=True,
    )[:top_k]

    # ── Step 3: Pareto Eigenvector — 최고 레버리지 태깅 ──
    if final:
        final[0]["pareto"] = True  # 최고 레버리지 결과
        for r in final[1:]:
            r["pareto"] = False

    # 외부 호환성: score 필드 유지
    for r in final:
        r["score"] = r["composite_score"]

    logger.info(f"Ω Cognitive [Step 5] 최종 결과: {len(final)}건")
    return final


# ═══════════════════════════════════════════════════════
# 레거시 호환 API (기존 호출부 호환)
# ═══════════════════════════════════════════════════════

def semantic_search(
    query: str,
    top_k: int = 5,
    category_filter: str = "",
    company_filter: str = "",
    user_id: int = 0,
) -> List[Dict]:
    """
    레거시 호환 시맨틱 검색.
    내부적으로 cognitive_search를 호출.
    """
    return cognitive_search(
        query=query,
        top_k=top_k,
        category_filter=category_filter,
        company_filter=company_filter,
        user_id=user_id,
    )


# ═══════════════════════════════════════════════════════
# 인덱싱 API
# ═══════════════════════════════════════════════════════

def index_document(
    doc_id: int, filename: str, text: str,
    category: str = "", company: str = "",
    user_id: int = 0,
    source: str = "llm",
    clear_existing: bool = False,
    filing_date: str = "",
    period: str = "",
    collection_name: str = "",
):
    """
    문서 텍스트를 청크 분할 → 임베딩 → ChromaDB 저장
    source: "llm" (분석 요약) 또는 "ocr" (원문)
    """
    resolved_collection = collection_name or _user_collection(user_id)
    collection = _get_collection(resolved_collection)
    if collection is None:
        return 0

    # 기존 문서의 같은 소스 벡터 삭제 (재인덱싱 지원)
    if clear_existing:
        try:
            existing = collection.get(where={"doc_id": doc_id})
            if existing and existing["ids"]:
                collection.delete(ids=existing["ids"])
        except Exception:
            pass

    if user_id:
        logger.debug("  ├─ 컬렉션: %s (user_id=%d)", resolved_collection, user_id)

    chunks = _chunk_text(text)
    if not chunks:
        return 0

    ids = []
    embeddings = []
    documents = []
    metadatas = []

    # 1단계: 모든 청크를 FilingChunk로 변환하고 구조화된 프롬프트 생성
    prepared_docs = []
    f_chunks = []
    for i, chunk in enumerate(chunks):
        f_chunk = FilingChunk(
            doc_id=str(doc_id),
            chunk_id=hashlib.md5(f"{doc_id}_{source}_{i}_{chunk[:50]}".encode()).hexdigest(),
            chunk_text=chunk,
            company_name=company,
            doc_type=category,
            filing_type=category,
            filing_date=filing_date,
            period=period,
            source_file=filename,
        )
        item = prepare_embedding_item(f_chunk)
        prepared_docs.append(item.document)
        f_chunks.append(item)

    # 2단계: 배치 병렬 임베딩
    emb_list = _get_embeddings_batch(prepared_docs)

    # 3단계: 결과 수집
    for item, emb in zip(f_chunks, emb_list):
        if emb is None or (hasattr(emb, '__len__') and len(emb) == 0):
            continue

        ids.append(item.id)
        embeddings.append(emb)
        documents.append(item.document)
        metadatas.append(item.metadata)

    if ids:
        # 배치 단위로 추가 (대량 인덱싱 시 단일 에러가 전체를 중단시키지 않도록)
        BATCH = 200
        added = 0
        for start in range(0, len(ids), BATCH):
            end = start + BATCH
            try:
                collection.add(
                    ids=ids[start:end],
                    embeddings=embeddings[start:end],
                    documents=documents[start:end],
                    metadatas=metadatas[start:end],
                )
                added += end - start
            except Exception as batch_err:
                logger.warning(f"  ├─ 배치 인덱싱 실패 (#{doc_id} [{start}:{end}]): {batch_err}")
        if added > 0:
            logger.info(f"  ├─ 벡터 인덱싱: 문서 #{doc_id} [{source}] → {added}청크")

    return len(ids)


def get_index_stats() -> Dict:
    """벡터 인덱스 통계"""
    collection = _get_collection(COLLECTION_NAME)
    if collection is None:
        return {"status": "offline", "count": 0}

    return {
        "status": "online",
        "count": collection.count(),
        "collection": COLLECTION_NAME,
        "embed_model": EMBED_MODEL,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
    }


def index_chat_chunks(
    chunks: List[Dict],
    clear_document_id: Optional[int] = None,
    collection_name: str = "",
    user_id: int = 0,
) -> int:
    """구조화 청크 컬렉션에 원문 청크를 인덱싱."""
    resolved_collection = collection_name or _user_chunk_collection(user_id)
    collection = _get_collection(resolved_collection)
    if collection is None or not chunks:
        return 0

    if clear_document_id is not None:
        try:
            existing = collection.get(where={"doc_id": clear_document_id})
            if existing and existing.get("ids"):
                collection.delete(ids=existing["ids"])
        except Exception as exc:
            logger.warning("청크 컬렉션 초기화 실패: %s", exc)

    ids = []
    embeddings = []
    documents = []
    metadatas = []

    # ── 유효 청크 필터 먼저 ──
    valid_chunks = [
        c for c in chunks
        if (c.get("text") or "").strip() and c.get("chunk_uid")
    ]
    # 1단계: 모든 유효 청크를 FilingChunk로 변환하고 구조화된 프롬프트 생성
    f_chunks = []
    prepared_docs = []
    for chunk in valid_chunks:
        text = (chunk.get("text") or "").strip()
        f_chunk = FilingChunk(
            doc_id=str(chunk.get("document_id")),
            chunk_id=chunk["chunk_uid"],
            chunk_text=text,
            company_name=chunk.get("company_name", ""),
            doc_type=chunk.get("report_type", ""),
            filing_type=chunk.get("report_type", ""),
            filing_date=str(chunk.get("fiscal_year", "")),
            section_title=chunk.get("section_name", ""),
            page=int(chunk.get("page_no") or 0) if chunk.get("page_no") else None,
            source_file=chunk.get("filename", ""),
        )
        item = prepare_embedding_item(f_chunk)
        f_chunks.append(item)
        prepared_docs.append(item.document)

    # 2단계: 배치 병렬 임베딩
    emb_list = _get_embeddings_batch(prepared_docs)

    # 3단계: 결과 수집
    for item, emb in zip(f_chunks, emb_list):
        if emb is None:
            continue

        ids.append(item.id)
        embeddings.append(emb)
        documents.append(item.document)
        metadatas.append(item.metadata)

    if ids:
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info("  ├─ 청크 벡터 인덱싱: 문서 #%s → %s청크", clear_document_id, len(ids))
    return len(ids)


def search_chat_chunks(
    query: str,
    top_k: int = 5,
    company_filter: str = "",
    year_filters: Optional[List[int]] = None,
    period_type: str = "",
    statement_scope: str = "",
    user_id: int = 0,
) -> List[Dict]:
    """누적 지식 청크 컬렉션 검색."""
    collection = _get_collection(_user_chunk_collection(user_id))
    if collection is None:
        return []

    query_emb = _get_embedding(query)
    if query_emb is None:
        return []

    query_tokens = _tokenize(query)
    fetch_k = min(max(top_k * 4, 12), 40)

    try:
        results = collection.query(
            query_embeddings=[query_emb],
            n_results=fetch_k,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("청크 검색 실패: %s", exc)
        return []

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

    candidates = []
    for index, chunk_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][index] if results["metadatas"] else {}
        chunk_text = results["documents"][0][index] if results["documents"] else ""
        dist = results["distances"][0][index] if results["distances"] else 1.0

        company = str(meta.get("company", "") or "")
        report = str(meta.get("report_type", "") or "")
        chunk_year = int(meta.get("fiscal_year") or 0)
        chunk_period = str(meta.get("period_type", "") or "")
        chunk_scope = str(meta.get("statement_scope", "") or "")

        if company_filter and company_filter not in company and company_filter not in str(meta.get("company_norm", "")):
            continue
        if year_filters and chunk_year and chunk_year not in year_filters:
            continue
        if period_type and chunk_period and chunk_period != period_type:
            continue
        if statement_scope and chunk_scope and chunk_scope != statement_scope:
            continue

        vector_score = max(0.0, 1.0 - dist)
        doc_tokens = _tokenize(chunk_text)
        bm25 = _bm25_score(query_tokens, doc_tokens)
        bm25_norm = min(bm25 / max(len(query_tokens) * 1.5, 1), 1.0)

        meta_score = 0.0
        if company_filter and company_filter in company:
            meta_score += 0.45
        if year_filters and chunk_year and chunk_year in year_filters:
            meta_score += 0.25
        if period_type and chunk_period == period_type:
            meta_score += 0.15
        if statement_scope and chunk_scope == statement_scope:
            meta_score += 0.15
        if report:
            for token in query_tokens[:4]:
                if token and token in report:
                    meta_score += 0.1
                    break

        composite = (
            VECTOR_WEIGHT * vector_score +
            KEYWORD_WEIGHT * bm25_norm +
            META_WEIGHT * min(meta_score, 1.0)
        )

        candidates.append({
            "chunk_uid": chunk_id,
            "doc_id": meta.get("doc_id"),
            "filename": meta.get("filename", ""),
            "chunk": chunk_text,
            "page_no": int(meta.get("page_no") or 0) or None,
            "section_name": meta.get("section_name", ""),
            "company": company,
            "report_type": report,
            "fiscal_year": chunk_year or None,
            "period_type": chunk_period,
            "statement_scope": chunk_scope,
            "score": round(composite, 4),
        })

    candidates = [item for item in candidates if item["score"] >= 0.15]
    candidates.sort(key=lambda item: item["score"], reverse=True)

    deduped = []
    for candidate in candidates:
        if any(_chunks_similar(candidate["chunk"], existing["chunk"]) > DEDUP_THRESHOLD for existing in deduped):
            continue
        deduped.append(candidate)
        if len(deduped) >= top_k:
            break

    return deduped


def rebuild_index_from_db():
    """
    DB의 모든 analyzed 문서를 벡터 인덱스로 재구축
    ═══════════════════════════════════════════════════════
    듀얼 소스 임베딩:
    1. LLM 분석 요약 (summary + key_points + evidence) → source="llm"
    2. OCR 원문 (cleaned_text 전체) → source="ocr"
    ═══════════════════════════════════════════════════════
    """
    import json as _json
    from database import SessionLocal
    from models.models import Document, AnalysisResult, OcrText

    db = SessionLocal()
    try:
        docs = db.query(Document).filter(Document.status == "analyzed").all()
        total = len(docs)
        llm_chunks = 0
        ocr_chunks = 0
        skipped = 0

        for i, doc in enumerate(docs):
            # ── AnalysisResult에서 카테고리/회사명 공통 추출 ──
            ar = db.query(AnalysisResult).filter(
                AnalysisResult.document_id == doc.id
            ).order_by(AnalysisResult.created_at.desc()).first()

            category = ""
            company = ""
            raw = {}
            if ar:
                category = ar.category or ""
                raw = ar.raw_response
                if isinstance(raw, str):
                    try:
                        raw = _json.loads(raw)
                    except Exception:
                        raw = {}
                if isinstance(raw, dict):
                    company = raw.get("company_name", "")

            # ═══ 소스 1: LLM 분석 요약 ═══
            if ar and ar.summary:
                ERROR_PREFIXES = ("분석 중 오류", "LLM 분석 실패", "All connection", "분석할 텍스트")
                if not any((ar.summary or "").startswith(p) for p in ERROR_PREFIXES):
                    parts = []
                    if ar.summary:
                        parts.append(ar.summary)
                    if isinstance(raw, dict):
                        kp = raw.get("key_points", [])
                        if isinstance(kp, list):
                            parts.extend(str(p) for p in kp if p)
                    if ar.evidence and len(ar.evidence) > 5:
                        parts.append(ar.evidence)
                    if ar.financial_metrics and ar.financial_metrics != "해당 없음":
                        parts.append(ar.financial_metrics)
                    if ar.insight_vectors and ar.insight_vectors != "해당 없음":
                        parts.append(ar.insight_vectors)

                    llm_text = "\n".join(parts)
                    if len(llm_text) >= 30:
                        n = index_document(
                            doc.id, doc.filename, llm_text,
                            category, company,
                            user_id=doc.user_id,
                            source="llm",
                            clear_existing=(i == 0),
                        )
                        llm_chunks += n

            # ═══ 소스 2: OCR 원문 ═══
            ocr_rows = db.query(OcrText).filter(
                OcrText.document_id == doc.id,
                OcrText.cleaned_text != None,
            ).order_by(OcrText.id).all()

            if ocr_rows:
                ocr_full = "\n".join(
                    row.cleaned_text for row in ocr_rows
                    if row.cleaned_text and len(row.cleaned_text) > 20
                )
                if len(ocr_full) >= 50:
                    n = index_document(
                        doc.id, doc.filename, ocr_full,
                        category, company,
                        user_id=doc.user_id,
                        source="ocr",
                    )
                    ocr_chunks += n
                else:
                    skipped += 1
            else:
                skipped += 1

            if (i + 1) % 50 == 0:
                msg = (
                    f"  인덱싱 진행: {i+1}/{total} "
                    f"(LLM:{llm_chunks} + OCR:{ocr_chunks} = {llm_chunks+ocr_chunks}청크)"
                )
                logger.info(msg)
                print(msg, flush=True)

        total_chunks = llm_chunks + ocr_chunks
        logger.info(
            f"✦ 듀얼 소스 벡터 인덱스 재구축 완료 — {total}문서\n"
            f"  LLM 요약: {llm_chunks}청크 | OCR 원문: {ocr_chunks}청크\n"
            f"  합계: {total_chunks}청크 | 스킵: {skipped}건"
        )
        return {
            "documents": total,
            "llm_chunks": llm_chunks,
            "ocr_chunks": ocr_chunks,
            "total_chunks": total_chunks,
            "skipped": skipped,
        }

    finally:
        db.close()


def delete_user_collections(user_id: int) -> bool:
    """계정 탈퇴/삭제 시 해당 사용자의 모든 ChromaDB 컬렉션을 제거"""
    if not user_id:
        return False
    global _chroma_client, _collections
    if _chroma_client is None:
        _get_collection(_user_collection(user_id))
    deleted = []
    for col_name in [_user_collection(user_id), _user_chunk_collection(user_id)]:
        try:
            _chroma_client.delete_collection(col_name)
            _collections.pop(col_name, None)
            deleted.append(col_name)
        except Exception as e:
            logger.warning("컬렉션 삭제 실패 (%s): %s", col_name, e)
    if deleted:
        logger.info("✦ 사용자 %d 컬렉션 삭제 완료: %s", user_id, deleted)
    return bool(deleted)


# ── 벡터 서비스 인스턴스 ──
vector_service = type("VectorService", (), {
    "index_document": staticmethod(index_document),
    "index_chat_chunks": staticmethod(index_chat_chunks),
    "semantic_search": staticmethod(semantic_search),
    "cognitive_search": staticmethod(cognitive_search),
    "search_chat_chunks": staticmethod(search_chat_chunks),
    "get_index_stats": staticmethod(get_index_stats),
    "rebuild_index": staticmethod(rebuild_index_from_db),
    "delete_user_collections": staticmethod(delete_user_collections),
})()

