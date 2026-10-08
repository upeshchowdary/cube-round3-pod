import { useEffect, useRef, useState } from 'react'
import { agents, flowSteps } from './content'

/** Index of the block whose centre is nearest the viewport's reading line. */
function useActiveIndex(count: number) {
  const refs = useRef<Array<HTMLElement | null>>([])
  const [active, setActive] = useState(0)
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.index))
        })
      },
      { rootMargin: '-45% 0px -45% 0px' },
    )
    refs.current.slice(0, count).forEach((el) => el && io.observe(el))
    return () => io.disconnect()
  }, [count])
  return { refs, active }
}

/** Sticky image stage on the right; agent blocks scroll past on the left; the active image cross-fades in. */
export function AgentShowcase() {
  const { refs, active } = useActiveIndex(agents.length)
  return (
    <section className="cv-showcase" id="agents">
      <div className="cv-showcase-text">
        {agents.map((a, i) => (
          <article
            key={a.slug}
            ref={(el) => {
              refs.current[i] = el
            }}
            data-index={i}
            className={`cv-agent ${active === i ? 'on' : ''}`}
          >
            <div className="cv-agent-meta">
              <span className="cv-index">{a.index}</span>
              <span className="cv-eyebrow">{a.when}</span>
            </div>
            <h3>{a.name}</h3>
            <p>{a.summary}</p>
            <ul className="cv-checks">
              {a.checks.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
            <div className="cv-agent-foot">
              <span>Hands on → {a.handsOn}</span>
              <span className="cv-owner">{a.owner}</span>
            </div>
            <figure className="cv-agent-mobile-img">
              <img src={a.image} alt={`${a.name} illustration`} loading="lazy" />
            </figure>
          </article>
        ))}
      </div>
      <div className="cv-showcase-stage">
        <div className="cv-sticky">
          <div className="cv-frame">
            {agents.map((a, i) => (
              <figure key={a.slug} className={`cv-frame-img ${active === i ? 'on' : ''}`} aria-hidden={active !== i}>
                <img src={a.image} alt={`${a.name} illustration`} loading="lazy" />
                <figcaption>
                  <strong>{a.name}:</strong> {a.caption}
                </figcaption>
              </figure>
            ))}
            <div className="cv-progress" aria-hidden="true">
              {agents.map((a, i) => (
                <span key={a.slug} className={i <= active ? 'on' : ''} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function RouteDiagram() {
  const stages = ['Receiving', 'Prep', 'Pack', 'Returns', 'Recovery']
  return (
    <svg viewBox="0 0 420 260" className="cv-diagram">
      <path className="cv-d-track" d="M40 130 H120" />
      <path className="cv-d-flow cv-d-fba" d="M120 130 C150 130 150 70 190 70 H250 C290 70 290 130 320 130" />
      <path className="cv-d-flow cv-d-mfn" d="M120 130 C150 130 150 190 190 190 H250 C290 190 290 130 320 130" />
      <path className="cv-d-track" d="M320 130 H380" />
      {[
        [40, 130, stages[0]],
        [220, 70, stages[1]],
        [220, 190, stages[2]],
        [320, 130, stages[3]],
        [380, 130, stages[4]],
      ].map(([x, y, label]) => (
        <g key={label as string} transform={`translate(${x} ${y})`}>
          <circle r="15" className="cv-d-node" />
          <text y="34" textAnchor="middle" className="cv-d-label">{label}</text>
        </g>
      ))}
      <text x="220" y="40" textAnchor="middle" className="cv-d-hint">FBA</text>
      <text x="220" y="236" textAnchor="middle" className="cv-d-hint">MFN</text>
    </svg>
  )
}

function HandoffDiagram() {
  const recs = ['RCV', 'PRP', 'RTN', 'RCY']
  return (
    <svg viewBox="0 0 420 260" className="cv-diagram">
      <rect x="150" y="96" width="120" height="68" rx="16" className="cv-d-core" />
      <text x="210" y="126" textAnchor="middle" className="cv-d-core-t">Orchestrator</text>
      <text x="210" y="145" textAnchor="middle" className="cv-d-mono">validate · store · pass on</text>
      {recs.map((r, i) => {
        const x = 40 + i * 113
        const y = i % 2 ? 222 : 38
        return (
          <g key={r}>
            <path className="cv-d-flow" d={`M${x + 32} ${y + (i % 2 ? -14 : 14)} L210 ${i % 2 ? 164 : 96}`} style={{ animationDelay: `${i * 0.35}s` }} />
            <rect x={x} y={y - 14} width="64" height="28" rx="8" className="cv-d-rec" />
            <text x={x + 32} y={y + 4} textAnchor="middle" className="cv-d-mono">{r}</text>
          </g>
        )
      })}
    </svg>
  )
}

function DecideDiagram() {
  const outcomes = ['CLEAN', 'CLAIM_RECOMMENDED', 'EXCEPTION', 'NEEDS_REVIEW', 'INCOMPLETE']
  return (
    <svg viewBox="0 0 420 260" className="cv-diagram">
      {Array.from({ length: 8 }, (_, i) => {
        const a = (i / 8) * Math.PI * 2
        return <line key={i} x1="110" y1="130" x2={110 + Math.cos(a) * 70} y2={130 + Math.sin(a) * 70} className="cv-d-ray" style={{ animationDelay: `${i * 0.12}s` }} />
      })}
      <circle cx="110" cy="130" r="26" className="cv-d-node big" />
      <text x="110" y="135" textAnchor="middle" className="cv-d-core-t">sha256</text>
      {outcomes.map((o, i) => (
        <g key={o} transform={`translate(230 ${46 + i * 42})`}>
          <rect width="160" height="28" rx="14" className={`cv-d-out ${i === 1 ? 'pick' : ''}`} />
          <text x="80" y="18" textAnchor="middle" className="cv-d-mono">{o}</text>
        </g>
      ))}
    </svg>
  )
}

/** "How it works": numbered timeline on the left, a sticky diagram card on the right that follows the active step. */
export function FlowSteps() {
  const { refs, active } = useActiveIndex(flowSteps.length)
  const diagrams = [<RouteDiagram key="r" />, <HandoffDiagram key="h" />, <DecideDiagram key="d" />]
  return (
    <section className="cv-flow" id="how">
      <div className="cv-flow-steps">
        {flowSteps.map((s, i) => (
          <div
            key={s.index}
            ref={(el) => {
              refs.current[i] = el
            }}
            data-index={i}
            className={`cv-step ${active === i ? 'on' : ''}`}
          >
            <span className="cv-step-num">{s.index}</span>
            <span className="cv-chip">{s.tag}</span>
            <h3>{s.title}</h3>
            <p>{s.detail}</p>
          </div>
        ))}
      </div>
      <div className="cv-flow-stage">
        <div className="cv-sticky">
          <div className="cv-diagram-card">
            <span className="cv-chip solid">
              Step {flowSteps[active].index} · {flowSteps[active].tag}
            </span>
            {diagrams.map((d, i) => (
              <div key={i} className={`cv-diagram-slot ${active === i ? 'on' : ''}`}>
                {d}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
