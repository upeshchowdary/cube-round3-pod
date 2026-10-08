import '@fontsource-variable/bricolage-grotesque'
import '@fontsource-variable/figtree'
import '@fontsource-variable/jetbrains-mono'
import { ArrowRight, ArrowUpRight, Fingerprint, GitBranch, ShieldCheck } from 'lucide-react'
import { animate, motion, useInView, useMotionValue, useSpring } from 'motion/react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { facts, pillars, team } from './content'
import { IconWave, LineFan, Typewriter, useLenis, WordCycle } from './effects'
import MorphField from './MorphField'
import { AgentShowcase, FlowSteps } from './Showcase'
import './cover.css'

const HaloField = lazy(() => import('./HaloField'))

const rise = {
  initial: { opacity: 0, y: 28 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, amount: 0.3 },
  transition: { duration: 0.8, ease: [0.22, 1, 0.36, 1] as const },
}

function CountUp({ value }: { value: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true, amount: 0.6 })
  const [shown, setShown] = useState('0')
  useEffect(() => {
    if (!inView) return
    const target = Number(value)
    const controls = animate(0, target, { duration: 1.4, ease: 'easeOut', onUpdate: (v) => setShown(String(Math.round(v))) })
    return () => controls.stop()
  }, [inView, value])
  return <span ref={ref}>{shown}</span>
}

/** Product frame: scales in once, and a soft green spotlight follows the cursor across it. */
function SpotlightFrame({ src, alt }: { src: string; alt: string }) {
  const mx = useMotionValue(50)
  const my = useMotionValue(50)
  const sx = useSpring(mx, { stiffness: 120, damping: 20 })
  const sy = useSpring(my, { stiffness: 120, damping: 20 })
  const [glow, setGlow] = useState('50% 50%')
  useEffect(() => {
    const update = () => setGlow(`${sx.get()}% ${sy.get()}%`)
    const a = sx.on('change', update)
    const b = sy.on('change', update)
    return () => {
      a()
      b()
    }
  }, [sx, sy])
  return (
    <motion.div
      className="cv-showpiece"
      initial={{ opacity: 0, scale: 0.92 }}
      whileInView={{ opacity: 1, scale: 1 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect()
        mx.set(((e.clientX - r.left) / r.width) * 100)
        my.set(((e.clientY - r.top) / r.height) * 100)
      }}
      style={{ ['--glow' as string]: glow }}
    >
      <div className="cv-showpiece-bar">
        <span />
        <span />
        <span />
        <em>pod-05 · orchestrator · standard-v1</em>
      </div>
      <img src={src} alt={alt} />
      <div className="cv-showpiece-glow" aria-hidden="true" />
    </motion.div>
  )
}

export default function CoverPage() {
  useLenis()
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 24)
    on()
    window.addEventListener('scroll', on, { passive: true })
    return () => window.removeEventListener('scroll', on)
  }, [])

  return (
    <div className="cv">
      <header className={`cv-nav ${scrolled ? 'scrolled' : ''}`}>
        <Link to="/" className="cv-brand" aria-label="CUBE Pod 05 home">
          <span className="cv-brand-mark" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
          cube<span>·pod05</span>
        </Link>
        <nav className="cv-links" aria-label="Sections">
          <a href="#agents">Agents</a>
          <a href="#how">How it works</a>
          <a href="#system">One system</a>
          <a href="#evidence">Evidence</a>
        </nav>
        <Link to="/overview" className="cv-btn small">
          Open control center <ArrowRight size={15} />
        </Link>
      </header>

      <section className="cv-hero">
        <Suspense fallback={<div className="cv-halo" />}>
          <HaloField />
        </Suspense>
        <div className="cv-hero-inner">
          <motion.span className="cv-pill" {...rise}>
            <span className="cv-dot" /> CUBE Buildathon · Round 3 · Pod Integration Build
          </motion.span>
          <motion.h1 className="cv-h1" {...rise} transition={{ ...rise.transition, delay: 0.08 }}>
            Five agents. One unit.
            <br />
            <span className="cv-accent">One traceable outcome.</span>
          </motion.h1>
          <motion.p className="cv-lead" {...rise} transition={{ ...rise.transition, delay: 0.16 }}>
            Pod 05 connects Receiving, Prep, Pack, Returns and Recovery into one commerce system. A unit goes in at
            supplier delivery; a final outcome comes out that you can walk back to the exact bytes each agent examined.
          </motion.p>
          <div className="cv-pillars">
            {pillars.map((p, i) => (
              <motion.div key={p.title} className="cv-pillar" {...rise} transition={{ ...rise.transition, delay: 0.24 + i * 0.08 }}>
                {[<GitBranch key="g" size={18} />, <ShieldCheck key="s" size={18} />, <Fingerprint key="f" size={18} />][i]}
                <h3>{p.title}</h3>
                <p>{p.body}</p>
              </motion.div>
            ))}
          </div>
          <motion.div className="cv-ctas" {...rise} transition={{ ...rise.transition, delay: 0.5 }}>
            <Link to="/overview" className="cv-btn">
              Open the control center <ArrowRight size={16} />
            </Link>
            <a href="#agents" className="cv-btn ghost">
              Meet the five agents
            </a>
          </motion.div>
        </div>
      </section>

      <section className="cv-section cv-center">
        <motion.span className="cv-pill soft" {...rise}>
          <span className="cv-dot live" /> Integrated end to end
        </motion.span>
        <motion.h2 className="cv-h2" {...rise}>
          From supplier dock <span className="cv-accent">to final claim.</span>
        </motion.h2>
        <motion.p className="cv-sub" {...rise}>
          One orchestrator routes every unit, hands every stage the full evidence chain, and derives the outcome.
        </motion.p>
        <SpotlightFrame src="/cover/hero-pipeline.webp" alt="Five connected warehouse stations, illustration" />
      </section>

      <section className="cv-section cv-statement">
        <Typewriter
          parts={[
            { text: 'Pod 05 is not five demos side by side. It is ' },
            { text: 'one connected, testable commerce system', accent: true },
            { text: ' — every decision traceable to its evidence.' },
          ]}
        />
        <IconWave />
      </section>

      <AgentShowcase />

      <section className="cv-section cv-center cv-how-head">
        <motion.span className="cv-pill soft" {...rise}>How it works</motion.span>
        <motion.h2 className="cv-h2" {...rise}>
          Agents judge. <span className="cv-accent">The orchestrator decides.</span>
        </motion.h2>
      </section>
      <FlowSteps />

      <section className="cv-section cv-center" id="system">
        <motion.span className="cv-pill soft" {...rise}>Round 2 → Round 3</motion.span>
        <motion.h2 className="cv-h2" {...rise}>
          From five islands <span className="cv-accent">to one Pod.</span>
        </motion.h2>
        <MorphField />
      </section>

      <section className="cv-section cv-evidence" id="evidence">
        <div className="cv-evidence-copy">
          <motion.span className="cv-pill soft" {...rise}>Evidence trail</motion.span>
          <motion.h2 className="cv-h2 left" {...rise}>
            Walk any outcome <span className="cv-accent">back to its input.</span>
          </motion.h2>
          <ol className="cv-chain">
            {['Final outcome', 'Contributing records', 'Per-check verdicts', 'Evidence refs', 'sha256 of the input'].map((s, i) => (
              <motion.li key={s} {...rise} transition={{ ...rise.transition, delay: i * 0.08 }}>
                <span className="cv-index">{String(i + 1).padStart(2, '0')}</span>
                {s}
              </motion.li>
            ))}
          </ol>
          <div className="cv-facts">
            {facts.map((f) => (
              <div key={f.label} className="cv-fact">
                <strong>
                  <CountUp value={f.value} />
                </strong>
                <span>{f.label}</span>
              </div>
            ))}
          </div>
        </div>
        <motion.figure className="cv-orb" {...rise}>
          <img src="/cover/orchestrator.webp" alt="Orchestrator connecting five agents, illustration" loading="lazy" />
        </motion.figure>
      </section>

      <footer className="cv-footer">
        <div className="cv-footer-cta">
          <h2 className="cv-h2">
            There is a lot more <span className="cv-accent">under the hood.</span>
          </h2>
          <Link to="/overview" className="cv-btn">
            Open the control center <ArrowUpRight size={16} />
          </Link>
        </div>
        <div className="cv-footer-art">
          <div className="cv-footer-words">
            <WordCycle words={['Every unit.', 'Every hand-off.', 'Every check.']} />
            <strong>Evidenced.</strong>
          </div>
          <LineFan />
          <div className="cv-footer-mark">
            cube<span>·pod05</span>
            <small>Commerce Context · Round 3</small>
          </div>
        </div>
        <div className="cv-team">
          {team.map((m) => (
            <div key={m.name}>
              <strong>{m.name}</strong>
              <span>{m.role}</span>
            </div>
          ))}
        </div>
        <p className="cv-fineprint">Pod 05 · Sydon.ai × CodeQuesters CUBE 2026 · Illustrations generated locally with SDXL.</p>
      </footer>
    </div>
  )
}
