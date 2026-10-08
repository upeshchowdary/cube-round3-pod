import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  AlertTriangle,
  Bot,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  CircleDot,
  Database,
  FileText,
  Gauge,
  GitBranch,
  Info,
  Layers3,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Workflow,
  X,
  XCircle,
} from 'lucide-react'
import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import '@fontsource-variable/bricolage-grotesque'
import '@fontsource-variable/figtree'
import '@fontsource-variable/jetbrains-mono'
import './App.css'
import './theme.css'
import { exampleAgents } from './data'
import CoverPage from './cover/CoverPage'
import { StageEvidence } from './components/StageEvidence'
import {
  api,
  stageVariant,
} from './services/api'
import type {
  CaseItem,
  EvidenceBundle,
  EvidenceRecord,
  HealthResponse,
  StageResult,
  WorkflowState,
} from './services/api'

const queryClient = new QueryClient()

const STAGES = ['receiving', 'prep', 'pack', 'returns', 'recovery'] as const

/** Per-stage verdict mix computed from the stored workflows (percent of runs that produced a verdict). */
function stageStats(workflows: WorkflowState[]) {
  return STAGES.map((stage) => {
    const ran = workflows
      .map((w) => w.stage_results.find((s) => s.stage === stage))
      .filter((s): s is StageResult => Boolean(s) && s!.state !== 'skipped' && s!.state !== 'pending')
    const pct = (n: number) => (ran.length ? Math.round((100 * n) / ran.length) : 0)
    return {
      agent: stage.charAt(0).toUpperCase() + stage.slice(1),
      runs: ran.length,
      pass: pct(ran.filter((s) => s.verdict === 'PASS').length),
      fail: pct(ran.filter((s) => s.verdict === 'FAIL').length),
      uncertain: pct(ran.filter((s) => s.verdict === 'UNCERTAIN' && s.state !== 'error').length),
      error: pct(ran.filter((s) => s.state === 'error').length),
      latency: ran.length ? Math.round(ran.reduce((sum, s) => sum + (s.duration_ms ?? 0), 0) / ran.length) / 1000 : 0,
    }
  })
}

/** The record a person should decide on: the first stage asking for a human that no override has resolved yet. */
function reviewTarget(w: WorkflowState) {
  const overridden = new Set(w.overrides.map((o) => o.supersedes.record_id))
  const s =
    w.stage_results.find((r) => r.needs_human && r.record_id && !overridden.has(r.record_id)) ??
    w.stage_results.find((r) => r.needs_human && r.record_id)
  return s ? { workflowId: w.workflow_id, recordId: s.record_id as string, currentVerdict: s.verdict ?? 'UNCERTAIN', stage: s.stage } : null
}

/** The Returns stage result, if the unit went through Returns. */
function returnsOf(w: WorkflowState) {
  return w.stage_results.find((s) => s.stage === 'returns' && s.state !== 'skipped')
}

/** Badge colour by what the outcome means, not just "claim or not". */
function outcomeVariant(outcome?: string | null): 'success' | 'danger' | 'warning' | 'primary' {
  if (outcome === 'CLEAN') return 'success'
  if (outcome === 'CLAIM_RECOMMENDED') return 'primary'
  if (outcome === 'EXCEPTION' || outcome === 'INCOMPLETE') return 'danger'
  return 'warning'
}

/** The lines of the Overview verdict chart. */
const VERDICT_LINES = [
  { key: 'pass', name: 'PASS', color: '#16a34a', dash: undefined },
  { key: 'fail', name: 'FAIL', color: '#b4493f', dash: undefined },
  { key: 'uncertain', name: 'UNCERTAIN', color: '#d8a24a', dash: undefined },
  { key: 'error', name: 'Stage error', color: '#6b7570', dash: '5 4' },
] as const

function VerdictTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="chart-tooltip">
      <strong>{label} · {row.runs} {row.runs === 1 ? 'run' : 'runs'}</strong>
      {VERDICT_LINES.map((l) => (
        <div key={l.key}><em style={{ color: l.color }}>{l.name}</em><span>{row[l.key]}%</span></div>
      ))}
    </div>
  )
}

function ActivityTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="chart-tooltip">
      <strong>{row.full}</strong>
      <div><em>Stages completed</em><span>{row.completed}</span></div>
      <div><em>Stage errors</em><span>{row.errors}</span></div>
      <div><em>Overrides</em><span>{row.overrides}</span></div>
    </div>
  )
}

/** Stage completions, stage errors and overrides per time bucket, read from every workflow's transitions.
 *  The bucket size adapts to the time span so the chart has at most ~24 points; empty buckets count as 0. */
function stageActivity(workflows: WorkflowState[]) {
  const events = workflows.flatMap((w) => w.transitions).filter((t) => t.at && ['stage_completed', 'stage_error', 'override'].includes(t.event))
  if (!events.length) return { points: [] as any[], bucketLabel: '' }
  const times = events.map((t) => Date.parse(t.at))
  const lo = Math.min(...times)
  const hi = Math.max(...times)
  const sizes: Array<[number, string]> = [[60e3, 'minute'], [5 * 60e3, '5 minutes'], [15 * 60e3, '15 minutes'], [3600e3, 'hour'], [6 * 3600e3, '6 hours'], [86400e3, 'day']]
  const [size, bucketLabel] = sizes.find(([s]) => (hi - lo) / s <= 24) ?? sizes[sizes.length - 1]
  const start = Math.floor(lo / size) * size
  const n = Math.floor((hi - start) / size) + 1
  const points = Array.from({ length: n }, (_, i) => {
    const t = new Date(start + i * size)
    const day = size >= 86400e3
    return {
      label: day ? t.toLocaleDateString([], { month: 'short', day: 'numeric' }) : t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      full: t.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
      completed: 0,
      errors: 0,
      overrides: 0,
    }
  })
  events.forEach((t) => {
    const p = points[Math.floor((Date.parse(t.at) - start) / size)]
    if (!p) return
    if (t.event === 'stage_completed') p.completed += 1
    else if (t.event === 'stage_error') p.errors += 1
    else p.overrides += 1
  })
  return { points, bucketLabel }
}

/** Orchestrator transitions that mean something went wrong (shown as "Problem" in the activity feed). */
const PROBLEM_EVENTS = new Set(['stage_error', 'stage_degraded', 'invalid_output', 'retry'])

const OUTCOME_COLORS: Record<string, string> = {
  CLEAN: '#2f8f68',
  CLAIM_RECOMMENDED: '#3b6fb6',
  EXCEPTION: '#c46b64',
  INCOMPLETE: '#8a3a33',
  NEEDS_REVIEW: '#b78637',
}

/** Badge colour for a workflow status. */
function statusVariant(status?: string | null): 'success' | 'danger' | 'warning' | 'primary' {
  if (status === 'COMPLETED') return 'success'
  if (status === 'RECOVERY_REQUIRED') return 'primary'
  if (status === 'BLOCKED' || status === 'FAILED') return 'danger'
  return 'warning'
}

/** Mean end-to-end agent time per workflow, in seconds (sum of stage durations). */
function avgWorkflowSeconds(workflows: WorkflowState[]) {
  if (!workflows.length) return 0
  const total = workflows.reduce((sum, w) => sum + w.stage_results.reduce((s, r) => s + (r.duration_ms ?? 0), 0), 0)
  return total / workflows.length / 1000
}

interface RecoveryChargeItem {
  id: string
  workflowId: string
  type: string
  amount: string
  amountNum: number
  position: string
  evidence: string
  evidenceIds: string[]
  decision: string
  reason: string
}

/** Every fee line Recovery judged, read from the evidence of each workflow's current Recovery record. */
async function loadCharges(workflows: WorkflowState[]): Promise<RecoveryChargeItem[]> {
  const out: RecoveryChargeItem[] = []
  const withRecovery = workflows.filter((w) => w.stage_results.some((s) => s.stage === 'recovery' && s.state === 'completed'))
  const bundles = await Promise.allSettled(withRecovery.map((w) => api.getEvidence(w.workflow_id)))
  bundles.forEach((b, i) => {
    if (b.status !== 'fulfilled') return
    const wf = withRecovery[i]
    const rid = wf.stage_results.find((s) => s.stage === 'recovery')?.record_id
    const rec = rid ? b.value.evidence[rid] : undefined
    for (const c of (rec?.payload?.charges ?? []) as any[]) {
      const amt = typeof c.amount_usd === 'number' ? c.amount_usd : parseFloat(c.amount_usd) || 0
      out.push({
        id: c.line_id,
        workflowId: wf.workflow_id,
        type: String(c.charge_type || 'fee').replace(/_/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase()),
        amount: `$${amt.toFixed(2)}`,
        amountNum: amt,
        position: c.position || 'SILENT',
        evidence: (c.evidence_record_ids || []).join(', ') || 'none',
        evidenceIds: c.evidence_record_ids || [],
        decision: c.position === 'CONTRADICTS' ? 'CLAIM RECOMMENDED' : 'NO CLAIM',
        reason: c.reason || rec?.decision?.reason || '',
      })
    }
  })
  return out
}

// ── App Context ───────────────────────────────────────────────────────────
interface AppContextType {
  workflows: WorkflowState[]
  health: HealthResponse | null
  cases: CaseItem[]
  isBackendConnected: boolean
  loaded: boolean
  refreshData: () => Promise<void>
  openRunModal: () => void
  openOverrideModal: (ctx: { workflowId: string; recordId: string; currentVerdict: string; stage?: string }) => void
  openEvidenceDrawer: (record: EvidenceRecord) => void
  handleRunWorkflow: (orgId: string, unitId: string, route?: string, returned?: boolean) => Promise<WorkflowState>
  handleResumeWorkflow: (workflowId: string) => Promise<WorkflowState>
  handleApplyOverride: (
    workflowId: string,
    recordId: string,
    newVerdict: string,
    actor: string,
    reason: string,
    newOutcome?: string,
    autoResume?: boolean,
  ) => Promise<WorkflowState>
}

const AppContext = createContext<AppContextType | null>(null)

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used inside AppProvider')
  return ctx
}

// ── Main App Component ────────────────────────────────────────────────────
function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppProvider>
          <Shell />
        </AppProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

function AppProvider({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const [workflows, setWorkflows] = useState<WorkflowState[]>([])
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [cases, setCases] = useState<CaseItem[]>([])
  const [isBackendConnected, setIsBackendConnected] = useState(false)
  const [loaded, setLoaded] = useState(false)

  // Modals & Drawer State
  const [runModalOpen, setRunModalOpen] = useState(false)
  const [overrideModalContext, setOverrideModalContext] = useState<{
    workflowId: string
    recordId: string
    currentVerdict: string
    stage?: string
  } | null>(null)
  const [selectedEvidenceRecord, setSelectedEvidenceRecord] = useState<EvidenceRecord | null>(null)

  // Everything shown comes from the orchestrator API. If it is down the UI says so; it never invents state.
  const refreshData = async () => {
    // Health probes every agent and can be slow; workflows and cases must not wait for it.
    const healthCall = api.health().catch(() => null).then((h) => {
      setHealth(h)
      if (h) setIsBackendConnected(true)
      return h
    })
    const [casesRes, wfRes] = await Promise.all([api.cases().catch(() => null), api.listWorkflows().catch(() => null)])
    if (casesRes) setCases(casesRes)
    if (wfRes) setWorkflows(wfRes)
    setLoaded(true)
    if (!(await healthCall)) setIsBackendConnected(Boolean(wfRes))
  }

  // The cover page (/) is static: no API polling there.
  const onCover = location.pathname === '/'
  useEffect(() => {
    if (onCover) return
    refreshData()
    const interval = setInterval(refreshData, 15000)
    return () => clearInterval(interval)
  }, [onCover])

  const upsert = (res: WorkflowState) => {
    setWorkflows((prev) => [res, ...prev.filter((w) => w.workflow_id !== res.workflow_id)])
    return res
  }

  const handleRunWorkflow = async (orgId: string, unitId: string, route?: string, returned?: boolean) =>
    upsert(await api.runWorkflow(orgId, unitId, route, returned))

  const [apiError, setApiError] = useState<string | null>(null)

  // Resume buttons live on many pages: report a failure in one visible banner and leave the state untouched.
  const handleResumeWorkflow = async (workflowId: string) => {
    try {
      setApiError(null)
      return upsert(await api.resumeWorkflow(workflowId))
    } catch (err) {
      setApiError(`Resume of ${workflowId} failed: ${String(err)}`)
      const current = workflows.find((w) => w.workflow_id === workflowId)
      if (current) return current
      throw err
    }
  }

  const handleApplyOverride = async (
    workflowId: string,
    recordId: string,
    newVerdict: string,
    actor: string,
    reason: string,
    newOutcome?: string,
    autoResume = true
  ) => {
    let res = upsert(await api.applyOverride(workflowId, recordId, newVerdict, actor, reason, newOutcome))
    if (autoResume) {
      // The override is already stored; a failed resume must not be reported as a failed override.
      try {
        res = upsert(await api.resumeWorkflow(workflowId))
      } catch (err) {
        setApiError(`Override ${recordId} was recorded, but resuming ${workflowId} failed: ${String(err)}`)
      }
    }
    return res
  }

  const value: AppContextType = {
    workflows,
    health,
    cases,
    isBackendConnected,
    loaded,
    refreshData,
    openRunModal: () => setRunModalOpen(true),
    openOverrideModal: (ctx) => setOverrideModalContext(ctx),
    openEvidenceDrawer: (record) => setSelectedEvidenceRecord(record),
    handleRunWorkflow,
    handleResumeWorkflow,
    handleApplyOverride,
  }

  return (
    <AppContext.Provider value={value}>
      {(apiError || (loaded && !isBackendConnected)) && location.pathname !== '/' && (
        <div
          role="alert"
          style={{ position: 'fixed', bottom: 16, left: 16, right: 16, zIndex: 1000, padding: '10px 14px', borderRadius: 8,
                   background: '#fbecea', color: '#8a3a33', border: '1px solid #e2b4ae', fontSize: 13,
                   display: 'flex', justifyContent: 'space-between', gap: 12 }}
        >
          <span>{apiError ?? 'Orchestrator API unreachable: nothing below is live until it is back (start it with `make serve`).'}</span>
          {apiError && <button type="button" className="secondary-button small" onClick={() => setApiError(null)}>Dismiss</button>}
        </div>
      )}
      {children}
      {runModalOpen && <RunWorkflowModal onClose={() => setRunModalOpen(false)} />}
      {overrideModalContext && (
        <OverrideModal
          context={overrideModalContext}
          onClose={() => setOverrideModalContext(null)}
        />
      )}
      {selectedEvidenceRecord && (
        <EvidenceRecordDrawer
          record={selectedEvidenceRecord}
          onClose={() => setSelectedEvidenceRecord(null)}
        />
      )}
    </AppContext.Provider>
  )
}

// ── Modals & Drawer ────────────────────────────────────────────────────────

function RunWorkflowModal({ onClose }: { onClose: () => void }) {
  const { cases, handleRunWorkflow } = useApp()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'preset' | 'custom'>('preset')
  const [selectedCaseIdx, setSelectedCaseIdx] = useState(0)
  const [orgId, setOrgId] = useState('org_demo_alpha')
  const [unitId, setUnitId] = useState('UNIT-0014')
  // 'auto' lets the orchestrator derive route / returned from the unit's own records (a forced wrong route would send
  // the unit to a stage that has no record for it and fail for a reason that is not real).
  const [route, setRoute] = useState<'auto' | 'fba' | 'mfn'>('auto')
  const [returned, setReturned] = useState<'auto' | 'yes' | 'no'>('auto')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      let targetOrg = orgId.trim()
      let targetUnit = unitId.trim()
      let targetRoute: string | undefined = route === 'auto' ? undefined : route
      let targetReturned: boolean | undefined = returned === 'auto' ? undefined : returned === 'yes'

      if (mode === 'preset' && cases[selectedCaseIdx]) {
        const c = cases[selectedCaseIdx]
        targetOrg = c.org_id
        targetUnit = c.unit_id
        targetRoute = c.route || undefined
        targetReturned = c.returned ?? undefined
      }

      const res = await handleRunWorkflow(targetOrg, targetUnit, targetRoute, targetReturned)
      onClose()
      navigate(`/workflows/${res.workflow_id}`)
    } catch (err: any) {
      setError(err?.message || 'Failed to dispatch workflow')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3 className="modal-title">Run Workflow</h3>
            <p className="modal-subtitle">Dispatch commerce orchestration for an inventory unit</p>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close modal">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body">
          <div className="toggle-group">
            <button
              type="button"
              className={`toggle-btn ${mode === 'preset' ? 'active' : ''}`}
              onClick={() => setMode('preset')}
            >
              Demo Cases ({cases.length})
            </button>
            <button
              type="button"
              className={`toggle-btn ${mode === 'custom' ? 'active' : ''}`}
              onClick={() => setMode('custom')}
            >
              Custom Unit
            </button>
          </div>

          {mode === 'preset' ? (
            <div className="form-group">
              <label className="form-label">Select Case</label>
              <select
                className="form-select"
                value={selectedCaseIdx}
                onChange={(e) => setSelectedCaseIdx(Number(e.target.value))}
              >
                {cases.map((c, idx) => (
                  <option key={`${c.org_id}-${c.unit_id}-${idx}`} value={idx}>
                    {c.unit_id} · {c.org_id} (Route: {c.route ? c.route.toUpperCase() : 'from data'}, Returned:{' '}
                    {c.returned === undefined ? 'from data' : c.returned ? 'YES' : 'NO'}){c.source === 'pod' ? ' · Pod case' : ''}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <>
              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Organization ID</label>
                  <input
                    type="text"
                    className="form-input"
                    value={orgId}
                    onChange={(e) => setOrgId(e.target.value)}
                    required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Unit ID</label>
                  <input
                    type="text"
                    className="form-input"
                    value={unitId}
                    onChange={(e) => setUnitId(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label">Route</label>
                  <select
                    className="form-select"
                    value={route}
                    onChange={(e) => setRoute(e.target.value as 'auto' | 'fba' | 'mfn')}
                  >
                    <option value="auto">From the unit's records (recommended)</option>
                    <option value="fba">Force FBA (Fulfillment by Amazon)</option>
                    <option value="mfn">Force MFN (Merchant Fulfilled)</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Customer Returned?</label>
                  <select
                    className="form-select"
                    value={returned}
                    onChange={(e) => setReturned(e.target.value as 'auto' | 'yes' | 'no')}
                  >
                    <option value="auto">From the unit's records (recommended)</option>
                    <option value="yes">Force YES (runs Returns)</option>
                    <option value="no">Force NO</option>
                  </select>
                </div>
              </div>
            </>
          )}

          {error && <div className="incident-alert"><p style={{ color: '#c46b64' }}>{error}</p></div>}

          <div className="modal-footer">
            <button type="button" className="secondary-button small" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button type="submit" className="primary-button small" disabled={loading}>
              {loading ? <span className="spinner-inline" /> : <Play size={13} style={{ marginRight: 6 }} />}
              {loading ? 'Orchestrating...' : 'Launch Workflow'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function OverrideModal({
  context,
  onClose,
}: {
  context: { workflowId: string; recordId: string; currentVerdict: string; stage?: string }
  onClose: () => void
}) {
  const { handleApplyOverride } = useApp()
  // No pre-filled actor: an override must name the real person who made it.
  const [actor, setActor] = useState('')
  const [newVerdict, setNewVerdict] = useState<'PASS' | 'FAIL' | 'UNCERTAIN'>('PASS')
  const [reason, setReason] = useState('')
  const [newOutcome, setNewOutcome] = useState('')
  const [autoResume, setAutoResume] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!actor.trim() || !reason.trim()) {
      setError('An override needs the name of the person making it and a reason.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      await handleApplyOverride(
        context.workflowId,
        context.recordId,
        newVerdict,
        actor,
        reason,
        newOutcome || undefined,
        autoResume
      )
      onClose()
    } catch (err: any) {
      setError(err?.message || 'Failed to submit override')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3 className="modal-title">Human Intervention & Override</h3>
            <p className="modal-subtitle">
              Workflow: <strong>{context.workflowId}</strong> · Record: <strong>{context.recordId}</strong>
              {context.stage ? <> · Stage: <strong>{context.stage}</strong></> : null} · Current verdict:{' '}
              <strong>{context.currentVerdict}</strong>
            </p>
            <p className="modal-subtitle">
              The original record is kept unchanged; this override is appended with your name, reason and time.
            </p>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close modal">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body">
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Reviewer / Operator ID</label>
              <input
                type="text"
                className="form-input"
                value={actor}
                placeholder="your name or operator id"
                onChange={(e) => setActor(e.target.value)}
                required
              />
            </div>
            <div className="form-group">
              <label className="form-label">New Verdict</label>
              <select
                className="form-select"
                value={newVerdict}
                onChange={(e) => setNewVerdict(e.target.value as any)}
              >
                <option value="PASS">PASS (evidence supports it)</option>
                <option value="FAIL">FAIL (condition not met; on Recovery: charge contradicted)</option>
                <option value="UNCERTAIN">UNCERTAIN (still needs a decision)</option>
              </select>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Operational Justification / Reason *</label>
            <textarea
              className="form-textarea"
              placeholder="e.g. Physical carton inspection verified. Barcode clear and seals unbroken."
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label">New Outcome (Optional)</label>
            <input
              type="text"
              className="form-input"
              placeholder="e.g. compliant, refurbish, restock"
              value={newOutcome}
              onChange={(e) => setNewOutcome(e.target.value)}
            />
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer', marginTop: 4 }}>
            <input
              type="checkbox"
              checked={autoResume}
              onChange={(e) => setAutoResume(e.target.checked)}
            />
            Automatically resume workflow after override
          </label>

          {error && <div className="incident-alert"><p style={{ color: '#c46b64' }}>{error}</p></div>}

          <div className="modal-footer">
            <button type="button" className="secondary-button small" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button type="submit" className="primary-button small" disabled={loading}>
              {loading ? <span className="spinner-inline" /> : <SlidersHorizontal size={13} style={{ marginRight: 6 }} />}
              {loading ? 'Applying...' : 'Apply Override'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function EvidenceRecordDrawer({ record, onClose }: { record: EvidenceRecord; onClose: () => void }) {
  return (
    <div className="evidence-drawer-overlay" onClick={onClose}>
      <div className="evidence-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <div className="eyebrow">Evidence Record</div>
            <h2 style={{ margin: '4px 0 0', fontSize: 18 }}>{record.record_id}</h2>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close drawer">
            <X size={16} />
          </button>
        </div>

        <div className="drawer-section">
          <div className="drawer-label">Metadata</div>
          <div className="key-value"><span>Workflow</span><strong>{record.workflow_id}</strong></div>
          <div className="key-value"><span>Stage</span><strong>{record.stage.toUpperCase()}</strong></div>
          <div className="key-value"><span>Agent</span><strong>{record.agent_id}</strong></div>
          <div className="key-value"><span>Status</span><strong>{record.status}</strong></div>
          <div className="key-value">
            <span>Verdict</span>
            <StatusBadge
              label={record.decision?.verdict || 'N/A'}
              variant={stageVariant(record.decision?.verdict || null, record.status)}
            />
          </div>
        </div>

        {record.decision?.reason && (
          <div className="drawer-section">
            <div className="drawer-label">Decision Note</div>
            <p style={{ margin: 0, fontSize: 13, color: '#2a2f2d', lineHeight: 1.5 }}>
              {record.decision.reason}
            </p>
          </div>
        )}

        {record.checks && record.checks.length > 0 && (
          <div className="drawer-section">
            <div className="drawer-label">Rule & Quality Checks ({record.checks.length})</div>
            <div className="table-card" style={{ margin: 0 }}>
              <table>
                <thead>
                  <tr>
                    <th>Check</th>
                    <th>Verdict</th>
                    <th>Observed / detail</th>
                    <th>Cites</th>
                  </tr>
                </thead>
                <tbody>
                  {record.checks.map((chk, i) => (
                    <tr key={chk.check_key || i}>
                      <td><small>{chk.check_key}</small></td>
                      <td>
                        <StatusBadge
                          label={chk.verdict}
                          variant={chk.verdict === 'PASS' ? 'success' : chk.verdict === 'FAIL' ? 'danger' : 'warning'}
                        />
                        {chk.confidence != null && <small> {chk.confidence}</small>}
                        {chk.uncertain_reason && <div><small>{chk.uncertain_reason}</small></div>}
                      </td>
                      <td>
                        <small>{chk.detail || (typeof chk.observed === 'object' ? JSON.stringify(chk.observed) : String(chk.observed ?? '—'))}</small>
                      </td>
                      <td><small>{(chk.evidence_refs ?? []).join(', ') || '—'}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {record.payload && Object.keys(record.payload).length > 0 && (
          <div className="drawer-section">
            <div className="drawer-label">Payload Data</div>
            <pre className="json-viewer">{JSON.stringify(record.payload, null, 2)}</pre>
          </div>
        )}

        <div className="drawer-section">
          <div className="drawer-label">Traceability</div>
          <div className="key-value">
            <span>Model</span>
            <strong>{record.model ? `${record.model.name} · calls ${record.model.calls ?? '?'}` : '—'}</strong>
          </div>
          <div className="key-value"><span>Upstream records used</span><strong>{(record.upstream_refs ?? []).join(', ') || 'none'}</strong></div>
          {(record.inputs ?? []).map((inp) => (
            <div key={inp.ref} className="key-value">
              <span><code>{inp.ref}</code></span>
              <strong style={{ fontSize: 11 }}>{inp.sha256 ? `sha256 ${String(inp.sha256).slice(0, 16)}…` : 'no hash (not on disk)'}</strong>
            </div>
          ))}
        </div>

        {record.content_hash && (
          <div className="drawer-section">
            <div className="drawer-label">Content hash (SHA-256 of the canonical record; detects change, not tamper-proof)</div>
            <div className="hash-badge">{record.content_hash}</div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── App Shell ─────────────────────────────────────────────────────────────

const sidebarItems = [
  { to: '/overview', label: 'Overview', icon: Layers3 },
  { to: '/workflows', label: 'Workflows', icon: Workflow },
  { to: '/units', label: 'Units', icon: Database },
  { to: '/reviews', label: 'Review Queue', icon: FileText },
  { to: '/recovery', label: 'Recovery', icon: ShieldCheck },
  { to: '/evidence', label: 'Evidence', icon: GitBranch },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/failures', label: 'Failures', icon: XCircle },
  { to: '/analytics', label: 'Analytics', icon: Gauge },
  { to: '/system', label: 'Pod / System', icon: CircleDot },
]

function Shell() {
  const location = useLocation()
  const { workflows, isBackendConnected, refreshData, openRunModal, openOverrideModal, handleResumeWorkflow } = useApp()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // Find if there is any active halted or blocked workflow to warn in banner
  const blockedWorkflow = useMemo(() => {
    return workflows.find((w) => w.status === 'BLOCKED' || Boolean(w.halted))
  }, [workflows])

  if (location.pathname === '/') {
    return <CoverPage />
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        <div className="brand-block">
          <button
            type="button"
            className="collapse-toggle"
            onClick={() => setSidebarCollapsed((v) => !v)}
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? <ChevronsRight size={15} /> : <ChevronsLeft size={15} />}
          </button>
          <div className="brand-mark">C</div>
          <div className="brand-copy">
            <div className="brand-title">CUBE</div>
            <div className="brand-subtitle">Pod 05</div>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Sidebar navigation">
          {sidebarItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              title={label}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            >
              <Icon size={16} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="micro-label">POD STATUS</div>
          <div className="system-row">
            <span>Commerce Ops</span>
          </div>
          <div className={`system-row ${isBackendConnected ? 'healthy' : ''}`}>
            <span className={`status-dot ${isBackendConnected ? 'healthy-dot' : ''}`} />
            <span>Orchestrator</span>
            <span className="status-meta">{isBackendConnected ? 'Online' : 'Offline'}</span>
          </div>
        </div>
      </aside>

      <div className="main-panel">
        <header className="topbar">
          <div className="topbar-left">
            <div className="crumb-inline">CUBE / POD 05 / LIVE OPERATIONS</div>
          </div>
          <div className="topbar-actions">
            <button type="button" className="search-box" onClick={openRunModal}>
              <Search size={15} />
              <span>Run or find workflow...</span>
              <kbd>+ Run</kbd>
            </button>
            <div className="org-tag">Orgs: {Array.from(new Set(workflows.map((w) => w.org_id))).join(', ') || 'none yet'}</div>
            <div className="health-tag">
              <span className={`status-dot ${isBackendConnected ? 'healthy-dot' : ''}`} />
              {isBackendConnected ? 'Live API Connected' : 'API Offline'}
            </div>
            <button
              type="button"
              className="icon-button"
              onClick={() => refreshData()}
              title="Refresh Pod Data"
            >
              <RefreshCw size={14} />
            </button>
            <div className="user-pill">UP</div>
          </div>
        </header>

        <main className="router-shell">
          {blockedWorkflow && (
            <div style={{ padding: '16px 28px 0' }}>
              <div className="blocked-banner">
                <div className="blocked-banner-left">
                  <div className="blocked-banner-icon">
                    <AlertTriangle size={18} />
                  </div>
                  <div>
                    <div className="blocked-banner-title">
                      Workflow Blocked: {blockedWorkflow.workflow_id} ({blockedWorkflow.subject_id})
                    </div>
                    <div className="blocked-banner-desc">
                      Stage &quot;{reviewTarget(blockedWorkflow)?.stage ?? blockedWorkflow.current_stage}&quot; requires human intervention —{' '}
                      {blockedWorkflow.halted?.reason || blockedWorkflow.status_reason || 'Verdict uncertain'}
                    </div>
                  </div>
                </div>
                <div className="blocked-banner-actions">
                  <button
                    type="button"
                    className="primary-button small"
                    disabled={!reviewTarget(blockedWorkflow)}
                    onClick={() => {
                      const t = reviewTarget(blockedWorkflow)
                      if (t) openOverrideModal(t)
                    }}
                  >
                    Intervene & Override
                  </button>
                  <button
                    type="button"
                    className="secondary-button small"
                    onClick={() => handleResumeWorkflow(blockedWorkflow.workflow_id)}
                  >
                    Resume
                  </button>
                </div>
              </div>
            </div>
          )}

          <Routes>
            <Route path="/overview" element={<OverviewPage />} />
            <Route path="/dashboard" element={<OverviewPage />} />
            <Route path="/workflows" element={<WorkflowsPage />} />
            <Route path="/workflows/:id" element={<WorkflowDetailPage />} />
            <Route path="/units" element={<UnitsPage />} />
            <Route path="/units/:id" element={<UnitDetailPage />} />
            <Route path="/reviews" element={<ReviewQueuePage />} />
            <Route path="/recovery" element={<RecoveryPage />} />
            <Route path="/recovery/charges/:id" element={<RecoveryChargeDetailPage />} />
            <Route path="/evidence" element={<EvidencePage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/agents/:slug" element={<AgentDetailPage />} />
            <Route path="/failures" element={<FailuresPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/system" element={<SystemPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>

        <footer className="status-bar">
          <span className="status-label">Live</span>
          <span className="status-pulse" />
          <span>{location.pathname.replace('/', '') || 'overview'}</span>
          <span className="status-separator" />
          <span>{workflows.length} workflows tracked</span>
          <span className="status-separator" />
          <span>{isBackendConnected ? 'Connected to the orchestrator API' : 'Orchestrator API offline'}</span>
        </footer>
      </div>
    </div>
  )
}

// ── Pages ─────────────────────────────────────────────────────────────────

function OverviewPage() {
  const { workflows, health, openRunModal, openOverrideModal } = useApp()
  const navigate = useNavigate()
  const [activityFilter, setActivityFilter] = useState<'All' | 'OK' | 'Problem' | 'Needs a person'>('All')

  // Derive dynamic KPIs from real workflows
  const activeCount = workflows.filter((w) => w.status === 'IN_PROGRESS' || w.status === 'PENDING').length
  const returnedCount = workflows.filter((w) => Boolean((w.context as any)?.returned)).length
  const inspectedCount = workflows.filter((w) => returnsOf(w)?.state === 'completed').length
  // Same rule as the Review Queue: the orchestrator's final outcome still needs a person (overridden stages are resolved).
  const reviewCount = workflows.filter((w) => w.final_outcome?.needs_human).length
  const failedCount = workflows.filter((w) => w.status === 'FAILED' || w.errors.length > 0).length
  const claimableTotal = workflows.reduce((sum, w) => sum + (w.final_outcome?.claimable_usd || 0), 0)
  const claimsCount = workflows.filter((w) => w.final_outcome?.outcome === 'CLAIM_RECOMMENDED').length
  const completedCount = workflows.filter((w) => w.status === 'COMPLETED').length

  const kpis = [
    { label: 'Active Workflows', value: String(activeCount), indicator: `${workflows.length} total`, route: '/workflows?status=IN_PROGRESS', tone: 'ink' },
    { label: 'Returned Units', value: String(returnedCount), indicator: `${inspectedCount} inspected by Returns`, route: '/units', tone: 'mint' },
    { label: 'Needs Review', value: String(reviewCount), indicator: reviewCount > 0 ? 'waiting for a person' : 'none waiting', route: '/reviews', tone: 'amber' },
    { label: 'Failed / With Errors', value: String(failedCount), indicator: failedCount > 0 ? 'see Failures' : 'no recorded errors', route: '/failures', tone: 'clay' },
    { label: 'Claims Recommended', value: String(claimsCount), indicator: `$${claimableTotal.toFixed(2)} claimable`, route: '/recovery?filter=claimable', tone: 'claim' },
    { label: 'Completed', value: String(completedCount), indicator: 'status COMPLETED', route: '/workflows?status=COMPLETED', tone: 'mint' },
  ]

  // Dynamic priority bench
  const priorityItems = useMemo(() => {
    const list: Array<{ id: string; title: string; detail: string; severity: string; owner: string; wf: WorkflowState }> = []
    workflows.forEach((w) => {
      if (w.status === 'BLOCKED' || Boolean(w.halted)) {
        list.push({
          id: w.workflow_id,
          title: `${w.workflow_id} (${w.subject_id})`,
          detail: w.halted?.reason || w.status_reason || 'Halted awaiting human override.',
          severity: 'critical',
          owner: 'Human review',
          wf: w,
        })
      } else if (w.final_outcome?.outcome === 'CLAIM_RECOMMENDED') {
        list.push({
          id: w.workflow_id,
          title: `CLAIM: ${w.workflow_id}`,
          detail: `Recovery contradicted at least one charge: $${(w.final_outcome.claimable_usd ?? 0).toFixed(2)} claimable (recommendation only; no claim has been filed).`,
          severity: 'high',
          owner: 'Recovery',
          wf: w,
        })
      } else if (w.status === 'FAILED') {
        list.push({
          id: w.workflow_id,
          title: `FAIL: ${w.workflow_id}`,
          detail: w.errors[0]?.message ? String(w.errors[0].message) : 'Stage error recorded.',
          severity: 'medium',
          owner: 'Ops lead',
          wf: w,
        })
      }
    })
    return list.slice(0, 4)
  }, [workflows])

  const activity = useMemo(() => stageActivity(workflows), [workflows])

  // Activity feed: the most recent orchestrator transitions across all workflows, newest first. Nothing is invented:
  // with no workflows the table is empty.
  const liveEvents = useMemo(() => {
    const events: Array<{ at: string; time: string; unit: string; stage: string; event: string; status: string }> = []
    workflows.forEach((w) => {
      w.transitions.forEach((t: any) => {
        let status = 'OK'
        if (PROBLEM_EVENTS.has(t.event) || (t.event === 'status_changed' && t.to_status === 'FAILED')) status = 'Problem'
        else if (t.event === 'halted' || (t.event === 'status_changed' && t.to_status === 'BLOCKED')) status = 'Needs a person'
        events.push({
          at: t.at ?? '',
          time: t.at ? new Date(t.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—',
          unit: `${w.subject_id} · ${w.org_id}`,
          stage: t.stage || 'workflow',
          event: `${t.event.replace(/_/g, ' ')}${t.detail ? `: ${t.detail}` : ''}`,
          status,
        })
      })
    })
    return events.sort((a, b) => b.at.localeCompare(a.at)).slice(0, 10)
  }, [workflows])

  const filteredActivity = liveEvents.filter((entry) => {
    if (activityFilter === 'All') return true
    return entry.status === activityFilter
  })

  return (
    <div className="page-stack">
      <section className="hero-shell">
        <div className="hero-top">
          <div className="hero-copy">
            <span className="eyebrow">Pod 05 · Standard flow · {workflows.length} workflows in the store</span>
            <h1>Commerce Control Center</h1>
            <p>Five agents, one orchestrator, one evidence trail per unit.</p>
          </div>
          <div className="hero-actions">
            <button type="button" className="primary-button" onClick={openRunModal}>
              + New Workflow
            </button>
            <button type="button" className="secondary-button" onClick={() => navigate('/workflows')}>
              Browse Workflows
            </button>
            <button type="button" className="tertiary-button" onClick={() => navigate('/reviews')}>
              Review Queue ({reviewCount})
            </button>
          </div>
        </div>

        {/* The pipeline, stage by stage, from the stored workflows: runs and the verdict mix of each agent. */}
        <div className="pipeline-rail">
          {stageStats(workflows).map((s, i) => (
            <Link key={s.agent} to={`/agents/${s.agent.toLowerCase()}`} className="rail-stage" title={`${s.agent}: ${s.pass}% pass, ${s.fail}% fail, ${s.uncertain}% uncertain, ${s.error}% error`}>
              <div className="rail-head">
                <span className="rail-index">0{i + 1}</span>
                <span className="rail-name">{s.agent}</span>
              </div>
              <div className="rail-stat">
                <strong>{s.runs}</strong>
                <span>{s.runs === 1 ? 'run' : 'runs'}{s.runs ? ` · ${s.pass}% pass` : ''}</span>
              </div>
              <div className="rail-bar" aria-hidden="true">
                <i className="pass" style={{ width: `${s.pass}%` }} />
                <i className="fail" style={{ width: `${s.fail}%` }} />
                <i className="unsure" style={{ width: `${s.uncertain}%` }} />
                <i className="err" style={{ width: `${s.error}%` }} />
              </div>
            </Link>
          ))}
        </div>
      </section>

      <section className="kpi-strip">
        {kpis.map((item) => (
          <Link key={item.label} to={item.route} className="kpi-card" data-tone={item.tone}>
            <div className="kpi-topline">
              <span className="kpi-value">{item.value}</span>
              <span className="mini-trend">{item.indicator}</span>
            </div>
            <div className="kpi-label">{item.label}</div>
          </Link>
        ))}
      </section>

      {/* Priority Workbench */}
      <section className="priority-workbench panel">
        <div className="panel-header row-between">
          <div className="panel-title">Priority workbench</div>
          <button type="button" className="secondary-button small" onClick={() => navigate('/reviews')}>
            Open queue
          </button>
        </div>

        <div className="priority-grid">
          <div className="priority-list">
            {priorityItems.length > 0 ? (
              priorityItems.map((item) => (
                <div key={item.id} className={`priority-item ${item.severity}`}>
                  <div className="priority-topline">
                    <span className="priority-severity">{item.severity}</span>
                    <span className="priority-owner">{item.owner}</span>
                  </div>
                  <div className="priority-name">{item.title}</div>
                  <p>{item.detail}</p>
                  <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
                    <button
                      type="button"
                      className="primary-button small"
                      onClick={() => navigate(`/workflows/${item.wf.workflow_id}`)}
                    >
                      View
                    </button>
                    {item.severity === 'critical' && (
                      <button
                        type="button"
                        className="secondary-button small"
                        disabled={!reviewTarget(item.wf)}
                        onClick={() => {
                          const t = reviewTarget(item.wf)
                          if (t) openOverrideModal(t)
                        }}
                      >
                        Override
                      </button>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state">
                {workflows.length ? 'Nothing is blocked, failed or waiting on a claim decision.' : 'No workflows yet. Run one to start.'}
              </div>
            )}
          </div>

          <div className="priority-summary">
            <div className="summary-metric">
              <span className="summary-value">
                {workflows.length
                  ? Math.round((100 * workflows.filter((w) => w.final_outcome?.needs_human).length) / workflows.length)
                  : 0}
                %
              </span>
              <span className="summary-label">of workflows need a human</span>
            </div>
            <div className="summary-grid">
              <div>
                <span className="summary-subvalue">{workflows.length}</span>
                <span className="summary-sublabel">Workflows</span>
              </div>
              <div>
                <span className="summary-subvalue">${claimableTotal.toFixed(2)}</span>
                <span className="summary-sublabel">Claim Value</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Verdict mix along the pipeline (line chart) & Pod health */}
      <section className="chart-grid">
        <article className="panel">
          <div className="panel-header row-between">
            <div>
              <div className="eyebrow">Agent metrics</div>
              <h2>Verdict mix along the pipeline</h2>
            </div>
            <div className="meta-stamp">% of each agent's runs · {workflows.length} workflows</div>
          </div>
          <div className="chart-card">
            {workflows.length === 0 ? (
              <div className="chart-empty">No workflows yet. Run one to see the verdict mix.</div>
            ) : (
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={stageStats(workflows)} margin={{ top: 12, right: 34, left: -12, bottom: 0 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="agent" tickLine={false} axisLine={false} dy={6} />
                  <YAxis unit="%" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickLine={false} axisLine={false} />
                  <Tooltip content={<VerdictTooltip />} cursor={{ stroke: 'rgba(15,31,23,0.15)', strokeDasharray: '3 3' }} />
                  {VERDICT_LINES.map((l) => (
                    <Line
                      key={l.key}
                      type="monotone"
                      dataKey={l.key}
                      name={l.name}
                      stroke={l.color}
                      strokeWidth={l.key === 'pass' ? 3 : 2}
                      strokeDasharray={l.dash}
                      dot={{ r: 4, fill: '#fff', stroke: l.color, strokeWidth: 2 }}
                      activeDot={{ r: 6, fill: l.color, stroke: '#fff', strokeWidth: 2 }}
                      animationDuration={900}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            )}
            <div className="chart-legend">
              {VERDICT_LINES.map((l) => (
                <span key={l.key}>
                  <i className={l.dash ? 'dashed' : ''} style={{ background: l.color }} />
                  {l.name}
                </span>
              ))}
            </div>
          </div>
        </article>

        <article className="panel">
          <div className="panel-header row-between">
            <div>
              <div className="eyebrow">Pod environment</div>
              <h2>Pod 05 Health</h2>
            </div>
            <span className="health-tag">
              <span className={`status-dot ${health?.status === 'ok' ? 'healthy-dot' : ''}`} />
              {health ? (health.status === 'ok' ? 'All agents reachable' : 'Degraded') : 'Orchestrator unreachable'}
            </span>
          </div>

          <div className="side-stack">
            {exampleAgents.map((ag) => {
              const live = health?.agents?.[ag.slug]
              const stub = live?.implementation === 'organiser-stub'
              return (
                <div key={ag.slug} className="key-value">
                  <span>
                    {ag.title}
                    {live?.agent_id && <small style={{ marginLeft: 6, opacity: 0.7 }}>{live.agent_id}</small>}
                  </span>
                  <span style={{ display: 'flex', gap: 6 }}>
                    {stub && <StatusBadge label="STUB" variant="warning" />}
                    <StatusBadge
                      label={live ? (live.status === 'ok' ? 'UP' : 'DOWN') : 'UNKNOWN'}
                      variant={live?.status === 'ok' ? 'success' : 'danger'}
                    />
                  </span>
                </div>
              )
            })}
          </div>
        </article>
      </section>

      {/* Stage activity over time (line chart), from the orchestrator's own transitions */}
      <section className="panel">
        <div className="panel-header row-between">
          <div>
            <div className="eyebrow">Throughput</div>
            <h2>Stage activity over time</h2>
          </div>
          <div className="meta-stamp">{activity.bucketLabel ? `per ${activity.bucketLabel}` : ''}</div>
        </div>
        <div className="chart-card">
          {activity.points.length < 2 ? (
            <div className="chart-empty">Not enough recorded stage events yet to draw a trend.</div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={activity.points} margin={{ top: 12, right: 18, left: -18, bottom: 0 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} dy={6} minTickGap={24} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
                <Tooltip content={<ActivityTooltip />} cursor={{ stroke: 'rgba(15,31,23,0.15)', strokeDasharray: '3 3' }} />
                <Line type="monotone" dataKey="completed" name="Stages completed" stroke="#16a34a" strokeWidth={3}
                      dot={{ r: 3, fill: '#fff', stroke: '#16a34a', strokeWidth: 2 }} activeDot={{ r: 6 }} animationDuration={900} />
                <Line type="monotone" dataKey="errors" name="Stage errors" stroke="#b4493f" strokeWidth={2}
                      dot={{ r: 3, fill: '#fff', stroke: '#b4493f', strokeWidth: 2 }} activeDot={{ r: 6 }} animationDuration={900} />
                <Line type="monotone" dataKey="overrides" name="Overrides" stroke="#2f5fa8" strokeWidth={2} strokeDasharray="5 4"
                      dot={false} activeDot={{ r: 5 }} animationDuration={900} />
              </LineChart>
            </ResponsiveContainer>
          )}
          <div className="chart-legend">
            <span><i style={{ background: '#16a34a' }} />Stages completed</span>
            <span><i style={{ background: '#b4493f' }} />Stage errors</span>
            <span><i style={{ background: '#2f5fa8' }} />Overrides</span>
          </div>
        </div>
      </section>

      {/* Live Activity Feed */}
      <section className="panel">
        <div className="panel-header row-between">
          <div>
            <div className="eyebrow">Live ledger</div>
            <h2>Operational activity feed</h2>
          </div>
          <div className="filter-row">
            {(['All', 'OK', 'Problem', 'Needs a person'] as const).map((filter) => (
              <button
                key={filter}
                type="button"
                className={`secondary-button small ${activityFilter === filter ? 'active' : ''}`}
                onClick={() => setActivityFilter(filter)}
              >
                {filter}
              </button>
            ))}
          </div>
        </div>

        <div className="table-card">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Unit</th>
                <th>Stage</th>
                <th>Event</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredActivity.length === 0 && (
                <tr>
                  <td colSpan={5}>{workflows.length ? 'No events match this filter.' : 'No activity yet.'}</td>
                </tr>
              )}
              {filteredActivity.map((item, idx) => (
                <tr key={`${item.unit}-${item.at}-${idx}`}>
                  <td>{item.time}</td>
                  <td><strong>{item.unit}</strong></td>
                  <td>{item.stage}</td>
                  <td>{item.event}</td>
                  <td>
                    <StatusBadge
                      label={item.status}
                      variant={item.status === 'OK' ? 'success' : item.status === 'Problem' ? 'danger' : 'warning'}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function WorkflowsPage() {
  const { workflows, openRunModal } = useApp()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  // The status filter lives in the URL (?status=COMPLETED) so links from other pages land on the right view.
  const [searchParams, setSearchParams] = useSearchParams()
  const STATUS_FILTERS = ['All', 'IN_PROGRESS', 'BLOCKED', 'FAILED', 'RECOVERY_REQUIRED', 'COMPLETED'] as const
  type StatusFilter = (typeof STATUS_FILTERS)[number]
  const fromUrl = (searchParams.get('status') ?? 'All').toUpperCase()
  const statusFilter: StatusFilter = (STATUS_FILTERS as readonly string[]).includes(fromUrl) ? (fromUrl as StatusFilter) : 'All'
  const setStatusFilter = (f: StatusFilter) => setSearchParams(f === 'All' ? {} : { status: f })

  const filteredWorkflows = workflows.filter((w) => {
    const matchesQuery =
      w.workflow_id.toLowerCase().includes(query.toLowerCase()) ||
      w.subject_id.toLowerCase().includes(query.toLowerCase()) ||
      w.org_id.toLowerCase().includes(query.toLowerCase())

    const matchesStatus = statusFilter === 'All' || w.status === statusFilter
    return matchesQuery && matchesStatus
  })

  return (
    <PageTemplate title="Workflows" subtitle="All running and completed commerce workflows">
      <div className="toolbar" style={{ display: 'flex', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 10, flex: 1 }}>
          <input
            type="text"
            placeholder="Search by workflow ID, unit ID, org..."
            className="search-field"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {STATUS_FILTERS.map((filter) => (
            <button
              key={filter}
              type="button"
              className={`secondary-button small ${statusFilter === filter ? 'active' : ''}`}
              onClick={() => setStatusFilter(filter)}
            >
              {filter === 'All' ? 'All' : filter}
            </button>
          ))}
        </div>
        <button type="button" className="primary-button small" onClick={openRunModal}>
          + Run Workflow
        </button>
      </div>

      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th>Workflow ID</th>
              <th>Unit ID</th>
              <th>Org</th>
              <th>Route</th>
              <th>Returned</th>
              <th>Current Stage</th>
              <th>Workflow Status</th>
              <th>Final Outcome</th>
              <th>Claimable</th>
            </tr>
          </thead>
          <tbody>
            {filteredWorkflows.length === 0 && (
              <tr>
                <td colSpan={9}>{workflows.length ? 'No workflow matches this search or filter.' : 'No workflows yet. Use Run Workflow.'}</td>
              </tr>
            )}
            {filteredWorkflows.map((w) => (
              <tr key={w.workflow_id} onClick={() => navigate(`/workflows/${w.workflow_id}`)} style={{ cursor: 'pointer' }}>
                <td>
                  <Link to={`/workflows/${w.workflow_id}`} onClick={(e) => e.stopPropagation()}>
                    <strong>{w.workflow_id}</strong>
                  </Link>
                </td>
                <td>{w.subject_id}</td>
                <td>{w.org_id}</td>
                <td>{String((w.context as any)?.route ?? 'unknown').toUpperCase()}</td>
                <td>{(w.context as any)?.returned ? 'YES' : 'NO'}</td>
                <td>{w.current_stage || '—'}</td>
                <td>
                  <StatusBadge
                    label={w.status}
                    variant={
                      w.status === 'COMPLETED'
                        ? 'success'
                        : w.status === 'RECOVERY_REQUIRED'
                        ? 'primary'
                        : w.status === 'BLOCKED' || w.status === 'FAILED'
                        ? 'danger'
                        : 'warning'
                    }
                  />
                </td>
                <td>
                  {w.final_outcome ? (
                    <span>
                      <StatusBadge label={w.final_outcome.outcome} variant={outcomeVariant(w.final_outcome.outcome)} />
                      {w.final_outcome.provisional && <span className="provisional-badge">Provisional</span>}
                    </span>
                  ) : (
                    <span style={{ color: '#8b918c', fontSize: 12 }}>No outcome yet</span>
                  )}
                </td>
                <td>
                  {w.final_outcome?.claimable_usd ? (
                    <strong style={{ color: '#2f8f68' }}>${w.final_outcome.claimable_usd.toFixed(2)}</strong>
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PageTemplate>
  )
}

function WorkflowDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { workflows, loaded, openOverrideModal, handleResumeWorkflow, openEvidenceDrawer } = useApp()
  const [evidenceBundle, setEvidenceBundle] = useState<EvidenceBundle | null>(null)

  const workflow = workflows.find((w) => w.workflow_id === id)

  useEffect(() => {
    if (workflow) {
      api
        .getEvidence(workflow.workflow_id)
        .then((bundle) => setEvidenceBundle(bundle))
        .catch(() => setEvidenceBundle(null))
    }
  }, [workflow])

  if (!workflow) {
    return (
      <PageTemplate title={id ?? 'Workflow'} subtitle={loaded ? 'Not in the orchestrator store.' : 'Loading…'}>
        <Link to="/workflows">Back to Workflows</Link>
      </PageTemplate>
    )
  }

  // Extract clean stages
  const stageResults = workflow.stage_results || []
  const flowStages = ['receiving', 'prep', 'pack', 'returns', 'recovery']
  const stageMap = new Map<string, StageResult>()
  stageResults.forEach((s) => stageMap.set(s.stage, s))

  const handleRecordClick = (recordId: string) => {
    // Only stored records are shown; if the bundle has not loaded yet, nothing opens.
    if (evidenceBundle?.evidence[recordId]) {
      openEvidenceDrawer(evidenceBundle.evidence[recordId])
    }
  }

  return (
    <PageTemplate
      title={workflow.subject_id}
      subtitle={`${workflow.workflow_id} · Org: ${workflow.org_id}`}
      breadcrumb={[
        { label: 'Overview', to: '/overview' },
        { label: 'Workflows', to: '/workflows' },
        { label: workflow.workflow_id, to: `/workflows/${workflow.workflow_id}` },
      ]}
    >
      <div className="detail-layout">
        <div className="detail-main">
          <div className="detail-header">
            <div>
              <h2>{workflow.subject_id}</h2>
              <p>{workflow.workflow_id}</p>
            </div>
            <div className="pill-cluster">
              <StatusBadge
                label={workflow.status}
                variant={
                  workflow.status === 'COMPLETED'
                    ? 'success'
                    : workflow.status === 'RECOVERY_REQUIRED'
                    ? 'primary'
                    : workflow.status === 'BLOCKED' || workflow.status === 'FAILED'
                    ? 'danger'
                    : 'warning'
                }
              />
              {workflow.final_outcome && (
                <span>
                  <StatusBadge
                    label={workflow.final_outcome.outcome}
                    variant={outcomeVariant(workflow.final_outcome.outcome)}
                  />
                  {workflow.final_outcome.provisional && (
                    <span className="provisional-badge">Provisional</span>
                  )}
                </span>
              )}
            </div>
          </div>

          <div className="action-row">
            <button
              type="button"
              className="primary-button inline-link"
              onClick={() => navigate(`/evidence?workflow=${workflow.workflow_id}`)}
            >
              Explore Evidence Graph
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => handleResumeWorkflow(workflow.workflow_id)}
            >
              Resume
            </button>
            <button
              type="button"
              className="tertiary-button"
              disabled={!reviewTarget(workflow)}
              onClick={() => {
                const t = reviewTarget(workflow)
                if (t) openOverrideModal(t)
              }}
            >
              Intervene / Override
            </button>
          </div>

          {/* 5-Stage Orchestration Timeline */}
          <div className="timeline-panel">
            {flowStages.map((stageName) => {
              const res = stageMap.get(stageName)
              const isSkipped = res?.state === 'skipped'
              const isCompleted = res?.state === 'completed'
              const isError = res?.state === 'error'
              const verdict = res?.verdict || null
              const nextRec =
                typeof res?.next_step_recommendation === 'object' && res?.next_step_recommendation !== null
                  ? res.next_step_recommendation.reason
                  : typeof res?.next_step_recommendation === 'string'
                  ? res.next_step_recommendation
                  : null

              return (
                <div
                  key={stageName}
                  className={`timeline-item ${isSkipped ? 'skipped' : isError ? 'error' : isCompleted ? 'complete' : 'active'}`}
                >
                  <span style={{ textTransform: 'capitalize', fontWeight: 600 }}>{stageName}</span>
                  <div className="timeline-copy">
                    <strong>
                      {isSkipped
                        ? 'Stage Bypassed'
                        : isCompleted
                        ? `Verdict: ${verdict ?? 'none'} · ${res?.outcome ?? '—'}`
                        : isError
                        ? `Error (${res?.error?.code ?? 'unknown'}): ${res?.error?.message ?? 'no message recorded'}`
                        : 'Awaiting execution'}
                    </strong>
                    {isSkipped && res?.skipped_reason && (
                      <div className="skip-reason">Skipped: {res.skipped_reason}</div>
                    )}
                    {res?.record_id && (
                      <small
                        onClick={() => handleRecordClick(res.record_id!)}
                        style={{ cursor: 'pointer', textDecoration: 'underline' }}
                      >
                        Evidence: {res.record_id}
                      </small>
                    )}
                    {nextRec && (
                      <div>
                        <span className="hint-chip">
                          <Info size={11} /> {nextRec}
                        </span>
                      </div>
                    )}
                  </div>
                  <span>
                    {isSkipped ? (
                      'SKIPPED'
                    ) : isCompleted ? (
                      '✓'
                    ) : isError ? (
                      <XCircle size={15} color="#c46b64" />
                    ) : (
                      'PENDING'
                    )}
                  </span>
                </div>
              )
            })}
          </div>

          {/* What each agent actually reported, read from its stored Evidence Record */}
          <div className="se-list">
            <div className="side-label">Agent evidence, stage by stage</div>
            {flowStages.map((stageName) => (
              <StageEvidence key={stageName} stage={stageName} result={stageMap.get(stageName)} bundle={evidenceBundle} />
            ))}
          </div>

          {/* Override History if present */}
          {workflow.overrides && workflow.overrides.length > 0 && (
            <div className="override-history-card">
              <div className="side-label">Audit: Override History ({workflow.overrides.length})</div>
              <table className="override-table">
                <thead>
                  <tr>
                    <th>Actor</th>
                    <th>Target Record</th>
                    <th>Verdict Change</th>
                    <th>Reason</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {workflow.overrides.map((ovr) => (
                    <tr key={ovr.override_id}>
                      <td><strong>{ovr.actor}</strong></td>
                      <td>{ovr.supersedes?.record_id ?? ovr.target}</td>
                      <td>
                        {ovr.previous_verdict} → <strong>{ovr.new_verdict}</strong>
                      </td>
                      <td>{ovr.reason}</td>
                      <td><small>{new Date(ovr.at).toLocaleTimeString()}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Transition Audit Log */}
          {workflow.transitions && workflow.transitions.length > 0 && (
            <div className="override-history-card">
              <div className="side-label">State Transitions & Audit Log</div>
              <div className="transitions-list">
                {workflow.transitions.map((tr, idx) => (
                  <div key={idx} className="transition-entry">
                    <div>
                      <strong>{tr.event}</strong> · {tr.stage ? `${tr.stage}: ` : ''}
                      <span>{tr.detail || '—'}</span>
                    </div>
                    <span className="transition-time">
                      {new Date(tr.at).toLocaleTimeString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <aside className="detail-side">
          <div className="side-card">
            <div className="side-label">Final outcome</div>
            <h3>{workflow.final_outcome?.outcome || workflow.status}</h3>
            {workflow.final_outcome?.claimable_usd ? (
              <div className="money-line">
                Claimable <strong className="claimable-value">${workflow.final_outcome.claimable_usd.toFixed(2)}</strong>
              </div>
            ) : null}
            <p>
              {workflow.final_outcome?.reason || workflow.status_reason || '—'}
            </p>

            <div className="side-label" style={{ marginTop: 16 }}>Contributing Evidence</div>
            <div className="record-list">
              {workflow.evidence_references.map((ref) => (
                <span
                  key={ref}
                  onClick={() => handleRecordClick(ref)}
                  style={{ cursor: 'pointer' }}
                  title="Click to view evidence details"
                >
                  {ref}
                </span>
              ))}
            </div>
          </div>

          <div className="side-card">
            <div className="side-label">Workflow Context</div>
            <div className="key-value"><span>Org ID</span><strong>{workflow.org_id}</strong></div>
            <div className="key-value"><span>Unit ID</span><strong>{workflow.subject_id}</strong></div>
            <div className="key-value"><span>Route</span><strong>{String((workflow.context as any)?.route ?? 'unknown').toUpperCase()}</strong></div>
            <div className="key-value"><span>Customer Returned</span><strong>{(workflow.context as any)?.returned ? 'YES' : 'NO'}</strong></div>
            <div className="key-value"><span>Evidence Records</span><strong>{workflow.evidence_references.length}</strong></div>
          </div>
        </aside>
      </div>
    </PageTemplate>
  )
}

function UnitsPage() {
  const { workflows } = useApp()
  const navigate = useNavigate()
  const [unitFilter, setUnitFilter] = useState<'All' | 'BLOCKED' | 'FAILED' | 'RECOVERY_REQUIRED' | 'COMPLETED'>('All')

  const units = useMemo(() => {
    return workflows.map((w) => ({
      id: w.subject_id,
      workflowId: w.workflow_id,
      org: w.org_id,
      route: String((w.context as any)?.route ?? 'unknown').toUpperCase(),
      returned: (w.context as any)?.returned ? 'YES' : 'NO',
      stage: w.current_stage || '—',
      condition: returnsOf(w)?.verdict ?? (returnsOf(w) ? 'not judged' : 'not returned'),
      disposition: returnsOf(w)?.outcome ?? '—',
      workflowStatus: w.status,
      finalOutcome: w.final_outcome?.outcome ?? null,
    }))
  }, [workflows])

  const filteredUnits = units.filter((u) => unitFilter === 'All' || u.workflowStatus === unitFilter)

  return (
    <PageTemplate title="Units" subtitle="Operational commerce objects and unit trajectories">
      <div className="page-summary-grid">
        <div className="summary-card">
          <span>Total units</span>
          <strong>{units.length}</strong>
        </div>
        <div className="summary-card">
          <span>Needs action (blocked, failed, recovery required)</span>
          <strong>{units.filter((u) => ['BLOCKED', 'FAILED', 'RECOVERY_REQUIRED'].includes(u.workflowStatus)).length}</strong>
        </div>
        <div className="summary-card">
          <span>Finalized</span>
          <strong>{units.filter((u) => u.workflowStatus === 'COMPLETED').length}</strong>
        </div>
      </div>

      <div className="toolbar filter-toolbar">
        {(['All', 'BLOCKED', 'FAILED', 'RECOVERY_REQUIRED', 'COMPLETED'] as const).map((filter) => (
          <button
            key={filter}
            type="button"
            className={`secondary-button small ${unitFilter === filter ? 'active' : ''}`}
            onClick={() => setUnitFilter(filter)}
          >
            {filter}
          </button>
        ))}
      </div>

      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th>Unit ID</th>
              <th>Workflow</th>
              <th>Organization</th>
              <th>Route</th>
              <th>Returned</th>
              <th>Stage</th>
              <th>Disposition</th>
              <th>Workflow Status</th>
              <th>Final Outcome</th>
            </tr>
          </thead>
          <tbody>
            {filteredUnits.length === 0 && (
              <tr>
                <td colSpan={9}>{units.length ? 'No unit matches this filter.' : 'No workflows yet.'}</td>
              </tr>
            )}
            {filteredUnits.map((unit) => (
              // The same unit id can exist in two orgs: the workflow id is the unique key, and the org goes in the link.
              <tr key={unit.workflowId} onClick={() => navigate(`/units/${unit.id}?org=${unit.org}`)} style={{ cursor: 'pointer' }}>
                <td><strong>{unit.id}</strong></td>
                <td><Link to={`/workflows/${unit.workflowId}`}>{unit.workflowId}</Link></td>
                <td>{unit.org}</td>
                <td>{unit.route}</td>
                <td>{unit.returned}</td>
                <td>{unit.stage}</td>
                <td>{unit.disposition}</td>
                <td>
                  <StatusBadge
                    label={unit.workflowStatus}
                    variant={statusVariant(unit.workflowStatus)}
                  />
                </td>
                <td>
                  {unit.finalOutcome ? <StatusBadge label={unit.finalOutcome} variant={outcomeVariant(unit.finalOutcome)} /> : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PageTemplate>
  )
}

function UnitDetailPage() {
  const { id } = useParams()
  const { workflows, loaded, openEvidenceDrawer } = useApp()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'INBOUND' | 'PACK / PREP' | 'RETURNED'>('RETURNED')
  const [bundle, setBundle] = useState<EvidenceBundle | null>(null)
  const [searchParams] = useSearchParams()
  const org = searchParams.get('org')

  // A unit id is only unique within an org: with ?org= pick that org's workflow; without it, only an unambiguous match.
  const candidates = workflows.filter((w) => w.subject_id === id && (!org || w.org_id === org))
  const matchingWf = candidates.length === 1 ? candidates[0] : undefined

  useEffect(() => {
    if (matchingWf) api.getEvidence(matchingWf.workflow_id).then(setBundle).catch(() => setBundle(null))
  }, [matchingWf])

  if (!matchingWf) {
    return (
      <PageTemplate
        title={`Unit ${id}`}
        subtitle={!loaded ? 'Loading…' : candidates.length > 1 ? 'Same unit id in several orgs.' : 'No workflow for this unit in the orchestrator store.'}
      >
        {candidates.length > 1 ? (
          <div className="side-card">
            <p>This unit id exists in more than one org. Pick one:</p>
            {candidates.map((w) => (
              <div key={w.workflow_id}>
                <Link to={`/units/${id}?org=${w.org_id}`}>{w.org_id}</Link>
              </div>
            ))}
          </div>
        ) : (
          <Link to="/units">Back to Units</Link>
        )}
      </PageTemplate>
    )
  }

  const tabStages = { INBOUND: ['receiving'], 'PACK / PREP': ['prep', 'pack'], RETURNED: ['returns'] }[tab]
  const tabRecords = matchingWf.stage_results
    .filter((s) => tabStages.includes(s.stage) && s.record_id)
    .map((s) => bundle?.evidence[s.record_id as string])
    .filter((r): r is EvidenceRecord => Boolean(r))
  const eff = matchingWf.final_outcome?.effective_verdicts ?? {}

  return (
    <PageTemplate
      title={`Unit ${matchingWf.subject_id}`}
      subtitle={`${matchingWf.workflow_id} · Route: ${String((matchingWf.context as any)?.route ?? 'unknown').toUpperCase()}`}
      breadcrumb={[
        { label: 'Overview', to: '/overview' },
        { label: 'Units', to: '/units' },
        { label: matchingWf.subject_id, to: `/units/${matchingWf.subject_id}?org=${matchingWf.org_id}` },
      ]}
    >
      <div className="detail-layout">
        <div className="detail-main">
          <div className="detail-header">
            <div>
              <h2>{matchingWf.subject_id}</h2>
              <p>Organization: {matchingWf.org_id}</p>
            </div>
            <div className="pill-cluster">
              <StatusBadge label={matchingWf.status} variant={statusVariant(matchingWf.status)} />
              {matchingWf.final_outcome && (
                <StatusBadge label={matchingWf.final_outcome.outcome} variant={outcomeVariant(matchingWf.final_outcome.outcome)} />
              )}
            </div>
          </div>

          <div className="action-row">
            <Link to={`/workflows/${matchingWf.workflow_id}`} className="primary-button inline-link">
              Open Workflow
            </Link>
            <button
              type="button"
              className="secondary-button"
              onClick={() => navigate(`/evidence?workflow=${matchingWf.workflow_id}`)}
            >
              View Evidence Graph
            </button>
          </div>

          <div className="identity-grid">
            <div className="identity-card">
              <span className="side-label">Unit</span>
              <h3>{matchingWf.subject_id}</h3>
              <div className="key-value"><span>Org</span><strong>{matchingWf.org_id}</strong></div>
              <div className="key-value"><span>Route</span><strong>{String((matchingWf.context as any)?.route ?? 'unknown').toUpperCase()}</strong></div>
              <div className="key-value"><span>Returned</span><strong>{(matchingWf.context as any)?.returned ? 'YES' : 'NO'}</strong></div>
            </div>
            <div className="identity-card">
              <span className="side-label">Effective verdicts (after overrides)</span>
              {Object.entries(eff).map(([stage, verdict]) => (
                <div key={stage} className="key-value">
                  <span>{stage}</span>
                  <StatusBadge label={verdict} variant={stageVariant(verdict, 'completed')} />
                </div>
              ))}
              <div className="key-value"><span>Evidence records</span><strong>{matchingWf.evidence_references.length}</strong></div>
            </div>
          </div>

          <div className="tab-row">
            {(['INBOUND', 'PACK / PREP', 'RETURNED'] as const).map((tabKey) => (
              <button
                key={tabKey}
                type="button"
                className={`tab-button ${tab === tabKey ? 'selected' : ''}`}
                onClick={() => setTab(tabKey)}
              >
                {tabKey}
              </button>
            ))}
          </div>

          <div className="detail-two-col">
            <div className="compare-card">
              <div className="mini-head">Stage checks</div>
              {tabRecords.length === 0 && <p className="detail-note">No record for this stage (skipped or not run).</p>}
              <ul>
                {tabRecords.flatMap((r) =>
                  (r.checks ?? []).map((c) => (
                    <li key={`${r.record_id}-${c.check_key}`}>
                      <strong>{c.verdict}</strong> {c.check_key}
                      {c.confidence != null ? ` (${c.confidence})` : ''}
                      {c.uncertain_reason ? ` · ${c.uncertain_reason}` : ''}
                    </li>
                  )),
                )}
              </ul>
            </div>
            <div className="compare-card">
              <div className="mini-head">Inputs examined (sha256)</div>
              <ul>
                {tabRecords.flatMap((r) =>
                  (r.inputs ?? []).map((i) => (
                    <li key={`${r.record_id}-${i.ref}`}>
                      <code>{i.ref}</code> {i.sha256 ? <small>{String(i.sha256).slice(0, 12)}…</small> : <small>(no hash)</small>}
                    </li>
                  )),
                )}
              </ul>
              {tabRecords.map((r) => (
                <button key={r.record_id} type="button" className="secondary-button small" onClick={() => openEvidenceDrawer(r)}>
                  Open {r.record_id}
                </button>
              ))}
            </div>
          </div>
          <div className="compare-card" style={{ marginTop: 16 }}>
            <div className="mini-head">Final outcome reason</div>
            <p className="detail-note">{matchingWf.final_outcome?.reason ?? 'No outcome yet.'}</p>
          </div>
        </div>

        <aside className="detail-side">
          <div className="side-card">
            <div className="side-label">Evidence Chain</div>
            <div className="record-list">
              {matchingWf.evidence_references.map((r) => (
                <span key={r}>{r}</span>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </PageTemplate>
  )
}

function ReviewQueuePage() {
  const { workflows, openOverrideModal, handleResumeWorkflow } = useApp()
  const navigate = useNavigate()

  // A workflow is in the queue while the orchestrator's final outcome still needs a person. A stage that a person
  // already overrode is resolved even though the agent's own record keeps needs_human.
  const displayList = useMemo(() => {
    return workflows
      .filter((w) => w.final_outcome?.needs_human)
      .map((w) => {
        const overridden = new Set(w.overrides.map((o) => o.supersedes.record_id))
        const open = w.stage_results.find((s) => s.needs_human && s.record_id && !overridden.has(s.record_id))
        return {
          unit: w.subject_id,
          workflow: w.workflow_id,
          stage: open?.stage || '—',
          problem: !open
            ? `Final outcome ${w.final_outcome?.outcome ?? '—'}`
            : open.error?.message
            ? `${open.state === 'error' ? 'Stage error' : 'Pending'}: ${String(open.error.message)}`
            : `${open.verdict ?? 'no verdict'} (${open.outcome ?? '—'})`,
          verdict: open?.verdict ?? 'UNCERTAIN',
          reason: w.final_outcome?.reason || w.status_reason,
          evidenceCount: w.evidence_references.length,
          recordId: open?.record_id ?? null,
          canResume: w.status === 'FAILED',
        }
      })
  }, [workflows])

  return (
    <PageTemplate title="Review Queue" subtitle="Items waiting on human intervention or override">
      <div className="page-summary-grid">
        <div className="summary-card">
          <span>Open reviews</span>
          <strong>{displayList.length}</strong>
        </div>
        <div className="summary-card">
          <span>Failed (resume)</span>
          <strong>{displayList.filter((r) => r.canResume).length}</strong>
        </div>
        <div className="summary-card">
          <span>Evidence assets</span>
          <strong>{displayList.reduce((sum, r) => sum + r.evidenceCount, 0)}</strong>
        </div>
      </div>

      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th>Unit</th>
              <th>Workflow</th>
              <th>Stage</th>
              <th>Problem</th>
              <th>Reason</th>
              <th>Evidence</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {displayList.length === 0 && (
              <tr>
                <td colSpan={7}>No workflow is waiting for a person.</td>
              </tr>
            )}
            {displayList.map((rev) => (
              <tr key={rev.workflow}>
                <td><strong>{rev.unit}</strong></td>
                <td><Link to={`/workflows/${rev.workflow}`}>{rev.workflow}</Link></td>
                <td>{rev.stage}</td>
                <td><span style={{ color: '#c46b64' }}>{rev.problem}</span></td>
                <td><small>{rev.reason}</small></td>
                <td>{rev.evidenceCount} records</td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {rev.canResume ? (
                      <button type="button" className="primary-button small" onClick={() => handleResumeWorkflow(rev.workflow)}>
                        Resume
                      </button>
                    ) : (
                      rev.recordId && (
                        <button
                          type="button"
                          className="primary-button small"
                          onClick={() =>
                            openOverrideModal({
                              workflowId: rev.workflow,
                              recordId: rev.recordId as string,
                              currentVerdict: rev.verdict,
                              stage: rev.stage,
                            })
                          }
                        >
                          Apply Override
                        </button>
                      )
                    )}
                    <button
                      type="button"
                      className="secondary-button small"
                      onClick={() => navigate(`/workflows/${rev.workflow}`)}
                    >
                      Inspect
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PageTemplate>
  )
}

function RecoveryPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeFilter = searchParams.get('filter') ?? 'all'
  const { workflows } = useApp()
  const [loadedCharges, setCharges] = useState<RecoveryChargeItem[] | null>(null)
  const charges = loadedCharges ?? []

  useEffect(() => {
    let cancelled = false
    loadCharges(workflows).then((rows) => {
      if (!cancelled) setCharges(rows)
    })
    return () => {
      cancelled = true
    }
  }, [workflows])

  const filteredCharges = charges.filter((row) => {
    if (activeFilter === 'claimable') return row.decision === 'CLAIM RECOMMENDED'
    if (activeFilter === 'supports') return row.position === 'SUPPORTS'
    if (activeFilter === 'silent') return row.position === 'SILENT'
    return true
  })

  const claimableTotal = charges
    .filter((row) => row.decision === 'CLAIM RECOMMENDED')
    .reduce((sum, row) => sum + row.amountNum, 0)

  return (
    <PageTemplate title="Recovery & Claims" subtitle="Charge review and automated claim recommendation workflow">
      <div className="metrics-row">
        <MetricCard label="Charges Reviewed" value={String(charges.length)} />
        <MetricCard label="Claims Recommended" value={String(charges.filter((r) => r.decision === 'CLAIM RECOMMENDED').length)} />
        <MetricCard label="Claimable Value" value={`$${claimableTotal.toFixed(2)}`} />
        <MetricCard label="Silent" value={String(charges.filter((r) => r.position === 'SILENT').length)} />
      </div>

      <div className="toolbar filter-toolbar">
        {(['all', 'claimable', 'supports', 'silent'] as const).map((filter) => (
          <button
            key={filter}
            type="button"
            className={`secondary-button small ${activeFilter === filter ? 'active' : ''}`}
            onClick={() => setSearchParams(filter === 'all' ? {} : { filter })}
          >
            {filter.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th>Charge ID</th>
              <th>Type</th>
              <th>Amount</th>
              <th>Position</th>
              <th>Evidence</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {loadedCharges === null && (
              <tr>
                <td colSpan={6}>Loading Recovery evidence…</td>
              </tr>
            )}
            {loadedCharges !== null && filteredCharges.length === 0 && (
              <tr>
                <td colSpan={6}>No fee lines match this filter.</td>
              </tr>
            )}
            {filteredCharges.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link to={`/recovery/charges/${row.id}`}>
                    <strong>{row.id}</strong>
                  </Link>
                </td>
                <td>{row.type}</td>
                <td><strong>{row.amount}</strong></td>
                <td>
                  <StatusBadge
                    label={row.position}
                    variant={row.position === 'CONTRADICTS' ? 'primary' : row.position === 'SUPPORTS' ? 'success' : 'warning'}
                  />
                </td>
                <td><small>{row.evidence}</small></td>
                <td>
                  <StatusBadge
                    label={row.decision}
                    variant={row.decision === 'CLAIM RECOMMENDED' ? 'primary' : 'success'}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PageTemplate>
  )
}

function RecoveryChargeDetailPage() {
  const { id } = useParams()
  const { workflows, openEvidenceDrawer } = useApp()
  const [charge, setCharge] = useState<RecoveryChargeItem | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [inspectError, setInspectError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    loadCharges(workflows).then((rows) => {
      if (cancelled) return
      setCharge(rows.find((c) => c.id === id) ?? null)
      setLoaded(true)
    })
    return () => {
      cancelled = true
    }
  }, [id, workflows])

  if (!charge) {
    return (
      <PageTemplate title={id ?? 'Charge'} subtitle={loaded ? 'No Recovery record contains this fee line.' : 'Loading…'}>
        <Link to="/recovery">Back to Recovery</Link>
      </PageTemplate>
    )
  }
  const targetCharge = charge

  const handleInspect = async (recId: string) => {
    setInspectError(null)
    try {
      const bundle = await api.getEvidence(targetCharge.workflowId)
      if (bundle?.evidence?.[recId]) {
        openEvidenceDrawer(bundle.evidence[recId])
        return
      }
      setInspectError(`${recId} is not stored in ${targetCharge.workflowId}`)
    } catch (err) {
      setInspectError(`Could not load evidence: ${String(err)}`)
    }
  }

  return (
    <PageTemplate
      title={targetCharge.id}
      subtitle={`${targetCharge.type} · ${targetCharge.amount}`}
      breadcrumb={[
        { label: 'Overview', to: '/overview' },
        { label: 'Recovery', to: '/recovery' },
        { label: targetCharge.id, to: `/recovery/charges/${targetCharge.id}` },
      ]}
    >
      <div className="detail-layout">
        <div className="detail-main">
          <div className="detail-header">
            <div>
              <h2>{targetCharge.id}</h2>
              <p>{targetCharge.type} · {targetCharge.amount}</p>
            </div>
            <StatusBadge
              label={targetCharge.position}
              variant={targetCharge.position === 'CONTRADICTS' ? 'primary' : targetCharge.position === 'SUPPORTS' ? 'success' : 'warning'}
            />
          </div>

          <div className="side-card" style={{ marginTop: 20 }}>
            <div className="side-label">
              {targetCharge.position === 'CONTRADICTS' ? 'Why is this charge disputed?' : 'Why is this charge not claimed?'}
            </div>
            <p style={{ lineHeight: 1.6, fontSize: 14 }}>
              {targetCharge.reason}
            </p>
            {inspectError && <p style={{ color: '#c46b64' }}>{inspectError}</p>}
            {targetCharge.evidenceIds && targetCharge.evidenceIds.length > 0 && (
              <div style={{ marginTop: 16, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                {targetCharge.evidenceIds.map((eId) => (
                  <button
                    key={eId}
                    type="button"
                    className="primary-button small"
                    onClick={() => handleInspect(eId)}
                  >
                    Inspect {eId} Evidence
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <aside className="detail-side">
          <div className="side-card">
            <div className="side-label">Decision Summary</div>
            <h3 style={{ color: targetCharge.decision === 'CLAIM RECOMMENDED' ? '#2f8f68' : '#737373' }}>
              {targetCharge.decision}
            </h3>
            <div className="key-value"><span>Workflow</span><strong style={{ fontSize: 12 }}>{targetCharge.workflowId}</strong></div>
            <div className="key-value"><span>Type</span><strong>{targetCharge.type}</strong></div>
            <div className="key-value"><span>Amount</span><strong>{targetCharge.amount}</strong></div>
            <div className="key-value"><span>Position</span><strong>{targetCharge.position}</strong></div>
            <div className="key-value"><span>Evidence Ref</span><strong>{targetCharge.evidence}</strong></div>
          </div>
        </aside>
      </div>
    </PageTemplate>
  )
}

function EvidencePage() {
  const { workflows, loaded, openEvidenceDrawer } = useApp()
  const [searchParams, setSearchParams] = useSearchParams()
  const [bundle, setBundle] = useState<EvidenceBundle | null>(null)
  const selectedWfId = searchParams.get('workflow') || workflows[0]?.workflow_id || ''
  const activeWorkflow = workflows.find((w) => w.workflow_id === selectedWfId)

  useEffect(() => {
    if (activeWorkflow) api.getEvidence(activeWorkflow.workflow_id).then(setBundle).catch(() => setBundle(null))
  }, [activeWorkflow])

  if (!activeWorkflow) {
    return (
      <PageTemplate title="Evidence Explorer" subtitle={loaded ? 'No workflows in the orchestrator store yet.' : 'Loading…'}>
        <Link to="/workflows">Run a workflow first</Link>
      </PageTemplate>
    )
  }

  // One node per current stage record, laid out left to right; edges are the records' own upstream_refs.
  const current = activeWorkflow.stage_results.filter((s) => s.record_id)
  const nodes = current.map((s, i) => ({ id: s.record_id as string, stage: s.stage, verdict: s.verdict, x: 110 + i * 175, y: 200 }))
  const pos = new Map(nodes.map((n) => [n.id, n]))
  const edges: Array<[string, string]> = []
  nodes.forEach((n) => {
    for (const up of bundle?.evidence[n.id]?.upstream_refs ?? []) if (pos.has(up)) edges.push([up, n.id])
  })
  const outcome = { x: 110 + Math.max(0, nodes.length - 1) * 175, y: 60 }

  return (
    <PageTemplate title="Evidence Explorer" subtitle="Each arrow is an upstream_ref recorded in the evidence itself">
      <div className="toolbar" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Workflow:</span>
        <select
          className="form-select"
          style={{ width: 340 }}
          value={selectedWfId}
          onChange={(e) => setSearchParams({ workflow: e.target.value })}
        >
          {workflows.map((w) => (
            <option key={w.workflow_id} value={w.workflow_id}>
              {w.workflow_id} ({w.subject_id} · {w.status})
            </option>
          ))}
        </select>
        <span style={{ fontSize: 12, color: '#606661' }}>Click a record to open it</span>
      </div>

      <div className="evidence-graph-panel">
        {/* No viewBox: SVG user units are CSS pixels, the same frame the absolutely positioned nodes use. */}
        <svg className="evidence-svg" aria-hidden="true">
          {edges.map(([a, b]) => {
            const from = pos.get(a)!
            const to = pos.get(b)!
            const lift = (to.x - from.x) / 4
            return (
              <path
                key={`${a}-${b}`}
                d={`M ${from.x} ${from.y} Q ${(from.x + to.x) / 2} ${from.y + lift} ${to.x} ${to.y}`}
                fill="none"
                stroke="rgba(47, 143, 104, 0.45)"
                strokeWidth="2"
              />
            )
          })}
          {(activeWorkflow.final_outcome?.contributing_records ?? []).map((rid) =>
            pos.has(rid) ? (
              <line key={`out-${rid}`} x1={pos.get(rid)!.x} y1={pos.get(rid)!.y} x2={outcome.x} y2={outcome.y}
                    stroke="rgba(96, 102, 97, 0.25)" strokeDasharray="4 4" strokeWidth="1.5" />
            ) : null,
          )}
        </svg>

        <div className="graph-node-grid">
          {nodes.map((node) => (
            <div
              key={node.id}
              className="graph-node clickable-node"
              style={{ left: `${node.x}px`, top: `${node.y}px` }}
              onClick={() => bundle?.evidence[node.id] && openEvidenceDrawer(bundle.evidence[node.id])}
              title="Click to inspect record"
            >
              <div>{node.stage} · {node.verdict}</div>
              <strong>{node.id}</strong>
            </div>
          ))}
          <div className="graph-node" style={{ left: `${outcome.x}px`, top: `${outcome.y}px` }}>
            <div>Final Outcome</div>
            <strong>{activeWorkflow.final_outcome?.outcome ?? '—'}</strong>
          </div>
        </div>
      </div>
    </PageTemplate>
  )
}

function AgentsPage() {
  const { health } = useApp()
  const live = Object.values(health?.agents ?? {})
  const integrated = live.filter((a) => a.implementation && a.implementation !== 'organiser-stub').length
  return (
    <PageTemplate title="Agents" subtitle="Five specialized operational agents and their live pod status">
      <div className="page-summary-grid compact">
        <div className="summary-card">
          <span>Agents in flow</span>
          <strong>{live.length || '—'}</strong>
        </div>
        <div className="summary-card">
          <span>Integrated (not stubs)</span>
          <strong style={{ color: '#2f8f68' }}>{health ? `${integrated} of ${live.length}` : '—'}</strong>
        </div>
        <div className="summary-card">
          <span>System Status</span>
          <strong>{health ? health.status.toUpperCase() : 'OFFLINE'}</strong>
        </div>
      </div>

      <div className="agent-grid">
        {exampleAgents.map((agent) => {
          const liveAgent = health?.agents?.[agent.slug]
          const isIntegrated = liveAgent ? liveAgent.implementation !== 'organiser-stub' : agent.status === 'INTEGRATED'
          return (
            <Link key={agent.slug} to={`/agents/${agent.slug}`} className="agent-card">
              <div className="agent-card-top">
                <div className={`status-dot ${isIntegrated ? 'healthy-dot' : 'warning-dot'}`} />
                <span style={{ fontWeight: 600, color: isIntegrated ? '#2f8f68' : '#d97706' }}>
                  {isIntegrated ? 'INTEGRATED' : 'ORGANISER STUB'}
                </span>
              </div>
              <h3>{agent.title}</h3>
              <p style={{ fontSize: 13, color: '#555', margin: '4px 0 10px 0', lineHeight: 1.4 }}>
                {agent.description}
              </p>
              <div className="meta-stack">
                <span>Stage: <strong>{agent.stage}</strong></span>
                <span>Agent ID: <code>{liveAgent?.agent_id || agent.id}</code></span>
                <span>Owner: <strong>{liveAgent?.owner || agent.owner}</strong></span>
                <span>Mode: <code>{liveAgent?.mode || agent.mode}</code></span>
              </div>
            </Link>
          )
        })}
      </div>
    </PageTemplate>
  )
}

function AgentDetailPage() {
  const { slug } = useParams()
  const { workflows, health } = useApp()
  const agent = exampleAgents.find((item) => item.slug === slug)
  if (!agent) {
    return (
      <PageTemplate title="Agent not found" subtitle={`There is no agent called "${slug}" in this Pod.`}>
        <Link to="/agents">Back to Agents</Link>
      </PageTemplate>
    )
  }
  const liveAgent = health?.agents?.[agent.slug]
  const isIntegrated = liveAgent ? liveAgent.implementation !== 'organiser-stub' : agent.status === 'INTEGRATED'
  const stats = stageStats(workflows).find((s) => s.agent.toLowerCase() === agent.slug)

  return (
    <PageTemplate
      title={agent.title}
      subtitle={`${agent.stage} · ${agent.id}`}
      breadcrumb={[
        { label: 'Overview', to: '/overview' },
        { label: 'Agents', to: '/agents' },
        { label: agent.title, to: `/agents/${agent.slug}` },
      ]}
    >
      <div className="agent-detail-grid">
        <div className="detail-main">
          <div className="detail-header">
            <div>
              <h2>{agent.title}</h2>
              <p>{agent.stage} Stage · Owner {agent.owner}</p>
            </div>
            <StatusBadge
              label={isIntegrated ? 'INTEGRATED' : 'ORGANISER STUB'}
              variant={isIntegrated ? 'success' : 'warning'}
            />
          </div>

          <div className="metrics-row">
            <MetricCard label="Runs" value={String(stats?.runs ?? 0)} />
            <MetricCard label="PASS" value={`${stats?.pass ?? 0}%`} />
            <MetricCard label="FAIL" value={`${stats?.fail ?? 0}%`} />
            <MetricCard label="UNCERTAIN" value={`${stats?.uncertain ?? 0}%`} />
            <MetricCard label="Errors" value={`${stats?.error ?? 0}%`} />
          </div>

          <div className="detail-two-col">
            <div className="compare-card">
              <div className="mini-head">Check keys it reports</div>
              <ul>
                {(agent.details?.checks ?? []).map((chk) => (
                  <li key={chk}><code>{chk}</code></li>
                ))}
              </ul>
            </div>
            <div className="compare-card">
              <div className="mini-head">When it runs · what it is responsible for</div>
              <ul>
                {[...(agent.details?.stages ?? []), ...(agent.details?.responsibilities ?? [])].map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <aside className="detail-side">
          <div className="side-card">
            <div className="side-label">Agent Specification</div>
            <div className="key-value"><span>Stage</span><strong>{agent.stage}</strong></div>
            <div className="key-value"><span>Agent ID</span><strong style={{ fontSize: 11 }}>{liveAgent?.agent_id || agent.id}</strong></div>
            <div className="key-value"><span>Owner</span><strong>{liveAgent?.owner || agent.owner}</strong></div>
            <div className="key-value"><span>Mode</span><strong>{liveAgent?.mode || agent.mode}</strong></div>
            <div className="key-value"><span>Implementation</span><strong style={{ fontSize: 11 }}>{liveAgent?.implementation || agent.status}</strong></div>
          </div>
          <div className="side-card" style={{ marginTop: 16 }}>
            <div className="side-label">Description</div>
            <p style={{ fontSize: 13, lineHeight: 1.5, margin: 0, color: '#444' }}>
              {agent.description}
            </p>
          </div>
        </aside>
      </div>
    </PageTemplate>
  )
}

function FailuresPage() {
  const { workflows, handleResumeWorkflow, openOverrideModal } = useApp()

  const failedWorkflows = useMemo(() => {
    return workflows.filter((w) => w.status === 'FAILED' || w.status === 'BLOCKED' || w.errors.length > 0)
  }, [workflows])

  return (
    <PageTemplate title="Failures & Incidents" subtitle="Operational failures, retries, and halted workflows">
      <div className="incident-overview">
        <div className="incident-grid">
          <div className="incident-card danger">
            <span className="incident-label">Open incidents</span>
            <strong>{failedWorkflows.length}</strong>
            <small>Workflows that are FAILED or BLOCKED, or have a recorded stage error.</small>
          </div>
          <div className="incident-card">
            <span className="incident-label">Failed</span>
            <strong>{workflows.filter((w) => w.status === 'FAILED').length}</strong>
            <small>A stage did not complete. Fix the cause, then Resume.</small>
          </div>
          <div className="incident-card warning">
            <span className="incident-label">Blocked workflows</span>
            <strong>{workflows.filter((w) => w.status === 'BLOCKED').length}</strong>
            <small>Awaiting override or human review.</small>
          </div>
        </div>

        <div className="incident-alert">
          <div className="incident-alert-header">
            <span className="side-label">Incident Management</span>
            <StatusBadge label="ATTENTION" variant="warning" />
          </div>
          <p>
            A FAILED workflow is retried with Resume once the agent is reachable again. A BLOCKED workflow needs a person:
            record an override (with your name and a reason) on the record that asks for review, then Resume.
          </p>
        </div>
      </div>

      <div className="table-card">
        <table>
          <thead>
            <tr>
              <th>Workflow ID</th>
              <th>Unit ID</th>
              <th>Stage</th>
              <th>Status Reason</th>
              <th>Status</th>
              <th>Errors</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {failedWorkflows.length === 0 && (
              <tr>
                <td colSpan={7}>No failed or blocked workflows and no recorded errors.</td>
              </tr>
            )}
            {failedWorkflows.map((w) => (
              <tr key={w.workflow_id}>
                <td>
                  <Link to={`/workflows/${w.workflow_id}`}>
                    <strong>{w.workflow_id}</strong>
                  </Link>
                </td>
                <td>{w.subject_id}</td>
                <td>{w.current_stage || '—'}</td>
                <td><small>{w.halted?.reason || w.status_reason}</small></td>
                <td>
                  <StatusBadge label={w.status} variant={statusVariant(w.status)} />
                </td>
                <td>
                  {w.errors.length ? (
                    <small title={w.errors.map((e: any) => `${e.stage ?? ''} ${e.code ?? ''}: ${e.message ?? ''}`).join('\n')}>
                      {w.errors.length} ({Array.from(new Set(w.errors.map((e: any) => e.code))).join(', ')})
                    </small>
                  ) : (
                    '0'
                  )}
                </td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button
                      type="button"
                      className="primary-button small"
                      onClick={() => handleResumeWorkflow(w.workflow_id)}
                    >
                      Resume
                    </button>
                    <button
                      type="button"
                      className="secondary-button small"
                      disabled={!reviewTarget(w)}
                      onClick={() => {
                        const t = reviewTarget(w)
                        if (t) openOverrideModal(t)
                      }}
                    >
                      Override
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PageTemplate>
  )
}

function AnalyticsPage() {
  const { workflows } = useApp()

  const outcomeCounts = useMemo(() => {
    const map: Record<string, number> = {
      CLEAN: 0,
      CLAIM_RECOMMENDED: 0,
      EXCEPTION: 0,
      NEEDS_REVIEW: 0,
      INCOMPLETE: 0,
    }
    workflows.forEach((w) => {
      const out = w.final_outcome?.outcome || w.status
      map[out] = (map[out] || 0) + 1
    })
    return Object.entries(map).map(([name, value]) => ({ name, value }))
  }, [workflows])

  return (
    <PageTemplate title="Analytics" subtitle="Agent performance, workflow health, and operational outcomes">
      <div className="metrics-row">
        <MetricCard label="Workflow Volume" value={String(workflows.length)} />
        <MetricCard label="Completed" value={String(workflows.filter((w) => w.status === 'COMPLETED').length)} />
        <MetricCard label="Needs a Human" value={`${Math.round((workflows.filter((w) => w.final_outcome?.needs_human).length / Math.max(1, workflows.length)) * 100)}%`} />
        <MetricCard label="Avg agent time per workflow" value={`${avgWorkflowSeconds(workflows).toFixed(2)}s`} />
      </div>

      <div className="stack-grid lower-grid">
        <article className="panel">
          <div className="panel-header row-between">
            <div>
              <div className="eyebrow">Agent comparison</div>
              <h2>Operational efficiency</h2>
            </div>
          </div>
          <div className="chart-card">
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={stageStats(workflows)} margin={{ top: 12, right: 34, left: -6, bottom: 0 }}>
                <defs>
                  <linearGradient id="stageTimeFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#16a34a" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#16a34a" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="agent" tickLine={false} axisLine={false} dy={6} />
                <YAxis unit="s" tickLine={false} axisLine={false} tickFormatter={(v: number) => String(Math.round(v * 100) / 100)} />
                <Tooltip formatter={(v) => [`${v}s`, 'Mean stage time']} />
                <Area type="monotone" dataKey="latency" name="Mean stage time (s)" stroke="#16a34a" strokeWidth={3}
                      fill="url(#stageTimeFill)" dot={{ r: 4, fill: '#fff', stroke: '#16a34a', strokeWidth: 2 }} activeDot={{ r: 6 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="panel">
          <div className="panel-header row-between">
            <div>
              <div className="eyebrow">Outcome distribution</div>
              <h2>Workflows by state</h2>
            </div>
          </div>
          <div className="chart-card">
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={outcomeCounts.filter((o) => o.value > 0)} dataKey="value" nameKey="name" innerRadius={40} outerRadius={80} label>
                  {outcomeCounts
                    .filter((o) => o.value > 0)
                    .map((o) => (
                      <Cell key={o.name} fill={OUTCOME_COLORS[o.name] ?? '#a3a8a5'} />
                    ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </article>
      </div>
    </PageTemplate>
  )
}

function SystemPage() {
  const { health, isBackendConnected, refreshData } = useApp()

  return (
    <PageTemplate title="Pod 05" subtitle="Standard commerce flow · orchestration environment">
      <div className="system-grid">
        <div className="side-card">
          <div className="side-label">Architecture</div>
          <div className="community-stack">
            <span>Receiving Manager</span>
            <span>Prep Manager</span>
            <span>Pack Manager</span>
            <span>Returns Manager</span>
            <span>Recovery Manager</span>
          </div>
        </div>

        <div className="side-card">
          <div className="side-label">Health & Connectivity</div>
          <div className="key-value">
            <span>Backend API</span>
            <strong>{isBackendConnected ? 'Online' : 'Offline'}</strong>
          </div>
          <div className="key-value">
            <span>Flow Engine</span>
            <strong>{health?.flow ?? '—'}</strong>
          </div>
          <div className="key-value">
            <span>Orchestrator Status</span>
            <StatusBadge label={health ? health.status.toUpperCase() : 'OFFLINE'} variant={health?.status === 'ok' ? 'success' : 'danger'} />
          </div>
          <div style={{ marginTop: 14 }}>
            <button type="button" className="secondary-button small" onClick={() => refreshData()}>
              Recheck Connection
            </button>
          </div>
        </div>
      </div>
    </PageTemplate>
  )
}

function NotFoundPage() {
  return (
    <PageTemplate title="Page not found" subtitle="The route does not exist in this operations shell.">
      <div className="side-card">
        <p>Return to the overview and continue from there.</p>
        <Link to="/overview" className="primary-button small inline-link">
          Go to Overview
        </Link>
      </div>
    </PageTemplate>
  )
}

function PageTemplate({
  title,
  subtitle,
  breadcrumb,
  children,
}: {
  title: string
  subtitle: string
  breadcrumb?: { label: string; to: string }[]
  children: React.ReactNode
}) {
  return (
    <div className="page-shell">
      {breadcrumb ? (
        <nav className="breadcrumbs" aria-label="Breadcrumb">
          {breadcrumb.map((item) => (
            <div key={item.to} className="breadcrumb-item">
              <Link to={item.to}>{item.label}</Link>
              <ChevronRight size={12} />
            </div>
          ))}
        </nav>
      ) : null}
      <div className="page-header">
        <div>
          <div className="eyebrow">Operations</div>
          <h1>{title}</h1>
        </div>
        <div className="page-subtitle">{subtitle}</div>
      </div>
      {children}
    </div>
  )
}

function StatusBadge({ label, variant }: { label: string; variant: 'success' | 'danger' | 'warning' | 'primary' }) {
  return <span className={`status-badge ${variant}`}>{label}</span>
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  )
}

export default App
