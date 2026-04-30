# Rechunk v2 — RAGAS 95 Target Chunker

## 목표
- 모든 chunk가 **hard max 1,000 chars 이하** (BGE-M3 max_seq=512 tokens에 안전)
- `chunk_text_quality`의 기존 장점 유지 (섹션·재무표 분리, Korean 문장 경계, prefix 주입)
- RAGAS 95 목표: silent truncation 0건, 완전 검색 커버리지

## 현재 문제 (v1 = `chunk_text_quality`)
- `TARGET_SIZE=900`은 "목표"일 뿐 **hard cap이 없음**
- 단일 긴 행(재무표 row)이 37,999 chars까지 감
- 512 tokens 임베딩 시 첫 ~5%만 CLS 벡터에 반영 → 검색 실패

## v2 변경 사항

### 1. Post-processing hard enforcement
- `chunk_text_quality` 그대로 호출 → 결과 chunks에 **hard max filter**
- max 초과 chunk는 prefix 보존 후 **recursive split**

### 2. Recursive splitter (Korean-aware)
Separator 우선순위:
1. `\n\n` (paragraph)
2. `\n` (line)
3. `다. ` / `요. ` / `습니다. ` (Korean sentence endings)
4. `. ` (generic period)
5. `, ` (comma)
6. ` ` (space)
7. `` (character-level, last resort)

각 레벨에서 merge until max → 여전히 초과 시 다음 separator로 재귀.

### 3. Prefix 보존
- 분할된 모든 sub-chunk에 `[company] section_title\n` 재부착
- Prefix tokens 차감 후 body budget 계산

### 4. Parameters
- `MAX_CHARS = 1000` (safe below 512 tokens for Korean ~0.5 tok/char)
- `OVERLAP_CHARS = 100` (context continuity)
- `MIN_CHARS = 80` (품질 필터)

## 파이프라인
1. 기존 `document_chunks` → `document_chunks_v1_{timestamp}` rename (백업)
2. 새 `document_chunks` 생성 (동일 스키마)
3. `documents` × `ocr_texts` × `document_metadata` JOIN
4. 각 문서 → `deep_clean_text` → `chunk_text_v2` (chunk_text_quality + enforce_hard_max)
5. SQLite bulk insert
6. Distribution histogram 출력 + hard max 검증

## 검증
- max_length == 1000 (정확)
- >1000 chars chunks: 0개 (필수)
- 히스토그램: [0-256], (256-512], (512-1000]
- 총 chunk 수는 v1보다 약간 증가 예상 (강제 분할 때문)

## 다음 단계 (이 스크립트 이후)
1. Colab A100 재가동 → BGE-M3 로드 (aria2 캐시 있음)
2. `phase3_embedding_a100.py`로 재임베딩 — max_seq=512 그대로 유지
3. 기존 `omega_documents_v2` 컬렉션 drop → 새로 생성
4. RAGAS 평가 셋 구축 → 점수 측정
