const { app, BrowserWindow, ipcMain } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const http = require('http')
const fs = require('fs')

// ── Config ────────────────────────────────────────────────────────────────────
const BRIDGE_PORT = 57421
let   mainWindow  = null
let   pyProcess   = null

// ── App identity ──────────────────────────────────────────────────────────────
app.setAppUserModelId('com.ilumia.snipebot')

// ── Find Python bridge executable ────────────────────────────────────────────
function getPythonPath() {
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, 'python', 'bridge.exe')
    if (fs.existsSync(exe)) return { cmd: exe, args: [] }
    return {
      cmd: 'python',
      args: [path.join(process.resourcesPath, 'python', 'bridge.py')]
    }
  }
  return {
    cmd: 'python',
    args: [path.join(__dirname, '..', 'python', 'bridge.py')]
  }
}

// ── Spawn Python bridge ───────────────────────────────────────────────────────
function startPythonBridge() {
  const { cmd, args } = getPythonPath()
  console.log('[main] Starting Python bridge:', cmd, args)

  pyProcess = spawn(cmd, args, {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, BRIDGE_PORT: String(BRIDGE_PORT) }
  })

  pyProcess.stdout.on('data', d => console.log('[py]', d.toString().trim()))
  pyProcess.stderr.on('data', d => console.error('[py:err]', d.toString().trim()))
  pyProcess.on('close', code => console.log('[py] exited with code', code))
}

// ── Helper: call Python bridge ────────────────────────────────────────────────
function callBridge(endpoint, body = {}) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body)
    const req = http.request({
      hostname: '127.0.0.1',
      port: BRIDGE_PORT,
      path: endpoint,
      method: 'POST',
      headers: {
        'Content-Type':   'application/json',
        'Content-Length': Buffer.byteLength(data)
      }
    }, res => {
      let raw = ''
      res.on('data', c => raw += c)
      res.on('end', () => {
        try { resolve(JSON.parse(raw)) }
        catch (e) { reject(e) }
      })
    })
    req.on('error', reject)
    req.write(data)
    req.end()
  })
}

// ── Wait for bridge to be ready ───────────────────────────────────────────────
function waitForBridge(retries = 20) {
  return new Promise((resolve, reject) => {
    const attempt = (n) => {
      callBridge('/ping')
        .then(() => resolve())
        .catch(() => {
          if (n <= 0) return reject(new Error('Bridge did not start'))
          setTimeout(() => attempt(n - 1), 300)
        })
    }
    attempt(retries)
  })
}

// ── Icon path helper ──────────────────────────────────────────────────────────
function getIconPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'assets', 'icon.ico')
  }
  return path.join(__dirname, '..', 'assets', 'icon.ico')
}

// ── Create window ─────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width:           720,
    height:          580,
    frame:           false,
    transparent:     false,
    resizable:       false,
    backgroundColor: '#000000',
    icon:            getIconPath(),
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
    }
  })

  mainWindow.loadFile(path.join(__dirname, 'index.html'))
  // mainWindow.webContents.openDevTools({ mode: 'detach' })  // DevTools deaktiviert
}

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  startPythonBridge()

  try {
    await waitForBridge()
    console.log('[main] Bridge ready')
  } catch (e) {
    console.error('[main] Bridge failed to start — opening anyway')
  }

  createWindow()
})

app.on('window-all-closed', () => {
  if (pyProcess) {
    pyProcess.kill('SIGTERM')
    setTimeout(() => app.quit(), 200)
  } else {
    app.quit()
  }
})

// ── IPC handlers ──────────────────────────────────────────────────────────────

ipcMain.handle('get-hwid', async () => {
  try { return await callBridge('/hwid') }
  catch (e) { return { error: e.message } }
})

ipcMain.handle('check-license', async (_e, key) => {
  console.log('[main] check-license key:', key)
  try { return await callBridge('/check-license', { key }) }
  catch (e) { return { valid: false, info: e.message } }
})

ipcMain.handle('check-update', async () => {
  try { return await callBridge('/check-update') }
  catch (e) { return { has_update: false } }
})

ipcMain.handle('start-bot', async (_e, key, url, ver) => {
  console.log('[main] start-bot key:', key)
  try {
    if (key === '__update__') {
      return await callBridge('/start-bot', { key, url, version: ver })
    }
    return await callBridge('/start-bot', { key })
  }
  catch (e) { return { ok: false, error: e.message } }
})

ipcMain.handle('poll-status', async () => {
  try { return await callBridge('/poll-status') }
  catch (e) { return { first_item_found: false } }
})

ipcMain.handle('window-close', () => {
  if (pyProcess) pyProcess.kill()
  app.quit()
})

ipcMain.handle('get-app-version', () => {
  try {
    const pkgPath = path.join(app.getAppPath(), 'package.json')
    return 'v' + JSON.parse(require('fs').readFileSync(pkgPath, 'utf8')).version
  } catch (e) {
    return 'v1.0.0'
  }
})

ipcMain.handle('restart-app', () => {
  if (pyProcess) {
    pyProcess.kill('SIGTERM')
    setTimeout(() => { app.relaunch(); app.exit(0) }, 500)
  } else {
    app.relaunch()
    app.exit(0)
  }
})

ipcMain.handle('window-minimize', () => {
  mainWindow?.minimize()
})