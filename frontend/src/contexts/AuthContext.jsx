/**
 * ═══════════════════════════════════════════════════════
 * Omega CivicFlow — Auth Context
 * 사건의 지평선 상태 관리 (Event Horizon State Management)
 * ═══════════════════════════════════════════════════════
 */

import { createContext, useContext, useState, useEffect } from 'react';
import { authAPI } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('omega_token');
    if (token) {
      loadUser();
    } else {
      setLoading(false);
    }
  }, []);

  const loadUser = async () => {
    try {
      const res = await authAPI.getMe();
      setUser(res.data);
    } catch {
      localStorage.removeItem('omega_token');
      localStorage.removeItem('omega_user');
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const login = async (email, password) => {
    const res = await authAPI.login({ email, password });
    localStorage.setItem('omega_token', res.data.access_token);
    await loadUser();
    return res.data;
  };

  const register = async (email, username, password) => {
    const res = await authAPI.register({ email, username, password });
    return res.data;
  };

  const logout = () => {
    localStorage.removeItem('omega_token');
    localStorage.removeItem('omega_user');
    setUser(null);
    window.location.href = '/login';
  };

  const updateProfile = async (data) => {
    const res = await authAPI.updateMe(data);
    setUser(res.data);
    return res.data;
  };

  const value = {
    user,
    loading,
    login,
    register,
    logout,
    updateProfile,
    isAdmin: user?.role === 'admin',
    isAuthenticated: !!user,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}
