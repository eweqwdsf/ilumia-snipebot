const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('api', {
  getAppVersion:  ()      => ipcRenderer.invoke('get-app-version'),
  getHwid:        ()      => ipcRenderer.invoke('get-hwid'),
  checkLicense:   (key)   => ipcRenderer.invoke('check-license', key),
  checkUpdate:    ()      => ipcRenderer.invoke('check-update'),
  startBot:       (key, url, ver) => ipcRenderer.invoke('start-bot', key, url, ver),
  pollStatus:     ()      => ipcRenderer.invoke('poll-status'),
  closeWindow:    ()      => ipcRenderer.invoke('window-close'),
  minimizeWindow: ()      => ipcRenderer.invoke('window-minimize'),
  restartApp:     ()      => ipcRenderer.invoke('restart-app'),
})