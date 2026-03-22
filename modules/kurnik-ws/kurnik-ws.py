#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kurnik.pl — klient CLI / subprocess bot
Domyślna gra: Kalambury, pokój 100
"""
import argparse
import asyncio
import json
import websockets
import requests
import re
import sys
import io
from datetime import datetime
from typing import Dict, List, Any

# ─── UTF-8 dla Windows ────────────────────────────────────────────────────────
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    sys.stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding='utf-8', errors='replace')

# ─── stałe ────────────────────────────────────────────────────────────────────
UA   = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/122.0.0.0 Safari/537.36')

PING      = 1
TABLES    = 71
JOIN_TAB  = 72
CHAT      = 81

IGNORE_CODES = {18, 20, 22, 23, 24, 25, 27, 28, 30, 31, 32,
                51, 70, 72, 74, 88, 90, 92}

DEFAULT_GAME = 'kalambury'
DEFAULT_ROOM = '100'

# ─── protokół ────────────────────────────────────────────────────────────────

def encode(codes: List[int], strings: List[str] = None) -> str:
    out = '{"i":[' + ','.join(map(str, codes)) + ']'
    if strings:
        out += ',"s":["'
        out += '","'.join(
            s.replace('\\', '\\\\').replace('"', '\\"') for s in strings
        )
        out += '"]'
    return out + '}'


def decode(raw: str) -> List[Dict[str, Any]]:
    results = []
    for line in (raw.split('\n') if '\n' in raw else [raw]):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
            results.append({'i': o.get('i', []), 's': o.get('s', [])})
        except json.JSONDecodeError:
            pass
    return results


# ─── sesja HTTP ───────────────────────────────────────────────────────────────
_session = requests.Session()
_cookies = ''


def get_session(game: str, room: str) -> Dict[str, Any]:
    global _cookies
    _session.cookies.update({'kguest': '1', 'kbeta': 'gs', 'kroom': room})
    try:
        response = _session.post(
            f'https://www.kurnik.pl/{game}/',
            data='gmid=gs',
            headers={
                'User-Agent': UA,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin':  'https://www.kurnik.pl',
                'Referer': f'https://www.kurnik.pl/{game}/',
            },
            timeout=10
        )
        body = response.text

        cookie_str = f'kguest=1; kbeta=gs; kroom={room}'
        for k, v in _session.cookies.items():
            if k not in ('kguest', 'kbeta', 'kroom'):
                cookie_str += f'; {k}={v}'
        _cookies = cookie_str

        ge  = (re.search(r'window\.ge\s*=\s*(\d+)', body) or [None,''])[1] or ''
        ap  = (re.search(r'window\.ap\s*=\s*(\d+)', body) or [None,''])[1] or ''
        tf_m = re.search(r'tf\s*:\s*(\d+)', body)
        tf   = int(tf_m[1]) if tf_m else 1751
        ver_m = re.search(r'k2ver\s*=\s*(\d+)', body)
        ver   = ver_m[1] if ver_m else '264'

        print('SESSION_OK' if 'kt=' in _cookies else 'SESSION_WARN', flush=True)
        return {'ge': ge, 'ap': ap, 'tf': tf, 'ver': ver}

    except Exception as e:
        print(f'[BŁĄD HTTP] {e}', flush=True)
        raise


# ─── lista stołów ─────────────────────────────────────────────────────────────

def parse_tables(codes: List[int], strings: List[str]) -> List[Dict[str, Any]]:
    tables = []
    if len(codes) < 3:
        return tables
    block_size   = codes[1]
    str_per_table = codes[2]
    f, si = 3, 0
    while f < len(codes) and si < len(strings) - 1:
        tid = codes[f]
        if tid > 1:
            tables.append({
                'id':      tid,
                'params':  strings[si]     if si     < len(strings) else '',
                'players': strings[si + 1] if si + 1 < len(strings) else '',
            })
        f  += block_size
        si += str_per_table
    return tables


def format_tables(tables: List[Dict[str, Any]]) -> str:
    if not tables:
        return 'TABLES_EMPTY'
    lines = [f'TABLES_START {len(tables)}']
    for t in tables:
        players = t['players'] or '(brak graczy)'
        lines.append(f"TABLE {t['id']} | {t['params']} | {players}")
    lines.append('TABLES_END')
    return '\n'.join(lines)


# ─── WebSocket ────────────────────────────────────────────────────────────────

async def connect_ws(game: str, room: str, ge: str, ap: str,
                     tf: int, ver: str, initial_table: int) -> None:
    """
    Łączy z WebSocket.
    stdin steruje botem:
      - liczba                → /join <id>
      - /join <id>            → zmiana stołu (bez restartu)
      - /table                → wyświetl aktualny stół
      - tekst                 → wyślij chat na aktualny stół
      - /quit                 → rozłącz
    Wszystkie statusy i wiadomości są wypisywane przez print() → stdout.
    """
    current_table = initial_table

    print(f'[WS] Łączę z pokojem #{room} ({game})...', flush=True)

    uri = 'wss://x.kurnik.pl:17003/ws/'
    headers = {
        'User-Agent': UA,
        'Origin':     'https://www.kurnik.pl',
        'Cookie':     _cookies,
    }

    try:
        async with websockets.connect(uri, extra_headers=headers) as ws:
            print('CONNECTED', flush=True)

            autoid = str(int(abs(hash(datetime.now())) % 10**18))
            await ws.send(encode([tf], [
                f'+{autoid}|{ap}|{ge}',
                'pl', 'b', '', UA,
                f'/{int(datetime.now().timestamp() * 1000)}/1',
                'w', '1920x1080 1',
                f'ref:https://www.kurnik.pl/{game}/',
                f'ver:{ver}',
            ]))

            # ── heartbeat ─────────────────────────────────────────────────────
            async def heartbeat():
                try:
                    while True:
                        await asyncio.sleep(30)
                        await ws.send('{"i":[]}')
                except asyncio.CancelledError:
                    pass

            # ── odbieranie WS ─────────────────────────────────────────────────
            async def receive():
                nonlocal current_table
                try:
                    while True:
                        data = await ws.recv()
                        raw  = data if isinstance(data, str) else data.decode('utf-8')
                        for msg in decode(raw):
                            code = msg['i'][0] if msg['i'] else None

                            if code == PING:
                                await ws.send('{"i":[2]}')
                                continue

                            if code == TABLES:
                                tables = parse_tables(msg['i'], msg['s'])
                                print(format_tables(tables), flush=True)
                                # jeśli initial_table podany — dołącz od razu
                                if current_table:
                                    await ws.send(encode([JOIN_TAB, current_table]))
                                    print(f'JOINED {current_table}', flush=True)
                                continue

                            if code in IGNORE_CODES:
                                continue

                            if msg['s']:
                                print('MSG ' + ' '.join(msg['s']), flush=True)
                            elif len(msg['i']) > 1:
                                codes_str = ','.join(map(str, msg['i']))
                                print(f'RAW [{code}] {codes_str}', flush=True)

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f'[BŁĄD RECV] {e}', flush=True)

            # ── odczyt stdin ──────────────────────────────────────────────────
            async def read_stdin():
                nonlocal current_table
                loop = asyncio.get_event_loop()
                try:
                    while True:
                        line = await loop.run_in_executor(None, sys.stdin.readline)
                        if not line:          # EOF → launcher zamknął pipe
                            break
                        line = line.strip()
                        if not line:
                            continue

                        # sama liczba → /join
                        if re.match(r'^\d+$', line):
                            line = f'/join {line}'

                        if line.startswith('/join '):
                            try:
                                tid = int(line[6:].strip())
                                current_table = tid
                                await ws.send(encode([JOIN_TAB, tid]))
                                print(f'JOINED {tid}', flush=True)
                            except ValueError:
                                print('ERR nieprawidłowy numer stołu', flush=True)

                        elif line == '/table':
                            print(f'CURRENT_TABLE {current_table}', flush=True)

                        elif line in ('/quit', '/exit'):
                            await ws.close()
                            return

                        elif current_table:
                            await ws.send(encode([CHAT, current_table], [line]))

                        else:
                            print('ERR brak stołu, użyj /join ID', flush=True)

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f'[BŁĄD STDIN] {e}', flush=True)

            hb   = asyncio.create_task(heartbeat())
            recv = asyncio.create_task(receive())
            inp  = asyncio.create_task(read_stdin())

            try:
                await asyncio.gather(recv, inp)
            finally:
                hb.cancel()
                recv.cancel()
                inp.cancel()
                try:
                    await ws.close()
                except Exception:
                    pass

    except Exception as e:
        print(f'[BŁĄD WS] {e}', flush=True)
        raise


# ─── start ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Kurnik.pl bot CLI')
    p.add_argument('--game',  default=DEFAULT_GAME,
                   help=f'Gra (default: {DEFAULT_GAME})')
    p.add_argument('--room',  default=DEFAULT_ROOM,
                   help=f'Pokój (default: {DEFAULT_ROOM})')
    p.add_argument('--table', type=int, default=0,
                   help='Stół do automatycznego dołączenia (0 = obserwator)')
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    game  = args.game
    room  = args.room
    table = args.table

    print(f'BOT_START game={game} room={room} table={table}', flush=True)

    try:
        sess = get_session(game, room)
        await connect_ws(game, room,
                         sess['ge'], sess['ap'], sess['tf'], sess['ver'],
                         table)
    except Exception as err:
        print(f'[BŁĄD] {err}', flush=True)
        sys.exit(1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[PRZERWANO]', flush=True)
        sys.exit(0)
