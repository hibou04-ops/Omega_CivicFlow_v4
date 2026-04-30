"""
═══════════════════════════════════════════════════════
Omega CivicFlow — 요약 PDF 심층 무결성 감사 (Deep PDF Audit)
═══════════════════════════════════════════════════════

실행: cd backend && python -m tests.deep_pdf_audit

검사 항목:
  1. 중국어/일본어 한자 잔존 (개별 문자 단위 탐지)
  2. 히라가나/카타카나 잔존
  3. 한국어 띄어쓰기 결함 (종결어미 뒤 붙음, 구두점 뒤 공백 등)
  4. 뜬금포 영어 표현 (맥락 없는 영어 문장/단어)
  5. 중국어 구두점 잔존 (，。、等)
  6. 깨진 한글 자모 잔존 (ㄱ-ㅎ, ㅏ-ㅣ 연속)
  7. LLM 지시문 누출 (Instruction leakage)
  8. JSON 잔재 노출
"""

import sqlite3, json, sys, re, os
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB = str(BACKEND_DIR / "omega_civicflow.db")


# ═══════════════════════════════════════════════════════
# 탐지 엔진
# ═══════════════════════════════════════════════════════

def find_chinese_chars(text: str) -> list:
    """중국어/일본어 한자(CJK Unified Ideographs) 개별 문자 위치 탐지"""
    if not text:
        return []
    results = []
    for i, c in enumerate(text):
        if '\u4e00' <= c <= '\u9fff':
            # 전후 문맥 추출
            start = max(0, i - 10)
            end = min(len(text), i + 11)
            context = text[start:end].replace('\n', ' ')
            results.append({
                "char": c,
                "pos": i,
                "context": f"...{context}...",
            })
    return results


def find_japanese_kana(text: str) -> list:
    """히라가나/카타카나 잔존 탐지"""
    if not text:
        return []
    results = []
    # 히라가나: 3040-309F, 카타카나: 30A0-30FF
    for i, c in enumerate(text):
        if ('\u3040' <= c <= '\u309f') or ('\u30a0' <= c <= '\u30ff'):
            start = max(0, i - 8)
            end = min(len(text), i + 9)
            context = text[start:end].replace('\n', ' ')
            results.append({"char": c, "pos": i, "context": f"...{context}..."})
    return results


def find_chinese_punctuation(text: str) -> list:
    """중국어/전각 구두점 잔존 탐지"""
    if not text:
        return []
    CN_PUNCT = {'，', '。', '、', '；', '：', '（', '）', '「', '」',
                '\u201c', '\u201d', '！', '？', '【', '】'}
    results = []
    for i, c in enumerate(text):
        if c in CN_PUNCT:
            start = max(0, i - 8)
            end = min(len(text), i + 9)
            context = text[start:end].replace('\n', ' ')
            results.append({"char": c, "pos": i, "context": f"...{context}..."})
    return results


def find_spacing_issues(text: str) -> list:
    """한국어 띄어쓰기 결함 탐지"""
    if not text:
        return []
    issues = []

    # 1. 종결어미 뒤 한글이 바로 붙은 경우 (습니다회사, 합니다또한 등)
    endings = ['습니다', '됩니다', '있습니다', '없습니다',
               '합니다', '입니다', '였습니다', '었습니다', '겠습니다']
    for ending in endings:
        for m in re.finditer(rf'{ending}([가-힣])', text):
            ctx_start = max(0, m.start() - 5)
            ctx_end = min(len(text), m.end() + 5)
            issues.append({
                "type": "종결어미_뒤_붙음",
                "match": m.group(),
                "context": text[ctx_start:ctx_end],
            })

    # 2. 마침표/쉼표 뒤에 공백 없이 한글이 바로 오는 경우
    for m in re.finditer(r'[.]\s*([가-힣A-Za-z])', text):
        # 마침표 바로 뒤에 공백이 없는 경우만
        actual = text[m.start():m.start()+2]
        if len(actual) >= 2 and actual[1] != ' ':
            ctx_start = max(0, m.start() - 5)
            ctx_end = min(len(text), m.end() + 5)
            issues.append({
                "type": "마침표_공백없음",
                "match": actual,
                "context": text[ctx_start:ctx_end],
            })

    # 3. 깨진 종결어미 (OCR 아티팩트: "습니 다", "합니 다")
    broken = [
        r'습니\s+다', r'됩니\s+다', r'합니\s+다', r'입니\s+다',
        r'있\s+습니다', r'없\s+습니다', r'했\s+습니다',
    ]
    for pat in broken:
        for m in re.finditer(pat, text):
            ctx_start = max(0, m.start() - 5)
            ctx_end = min(len(text), m.end() + 5)
            issues.append({
                "type": "깨진_종결어미",
                "match": m.group(),
                "context": text[ctx_start:ctx_end],
            })

    # 4. 접속사 앞뒤 공백 없음 (한글및한글, 한글또는한글)
    for conn in ['및', '또는', '그리고', '그러나', '따라서', '또한']:
        for m in re.finditer(rf'([가-힣]){conn}([가-힣])', text):
            ctx_start = max(0, m.start() - 3)
            ctx_end = min(len(text), m.end() + 3)
            issues.append({
                "type": "접속사_공백없음",
                "match": m.group(),
                "context": text[ctx_start:ctx_end],
            })

    return issues


def find_random_english(text: str) -> list:
    """맥락 없는 영어 표현 탐지 (허용 목록 제외)"""
    if not text:
        return []

    # 허용되는 영어 표현들
    ALLOWED_EN = {
        # 재무 약어
        'PER', 'PBR', 'ROE', 'ROA', 'EPS', 'BPS', 'EBITDA', 'EV',
        'GDP', 'CPI', 'IPO', 'M&A', 'IR', 'ESG', 'ETF', 'SPAC',
        'KRW', 'USD', 'EUR', 'JPY', 'CNY',
        # IT/기술 약어
        'AI', 'IT', 'IoT', 'SaaS', 'API', 'CEO', 'CFO', 'CTO',
        'DART', 'NAVER', 'KB', 'SK', 'LG', 'KT', 'GS', 'CJ',
        'SNT', 'HL', 'DB', 'KDB', 'NH', 'IBK', 'JB',
        # 보고서 섹션명 (PDF 생성기에서 사용)
        'Section', 'Executive', 'Summary',
        # 기타 허용
        'OK', 'vs', 'N/A', 'null', 'None',
        'PDF', 'OCR', 'LLM', 'JSON',
        'p', 'P', 'DART',
        # 회사명에서 흔히 나오는 것
        'Inc', 'Corp', 'Co', 'Ltd', 'Holdings',
    }

    issues = []

    # 영어 단어/문장 탐지 (3글자 이상 연속 영어)
    for m in re.finditer(r'[A-Za-z]{3,}(?:\s+[A-Za-z]{2,})*', text):
        word = m.group().strip()
        # 허용 목록 체크
        words = word.split()
        is_allowed = all(w.upper() in {a.upper() for a in ALLOWED_EN} for w in words)
        if is_allowed:
            continue

        # 단일 단어가 허용 목록에 있으면 skip
        if word.upper() in {a.upper() for a in ALLOWED_EN}:
            continue

        # 특수 패턴 예외: 회사명 일부 (영문 이름)
        # "에이디에프" 같은 음역은 한글이므로 무관
        # 영어 전문용어처럼 보이는 것 (파일명, URL 등)
        if re.match(r'^(http|www|\.com|\.kr|zip|pdf|doc)', word, re.I):
            continue

        # LLM 지시문 영어 (높은 심각도)
        is_instruction = bool(re.search(
            r'(analyze|extract|generate|output|format|provide|document|'
            r'following|based|response|template|instruction|please|'
            r'translate|convert|return|input|JSON|markdown)',
            word, re.I
        ))

        ctx_start = max(0, m.start() - 10)
        ctx_end = min(len(text), m.end() + 10)
        issues.append({
            "type": "LLM_지시문_영어" if is_instruction else "뜬금포_영어",
            "match": word,
            "context": text[ctx_start:ctx_end],
            "severity": "HIGH" if is_instruction else "MEDIUM",
        })

    return issues


def find_broken_jamo(text: str) -> list:
    """깨진 한글 자모 (ㄱ-ㅎ, ㅏ-ㅣ) 연속 잔존 탐지"""
    if not text:
        return []
    issues = []
    for m in re.finditer(r'[\u3131-\u318E]{2,}', text):
        ctx_start = max(0, m.start() - 5)
        ctx_end = min(len(text), m.end() + 5)
        issues.append({
            "type": "깨진_자모",
            "match": m.group(),
            "context": text[ctx_start:ctx_end],
        })
    return issues


def find_instruction_leakage(text: str) -> list:
    """LLM 지시문 누출 탐지"""
    if not text:
        return []
    LEAK_PATTERNS = [
        r'JSON\s*형식으로\s*(구성|출력|변환|생성)',
        r'템플릿을?\s*기반으로',
        r'다음은\s*문서\s*내용을?\s*기반으로\s*생성된',
        r'귀하의\s*요구\s*사항',
        r'아래[는와]\s*(요약|분석|결과)',
        r'요청하신\s*(대로|바와)',
        r'제공된\s*(문서|정보|데이터)를?\s*(분석|처리)',
        r'추출하여\s*JSON',
        r'```json',
        r'```',
        r'I will now',
        r'I\'ll analyze',
        r'Here is the',
        r'Based on the',
        r'Let me analyze',
        r'The document',
    ]
    issues = []
    for pat in LEAK_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx_start = max(0, m.start() - 10)
            ctx_end = min(len(text), m.end() + 10)
            issues.append({
                "type": "지시문_누출",
                "match": m.group(),
                "context": text[ctx_start:ctx_end],
            })
    return issues


# ═══════════════════════════════════════════════════════
# 메인 감사 엔진
# ═══════════════════════════════════════════════════════

def extract_all_text_fields(raw: dict) -> dict:
    """raw_response에서 모든 텍스트 필드를 추출"""
    fields = {}

    # 직접 문자열 필드
    for key in ['summary', 'company_name', 'category', 'disclosure_title',
                'event_type', 'document_type']:
        val = raw.get(key)
        if isinstance(val, str):
            fields[f"raw.{key}"] = val
        elif isinstance(val, dict):
            for sub_k, sub_v in val.items():
                if isinstance(sub_v, str):
                    fields[f"raw.{key}.{sub_k}"] = sub_v

    # key_points
    kp = raw.get('key_points', [])
    if isinstance(kp, list):
        for i, pt in enumerate(kp):
            if isinstance(pt, str):
                fields[f"raw.key_points[{i}]"] = pt

    # evidence
    ev = raw.get('evidence', [])
    if isinstance(ev, str):
        fields["raw.evidence"] = ev
    elif isinstance(ev, list):
        for i, item in enumerate(ev):
            if isinstance(item, str):
                fields[f"raw.evidence[{i}]"] = item
            elif isinstance(item, dict):
                for sub_k in ['quote', 'why_it_matters']:
                    sv = item.get(sub_k, '')
                    if isinstance(sv, str) and sv:
                        fields[f"raw.evidence[{i}].{sub_k}"] = sv

    # evidence_detailed
    evd = raw.get('evidence_detailed', [])
    if isinstance(evd, list):
        for i, item in enumerate(evd):
            if isinstance(item, dict):
                for sub_k in ['quote', 'why_it_matters']:
                    sv = item.get(sub_k, '')
                    if isinstance(sv, str) and sv:
                        fields[f"raw.evidence_detailed[{i}].{sub_k}"] = sv

    # risk_notes
    rn = raw.get('risk_notes', [])
    if isinstance(rn, list):
        for i, note in enumerate(rn):
            if isinstance(note, str):
                fields[f"raw.risk_notes[{i}]"] = note

    # key_changes
    kc = raw.get('key_changes', [])
    if isinstance(kc, list):
        for i, ch in enumerate(kc):
            if isinstance(ch, dict):
                for sub_k in ['field', 'before', 'after', 'meaning']:
                    sv = ch.get(sub_k, '')
                    if isinstance(sv, str) and sv:
                        fields[f"raw.key_changes[{i}].{sub_k}"] = sv

    # _safe_context
    sc = raw.get('_safe_context', {})
    if isinstance(sc, dict):
        for k, v in sc.items():
            if isinstance(v, str):
                fields[f"raw._safe_context.{k}"] = v

    # offering_terms
    ot = raw.get('offering_terms', {})
    if isinstance(ot, dict):
        for k, v in ot.items():
            if isinstance(v, str):
                fields[f"raw.offering_terms.{k}"] = v

    # financial_metrics (문자열인 경우)
    fm = raw.get('financial_metrics', '')
    if isinstance(fm, str):
        fields["raw.financial_metrics"] = fm
    elif isinstance(fm, dict):
        for k, v in fm.items():
            if isinstance(v, str):
                fields[f"raw.financial_metrics.{k}"] = v

    return fields


def run_deep_audit():
    """전체 분석 결과에 대한 심층 무결성 감사"""
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT ar.id, ar.document_id, ar.summary, ar.category,
               ar.evidence, ar.raw_response, d.filename
        FROM analysis_results ar
        JOIN documents d ON d.id = ar.document_id
        WHERE d.status = 'analyzed'
        ORDER BY d.id
    """)
    rows = cur.fetchall()

    print()
    print("═" * 60)
    print("  Ω  OMEGA CIVICFLOW — 요약 PDF 심층 무결성 감사")
    print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  대상: {len(rows)}건 분석 결과")
    print("═" * 60)

    # 통계
    stats = Counter()
    doc_issues = defaultdict(list)  # doc_id → [issues]
    field_issue_map = defaultdict(Counter)  # field_name → issue_type → count
    sample_issues = defaultdict(list)  # issue_type → [(doc_id, sample)]

    for ar_id, doc_id, summary, category, evidence, raw_resp, filename in rows:
        # raw_response 파싱
        raw = {}
        if raw_resp:
            try:
                decoded = json.loads(raw_resp) if isinstance(raw_resp, str) else raw_resp
                if isinstance(decoded, str):
                    decoded = json.loads(decoded)
                if isinstance(decoded, dict):
                    raw = decoded
            except:
                stats["json_parse_fail"] += 1

        # 모든 텍스트 필드 수집
        text_fields = extract_all_text_fields(raw)

        # DB 직접 필드 추가
        if summary:
            text_fields["db.summary"] = summary
        if category:
            text_fields["db.category"] = category
        if evidence:
            text_fields["db.evidence"] = evidence

        # 각 필드에 대해 모든 검사 실행
        doc_total = 0
        for field_name, text in text_fields.items():
            if not text or len(text) < 2:
                continue

            # 1. 중국어 한자
            cn = find_chinese_chars(text)
            if cn:
                count = len(cn)
                stats["chinese_chars"] += count
                doc_issues[doc_id].append(("중국어한자", field_name, count, cn[:3]))
                field_issue_map[field_name]["중국어한자"] += count
                if len(sample_issues["중국어한자"]) < 10:
                    sample_issues["중국어한자"].append((doc_id, filename, field_name, cn[:3]))
                doc_total += count

            # 2. 일본어 가나
            jp = find_japanese_kana(text)
            if jp:
                count = len(jp)
                stats["japanese_kana"] += count
                doc_issues[doc_id].append(("일본어가나", field_name, count, jp[:3]))
                field_issue_map[field_name]["일본어가나"] += count
                if len(sample_issues["일본어가나"]) < 10:
                    sample_issues["일본어가나"].append((doc_id, filename, field_name, jp[:3]))
                doc_total += count

            # 3. 중국어 구두점
            cp = find_chinese_punctuation(text)
            if cp:
                count = len(cp)
                stats["chinese_punct"] += count
                doc_issues[doc_id].append(("중국어구두점", field_name, count, cp[:3]))
                field_issue_map[field_name]["중국어구두점"] += count
                if len(sample_issues["중국어구두점"]) < 5:
                    sample_issues["중국어구두점"].append((doc_id, filename, field_name, cp[:3]))
                doc_total += count

            # 4. 띄어쓰기 결함
            sp = find_spacing_issues(text)
            if sp:
                count = len(sp)
                stats["spacing_issues"] += count
                doc_issues[doc_id].append(("띄어쓰기결함", field_name, count, sp[:3]))
                field_issue_map[field_name]["띄어쓰기결함"] += count
                if len(sample_issues["띄어쓰기결함"]) < 10:
                    sample_issues["띄어쓰기결함"].append((doc_id, filename, field_name, sp[:3]))
                doc_total += count

            # 5. 뜬금포 영어
            en = find_random_english(text)
            if en:
                count = len(en)
                stats["random_english"] += count
                doc_issues[doc_id].append(("뜬금포영어", field_name, count, en[:3]))
                field_issue_map[field_name]["뜬금포영어"] += count
                if len(sample_issues["뜬금포영어"]) < 10:
                    sample_issues["뜬금포영어"].append((doc_id, filename, field_name, en[:3]))
                doc_total += count

            # 6. 깨진 자모
            jm = find_broken_jamo(text)
            if jm:
                count = len(jm)
                stats["broken_jamo"] += count
                doc_issues[doc_id].append(("깨진자모", field_name, count, jm[:3]))
                field_issue_map[field_name]["깨진자모"] += count
                if len(sample_issues["깨진자모"]) < 5:
                    sample_issues["깨진자모"].append((doc_id, filename, field_name, jm[:3]))
                doc_total += count

            # 7. 지시문 누출
            il = find_instruction_leakage(text)
            if il:
                count = len(il)
                stats["instruction_leak"] += count
                doc_issues[doc_id].append(("지시문누출", field_name, count, il[:3]))
                field_issue_map[field_name]["지시문누출"] += count
                if len(sample_issues["지시문누출"]) < 5:
                    sample_issues["지시문누출"].append((doc_id, filename, field_name, il[:3]))
                doc_total += count

        if doc_total > 0:
            stats["affected_docs"] += 1

    conn.close()

    # ═══ 결과 출력 ═══

    total_docs = len(rows)
    affected = stats["affected_docs"]
    clean = total_docs - affected

    print(f"\n{'─' * 60}")
    print(f"  📊 전체 현황")
    print(f"{'─' * 60}")
    print(f"  총 문서:     {total_docs}건")
    print(f"  이슈 문서:   {affected}건 ({affected*100//max(total_docs,1)}%)")
    print(f"  클린 문서:   {clean}건 ({clean*100//max(total_docs,1)}%)")

    print(f"\n{'─' * 60}")
    print(f"  🔍 이슈 유형별 집계")
    print(f"{'─' * 60}")

    issue_labels = {
        "chinese_chars": ("🇨🇳 중국어 한자", "HIGH"),
        "japanese_kana": ("🇯🇵 일본어 가나", "HIGH"),
        "chinese_punct": ("⁉️  중국어 구두점", "MEDIUM"),
        "spacing_issues": ("📏 띄어쓰기 결함", "MEDIUM"),
        "random_english": ("🔤 뜬금포 영어", "MEDIUM"),
        "broken_jamo": ("💔 깨진 자모", "LOW"),
        "instruction_leak": ("⚠️  지시문 누출", "HIGH"),
        "json_parse_fail": ("🔧 JSON 파싱 실패", "HIGH"),
    }

    for key, (label, severity) in issue_labels.items():
        count = stats.get(key, 0)
        if count > 0:
            print(f"  {label:20s} : {count:>6,}건  [{severity}]")
        else:
            print(f"  {label:20s} : {count:>6,}건  ✅ 클린")

    # ═══ 필드별 이슈 분포 ═══
    print(f"\n{'─' * 60}")
    print(f"  📋 필드별 이슈 분포 (상위 15개)")
    print(f"{'─' * 60}")

    field_totals = {}
    for field, issues_counter in field_issue_map.items():
        field_totals[field] = sum(issues_counter.values())

    for field, total in sorted(field_totals.items(), key=lambda x: -x[1])[:15]:
        detail = ", ".join(f"{k}:{v}" for k, v in field_issue_map[field].most_common(3))
        print(f"  {field:40s}  {total:>4,}건  ({detail})")

    # ═══ 상세 샘플 ═══
    print(f"\n{'─' * 60}")
    print(f"  🔬 이슈별 샘플 (각 최대 5건)")
    print(f"{'─' * 60}")

    sample_labels = {
        "중국어한자": "🇨🇳 중국어 한자 잔존",
        "일본어가나": "🇯🇵 일본어 가나 잔존",
        "중국어구두점": "⁉️  중국어 구두점",
        "띄어쓰기결함": "📏 띄어쓰기 결함",
        "뜬금포영어": "🔤 뜬금포 영어 표현",
        "깨진자모": "💔 깨진 자모",
        "지시문누출": "⚠️  LLM 지시문 누출",
    }

    for issue_type, label in sample_labels.items():
        samples = sample_issues.get(issue_type, [])
        if not samples:
            continue
        print(f"\n  ── {label} ──")
        for doc_id, fname, field, items in samples[:5]:
            # 파일명에서 회사명 추출
            fn_match = re.match(r'^[a-f0-9]+_DART_P\d+_(.+?)_\d{13,14}', fname or '')
            company = fn_match.group(1) if fn_match else f"Doc#{doc_id}"
            print(f"    [{company}] (#{doc_id}) {field}:")
            for item in items[:2]:
                if isinstance(item, dict):
                    ctx = item.get('context', item.get('match', ''))[:60]
                    print(f"      → {ctx}")

    # ═══ 가장 심각한 문서 TOP 10 ═══
    print(f"\n{'─' * 60}")
    print(f"  🚨 이슈 집중 문서 TOP 10")
    print(f"{'─' * 60}")

    doc_severity = {}
    for doc_id, issues_list in doc_issues.items():
        total_count = sum(count for _, _, count, _ in issues_list)
        doc_severity[doc_id] = total_count

    for doc_id, total in sorted(doc_severity.items(), key=lambda x: -x[1])[:10]:
        # 파일명 조회
        cur2 = sqlite3.connect(DB).cursor()
        cur2.execute("SELECT filename FROM documents WHERE id = ?", (doc_id,))
        row = cur2.fetchone()
        fname = row[0] if row else ""
        cur2.connection.close()

        fn_match = re.match(r'^[a-f0-9]+_DART_P\d+_(.+?)_\d{13,14}', fname or '')
        company = fn_match.group(1) if fn_match else f"Doc#{doc_id}"

        issue_summary = Counter()
        for itype, _, count, _ in doc_issues[doc_id]:
            issue_summary[itype] += count
        detail = ", ".join(f"{k}:{v}" for k, v in issue_summary.most_common())
        print(f"  #{doc_id:>4} {company:20s} | {total:>4}건 | {detail}")

    # ═══ 최종 판정 ═══
    print(f"\n{'═' * 60}")
    total_issues = sum(stats.get(k, 0) for k in issue_labels.keys())
    critical = stats.get("chinese_chars", 0) + stats.get("instruction_leak", 0) + stats.get("japanese_kana", 0)

    if critical == 0 and total_issues == 0:
        print("  ✅ 전체 무결성 검증 통과 — 모든 PDF 소스 데이터 클린")
        verdict = "PASS"
    elif critical == 0:
        print(f"  ⚠️  경미한 이슈 {total_issues}건 — 가독성 개선 권장")
        verdict = "WARN"
    else:
        print(f"  ❌ 심각한 이슈 {critical}건 포함 총 {total_issues}건 — 재정제 필요")
        verdict = "FAIL"

    print(f"  판정: {verdict}")
    print("═" * 60)

    return verdict, stats, doc_issues


if __name__ == "__main__":
    verdict, stats, doc_issues = run_deep_audit()
    sys.exit(0 if verdict != "FAIL" else 1)
