'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('marvinDesktop', Object.freeze({
  status: () => ipcRenderer.invoke('marvin:status'),
  start: () => ipcRenderer.invoke('marvin:start'),
  stop: () => ipcRenderer.invoke('marvin:stop'),
  openMain: () => ipcRenderer.invoke('marvin:open-main'),
  setWindowMode: (mode) => ipcRenderer.invoke('marvin:window-mode', mode === 'compact' ? 'compact' : 'expanded'),
  startResize: (edge) => ipcRenderer.send('marvin:resize-start', String(edge)),
  stopResize: () => ipcRenderer.send('marvin:resize-stop'),
  minimize: () => ipcRenderer.invoke('marvin:minimize'),
  quit: () => ipcRenderer.invoke('marvin:quit-avatar'),
}));
