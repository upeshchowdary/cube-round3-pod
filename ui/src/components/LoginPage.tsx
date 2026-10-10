import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  LogIn,
  Sparkles,
  UserCheck,
  UserPlus,
} from 'lucide-react'
import {
  DEMO_PROFILES,
  isSupabaseConfigured,
  loginAsDemoProfile,
  signInWithEmailPassword,
  signInWithOAuth,
  signUpWithEmailPassword,
  type UserRole,
  type UserSession,
} from '../services/supabase'
import './LoginPage.css'

interface LoginPageProps {
  onLoginSuccess: (session: UserSession) => void
}

export function LoginPage({ onLoginSuccess }: LoginPageProps) {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<'signin' | 'signup'>('signin')

  // Form states
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [orgId, setOrgId] = useState('org_demo_alpha')
  const [role, setRole] = useState<UserRole>('supervisor')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const handleDemoLogin = (profileKey: string) => {
    setError(null)
    const session = loginAsDemoProfile(profileKey)
    onLoginSuccess(session)
    navigate('/overview')
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
      if (isSupabaseConfigured) {
        const session = await signInWithEmailPassword(email.trim(), password)
        onLoginSuccess(session)
        navigate('/overview')
      } else {
        // Fallback for demo when Supabase credentials are not set
        const demoSession: UserSession = {
          id: `usr_${Math.random().toString(36).slice(2, 9)}`,
          email: email.trim(),
          name: fullName || email.split('@')[0],
          role: role,
          org_id: orgId || 'org_demo_alpha',
          provider: 'demo',
        }
        onLoginSuccess(demoSession)
        navigate('/overview')
      }
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
      if (isSupabaseConfigured) {
        const { session, requiresEmailConfirmation } = await signUpWithEmailPassword(
          email.trim(),
          password,
          fullName.trim() || email.split('@')[0],
          orgId.trim() || 'org_demo_alpha',
          role
        )
        if (requiresEmailConfirmation) {
          setNotice('Registration successful! Please check your email to confirm your account.')
        } else if (session) {
          onLoginSuccess(session)
          navigate('/overview')
        }
      } else {
        const demoSession: UserSession = {
          id: `usr_${Math.random().toString(36).slice(2, 9)}`,
          email: email.trim(),
          name: fullName.trim() || email.split('@')[0],
          role: role,
          org_id: orgId.trim() || 'org_demo_alpha',
          provider: 'demo',
        }
        onLoginSuccess(demoSession)
        navigate('/overview')
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const handleOAuth = async (provider: 'google' | 'github') => {
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
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                backgroundColor: isSupabaseConfigured ? '#16a34a' : '#a8701d',
              }}
            />
            {isSupabaseConfigured
              ? 'Supabase Cloud Auth Active'
              : 'Offline / 1-Click Demo Evaluation Mode'}
          </div>
        </div>

        {error && <div className="auth-error-banner">{error}</div>}
        {notice && <div className="auth-success-banner">{notice}</div>}

        {/* 1-Click Judge & Demo Fast Access */}
        <div className="login-section-title">
          <span>Fast Evaluator & Judge Access</span>
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
              <div className="demo-profile-info">
                <div className="demo-profile-name">
                  <UserCheck size={14} color={p.badgeColor} />
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
              <div className="demo-profile-org">{p.org_id}</div>
            </button>
          ))}
        </div>

        <div className="login-divider">
          <span>{isSupabaseConfigured ? 'OR SIGN IN WITH SUPABASE' : 'OR ENTERPRISE SIGN IN'}</span>
        </div>

        {/* Supabase / Custom Form */}
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

              <div className="form-row">
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
                <div className="form-field">
                  <label htmlFor="role-select">Role Clearance</label>
                  <select
                    id="role-select"
                    className="form-input"
                    value={role}
                    onChange={(e) => setRole(e.target.value as UserRole)}
                  >
                    <option value="supervisor">Supervisor</option>
                    <option value="auditor">Auditor</option>
                    <option value="operator">Operator</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
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
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="form-field">
            <label htmlFor="password-input">Password</label>
            <input
              id="password-input"
              type="password"
              className="form-input"
              placeholder="••••••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button type="submit" className="form-submit-btn" disabled={loading}>
            {loading ? (
              <span>Authenticating...</span>
            ) : activeTab === 'signin' ? (
              <>
                <LogIn size={15} />
                <span>Sign In to Control Center</span>
              </>
            ) : (
              <>
                <UserPlus size={15} />
                <span>Register Operator</span>
              </>
            )}
          </button>
        </form>

        {isSupabaseConfigured && (
          <div className="oauth-row">
            <button
              type="button"
              className="oauth-btn"
              onClick={() => handleOAuth('google')}
            >
              Google SSO
            </button>
            <button
              type="button"
              className="oauth-btn"
              onClick={() => handleOAuth('github')}
            >
              GitHub SSO
            </button>
          </div>
        )}

        {!isSupabaseConfigured && (
          <div style={{ marginTop: 14 }}>
            <div className="supabase-info-card">
              <strong>Live Supabase Connection:</strong> To connect your project's hosted Supabase database, define <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> in <code>.env</code>.
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
  )
}

export default LoginPage
