import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('znDesktop', {
  resident: {
    start: () => ipcRenderer.invoke('zn:resident:start'),
    stop: () => ipcRenderer.invoke('zn:resident:stop'),
    status: () => ipcRenderer.invoke('zn:resident:status'),
    self: () => ipcRenderer.invoke('zn:resident:self'),
    pulses: limit => ipcRenderer.invoke('zn:resident:pulses', limit),
    situations: limit => ipcRenderer.invoke('zn:resident:situations', limit),
    thoughts: limit => ipcRenderer.invoke('zn:resident:thoughts', limit),
    impasses: limit => ipcRenderer.invoke('zn:resident:impasses', limit),
    learning: limit => ipcRenderer.invoke('zn:resident:learning', limit),
    neural: limit => ipcRenderer.invoke('zn:resident:neural', limit),
    perceive: payload => ipcRenderer.invoke('zn:resident:perceive', payload),
    worldFollow: payload => ipcRenderer.invoke('zn:resident:world-follow', payload),
    worldFocuses: payload => ipcRenderer.invoke('zn:resident:world-focuses', payload || {}),
    worldObserve: payload => ipcRenderer.invoke('zn:resident:world-observe', payload),
    submit: payload => ipcRenderer.invoke('zn:resident:submit', payload),
    remember: payload => ipcRenderer.invoke('zn:resident:remember', payload),
    forget: key => ipcRenderer.invoke('zn:resident:forget', key)
  },
  updates: {
    check: () => ipcRenderer.invoke('zn:updates:check'),
    apply: () => ipcRenderer.invoke('zn:updates:apply')
  }
})
