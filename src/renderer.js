// ============================================================
//  ILUMIA Launcher — renderer.js
// ============================================================

const W = 720, H = 580

// Version wird beim Boot via IPC geladen
let CURRENT_VERSION = 'v1.0.0'

const SCREENS_WITH_BACK = ['screen-hwid', 'screen-key', 'screen-launch']

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
let pendingUpdate = null   // stores { url, version } from checkUpdate

document.getElementById('version-tag').textContent = CURRENT_VERSION

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

  setLoadingText('Suche nach Updates…')
  show('screen-loading')

  let updateData = null
  try { updateData = await window.api.checkUpdate() } catch (_) {}

  if (updateData?.has_update) {
    pendingUpdate = { url: updateData.url, version: updateData.version }
    document.getElementById('update-ver-current').textContent = CURRENT_VERSION
    document.getElementById('update-ver-new').textContent     = updateData.version
    show('screen-update')
    return
  }

  setLoadingText('Prüfe gespeicherten Key…')
  try {
    const res = await window.api.checkLicense('__load_saved__')
    if (res?.valid) { showLaunch(res.info, res.key); return }
  } catch (_) {}

  show('screen-menu')
}

function setLoadingText(msg) {
  document.getElementById('loading-text').textContent = msg
}

document.getElementById('btn-do-update').addEventListener('click', async () => {
  const wrap      = document.getElementById('update-progress-wrap')
  const bar       = document.getElementById('update-progress-bar')
  const pct       = document.getElementById('update-progress-pct')
  const label     = document.getElementById('update-progress-label')
  const btnUpdate  = document.getElementById('btn-do-update')
  const btnSkip    = document.getElementById('btn-skip-update')
  const btnRestart = document.getElementById('btn-restart-update')

  wrap.style.display  = 'flex'
  btnUpdate.disabled  = true
  btnSkip.disabled    = true
  btnUpdate.style.opacity = '0.4'
  btnSkip.style.opacity   = '0.4'

  let progress = 0
  const simulateFill = setInterval(() => {
    if (progress < 85) {
      progress += (Math.random() * 3.5 + 0.8)
      if (progress > 85) progress = 85
      bar.style.width = progress.toFixed(1) + '%'
      pct.textContent = Math.round(progress) + '%'
    }
  }, 120)

  try {
    const url = pendingUpdate?.url || ''
    const ver = pendingUpdate?.version || ''
    await window.api.startBot('__update__', url, ver)
  } catch (_) {}

  clearInterval(simulateFill)

  bar.style.width   = '100%'
  pct.textContent   = '100%'
  label.textContent = 'Abgeschlossen — Installer wird gestartet…'
  label.style.color = 'rgba(106,184,126,0.75)'

  // Show restart button
  btnRestart.style.display = 'block'
  btnRestart.textContent   = 'Jetzt installieren & schließen'
  btnSkip.disabled         = false
  btnSkip.style.opacity    = '1'
})

document.getElementById('btn-restart-update').addEventListener('click', () => {
  window.api.closeWindow()  // App schließen — Installer läuft bereits im Hintergrund
})
document.getElementById('btn-skip-update').addEventListener('click', () => show('screen-menu'))

document.getElementById('btn-go-key').addEventListener('click', () => {
  document.getElementById('key-status').textContent = ''
  document.getElementById('key-input').value = ''
  show('screen-key')
  setTimeout(() => document.getElementById('key-input').focus(), 50)
})

document.getElementById('btn-go-hwid').addEventListener('click', async () => {
  show('screen-hwid')
  if (!cachedHwid) {
    document.getElementById('hwid-display').textContent = 'Lade…'
    const res = await window.api.getHwid()
    cachedHwid = res?.hwid || 'Fehler'
  }
  const short = cachedHwid.slice(0, 22) + '…' + cachedHwid.slice(-8)
  document.getElementById('hwid-display').textContent = short
})

document.getElementById('btn-copy-hwid').addEventListener('click', () => {
  if (!cachedHwid) return
  navigator.clipboard.writeText(cachedHwid)
  const hint = document.getElementById('copy-hint')
  hint.textContent = 'kopiert ✓'
  setTimeout(() => { hint.textContent = '' }, 1600)
})
document.getElementById('btn-hwid-back').addEventListener('click', () => show('screen-menu'))

document.getElementById('btn-key-back').addEventListener('click', () => show('screen-menu'))
document.getElementById('key-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') submitKey()
})
document.getElementById('btn-submit-key').addEventListener('click', submitKey)

async function submitKey() {
  const key = document.getElementById('key-input').value.trim()
  if (!key) return
  const statusEl = document.getElementById('key-status')
  statusEl.textContent = 'Prüfe Key…'
  statusEl.className   = 'status'
  const res = await window.api.checkLicense(key)
  if (res?.valid) {
    showLaunch(res.info, key)
  } else {
    statusEl.textContent = res?.info || 'Ungültiger Key.'
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

function stopPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null }
}

function startPolling() {
  stopPolling()
  pollInterval = setInterval(async () => {
    if (!botRunning) { stopPolling(); return }
    try {
      const res = await window.api.pollStatus()
      if (res?.first_item_found) {
        stopPolling()
        document.getElementById('launch-bot-starting').style.display = 'none'
        document.getElementById('launch-bot-active').style.display   = 'block'
        showToast()
      }
    } catch (_) {}
  }, 1000)  // Schneller polling: 1s statt 2s
}

function showLaunch(info, key) {
  console.log('[renderer] showLaunch key:', key, 'botRunning:', botRunning)
  savedKey = key
  botRunning = false  // ← reset so bot always starts fresh
  document.getElementById('launch-info').textContent = info || ''

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

boot()