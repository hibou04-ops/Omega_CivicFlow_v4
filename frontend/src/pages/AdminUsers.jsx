import { useState, useEffect } from 'react';
import { adminAPI } from '../api/client';

export default function AdminUsers() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadUsers();
  }, []);

  const loadUsers = async () => {
    try {
      const res = await adminAPI.listUsers();
      setUsers(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleActiveToggle = async (userId, currentActive) => {
    try {
      const res = await adminAPI.updateUserActive(userId, !currentActive);
      setUsers(users.map(u => u.id === userId ? res.data : u));
    } catch (err) {
      alert(err.response?.data?.detail || '상태 변경 실패');
    }
  };

  const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleString('ko-KR', {
      year: 'numeric', month: '2-digit', day: '2-digit',
    });
  };

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner spinner-lg"></div>
        <p>회원 로딩 중...</p>
      </div>
    );
  }

  return (
    <div className="page-container fade-in">
      <div className="page-header">
        <h1>👥 회원 관리</h1>
        <p>전체 회원 목록 — 계정 활성/비활성 관리</p>
      </div>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>이메일</th>
              <th>사용자명</th>
              <th>역할</th>
              <th>상태</th>
              <th>가입일</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>#{u.id}</td>
                <td style={{ color: 'var(--omega-text)' }}>{u.email}</td>
                <td>{u.username}</td>
                <td>
                  <span className={`badge ${u.role === 'admin' ? 'badge-warning' : 'badge-primary'}`}>
                    {u.role}
                  </span>
                </td>
                <td>
                  <span className={`badge ${u.is_active ? 'badge-success' : 'badge-danger'}`}>
                    {u.is_active ? '활성' : '비활성'}
                  </span>
                </td>
                <td>{formatDate(u.created_at)}</td>
                <td>
                  <button
                    className={`btn btn-sm ${u.is_active ? 'btn-danger' : 'btn-success'}`}
                    onClick={() => handleActiveToggle(u.id, u.is_active)}
                  >
                    {u.is_active ? '비활성화' : '활성화'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
