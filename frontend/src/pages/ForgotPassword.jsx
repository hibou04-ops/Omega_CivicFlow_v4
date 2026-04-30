import { useState } from 'react';
import { Link } from 'react-router-dom';
import { authAPI } from '../api/client';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);

    try {
      const res = await authAPI.forgotPassword({ email });
      setSuccess(res.data.message || '비밀번호 재설정 링크가 전송되었습니다.');
    } catch (err) {
      setError(err.response?.data?.detail || '요청 처리 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container fade-in">
      <div className="auth-card">
        <div className="auth-header">
          <div className="omega-logo" style={{ color: '#F87171' }}>Ω</div>
          <h1>비밀번호 찾기</h1>
          <p>임계점 복구 (Critical Point Recovery)</p>
        </div>

        {error && <div className="alert alert-error">⚠️ {error}</div>}
        {success && <div className="alert alert-success">✅ {success}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">가입한 이메일 주소</label>
            <input
              type="email"
              className="form-input"
              placeholder="example@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-lg btn-full"
            disabled={loading}
            style={{ backgroundColor: '#EF4444' }}
          >
            {loading ? <><span className="spinner"></span> 발송 중...</> : '재설정 링크 받기'}
          </button>
        </form>

        <div className="auth-footer" style={{ marginTop: '20px', textAlign: 'center' }}>
          <Link to="/login" style={{ color: '#9CA3AF' }}>로그인 페이지로 돌아가기</Link>
        </div>
      </div>
    </div>
  );
}
