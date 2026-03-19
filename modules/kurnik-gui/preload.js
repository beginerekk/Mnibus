'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('kurnik', {
  // wywołania do main
  getGames:    ()       => ipcRenderer.invoke('get-games'),
  connect:     (opts)   => ipcRenderer.invoke('connect', opts),
  joinTable:   (opts)   => ipcRenderer.invoke('join-table', opts),
  sendChat:    (opts)   => ipcRenderer.invoke('send-chat', opts),
  disconnect:  ()       => ipcRenderer.invoke('disconnect'),

  // push z main do renderer
  onWsStatus:     (fn) => ipcRenderer.on('ws-status',     (_e, d) => fn(d)),
  onWsError:      (fn) => ipcRenderer.on('ws-error',      (_e, d) => fn(d)),
  onTables:       (fn) => ipcRenderer.on('tables',        (_e, d) => fn(d)),
  onMessage:      (fn) => ipcRenderer.on('message',       (_e, d) => fn(d)),
  onSessionResult:(fn) => ipcRenderer.on('session-result',(_e, d) => fn(d)),
});
