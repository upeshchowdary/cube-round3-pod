import React, { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  Eye,
  EyeOff,
  LogIn,
  ShieldCheck,
  Sparkles,
  UserPlus,
} from 'lucide-react'
import {
  DEMO_PROFILES,
  enabledOAuthProviders,
  isSupabaseConfigured,
  loginAsDemoProfile,
  signInWithEmailPassword,
  signInWithOAuth,
  signUpWithEmailPassword,
  type OAuthProvider,
  type UserSession,
} from '../services/supabase'
import './LoginPage.css'

// The flow the control center watches, shown beside the sign-in on wide screens.
const FLOW = [
  { name: 'Receiving', does: 'checks what arrived against the PO' },
  { name: 'Prep', does: "Amazon's prep rules, for FBA units" },
  { name: 'Pack', does: 'the open box, for merchant orders' },
  { name: 'Returns', does: 'grades the returned item from photos' },
  { name: 'Recovery', does: 'contests fees the evidence contradicts' },
]

const initials = (name: string) => name.split(' ').map((w) => w[0]).join('').slice(0, 2)

interface LoginPageProps {
  onLoginSuccess: (session: UserSession) => void
}

export function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const navigate = useNavigate()
  const location = useLocation()
  // Opened from a deep link (e.g. /live?run=...) while signed out: go back there after signing in.
  const target = location.pathname === '/login' ? '/overview' : `${location.pathname}${location.search}`
  const [activeTab, setActiveTab] = useState<'signin' | 'signup'>('signin')

  // Form states
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [orgId, setOrgId] = useState('org_demo_alpha')
  const [providers, setProviders] = useState<OAuthProvider[]>([])
  const [showPassword, setShowPassword] = useState(false)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    enabledOAuthProviders().then(setProviders)
  }, [])

  const handleDemoLogin = (profileKey: string) => {
    setError(null)
    const session = loginAsDemoProfile(profileKey)
    onLoginSuccess(session)
    navigate(target)
  }

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setNotice(null)

    if (!email || !password) {
      setError('Please provide both email and password.')
      return
    }

    setLoading(true)
    try {
      const session = await signInWithEmailPassword(email.trim(), password)
      onLoginSuccess(session)
      navigate(target)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const handleSignUp = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setNotice(null)

    if (!email || !password) {
      setError('Email and password are required.')
      return
    }

    setLoading(true)
    try {
      const { session, requiresEmailConfirmation } = await signUpWithEmailPassword(
        email.trim(),
        password,
        fullName.trim() || email.split('@')[0],
        orgId.trim() || 'org_demo_alpha'
      )
      if (requiresEmailConfirmation) {
        setNotice('Account created. Open the link in the email we sent you, then sign in.')
        setActiveTab('signin')
      } else if (session) {
        onLoginSuccess(session)
        navigate(target)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const handleOAuth = async (provider: OAuthProvider) => {
    setError(null)
    try {
      await signInWithOAuth(provider)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
    }
  }

  return (
    <div className="login-viewport">
      <div className="login-shell">
      <aside className="login-aside">
        <span className="login-aside-kicker">CUBE Buildathon 2026 · Pod 05</span>
        <h2>One evidence trail for every unit.</h2>
        <p>Five agents look at each product in turn. The orchestrator keeps what each one saw and why, and asks a person when the evidence is not enough.</p>
        <ol className="login-flow">
          {FLOW.map((f, i) => (
            <li key={f.name} style={{ animationDelay: `${120 + i * 90}ms` }}>
              <span className="login-flow-dot">{i + 1}</span>
              <span><b>{f.name}</b> {f.does}</span>
            </li>
          ))}
        </ol>
        <span className="login-aside-foot"><ShieldCheck size={14} /> Every decision is stored as evidence; overrides keep the original.</span>
      </aside>
      <div className="login-card">
        <div className="login-header">
          <div className="login-brand">
            <img src="/logo-mark.png" alt="" className="login-mark" />
            <img src="/logo-sydon.webp" alt="Sydon" className="login-logo" />
          </div>
          <h1 className="login-title">Operations Control Center</h1>
          <p className="login-subtitle">
            CUBE Pod 05 · Autonomous Commerce Orchestration & Ledger
          </p>
          <div className={`auth-status-badge ${isSupabaseConfigured ? 'active' : 'demo'}`}>
            <span className="auth-status-dot" />
            {isSupabaseConfigured ? 'Accounts online · Supabase' : 'Demo profiles only'}
          </div>
        </div>

        {error && <div className="auth-error-banner">{error}</div>}
        {notice && <div className="auth-success-banner">{notice}</div>}

        {/* 1-Click Judge & Demo Fast Access */}
        <div className="login-section-title">
          <span>One-click access for judges</span>
          <Sparkles size={13} />
        </div>

        <div className="demo-access-grid">
          {DEMO_PROFILES.map((p) => (
            <button
              key={p.key}
              type="button"
              className="demo-profile-btn"
              onClick={() => handleDemoLogin(p.key)}
            >
              <span className="demo-avatar" style={{ backgroundColor: `${p.badgeColor}1f`, color: p.badgeColor }}>
                {initials(p.name)}
              </span>
              <div className="demo-profile-info">
                <div className="demo-profile-name">
                  <span>{p.name}</span>
                  <span
                    className="demo-role-badge"
                    style={{
                      backgroundColor: `${p.badgeColor}18`,
                      color: p.badgeColor,
                    }}
                  >
                    {p.role}
                  </span>
                </div>
                <div className="demo-profile-desc">{p.description}</div>
              </div>
              <div className="demo-profile-side">
                <span className="demo-profile-org">{p.org_id}</span>
                <ArrowRight size={14} className="demo-arrow" />
              </div>
            </button>
          ))}
        </div>

        {/* Accounts exist only in Supabase: without it there is nothing to sign in to, so no form (it used to accept any
            email and password as a demo session). */}
        {isSupabaseConfigured && (
        <>
        <div className="login-divider">
          <span>OR SIGN IN WITH YOUR ACCOUNT</span>
        </div>

        <div className="auth-tabs">
          <button
            type="button"
            className={`auth-tab ${activeTab === 'signin' ? 'active' : ''}`}
            onClick={() => setActiveTab('signin')}
          >
            Sign In
          </button>
          <button
            type="button"
            className={`auth-tab ${activeTab === 'signup' ? 'active' : ''}`}
            onClick={() => setActiveTab('signup')}
          >
            Create Account
          </button>
        </div>

        <form onSubmit={activeTab === 'signin' ? handleSignIn : handleSignUp} className="auth-form">
          {activeTab === 'signup' && (
            <>
              <div className="form-field">
                <label htmlFor="fullname-input">Full Name</label>
                <input
                  id="fullname-input"
                  type="text"
                  className="form-input"
                  placeholder="e.g. Alex Morgan"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                />
              </div>

              <div className="form-field">
                <label htmlFor="orgid-select">Organization</label>
                <select
                  id="orgid-select"
                  className="form-input code-font"
                  value={orgId}
                  onChange={(e) => setOrgId(e.target.value)}
                >
                  <option value="org_demo_alpha">org_demo_alpha</option>
                  <option value="org_demo_bravo">org_demo_bravo</option>
                </select>
              </div>
            </>
          )}

          <div className="form-field">
            <label htmlFor="email-input">Work Email</label>
            <input
              id="email-input"
              type="email"
              className="form-input code-font"
              placeholder="operator@company.com"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-field">
            <label htmlFor="password-input">Password</label>
            <div className="password-wrap">
              <input
                id="password-input"
                type={showPassword ? 'text' : 'password'}
                className="form-input"
                placeholder="••••••••••••"
                autoComplete={activeTab === 'signin' ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>

          <button type="submit" className="form-submit-btn" disabled={loading}>
            {loading ? (
              <span>{activeTab === 'signin' ? 'Signing in…' : 'Creating account…'}</span>
            ) : activeTab === 'signin' ? (
              <>
                <LogIn size={15} />
                <span>Sign In to Control Center</span>
              </>
            ) : (
              <>
                <UserPlus size={15} />
                <span>Create account</span>
              </>
            )}
          </button>
        </form>

        {providers.length > 0 && (
          <div className="oauth-row">
            {providers.map((p) => (
              <button key={p} type="button" className="oauth-btn" onClick={() => handleOAuth(p)}>
                {p === 'google' ? 'Google' : 'GitHub'} SSO
              </button>
            ))}
          </div>
        )}
        </>
        )}

        {!isSupabaseConfigured && (
          <div style={{ marginTop: 14 }}>
            <div className="supabase-info-card">
              <strong>Accounts are off:</strong> set <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> in the project root <code>.env</code> (on Render: Environment) to sign in with real accounts.
            </div>
          </div>
        )}

        <div className="login-footer-links">
          <Link to="/" className="return-link">
            <ArrowLeft size={13} />
            <span>Return to Public Showcase</span>
          </Link>
        </div>
      </div>
      </div>
    </div>
  )
}

export default LoginPage
