# -*- coding: utf-8 -*-
"""
qa_narrative_quality.py — narrative_summarizer 결과물 빡쎈 QA/QC

검사 항목:
  1. 길이 분포 + 200-doc 구간별 평균
  2. 보고서 유형별 분포
  3. 빈/매우 짧은 요약
  4. 한국어 조사 미처리
  5. "당사는" 중복 prefix
  6. False positive 이벤트 감지
     - 대형 우량 회사 + 회생절차/해산/부도
     - 합병 + 잘못된 일정 (분할기일/납입일 매칭)
  7. 숫자 sanity (매출 > 100조? 부채비율 음수?)
  8. 빈 자회사 / 빈 첫 문장 fallback
  9. 동일 회사 동일 이벤트 반복 (의심 케이스)
  10. 보고서 유형 vs 이벤트 일치성

출력: 콘솔 + JSON 결과
"""
import sys
import re
import json
from collections import defaultdict, Counter
from pathlib import Path

THIS_DIR = Path(__file__).parent
BACKEND_DIR = THIS_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database import SessionLocal
from sqlalchemy import text


# ═══════════════════════════════════════════════════════════════
# 검사 규칙
# ═══════════════════════════════════════════════════════════════

# 우량 대기업 화이트리스트 — 이들이 회생절차/해산/부도 → false positive 확정
_BLUECHIPS = {
    '삼성전자', '삼성생명', '삼성SDI', '삼성물산', '삼성중공업', '삼성SDS', '삼성전기',
    '삼성화재', '삼성카드', '삼성증권', '삼성바이오로직스', '삼성에스디에스',
    'SK하이닉스', 'SK이노베이션', 'SK텔레콤', 'SK바이오팜', 'SK', 'SK스퀘어',
    '현대자동차', '기아', '현대모비스', '현대제철', '현대건설', '현대글로비스',
    '현대차', '현대중공업', '현대미포조선', 'HD현대', 'HD현대중공업',
    'LG전자', 'LG화학', 'LG에너지솔루션', 'LG디스플레이', 'LG생활건강', 'LG유플러스',
    'LG', 'LG이노텍', 'LG CNS',
    'POSCO홀딩스', '포스코', 'POSCO', '포스코퓨처엠',
    '신한지주', '신한금융지주', 'KB금융', 'KB금융지주', '하나금융지주', '하나금융',
    '우리금융지주', '우리금융', 'BNK금융지주', 'DGB금융지주', 'JB금융지주',
    '메리츠금융지주', '메리츠화재', '메리츠증권',
    '카카오', '카카오뱅크', '카카오페이', '카카오게임즈',
    '네이버', 'NAVER',
    '한화', '한화솔루션', '한화시스템', '한화오션', '한화에어로스페이스', '한화생명',
    'CJ', 'CJ제일제당', 'CJ대한통운', 'CJ ENM', 'CJ프레시웨이',
    '롯데', '롯데지주', '롯데케미칼', '롯데쇼핑', '롯데정밀화학', '롯데웰푸드',
    '아모레퍼시픽', '아모레G',
    'GS', 'GS건설', 'GS리테일', 'GS칼텍스',
    '두산', '두산밥캣', '두산에너빌리티',
    '효성', '효성중공업', '효성티앤씨',
    'KT', 'KT&G', 'KT스카이라이프',
    '한국전력', '한국가스공사', '한국타이어', '한국조선해양',
    '농심', '오뚜기', '대상', '동원',
    'BGF리테일', 'GS25',
    '셀트리온', '유한양행', '녹십자', '대웅제약', '한미약품',
    '미래에셋증권', '키움증권', '한국투자증권', 'NH투자증권', '대신증권',
}

NEGATIVE_EVENT_KEYWORDS = {
    '회생절차', '해산', '부도', '상장폐지', '횡령·배임',
}


def check_summaries(rows):
    """3,135건 요약에 대한 종합 검사."""
    issues = defaultdict(list)

    for r in rows:
        doc_id = r['document_id']
        company = r['company'] or ''
        rt = r['report_type'] or ''
        summary = r['summary'] or ''
        slen = len(summary)

        # 1. 빈/극단적 짧은
        if slen == 0:
            issues['empty'].append(doc_id)
            continue
        if slen < 30:
            issues['too_short_30'].append({
                'doc_id': doc_id, 'company': company, 'len': slen, 'preview': summary
            })
        elif slen < 60:
            issues['too_short_60'].append({
                'doc_id': doc_id, 'company': company, 'len': slen
            })

        # 2. 한국어 조사 미처리
        if re.search(r'은\(는\)|이\(가\)|을\(를\)|와\(과\)', summary):
            issues['josa_unprocessed'].append(doc_id)

        # 3. "당사는" 중복
        if re.search(r'은 당사는|는 당사는', summary):
            issues['dangsa_dup'].append(doc_id)

        # 4. False positive: 우량 대기업 + 부정 이벤트
        # 단, "주권등 상장폐지" (해외 DR/우선주)는 실제 정확하므로 제외
        if company in _BLUECHIPS:
            for neg in NEGATIVE_EVENT_KEYWORDS:
                if neg in summary:
                    # 진짜 해외 DR 부분 상장폐지는 false positive 아님
                    if neg == '상장폐지' and ('주권등' in summary or '해외' in summary or 'DR' in summary):
                        continue
                    issues['fp_negative_event'].append({
                        'doc_id': doc_id, 'company': company, 'negative': neg,
                        'preview': summary[:100]
                    })

        # 5. 보고서 유형과 이벤트 불일치
        # 사업보고서/감사보고서인데 "결정·공시" 표현 (이건 주요사항용)
        if rt in ('사업보고서', '분기보고서', '반기보고서', '감사보고서'):
            if '결정·공시' in summary:
                issues['type_event_mismatch'].append({
                    'doc_id': doc_id, 'rt': rt, 'preview': summary[:100]
                })

        # 6. 잘못된 일정-이벤트 조합
        # 인적분할 + 납입일 (인적분할은 분할기일이지 납입일이 아님)
        if '인적분할' in summary and '납입일' in summary:
            issues['split_with_payment_date'].append({
                'doc_id': doc_id, 'preview': summary[:120]
            })
        # 회생절차/해산 + 납입일 (이런 이벤트는 납입일 없음)
        for neg in ('회생절차', '해산'):
            if neg in summary and ('납입일' in summary or '상장예정일' in summary):
                issues['negative_with_unrelated_date'].append({
                    'doc_id': doc_id, 'event': neg, 'preview': summary[:120]
                })
                break

        # 7. 영문/숫자 잔재
        if re.search(r'\(\s*\)|\s\.\s\.', summary):
            issues['orphan_punct'].append(doc_id)

        # 8. 매출 sanity (>1,000조원? 한국 GDP 초과)
        m = re.search(r'매출(?:액|수익)?\s+([\d,.]+)\s*조원', summary)
        if m:
            try:
                v = float(m.group(1).replace(',', ''))
                if v > 1000:
                    issues['revenue_too_large'].append({
                        'doc_id': doc_id, 'value': f'{v}조원'
                    })
            except Exception:
                pass

        # 9. 부채비율 음수 또는 비정상
        m = re.search(r'부채비율\s+([\d.-]+)\s*%', summary)
        if m:
            try:
                v = float(m.group(1))
                if v < 0:
                    issues['negative_debt_ratio'].append(doc_id)
                elif v > 5000:
                    issues['extreme_debt_ratio'].append({
                        'doc_id': doc_id, 'value': f'{v}%', 'company': company
                    })
            except Exception:
                pass

    return issues


def length_buckets(rows):
    """200-doc 구간별 길이 분포."""
    buckets = defaultdict(list)
    for r in rows:
        bucket = (r['document_id'] // 200) * 200
        buckets[bucket].append(len(r['summary'] or ''))
    return buckets


def report_type_stats(rows):
    """보고서 유형별 길이 통계."""
    stats = defaultdict(list)
    for r in rows:
        stats[r['report_type'] or '미상'].append(len(r['summary'] or ''))
    return stats


def event_detection_stats(rows):
    """주요사항보고서의 이벤트 감지 분포 (최신 키워드 반영)."""
    main_events = Counter()
    # 신규 이벤트 라벨 (DART 표준 제목 + 키워드 추출 결과)
    EVENT_LABELS = [
        # 사채/자본증권 (신규)
        '상각형 조건부자본증권', '조건부자본증권', '신종자본증권',
        '자본으로인정되는채무증권', '자본인정 채무증권',
        '전환사채', '신주인수권부사채', '교환사채',
        # 자기주식 + 신탁계약 (신규)
        '자기주식취득 신탁계약', '자기주식처분 신탁계약',
        '자기주식 취득', '자기주식 처분', '자기주식 소각',
        # 처분/취득 결과보고서 (신규)
        '자기주식처분결과보고서', '자기주식취득결과보고서',
        # 분할/합병
        '회사 분할합병', '인적분할', '물적분할', '회사 분할',
        '분할합병', '합병',
        # 증자/감자
        '유상증자', '무상증자', '감자',
        # 주식교환
        '주식교환', '주식의 포괄적 교환',
        # 영업/자산 양수도
        '영업 양수', '영업 양도', '자산 양수', '자산 양도',
        # 부정 이벤트
        '회생절차 개시', '해산 사유 발생', '해산', '부도', '횡령',
        '주권등 상장폐지', '상장폐지',
        # 기타
        '최대주주 변경', '대규모 단일 공급계약', '단일판매',
        '주요 경영사항',
    ]
    for r in rows:
        if r['report_type'] != '주요사항보고서':
            continue
        s = r['summary'] or ''
        # 가장 긴 라벨부터 매칭 (구체성 우선)
        matched = False
        for ev in sorted(EVENT_LABELS, key=lambda x: -len(x)):
            if ev in s:
                main_events[ev] += 1
                matched = True
                break
        if not matched:
            main_events['(미감지)'] += 1
    return main_events


def evidence_stats(rows):
    """근거 문장 (evidence) 필드 검증."""
    buckets = {
        'A: 빈 (0자)': 0,
        'B: 1-200자': 0,
        'C: 200-500자': 0,
        'D: 500-1000자': 0,
        'E: 1000+자': 0,
    }
    empty_samples = []
    for r in rows:
        ev_text = (r.get('evidence') or '').strip()
        ev_len = len(ev_text)
        if ev_len == 0:
            buckets['A: 빈 (0자)'] += 1
            if len(empty_samples) < 10:
                empty_samples.append({
                    'doc_id': r['document_id'],
                    'company': r['company'],
                    'rt': r['report_type'],
                })
        elif ev_len < 200:
            buckets['B: 1-200자'] += 1
        elif ev_len < 500:
            buckets['C: 200-500자'] += 1
        elif ev_len < 1000:
            buckets['D: 500-1000자'] += 1
        else:
            buckets['E: 1000+자'] += 1
    return buckets, empty_samples


def detect_sentence_cuts(rows):
    """요약/사업개요 문장 중간 잘림 감지.

    종결 부호 ('.', '다.', '!', '?', ':') 없이 끝나는 케이스.
    """
    summary_cuts = []
    overview_cuts = []
    import json as _json
    for r in rows:
        s = (r.get('summary') or '').strip()
        if s and not re.search(r'[.다!?:](?:[가-힣A-Za-z0-9]+\s*)?$', s):
            # 정확히 종결 부호로 끝나지 않음
            if not s.endswith(('.', '다.', '!', '?', ':', '습니다', '입니다')):
                summary_cuts.append({
                    'doc_id': r['document_id'], 'company': r['company'],
                    'tail': s[-30:],
                })
        # raw_response → business_overview 검증
        rr = r.get('raw_response') or ''
        if rr:
            try:
                data = _json.loads(rr)
                if isinstance(data, str):
                    data = _json.loads(data)
                if isinstance(data, dict):
                    bo = (data.get('business_overview') or '').strip()
                    if bo and not bo.endswith(('.', '다.', '!', '?', '습니다', '입니다')):
                        overview_cuts.append({
                            'doc_id': r['document_id'], 'company': r['company'],
                            'len': len(bo), 'tail': bo[-40:],
                        })
            except (ValueError, TypeError):
                pass
    return summary_cuts, overview_cuts


def main():
    db = SessionLocal()
    rows_raw = db.execute(text('''
        SELECT ar.document_id, ar.summary, ar.evidence, ar.raw_response,
               dm.company_name_norm AS company, dm.report_type
          FROM analysis_results ar
          LEFT JOIN document_metadata dm ON dm.document_id = ar.document_id
         WHERE ar.model_name = 'code_only_v1'
         ORDER BY ar.document_id
    ''')).fetchall()
    rows = [dict(document_id=r[0], summary=r[1], evidence=r[2], raw_response=r[3],
                 company=r[4], report_type=r[5]) for r in rows_raw]
    db.close()

    print(f'>>> 총 검사 대상: {len(rows)}건')
    print()

    # 1. 길이 분포
    print('=' * 70)
    print('1. 200-doc 구간별 길이 (배치 진행 추이 확인)')
    print('=' * 70)
    buckets = length_buckets(rows)
    for b in sorted(buckets):
        lens = buckets[b]
        avg = sum(lens) / len(lens)
        bar = '█' * int(avg / 10)
        warn = ' ⚠️ 짧음!' if avg < 100 else ''
        print(f'  {b:4}-{b+199:4}: cnt={len(lens):4} | avg={avg:5.0f}자 {bar}{warn}')
    print()

    # 2. 보고서 유형별
    print('=' * 70)
    print('2. 보고서 유형별 길이')
    print('=' * 70)
    rt_stats = report_type_stats(rows)
    for rt, lens in sorted(rt_stats.items(), key=lambda x: -len(x[1])):
        avg = sum(lens) / len(lens)
        warn = ' ⚠️ 짧음!' if avg < 100 else ''
        print(f'  {rt:15}: {len(lens):4}건 | avg={avg:5.0f}자{warn}')
    print()

    # 3. 주요사항보고서 이벤트 감지
    print('=' * 70)
    print('3. 주요사항보고서 이벤트 감지 분포')
    print('=' * 70)
    events = event_detection_stats(rows)
    for ev, cnt in events.most_common():
        print(f'  {ev:20}: {cnt}건')
    print()

    # 4. 결함 검사
    print('=' * 70)
    print('4. 결함 검사 (요약 품질)')
    print('=' * 70)
    issues = check_summaries(rows)

    print(f'  ❌ 빈 요약: {len(issues["empty"])}건')
    print(f'  ❌ 30자 미만: {len(issues["too_short_30"])}건')
    print(f'  ⚠️  60자 미만: {len(issues["too_short_60"])}건')
    print(f'  ❌ 한국어 조사 미처리: {len(issues["josa_unprocessed"])}건')
    print(f'  ❌ "당사는" 중복: {len(issues["dangsa_dup"])}건')
    print(f'  🚨 우량 대기업 + 부정 이벤트 (false positive): {len(issues["fp_negative_event"])}건')
    print(f'  ❌ 보고서 유형 vs 이벤트 불일치: {len(issues["type_event_mismatch"])}건')
    print(f'  ❌ 인적분할 + 납입일 (잘못된 조합): {len(issues["split_with_payment_date"])}건')
    print(f'  ❌ 회생/해산 + 납입일 (잘못된 조합): {len(issues["negative_with_unrelated_date"])}건')
    print(f'  ⚠️  매출 1,000조 초과: {len(issues["revenue_too_large"])}건')
    print(f'  ⚠️  부채비율 5,000% 초과: {len(issues["extreme_debt_ratio"])}건')
    print()

    # 5. 우량 대기업 false positive 상세
    if issues['fp_negative_event']:
        print('=' * 70)
        print('5. 🚨 우량 대기업 false positive 상세 (최대 15건)')
        print('=' * 70)
        for i, item in enumerate(issues['fp_negative_event'][:15]):
            print(f"  doc={item['doc_id']:4} | {item['company']:15} | {item['negative']}")
            print(f"    > {item['preview']}")
        print()

    # 6. 30자 미만 샘플
    if issues['too_short_30']:
        print('=' * 70)
        print(f'6. ❌ 30자 미만 요약 샘플 (총 {len(issues["too_short_30"])}건, 최대 10건)')
        print('=' * 70)
        for item in issues['too_short_30'][:10]:
            print(f"  doc={item['doc_id']:4} | {item['company']:15} | {item['len']:2}자 | {item['preview']}")
        print()

    # 7. 근거 문장 (evidence) 분포
    print('=' * 70)
    print('7. 📋 근거 문장 (evidence) 필드 분포')
    print('=' * 70)
    ev_buckets, ev_empty = evidence_stats(rows)
    total_with_evidence = sum(v for k, v in ev_buckets.items() if 'A:' not in k)
    for k, v in ev_buckets.items():
        warn = ' ❌' if 'A:' in k and v > 0 else ''
        print(f'  {k}: {v}건{warn}')
    print(f'  → 근거 보유율: {total_with_evidence}/{len(rows)} ({total_with_evidence*100//len(rows)}%)')
    if ev_empty:
        print()
        print(f'  빈 evidence 샘플 ({len(ev_empty)}건 중 최대 10건):')
        for item in ev_empty[:10]:
            print(f"    doc={item['doc_id']:4} | {item['rt']:12} | {item['company']}")
    print()

    # 8. 문장 중간 잘림 감지
    print('=' * 70)
    print('8. ✂️  문장 중간 잘림 감지 (요약 + 사업개요)')
    print('=' * 70)
    summary_cuts, overview_cuts = detect_sentence_cuts(rows)
    print(f'  요약 문장 잘림: {len(summary_cuts)}건')
    if summary_cuts:
        for item in summary_cuts[:5]:
            print(f"    doc={item['doc_id']:4} | {item['company']:15} | ...{item['tail']}")
    print(f'  사업개요 문장 잘림: {len(overview_cuts)}건')
    if overview_cuts:
        for item in overview_cuts[:5]:
            print(f"    doc={item['doc_id']:4} | {item['company']:15} | {item['len']}자 | ...{item['tail']}")
    print()

    # 9. 결과 JSON 저장
    out_path = THIS_DIR / 'qa_narrative_report.json'
    summary_dict = {
        'total': len(rows),
        'avg_summary_len': sum(len(r['summary'] or '') for r in rows) / max(len(rows), 1),
        'avg_evidence_len': sum(len((r.get('evidence') or '')) for r in rows) / max(len(rows), 1),
        'issue_counts': {k: len(v) for k, v in issues.items()},
        'evidence_buckets': ev_buckets,
        'evidence_coverage_pct': total_with_evidence * 100 // len(rows),
        'sentence_cuts': {
            'summary': len(summary_cuts),
            'overview': len(overview_cuts),
        },
        'fp_negative_event': issues['fp_negative_event'][:50],
        'too_short_30_samples': issues['too_short_30'][:50],
        'overview_cut_samples': overview_cuts[:30],
        'summary_cut_samples': summary_cuts[:30],
    }
    out_path.write_text(json.dumps(summary_dict, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'>>> 상세 JSON 저장: {out_path}')


if __name__ == '__main__':
    main()
