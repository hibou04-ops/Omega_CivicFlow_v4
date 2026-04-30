import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { adminAPI, documentsAPI } from '../api/client';
import { LayoutDashboard, Users, Zap, FileText, ChevronRight, RefreshCw, Trash2 } from 'lucide-react';
import { translateCategory, deduplicateCategories, parseDisplayFilename } from '../utils/categoryTranslation';

/* ═══════════════════════════════════════════════════════
   Status badge map for documents
   ═══════════════════════════════════════════════════════ */
const STATUS_MAP = {
  uploaded: { label: '업로드', class: 'badge-info' },
  ocr_done: { label: 'OCR 완료', class: 'badge-warning' },
  analyzed: { label: '분석 완료', class: 'badge-success' },
  failed: { label: '실패', class: 'badge-danger' },
};

/* ═══════════════════════════════════════════════════════
   Tab definitions (대시보드+전체문서 merged → 문서관리)
   ═══════════════════════════════════════════════════════ */
const TABS = [
  { key: 'dashboard', label: '문서관리', Icon: LayoutDashboard },
  { key: 'users',     label: '회원관리', Icon: Users },
];

const CHART_COLORS = [
  '#6C63FF', '#FF6B6B', '#4ECDC4', '#FFD93D', '#FF8C42',
  '#A8E6CF', '#DDA0F5', '#45B7D1', '#F78C6C', '#96CEB4',
  '#FFEAA7', '#74B9FF', '#FD79A8', '#55E6C1', '#F8A5C2',
];



export default function AdminDashboard() {
  const [activeTab, setActiveTab] = useState('dashboard');

  // Dashboard state
  const [dashboard, setDashboard] = useState(null);
  const [dashLoading, setDashLoading] = useState(true);

  // Category tab state
  const [activeCategory, setActiveCategory] = useState('전체');
  const [categoryDocs, setCategoryDocs] = useState([]);
  const [categoryDocsLoading, setCategoryDocsLoading] = useState(false);

  // Reclassify modal
  const [reclassModal, setReclassModal] = useState(null);
  const [newCategory, setNewCategory] = useState('');
  const [reason, setReason] = useState('');

  // Users state
  const [users, setUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersLoaded, setUsersLoaded] = useState(false);

  // Filename display toggle
  const [showOriginalFilename, setShowOriginalFilename] = useState(false);

  // Document search & pagination
  const [adminSearchQuery, setAdminSearchQuery] = useState('');
  const [adminPageSize, setAdminPageSize] = useState(100);
  const [adminCurrentPage, setAdminCurrentPage] = useState(1);

  /* ── Load dashboard on mount ── */
  useEffect(() => {
    loadDashboard();
  }, []);

  /* ── Lazy load tab data ── */
  useEffect(() => {
    if (activeTab === 'users' && !usersLoaded) {
      loadUsers();
    }
  }, [activeTab]);

  /* ── Load category docs when activeCategory changes ── */
  useEffect(() => {
    if (dashboard) {
      loadCategoryDocs(activeCategory);
    }
  }, [activeCategory, dashboard]);

  /* ═══════════════════════════════════════════════════════
     Data loaders
     ═══════════════════════════════════════════════════════ */
  const loadDashboard = async () => {
    try {
      const res = await adminAPI.getDashboard();
      setDashboard(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setDashLoading(false);
    }
  };

  const loadCategoryDocs = async (category) => {
    setCategoryDocsLoading(true);
    try {
      const res = await adminAPI.listDocumentsByCategory(category);
      setCategoryDocs(res.data.documents || []);
    } catch (err) {
      console.error(err);
      setCategoryDocs([]);
    } finally {
      setCategoryDocsLoading(false);
    }
  };

  const loadUsers = async () => {
    setUsersLoading(true);
    try {
      const res = await adminAPI.listUsers();
      setUsers(res.data);
      setUsersLoaded(true);
    } catch (err) {
      console.error(err);
    } finally {
      setUsersLoading(false);
    }
  };

  /* ═══════════════════════════════════════════════════════
     Actions
     ═══════════════════════════════════════════════════════ */
  const handleReclassify = async () => {
    if (!newCategory.trim()) return;
    try {
      await adminAPI.reclassify(reclassModal, {
        new_category: newCategory,
        reason: reason || null,
      });
      setReclassModal(null);
      setNewCategory('');
      setReason('');
      loadDashboard();
      loadCategoryDocs(activeCategory);
      alert('재분류가 완료되었습니다.');
    } catch (err) {
      alert(err.response?.data?.detail || '재분류 실패');
    }
  };

  const handleDeleteDocument = async (docId, filename) => {
    if (!confirm(`문서 #${docId} (${filename})을(를) 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.`)) return;
    try {
      await documentsAPI.delete(docId);
      loadDashboard();
      loadCategoryDocs(activeCategory);
    } catch (err) {
      alert(err.response?.data?.detail || '삭제 실패');
    }
  };

  const handleActiveToggle = async (userId, currentActive) => {
    try {
      const res = await adminAPI.updateUserActive(userId, !currentActive);
      setUsers(users.map(u => u.id === userId ? res.data : u));
    } catch (err) {
      alert(err.response?.data?.detail || '상태 변경 실패');
    }
  };

  /* ═══════════════════════════════════════════════════════
     Formatters
     ═══════════════════════════════════════════════════════ */
  const formatDate = (dateStr) =>
    new Date(dateStr).toLocaleString('ko-KR', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  };


  /* ═══════════════════════════════════════════════════════
     TAB PANELS
     ═══════════════════════════════════════════════════════ */

  /* ── Dashboard + Documents (merged) Panel ── */
  const renderDashboard = () => {
    if (dashLoading) {
      return (
        <div className="loading-container">
          <div className="spinner spinner-lg"></div>
          <p>대시보드 로딩 중...</p>
        </div>
      );
    }
    if (!dashboard) return null;

    const dedupedStats = deduplicateCategories(dashboard.category_stats);
    const allCategories = [
      { category: '전체', count: dashboard.total_documents },
      ...dedupedStats,
    ];

    // Bar chart data — sorted by count descending
    const barStats = dedupedStats
      .filter((s) => s.count > 0)
      .sort((a, b) => b.count - a.count);
    const maxCount = barStats.length > 0 ? barStats[0].count : 1;

    return (
      <div className="fade-in">
        {/* Stats Grid */}
        <div className="stats-grid">
          <div className="stat-card primary slide-up stagger-1" id="stat-total-docs">
            <div className="stat-label">전체 문서</div>
            <div className="stat-value">{dashboard.total_documents}</div>
          </div>
          <div className="stat-card success slide-up stagger-2" id="stat-analyzed">
            <div className="stat-label">분석 완료</div>
            <div className="stat-value">{dashboard.total_analyzed}</div>
          </div>
          <div className="stat-card warning slide-up stagger-3" id="stat-pending">
            <div className="stat-label">대기 중</div>
            <div className="stat-value">{dashboard.total_pending}</div>
          </div>
          <div className="stat-card secondary slide-up stagger-4" id="stat-total-users">
            <div className="stat-label">전체 회원</div>
            <div className="stat-value">{dashboard.total_users}</div>
          </div>
        </div>

        {/* ── Horizontal Bar Chart (sorted by count desc) ── */}
        {barStats.length > 0 && (
          <div className="card slide-up" style={{ marginTop: '1.5rem', padding: '1.5rem' }}>
            <h3 style={{ marginBottom: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              📊 카테고리 분포
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
              {barStats.map((s, i) => {
                const pct = (s.count / maxCount) * 100;
                const color = CHART_COLORS[i % CHART_COLORS.length];
                return (
                  <div
                    key={s.category}
                    onClick={() => setActiveCategory(s.category)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: '0.75rem',
                      cursor: 'pointer', padding: '0.3rem 0',
                      opacity: activeCategory === s.category ? 1 : 0.85,
                      transition: 'opacity 0.2s',
                    }}
                  >
                    <span style={{
                      width: '110px', flexShrink: 0, fontSize: '0.82rem',
                      fontWeight: activeCategory === s.category ? 700 : 500,
                      color: activeCategory === s.category ? color : 'var(--omega-text)',
                      textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}>
                      {s.category}
                    </span>
                    <div style={{
                      flex: 1, height: '22px', borderRadius: '4px',
                      background: 'rgba(255,255,255,0.04)',
                      overflow: 'hidden', position: 'relative',
                    }}>
                      <div style={{
                        width: `${pct}%`, height: '100%',
                        background: `linear-gradient(90deg, ${color}, ${color}dd)`,
                        borderRadius: '4px',
                        transition: 'width 0.6s ease',
                        minWidth: '2px',
                      }} />
                    </div>
                    <span style={{
                      width: '70px', flexShrink: 0, fontSize: '0.8rem',
                      fontWeight: 600, color: 'var(--omega-text-muted)',
                      fontVariantNumeric: 'tabular-nums', textAlign: 'right',
                    }}>
                      {s.count}건
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Reclassify Modal */}
        {reclassModal && (
          <div
            className="modal-overlay"
            onClick={() => setReclassModal(null)}
          >
            <div
              className="card-glass"
              style={{ width: '100%', maxWidth: '480px', padding: '2rem' }}
              onClick={(e) => e.stopPropagation()}
            >
              <h3 style={{ marginBottom: '1.5rem', color: 'var(--omega-primary-light)' }}>
                🔄 문서 재분류 (#{reclassModal})
              </h3>

              <div className="form-group">
                <label className="form-label">새 카테고리 *</label>
                <select
                  className="form-input"
                  value={newCategory}
                  onChange={(e) => setNewCategory(e.target.value)}
                  id="reclass-category-select"
                >
                  <option value="">선택하세요</option>
                  <option value="도로/교통">도로/교통</option>
                  <option value="환경/위생">환경/위생</option>
                  <option value="복지/보건">복지/보건</option>
                  <option value="건축/주택">건축/주택</option>
                  <option value="세금/재정">세금/재정</option>
                  <option value="교육/문화">교육/문화</option>
                  <option value="안전/재난">안전/재난</option>
                  <option value="민원행정">민원행정</option>
                  <option value="기타">기타</option>
                </select>
              </div>

              <div className="form-group">
                <label className="form-label">재분류 사유</label>
                <input
                  className="form-input"
                  placeholder="변경 사유를 입력하세요"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  id="reclass-reason-input"
                />
              </div>

              <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                <button className="btn btn-secondary" onClick={() => setReclassModal(null)}>
                  취소
                </button>
                <button className="btn btn-primary" onClick={handleReclassify} id="reclass-submit-btn">
                  재분류 적용
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Category Tabs + Document List */}
        <div className="detail-section slide-up" style={{ marginTop: '1.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
            <h3>📂 카테고리별 문서</h3>
            <button className="btn btn-sm btn-secondary" onClick={() => { loadDashboard(); loadCategoryDocs(activeCategory); }} id="refresh-docs-btn"
              style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <RefreshCw size={13} /> 새로고침
            </button>
          </div>

          {/* Category Tab Buttons */}
          <div style={{
            display: 'flex', flexWrap: 'wrap', gap: '0.5rem',
            marginBottom: '1rem', paddingBottom: '0.75rem',
            borderBottom: '1px solid var(--omega-border)',
          }}>
            {allCategories.map((stat) => (
              <button
                key={stat.category}
                id={`cat-tab-${stat.category}`}
                onClick={() => setActiveCategory(stat.category)}
                style={{
                  padding: '0.5rem 1rem',
                  borderRadius: 'var(--radius-sm)',
                  border: activeCategory === stat.category
                    ? '2px solid var(--omega-primary-light)'
                    : '1px solid var(--omega-border)',
                  background: activeCategory === stat.category
                    ? 'var(--omega-primary-light)'
                    : 'var(--omega-surface-2)',
                  color: activeCategory === stat.category
                    ? '#fff'
                    : 'var(--omega-text-secondary)',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: activeCategory === stat.category ? 600 : 400,
                  transition: 'all 0.2s ease',
                  display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
                }}
              >
                {stat.category}
                <span style={{
                  background: activeCategory === stat.category
                    ? 'rgba(255,255,255,0.25)'
                    : 'var(--omega-surface-3, rgba(255,255,255,0.08))',
                  padding: '0.1rem 0.45rem',
                  borderRadius: '999px',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                }}>
                  {stat.count}
                </span>
              </button>
            ))}
          </div>

          {/* ── 문서 검색 ── */}
          <div style={{ marginBottom: '0.75rem' }}>
            <input
              type="text"
              placeholder="🔍 문서 검색 (ID, 파일명, 회사명...)"
              value={adminSearchQuery}
              onChange={(e) => setAdminSearchQuery(e.target.value)}
              style={{
                width: '100%', padding: '0.6rem 1rem', fontSize: '0.85rem',
                background: 'var(--omega-surface-2)', color: 'var(--omega-text)',
                border: '1px solid var(--omega-border)', borderRadius: 'var(--radius-sm)',
                outline: 'none', transition: 'border-color 0.2s',
              }}
              onFocus={(e) => e.target.style.borderColor = 'var(--omega-primary-light)'}
              onBlur={(e) => e.target.style.borderColor = 'var(--omega-border)'}
            />
          </div>

          {/* Document Table for Selected Category */}
          {categoryDocsLoading ? (
            <div style={{ textAlign: 'center', padding: '2rem' }}>
              <div className="spinner"></div>
              <p style={{ marginTop: '0.5rem', color: 'var(--omega-text-muted)' }}>
                문서 로딩 중...
              </p>
            </div>
          ) : categoryDocs.length === 0 ? (
            <div className="empty-state" style={{ padding: '2rem' }}>
              <p>📄 해당 카테고리에 문서가 없습니다</p>
            </div>
          ) : (() => {
            const q = adminSearchQuery.trim().toLowerCase();
            const filteredDocs = q
              ? categoryDocs.filter(doc => {
                  const docCat = doc.category || (activeCategory !== '전체' ? activeCategory : '');
                  const { display } = parseDisplayFilename(doc.filename, docCat, doc.company_name);
                  return doc.filename.toLowerCase().includes(q)
                    || display.toLowerCase().includes(q)
                    || String(doc.id).includes(q)
                    || String(doc.user_id).includes(q);
                })
              : categoryDocs;

            const totalPages = Math.ceil(filteredDocs.length / adminPageSize);
            const safePage = Math.min(adminCurrentPage, totalPages || 1);
            const startIdx = (safePage - 1) * adminPageSize;
            const paginatedDocs = filteredDocs.slice(startIdx, startIdx + adminPageSize);

            return filteredDocs.length === 0 ? (
              <div className="empty-state" style={{ padding: '2rem' }}>
                <p>🔍 '{adminSearchQuery}'에 대한 검색 결과가 없습니다</p>
              </div>
            ) : (
            <div className="table-container">
              {/* ── 표시 건수 + 페이지 정보 ── */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '0.5rem 0.75rem', marginBottom: '0.5rem',
                background: 'var(--omega-surface-2)', borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--omega-border)',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', color: 'var(--omega-text-muted)' }}>
                  <span>표시:</span>
                  {[100, 200, 300, 500, 1000].map(n => (
                    <button
                      key={n}
                      onClick={() => { setAdminPageSize(n); setAdminCurrentPage(1); }}
                      style={{
                        padding: '0.2rem 0.45rem', fontSize: '0.73rem', fontWeight: adminPageSize === n ? 600 : 400,
                        background: adminPageSize === n ? 'var(--omega-primary)' : 'rgba(255,255,255,0.04)',
                        color: adminPageSize === n ? '#fff' : 'var(--omega-text-muted)',
                        border: 'none', borderRadius: '4px', cursor: 'pointer', transition: 'all 0.15s',
                      }}
                    >{n}</button>
                  ))}
                  <span>건</span>
                </div>
                <span style={{ fontSize: '0.78rem', color: 'var(--omega-text-muted)' }}>
                  {filteredDocs.length}건 중 {startIdx + 1}–{Math.min(startIdx + adminPageSize, filteredDocs.length)}
                </span>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        {showOriginalFilename ? '원본 파일명' : '문서명'}
                        <button
                          onClick={() => setShowOriginalFilename(!showOriginalFilename)}
                          style={{
                            padding: '0.15rem 0.4rem', fontSize: '0.65rem',
                            background: showOriginalFilename ? 'var(--omega-primary-light)' : 'var(--omega-surface-2)',
                            color: showOriginalFilename ? '#fff' : 'var(--omega-text-muted)',
                            border: '1px solid var(--omega-border)',
                            borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                            transition: 'all 0.2s',
                          }}
                          title={showOriginalFilename ? '간략 표시로 전환' : '원본 파일명 보기'}
                        >
                          {showOriginalFilename ? '📄 간략' : '📎 원본명'}
                        </button>
                      </div>
                    </th>
                    <th>형식</th>
                    <th>크기</th>
                    <th>상태</th>
                    <th>업로드일</th>
                    <th style={{ width: '130px' }}>작업</th>
                  </tr>
                </thead>
                <tbody>
                  {paginatedDocs.map((doc) => {
                    const status = STATUS_MAP[doc.status] || { label: doc.status, class: 'badge-info' };
                    const displayCat = doc.category || (activeCategory !== '전체' ? activeCategory : '');
                    const { display: displayName } = parseDisplayFilename(doc.filename, displayCat, doc.company_name);
                    return (
                      <tr key={doc.id}>
                        <td style={{ fontSize: '0.8rem', opacity: 0.6 }}>#{doc.id}</td>
                        <td style={{ fontWeight: 500, color: 'var(--omega-text)', maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                            title={doc.filename}
                        >
                          {showOriginalFilename ? doc.filename : displayName}
                        </td>
                        <td><span className="badge badge-info" style={{ fontSize: '0.7rem' }}>{doc.file_type.toUpperCase()}</span></td>
                        <td style={{ fontSize: '0.82rem' }}>{formatSize(doc.file_size)}</td>
                        <td><span className={`badge ${status.class}`} style={{ fontSize: '0.72rem' }}>{status.label}</span></td>
                        <td style={{ fontSize: '0.78rem', color: 'var(--omega-text-muted)' }}>{formatDate(doc.created_at)}</td>
                        <td>
                          <div style={{ display: 'flex', gap: '0.3rem', alignItems: 'center' }}>
                            <Link to={`/documents/${doc.id}`}
                              style={{
                                fontSize: '0.72rem', padding: '0.2rem 0.5rem',
                                borderRadius: '4px', textDecoration: 'none',
                                background: 'rgba(255,255,255,0.06)',
                                color: 'var(--omega-text-muted)',
                                transition: 'all 0.15s',
                              }}
                              onMouseEnter={e => { e.target.style.background = 'rgba(255,255,255,0.12)'; e.target.style.color = '#fff'; }}
                              onMouseLeave={e => { e.target.style.background = 'rgba(255,255,255,0.06)'; e.target.style.color = 'var(--omega-text-muted)'; }}
                            >
                              상세
                            </Link>
                            {doc.status === 'analyzed' && (
                              <button
                                onClick={() => setReclassModal(doc.id)}
                                style={{
                                  fontSize: '0.68rem', padding: '0.2rem 0.45rem',
                                  borderRadius: '4px', border: 'none', cursor: 'pointer',
                                  background: 'transparent',
                                  color: 'rgba(255,255,255,0.25)',
                                  transition: 'all 0.15s',
                                }}
                                onMouseEnter={e => { e.target.style.color = 'var(--omega-primary-light)'; e.target.style.background = 'rgba(255,255,255,0.06)'; }}
                                onMouseLeave={e => { e.target.style.color = 'rgba(255,255,255,0.25)'; e.target.style.background = 'transparent'; }}
                                title="카테고리 재분류"
                              >
                                재분류
                              </button>
                            )}
                            <button
                              onClick={() => handleDeleteDocument(doc.id, doc.filename)}
                              style={{
                                padding: '0.2rem 0.4rem', fontSize: '0.7rem',
                                background: 'transparent', color: 'rgba(239,68,68,0.35)',
                                border: 'none', cursor: 'pointer',
                                display: 'flex', alignItems: 'center',
                                transition: 'all 0.15s',
                              }}
                              onMouseEnter={e => { e.target.style.color = '#f87171'; }}
                              onMouseLeave={e => { e.target.style.color = 'rgba(239,68,68,0.35)'; }}
                              title="삭제"
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {/* ── 페이지네이션 ── */}
              {totalPages > 1 && (
                <div style={{
                  display: 'flex', justifyContent: 'center', alignItems: 'center',
                  gap: '0.3rem', marginTop: '1rem', padding: '0.5rem 0',
                }}>
                  <button onClick={() => setAdminCurrentPage(1)} disabled={safePage <= 1}
                    style={{ padding: '0.3rem 0.5rem', fontSize: '0.75rem', borderRadius: '4px', border: 'none', cursor: safePage <= 1 ? 'default' : 'pointer', background: 'rgba(255,255,255,0.06)', color: safePage <= 1 ? 'rgba(255,255,255,0.15)' : 'var(--omega-text-muted)' }}
                  >«</button>
                  <button onClick={() => setAdminCurrentPage(p => Math.max(1, p - 1))} disabled={safePage <= 1}
                    style={{ padding: '0.3rem 0.5rem', fontSize: '0.75rem', borderRadius: '4px', border: 'none', cursor: safePage <= 1 ? 'default' : 'pointer', background: 'rgba(255,255,255,0.06)', color: safePage <= 1 ? 'rgba(255,255,255,0.15)' : 'var(--omega-text-muted)' }}
                  >‹</button>
                  {Array.from({ length: totalPages }, (_, i) => i + 1)
                    .filter(p => p === 1 || p === totalPages || Math.abs(p - safePage) <= 2)
                    .reduce((acc, p, i, arr) => { if (i > 0 && p - arr[i-1] > 1) acc.push('...'); acc.push(p); return acc; }, [])
                    .map((item, i) => item === '...' ? (
                      <span key={`e${i}`} style={{ color: 'rgba(255,255,255,0.2)', fontSize: '0.75rem' }}>…</span>
                    ) : (
                      <button key={item} onClick={() => setAdminCurrentPage(item)}
                        style={{ padding: '0.3rem 0.5rem', fontSize: '0.75rem', borderRadius: '4px', border: 'none', cursor: 'pointer', fontWeight: safePage === item ? 600 : 400, background: safePage === item ? 'var(--omega-primary)' : 'rgba(255,255,255,0.04)', color: safePage === item ? '#fff' : 'var(--omega-text-muted)', transition: 'all 0.15s', minWidth: '28px' }}
                      >{item}</button>
                    ))}
                  <button onClick={() => setAdminCurrentPage(p => Math.min(totalPages, p + 1))} disabled={safePage >= totalPages}
                    style={{ padding: '0.3rem 0.5rem', fontSize: '0.75rem', borderRadius: '4px', border: 'none', cursor: safePage >= totalPages ? 'default' : 'pointer', background: 'rgba(255,255,255,0.06)', color: safePage >= totalPages ? 'rgba(255,255,255,0.15)' : 'var(--omega-text-muted)' }}
                  >›</button>
                  <button onClick={() => setAdminCurrentPage(totalPages)} disabled={safePage >= totalPages}
                    style={{ padding: '0.3rem 0.5rem', fontSize: '0.75rem', borderRadius: '4px', border: 'none', cursor: safePage >= totalPages ? 'default' : 'pointer', background: 'rgba(255,255,255,0.06)', color: safePage >= totalPages ? 'rgba(255,255,255,0.15)' : 'var(--omega-text-muted)' }}
                  >»</button>
                </div>
              )}
            </div>
            );
          })()}
        </div>
      </div>
    );
  };


  /* ── Users Panel ── */
  const renderUsers = () => {
    if (usersLoading) {
      return (
        <div className="loading-container">
          <div className="spinner spinner-lg"></div>
          <p>회원 로딩 중...</p>
        </div>
      );
    }

    return (
      <div className="fade-in">
        <div className="admin-tab-toolbar">
          <span className="admin-tab-count">총 {users.length}명</span>
          <button className="btn btn-sm btn-secondary" onClick={loadUsers} id="refresh-users-btn">
            🔄 새로고침
          </button>
        </div>

        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>이메일</th>
                <th>사용자명</th>
                <th>역할</th>
                <th>상태</th>
                <th>가입일</th>
                <th>작업</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>#{u.id}</td>
                  <td style={{ color: 'var(--omega-text)' }}>{u.email}</td>
                  <td>{u.username}</td>
                  <td>
                    <span className={`badge ${u.role === 'admin' ? 'badge-warning' : 'badge-primary'}`}>
                      {u.role}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${u.is_active ? 'badge-success' : 'badge-danger'}`}>
                      {u.is_active ? '활성' : '비활성'}
                    </span>
                  </td>
                  <td>{formatDate(u.created_at)}</td>
                  <td>
                    <button
                      className={`btn btn-sm ${u.is_active ? 'btn-danger' : 'btn-success'}`}
                      onClick={() => handleActiveToggle(u.id, u.is_active)}
                    >
                      {u.is_active ? '비활성화' : '활성화'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {users.length === 0 && (
            <div className="empty-state" style={{ padding: '2rem' }}>
              <p>👤 등록된 회원이 없습니다</p>
            </div>
          )}
        </div>
      </div>
    );
  };


  /* ═══════════════════════════════════════════════════════
     RENDER
     ═══════════════════════════════════════════════════════ */
  return (
    <div className="page-container fade-in">
      <div className="page-header">
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <Zap size={28} strokeWidth={1.5} style={{ color: 'var(--omega-accent)' }} />
          관리자 대시보드
        </h1>
        <p>Omega CivicFlow — 시스템 위상 모니터링</p>
      </div>

      {/* Tab Navigation */}
      <div className="admin-tabs" id="admin-tab-nav">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            className={`admin-tab-btn ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
            id={`admin-tab-${tab.key}`}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
          >
            <tab.Icon size={14} strokeWidth={1.8} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="admin-tab-content">
        {activeTab === 'dashboard' && renderDashboard()}
        {activeTab === 'users' && renderUsers()}
      </div>
    </div>
  );
}
