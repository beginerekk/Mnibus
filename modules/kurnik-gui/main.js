'use strict';

const { app, BrowserWindow, ipcMain } = require('electron');
const WebSocket = require('ws');
const https     = require('https');
const path      = require('path');

// ─── stałe protokołu ──────────────────────────────────────────────────────────
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36';

const PING     = 1;
const PONG     = 2;
const TABLES   = 71;
const JOIN_TAB = 72;
const CHAT     = 81;

const IGNORE_CODES = new Set([18,20,22,23,24,25,27,28,30,31,32,51,70,74,72,88,90,92]);

const GAMES = {
  szachy:'Szachy', warcaby:'Warcaby', kalambury:'Kalambury',
  literaki:'Literaki', chinczyk:'Chińczyk', go:'Go',
  backgammon:'Backgammon', reversi:'Reversi', brydz:'Brydż',
  kierki:'Kierki', remik:'Remik', hex:'Hex', gomoku:'Gomoku', bierki:'Bierki',
};

// ─── stan sesji ───────────────────────────────────────────────────────────────
let mainWin    = null;
let ws         = null;
let cookies    = '';
let heartbeat  = null;
let currentTable = 0;

// ─── protokół ─────────────────────────────────────────────────────────────────
function encode(codes, strings) {
  let out = '{"i":[' + codes.join(',') + ']';
  if (strings && strings.length) {
    out += ',"s":["';
    for (let i = 0; i < strings.length; i++) {
      if (i) out += '","';
      out += strings[i].replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    }
    out += '"]';
  }
  return out + '}';
}

function decode(raw) {
  const results = [];
  const nl = raw.indexOf('\n');
  if (nl === -1) {
    try { const o = JSON.parse(raw); results.push({ i: o.i || [], s: o.s || [] }); } catch {}
    return results;
  }
  for (const line of raw.split('\n')) {
    if (!line) continue;
    try { const o = JSON.parse(line); results.push({ i: o.i || [], s: o.s || [] }); } catch {}
  }
  return results;
}

function parseTables(codes, strings) {
  const tables = [];
  const d = codes[1], m = codes[2];
  let f = 3, si = 0;
  while (f < codes.length && si < strings.length - 1) {
    const id = codes[f];
    if (id > 1) tables.push({ id, params: strings[si], players: strings[si + 1] || '' });
    f += d; si += m;
  }
  return tables;
}

// ─── HTTP sesja ───────────────────────────────────────────────────────────────
function getSession(game, room) {
  return new Promise((resolve, reject) => {
    const postData = 'gmid=gs';
    const req = https.request({
      hostname: 'www.kurnik.pl',
      path: `/${game}/`,
      method: 'POST',
      headers: {
        'User-Agent':     UA,
        'Content-Type':   'application/x-www-form-urlencoded',
        'Content-Length': Buffer.byteLength(postData),
        'Cookie':         `kguest=1; kbeta=gs; kroom=${room}`,
        'Origin':         'https://www.kurnik.pl',
        'Referer':        `https://www.kurnik.pl/${game}/`,
      },
    }, (res) => {
      const parts = [];
      const setCookies = res.headers['set-cookie'] || [];
      res.on('data', c => parts.push(c));
      res.on('end', () => {
        const body = Buffer.concat(parts).toString();
        let cookieStr = `kguest=1; kbeta=gs; kroom=${room}`;
        for (const c of setCookies) {
          const pair = c.split(';')[0];
          if (pair) cookieStr += '; ' + pair;
        }
        cookies = cookieStr;
        const ge  = (body.match(/window\.ge\s*=\s*(\d+)/) || [])[1] || '';
        const ap  = (body.match(/window\.ap\s*=\s*(\d+)/) || [])[1] || '';
        const tf  = (body.match(/tf\s*:\s*(\d+)/)         || [])[1] || '1751';
        const ver = (body.match(/k2ver\s*=\s*(\d+)/)      || [])[1] || '264';
        const ok  = cookies.includes('kt=');
        send('session-result', { ok, ge, ap, tf: parseInt(tf, 10), ver });
        if (ok) resolve({ ge, ap, tf: parseInt(tf, 10), ver });
        else    reject(new Error('Brak cookie kt= — sesja nieważna'));
      });
    });
    req.on('error', reject);
    req.write(postData);
    req.end();
  });
}

// ─── WebSocket ────────────────────────────────────────────────────────────────
function connectWS(game, room, ge, ap, tf, ver) {
  if (ws) { try { ws.close(); } catch {} }
  currentTable = 0;

  ws = new WebSocket('wss://x.kurnik.pl:17003/ws/', {
    headers: { 'User-Agent': UA, 'Origin': 'https://www.kurnik.pl', 'Cookie': cookies },
    perMessageDeflate: false,
  });

  ws.on('open', () => {
    send('ws-status', { connected: true });
    const autoid = (Math.random() * 1e18 >>> 0).toString();
    ws.send(encode([tf], [
      `+${autoid}|${ap}|${ge}`, 'pl', 'b', '', UA,
      `/${Date.now()}/1`, 'w', '1920x1080 1',
      `ref:https://www.kurnik.pl/${game}/`, `ver:${ver}`,
    ]));
    heartbeat = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send('{"i":[]}');
    }, 30000);
  });

  ws.on('message', (data) => {
    const raw = typeof data === 'string' ? data : data.toString();
    const messages = decode(raw);

    for (const msg of messages) {
      const code = msg.i[0];

      if (code === PING) { ws.send('{"i":[2]}'); continue; }

      if (code === TABLES) {
        const tables = parseTables(msg.i, msg.s);
        send('tables', tables);
        continue;
      }

      if (IGNORE_CODES.has(code)) continue;

      if (msg.s.length) {
        send('message', { type: 'chat', text: msg.s.join(' '), code });
      } else if (msg.i.length > 1) {
        send('message', { type: 'system', text: `[${code}] i:[${msg.i.join(',')}]`, code });
      }
    }
  });

  ws.on('error', (err) => send('ws-error', { message: err.message }));
  ws.on('close', (code) => {
    if (heartbeat) { clearInterval(heartbeat); heartbeat = null; }
    send('ws-status', { connected: false, code });
  });
}

// ─── IPC handlers ─────────────────────────────────────────────────────────────
ipcMain.handle('get-games', () => GAMES);

ipcMain.handle('connect', async (_e, { game, room }) => {
  try {
    const { ge, ap, tf, ver } = await getSession(game, room);
    connectWS(game, room, ge, ap, tf, ver);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('join-table', (_e, { tableId }) => {
  currentTable = tableId;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(encode([JOIN_TAB, tableId]));
    return { ok: true };
  }
  return { ok: false, error: 'WS nie połączony' };
});

ipcMain.handle('send-chat', (_e, { text }) => {
  if (!currentTable) return { ok: false, error: 'Nie wybrano stołu' };
  if (!ws || ws.readyState !== WebSocket.OPEN) return { ok: false, error: 'Brak połączenia' };
  ws.send(encode([CHAT, currentTable], [text]));
  return { ok: true };
});

ipcMain.handle('disconnect', () => {
  if (ws) { try { ws.close(); } catch {} ws = null; }
  if (heartbeat) { clearInterval(heartbeat); heartbeat = null; }
  return { ok: true };
});

// ─── helper push do renderer ──────────────────────────────────────────────────
function send(channel, data) {
  if (mainWin && !mainWin.isDestroyed()) {
    mainWin.webContents.send(channel, data);
  }
}

// ─── okno ─────────────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  mainWin = new BrowserWindow({
    width:  1100,
    height: 720,
    minWidth:  800,
    minHeight: 560,
    backgroundColor: '#0c0e13',
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#0c0e13',
      symbolColor: '#6b7280',
      height: 36,
    },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWin.loadFile(path.join(__dirname, 'renderer', 'index.html'));
});

app.on('window-all-closed', () => {
  if (ws) try { ws.close(); } catch {}
  app.quit();
});
