const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('api', {
  getAppVersion:  ()      => ipcRenderer.invoke('get-app-version'),
  getHwid:        ()      => ipcRenderer.invoke('get-hwid'),
  checkLicense:   (key)   => ipcRenderer.invoke('check-license', key),
  startBot:       (key)   => ipcRenderer.invoke('start-bot', key),
  pollStatus:     ()      => ipcRenderer.invoke('poll-status'),
  getBotError:    ()      => ipcRenderer.invoke('get-bot-error'),
  closeWindow:    ()      => ipcRenderer.invoke('window-close'),
  minimizeWindow: ()      => ipcRenderer.invoke('window-minimize'),

  // ── Filter configs ─────────────────────────────────────────
  listConfigs:    ()                  => ipcRenderer.invoke('list-configs'),
  saveConfig:     (id, name, data)    => ipcRenderer.invoke('save-config', { id, name, data }),
  deleteConfig:   (id)                => ipcRenderer.invoke('delete-config', id),
  activateConfig: (id)                => ipcRenderer.invoke('activate-config', id),

  // ── Filter window ──────────────────────────────────────────
  openFilterWindow:     (state)           => ipcRenderer.invoke('open-filter-window', state),
  getFilterWindowState: ()                => ipcRenderer.invoke('get-filter-window-state'),
  closeFilterWindow:    ()                => ipcRenderer.invoke('close-filter-window'),
  minimizeFilterWindow: ()                => ipcRenderer.invoke('minimize-filter-window'),
  saveFilterConfig:     (id, name, data)  => ipcRenderer.invoke('save-filter-config', { id, name, data }),
  saveAndStartBot:      (configId)        => ipcRenderer.invoke('save-and-start-bot', configId),

  // ── Main-process → renderer events ────────────────────────
  onFilterWindowClosed: (cb)  => ipcRenderer.on('filter-window-closed', cb),
  onStartBotFromFilter: (cb)  => ipcRenderer.on('start-bot-from-filter', cb),
})