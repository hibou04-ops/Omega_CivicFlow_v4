/**
 * 중국어 → 한국어 카테고리 번역 맵 (Qwen 계열 LLM 대응)
 * 
 * DART 공시 카테고리를 Qwen LLM이 중국어로 반환하는 경우가 있어
 * 간체/번체를 모두 포함한 매핑 테이블입니다.
 * 모든 페이지에서 공통으로 사용합니다.
 */

export const ZH_TO_KR = {
  // ── 주요사항보고서 ──
  '主要事项报告书': '주요사항보고서', '主要事項報告書': '주요사항보고서',
  '主事项报告书': '주요사항보고서', '主事項報告書': '주요사항보고서',

  // ── 재무제표 ──
  '财务报表': '재무제표', '財務報表': '재무제표',
  '财务诸表': '재무제표', '財務諸表': '재무제표',

  // ── 사업보고서 ──
  '事业报告书': '사업보고서', '事業報告書': '사업보고서',

  // ── 감사보고서 ──
  '监查报告书': '감사보고서', '監查報告書': '감사보고서',
  '审计报告书': '감사보고서', '審計報告書': '감사보고서',
  '监査报告书': '감사보고서',

  // ── 반기/분기 보고서 ──
  '半期报告书': '반기보고서', '半期報告書': '반기보고서',
  '季度报告书': '분기보고서', '季度報告書': '분기보고서',

  // ── 유상증자 ──
  '有偿增资': '유상증자결정', '有償增資': '유상증자결정',
  '有偿增资决定': '유상증자결정', '有償增資決定': '유상증자결정',
  '增发决定': '유상증자결정', '增發決定': '유상증자결정',

  // ── 무상증자 ──
  '无偿增资': '무상증자', '無償增資': '무상증자',

  // ── 감자 ──
  '减资': '감자', '減資': '감자',

  // ── 전환사채 ──
  '转换社债': '전환사채', '轉換社債': '전환사채',
  '可转换债券': '전환사채', '可轉換債券': '전환사채',

  // ── 신주인수권부사채 ──
  '新股认购权附社债': '신주인수권부사채', '新株引受權附社債': '신주인수권부사채',

  // ── 자기주식 ──
  '己股': '자기주식', '自己股': '자기주식', '自己株式': '자기주식',
  '自社株': '자기주식', '库存股': '자기주식', '庫存股': '자기주식',
  '自己股票': '자기주식', '自社股': '자기주식',

  // ── 합병/분할 ──
  '合并': '합병', '合併': '합병',
  '分割': '분할',

  // ── 임원·주요주주변동 ──
  '任员·主要股东变动': '임원·주요주주변동', '任員·主要股東變動': '임원·주요주주변동',
  '任员主要股东变动': '임원·주요주주변동', '任員主要股東變動': '임원·주요주주변동',
  '任员-主要股东变动': '임원·주요주주변동',
  '임원·주요주주변동': '임원·주요주주변동',

  // ── 배당 ──
  '配当': '배당', '分红': '배당', '分紅': '배당',

  // ── 정정신고 ──
  '更正申告': '정정신고(보고)', '订正报告': '정정신고(보고)',

  // ── 기타 ──
  '其他': '기타', '其他公示': '기타공시',
  '其它': '기타', '其它公示': '기타공시',
};

/**
 * 중국어 카테고리명을 한국어로 변환합니다.
 * LLM이 공백을 삽입하는 경우가 있어 공백 제거 후 재검색합니다.
 * 매핑에 없으면 원본을 그대로 반환합니다.
 */
export const translateCategory = (cat) => {
  if (!cat) return cat;
  if (ZH_TO_KR[cat]) return ZH_TO_KR[cat];
  // 공백 제거 후 재검색 (예: "财 务报表" → "财务报表")
  const stripped = cat.replace(/\s+/g, '');
  if (stripped !== cat && ZH_TO_KR[stripped]) return ZH_TO_KR[stripped];
  return cat;
};

/**
 * 번역 후 동일한 카테고리명이 중복되면 count를 합산합니다.
 * 예: { category: '财务报表', count: 1 } + { category: '재무제표', count: 48 }
 *   → { category: '재무제표', count: 49 }
 */
export const deduplicateCategories = (stats) => {
  const map = new Map();
  for (const s of stats) {
    const kr = translateCategory(s.category);
    if (map.has(kr)) {
      map.get(kr).count += s.count;
    } else {
      map.set(kr, { ...s, category: kr });
    }
  }
  return Array.from(map.values());
};

/**
 * DART 파일명에서 회사명을 추출하고 "회사명_카테고리" 형식으로 반환합니다.
 * 패턴: {hash}_DART_P{num}_{회사명}_{날짜}.zip.pdf
 * 
 * @param {string} filename - 원본 파일명
 * @param {string} category - 번역된 카테고리명 (optional)
 * @param {string} companyOverride - API에서 받은 교정 회사명 (optional, 파일명보다 우선)
 * @returns {{ display: string, company: string|null }}
 */
export const parseDisplayFilename = (filename, category, companyOverride) => {
  if (!filename) return { display: filename, company: null };

  // Pattern: {hash}_DART_P{num}_{companyName}_{date...}
  const match = filename.match(/^[a-f0-9]+_DART_P\d+_(.+?)_(\d{13,14})/);
  if (match) {
    const company = companyOverride || match[1];
    const cat = category || '미분류';
    return { display: `${company}_${cat}`, company };
  }

  // Fallback: 원본 파일명 그대로
  return { display: filename, company: null };
};
/**
 * 파일명의 회사명을 교정합니다 (크로스체크).
 * - correctCompany 제공 시: 파일명 내 회사명을 교정된 이름으로 교체
 * - correctCompany 미제공 시: 원본 파일명 그대로 반환
 * 
 * {hash}_DART_P{n}_{오타회사명}_{날짜}.ext → {hash}_DART_P{n}_{정확한회사명}_{날짜}.ext
 */
export const correctFilenameCompany = (filename, correctCompany) => {
  if (!filename) return filename;
  if (!correctCompany || correctCompany === '미확인') return filename;
  
  const match = filename.match(/^([a-f0-9]+_DART_P\d+)_.+_(\d{13,14})/);
  if (match) {
    return `${match[1]}_${correctCompany}_${match[2]}`;
  }
  
  // DART 패턴이 아닌 일반/숫자 파일명인 경우, 파악된 회사명이 있다면 앞에 직관적으로 붙여줌
  if (!filename.includes(correctCompany)) {
    return `[${correctCompany}] ${filename}`;
  }
  
  return filename;
};

// 하위 호환성 유지
export const stripCompanyFromFilename = correctFilenameCompany;
