// ui/src/app.js
// Vanilla JS — zero frameworków, zero zbędnych dependencji
import { invoke } from '@tauri-apps/api/core';
import { listen }  from '@tauri-apps/api/event';

// ─── stan ─────────────────────────────────────────────────────────────────────
// bots: Map<bot_id, { game, room, online, table, tables: Table[] }>
const bots = new Map();
let activeBotId = null;

// ─── elementy DOM (cache — nie szukamy ich w pętli) ───────────────────────────
const $ = id => document.getElementById(id);
const viewWelcome  = $('view-welcome');
const viewNewBot   = $('view-new-bot');
const viewBot      = $('view-bot');
const botList      = $('bot-list');
const botTitle     = $('bot-title');
const botBadge     = $('bot-badge');
const tableTbody   = $('table-tbody');
const lobbyEmpty   = $('lobby-empty');
const chatMessages = $('chat-messages');
const chatInput    = $('chat-input');
const btnSend      = $('btn-send');
const chatLabel    = $('chat-table-label');

// ─── nawigacja widoków ────────────────────────────────────────────────────────
function showView(view) {
    viewWelcome.classList.remove('active');
    viewNewBot .classList.remove('active');
    viewBot    .classList.remove('active');
    view.classList.add('active');
}

// ─── sidebar: lista botów ─────────────────────────────────────────────────────
function renderBotList() {
    botList.innerHTML = '';
    for (const [id, bot] of bots) {
        const li  = document.createElement('li');
        li.dataset.id = id;
        if (id === activeBotId) li.classList.add('active');

        const dot  = document.createElement('span');
        dot.className = 'bot-dot' + (bot.online ? ' online' : '');

        const lbl  = document.createElement('span');
        lbl.className = 'label';
        lbl.textContent = `#${bot.room} ${bot.game}`;

        li.append(dot, lbl);
        li.addEventListener('click', () => selectBot(id));
        botList.appendChild(li);
    }
}

// ─── wybór aktywnego bota ─────────────────────────────────────────────────────
function selectBot(id) {
    activeBotId = id;
    renderBotList();
    const bot = bots.get(id);
    if (!bot) { showView(viewWelcome); return; }

    botTitle.textContent = `Bot ${id} — ${bot.game} / pokój ${bot.room}`;
    setBadge(bot.online);
    renderTables(bot.tables || []);
    renderChat(id);
    setInputState(bot.table != null);
    chatLabel.textContent = bot.table ? `stół ${bot.table}` : '';
    showView(viewBot);
}

function setBadge(online) {
    botBadge.textContent  = online ? 'online' : 'offline';
    botBadge.className    = 'badge ' + (online ? 'online' : 'offline');
}

// ─── lobby ────────────────────────────────────────────────────────────────────
function renderTables(tables) {
    if (!tables.length) {
        tableTbody.innerHTML = '';
        lobbyEmpty.style.display = 'block';
        return;
    }
    lobbyEmpty.style.display = 'none';

    // buduj HTML jednym stringiem — szybsze niż N appendChild
    const rows = tables.map(t => `
      <tr>
        <td>${t.id}</td>
        <td>${esc(t.params)}</td>
        <td>${esc(t.players) || '<span style="color:var(--text2)">(brak)</span>'}</td>
        <td><button class="btn-join" data-id="${t.id}">Dołącz</button></td>
      </tr>`).join('');
    tableTbody.innerHTML = rows;
}

tableTbody.addEventListener('click', e => {
    const btn = e.target.closest('.btn-join');
    if (!btn || activeBotId == null) return;
    const tableId = parseInt(btn.dataset.id, 10);
    doJoinTable(activeBotId, tableId);
});

async function doJoinTable(botId, tableId) {
    await invoke('join_table', { botId, tableId });
    const bot = bots.get(botId);
    if (bot) {
        bot.table = tableId;
        if (botId === activeBotId) {
            setInputState(true);
            chatLabel.textContent = `stół ${tableId}`;
            addChatLine(botId, 'sys', `➡ Dołączono do stołu ${tableId}`);
        }
    }
}

// ─── chat ─────────────────────────────────────────────────────────────────────
// chatLogs: Map<bot_id, Array<{cls, text}>>
const chatLogs = new Map();
const MAX_LOG  = 500; // max linii na bota (oszczędność RAM)

function addChatLine(botId, cls, text) {
    if (!chatLogs.has(botId)) chatLogs.set(botId, []);
    const log = chatLogs.get(botId);
    log.push({ cls, text });
    if (log.length > MAX_LOG) log.shift();

    if (botId === activeBotId) {
        appendLine(cls, text);
    }
}

function appendLine(cls, text) {
    const div = document.createElement('div');
    div.className = 'chat-line ' + cls;
    div.textContent = text;
    chatMessages.appendChild(div);
    // scroll tylko jeśli blisko dołu (nie przerywaj przewijania użytkownika)
    const el = chatMessages;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) {
        el.scrollTop = el.scrollHeight;
    }
}

function renderChat(botId) {
    chatMessages.innerHTML = '';
    const log = chatLogs.get(botId) || [];
    // batch insert — DocumentFragment zamiast N appendChild
    const frag = document.createDocumentFragment();
    for (const { cls, text } of log) {
        const div = document.createElement('div');
        div.className = 'chat-line ' + cls;
        div.textContent = text;
        frag.appendChild(div);
    }
    chatMessages.appendChild(frag);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function setInputState(enabled) {
    chatInput.disabled = !enabled;
    btnSend.disabled   = !enabled;
}

// ─── wysyłanie czatu ──────────────────────────────────────────────────────────
async function sendChat() {
    const text = chatInput.value.trim();
    if (!text || activeBotId == null) return;
    const bot = bots.get(activeBotId);
    if (!bot?.table) return;

    chatInput.value = '';
    addChatLine(activeBotId, 'sent', `TY: ${text}`);
    await invoke('send_chat', { botId: activeBotId, tableId: bot.table, text });
}

btnSend.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });

// ─── formularz nowego bota ────────────────────────────────────────────────────
$('btn-new-bot').addEventListener('click', () => showView(viewNewBot));
$('btn-cancel-new').addEventListener('click', () => {
    activeBotId == null ? showView(viewWelcome) : selectBot(activeBotId);
});

$('btn-connect').addEventListener('click', async () => {
    const game = $('sel-game').value;
    const room = $('inp-room').value.trim();
    if (!room) { $('inp-room').focus(); return; }

    const btn = $('btn-connect');
    btn.disabled = true;
    btn.textContent = 'Łączę…';

    try {
        const botId = await invoke('start_bot', { game, room });
        bots.set(botId, { game, room, online: false, table: null, tables: [] });
        renderBotList();
        selectBot(botId);
        addChatLine(botId, 'sys', `Łączę: ${game} / pokój ${room}…`);
    } catch (err) {
        alert('Błąd: ' + err);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Połącz';
    }
});

// ─── stop bot ─────────────────────────────────────────────────────────────────
$('btn-stop-bot').addEventListener('click', async () => {
    if (activeBotId == null) return;
    await invoke('stop_bot', { botId: activeBotId });
    bots.delete(activeBotId);
    chatLogs.delete(activeBotId);
    activeBotId = null;
    renderBotList();
    showView(viewWelcome);
});

// ─── eventy z Rust ────────────────────────────────────────────────────────────
listen('bot-status', ({ payload: p }) => {
    const bot = bots.get(p.bot_id);
    if (!bot) return;
    bot.online = p.online;
    if (p.table != null) bot.table = p.table;
    renderBotList();
    if (p.bot_id === activeBotId) {
        setBadge(p.online);
        if (!p.online) {
            setInputState(false);
            addChatLine(p.bot_id, 'sys', '--- Rozłączono ---');
        }
    }
});

listen('bot-tables', ({ payload: [botId, tables] }) => {
    const bot = bots.get(botId);
    if (!bot) return;
    bot.tables = tables;
    if (botId === activeBotId) renderTables(tables);
});

listen('bot-msg', ({ payload: p }) => {
    addChatLine(p.bot_id, 'msg', `[${p.code}] ${p.text}`);
});

listen('bot-error', ({ payload: msg }) => {
    // znajdź bota po ID w wiadomości (np. "Bot 2: …")
    const m = msg.match(/^Bot (\d+):/);
    const id = m ? parseInt(m[1], 10) : activeBotId;
    if (id != null) addChatLine(id, 'sys', '⚠ ' + msg);
});

// ─── utils ────────────────────────────────────────────────────────────────────
function esc(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// ─── init ─────────────────────────────────────────────────────────────────────
showView(viewWelcome);
