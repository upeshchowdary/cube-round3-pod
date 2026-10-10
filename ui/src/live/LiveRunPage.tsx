// Live Run: type in one product, upload its photos, press Start, and watch the Pod's real agents process it step by
// step. Every verdict and reason below the timeline is read from the agents' evidence records; this page writes none.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { StageEvidence } from '../components/StageEvidence'
import type { EvidenceBundle, EvidenceRecord, StageResult, WorkflowState } from '../services/api'
import './live.css'

const API = '/api/live'
const STAGES = ['receiving', 'prep', 'pack', 'returns', 'recovery'] as const
type Stage = (typeof STAGES)[number]

const AGENTS: Record<Stage, { name: string; owner: string; does: string }> = {
  receiving: { name: 'Receiving Manager', owner: 'Kiran', does: 'Checks what arrived against the purchase order: identity, cartons, quantity, damage, quality.' },
  prep: { name: 'Prep Manager', owner: 'Suhana', does: "FBA only: checks Amazon's prep rules (polybag, suffocation warning, FNSKU label, barcode, expiry, handling marks)." },
  pack: { name: 'Pack Manager', owner: 'Nikhil', does: 'Merchant-fulfilled only: checks the open box against the order before it is sealed.' },
  returns: { name: 'Returns Manager', owner: 'Upesh', does: 'Compares the returned item with the reference photo from Pack or Receiving: identity, completeness, condition, disposition.' },
  recovery: { name: 'Recovery Manager', owner: 'Vishruth', does: 'Audits each Amazon fee against the earlier records: contradicted (claim), supported, or silent.' },
}

type Photo = { name: string; data: string }
type PhotoSlot = 'receiving' | 'pack' | 'returns' | 'returns_ref'
type Line = { sku: string; qty: number }
type Fee = { charge_type: string; amount_usd: number; quantity: number; report_type: string }
type Config = {
  categories: string[]
  damage: string[]
  quality_flags: string[]
  channels: string[]
  charge_types: string[]
  report_types: string[]
  prep_observed: Record<string, string[]>
  keys: { gemini: number; groq: number }
  models: { gemini: string; groq: string }
}
type DemoSet = { name: string; title: string; story: string; spec: Record<string, any>; photos: Record<string, string[]> }
type RunView = {
  run_id: string
  spec: { ai?: { receiving?: boolean; pack?: boolean; returns?: boolean }; route?: string; returned?: boolean; product?: { title: string; sku: string } }
  status: { state?: string; started_at?: string; finished_at?: string; error?: string; notes?: { at: string; text: string }[]; keys_used?: Record<string, number> }
  running_stage: string | null
  workflow: WorkflowState | null
  evidence: Record<string, EvidenceRecord>
  photos: Record<string, string[]>
  log_tail: string
}

const EXAMPLE = {
  product: { title: 'PlayStation 5 DualSense Wireless Controller', sku: 'SKU-DUALSENSE-WHT', asin: 'B08H99BPJN', category: 'electronics', colour: 'white', variant: 'standard', components: 'controller; USB cable' },
  route: 'mfn' as 'mfn' | 'fba',
  returned: true,
  receiving: { supplier: 'Sony Interactive (distributor)', po_number: 'PO-LIVE-1001', cartons_ordered: 1, cartons_received: 1, units_per_carton_ordered: 12, units_per_carton_counted: 12, qty_ordered: 12, qty_received: 12, identity_match: 'yes', carton_damage: 'none', unit_damage: 'none', quality_flags: [] as string[] },
  prep: { fnsku: 'X00LIVE001', prep_price_usd: 0.4, wo_polybag: true, wo_suffocation_warning: true, wo_expiry_date: false, wo_handling_marks: [] as string[], polybag_present_sealed: 'yes', suffocation_warning: 'legible', fnsku_label_placement: 'flat', original_barcode_covered: 'yes', expiry_date: 'not_required', handling_marks: 'not_required' },
  pack: { channel: 'shopify', order_lines: [{ sku: 'SKU-DUALSENSE-WHT', qty: 1 }] as Line[], observed_in_box: [] as Line[], operator_verdict: 'seal' },
  returns: { parts_list: 'controller; USB cable' },
  fees: [{ charge_type: 'inbound_defect_fee', amount_usd: 3, quantity: 1, report_type: 'fee_report' }] as Fee[],
}

const split = (s: string) => s.split(/[;,]/).map((x) => x.trim()).filter(Boolean)
const tone = (v?: string | null) => (v === 'PASS' ? 'ok' : v === 'FAIL' ? 'bad' : v === 'UNCERTAIN' ? 'unsure' : 'none')
const human = (s: string) => s.replace(/_/g, ' ')

function readFile(file: File): Promise<Photo> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve({ name: file.name, data: String(r.result) })
    r.onerror = () => reject(r.error)
    r.readAsDataURL(file)
  })
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="form-group lr-field">
      <span className="form-label">{label}</span>
      {children}
      {hint && <span className="lr-hint">{hint}</span>}
    </label>
  )
}

function Select({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <select className="form-select" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => (
        <option key={o} value={o}>{human(o)}</option>
      ))}
    </select>
  )
}

function Num({ value, onChange, min = 0, step = 1 }: { value: number; onChange: (v: number) => void; min?: number; step?: number }) {
  return <input className="form-input" type="number" min={min} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
}

function PhotoPicker({ label, hint, photos, onChange, required }: { label: string; hint: string; photos: Photo[]; onChange: (p: Photo[]) => void; required?: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const add = async (files: FileList | null) => {
    if (!files) return
    const read = await Promise.all(Array.from(files).slice(0, 4 - photos.length).map(readFile))
    onChange([...photos, ...read])
    if (input.current) input.current.value = ''
  }
  return (
    <div className="lr-photos">
      <div className="lr-photos-head">
        <span className="form-label">{label}{required ? ' *' : ''}</span>
        <button type="button" className="secondary-button small" onClick={() => input.current?.click()} disabled={photos.length >= 4}>
          Add photo
        </button>
        <input ref={input} type="file" accept="image/*" multiple hidden onChange={(e) => add(e.target.files)} />
      </div>
      <span className="lr-hint">{hint}</span>
      {photos.length > 0 && (
        <div className="lr-thumbs">
          {photos.map((p, i) => (
            <figure key={`${p.name}-${i}`}>
              <img src={p.data} alt={p.name} />
              <figcaption title={p.name}>{p.name}</figcaption>
              <button type="button" aria-label={`Remove ${p.name}`} onClick={() => onChange(photos.filter((_, j) => j !== i))}>×</button>
            </figure>
          ))}
        </div>
      )}
    </div>
  )
}

function LinesEditor({ lines, onChange, label }: { lines: Line[]; onChange: (l: Line[]) => void; label: string }) {
  return (
    <div className="lr-lines">
      <span className="form-label">{label}</span>
      {lines.map((l, i) => (
        <div key={i} className="lr-line">
          <input className="form-input" value={l.sku} placeholder="SKU" onChange={(e) => onChange(lines.map((x, j) => (j === i ? { ...x, sku: e.target.value } : x)))} />
          <input className="form-input lr-qty" type="number" min={1} value={l.qty} onChange={(e) => onChange(lines.map((x, j) => (j === i ? { ...x, qty: Number(e.target.value) } : x)))} />
          <button type="button" className="secondary-button small" onClick={() => onChange(lines.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <button type="button" className="secondary-button small" onClick={() => onChange([...lines, { sku: '', qty: 1 }])}>Add line</button>
    </div>
  )
}

function Section({ n, title, who, children, note }: { n: number; title: string; who: string; children: ReactNode; note?: string }) {
  return (
    <section className="lr-section">
      <header>
        <span className="lr-n">{String(n).padStart(2, '0')}</span>
        <div>
          <h3>{title}</h3>
          <p>{who}</p>
        </div>
      </header>
      {note && <p className="lr-note">{note}</p>}
      <div className="lr-grid">{children}</div>
    </section>
  )
}

function stageState(stage: Stage, run: RunView | null): { state: string; sr?: StageResult } {
  const sr = run?.workflow?.stage_results.find((s) => s.stage === stage)
  if (run && run.running_stage === stage && (!sr || sr.state === 'pending' || sr.state === 'error') && run.status.state !== 'done') return { state: 'running', sr }
  // A halted workflow leaves its later stages pending: once the run is over they are stopped, not waiting.
  if (sr?.state === 'pending' && run?.workflow?.halted && run.status.state === 'done') return { state: 'halted', sr }
  if (sr?.state === 'pending' || (!sr && run)) return { state: 'waiting', sr }
  return { state: sr?.state ?? 'idle', sr }
}

function Elapsed({ from, to }: { from?: string; to?: string }) {
  const [, tick] = useState(0)
  useEffect(() => {
    if (to) return
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [to])
  if (!from) return null
  const s = Math.max(0, Math.round(((to ? Date.parse(to) : Date.now()) - Date.parse(from)) / 1000))
  return <span className="lr-elapsed">{Math.floor(s / 60)}:{String(s % 60).padStart(2, '0')}</span>
}

export default function LiveRunPage() {
  const [params, setParams] = useSearchParams()
  const [config, setConfig] = useState<Config | null>(null)
  const [form, setForm] = useState(EXAMPLE)
  const [photos, setPhotos] = useState<Record<PhotoSlot, Photo[]>>({ receiving: [], pack: [], returns: [], returns_ref: [] })
  const [errors, setErrors] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [run, setRun] = useState<RunView | null>(null)
  const [sets, setSets] = useState<DemoSet[]>([])
  const [chosen, setChosen] = useState('')
  const [loadingSet, setLoadingSet] = useState(false)
  const runId = params.get('run')
  const results = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch(`${API}/config`).then((r) => r.json()).then(setConfig).catch(() => setConfig(null))
    fetch(`${API}/sets`).then((r) => r.json()).then(setSets).catch(() => setSets([]))
  }, [])

  // A demo set only fills the form and attaches its photos (live_demo_sets/<set>/); Start runs it like anything typed in.
  const loadSet = async (name: string) => {
    const s = sets.find((x) => x.name === name)
    if (!s) return
    setLoadingSet(true)
    setErrors([])
    const sp = s.spec
    const lines = (ls?: Line[]) => (ls ?? []).map((l) => ({ sku: l.sku, qty: l.qty }))
    setForm({
      product: { ...EXAMPLE.product, ...sp.product, components: (sp.product?.components ?? []).join('; ') },
      route: sp.route,
      returned: sp.returned,
      receiving: { ...EXAMPLE.receiving, ...sp.receiving },
      prep: { ...EXAMPLE.prep, ...(sp.prep ?? {}) },
      pack: { ...EXAMPLE.pack, ...(sp.pack ?? {}), order_lines: sp.pack ? lines(sp.pack.order_lines) : EXAMPLE.pack.order_lines, observed_in_box: lines(sp.pack?.observed_in_box) },
      returns: { parts_list: (sp.returns?.parts_list ?? []).join('; ') || EXAMPLE.returns.parts_list },
      fees: (sp.fees ?? []).map((f: Partial<Fee>) => ({ quantity: 1, report_type: 'fee_report', ...f }) as Fee),
    })
    const fetched: Record<PhotoSlot, Photo[]> = { receiving: [], pack: [], returns: [], returns_ref: [] }
    try {
      for (const [stage, urls] of Object.entries(s.photos)) {
        for (const u of urls) {
          const blob = await fetch(`/api${u}`).then((r) => r.blob())
          fetched[stage as PhotoSlot].push(await readFile(new File([blob], u.split('/').pop() ?? 'photo.jpg', { type: blob.type })))
        }
      }
      setPhotos(fetched)
    } catch (e) {
      setErrors([`Could not load the set's photos: ${e}`])
    } finally {
      setLoadingSet(false)
    }
  }
  const chosenSet = sets.find((x) => x.name === chosen)

  // Poll the run until it is finished: the workflow is saved after every stage, so each agent appears as it finishes.
  useEffect(() => {
    if (!runId) return
    let stop = false
    const load = async () => {
      try {
        const r = await fetch(`${API}/runs/${runId}`)
        if (!r.ok) throw new Error(String(r.status))
        const view: RunView = await r.json()
        if (stop) return
        setRun(view)
        if (view.status.state === 'done' || view.status.state === 'error') return
      } catch {
        if (stop) return
      }
      setTimeout(load, 1000)
    }
    load()
    return () => {
      stop = true
    }
  }, [runId])

  const set = <K extends 'product' | 'receiving' | 'prep' | 'pack' | 'returns'>(section: K, patch: Partial<(typeof EXAMPLE)[K]>) =>
    setForm((f) => ({ ...f, [section]: { ...f[section], ...patch } }) as typeof EXAMPLE)

  const start = async () => {
    setErrors([])
    const body = {
      product: { ...form.product, components: split(form.product.components) },
      route: form.route,
      returned: form.returned,
      receiving: form.receiving,
      prep: form.route === 'fba' ? form.prep : null,
      pack: form.route === 'mfn' ? { ...form.pack, order_lines: form.pack.order_lines.filter((l) => l.sku.trim()), observed_in_box: form.pack.observed_in_box.filter((l) => l.sku.trim()) } : null,
      returns: form.returned ? { parts_list: split(form.returns.parts_list) } : null,
      fees: form.fees,
      photos: Object.fromEntries(Object.entries(photos).filter(([slot, list]) => list.length && (slot !== 'pack' || form.route === 'mfn') && (!slot.startsWith('returns') || form.returned))),
    }
    setSubmitting(true)
    try {
      const r = await fetch(`${API}/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const data = await r.json()
      if (!r.ok) {
        const detail = data.detail
        setErrors(Array.isArray(detail) ? detail.map((d: { loc?: (string | number)[]; msg: string }) => `${(d.loc ?? []).slice(1).join(' › ') || 'form'}: ${d.msg.replace(/^Value error, /, '')}`) : [String(detail)])
        return
      }
      setRun(null)
      setParams({ run: data.run_id })
      setTimeout(() => results.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150)
    } catch (e) {
      setErrors([`Could not reach the API: ${e}`])
    } finally {
      setSubmitting(false)
    }
  }

  const bundle: EvidenceBundle | null = useMemo(() => (run?.workflow ? { workflow: run.workflow, evidence: run.evidence } as EvidenceBundle : null), [run])
  const stageOfRecord = useMemo(() => Object.fromEntries(Object.values(run?.evidence ?? {}).map((r) => [r.record_id, r.stage])), [run])
  const busy = run && run.status.state !== 'done' && run.status.state !== 'error'
  const fo = run?.workflow?.final_outcome
  const ai = run?.spec.ai ?? {}
  const keys = config?.keys

  return (
    <div className="page-shell lr">
      <div className="page-header">
        <div>
          <div className="eyebrow">Live demo · local</div>
          <h1>Live Run</h1>
        </div>
        <div className="page-subtitle">Enter one product and its photos, press Start, and watch the five agents process it step by step.</div>
      </div>

      <div className="lr-ai">
        <span>AI on photos:</span>
        <b>Receiving</b> Gemini (if you add receiving photos) · <b>Pack</b> Groq vision · <b>Returns</b> Gemini, against the reference photo it takes from Pack.
        {keys && (
          <span className="lr-keys">
            {keys.gemini} Gemini key{keys.gemini === 1 ? '' : 's'} · {keys.groq} Groq key{keys.groq === 1 ? '' : 's'} (switched automatically when one hits its limit)
          </span>
        )}
      </div>

      {sets.length > 0 && (
        <div className="lr-sets">
          <span className="form-label">Ready-made demo sets</span>
          <select className="form-select" value={chosen} onChange={(e) => setChosen(e.target.value)}>
            <option value="">Choose a product…</option>
            {sets.map((s) => <option key={s.name} value={s.name}>{s.title}</option>)}
          </select>
          <button type="button" className="secondary-button small" disabled={!chosen || loadingSet} onClick={() => loadSet(chosen)}>
            {loadingSet ? 'Loading…' : 'Load into the form'}
          </button>
          {chosenSet && <p>{chosenSet.story}</p>}
        </div>
      )}

      <div className="lr-form">
        <Section n={1} title="Product" who="Who the unit is, and how it is fulfilled">
          <Field label="Product name"><input className="form-input" value={form.product.title} onChange={(e) => set('product', { title: e.target.value })} /></Field>
          <Field label="SKU"><input className="form-input" value={form.product.sku} onChange={(e) => set('product', { sku: e.target.value })} /></Field>
          <Field label="ASIN"><input className="form-input" value={form.product.asin} onChange={(e) => set('product', { asin: e.target.value })} /></Field>
          <Field label="Category (Returns grading rubric)"><Select value={form.product.category} options={config?.categories ?? ['electronics']} onChange={(v) => set('product', { category: v })} /></Field>
          <Field label="Colour"><input className="form-input" value={form.product.colour} onChange={(e) => set('product', { colour: e.target.value })} /></Field>
          <Field label="Variant"><input className="form-input" value={form.product.variant} onChange={(e) => set('product', { variant: e.target.value })} /></Field>
          <Field label="Components (what should be in the box)" hint="Separate with ; or ,"><input className="form-input" value={form.product.components} onChange={(e) => set('product', { components: e.target.value })} /></Field>
          <Field label="Fulfilment route" hint="FBA: Amazon ships it (Prep checks Amazon's rules). MFN: we ship it (Pack checks the box).">
            <Select value={form.route} options={['mfn', 'fba']} onChange={(v) => setForm((f) => ({ ...f, route: v as 'mfn' | 'fba' }))} />
          </Field>
          <Field label="Did the customer return it?">
            <Select value={form.returned ? 'yes' : 'no'} options={['yes', 'no']} onChange={(v) => setForm((f) => ({ ...f, returned: v === 'yes' }))} />
          </Field>
        </Section>

        <Section n={2} title="Receiving" who={`${AGENTS.receiving.name} · ${AGENTS.receiving.owner}`} note="The purchase order, and what the operator counted. With receiving photos, Gemini also looks at them; without, the agent judges the counts typed here.">
          <Field label="Supplier"><input className="form-input" value={form.receiving.supplier} onChange={(e) => set('receiving', { supplier: e.target.value })} /></Field>
          <Field label="PO number"><input className="form-input" value={form.receiving.po_number} onChange={(e) => set('receiving', { po_number: e.target.value })} /></Field>
          <Field label="Cartons ordered"><Num value={form.receiving.cartons_ordered} onChange={(v) => set('receiving', { cartons_ordered: v })} /></Field>
          <Field label="Cartons received"><Num value={form.receiving.cartons_received} onChange={(v) => set('receiving', { cartons_received: v })} /></Field>
          <Field label="Units per carton (ordered)"><Num min={1} value={form.receiving.units_per_carton_ordered} onChange={(v) => set('receiving', { units_per_carton_ordered: v })} /></Field>
          <Field label="Units per carton (counted)"><Num value={form.receiving.units_per_carton_counted} onChange={(v) => set('receiving', { units_per_carton_counted: v })} /></Field>
          <Field label="Quantity ordered"><Num value={form.receiving.qty_ordered} onChange={(v) => set('receiving', { qty_ordered: v })} /></Field>
          <Field label="Quantity received"><Num value={form.receiving.qty_received} onChange={(v) => set('receiving', { qty_received: v })} /></Field>
          <Field label="Right product received?"><Select value={form.receiving.identity_match} options={['yes', 'no', 'uncertain']} onChange={(v) => set('receiving', { identity_match: v })} /></Field>
          <Field label="Carton damage"><Select value={form.receiving.carton_damage} options={config?.damage ?? ['none']} onChange={(v) => set('receiving', { carton_damage: v })} /></Field>
          <Field label="Unit damage"><Select value={form.receiving.unit_damage} options={config?.damage ?? ['none']} onChange={(v) => set('receiving', { unit_damage: v })} /></Field>
          <div className="form-group lr-field">
            <span className="form-label">Quality flags</span>
            <div className="lr-checks">
              {(config?.quality_flags ?? []).map((q) => (
                <label key={q}>
                  <input type="checkbox" checked={form.receiving.quality_flags.includes(q)} onChange={(e) => set('receiving', { quality_flags: e.target.checked ? [...form.receiving.quality_flags, q] : form.receiving.quality_flags.filter((x) => x !== q) })} />
                  {human(q)}
                </label>
              ))}
            </div>
          </div>
          <div className="lr-wide">
            <PhotoPicker label="Receiving photos (optional)" hint="Pallet, carton, unit. Gemini compares them with the purchase order." photos={photos.receiving} onChange={(p) => setPhotos((s) => ({ ...s, receiving: p }))} />
          </div>
        </Section>

        {form.route === 'fba' ? (
          <Section n={3} title="Prep (FBA)" who={`${AGENTS.prep.name} · ${AGENTS.prep.owner}`} note="What the work order requires, and what the prep operator observed. Prep has no vision: it applies Amazon's prep rules to these observations.">
            <Field label="FNSKU"><input className="form-input" value={form.prep.fnsku} onChange={(e) => set('prep', { fnsku: e.target.value })} /></Field>
            <Field label="Prep price (USD)"><Num step={0.01} value={form.prep.prep_price_usd} onChange={(v) => set('prep', { prep_price_usd: v })} /></Field>
            <Field label="Work order: polybag required?"><Select value={String(form.prep.wo_polybag)} options={['true', 'false']} onChange={(v) => set('prep', { wo_polybag: v === 'true' })} /></Field>
            <Field label="Work order: suffocation warning required?"><Select value={String(form.prep.wo_suffocation_warning)} options={['true', 'false']} onChange={(v) => set('prep', { wo_suffocation_warning: v === 'true' })} /></Field>
            <Field label="Work order: expiry date required?"><Select value={String(form.prep.wo_expiry_date)} options={['false', 'true']} onChange={(v) => set('prep', { wo_expiry_date: v === 'true' })} /></Field>
            <div className="form-group lr-field">
              <span className="form-label">Work order: handling marks</span>
              <div className="lr-checks">
                {['fragile', 'this_way_up', 'liquid'].map((m) => (
                  <label key={m}>
                    <input type="checkbox" checked={form.prep.wo_handling_marks.includes(m)} onChange={(e) => set('prep', { wo_handling_marks: e.target.checked ? [...form.prep.wo_handling_marks, m] : form.prep.wo_handling_marks.filter((x) => x !== m) })} />
                    {human(m)}
                  </label>
                ))}
              </div>
            </div>
            {Object.entries(config?.prep_observed ?? {}).map(([k, opts]) => (
              <Field key={k} label={`Observed: ${human(k)}`}>
                <Select value={(form.prep as Record<string, unknown>)[k] as string} options={opts} onChange={(v) => set('prep', { [k]: v } as Partial<typeof EXAMPLE.prep>)} />
              </Field>
            ))}
          </Section>
        ) : (
          <Section n={3} title="Pack (merchant-fulfilled)" who={`${AGENTS.pack.name} · ${AGENTS.pack.owner}`} note="The customer's order and a photo of the open box. Groq's vision model checks the photo; without a photo the agent checks the box contents typed below.">
            <Field label="Sales channel"><Select value={form.pack.channel} options={config?.channels ?? ['shopify']} onChange={(v) => set('pack', { channel: v })} /></Field>
            <Field label="Operator's decision"><Select value={form.pack.operator_verdict} options={['seal', 'stop_and_fix']} onChange={(v) => set('pack', { operator_verdict: v })} /></Field>
            <div className="lr-wide"><LinesEditor label="Order lines (what the customer ordered)" lines={form.pack.order_lines} onChange={(l) => set('pack', { order_lines: l })} /></div>
            <div className="lr-wide"><LinesEditor label="Seen in the box (only used without a photo; empty = same as the order)" lines={form.pack.observed_in_box} onChange={(l) => set('pack', { observed_in_box: l })} /></div>
            <div className="lr-wide">
              <PhotoPicker label="Open-box photo" hint="The product as packed. Pack checks it, and Returns later uses it as its reference photo." photos={photos.pack} onChange={(p) => setPhotos((s) => ({ ...s, pack: p }))} />
            </div>
          </Section>
        )}

        {form.returned && (
          <Section n={4} title="Returns" who={`${AGENTS.returns.name} · ${AGENTS.returns.owner}`} note="Photos of the item that came back. Gemini compares them with the reference photo Returns takes from Pack (or Receiving).">
            <Field label="Parts that should come back" hint="Separate with ; or ,"><input className="form-input" value={form.returns.parts_list} onChange={(e) => set('returns', { parts_list: e.target.value })} /></Field>
            <div className="lr-wide">
              <PhotoPicker required label="Returned item photos" hint="1 to 4 photos of what the customer sent back." photos={photos.returns} onChange={(p) => setPhotos((s) => ({ ...s, returns: p }))} />
            </div>
            <div className="lr-wide">
              <PhotoPicker label="Reference photo (only if Pack and Receiving have none)" hint="Normally the reference comes from Pack's or Receiving's record; this is the fallback." photos={photos.returns_ref} onChange={(p) => setPhotos((s) => ({ ...s, returns_ref: p }))} />
            </div>
          </Section>
        )}

        <Section n={form.returned ? 5 : 4} title="Recovery: Amazon fee lines" who={`${AGENTS.recovery.name} · ${AGENTS.recovery.owner}`} note="The fees Amazon charged for this unit. Recovery checks each one against the earlier agents' records. With no fee lines, Recovery has nothing to audit and is skipped.">
          <div className="lr-wide lr-fees">
            {form.fees.map((f, i) => (
              <div key={i} className="lr-line">
                <select className="form-select" value={f.charge_type} onChange={(e) => setForm((s) => ({ ...s, fees: s.fees.map((x, j) => (j === i ? { ...x, charge_type: e.target.value } : x)) }))}>
                  {(config?.charge_types ?? []).map((c) => <option key={c} value={c}>{human(c)}</option>)}
                </select>
                <input className="form-input lr-qty" type="number" min={0} step={0.01} value={f.amount_usd} title="Amount (USD)" onChange={(e) => setForm((s) => ({ ...s, fees: s.fees.map((x, j) => (j === i ? { ...x, amount_usd: Number(e.target.value) } : x)) }))} />
                <span className="lr-hint">USD</span>
                <button type="button" className="secondary-button small" onClick={() => setForm((s) => ({ ...s, fees: s.fees.filter((_, j) => j !== i) }))}>Remove</button>
              </div>
            ))}
            <button type="button" className="secondary-button small" onClick={() => setForm((s) => ({ ...s, fees: [...s.fees, { charge_type: 'inbound_defect_fee', amount_usd: 1, quantity: 1, report_type: 'fee_report' }] }))}>Add fee line</button>
          </div>
        </Section>

        {errors.length > 0 && (
          <div className="lr-errors" role="alert">
            <b>Fix these before starting:</b>
            <ul>{errors.map((e) => <li key={e}>{e}</li>)}</ul>
          </div>
        )}
        <div className="lr-start">
          <button type="button" className="primary-button" onClick={start} disabled={submitting || !!busy}>
            {submitting ? 'Sending…' : busy ? 'Running…' : 'Start processing'}
          </button>
          <button type="button" className="secondary-button small" onClick={() => { setForm(EXAMPLE); setPhotos({ receiving: [], pack: [], returns: [], returns_ref: [] }); setErrors([]) }}>
            Reset to the example
          </button>
          <span className="lr-hint">The run uses the real agents and real model calls. Receiving and Pack take seconds; Returns' Gemini judgment usually takes about a minute.</span>
        </div>
      </div>

      <div ref={results}>
        {runId && (
          <section className="lr-run">
            <header className="lr-run-head">
              <div>
                <div className="eyebrow">Run {runId}</div>
                <h2>{run?.spec.product?.title ?? 'Starting…'}</h2>
              </div>
              <div className="lr-run-state">
                <span className={`lr-state ${run?.status.state ?? 'starting'}`}>{run?.status.state ?? 'starting'}</span>
                <Elapsed from={run?.status.started_at} to={run?.status.finished_at} />
              </div>
            </header>

            <ol className="lr-timeline">
              {STAGES.map((stage, i) => {
                const { state, sr } = stageState(stage, run)
                const usesAi = (stage === 'receiving' && ai.receiving) || (stage === 'pack' && ai.pack) || (stage === 'returns' && ai.returns)
                return (
                  <li key={stage} className={`lr-step ${state}`}>
                    <div className="lr-dot">{state === 'completed' ? '✓' : state === 'error' ? '!' : state === 'skipped' ? '–' : i + 1}</div>
                    <div className="lr-step-body">
                      <strong>{AGENTS[stage].name}</strong>
                      <span className="lr-step-sub">
                        {state === 'running'
                          ? usesAi
                            ? stage === 'returns' ? 'Gemini is comparing the returned item with the reference photo (about a minute)…' : 'looking at the photos with AI…'
                            : 'processing…'
                          : state === 'skipped' ? sr?.skipped_reason : state === 'halted' ? 'not run: stopped for a person (see below)' : state === 'waiting' ? 'waiting for earlier agents' : state === 'idle' ? AGENTS[stage].owner : ''}
                      </span>
                      {sr?.verdict && state !== 'running' && (
                        <span className="lr-step-verdict">
                          <span className={`se-badge ${tone(sr.verdict)}`}>{sr.verdict}</span> {sr.outcome && human(sr.outcome)}
                          {sr.duration_ms != null && <em>{(sr.duration_ms / 1000).toFixed(1)} s</em>}
                        </span>
                      )}
                    </div>
                  </li>
                )
              })}
            </ol>

            {run?.workflow?.halted && run.status.state === 'done' && (
              <div className="lr-halt">
                <b>Stopped before {AGENTS[run.workflow.halted.stage as Stage]?.name ?? run.workflow.halted.stage}.</b> {run.workflow.halted.reason}.
              </div>
            )}
            {(run?.status.notes ?? []).length > 0 && (
              <div className="lr-notes">
                {run!.status.notes!.map((n) => <p key={n.at + n.text}><b>{n.at}</b> {n.text}</p>)}
              </div>
            )}
            {run?.status.state === 'error' && (
              <div className="lr-errors"><b>The run stopped:</b> {run.status.error}<pre>{run.log_tail}</pre></div>
            )}

            {run?.workflow && (
              <div className="lr-results">
                <h3>What each agent did, and why</h3>
                {STAGES.map((stage) => {
                  const sr = run.workflow!.stage_results.find((s) => s.stage === stage)
                  if (!sr || sr.state === 'pending') return null
                  if (sr.state === 'skipped')
                    return (
                      <div key={stage} className="lr-skipped">
                        <b>{AGENTS[stage].name}</b> skipped: {sr.skipped_reason}
                      </div>
                    )
                  const rec = sr.record_id ? run.evidence[sr.record_id] : undefined
                  const shots = run.photos[stage] ?? []
                  const fromStages = (rec?.upstream_refs ?? []).map((id) => `${AGENTS[stageOfRecord[id] as Stage]?.name ?? id} (${id})`)
                  return (
                    <article key={stage} className="lr-agent">
                      <div className="lr-agent-head">
                        <div>
                          <strong>{AGENTS[stage].name}</strong> <span className="lr-hint">· {AGENTS[stage].owner}</span>
                          <p>{AGENTS[stage].does}</p>
                        </div>
                      </div>
                      <div className="lr-io">
                        <div>
                          <span className="lr-io-label">Its own input</span>
                          {shots.length ? (
                            <div className="lr-thumbs small">
                              {shots.map((u) => (
                                <a key={u} href={`/api${u}`} target="_blank" rel="noreferrer"><img src={`/api${u}`} alt={`${stage} photo`} /></a>
                              ))}
                            </div>
                          ) : (
                            <span className="lr-hint">the typed {stage === 'recovery' ? 'fee lines' : 'fields'} (no photo)</span>
                          )}
                        </div>
                        <div>
                          <span className="lr-io-label">Taken from earlier agents</span>
                          {fromStages.length ? <ul>{fromStages.map((s) => <li key={s}>{s}</li>)}</ul> : <span className="lr-hint">nothing: it is the first agent</span>}
                          {stage === 'returns' && rec?.payload?.reference_source && (
                            <span className="lr-ref">Reference photo from: <b>{String(rec.payload.reference_source)}</b></span>
                          )}
                        </div>
                      </div>
                      <StageEvidence stage={stage} result={sr} bundle={bundle} />
                      {rec?.model && (
                        <p className="lr-model">
                          Model: <b>{rec.model.name}</b> · {rec.model.calls ?? 0} call{rec.model.calls === 1 ? '' : 's'}
                          {(rec as { latency_ms?: number | null }).latency_ms != null && <> · {(((rec as { latency_ms?: number }).latency_ms ?? 0) / 1000).toFixed(1)} s</>}
                        </p>
                      )}
                    </article>
                  )
                })}

                {fo && run.status.state === 'done' && (
                  <article className={`lr-final ${fo.outcome === 'CLAIM_RECOMMENDED' ? 'claim' : tone(fo.verdict)}`}>
                    <div className="eyebrow">Final outcome (orchestrator)</div>
                    <h3>{human(fo.outcome)}</h3>
                    <p>{fo.reason}</p>
                    <dl>
                      <div><dt>Workflow status</dt><dd>{run.workflow.status}</dd></div>
                      <div><dt>Needs a person</dt><dd>{fo.needs_human ? 'yes' : 'no'}</dd></div>
                      <div><dt>Claimable</dt><dd>{fo.claimable_usd != null ? `$${Number(fo.claimable_usd).toFixed(2)}` : '—'}</dd></div>
                      <div><dt>Verdicts used</dt><dd>{Object.entries(fo.effective_verdicts ?? {}).map(([s, v]) => `${s}: ${v}`).join(' · ')}</dd></div>
                      <div><dt>Built from</dt><dd className="se-mono">{(fo.contributing_records ?? []).join(', ')}</dd></div>
                    </dl>
                  </article>
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
