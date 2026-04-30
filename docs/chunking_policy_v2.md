# DART 청킹 정책 v2 — 확정 문서
> 작성일: 2026-04-14
> 기반: chunking_policy_v1.md + 사용자 확정 결정 (Q1~Q4)
> 상태: **구현 착수 가능**

---

## 0. 하드 제약 (불변)

| 제약 | 값 | 근거 |
|------|---|------|
| 임베딩 모델 | BGE-M3 | 운영 확정 |
| BGE-M3 max_seq | **512 tokens** | 초과 시 silently truncate — 수치 유실 |
| XML 파서 | `lxml.etree(recover=True)` | 표준 ET → ParseError 다수 |
| 인코딩 | UTF-8 | 전수 확인 완료 |
| 청크 기본 상한 | **400 tokens** | 헤더 여유분 + truncate 안전마진 |
| 청크 예외 상한 | **480 tokens** | NOTE fallback 한정 (§6 참조) |
| 청크 절대 상한 | **512 tokens 미사용** | 확정 |
| 토큰 카운터 | `tiktoken cl100k_base` | BGE-M3 WordPiece 근사치로 허용 |

---

## 1. Final Chunk Types

총 5가지 타입. 각 타입은 독립 인덱싱.

| Type | 명칭 | 소스 | 문서당 예상 수 |
|------|------|------|--------------|
| **T0** | Fact Chunk | `<SUMMARY>` EXTRACTION | 1개 고정 |
| **T1** | Narrative Chunk | `<P>` 서술 텍스트 | ~80개 |
| **T2** | Financial Table Chunk | `<TABLE ACLASS=NORMAL>` (재무제표·표형 주석) | ~70개 |
| **T3** | Audit Chunk | `_00760` / `_00761` / V섹션 embedded | ~10개 |
| **T1-NOTE** | Narrative Note Chunk | 서술형 주석 `<P>` | ~20개 |

> T1-NOTE는 T1의 서브타입. 처리 로직 동일, metadata `note_type: "narrative"` 구분.
> 전체 문서당 평균 **~181 청크** 예상 (연결·개별 모두 인덱싱 기준).

---

## 2. Token Budget by Type

### 2-1. 타입별 토큰 할당

| Type | 헤더 예약 | 본문 목표 | 본문 상한 | 전체 상한 | Overlap |
|------|---------|---------|---------|---------|---------|
| T0 | 25t | 150t | 175t | **200t** | 0 |
| T1 | 30t | 220t | 340t | **370t** | **64t** |
| T2 | 40t | 280t | 340t | **380t** | 0 |
| T3 | 25t | 220t | 345t | **370t** | **32t** |
| T1-NOTE | 30t | 220t | 340t | **370t** | **32t** |
| T2-NOTE | 40t | 280t | 340t | **380t** | 0 |
| T2-NOTE (fallback) | 40t | 280t | 400t | **440t** | 0 |

> **헤더 예약**: breadcrumb 텍스트 토큰. 초과 시 섹션명 축약 허용 (§3-1 참조).

### 2-2. 헤더 토큰 초과 대응

breadcrumb이 40t 초과 시:
1. SECTION-2 제목만 사용 (SECTION-1 생략)
2. 그래도 초과 시: 제목 앞 30자 잘라 `...` 처리
3. 본문 예산은 항상 보호 — 헤더를 줄이고 본문 유지

---

## 3. Note Handling Rules (Q1 확정)

### 3-1. NOTE 분류 기준

주석(`NOTE`) 섹션 내 각 요소를 **요소 단위**로 분류. 섹션 전체를 하나의 타입으로 묶지 않는다.

#### 분류 트리

```
주석 섹션 내 요소
│
├── <TABLE ACLASS=NORMAL>
│   ├── 행 수 ≥ 3 AND 수치 셀 비율 ≥ 50%  → T2-NOTE (표형 주석)
│   ├── 행 수 ≥ 3 AND 수치 셀 비율 < 50%   → T1-NOTE (서술형 표)
│   └── 행 수 < 3                           → T1-NOTE (단순 레이아웃 표)
│
└── <P> 텍스트
    └── 항상 → T1-NOTE (서술형 주석)
```

#### 수치 셀 비율 계산

```
수치 셀 비율 = (숫자·괄호숫자·쉼표숫자가 포함된 TD 수) / (전체 TD 수)
```

숫자 패턴: `[\d,]+` 또는 `\([\d,]+\)` — 양수·음수 모두 포함.

#### NOTE 섹션 판별 기준

다음 중 하나라도 해당하면 NOTE 섹션:
- 상위 SECTION TITLE에 "주석" 포함
- EXTRACTION TABLE의 `ACODE` 값이 NOTE 관련 코드
- SECTION-3 이하 depth에서 "제N호" 패턴 TITLE (예: "제1호 주석")

### 3-2. T2-NOTE 처리 (표형 주석)

T2(Financial Table Chunk)와 동일 로직 적용, 단:
- `table_type: "NOTE"`
- `note_seq`: 주석 번호 (추출 가능한 경우)
- fallback 상한 적용 가능 (§6-2 참조)

### 3-3. T1-NOTE 처리 (서술형 주석)

T1(Narrative Chunk)과 동일 로직 적용, 단:
- `chunk_type: "narrative"`, `note_type: "narrative"`
- overlap: 32t (T1의 64t보다 작게 — 주석은 항목 독립성이 높음)
- 주석 항목 번호 변경 시 새 청크 시작 (overlap 금지)

### 3-4. 혼합 섹션 처리 순서

같은 SECTION-3 내에 TABLE과 P가 혼재할 때:
1. EXTRACTION TABLE (메타 헤더) → 다음 요소 분류에 컨텍스트로 사용
2. NORMAL TABLE → T2-NOTE or T1-NOTE 분류 후 독립 청크
3. P 텍스트 → T1-NOTE로 누적
4. 다음 EXTRACTION TABLE이 나타나면 → 이전 T1-NOTE 청크 확정 후 새 컨텍스트 시작

---

## 4. Consolidated / Separate Metadata Policy (Q2 확정)

### 4-1. 인덱싱 정책

**연결(consolidated)과 개별(separate) 재무제표 모두 인덱싱.**

| 소스 | `statement_scope` 값 | 소스 XML |
|------|---------------------|---------|
| 연결 재무제표 | `"consolidated"` | `_00761.xml` 또는 main XML III섹션 연결 부분 |
| 개별 재무제표 | `"separate"` | `_00760.xml` 또는 main XML III섹션 개별 부분 |
| 구분 불가 | `"unknown"` | 판별 실패 시 — 로깅 후 처리 |

**연결/개별 판별 규칙** (우선순위 순):
1. 소스 파일이 `_00761.xml` → `consolidated`
2. 소스 파일이 `_00760.xml` → `separate`
3. main XML 내 SECTION TITLE에 "연결" 포함 → `consolidated`
4. main XML 내 SECTION TITLE에 "별도" / "개별" 포함 → `separate`
5. `<COMPANY-NAME AACCOUNTTYPE="A">` → `consolidated`, `"B"` → `separate`

### 4-2. Retrieval 우선순위 정책

**기본 retrieval: consolidated 우선, separate fallback.**

```
retrieval_filter_default:
  statement_scope: ["consolidated", "separate"]   # 둘 다 후보 포함
  
ranking_boost:
  if statement_scope == "consolidated": score += 0.05
  if statement_scope == "separate":     score += 0.00  (기본)
```

**예외 — separate 우선 쿼리 조건**:
- 쿼리에 "별도", "개별", "모회사" 키워드 포함 시
- `statement_scope` 필터를 `"separate"` 단독으로 변경

### 4-3. 중복 데이터 주의

동일 재무제표가 main XML과 _00760/_00761 양쪽에 존재하는 경우:
- _00760/_00761 우선 사용 (구조화 품질 높음)
- main XML의 동일 재무제표는 `duplicate_of: "{rcept_no}_00760"` 메타데이터 부여 후 **인덱싱 제외**
- 판별: EXTRACTION TABLE의 기간 + 회사명 + 재무제표 유형 3-way 일치 시 중복으로 판단

---

## 5. Audit Opinion Extraction Validation Plan (Q3 확정)

### 5-1. 배경

- 2,503건(80%)이 main XML 단독 — `_00760`/`_00761` 없음
- 이 파일들의 감사의견은 main XML `V. 회계감사인의 감사의견` SECTION에서 추출
- **전수 검증 불필요, 표본 기반 검증으로 결정**

### 5-2. 표본 설계

| 항목 | 기준 |
|------|------|
| 샘플 크기 | **75건** (50~100 범위, 중앙값) |
| 샘플링 방법 | 연도별 층화 (2024: 25건 / 2025: 25건 / 2026: 25건) |
| 선정 방식 | 랜덤 (`random.seed(42)`) |

### 5-3. 검증 절차

```
Step 1: 75건 샘플 대상 embedded 추출 실행
        → main XML V섹션 SECTION-2 텍스트에서 감사의견 추출

Step 2: SUMMARY SUPV_OPIN 코드와 대조
        추출 텍스트에 아래 키워드 포함 여부 확인:
        - SUPV_OPIN=100000000000 → "적정" 포함 여부
        - SUPV_OPIN=010000000000 → "한정" 포함 여부
        - SUPV_OPIN=001000000000 → "부적정" 포함 여부
        - SUPV_OPIN=000100000000 → "의견거절" 포함 여부

Step 3: 매칭률 산출
        pass_rate = (키워드 일치 건수) / 75

Step 4: 판정
        - pass_rate ≥ 0.95 → embedded 추출 방식 채택 확정
        - 0.85 ≤ pass_rate < 0.95 → 추출 정규식 보완 후 재검증
        - pass_rate < 0.85 → 추출 실패. V섹션 구조 변동 여부 재분석 필요

Step 5: 실패 샘플 오류 분류
        - 섹션 없음: main XML에 V섹션 자체 부재 (일부 약식 보고서)
        - 키워드 다른 표현: "이견 없음" 등 비표준 표현
        - 파싱 오류: XML 복구 후에도 텍스트 누락
```

### 5-4. Metadata 표기

| 감사의견 소스 | `audit_source` 값 | `audit_confidence` |
|------------|-----------------|-------------------|
| `_00760`/`_00761` XML | `"external"` | `"high"` |
| main XML V섹션 (검증 통과) | `"embedded"` | `"medium"` |
| main XML V섹션 (추출 실패) | `"embedded_failed"` | `"low"` |
| SUMMARY SUPV_OPIN 코드만 | `"summary_code"` | `"medium"` |

`audit_confidence: "low"` 청크는 감사의견 관련 쿼리에서 **retrieval 후보 제외** 처리.

---

## 6. Fallback Rules (전체)

### 6-1. 기본 Fallback 체계

```
[Token Count 결과]
  ≤ 380t  → 정상 청크, 그대로 확정
  381~400t → 정상 허용 범위 (허용 상한)
  401~480t → Fallback Zone (타입별 조건 적용)
  > 480t  → 강제 분할 필요
```

### 6-2. Type별 Fallback 규칙

#### T0 (Fact Chunk) — Fallback 없음

SUMMARY 항목 수가 고정적이므로 200t 초과 시 항목 중요도 순으로 하위 항목 제거.
제거 우선순위 (낮을수록 먼저 제거): ETC_OTHR_YN, POW_OTHR_YN, ACC_PROF_YN.

#### T1 / T1-NOTE (Narrative) — 강제 분할

400t 초과 시 fallback 없음. 문단 경계에서 즉시 분할.
단, 분할점 탐색 순서:
1. `\n\n` (빈 줄 경계)
2. `。` / `.` + 공백 (문장 끝)
3. 어절 경계 (공백)
4. 위 모두 없으면 399t에서 강제 절단

#### T2 (Financial Table) — 행 단위 보호 분할

400t 초과 시 행(`<TR>`) 경계에서 분할. 절대로 TR 중간 절단 금지.

```
분할 점 탐색:
  1. 합계 행("합계", "소계", "Total" 포함 TR) 직후
  2. 계정 그룹 구분행 (COLSPAN 전체 행) 직후
  3. 위 없으면 400t 이하 마지막 완전한 TR 직후
```

#### T2-NOTE / T3 (NOTE Table / Audit) — 확장 허용 (핵심 결정)

**기본: 400t 상한 적용.**

**Fallback 허용 조건** (모두 충족 시):
1. 401~480t 범위 내에 자연 경계가 존재할 것
   - 자연 경계 = 주석 항목 번호 변경 행, 합계 행, 빈 TR, KAM 섹션 구분
2. 400t에서 분할하면 의미 단위가 파괴될 것
   - 예: 합계 행이 401t에 있는 경우

**Fallback 적용 시**: 자연 경계까지 연장, 최대 **480t**까지.

**Fallback 금지 조건** (하나라도 해당 시 강제 분할):
- 480t 이내에 자연 경계 없음
- 확장 시 추정 토큰이 481t 이상
- 512t는 어떤 경우에도 사용하지 않음

### 6-3. Fallback 발생 Logging

Fallback 적용된 청크는 metadata에 기록:

```json
{
  "fallback_applied": true,
  "fallback_reason": "note_natural_boundary_at_420t",
  "final_tokens": 420
}
```

---

## 7. Final Recommended Defaults

### 7-1. 파라미터 기본값 (구현 시 사용)

```python
CHUNK_DEFAULTS = {
    # Token limits
    "T0_max": 200,
    "T1_target": 256,
    "T1_max": 380,
    "T1_overlap": 64,
    "T2_target": 320,
    "T2_max": 400,
    "T2_overlap": 0,
    "T3_target": 256,
    "T3_max": 380,
    "T3_overlap": 32,
    "T1_NOTE_max": 370,
    "T1_NOTE_overlap": 32,
    "T2_NOTE_max": 400,
    "T2_NOTE_fallback_max": 480,  # Q4 확정
    "ABSOLUTE_MAX": 480,          # 512 미사용 확정

    # NOTE classification
    "note_table_min_rows": 3,
    "note_numeric_cell_ratio": 0.5,

    # Consolidated priority
    "consolidated_score_boost": 0.05,

    # Audit validation
    "audit_sample_size": 75,
    "audit_pass_threshold": 0.95,

    # Token counter
    "tokenizer": "cl100k_base",
}
```

### 7-2. 처리 순서 (문서 1건 기준)

```
[1] ZIP 열기 (확장자 무관)
[2] XML 파일 역할 판별 (DOCUMENT-NAME ACODE)
[3] SUMMARY → T0 생성 (1개)
[4] BODY 트리 순회
    [4a] SECTION 경계마다 breadcrumb 갱신
    [4b] 요소별 분기:
         - <P> → 주석 여부 확인 → T1 or T1-NOTE 누적
         - <TABLE ACLASS=NORMAL> → 재무제표/주석 판별 → T2 or T2-NOTE 분류
         - <TABLE ACLASS=EXTRACTION> → 컨텍스트 추출 (기간·단위·재무유형) 후 스킵
         - <IMAGE> → 스킵
         - <PGBRK> → 스킵
    [4c] 누적 중인 T1 청크가 T1_target 초과 → 청크 확정 + overlap 준비
[5] _00760 / _00761 존재 시 → T3 생성
    없을 경우 → main XML V섹션에서 T3 embedded 추출
[6] 중복 재무제표 제거 (_00760/761과 main 중복 판별)
[7] 전체 청크 metadata 완성 + chunk_id 부여
[8] statement_scope 확정 (연결/개별 판별)
[9] JSONL 출력
```

### 7-3. Metadata 스키마 (v2 확정)

```json
{
  "chunk_id": "DART_{rcept_no}_{type}_{seq:04d}",
  "chunk_type": "fact | narrative | table | audit",
  "note_type": "tabular | narrative | null",

  "company_name": "BGF리테일",
  "company_reg_no": "01263022",
  "rcept_no": "20260318000829",
  "doc_type": "사업보고서",
  "report_date": "20260318",

  "fiscal_year": "2025",
  "fiscal_year_end": "20251231",

  "source_file": "DART_P0_BGF리테일_20260318000829.zip",
  "source_xml": "20260318000829.xml",

  "section_path": "III.재무에관한사항 > 8.기타재무에관한사항",
  "section_depth": 2,

  "table_type": "BS | IS | CF | EQ | RE | NOTE | null",
  "statement_scope": "consolidated | separate | unknown",
  "fin_unit": "백만원",
  "ifrs": true,
  "period_current": "20250101~20251231",
  "period_prior": "20240101~20241231",

  "note_seq": "3",
  "duplicate_of": "null",

  "audit_source": "external | embedded | embedded_failed | summary_code",
  "audit_confidence": "high | medium | low",
  "audit_opinion": "적정 | 한정 | 부적정 | 의견거절 | null",
  "auditor": "삼일회계법인",

  "chunk_tokens": 312,
  "chunk_chars": 580,
  "has_table": true,
  "has_numbers": true,

  "fallback_applied": false,
  "fallback_reason": null,
  "final_tokens": 312
}
```

### 7-4. 필드 필수/선택 매트릭스 (v2)

| 필드 | T0 | T1 | T2 | T3 | T1-NOTE | T2-NOTE |
|------|----|----|----|----|---------|---------|
| chunk_id | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| company_name | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| rcept_no | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| fiscal_year | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| statement_scope | ✓ | — | ✓ | ✓ | — | ✓ |
| section_path | — | ✓ | ✓ | — | ✓ | ✓ |
| table_type | — | — | ✓ | — | — | ✓(`NOTE`) |
| fin_unit | — | — | ✓ | — | — | 선택 |
| period_current | — | — | ✓ | — | — | 선택 |
| note_type | — | — | — | — | ✓ | ✓ |
| note_seq | — | — | — | — | 선택 | 선택 |
| audit_source | ✓ | — | — | ✓ | — | — |
| audit_confidence | ✓ | — | — | ✓ | — | — |
| audit_opinion | ✓ | — | — | ✓ | — | — |
| auditor | — | — | — | ✓ | — | — |
| has_table | — | 선택 | ✓ | 선택 | 선택 | ✓ |
| has_numbers | 선택 | 선택 | ✓ | 선택 | 선택 | ✓ |
| fallback_applied | — | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## 8. 예상 청크 수 추정 (v2 기준)

단일 문서(연결+개별 모두 인덱싱):

| Type | 예상 청크 수 |
|------|------------|
| T0 Fact | 1 |
| T1 Narrative | ~70 |
| T2 Financial Table (consolidated) | ~35 |
| T2 Financial Table (separate) | ~30 |
| T3 Audit | ~10 |
| T1-NOTE Narrative Note | ~20 |
| T2-NOTE Tabular Note | ~15 |
| **합계** | **~181 청크/문서** |

**전체 데이터셋 추정**:
- 3,135문서 × 평균 160청크 = **약 501,600 청크**
- BGE-M3 1024-dim float32 → Qdrant ~2.0GB 예상

---

## 9. Phase B 품질 검증 기준

샘플 10개사, 150건 문서 기준:

| 검증 항목 | 합격 기준 | 측정 방법 |
|---------|---------|---------|
| 청크 토큰 분포 | 95%가 400t 이하 | histogram |
| Fallback 발생률 | T2-NOTE 중 10% 이하 | fallback_applied count |
| 재무제표 헤더 부착률 | T2 청크 100% | section_path + table_type 비어있지 않음 |
| breadcrumb 유효율 | T1/T2 98% 이상 | section_path null 비율 |
| statement_scope 확정률 | 95% 이상 non-"unknown" | scope 분포 |
| NOTE 분류 정확도 | 수동 검토 30건, 90% 이상 일치 | 수동 검증 |
| 감사의견 추출 pass_rate | ≥ 95% (75건 샘플) | §5-3 절차 |
| RAGAS ctx_precision | 기존 63.3 대비 **+7p 이상** | real RAGAS lib |
