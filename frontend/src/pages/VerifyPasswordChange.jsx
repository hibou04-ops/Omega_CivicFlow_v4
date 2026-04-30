import { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { authAPI } from '../api/client';
import { useAuth } from '../contexts/AuthContext';

export default function VerifyPasswordChange() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const navigate = useNavigate();
  const { logout } = useAuth();

  const [status, setStatus] = useState('processing'); // processing | success | error
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('잘못된 접근입니다. 인증 토큰이 존재하지 않습니다.');
      return;
    }

    // 페이지 로드 시 자동으로 비밀번호 변경 확인
    const confirmChange = async () => {
      try {
        const res = await authAPI.confirmPasswordChange({ token });
        setStatus('success');
        setMessage(res.data.message || '비밀번호가 성공적으로 변경되었습니다.');
        // 3초 후 로그아웃 처리 후 로그인 이동
        setTimeout(() => {
          logout(); // 기존 토큰 제거 → window.location.href='/login' 호출
        }, 3000);
      } catch (err) {
        setStatus('error');
        setMessage(err.response?.data?.detail || '비밀번호 변경 인증에 실패했습니다. 링크가 만료되었을 수 있습니다.');
      }
    };

    confirmChange();
  }, [token, navigate]);

  return (
    <div className="auth-container fade-in">
      <div className="auth-card">
        <div className="auth-header">
          <div className="omega-logo" style={{ color: '#FBBF24' }}>Ω</div>
          <h1>비밀번호 변경 인증</h1>
        </div>

        {status === 'processing' && (
          <div style={{ textAlign: 'center', padding: '2rem' }}>
            <div className="spinner spinner-lg" style={{ margin: '0 auto 1rem' }}></div>
            <p style={{ color: 'var(--omega-text-muted)' }}>비밀번호 변경을 처리하고 있습니다...</p>
          </div>
        )}

        {status === 'success' && (
          <>
            <div className="alert alert-success">✅ {message}</div>
            <p style={{ textAlign: 'center', color: 'var(--omega-text-muted)', marginTop: '1rem' }}>
              3초 후 로그인 페이지로 이동합니다...
            </p>
            <button
              onClick={() => logout()}
              className="btn btn-primary btn-lg btn-full"
              style={{ marginTop: '1rem' }}
            >
              로그인으로 이동
            </button>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="alert alert-error">⚠️ {message}</div>
            <button
              onClick={() => navigate('/mypage')}
              className="btn btn-primary btn-lg btn-full"
              style={{ marginTop: '1rem' }}
            >
              마이페이지로 돌아가기
            </button>
          </>
        )}
      </div>
    </div>
  );
}
