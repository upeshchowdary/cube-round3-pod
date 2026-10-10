import { createClient, type SupabaseClient, type User } from '@supabase/supabase-js'

export type UserRole = 'supervisor' | 'auditor' | 'operator' | 'admin'

export interface UserSession {
  id: string
  email: string
  name: string
  role: UserRole
  org_id: string
  provider: 'supabase' | 'demo'
  avatar_url?: string
}

export interface DemoProfile {
  id: string
  key: string
  name: string
  email: string
  role: UserRole
  org_id: string
  roleTitle: string
  description: string
  badgeColor: string
}

export const DEMO_PROFILES: DemoProfile[] = [
  {
    id: 'usr_demo_alpha',
    key: 'alpha_supervisor',
    name: 'Elena Vance',
    email: 'supervisor@alpha-logistics.cube',
    role: 'supervisor',
    org_id: 'org_demo_alpha',
    roleTitle: 'Operations Supervisor',
    description: 'Supervisor privileges · Full live workflow dispatch & human override clearance',
    badgeColor: '#16a34a',
  },
  {
    id: 'usr_demo_bravo',
    key: 'bravo_auditor',
    name: 'Marcus Reed',
    email: 'auditor@bravo-claims.cube',
    role: 'auditor',
    org_id: 'org_demo_bravo',
    roleTitle: 'Claims Auditor',
    description: 'Auditor privileges · Chain-of-custody verification & recovery charge audits',
    badgeColor: '#2f5fa8',
  },
  {
    id: 'usr_judge_evaluator',
    key: 'judge_evaluator',
    name: 'Cube Evaluator',
    email: 'judge@cube-hackathon.org',
    role: 'admin',
    org_id: 'org_demo_alpha',
    roleTitle: 'Hackathon Judge / Admin',
    description: 'Root evaluator clearance · Unrestricted access across all stages & organizations',
    badgeColor: '#a8701d',
  },
]

function normalizeSupabaseUrl(url: string): string {
  let cleaned = (url || '').trim()
  cleaned = cleaned.replace(/\/rest\/v1\/?$/, '')
  cleaned = cleaned.replace(/\/+$/, '')
  return cleaned
}

const rawSupabaseUrl = (
  import.meta.env.VITE_SUPABASE_URL ||
  import.meta.env.NEXT_PUBLIC_SUPABASE_URL ||
  ''
).trim()
const SUPABASE_URL = normalizeSupabaseUrl(rawSupabaseUrl)
const SUPABASE_ANON_KEY = (
  import.meta.env.VITE_SUPABASE_ANON_KEY ||
  import.meta.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  import.meta.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ||
  ''
).trim()

export const isSupabaseConfigured: boolean = Boolean(
  SUPABASE_URL &&
  SUPABASE_ANON_KEY &&
  !SUPABASE_URL.includes('your-project') &&
  !SUPABASE_ANON_KEY.includes('your-anon-key')
)

export const supabase: SupabaseClient | null = isSupabaseConfigured
  ? createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
      auth: {
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl: true,
      },
    })
  : null

const STORAGE_KEY = 'cube_pod_session'

export function getStoredSession(): UserSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as UserSession
  } catch (err) {
    console.warn('[auth] Failed to read stored session:', err)
    return null
  }
}

export function saveStoredSession(session: UserSession | null): void {
  try {
    if (session) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  } catch (err) {
    console.warn('[auth] Failed to persist session:', err)
  }
}

export function mapSupabaseUserToSession(user: User): UserSession {
  const meta = user.user_metadata || {}
  const role: UserRole = meta.role || 'supervisor'
  const org_id: string = meta.org_id || 'org_demo_alpha'
  const name: string = meta.full_name || meta.name || user.email?.split('@')[0] || 'Operator'

  return {
    id: user.id,
    email: user.email || '',
    name,
    role,
    org_id,
    provider: 'supabase',
    avatar_url: meta.avatar_url,
  }
}

export async function signInWithEmailPassword(email: string, password: string): Promise<UserSession> {
  if (!supabase) {
    throw new Error('Supabase is not configured. Please supply VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY or use 1-Click Demo Login.')
  }
  const { data, error } = await supabase.auth.signInWithPassword({ email, password })
  if (error) {
    throw error
  }
  if (!data.user) {
    throw new Error('No user returned by Supabase')
  }
  const session = mapSupabaseUserToSession(data.user)
  saveStoredSession(session)
  return session
}

export async function signUpWithEmailPassword(
  email: string,
  password: string,
  name: string,
  orgId: string,
  role: UserRole = 'supervisor'
): Promise<{ session: UserSession | null; requiresEmailConfirmation: boolean }> {
  if (!supabase) {
    throw new Error('Supabase is not configured. Please supply VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY or use 1-Click Demo Login.')
  }
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      data: {
        full_name: name,
        org_id: orgId,
        role: role,
      },
    },
  })
  if (error) {
    throw error
  }
  if (data.session && data.user) {
    const session = mapSupabaseUserToSession(data.user)
    saveStoredSession(session)
    return { session, requiresEmailConfirmation: false }
  }
  return { session: null, requiresEmailConfirmation: true }
}

export async function signInWithOAuth(provider: 'google' | 'github'): Promise<void> {
  if (!supabase) {
    throw new Error('Supabase is not configured.')
  }
  const { error } = await supabase.auth.signInWithOAuth({
    provider,
    options: {
      redirectTo: `${window.location.origin}/overview`,
    },
  })
  if (error) {
    throw error
  }
}

export function loginAsDemoProfile(key: string): UserSession {
  const profile = DEMO_PROFILES.find((p) => p.key === key) || DEMO_PROFILES[0]
  const session: UserSession = {
    id: profile.id,
    email: profile.email,
    name: profile.name,
    role: profile.role,
    org_id: profile.org_id,
    provider: 'demo',
  }
  saveStoredSession(session)
  return session
}

export async function logoutSession(): Promise<void> {
  if (supabase) {
    try {
      await supabase.auth.signOut()
    } catch (err) {
      console.warn('[auth] Supabase sign out warning:', err)
    }
  }
  saveStoredSession(null)
}
