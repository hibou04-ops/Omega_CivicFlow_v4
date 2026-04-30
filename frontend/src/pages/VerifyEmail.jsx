import { useEffect, useState } from 'react';
import { useSearchParams, Link, useNavigate } from 'react-router-dom';
import { authAPI } from '../api/client';

export default function VerifyEmail() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const [status, setStatus] = useState('loading'); // loading, success, error
  const [message, setMessage] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('인증 토큰이 유효하지 않거나 만료되었습니다.');
      return;
    }

    const verify = async () => {
      try {
        const res = await authAPI.verifyEmail({ token });
        setStatus('success');
        setMessage(res.data.message || '이메일 인증이 완료되었습니다.');
      } catch (err) {
        setStatus('error');
        setMessage(err.response?.data?.detail || '이메일 인증에 실패했습니다.');
      }
    };

    verify();
  }, [token]);

  return (
    <div className="auth-container fade-in">
      <div className="auth-card">
        <div className="auth-header">
          <div className="omega-logo">Ω</div>
          <h1>위상 복원 (Verification)</h1>
          <p>시스템 접근 권한 검증</p>
        </div>

        {status === 'loading' && (
          <div className="alert alert-info">
            <span className="spinner" style={{ marginRight: '10px' }}></span>
            인증 토큰을 확인 중입니다...
          </div>
        )}

        {status === 'success' && (
          <>
            <div className="alert alert-success">✅ {message}</div>
            <button
              onClick={() => navigate('/login')}
              className="btn btn-primary btn-lg btn-full"
              style={{ marginTop: '20px' }}
            >
              로그인 페이지로 이동
            </button>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="alert alert-error">⚠️ {message}</div>
            <button
              onClick={() => navigate('/register')}
              className="btn btn-secondary btn-lg btn-full"
              style={{ marginTop: '20px' }}
            >
              회원가입 다시하기
            </button>
          </>
        )}

      </div>
    </div>
  );
}
