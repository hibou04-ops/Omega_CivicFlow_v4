import { useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { authAPI } from '../api/client';

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const navigate = useNavigate();
  
  const [newPassword, setNewPassword] = useState('');
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

  // 토큰 미존재 시 강제 에러 방출
  if (!token) {
    return (
      <div className="auth-container fade-in">
        <div className="auth-card">
          <div className="alert alert-error">
            ⚠️ 잘못된 접근입니다. 비밀번호 재설정 토큰이 존재하지 않습니다.
          </div>
          <button onClick={() => navigate('/login')} className="btn btn-primary btn-lg btn-full" style={{ marginTop: '20px' }}>
            돌아가기
          </button>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (newPassword !== confirmPassword) {
      setError('비밀번호가 일치하지 않습니다.');
      return;
    }

    const pwErr = validatePassword(newPassword);
    if (pwErr) {
      setPasswordError(pwErr);
      setError('비밀번호 양식이 맞지 않습니다. 아래 조건을 확인해주세요.');
      return;
    }

    setLoading(true);

    try {
      const res = await authAPI.resetPassword({ token, new_password: newPassword });
      setSuccess(res.data.message || '비밀번호가 성공적으로 재설정되었습니다.');
      // 3초 후 로그인으로 부드러운 위상 전환
      setTimeout(() => navigate('/login'), 3000);
    } catch (err) {
      setError(err.response?.data?.detail || '비밀번호 재설정에 실패했습니다. (토큰 만료 가능성)');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container fade-in">
      <div className="auth-card">
        <div className="auth-header">
          <div className="omega-logo" style={{ color: '#F87171' }}>Ω</div>
          <h1>새 비밀번호 설정</h1>
          <p>새로운 시공간 궤도로 진입하십시오</p>
        </div>

        {error && <div className="alert alert-error">⚠️ {error}</div>}
        {success && <div className="alert alert-success">✅ {success}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">새 비밀번호</label>
            <input
              type="password"
              className="form-input"
              placeholder="영문 + 숫자 + 특수문자 포함 8자 이상"
              value={newPassword}
              onChange={(e) => {
                setNewPassword(e.target.value);
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
              placeholder="위의 비밀번호와 동일하게 입력"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-lg btn-full"
            disabled={loading || !!success}
            style={{ backgroundColor: '#EF4444' }}
          >
            {loading ? <><span className="spinner"></span> 동기화 중...</> : '새 비밀번호 저장'}
          </button>
        </form>
      </div>
    </div>
  );
}
