"""
═══════════════════════════════════════════════════════
Omega CivicFlow — LLM Service v2
해밀토니안 최적화 경로 (Hamiltonian Optimal Path) 엔진
Ollama 기반 DART 공시문서 분석 — 문서유형별 전용 분류/요약/추출

Phase 2: 문서유형 분류 + 유형별 전용 프롬프트 + PDF 수준 구조화 출력
═══════════════════════════════════════════════════════
"""

import json
import re
import time
import asyncio
import logging
from typing import Optional, Dict, Any, List

import httpx

from config import settings
from services.metadata_validator import metadata_validator, SafeRenderContext
from services.document_metadata_extractor import (
    extract_document_metadata, build_metadata_prompt_block,
    is_section_title, NEGATIVE_KEYWORDS as SECTION_NEGATIVE_KEYWORDS,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# Phase 2 — 문서유형 분류 프롬프트
# ═══════════════════════════════════════════════════════

CLASSIFICATION_PROMPT = """당신은 한국 DART 공시문서 유형 분류 전문가입니다.

아래 텍스트를 읽고, 가장 정확한 문서 유형을 분류하세요.

[분류 기준 — 15개 유형]
1. 사업보고서 — "사업보고서", "사업의 내용", "임원 및 직원 등의 현황", "이사회 운영"
2. 반기보고서 — "반기보고서", "반기검토", "상반기", "하반기"
3. 분기보고서 — "분기보고서", "분기검토", "1분기", "2분기", "3분기"
4. 재무제표 — "재무상태표", "손익계산서", "포괄손익계산서", "현금흐름표", "자본변동표"
5. 감사보고서 — "감사보고서", "감사의견", "적정의견", "한정의견", "의견거절"
6. 주석 — "주석", "재무제표에 대한 주석", "유의적인 회계정책"
7. 정정신고(보고) — "정정신고", "정정 전", "정정 후", "정정보고"
8. 주요사항보고서 — "주요사항보고서", "주요경영사항", "전환사채", "신주인수권부사채"
9. 유상증자결정 — "유상증자", "신주발행", "제3자배정", "증자결정"
10. 대량보유보고서 — "대량보유", "주식등의 대량보유", "5% 보고", "보유비율"
11. 임원·주요주주변동 — "임원변동", "주요주주", "특정증권등 소유", "임원 선임", "사외이사"
12. 자기주식 — "자기주식", "자사주", "자기주식처분", "자기주식취득"
13. 합병·분할 — "합병", "분할합병", "분할", "영업양수도", "주식의 포괄적 교환"
14. 배당 — "배당", "현금배당", "주식배당", "배당금", "중간배당"
15. 기타공시 — 위 14개에 해당하지 않는 경우에만 사용

[핵심 규칙]
- "기타공시"는 최후의 수단으로만 사용. 위 14개 유형 중 하나에 반드시 매칭을 시도하세요.
- 문서가 여러 유형에 해당하면 primary_type(주), secondary_type(부)을 모두 지정
- 반기/분기보고서 안에 재무제표가 있으면 primary=반기보고서, secondary=재무제표
- 반드시 아래 JSON만 출력

[회사명 추출 규칙]
- company_name은 순수 법인명(상호)만 기입 (예: "삼성전자", "(주)바른손", "한화에너지")
- "대표이사", "본점소재지", "주소", "등기번호", "사업자등록번호" 등은 절대 포함 불가
- "주식회사", "(주)" 등 법인 접미/접두어는 허용
- 숫자, 날짜, 금액, 주소는 절대 불가
- 못 찾으면 "미확인"

[텍스트]
{document_text}

{{"primary_type": "...", "secondary_type": "...", "company_name": "...", "disclosure_title": "..."}}"""


# ═══════════════════════════════════════════════════════
# Phase 2 — 재무제표 전용 분석 프롬프트
# ═══════════════════════════════════════════════════════

FINANCIAL_ANALYSIS_PROMPT = """당신은 한국 재무제표/사업보고서 분석 전문 아키텍트입니다.

[역할]
입력된 텍스트에서 재무 정보를 **빠짐없이** 추출합니다.
문서에 없는 숫자를 지어내지 마세요.

[정보 가중치 필터 — 칼만 필터 원리 적용]
아래 가중치 순서에 따라 정보를 필터링하라. 가중치가 높은 정보를 우선 추출하고, 가중치 下(하) 정보는 제거하라.

★★★ 가중치 최상 (반드시 추출):
- 전기 대비 증감률 (매출, 영업이익, 순이익의 전기 vs 당기 비교)
- 영업이익률, 부채비율, ROE/ROA 등 핵심 비율
- 감사의견 종류 (적정/한정/부적정/의견거절)
- 계속기업 존속 관련 의견
- ★★★ 핵심감사사항 (Key Audit Matters) — 감사인이 가장 위험하게 본 영역
  반드시 모든 핵심감사사항을 추출하라. 예: '검색광고 수익인식', '투자부동산 공정가치평가', '종속기업투자주식 손상평가'
  각 항목마다 왜 핵심감사사항으로 지정되었는지 이유도 간략히 포함

★★ 가중치 상 (추출 권장):
- 당기 절대값: 매출액, 영업이익, 당기순이익, 자산총계, 부채총계, 자본총계
- 발행주식수, 주당이익(EPS), 배당금
- 주요 투자/차입 금액
- 영업활동현금흐름, 기말 현금및현금성자산
- ★★ 주석 기반 리스크 — 숫자 밑에 숨어있는 리스크를 추출하라
  유동성위험, 차입약정한도, 난외약정, 파생금융부채, 풋/콜옵션, 우발부채 등

★ 가중치 중 (있으면 추출):
- 자산/부채 세부 구성 (유동/비유동)
- 현금흐름표 주요 항목
- 사업 부문별 매출 비중

✗ 가중치 하 (제거 — 요약에 포함하지 마라):
- 표지, 목차, 페이지 번호
- 법적 면책 조항 ("본 보고서는 법령에 따라...")
- 일반적인 회계 정책 설명 (이미 알려진 IFRS 원칙)
- 관계사 목록 나열 (주요 거래 없는 경우)

[카테고리-컨텍스트 정렬]
문서유형이 "{doc_type}"이므로, 해당 유형에 맞는 정보를 우선 추출하라:
- 사업보고서 → 사업 현황, 매출 구성, 임직원 현황, 성장 전략 우선
- 재무제표 → 재무상태표, 손익계산서, 현금흐름표 수치 우선
- 감사보고서 → 감사의견, 핵심감사사항, 특기사항 우선
- 반기/분기보고서 → 전기 대비 변동률 우선

[주의] 깨진 OCR은 인용하지 말고 문맥으로 재구성. 회사명 불확실하면 "미확인".

[문서 텍스트]
{document_text}

[출력 규칙]
1. 반드시 아래 JSON만 출력
2. 숫자는 문서 내 표기된 '단위(원, 백만원 등)'를 실제 숫자에 곱해서 '원(KRW)' 단위 정수로 변환하여 기입하라 (예: 수치가 '10,000'이고 단위가 '백만원'이면 '10000000000' 기입). 괄호 안의 숫자는 음수이다.
3. ★ 주의: 표 상단의 '(단위: 1원)' 같은 메타데이터 레이블을 실제 재무 수치인 '1'로 추출하는 환각(Hallucination)을 절대 범하지 마라.
4. 값이 공란이거나 대시(-)로 표기된 경우 임의로 1이나 0을 넣지 말고 무조건 `null` 처리하라.
5. summary에 최소 10개 이상의 구체적 숫자를 포함하라. 숫자 없는 추상 요약은 실패로 간주
6. "전기 대비", "증가", "감소" 등 변화를 나타내는 문장을 우선 인용하라

{{"document_type": {{"primary": "{doc_type}", "secondary": "{doc_secondary}"}},
"company_name": "{company_name}",
"disclosure_title": "{disclosure_title}",
"summary": "【필수 구조 — 아래 9가지를 반드시 모두 포함하여 최소 10문장 이상 작성】\n1) 문서 유형 및 대상 기간 (제N기, 20XX.01.01~12.31)\n2) 회사명 및 사업 개요 (주요 사업 분야)\n3) 매출액, 영업이익, 당기순이익 (당기 절대값 + 전기 대비 증감률)\n4) 자산총계, 부채총계, 자본총계 (당기 값)\n5) 부채비율, 영업이익률 등 핵심 비율 지표\n6) 감사의견 + 핵심감사사항 (감사인이 위험으로 본 영역과 이유)\n7) 현금흐름 요약 (영업활동현금흐름, 기말현금)\n8) 주석 기반 리스크 (유동성위험, 차입한도, 우발부채, 파생상품 등)\n9) 투자 시사점 — 한 줄 판정 (성장성 vs 리스크 종합)\n★ 숫자가 없는 문장은 작성하지 마라. 모든 문장에 숫자를 포함하라.",
"category": "{doc_type}",
"key_points": ["(핵심 사실 5개 이상 — 각 포인트에 구체적 숫자·비율·날짜 필수. 예: '매출액 6조 1,809억원으로 전기 대비 10.2% 증가')"],
"key_audit_matters": ["(감사보고서에 명시된 핵심감사사항을 모두 추출. 각 항목: 감사사항명 + 이유 요약. 없으면 빈 배열 [])"],
"financial_metrics": {{
  "assets_total": "자산총계 (원문 그대로, 없으면 null)",
  "liabilities_total": "부채총계 (원문 그대로, 없으면 null)",
  "equity_total": "자본총계 (원문 그대로, 없으면 null)",
  "revenue": "매출액 (원문 그대로, 없으면 null)",
  "operating_income": "영업이익 (원문 그대로, 없으면 null)",
  "net_income": "당기순이익 (원문 그대로, 없으면 null)",
  "debt_ratio": "부채비율 (계산 가능하면 계산, 없으면 null)",
  "operating_margin": "영업이익률 (계산 가능하면 계산, 없으면 null)",
  "operating_cash_flow": "영업활동현금흐름 (원문 그대로, 없으면 null)",
  "cash_end": "기말 현금및현금성자산 (원문 그대로, 없으면 null)"
}},
"insight_vectors": "전기 대비 주요 변동 사항 + 경영 리스크 + 성장 기회 (문서 근거만)",
"risk_notes": ["(구체적 리스크 요인 — 숫자 포함. 예: '부채비율 450%로 업계 평균 대비 위험 수준')"],
"footnote_risks": ["(주석에서 발견된 숨겨진 리스크: 유동성위험, 우발부채, 차입약정한도, 파생상품, 공정가치평가 관련 불확실성 등. 없으면 빈 배열 [])"],
"evidence": "(문서에서 가장 중요한 핵심 근거 문장 3개 이상을 원문 그대로 인용)"
}}"""


# ═══════════════════════════════════════════════════════
# Phase 2 — 정정신고/유상증자/주요사항 전용 분석 프롬프트
# ═══════════════════════════════════════════════════════

DISCLOSURE_EVENT_PROMPT = """당신은 한국 공시 이벤트 분석 전문 아키텍트입니다.

[역할]
정정신고/유상증자/주요사항보고서에서 공시 이벤트 정보를 추출합니다.
재무제표 숫자(자산총계/매출액/영업이익 등)를 지어내지 마세요. 이 문서는 재무제표가 아닙니다.

[정보 가중치 필터 — 공시 이벤트용]
★★★ 가중치 최상: 정정 전/후 비교 (변경 항목, 수치 변동, 델타 계산)
★★ 가중치 상: 발행 조건 (발행가액, 신주 수, 할인율, 납입일)
★ 가중치 중: 자금 사용 목적, 배정 대상자 정보
✗ 가중치 하 (제거): 법적 면책, 목차, 일반 서식 boilerplate

[델타 계산 지시]
정정 전후 수치가 있으면 반드시 변동분(Δ)과 변동률(%)을 계산하라.
예: 정정 전 발행가액 5,000원 → 정정 후 4,500원 = Δ-500원(-10%)

[투자자 영향도 평가]
각 변경 사항에 대해 투자자 영향도를 평가하라:
상 — 주가/지분에 직접 영향 (발행가액 변동, 신주 수 변동, 희석률)
중 — 간접 영향 (납입일 변경, 자금 용도 변경)
하 — 형식적 변경 (오타 정정, 서식 변경)

[주의] 깨진 OCR은 인용하지 말고 문맥으로 재구성. 회사명 불확실하면 "미확인".

[문서 텍스트]
{document_text}

[출력 규칙]
1. 반드시 아래 JSON만 출력
2. 숫자 추출 시 반드시 단위(원, 백만원 등)를 확인하여 '원(KRW)' 단위 정수로 변환하여 기입하라.
3. ★ 주의: '(단위: 1원)' 등의 레이블을 실제 값으로 오인하여 숫자로 추출하는 오류를 절대 범하지 마라. 공란이거나 '-'인 경우 임의 구상하지 말고 `null` 처리하라.
4. 문서에 없는 정보는 `null`. 정정 전/후가 있으면 key_changes에 반드시 포함
5. summary에 최소 6개 이상 구체적 숫자 포함

{{"document_type": {{"primary": "{doc_type}", "secondary": "{doc_secondary}"}},
"company_name": "{company_name}",
"disclosure_title": "{disclosure_title}",
"initial_filing_date": "최초 제출일 (없으면 null)",
"amendment_date": "정정일 (없으면 null)",
"summary": "【필수 구조 — 아래 6가지를 반드시 모두 포함하여 최소 7문장 이상 작성】\n1) 공시 종류 및 제출 배경 (회사명, 날짜 포함)\n2) 정정 전 핵심 내용 (수치 포함)\n3) 정정 후 변경 내용 (수치 + 변동분Δ + 변동률% 포함)\n4) 발행/증자 조건 (발행가, 신주 수, 할인율 등 구체적 수치)\n5) 자금 사용 목적 및 구체적 배분 금액\n6) 투자자 관점 영향 평가 (상/중/하)\n★ 모든 문장에 숫자를 포함하라.",
"category": "{doc_type}",
"event_type": "정정신고/유상증자/주요사항 등",
"key_points": ["(핵심 사실 5개 이상 — 각 포인트에 구체적 숫자·날짜·비율 필수)"],
"key_changes": [
  {{"field": "변경 항목명", "before": "정정 전 값", "after": "정정 후 값", "delta": "변동분 (Δ)", "delta_pct": "변동률 (%)", "impact": "투자자 영향도 (상/중/하)", "meaning": "변경 의미"}}
],
"offering_terms": {{
  "share_type": "신주 종류 (없으면 null)",
  "new_shares": "신주 수 (없으면 null)",
  "fund_use": "자금조달 목적 (없으면 null)",
  "fund_breakdown": "자금 용도별 배분 금액 (없으면 null)",
  "dilution_rate": "기존 주주 희석률 (계산 가능하면 계산, 없으면 null)",
  "offering_method": "증자 방식 (없으면 null)",
  "issue_price": "발행가액 (없으면 null)",
  "reference_price": "기준주가 (없으면 null)",
  "discount_rate": "할인율 (없으면 null)",
  "payment_date": "납입일 (없으면 null)",
  "listing_date": "상장예정일 (없으면 null)"
}},
"third_party_allotment": {{
  "allottee": "배정 대상자 (없으면 null)",
  "relationship": "관계 (없으면 null)",
  "selection_reason": "선정 경위 (없으면 null)",
  "legal_basis": "법적 근거 (없으면 null)"
}},
"financial_metrics": "해당 없음",
"insight_vectors": "투자자 관점: 변경 사항의 종합 영향 (희석률, 자금 용도, 일정 변경 의미)",
"risk_notes": ["(구체적 리스크 — 숫자 포함. 예: '희석률 23.5%로 기존 주주 가치 훼손 우려')"],
"evidence": "(핵심 근거 문장 3개 이상 원문 그대로 인용)",
"forbidden_financial_metrics": {{
  "assets_total": null,
  "liabilities_total": null,
  "sales": null,
  "operating_income": null,
  "net_income": null
}}
}}"""


# ═══════════════════════════════════════════════════════
# Phase 2 — 일반 공시문서 프롬프트
# ═══════════════════════════════════════════════════════

GENERAL_ANALYSIS_PROMPT = """당신은 한국 DART 공시문서를 완벽하게 분석하는 금융 전문가입니다.

[최우선 규칙 — 숫자를 절대 생략하지 마라]
- 문서에 나오는 모든 주식수, 비율(%), 금액, 날짜를 반드시 summary와 key_points에 포함하라.
- 금액 추출 시 문서의 기준 단위를 모두 '원(KRW)'이나 명시적 단위로 환산하라. 표 상단의 '(단위: 1원)' 등을 실제 값으로 추출하는 추출 오류를 주의하라.
- "변동이 있었다", "매수와 매도를 했다" 같은 추상적 요약은 금지. 구체적 숫자를 반드시 써라.
- 사람 이름, 법인명이 나오면 해당 주체의 주식수와 비율을 반드시 포함하라.
- summary는 최소 10문장 이상 작성하라.

[분석 예시]
입력: "보통주식 증감 25,445주. 종류주식 증감 -8,181주. 삼성생명 503,904,843주(8.51%). 이재용 97,414,196주(1.65%)."
출력:
{{"document_type": {{"primary": "임원·주요주주변동", "secondary": "기타공시"}},
"company_name": "삼성전자주식회사",
"disclosure_title": "최대주주등소유주식변동신고서",
"summary": "삼성전자주식회사의 최대주주 등 소유주식 변동신고서이다. 2026년 3월 13일 대비 3월 20일 기준으로 보통주식 25,445주가 증가하고 종류주식 8,181주가 감소하여 합계 17,264주가 순증하였다. 최대주주 등의 합산 보유 현황은 보통주 1,173,889,361주(19.83%), 종류주 837,208주(0.10%), 합계 1,174,726,569주(17.44%)이다. 삼성생명은 503,904,843주(8.51%)를 보유하고 있으며, 삼성생명(특별계정)은 보통주 3,864,351주(0.07%)와 종류주 173,358주(0.02%)를 보유하고 있다. 삼성물산은 298,818,100주(5.05%), 삼성화재는 88,058,948주(1.49%)를 보유 중이다. 개인 주주 중 이재용은 97,414,196주(1.65%), 홍라희는 87,978,700주(1.49%)를 보유하고 있다. 삼성생명(특별계정)은 2026년 3월 16일부터 20일까지 보통주 장내매수/매도를 반복하였다. 송재혁 이사가 사임하면서 보통주 17,100주가 변동(감소)하였고, 김용관이 이사로 신규 선임되면서 32,158주가 증가하였다. 발행주식 총수는 보통주 5,919,637,922주, 종류주 815,974,664주, 합계 6,735,612,586주이다.",
"category": "임원·주요주주변동",
"key_points": ["보통주 증감 +25,445주, 종류주 증감 -8,181주, 합계 +17,264주", "삼성생명 503,904,843주(8.51%), 삼성물산 298,818,100주(5.05%)", "이재용 97,414,196주(1.65%), 홍라희 87,978,700주(1.49%)", "송재혁 이사 사임(-17,100주), 김용관 이사 선임(+32,158주)", "삼성생명(특별계정) 2026.03.16~03.20 보통주/종류주 장내매매 반복"],
"financial_metrics": "발행주식총수: 보통주 5,919,637,922주 + 종류주 815,974,664주 = 6,735,612,586주. 최대주주등 합계: 1,174,726,569주(17.44%)",
"insight_vectors": "최대주주등의 지분율은 17.44%로 전기와 동일하나, 삼성생명(특별계정)의 단기 장내매매가 활발하며 이사진 변경(송재혁 사임, 김용관 선임)이 있어 지배구조 변화에 주의가 필요하다.",
"risk_notes": ["삼성생명(특별계정)의 빈번한 장내매매로 단기 수급 변동 가능성", "이사진 변경에 따른 경영 방향성 변화 가능성"],
"evidence": "보통주식 25,445주 증가, 종류주식 -8,181주 감소. 송재혁 2026-03-18 임원퇴임(-) 보통주식 17,100주. 김용관 2026-03-18 신규선임(+) 보통주식 32,158주."}}

[실제 문서 — 분석 대상]
{document_text}

[출력 요구사항]
- 위 예시 수준의 상세도로 JSON을 출력하라. 숫자를 생략하면 분석 실패로 간주한다.
- company_name: "{company_name}" (확인 불가 시 "미확인")
- disclosure_title: "{disclosure_title}" (확인 불가 시 "미확인")
- category: "{doc_type}"
- document_type: {{"primary": "{doc_type}", "secondary": "{doc_secondary}"}}
- summary: 최소 10문장. 문서의 모든 주요 숫자(주식수, 비율%, 날짜) 포함. 완성된 한국어 문장형태의 요약글로 작성하며, 내부에 프롬프트 지시어, JSON 키, null 등을 절대 언급하지 말 것.
- key_points: 5개 이상. 각 포인트에 구체적 숫자 포함 필수.
- financial_metrics: 발행주식수, 지분율, 금액 등 모든 재무 수치.
- evidence: 원문의 핵심 근거 문장을 한국어로 번역하여 3개 이상 인용.
- JSON만 출력. 다른 텍스트 절대 금지."""


# ═══════════════════════════════════════════════════════
# SYSTEM_PROMPT — Phase 2 공통 시스템 프롬프트
# ═══════════════════════════════════════════════════════

SYSTEM_PROMPT = """[ROLE] 당신은 한국 금융감독원 DART 전자공시시스템 문서를 분석하는 전문 AI 분석 아키텍트입니다.
당신의 임무는 공시문서를 정밀하게 읽고, 구조화된 JSON으로 분석 결과를 출력하는 것입니다.

[절대 규칙 — 위반 시 분석 실패로 간주]
1. 출력은 반드시 JSON 단독. 인사말/설명/마크다운 절대 금지.
2. 문서에 없는 숫자를 절대 만들지 마라.
3. ★★★ 최우선 규칙: 모든 텍스트는 반드시 한국어(한글)로만 작성하라. ★★★
   - 중국어(汉字/简体/繁体) 문자 사용 절대 금지. 단 한 글자도 허용하지 않는다.
   - 일본어(ひらがな/カタカナ) 문자 사용 절대 금지.
   - 영어는 고유명사나 약어(CEO, PER, ROE 등)에만 허용.
   - 금지 예시: "交換" → "교환", "因此" → "따라서", "保有的是500주" → "보유한 주식은 500주"
   - 이 규칙을 1건이라도 위반하면 전체 분석이 실패로 처리된다.
4. 추출하는 금액은 '원' 단위로 통일하거나 원래 단위를 확실히 포함할 것. 문서의 목차나 표의 '(단위: 1원)' 텍스트를 파싱하여 값을 '1'로 조작하는 환각을 금지.
5. 불확실하거나 빈 값, 대시(-) 등은 임의의 숫자를 지어내지 말고 무조건 `null` 또는 "해당 없음".
6. 깨진 OCR 텍스트(자모 분리, 특수문자 나열)는 인용하지 말고 문맥으로 재구성.
7. company_name이 불확실하면 "미확인", 섹션 제목을 회사명으로 쓰지 마라.
8. summary는 반드시 자연스러운 한국어 문장으로 작성. 띄어쓰기를 정확히.

[노이즈 제거 규칙 — 아래 내용은 요약에서 완전히 제거하라]
- 목차, 페이지 번호, 머리글/바닥글
- 법적 면책 조항 ("본 보고서는 관계 법령에 의하여...")
- 일반적인 IFRS/K-IFRS 회계 정책 설명 (구체적 수치 없는 정책 나열)
- 관계사 단순 목록 나열 (거래 금액 없는 경우)
- 입력 텍스트의 서식 태그, HTML 잔해, 특수문자 나열

[출력 완성도 강제 규칙 — EXAONE 필수 준수]
★ JSON의 모든 키는 빠짐없이 출력해야 한다. 중간에 멈추거나 생략하면 분석 실패.
★ summary는 반드시 9가지 항목(문서유형/회사개요/손익/재무상태/비율/감사/현금흐름/리스크/시사점)을 모두 포함하여 최소 10문장 이상 작성.
★ risk_notes 배열과 evidence 필드는 절대 빈 채로 두지 마라. 문서에서 근거를 찾아 반드시 채워라.
★ key_points는 5개 이상. 각 항목에 구체적 숫자가 없으면 해당 포인트를 작성하지 마라.
★ JSON 닫는 괄호까지 반드시 완성한다. 출력이 잘린 것처럼 끝나면 안 된다.

[수치 밀도 기준 — CRITICAL]
- summary: 최소 8개 이상의 구체적 숫자 포함 필수. 완성된 문장으로 작성하며, 내부에 프롬프트 규칙이나 JSON 구조를 절대 언급하지 말 것.
- key_points: 각 포인트에 최소 1개 이상의 숫자 필수
- 숫자 없는 추상적 문장 ("성장세를 보였다", "안정적이다") 금지 → "매출 15.3% 증가", "부채비율 127%"로 대체

[분석 절차 — Cognitive Engine]
Step 1: 문서 유형 식별 및 카테고리 확정
Step 2: 회사명과 공시 제목 추출
Step 3: 칼만 필터 — 가중치 최상/상/중/하로 정보 분류 후 최상부터 추출
Step 4: 수치 추출 — 당기 절대값 + 전기 대비 변화율 동시 추출
Step 5: 투자 시사점과 리스크 도출 (구체적 수치 근거 포함)
Step 6: ★ JSON 전체 필드 완성 확인 후 출력. 닫는 괄호 누락 금지.

[JSON 작성 시 주의]
- 문자열 값 안에 큰따옴표(")를 쓰지 마라. 작은따옴표(')를 사용.
- 배열은 최소 1개 이상의 항목.
- null은 소문자."""


# RETRY 프롬프트 (기존 유지)
RETRY_PROMPT = """이전 응답이 올바른 JSON 형식이 아니었습니다.
반드시 JSON만 출력하세요. 다른 텍스트는 절대 포함하지 마세요."""


# ═══════════════════════════════════════════════════════
# 재무 키워드 사전 — 지능형 청킹에 사용
# ═══════════════════════════════════════════════════════

FINANCIAL_KEYWORDS = [
    "매출액", "매출", "영업이익", "영업손실", "당기순이익", "당기순손실",
    "자산총계", "부채총계", "자본총계", "자본금",
    "유동자산", "비유동자산", "유동부채", "비유동부채",
    "영업활동", "투자활동", "재무활동", "현금흐름",
    "이익잉여금", "감가상각", "법인세", "주당이익",
    "재무상태표", "손익계산서", "포괄손익계산서", "현금흐름표",
    "자본변동표", "재무제표", "연결재무제표", "별도재무제표",
    "감사보고서", "감사의견", "적정의견",
    "당기", "전기", "전전기", "당반기", "전반기",
    "연결", "별도", "결산", "반기", "분기",
    "백만원", "천원", "억원", "원",
    "사업의 내용", "주요 재무", "배당", "이사회", "주주",
    "위험관리", "신용위험", "시장위험",
    # 정정/유상증자 키워드
    "정정 전", "정정 후", "정정신고", "유상증자", "신주발행",
    "제3자배정", "주요사항보고서", "발행가액", "기준주가",
    "할인율", "납입일", "상장예정일",
]

# 문서유형 분류용 키워드 매핑
DOC_TYPE_KEYWORDS = {
    "정정신고(보고)": ["정정신고", "정정 전", "정정 후", "정정보고", "기재정정"],
    "주요사항보고서": ["주요사항보고서", "주요경영사항", "전환사채", "신주인수권부사채", "CB발행", "BW발행", "교환사채"],
    "유상증자결정": ["유상증자", "신주발행", "제3자배정", "증자결정", "주주배정", "일반공모"],
    "사업보고서": ["사업보고서", "사업의 내용", "임원 및 직원", "이사회 운영", "회사의 개요"],
    "반기보고서": ["반기보고서", "반기검토", "반기재무", "상반기", "하반기"],
    "분기보고서": ["분기보고서", "분기검토", "분기재무", "1분기", "2분기", "3분기"],
    "재무제표": ["재무상태표", "손익계산서", "포괄손익계산서", "현금흐름표", "자본변동표", "연결재무제표"],
    "감사보고서": ["감사보고서", "감사의견", "적정의견", "한정의견", "의견거절", "부적정의견"],
    "주석": ["주석", "재무제표에 대한 주석", "유의적인 회계정책", "금융상품", "우발채무"],
    "대량보유보고서": ["대량보유", "주식등의 대량보유", "5% 보고", "보유비율 변동", "보유목적"],
    "임원·주요주주변동": ["임원변동", "주요주주", "특정증권등 소유", "임원 선임", "사외이사", "대표이사 변경"],
    "자기주식": ["자기주식", "자사주", "자기주식처분", "자기주식취득", "소각"],
    "합병·분할": ["합병", "분할합병", "분할", "영업양수도", "주식의 포괄적 교환", "주식이전"],
    "배당": ["배당", "현금배당", "주식배당", "배당금", "중간배당", "결산배당"],
}


# ═══════════════════════════════════════════════════════
# 회사명 검증 함수 — 다층 방어 체계의 핵심
# ═══════════════════════════════════════════════════════

# 회사명으로 절대 허용하지 않는 패턴
_COMPANY_NAME_BLACKLIST_PATTERNS = [
    re.compile(r'^[\d,\.\s]+$'),                     # 순수 숫자 (4,000,000)
    re.compile(r'^[\d,]+(?:\s*주)?$'),                # 주식수 (4,000,000 주)
    re.compile(r'^[\d,]+(?:\s*원)?$'),                # 금액 (1,234,567 원)
    re.compile(r'^\d{8,14}$'),                        # 접수번호/문서번호
    re.compile(r'^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}'),   # 날짜
    re.compile(r'\d{4}년'),                           # 날짜 (2026년)
    re.compile(r'_rendered|\.pdf|\.txt|doc_id|tmp',   # 시스템 문자열
               re.IGNORECASE),
    re.compile(r'^(주요사항보고서|유상증자결정|사업보고서|감사보고서|'
               r'정정신고|재무제표|현금흐름표|손익계산서|재무상태표|'
               r'기타공시|주석)'),                     # 문서유형명
    re.compile(r'^page_?\d+', re.IGNORECASE),         # 페이지 번호
    re.compile(r'^\d+$'),                             # 순수 숫자
    re.compile(r'대\s*표\s*이\s*사'),                  # 대표이사 오염
    re.compile(r'본\s*점\s*소\s*재\s*지'),             # 주소 오염
    re.compile(r'등\s*기\s*번\s*호'),                  # 등기번호
    re.compile(r'사업자\s*등록'),                       # 사업자등록번호
    re.compile(r'서울시|경기도|부산시|인천시|충청|전라|경상|강원|제주'),  # 지역명
    re.compile(r'\d+[길로]\s*\d+'),                    # 도로명주소 패턴
]

# 법인명에 흔히 포함되는 키워드 (가산점용)
_CORP_SUFFIX_KEYWORDS = [
    "주식회사", "(주)", "㈜", "유한회사", "유한책임회사",
    "코리아", "홀딩스", "전자", "바이오", "미디어",
    "시스템", "테크", "산업", "건설", "엔지니어링",
    "파이낸셜", "증권", "투자", "캐피탈", "보험",
    "에너지", "제약", "화학", "소프트", "네트워크",
    "파트너스", "그룹", "인터내셔널", "글로벌",
    "Corp", "Inc", "Ltd", "Co.",
]


def _validate_company_name(candidate: str) -> str:
    """
    회사명 후보를 검증하여 유효하면 정제된 이름을 반환,
    유효하지 않으면 "미확인"을 반환.

    검증 순서:
    1. None/빈 문자열 체크
    2. 블랙리스트 패턴 매칭 (숫자/금액/날짜/파일명/문서유형)
    3. 숫자 비율 검증 (50% 이상이면 거부)
    4. 최소 한글 1자 또는 영문 2자 이상 포함 필수
    5. 길이 제한 (2~50자)
    """
    if not candidate or not candidate.strip():
        return "미확인"

    name = candidate.strip()

    # 공백/특수문자 정리 — (주), ㈜ 접두사 보존
    name = re.sub(r'\s+', ' ', name)
    name = name.strip('.,;:!?[]{}"\'')

    if not name or name == "미확인" or name == "정보 없음":
        return "미확인"

    # 0. 오염 절단 — "한화에너지 대 표 이 사 : 홍길동..." → "한화에너지"
    for sep_pat in [r'대\s*표\s*이\s*사', r'본\s*점\s*소\s*재\s*지', r'등\s*기\s*번\s*호']:
        m = re.search(sep_pat, name)
        if m:
            before = name[:m.start()].strip().rstrip('·:·')
            if before and len(before) >= 2 and re.search(r'[가-힣a-zA-Z]', before):
                name = before
                logger.debug(f"회사명 오염 절단: '{candidate}' → '{name}'")
            else:
                return "미확인"

    # 1. 블랙리스트 패턴 매칭
    for pattern in _COMPANY_NAME_BLACKLIST_PATTERNS:
        if pattern.search(name):
            logger.debug(f"회사명 거부 (블랙리스트): '{name}' — 패턴: {pattern.pattern}")
            return "미확인"

    # 2. 숫자 비율 검증
    digits = sum(1 for c in name if c.isdigit())
    total = sum(1 for c in name if not c.isspace())
    if total > 0 and (digits / total) > 0.5:
        logger.debug(f"회사명 거부 (숫자 비율 과다): '{name}' — {digits}/{total}")
        return "미확인"

    # 3. 한글 또는 영문 포함 검증
    has_korean = bool(re.search(r'[가-힣]', name))
    has_alpha = bool(re.search(r'[a-zA-Z]', name))
    if not has_korean and not has_alpha:
        logger.debug(f"회사명 거부 (한글/영문 없음): '{name}'")
        return "미확인"

    # 4. 길이 제한 (실제 법인명은 대부분 20자 이내)
    if len(name) < 2 or len(name) > 30:
        logger.debug(f"회사명 거부 (길이): '{name}' — {len(name)}자")
        return "미확인"

    # 5. 콜론(:) 포함 시 거부 (주소/대표이사 오염 패턴: "대표이사:홍길동")
    if ':' in name or '：' in name:
        logger.debug(f"회사명 거부 (콜론 포함): '{name}'")
        return "미확인"

    # 6. 주소 키워드 포함 시 거부
    address_keywords = ['구 ', '동 ', '로 ', '길 ', '번지', '층', '호']
    for kw in address_keywords:
        if kw in name:
            logger.debug(f"회사명 거부 (주소 키워드): '{name}' — '{kw}'")
            return "미확인"

    # 7. 쉼표 포함 숫자열 재검증 ("4,000,000" 같은 케이스)
    cleaned_for_check = name.replace(',', '').replace(' ', '')
    if cleaned_for_check.isdigit():
        logger.debug(f"회사명 거부 (쉼표 제거 후 순수 숫자): '{name}'")
        return "미확인"

    logger.debug(f"회사명 승인: '{name}'")
    return name


class LlmService:
    """
    Ollama LLM 클라이언트 — 해밀토니안 최적화 경로 연산 엔진 v2
    문서유형 분류 → 유형별 전용 분석 → PDF 수준 구조화 출력
    """

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = getattr(
            settings,
            "OLLAMA_ANALYSIS_MODEL",
            getattr(settings, "OLLAMA_MODEL", "dart-qwen-korean:latest"),
        )
        self.timeout = 600.0  # dart-exaone 로컬 처리 여유 시간 확보

    # ═══════════════════════════════════════════════════════
    # Phase 2: 2단계 분석 — 분류 → 전용 추출
    # ═══════════════════════════════════════════════════════

    async def analyze_document(self, document_text: str) -> Dict[str, Any]:
        """
        문서 분석 실행 — 3단계 파이프라인
        0단계: 메타데이터 전처리 (회사명/섹션 확정)
        1단계: 문서유형 분류 (키워드 기반 로컬 + LLM 보조)
        2단계: 유형별 전용 프롬프트로 상세 분석
        """
        if not document_text or len(document_text.strip()) < 10:
            return self._empty_result("분석할 텍스트가 부족합니다.")

        start_time = time.time()

        # ── 0단계: 메타데이터 전처리 (Pre-LLM 확정) ──
        pre_metadata = extract_document_metadata(document_text)
        metadata_block = build_metadata_prompt_block(pre_metadata)

        # ── 0.5단계: Python 구조 추출 (결정적 앵커 데이터) ──
        from services.text_summarizer import (
            extract_financial_metrics as py_extract_metrics,
            extract_context as py_extract_context,
            extract_company_name as py_extract_company,
            classify_document as py_classify,
            clean_text as py_clean_text,
        )
        py_clean = py_clean_text(document_text)
        py_metrics = py_extract_metrics(py_clean)
        py_context = py_extract_context(py_clean)
        py_company = py_extract_company(py_clean, "")
        py_category = py_classify(py_clean)

        # Python 추출 재무데이터를 메타데이터 블록에 주입 (LLM 그라운딩)
        if py_metrics:
            metrics_table = "\n[확정 재무지표 — Python 구조 추출]\n"
            metrics_table += "| 항목 | 수치 | 단위 |\n|---|---|---|\n"
            for name, data in py_metrics.items():
                metrics_table += f"| {name} | {data['raw']} | {data.get('unit', '')} |\n"
            metadata_block += metrics_table

        if py_context:
            ctx_lines = [f"  {k}: {v}" for k, v in py_context.items()]
            metadata_block += "\n[확정 맥락 정보 — Python 구조 추출]\n" + "\n".join(ctx_lines)

        # ── 1단계: 문서유형 분류 (키워드 기반 빠른 분류) ──
        doc_type, doc_secondary, company_name, disclosure_title = \
            self._classify_document_local(document_text)

        # 전처리에서 확정된 회사명이 있으면 우선 사용
        if pre_metadata.company_name:
            company_name = pre_metadata.company_name
        # Python 추출 회사명 fallback
        elif company_name == "미확인" and py_company and py_company != "미확인":
            company_name = py_company

        # Python 추출 카테고리 fallback
        if doc_type == "기타공시" and py_category != "기타공시":
            doc_type = py_category

        # 전처리에서 문서유형 힌트가 있으면 적용
        if pre_metadata.document_type_hint and doc_type == "기타공시":
            doc_type = pre_metadata.document_type_hint

        logger.info(
            f"  ├─ 문서유형 분류 완료 — "
            f"primary: {doc_type}, secondary: {doc_secondary}"
        )

        # ── 앵커 기반 메타데이터 추출 ──
        anchored_meta = metadata_validator.extract_anchored_metadata(document_text)
        # 앵커에서 회사명/공시명이 확인되면 우선 사용
        anchor_company = anchored_meta.get("company_name")
        if anchor_company and anchor_company.is_confirmed:
            company_name = anchor_company.value
        anchor_filing = anchored_meta.get("filing_title")
        if anchor_filing and anchor_filing.is_confirmed:
            disclosure_title = anchor_filing.value

        # LLM으로 보조 분류 (회사명/공시명 보강)
        llm_company_raw = ""
        llm_filing_raw = ""
        if company_name == "미확인" or disclosure_title == "미확인":
            try:
                llm_class = await self._classify_with_llm(document_text[:3000])
                llm_company_raw = llm_class.get("company_name", "")
                llm_filing_raw = llm_class.get("disclosure_title", "")
                if company_name == "미확인" and llm_company_raw:
                    validated = metadata_validator._validate_company_name(llm_company_raw)
                    if validated != "미확인":
                        company_name = validated
                if disclosure_title == "미확인" and llm_filing_raw:
                    validated = metadata_validator._validate_filing_title(llm_filing_raw)
                    if validated != "미확인":
                        disclosure_title = validated
            except Exception as e:
                logger.warning(f"  ├─ LLM 보조 분류 실패 (무시): {e}")

        # ── 2단계: 유형별 전용 프롬프트로 상세 분석 ──
        # 청크 분할 임계치 (14,000자 초과 시 분할 요약)
        CHUNK_THRESHOLD = 14000

        clean_text = self._clean_ocr_noise(document_text)
        text_length = len(clean_text)

        # 적응형 청크 크기: 초장문(50만자+) → 큰 청크로 분할 횟수 감소
        if text_length > 500000:
            CHUNK_SIZE = 20000  # 100만자 → ~50청크 (vs 84)
        elif text_length > 100000:
            CHUNK_SIZE = 16000  # 10만자+ → ~7청크
        else:
            CHUNK_SIZE = 12000  # 기본값

        if text_length > CHUNK_THRESHOLD:
            # ═══ 장문 문서: 청크 분할 요약 파이프라인 ═══
            logger.info(
                f"  ├─ 장문 문서 감지 — {text_length:,}자 > {CHUNK_THRESHOLD:,}자 → "
                f"청크 분할 요약 모드"
            )

            try:
                normalized = await self._analyze_long_document(
                    clean_text, doc_type, doc_secondary,
                    company_name, disclosure_title,
                    metadata_block, pre_metadata, anchored_meta,
                    llm_company_raw, llm_filing_raw,
                    start_time, CHUNK_SIZE,
                )

                # 요약문 post-processing
                from services.text_quality import sanitize_summary_text
                if normalized.get("summary"):
                    normalized["summary"] = sanitize_summary_text(normalized["summary"])

                processing_time = time.time() - start_time
                logger.info(
                    f"✦ LLM 청크 분할 분석 완료 — "
                    f"유형: {doc_type} | 카테고리: {normalized.get('category', 'N/A')} | "
                    f"원본: {text_length:,}자 | 처리: {processing_time:.2f}s"
                )
                return normalized

            except Exception as e:
                logger.warning(f"  ├─ 청크 분할 요약 실패, 단일 청크 폴백: {e}")
                # 실패 시 기존 단일 청크 방식으로 폴백

        # ═══ 일반 문서 (14,000자 이하) 또는 폴백 ═══
        focused_text = self._extract_financial_sections(document_text, max_chars=14000)

        # 메타데이터 블록을 focused_text 앞에 주입
        focused_text_with_meta = f"{metadata_block}\n\n{focused_text}"

        # 프롬프트 선택
        prompt = self._select_prompt(
            doc_type, doc_secondary, company_name, disclosure_title,
            focused_text_with_meta
        )

        try:
            result = await self._call_ollama_with_retry(prompt, max_retries=2)
            processing_time = time.time() - start_time

            parsed = self._robust_parse_json(result)

            normalized = self._normalize_to_legacy(
                parsed, doc_type, doc_secondary,
                company_name, disclosure_title,
                anchored_meta=anchored_meta,
                llm_company_raw=llm_company_raw,
                llm_filing_raw=llm_filing_raw,
            )
            normalized["_processing_time"] = processing_time
            normalized["_model"] = self.model
            normalized["_input_length"] = len(focused_text)
            normalized["_doc_type"] = doc_type
            normalized["_pre_metadata"] = pre_metadata.to_dict()
            normalized["_doc_secondary"] = doc_secondary
            normalized["_py_metrics"] = {k: v.get("display", "") for k, v in py_metrics.items()} if py_metrics else {}
            normalized["_py_context"] = py_context if py_context else {}

            # Python 추출 재무지표로 LLM 결과 보강
            if py_metrics and normalized.get("financial_metrics") in ("해당 없음", "", None):
                fm_parts = [f"{k}: {v['display']}" for k, v in py_metrics.items()]
                normalized["financial_metrics"] = " | ".join(fm_parts)

            # ── 요약문 post-processing — 깨진 OCR 잔해 정제 ──
            from services.text_quality import sanitize_summary_text
            if normalized.get("summary"):
                normalized["summary"] = sanitize_summary_text(normalized["summary"])

            logger.info(
                f"✦ LLM 분석 완료 — "
                f"유형: {doc_type} | 카테고리: {normalized.get('category', 'N/A')} | "
                f"입력: {len(focused_text)}자 | 처리: {processing_time:.2f}s"
            )

            return normalized

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"LLM 분석 실패 ({processing_time:.2f}s): {e}")
            return self._empty_result(f"분석 중 오류: {str(e)}",
                                       processing_time=processing_time)

    # ═══════════════════════════════════════════════════════
    # 1단계: 로컬 키워드 기반 문서유형 분류
    # ═══════════════════════════════════════════════════════

    def _classify_document_local(self, text: str):
        """키워드 매칭으로 빠른 문서유형 분류 (LLM 호출 없이)"""
        text_lower = text[:5000].lower()

        scores = {}
        for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scores[doc_type] = score

        if not scores:
            primary = "기타공시"
            secondary = ""
        else:
            sorted_types = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            primary = sorted_types[0][0]
            secondary = sorted_types[1][0] if len(sorted_types) > 1 else ""

        # 회사명 추출 — 강화된 다중 패턴 + 즉시 검증
        company_name = "미확인"
        company_patterns = [
            # 명시적 필드 라벨 (최우선)
            r'회사명\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
            r'법인명\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
            r'상호\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
            r'상호명\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
            r'발행회사\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
            r'제출인\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
            r'신고인\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
            r'발행인\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
            r'회사의\s*명칭\s*[:\s]\s*(.+?)(?:\s{2,}|\n|$)',
            # 법인 형태 패턴
            r'주식회사\s+(.+?)(?:\s*[\(\[]|\s{2,}|\n|$)',
            r'㈜\s*(.+?)(?:\s{2,}|\n|$)',
            r'\(주\)\s*(.+?)(?:\s{2,}|\n|$)',
        ]
        for pattern in company_patterns:
            match = re.search(pattern, text[:3000])
            if match:
                candidate = match.group(1).strip()[:50]
                validated = _validate_company_name(candidate)
                if validated != "미확인":
                    company_name = validated
                    break

        # 공시명 추출
        disclosure_title = "미확인"
        title_patterns = [
            r'(정정신고서?\s*\(.+?\))',
            r'(주요사항보고서\s*\(.+?\))',
            r'(사업보고서)',
            r'(감사보고서)',
        ]
        for pattern in title_patterns:
            match = re.search(pattern, text[:2000])
            if match:
                disclosure_title = match.group(1).strip()[:100]
                break

        return primary, secondary, company_name, disclosure_title

    async def _classify_with_llm(self, text_head: str) -> Dict[str, str]:
        """LLM으로 보조 분류 (회사명/공시명 추출)"""
        prompt = CLASSIFICATION_PROMPT.format(document_text=text_head[:2000])
        response = await self._call_ollama(prompt)
        return self._robust_parse_json(response)

    # ═══════════════════════════════════════════════════════
    # 2단계: 유형별 프롬프트 선택
    # ═══════════════════════════════════════════════════════

    def _select_prompt(self, doc_type, doc_secondary, company_name,
                       disclosure_title, focused_text) -> str:
        """문서유형에 맞는 전용 프롬프트 선택"""

        context = {
            "document_text": focused_text,
            "doc_type": doc_type,
            "doc_secondary": doc_secondary or "",
            "company_name": company_name,
            "disclosure_title": disclosure_title,
        }

        # 재무제표 / 사업보고서 / 감사보고서 / 반기·분기보고서 / 주석 → 재무 전용 프롬프트
        financial_types = {"재무제표", "사업보고서", "감사보고서", "반기보고서", "분기보고서", "주석"}
        if doc_type in financial_types:
            return FINANCIAL_ANALYSIS_PROMPT.format(**context)

        # 정정신고 / 유상증자 / 주요사항 / 합병·분할 / 자기주식 → 공시 이벤트 프롬프트
        event_types = {"정정신고(보고)", "유상증자결정", "주요사항보고서", "합병·분할", "자기주식"}
        if doc_type in event_types or doc_secondary in event_types:
            return DISCLOSURE_EVENT_PROMPT.format(**context)

        # 대량보유 / 임원변동 / 배당 → 일반 프롬프트 (재무 아님)
        return GENERAL_ANALYSIS_PROMPT.format(**context)

    # ═══════════════════════════════════════════════════════
    # 기존 5필드 호환 매핑
    # ═══════════════════════════════════════════════════════

    def _normalize_to_legacy(self, parsed: Dict, doc_type: str,
                              doc_secondary: str, company_name: str,
                              disclosure_title: str,
                              anchored_meta: Dict = None,
                              llm_company_raw: str = "",
                              llm_filing_raw: str = "") -> Dict[str, Any]:
        """
        새 확장 JSON을 기존 5필드에 호환 매핑.
        raw_response에는 전체 확장 JSON + SafeRenderContext 저장.
        """
        # ── 회사명 최종 검증 (다층 방어 마지막 레이어) ──
        company_name = _validate_company_name(company_name)
        parsed_company = parsed.get("company_name", "")
        if company_name == "미확인" and parsed_company:
            company_name = _validate_company_name(parsed_company)

        # ── SafeRenderContext 생성 ──
        if anchored_meta is None:
            anchored_meta = {}
        safe_ctx = metadata_validator.build_safe_render_context(
            anchored=anchored_meta,
            doc_type=doc_type,
            doc_secondary=doc_secondary,
            category=parsed.get("category", doc_type),
            event_type=parsed.get("event_type", ""),
            llm_company=company_name,
            llm_filing_title=disclosure_title,
        )
        # safe context가 더 신뢰도 높은 회사명을 가지면 사용
        if safe_ctx.safe_company_name != "미확인":
            company_name = safe_ctx.safe_company_name

        # summary
        summary = parsed.get("summary", "")
        if not summary or summary == "파싱 실패":
            summary = f"{company_name} — {disclosure_title}"

        # category — 새 분류 우선, 없으면 기존 사용
        category = doc_type
        if parsed.get("category") and parsed["category"] not in ("기타", "파싱 실패", ""):
            category = parsed["category"]

        # financial_metrics — 비재무 문서는 강제로 "해당 없음"
        financial_types = {"재무제표", "사업보고서", "감사보고서"}
        fm = parsed.get("financial_metrics", "해당 없음")
        if doc_type not in financial_types:
            if isinstance(fm, dict):
                fm = "해당 없음"
            elif isinstance(fm, str) and fm not in ("해당 없음", ""):
                # 비재무 문서인데 재무 메트릭이 있으면 무시
                fm = "해당 없음"
        elif isinstance(fm, dict):
            # 재무제표인 경우 dict → 문자열로 정리
            parts = []
            for k, v in fm.items():
                if v and v != "null" and v != "해당 없음":
                    label = {
                        "assets_total": "자산총계",
                        "liabilities_total": "부채총계",
                        "equity_total": "자본총계",
                        "revenue": "매출액",
                        "operating_income": "영업이익",
                        "net_income": "당기순이익",
                        "debt_ratio": "부채비율",
                        "operating_margin": "영업이익률",
                        "operating_cash_flow": "영업활동현금흐름",
                        "cash_end": "기말현금",
                    }.get(k, k)
                    parts.append(f"{label}: {v}")
            fm = " | ".join(parts) if parts else "해당 없음"

        # insight_vectors
        insight = parsed.get("insight_vectors", "해당 없음")
        risk_notes = parsed.get("risk_notes", [])
        if isinstance(risk_notes, list) and risk_notes:
            insight = " | ".join(risk_notes)

        # evidence — 다양한 형태 지원 + fallback
        evidence_raw = parsed.get("evidence", "")
        evidence_str = ""
        if isinstance(evidence_raw, list) and evidence_raw:
            quotes = []
            for ev in evidence_raw[:3]:
                if isinstance(ev, dict):
                    q = ev.get("quote", "")
                    if q:
                        quotes.append(q)
                elif isinstance(ev, str) and ev:
                    quotes.append(ev)
            evidence_str = " | ".join(quotes)
        elif isinstance(evidence_raw, str) and evidence_raw.strip():
            evidence_str = evidence_raw.strip()

        # fallback: LLM이 evidence를 비워놨으면 key_points 또는 summary에서 추출
        if not evidence_str or evidence_str in ("근거 없음", "해당 없음", "없음"):
            key_pts = parsed.get("key_points", [])
            if isinstance(key_pts, list) and key_pts:
                evidence_str = key_pts[0] if isinstance(key_pts[0], str) else ""
            if not evidence_str and summary:
                # summary 첫 문장 사용
                first_sentence = summary.split(".")[0].strip()
                if first_sentence and len(first_sentence) > 5:
                    evidence_str = first_sentence + "."

        return {
            "summary": summary,
            "category": category,
            "financial_metrics": fm if isinstance(fm, str) else str(fm),
            "insight_vectors": insight if isinstance(insight, str) else str(insight),
            "evidence": evidence_str,
            # 확장 필드 (raw_response에 저장됨)
            "document_type": {"primary": doc_type, "secondary": doc_secondary},
            "company_name": company_name,
            "disclosure_title": disclosure_title,
            "key_points": parsed.get("key_points", []),
            "key_changes": parsed.get("key_changes", []),
            "offering_terms": parsed.get("offering_terms", {}),
            "third_party_allotment": parsed.get("third_party_allotment", {}),
            "risk_notes": risk_notes,
            "key_audit_matters": parsed.get("key_audit_matters", []),
            "footnote_risks": parsed.get("footnote_risks", []),
            "evidence_detailed": evidence_raw,
            "initial_filing_date": parsed.get("initial_filing_date"),
            "amendment_date": parsed.get("amendment_date"),
            "event_type": parsed.get("event_type"),
            "_safe_context": safe_ctx.to_dict(),
        }

    def _empty_result(self, message: str, processing_time: float = 0.0) -> Dict[str, Any]:
        """빈 결과 반환 (LLM 오류 시)"""
        return {
            "summary": message,
            "category": "기타",
            "financial_metrics": "해당 없음",
            "insight_vectors": "해당 없음",
            "evidence": "",
            "document_type": {"primary": "기타공시", "secondary": ""},
            "company_name": "",
            "disclosure_title": "",
            "key_points": [],
            "key_changes": [],
            "offering_terms": {},
            "third_party_allotment": {},
            "risk_notes": [],
            "evidence_detailed": [],
            "_processing_time": processing_time,
            "_model": self.model,
            "_is_error": True,  # LLM 실패 플래그 — documents.py에서 상태 오염 방지용
        }


    # ═══════════════════════════════════════════════════════
    # OCR 노이즈 전처리 — ZIP/XBRL 글자 공백 분리 복원
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _clean_ocr_noise(text: str) -> str:
        """
        ZIP/XBRL 파싱 결과물에서 나타나는 '한 글 자 씩 공 백' 패턴 복원.

        예: 'K B 금 융 지 주' → 'KB금융지주'
            '자 산 총 계' → '자산총계'
        """
        if not text or len(text) < 50:
            return text

        # 라인 단위로 처리 — 종류별 전처리
        cleaned_lines = []
        for line in text.splitlines():
            tokens = line.split(' ')
            if not tokens:
                cleaned_lines.append(line)
                continue

            # 1자 토큰 비율 계산
            single_char_ratio = sum(1 for t in tokens if len(t) == 1) / max(len(tokens), 1)

            if single_char_ratio >= 0.65 and len(tokens) >= 4:
                # 공백 분리 글자열 — 공백 제거 후 의미 단위로 재조합
                merged = line.replace(' ', '')
                # 숫자/단위 사이 공백 복원 (쉼표 그룹)
                merged = re.sub(r'(\d)([가-힣])', r'\1 \2', merged)
                merged = re.sub(r'([가-힣])(\d)', r'\1 \2', merged)
                cleaned_lines.append(merged)
            else:
                cleaned_lines.append(line)

        result = '\n'.join(cleaned_lines)

        # 3개 이상 연속 공백 → 단일 공백
        result = re.sub(r' {3,}', '  ', result)
        # 4개 이상 연속 개행 → 2개로 압축
        result = re.sub(r'\n{4,}', '\n\n', result)

        return result

    # ═══════════════════════════════════════════════════════
    # Ollama 텍스트 모드 호출 (청크 요약용 — JSON 포맷 없음)
    # ═══════════════════════════════════════════════════════

    async def _call_ollama_text(self, prompt: str) -> str:
        """Ollama API 호출 (텍스트 모드 — 청크 요약용, JSON 포맷 강제 없음)"""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": 0.1,
                "seed": 42,
                "num_ctx": 16384,
                "num_predict": 3072,  # EXAONE: 청크 요약 완성도 확보
                "top_p": 0.9,
                "repeat_penalty": 1.05,  # EXAONE: 조기 종료 방지
                "num_gpu": 99,
                "num_batch": 512,
            }
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            raw = data.get("response", "").strip()
            return raw

    # ═══════════════════════════════════════════════════════
    # 장문 문서 청크 분할 요약 엔진 — Ollama 순차 처리
    # ═══════════════════════════════════════════════════════

    async def _analyze_long_document(
        self, clean_text: str,
        doc_type: str, doc_secondary: str,
        company_name: str, disclosure_title: str,
        metadata_block: str, pre_metadata, anchored_meta: dict,
        llm_company_raw: str, llm_filing_raw: str,
        start_time: float, chunk_size: int = 12000,
    ) -> Dict[str, Any]:
        """
        14,000자 초과 장문 문서를 Ollama 순차 분할 요약.

        파이프라인:
          1) 문단 경계 기반 청크 분할
          2) 각 청크를 Ollama 순차 처리 (결정적 출력)
          3) 실패한 청크는 재시도
          4) 부분 요약 통합 → 최종 구조화 분석
        """
        # ── 1단계: 청크 분할 (문단 경계 존중) ──
        chunks = self._split_into_chunks(clean_text, chunk_size)
        total_chunks = len(chunks)
        logger.info(f"  ├─ 텍스트 {len(clean_text):,}자 → {total_chunks}개 청크 분할")

        # ── 2단계: 청크별 요약 (Ollama 순차) ──
        CHUNK_SUMMARY_PROMPT = """당신은 한국 DART 공시문서 전문 분석가입니다.

다음은 '{company_name}' ({disclosure_title}) 문서의 일부입니다.
이 부분의 핵심 내용을 빠짐없이 요약해주세요.

규칙:
1. 재무 수치가 있으면 반드시 포함 (매출액, 영업이익, 자산, 부채 등)
2. 핵심 사업 내용, 변동 사항, 주요 계약 등을 포함
3. 숫자와 비율은 정확하게 기록
4. 200~500자 범위의 한국어 요약문을 작성
5. JSON이 아닌 순수 텍스트로 작성

[문서 파트 {chunk_idx}/{total_chunks}]
{chunk_text}

위 내용의 핵심 요약:"""

        partial_summaries = []
        for i, chunk in enumerate(chunks):
            prompt = CHUNK_SUMMARY_PROMPT.format(
                company_name=company_name,
                disclosure_title=disclosure_title,
                chunk_idx=i + 1,
                total_chunks=total_chunks,
                chunk_text=chunk,
            )
            for attempt in range(2):
                try:
                    partial = await self._call_ollama_text(prompt)
                    if partial:
                        logger.info(
                            f"  ├─ 청크 {i+1}/{total_chunks} 완료 — "
                            f"{len(chunk):,}자 → {len(partial)}자"
                        )
                        partial_summaries.append(f"[파트 {i+1}/{total_chunks}]\n{partial}")
                        break
                except Exception as e:
                    if attempt == 0:
                        logger.warning(f"  ├─ 청크 {i+1}/{total_chunks} 실패, 재시도: {e}")
                    else:
                        logger.error(f"  ├─ 청크 {i+1}/{total_chunks} 최종 실패: {e}")

        if not partial_summaries:
            raise RuntimeError("모든 청크 요약 실패")

        logger.info(
            f"  ├─ 청크 요약 완료: {len(partial_summaries)}/{total_chunks}개 성공"
        )

        # ── 3단계: 부분 요약 통합 → 최종 구조화 분석 ──
        merged_summaries = "\n\n".join(partial_summaries)
        if len(merged_summaries) > 12000:
            merged_summaries = merged_summaries[:12000]

        final_input = f"{metadata_block}\n\n{merged_summaries}"
        prompt = self._select_prompt(
            doc_type, doc_secondary, company_name, disclosure_title,
            final_input
        )

        result = await self._call_ollama_with_retry(prompt, max_retries=2)
        processing_time = time.time() - start_time

        parsed = self._robust_parse_json(result)
        normalized = self._normalize_to_legacy(
            parsed, doc_type, doc_secondary,
            company_name, disclosure_title,
            anchored_meta=anchored_meta,
            llm_company_raw=llm_company_raw,
            llm_filing_raw=llm_filing_raw,
        )
        normalized["_processing_time"] = processing_time
        normalized["_model"] = self.model
        normalized["_input_length"] = len(clean_text)
        normalized["_doc_type"] = doc_type
        normalized["_pre_metadata"] = pre_metadata.to_dict()
        normalized["_doc_secondary"] = doc_secondary
        normalized["_chunk_count"] = total_chunks
        normalized["_chunk_mode"] = True

        return normalized

    def _split_into_chunks(self, text: str, chunk_size: int = 12000) -> list:
        """
        문단 경계를 존중하며 텍스트를 chunk_size 단위로 분할.
        빈 줄(\\n\\n)을 기준으로 문단을 나누고, chunk_size에 맞게 조립.
        """
        paragraphs = re.split(r'\n\s*\n', text)
        chunks = []
        current_chunk = []
        current_length = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_len = len(para)

            # 단일 문단이 chunk_size를 초과하면 강제 분할
            if para_len > chunk_size:
                # 현재 청크가 있으면 먼저 저장
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # 긴 문단을 chunk_size 단위로 자름
                for start in range(0, para_len, chunk_size):
                    chunks.append(para[start:start + chunk_size])
                continue

            # 현재 청크에 추가하면 초과하는 경우 → 새 청크 시작
            if current_length + para_len + 2 > chunk_size and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_length = 0

            current_chunk.append(para)
            current_length += para_len + 2  # "\n\n" 길이

        # 마지막 청크 저장
        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks

    # ═══════════════════════════════════════════════════════
    # 지능형 청킹 — 재무 키워드 기반 핵심 섹션 추출
    # ═══════════════════════════════════════════════════════

    def _extract_financial_sections(self, full_text: str, max_chars: int = 12000) -> str:

        """
        DART 문서 구조 기반 지능형 섹션 분리 + 태깅.

        구조:
          [섹션: 메타 헤더]  — 상단 1000자 (항상 포함, 감사보고서 등 앞단 밀집 문서 대응)
          [섹션: 본문 핵심]  — 키워드 스코어 상위 문단
          [섹션: 재무 데이터] — 표/숫자 밀집 구간
          [섹션: 주석/부록]  — 후순위, 공간 여유 시 포함
        """
        # ── 0단계: OCR 노이즈 전처리 ──
        full_text = self._clean_ocr_noise(full_text)

        if len(full_text) <= max_chars:
            # 짧은 문서는 메타 헤더 태그만 부여
            head = full_text[:1000]
            body = full_text[1000:]
            if body.strip():
                return f"[섹션: 메타 헤더]\n{head}\n\n[섹션: 본문]\n{body}"
            return f"[섹션: 메타 헤더]\n{head}"

        # ── 1단계: 메타 헤더 추출 (1000자 — 감사보고서 앞단 결론 포함) ──
        meta_header = full_text[:1000].strip()
        remaining_budget = max_chars - len(meta_header) - 50

        # ── 2단계: 문단 분리 및 섹션 분류 ──
        paragraphs = re.split(r'\n\s*\n', full_text[1000:])
        if not paragraphs:
            return f"[섹션: 메타 헤더]\n{meta_header}\n\n[섹션: 본문]\n{full_text[1000:max_chars]}"

        # DART 섹션 분류 키워드
        _NOTE_KEYWORDS = ["주석", "유의적인 회계정책", "감사인의", "별첨", "부록"]
        _TABLE_INDICATORS = ["\t", "  ", "|"]

        classified = []  # (idx, section_type, score, text)
        for idx, para in enumerate(paragraphs):
            text = para.strip()
            if len(text) < 5:
                continue

            # OCR 품질 태그가 이미 붙어있으면 보존
            has_quality_tag = "[OCR 품질 낮음" in text or "참고용]" in text

            # 섹션 유형 결정
            section_type = "body"
            score = 0

            # 주석/부록 감지
            if any(kw in text for kw in _NOTE_KEYWORDS):
                section_type = "note"
                score -= 5  # 후순위

            # 표/데이터 구간 감지
            elif any(ind in text for ind in _TABLE_INDICATORS):
                number_matches = re.findall(r'[\d,]+(?:\.\d+)?', text)
                if len(number_matches) >= 3:
                    section_type = "financial"
                    score += 8

            # 핵심 본문 스코어링
            for keyword in FINANCIAL_KEYWORDS:
                if keyword.lower() in text.lower():
                    score += 2

            # 정정 전/후는 최고 우선순위
            if "정정 전" in text or "정정 후" in text:
                score += 20

            # OCR 품질 낮음 태그가 있으면 감점
            if has_quality_tag:
                score -= 10

            classified.append((idx, section_type, score, text))

        if not classified:
            return f"[섹션: 메타 헤더]\n{meta_header}\n\n[섹션: 본문]\n{full_text[500:max_chars]}"

        # ── 3단계: 우선순위별 조립 ──
        # 본문 핵심(body+financial) → 스코어 높은 순
        # 주석(note) → 마지막
        classified.sort(key=lambda x: (-1 if x[1] == "note" else 1, x[2], -x[0]), reverse=True)

        parts = [f"[섹션: 메타 헤더]\n{meta_header}"]
        total = len(meta_header)

        # 현재 섹션 유형 추적 (동일 유형 연속 시 태그 생략)
        current_section = None
        section_labels = {
            "body": "본문 핵심",
            "financial": "재무 데이터",
            "note": "주석/부록",
        }

        for idx, section_type, score, text in classified:
            needed = len(text) + 30
            if total + needed > remaining_budget + len(meta_header):
                continue

            # 섹션 전환 시 태그 삽입
            if section_type != current_section:
                label = section_labels.get(section_type, "본문")
                parts.append(f"\n[섹션: {label}]")
                current_section = section_type

            parts.append(text)
            total += needed

        result = "\n".join(parts)

        logger.info(
            f"  ├─ DART 구조 청킹 완료 — "
            f"원본 {len(full_text)}자 → {len(result)}자 "
            f"(메타 헤더 500자 + 본문 {sum(1 for c in classified if c[1]=='body')}건 "
            f"+ 재무 {sum(1 for c in classified if c[1]=='financial')}건 "
            f"+ 주석 {sum(1 for c in classified if c[1]=='note')}건)"
        )

        return result if result else full_text[:max_chars]

    # ═══════════════════════════════════════════════════════
    # Ollama 호출 + 자동 재시도
    # ═══════════════════════════════════════════════════════

    async def _call_ollama_with_retry(self, prompt: str, max_retries: int = 2) -> str:
        """Ollama API 호출 + JSON 파싱 실패 시 자동 재시도"""
        last_response = ""

        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    response = await self._call_ollama(prompt)
                else:
                    retry_prompt = f"{prompt}\n\n{RETRY_PROMPT}"
                    response = await self._call_ollama(retry_prompt)

                last_response = response

                test_parsed = self._robust_parse_json(response)
                if test_parsed.get("summary") != "파싱 실패":
                    return response

                logger.warning(
                    f"  ├─ LLM 응답 JSON 파싱 실패 (시도 {attempt + 1}/{max_retries}) — "
                    f"응답 앞부분: {response[:100]}..."
                )

            except Exception as e:
                logger.error(f"  ├─ Ollama 호출 실패 (시도 {attempt + 1}/{max_retries}): {e}")
                last_response = ""
                if attempt == max_retries - 1:
                    raise

        return last_response

    async def _call_ollama(self, prompt: str) -> str:
        """Ollama API 호출"""
        url = f"{self.base_url}/api/generate"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "format": "json",
            "keep_alive": "10m",
            "options": {
                "temperature": 0.1,
                "seed": 42,
                "num_ctx": 16384,
                "num_predict": 4096,  # EXAONE: 섹션 완성도를 위해 증가
                "top_p": 0.9,
                "repeat_penalty": 1.05,  # EXAONE: 조기 종료 방지
                "num_gpu": 99,
                "num_batch": 512,
            }
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            raw = data.get("response", "")

            # Template 접두사 제거 ("[한국어 JSON 출력]:" 등)
            prefixes = ["[한국어 JSON 출력]:", "[한국어 JSON 출력]", "[JSON 출력]:"]
            for prefix in prefixes:
                if raw.strip().startswith(prefix):
                    raw = raw.strip()[len(prefix):].strip()
                    break

            # 종목명 정규화 (에스케이하이닉스 → SK하이닉스)
            try:
                from services.stock_name_normalizer import normalize_text_company_names
                raw = normalize_text_company_names(raw)
            except ImportError:
                pass

            return raw

    # ═══════════════════════════════════════════════════════
    # 강화된 JSON 파싱 (5단계 Fallback) — Phase 2 확장
    # ═══════════════════════════════════════════════════════

    def _robust_parse_json(self, response_text: str) -> Dict[str, Any]:
        """
        LLM 응답 JSON 파싱 — 5단계 Fallback 체계
        Phase 2: 확장 필드 지원 + 기존 5필드 호환
        """
        default = {
            "summary": "파싱 실패",
            "category": "기타",
            "financial_metrics": "해당 없음",
            "insight_vectors": "해당 없음",
            "evidence": ""
        }

        if not response_text:
            return default

        # ── 1차: 직접 JSON 파싱 ──
        try:
            result = json.loads(response_text.strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # ── 2차: 코드블록 내 JSON ──
        json_block_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
        match = re.search(json_block_pattern, response_text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # ── 3차: 첫 { ~ 마지막 } ──
        first_brace = response_text.find('{')
        last_brace = response_text.rfind('}')
        if first_brace != -1 and last_brace > first_brace:
            candidate = response_text[first_brace:last_brace + 1]
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # ── 4차: 중괄호 블록 중 "summary" 포함 ──
        brace_pattern = r'\{[^{}]*\}'
        matches = re.findall(brace_pattern, response_text, re.DOTALL)
        for m in matches:
            try:
                result = json.loads(m)
                if isinstance(result, dict) and "summary" in result:
                    return result
            except json.JSONDecodeError:
                continue

        # ── 5차: 정규식 필드별 추출 ──
        extracted = {}
        for field in ["summary", "category", "financial_metrics",
                       "insight_vectors", "evidence", "company_name",
                       "disclosure_title", "event_type"]:
            pattern = rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)"'
            field_match = re.search(pattern, response_text, re.DOTALL)
            if field_match:
                extracted[field] = field_match.group(1) or default.get(field, "")

        if extracted.get("summary"):
            logger.info("  ├─ JSON 5차 필드별 개별 추출 성공")
            return extracted

        logger.warning(f"JSON 파싱 최종 실패 — 원본 응답 앞부분: {response_text[:300]}")
        return default

    async def check_health(self) -> bool:
        """Ollama 서버 상태 확인"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False


# 싱글턴 인스턴스
llm_service = LlmService()
