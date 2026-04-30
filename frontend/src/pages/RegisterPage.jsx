import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export default function RegisterPage() {
  const { register, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  const [passwordError, setPasswordError] = useState('');

  const validatePassword = (pw) => {
    if (pw.length < 8) return '비밀번호는 8자 이상이어야 합니다.';
    if (!/[a-zA-Z]/.test(pw)) return '영문자를 포함해야 합니다.';
    if (!/\d/.test(pw)) return '숫자를 포함해야 합니다.';
    if (!/[!@#$%^&*()\-_=+\[\]{};:'",.<>/?\\|`~]/.test(pw)) return '특수문자를 포함해야 합니다.';
    return '';
  };

  if (isAuthenticated) {
    navigate('/mypage', { replace: true });
    return null;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (password !== confirmPassword) {
      setError('비밀번호가 일치하지 않습니다.');
      return;
    }

    const pwErr = validatePassword(password);
    if (pwErr) {
      setPasswordError(pwErr);
      setError('비밀번호 양식이 맞지 않습니다. 아래 조건을 확인해주세요.');
      return;
    }

    setLoading(true);
    try {
      await register(email, username, password);
      setSuccess('회원가입 완료! 인증 이메일(터미널 로그)이 발송되었습니다. 링크를 확인해주세요.');
      setTimeout(() => navigate('/login'), 4000);
    } catch (err) {
      setError(err.response?.data?.detail || '회원가입에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container fade-in">
      <div className="auth-card">
        <div className="auth-header">
          <div className="omega-logo">Ω</div>
          <h1>CivicFlow 회원가입</h1>
          <p>공공 민원 문서 분석 시스템 등록</p>
        </div>

        {error && <div className="alert alert-error">⚠️ {error}</div>}
        {success && <div className="alert alert-success">✅ {success}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">이메일</label>
            <input
              type="email"
              className="form-input"
              placeholder="example@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">사용자명</label>
            <input
              type="text"
              className="form-input"
              placeholder="사용자명 (2자 이상)"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={2}
            />
          </div>

          <div className="form-group">
            <label className="form-label">비밀번호</label>
            <input
              type="password"
              className="form-input"
              placeholder="영문 + 숫자 + 특수문자 포함 8자 이상"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setPasswordError(validatePassword(e.target.value));
              }}
              required
              minLength={8}
            />
            <div style={{ fontSize: '0.75rem', color: '#9CA3AF', marginTop: '4px' }}>
              영문, 숫자, 특수문자(!@#$ 등)를 각각 1자 이상 포함, 총 8자 이상
            </div>
            {passwordError && (
              <div style={{ fontSize: '0.75rem', color: '#F87171', marginTop: '4px' }}>
                ⚠️ {passwordError}
              </div>
            )}
          </div>

          <div className="form-group">
            <label className="form-label">비밀번호 확인</label>
            <input
              type="password"
              className="form-input"
              placeholder="비밀번호를 다시 입력하세요"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-lg btn-full"
            disabled={loading}
          >
            {loading ? <><span className="spinner"></span> 등록 중...</> : '회원가입'}
          </button>
        </form>

        <div className="auth-footer">
          이미 계정이 있으신가요? <Link to="/login">로그인</Link>
        </div>
      </div>
    </div>
  );
}
