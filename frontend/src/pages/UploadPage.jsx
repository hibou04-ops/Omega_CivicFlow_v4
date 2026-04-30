import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import JSZip from 'jszip';
import { documentsAPI } from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { correctFilenameCompany } from '../utils/categoryTranslation';

const MAX_FILES = 20;
const ZIP_THRESHOLD = 20;
const POLL_INTERVAL = 3000;
const DOC_EXTS = new Set(['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.hwp', '.txt', '.png', '.jpg', '.jpeg', '.xbrl', '.xml', '.xsd', '.html', '.htm']);

const MIME_MAP = {
  '.pdf': 'application/pdf', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.doc': 'application/msword', '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.xls': 'application/vnd.ms-excel', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.hwp': 'application/x-hwp', '.txt': 'text/plain',
  '.xbrl': 'application/xml', '.xml': 'application/xml', '.xsd': 'application/xml',
  '.html': 'text/html', '.htm': 'text/html',
};

const getExt = (name) => {
  const parts = name.toLowerCase().split('.');
  return parts.length > 1 ? '.' + parts[parts.length - 1] : '';
};

// ZIP 파일 여부 판별 (magic bytes — .zip.pdf 같은 이중 확장자도 대응)
const isZipFile = async (file) => {
  if (file.name.toLowerCase().endsWith('.zip')) return true;
  try {
    const buf = await file.slice(0, 4).arrayBuffer();
    const b = new Uint8Array(buf);
    return b[0] === 0x50 && b[1] === 0x4B && b[2] === 0x03 && b[3] === 0x04;
  } catch { return false; }
};

export default function UploadPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const fileInputRef = useRef(null);
  const pollTimerRef = useRef(null);

  const [files, setFiles]         = useState([]);
  const [dragging, setDragging]   = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError]         = useState('');
  const [sendEmail, setSendEmail] = useState(false);

  // ZIP 선택 모달
  const [zipModal, setZipModal]   = useState(null); // { zipFile, docEntries }
  const [zipSelected, setZipSelected] = useState(new Set());

  // 비동기 결과
  const [batchDocs, setBatchDocs] = useState(null);
  const [docIds, setDocIds]       = useState([]);
  const [pollResults, setPollResults] = useState(null);
  const [polling, setPolling]     = useState(false);

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  };
  const totalSize = files.reduce((s, f) => s + f.size, 0);

  // ── ZIP 처리 ──────────────────────────────────────────────
  const processZip = async (file) => {
    try {
      const zip = await JSZip.loadAsync(file);
      const entries = [];
      zip.forEach((path, entry) => {
        if (!entry.dir && DOC_EXTS.has(getExt(path))) {
          entries.push({ path, entry });
        }
      });

      if (entries.length === 0) {
        setError('ZIP 파일 내에 지원되는 문서가 없습니다.');
        return;
      }

      if (entries.length <= ZIP_THRESHOLD) {
        // 20개 이하 → 전체 자동 추출
        const extracted = [];
        const zipBaseName = file.name.replace(/\.zip(\.pdf)?$/i, '');
        for (const { path, entry } of entries) {
          const blob = await entry.async('blob');
          let fname = path.split('/').pop();
          const ext = getExt(fname);
          fname = `${zipBaseName}_${fname}`;
          extracted.push(new File([blob], fname, { type: MIME_MAP[ext] || 'application/octet-stream' }));
        }
        addExtractedFiles(extracted);
      } else {
        // 20개 초과 → 선택 모달 (PDF 우선 정렬)
        const sorted = entries.sort((a, b) => {
          const ap = getExt(a.path) === '.pdf' ? 0 : 1;
          const bp = getExt(b.path) === '.pdf' ? 0 : 1;
          return ap - bp;
        });
        // PDF는 기본 선택
        const defaultSelected = new Set(
          sorted.filter(e => getExt(e.path) === '.pdf').map(e => e.path)
        );
        setZipModal({ zipFile: file, docEntries: sorted });
        setZipSelected(defaultSelected);
      }
    } catch (e) {
      setError('ZIP 파일을 읽을 수 없습니다: ' + e.message);
    }
  };

  const addExtractedFiles = (newFiles) => {
    setFiles(prev => {
      const combined = [...prev, ...newFiles];
      if (combined.length > MAX_FILES) {
        setError(`최대 ${MAX_FILES}개까지 선택 가능합니다. (${combined.length - MAX_FILES}개 초과)`);
        return prev;
      }
      return combined;
    });
    setError('');
  };

  // ZIP 선택 확인
  const confirmZipSelection = async () => {
    if (!zipModal || zipSelected.size === 0) return;
    const selected = zipModal.docEntries.filter(e => zipSelected.has(e.path));
    const extracted = [];
    const zipBaseName = zipModal.zipFile.name.replace(/\.zip(\.pdf)?$/i, '');
    for (const { path, entry } of selected) {
      const blob = await entry.async('blob');
      let fname = path.split('/').pop();
      const ext = getExt(fname);
      fname = `${zipBaseName}_${fname}`;
      extracted.push(new File([blob], fname, { type: MIME_MAP[ext] || 'application/octet-stream' }));
    }
    addExtractedFiles(extracted);
    setZipModal(null);
    setZipSelected(new Set());
  };

  // ── 파일 추가 ─────────────────────────────────────────────
  const addFiles = async (rawFiles) => {
    const arr = Array.from(rawFiles);
    for (const file of arr) {
      const ext = getExt(file.name);

      // .zip.pdf 같은 이중확장자: 마지막 확장자가 .pdf → 서버가 ZIP 감지 처리
      // 일반 .pdf도 동일하게 직접 업로드
      if (ext === '.pdf') {
        addExtractedFiles([file]);
        continue;
      }

      if (await isZipFile(file)) {
        // DART XBRL ZIP: .xbrl 파일이 포함된 ZIP은 서버에서 직접 처리
        try {
          const zip = await JSZip.loadAsync(file);
          const hasXbrl = Object.keys(zip.files).some(n => n.endsWith('.xbrl'));
          if (hasXbrl) {
            // DART XBRL ZIP → 서버에 통째로 전송 (label+data 연관 유지)
            addExtractedFiles([new File([await file.arrayBuffer()], file.name, { type: 'application/zip' })]);
            continue;
          }
        } catch {}
        await processZip(file);
      } else if (ext === '.xls' || ext === '.xlsx') {
        // XLS/XLSX → 직접 업로드 (서버에서 xlrd/openpyxl 처리)
        addExtractedFiles([file]);
      } else {
        if (DOC_EXTS.has(ext)) {
          addExtractedFiles([file]);
        } else {
          setError(`지원하지 않는 파일 형식: ${file.name}`);
        }
      }
    }
  };

  // ── 드래그 ────────────────────────────────────────────────
  const handleDrag    = (e) => { e.preventDefault(); e.stopPropagation(); };
  const handleDragIn  = (e) => { e.preventDefault(); setDragging(true); };
  const handleDragOut = (e) => { e.preventDefault(); setDragging(false); };
  const handleDrop    = (e) => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files); };
  const handleFileSelect = (e) => { if (e.target.files?.length) addFiles(e.target.files); e.target.value = ''; };

  const removeFile = (i) => { setFiles(files.filter((_, idx) => idx !== i)); setError(''); };
  const clearAll = () => {
    setFiles([]); setError('');
    setBatchDocs(null); setDocIds([]); setPollResults(null); setPolling(false);
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
  };

  // ── 폴링 ─────────────────────────────────────────────────
  const pollStatus = useCallback(async (ids) => {
    try {
      const res = await documentsAPI.batchStatus(ids.join(','));
      setPollResults(res.data);
      if (res.data.all_done) { setPolling(false); if (pollTimerRef.current) clearInterval(pollTimerRef.current); }
    } catch {}
  }, []);

  useEffect(() => () => { if (pollTimerRef.current) clearInterval(pollTimerRef.current); }, []);

  // ── 업로드 ────────────────────────────────────────────────
  const handleUpload = async () => {
    if (!files.length) return;
    setUploading(true); setError(''); setBatchDocs(null); setDocIds([]); setPollResults(null);
    try {
      const res = await documentsAPI.uploadBatch(files, sendEmail);
      const data = res.data;
      setBatchDocs(data.documents);
      const ids = data.documents.filter(d => d.id > 0).map(d => String(d.id));
      setDocIds(ids); setUploading(false);
      if (ids.length > 0) {
        setPolling(true); pollStatus(ids);
        pollTimerRef.current = setInterval(() => pollStatus(ids), POLL_INTERVAL);
      }
    } catch (err) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail || '업로드 중 오류가 발생했습니다.';
      if (status === 409) {
        // 중복 업로드 감지
        const idMatch = detail.match(/#(\d+)/);
        const docId = idMatch ? idMatch[1] : null;
        setError(
          `📋 ${detail}` +
          (docId ? ` — 해당 문서를 확인하려면 '내 문서'에서 #${docId}을 열어보세요.` : '')
        );
      } else {
        setError(detail);
      }
      setUploading(false);
    }
  };

  const completedCount  = pollResults ? pollResults.completed : 0;
  const totalDocs       = docIds.length;
  const progressPercent = totalDocs > 0 ? Math.round((completedCount / totalDocs) * 100) : 0;
  const allDone         = pollResults?.all_done || false;

  // ── ZIP 선택 모달 ─────────────────────────────────────────
  const ZipModal = () => {
    if (!zipModal) return null;
    const { docEntries } = zipModal;
    const pdfCount = docEntries.filter(e => getExt(e.path) === '.pdf').length;

    return (
      <div className="modal-overlay" onClick={() => setZipModal(null)}>
        <div onClick={e => e.stopPropagation()} style={{
          background: '#0D0D0D', border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: '14px', padding: '2rem', maxWidth: '560px', width: '90%',
          maxHeight: '80vh', display: 'flex', flexDirection: 'column', gap: '1rem',
        }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: '1.1rem', marginBottom: '4px' }}>
              📦 ZIP 파일 내 문서 선택
            </div>
            <div style={{ fontSize: '0.82rem', color: 'var(--omega-text-secondary)' }}>
              총 {docEntries.length}개 파일 발견 · PDF {pdfCount}개 자동 선택됨
            </div>
          </div>

          {/* 전체 선택/해제 */}
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="btn btn-secondary btn-sm" onClick={() => setZipSelected(new Set(docEntries.map(e => e.path)))}>전체 선택</button>
            <button className="btn btn-secondary btn-sm" onClick={() => setZipSelected(new Set())}>전체 해제</button>
            <button className="btn btn-secondary btn-sm" onClick={() => setZipSelected(new Set(docEntries.filter(e => getExt(e.path) === '.pdf').map(e => e.path)))}>PDF만</button>
          </div>

          {/* 파일 목록 */}
          <div style={{ overflowY: 'auto', flex: 1, maxHeight: '360px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {docEntries.map(({ path }) => {
              const fname = path.split('/').pop();
              const ext = getExt(fname);
              const isPdf = ext === '.pdf';
              const checked = zipSelected.has(path);
              return (
                <label key={path} style={{
                  display: 'flex', alignItems: 'center', gap: '10px',
                  padding: '8px 12px', borderRadius: '8px', cursor: 'pointer',
                  background: checked ? 'rgba(255,255,255,0.04)' : 'transparent',
                  border: `1px solid ${checked ? 'rgba(255,255,255,0.12)' : 'transparent'}`,
                  transition: 'all 0.15s',
                }}>
                  <input type="checkbox" checked={checked}
                    onChange={e => {
                      const s = new Set(zipSelected);
                      e.target.checked ? s.add(path) : s.delete(path);
                      setZipSelected(s);
                    }}
                    style={{ accentColor: '#FFFFFF', width: 15, height: 15 }}
                  />
                  <span style={{ fontSize: '0.85rem', flex: 1, wordBreak: 'break-all' }}>
                    {isPdf && <span style={{ color: '#C0A060', marginRight: 4, fontSize: '0.75rem', fontWeight: 600 }}>PDF</span>}
                    {fname}
                  </span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--omega-text-secondary)', whiteSpace: 'nowrap' }}>
                    {ext.slice(1).toUpperCase()}
                  </span>
                </label>
              );
            })}
          </div>

          {/* 확인/취소 */}
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary" onClick={() => setZipModal(null)}>취소</button>
            <button className="btn btn-primary" onClick={confirmZipSelection} disabled={zipSelected.size === 0}>
              {zipSelected.size}개 파일 추가
            </button>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="page-container fade-in">
      <ZipModal />

      <div className="page-header">
        <h1>📤 문서 업로드</h1>
        <p>최대 {MAX_FILES}개 문서 업로드 — ZIP/이중확장자(.zip.pdf) 자동 인식 · OCR + LLM 분석</p>
      </div>

      {error && <div className="alert alert-error">⚠️ {error}</div>}

      {/* 결과 카드 */}
      {batchDocs && (
        <div className="card" style={{ marginBottom: '1.5rem', borderLeft: '4px solid var(--omega-accent)' }}>
          <div className="card-header">
            <div>
              <div className="card-title" style={{ fontSize: '1.1rem' }}>
                {allDone ? `✅ 분석 완료 — ${completedCount}건 처리됨` : `🔄 분석 중... ${completedCount}/${totalDocs}건 완료`}
              </div>
              {polling && (
                <div style={{ fontSize: '0.8rem', color: 'var(--omega-secondary)', marginTop: '4px' }}>
                  <span className="spinner" style={{ width: 12, height: 12, borderWidth: 1.5, marginRight: 6 }}></span>
                  백그라운드 분석 중 (자동 갱신)
                </div>
              )}
            </div>
            {allDone && <button className="btn btn-secondary btn-sm" onClick={() => navigate('/mypage')}>📋 내 문서 보기</button>}
          </div>

          {totalDocs > 0 && (
            <div style={{ marginBottom: '1rem' }}>
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${progressPercent}%`, transition: 'width 0.5s ease' }}></div>
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--omega-text-muted)', textAlign: 'center' }}>
                {progressPercent}% ({completedCount}/{totalDocs})
              </div>
            </div>
          )}

          <div style={{ maxHeight: '400px', overflowY: 'auto', padding: '0.5rem' }}>
            {(pollResults?.documents?.length > 0 ? pollResults.documents : batchDocs).map((doc, i) => {
              const status = doc.status || 'pending';
              const isAnalyzed = status === 'analyzed';
              const isFailed = status === 'failed' || status === 'rejected';
              const PROGRESS_STEPS = {
                pending:      { pct: 5,   label: '⏳ 대기' },
                uploaded:     { pct: 5,   label: '⏳ 대기' },
                ocr_running:  { pct: 25,  label: '📄 OCR 실행중' },
                ocr_done:     { pct: 50,  label: '✨ OCR 완료 · 전처리' },
                analyzing:    { pct: 80,  label: '🧠 AI 분석중' },
                analyzed:     { pct: 100, label: '✅ 완료' },
              };
              const prog = isFailed ? null : (PROGRESS_STEPS[status] || { pct: 15, label: '🔄 처리중' });
              return (
                <div key={i} style={{
                  padding: '12px 16px', marginBottom: '8px', borderRadius: '8px',
                  background: isFailed ? 'rgba(184,67,67,0.1)' : isAnalyzed ? 'rgba(61,138,72,0.08)' : 'rgba(255,255,255,0.03)',
                  borderLeft: `3px solid ${isFailed ? '#B84343' : isAnalyzed ? '#3D8A48' : '#555'}`,
                  cursor: isAnalyzed ? 'pointer' : 'default',
                }} onClick={() => doc.id > 0 && isAnalyzed && navigate(`/documents/${doc.id}`)}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600, marginBottom: '4px' }}>📄 {correctFilenameCompany(doc.filename, doc.company_name)}</div>
                      {doc.category && isAnalyzed && (
                        <span style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '4px', background: 'rgba(61,138,72,0.15)', color: '#3D8A48' }}>
                          {doc.category}
                        </span>
                      )}
                      {doc.summary && (
                        <div style={{ fontSize: '0.85rem', color: 'var(--omega-text-secondary)', marginTop: '6px', lineHeight: '1.4' }}>
                          {doc.summary?.length > 120 ? doc.summary.slice(0, 120) + '…' : doc.summary}
                        </div>
                      )}
                    </div>
                    <span style={{
                      fontSize: '0.75rem', padding: '2px 8px', borderRadius: '4px',
                      background: isAnalyzed ? 'rgba(61,138,72,0.15)' : isFailed ? 'rgba(184,67,67,0.15)' : 'rgba(192,160,96,0.1)',
                      color: isAnalyzed ? '#3D8A48' : isFailed ? '#B84343' : 'rgba(192,160,96,0.85)',
                      whiteSpace: 'nowrap', marginLeft: '12px',
                    }}>
                      {isFailed ? '❌ 실패' : prog.label}
                    </span>
                  </div>
                  {prog && !isFailed && (
                    <div style={{ marginTop: '10px' }}>
                      <div style={{
                        height: 6, width: '100%',
                        background: 'rgba(255,255,255,0.05)',
                        borderRadius: 3,
                        overflow: 'hidden',
                      }}>
                        <div style={{
                          height: '100%',
                          width: `${prog.pct}%`,
                          background: isAnalyzed
                            ? 'linear-gradient(90deg, #3D8A48, #5BAE66)'
                            : 'linear-gradient(90deg, rgba(192,160,96,0.9), rgba(192,160,96,0.55))',
                          transition: 'width 0.8s cubic-bezier(0.16, 1, 0.3, 1)',
                          boxShadow: isAnalyzed
                            ? '0 0 8px rgba(61,138,72,0.4)'
                            : '0 0 8px rgba(192,160,96,0.3)',
                        }} />
                      </div>
                      <div style={{
                        fontSize: '0.68rem',
                        color: isAnalyzed ? 'rgba(91,174,102,0.8)' : 'rgba(192,160,96,0.6)',
                        marginTop: '4px',
                        textAlign: 'right',
                        fontVariantNumeric: 'tabular-nums',
                      }}>
                        {prog.pct}%
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {allDone && (
            <div style={{ padding: '0.5rem', textAlign: 'center' }}>
              <button className="btn btn-primary" onClick={clearAll}>🔄 새 업로드</button>
            </div>
          )}
        </div>
      )}

      {/* 업로드 존 */}
      {!batchDocs && (
        <>
          <div
            className={`upload-zone ${dragging ? 'dragging' : ''}`}
            onDragEnter={handleDragIn} onDragLeave={handleDragOut}
            onDragOver={handleDrag} onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <span className="upload-icon">📄</span>
            <h3>파일을 드래그하거나 클릭하여 선택</h3>
            <p>지원: PDF · HTML · XBRL · XLS · XML · ZIP · <strong style={{ color: 'var(--omega-text-secondary)' }}>DART 공시 전체 형식</strong> (최대 50MB)</p>
            <div style={{ marginTop: '0.75rem', fontSize: '0.78rem', color: 'var(--omega-text-muted)' }}>
              ZIP 내 20개 이하 → 자동 추출 &nbsp;·&nbsp; 20개 초과 → PDF 우선 선택창
            </div>
            <input
              ref={fileInputRef} type="file"
              accept=".pdf,.html,.htm,.jpg,.jpeg,.png,.docx,.doc,.xlsx,.xls,.hwp,.txt,.zip,.xml,.xbrl,.xsd"
              multiple onChange={handleFileSelect} style={{ display: 'none' }}
            />
          </div>

          {/* 파일 목록 */}
          {files.length > 0 && (
            <div className="card" style={{ marginTop: '1.5rem' }}>
              <div className="card-header">
                <div className="card-title">
                  📎 {files.length}개 파일 선택됨
                  <span style={{ fontSize: '0.8rem', color: 'var(--omega-text-muted)', marginLeft: '0.5rem' }}>({formatSize(totalSize)})</span>
                </div>
                <button className="btn btn-secondary btn-sm" onClick={clearAll} disabled={uploading}>전체 취소</button>
              </div>

              <div style={{ maxHeight: '250px', overflowY: 'auto', padding: '0.5rem', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                {files.map((file, i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '8px 12px', borderRadius: '6px', marginBottom: '4px',
                    background: 'rgba(255,255,255,0.03)',
                  }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: '0.9rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{file.name}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--omega-text-muted)' }}>{formatSize(file.size)}</div>
                    </div>
                    <button onClick={(e) => { e.stopPropagation(); removeFile(i); }} disabled={uploading}
                      style={{ background: 'none', border: 'none', color: '#666', cursor: 'pointer', fontSize: '1.1rem', padding: '4px 8px' }}>✕</button>
                  </div>
                ))}
              </div>

              {/* 이메일 토글 */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <div>
                  <div style={{ fontSize: '0.9rem', fontWeight: 500 }}>📧 분석 결과 이메일 수신</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--omega-text-muted)' }}>{user?.email || '이메일 주소'}로 분석 결과 전송</div>
                </div>
                <label style={{ position: 'relative', display: 'inline-block', width: '48px', height: '26px', cursor: 'pointer' }}>
                  <input type="checkbox" checked={sendEmail} onChange={e => setSendEmail(e.target.checked)} disabled={uploading} style={{ opacity: 0, width: 0, height: 0 }} />
                  <span style={{ position: 'absolute', inset: 0, borderRadius: '13px', background: sendEmail ? '#FFFFFF' : '#2A2A2A', transition: 'all 0.3s' }}>
                    <span style={{ position: 'absolute', top: '3px', left: sendEmail ? '25px' : '3px', width: '20px', height: '20px', borderRadius: '50%', background: sendEmail ? '#050505' : '#666', transition: 'left 0.3s', boxShadow: '0 1px 3px rgba(0,0,0,0.3)' }} />
                  </span>
                </label>
              </div>

              {/* 업로드 버튼 */}
              <div style={{ padding: '12px 16px', display: 'flex', justifyContent: 'center' }}>
                <button className="btn btn-primary" onClick={handleUpload} disabled={uploading} style={{ minWidth: '200px' }}>
                  {uploading ? <><span className="spinner"></span> 업로드 중...</> : `🚀 ${files.length}건 업로드`}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
