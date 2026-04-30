import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import Navbar from './components/Navbar';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import VerifyEmail from './pages/VerifyEmail';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import VerifyPasswordChange from './pages/VerifyPasswordChange';
import VerifyWithdraw from './pages/VerifyWithdraw';
import AdminRegisterPage from './pages/AdminRegisterPage';
import UploadPage from './pages/UploadPage';
import MyPage from './pages/MyPage';
import DocumentDetail from './pages/DocumentDetail';
import AdminDashboard from './pages/AdminDashboard';
import AdminUsers from './pages/AdminUsers';
import AdminDocuments from './pages/AdminDocuments';
import HomePage from './pages/HomePage';
import { LeftPanel, RightPanel } from './components/SideDecorations';

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <div className="app-layout">
          <Navbar />
          <div style={{
            display: 'flex',
            minHeight: 'calc(100vh - 64px)',
            position: 'relative',
          }}>
            <LeftPanel />
            <main style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
              <Routes>
                {/* Public */}
                <Route path="/login" element={<LoginPage />} />
                <Route path="/register" element={<RegisterPage />} />
                <Route path="/verify-email" element={<VerifyEmail />} />
                <Route path="/forgot-password" element={<ForgotPassword />} />
                <Route path="/reset-password" element={<ResetPassword />} />
                <Route path="/verify-password-change" element={<VerifyPasswordChange />} />
                <Route path="/verify-withdraw" element={<VerifyWithdraw />} />
                <Route path="/master-key" element={<AdminRegisterPage />} />

                {/* Public — 홈페이지 (비로그인 사용자도 접근 가능) */}
                <Route path="/home" element={<HomePage />} />

                {/* Protected — 일반 유저 + 관리자 */}
                <Route path="/upload" element={
                  <ProtectedRoute><UploadPage /></ProtectedRoute>
                } />
                <Route path="/mypage" element={
                  <ProtectedRoute><MyPage /></ProtectedRoute>
                } />
                <Route path="/documents/:id" element={
                  <ProtectedRoute><DocumentDetail /></ProtectedRoute>
                } />
                <Route path="/view/:id" element={
                  <ProtectedRoute><DocumentDetail /></ProtectedRoute>
                } />

                {/* Admin Only */}
                <Route path="/admin/dashboard" element={
                  <ProtectedRoute adminOnly><AdminDashboard /></ProtectedRoute>
                } />
                <Route path="/admin/users" element={
                  <ProtectedRoute adminOnly><AdminUsers /></ProtectedRoute>
                } />
                <Route path="/admin/documents" element={
                  <ProtectedRoute adminOnly><AdminDocuments /></ProtectedRoute>
                } />

                {/* Default */}
                <Route path="/" element={<Navigate to="/home" replace />} />
                <Route path="*" element={<Navigate to="/login" replace />} />
              </Routes>
            </main>
            <RightPanel />
          </div>
        </div>
      </AuthProvider>
    </BrowserRouter>
  );
}
