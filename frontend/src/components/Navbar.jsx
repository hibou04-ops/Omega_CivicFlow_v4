import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Upload, FileText, LayoutDashboard, Home } from 'lucide-react';

export default function Navbar() {
  const { user, isAdmin, isAuthenticated, logout } = useAuth();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  const isActive = (path) => location.pathname === path ? 'navbar-link active' : 'navbar-link';

  const handleNavClick = () => setMenuOpen(false);

  if (!isAuthenticated) return null;

  return (
    <nav className="navbar">
      <Link to="/home" className="navbar-brand" onClick={handleNavClick}>
        <span className="omega-symbol">Ω</span>
        <span>CivicFlow</span>
      </Link>

      {/* Hamburger Button */}
      <button
        className={`hamburger ${menuOpen ? 'open' : ''}`}
        onClick={() => setMenuOpen(!menuOpen)}
        aria-label="메뉴 열기"
      >
        <span></span>
        <span></span>
        <span></span>
      </button>

      {/* Navigation Links */}
      <div className={`navbar-nav ${menuOpen ? 'show' : ''}`}>
        <Link to="/home" className={isActive('/home')} onClick={handleNavClick}>
          <Home size={16} strokeWidth={1.8} />
          <span>홈</span>
        </Link>

        <Link to="/upload" className={isActive('/upload')} onClick={handleNavClick}>
          <Upload size={16} strokeWidth={1.8} />
          <span>업로드</span>
        </Link>

        <Link to="/mypage" className={isActive('/mypage')} onClick={handleNavClick}>
          <FileText size={16} strokeWidth={1.8} />
          <span>내 문서</span>
        </Link>

        {isAdmin && (
          <Link to="/admin/dashboard" className={isActive('/admin/dashboard')} onClick={handleNavClick}>
            <LayoutDashboard size={16} strokeWidth={1.8} />
            <span>대시보드</span>
          </Link>
        )}

        {/* Mobile-only user info */}
        <div className="navbar-user-mobile">
          <span className="navbar-username">{user?.username}</span>
          <span className={`navbar-role ${user?.role}`}>{user?.role}</span>
          <button className="btn btn-sm btn-secondary" onClick={() => { logout(); handleNavClick(); }}>
            로그아웃
          </button>
        </div>
      </div>

      {/* Desktop user section */}
      <div className="navbar-user">
        <span className="navbar-username">{user?.username}</span>
        <span className={`navbar-role ${user?.role}`}>{user?.role}</span>
        <button className="btn btn-sm btn-secondary" onClick={logout}>
          로그아웃
        </button>
      </div>

      {/* Overlay */}
      {menuOpen && <div className="navbar-overlay" onClick={() => setMenuOpen(false)} />}
    </nav>
  );
}
