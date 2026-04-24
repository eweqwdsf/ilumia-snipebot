// ============================================================
//  ILUMIA Launcher — renderer.js
// ============================================================

const W = 720, H = 580

// Version wird beim Boot via IPC geladen
let CURRENT_VERSION = 'v1.0.0'

const SCREENS_WITH_BACK = ['screen-hwid', 'screen-key', 'screen-configs', 'screen-filters', 'screen-launch']

function show(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'))
  document.getElementById(id).classList.add('active')
  const arrow = document.getElementById('btn-back-arrow')
  if (SCREENS_WITH_BACK.includes(id)) {
    arrow.style.display = 'flex'
  } else {
    arrow.style.display = 'none'
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const lerp = (a, b, t) => a + (b - a) * t
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
const easeInOut = t => t < 0.5 ? 2*t*t : -1+(4-2*t)*t

// ── Star field ────────────────────────────────────────────────────────────────
const bgCanvas = document.getElementById('bg-canvas')
const bgCtx    = bgCanvas.getContext('2d')

const N_STARS = 260
const stars = Array.from({ length: N_STARS }, () => ({
  x:  Math.random() * W,
  y:  Math.random() * H,
  r:  Math.pow(Math.random(), 2.2) * 0.9 + 0.15,   // size weighted to small
  vx: (Math.random() - 0.5) * 0.018,
  vy: (Math.random() - 0.5) * 0.012,
  a:  Math.random() * 0.38 + 0.12,
  // each star has its own slow sine twinkle
  freq:  0.003 + Math.random() * 0.012,
  phase: Math.random() * Math.PI * 2,
}))

// ── Meteors ───────────────────────────────────────────────────────────────────
const meteors = []
let  meteorTimer   = 0
let  meteorBatch   = 0   // counts how many spawned in current batch (max 2)

function spawnMeteor() {
  // Pick a random edge: 0=top, 1=right, 2=bottom, 3=left
  const edge = Math.floor(Math.random() * 4)
  const margin = 40

  let ox, oy, tx, ty

  if (edge === 0) {
    // Top edge → bottom edge
    ox = Math.random() * W
    oy = -margin
    tx = Math.random() * W
    ty = H + margin
  } else if (edge === 1) {
    // Right edge → left edge
    ox = W + margin
    oy = Math.random() * H
    tx = -margin
    ty = Math.random() * H
  } else if (edge === 2) {
    // Bottom edge → top edge
    ox = Math.random() * W
    oy = H + margin
    tx = Math.random() * W
    ty = -margin
  } else {
    // Left edge → right edge
    ox = -margin
    oy = Math.random() * H
    tx = W + margin
    ty = Math.random() * H
  }

  const dx   = tx - ox
  const dy   = ty - oy
  const dist = Math.hypot(dx, dy)
  const speed = 1.6 + Math.random() * 2.2   // slow, cinematic

  meteors.push({
    x:    ox,
    y:    oy,
    vx:   (dx / dist) * speed,
    vy:   (dy / dist) * speed,
    len:  100 + Math.random() * 130,
    life: 1.0,
    fade: 0.003 + Math.random() * 0.003,
    w:    0.7 + Math.random() * 0.8,
  })
}

function drawMeteors() {
  for (let i = meteors.length - 1; i >= 0; i--) {
    const m   = meteors[i]
    const ang = Math.atan2(m.vy, m.vx)

    const tx = m.x - Math.cos(ang) * m.len
    const ty = m.y - Math.sin(ang) * m.len
    const grd = bgCtx.createLinearGradient(tx, ty, m.x, m.y)
    grd.addColorStop(0,    `rgba(255,255,255,0)`)
    grd.addColorStop(0.55, `rgba(255,255,255,${(m.life * 0.14).toFixed(3)})`)
    grd.addColorStop(1,    `rgba(255,255,255,${(m.life * 0.65).toFixed(3)})`)

    bgCtx.beginPath()
    bgCtx.moveTo(tx, ty)
    bgCtx.lineTo(m.x, m.y)
    bgCtx.strokeStyle = grd
    bgCtx.lineWidth   = m.w * m.life
    bgCtx.stroke()

    const glow = bgCtx.createRadialGradient(m.x, m.y, 0, m.x, m.y, 4)
    glow.addColorStop(0, `rgba(255,255,255,${(m.life * 0.45).toFixed(3)})`)
    glow.addColorStop(1, 'rgba(255,255,255,0)')
    bgCtx.beginPath()
    bgCtx.arc(m.x, m.y, 4, 0, Math.PI * 2)
    bgCtx.fillStyle = glow
    bgCtx.fill()

    m.x += m.vx; m.y += m.vy
    m.life -= m.fade
    if (m.life <= 0 || m.y > H + 200 || m.x < -400 || m.x > W + 400 || m.y < -200) {
      meteors.splice(i, 1)
    }
  }
}

// ── Milky Way ─────────────────────────────────────────────────────────────────
// Each "galaxy patch" is a cluster: a band of faint star-dots + connecting lines
// that fades in, drifts, then fades out and respawns at a new random position.

const N_GALAXY_PATCHES = 4   // simultaneous patches visible at once

function makeGalaxyPatch() {
  // Random band angle (diagonal streaks, vary between patches)
  const angle  = (Math.random() * 0.6 + 0.1) * Math.PI   // 18°–126° spread
  const cx     = Math.random() * W
  const cy     = Math.random() * H
  const len    = 90 + Math.random() * 130    // band length
  const spread = 14 + Math.random() * 22     // perpendicular scatter
  const nDots  = Math.floor(18 + Math.random() * 28)
  const nLines = Math.floor(6  + Math.random() * 10)

  // Pre-generate dot positions along the band
  const dots = Array.from({ length: nDots }, () => {
    const t  = (Math.random() - 0.5) * len
    const perp = (Math.random() - 0.5) * spread * 2
    // Gaussian-ish weight — denser in centre
    const weight = Math.exp(-Math.abs(t) / (len * 0.38))
    return {
      x:    cx + Math.cos(angle) * t - Math.sin(angle) * perp,
      y:    cy + Math.sin(angle) * t + Math.cos(angle) * perp,
      r:    Math.pow(Math.random(), 1.8) * 0.95 + 0.12,
      baseA: (0.08 + Math.random() * 0.22) * weight,
      freq:  0.008 + Math.random() * 0.022,
      phase: Math.random() * Math.PI * 2,
    }
  })

  // Pre-generate line connections between nearby dots (star-chain feel)
  const lines = []
  for (let i = 0; i < nLines; i++) {
    const a = Math.floor(Math.random() * nDots)
    let   b = Math.floor(Math.random() * nDots)
    if (b === a) b = (a + 1) % nDots
    const dist = Math.hypot(dots[a].x - dots[b].x, dots[a].y - dots[b].y)
    if (dist < spread * 2.8) {   // only connect nearby dots
      lines.push({ a, b, baseA: 0.025 + Math.random() * 0.055 })
    }
  }

  return {
    dots, lines,
    life:    0.0,          // 0→1 fade in, then 1→0 fade out
    phase:   'in',         // 'in' | 'hold' | 'out'
    holdFor: 4.5 + Math.random() * 7.0,   // seconds to stay visible
    holdT:   0,
    inSpeed:  0.008 + Math.random() * 0.006,
    outSpeed: 0.005 + Math.random() * 0.005,
    // Slow drift
    vx: (Math.random() - 0.5) * 0.08,
    vy: (Math.random() - 0.5) * 0.05,
    cx, cy,
  }
}

// Stagger initial patches so they don't all appear at once
const galaxyPatches = Array.from({ length: N_GALAXY_PATCHES }, (_, i) => {
  const p = makeGalaxyPatch()
  // Start some patches mid-cycle so the screen isn't empty at boot
  if (i < 2) {
    p.life  = 0.4 + Math.random() * 0.5
    p.phase = 'hold'
    p.holdT = Math.random() * p.holdFor * 0.5
  }
  return p
})

function drawGalaxy(dt, t) {
  for (let pi = 0; pi < galaxyPatches.length; pi++) {
    const p = galaxyPatches[pi]

    // Lifecycle state machine
    if (p.phase === 'in') {
      p.life += p.inSpeed
      if (p.life >= 1.0) { p.life = 1.0; p.phase = 'hold' }
    } else if (p.phase === 'hold') {
      p.holdT += dt
      if (p.holdT >= p.holdFor) p.phase = 'out'
    } else {
      p.life -= p.outSpeed
      if (p.life <= 0) {
        // Respawn at a new position
        galaxyPatches[pi] = makeGalaxyPatch()
        continue
      }
    }

    // Drift all dots
    for (const d of p.dots) {
      d.x += p.vx
      d.y += p.vy
    }

    const masterA = p.life   // 0–1 envelope

    // Draw lines first (underneath dots)
    for (const ln of p.lines) {
      const da = p.dots[ln.a], db = p.dots[ln.b]
      const a  = ln.baseA * masterA
      if (a < 0.003) continue
      bgCtx.beginPath()
      bgCtx.moveTo(da.x, da.y)
      bgCtx.lineTo(db.x, db.y)
      bgCtx.strokeStyle = `rgba(200,210,255,${a.toFixed(3)})`
      bgCtx.lineWidth   = 0.4
      bgCtx.stroke()
    }

    // Draw dots with per-dot twinkle
    for (const d of p.dots) {
      const twinkle = 0.55 + 0.45 * Math.sin(t * (d.freq * 60) + d.phase)
      const a       = d.baseA * masterA * twinkle
      if (a < 0.004) continue
      bgCtx.beginPath()
      bgCtx.arc(d.x, d.y, d.r, 0, Math.PI * 2)
      bgCtx.fillStyle = `rgba(210,220,255,${a.toFixed(3)})`
      bgCtx.fill()
    }
  }
}

// ── Sphere ────────────────────────────────────────────────────────────────────
const sphCanvas = document.getElementById('sphere-canvas')
const sphCtx    = sphCanvas.getContext('2d')

// Sphere sits at top-center, title at ~196px so sphere bottom ~170px → CY=110, SR=56
const CX = W / 2, CY = 106, SR = 56

// Rotation matrices — kept smooth by using tiny increments
function rot3(x, y, z, rx, ry) {
  // Rotate around Y then X
  const cosY = Math.cos(ry), sinY = Math.sin(ry)
  const cosX = Math.cos(rx), sinX = Math.sin(rx)
  const x1 =  x * cosY + z * sinY
  const z1 = -x * sinY + z * cosY
  const y2 =  y * cosX - z1 * sinX
  const z2 =  y * sinX + z1 * cosX
  return [x1, y2, z2]
}

// Pre-compute sphere grid — positions only change by rotation each frame
const LAT_COUNT = 7        // latitude lines
const LON_COUNT = 12       // longitude lines
const SEG       = 64       // segments per ring/arc

function drawSphere(t) {
  sphCtx.clearRect(0, 0, W, 265)

  // ── Ambient glow ─────────────────────────────────────────
  // Slow breathe: 0.008 rad/frame so very gradual
  const breathe = 0.5 + 0.5 * Math.sin(t * 0.4)
  const glowR   = SR * (1.6 + 0.15 * breathe)
  const glowA   = 0.012 + 0.006 * breathe
  const grd = sphCtx.createRadialGradient(CX, CY, SR * 0.2, CX, CY, glowR)
  grd.addColorStop(0, `rgba(255,255,255,${glowA.toFixed(4)})`)
  grd.addColorStop(0.5, `rgba(255,255,255,${(glowA * 0.4).toFixed(4)})`)
  grd.addColorStop(1,   'rgba(0,0,0,0)')
  sphCtx.beginPath()
  sphCtx.ellipse(CX, CY, glowR, glowR * 0.82, 0, 0, Math.PI * 2)
  sphCtx.fillStyle = grd
  sphCtx.fill()

  // ── Grid lines ────────────────────────────────────────────
  // Very slow rotation: longitude rotates at t*0.035
  const lonRot = t * 0.035

  // Latitude circles (static in Y, no rotation needed)
  for (let i = 0; i < LAT_COUNT; i++) {
    const lat = ((i / (LAT_COUNT - 1)) - 0.5) * Math.PI * 0.85
    const r   = SR * Math.cos(lat)
    const yo  = SR * Math.sin(lat) * 0.84
    // Fade lines near poles
    const fade = Math.abs(Math.cos(lat))
    const a    = fade * 0.10
    if (a < 0.005) continue

    sphCtx.beginPath()
    for (let j = 0; j <= SEG; j++) {
      const ang = (j / SEG) * Math.PI * 2
      const px  = CX + Math.cos(ang) * r
      const py  = CY - yo + Math.sin(ang) * r * 0.10   // slight perspective flatten
      j === 0 ? sphCtx.moveTo(px, py) : sphCtx.lineTo(px, py)
    }
    sphCtx.strokeStyle = `rgba(255,255,255,${a.toFixed(3)})`
    sphCtx.lineWidth   = 0.6
    sphCtx.stroke()
  }

  // Longitude arcs (rotate continuously)
  for (let m = 0; m < LON_COUNT; m++) {
    const ma = (m / LON_COUNT) * Math.PI + lonRot
    // Depth cue: lines facing viewer are slightly brighter
    const facing = Math.abs(Math.cos(ma))
    const a = 0.055 + facing * 0.055

    sphCtx.beginPath()
    for (let j = 0; j <= SEG; j++) {
      const lat = ((j / SEG) - 0.5) * Math.PI
      const px  = CX + Math.cos(ma) * SR * Math.cos(lat)
      const py  = CY - SR * Math.sin(lat) * 0.84
      j === 0 ? sphCtx.moveTo(px, py) : sphCtx.lineTo(px, py)
    }
    sphCtx.strokeStyle = `rgba(255,255,255,${a.toFixed(3)})`
    sphCtx.lineWidth   = 0.6
    sphCtx.stroke()
  }

  // Sphere outline
  sphCtx.beginPath()
  sphCtx.ellipse(CX, CY, SR, SR * 0.84, 0, 0, Math.PI * 2)
  sphCtx.strokeStyle = 'rgba(255,255,255,0.10)'
  sphCtx.lineWidth   = 0.8
  sphCtx.stroke()

  // ── Orbital rings ─────────────────────────────────────────
  // Each ring: [tiltX, tiltY_offset, radius, speed, baseAlpha, dotSize]
  // Speeds are very slow — smooth and cinematic
  const rings = [
    [Math.PI * 0.10,  0.00, SR * 1.68,  0.28, 0.18, 2.2],
    [Math.PI * 0.34,  0.80, SR * 1.42, -0.20, 0.22, 2.0],
    [Math.PI * 0.56,  1.80, SR * 1.18,  0.16, 0.25, 1.8],
    [Math.PI * 0.78,  2.80, SR * 0.88, -0.24, 0.28, 1.6],
  ]

  for (const [tx, tyrOff, rad, spd, ba, ds] of rings) {
    const tyr = tyrOff + t * spd    // very slow accumulated rotation

    // Collect back/front points with smooth depth fade
    const backPts = [], frontPts = []
    const backA   = [], frontA  = []

    for (let i = 0; i <= SEG; i++) {
      const ang = (i / SEG) * Math.PI * 2
      const [rx, ry, rz] = rot3(Math.cos(ang) * rad, Math.sin(ang) * rad, 0, tx, tyr)
      const depth = (rz + rad) / (2 * rad)   // 0=back, 1=front
      const px = CX + rx
      const py = CY - ry * 0.84
      if (rz >= 0) {
        frontPts.push([px, py])
        frontA.push(depth)
      } else {
        backPts.push([px, py])
        backA.push(depth)
      }
    }

    // Draw back half (behind sphere)
    if (backPts.length > 1) {
      for (let i = 0; i < backPts.length - 1; i++) {
        const a = ba * 0.15 * backA[i]
        sphCtx.beginPath()
        sphCtx.moveTo(backPts[i][0],   backPts[i][1])
        sphCtx.lineTo(backPts[i+1][0], backPts[i+1][1])
        sphCtx.strokeStyle = `rgba(255,255,255,${a.toFixed(3)})`
        sphCtx.lineWidth   = 0.6
        sphCtx.stroke()
      }
    }

    // Draw front half with per-segment depth brightness
    if (frontPts.length > 1) {
      for (let i = 0; i < frontPts.length - 1; i++) {
        const a = ba * (0.25 + 0.75 * frontA[i])
        sphCtx.beginPath()
        sphCtx.moveTo(frontPts[i][0],   frontPts[i][1])
        sphCtx.lineTo(frontPts[i+1][0], frontPts[i+1][1])
        sphCtx.strokeStyle = `rgba(255,255,255,${a.toFixed(3)})`
        sphCtx.lineWidth   = 0.7
        sphCtx.stroke()
      }
    }

    // ── Orbiting dot with soft glow ───────────────────────
    const da = t * spd + Math.PI * 0.25
    const [dx, dy, dz] = rot3(Math.cos(da) * rad, Math.sin(da) * rad, 0, tx, tyr)
    const depth = clamp((dz + rad) / (2 * rad), 0, 1)
    const dotA  = ba * (0.3 + 0.7 * depth)
    const dr    = ds * (0.55 + 0.45 * depth)
    const dpx   = CX + dx
    const dpy   = CY - dy * 0.84

    // Soft glow around dot
    const dotGlow = sphCtx.createRadialGradient(dpx, dpy, 0, dpx, dpy, dr * 3.5)
    dotGlow.addColorStop(0, `rgba(255,255,255,${(dotA * 0.6).toFixed(3)})`)
    dotGlow.addColorStop(1, 'rgba(255,255,255,0)')
    sphCtx.beginPath()
    sphCtx.arc(dpx, dpy, dr * 3.5, 0, Math.PI * 2)
    sphCtx.fillStyle = dotGlow
    sphCtx.fill()

    // Solid dot core
    sphCtx.beginPath()
    sphCtx.arc(dpx, dpy, dr, 0, Math.PI * 2)
    sphCtx.fillStyle = `rgba(255,255,255,${dotA.toFixed(3)})`
    sphCtx.fill()
  }

  // ── Side HUD tick marks ───────────────────────────────────
  for (const side of [-1, 1]) {
    const x0   = CX + side * (SR + 22)
    const x1   = CX + side * (W / 2 - 40)
    const span = Math.abs(x1 - x0)

    // Horizontal dashes fading outward
    const DASHES = 10
    for (let i = 0; i < DASHES; i++) {
      const f  = i / DASHES
      const a  = 0.09 * Math.pow(1 - f, 1.4)
      const gx0 = x0 + side * span * f
      const gx1 = x0 + side * span * (f + 0.08)
      sphCtx.beginPath()
      sphCtx.moveTo(gx0, CY)
      sphCtx.lineTo(gx1, CY)
      sphCtx.strokeStyle = `rgba(255,255,255,${a.toFixed(3)})`
      sphCtx.lineWidth   = 0.6
      sphCtx.stroke()
    }

    // Vertical tick marks at key intervals
    const ticks = [0.20, 0.45, 0.70, 0.90]
    for (const frac of ticks) {
      const tx2 = x0 + side * span * frac
      const th  = frac < 0.5 ? 6 : frac < 0.8 ? 4 : 3
      const ta  = 0.08 * (1 - frac)
      sphCtx.beginPath()
      sphCtx.moveTo(tx2, CY - th)
      sphCtx.lineTo(tx2, CY + th)
      sphCtx.strokeStyle = `rgba(255,255,255,${ta.toFixed(3)})`
      sphCtx.lineWidth   = 0.6
      sphCtx.stroke()
    }
  }
}

// ── Main animation loop ───────────────────────────────────────────────────────
let t = 0
let lastTime = null

function frame(now) {
  if (!lastTime) lastTime = now
  const dt = Math.min((now - lastTime) / 1000, 0.05)   // seconds, capped
  lastTime = now

  // t advances ~1/s at 60fps: 0.005 * 60 ≈ 0.3 rad/s — very slow & smooth
  t += dt * 0.30

  // ── Stars ──────────────────────────────────────────────
  bgCtx.clearRect(0, 0, W, H)
  for (const s of stars) {
    s.x += s.vx; s.y += s.vy
    if (s.x < 0) s.x = W; if (s.x > W) s.x = 0
    if (s.y < 0) s.y = H; if (s.y > H) s.y = 0
    // Smooth sine twinkle per star
    const pulse = 0.60 + 0.40 * Math.sin(t * (s.freq * 60) + s.phase)
    const a     = s.a * pulse
    bgCtx.beginPath()
    bgCtx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
    bgCtx.fillStyle = `rgba(255,255,255,${a.toFixed(3)})`
    bgCtx.fill()
  }

  // ── Meteors ────────────────────────────────────────────
  meteorTimer += dt
  // Spawn every 1.5–3.5s; 40% chance of a second simultaneous meteor
  if (meteorTimer > 1.5 + Math.random() * 2.0) {
    spawnMeteor()
    if (Math.random() < 0.40) spawnMeteor()   // occasional double
    meteorTimer = 0
  }
  drawMeteors()

  // ── Milky Way galaxy patches ───────────────────────────
  drawGalaxy(dt, t)

  // ── Sphere ────────────────────────────────────────────
  drawSphere(t)

  requestAnimationFrame(frame)
}
requestAnimationFrame(frame)

// ── Window chrome ─────────────────────────────────────────────────────────────
document.getElementById('btn-close').addEventListener('click', () => window.api.closeWindow())
document.getElementById('btn-minimize').addEventListener('click', () => window.api.minimizeWindow())

document.getElementById('btn-back-arrow').addEventListener('click', () => {
  const active = document.querySelector('.screen.active')
  if (active?.id === 'screen-launch') {
    botRunning = false
    stopPolling()
    // Reset layers for next visit
    const ll = document.getElementById('launch-license-layer')
    const sl = document.getElementById('launch-socials-layer')
    ll.style.display      = 'flex'
    ll.style.opacity      = '1'
    sl.style.opacity      = '0'
    sl.style.pointerEvents = 'none'
    document.getElementById('launch-bot-starting').style.display = 'flex'
    document.getElementById('launch-bot-active').style.display   = 'none'
  }
  show('screen-menu')
})

// ── State ─────────────────────────────────────────────────────────────────────
let cachedHwid   = null
let botRunning   = false
let savedKey     = null

document.getElementById('version-tag').textContent = CURRENT_VERSION

// ── Helpers ───────────────────────────────────────────────────────────────────
function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderHwid(raw) {
  // Erwartet: "UUID | BASEBOARD"  — einer von beiden kann fehlen
  const parts = raw.split('|').map(s => s.trim()).filter(Boolean)
  const uuid  = parts[0] || raw
  const board = parts[1] || ''

  let html = `
    <div class="hwid-row">
      <span class="hwid-label">UUID</span>
      <span class="hwid-value">${escapeHtml(uuid)}</span>
    </div>`

  if (board) {
    html += `
      <div class="hwid-divider"></div>
      <div class="hwid-row">
        <span class="hwid-label">BOARD</span>
        <span class="hwid-value">${escapeHtml(board)}</span>
      </div>`
  }
  return html
}

function formatLicenseKey(raw) {
  // "30dabc1234def5678..." → "30D-ABC1-234D-EF56-78..."  (Durations-Prefix + 5×4 Blöcke)
  // Wir akzeptieren beliebigen Input, normalisieren auf Großbuchstaben + Digits.
  const clean = String(raw).toUpperCase().replace(/[^A-Z0-9]/g, '')
  if (!clean) return ''

  // Prefix = führende Ziffern + 'D' falls vorhanden  (z.B. "30D", "365D", "7D")
  const prefixMatch = clean.match(/^(\d+D)(.*)$/)
  let prefix = ''
  let rest   = clean
  if (prefixMatch) {
    prefix = prefixMatch[1]
    rest   = prefixMatch[2]
  }

  // Rest in 4er-Blöcke splitten (max 5 Blöcke = 20 Zeichen)
  rest = rest.slice(0, 20)
  const blocks = rest.match(/.{1,4}/g) || []

  const parts = prefix ? [prefix, ...blocks] : blocks
  return parts.join('-')
}

// ── Boot ──────────────────────────────────────────────────────────────────────
async function boot() {
  // Version laden
  try {
    const v = await window.api.getAppVersion()
    if (v) {
      CURRENT_VERSION = v
      document.getElementById('version-tag').textContent = CURRENT_VERSION
    }
  } catch (_) {}

  show('screen-menu')
}


document.getElementById('btn-go-key').addEventListener('click', () => {
  document.getElementById('key-status').textContent = ''
  document.getElementById('key-input').value = ''
  show('screen-key')
  setTimeout(() => document.getElementById('key-input').focus(), 50)
})

document.getElementById('btn-go-hwid').addEventListener('click', async () => {
  show('screen-hwid')
  const display  = document.getElementById('hwid-display')
  const copyBtn  = document.getElementById('btn-copy-hwid')

  // Immer frisch laden — kein Cache, damit Registry-HWID immer aktuell ist
  cachedHwid = null
  copyBtn.disabled      = true
  copyBtn.style.opacity = '0.35'
  display.classList.remove('error')
  display.classList.add('loading')
  display.innerHTML = ''
  display.textContent   = 'loading…'

  const res  = await window.api.getHwid()
  cachedHwid = res?.hwid || null

  if (!cachedHwid) {
    display.classList.remove('loading')
    display.classList.add('error')
    display.textContent = 'Failed to load'
    return
  }

  // HWID kommt aus der Bridge als "UUID | Baseboard" — sauber in zwei Zeilen rendern
  display.classList.remove('loading', 'error')
  display.innerHTML = renderHwid(cachedHwid)
  display.style.color   = ''

  copyBtn.disabled      = false
  copyBtn.style.opacity = '1'
})

document.getElementById('btn-copy-hwid').addEventListener('click', () => {
  if (!cachedHwid) return
  navigator.clipboard.writeText(cachedHwid)  // rohe HWID ohne Bindestriche
  const hint = document.getElementById('copy-hint')
  hint.textContent = 'copied ✓'
  setTimeout(() => { hint.textContent = '' }, 1600)
})
document.getElementById('btn-hwid-back').addEventListener('click', () => show('screen-menu'))

document.getElementById('btn-key-back').addEventListener('click', () => show('screen-menu'))

// ── Filters screen ───────────────────────────────────────────────────────────
const FILTER_FIELDS = {
  sizes:     { key: 'permitted_sizes' },
  brands:    { key: 'core_brands' },
  hype:      { key: 'hype_keywords' },
  blacklist: { key: 'blacklist' },
}

// Default filters used by the bot when no profile is active — never shown in UI by default
const DEFAULT_FILTERS = {
  permitted_sizes: ['s','m','l','xl','small','medium','large','extra large','44','46','48','50','52','54'],
  core_brands: ['nike','adidas','lacoste','ralph lauren','polo','corteiz','chrome hearts','arcteryx','stussy','carhartt','stone island','fred perry','levis','bershka','true religion'],
  hype_keywords: ['vintage','vintedstyle','2000s','pasha-style','90s','00s','y2k','jersey','trikot','tracksuit','windbreaker','harley davidson','nascar','baggy','jeans','puffer','backprint jeans'],
  blacklist: ['zara','h&m','shein','asos','defacto','pull&bear','primark','damen','frau','women','kids','kinder','mädchen','junge','basic','skinny','regular fit','slim fit'],
  min_price: 5.0,
  max_price: 65.0,
}

// Empty state for new profiles — fields start blank in the UI
const EMPTY_FILTERS = {
  permitted_sizes: [],
  core_brands: [],
  hype_keywords: [],
  blacklist: [],
  min_price: null,
  max_price: null,
}

// All available sizes on Vinted
const ALL_SIZES = [
  'XXS','XS','S','M','L','XL','XXL','XXXL',
  'XS / 34','S / 36','M / 38','L / 40','XL / 42','XXL / 44',
  '34','36','38','40','42','44','46','48','50','52','54','56','58',
  'One Size','Oversize',
  'Small','Medium','Large','Extra Large',
]

// All brands available on Vinted (comprehensive list)
const ALL_BRANDS = [
  'Abercrombie & Fitch','Acne Studios','Adidas','Alpha Industries','AMIRI',
  'Arc\'teryx','Armani','ASOS','Balenciaga','Balmain','Barbour','Bershka',
  'Boss','Bottega Veneta','Burberry','Calvin Klein','Carhartt','Champion',
  'Chrome Hearts','Columbia','Comme des Garçons','Corteiz','CP Company',
  'Denim Tears','Dickies','Diesel','DKNY','Dolce & Gabbana','Dr. Martens',
  'Ellesse','Fear of God','Fendi','Fred Perry','Givenchy','Gucci',
  'H&M','Harley Davidson','Hugo Boss','Icebreaker','Jack & Jones',
  'Jack Wolfskin','Karl Lagerfeld','Kenzo','Lacoste','Lee','Levi\'s',
  'Loewe','Louis Vuitton','Mango','Marc Jacobs','MCM','Miu Miu',
  'Moncler','Napapijri','New Balance','New Era','Nike','North Face',
  'Off-White','Palace','Palm Angels','Patagonia','Paul & Shark',
  'Polo Ralph Lauren','Prada','Puma','Pull&Bear','Ralph Lauren',
  'Reebok','Represent','Rhude','Rick Owens','Salomon','Sergio Tacchini',
  'Shein','Stone Island','Stussy','Supreme','Timberland','Tommy Hilfiger',
  'True Religion','Umbro','Under Armour','Valentino','Versace',
  'Vintage','Vans','Vivienne Westwood','Wrangler','Yeezy','Zara',
]

// Current in-memory working copy
let filterState = null

// Track open dropdown
let openDropdown = null

function setFiltersStatus(msg, kind = '') {
  const el = document.getElementById('filters-status')
  el.textContent = msg
  el.className = 'filters-status' + (kind ? ' ' + kind : '')
}

// ── Dropdown helpers ──────────────────────────────────────────────────────────

function buildDropdown(listEl, triggerEl, field, allOptions) {
  listEl.innerHTML = ''
  const key = FILTER_FIELDS[field].key
  const selected = filterState ? (filterState[key] || []).map(v => v.toLowerCase()) : []

  allOptions.forEach(opt => {
    const isSelected = selected.includes(opt.toLowerCase())
    const item = document.createElement('div')
    item.className = 'fe-dropdown-item' + (isSelected ? ' selected' : '')
    item.innerHTML = `<span class="check">${isSelected ? '&#x2713;' : ''}</span><span class="label">${escapeHtml(opt)}</span>`
    item.addEventListener('click', (e) => {
      e.stopPropagation()
      toggleDropdownItem(field, opt, item)
    })
    listEl.appendChild(item)
  })
}

function toggleDropdownItem(field, val, itemEl) {
  if (!filterState) return
  const key = FILTER_FIELDS[field].key
  if (!filterState[key]) filterState[key] = []
  const lower = val.toLowerCase()
  const idx = filterState[key].indexOf(lower)
  if (idx === -1) {
    filterState[key].push(lower)
    itemEl.classList.add('selected')
    itemEl.querySelector('.check').innerHTML = '&#x2713;'
    itemEl.querySelector('.label').style.color = '#ffffff'
    itemEl.querySelector('.label').style.fontWeight = '500'
  } else {
    filterState[key].splice(idx, 1)
    itemEl.classList.remove('selected')
    itemEl.querySelector('.check').innerHTML = ''
    itemEl.querySelector('.label').style.color = ''
    itemEl.querySelector('.label').style.fontWeight = ''
  }
  renderTagsForDropdown(field)
  setFiltersStatus('')
}

function renderTagsForDropdown(field) {
  const tagWrapId = field === 'sizes' ? 'f-sizes-tags' : 'f-brands-tags'
  const wrap = document.getElementById(tagWrapId)
  if (!wrap) return
  wrap.innerHTML = ''
  const key = FILTER_FIELDS[field].key
  const list = filterState[key] || []
  list.forEach(val => {
    const tag = document.createElement('span')
    tag.className = 'tag'
    tag.innerHTML = `<span>${escapeHtml(val)}</span><span class="tag-x">&#xD7;</span>`
    tag.querySelector('.tag-x').addEventListener('click', () => {
      filterState[key] = filterState[key].filter(v => v !== val)
      renderTagsForDropdown(field)
      // Sync dropdown item visual state
      const listEl = document.getElementById(field + '-list')
      if (listEl) {
        listEl.querySelectorAll('.fe-dropdown-item').forEach(item => {
          const lbl = item.querySelector('.label')?.textContent?.toLowerCase()
          if (lbl === val.toLowerCase()) {
            item.classList.remove('selected')
            item.querySelector('.check').innerHTML = ''
            lbl && (item.querySelector('.label').style.color = '')
            lbl && (item.querySelector('.label').style.fontWeight = '')
          }
        })
      }
      setFiltersStatus('')
    })
    wrap.appendChild(tag)
  })
}

function openDropdownFor(field, allOptions) {
  const triggerEl = document.getElementById(field + '-trigger')
  const listEl    = document.getElementById(field + '-list')
  if (!triggerEl || !listEl) return

  // Close any other open dropdown
  if (openDropdown && openDropdown !== field) {
    closeDropdown(openDropdown)
  }

  const isOpen = listEl.classList.contains('open')
  if (isOpen) {
    closeDropdown(field)
  } else {
    buildDropdown(listEl, triggerEl, field, allOptions)
    listEl.classList.add('open')
    triggerEl.classList.add('open')
    openDropdown = field
  }
}

function closeDropdown(field) {
  const triggerEl = document.getElementById(field + '-trigger')
  const listEl    = document.getElementById(field + '-list')
  if (listEl) listEl.classList.remove('open')
  if (triggerEl) triggerEl.classList.remove('open')
  if (openDropdown === field) openDropdown = null
}

// Close dropdowns when clicking outside
document.addEventListener('click', (e) => {
  if (openDropdown) {
    const wrap = e.target.closest('.fe-dropdown-wrap')
    if (!wrap) closeDropdown(openDropdown)
  }
})

// Wire up dropdown triggers
document.getElementById('sizes-trigger').addEventListener('click', (e) => {
  e.stopPropagation()
  openDropdownFor('sizes', ALL_SIZES)
})
document.getElementById('brands-trigger').addEventListener('click', (e) => {
  e.stopPropagation()
  openDropdownFor('brands', ALL_BRANDS)
})

// ── Tag rendering for free-text fields ───────────────────────────────────────

function renderFreeTags(field) {
  const wrapId = field === 'hype' ? 'f-hype-wrap' : 'f-blacklist-wrap'
  const wrap = document.getElementById(wrapId)
  if (!wrap) return
  const key = FILTER_FIELDS[field].key
  const list = filterState[key] || []
  wrap.querySelectorAll('.tag').forEach(t => t.remove())
  const input = wrap.querySelector('.tag-input')
  list.forEach(val => {
    const tag = document.createElement('span')
    tag.className = 'tag'
    tag.innerHTML = `<span>${escapeHtml(val)}</span><span class="tag-x">&#xD7;</span>`
    tag.querySelector('.tag-x').addEventListener('click', () => {
      filterState[key] = filterState[key].filter(v => v !== val)
      renderFreeTags(field)
      setFiltersStatus('')
    })
    wrap.insertBefore(tag, input)
  })
}

function renderAllFilters() {
  if (!filterState) return
  document.getElementById('f-min-price').value = filterState.min_price ?? ''
  document.getElementById('f-max-price').value = filterState.max_price ?? ''
  renderTagsForDropdown('sizes')
  renderTagsForDropdown('brands')
  renderFreeTags('hype')
  renderFreeTags('blacklist')
}

function addFreeTag(field, raw) {
  const val = String(raw).trim().toLowerCase()
  if (!val) return
  const key = FILTER_FIELDS[field].key
  if (!filterState[key]) filterState[key] = []
  if (filterState[key].includes(val)) return
  filterState[key].push(val)
  renderFreeTags(field)
  setFiltersStatus('')
}

// Bind tag-input handlers (only for hype + blacklist)
document.querySelectorAll('.tag-input').forEach(input => {
  input.addEventListener('keydown', e => {
    const field = input.dataset.for
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addFreeTag(field, input.value)
      input.value = ''
    } else if (e.key === 'Backspace' && input.value === '') {
      const key = FILTER_FIELDS[field].key
      if (filterState && filterState[key]?.length) {
        filterState[key].pop()
        renderFreeTags(field)
      }
    }
  })
  input.addEventListener('blur', () => {
    const field = input.dataset.for
    if (input.value.trim()) {
      addFreeTag(field, input.value)
      input.value = ''
    }
  })
})

// Click inside tag-wrap → focus input
document.querySelectorAll('.fe-tag-wrap').forEach(wrap => {
  wrap.addEventListener('click', e => {
    const inp = wrap.querySelector('.tag-input')
    if (inp && e.target === wrap) inp.focus()
  })
})

// Clear buttons
document.querySelectorAll('.fe-clear-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const field = btn.dataset.clear
    if (!filterState || !FILTER_FIELDS[field]) return
    filterState[FILTER_FIELDS[field].key] = []
    if (field === 'sizes' || field === 'brands') {
      renderTagsForDropdown(field)
      // Reset dropdown visual state if open
      const listEl = document.getElementById(field + '-list')
      if (listEl) {
        listEl.querySelectorAll('.fe-dropdown-item').forEach(item => {
          item.classList.remove('selected')
          item.querySelector('.check').innerHTML = ''
        })
      }
    } else {
      renderFreeTags(field)
    }
    setFiltersStatus('')
  })
})

// Price input sync
;['f-min-price', 'f-max-price'].forEach(id => {
  document.getElementById(id).addEventListener('input', e => {
    if (!filterState) return
    const key = id === 'f-min-price' ? 'min_price' : 'max_price'
    const v = parseFloat(e.target.value)
    filterState[key] = isNaN(v) ? null : v
    setFiltersStatus('')
  })
})

// ══════════════════════════════════════════════════════════════════════
//  Multi-Config flow: List (up to 3) → Editor → Save via Supabase
// ══════════════════════════════════════════════════════════════════════

const MAX_CONFIGS = 3

// Cache of configs loaded from bridge
let configsCache = []
// Which config is currently being edited ({ id, name } meta)
let editingMeta  = { id: null, name: '' }

function setScreenBusy(screenId, msg) {
  // Lightweight: set the filters-status if the filter screen is active
  const el = document.getElementById('filters-status')
  if (el && screenId === 'screen-filters') {
    el.textContent = msg || ''
    el.className = 'filters-status'
  }
}

function formatConfigMeta(cfg) {
  const tags = (cfg.core_brands?.length || 0) +
               (cfg.hype_keywords?.length || 0) +
               (cfg.blacklist?.length || 0) +
               (cfg.permitted_sizes?.length || 0)
  const price = `${Number(cfg.price_min).toFixed(0)}–${Number(cfg.price_max).toFixed(0)}€`
  return `${tags} TAGS · ${price}`
}

function renderConfigList() {
  const list = document.getElementById('config-list')
  list.innerHTML = ''

  // Existing configs
  configsCache.forEach(cfg => {
    const card = document.createElement('div')
    card.className = 'config-card' + (cfg.is_active ? ' active' : '')

    card.innerHTML = `
      <span class="config-dot"></span>
      <div class="config-info">
        <div class="config-name">${escapeHtml(cfg.name || 'Unnamed')}</div>
        <div class="config-meta">${escapeHtml(formatConfigMeta(cfg))}</div>
      </div>
      <div class="config-actions">
        ${cfg.is_active ? '' : `<button class="config-icon-btn" data-act="activate" title="Activate">▶</button>`}
        <button class="config-icon-btn danger" data-act="delete" title="Delete">×</button>
      </div>
    `

    // Main click → edit in filter window
    card.addEventListener('click', (e) => {
      if (e.target.closest('[data-act]')) return
      openFilterWindowEdit(cfg)
    })

    // Action buttons
    card.querySelectorAll('[data-act]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation()
        const act = btn.dataset.act
        if (act === 'activate') {
          btn.disabled = true
          const res = await window.api.activateConfig(cfg.id)
          if (res?.ok) { await loadConfigList() }
          else { btn.disabled = false }
        } else if (act === 'delete') {
          if (!confirm(`Delete "${cfg.name}"?`)) return
          btn.disabled = true
          const res = await window.api.deleteConfig(cfg.id)
          if (res?.ok) { await loadConfigList() }
          else { btn.disabled = false }
        }
      })
    })

    list.appendChild(card)
  })

  // Empty slots (up to MAX_CONFIGS total)
  const emptySlots = MAX_CONFIGS - configsCache.length
  for (let i = 0; i < emptySlots; i++) {
    const empty = document.createElement('div')
    empty.className = 'config-card empty'
    empty.textContent = '+ New Profile'
    empty.addEventListener('click', () => openFilterWindowNew())
    list.appendChild(empty)
  }
}

async function loadConfigList() {
  const list = document.getElementById('config-list')
  list.innerHTML = '<div class="config-card empty">loading…</div>'
  try {
    const res = await window.api.listConfigs()
    configsCache = res?.configs || []
  } catch (_) {
    configsCache = []
  }
  renderConfigList()
}

// ── Filter window helpers ─────────────────────────────────────────────────────

function openFilterWindowNew() {
  window.api.openFilterWindow({
    id: null, name: '',
    permitted_sizes: [], core_brands: [], hype_keywords: [], blacklist: [],
    price_min: null, price_max: null,
  })
}

function openFilterWindowEdit(cfg) {
  window.api.openFilterWindow({
    id:              cfg.id,
    name:            cfg.name || '',
    permitted_sizes: cfg.permitted_sizes || [],
    core_brands:     cfg.core_brands     || [],
    hype_keywords:   cfg.hype_keywords   || [],
    blacklist:       cfg.blacklist       || [],
    price_min:       cfg.price_min != null ? Number(cfg.price_min) : null,
    price_max:       cfg.price_max != null ? Number(cfg.price_max) : null,
  })
}

// Refresh config list when filter window closes
window.api.onFilterWindowClosed(() => {
  if (document.getElementById('screen-configs').classList.contains('active')) {
    loadConfigList()
  }
})

// When "Save & Start Bot" is triggered from filter window → go to key screen
window.api.onStartBotFromFilter(() => {
  document.getElementById('key-status').textContent = ''
  document.getElementById('key-input').value = ''
  show('screen-key')
  setTimeout(() => document.getElementById('key-input').focus(), 80)
})



function openEditor(cfg) {
  // Close any open dropdown first
  if (openDropdown) closeDropdown(openDropdown)

  if (cfg) {
    editingMeta = { id: cfg.id, name: cfg.name }
    filterState = {
      permitted_sizes: [...(cfg.permitted_sizes || [])],
      core_brands:     [...(cfg.core_brands     || [])],
      hype_keywords:   [...(cfg.hype_keywords   || [])],
      blacklist:       [...(cfg.blacklist       || [])],
      min_price:       cfg.price_min != null ? Number(cfg.price_min) : null,
      max_price:       cfg.price_max != null ? Number(cfg.price_max) : null,
    }
    document.getElementById('filters-title').textContent = 'Edit profile'
  } else {
    editingMeta = { id: null, name: '' }
    // New profile: completely empty — defaults only run as fallback in the bot
    filterState = JSON.parse(JSON.stringify(EMPTY_FILTERS))
    document.getElementById('filters-title').textContent = 'New profile'
  }
  document.getElementById('f-name').value = editingMeta.name || ''
  renderAllFilters()
  setFiltersStatus('')
  show('screen-filters')
}

// Menu button → open the list screen
document.getElementById('btn-go-filters').addEventListener('click', async () => {
  show('screen-configs')
  await loadConfigList()
})

document.getElementById('btn-configs-back').addEventListener('click', () => show('screen-menu'))

// Name input → update editingMeta
document.getElementById('f-name').addEventListener('input', (e) => {
  editingMeta.name = e.target.value
})

document.getElementById('btn-save-filters').addEventListener('click', async () => {
  if (!filterState) return

  const name = (editingMeta.name || '').trim()
  if (!name) { setFiltersStatus('Name required', 'err'); return }

  // Validate prices
  const minP = parseFloat(filterState.min_price)
  const maxP = parseFloat(filterState.max_price)
  if (isNaN(minP) || isNaN(maxP) || minP < 0 || maxP <= minP) {
    setFiltersStatus('Invalid price range', 'err')
    return
  }

  setFiltersStatus('Saving…')

  const payload = {
    hype_keywords:   filterState.hype_keywords   || [],
    core_brands:     filterState.core_brands     || [],
    blacklist:       filterState.blacklist       || [],
    permitted_sizes: filterState.permitted_sizes || [],
    price_min:       minP,
    price_max:       maxP,
  }

  try {
    const res = await window.api.saveConfig(editingMeta.id, name, payload)
    if (res?.ok) {
      setFiltersStatus('Saved ✓', 'ok')
      // If new, remember the id so subsequent saves update instead of creating
      if (res.config?.id) editingMeta.id = res.config.id
      // Refresh cache quietly
      loadConfigList()
    } else {
      setFiltersStatus(res?.message || 'Save failed', 'err')
    }
  } catch (e) {
    setFiltersStatus('Save failed', 'err')
  }
})

document.getElementById('btn-reset-filters').addEventListener('click', () => {
  filterState = JSON.parse(JSON.stringify(EMPTY_FILTERS))
  if (openDropdown) closeDropdown(openDropdown)
  renderAllFilters()
  setFiltersStatus('Cleared — Save to apply')
})

document.getElementById('btn-filters-back').addEventListener('click', () => { if (openDropdown) closeDropdown(openDropdown); show('screen-configs') })

document.getElementById('key-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') submitKey()
})
// Live-Auto-Formatierung: schreibt Bindestriche automatisch, hält Caret am Ende
document.getElementById('key-input').addEventListener('input', e => {
  const el  = e.target
  const before = el.value
  const after  = formatLicenseKey(before)
  if (before !== after) {
    el.value = after
    // Caret immer ans Ende — einfachste Lösung, passt für dieses Format
    el.setSelectionRange(after.length, after.length)
  }
})
document.getElementById('btn-submit-key').addEventListener('click', submitKey)

async function submitKey() {
  const key = document.getElementById('key-input').value.trim()
  if (!key) return
  const statusEl = document.getElementById('key-status')
  statusEl.textContent = 'Checking key…'
  statusEl.className   = 'status'
  const res = await window.api.checkLicense(key)
  if (res?.valid) {
    showLaunch(res.info, key)
  } else {
    statusEl.textContent = res?.info || 'Invalid key.'
    statusEl.className   = 'status err'
  }
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function showToast() {
  const t = document.getElementById('toast')
  t.classList.remove('hide')
  t.classList.add('show')
  setTimeout(() => {
    t.classList.add('hide')
    t.classList.remove('show')
  }, 7000)
}

let pollInterval = null
let pollStartTime = null

function stopPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null }
}

function setBotStatus(msg) {
  const el = document.getElementById('launch-bot-status')
  if (el) el.textContent = msg
}

function setBotError(msg) {
  const errEl = document.getElementById('launch-bot-error')
  const statusEl = document.getElementById('launch-bot-status')
  if (errEl) { errEl.textContent = msg; errEl.style.display = 'block' }
  if (statusEl) statusEl.textContent = ''
}

function startPolling() {
  stopPolling()
  pollStartTime = Date.now()
  setBotStatus('connecting…')

  pollInterval = setInterval(async () => {
    if (!botRunning) { stopPolling(); return }

    const elapsed = Math.floor((Date.now() - pollStartTime) / 1000)

    if (elapsed > 45) {
      stopPolling()
      // Diagnose vom Bridge holen
      try {
        const diag = await window.api.getBotError()
        const lines = []
        if (diag?.chromium_path) lines.push(`CHROMIUM: ${diag.chromium_path}`)
        if (diag?.bot_exists === false) lines.push('BOT EXE: NICHT GEFUNDEN')
        if (diag?.running === false) lines.push('BOT PROZESS: NICHT AKTIV')
        const diagText = lines.length ? lines.join('\n') : ''
        setBotError('BOT KONNTE NICHT STARTEN — App neu starten.\n' + diagText)
      } catch(_) {
        setBotError('BOT KONNTE NICHT STARTEN — App neu starten.\nSupport kontaktieren falls Problem weiterbesteht.')
      }
      return
    }

    if (elapsed < 10)      setBotStatus('connecting…')
    else if (elapsed < 20) setBotStatus('fetching cookies…')
    else if (elapsed < 35) setBotStatus('waiting for discord…')
    else                   setBotStatus('almost there…')

    try {
      const res = await window.api.pollStatus()
      if (res?.first_item_found) {
        stopPolling()
        setBotStatus('')
        document.getElementById('launch-bot-starting').style.display = 'none'
        document.getElementById('launch-bot-active').style.display   = 'block'
        playSuccessChime()
        showToast()
      }
    } catch (_) {}
  }, 1000)
}

function renderLaunchInfo(info) {
  const el = document.getElementById('launch-info')
  if (!info) { el.innerHTML = ''; return }

  // Expected patterns from bridge.py:
  //   "Valid for 14 more days"
  //   "Valid for 1 more day"
  //   "Activated — expires on 22.05.2026"
  //   fallback: any other string

  let label = 'Status'
  let valueHtml = escapeHtml(info)

  const validMatch = info.match(/^Valid for (\d+) more (day|days)$/i)
  if (validMatch) {
    label = 'Remaining'
    const n = validMatch[1]
    const unit = validMatch[2].toLowerCase()
    valueHtml = `<span class="num">${n}</span> ${unit}`
  } else {
    const expiresMatch = info.match(/^Activated\s*[—-]\s*expires on (.+)$/i)
    if (expiresMatch) {
      label = 'Expires'
      valueHtml = `<span class="num">${escapeHtml(expiresMatch[1])}</span>`
    }
  }

  el.innerHTML = `
    <div class="launch-info-label">${escapeHtml(label)}</div>
    <div class="launch-info-value">${valueHtml}</div>
  `
}

function showLaunch(info, key) {
  console.log('[renderer] showLaunch key:', key, 'botRunning:', botRunning)
  savedKey = key
  botRunning = false  // ← reset so bot always starts fresh
  renderLaunchInfo(info)

  // Reset layers
  const licenseLayer = document.getElementById('launch-license-layer')
  const socialsLayer  = document.getElementById('launch-socials-layer')
  licenseLayer.style.opacity      = '1'
  licenseLayer.style.display      = 'flex'
  socialsLayer.style.opacity      = '0'
  socialsLayer.style.pointerEvents = 'none'

  document.getElementById('launch-bot-starting').style.display = 'flex'
  document.getElementById('launch-bot-active').style.display   = 'none'

  show('screen-launch')

  // After 2s: crossfade license → socials
  setTimeout(() => {
    licenseLayer.style.opacity      = '0'
    setTimeout(() => {
      licenseLayer.style.display       = 'none'
      socialsLayer.style.opacity       = '1'
      socialsLayer.style.pointerEvents = 'auto'
    }, 700)
  }, 2000)

  setTimeout(async () => {
    console.log('[renderer] startBot called, key:', key, 'botRunning:', botRunning)
    if (!botRunning) {
      botRunning = true
      try {
        const res = await window.api.startBot(key)
        console.log('[renderer] startBot response:', JSON.stringify(res))
      } catch(e) {
        console.error('[renderer] startBot error:', e)
      }
      if (botRunning) startPolling()
    }
  }, 1400)
}

// ── Intro: 2s Fade-In + Startup Chime ─────────────────────────────────────────
function playStartupChime() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext
    if (!AC) return
    const ctx = new AC()
    const now = ctx.currentTime

    // ── Master bus + sanfter Reverb-Ersatz (FeedbackDelay) ────────────────
    const master = ctx.createGain()
    master.gain.value = 0.28
    master.connect(ctx.destination)

    // Kurzer FeedbackDelay gibt räumliches "Hallen" ohne ConvolverReverb-Datei
    const delay = ctx.createDelay(0.5)
    delay.delayTime.value = 0.18
    const delayFb = ctx.createGain()
    delayFb.gain.value = 0.28
    const delayMix = ctx.createGain()
    delayMix.gain.value = 0.35
    delay.connect(delayFb).connect(delay)
    delay.connect(delayMix).connect(master)

    // Master-Lowpass — nimmt Schärfe raus, gibt "premium" Gefühl
    const tone = ctx.createBiquadFilter()
    tone.type = 'lowpass'
    tone.frequency.value = 4500
    tone.Q.value = 0.5
    tone.connect(master)
    tone.connect(delay)

    // ── Layer 1: Sub-Bass Drone (A1) — gibt Fundament ────────────────────
    const subOsc = ctx.createOscillator()
    const subGain = ctx.createGain()
    subOsc.type = 'sine'
    subOsc.frequency.value = 55  // A1
    subGain.gain.setValueAtTime(0.0001, now)
    subGain.gain.exponentialRampToValueAtTime(0.55, now + 0.8)
    subGain.gain.exponentialRampToValueAtTime(0.0001, now + 3.8)
    subOsc.connect(subGain).connect(tone)
    subOsc.start(now); subOsc.stop(now + 3.9)

    // ── Layer 2: Haupt-Pad — A-moll add9 Akkord, sanft gesweept ──────────
    // Noten: A2 (110), E3 (164.81), A3 (220), B3 (246.94), E4 (329.63)
    const padNotes = [110, 164.81, 220, 246.94, 329.63]
    const padFilter = ctx.createBiquadFilter()
    padFilter.type = 'lowpass'
    padFilter.Q.value = 1.2
    // Filter-Sweep: startet dunkel, öffnet sanft
    padFilter.frequency.setValueAtTime(400, now)
    padFilter.frequency.exponentialRampToValueAtTime(2800, now + 1.9)
    padFilter.frequency.exponentialRampToValueAtTime(1800, now + 3.5)
    padFilter.connect(tone)

    const padGain = ctx.createGain()
    padGain.gain.setValueAtTime(0.0001, now)
    padGain.gain.exponentialRampToValueAtTime(0.22, now + 1.0)
    padGain.gain.exponentialRampToValueAtTime(0.12, now + 2.4)
    padGain.gain.exponentialRampToValueAtTime(0.0001, now + 3.8)
    padGain.connect(padFilter)

    padNotes.forEach((freq, i) => {
      // Zwei leicht verstimmte Oszillatoren pro Note = Chorus-Breite
      ;[0, 1].forEach(detune => {
        const osc = ctx.createOscillator()
        osc.type = 'triangle'  // wärmer als sine, weniger harsh als saw
        osc.frequency.value = freq
        osc.detune.value = detune === 0 ? -6 : 6
        // Staffel-Einstieg der Akkord-Töne für "auffächern"-Effekt
        const entryDelay = i * 0.06
        const g = ctx.createGain()
        g.gain.setValueAtTime(0.0001, now)
        g.gain.setValueAtTime(0.0001, now + entryDelay)
        g.gain.exponentialRampToValueAtTime(0.18, now + entryDelay + 0.4)
        g.gain.exponentialRampToValueAtTime(0.0001, now + 3.8)
        osc.connect(g).connect(padGain)
        osc.start(now); osc.stop(now + 3.9)
      })
    })

    // ── Layer 3: Bell Shimmer — hoher A5 + E6 mit schnellem Attack ───────
    const bellFreqs = [880, 1318.5]  // A5, E6
    bellFreqs.forEach((freq, i) => {
      const t0 = now + 0.6 + i * 0.24
      const osc = ctx.createOscillator()
      const g = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.value = freq

      g.gain.setValueAtTime(0.0001, t0)
      g.gain.linearRampToValueAtTime(0.08, t0 + 0.015)  // schneller Attack = Bell
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + 2.2)

      // Leichte Harmonische für Glanz
      const h = ctx.createOscillator()
      const hg = ctx.createGain()
      h.type = 'sine'
      h.frequency.value = freq * 3
      hg.gain.setValueAtTime(0.0001, t0)
      hg.gain.linearRampToValueAtTime(0.012, t0 + 0.015)
      hg.gain.exponentialRampToValueAtTime(0.0001, t0 + 1.1)

      osc.connect(g).connect(tone)
      h.connect(hg).connect(tone)
      osc.start(t0); osc.stop(t0 + 2.3)
      h.start(t0); h.stop(t0 + 1.15)
    })

    // ── Layer 4: Air/Breath — gefiltertes Rauschen gibt "Atem" ───────────
    const noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 3, ctx.sampleRate)
    const nData = noiseBuf.getChannelData(0)
    for (let i = 0; i < nData.length; i++) nData[i] = (Math.random() * 2 - 1) * 0.5
    const noise = ctx.createBufferSource()
    noise.buffer = noiseBuf
    const noiseFilter = ctx.createBiquadFilter()
    noiseFilter.type = 'bandpass'
    noiseFilter.frequency.value = 2200
    noiseFilter.Q.value = 0.8
    const noiseGain = ctx.createGain()
    noiseGain.gain.setValueAtTime(0.0001, now)
    noiseGain.gain.exponentialRampToValueAtTime(0.025, now + 0.8)
    noiseGain.gain.exponentialRampToValueAtTime(0.0001, now + 3.3)
    noise.connect(noiseFilter).connect(noiseGain).connect(tone)
    noise.start(now); noise.stop(now + 3.4)

    // Nach dem Ausklang alles sauber schließen
    setTimeout(() => { try { ctx.close() } catch (_) {} }, 5000)
  } catch (_) { /* Audio nicht verfügbar → stumm starten */ }
}

// ── Success Chime: spielt wenn "Ilumia aktiv" erscheint ──────────────────────
function playSuccessChime() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext
    if (!AC) return
    const ctx = new AC()
    const now = ctx.currentTime

    // Master mit leichtem FeedbackDelay für Räumlichkeit
    const master = ctx.createGain()
    master.gain.value = 0.22
    master.connect(ctx.destination)

    const delay = ctx.createDelay(0.4)
    delay.delayTime.value = 0.14
    const delayFb = ctx.createGain()
    delayFb.gain.value = 0.22
    const delayMix = ctx.createGain()
    delayMix.gain.value = 0.25
    delay.connect(delayFb).connect(delay)
    delay.connect(delayMix).connect(master)

    const tone = ctx.createBiquadFilter()
    tone.type = 'lowpass'
    tone.frequency.value = 5500
    tone.Q.value = 0.4
    tone.connect(master)
    tone.connect(delay)

    // Zwei aufsteigende Töne: E5 (659.25) → B5 (987.77) — offene Quinte, positiv
    const notes = [
      { freq: 659.25, start: 0.00, dur: 1.4 },
      { freq: 987.77, start: 0.12, dur: 1.6 },
    ]

    notes.forEach(n => {
      const t0 = now + n.start

      // Grundton — triangle für Wärme
      const osc = ctx.createOscillator()
      const g = ctx.createGain()
      osc.type = 'triangle'
      osc.frequency.value = n.freq

      g.gain.setValueAtTime(0.0001, t0)
      g.gain.linearRampToValueAtTime(0.22, t0 + 0.025)  // schneller Attack
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + n.dur)

      // Zweite Harmonische für Glanz
      const h = ctx.createOscillator()
      const hg = ctx.createGain()
      h.type = 'sine'
      h.frequency.value = n.freq * 2
      hg.gain.setValueAtTime(0.0001, t0)
      hg.gain.linearRampToValueAtTime(0.055, t0 + 0.025)
      hg.gain.exponentialRampToValueAtTime(0.0001, t0 + n.dur * 0.7)

      osc.connect(g).connect(tone)
      h.connect(hg).connect(tone)
      osc.start(t0); osc.stop(t0 + n.dur + 0.05)
      h.start(t0); h.stop(t0 + n.dur * 0.7 + 0.05)
    })

    // Sanfter Shimmer oben drauf (E6) — kurz, wie ein Funke
    const shimmerT = now + 0.35
    const shimmer = ctx.createOscillator()
    const shimmerGain = ctx.createGain()
    shimmer.type = 'sine'
    shimmer.frequency.value = 1318.51  // E6
    shimmerGain.gain.setValueAtTime(0.0001, shimmerT)
    shimmerGain.gain.linearRampToValueAtTime(0.06, shimmerT + 0.01)
    shimmerGain.gain.exponentialRampToValueAtTime(0.0001, shimmerT + 0.9)
    shimmer.connect(shimmerGain).connect(tone)
    shimmer.start(shimmerT); shimmer.stop(shimmerT + 1.0)

    // Nach dem Ausklang sauber schließen
    setTimeout(() => { try { ctx.close() } catch (_) {} }, 2500)
  } catch (_) { /* Audio nicht verfügbar → stumm */ }
}

function runIntro() {
  const veil = document.getElementById('intro-veil')
  if (!veil) return

  // Kurzer Delay damit Browser die Start-Opacity commitet, dann Fade starten
  requestAnimationFrame(() => {
    setTimeout(() => {
      veil.classList.add('lift')
      playStartupChime()
    }, 50)
  })

  // Veil nach dem Fade entfernen, damit er keine Klicks blockiert
  setTimeout(() => { veil?.remove() }, 3200)
}

runIntro()
boot()