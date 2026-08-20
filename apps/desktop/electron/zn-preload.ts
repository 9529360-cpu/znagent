import { contextBridge, ipcRenderer } from 'electron'

// Preserve the mature compatibility bridge while giving new ZN surfaces their
// own namespace. New product code should prefer window.znDesktop.
import './preload'

contextBridge.exposeInMainWorld('znDesktop', {
  resident: {
    start: () => ipcRenderer.invoke('zn:resident:start'),
    stop: () => ipcRenderer.invoke('zn:resident:stop'),
    status: () => ipcRenderer.invoke('zn:resident:status'),
    self: () => ipcRenderer.invoke('zn:resident:self'),
    pulses: limit => ipcRenderer.invoke('zn:resident:pulses', limit),
    thoughts: limit => ipcRenderer.invoke('zn:resident:thoughts', limit),
    submit: payload => ipcRenderer.invoke('zn:resident:submit', payload),
    remember: payload => ipcRenderer.invoke('zn:resident:remember', payload),
    forget: key => ipcRenderer.invoke('zn:resident:forget', key)
  }
})
