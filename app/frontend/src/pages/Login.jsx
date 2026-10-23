import { useState, useEffect, useRef } from 'preact/hooks';
import {
  requestMagicLink, verifyMagicLink, login, register,
  passkeyRegisterOptions, passkeyRegisterVerify,
  passkeyAuthOptions, passkeyAuthVerify,
} from '../lib/api.js';
import { ssoLoginUrl } from '../lib/api.js';
import { registerPasskey, authenticatePasskey } from '../lib/webauthn.js';

export function Login({ onLogin, branding = {}, authMode = 'password', samlEnabled = false }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(authMode === 'password' ? 'login' : 'email');
  const [mfaToken, setMfaToken] = useState(null);
  const [userData, setUserData] = useState(null);
  const verifyingRef = useRef(false);

  useEffect(() => {
    const hash = window.location.hash;
    const match = hash.match(/magic-link\?token=([^&]+)/);
    if (match && !verifyingRef.current) {
      verifyingRef.current = true;
      window.location.hash = '';
      handleMagicLinkVerify(match[1]);
    }
  }, []);

  const handleMagicLinkVerify = async (token) => {
    setStep('verifying');
    setLoading(true);
    setError('');
    try {
      const data = await verifyMagicLink(token);
      window.location.hash = '';

      if (data.passkey_required) {
        setMfaToken(data.mfa_token);
        setUserData(data.user);
        setStep('passkey-challenge');
        await startPasskeyAuth(data.mfa_token);
      } else if (data.needs_passkey_setup) {
        setUserData(data.user);
        setStep('passkey-setup');
      } else {
        onLogin();
      }
    } catch (err) {
      setError(err.message);
      window.location.hash = '';
      setStep(authMode === 'password' ? 'login' : 'email');
    } finally {
      setLoading(false);
    }
  };

  const handlePasswordLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      onLogin();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await register(email, password, displayName);
      onLogin();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSendLink = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await requestMagicLink(email);
      setStep('check-email');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const startPasskeyAuth = async (token) => {
    setLoading(true);
    setError('');
    try {
      const { options } = await passkeyAuthOptions(token);
      const credential = await authenticatePasskey(options);
      await passkeyAuthVerify(token, credential);
      onLogin();
    } catch (err) {
      if (err.name === 'NotAllowedError') {
        setError('Passkey authentication was cancelled.');
      } else {
        setError(err.message || 'Passkey authentication failed');
      }
    } finally {
      setLoading(false);
    }
  };

  const handlePasskeySetup = async () => {
    setLoading(true);
    setError('');
    try {
      const { options, challenge_token } = await passkeyRegisterOptions(mfaToken);
      const credential = await registerPasskey(options, challenge_token);
      await passkeyRegisterVerify(credential, mfaToken);
      onLogin();
    } catch (err) {
      if (err.name === 'NotAllowedError') {
        setError('Passkey registration is required. Please try again.');
      } else {
        setError(err.message || 'Passkey setup failed');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div class="login-container">
      <div class="login-card">
        <div class="login-header">
          <h1>{branding.title || 'Acme Insurance'}</h1>
          <p class="login-subtitle">{branding.subtitle || 'Policy & Claims Knowledge Agent'}</p>
        </div>

        {samlEnabled && (step === 'login' || step === 'email') && (
          <div style="margin-bottom:16px;">
            <button type="button" onClick={() => window.location.assign(ssoLoginUrl())}>
              Sign in with Microsoft (SSO)
            </button>
          </div>
        )}

        {step === 'verifying' && (
          <div class="magic-sent">
            <p class="magic-sent-text">Verifying your sign-in link...</p>
          </div>
        )}

        {step === 'login' && (
          <form onSubmit={handlePasswordLogin}>
            <div class="email-input-group">
              <input
                type="email"
                placeholder="you@example.com"
                value={email}
                onInput={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div class="email-input-group">
              <input
                type="password"
                placeholder="Password"
                value={password}
                onInput={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <div class="error">{error}</div>}
            <button type="submit" disabled={loading}>
              {loading ? '...' : 'Log In'}
            </button>
            <button type="button" class="link-btn" onClick={() => { setStep('register'); setError(''); }}>
              Create account
            </button>
          </form>
        )}

        {step === 'register' && (
          <form onSubmit={handleRegister}>
            <div class="email-input-group">
              <input
                type="email"
                placeholder="you@example.com"
                value={email}
                onInput={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div class="email-input-group">
              <input
                type="password"
                placeholder="Password"
                value={password}
                onInput={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <div class="email-input-group">
              <input
                type="text"
                placeholder="Display name (optional)"
                value={displayName}
                onInput={(e) => setDisplayName(e.target.value)}
              />
            </div>
            {error && <div class="error">{error}</div>}
            <button type="submit" disabled={loading}>
              {loading ? '...' : 'Create Account'}
            </button>
            <button type="button" class="link-btn" onClick={() => { setStep('login'); setError(''); }}>
              Already have an account? Log in
            </button>
          </form>
        )}

        {step === 'email' && (
          <form onSubmit={handleSendLink}>
            <p class="login-hint">No sign-up needed — just enter your email to get started.</p>
            <div class="email-input-group">
              <input
                type="email"
                placeholder="you@example.com"
                value={email}
                onInput={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            {error && <div class="error">{error}</div>}
            <button type="submit" disabled={loading}>
              {loading ? '...' : 'Send Sign-In Link'}
            </button>
          </form>
        )}

        {step === 'check-email' && (
          <div class="magic-sent">
            <div class="magic-sent-icon">✉️</div>
            <p class="magic-sent-text">Check your email for the sign-in link.</p>
            <p class="magic-sent-sub">Sent to <strong>{email}</strong></p>
            <button type="button" class="link-btn" onClick={() => { setStep('email'); setError(''); }}>
              Try a different email
            </button>
          </div>
        )}

        {step === 'passkey-challenge' && (
          <div class="magic-sent">
            <div class="magic-sent-icon">🔐</div>
            <p class="magic-sent-text">Verify your passkey</p>
            <p class="magic-sent-sub">Use your registered device to complete sign-in.</p>
            {error && <div class="error">{error}</div>}
            <button
              type="button"
              class="passkey-btn"
              onClick={() => startPasskeyAuth(mfaToken)}
              disabled={loading}
            >
              {loading ? 'Waiting...' : 'Retry Passkey'}
            </button>
          </div>
        )}

        {step === 'passkey-setup' && (
          <div class="magic-sent">
            <div class="magic-sent-icon">🔑</div>
            <p class="magic-sent-text">Set up a passkey</p>
            <p class="magic-sent-sub">
              Secure your account with a passkey. This will be required for future sign-ins.
            </p>
            {error && <div class="error">{error}</div>}
            <button
              type="button"
              class="passkey-btn"
              onClick={handlePasskeySetup}
              disabled={loading}
            >
              {loading ? 'Setting up...' : 'Register Passkey'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
