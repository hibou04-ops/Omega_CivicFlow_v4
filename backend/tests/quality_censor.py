"""
═══════════════════════════════════════════════════════
Omega CivicFlow — 요약 품질 검열기 (Summary Quality Censor)
═══════════════════════════════════════════════════════

LLM 출력에서 발생하는 모든 유형의 에러를 탐지 + 자동 교정:
  1. LLM 지시문 누출 (instruction leakage)
  2. JSON 잔재 ( { } [ ] )
  3. 메타 코멘터리 (LLM이 자기 행동을 설명)
  4. 중국어 혼입
  5. company_name 필드에 대표이사/주소 오염
  6. 빈 요약 / 에러 요약
  7. raw_response 내 summary/evidence 동일 검사
"""

import sqlite3, json, sys, re, os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "omega_civicflow.db")
conn = sqlite3.connect(DB)
cur = conn.cursor()

# ═══ 탐지 패턴 ═══

# LLM 지시문 누출 패턴 (요약에 나오면 안 되는 문장들)
INSTRUCTION_LEAKAGE = [
    r'JSON\s*형식으로\s*(구성|출력|변환|생성)',
    r'템플릿을?\s*기반으로',
    r'다음은\s*문서\s*내용을?\s*기반으로\s*생성된',
    r'다음은.*JSON\s*데이터',
    r'귀하의\s*요구\s*사항',
    r'아래[는와]\s*(요약|분석|결과)',
    r'요청하신\s*(대로|바와)',
    r'제공된\s*(문서|정보|데이터)를?\s*(분석|처리)',
    r'주어진\s*(문서|텍스트)를?\s*분석',
    r'분석\s*결과를?\s*(아래|다음)',
    r'JSON\s*(데이터|형식|구조)입니다',
    r'추출하여\s*JSON',
    r'다음과\s*같[은이].*JSON',
    r'```json',
    r'```',
    r'I will now',
    r'I\'ll analyze',
    r'Here is',
    r'Based on the',
    r'Let me analyze',
]

# JSON 잔재 패턴
JSON_ARTIFACTS = [
    r'^\s*\{\s*$',          # 줄 전체가 { 만
    r'^\s*\}\s*$',          # 줄 전체가 } 만
    r'^\s*\[\s*$',
    r'^\s*\]\s*$',
    r'"summary"\s*:',       # JSON 키가 그대로 노출
    r'"category"\s*:',
    r'"key_points"\s*:',
    r'"evidence"\s*:',
    r'"document_type"\s*:',
    r'"company_name"\s*:',
]

# 메타 코멘터리 패턴
META_COMMENTARY = [
    r'이\s*문서를?\s*분석한\s*결과',
    r'이\s*보고서는?\s*AI',
    r'LLM이?\s*생성',
    r'자동\s*생성된\s*요약',
    r'본\s*분석은',
]

# company_name 오염 패턴 (대표이사, 주소 등이 company_name에 들어간 경우)
COMPANY_CONTAMINATION = [
    r'대\s*표\s*이\s*사',
    r'본\s*점\s*소\s*재\s*지',
    r'대표이사.*:',
    r'서울시|경기도|부산시|인천시|대구시|대전시|광주시',
    r'\d+길\s*\d+',
    r'번지',
]


def has_chinese(text):
    if not text:
        return False
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total = len(text.replace(" ", ""))
    return total > 0 and (cjk / total) > 0.05


def detect_issues(text, patterns, label):
    """텍스트에서 패턴 매칭, 매칭된 부분 반환"""
    issues = []
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            issues.append((label, pat, m.group()[:60]))
    return issues


def clean_summary(summary):
    """요약 텍스트에서 에러 패턴 제거"""
    if not summary:
        return summary, 0

    original = summary
    fixes = 0

    # 1. LLM 지시문 누출 문장 제거 (문장 단위)
    sentences = re.split(r'(?<=[.다니요])\s*', summary)
    clean_sentences = []
    for sent in sentences:
        skip = False
        for pat in INSTRUCTION_LEAKAGE:
            if re.search(pat, sent, re.IGNORECASE):
                skip = True
                fixes += 1
                break
        if not skip:
            clean_sentences.append(sent)
    summary = " ".join(clean_sentences).strip()

    # 2. JSON 잔재 줄 제거
    lines = summary.split('\n')
    clean_lines = []
    for line in lines:
        skip = False
        for pat in JSON_ARTIFACTS:
            if re.search(pat, line.strip(), re.IGNORECASE):
                skip = True
                fixes += 1
                break
        if not skip:
            clean_lines.append(line)
    summary = '\n'.join(clean_lines).strip()

    # 3. 남은 JSON 잔재 문자 제거 (앞뒤 { } 만)
    summary = re.sub(r'^\s*[\{\[\]\}]\s*', '', summary)
    summary = re.sub(r'\s*[\{\[\]\}]\s*$', '', summary)

    # 4. 중국어 문장 제거
    if has_chinese(summary):
        cn_sentences = re.split(r'(?<=[.。!?\n])\s*', summary)
        filtered = []
        for s in cn_sentences:
            cjk = sum(1 for c in s if '\u4e00' <= c <= '\u9fff')
            total = len(s.replace(" ", ""))
            if total > 0 and (cjk / total) > 0.2:
                fixes += 1
                continue
            filtered.append(s)
        summary = " ".join(filtered).strip()

    # 5. 연속 공백/줄바꿈 정리
    summary = re.sub(r'\n{3,}', '\n\n', summary)
    summary = re.sub(r' {2,}', ' ', summary)

    if summary != original:
        return summary.strip(), fixes
    return summary, 0


def clean_company_name(name):
    """company_name에서 대표이사/주소 오염 제거"""
    if not name:
        return name, False

    # "대 표 이 사 : 염태순 본 점 소 재 지 : 서울시..." 패턴
    m = re.search(r'대\s*표\s*이\s*사\s*:', name)
    if m:
        # 대표이사 이전 부분이 회사명
        before = name[:m.start()].strip()
        if before and len(before) > 1:
            return before, True
        return name, False

    # "회사명 본 점 소 재 지 : ..." 패턴
    m = re.search(r'본\s*점\s*소\s*재\s*지\s*:', name)
    if m:
        before = name[:m.start()].strip()
        if before and len(before) > 1:
            return before, True

    return name, False


def clean_evidence(evidence):
    """evidence 필드 정리"""
    if not evidence:
        return evidence, 0

    fixes = 0

    if isinstance(evidence, str):
        # JSON 잔재 제거
        evidence = re.sub(r'^\s*[\{\[\]\}]\s*', '', evidence)
        evidence = re.sub(r'\s*[\{\[\]\}]\s*$', '', evidence)

        # LLM 지시문 제거
        for pat in INSTRUCTION_LEAKAGE:
            if re.search(pat, evidence, re.IGNORECASE):
                evidence = re.sub(pat, '', evidence, flags=re.IGNORECASE)
                fixes += 1

    return evidence.strip() if isinstance(evidence, str) else evidence, fixes


# ═══ 메인 스캔 + 교정 ═══

print("═" * 56)
print("  Ω  OMEGA CIVICFLOW — 요약 품질 검열기")
print("═" * 56)

cur.execute("""
    SELECT id, document_id, summary, category, evidence, raw_response
    FROM analysis_results
    WHERE summary IS NOT NULL
""")
rows = cur.fetchall()
print(f"\n  📊 총 {len(rows)}건 분석 결과 스캔")

total_issues = 0
total_fixed = 0
issue_details = []

for ar_id, doc_id, summary, category, evidence, raw_resp in rows:
    issues = []

    # ── 1. summary 검사 ──
    issues.extend(detect_issues(summary, INSTRUCTION_LEAKAGE, "지시문누출"))
    issues.extend(detect_issues(summary, JSON_ARTIFACTS, "JSON잔재"))
    issues.extend(detect_issues(summary, META_COMMENTARY, "메타코멘터리"))
    if has_chinese(summary):
        issues.append(("중국어혼입", "CJK>5%", summary[:30]))

    # ── 2. raw_response 검사 ──
    raw = {}
    if raw_resp:
        try:
            r = raw_resp if isinstance(raw_resp, dict) else json.loads(raw_resp)
            if isinstance(r, str):
                r = json.loads(r)
            if isinstance(r, dict):
                raw = r
        except:
            pass

    # company_name 오염
    cn = raw.get("company_name", "")
    if cn:
        for pat in COMPANY_CONTAMINATION:
            if re.search(pat, cn, re.IGNORECASE):
                issues.append(("회사명오염", pat, cn[:50]))
                break

    # evidence 검사
    ev = raw.get("evidence", evidence or "")
    if isinstance(ev, str):
        issues.extend(detect_issues(ev, INSTRUCTION_LEAKAGE, "증거_지시문"))
        issues.extend(detect_issues(ev, JSON_ARTIFACTS, "증거_JSON"))

    # ── 교정 ──
    if issues:
        total_issues += len(issues)
        issue_details.append((doc_id, ar_id, issues))

        # summary 교정
        new_summary, s_fixes = clean_summary(summary)
        if s_fixes > 0:
            cur.execute("UPDATE analysis_results SET summary = ? WHERE id = ?", (new_summary, ar_id))
            total_fixed += s_fixes

        # raw_response 내 교정
        if raw:
            changed = False

            # company_name 교정
            cn = raw.get("company_name", "")
            new_cn, cn_fixed = clean_company_name(cn)
            if cn_fixed:
                raw["company_name"] = new_cn
                changed = True
                total_fixed += 1

            # summary in raw 교정
            raw_summary = raw.get("summary", "")
            if raw_summary and isinstance(raw_summary, str):
                new_raw_sum, rs_fixes = clean_summary(raw_summary)
                if rs_fixes > 0:
                    raw["summary"] = new_raw_sum
                    changed = True
                    total_fixed += rs_fixes

            # evidence 교정
            ev = raw.get("evidence", "")
            if isinstance(ev, str):
                new_ev, ev_fixes = clean_evidence(ev)
                if ev_fixes > 0:
                    raw["evidence"] = new_ev
                    changed = True
                    total_fixed += ev_fixes

            if changed:
                cur.execute(
                    "UPDATE analysis_results SET raw_response = ? WHERE id = ?",
                    (json.dumps(raw, ensure_ascii=False), ar_id)
                )

conn.commit()

# ── 결과 출력 ──
print(f"\n{'─' * 56}")
print(f"  📋 이슈 분류")
print(f"{'─' * 56}")

issue_types = {}
for doc_id, ar_id, issues in issue_details:
    for itype, _, _ in issues:
        issue_types[itype] = issue_types.get(itype, 0) + 1

for itype, count in sorted(issue_types.items(), key=lambda x: -x[1]):
    print(f"  {'⚠️':2s} {itype:15s} : {count}건")

print(f"\n{'─' * 56}")
print(f"  영향 문서: {len(issue_details)}건")
print(f"  발견 이슈: {total_issues}건")
print(f"  교정 완료: {total_fixed}건")
print(f"{'─' * 56}")

# 상위 5건 상세 출력
if issue_details:
    print(f"\n  📝 주요 이슈 문서 (상위 5건)")
    for doc_id, ar_id, issues in issue_details[:5]:
        print(f"    문서 #{doc_id} (AR #{ar_id}):")
        for itype, pat, sample in issues[:3]:
            print(f"      [{itype}] {sample}")

conn.close()
print(f"\n✅ 검열 완료!")
