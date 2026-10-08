// Human-readable view of each agent's Evidence Record: checks, the agent-specific payload fields, and what
// produced it. Everything is read from the stored record; nothing is inferred or filled in.
import type { EvidenceBundle, EvidenceRecord, StageResult } from '../services/api'
import './StageEvidence.css'

const show = (v: unknown): string => {
  if (v === null || v === undefined || v === '') return '—'
  if (Array.isArray(v)) return v.length ? v.map(show).join(', ') : 'none'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

const tone = (verdict?: string) =>
  verdict === 'PASS' ? 'ok' : verdict === 'FAIL' ? 'bad' : verdict === 'UNCERTAIN' ? 'unsure' : 'none'

function Facts({ rows }: { rows: Array<[string, unknown]> }) {
  const shown = rows.filter(([, v]) => v !== undefined)
  if (!shown.length) return null
  return (
    <dl className="se-facts">
      {shown.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{show(v)}</dd>
        </div>
      ))}
    </dl>
  )
}

function AgentFacts({ rec }: { rec: EvidenceRecord }) {
  const p = rec.payload ?? {}
  switch (rec.stage) {
    case 'receiving':
      return <Facts rows={[['Supplier', p.supplier], ['Ordered', p.qty_ordered], ['Received', p.qty_received], ['Shortfall (units)', p.shortfall_units], ['Quality flags', p.quality_flags]]} />
    case 'prep':
      return <Facts rows={[['Prep price (USD)', p.prep_price_usd], ['Measurements', p.measurements ?? 'not recorded'], ['Rule source', p.rule_source]]} />
    case 'pack':
      return (
        <Facts
          rows={[
            ['Channel', p.channel],
            ['Order lines', Array.isArray(p.order_lines) ? p.order_lines.map((l: any) => `${l.sku} ×${l.quantity ?? l.qty ?? 1}`) : p.order_lines],
            ['Seen in box', Array.isArray(p.observed_in_box) ? p.observed_in_box.map((o: any) => (typeof o === 'string' ? o : `${o.sku} ×${o.quantity}`)) : p.observed_in_box],
            ['Operator said', p.operator_verdict],
            ['Agent agrees with operator', p.agent_agrees_with_operator],
          ]}
        />
      )
    case 'returns': {
      // What Returns did with the records handed to it (payload.upstream_reconciliation).
      const recon = p.upstream_reconciliation ?? {}
      const pack = recon.pack
      const rcv = recon.receiving
      return (
        <>
          <Facts
            rows={[
              ['Disposition (rules engine)', p.recommended_disposition],
              ['Amazon condition', p.amazon_condition],
              ['Observed state', p.observed_state],
              ['Parts missing', p.parts_missing],
              ['Needs review because', p.review_reasons],
              ['Rule', p.rule_id],
              ['Reference photo from', p.reference_source],
              ['Model mode', p.model_mode],
            ]}
          />
          {(pack || rcv) && (
            <div className="se-crosscheck">
              <div className="se-sub">Cross-check with earlier stages</div>
              <Facts
                rows={[
                  ...(pack
                    ? ([[`Pack ${pack.record_id} (${pack.effective_verdict})`, pack.shipped_skus?.length ? `saw ${show(pack.shipped_skus)} in the box` : 'did not record what was in the box']] as Array<[string, unknown]>)
                    : []),
                  ...(rcv
                    ? ([[`Receiving ${rcv.record_id} (${rcv.effective_verdict})`, rcv.received_sku ? `received ${rcv.received_sku}` : 'no SKU recorded']] as Array<[string, unknown]>)
                    : []),
                  ['SKU consistent with the order', recon.sku_consistent_with_order === false ? 'NO' : 'yes'],
                  ['Upstream photo used as reference', pack?.used_as_reference ? `yes (${pack.record_id})` : rcv?.used_as_reference ? `yes (${rcv.record_id})` : 'no'],
                ]}
              />
              {(recon.notes ?? []).map((n: string) => (
                <p key={n} className="se-note se-warn">{n}</p>
              ))}
            </div>
          )}
        </>
      )
    }
    case 'recovery':
      return (
        <>
          <Facts rows={[['Claimable (USD)', p.claimable_usd], ['Model fallback', p.model_fallback]]} />
          {Array.isArray(p.charges) && p.charges.length > 0 && (
            <table className="se-table">
              <thead>
                <tr>
                  <th>Fee line</th>
                  <th>Charge</th>
                  <th>Amount</th>
                  <th>Position</th>
                  <th>Cites</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {p.charges.map((c: any) => (
                  <tr key={c.line_id}>
                    <td className="se-mono">{c.line_id}</td>
                    <td>{show(c.charge_type).replace(/_/g, ' ')}</td>
                    <td>${Number(c.amount_usd).toFixed(2)}</td>
                    <td><span className={`se-pos ${c.position}`}>{c.position}</span></td>
                    <td className="se-mono">{show(c.evidence_record_ids)}</td>
                    <td>{c.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {Array.isArray(p.charges) && p.charges.length === 0 && <p className="se-note">No fee lines were posted for this unit.</p>}
        </>
      )
    default:
      return null
  }
}

export function StageEvidence({ stage, result, bundle }: { stage: string; result?: StageResult; bundle: EvidenceBundle | null }) {
  if (!result || result.state === 'skipped') return null
  const rec = result.record_id ? bundle?.evidence[result.record_id] : undefined
  if (!rec) return <div className="se-card se-loading">{stage}: loading {result.record_id ?? 'record'}…</div>
  return (
    <section className={`se-card ${tone(rec.decision?.verdict)}`} data-stage={stage} data-record={rec.record_id}>
      <header>
        <div>
          <strong className="se-stage">{stage}</strong>
          <span className="se-mono">{rec.record_id}</span>
        </div>
        <div className="se-verdict">
          <span className={`se-badge ${tone(rec.decision?.verdict)}`}>{rec.decision?.verdict ?? 'no verdict'}</span>
          <span>{rec.decision?.outcome}</span>
          {rec.decision?.needs_human && <span className="se-badge unsure">needs a person</span>}
        </div>
      </header>
      {rec.decision?.reason && <p className="se-reason">{rec.decision.reason}</p>}
      {rec.status !== 'completed' && (
        <p className="se-error">
          Stage did not complete ({rec.status}): {show((rec as any).error?.code)} — {show((rec as any).error?.message)}
        </p>
      )}
      {(rec.checks ?? []).length > 0 && (
        <table className="se-table">
          <thead>
            <tr>
              <th>Check</th>
              <th>Verdict</th>
              <th>Confidence</th>
              <th>Why / detail</th>
            </tr>
          </thead>
          <tbody>
            {(rec.checks ?? []).map((c) => (
              <tr key={c.check_key}>
                <td className="se-mono">{c.check_key}</td>
                <td><span className={`se-badge ${tone(c.verdict)}`}>{c.verdict}</span></td>
                <td>{c.confidence ?? '—'}</td>
                <td>{c.uncertain_reason ? `${c.uncertain_reason}: ` : ''}{c.detail || show(c.observed)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <AgentFacts rec={rec} />
      <footer>
        <span>
          Produced by <b>{rec.agent_id}</b> · model <b>{rec.model?.name ?? '—'}</b> ({rec.model?.calls ?? 0} calls)
        </span>
        <span>Used upstream: {show(rec.upstream_refs)}</span>
      </footer>
    </section>
  )
}
