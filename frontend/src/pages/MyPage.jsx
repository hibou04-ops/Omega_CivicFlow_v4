import { useState, useEffect, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { documentsAPI, authAPI } from '../api/client';
import { FileText, User, FolderOpen, Upload, Inbox, BarChart3, Trash2, Copy, Pencil, Check, X, Sparkles } from 'lucide-react';
import { translateCategory, deduplicateCategories, parseDisplayFilename } from '../utils/categoryTranslation';

const STATUS_MAP = {
  uploaded: { label: '업로드', class: 'badge-info' },
  ocr_done: { label: 'OCR 완료', class: 'badge-warning' },
  analyzed: { label: '분석 완료', class: 'badge-success' },
  failed: { label: '실패', class: 'badge-danger' },
};

const CHART_COLORS = [
  '#6C63FF', '#FF6B6B', '#4ECDC4', '#FFD93D', '#FF8C42',
  '#A8E6CF', '#DDA0F5', '#45B7D1', '#F78C6C', '#96CEB4',
];

export default function MyPage() {
  const { user, updateProfile, logout } = useAuth();
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editMode, setEditMode] = useState(false);
  const [username, setUsername] = useState(user?.username || '');
  const [password, setPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [profileMsg, setProfileMsg] = useState('');
  const [profileMsgType, setProfileMsgType] = useState('success');
  const [changingPassword, setChangingPassword] = useState(false);

  const validatePassword = (pw) => {
    if (pw.length < 8) return '비밀번호는 8자 이상이어야 합니다.';
    if (!/[a-zA-Z]/.test(pw)) return '영문자를 포함해야 합니다.';
    if (!/\d/.test(pw)) return '숫자를 포함해야 합니다.';
    if (!/[!@#$%^&*()\-_=+\[\]{};:'",.<>/?\\|`~]/.test(pw)) return '특수문자를 포함해야 합니다.';
    return '';
  };

  // 회원탈퇴 모달 상태
  const [showWithdrawModal, setShowWithdrawModal] = useState(false);
  const [withdrawPassword, setWithdrawPassword] = useState('');
  const [withdrawConfirmText, setWithdrawConfirmText] = useState('');
  const [withdrawing, setWithdrawing] = useState(false);

  // 인사이트 생성된 문서만 보기 토글
  const [showOnlyWithInsight, setShowOnlyWithInsight] = useState(false);

  // URL search params로 상태 유지 (뒤로가기 시 복원)
  const [searchParams, setSearchParams] = useSearchParams();
  const urlPage = parseInt(searchParams.get('page') || '1', 10);
  const urlPerPage = parseInt(searchParams.get('pp') || '50', 10);
  const urlCategory = searchParams.get('cat') || '전체';
  const urlSearch = searchParams.get('q') || '';

  // 카테고리 필터
  const [stats, setStats] = useState(null);
  const [activeCategory, setActiveCategory] = useState(urlCategory);

  // 파일명 표시 토글
  const [showOriginalFilename, setShowOriginalFilename] = useState(false);

  // 문서 검색
  const [searchQuery, setSearchQuery] = useState(urlSearch);

  // 페이지네이션
  const [currentPage, setCurrentPage] = useState(urlPage);
  const [perPage, setPerPage] = useState(urlPerPage);

  // 스크롤 위치 복원
  const scrollRestoredRef = useRef(false);

  // 체크박스 선택 (일괄 삭제)
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  // 중복 문서 관리
  const [dupGroups, setDupGroups] = useState([]);
  const [dupLoading, setDupLoading] = useState(false);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [expandedGroup, setExpandedGroup] = useState(null);
  const [renamingId, setRenamingId] = useState(null);
  const [renameValue, setRenameValue] = useState('');

  // URL params -> state (뒤로가기 시)
  useEffect(() => {
    loadStats();
    loadDocs(urlCategory);
  }, []);

  // 스크롤 위치 복원 (문서 로딩 완료 후)
  useEffect(() => {
    if (!loading && !scrollRestoredRef.current) {
      scrollRestoredRef.current = true;
      const savedScroll = sessionStorage.getItem('mypage_scroll');
      if (savedScroll) {
        requestAnimationFrame(() => {
          window.scrollTo(0, parseInt(savedScroll, 10));
        });
      }
    }
  }, [loading]);


  // URL search params 자동 동기화 (상태 변경 → URL 반영)
  useEffect(() => {
    const next = {};
    if (currentPage > 1) next.page = String(currentPage);
    if (perPage !== 50) next.pp = String(perPage);
    if (activeCategory !== '전체') next.cat = activeCategory;
    if (searchQuery.trim()) next.q = searchQuery.trim();
    setSearchParams(next, { replace: true });
  }, [currentPage, perPage, activeCategory, searchQuery]);

  // 문서 상세 이동 전 스크롤 저장
  const saveScroll = () => {
    sessionStorage.setItem('mypage_scroll', String(window.scrollY));
  };

  const loadStats = async () => {
    try {
      const res = await documentsAPI.myStats();
      setStats(res.data);
    } catch (err) {
      console.error(err);
    }
  };

  const loadDocs = async (category) => {
    setLoading(true);
    try {
      const res = category === '전체'
        ? await documentsAPI.list()
        : await documentsAPI.listByCategory(category);
      setDocs(res.data.documents);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
      setSelectedIds(new Set());
    }
  };

  const handleCategoryChange = (category) => {
    setActiveCategory(category);
    setCurrentPage(1);
    loadDocs(category);
  };

  const handleDelete = async (docId) => {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
      await documentsAPI.delete(docId);
      setDocs(docs.filter(d => d.id !== docId));
      loadStats(); // refresh stats
    } catch (err) {
      alert(err.response?.data?.detail || '삭제 실패');
    }
  };

  // ── 일괄 삭제 ──
  const toggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = (docsToToggle) => {
    const ids = docsToToggle.map(d => d.id);
    const allSelected = ids.every(id => selectedIds.has(id));
    
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (allSelected) {
        ids.forEach(id => next.delete(id));
      } else {
        ids.forEach(id => next.add(id));
      }
      return next;
    });
  };

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`선택한 ${selectedIds.size}건의 문서를 삭제하시겠습니까?`)) return;
    setBulkDeleting(true);
    let deleted = 0;
    for (const id of selectedIds) {
      try {
        await documentsAPI.delete(id);
        deleted++;
      } catch (err) {
        console.error(`문서 #${id} 삭제 실패:`, err);
      }
    }
    setSelectedIds(new Set());
    setBulkDeleting(false);
    loadDocs(activeCategory);
    loadStats();
    if (deleted > 0) alert(`${deleted}건 삭제 완료`);
    if (showDuplicates) loadDuplicates();
  };

  // ── 중복 문서 로드 ──
  const loadDuplicates = async () => {
    setDupLoading(true);
    try {
      const res = await documentsAPI.getDuplicates();
      setDupGroups(res.data.groups);
    } catch (err) {
      console.error(err);
    } finally {
      setDupLoading(false);
    }
  };

  const handleToggleDuplicates = () => {
    const next = !showDuplicates;
    setShowDuplicates(next);
    if (next && dupGroups.length === 0) loadDuplicates();
  };

  const handleRename = async (docId) => {
    if (!renameValue.trim()) return;
    try {
      await documentsAPI.rename(docId, renameValue.trim());
      setRenamingId(null);
      loadDocs(activeCategory);
      loadDuplicates();
    } catch (err) {
      alert(err.response?.data?.detail || '이름 변경 실패');
    }
  };

  const showMsg = (msg, type = 'success') => {
    setProfileMsg(msg);
    setProfileMsgType(type);
    if (type !== 'info') setTimeout(() => setProfileMsg(''), 5000);
  };

  const handleProfileUpdate = async (e) => {
    e.preventDefault();
    if (username !== user.username) {
      try {
        await updateProfile({ username });
        showMsg('닉네임이 업데이트되었습니다.');
      } catch (err) {
        showMsg(err.response?.data?.detail || '닉네임 업데이트 실패', 'error');
        return;
      }
    }
    if (password) {
      const pwErr = validatePassword(password);
      if (pwErr) {
        setPasswordError(pwErr);
        showMsg('비밀번호 양식이 맞지 않습니다. 조건을 확인해주세요.', 'error');
        return;
      }
      setChangingPassword(true);
      try {
        const res = await authAPI.requestPasswordChange({ new_password: password });
        showMsg(res.data.message, 'info');
        setPassword('');
      } catch (err) {
        showMsg(err.response?.data?.detail || '비밀번호 변경 요청 실패', 'error');
      } finally {
        setChangingPassword(false);
      }
      return;
    }
    setEditMode(false);
  };

  const handleWithdraw = async () => {
    if (!withdrawPassword || withdrawConfirmText !== '탈퇴합니다') return;
    setWithdrawing(true);
    try {
      const res = await authAPI.requestWithdraw({
        password: withdrawPassword,
        confirm_text: withdrawConfirmText,
      });
      setShowWithdrawModal(false);
      setWithdrawPassword('');
      setWithdrawConfirmText('');
      showMsg(
        res.data?.message ||
          '회원탈퇴 인증 메일이 전송되었습니다. 15분 내에 메일의 링크를 클릭해 최종 확정해주세요.',
        'info',
      );
    } catch (err) {
      showMsg(
        err.response?.data?.detail || '회원탈퇴 인증 메일 전송 중 오류가 발생했습니다.',
        'error',
      );
    } finally {
      setWithdrawing(false);
    }
  };

  const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleString('ko-KR', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  };

  // ── 카테고리 목록 구성 (중복 합산) ──
  const dedupedStats = stats ? deduplicateCategories(stats.category_stats) : [];
  const allCategories = stats
    ? [
      { category: '전체', count: stats.total },
      ...dedupedStats,
    ]
    : [{ category: '전체', count: 0 }];

  // ── 바 차트 데이터 ──
  const chartStats = dedupedStats.filter(s => s.count > 0);

  return (
    <div className="page-container fade-in">
      <div className="page-header">
        <h1 style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <FileText size={28} strokeWidth={1.5} />
          마이페이지
        </h1>
        <p>{user?.username}님의 문서 관리 및 프로필 설정</p>
      </div>

      {/* Profile Section */}
      <div className="card" style={{ marginBottom: '2rem' }}>
        <div className="card-header">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <User size={16} strokeWidth={1.5} /> 내 정보
          </div>
          <button
            className="btn btn-sm btn-secondary"
            onClick={() => setEditMode(!editMode)}
          >
            {editMode ? '취소' : '수정'}
          </button>
        </div>

        {profileMsg && (
          <div className={`alert ${
            profileMsgType === 'error' ? 'alert-error'
            : profileMsgType === 'info' ? 'alert-info'
            : 'alert-success'
          }`} style={profileMsgType === 'info' ? {
            background: 'rgba(251,191,36,0.1)', borderColor: '#FBBF24',
            color: '#FBBF24',
          } : {}}>
            {profileMsgType === 'error' ? '❌' : profileMsgType === 'info' ? '📧' : '✅'} {profileMsg}
          </div>
        )}

        {editMode ? (
          <form onSubmit={handleProfileUpdate}>
            <div className="form-group">
              <label className="form-label">사용자명</label>
              <input
                className="form-input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label className="form-label">새 비밀번호 (이메일 인증 필요)</label>
              <input
                type="password"
                className="form-input"
                placeholder="영문 + 숫자 + 특수문자 포함 8자 이상"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setPasswordError(e.target.value ? validatePassword(e.target.value) : '');
                }}
              />
              <div style={{ fontSize: '0.75rem', color: '#9CA3AF', marginTop: '4px' }}>
                영문, 숫자, 특수문자(!@#$ 등)를 각각 1자 이상 포함, 총 8자 이상
              </div>
              {passwordError && (
                <div style={{ fontSize: '0.75rem', color: '#F87171', marginTop: '4px' }}>
                  ⚠️ {passwordError}
                </div>
              )}
              <div style={{ fontSize: '0.75rem', color: '#FBBF24', marginTop: '4px' }}>
                🔐 비밀번호 변경 시 등록된 이메일로 인증 링크가 발송됩니다
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button type="submit" className="btn btn-primary" disabled={changingPassword}>
                {changingPassword ? (
                  <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 1.5 }}></span> 인증 메일 발송 중...</>
                ) : password ? '🔐 비밀번호 변경 요청' : '저장'}
              </button>
            </div>
          </form>
        ) : (
          <div>
            <div className="detail-row">
              <span className="label">이메일</span>
              <span className="value">{user?.email}</span>
            </div>
            <div className="detail-row">
              <span className="label">사용자명</span>
              <span className="value">{user?.username}</span>
            </div>
            <div className="detail-row">
              <span className="label">역할</span>
              <span className={`badge ${user?.role === 'admin' ? 'badge-warning' : 'badge-primary'}`}>
                {user?.role}
              </span>
            </div>
            <div className="detail-row">
              <span className="label">가입일</span>
              <span className="value">{user?.created_at && formatDate(user.created_at)}</span>
            </div>
          </div>
        )}
      </div>

      {/* ── 회원탈퇴 확인 모달 ── */}
      {showWithdrawModal && (
        <div
          onClick={() => {
            if (withdrawing) return;
            setShowWithdrawModal(false);
            setWithdrawPassword('');
            setWithdrawConfirmText('');
          }}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            padding: '1rem',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="card"
            style={{
              maxWidth: 480,
              width: '100%',
              padding: '1.5rem',
              border: '1px solid rgba(239,68,68,0.4)',
            }}
          >
            <h3
              style={{
                marginTop: 0,
                marginBottom: '1rem',
                color: '#EF4444',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <Trash2 size={18} strokeWidth={1.5} /> 회원탈퇴 확인
            </h3>
            <div
              style={{
                fontSize: '0.85rem',
                color: 'var(--omega-text-muted)',
                marginBottom: '1rem',
                lineHeight: 1.6,
              }}
            >
              탈퇴 후에는 동일 이메일로 재가입할 수 있지만, 기존 계정의 분석 이력은
              익명화된 형태로 남아있게 됩니다. 이 작업은{' '}
              <strong style={{ color: '#EF4444' }}>되돌릴 수 없습니다</strong>.
            </div>
            <div className="form-group">
              <label className="form-label">현재 비밀번호</label>
              <input
                type="password"
                className="form-input"
                placeholder="본인 확인을 위해 비밀번호를 입력하세요"
                value={withdrawPassword}
                onChange={(e) => setWithdrawPassword(e.target.value)}
                autoFocus
              />
            </div>
            <div className="form-group">
              <label className="form-label">
                확인 문구 — <code>탈퇴합니다</code> 를 정확히 입력
              </label>
              <input
                type="text"
                className="form-input"
                placeholder="탈퇴합니다"
                value={withdrawConfirmText}
                onChange={(e) => setWithdrawConfirmText(e.target.value)}
              />
            </div>
            <div
              style={{
                display: 'flex',
                gap: '0.5rem',
                justifyContent: 'flex-end',
                marginTop: '1rem',
              }}
            >
              <button
                className="btn btn-sm btn-secondary"
                onClick={() => {
                  setShowWithdrawModal(false);
                  setWithdrawPassword('');
                  setWithdrawConfirmText('');
                }}
                disabled={withdrawing}
              >
                취소
              </button>
              <button
                className="btn btn-sm"
                style={{
                  background: '#EF4444',
                  color: 'white',
                  borderColor: '#EF4444',
                  opacity:
                    withdrawing ||
                    !withdrawPassword ||
                    withdrawConfirmText !== '탈퇴합니다'
                      ? 0.5
                      : 1,
                }}
                disabled={
                  withdrawing ||
                  !withdrawPassword ||
                  withdrawConfirmText !== '탈퇴합니다'
                }
                onClick={handleWithdraw}
              >
                {withdrawing ? '처리 중...' : '영구 탈퇴'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 내 문서 통계 + 도넛 차트 ── */}
      {stats && (
        <div className="card" style={{ marginBottom: '1.5rem', padding: '1.5rem' }}>
          <h3 style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <BarChart3 size={18} strokeWidth={1.5} /> 내 문서 현황
          </h3>

          {/* Stats Row */}
          <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
            <div style={{
              flex: '1 1 100px', padding: '1rem', borderRadius: 'var(--radius-md)',
              background: 'rgba(108,99,255,0.1)', border: '1px solid rgba(108,99,255,0.25)', textAlign: 'center',
            }}>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#6C63FF' }}>{stats.total}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--omega-text-muted)' }}>전체</div>
            </div>
            <div style={{
              flex: '1 1 100px', padding: '1rem', borderRadius: 'var(--radius-md)',
              background: 'rgba(76,205,196,0.1)', border: '1px solid rgba(76,205,196,0.25)', textAlign: 'center',
            }}>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#4ECDC4' }}>{stats.analyzed}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--omega-text-muted)' }}>분석완료</div>
            </div>
            <div style={{
              flex: '1 1 100px', padding: '1rem', borderRadius: 'var(--radius-md)',
              background: 'rgba(255,217,61,0.1)', border: '1px solid rgba(255,217,61,0.25)', textAlign: 'center',
            }}>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#FFD93D' }}>{stats.pending}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--omega-text-muted)' }}>대기중</div>
            </div>
          </div>

          {/* Horizontal Bar Chart (sorted by count desc) */}
          {chartStats.length > 0 && (() => {
            const sorted = [...chartStats].sort((a, b) => b.count - a.count);
            const maxCount = sorted[0]?.count || 1;
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {sorted.map((s, i) => {
                  const pct = (s.count / maxCount) * 100;
                  const color = CHART_COLORS[i % CHART_COLORS.length];
                  return (
                    <div
                      key={s.category}
                      onClick={() => handleCategoryChange(s.category)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '0.65rem',
                        cursor: 'pointer', padding: '0.25rem 0',
                        opacity: activeCategory === s.category ? 1 : 0.85,
                        transition: 'opacity 0.2s',
                      }}
                    >
                      <span style={{
                        width: '90px', flexShrink: 0, fontSize: '0.8rem',
                        fontWeight: activeCategory === s.category ? 700 : 500,
                        color: activeCategory === s.category ? color : 'var(--omega-text)',
                        textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}>
                        {s.category}
                      </span>
                      <div style={{
                        flex: 1, height: '18px', borderRadius: '3px',
                        background: 'rgba(255,255,255,0.04)', overflow: 'hidden',
                      }}>
                        <div style={{
                          width: `${pct}%`, height: '100%',
                          background: `linear-gradient(90deg, ${color}, ${color}dd)`,
                          borderRadius: '3px', transition: 'width 0.6s ease', minWidth: '2px',
                        }} />
                      </div>
                      <span style={{
                        width: '45px', flexShrink: 0, fontSize: '0.78rem',
                        fontWeight: 600, color: 'var(--omega-text-muted)',
                        fontVariantNumeric: 'tabular-nums', textAlign: 'right',
                      }}>
                        {s.count}건
                      </span>
                    </div>
                  );
                })}
              </div>
            );
          })()}
        </div>
      )}

      {/* ── 카테고리 필터 탭 ── */}
      <div className="card-header" style={{ marginBottom: '0.5rem' }}>
        <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <FolderOpen size={16} strokeWidth={1.5} /> 내 문서 목록 ({docs.length}건)
        </div>
        <Link to="/upload" className="btn btn-primary btn-sm">+ 새 업로드</Link>
      </div>

      {/* Category Tabs */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: '0.4rem',
        marginBottom: '1rem', paddingBottom: '0.6rem',
        borderBottom: '1px solid var(--omega-border)',
      }}>
        {allCategories.map((stat) => (
          <button
            key={stat.category}
            onClick={() => handleCategoryChange(stat.category)}
            style={{
              padding: '0.4rem 0.85rem',
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
              fontSize: '0.8rem',
              fontWeight: 500,
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            {stat.category} ({stat.count})
          </button>
        ))}
      </div>

      {/* ── 문서 검색 ── */}
      <div style={{ marginBottom: '0.75rem' }}>
        <input
          type="text"
          placeholder="🔍 문서 검색 (ID, 파일명, 회사명...)"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
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

      {/* ── 필터 토글 (중복 문서 + 인사이트 생성됨) ── */}
      <div style={{ marginBottom: '1rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <button
          onClick={handleToggleDuplicates}
          style={{
            display: 'flex', alignItems: 'center', gap: '0.4rem',
            padding: '0.5rem 1rem', fontSize: '0.82rem', fontWeight: 600,
            background: showDuplicates ? 'rgba(108,99,255,0.15)' : 'var(--omega-surface-2)',
            color: showDuplicates ? '#6C63FF' : 'var(--omega-text-secondary)',
            border: showDuplicates ? '1px solid rgba(108,99,255,0.4)' : '1px solid var(--omega-border)',
            borderRadius: 'var(--radius-sm)', cursor: 'pointer', transition: 'all 0.2s',
          }}
        >
          <Copy size={14} /> 중복 문서 관리 {dupGroups.length > 0 && `(${dupGroups.length}그룹)`}
        </button>
        <button
          onClick={() => {
            setShowOnlyWithInsight((v) => !v);
            setCurrentPage(1);
          }}
          style={{
            display: 'flex', alignItems: 'center', gap: '0.4rem',
            padding: '0.5rem 1rem', fontSize: '0.82rem', fontWeight: 600,
            background: showOnlyWithInsight ? 'rgba(251,191,36,0.15)' : 'var(--omega-surface-2)',
            color: showOnlyWithInsight ? '#FBBF24' : 'var(--omega-text-secondary)',
            border: showOnlyWithInsight ? '1px solid rgba(251,191,36,0.4)' : '1px solid var(--omega-border)',
            borderRadius: 'var(--radius-sm)', cursor: 'pointer', transition: 'all 0.2s',
          }}
        >
          <Sparkles size={14} /> 인사이트 생성된 문서만
          {showOnlyWithInsight && ` (${docs.filter((d) => d.has_insight).length}건)`}
        </button>
      </div>

      {/* ── 중복 문서 관리 섹션 ── */}
      {showDuplicates && (
        <div className="card" style={{ marginBottom: '1.5rem', padding: '1.2rem' }}>
          <h3 style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '1rem' }}>
            <Copy size={16} /> 중복 문서 그룹
            <span style={{ fontSize: '0.75rem', color: 'var(--omega-text-muted)', fontWeight: 400 }}>
              같은 이름으로 표시되는 문서들을 그룹화합니다
            </span>
          </h3>

          {dupLoading ? (
            <div style={{ textAlign: 'center', padding: '2rem' }}>
              <div className="spinner"></div>
              <p style={{ color: 'var(--omega-text-muted)', marginTop: '0.5rem' }}>중복 문서 분석 중...</p>
            </div>
          ) : dupGroups.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--omega-text-muted)' }}>
              ✅ 중복 문서가 없습니다
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {dupGroups.map((group, gi) => (
                <div
                  key={gi}
                  style={{
                    border: '1px solid var(--omega-border)', borderRadius: 'var(--radius-sm)',
                    overflow: 'hidden',
                  }}
                >
                  {/* 그룹 헤더 */}
                  <div
                    onClick={() => setExpandedGroup(expandedGroup === gi ? null : gi)}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '0.7rem 1rem', cursor: 'pointer',
                      background: 'rgba(108,99,255,0.05)',
                      borderBottom: expandedGroup === gi ? '1px solid var(--omega-border)' : 'none',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{group.display_name}</span>
                      <span className="badge badge-warning" style={{ fontSize: '0.7rem' }}>
                        {group.documents.length}건 중복
                      </span>
                    </div>
                    <span style={{ color: 'var(--omega-text-muted)', fontSize: '0.8rem' }}>
                      {expandedGroup === gi ? '▲ 접기' : '▼ 펼치기'}
                    </span>
                  </div>

                  {/* 그룹 내 문서 목록 */}
                    {expandedGroup === gi && (
                      <div style={{ padding: '0.5rem' }}>
                        {group.documents.map((doc) => (
                          <div
                            key={doc.id}
                            style={{
                              display: 'flex', flexDirection: 'column', gap: '0.3rem',
                              padding: '0.6rem 0.75rem', borderRadius: '6px',
                              background: selectedIds.has(doc.id) ? 'rgba(108,99,255,0.08)' : 'transparent',
                              transition: 'background 0.15s',
                              marginBottom: '0.3rem',
                              border: '1px solid rgba(255,255,255,0.04)',
                            }}
                          >
                            {/* 상단: 체크박스 + ID + 파일명 + 상태 + 날짜 */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                              <input
                                type="checkbox"
                                checked={selectedIds.has(doc.id)}
                                onChange={() => toggleSelect(doc.id)}
                                style={{ cursor: 'pointer', accentColor: '#6C63FF', flexShrink: 0 }}
                              />
                              <span style={{ fontSize: '0.75rem', color: 'var(--omega-text-muted)', width: '40px', flexShrink: 0 }}>
                                #{doc.id}
                              </span>

                              {/* 원본 파일명 또는 이름 편집 */}
                              <div style={{ flex: 1, minWidth: 0 }}>
                                {renamingId === doc.id ? (
                                  <div style={{ display: 'flex', gap: '0.3rem', alignItems: 'center' }}>
                                    <input
                                      type="text"
                                      value={renameValue}
                                      onChange={(e) => setRenameValue(e.target.value)}
                                      onKeyDown={(e) => e.key === 'Enter' && handleRename(doc.id)}
                                      autoFocus
                                      style={{
                                        flex: 1, padding: '0.25rem 0.5rem', fontSize: '0.8rem',
                                        background: 'var(--omega-surface-2)', color: 'var(--omega-text)',
                                        border: '1px solid var(--omega-primary-light)',
                                        borderRadius: '4px', outline: 'none',
                                      }}
                                    />
                                    <button onClick={() => handleRename(doc.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#4ECDC4', padding: '2px' }}>
                                      <Check size={14} />
                                    </button>
                                    <button onClick={() => setRenamingId(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#E57373', padding: '2px' }}>
                                      <X size={14} />
                                    </button>
                                  </div>
                                ) : (
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                    <span
                                      style={{
                                        fontSize: '0.8rem', color: 'var(--omega-text)',
                                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                      }}
                                      title={doc.filename}
                                    >
                                      {doc.filename}
                                    </span>
                                    <button
                                      onClick={(e) => { e.stopPropagation(); setRenamingId(doc.id); setRenameValue(doc.filename); }}
                                      title="이름 변경"
                                      style={{
                                        background: 'none', border: 'none', cursor: 'pointer',
                                        color: 'var(--omega-text-muted)', padding: '2px', flexShrink: 0,
                                        opacity: 0.6, transition: 'opacity 0.2s',
                                      }}
                                      onMouseEnter={(e) => e.target.style.opacity = 1}
                                      onMouseLeave={(e) => e.target.style.opacity = 0.6}
                                    >
                                      <Pencil size={12} />
                                    </button>
                                  </div>
                                )}
                              </div>

                              <span className={`badge ${({'analyzed':'badge-success','ocr_done':'badge-warning','uploaded':'badge-info','failed':'badge-danger'})[doc.status] || 'badge-info'}`}
                                style={{ fontSize: '0.65rem', flexShrink: 0 }}>
                                {({'analyzed':'분석완료','ocr_done':'OCR완료','uploaded':'업로드','failed':'실패'})[doc.status] || doc.status}
                              </span>

                              <span style={{ fontSize: '0.7rem', color: 'var(--omega-text-muted)', flexShrink: 0, width: '80px', textAlign: 'right' }}>
                                {doc.created_at && new Date(doc.created_at).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                              </span>

                              <Link
                                to={`/documents/${doc.id}`}
                                onClick={saveScroll}
                                style={{
                                  fontSize: '0.68rem', padding: '0.15rem 0.4rem',
                                  borderRadius: '4px', textDecoration: 'none', flexShrink: 0,
                                  background: 'rgba(255,255,255,0.06)',
                                  color: 'var(--omega-text-muted)',
                                  transition: 'all 0.15s',
                                }}
                                onMouseEnter={e => { e.target.style.background = 'rgba(255,255,255,0.12)'; e.target.style.color = '#fff'; }}
                                onMouseLeave={e => { e.target.style.background = 'rgba(255,255,255,0.06)'; e.target.style.color = 'var(--omega-text-muted)'; }}
                              >
                                상세
                              </Link>
                            </div>

                            {/* 하단: 요약 미리보기 */}
                            {doc.summary && (
                              <div style={{
                                fontSize: '0.72rem', color: 'var(--omega-text-muted)',
                                paddingLeft: '2.5rem', lineHeight: 1.5,
                                opacity: 0.7,
                                overflow: 'hidden', textOverflow: 'ellipsis',
                                display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                              }}>
                                {doc.summary}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Documents Table */}
      {loading ? (
        <div className="loading-container">
          <div className="spinner spinner-lg"></div>
          <p>문서 로딩 중...</p>
        </div>
      ) : docs.length === 0 ? (
        <div className="empty-state">
          <div className="icon"><Inbox size={40} strokeWidth={1.2} style={{ opacity: 0.4 }} /></div>
          <h3>{activeCategory === '전체' ? '업로드된 문서가 없습니다' : `'${activeCategory}' 카테고리 문서가 없습니다`}</h3>
          <p>첫 번째 문서를 업로드해보세요!</p>
          <Link to="/upload" className="btn btn-primary" style={{ marginTop: '1rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
            <Upload size={15} strokeWidth={2} /> 문서 업로드
          </Link>
        </div>
      ) : (() => {
        const q = searchQuery.trim().toLowerCase();
        let filteredDocs = q
          ? docs.filter(doc => {
              const docCat = doc.category || '';
              const { display } = parseDisplayFilename(doc.filename, docCat, doc.company_name);
              return doc.filename.toLowerCase().includes(q)
                || display.toLowerCase().includes(q)
                || String(doc.id).includes(q);
            })
          : docs;

        // 인사이트 생성된 문서만 보기 필터
        if (showOnlyWithInsight) {
          filteredDocs = filteredDocs.filter((doc) => doc.has_insight);
        }

        // 페이지네이션 계산
        const totalPages = Math.ceil(filteredDocs.length / perPage);
        const safePage = Math.min(currentPage, totalPages || 1);
        const startIdx = (safePage - 1) * perPage;
        const paginatedDocs = filteredDocs.slice(startIdx, startIdx + perPage);

        return filteredDocs.length === 0 ? (
          <div className="empty-state" style={{ padding: '2rem' }}>
            <p>🔍 '{searchQuery}'에 대한 검색 결과가 없습니다</p>
          </div>
        ) : (
        <div className="table-container">
          {/* 페이지네이션 컨트롤 (상단) */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '0.5rem 0.75rem', marginBottom: '0.5rem',
            background: 'var(--omega-surface-2)', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--omega-border)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', color: 'var(--omega-text-muted)' }}>
              <span>페이지당</span>
              {[50, 100, 200].map(n => (
                <button
                  key={n}
                  onClick={() => { setPerPage(n); setCurrentPage(1); }}
                  style={{
                    padding: '0.25rem 0.6rem', fontSize: '0.78rem', fontWeight: 600,
                    background: perPage === n ? 'var(--omega-primary-light)' : 'transparent',
                    color: perPage === n ? '#fff' : 'var(--omega-text-muted)',
                    border: perPage === n ? '1px solid var(--omega-primary-light)' : '1px solid var(--omega-border)',
                    borderRadius: '4px', cursor: 'pointer', transition: 'all 0.2s',
                  }}
                >
                  {n}개
                </button>
              ))}
            </div>
            <span style={{ fontSize: '0.8rem', color: 'var(--omega-text-muted)' }}>
              총 {filteredDocs.length}건 중 {startIdx + 1}~{Math.min(startIdx + perPage, filteredDocs.length)}건
            </span>
          </div>
          {/* 일괄 삭제 툴바 */}
          {selectedIds.size > 0 && (
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '0.6rem 1rem', marginBottom: '0.5rem',
              background: 'rgba(184,67,67,0.08)', border: '1px solid rgba(184,67,67,0.25)',
              borderRadius: 'var(--radius-sm)',
            }}>
              <span style={{ fontSize: '0.85rem', color: '#E57373', fontWeight: 600 }}>
                ✓ {selectedIds.size}건 선택됨
              </span>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  onClick={() => setSelectedIds(new Set())}
                  style={{
                    padding: '0.3rem 0.7rem', fontSize: '0.78rem', fontWeight: 600,
                    background: 'rgba(255,255,255,0.06)', color: 'var(--omega-text-muted)',
                    border: '1px solid var(--omega-border)', borderRadius: '6px', cursor: 'pointer',
                  }}
                >
                  선택 해제
                </button>
                <button
                  onClick={handleBulkDelete}
                  disabled={bulkDeleting}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '0.3rem',
                    padding: '0.3rem 0.7rem', fontSize: '0.78rem', fontWeight: 600,
                    background: 'rgba(184,67,67,0.2)', color: '#E57373',
                    border: '1px solid rgba(184,67,67,0.35)', borderRadius: '6px', cursor: 'pointer',
                  }}
                >
                  {bulkDeleting ? (
                    <><span className="spinner" style={{ width: 12, height: 12, borderWidth: 1.5 }}></span> 삭제 중...</>
                  ) : (
                    <><Trash2 size={13} /> 선택 삭제</>
                  )}
                </button>
              </div>
            </div>
          )}
          <table>
            <thead>
              <tr>
                <th style={{ width: '36px', textAlign: 'center' }}>
                  <input
                    type="checkbox"
                    checked={paginatedDocs.length > 0 && paginatedDocs.every(d => selectedIds.has(d.id))}
                    onChange={() => toggleSelectAll(paginatedDocs)}
                    style={{ cursor: 'pointer', accentColor: '#6C63FF' }}
                    title="현재 페이지 전체 선택"
                  />
                </th>
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
                <th>상태</th>
                <th>업로드일</th>
                <th>작업</th>
              </tr>
            </thead>
            <tbody>
              {paginatedDocs.map((doc) => {
                const status = STATUS_MAP[doc.status] || { label: doc.status, class: 'badge-info' };
                const displayCat = doc.category || (activeCategory !== '전체' ? activeCategory : '');
                const { display: displayName } = parseDisplayFilename(doc.filename, displayCat, doc.company_name);
                return (
                  <tr key={doc.id} style={{
                    background: selectedIds.has(doc.id) ? 'rgba(108,99,255,0.06)' : undefined,
                  }}>
                    <td style={{ textAlign: 'center' }}>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(doc.id)}
                        onChange={() => toggleSelect(doc.id)}
                        style={{ cursor: 'pointer', accentColor: '#6C63FF' }}
                      />
                    </td>
                    <td>#{doc.id}</td>
                    <td style={{ fontWeight: 500, color: 'var(--omega-text)', maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={doc.filename}
                    >
                      {showOriginalFilename ? doc.filename : displayName}
                    </td>
                    <td><span className="badge badge-info">{doc.file_type.toUpperCase()}</span></td>
                    <td><span className={`badge ${status.class}`}>{status.label}</span></td>
                    <td>{formatDate(doc.created_at)}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                        <Link
                          to={`/documents/${doc.id}`}
                          onClick={saveScroll}
                          style={{
                            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                            padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.78rem',
                            fontWeight: 600, whiteSpace: 'nowrap', textDecoration: 'none',
                            background: 'rgba(255,255,255,0.06)', color: 'var(--omega-text)',
                            border: '1px solid rgba(255,255,255,0.1)', transition: 'all 0.2s',
                          }}
                        >
                          상세
                        </Link>
                        <button
                          onClick={() => handleDelete(doc.id)}
                          style={{
                            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                            padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.78rem',
                            fontWeight: 600, whiteSpace: 'nowrap', cursor: 'pointer',
                            background: 'rgba(184,67,67,0.12)', color: '#E57373',
                            border: '1px solid rgba(184,67,67,0.25)', transition: 'all 0.2s',
                          }}
                        >
                          삭제
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table >

          {/* 페이지네이션 컨트롤 (하단) */}
          {totalPages > 1 && (
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              gap: '0.3rem', padding: '1rem 0', marginTop: '0.5rem',
            }}>
              <button
                onClick={() => setCurrentPage(1)}
                disabled={safePage <= 1}
                style={{
                  padding: '0.3rem 0.6rem', fontSize: '0.78rem', fontWeight: 600,
                  background: 'var(--omega-surface-2)', color: safePage <= 1 ? 'var(--omega-border)' : 'var(--omega-text)',
                  border: '1px solid var(--omega-border)', borderRadius: '4px',
                  cursor: safePage <= 1 ? 'default' : 'pointer', transition: 'all 0.2s',
                }}
              >
                «
              </button>
              <button
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                disabled={safePage <= 1}
                style={{
                  padding: '0.3rem 0.6rem', fontSize: '0.78rem', fontWeight: 600,
                  background: 'var(--omega-surface-2)', color: safePage <= 1 ? 'var(--omega-border)' : 'var(--omega-text)',
                  border: '1px solid var(--omega-border)', borderRadius: '4px',
                  cursor: safePage <= 1 ? 'default' : 'pointer', transition: 'all 0.2s',
                }}
              >
                ‹ 이전
              </button>
              {(() => {
                const pages = [];
                let start = Math.max(1, safePage - 2);
                let end = Math.min(totalPages, start + 4);
                if (end - start < 4) start = Math.max(1, end - 4);
                for (let i = start; i <= end; i++) pages.push(i);
                return pages.map(p => (
                  <button
                    key={p}
                    onClick={() => setCurrentPage(p)}
                    style={{
                      padding: '0.3rem 0.55rem', fontSize: '0.78rem', fontWeight: 600,
                      background: p === safePage ? 'var(--omega-primary-light)' : 'var(--omega-surface-2)',
                      color: p === safePage ? '#fff' : 'var(--omega-text-muted)',
                      border: p === safePage ? '1px solid var(--omega-primary-light)' : '1px solid var(--omega-border)',
                      borderRadius: '4px', cursor: 'pointer', transition: 'all 0.2s',
                      minWidth: '30px',
                    }}
                  >
                    {p}
                  </button>
                ));
              })()}
              <button
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                disabled={safePage >= totalPages}
                style={{
                  padding: '0.3rem 0.6rem', fontSize: '0.78rem', fontWeight: 600,
                  background: 'var(--omega-surface-2)', color: safePage >= totalPages ? 'var(--omega-border)' : 'var(--omega-text)',
                  border: '1px solid var(--omega-border)', borderRadius: '4px',
                  cursor: safePage >= totalPages ? 'default' : 'pointer', transition: 'all 0.2s',
                }}
              >
                다음 ›
              </button>
              <button
                onClick={() => setCurrentPage(totalPages)}
                disabled={safePage >= totalPages}
                style={{
                  padding: '0.3rem 0.6rem', fontSize: '0.78rem', fontWeight: 600,
                  background: 'var(--omega-surface-2)', color: safePage >= totalPages ? 'var(--omega-border)' : 'var(--omega-text)',
                  border: '1px solid var(--omega-border)', borderRadius: '4px',
                  cursor: safePage >= totalPages ? 'default' : 'pointer', transition: 'all 0.2s',
                }}
              >
                »
              </button>
            </div>
          )}
        </div>
        );
      })()}

      {/* ── 회원탈퇴 (Danger Zone) — 페이지 최하단 ── */}
      {user?.role !== 'admin' && (
        <div
          className="card"
          style={{ marginTop: '3rem', border: '1px solid rgba(239,68,68,0.4)', opacity: 0.7 }}
        >
          <div className="card-header">
            <div
              className="card-title"
              style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#EF4444', fontSize: '0.85rem' }}
            >
              <Trash2 size={14} strokeWidth={1.5} /> 회원탈퇴
            </div>
          </div>
          <div
            style={{
              fontSize: '0.8rem',
              color: 'var(--omega-text-muted)',
              marginBottom: '0.75rem',
              lineHeight: 1.6,
            }}
          >
            탈퇴 시 회원 정보(이메일·사용자명·비밀번호)는 즉시 익명화되며 복구할 수 없습니다.
            업로드한 문서와 분석 결과는 익명화된 계정에 연결되어 보존됩니다.
            <br />
            개인정보보호법(PIPA) 준수 절차에 따라 처리됩니다.
          </div>
          <button
            className="btn btn-sm"
            style={{
              background: 'rgba(239,68,68,0.15)',
              borderColor: 'rgba(239,68,68,0.4)',
              color: '#EF4444',
              fontSize: '0.78rem',
            }}
            onClick={() => setShowWithdrawModal(true)}
          >
            회원탈퇴 신청
          </button>
        </div>
      )}
    </div>
  );
}
