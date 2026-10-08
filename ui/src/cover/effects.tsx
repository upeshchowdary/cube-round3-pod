import Lenis from 'lenis'
import {
  Boxes,
  ClipboardCheck,
  Fingerprint,
  GitBranch,
  Hash,
  PackageCheck,
  Receipt,
  RotateCcw,
  Scale,
  ScanBarcode,
  ShieldCheck,
  Tag,
  Truck,
  Workflow,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Lenis smooth scrolling for the lifetime of the cover page only. */
export function useLenis() {
  useEffect(() => {
    if (reducedMotion()) return
    const lenis = new Lenis({ lerp: 0.1, smoothWheel: true })
    let raf = 0
    const loop = (time: number) => {
      lenis.raf(time)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => {
      cancelAnimationFrame(raf)
      lenis.destroy()
    }
  }, [])
}

/** Types `parts` once when it scrolls into view. Accent parts render in the green accent colour. */
export function Typewriter({ parts, speed = 28 }: { parts: Array<{ text: string; accent?: boolean }>; speed?: number }) {
  const total = parts.reduce((n, p) => n + p.text.length, 0)
  const ref = useRef<HTMLHeadingElement>(null)
  const [shown, setShown] = useState(reducedMotion() ? total : 0)
  const [started, setStarted] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el || started) return
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setStarted(true), { threshold: 0.4 })
    io.observe(el)
    return () => io.disconnect()
  }, [started])

  useEffect(() => {
    if (!started || shown >= total) return
    const id = window.setTimeout(() => setShown((n) => n + 1), speed + Math.random() * speed)
    return () => window.clearTimeout(id)
  }, [started, shown, total, speed])

  let left = shown
  return (
    <h2 ref={ref} className="cv-type" aria-label={parts.map((p) => p.text).join('')}>
      {parts.map((p, i) => {
        const take = Math.max(0, Math.min(p.text.length, left))
        left -= take
        return (
          <span key={i} className={p.accent ? 'cv-accent' : undefined} aria-hidden="true">
            {p.text.slice(0, take)}
          </span>
        )
      })}
      <span className={`cv-caret ${shown >= total ? 'done' : ''}`} aria-hidden="true" />
    </h2>
  )
}

const ICONS = [Truck, ScanBarcode, Tag, PackageCheck, Boxes, RotateCcw, ClipboardCheck, Receipt, Scale, ShieldCheck,
  Fingerprint, Hash, GitBranch, Workflow]

/** An endless row of icon chips that drifts sideways while each chip bobs on a sine wave. */
export function IconWave() {
  const track = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = track.current
    if (!el || reducedMotion()) return
    const chips = Array.from(el.children) as HTMLElement[]
    let raf = 0
    let x = 0
    const tick = (t: number) => {
      const half = el.scrollWidth / 2
      x = (x + 0.45) % half
      el.style.transform = `translate3d(${-x}px,0,0)`
      chips.forEach((c, i) => {
        c.style.transform = `translate3d(0, ${Math.sin(t / 900 + i * 0.55) * 14}px, 0)`
      })
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])
  const row = [...ICONS, ...ICONS]
  return (
    <div className="cv-wave" aria-hidden="true">
      <div ref={track} className="cv-wave-track">
        {row.map((Icon, i) => (
          <div key={i} className="cv-wave-chip">
            <Icon size={30} strokeWidth={1.6} />
          </div>
        ))}
      </div>
    </div>
  )
}

/** Footer canvas: thin green lines fan out from one point and sweep across the wordmark. */
export function LineFan() {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    let w = 0
    let h = 0
    let frame = 0
    let raf = 0
    let running = false
    const resize = () => {
      const r = canvas.getBoundingClientRect()
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = r.width
      h = r.height
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    const draw = () => {
      ctx.clearRect(0, 0, w, h)
      frame += reducedMotion() ? 0 : 1
      const lines = 18
      const startY = h * 0.94
      for (let i = 0; i < lines; i++) {
        const r = i / (lines - 1)
        const endY = h * (0.82 - r * 0.76)
        const phase = r * 4 + frame * 0.012
        const mid = 1 - Math.abs(r - 0.5) * 2
        ctx.beginPath()
        ctx.strokeStyle = `rgba(22, 163, 74, ${Math.max(0.07, 0.12 + 0.42 * mid)})`
        ctx.lineWidth = 0.8 + mid * 0.8
        for (let x = 0; x <= w; x += 3) {
          const n = x / w
          const ease = n * n * (3 - 2 * n)
          const wobble = Math.sin(n * Math.PI * 1.6 + phase) * h * 0.045 * n
          const y = startY + (endY - startY) * ease + wobble
          if (x === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        }
        ctx.stroke()
      }
      if (running) raf = requestAnimationFrame(draw)
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    const io = new IntersectionObserver(([e]) => {
      running = e.isIntersecting
      cancelAnimationFrame(raf)
      if (running) raf = requestAnimationFrame(draw)
    })
    io.observe(canvas)
    draw()
    return () => {
      running = false
      cancelAnimationFrame(raf)
      ro.disconnect()
      io.disconnect()
    }
  }, [])
  return <canvas ref={ref} className="cv-fan" aria-hidden="true" />
}

/** Cycles through words with a soft blur/slide, like the footer of the reference site. */
export function WordCycle({ words, interval = 2200 }: { words: string[]; interval?: number }) {
  const [i, setI] = useState(0)
  useEffect(() => {
    if (reducedMotion()) return
    const id = window.setInterval(() => setI((n) => (n + 1) % words.length), interval)
    return () => window.clearInterval(id)
  }, [words.length, interval])
  return (
    <span className="cv-cycle" aria-live="off">
      {words.map((w, k) => (
        <span key={w} className={`cv-cycle-word ${k === i ? 'on' : ''}`}>
          {w}
        </span>
      ))}
    </span>
  )
}
