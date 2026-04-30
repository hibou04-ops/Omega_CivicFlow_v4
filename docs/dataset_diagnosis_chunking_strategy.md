# DART 데이터셋 진단 & 청킹 전략 초안
> 작성일: 2026-04-14 | 대상: C:\Users\hibou\Desktop\DataSet

---

## 1. 파일 구조 진단 결과

### 1-1. 포맷 판별 (결론)

| 확장자 | 파일 수 | 실제 포맷 | 판별 근거 |
|--------|---------|-----------|-----------|
| `.zip` | 2,131건 | ZIP 컨테이너 | magic bytes `PK\x03\x04` |
| `.zip.pdf` | 1,004건 | **ZIP 컨테이너** (PDF 아님) | magic bytes `PK\x03\x04` |
| 합계 | 3,135건 | 모두 ZIP | — |

**핵심**: `.zip.pdf`는 잘못된 확장자이지만 실제 내용은 ZIP이다.
PDF 바이너리(`%PDF`)는 한 건도 없다. PDF 파싱 시도 불필요.

### 1-2. ZIP 내부 구성

ZIP 내부는 XML 파일만 존재한다 (이미지/첨부파일 없음).

| 내부 파일 수 | 건수 | 구성 |
|------------|------|------|
| 1개 | 2,503건 | `{rcept_no}.xml` (사업보고서 단독) |
| 2개 | 158건 | main + `_00760` 또는 main + `_00761` |
| 3개 | 474건 | main + `_00760` + `_00761` |

### 1-3. XML 파일 역할 정의

| 파일명 패턴 | ACODE | 문서명 | 평균 크기 |
|-----------|-------|--------|----------|
| `{rcept_no}.xml` | 11011 | 사업보고서 | ~5MB (최대 10MB) |
| `{rcept_no}_00760.xml` | 00760 | 감사보고서 (개별 재무제표) | ~500KB |
| `{rcept_no}_00761.xml` | 00761 | 연결감사보고서 (연결 재무제표) | ~650KB |

### 1-4. 데이터셋 규모

- **고유 회사**: 503개
- **연도 범위**: 2024년(725건) / 2025년(1,114건) / 2026년(1,296건)
- **인코딩**: UTF-8 (전수 확인)
- **XML 파서**: 표준 파서 파싱 오류 발생 → `lxml`(recover=True) 필수

---

## 2. XML 문서 구조 분석

### 2-1. DART 전용 XML 스키마 (dart4.xsd)

```
<DOCUMENT>
├── <DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>
├── <FORMULA-VERSION>
├── <COMPANY-NAME AREGCIK="...">
├── <SUMMARY>               ← XBRL 구조화 값 (key-value)
│   ├── <EXTRACTION ACODE="TOT_ASSETS">  총자산
│   ├── <EXTRACTION ACODE="TOT_DEBTS">   총부채
│   ├── <EXTRACTION ACODE="TOT_SALES">   매출액
│   ├── <EXTRACTION ACODE="IFRS_YN">     IFRS 적용 여부
│   └── ... (18~20개 항목)
└── <BODY>
    ├── <COVER>
    ├── <TITLE>
    ├── <SECTION-1 "I. 회사의 개요">
    │   ├── <TITLE>
    │   ├── <SECTION-2 "1. 회사의 개요">
    │   └── <SECTION-2 "2. 회사의 연혁">
    ├── <SECTION-1 "II. 사업의 내용">
    ├── <SECTION-1 "III. 재무에 관한 사항">  ← 핵심, 테이블 87%
    │   ├── <SECTION-2 "1. 요약재무정보">
    │   └── <SECTION-2 "8. 기타 재무에 관한 사항">
    │       └── (재무제표 전문: 연결/개별 B/S, I/S, C/F 등)
    └── ... (IV~XII)
```

### 2-2. TABLE 분류 체계 (ACLASS 기준)

| ACLASS | 수 (BGF 예시) | 역할 |
|--------|-------------|------|
| `EXTRACTION` | 90개 | 구조화 핵심 데이터 (기간, 단위 헤더 등) |
| `NORMAL` | 1,667개 | 일반 서술 테이블, 재무제표 본문 |

> `EXTRACTION` 테이블은 기간·단위·재무유형 등 메타데이터를 담는다.
> 재무제표 실제 수치는 `NORMAL` 테이블에 있다.

### 2-3. 섹션별 테이블 밀도 (BGF리테일 2026 기준)

| 섹션 | 테이블 수 | 비고 |
|------|----------|------|
| III. 재무에 관한 사항 | **1,522** | 전체의 87% |
| VIII. 임원 및 직원 | 33 | |
| II. 사업의 내용 | 59 | |
| VI. 이사회 등 기관 | 23 | |
| 나머지 합계 | ~120 | |

---

## 3. 청킹 이전 필요한 전처리 단계

### 3-1. 추출 파이프라인 (순서)

```
[1] 컨테이너 해제
    .zip / .zip.pdf → zipfile.ZipFile(path, 'r') 동일하게 처리
    → 확장자 무시, 파일명 패턴 기준으로 role 결정

[2] XML 파싱
    lxml.etree.XMLParser(recover=True, encoding='utf-8') 필수
    표준 xml.etree.ElementTree → 말형식 오류로 실패함

[3] 문서 역할 분류
    DOCUMENT-NAME @ACODE 기준:
    - 11011 → 사업보고서 (main)
    - 00760 → 개별 감사보고서
    - 00761 → 연결 감사보고서

[4] SUMMARY 구조화 데이터 분리 추출
    EXTRACTION @ACODE → 별도 메타데이터 필드로 보관
    (TOT_ASSETS, TOT_DEBTS, TOT_SALES, IFRS_YN 등)

[5] BODY 섹션 트리 구성
    SECTION-1 → SECTION-2 → SECTION-3 계층 추적
    각 노드의 breadcrumb = "I. 회사의 개요 > 1. 회사의 개요"

[6] 테이블 분리 처리
    ACLASS=EXTRACTION → 기간/단위 메타데이터로 파싱
    ACLASS=NORMAL → 청킹 대상
```

### 3-2. 이미지/첨부 처리

현 데이터셋: `<IMAGE>` 태그 참조는 있으나 실제 이미지 바이너리 미포함.
대표이사 확인서 이미지 등 → 해당 섹션 텍스트 기여값 없음. 스킵 처리.

---

## 4. 청킹 전략 초안

### 4-1. 현재 RAGAS 병목 분석

```
RAGAS baseline: 74.07
ctx_precision: 63.3  ← 주요 병목
```

**원인 진단**: 재무제표 line item 수치가 섹션 헤더(계정명, 기간, 단위)와
물리적으로 분리된 채 청킹되면, LLM이 "이 숫자가 무엇인지" 추론 불가.

### 4-2. 청킹 전략: 4-Layer 구조

---

#### Layer 0: SUMMARY Fact Chunk (문서당 1개)

**대상**: `<SUMMARY>` 전체
**크기**: 고정 (~300 tokens)
**형식**:

```
[회사명] [기간] 핵심 재무 요약
- 총자산: {TOT_ASSETS}
- 총부채: {TOT_DEBTS}
- 매출액: {TOT_SALES}
- IFRS: {IFRS_YN}
- 종업원 수: {TOT_EMPL}
```

**목적**: "BGF리테일 총자산이 얼마야?" 같은 단순 수치 질문에 정밀 응답.
ctx_precision 직접 기여.

---

#### Layer 1: Section Narrative Chunk

**대상**: SECTION-1 > SECTION-2 단위로 텍스트 추출 (TABLE 제외)
**크기**: 512~1,024 tokens (문단 경계 기준 분할)
**헤더 강제 부착**:

```
[회사명 | 사업연도 | I. 회사의 개요 > 1. 회사의 개요]
{텍스트 본문}
```

**목적**: 서술형 질문 (사업모델, 리스크, 지배구조 등)
`ctx_precision` 개선: 헤더로 컨텍스트 오염 방지.

---

#### Layer 2: Financial Table Chunk (가장 중요)

**대상**: III. 재무에 관한 사항 내 NORMAL TABLE

**핵심 원칙**: 테이블 = 헤더(기간+단위) + 본문(계정명+수치)를 절대 분리하지 않는다.

**청킹 단위**: 재무제표 1개 = 1 Chunk
- 연결 재무상태표 (B/S)
- 연결 손익계산서 (I/S)
- 연결 현금흐름표 (C/F)
- 연결 자본변동표
- 개별 재무상태표
- 개별 손익계산서

**헤더 강제 부착**:

```
[회사명 | 사업연도 | 재무제표 유형(연결/개별) | 단위(백만원) | 기간(전기/당기)]
{TABLE 전체 → Markdown 테이블 변환}
```

**TABLE → Markdown 변환 방법**:
- TR 각 행을 `| col1 | col2 | ... |` 형식으로 변환
- 첫 TR은 header separator(`|---|---|`) 삽입
- COLSPAN/ROWSPAN: 셀 반복 처리 (lxml attrib 기준)

**크기 제한**: 재무제표 테이블이 2,000 tokens 초과 시 → 계정 그룹 단위로 분할:
- 유동자산 그룹 / 비유동자산 그룹 / 부채 그룹 / 자본 그룹
- **단**: 각 서브청크에도 테이블 헤더(기간, 단위, 재무제표명) 재부착 필수

---

#### Layer 3: Audit Opinion Chunk (_00760 / _00761)

**대상**: 감사보고서/연결감사보고서 (`_00760`, `_00761`)
**크기**: 512~1,024 tokens

**추출 항목**:
- 감사의견 (적정/한정/부적정)
- 핵심감사사항 (KAM)
- 감사인명 + 감사 기간

**헤더**:

```
[회사명 | 사업연도 | 감사보고서(연결/개별) | 감사인]
{감사의견 텍스트}
```

**목적**: "XX 회사 감사의견이 뭐야?" 질문 전용 retrieval.

---

### 4-3. 메타데이터 스키마 (모든 청크 공통)

```json
{
  "chunk_id": "DART_{rcept_no}_L{layer}_{seq}",
  "company_name": "BGF리테일",
  "company_reg_no": "01263022",
  "rcept_no": "20260318000829",
  "doc_type": "사업보고서",
  "report_year": "2025",
  "fiscal_year_end": "20251231",
  "layer": 0,
  "section_path": "III.재무에관한사항>1.요약재무정보",
  "fin_type": "consolidated",
  "ifrs": true,
  "unit": "백만원",
  "chunk_tokens": 512,
  "source_file": "DART_P0_BGF리테일_20260318000829.zip"
}
```

---

### 4-4. ctx_precision 개선 예상 경로

| 현재 문제 | 개선 메커니즘 | 예상 효과 |
|---------|-------------|---------|
| 수치-헤더 분리 | Layer 2: 헤더 강제 부착 + 재무제표 단위 청킹 | ctx_precision +10~15p |
| 잘못된 섹션 혼입 | Layer 1: breadcrumb 헤더 + 섹션 단위 경계 | ctx_precision +5p |
| 단순 수치 질문 실패 | Layer 0: SUMMARY Fact Chunk | precision @top1 개선 |
| 감사의견 질문 오염 | Layer 3 분리 | recall 개선 |

---

## 5. 미결 이슈 (Phase B 진입 전 확인 필요)

### 5-1. III. 재무에 관한 사항 내 재무제표 경계 판별

현재 관찰: SECTION-2 "8. 기타 재무에 관한 사항" 내 1,522개 TABLE이 밀집.
개별 재무제표의 시작/끝을 어떤 태그로 판별할 수 있는지 추가 분석 필요.

→ `EXTRACTION AFIXTABLE=Y` 테이블이 각 재무제표 앞에 나타나는 패턴 검증 필요

### 5-2. COLSPAN/ROWSPAN 처리

재무표 헤더 행에서 COLSPAN 미처리 시 열 정렬 깨짐.
`lxml` 기준 `colspan` attrib 처리 로직 설계 필요.

### 5-3. 감사보고서 없는 1개짜리 파일 처리

2,503건(80%)이 main XML만 존재.
_00760 없는 파일의 감사의견은 main XML 내 "V. 회계감사인의 감사의견"
섹션에서 추출 — 단, 구조 차이 검증 필요.

### 5-4. 청크 크기 검증

현재 RAGAS baseline이 74.07 (real RAGAS).
Layer 2 청크가 너무 크면 (>1,500 tokens) ctx_precision 역효과.
→ 토크나이저 기준 실측 필요 (tiktoken 또는 transformers tokenizer).

### 5-5. 연도별 스키마 변동

2024~2026년 파일 혼재. DART XML 스키마 버전(`FORMULA-VERSION`)이
연도별로 다를 수 있음 → 파싱 로직의 fallback 설계 필요.

---

## 6. 권장 작업 순서 (Phase B)

```
Step 1: Layer 2 재무제표 경계 판별 로직 검증 (5-1 해결)
Step 2: TABLE → Markdown 변환 + COLSPAN 처리 프로토타입
Step 3: 샘플 10개사로 4-Layer 청킹 실행 + 토큰 수 분포 실측
Step 4: RAGAS eval 재실행 (real RAGAS lib 기준)
Step 5: ctx_precision 병목 재확인 후 Layer 2 파라미터 조정
Step 6: 전체 3,135건 청킹 실행 (클라우드)
```
