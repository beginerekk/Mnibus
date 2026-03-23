'use strict';
const WebSocket  = require('ws');
const https      = require('https');
const readline   = require('readline');

// ─── stałe ────────────────────────────────────────────────────────────────────
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36';

const PING     = 1;
const PONG     = 2;
const TABLES   = 71;
const JOIN_TAB = 72;
const CHAT     = 81;

// Kody do zignorowania — Set.has() to O(1)
const IGNORE_CODES = new Set([18,20,22,23,24,25,27,28,30,31,32,51,70,74,72,88,90,92]);

const GAMES = {
    szachy:'Szachy', warcaby:'Warcaby', kalambury:'Kalambury',
    literaki:'Literaki', chinczyk:'Chińczyk', go:'Go',
    backgammon:'Backgammon', reversi:'Reversi', brydz:'Brydż',
    kierki:'Kierki', remik:'Remik', hex:'Hex', gomoku:'Gomoku', bierki:'Bierki',
};
const GAME_KEYS = Object.keys(GAMES);

// ─── protokół ────────────────────────────────────────────────────────────────

// Buduje ramkę WS bez pośredniej tablicy mapowania
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

// Parsuje jedną lub wiele ramek rozdzielonych '\n'
function decode(raw) {
    const results = [];
    // szybka ścieżka: brak nowej linii → jedna ramka
    const nl = raw.indexOf('\n');
    if (nl === -1) {
        try {
            const o = JSON.parse(raw);
            results.push({ i: o.i || [], s: o.s || [] });
        } catch {}
        return results;
    }
    const lines = raw.split('\n');
    for (let k = 0; k < lines.length; k++) {
        const line = lines[k];
        if (!line) continue;
        try {
            const o = JSON.parse(line);
            results.push({ i: o.i || [], s: o.s || [] });
        } catch {}
    }
    return results;
}

// ─── sesja HTTP ───────────────────────────────────────────────────────────────
let cookies = '';

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
                // buduj cookies raz, bez push do tymczasowej tablicy
                let cookieStr = `kguest=1; kbeta=gs; kroom=${room}`;
                for (let i = 0; i < setCookies.length; i++) {
                    const pair = setCookies[i].split(';')[0];
                    if (pair) cookieStr += '; ' + pair;
                }
                cookies = cookieStr;

                const ge  = (body.match(/window\.ge\s*=\s*(\d+)/) || [])[1] || '';
                const ap  = (body.match(/window\.ap\s*=\s*(\d+)/) || [])[1] || '';
                const tf  = (body.match(/tf\s*:\s*(\d+)/)         || [])[1] || '1751';
                const ver = (body.match(/k2ver\s*=\s*(\d+)/)      || [])[1] || '264';
                console.log(cookies.includes('kt=') ? '✅ Sesja OK' : '⚠️  Brak kt');
                resolve({ ge, ap, tf: parseInt(tf, 10), ver });
            });
        });
        req.on('error', reject);
        req.write(postData);
        req.end();
    });
}

// ─── lista stołów ─────────────────────────────────────────────────────────────

// i=[71, blockSize, strPerTable, id0, ..., idN]
// s=[params0, players0, params1, players1, ...]
function parseTables(codes, strings) {
    const tables = [];
    const d  = codes[1];
    const m  = codes[2];
    const maxF  = codes.length;
    const maxSi = strings.length - 1;
    let f  = 3;
    let si = 0;
    while (f < maxF && si < maxSi) {
        const id = codes[f];
        if (id > 1) tables.push({ id, params: strings[si], players: strings[si + 1] || '' });
        f  += d;
        si += m;
    }
    return tables;
}

function displayTables(tables) {
    if (!tables.length) { console.log('\n⚠️  Brak stołów w tym pokoju\n'); return; }
    const lines = [`\n📋 Stoły w pokoju (${tables.length}):\n`];
    for (let i = 0; i < tables.length; i++) {
        const t = tables[i];
        lines.push(`  ID: ${t.id}  ⚙️  ${t.params}  👥 ${t.players || '(brak graczy)'}`);
    }
    console.log(lines.join('\n') + '\n');
}

// ─── interfejs CLI ────────────────────────────────────────────────────────────
const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
let rlOpen = true;
rl.on('close', () => { rlOpen = false; });
const prompt = () => { if (rlOpen) rl.prompt(); };

function ask(question) {
    return new Promise(resolve => rl.question(question, resolve));
}

async function askGame() {
    console.log('\n🎮 Dostępne gry:\n');
    const chunks = [];
    for (let i = 0; i < GAME_KEYS.length; i++) {
        chunks.push(`  ${(i + 1).toString().padEnd(3)} ${GAMES[GAME_KEYS[i]].padEnd(15)}`);
        if ((i + 1) % 4 === 0) chunks.push('\n');
    }
    console.log(chunks.join('') + '\n');

    const answer = (await ask('Wybierz grę (numer lub nazwa): ')).trim().toLowerCase();
    const idx    = parseInt(answer, 10);
    if (idx >= 1 && idx <= GAME_KEYS.length) return GAME_KEYS[idx - 1];
    if (GAMES[answer]) return answer;
    console.log('❌ Nieznana gra, spróbuj ponownie');
    return askGame();
}

async function askRoom() {
    const raw = (await ask('Podaj numer pokoju (np. 100, 200, 300...): ')).trim().replace(/^#/, '');
    if (!/^\d+$/.test(raw)) { console.log('❌ Podaj same cyfry'); return askRoom(); }
    return raw;
}

// ─── WebSocket ────────────────────────────────────────────────────────────────
function connectWS(game, room, ge, ap, tf, ver) {
    let currentTable = 0;
    let tableAsked   = false;
    let heartbeat    = null;

    console.log(`\n[WS] Łączę z pokojem #${room} (${game})...`);

    const ws = new WebSocket('wss://x.kurnik.pl:17003/ws/', {
        headers: { 'User-Agent': UA, 'Origin': 'https://www.kurnik.pl', 'Cookie': cookies },
        // wyłącz automatyczne per-message deflate jeśli zbędne (oszczędność CPU)
        perMessageDeflate: false,
    });

    ws.on('open', () => {
        console.log('✅ Połączono\n');
        const autoid = (Math.random() * 1e18 >>> 0).toString();   // szybszy RNG
        ws.send(encode([tf], [
            `+${autoid}|${ap}|${ge}`, 'pl', 'b', '', UA,
            `/${Date.now()}/1`, 'w', '1920x1080 1',
            `ref:https://www.kurnik.pl/${game}/`, `ver:${ver}`,
        ]));
        heartbeat = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send('{"i":[]}');
        }, 30000);
    });

    ws.on('message', (data) => {
        const raw      = typeof data === 'string' ? data : data.toString();
        const messages = decode(raw);

        for (let m = 0; m < messages.length; m++) {
            const msg  = messages[m];
            const code = msg.i[0];

            if (code === PING) { ws.send('{"i":[2]}'); continue; }

            if (code === TABLES && !tableAsked) {
                tableAsked = true;
                const tables = parseTables(msg.i, msg.s);
                displayTables(tables);

                ask('Podaj ID stołu (lub Enter = obserwator): ').then(answer => {
                    const id = parseInt(answer.trim(), 10);
                    if (isNaN(id)) {
                        console.log('👁️  Tryb obserwatora\n');
                        rl.setPrompt('');
                    } else {
                        currentTable = id;
                        ws.send(encode([JOIN_TAB, id]));
                        console.log(`\n➡️  Dołączam do stołu ID: ${id}\n`);
                        rl.setPrompt('TY: ');
                    }
                    prompt();
                });
                continue;
            }

            if (IGNORE_CODES.has(code)) continue;

            if (msg.s.length) {
                process.stdout.write('\r' + msg.s.join(' ') + '\n');
                prompt();
            } else if (msg.i.length > 1) {
                process.stdout.write(`\r[${code}] i:[${msg.i.join(',')}]\n`);
                prompt();
            }
        }
    });

    rl.on('line', (line) => {
        const msg = line.trim();
        if (!msg) { prompt(); return; }

        if (msg.charCodeAt(0) === 47) {           // '/'
            if (msg.length > 6 && msg.startsWith('/join ')) {
                currentTable = parseInt(msg.slice(6), 10);
                ws.send(encode([JOIN_TAB, currentTable]));
                console.log(`➡️  Stół ID: ${currentTable}`);
            } else if (msg === '/quit' || msg === '/exit') {
                ws.close();
                return;
            }
        } else if (currentTable) {
            ws.send(encode([CHAT, currentTable], [msg]));
        } else {
            console.log('⚠️  Najpierw wybierz stół (/join ID)');
        }
        prompt();
    });

    ws.on('error', (err) => console.error('\n[Błąd WS]:', err.message));
    ws.on('close', (code) => {
        if (heartbeat) clearInterval(heartbeat);
        console.log(`\n--- ROZŁĄCZONO (${code}) ---`);
        process.exit(0);
    });
}

// ─── start ────────────────────────────────────────────────────────────────────
(async () => {
    console.log('🎮 Kurnik.pl — klient CLI\n');
    try {
        const game               = await askGame();
        console.log(`\n[INFO] Wybrałeś: ${GAMES[game]}`);
        const room               = await askRoom();
        const { ge, ap, tf, ver } = await getSession(game, room);
        connectWS(game, room, ge, ap, tf, ver);
    } catch (err) {
        console.error('[BŁĄD]', err.message);
        process.exit(1);
    }
})();
