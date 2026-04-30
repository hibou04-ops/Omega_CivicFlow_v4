import { useState, useEffect, useMemo, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { adminAPI } from '../api/client';
import { correctFilenameCompany } from '../utils/categoryTranslation';

const STATUS_MAP = {
  uploaded: { label: '업로드', class: 'badge-info' },
  ocr_done: { label: 'OCR 완료', class: 'badge-warning' },
  analyzed: { label: '분석 완료', class: 'badge-success' },
  failed: { label: '실패', class: 'badge-danger' },
};

const PAGE_SIZE_OPTIONS = [100, 200, 300, 500, 1000];

export default function AdminDocuments() {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [reclassModal, setReclassModal] = useState(null);
  const [newCategory, setNewCategory] = useState('');
  const [reason, setReason] = useState('');

  // URL search params 상태 복원
  const [searchParams, setSearchParams] = useSearchParams();
  const [searchQuery, setSearchQuery] = useState(searchParams.get('q') || '');
  const [pageSize, setPageSize] = useState(parseInt(searchParams.get('pp') || '100', 10));
  const [currentPage, setCurrentPage] = useState(parseInt(searchParams.get('page') || '1', 10));
  const [selectedCategory, setSelectedCategory] = useState(searchParams.get('cat') || '전체');

  const scrollRestoredRef = useRef(false);

  useEffect(() => {
    loadDocs();
  }, []);

  const loadDocs = async () => {
    try {
      const res = await adminAPI.listAllDocuments();
      setDocs(res.data.documents);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // 카테고리 집계
  const categoryStats = useMemo(() => {
    const counts = {};
    docs.forEach(d => {
      const cat = d.category || '미분류';
      counts[cat] = (counts[cat] || 0) + 1;
    });
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count }));
  }, [docs]);

  // 필터링
  const filteredDocs = useMemo(() => {
    let result = docs;
    if (selectedCategory !== '전체') {
      result = result.filter(d => (d.category || '미분류') === selectedCategory);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(d =>
        String(d.id).includes(q) ||
        (d.filename || '').toLowerCase().includes(q) ||
        (d.company_name || '').toLowerCase().includes(q)
      );
    }
    return result;
  }, [docs, selectedCategory, searchQuery]);

  // 페이지네이션
  const totalPages = Math.ceil(filteredDocs.length / pageSize);
  const paginatedDocs = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredDocs.slice(start, start + pageSize);
  }, [filteredDocs, currentPage, pageSize]);

  // 카테고리/검색 변경 시 1페이지로 리셋
  useEffect(() => { setCurrentPage(1); }, [selectedCategory, searchQuery, pageSize]);

  // URL 동기화
  useEffect(() => {
    const next = {};
    if (currentPage > 1) next.page = String(currentPage);
    if (pageSize !== 100) next.pp = String(pageSize);
    if (selectedCategory !== '전체') next.cat = selectedCategory;
    if (searchQuery.trim()) next.q = searchQuery.trim();
    setSearchParams(next, { replace: true });
  }, [currentPage, pageSize, selectedCategory, searchQuery]);

  // 스크롤 복원
  useEffect(() => {
    if (!loading && !scrollRestoredRef.current) {
      scrollRestoredRef.current = true;
      const saved = sessionStorage.getItem('admin_docs_scroll');
      if (saved) {
        requestAnimationFrame(() => window.scrollTo(0, parseInt(saved, 10)));
      }
    }
  }, [loading]);

  const saveScroll = () => {
    sessionStorage.setItem('admin_docs_scroll', String(window.scrollY));
  };

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
      loadDocs();
    } catch (err) {
      alert(err.response?.data?.detail || '재분류 실패');
    }
  };

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

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner spinner-lg"></div>
        <p>문서 로딩 중...</p>
      </div>
    );
  }

  return (
    <div className="page-container fade-in">
      <div className="page-header">
        <h1>📁 전체 문서 관리</h1>
        <p>시스템 전체 문서 조회 및 재분류 관리</p>
      </div>

      {/* ═══ 카테고리 필터 칩 ═══ */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: '0.4rem',
        marginBottom: '1rem', padding: '0.75rem',
        background: 'rgba(255,255,255,0.03)', borderRadius: '10px',
        border: '1px solid rgba(255,255,255,0.06)',
      }}>
        <button
          onClick={() => setSelectedCategory('전체')}
          style={{
            padding: '0.3rem 0.7rem', fontSize: '0.75rem', fontWeight: 500,
            borderRadius: '6px', border: 'none', cursor: 'pointer',
            transition: 'all 0.2s',
            background: selectedCategory === '전체'
              ? 'var(--omega-primary)' : 'rgba(255,255,255,0.06)',
            color: selectedCategory === '전체'
              ? '#fff' : 'var(--omega-text-muted)',
          }}
        >
          전체 {docs.length}
        </button>
        {categoryStats.map(({ name, count }) => (
          <button
            key={name}
            onClick={() => setSelectedCategory(name)}
            style={{
              padding: '0.3rem 0.7rem', fontSize: '0.72rem', fontWeight: 400,
              borderRadius: '6px', border: 'none', cursor: 'pointer',
              transition: 'all 0.2s',
              background: selectedCategory === name
                ? 'var(--omega-primary)' : 'rgba(255,255,255,0.06)',
              color: selectedCategory === name
                ? '#fff' : 'var(--omega-text-muted)',
            }}
          >
            {name} {count}
          </button>
        ))}
      </div>

      {/* ═══ 검색 + 페이지 크기 컨트롤 바 ═══ */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '1rem',
        marginBottom: '1rem', flexWrap: 'wrap',
      }}>
        <div style={{ flex: 1, minWidth: '200px' }}>
          <input
            className="form-input"
            placeholder="🔍 문서 검색 (ID, 파일명, 회사명...)"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            style={{ fontSize: '0.85rem', padding: '0.5rem 0.75rem' }}
          />
        </div>

        <div style={{
          display: 'flex', alignItems: 'center', gap: '0.4rem',
          fontSize: '0.8rem', color: 'var(--omega-text-muted)',
        }}>
          <span>표시:</span>
          {PAGE_SIZE_OPTIONS.map(size => (
            <button
              key={size}
              onClick={() => setPageSize(size)}
              style={{
                padding: '0.25rem 0.5rem', fontSize: '0.75rem',
                borderRadius: '4px', border: 'none', cursor: 'pointer',
                fontWeight: pageSize === size ? 600 : 400,
                background: pageSize === size
                  ? 'var(--omega-primary)' : 'rgba(255,255,255,0.06)',
                color: pageSize === size ? '#fff' : 'var(--omega-text-muted)',
                transition: 'all 0.15s',
              }}
            >
              {size}
            </button>
          ))}
          <span style={{ marginLeft: '0.3rem' }}>건</span>
        </div>

        <div style={{
          fontSize: '0.78rem', color: 'var(--omega-text-muted)',
          whiteSpace: 'nowrap',
        }}>
          {filteredDocs.length}건 중 {(currentPage - 1) * pageSize + 1}–
          {Math.min(currentPage * pageSize, filteredDocs.length)}
        </div>
      </div>

      {/* ═══ 재분류 모달 ═══ */}
      {reclassModal && (
        <div
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.7)', display: 'flex',
            alignItems: 'center', justifyContent: 'center', zIndex: 1000,
          }}
          onClick={() => setReclassModal(null)}
        >
          <div
            className="card-glass"
            style={{ width: '100%', maxWidth: '440px', padding: '1.5rem' }}
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{
              marginBottom: '1.2rem', fontSize: '1rem',
              color: 'var(--omega-primary-light)',
            }}>
              🔄 문서 재분류 <span style={{ opacity: 0.5 }}>#{reclassModal}</span>
            </h3>

            <div className="form-group" style={{ marginBottom: '0.8rem' }}>
              <label className="form-label" style={{ fontSize: '0.82rem' }}>새 카테고리 *</label>
              <select
                className="form-input"
                value={newCategory}
                onChange={e => setNewCategory(e.target.value)}
                style={{ fontSize: '0.85rem' }}
              >
                <option value="">선택하세요</option>
                {categoryStats.map(({ name }) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>

            <div className="form-group" style={{ marginBottom: '1rem' }}>
              <label className="form-label" style={{ fontSize: '0.82rem' }}>재분류 사유</label>
              <input
                className="form-input"
                placeholder="변경 사유를 입력하세요"
                value={reason}
                onChange={e => setReason(e.target.value)}
                style={{ fontSize: '0.85rem' }}
              />
            </div>

            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button className="btn btn-secondary" onClick={() => setReclassModal(null)}
                style={{ fontSize: '0.82rem', padding: '0.4rem 1rem' }}>
                취소
              </button>
              <button className="btn btn-primary" onClick={handleReclassify}
                style={{ fontSize: '0.82rem', padding: '0.4rem 1rem' }}>
                적용
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ═══ 문서 테이블 ═══ */}
      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>문서명</th>
              <th>카테고리</th>
              <th>형식</th>
              <th>크기</th>
              <th>상태</th>
              <th>업로드일</th>
              <th style={{ width: '120px' }}>작업</th>
            </tr>
          </thead>
          <tbody>
            {paginatedDocs.map(doc => {
              const status = STATUS_MAP[doc.status] || { label: doc.status, class: 'badge-info' };
              return (
                <tr key={doc.id}>
                  <td style={{ fontSize: '0.8rem', opacity: 0.6 }}>#{doc.id}</td>
                  <td style={{
                    fontWeight: 500, color: 'var(--omega-text)',
                    maxWidth: '220px', overflow: 'hidden',
                    textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {correctFilenameCompany(doc.filename, doc.company_name)}
                  </td>
                  <td>
                    <span style={{
                      fontSize: '0.72rem', padding: '0.15rem 0.4rem',
                      borderRadius: '4px',
                      background: 'rgba(255,255,255,0.05)',
                      color: 'var(--omega-text-muted)',
                    }}>
                      {doc.category || '—'}
                    </span>
                  </td>
                  <td><span className="badge badge-info" style={{ fontSize: '0.7rem' }}>{doc.file_type?.toUpperCase()}</span></td>
                  <td style={{ fontSize: '0.82rem' }}>{formatSize(doc.file_size)}</td>
                  <td><span className={`badge ${status.class}`} style={{ fontSize: '0.72rem' }}>{status.label}</span></td>
                  <td style={{ fontSize: '0.78rem', color: 'var(--omega-text-muted)' }}>{formatDate(doc.created_at)}</td>
                  <td>
                    <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'center' }}>
                      <Link to={`/documents/${doc.id}`}
                        onClick={saveScroll}
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
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* ═══ 페이지네이션 ═══ */}
      {totalPages > 1 && (
        <div style={{
          display: 'flex', justifyContent: 'center', alignItems: 'center',
          gap: '0.3rem', marginTop: '1.2rem', flexWrap: 'wrap',
        }}>
          <button
            onClick={() => setCurrentPage(1)}
            disabled={currentPage === 1}
            style={{
              padding: '0.3rem 0.6rem', fontSize: '0.75rem',
              borderRadius: '4px', border: 'none', cursor: currentPage === 1 ? 'default' : 'pointer',
              background: 'rgba(255,255,255,0.06)',
              color: currentPage === 1 ? 'rgba(255,255,255,0.15)' : 'var(--omega-text-muted)',
            }}
          >«</button>
          <button
            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
            disabled={currentPage === 1}
            style={{
              padding: '0.3rem 0.6rem', fontSize: '0.75rem',
              borderRadius: '4px', border: 'none', cursor: currentPage === 1 ? 'default' : 'pointer',
              background: 'rgba(255,255,255,0.06)',
              color: currentPage === 1 ? 'rgba(255,255,255,0.15)' : 'var(--omega-text-muted)',
            }}
          >‹</button>

          {Array.from({ length: totalPages }, (_, i) => i + 1)
            .filter(p => p === 1 || p === totalPages || Math.abs(p - currentPage) <= 2)
            .reduce((acc, p, i, arr) => {
              if (i > 0 && p - arr[i - 1] > 1) acc.push('...');
              acc.push(p);
              return acc;
            }, [])
            .map((item, i) =>
              item === '...' ? (
                <span key={`ellip-${i}`} style={{ color: 'rgba(255,255,255,0.2)', fontSize: '0.75rem', padding: '0 0.2rem' }}>…</span>
              ) : (
                <button
                  key={item}
                  onClick={() => setCurrentPage(item)}
                  style={{
                    padding: '0.3rem 0.55rem', fontSize: '0.75rem',
                    borderRadius: '4px', border: 'none', cursor: 'pointer',
                    fontWeight: currentPage === item ? 600 : 400,
                    background: currentPage === item
                      ? 'var(--omega-primary)' : 'rgba(255,255,255,0.04)',
                    color: currentPage === item ? '#fff' : 'var(--omega-text-muted)',
                    transition: 'all 0.15s',
                    minWidth: '28px',
                  }}
                >
                  {item}
                </button>
              )
            )
          }

          <button
            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
            disabled={currentPage === totalPages}
            style={{
              padding: '0.3rem 0.6rem', fontSize: '0.75rem',
              borderRadius: '4px', border: 'none', cursor: currentPage === totalPages ? 'default' : 'pointer',
              background: 'rgba(255,255,255,0.06)',
              color: currentPage === totalPages ? 'rgba(255,255,255,0.15)' : 'var(--omega-text-muted)',
            }}
          >›</button>
          <button
            onClick={() => setCurrentPage(totalPages)}
            disabled={currentPage === totalPages}
            style={{
              padding: '0.3rem 0.6rem', fontSize: '0.75rem',
              borderRadius: '4px', border: 'none', cursor: currentPage === totalPages ? 'default' : 'pointer',
              background: 'rgba(255,255,255,0.06)',
              color: currentPage === totalPages ? 'rgba(255,255,255,0.15)' : 'var(--omega-text-muted)',
            }}
          >»</button>
        </div>
      )}
    </div>
  );
}
