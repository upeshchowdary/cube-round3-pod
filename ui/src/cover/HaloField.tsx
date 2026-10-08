import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'

// A field of small instanced "dashes" drifting on sine waves. Around the cursor a breathing, noisy halo pushes
// them outward, enlarges them and tints them green; everything outside the halo ripples gently.

const vertexShader = /* glsl */ `
  uniform float uTime;
  uniform vec2 uMouse;
  uniform float uRadius;
  attribute vec3 aOffset;
  attribute float aRand;
  varying vec2 vUv;
  varying float vRim;
  varying vec2 vPos;

  float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
  }
  mat2 rot(float a) { return mat2(cos(a), sin(a), -sin(a), cos(a)); }

  void main() {
    vUv = uv;
    vec3 pos = aOffset;

    // 1. idle drift
    float t = uTime * 0.15;
    pos.x += (sin(t + pos.y * 0.5) + sin(t * 0.5 + pos.y * 2.0)) * 0.16;
    pos.y += (cos(t + pos.x * 0.5) + cos(t * 0.5 + pos.x * 2.0)) * 0.16;

    // 2. breathing halo around the (smoothed) cursor
    vec2 rel = pos.xy - uMouse;
    vec2 scaled = rel / vec2(1.3, 1.0);
    float dist = length(scaled);
    vec2 dir = normalize(rel + vec2(0.0001, 0.0));
    float breath = sin(uTime * 0.8);
    float radius = uRadius + breath * 0.35 + noise(dir * 2.0 + vec2(0.0, uTime * 0.1)) * 0.7;
    float rim = smoothstep(1.5, 0.0, abs(dist - radius));
    pos.xy += dir * (breath * 0.5 + 0.5) * 0.4 * rim;
    pos.z += rim * 0.3 * sin(uTime);

    // 3. faster ripple outside the halo
    float outer = smoothstep(radius + 0.4, radius + 2.2, dist);
    pos.xy += dir * sin(uTime * 2.4 + pos.x * 0.6 + pos.y * 0.6) * 0.09 * outer;

    // 4. size, stretch and orientation (dashes point away from the cursor)
    float size = 0.03 + sin(uTime + pos.x) * 0.004 + rim * 0.065;
    vec2 shape = position.xy * vec2(size * (1.0 + rim * 0.9), size * 0.42);
    float angle = atan(dir.y, dir.x) + (aRand - 0.5) * 0.6 + sin(uTime * 0.1 + aRand * 6.2831) * 0.2;
    shape = rot(-angle) * shape;

    vRim = rim;
    vPos = pos.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(pos + vec3(shape, 0.0), 1.0);
  }
`

const fragmentShader = /* glsl */ `
  uniform float uTime;
  uniform vec3 uBase;
  uniform vec3 uA;
  uniform vec3 uB;
  uniform vec3 uC;
  varying vec2 vUv;
  varying float vRim;
  varying vec2 vPos;

  void main() {
    vec2 p = abs(vUv - 0.5) * 2.0;
    float d = pow(pow(p.x, 2.6) + pow(p.y, 2.6), 1.0 / 2.6);   // squircle
    float alpha = 1.0 - smoothstep(0.78, 1.0, d);
    if (alpha < 0.01) discard;
    float t = uTime * 1.1;
    float p1 = sin(vPos.x * 0.8 + t);
    float p2 = sin(vPos.y * 0.8 + t * 0.8 + p1);
    vec3 lit = mix(uA, uB, p1 * 0.5 + 0.5);   // note: "active" is a reserved word in GLSL ES 3.00
    lit = mix(lit, uC, p2 * 0.5 + 0.5);
    vec3 color = mix(uBase, lit, smoothstep(0.08, 0.75, vRim));
    gl_FragColor = vec4(color, alpha * mix(0.32, 0.9, vRim));
  }
`

function Particles({ reduced }: { reduced: boolean }) {
  const { viewport, size } = useThree()
  const mouse = useRef(new THREE.Vector2(0, 0.6))
  const target = useRef(new THREE.Vector2(0, 0.6))
  const lastMove = useRef(0)

  const geometry = useMemo(() => {
    const spacing = 0.26
    const cols = Math.ceil(viewport.width / spacing) + 4
    const rows = Math.ceil(viewport.height / spacing) + 4
    const offsets: number[] = []
    const rands: number[] = []
    for (let i = 0; i < cols; i++) {
      for (let j = 0; j < rows; j++) {
        const x = (i - cols / 2) * spacing + (Math.random() - 0.5) * spacing * 0.9
        const y = (j - rows / 2) * spacing + (Math.random() - 0.5) * spacing * 0.9
        offsets.push(x, y, 0)
        rands.push(Math.random())
      }
    }
    const g = new THREE.InstancedBufferGeometry()
    const plane = new THREE.PlaneGeometry(1, 1)
    g.index = plane.index
    g.setAttribute('position', plane.getAttribute('position'))
    g.setAttribute('uv', plane.getAttribute('uv'))
    g.setAttribute('aOffset', new THREE.InstancedBufferAttribute(new Float32Array(offsets), 3))
    g.setAttribute('aRand', new THREE.InstancedBufferAttribute(new Float32Array(rands), 1))
    g.instanceCount = cols * rows
    return g
  }, [viewport.width, viewport.height])

  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader,
        fragmentShader,
        transparent: true,
        depthWrite: false,
        uniforms: {
          uTime: { value: 0 },
          uMouse: { value: new THREE.Vector2(0, 0.6) },
          uRadius: { value: 2.1 },
          uBase: { value: new THREE.Color('#b9cfc0') },
          uA: { value: new THREE.Color('#16a34a') },
          uB: { value: new THREE.Color('#4ade80') },
          uC: { value: new THREE.Color('#0d9488') },
        },
      }),
    [],
  )

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const nx = (e.clientX / size.width) * 2 - 1
      const ny = -((e.clientY / size.height) * 2 - 1)
      target.current.set((nx * viewport.width) / 2, (ny * viewport.height) / 2)
      lastMove.current = performance.now()
    }
    window.addEventListener('pointermove', onMove, { passive: true })
    return () => window.removeEventListener('pointermove', onMove)
  }, [size.width, size.height, viewport.width, viewport.height])

  useFrame((state) => {
    const t = reduced ? 4 : state.clock.elapsedTime
    // Idle: the halo drifts slowly around the headline until the visitor moves the mouse.
    if (performance.now() - lastMove.current > 3500) {
      target.current.set(Math.sin(t * 0.22) * viewport.width * 0.16, 0.5 + Math.cos(t * 0.3) * 0.5)
    }
    mouse.current.lerp(target.current, reduced ? 1 : 0.045)
    material.uniforms.uTime.value = t
    material.uniforms.uMouse.value.copy(mouse.current)
  })

  return <mesh geometry={geometry} material={material} frustumCulled={false} />
}

export default function HaloField() {
  const host = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(true)
  const reduced = useMemo(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches, [])

  useEffect(() => {
    const el = host.current
    if (!el) return
    const io = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { threshold: 0 })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  return (
    <div ref={host} className="cv-halo" aria-hidden="true">
      <Canvas
        dpr={[1, 2]}
        camera={{ position: [0, 0, 10], fov: 45 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        frameloop={visible && !reduced ? 'always' : 'demand'}
      >
        <Particles reduced={reduced} />
      </Canvas>
    </div>
  )
}
