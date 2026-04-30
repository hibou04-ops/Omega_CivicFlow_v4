import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { documentsAPI } from '../api/client';
import { FileText, Info, Brain, FileEdit, Search, Zap, RefreshCw, Download, Eye, X, Shield, Activity, Target, TrendingUp, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';
import { translateCategory, correctFilenameCompany } from '../utils/categoryTranslation';


const STATUS_MAP = {
  uploaded: { label: '업로드', class: 'badge-info' },
  ocr_done: { label: 'OCR 완료', class: 'badge-warning' },
  analyzed: { label: '분석 완료', class: 'badge-success' },
  failed: { label: '실패', class: 'badge-danger' },
};

// ── Insight 백그라운드 생성 추적 (localStorage 기반) ──
// 사용자가 페이지 이탈해도 backend는 계속 작동, 재방문 시 polling 재개.
const INSIGHT_GEN_TTL_MS = 5 * 60 * 1000; // 5분 timeout (그 이상은 실패로 간주)
const INSIGHT_POLL_INTERVAL_MS = 5000; // 5초마다 결과 확인
const insightGenKey = (docId) => `omega_insight_gen_${docId}`;

const getInsightGenStartedAt = (docId) => {
  try {
    const raw = localStorage.getItem(insightGenKey(docId));
    if (!raw) return null;
    const ts = parseInt(raw, 10);
    if (Number.isNaN(ts)) return null;
    if (Date.now() - ts > INSIGHT_GEN_TTL_MS) {
      localStorage.removeItem(insightGenKey(docId));
      return null;
    }
    return ts;
  } catch {
    return null;
  }
};

const setInsightGenStarted = (docId) => {
  try {
    localStorage.setItem(insightGenKey(docId), String(Date.now()));
  } catch {
    /* localStorage 비활성화 환경 — 무시 */
  }
};

const clearInsightGenStarted = (docId) => {
  try {
    localStorage.removeItem(insightGenKey(docId));
  } catch {
    /* ignore */
  }
};

export default function DocumentDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Insight 상태
  const [activeTab, setActiveTab] = useState('analysis'); // 'analysis' | 'insight'
  const [insight, setInsight] = useState(null);
  const [insightLoading, setInsightLoading] = useState(false);
  const [insightError, setInsightError] = useState('');

  // Insight 백그라운드 생성 — 페이지 이탈해도 backend 계속 작동
  const [genStartedAt, setGenStartedAt] = useState(null); // ms 또는 null
  const [tickNow, setTickNow] = useState(Date.now());

  // 재분석 상태
  const [reanalyzing, setReanalyzing] = useState(false);
  const [reanalyzeMsg, setReanalyzeMsg] = useState('');

  // PDF 미리보기
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);

  const openPreview = async () => {
    try {
      const res = await documentsAPI.downloadReport(data.document.id);
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      setPreviewUrl(url);
      setPreviewOpen(true);
    } catch {
      alert('PDF 보고서를 불러올 수 없습니다.');
    }
  };

  const closePreview = () => {
    setPreviewOpen(false);
    if (previewUrl) { window.URL.revokeObjectURL(previewUrl); setPreviewUrl(null); }
  };

  useEffect(() => {
    loadDocument();
  }, [id]);

  const loadDocument = async () => {
    try {
      const res = await documentsAPI.getDetail(id);
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || '문서를 불러올 수 없습니다.');
    } finally {
      setLoading(false);
    }
  };

  const loadInsight = async () => {
    try {
      setInsightLoading(true);
      setInsightError('');
      const res = await documentsAPI.getInsight(id);
      if (res.data.exists) {
        setInsight(res.data.insight);
        clearInsightGenStarted(id);
        setGenStartedAt(null);
      } else {
        // 인사이트 없음 — 백그라운드 생성이 진행 중인지 확인
        const startedAt = getInsightGenStartedAt(id);
        if (startedAt) {
          // 진행 중 → polling useEffect가 자동으로 5초마다 확인
          setGenStartedAt(startedAt);
        }
      }
    } catch (err) {
      console.error('Insight 로드 실패:', err);
    } finally {
      setInsightLoading(false);
    }
  };

  const generateInsight = async () => {
    try {
      setInsightError('');
      // ── 1. localStorage에 시작 시각 기록 (페이지 이탈 후 재방문 시 polling 재개용) ──
      setInsightGenStarted(id);
      const startedAt = Date.now();
      setGenStartedAt(startedAt);
      setInsightLoading(true);

      // ── 2. POST 요청 발사 (await O — 정상 케이스에서 즉시 결과 받음) ──
      // 사용자가 도중에 페이지를 떠나면 axios는 cancel되지만
      // FastAPI 백엔드는 계속 작동 → DB에 저장 → polling이 결과 발견 → 표시
      const res = await documentsAPI.generateInsight(id);
      if (res.data?.success) {
        setInsight(res.data.insight);
        clearInsightGenStarted(id);
        setGenStartedAt(null);
        setInsightLoading(false);
      }
    } catch (err) {
      // 네트워크/cancel 에러는 무시 — polling이 backend 결과를 catch
      // 진짜 실패만 polling timeout(5분) 후 표시됨
      console.warn(
        'Insight 생성 요청 응답 누락 (backend는 진행 중일 가능성 — polling이 대체):',
        err?.message,
      );
    }
  };

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    if (tab === 'insight' && !insight) {
      loadInsight();
    }
  };

  // ── 마운트 시 자동으로 백그라운드 생성 진행 여부 확인 ──
  // 사용자가 다른 페이지 다녀와도 진행 중이던 작업을 자동으로 추적 재개
  useEffect(() => {
    const startedAt = getInsightGenStartedAt(id);
    if (startedAt && !insight) {
      setGenStartedAt(startedAt);
      // Insight 탭으로 자동 전환 (사용자가 직전에 보고 있던 컨텍스트)
      setActiveTab('insight');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // ── Insight 생성 polling: genStartedAt이 있으면 5초마다 GET, 5분 timeout ──
  useEffect(() => {
    if (!genStartedAt) return undefined;

    // UI 경과 시간 1초 tick
    const tickInterval = setInterval(() => {
      setTickNow(Date.now());
    }, 1000);

    // 결과 polling 5초 간격
    const pollInterval = setInterval(async () => {
      // Timeout 체크
      if (Date.now() - genStartedAt > INSIGHT_GEN_TTL_MS) {
        clearInterval(pollInterval);
        clearInterval(tickInterval);
        setGenStartedAt(null);
        clearInsightGenStarted(id);
        setInsightLoading(false);
        setInsightError(
          'Insight 생성 시간 초과 (5분). 백엔드 로그 확인 후 다시 시도해주세요.',
        );
        return;
      }

      try {
        const res = await documentsAPI.getInsight(id);
        if (res.data?.exists) {
          setInsight(res.data.insight);
          clearInterval(pollInterval);
          clearInterval(tickInterval);
          setGenStartedAt(null);
          clearInsightGenStarted(id);
          setInsightLoading(false);
        }
      } catch (err) {
        // 일시적 네트워크 오류 — 다음 tick에 재시도
        console.warn('Insight polling 오류 (재시도 예정):', err?.message);
      }
    }, INSIGHT_POLL_INTERVAL_MS);

    return () => {
      clearInterval(pollInterval);
      clearInterval(tickInterval);
    };
  }, [genStartedAt, id]);

  // 경과 시간 계산 (UI 표시용)
  const elapsedSec = genStartedAt
    ? Math.max(0, Math.floor((tickNow - genStartedAt) / 1000))
    : 0;

  // 에러 요약 판별 헬퍼
  const INSUFFICIENT_PREFIXES = ['분석할 텍스트'];
  const LLM_ERROR_PREFIXES = ['분석 중 오류', 'LLM 분석 실패', 'All connection'];
  const isInsufficientContent = (summary) =>
    INSUFFICIENT_PREFIXES.some(p => (summary || '').startsWith(p));
  const isLlmError = (summary) =>
    !summary || LLM_ERROR_PREFIXES.some(p => (summary || '').startsWith(p));
  const isErrorSummary = (summary) =>
    isInsufficientContent(summary) || isLlmError(summary);

  const handleReanalyze = async () => {
    setReanalyzing(true);
    setReanalyzeMsg('');
    try {
      await documentsAPI.reanalyze(id);
      setReanalyzeMsg('재분석 완료! 결과를 불러옵니다...');
      setTimeout(() => loadDocument(), 800);
    } catch (err) {
      setReanalyzeMsg(
        '재분석 실패: ' + (err.response?.data?.detail || '알 수 없는 오류')
      );
    } finally {
      setReanalyzing(false);
    }
  };

  const handleDownloadReport = async () => {
    try {
      const res = await documentsAPI.downloadReport(data.document.id);
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${correctFilenameCompany(data.document.filename, data.company_name).replace(/\.[^/.]+$/, '')}_요약보고서.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      alert('PDF 보고서를 다운로드할 수 없습니다.');
    }
  };

  const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleString('ko-KR', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  };

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner spinner-lg"></div>
        <p>문서 로딩 중...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="page-container">
        <div className="alert alert-error">⚠️ {error}</div>
        <Link to="/mypage" className="btn btn-secondary">← 돌아가기</Link>
      </div>
    );
  }

  const { document: doc, ocr_texts, analysis, owner_username, company_name } = data;
  const status = STATUS_MAP[doc.status] || { label: doc.status, class: 'badge-info' };

  return (
    <div className="page-container fade-in">
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem', flexWrap: 'wrap' }}>
        <Link to="/mypage" className="btn btn-secondary btn-sm">← 목록</Link>
        <div className="page-header" style={{ marginBottom: 0, flex: 1 }}>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileText size={22} strokeWidth={1.5} style={{ flexShrink: 0, opacity: 0.7 }} />
            <span className="doc-filename-title">{correctFilenameCompany(doc.filename, company_name)}</span>
          </h1>
          <p>문서 #{doc.id} · 업로더: {owner_username || 'N/A'}</p>
        </div>
        {doc.status === 'analyzed' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', alignItems: 'flex-end' }}>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button onClick={openPreview} className="btn btn-secondary"
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                  padding: '0.6rem 1rem', fontSize: '0.85rem', fontWeight: 600,
                }}
              ><Eye size={16} /> 미리보기</button>
              <button onClick={handleDownloadReport} className="btn btn-primary"
                style={{
                  background: 'linear-gradient(135deg, #00b4d8 0%, #0077b6 100%)',
                  border: 'none', display: 'flex', alignItems: 'center', gap: '0.4rem',
                  padding: '0.6rem 1rem', fontSize: '0.85rem', fontWeight: 600,
                }}
              ><Download size={16} /> 다운로드</button>
              <button
                onClick={handleReanalyze}
                disabled={reanalyzing}
                className="btn"
                style={{
                  background: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
                  color: '#fff', border: 'none',
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                  padding: '0.6rem 1rem', fontSize: '0.85rem', fontWeight: 600,
                  opacity: reanalyzing ? 0.7 : 1,
                }}
              >
                <RefreshCw size={16} strokeWidth={2}
                  style={{ animation: reanalyzing ? 'spin 1s linear infinite' : 'none' }} />
                {reanalyzing ? '재분석 중...' : '재분석'}
              </button>
            </div>
            {reanalyzeMsg && (
              <div style={{
                fontSize: '0.8rem',
                color: reanalyzeMsg.includes('실패') ? '#f87171' : '#34d399',
                fontWeight: 500,
              }}>
                {reanalyzeMsg}
              </div>
            )}
          </div>
        )}

        {/* PDF 미리보기 모달 */}
        {previewOpen && (
          <div style={{
            position: 'fixed', inset: 0, zIndex: 9999,
            background: 'rgba(0,0,0,0.85)',
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            padding: '1.5rem',
          }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              width: '100%', maxWidth: '900px', marginBottom: '0.75rem', gap: '1rem',
            }}>
              <span style={{
                fontWeight: 700, fontSize: '0.95rem', color: '#fff',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                minWidth: 0, flex: 1,
              }}>
                📄 {correctFilenameCompany(doc.filename, company_name)} — PDF 요약 보고서 미리보기
              </span>
              <div style={{ display: 'flex', gap: '0.5rem', flexShrink: 0 }}>
                <button onClick={handleDownloadReport} className="btn btn-primary btn-sm"
                  style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', whiteSpace: 'nowrap' }}>
                  <Download size={14} /> 다운로드
                </button>
                <button onClick={closePreview} className="btn btn-secondary btn-sm"
                  style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', whiteSpace: 'nowrap' }}>
                  <X size={14} /> 닫기
                </button>
              </div>
            </div>
            <iframe
              src={previewUrl}
              style={{
                width: '100%', maxWidth: '900px', flex: 1,
                border: '1px solid rgba(255,255,255,0.15)',
                borderRadius: '8px', background: '#fff',
              }}
              title="PDF Preview"
            />
          </div>
        )}
      </div>

      {/* 분석 배너 */}
      {analysis && isInsufficientContent(analysis.summary) && (
        <div style={{
          background: 'rgba(251,191,36,0.08)',
          border: '1px solid rgba(251,191,36,0.35)',
          borderRadius: '10px',
          padding: '1rem 1.25rem',
          marginBottom: '1.5rem',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexWrap: 'wrap', gap: '0.75rem',
        }}>
          <div>
            <div style={{ fontWeight: 700, color: '#FBBF24', marginBottom: '0.25rem' }}>
              📄 문서 내용 부족
            </div>
            <div style={{ fontSize: '0.85rem', color: 'var(--omega-text-muted)' }}>
              원본 문서에서 분석 가능한 텍스트가 충분히 추출되지 않았습니다. 빈 페이지이거나 이미지만 포함된 문서일 수 있습니다.
            </div>
          </div>
        </div>
      )}
      {analysis && isLlmError(analysis.summary) && !isInsufficientContent(analysis.summary) && (
        <div style={{
          background: 'rgba(239,68,68,0.1)',
          border: '1px solid rgba(239,68,68,0.4)',
          borderRadius: '10px',
          padding: '1rem 1.25rem',
          marginBottom: '1.5rem',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          flexWrap: 'wrap', gap: '0.75rem',
        }}>
          <div>
            <div style={{ fontWeight: 700, color: '#f87171', marginBottom: '0.25rem' }}>
              ⚠ LLM 분석 실패
            </div>
            <div style={{ fontSize: '0.85rem', color: 'var(--omega-text-muted)' }}>
              {analysis.summary || 'Ollama 연결에 실패했습니다.'} — Ollama가 실행 중인지 확인 후 재분석해주세요.
            </div>
            {reanalyzeMsg && (
              <div style={{
                marginTop: '0.5rem', fontSize: '0.85rem',
                color: reanalyzeMsg.includes('실패') ? '#f87171' : '#34d399'
              }}>
                {reanalyzeMsg}
              </div>
            )}
          </div>
          <button
            onClick={handleReanalyze}
            disabled={reanalyzing}
            className="btn btn-sm"
            style={{
              background: 'linear-gradient(135deg, #dc2626, #b91c1c)',
              color: '#fff', border: 'none',
              display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
              opacity: reanalyzing ? 0.7 : 1,
            }}
          >
            <RefreshCw size={14} strokeWidth={2}
              style={{ animation: reanalyzing ? 'spin 1s linear infinite' : 'none' }} />
            {reanalyzing ? '재분석 중...' : 'LLM 재분석'}
          </button>
        </div>
      )}

      {/* 문서 정보 */}
      <div className="detail-grid" style={{ marginBottom: '1.5rem' }}>
        <div className="detail-section slide-up stagger-1">
          <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <Info size={15} strokeWidth={1.8} /> 문서 정보
          </h3>
          <div className="detail-row">
            <span className="label">파일명</span>
            <span className="value">{correctFilenameCompany(doc.filename, company_name)}</span>
          </div>
          <div className="detail-row">
            <span className="label">형식</span>
            <span className="value">{doc.file_type.toUpperCase()}</span>
          </div>
          <div className="detail-row">
            <span className="label">크기</span>
            <span className="value">{formatSize(doc.file_size)}</span>
          </div>
          <div className="detail-row">
            <span className="label">상태</span>
            <span className={`badge ${status.class}`}>{status.label}</span>
          </div>
          <div className="detail-row">
            <span className="label">업로드일</span>
            <span className="value">{formatDate(doc.created_at)}</span>
          </div>
        </div>

        {analysis && (
          <div className="detail-section slide-up stagger-2">
            <h3 style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Brain size={15} strokeWidth={1.8} /> LLM 분석 결과
            </h3>
            <div className="detail-row">
              <span className="label">카테고리</span>
              <span className="badge badge-primary" style={{ fontSize: '0.85rem', padding: '0.3rem 0.75rem' }}>
                {translateCategory(analysis.category)}
              </span>
            </div>
            <div className="detail-row">
              <span className="label">핵심 재무</span>
              <span className="value">{analysis.financial_metrics || '해당 없음'}</span>
            </div>
            <div className="detail-row">
              <span className="label">모델</span>
              <span className="value">{analysis.model_name}</span>
            </div>
            <div className="detail-row">
              <span className="label">처리 시간</span>
              <span className="value">{analysis.processing_time?.toFixed(2)}초</span>
            </div>
          </div>
        )}
      </div>

      {/* 탭 — 분석/Insight */}
      {analysis && (
        <>
          <div style={{
            display: 'flex', gap: '0', borderBottom: '2px solid var(--omega-border)',
            marginBottom: '1.5rem',
          }}>
            <button
              onClick={() => handleTabChange('analysis')}
              style={{
                padding: '0.7rem 1.5rem', fontSize: '0.95rem', fontWeight: 600,
                border: 'none', cursor: 'pointer',
                borderBottom: activeTab === 'analysis' ? '3px solid var(--omega-accent)' : '3px solid transparent',
                color: activeTab === 'analysis' ? 'var(--omega-accent)' : 'var(--omega-text-muted)',
                background: 'transparent', transition: 'all 0.2s ease',
                display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
              }}
            >
              <FileEdit size={14} strokeWidth={1.8} /> 분석 결과
            </button>
            <button
              onClick={() => handleTabChange('insight')}
              style={{
                padding: '0.7rem 1.5rem', fontSize: '0.95rem', fontWeight: 600,
                border: 'none', cursor: 'pointer',
                borderBottom: activeTab === 'insight' ? '3px solid #f59e0b' : '3px solid transparent',
                color: activeTab === 'insight' ? '#f59e0b' : 'var(--omega-text-muted)',
                background: 'transparent', transition: 'all 0.2s ease',
                display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
              }}
            >
              <Zap size={14} strokeWidth={1.8} /> Insight
            </button>
          </div>

          {/* 분석 결과 탭 */}
          {activeTab === 'analysis' && (
            <div className="detail-grid" style={{ marginBottom: '1.5rem' }}>
              <div className="detail-section slide-up stagger-3">
                <h3>📝 요약</h3>
                <p style={{ fontSize: '0.9rem', lineHeight: 1.8, color: 'var(--omega-text-secondary)' }}>
                  {analysis.summary || '요약 없음'}
                </p>
              </div>
              <div className="detail-section slide-up stagger-4">
                <h3>🔍 근거 문장</h3>
                <p style={{
                  fontSize: '0.9rem', lineHeight: 1.8, fontStyle: 'italic',
                  color: 'var(--omega-accent)', borderLeft: '3px solid var(--omega-accent)',
                  paddingLeft: '1rem',
                }}>
                  "{analysis.evidence || '근거 없음'}"
                </p>
              </div>
            </div>
          )}

          {/* Insight 탭 */}
          {activeTab === 'insight' && (
            <div style={{ marginBottom: '1.5rem' }}>
              {insightLoading || genStartedAt ? (
                <div className="loading-container" style={{ minHeight: '200px' }}>
                  <div className="spinner spinner-lg"></div>
                  <p style={{ marginTop: '1rem', color: 'var(--omega-text-muted)' }}>
                    Gemini 2.5 Pro + Omega-Prime Supervisor로 Insight 생성 중... (약 60~120초 소요)
                  </p>
                  {genStartedAt && (
                    <>
                      <p
                        style={{
                          marginTop: '0.5rem',
                          color: '#FBBF24',
                          fontSize: '0.85rem',
                          fontWeight: 600,
                        }}
                      >
                        ⏱ 경과 시간: {elapsedSec}초
                      </p>
                      <p
                        style={{
                          marginTop: '0.25rem',
                          color: 'var(--omega-text-muted)',
                          fontSize: '0.78rem',
                          maxWidth: 360,
                          textAlign: 'center',
                          lineHeight: 1.5,
                        }}
                      >
                        💡 뒤로가기 / 다른 페이지로 이동하셔도 백엔드는 계속 진행됩니다.
                        <br />
                        이 문서로 다시 돌아오시면 자동으로 결과를 가져옵니다.
                      </p>
                    </>
                  )}
                </div>
              ) : insightError ? (
                <div className="alert alert-error">⚠️ {insightError}</div>
              ) : insight ? (
                <div className="fade-in">
                  {/* Insight 헤더 */}
                  <div style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem',
                  }}>
                    <div>
                      <span style={{ fontSize: '0.8rem', color: 'var(--omega-text-muted)' }}>
                        {insight.model_name} · {insight.processing_time?.toFixed(1)}초 ·{' '}
                        {insight.created_at && formatDate(insight.created_at)}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: '0.4rem' }}>
                      <button
                        onClick={async () => {
                          try {
                            const res = await documentsAPI.downloadInsightPdf(id);
                            const blob = new Blob([res.data], { type: 'application/pdf' });
                            const url = window.URL.createObjectURL(blob);
                            const a = document.createElement('a');
                            a.href = url;
                            a.download = `${correctFilenameCompany(doc.filename, company_name).replace(/\.[^/.]+$/, '')}_Insight보고서.pdf`;
                            document.body.appendChild(a);
                            a.click();
                            a.remove();
                            window.URL.revokeObjectURL(url);
                          } catch {
                            alert('Insight PDF를 다운로드할 수 없습니다.');
                          }
                        }}
                        className="btn btn-sm"
                        style={{
                          background: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
                          color: '#fff', border: 'none',
                          display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                          fontWeight: 600,
                        }}
                      >
                        <Download size={14} /> PDF 다운로드
                      </button>
                      <button onClick={generateInsight} className="btn btn-sm btn-secondary">
                        🔄 재생성
                      </button>
                    </div>
                  </div>

                  {/* 전략 등급 */}
                  {insight.strategy_rating && (
                    <div className="detail-section" style={{ marginBottom: '1rem', borderLeft: '4px solid #f59e0b' }}>
                      <h3 style={{ color: '#f59e0b' }}>⭐ 전략 등급</h3>
                      <p style={{ fontSize: '0.9rem', lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                        {insight.strategy_rating}
                      </p>
                    </div>
                  )}

                  {/* 투자 시사점 */}
                  {insight.investment_thesis && (
                    <div className="detail-section" style={{ marginBottom: '1rem' }}>
                      <h3>💡 핵심 투자 시사점</h3>
                      <p style={{ fontSize: '0.9rem', lineHeight: 1.8, whiteSpace: 'pre-wrap', color: 'var(--omega-text-secondary)' }}>
                        {insight.investment_thesis}
                      </p>
                    </div>
                  )}

                  {/* 시장 컨텍스트 */}
                  {insight.market_context && (
                    <div className="detail-section" style={{ marginBottom: '1rem' }}>
                      <h3>📊 시장 컨텍스트</h3>
                      <p style={{ fontSize: '0.9rem', lineHeight: 1.8, whiteSpace: 'pre-wrap', color: 'var(--omega-text-secondary)' }}>
                        {insight.market_context}
                      </p>
                    </div>
                  )}

                  {/* 리스크 */}
                  {insight.risk_factors && (
                    <div className="detail-section" style={{ marginBottom: '1rem', borderLeft: '4px solid #ef4444' }}>
                      <h3 style={{ color: '#ef4444' }}>⚠️ 리스크 팩터</h3>
                      <p style={{ fontSize: '0.9rem', lineHeight: 1.8, whiteSpace: 'pre-wrap', color: 'var(--omega-text-secondary)' }}>
                        {insight.risk_factors}
                      </p>
                    </div>
                  )}

                  {/* 전략적 행동 */}
                  {insight.strategic_action && (
                    <div className="detail-section" style={{ marginBottom: '1rem', borderLeft: '4px solid #22c55e' }}>
                      <h3 style={{ color: '#22c55e' }}>🎯 전략적 행동 지침</h3>
                      <p style={{ fontSize: '0.9rem', lineHeight: 1.8, whiteSpace: 'pre-wrap', color: 'var(--omega-text-secondary)' }}>
                        {insight.strategic_action}
                      </p>
                    </div>
                  )}

                  {/* ═══ Omega-Prime Supervisor 보강 ═══ */}
                  {insight.supervisor_decision && (
                    <div className="fade-in" style={{ marginTop: '2rem' }}>
                      {/* Supervisor 헤더 */}
                      <div style={{
                        display: 'flex', alignItems: 'center', gap: '0.6rem',
                        marginBottom: '1.25rem', paddingBottom: '0.75rem',
                        borderBottom: '1px solid rgba(139, 92, 246, 0.2)',
                      }}>
                        <div style={{
                          width: '32px', height: '32px', borderRadius: '8px',
                          background: 'linear-gradient(135deg, #8B5CF6 0%, #6D28D9 100%)',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          boxShadow: '0 0 20px rgba(139, 92, 246, 0.15)',
                        }}>
                          <Shield size={16} strokeWidth={2} style={{ color: '#fff' }} />
                        </div>
                        <div>
                          <div style={{ fontWeight: 700, fontSize: '0.95rem', color: '#A78BFA' }}>
                            Ω Omega-Prime Supervisor
                          </div>
                          <div style={{ fontSize: '0.72rem', color: 'var(--omega-text-muted)' }}>
                            Harness Agent — 사후 검증 및 전략 보강
                            {insight.supervisor_model && (
                              <span style={{ marginLeft: '0.5rem', opacity: 0.7 }}>
                                · {insight.supervisor_model}
                              </span>
                            )}
                            {insight.supervisor_time > 0 && (
                              <span style={{ marginLeft: '0.3rem', opacity: 0.7 }}>
                                · {insight.supervisor_time.toFixed(1)}s
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* 메타 배지 그리드 */}
                      <div style={{
                        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                        gap: '0.75rem', marginBottom: '1.25rem',
                      }}>
                        {/* 판단 유형 */}
                        <div style={{
                          background: 'rgba(139, 92, 246, 0.06)',
                          border: '1px solid rgba(139, 92, 246, 0.15)',
                          borderRadius: '10px', padding: '0.85rem 1rem',
                        }}>
                          <div style={{
                            fontSize: '0.65rem', fontWeight: 700, color: 'var(--omega-text-muted)',
                            textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.35rem',
                            display: 'flex', alignItems: 'center', gap: '0.35rem',
                          }}>
                            <Target size={11} strokeWidth={2} /> 판단 유형
                          </div>
                          <div style={{
                            fontSize: '0.85rem', fontWeight: 600,
                            color: '#A78BFA',
                          }}>
                            {{
                              direct_answer: '✦ 직접 판단',
                              clarify: '❓ 추가 정보 필요',
                              route: '↗ 전문가 라우팅',
                              partial_answer: '◐ 부분 판단',
                              defer_until_input: '⏸ 입력 대기',
                            }[insight.supervisor_decision] || insight.supervisor_decision}
                          </div>
                        </div>

                        {/* 주요 도메인 */}
                        <div style={{
                          background: 'rgba(59, 130, 246, 0.06)',
                          border: '1px solid rgba(59, 130, 246, 0.15)',
                          borderRadius: '10px', padding: '0.85rem 1rem',
                        }}>
                          <div style={{
                            fontSize: '0.65rem', fontWeight: 700, color: 'var(--omega-text-muted)',
                            textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.35rem',
                            display: 'flex', alignItems: 'center', gap: '0.35rem',
                          }}>
                            <Activity size={11} strokeWidth={2} /> 주요 도메인
                          </div>
                          <div style={{
                            fontSize: '0.85rem', fontWeight: 600,
                            color: '#60A5FA',
                          }}>
                            {{
                              F: '📊 Finance (금융)',
                              E: '⚙️ Engineering (공학)',
                              S: '♟ Strategy (전략)',
                              D: '🎨 Design (디자인)',
                              R: '🤝 Relations (관계)',
                              UNKNOWN: '— 미분류',
                            }[insight.primary_axis] || insight.primary_axis}
                          </div>
                        </div>

                        {/* 신뢰 등급 */}
                        <div style={{
                          background: (() => {
                            const map = {
                              AXIOM: 'rgba(34, 197, 94, 0.06)',
                              CONSENSUS: 'rgba(34, 197, 94, 0.05)',
                              INFERENCE: 'rgba(245, 158, 11, 0.06)',
                              SPECULATION: 'rgba(239, 68, 68, 0.06)',
                              EXPLORATION: 'rgba(239, 68, 68, 0.05)',
                            };
                            return map[insight.confidence_label] || 'rgba(255,255,255,0.03)';
                          })(),
                          border: (() => {
                            const map = {
                              AXIOM: '1px solid rgba(34, 197, 94, 0.2)',
                              CONSENSUS: '1px solid rgba(34, 197, 94, 0.15)',
                              INFERENCE: '1px solid rgba(245, 158, 11, 0.2)',
                              SPECULATION: '1px solid rgba(239, 68, 68, 0.2)',
                              EXPLORATION: '1px solid rgba(239, 68, 68, 0.15)',
                            };
                            return map[insight.confidence_label] || '1px solid rgba(255,255,255,0.08)';
                          })(),
                          borderRadius: '10px', padding: '0.85rem 1rem',
                        }}>
                          <div style={{
                            fontSize: '0.65rem', fontWeight: 700, color: 'var(--omega-text-muted)',
                            textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.35rem',
                            display: 'flex', alignItems: 'center', gap: '0.35rem',
                          }}>
                            <TrendingUp size={11} strokeWidth={2} /> 신뢰 등급
                          </div>
                          <div style={{
                            fontSize: '0.85rem', fontWeight: 600,
                            color: (() => {
                              const map = {
                                AXIOM: '#22C55E',
                                CONSENSUS: '#4ADE80',
                                INFERENCE: '#F59E0B',
                                SPECULATION: '#EF4444',
                                EXPLORATION: '#F87171',
                              };
                              return map[insight.confidence_label] || '#A0A0A0';
                            })(),
                          }}>
                            {{
                              AXIOM: '■ AXIOM [99%]',
                              CONSENSUS: '■ CONSENSUS [85-95%]',
                              INFERENCE: '■ INFERENCE [65-84%]',
                              SPECULATION: '■ SPECULATION [40-64%]',
                              EXPLORATION: '■ EXPLORATION [<40%]',
                            }[insight.confidence_label] || insight.confidence_label}
                          </div>
                        </div>

                        {/* 근거 품질 */}
                        <div style={{
                          background: (() => {
                            const map = {
                              high: 'rgba(34, 197, 94, 0.06)',
                              medium: 'rgba(245, 158, 11, 0.06)',
                              low: 'rgba(239, 68, 68, 0.06)',
                            };
                            return map[insight.evidence_quality] || 'rgba(255,255,255,0.03)';
                          })(),
                          border: (() => {
                            const map = {
                              high: '1px solid rgba(34, 197, 94, 0.15)',
                              medium: '1px solid rgba(245, 158, 11, 0.15)',
                              low: '1px solid rgba(239, 68, 68, 0.15)',
                            };
                            return map[insight.evidence_quality] || '1px solid rgba(255,255,255,0.08)';
                          })(),
                          borderRadius: '10px', padding: '0.85rem 1rem',
                        }}>
                          <div style={{
                            fontSize: '0.65rem', fontWeight: 700, color: 'var(--omega-text-muted)',
                            textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.35rem',
                            display: 'flex', alignItems: 'center', gap: '0.35rem',
                          }}>
                            <AlertTriangle size={11} strokeWidth={2} /> 근거 품질
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <div style={{
                              fontSize: '0.85rem', fontWeight: 600,
                              color: (() => {
                                const map = { high: '#22C55E', medium: '#F59E0B', low: '#EF4444' };
                                return map[insight.evidence_quality] || '#A0A0A0';
                              })(),
                            }}>
                              {{ high: '◉ 높음', medium: '◎ 보통', low: '○ 낮음' }[insight.evidence_quality] || insight.evidence_quality}
                            </div>
                            {/* 미니 바 게이지 */}
                            <div style={{
                              flex: 1, height: '4px', borderRadius: '2px',
                              background: 'rgba(255,255,255,0.06)', overflow: 'hidden',
                            }}>
                              <div style={{
                                height: '100%', borderRadius: '2px',
                                width: insight.evidence_quality === 'high' ? '100%'
                                  : insight.evidence_quality === 'medium' ? '60%' : '25%',
                                background: (() => {
                                  const map = {
                                    high: 'linear-gradient(90deg, #22C55E, #4ADE80)',
                                    medium: 'linear-gradient(90deg, #F59E0B, #FBBF24)',
                                    low: 'linear-gradient(90deg, #EF4444, #F87171)',
                                  };
                                  return map[insight.evidence_quality] || '#666';
                                })(),
                                transition: 'width 0.8s cubic-bezier(0.16, 1, 0.3, 1)',
                              }} />
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Supervisor 분석 텍스트 */}
                      {insight.supervisor_text && (
                        <div className="detail-section" style={{
                          marginBottom: '1rem',
                          borderLeft: '4px solid #8B5CF6',
                          background: 'rgba(139, 92, 246, 0.03)',
                        }}>
                          <h3 style={{ color: '#A78BFA', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                            <Shield size={14} strokeWidth={2} /> Supervisor 감독 분석
                          </h3>
                          <p style={{
                            fontSize: '0.88rem', lineHeight: 1.85,
                            whiteSpace: 'pre-wrap', color: 'var(--omega-text-secondary)',
                          }}>
                            {insight.supervisor_text}
                          </p>
                        </div>
                      )}
                    </div>
                  )}

                  {/* 면책 문구 */}
                  <div style={{
                    marginTop: '1.5rem', padding: '1rem',
                    background: 'rgba(100,100,100,0.08)', borderRadius: '8px',
                    fontSize: '0.75rem', color: 'var(--omega-text-muted)', lineHeight: 1.6,
                  }}>
                    ⚖️ 본 분석은 공시 정보에 기반한 AI 생성 참고 자료이며, 투자 자문이나 매수·매도 권유가 아닙니다.
                    투자 결정은 반드시 본인의 판단과 책임하에 이루어져야 합니다.
                    정확한 정보는 원본 공시문서를 반드시 확인하시기 바랍니다.
                  </div>
                </div>
              ) : (
                /* Insight 없을 때 — 생성 유도 */
                <div style={{
                  textAlign: 'center', padding: '3rem 2rem',
                  background: 'rgba(245, 158, 11, 0.05)',
                  borderRadius: '12px', border: '1px dashed rgba(245, 158, 11, 0.3)',
                }}>
                  <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>
                    <Zap size={40} strokeWidth={1.2} style={{ color: '#f59e0b', opacity: 0.7 }} />
                  </div>
                  <h3 style={{ color: '#f59e0b', marginBottom: '0.5rem' }}>전략 Insight 생성</h3>
                  <p style={{ color: 'var(--omega-text-muted)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
                    Gemini 2.5 Pro가 이 공시문서를 한국 증시 관점에서 분석합니다.
                    <br />투자 시사점, 시장 컨텍스트, 리스크 팩터, 전략적 행동 지침을 제공합니다.
                  </p>
                  <button
                    onClick={generateInsight}
                    className="btn btn-primary"
                    style={{
                      background: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
                      border: 'none', padding: '0.8rem 2rem', fontSize: '1rem', fontWeight: 600,
                      display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
                    }}
                  >
                    <Zap size={16} strokeWidth={2} /> Insight 생성하기
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* OCR 텍스트 */}
      {ocr_texts && ocr_texts.length > 0 && (
        <div className="detail-section slide-up" style={{ marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <h3 style={{ marginBottom: 0 }}>📖 OCR 추출 텍스트</h3>
            <button
              className="btn btn-sm btn-secondary"
              id="download-ocr-btn"
              onClick={() => {
                const allText = ocr_texts
                  .map((ocr) => {
                    const header = ocr.page_number
                      ? `===== 페이지 ${ocr.page_number} (신뢰도: ${(ocr.confidence * 100).toFixed(1)}%) =====`
                      : '';
                    const body = ocr.cleaned_text || ocr.raw_text || '';
                    return header ? `${header}\n${body}` : body;
                  })
                  .join('\n\n');
                const blob = new Blob([allText], { type: 'text/plain;charset=utf-8' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${correctFilenameCompany(doc.filename, company_name).replace(/\.[^/.]+$/, '')}_OCR텍스트.txt`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
              }}
              style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}
            >
              📥 다운로드
            </button>
          </div>
          {ocr_texts.map((ocr) => (
            <div key={ocr.id} style={{ marginBottom: '1rem', marginTop: '1rem' }}>
              {ocr.page_number && (
                <div style={{ fontSize: '0.8rem', color: 'var(--omega-text-muted)', marginBottom: '0.5rem' }}>
                  페이지 {ocr.page_number} · 신뢰도: {(ocr.confidence * 100).toFixed(1)}%
                </div>
              )}
              <div className="ocr-text-box">
                {ocr.cleaned_text || ocr.raw_text || '(텍스트 없음)'}
              </div>
            </div>
          ))}
        </div>
      )}

      {!analysis && doc.status !== 'analyzed' && (
        <div className="alert alert-info">
          ℹ️ 이 문서는 아직 LLM 분석이 완료되지 않았습니다. 상태: {status.label}
        </div>
      )}
    </div>
  );
}
