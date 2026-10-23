import { render } from 'preact';
import { useState, useEffect, useCallback } from 'preact/hooks';
import { isAuthenticated, getUser, logout, fetchConfig } from './lib/api.js';
import { Login } from './pages/Login.jsx';
import { QAChat } from './pages/QAChat.jsx';
import { TaskBoard } from './pages/TaskBoard.jsx';
import { Review } from './pages/Review.jsx';
import { Admin } from './pages/Admin.jsx';
import { FileLibrary } from './pages/FileLibrary.jsx';
import { RoleCheck } from './pages/RoleCheck.jsx';
import { completeSsoLogin, ssoLogout } from './lib/api.js';
import './styles/app.css';

// SSO return leg: the backend redirects here with the app JWT in the URL fragment.
// Store it and replace() to the deep link so the hop never lands in history.
if (window.location.pathname === '/sso-complete') {
  completeSsoLogin(window.location.hash);
}

const VALID_TABS = ['qa', 'files', 'tasks', 'review', 'admin', 'roles'];

function getTabFromHash() {
  const hash = window.location.hash;
  // Don't parse magic-link hashes as tabs
  if (!hash || hash.includes('magic-link')) return null;
  const match = hash.match(/^#\/(\w+)/);
  if (match && VALID_TABS.includes(match[1])) return match[1];
  return null;
}

function getSessionFromHash() {
  const hash = window.location.hash;
  const match = hash.match(/[?&]session=([a-f0-9-]+)/);
  return match ? match[1] : null;
}

function App() {
  const [authed, setAuthed] = useState(isAuthenticated());
  const [user, setUser] = useState(getUser());
  const [activeTab, _setActiveTab] = useState(getTabFromHash() || 'qa');
  const [homeSignal, setHomeSignal] = useState(0);
  const [navSessionId, setNavSessionId] = useState(getSessionFromHash());
  const [features, setFeatures] = useState({ tasks: false, review: true, qa: true });
  const [branding, setBranding] = useState({ title: 'Acme Insurance', subtitle: 'Policy & Claims Knowledge Agent', logo_icon: '🛡' });
  const [quickQuestions, setQuickQuestions] = useState([]);
  const [authMode, setAuthMode] = useState('password');
  const [samlEnabled, setSamlEnabled] = useState(false);
  const [sfOauth, setSfOauth] = useState(false);

  useEffect(() => {
    fetchConfig().then(cfg => {
      setFeatures(cfg.features || {});
      if (cfg.branding) setBranding(cfg.branding);
      if (cfg.quick_questions) setQuickQuestions(cfg.quick_questions);
      if (cfg.auth_mode) setAuthMode(cfg.auth_mode);
      setSamlEnabled(!!cfg.saml_enabled);
      setSfOauth(!!cfg.snowflake_oauth);
    });
  }, []);

  const setActiveTab = useCallback((tab) => {
    _setActiveTab(tab);
    window.history.replaceState(null, '', `#/${tab}`);
  }, []);

  // Listen for hash changes (e.g. clicking session links from Admin)
  useEffect(() => {
    function onHashChange() {
      const tab = getTabFromHash();
      if (tab) _setActiveTab(tab);
      const sid = getSessionFromHash();
      if (sid) setNavSessionId(sid);
    }
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const handleLogin = () => {
    setAuthed(true);
    setUser(getUser());
    // Navigate to the tab from the URL hash or saved destination
    const target = getTabFromHash() || sessionStorage.getItem('ncx_goto_tab');
    sessionStorage.removeItem('ncx_goto_tab');
    if (target && VALID_TABS.includes(target)) _setActiveTab(target);
  };

  const handleLogout = async () => {
    // Two sessions to end: Snowflake tokens server-side, then the app JWT.
    const entraLogout = await ssoLogout();
    logout();
    setAuthed(false);
    setUser(null);
    if (entraLogout) window.location.replace(entraLogout);
  };

  if (!authed) {
    // Save the intended destination so it persists through the magic-link flow
    const intended = getTabFromHash();
    if (intended) sessionStorage.setItem('ncx_goto_tab', intended);
    return <Login onLogin={handleLogin} branding={branding} authMode={authMode} samlEnabled={samlEnabled} />;
  }

  const isReviewer = user?.role === 'reviewer' || user?.role === 'admin';
  const isAdmin = user?.role === 'admin';

  return (
    <div style="display:flex;flex-direction:column;height:100vh;">
      <header class="app-header">
        <div class="app-logo">
          <div class="app-logo-icon">{branding.logo_icon}</div>
          <span class="app-title">{branding.title}</span>
          <span class="app-subtitle">{branding.subtitle}</span>
        </div>
        <nav class="header-nav">
          <button class="header-nav-btn" onClick={() => { setActiveTab('qa'); setHomeSignal(h => h + 1); }} title="Home">&#8962;</button>
          <button class={`header-nav-btn ${activeTab === 'qa' ? 'active' : ''}`} onClick={() => setActiveTab('qa')}>Q&A</button>
          <button class={`header-nav-btn ${activeTab === 'files' ? 'active' : ''}`} onClick={() => setActiveTab('files')}>Files</button>
          {features.tasks && (
            <button class={`header-nav-btn ${activeTab === 'tasks' ? 'active' : ''}`} onClick={() => setActiveTab('tasks')}>Tasks</button>
          )}
          {isReviewer && (
            <button class={`header-nav-btn ${activeTab === 'review' ? 'active' : ''}`} onClick={() => setActiveTab('review')}>Review</button>
          )}
          {isAdmin && (
            <button class={`header-nav-btn ${activeTab === 'admin' ? 'active' : ''}`} onClick={() => setActiveTab('admin')}>Admin</button>
          )}
          {sfOauth && (
            <button class={`header-nav-btn ${activeTab === 'roles' ? 'active' : ''}`} onClick={() => setActiveTab('roles')}>Role Check</button>
          )}
        </nav>
        <div class="header-spacer" />
        <div class="header-user">
          <span class="header-user-role">{user?.role}</span>
          <span>{user?.display_name || user?.email}</span>
          <button class="header-logout" onClick={handleLogout}>Logout</button>
        </div>
      </header>

      <div style="flex:1;min-height:0;display:flex;flex-direction:column;">
        {activeTab === 'qa' && <QAChat user={user} onLogout={handleLogout} homeSignal={homeSignal} initialSessionId={navSessionId} quickQuestions={quickQuestions} features={features} />}
        {activeTab === 'files' && <FileLibrary user={user} />}
        {activeTab === 'tasks' && features.tasks && <TaskBoard user={user} onLogout={handleLogout} />}
        {activeTab === 'review' && isReviewer && <Review user={user} />}
        {activeTab === 'admin' && isAdmin && <Admin user={user} />}
        {activeTab === 'roles' && sfOauth && <RoleCheck />}
      </div>
    </div>
  );
}

render(<App />, document.getElementById('app'));
