/**
 * ═══════════════════════════════════════════════════════
 * Omega CivicFlow — API Client
 * 에너지 전송 경로 (Energy Transmission Path)
 * Axios 인스턴스 + JWT 인터셉터
 * ═══════════════════════════════════════════════════════
 */

import axios from 'axios';

const API_BASE_URL = '/';

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ── JWT 인터셉터: 요청에 토큰 자동 주입 ──
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('omega_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── 응답 인터셉터: 401 시 로그인 리다이렉트 ──
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('omega_token');
      localStorage.removeItem('omega_user');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

// ═══════════════════════════════════════════════════════
// AUTH API
// ═══════════════════════════════════════════════════════

export const authAPI = {
  register: (data) => client.post('/api/auth/register', data),
  masterRegister: (data) => client.post('/api/auth/master-register', data),
  login: (data) => client.post('/api/auth/login', data),
  getMe: () => client.get('/api/auth/me'),
  updateMe: (data) => client.patch('/api/auth/me', data),
  verifyEmail: (data) => client.post('/api/auth/verify-email', data),
  forgotPassword: (data) => client.post('/api/auth/forgot-password', data),
  resetPassword: (data) => client.post('/api/auth/reset-password', data),
  requestPasswordChange: (data) => client.post('/api/auth/request-password-change', data),
  confirmPasswordChange: (data) => client.post('/api/auth/confirm-password-change', data),
  requestWithdraw: (data) => client.post('/api/auth/request-withdraw', data),
  confirmWithdraw: (data) => client.post('/api/auth/confirm-withdraw', data),
};


// ═══════════════════════════════════════════════════════
// DOCUMENTS API
// ═══════════════════════════════════════════════════════

export const documentsAPI = {
  upload: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/api/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  uploadBatch: (files, sendEmail = false) => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    formData.append('send_email', sendEmail);
    return client.post('/api/documents/upload-batch', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000, // 10분 타임아웃 (다중 파일)
    });
  },
  list: () => client.get('/api/documents'),
  listByCategory: (category) => client.get(`/api/documents/by-category?category=${encodeURIComponent(category || '전체')}`),
  getDetail: (id) => client.get(`/api/documents/${id}`),
  delete: (id) => client.delete(`/api/documents/${id}`),
  batchStatus: (docIds) => client.get(`/api/documents/batch-status?doc_ids=${docIds}`),
  downloadReport: (id) => client.get(`/api/documents/download-report/${id}`, {
    responseType: 'blob',
  }),
  getInsight: (id) => client.get(`/api/documents/insight/${id}`),
  generateInsight: (id) => client.post(`/api/documents/insight/${id}`),
  downloadInsightPdf: (id) => client.get(`/api/documents/insight/${id}/download-pdf`, {
    responseType: 'blob',
  }),
  reanalyze: (id) => client.post(`/api/documents/${id}/reanalyze`),
  myStats: () => client.get('/api/documents/my-stats'),
  previewReport: (id) => `/api/documents/preview-report/${id}`,
  rename: (id, filename) => client.patch(`/api/documents/${id}/rename`, { filename }),
  getDuplicates: () => client.get('/api/documents/duplicates/list'),
};

// ═══════════════════════════════════════════════════════
// ADMIN API
// ═══════════════════════════════════════════════════════

export const adminAPI = {
  getDashboard: () => client.get('/api/admin/dashboard'),
  listAllDocuments: () => client.get('/api/admin/documents'),
  listDocumentsByCategory: (category) => client.get(`/api/admin/documents/by-category?category=${encodeURIComponent(category || '전체')}`),
  listUsers: () => client.get('/api/admin/users'),
  updateUserActive: (userId, isActive) =>
    client.patch(`/api/admin/users/${userId}/active`, { is_active: isActive }),
  reclassify: (docId, data) =>
    client.post(`/api/admin/documents/${docId}/reclassify`, data),
  getReclassHistory: (docId) =>
    client.get(`/api/admin/documents/${docId}/reclassifications`),
};

// ═══════════════════════════════════════════════════════
// PANEL API
// ═══════════════════════════════════════════════════════

export const panelAPI = {
  getStats: () => client.get('/api/panel/stats'),
  getSystemStatus: () => client.get('/api/panel/system-status'),
  getActivityLog: () => client.get('/api/panel/activity-log'),
  getChatConfig: () => client.get('/api/panel/chat/config'),
  search: (query) => client.post('/api/panel/search', { query }),
  autocomplete: (q) => client.get(`/api/panel/autocomplete?q=${encodeURIComponent(q)}`),
  chat: (message, history = [], requestId = null) =>
    client.post('/api/panel/chat', { message, history, request_id: requestId }),
};

export default client;

