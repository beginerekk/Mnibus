#!/usr/bin/env python3
"""
Kurnik.pl — klient CLI
Połączenie WebSocket do gier na kurnik.pl
"""

import asyncio
import json
import websockets
import requests
import re
import sys
from datetime import datetime
from typing import Dict, List, Tuple, Any
import aioconsole

# ─── stałe ────────────────────────────────────────────────────────────────────
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'

PING = 1
PONG = 2
TABLES = 71
JOIN_TAB = 72
CHAT = 81

# Kody do zignorowania — set dla O(1)
IGNORE_CODES = {18, 20, 22, 23, 24, 25, 27, 28, 30, 31, 32, 51, 70, 74, 72, 88, 90, 92}

GAMES = {
    'szachy': 'Szachy',
    'warcaby': 'Warcaby',
    'kalambury': 'Kalambury',
    'literaki': 'Literaki',
    'chinczyk': 'Chińczyk',
    'go': 'Go',
    'backgammon': 'Backgammon',
    'reversi': 'Reversi',
    'brydz': 'Brydż',
    'kierki': 'Kierki',
    'remik': 'Remik',
    'hex': 'Hex',
    'gomoku': 'Gomoku',
    'bierki': 'Bierki',
}

GAME_KEYS = list(GAMES.keys())

# ─── protokół ────────────────────────────────────────────────────────────────

def encode(codes: List[int], strings: List[str] = None) -> str:
    """Buduje ramkę WS bez pośredniej tablicy mapowania"""
    out = '{"i":[' + ','.join(map(str, codes)) + ']'
    if strings:
        out += ',"s":["'
        out += '","'.join(
            s.replace('\\', '\\\\').replace('"', '\\"')
            for s in strings
        )
        out += '"]'
    return out + '}'


def decode(raw: str) -> List[Dict[str, Any]]:
    """Parsuje jedną lub wiele ramek rozdzielonych '\\n'"""
    results = []
    
    # szybka ścieżka: brak nowej linii → jedna ramka
    if '\n' not in raw:
        try:
            o = json.loads(raw)
            results.append({'i': o.get('i', []), 's': o.get('s', [])})
        except json.JSONDecodeError:
            pass
        return results
    
    # wiele ramek
    for line in raw.split('\n'):
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
session = requests.Session()
cookies = ''


def get_session(game: str, room: str) -> Dict[str, Any]:
    """Pobiera sesję HTTP i pliki cookies - jak w skrypcie JS"""
    global cookies

    post_data = 'gmid=gs'

    try:
        # Ustawienie wstępnych cookies
        session.cookies.update({
            'kguest': '1',
            'kbeta': 'gs',
            'kroom': room,
        })

        response = session.post(
            f'https://www.kurnik.pl/{game}/',
            data=post_data,
            headers={
                'User-Agent': UA,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://www.kurnik.pl',
                'Referer': f'https://www.kurnik.pl/{game}/',
            },
            timeout=10
        )

        body = response.text

        # Buduj cookie string z cookies z sesji (jak w JS)
        cookie_str = f'kguest=1; kbeta=gs; kroom={room}'
        for cookie_name, cookie_value in session.cookies.items():
            if cookie_name not in ['kguest', 'kbeta', 'kroom']:
                cookie_str += f'; {cookie_name}={cookie_value}'

        cookies = cookie_str

        # wyciąg parametrów
        ge = (re.search(r'window\.ge\s*=\s*(\d+)', body) or (None, ''))[1] or ''
        ap = (re.search(r'window\.ap\s*=\s*(\d+)', body) or (None, ''))[1] or ''
        tf_match = re.search(r'tf\s*:\s*(\d+)', body)
        tf = int(tf_match[1]) if tf_match else 1751
        ver_match = re.search(r'k2ver\s*=\s*(\d+)', body)
        ver = ver_match[1] if ver_match else '264'

        status = '✅ Sesja OK' if 'kt=' in cookies else '⚠️  Brak kt'
        print(status)

        return {'ge': ge, 'ap': ap, 'tf': tf, 'ver': ver}

    except Exception as e:
        print(f'[BŁĄD HTTP] {e}')
        raise


# ─── lista stołów ─────────────────────────────────────────────────────────────

def parse_tables(codes: List[int], strings: List[str]) -> List[Dict[str, Any]]:
    """
    Parsuje liste stołów z wiadomości TABLES (code=71)
    i=[71, blockSize, strPerTable, id0, ..., idN]
    s=[params0, players0, params1, players1, ...]
    """
    tables = []
    if len(codes) < 3:
        return tables
    
    block_size = codes[1]
    str_per_table = codes[2]
    
    f = 3
    si = 0
    
    while f < len(codes) and si < len(strings) - 1:
        table_id = codes[f]
        if table_id > 1:
            tables.append({
                'id': table_id,
                'params': strings[si] if si < len(strings) else '',
                'players': strings[si + 1] if si + 1 < len(strings) else ''
            })
        f += block_size
        si += str_per_table
    
    return tables


def display_tables(tables: List[Dict[str, Any]]) -> None:
    """Wyświetla listę dostępnych stołów"""
    if not tables:
        print('\n⚠️  Brak stołów w tym pokoju\n')
        return
    
    print(f'\n📋 Stoły w pokoju ({len(tables)}):\n')
    for t in tables:
        players = t.get('players') or '(brak graczy)'
        print(f"  ID: {t['id']}  ⚙️  {t['params']}  👥 {players}")
    print()


# ─── interfejs CLI ────────────────────────────────────────────────────────────

def ask_game() -> str:
    """Prosi użytkownika o wybranie gry"""
    print('\n🎮 Dostępne gry:\n')
    
    for i, key in enumerate(GAME_KEYS):
        num = str(i + 1).rjust(3)
        name = GAMES[key].ljust(15)
        print(f'  {num} {name}', end='')
        if (i + 1) % 4 == 0:
            print()
    print('\n')
    
    answer = input('Wybierz grę (numer lub nazwa): ').strip().lower()
    
    try:
        idx = int(answer)
        if 1 <= idx <= len(GAME_KEYS):
            return GAME_KEYS[idx - 1]
    except ValueError:
        pass
    
    if answer in GAMES:
        return answer
    
    print('❌ Nieznana gra, spróbuj ponownie')
    return ask_game()


def ask_room() -> str:
    """Prosi użytkownika o numer pokoju"""
    raw = input('Podaj numer pokoju (np. 100, 200, 300...): ').strip().lstrip('#')
    
    if not re.match(r'^\d+$', raw):
        print('❌ Podaj same cyfry')
        return ask_room()
    
    return raw


# ─── WebSocket ────────────────────────────────────────────────────────────────

async def connect_ws(game: str, room: str, ge: str, ap: str, tf: int, ver: str) -> None:
    """Łączy się z WebSocket i obsługuje wiadomości"""
    current_table = 0
    table_asked = False

    print(f'\n[WS] Łączę z pokojem #{room} ({game})...')

    uri = 'wss://x.kurnik.pl:17003/ws/'

    try:
        headers = {
            'User-Agent': UA,
            'Origin': 'https://www.kurnik.pl',
            'Cookie': cookies,
        }

        async with websockets.connect(
            uri,
            extra_headers=headers,
        ) as ws:
            print('✅ Połączono\n')

            # Wyślij wiadomość autoryzacyjną
            autoid = str(int(abs(hash(datetime.now())) % 1e18))

            initial_msg = encode([tf], [
                f'+{autoid}|{ap}|{ge}',
                'pl',
                'b',
                '',
                UA,
                f'/{int(datetime.now().timestamp() * 1000)}/1',
                'w',
                '1920x1080 1',
                f'ref:https://www.kurnik.pl/{game}/',
                f'ver:{ver}',
            ])
            await ws.send(initial_msg)

            # Heartbeat task
            async def heartbeat():
                try:
                    while True:
                        await asyncio.sleep(30)
                        await ws.send('{"i":[]}')
                except asyncio.CancelledError:
                    pass

            hb_task = asyncio.create_task(heartbeat())

            # Task do odbioru wiadomości z WebSocket
            async def receive_messages():
                nonlocal current_table, table_asked
                try:
                    while True:
                        data = await ws.recv()
                        raw = data if isinstance(data, str) else data.decode()
                        messages = decode(raw)

                        for msg in messages:
                            code = msg['i'][0] if msg['i'] else None

                            if code == PING:
                                await ws.send('{"i":[2]}')
                                continue

                            if code == TABLES and not table_asked:
                                table_asked = True
                                tables = parse_tables(msg['i'], msg['s'])
                                display_tables(tables)

                                # Zapytaj o wybór stołu asynchronicznie
                                answer = await aioconsole.ainput('Podaj ID stołu (lub Enter = obserwator): ')
                                try:
                                    table_id = int(answer.strip())
                                    current_table = table_id
                                    await ws.send(encode([JOIN_TAB, table_id]))
                                    print(f'\n➡️  Dołączam do stołu ID: {table_id}\n')
                                except ValueError:
                                    print('👁️  Tryb obserwatora\n')
                                continue

                            if code in IGNORE_CODES:
                                continue

                            if msg['s']:
                                print('\r' + ' '.join(msg['s']))
                            elif len(msg['i']) > 1:
                                print(f"\r[{code}] i:[{','.join(map(str, msg['i']))}]")
                except asyncio.CancelledError:
                    pass

            # Task do odbioru linii z stdin
            async def read_input():
                nonlocal current_table, table_asked
                try:
                    while True:
                        # Czekaj aż stół będzie wybrany
                        if not table_asked:
                            await asyncio.sleep(0.1)
                            continue

                        line = await aioconsole.ainput()
                        msg = line.strip()

                        if not msg:
                            continue

                        if msg and msg[0] == '/':  # komenda
                            if msg.startswith('/join '):
                                try:
                                    current_table = int(msg[6:])
                                    await ws.send(encode([JOIN_TAB, current_table]))
                                    print(f'➡️  Stół ID: {current_table}')
                                except ValueError:
                                    print('❌ Nieprawidłowy numer stołu')
                            elif msg == '/quit' or msg == '/exit':
                                await ws.close()
                                return
                        elif current_table:
                            await ws.send(encode([CHAT, current_table], [msg]))
                        else:
                            print('⚠️  Najpierw wybierz stół (/join ID)')
                except asyncio.CancelledError:
                    pass

            recv_task = asyncio.create_task(receive_messages())
            input_task = asyncio.create_task(read_input())

            try:
                await asyncio.gather(recv_task, input_task)
            except asyncio.CancelledError:
                pass
            finally:
                hb_task.cancel()
                recv_task.cancel()
                input_task.cancel()
                try:
                    await ws.close()
                except:
                    pass
    except Exception as e:
        print(f'[BŁĄD WS] {e}')
        raise


# ─── start ────────────────────────────────────────────────────────────────────

async def main() -> None:
    """Główna funkcja aplikacji"""
    print('🎮 Kurnik.pl — klient CLI\n')
    
    try:
        game = ask_game()
        print(f'\n[INFO] Wybrałeś: {GAMES[game]}')
        
        room = ask_room()
        
        session = get_session(game, room)
        
        await connect_ws(game, room, session['ge'], session['ap'], session['tf'], session['ver'])
    
    except Exception as err:
        print(f'[BŁĄD] {err}')
        sys.exit(1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[PRZERWANO]')
        sys.exit(0)
