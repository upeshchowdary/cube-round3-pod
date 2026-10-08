/** CUBE Round 3 — Typed API client.
 *  All requests go through /api which Vite proxies to http://localhost:8100
 */

const BASE = '/api'

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

// ── Types ─────────────────────────────────────────────────────────────────

export interface HealthAgent {
  status: string
  mode?: string
  latency?: string
  error?: string
  owner?: string
  agent_id?: string
  implementation?: string
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  flow: string
  agents: Record<string, HealthAgent>
}

export interface StageResult {
  stage: string
  agent_id: string | null
  state: 'pending' | 'completed' | 'error' | 'skipped'
  skipped_reason: string | null
  record_id: string | null
  evidence_status: string | null
  verdict: string | null
  outcome: string | null
  needs_human: boolean | null
  next_step_recommendation: string | { action?: string; reason?: string } | null
  runs: number
  attempts: number
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  error: Record<string, unknown> | null
}

export interface OverrideEntry {
  override_id: string
  supersedes: { record_id: string; override_id: string | null }
  target: string
  actor: string
  at: string
  reason: string
  original_verdict: string
  previous_verdict: string
  new_verdict: string
  new_outcome: string | null
}

export interface Transition {
  at: string
  event: string
  stage: string | null
  detail: string | null
  from_status?: string
  to_status?: string
}

export interface FinalOutcome {
  workflow_id: string
  outcome: string
  verdict: string
  reason: string
  needs_human: boolean
  provisional: boolean
  claimable_usd: number | null
  contributing_records: string[]
  effective_verdicts: Record<string, string>
  decided_by: string
  decided_at: string
}

export interface WorkflowState {
  schema_version: string
  workflow_id: string
  flow_id: string
  org_id: string
  subject_id: string
  context: Record<string, unknown>
  status: 'PENDING' | 'IN_PROGRESS' | 'FAILED' | 'RECOVERY_REQUIRED' | 'BLOCKED' | 'COMPLETED'
  status_reason: string
  current_stage: string | null
  previous_stage: string | null
  stage_results: StageResult[]
  evidence_references: string[]
  timestamps: { created_at: string; updated_at: string; completed_at: string | null }
  errors: Array<Record<string, unknown>>
  overrides: OverrideEntry[]
  halted: { stage: string; reason: string; at: string } | null
  final_outcome: FinalOutcome | null
  transitions: Transition[]
}

export interface EvidenceCheck {
  check_key: string
  verdict: string
  confidence?: number | null
  expected?: unknown
  observed?: unknown
  detail?: string
  evidence_refs?: string[]
  uncertain_reason?: string
}

export interface EvidenceRecord {
  record_id: string
  workflow_id: string
  stage: string
  agent_id: string
  status: string
  subject: { org_id: string; subject_id: string; route?: string; unit_id?: string; unit_scope?: string; refs?: Record<string, unknown> }
  decision: {
    verdict: 'PASS' | 'FAIL' | 'UNCERTAIN' | string
    outcome: string
    needs_human: boolean
    reason?: string
    confidence?: number | null
  }
  checks?: EvidenceCheck[]
  payload: Record<string, any>
  inputs: Array<{ ref?: string; kind?: string; sha256?: string; [key: string]: any }>
  upstream_refs?: string[]
  model?: { name: string; version?: string; calls?: number; cost_usd?: number | null }
  content_hash?: string
}

export interface CaseItem {
  org_id: string
  unit_id: string
  route?: string
  returned?: boolean
  source?: 'pod' | 'sample'
}

export interface EvidenceBundle {
  workflow: WorkflowState
  evidence: Record<string, EvidenceRecord>
}

// ── Helpers ───────────────────────────────────────────────────────────────

export function workflowIdFor(orgId: string, unitId: string): string {
  return `WF-${orgId}-${unitId}`
}

export function stageVariant(verdict: string | null, state: string): 'success' | 'danger' | 'warning' | 'primary' {
  if (state === 'skipped') return 'primary'
  if (verdict === 'PASS') return 'success'
  if (verdict === 'FAIL') return 'danger'
  if (verdict === 'UNCERTAIN') return 'warning'
  return 'primary'
}

// ── API calls ─────────────────────────────────────────────────────────────

export const api = {
  health: () => req<HealthResponse>('/health'),

  cases: () => req<CaseItem[]>('/cases'),

  listWorkflows: () => req<WorkflowState[]>('/workflows'),

  runWorkflow: (orgId: string, unitId: string, route?: string, returned?: boolean) =>
    req<WorkflowState>('/workflows', {
      method: 'POST',
      body: JSON.stringify({ org_id: orgId, unit_id: unitId, route, returned }),
    }),

  getWorkflow: (id: string) => req<WorkflowState>(`/workflows/${id}`),

  getEvidence: (id: string) => req<EvidenceBundle>(`/workflows/${id}/evidence`),

  resumeWorkflow: (id: string) =>
    req<WorkflowState>(`/workflows/${id}/resume`, { method: 'POST' }),

  applyOverride: (
    workflowId: string,
    recordId: string,
    newVerdict: string,
    actor: string,
    reason: string,
    newOutcome?: string,
  ) =>
    req<WorkflowState>(`/workflows/${workflowId}/overrides`, {
      method: 'POST',
      body: JSON.stringify({
        record_id: recordId,
        new_verdict: newVerdict,
        actor,
        reason,
        new_outcome: newOutcome || undefined,
      }),
    }),
}
