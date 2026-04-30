import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Upload, BarChart3, ArrowRight, Zap, Shield, Brain, Activity, Layers, Target } from 'lucide-react';

/* ── 홈페이지 전용 스타일 ── */
const HOME_STYLE = `
@keyframes heroGlow {
  0%, 100% { opacity: 0.6; }
  50%      { opacity: 1; }
}
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(20px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes lineExpand {
  from { width: 0; opacity: 0; }
  to   { width: 100%; opacity: 1; }
}
@keyframes subtleFloat {
  0%, 100% { transform: translateY(0px); }
  50%      { transform: translateY(-4px); }
}
@keyframes shimmer {
  0% { background-position: -200% center; }
  100% { background-position: 200% center; }
}
.omega-pillar-card {
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}
.omega-pillar-card:hover {
  transform: translateY(-3px);
  border-color: rgba(255,255,255,0.08) !important;
  box-shadow: 0 16px 48px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.04);
}
.omega-cta-primary {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.omega-cta-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(192,160,96,0.12);
}
.omega-cta-secondary {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.omega-cta-secondary:hover {
  transform: translateY(-1px);
  border-color: rgba(255,255,255,0.15) !important;
  color: rgba(255,255,255,0.8) !important;
}
.omega-step-chip {
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.omega-step-chip:hover {
  background: rgba(192,160,96,0.1) !important;
  border-color: rgba(192,160,96,0.25) !important;
  color: rgba(192,160,96,0.9) !important;
}
`;

export default function HomePage() {
  const { user } = useAuth();

  useEffect(() => {
    const el = document.createElement('style');
    el.id = 'omega-home-style';
    if (!document.getElementById('omega-home-style')) {
      el.textContent = HOME_STYLE;
      document.head.appendChild(el);
    }
    return () => {
      const existing = document.getElementById('omega-home-style');
      if (existing) existing.remove();
    };
  }, []);

  /* ── Core Identity Pillars ── */
  const PILLARS = [
    {
      icon: <Brain size={20} strokeWidth={1.5} />,
      title: 'Cognitive Engine',
      desc: '다차원 변수 분해, 목적함수 정의, 파레토 고유벡터 식별을 통한 최적화 경로 도출',
      accent: '192,160,96',
    },
    {
      icon: <Activity size={20} strokeWidth={1.5} />,
      title: 'Entropy Reduction',
      desc: '노이즈와 편향을 소거하고 전략적 명확성을 극대화하는 정보 정제 파이프라인',
      accent: '91,164,164',
    },
    {
      icon: <Shield size={20} strokeWidth={1.5} />,
      title: 'V-MASK Protocol',
      desc: '내부 추론 과정을 완벽히 은폐하고 최종 정제된 전략적 결과만을 출력하는 보안 계층',
      accent: '123,115,204',
    },
  ];

  /* ── Service Architecture Cards ── */
  const SERVICES = [
    {
      icon: <Layers size={18} strokeWidth={1.5} />,
      title: '문서 인텔리전스',
      desc: '다형식 금융 문서의 자동 인식 · 구조화 · 의미 추출',
      accent: '91,164,164',
    },
    {
      icon: <Target size={18} strokeWidth={1.5} />,
      title: '전략 분석 엔진',
      desc: '교차 비교 · 재무 지표 변동 추적 · 투자 시사점 도출',
      accent: '192,160,96',
    },
    {
      icon: <Zap size={18} strokeWidth={1.5} />,
      title: 'Insight 보고서',
      desc: '기업별 전략 요약 · 리스크 진단 · PDF 보고서 생성',
      accent: '123,115,204',
    },
  ];

  return (
    <div style={{
      minHeight: '100%',
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: '0 2rem 3rem',
      overflow: 'hidden',
    }}>

      {/* ═══ Hero Section ═══ */}
      <div style={{
        textAlign: 'center',
        paddingTop: '5rem',
        paddingBottom: '3rem',
        maxWidth: 680,
        animation: 'fadeInUp 0.8s cubic-bezier(0.16, 1, 0.3, 1)',
      }}>
        {/* Omega Symbol — Monumental */}
        <div style={{
          fontSize: '3rem',
          fontWeight: 800,
          background: 'linear-gradient(180deg, rgba(192,160,96,1) 0%, rgba(192,160,96,0.35) 100%)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          animation: 'heroGlow 4s ease-in-out infinite, subtleFloat 8s ease-in-out infinite',
          marginBottom: '1rem',
          lineHeight: 1,
          userSelect: 'none',
          letterSpacing: '-0.03em',
        }}>
          Ω
        </div>

        <h1 style={{
          fontSize: '2rem',
          fontWeight: 800,
          color: 'rgba(255,255,255,0.9)',
          letterSpacing: '-0.03em',
          marginBottom: '0.5rem',
          lineHeight: 1.15,
        }}>
          Omega <span style={{
            background: 'linear-gradient(135deg, rgba(192,160,96,0.9), rgba(192,160,96,0.45))',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}>CivicFlow</span>
        </h1>

        <p style={{
          fontSize: '0.82rem',
          color: 'rgba(255,255,255,0.28)',
          fontWeight: 500,
          lineHeight: 1.7,
          maxWidth: 440,
          margin: '0 auto 0.5rem',
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
        }}>
          Financial Document Intelligence
        </p>

        <p style={{
          fontSize: '0.78rem',
          color: 'rgba(255,255,255,0.2)',
          fontWeight: 400,
          lineHeight: 1.8,
          maxWidth: 480,
          margin: '0 auto 2.5rem',
        }}>
          에너지(E) · 엔트로피(S) · 효율(η) 프레임워크 기반<br />
          <span style={{ color: 'rgba(192,160,96,0.45)' }}>전략 자문 플랫폼</span>
        </p>

        {/* CTA Buttons */}
        <div style={{
          display: 'flex', justifyContent: 'center', gap: '0.6rem',
          animation: 'fadeInUp 1s cubic-bezier(0.16, 1, 0.3, 1)',
        }}>
          <Link to="/upload" className="omega-cta-primary" style={{
            display: 'inline-flex', alignItems: 'center', gap: 7,
            padding: '0.65rem 1.6rem',
            background: 'linear-gradient(135deg, rgba(192,160,96,0.22), rgba(192,160,96,0.08))',
            border: '1px solid rgba(192,160,96,0.3)',
            borderRadius: 10,
            color: 'rgba(192,160,96,0.9)',
            fontSize: '0.82rem',
            fontWeight: 600,
            textDecoration: 'none',
            letterSpacing: '0.02em',
          }}>
            <Upload size={15} strokeWidth={2} />
            문서 업로드
          </Link>
          <Link to="/mypage" className="omega-cta-secondary" style={{
            display: 'inline-flex', alignItems: 'center', gap: 7,
            padding: '0.65rem 1.6rem',
            background: 'rgba(255,255,255,0.025)',
            border: '1px solid rgba(255,255,255,0.07)',
            borderRadius: 10,
            color: 'rgba(255,255,255,0.45)',
            fontSize: '0.82rem',
            fontWeight: 500,
            textDecoration: 'none',
          }}>
            <BarChart3 size={15} strokeWidth={1.8} />
            내 문서 관리
          </Link>
        </div>
      </div>

      {/* ── Gold divider ── */}
      <div style={{
        width: '100%', maxWidth: 500, height: 1,
        background: 'linear-gradient(to right, transparent, rgba(192,160,96,0.15), transparent)',
        marginBottom: '3rem',
      }}>
        <div style={{
          height: 1,
          background: 'linear-gradient(to right, transparent, rgba(192,160,96,0.35), transparent)',
          animation: 'lineExpand 2s cubic-bezier(0.16, 1, 0.3, 1) forwards',
        }} />
      </div>

      {/* ═══ Core Architecture Pillars ═══ */}
      <div style={{
        textAlign: 'center',
        marginBottom: '1.5rem',
        animation: 'fadeInUp 1s cubic-bezier(0.16, 1, 0.3, 1)',
      }}>
        <p style={{
          fontSize: '0.6rem',
          color: 'rgba(192,160,96,0.35)',
          letterSpacing: '0.25em',
          textTransform: 'uppercase',
          fontWeight: 700,
        }}>
          Core Architecture
        </p>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: '0.75rem',
        maxWidth: 780,
        width: '100%',
        marginBottom: '3.5rem',
      }}>
        {PILLARS.map((p, i) => (
          <div
            key={i}
            className="omega-pillar-card"
            style={{
              padding: '1.6rem 1.3rem',
              background: `linear-gradient(165deg, rgba(${p.accent},0.06) 0%, rgba(255,255,255,0) 100%)`,
              border: `1px solid rgba(${p.accent},0.14)`,
              borderRadius: 14,
              animation: `fadeInUp ${0.9 + i * 0.12}s cubic-bezier(0.16, 1, 0.3, 1)`,
              cursor: 'default',
              boxShadow: `inset 0 1px 0 rgba(${p.accent},0.06), 0 0 32px rgba(${p.accent},0.05)`,
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            {/* top accent line */}
            <div style={{
              position: 'absolute', top: 0, left: 0, right: 0, height: 2,
              background: `linear-gradient(90deg, rgba(${p.accent},1) 0%, rgba(${p.accent},0.5) 50%, transparent 100%)`,
              borderRadius: '14px 14px 0 0',
            }} />
            <div style={{
              width: 36, height: 36,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 10,
              background: `linear-gradient(135deg, rgba(${p.accent},0.18), rgba(${p.accent},0.06))`,
              border: `1px solid rgba(${p.accent},0.22)`,
              color: `rgb(${p.accent})`,
              marginBottom: '0.9rem',
            }}>
              {p.icon}
            </div>
            <h3 style={{
              fontSize: '0.85rem',
              fontWeight: 700,
              color: 'rgba(255,255,255,0.92)',
              marginBottom: '0.4rem',
              letterSpacing: '-0.01em',
            }}>
              {p.title}
            </h3>
            <p style={{
              fontSize: '0.7rem',
              color: 'rgba(255,255,255,0.42)',
              lineHeight: 1.7,
            }}>
              {p.desc}
            </p>
          </div>
        ))}
      </div>

      {/* ═══ Service Pipeline ═══ */}
      <div style={{
        textAlign: 'center',
        marginBottom: '1.5rem',
        animation: 'fadeInUp 1.2s cubic-bezier(0.16, 1, 0.3, 1)',
      }}>
        <p style={{
          fontSize: '0.6rem',
          color: 'rgba(192,160,96,0.35)',
          letterSpacing: '0.25em',
          textTransform: 'uppercase',
          fontWeight: 700,
        }}>
          Service Pipeline
        </p>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: '0.75rem',
        maxWidth: 780,
        width: '100%',
        marginBottom: '3rem',
      }}>
        {SERVICES.map((s, i) => (
          <div
            key={i}
            className="omega-pillar-card"
            style={{
              padding: '1.4rem 1.2rem',
              background: `linear-gradient(165deg, rgba(${s.accent},0.05) 0%, rgba(255,255,255,0) 100%)`,
              border: `1px solid rgba(${s.accent},0.12)`,
              borderRadius: 12,
              animation: `fadeInUp ${1.0 + i * 0.12}s cubic-bezier(0.16, 1, 0.3, 1)`,
              cursor: 'default',
              boxShadow: `inset 0 1px 0 rgba(${s.accent},0.05), 0 0 30px rgba(${s.accent},0.04)`,
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            {/* top accent line */}
            <div style={{
              position: 'absolute', top: 0, left: 0, right: 0, height: 2,
              background: `linear-gradient(90deg, rgba(${s.accent},1) 0%, rgba(${s.accent},0.5) 50%, transparent 100%)`,
              borderRadius: '12px 12px 0 0',
            }} />
            <div style={{
              width: 32, height: 32,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 8,
              background: `linear-gradient(135deg, rgba(${s.accent},0.15), rgba(${s.accent},0.05))`,
              border: `1px solid rgba(${s.accent},0.2)`,
              color: `rgb(${s.accent})`,
              marginBottom: '0.75rem',
            }}>
              {s.icon}
            </div>
            <h3 style={{
              fontSize: '0.8rem',
              fontWeight: 700,
              color: 'rgba(255,255,255,0.88)',
              marginBottom: '0.3rem',
              letterSpacing: '-0.01em',
            }}>
              {s.title}
            </h3>
            <p style={{
              fontSize: '0.68rem',
              color: 'rgba(255,255,255,0.38)',
              lineHeight: 1.7,
            }}>
              {s.desc}
            </p>
          </div>
        ))}
      </div>

      {/* ═══ Harness AI Agentic Architecture ═══ */}
      <div style={{
        maxWidth: 780, width: '100%',
        marginBottom: '3.5rem',
        animation: 'fadeInUp 1.6s cubic-bezier(0.16, 1, 0.3, 1)',
      }}>
        {/* Section header */}
        <div style={{
          textAlign: 'center',
          marginBottom: '1.5rem',
        }}>
          <p style={{
            fontSize: '0.6rem',
            color: 'rgba(139, 92, 246, 0.5)',
            letterSpacing: '0.25em',
            textTransform: 'uppercase',
            fontWeight: 700,
            marginBottom: '0.6rem',
          }}>
            AI Agentic Architecture
          </p>
          <h2 style={{
            fontSize: '1.2rem',
            fontWeight: 800,
            color: 'rgba(255,255,255,0.85)',
            letterSpacing: '-0.02em',
            marginBottom: '0.4rem',
          }}>
            Harness Agent <span style={{
              background: 'linear-gradient(135deg, #A78BFA, #7C3AED)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}>Supervision</span> System
          </h2>
          <p style={{
            fontSize: '0.72rem',
            color: 'rgba(255,255,255,0.22)',
            lineHeight: 1.7,
            maxWidth: 520,
            margin: '0 auto',
          }}>
            다중 에이전트 감독 체계로 AI 분석 결과를 실시간 검증·보강합니다.<br/>
            단일 모델의 한계를 넘어, <span style={{ color: 'rgba(167, 139, 250, 0.7)' }}>구조적 신뢰성</span>을 확보합니다.
          </p>
        </div>

        {/* Harness Agent Cards */}
        <div style={{
          display: 'flex',
          justifyContent: 'center',
          marginBottom: '1.5rem',
        }}>

          {/* Omega-Prime Supervisor — 단일 메인 */}
          <div
            className="omega-pillar-card"
            style={{
              width: '100%',
              maxWidth: '380px',
              padding: '1.4rem 1.2rem',
              background: 'linear-gradient(165deg, rgba(139,92,246,0.05) 0%, rgba(255,255,255,0) 100%)',
              border: '1px solid rgba(139,92,246,0.12)',
              borderRadius: 12,
              cursor: 'default',
              boxShadow: 'inset 0 1px 0 rgba(139,92,246,0.05), 0 0 30px rgba(139,92,246,0.03)',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            {/* top accent line — wider/brighter for primary agent */}
            <div style={{
              position: 'absolute', top: 0, left: 0, right: 0, height: 2,
              background: 'linear-gradient(90deg, #8B5CF6 0%, #A78BFA 50%, transparent 100%)',
              borderRadius: '12px 12px 0 0',
            }} />
            <div style={{
              width: 32, height: 32,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 8,
              background: 'linear-gradient(135deg, rgba(139,92,246,0.15), rgba(139,92,246,0.05))',
              border: '1px solid rgba(139,92,246,0.2)',
              color: '#A78BFA',
              marginBottom: '0.75rem',
            }}>
              <Shield size={16} strokeWidth={2} />
            </div>
            <div style={{
              fontSize: '0.6rem', fontWeight: 700,
              color: 'rgba(139,92,246,0.55)',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              marginBottom: '0.25rem',
            }}>
              SUPERVISOR
            </div>
            <h3 style={{
              fontSize: '0.82rem', fontWeight: 700,
              color: 'rgba(255,255,255,0.88)',
              marginBottom: '0.35rem',
            }}>
              Omega-Prime Supervisor
            </h3>
            <p style={{
              fontSize: '0.68rem',
              color: 'rgba(255,255,255,0.25)',
              lineHeight: 1.7,
            }}>
              다중 도메인 감독 · 인과적 추론 검증 · 반론 스트레스 테스트 · 전략 보강
            </p>
            {/* Active indicator */}
            <div style={{
              marginTop: '0.7rem',
              display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
              padding: '0.2rem 0.5rem',
              borderRadius: 6,
              background: 'rgba(139,92,246,0.08)',
              border: '1px solid rgba(139,92,246,0.12)',
            }}>
              <div style={{
                width: 5, height: 5, borderRadius: '50%',
                background: '#A78BFA',
                boxShadow: '0 0 6px rgba(167,139,250,0.4)',
                animation: 'heroGlow 3s ease-in-out infinite',
              }} />
              <span style={{
                fontSize: '0.55rem', fontWeight: 600,
                color: 'rgba(167,139,250,0.7)',
                letterSpacing: '0.05em',
              }}>
                ACTIVE · Gemini 2.5 Flash
              </span>
            </div>
          </div>


        </div>

        {/* Architecture flow visualization */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: '0.4rem',
          padding: '0.75rem 0',
        }}>
          {['Primary Insight (Gemini Pro)', 'Omega-Prime 감독 검증', '최종 Insight'].map((step, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <div className="omega-step-chip" style={{
                padding: '0.4rem 0.75rem',
                background: i === 1
                  ? 'rgba(139,92,246,0.06)'
                  : 'rgba(255,255,255,0.02)',
                border: i === 1
                  ? '1px solid rgba(139,92,246,0.15)'
                  : '1px solid rgba(255,255,255,0.05)',
                borderRadius: 8,
                fontSize: '0.65rem',
                color: i === 1
                  ? 'rgba(167,139,250,0.7)'
                  : 'rgba(255,255,255,0.3)',
                fontWeight: i === 1 ? 600 : 500,
                whiteSpace: 'nowrap',
              }}>
                {step}
              </div>
              {i < 2 && (
                <ArrowRight size={11} style={{
                  color: i === 0 ? 'rgba(139,92,246,0.3)' : 'rgba(255,255,255,0.1)',
                  flexShrink: 0,
                }} />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ═══ Footer ═══ */}
      <div style={{
        textAlign: 'center',
        padding: '2rem 0 0.5rem',
        borderTop: '1px solid rgba(255,255,255,0.03)',
        width: '100%', maxWidth: 500,
      }}>
        <div style={{
          fontSize: '0.55rem',
          color: 'rgba(255,255,255,0.12)',
          letterSpacing: '0.15em',
          textTransform: 'uppercase',
          fontWeight: 600,
        }}>
          Omega CivicFlow — Powered by Omega-Prime · Harness AI Agentic Architecture
        </div>
      </div>
    </div>
  );
}
