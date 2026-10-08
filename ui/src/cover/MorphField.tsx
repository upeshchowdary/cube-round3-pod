import gsap from 'gsap'
import { useEffect, useRef, useState } from 'react'

// A dust field split in two panels. "Five demos" assembles into five disconnected boxes; "One system" assembles
// into five nodes on one connected chain. It plays by itself while visible; hovering a panel takes over.

interface Dot {
  x: number
  y: number
  hx: number
  hy: number
  alpha: number
  baseAlpha: number
  tint: number
  size: number
  panel: 0 | 1
}

function boxPoints(cx: number, cy: number, s: number, n: number) {
  const pts: Array<[number, number]> = []
  for (let i = 0; i < n; i++) {
    const edge = i % 4
    const t = Math.random() * 2 - 1
    const p: [number, number] = edge === 0 ? [t, -1] : edge === 1 ? [1, t] : edge === 2 ? [t, 1] : [-1, t]
    const jitter = Math.random() < 0.3 ? 0.6 : 0
    pts.push([cx + (p[0] * (1 - jitter * Math.random())) * s, cy + (p[1] * (1 - jitter * Math.random())) * s])
  }
  return pts
}

function ringPoints(cx: number, cy: number, r: number, n: number) {
  const pts: Array<[number, number]> = []
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2
    const rr = r * (Math.random() < 0.7 ? 1 : Math.sqrt(Math.random()))
    pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr])
  }
  return pts
}

function linePoints(x1: number, y1: number, x2: number, y2: number, n: number) {
  const pts: Array<[number, number]> = []
  for (let i = 0; i < n; i++) {
    const t = Math.random()
    pts.push([x1 + (x2 - x1) * t, y1 + (y2 - y1) * t + (Math.random() - 0.5) * 3])
  }
  return pts
}

export default function MorphField() {
  const wrap = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const dots = useRef<Dot[]>([])
  const shapes = useRef<Record<0 | 1, Array<[number, number]>>>({ 0: [], 1: [] })
  const hovering = useRef<0 | 1 | null>(null)
  const [active, setActive] = useState<0 | 1 | null>(null)

  const assemble = (panel: 0 | 1) => {
    const pts = gsap.utils.shuffle([...shapes.current[panel]])
    const mine = gsap.utils.shuffle(dots.current.filter((d) => d.panel === panel))
    mine.forEach((d, i) => {
      gsap.killTweensOf(d)
      if (i < pts.length) {
        const [x, y] = pts[i]
        const dur = gsap.utils.random(0.8, 1.3)
        const delay = Math.random() * 0.45
        gsap.to(d, { x, y, tint: 1, duration: dur, delay, ease: 'power3.out' })
        gsap.to(d, { keyframes: { alpha: [d.alpha, d.alpha * 0.2, gsap.utils.random(0.75, 1)] }, duration: dur, delay, ease: 'none' })
      } else {
        gsap.to(d, { alpha: d.baseAlpha * 0.6, tint: 0, duration: 0.5 })
      }
    })
    setActive(panel)
  }

  const release = (panel: 0 | 1) => {
    dots.current.filter((d) => d.panel === panel).forEach((d) => {
      gsap.killTweensOf(d)
      gsap.to(d, { x: d.hx, y: d.hy, tint: 0, alpha: d.baseAlpha, duration: gsap.utils.random(0.9, 1.4), delay: Math.random() * 0.3, ease: 'power2.inOut' })
    })
    setActive((a) => (a === panel ? null : a))
  }

  useEffect(() => {
    const c = canvas.current
    const host = wrap.current
    const ctx = c?.getContext('2d')
    if (!c || !host || !ctx) return
    let w = 0
    let h = 0
    let raf = 0
    let running = false

    const layout = () => {
      const r = host.getBoundingClientRect()
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = r.width
      h = r.height
      c.width = Math.round(w * dpr)
      c.height = Math.round(h * dpr)
      c.style.width = `${w}px`
      c.style.height = `${h}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const stacked = w < 768
      const count = stacked ? 700 : 1300
      dots.current = Array.from({ length: count }, (_, i) => {
        const panel = (stacked ? (i % 2) : (i % 2)) as 0 | 1
        const hx = stacked ? Math.random() * w : panel === 0 ? Math.random() * (w / 2) : w / 2 + Math.random() * (w / 2)
        const hy = stacked ? (panel === 0 ? Math.random() * (h / 2) : h / 2 + Math.random() * (h / 2)) : Math.random() * h
        const baseAlpha = 0.18 + Math.random() * 0.4
        return { x: hx, y: hy, hx, hy, alpha: baseAlpha, baseAlpha, tint: 0, size: 1 + Math.random() * 1.6, panel }
      })
      const s = Math.min(1, Math.max(0.6, (stacked ? w : w / 2) / 620))
      const left = stacked ? { x: w / 2, y: h * 0.25 } : { x: w * 0.25, y: h * 0.5 }
      const right = stacked ? { x: w / 2, y: h * 0.75 } : { x: w * 0.75, y: h * 0.5 }
      const per = Math.round((count / 2) * 0.62)
      // five disconnected boxes, scattered
      const offs = [[-150, -95], [40, -120], [160, 10], [-110, 85], [60, 115]]
      shapes.current[0] = offs.flatMap(([dx, dy]) => boxPoints(left.x + dx * s, left.y + dy * s, 38 * s, Math.floor(per / 5)))
      // five nodes on one connected chain
      const nodes = [-200, -100, 0, 100, 200].map((dx, i) => [right.x + dx * s, right.y + Math.sin(i * 1.1) * 34 * s] as const)
      const nodePts = nodes.flatMap(([x, y]) => ringPoints(x, y, 26 * s, Math.floor((per * 0.7) / 5)))
      const linkPts = nodes.slice(1).flatMap(([x, y], i) => linePoints(nodes[i][0] + 26 * s, nodes[i][1], x - 26 * s, y, Math.floor((per * 0.3) / 4)))
      shapes.current[1] = [...nodePts, ...linkPts]
    }

    const draw = () => {
      ctx.clearRect(0, 0, w, h)
      for (const d of dots.current) {
        const g = d.tint
        const r = Math.round(120 + (22 - 120) * g)
        const gg = Math.round(135 + (163 - 135) * g)
        const b = Math.round(128 + (74 - 128) * g)
        ctx.fillStyle = `rgba(${r},${gg},${b},${d.alpha})`
        const s = d.size * (1 + g * 0.6)
        ctx.fillRect(d.x - s / 2, d.y - s / 2, s, s)
      }
      if (running) raf = requestAnimationFrame(draw)
    }

    layout()
    const ro = new ResizeObserver(() => {
      layout()
      if (!running) draw()
    })
    ro.observe(host)

    // Autoplay while visible: five demos -> one system, every few seconds, unless someone is hovering.
    let step = 0
    const timer = window.setInterval(() => {
      if (!running || hovering.current !== null) return
      const panel = (step % 2) as 0 | 1
      release(((panel + 1) % 2) as 0 | 1)
      assemble(panel)
      step++
    }, 3200)
    const io = new IntersectionObserver(([e]) => {
      running = e.isIntersecting
      cancelAnimationFrame(raf)
      if (running) raf = requestAnimationFrame(draw)
    }, { threshold: 0.15 })
    io.observe(host)
    draw()
    return () => {
      running = false
      cancelAnimationFrame(raf)
      window.clearInterval(timer)
      ro.disconnect()
      io.disconnect()
      dots.current.forEach((d) => gsap.killTweensOf(d))
    }
  }, [])

  const enter = (p: 0 | 1) => {
    hovering.current = p
    release(((p + 1) % 2) as 0 | 1)
    assemble(p)
  }
  const leave = (p: 0 | 1) => {
    hovering.current = null
    release(p)
  }

  return (
    <div ref={wrap} className="cv-morph">
      <canvas ref={canvas} className="cv-morph-canvas" aria-hidden="true" />
      {([
        { tag: 'Round 2', title: 'Five separate demos', sub: 'Each agent judged alone. Nothing handed on.' },
        { tag: 'Round 3', title: 'One Pod system', sub: 'One contract, one orchestrator, one evidence trail.' },
      ] as const).map((p, i) => (
        <div
          key={p.title}
          className={`cv-morph-panel ${active === i ? 'on' : ''}`}
          onMouseEnter={() => enter(i as 0 | 1)}
          onMouseLeave={() => leave(i as 0 | 1)}
        >
          <span className="cv-chip">{p.tag}</span>
          <h3>{p.title}</h3>
          <p>{p.sub}</p>
        </div>
      ))}
    </div>
  )
}
