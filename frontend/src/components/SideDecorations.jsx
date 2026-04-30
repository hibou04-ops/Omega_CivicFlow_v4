import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { panelAPI } from '../api/client';

/* ── CSS 키프레임 ─────────────────────────────────────── */
const ANIM_STYLE = `
@keyframes tickerFlash {
  0%   { background: rgba(192,160,96,0.22); }
  40%  { background: rgba(192,160,96,0.08); }
  100% { background: transparent; }
}
@keyframes valueUp {
  0%   { color: #4EAA5E; text-shadow: 0 0 8px rgba(78,170,94,0.7); }
  100% { color: rgba(255,255,255,0.81); text-shadow: none; }
}
@keyframes valueDown {
  0%   { color: #C95B5B; text-shadow: 0 0 8px rgba(201,91,91,0.7); }
  100% { color: rgba(255,255,255,0.81); text-shadow: none; }
}
@keyframes pulseYellow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(240,192,64,0.7); opacity: 1; }
  50%       { box-shadow: 0 0 6px 3px rgba(240,192,64,0.4); opacity: 0.75; }
}
@keyframes pulseRed {
  0%, 100% { box-shadow: 0 0 0 0 rgba(224,80,80,0.8); opacity: 1; }
  40%       { box-shadow: 0 0 8px 4px rgba(224,80,80,0.5); opacity: 0.5; }
}
@keyframes slideInLog {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}
`;

/* ── 마켓 티커 초기값 ─────────────────────────────────── */
const BASE_TICKERS = [
  { name: 'KOSPI',   val: 2641.09,  decimals: 2, chgBase: 0.38,  unit: '%',  up: true  },
  { name: 'KOSDAQ',  val: 758.31,   decimals: 2, chgBase: -0.12, unit: '%',  up: false },
  { name: 'USD/KRW', val: 1321.50,  decimals: 2, chgBase: 0.05,  unit: '%',  up: true  },
  { name: 'KTB 10Y', val: 3.14,     decimals: 2, chgBase: -0.03, unit: 'bp', up: false },
  { name: 'WTI',     val: 81.22,    decimals: 2, chgBase: 1.04,  unit: '%',  up: true  },
  { name: 'GOLD',    val: 2312.40,  decimals: 2, chgBase: 0.27,  unit: '%',  up: true  },
  { name: 'NASDAQ',  val: 18239.92, decimals: 2, chgBase: 0.52,  unit: '%',  up: true  },
  { name: 'S&P500',  val: 5218.19,  decimals: 2, chgBase: 0.21,  unit: '%',  up: true  },
];

function fmtVal(val, decimals) {
  return val.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}
function fmtChg(chg, unit) {
  const sign = chg >= 0 ? '+' : '';
  return `${sign}${chg.toFixed(2)}${unit}`;
}

/* ── 경보 등불 ───────────────────────────────────────── */
const LEVEL_DOT = {
  ok:       { bg: '#4EAA5E', anim: 'none' },
  warning:  { bg: '#F0C040', anim: 'pulseYellow 1.6s ease-in-out infinite' },
  critical: { bg: '#E05050', anim: 'pulseRed 0.9s ease-in-out infinite' },
};

const DEFAULT_SERVICES = [
  'LLM 분석 서버', 'OCR 엔진', '보안 세션', '데이터베이스',
];

/* ════════════════════════════════════════════════════════
   왼쪽 패널
════════════════════════════════════════════════════════ */
export function LeftPanel() {
  const auth = useAuth();
  const isAdmin = auth ? auth.isAdmin : false;

  const [tickers, setTickers] = useState(BASE_TICKERS);
  const [activeIdx, setActiveIdx] = useState(0);
  const [flashIdx, setFlashIdx] = useState(-1);
  const [dirMap, setDirMap] = useState({});
  const [sysStatus, setSysStatus] = useState(null);

  /* 스타일 주입 */
  useEffect(() => {
    const el = document.createElement('style');
    el.id = 'omega-panel-anim';
    if (!document.getElementById('omega-panel-anim')) {
      el.textContent = ANIM_STYLE;
      document.head.appendChild(el);
    }
    return () => {
      const existing = document.getElementById('omega-panel-anim');
      if (existing) existing.remove();
    };
  }, []);

  /* 마켓 티커 애니메이션 */
  useEffect(() => {
    let cursor = 0;
    const t = setInterval(() => {
      const idx = cursor % BASE_TICKERS.length;
      cursor++;
      setActiveIdx(idx);
      setFlashIdx(idx);
      setTimeout(() => setFlashIdx(-1), 800);
      setTickers((prev) => {
        const next = [...prev];
        const item = { ...next[idx] };
        const delta = (Math.random() - 0.48) * item.val * 0.0003;
        item.val = Math.max(item.val + delta, 0.01);
        item.chgBase = item.chgBase + (Math.random() - 0.5) * 0.01;
        item.up = delta >= 0;
        next[idx] = item;
        setDirMap((dm) => ({ ...dm, [item.name]: delta >= 0 ? 'up' : 'down' }));
        return next;
      });
    }, 1000);
    return () => clearInterval(t);
  }, []);

  /* 시스템 상태 API 폴링 (30초) */
  useEffect(() => {
    if (!isAdmin) return;
    let mounted = true;
    const fetchStatus = async () => {
      try {
        const res = await panelAPI.getSystemStatus();
        if (mounted) setSysStatus(res.data);
      } catch (_e) {
        /* 폴링 실패 시 이전 상태 유지 */
      }
    };
    fetchStatus();
    const t = setInterval(fetchStatus, 30000);
    return () => {
      mounted = false;
      clearInterval(t);
    };
  }, [isAdmin]);

  return (
    <aside style={{
      width: 188, flexShrink: 0,
      borderRight: '1px solid rgba(192,160,96,0.12)',
      display: 'flex', flexDirection: 'column',
      paddingTop: '1.75rem',
      background: 'transparent',
      position: 'relative',
      overflowY: 'auto',
      overflowX: 'hidden',
      scrollbarWidth: 'thin',
      scrollbarColor: 'rgba(192,160,96,0.25) transparent',
    }}>
      {/* 수직 레이블 */}
      <div style={{
        writingMode: 'vertical-rl', textOrientation: 'mixed',
        fontSize: '0.6rem', letterSpacing: '0.22em',
        color: 'rgba(192,160,96,0.49)', fontWeight: 700,
        textTransform: 'uppercase', paddingLeft: '1.1rem',
        marginBottom: '1.75rem', userSelect: 'none',
      }}>
        MARKET INTELLIGENCE
      </div>

      <div style={{
        height: 1,
        background: 'linear-gradient(to right, transparent, rgba(192,160,96,0.25), transparent)',
        marginBottom: '1rem',
      }} />

      {/* 티커 목록 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0, flex: 1 }}>
        {tickers.map((t, i) => {
          const isFlash  = flashIdx === i;
          const isActive = activeIdx === i;
          const dir      = dirMap[t.name];
          const valAnim  = isFlash
            ? (dir === 'up' ? 'valueUp 0.8s ease-out forwards' : 'valueDown 0.8s ease-out forwards')
            : 'none';

          return (
            <div key={t.name} style={{
              padding: '0.55rem 1.1rem',
              borderBottom: '1px solid rgba(255,255,255,0.03)',
              animation: isFlash ? 'tickerFlash 0.8s ease-out forwards' : 'none',
              background: isActive && !isFlash ? 'rgba(192,160,96,0.04)' : 'transparent',
              transition: 'background 0.3s',
            }}>
              <div style={{
                fontSize: '0.65rem',
                color: isActive ? 'rgba(192,160,96,0.72)' : 'rgba(255,255,255,0.39)',
                letterSpacing: '0.08em', fontFamily: 'monospace',
                transition: 'color 0.3s',
                display: 'flex', alignItems: 'center', gap: 5,
              }}>
                {isFlash && (
                  <span style={{
                    width: 4, height: 4, borderRadius: '50%',
                    background: t.up ? '#4EAA5E' : '#C95B5B',
                    display: 'inline-block', flexShrink: 0,
                  }} />
                )}
                {t.name}
              </div>
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                alignItems: 'baseline', marginTop: 2,
              }}>
                <span style={{
                  fontSize: '0.8rem', fontWeight: 600,
                  color: 'rgba(255,255,255,0.81)',
                  fontFamily: 'monospace',
                  animation: valAnim,
                }}>
                  {fmtVal(t.val, t.decimals)}
                </span>
                <span style={{
                  fontSize: '0.62rem', fontFamily: 'monospace',
                  color: t.up ? '#4EAA5E' : '#C95B5B',
                  fontWeight: isFlash ? 700 : 400,
                  transition: 'color 0.3s',
                }}>
                  {fmtChg(t.chgBase, t.unit)}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* 하단 시스템 상태 — 관리자 전용 */}
      {isAdmin && (
        <div style={{
          borderTop: '1px solid rgba(192,160,96,0.12)',
          padding: '1rem 1.1rem 1.5rem',
        }}>
          <div style={{
            fontSize: '0.55rem', letterSpacing: '0.2em',
            color: 'rgba(192,160,96,0.49)', textTransform: 'uppercase',
            marginBottom: '0.6rem',
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            SYSTEM
            {sysStatus && sysStatus.overall_level && (
              <span style={{
                display: 'inline-block',
                width: 6, height: 6, borderRadius: '50%',
                background: (LEVEL_DOT[sysStatus.overall_level] || LEVEL_DOT.ok).bg,
                animation: (LEVEL_DOT[sysStatus.overall_level] || LEVEL_DOT.ok).anim,
                flexShrink: 0,
              }} />
            )}
          </div>

          {sysStatus && Array.isArray(sysStatus.services) ? (
            sysStatus.services.map((svc) => {
              const dot = LEVEL_DOT[svc.level] || LEVEL_DOT.ok;
              return (
                <div key={svc.name} style={{
                  fontSize: '0.62rem', fontFamily: 'monospace',
                  color: svc.level === 'ok' ? 'rgba(255,255,255,0.45)' : 'rgba(255,255,255,0.75)',
                  marginBottom: '0.35rem',
                  display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  <span style={{
                    width: 5, height: 5, borderRadius: '50%',
                    background: dot.bg,
                    animation: dot.anim,
                    flexShrink: 0,
                    display: 'inline-block',
                  }} />
                  <span style={{
                    flex: 1,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {svc.name}
                  </span>
                  {svc.level !== 'ok' && (
                    <span style={{
                      fontSize: '0.55rem',
                      color: svc.level === 'critical' ? '#E05050' : '#F0C040',
                      fontWeight: 700,
                    }}>
                      {svc.level === 'critical' ? '●' : '▲'}
                    </span>
                  )}
                </div>
              );
            })
          ) : (
            DEFAULT_SERVICES.map((name) => (
              <div key={name} style={{
                fontSize: '0.62rem', fontFamily: 'monospace',
                color: 'rgba(255,255,255,0.27)',
                marginBottom: '0.35rem',
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
                <span style={{
                  width: 5, height: 5, borderRadius: '50%',
                  background: 'rgba(255,255,255,0.17)',
                  flexShrink: 0, display: 'inline-block',
                }} />
                {name}
              </div>
            ))
          )}
        </div>
      )}
    </aside>
  );
}


/* ════════════════════════════════════════════════════════
   오른쪽 패널 — TOP TYPES + DART 검색 + Omega Cortex 인라인
════════════════════════════════════════════════════════ */
export function RightPanel() {
  const [stats, setStats] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const inputRef = useRef(null);

  // Autocomplete state
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const autocompleteTimer = useRef(null);

  /* 실제 DB 통계 폴링 (30초) */
  useEffect(() => {
    let mounted = true;
    const fetchStats = async () => {
      try {
        const res = await panelAPI.getStats();
        if (mounted) setStats(res.data);
      } catch (_e) { /* ignore */ }
    };
    fetchStats();
    const t = setInterval(fetchStats, 30000);
    return () => { mounted = false; clearInterval(t); };
  }, []);

  /* Autocomplete — 입력 시 300ms debounce */
  const handleInputChange = (e) => {
    const val = e.target.value;
    setSearchQuery(val);
    if (autocompleteTimer.current) clearTimeout(autocompleteTimer.current);
    if (val.trim().length < 1) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    autocompleteTimer.current = setTimeout(async () => {
      try {
        const res = await panelAPI.autocomplete(val.trim());
        const items = res.data?.suggestions || [];
        setSuggestions(items);
        setShowSuggestions(items.length > 0);
      } catch (_e) {
        setSuggestions([]);
      }
    }, 300);
  };

  const handleSuggestionClick = (item) => {
    setSearchQuery(item.name);
    setShowSuggestions(false);
    setSuggestions([]);
    setSearching(true);
    setSearchError('');
    setSearchResults([]);
    panelAPI.search(item.name).then(res => {
      const data = res.data || {};
      if (data.error && !(data.results && data.results.length)) {
        setSearchError(data.error);
      } else {
        setSearchResults(data.results || []);
      }
    }).catch(() => {
      setSearchError('검색 실패');
    }).finally(() => setSearching(false));
  };

  /* DART 검색 */
  const handleSearch = async (e) => {
    if (e) e.preventDefault();
    const q = searchQuery.trim();
    if (!q) return;
    setSearching(true);
    setSearchError('');
    setSearchResults([]);
    setShowSuggestions(false);
    try {
      const res = await panelAPI.search(q);
      const data = res.data || {};
      if (data.error && !(data.results && data.results.length)) {
        setSearchError(data.error);
      } else {
        setSearchResults(data.results || []);
      }
    } catch (_e) {
      setSearchError('검색 실패. 네트워크를 확인해주세요.');
    } finally {
      setSearching(false);
    }
  };

  return (
    <aside style={{
      width: 400, flexShrink: 0,
      borderLeft: '1px solid rgba(192,160,96,0.12)',
      display: 'flex', flexDirection: 'column',
      background: 'transparent',
      overflow: 'hidden',
    }}>
      {/* ── TOP TYPES 컴팩트 ── */}
      {stats && stats.top_categories && stats.top_categories.length > 0 && (
        <div style={{
          padding: '0.65rem 0.8rem 0.45rem',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}>
          <div style={{
            fontSize: '0.5rem', letterSpacing: '0.18em',
            color: 'rgba(192,160,96,0.6)', textTransform: 'uppercase',
            marginBottom: '0.3rem',
          }}>
            TOP TYPES
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            {stats.top_categories.map((cat) => (
              <span key={cat.category} style={{
                display: 'inline-flex', alignItems: 'center', gap: 4,
                fontSize: '0.58rem', fontFamily: 'monospace',
                padding: '0.15rem 0.45rem',
                background: 'rgba(192,160,96,0.06)',
                border: '1px solid rgba(192,160,96,0.12)',
                borderRadius: 3,
                color: 'rgba(255,255,255,0.6)',
              }}>
                <span style={{
                  overflow: 'hidden', textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap', maxWidth: 80,
                }}>
                  {cat.category}
                </span>
                <span style={{ color: 'rgba(192,160,96,0.75)', fontWeight: 700, fontSize: '0.56rem' }}>
                  {cat.count}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── DART 검색 컴팩트 ── */}
      <div style={{ padding: '0.45rem 0.8rem 0.6rem' }}>
        <div style={{
          fontSize: '0.5rem', letterSpacing: '0.18em',
          color: 'rgba(192,160,96,0.6)', textTransform: 'uppercase',
          marginBottom: '0.3rem',
        }}>
          DART 검색
        </div>

        <form onSubmit={handleSearch} style={{ display: 'flex', gap: 4, position: 'relative' }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <input
              ref={inputRef}
              value={searchQuery}
              onChange={handleInputChange}
              onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              placeholder="종목명 / 코드"
              autoComplete="off"
              style={{
                width: '100%',
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(192,160,96,0.18)',
                borderRadius: 3,
                padding: '0.28rem 0.45rem',
                fontSize: '0.62rem',
                color: 'rgba(255,255,255,0.75)',
                fontFamily: 'monospace',
                outline: 'none',
                minWidth: 0,
                boxSizing: 'border-box',
              }}
            />
            {/* Autocomplete dropdown */}
            {showSuggestions && suggestions.length > 0 && (
              <div style={{
                position: 'absolute', top: '100%', left: 0, right: 0,
                background: 'rgba(20,20,20,0.96)',
                border: '1px solid rgba(192,160,96,0.35)',
                borderRadius: 4, marginTop: 2,
                maxHeight: 160, overflowY: 'auto',
                zIndex: 9999,
                boxShadow: '0 4px 16px rgba(0,0,0,0.6)',
                scrollbarWidth: 'thin',
                scrollbarColor: 'rgba(192,160,96,0.3) transparent',
              }}>
                {suggestions.map((item, idx) => (
                  <div
                    key={idx}
                    onMouseDown={() => handleSuggestionClick(item)}
                    style={{
                      padding: '0.3rem 0.5rem',
                      fontSize: '0.58rem',
                      fontFamily: 'monospace',
                      cursor: 'pointer',
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      borderBottom: idx < suggestions.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                      transition: 'background 0.12s',
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(192,160,96,0.15)'}
                    onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                  >
                    <span style={{ color: 'rgba(255,255,255,0.85)', fontWeight: 500 }}>
                      {item.name}
                    </span>
                    <span style={{ color: 'rgba(192,160,96,0.7)', fontSize: '0.55rem' }}>
                      {item.code}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <button
            type="submit"
            disabled={searching}
            style={{
              background: 'rgba(192,160,96,0.15)',
              border: '1px solid rgba(192,160,96,0.25)',
              borderRadius: 3,
              padding: '0.28rem 0.5rem',
              fontSize: '0.6rem',
              color: 'rgba(192,160,96,0.85)',
              cursor: 'pointer',
              fontFamily: 'monospace',
              flexShrink: 0,
              opacity: searching ? 0.5 : 1,
            }}
          >
            {searching ? '…' : '↵'}
          </button>
        </form>

        {searchError && (
          <div style={{
            fontSize: '0.56rem', color: '#E05050',
            fontFamily: 'monospace', marginTop: '0.25rem',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <span>{searchError}</span>
            <span
              onClick={() => { setSearchError(''); setSearchQuery(''); }}
              style={{ cursor: 'pointer', color: 'rgba(255,255,255,0.4)', fontSize: '0.65rem', padding: '0 2px' }}
            >✕</span>
          </div>
        )}

        {searchResults.length > 0 && (
          <div style={{ marginTop: '0.3rem' }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              marginBottom: 3,
            }}>
              <span style={{ fontSize: '0.5rem', color: 'rgba(255,255,255,0.35)', fontFamily: 'monospace' }}>
                {searchResults.length}건
              </span>
              <span
                onClick={() => { setSearchResults([]); setSearchQuery(''); }}
                style={{
                  cursor: 'pointer', fontSize: '0.6rem', fontFamily: 'monospace',
                  color: 'rgba(255,255,255,0.4)', padding: '0 2px',
                  transition: 'color 0.15s',
                }}
                onMouseEnter={(e) => e.currentTarget.style.color = 'rgba(255,255,255,0.8)'}
                onMouseLeave={(e) => e.currentTarget.style.color = 'rgba(255,255,255,0.4)'}
              >✕</span>
            </div>
            <div style={{
              display: 'flex', flexDirection: 'column', gap: 3,
              maxHeight: 120, overflowY: 'auto',
            }}>
              {searchResults.map((r, i) => (
                <a
                  key={i}
                  href={r.url || '#'}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: 'block',
                    padding: '0.25rem 0.4rem',
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(192,160,96,0.08)',
                    borderRadius: 3,
                    textDecoration: 'none',
                  }}
                >
                  <div style={{
                    fontSize: '0.56rem',
                    color: 'rgba(192,160,96,0.85)',
                    fontFamily: 'monospace', fontWeight: 600,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {r.corp_name}
                  </div>
                  <div style={{
                    fontSize: '0.53rem', color: 'rgba(255,255,255,0.5)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {r.report_nm}
                  </div>
                  <div style={{
                    fontSize: '0.48rem', color: 'rgba(255,255,255,0.28)',
                    fontFamily: 'monospace',
                  }}>
                    {r.rcept_dt
                      ? `${r.rcept_dt.slice(0, 4)}.${r.rcept_dt.slice(4, 6)}.${r.rcept_dt.slice(6, 8)}`
                      : ''}
                  </div>
                </a>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Omega Cortex 인라인 채팅 ── */}
      <ChatBotInline />
    </aside>
  );
}

/* ── Cortex 인라인 래퍼 (순환 import 방지 + 로그인 게이트) ── */
function ChatBotInline() {
  const auth = useAuth();
  const isAuthenticated = auth ? auth.isAuthenticated : false;
  const [ChatBot, setChatBot] = useState(null);

  useEffect(() => {
    if (isAuthenticated) {
      import('./ChatBot').then(mod => setChatBot(() => mod.default));
    }
  }, [isAuthenticated]);

  /* 비로그인 → 로그인 유도 */
  if (!isAuthenticated) {
    return (
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        borderTop: '1px solid rgba(192,160,96,0.12)',
        padding: '2rem 1rem',
        gap: 12,
      }}>
        <div style={{
          width: 36, height: 36, borderRadius: '50%',
          background: 'linear-gradient(135deg, rgba(192,160,96,0.25), rgba(192,160,96,0.08))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '1rem', color: 'rgba(192,160,96,0.6)',
          border: '1px solid rgba(192,160,96,0.18)',
        }}>Ω</div>
        <div style={{
          fontSize: '0.68rem', color: 'rgba(255,255,255,0.5)',
          textAlign: 'center', lineHeight: 1.6,
          fontFamily: "'Inter', 'Noto Sans KR', sans-serif",
        }}>
          <span style={{ fontWeight: 600, color: 'rgba(192,160,96,0.8)' }}>Omega Cortex</span>
          <br />로그인 후 이용 가능합니다
        </div>
        <a
          href="/login"
          style={{
            fontSize: '0.6rem', fontFamily: 'monospace',
            padding: '0.3rem 0.8rem',
            background: 'rgba(192,160,96,0.12)',
            border: '1px solid rgba(192,160,96,0.3)',
            borderRadius: 4,
            color: 'rgba(192,160,96,0.9)',
            textDecoration: 'none',
            transition: 'background 0.2s',
            letterSpacing: '0.04em',
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'rgba(192,160,96,0.22)'}
          onMouseLeave={e => e.currentTarget.style.background = 'rgba(192,160,96,0.12)'}
        >
          로그인 →
        </a>
      </div>
    );
  }

  if (!ChatBot) return null;
  return <ChatBot inline />;
}

