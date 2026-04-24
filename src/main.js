const { app, BrowserWindow, ipcMain } = require('electron')
const { spawn, execSync } = require('child_process')
const path = require('path')
const http = require('http')
const fs = require('fs')

// ── Load .env für BRIDGE_SECRET ───────────────────────────────────────────────
const dotenv = require('dotenv')
dotenv.config({ path: path.join(__dirname, '..', 'python', '.env') })
const BRIDGE_SECRET = process.env.BRIDGE_SECRET || ''

// ── Config ────────────────────────────────────────────────────────────────────
const BRIDGE_PORT = 57421
let   mainWindow        = null
let   filterWindow      = null
let   pyProcess         = null
let   filterWindowState = null   // data passed from main → filter window

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
        'Content-Type':    'application/json',
        'Content-Length':  Buffer.byteLength(data),
        'X-Bridge-Secret': BRIDGE_SECRET
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

// ── Create filter window ──────────────────────────────────────────────────────
function createFilterWindow(state) {
  if (filterWindow && !filterWindow.isDestroyed()) {
    filterWindow.focus()
    return
  }
  filterWindowState = state || null

  filterWindow = new BrowserWindow({
    width:           720,
    height:          580,
    frame:           false,
    transparent:     false,
    resizable:       false,
    backgroundColor: '#000000',
    icon:            getIconPath(),
    parent:          mainWindow,
    modal:           false,
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
    }
  })

  filterWindow.loadFile(path.join(__dirname, 'filter-window.html'))

  filterWindow.on('closed', () => {
    filterWindow      = null
    filterWindowState = null
    // Refresh config list in main window
    mainWindow?.webContents?.send('filter-window-closed')
  })
}


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

// ── Robuster Python Cleanup ───────────────────────────────────────────────────
const PYTHON_TARGETS = ['bridge.exe', 'main_bot.exe', 'bridge.py', 'main_bot.py']

function killAllPythonInstances() {
  // 1. Graceful: /shutdown an Bridge senden
  try {
    const data = JSON.stringify({})
    const req = http.request({
      hostname: '127.0.0.1',
      port: BRIDGE_PORT,
      path: '/shutdown',
      method: 'POST',
      headers: {
        'Content-Type':    'application/json',
        'Content-Length':  Buffer.byteLength(data),
        'X-Bridge-Secret': BRIDGE_SECRET
      },
      timeout: 500
    })
    req.on('error', () => {})
    req.write(data)
    req.end()
  } catch (_) {}

  // 2. Force-Kill nach kurzem Warten
  const doKill = () => {
    // Child-Prozess-Baum beenden (bridge → main_bot → chromium)
    if (pyProcess?.pid) {
      try { execSync(`taskkill /PID ${pyProcess.pid} /T /F`, { stdio: 'ignore' }) } catch (_) {}
    }

    // Bekannte PyInstaller-Bundle-Namen killen
    for (const name of PYTHON_TARGETS) {
      try { execSync(`taskkill /IM "${name}" /F`, { stdio: 'ignore' }) } catch (_) {}
    }

    // python.exe Instanzen killen, die unsere Scripts laufen
    try {
      execSync(`wmic process where "name='python.exe' and commandline like '%bridge%'" delete`, { stdio: 'ignore' })
      execSync(`wmic process where "name='python.exe' and commandline like '%main_bot%'" delete`, { stdio: 'ignore' })
    } catch (_) {}

    pyProcess = null
    console.log('[main] Python cleanup done.')
  }

  setTimeout(doKill, 400)
}

// ── Cleanup einmalig ausführen (Sicherheitsschutz gegen Doppel-Calls) ─────────
let cleanupDone = false
function cleanupOnce() {
  if (cleanupDone) return
  cleanupDone = true
  console.log('[main] Cleanup triggered...')
  killAllPythonInstances()
}

// ── Alle Exit-Wege abfangen ───────────────────────────────────────────────────
app.on('window-all-closed', () => {
  cleanupOnce()
  setTimeout(() => app.quit(), 900)
})

app.on('before-quit', () => cleanupOnce())

process.on('exit',    () => cleanupOnce())
process.on('SIGINT',  () => { cleanupOnce(); process.exit(0) })
process.on('SIGTERM', () => { cleanupOnce(); process.exit(0) })

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

ipcMain.handle('start-bot', async (_e, key) => {
  console.log('[main] start-bot key:', key)
  try { return await callBridge('/start-bot', { key }) }
  catch (e) { return { ok: false, error: e.message } }
})

ipcMain.handle('poll-status', async () => {
  try { return await callBridge('/poll-status') }
  catch (e) { return { first_item_found: false } }
})

ipcMain.handle('get-bot-error', async () => {
  try { return await callBridge('/bot-error') }
  catch (e) { return { error: e.message } }
})

ipcMain.handle('window-close', () => {
  cleanupOnce()
  setTimeout(() => app.quit(), 900)
})

ipcMain.handle('get-app-version', () => {
  try {
    const pkgPath = path.join(app.getAppPath(), 'package.json')
    return 'v' + JSON.parse(fs.readFileSync(pkgPath, 'utf8')).version
  } catch (e) {
    return 'v1.0.0'
  }
})

ipcMain.handle('window-minimize', () => {
  mainWindow?.minimize()
})

// ── Config IPC handlers ───────────────────────────────────────────────────────

ipcMain.handle('list-configs', async () => {
  try { return await callBridge('/list-configs') }
  catch (e) { return { configs: [], max: 3, defaults: {} } }
})

ipcMain.handle('save-config', async (_e, { id, name, data }) => {
  try { return await callBridge('/save-config', { id, name, data }) }
  catch (e) { return { ok: false, message: e.message } }
})

ipcMain.handle('delete-config', async (_e, id) => {
  try { return await callBridge('/delete-config', { id }) }
  catch (e) { return { ok: false, message: e.message } }
})

ipcMain.handle('activate-config', async (_e, id) => {
  try { return await callBridge('/activate-config', { id }) }
  catch (e) { return { ok: false, message: e.message } }
})

// ── Filter Window IPC ─────────────────────────────────────────────────────────

ipcMain.handle('open-filter-window', async (_e, state) => {
  createFilterWindow(state)
  return { ok: true }
})

ipcMain.handle('get-filter-window-state', async () => {
  return filterWindowState || {}
})

ipcMain.handle('close-filter-window', () => {
  if (filterWindow && !filterWindow.isDestroyed()) {
    filterWindow.close()
  }
})

ipcMain.handle('minimize-filter-window', () => {
  filterWindow?.minimize()
})

ipcMain.handle('save-filter-config', async (_e, { id, name, data }) => {
  try { return await callBridge('/save-config', { id, name, data }) }
  catch (e) { return { ok: false, message: e.message } }
})

ipcMain.handle('save-and-start-bot', async (_e, configId) => {
  // Activate the config then signal the main window to navigate to bot start
  try {
    if (configId) await callBridge('/activate-config', { id: configId })
  } catch (_) {}
  mainWindow?.webContents?.send('start-bot-from-filter')
  return { ok: true }
})