# DART 청킹 정책 v1 — 결정 문서
> 작성일: 2026-04-14 | 기반: dataset_diagnosis_chunking_strategy.md

---

## 0. 하드 제약 (변경 불가)

| 제약 | 값 | 근거 |
|------|---|------|
| BGE-M3 max_seq | **512 tokens** | 초과 시 silently truncate, 수치 손실 |
| 파서 | `lxml(recover=True)` | 표준 ET → ParseError 다수 발생 |
| 인코딩 | UTF-8 | 전수 확인 완료 |
| 청크 상한 | **400 tokens** | 512에서 메타 헤더 여유분 확보 |

---

## 1. Chunk Type 정의

총 4가지 청크 타입. 각 타입은 독립적으로 인덱싱.

### Type 0: Fact Chunk (문서당 1개)

| 항목 | 값 |
|------|---|
| 대상 | `<SUMMARY>` EXTRACTION 항목 전체 |
| 목표 크기 | 150~200 tokens (고정) |
| overlap | 없음 (단일 블록) |
| 분할 없음 | SUMMARY 전체를 단일 청크 |

**텍스트 포맷**:
```
[{회사명} | {사업연도} | 핵심재무요약]
총자산: {TOT_ASSETS}백만원
총부채: {TOT_DEBTS}백만원
매출액: {TOT_SALES}백만원
종업원: {TOT_EMPL}명
IFRS적용: {IFRS_YN}
감사의견: {SUPV_OPIN_코드변환}
재무유형: {FIN_STAT 코드변환}
```

**SUPV_OPIN 코드 변환표**:
- `100000000000` → "적정"
- `010000000000` → "한정"
- `001000000000` → "부적정"
- `000100000000` → "의견거절"

---

### Type 1: Narrative Chunk (섹션 서술)

| 항목 | 값 |
|------|---|
| 대상 | `<P>` 태그 텍스트 (TABLE 제외) |
| 분할 단위 | SECTION-2 내부 문단 누적 |
| 목표 크기 | **256 tokens** |
| 최대 크기 | **380 tokens** |
| overlap | **64 tokens** (문단 경계 우선) |
| 분할 기준 | 문단 경계 → 어절 경계 순으로 fallback |

**헤더 포맷** (모든 청크 첫 줄에 강제 삽입):
```
[{회사명} | {사업연도} | {SECTION-1_제목} > {SECTION-2_제목}]
```

헤더는 토큰 카운트에 포함. 헤더 평균 20~30 tokens 예상.

**overlap 정책**:
- 동일 SECTION-2 내에서만 overlap 허용
- SECTION 경계 넘는 overlap 금지 (컨텍스트 오염 방지)
- overlap 구간에 헤더 재부착

**스킵 대상**:
- 빈 `<P>` (whitespace만 있는 노드)
- 10 tokens 미만 문단 (목차 참조 줄 등)
- `<IMAGE>` 자식 텍스트 (파일명만 있는 경우)

---

### Type 2: Financial Table Chunk (재무제표 핵심)

#### 2-A. 재무제표 단위 청크

| 항목 | 값 |
|------|---|
| 대상 | III. 재무에 관한 사항 내 ACLASS=NORMAL TABLE |
| 분할 단위 | 재무제표 1개 = 원칙적으로 1 청크 |
| 목표 크기 | **300~380 tokens** |
| 최대 크기 | **400 tokens** |
| overlap | **없음** (테이블 행 분할 시 헤더 행 반복으로 대체) |

**재무제표 경계 판별 규칙** (우선순위 순):
1. `ACLASS=EXTRACTION`, `AFIXTABLE=Y` TABLE이 선행 → 다음 NORMAL TABLE 묶음의 시작점
2. 첫 TR 내 "재무상태표", "손익계산서", "현금흐름표", "자본변동표" 텍스트 감지
3. 앞 EXTRACTION TABLE의 ACODE로 재무제표 유형 식별

**재무제표 유형 → 청크 레이블 매핑**:
| 판별 키워드 | 레이블 |
|-----------|--------|
| 재무상태표 / 대차대조표 | `BS` |
| 포괄손익계산서 / 손익계산서 | `IS` |
| 현금흐름표 | `CF` |
| 자본변동표 | `EQ` |
| 이익잉여금처분계산서 | `RE` |
| 주석 | `NOTE` |

#### 2-B. 테이블 분할 정책 (400 tokens 초과 시)

단일 재무제표 TABLE이 400 tokens 초과 → **계정 그룹 단위 분할**:

분할 기준 행:
- 유동자산 합계 / 비유동자산 합계 행 위에서 분할
- 유동부채 합계 / 비유동부채 합계 행 위에서 분할
- 자본 합계 행 위에서 분할

**분할 시 헤더 재부착 규칙** (핵심):
```
분할 서브청크 = [헤더 행 전체] + [분할된 계정 그룹 행]
```

헤더 행 = 기간 행 (제XX기 당기 / 전기) + 단위 행 — 절대 생략 금지.

#### 2-C. TABLE → Markdown 변환 규칙

```
TR → | cell1 | cell2 | cell3 |
첫 TR → | cell1 | cell2 | ... |
         | ---- | ---- | ... |   (구분선 삽입)
COLSPAN n → 동일 셀 텍스트를 n회 반복: | 유동자산 | 유동자산 | ...
ROWSPAN n → 병합된 행에서 동일 텍스트 반복
빈 TD → 공백 셀 유지: | | 
```

**텍스트 정규화**:
- 숫자 내 쉼표 유지: `1,234,567` (제거 금지 — 검색 패턴 일치용)
- `(음수)` 표현 유지
- 괄호 단위 표시 `(단위: 백만원)` 헤더 행에서 추출 → metadata에 저장

**헤더 포맷**:
```
[{회사명} | {사업연도} | {연결/개별} | {BS/IS/CF/EQ} | 단위:{unit} | 기간:{당기기간}~{전기기간}]
| 계정과목 | {당기} | {전기} |
| ---- | ---- | ---- |
| {계정명} | {수치} | {수치} |
...
```

---

### Type 3: Audit Chunk (_00760 / _00761)

| 항목 | 값 |
|------|---|
| 대상 | `_00760.xml` / `_00761.xml` |
| 분할 단위 | 감사의견 절 + KAM 각 항목 |
| 목표 크기 | **256 tokens** |
| 최대 크기 | **380 tokens** |
| overlap | **32 tokens** |

**추출 우선순위**:
1. `<SUMMARY>` SUPV_OPIN → Type 0에서 코드로 변환
2. 감사의견 본문 (의견 절, 의견 근거 절)
3. 핵심감사사항 (KAM) — 각 KAM을 독립 청크로
4. 강조 사항 / 기타 의사소통 사항

**_00760 없는 2,503건 처리**:
main XML 내 `V. 회계감사인의 감사의견` SECTION-2에서 Type 1과 동일한
Narrative 방식으로 추출. metadata `audit_source: "embedded"` 표시.

---

## 2. Overlap 정책 요약

| Type | overlap | 이유 |
|------|---------|------|
| Type 0 | 0 | 단일 구조화 블록 |
| Type 1 | 64 tokens | 문장 경계 걸침 방지 |
| Type 2-A | 0 | 헤더 행 반복으로 대체 |
| Type 2-B | 0 | 분할 시 헤더 재부착으로 대체 |
| Type 3 | 32 tokens | 짧은 감사 서술 보호 |

**overlap 계산 기준**: 토큰 수, tiktoken `cl100k_base` 기준.
(BGE-M3는 WordPiece이나 길이 추정용으로 cl100k 사용 허용)

---

## 3. 헤딩(Heading) 처리 정책

### 3-1. breadcrumb 생성 규칙

모든 청크에 적용. SECTION 계층 추적:

```python
# 의사코드
breadcrumb = []
for ancestor in element.iterancestors():
    if ancestor.tag.startswith('SECTION'):
        title_el = ancestor.find('TITLE')
        if title_el is not None:
            breadcrumb.insert(0, ''.join(title_el.itertext()).strip())

header = f"[{company_name} | {fiscal_year} | {' > '.join(breadcrumb)}]"
```

### 3-2. 헤딩이 없는 TITLE 태그 처리

BODY 직계 자식 `<TITLE>` (목차 등) → 스킵, 청크 미생성.

### 3-3. SECTION 경계 = 청크 경계

SECTION-2가 바뀌면 반드시 새 청크 시작. overlap 허용 안 함.
→ 서로 다른 섹션 내용이 한 청크에 공존하는 경우 금지.

---

## 4. Metadata 스키마 (확정)

```json
{
  "chunk_id": "DART_{rcept_no}_{type}_{seq:04d}",
  "type": "fact|narrative|table|audit",

  "company_name": "BGF리테일",
  "company_reg_no": "01263022",
  "rcept_no": "20260318000829",
  "doc_type": "사업보고서",

  "fiscal_year": "2025",
  "fiscal_year_end": "20251231",
  "report_date": "20260318",

  "source_file": "DART_P0_BGF리테일_20260318000829.zip",
  "source_xml": "20260318000829.xml",

  "section_path": "III.재무에관한사항 > 8.기타재무에관한사항",
  "section_depth": 2,

  "table_type": "BS",
  "fin_scope": "consolidated",
  "fin_unit": "백만원",
  "ifrs": true,
  "period_current": "20250101~20251231",
  "period_prior": "20240101~20241231",

  "audit_source": "embedded",
  "audit_opinion": "적정",
  "auditor": "삼일회계법인",

  "chunk_tokens": 312,
  "chunk_chars": 580,
  "has_table": true,
  "has_numbers": true
}
```

**필드별 필수/선택 구분**:

| 필드 | Type 0 | Type 1 | Type 2 | Type 3 |
|------|--------|--------|--------|--------|
| chunk_id | 필수 | 필수 | 필수 | 필수 |
| company_name | 필수 | 필수 | 필수 | 필수 |
| rcept_no | 필수 | 필수 | 필수 | 필수 |
| fiscal_year | 필수 | 필수 | 필수 | 필수 |
| section_path | — | 필수 | 필수 | — |
| table_type | — | — | 필수 | — |
| fin_scope | — | — | 필수 | — |
| fin_unit | — | — | 필수 | — |
| period_current | — | — | 필수 | — |
| audit_opinion | 필수 | — | — | 필수 |
| auditor | — | — | — | 필수 |
| has_table | — | 선택 | 필수(true) | 선택 |
| has_numbers | 선택 | 선택 | 필수 | 선택 |

---

## 5. 예상 청크 수 추정

BGF리테일 단일 문서 기준:
| Type | 예상 청크 수 |
|------|------------|
| Type 0 | 1 |
| Type 1 | ~80 (서술 섹션 기준) |
| Type 2 | ~60 (재무제표 + 주석) |
| Type 3 | ~10 |
| **합계** | **~151 청크/문서** |

**전체 데이터셋 추정**:
- 3,135개 문서 × 평균 120 청크 = **약 376,200 청크**
- Qdrant 컬렉션 용량: BGE-M3 1024-dim float32 → ~1.5GB 예상

---

## 6. 품질 검증 기준 (Phase B)

샘플 10개사로 먼저 실행 후 확인할 항목:

| 검증 항목 | 합격 기준 |
|---------|---------|
| 청크 토큰 분포 | 95%가 400 tokens 이하 |
| 재무제표 헤더 부착률 | Type 2 청크 100% 헤더 보유 |
| breadcrumb 유효율 | Type 1/2 청크 98% 이상 section_path 비어있지 않음 |
| 숫자 포함률 | Type 2 청크 90% 이상 has_numbers=true |
| RAGAS ctx_precision | 기존 63.3 대비 +5p 이상 개선 확인 |

---

## 7. 미결 결정 사항 (구현 착수 전 확인 필요)

| 번호 | 이슈 | 결정 필요자 |
|------|------|----------|
| Q1 | 주석(NOTE) 테이블을 Type 2로 분류할지 Type 1로 할지 | 사용자 |
| Q2 | 연결 vs 개별 재무제표 중복 시 둘 다 인덱싱할지 연결만 할지 | 사용자 |
| Q3 | 2,503건 단독 사업보고서에서 감사의견 추출 방식 (embedded 처리로 충분한지) | 검증 후 결정 |
| Q4 | Type 2 주석 청크의 최대 크기 완화 (400 → 512 허용 여부) | BGE-M3 실측 후 결정 |
