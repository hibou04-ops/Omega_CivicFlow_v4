import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authAPI } from '../api/client';

export default function AdminRegisterPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [masterKey, setMasterKey] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (password.length < 8) {
      setError('비밀번호는 8자 이상이어야 합니다.');
      return;
    }

    setLoading(true);
    try {
      await authAPI.masterRegister({ 
        email, 
        username, 
        password, 
        master_key: masterKey 
      });
      setSuccess('마스터 권한이 부여되었습니다. 인증 이메일을 확인하거나 대시보드로 이동하세요.');
      setTimeout(() => navigate('/login'), 3500);
    } catch (err) {
      setError(err.response?.data?.detail || '마스터 계정 생성에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container fade-in">
      <div className="auth-card" style={{ border: '1px solid #F59E0B', boxShadow: '0 0 20px rgba(245, 158, 11, 0.2)' }}>
        <div className="auth-header">
          <div className="omega-logo" style={{ color: '#F59E0B' }}>Ω</div>
          <h1 style={{ color: '#F59E0B' }}>창조자 권한 등록</h1>
          <p>마스터 비밀키를 통한 관리자 계정 생성 게이트웨이</p>
        </div>

        {error && <div className="alert alert-error">⚠️ {error}</div>}
        {success && <div className="alert alert-success">✅ {success}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" style={{ color: '#FCD34D' }}>마스터 암호키 (Master Key)</label>
            <input
              type="password"
              className="form-input"
              placeholder="시스템 창조자 고유 증명"
              value={masterKey}
              onChange={(e) => setMasterKey(e.target.value)}
              required
              style={{ borderColor: '#B45309' }}
            />
          </div>

          <div className="form-group">
            <label className="form-label">이메일</label>
            <input
              type="email"
              className="form-input"
              placeholder="admin@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">관리자명</label>
            <input
              type="text"
              className="form-input"
              placeholder="루트 관리자 이름"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">비밀번호</label>
            <input
              type="password"
              className="form-input"
              placeholder="8자 이상 특수문자 권장"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>

          <button
            type="submit"
            className="btn btn-lg btn-full"
            disabled={loading}
            style={{ backgroundColor: '#D97706', color: '#fff', border: 'none' }}
          >
            {loading ? <><span className="spinner"></span> 동기화 중...</> : '마스터 권한 획득 (Admin Register)'}
          </button>
        </form>

        <div className="auth-footer">
          <Link to="/login" style={{ color: '#9CA3AF' }}>돌아가기</Link>
        </div>
      </div>
    </div>
  );
}
