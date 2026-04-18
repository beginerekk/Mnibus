#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kurnik-ws.py — Kurnik.pl WebSocket Bot
=======================================
Łączy się z serwerem Kurnik.pl przez WebSocket i pozwala na:
  - obserwację stołów w pokoju
  - dołączanie do stołów (/join ID)
  - wysyłanie wiadomości na stół (chat)
  - wykrywanie wejść i wyjść graczy (PLAYER_JOIN / PLAYER_LEAVE)
  - automatyczny heartbeat (co 30 s)
  - rozpoznawanie słowa do zgadnięcia (Kalambury)

Komunikacja z procesem nadrzędnym (launcher.py) odbywa się przez stdin/stdout:
  STDIN:
    <liczba>         → /join <liczba> (skrót)
    /join <ID>       → zmień stół
    /table           → zwróć aktualny numer stołu
    /quit / /exit    → rozłącz i zakończ
    <tekst>          → wyślij jako chat na aktualny stół

  STDOUT (protokół tekstowy):
    SESSION_OK / SESSION_WARN   → status sesji HTTP
    CONNECTED                   → WebSocket połączony
    TABLES_START <n>            → początek listy stołów
    TABLE <id> | <params> | <gracze>
    TABLES_END
    TABLES_EMPTY                → brak stołów w pokoju
    JOINED <id>                 → bot dołączył do stołu
    CURRENT_TABLE <id>          → odpowiedź na /table
    MSG <tekst>                 → wiadomość z serwera
    PLAYER_JOIN <table_id> <nick>    → gracz wszedł na stół
    PLAYER_LEAVE <table_id> <nick>   → gracz opuścił stół
    CHAT <table_id> <nick>: <tekst>  → wiadomość czatu
    WORD <słowo>                → słowo do zgadnięcia (Kalambury)
    STATUS <kod> <...>          → surowy status z serwera
    EXT <table_id> <treść>      → wiadomość z tabeli
    RAW [<kod>] <...>           → surowa ramka (debugowanie)
    BOT_START <params>          → bot uruchomiony
    [BŁĄD ...] / [PRZERWANO]    → komunikaty błędów

Jak modyfikować:
  - Dodaj nowe kody do IGNORE_CODES, jeśli nie chcesz ich przetwarzać.
  - Rozszerz _handle_line() / receive() aby obsłużyć nowe zdarzenia.
  - Zmień DEFAULT_GAME / DEFAULT_ROOM na inną grę/pokój.
  - Dodaj własne komendy do sekcji read_stdin().
"""

import argparse
import asyncio
import json
import re
import sys
import io
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

# ─── Trzecia strona ────────────────────────────────────────────────────────────
try:
    import websockets
    import requests
except ImportError as _e:
    print(f'[BŁĄD IMPORT] Brak modułu: {_e}. Uruchom: pip install websockets requests', flush=True)
    sys.exit(1)

# ─── UTF-8 na Windows (bez tego polskie znaki mogą się nie wyświetlać) ────────
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    sys.stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding='utf-8', errors='replace')

# ─── Stałe konfiguracyjne ─────────────────────────────────────────────────────

# Nagłówek User-Agent używany w żądaniach HTTP i WebSocket
UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/122.0.0.0 Safari/537.36'
)

# Adresy serwerów WebSocket (próbowane w kolejności)
WS_HOSTS = [
    'wss://x.kurnik.pl:17003/ws/',
    'wss://x.kurnik.pl:443/ws/',
]

# Kody komunikatów protokołu Kurnik (wyekstrahowane z kurnik-ws.js)
MSG_PING          = 1       # Serwer pinguje — trzeba odpowiedzieć [2]
MSG_PONG          = 2       # Odpowiedź na ping
MSG_TABLES        = 71      # Lista stołów w pokoju
MSG_JOIN_TAB      = 72      # Dołącz do stołu / zmiana stołu
MSG_CHAT          = 81      # Wiadomość czatu na stole
MSG_TAB_UPDATE    = 70      # Aktualizacja danych stołu (gracze, wyniki)
MSG_TAB_OPEN      = 73      # Stół otwarty / zmiana pokoju zwrócona
MSG_TAB_CLOSE     = 74      # Stół zamknięty
MSG_TAB_STATUS    = 88      # Status gry na stole (kody stanu 90, 92 itp.)
MSG_TAB_DRAW      = 92      # Ruch rysunkowy (Kalambury)
MSG_TAB_HISTORY   = 91      # Historia ruchów
MSG_GAME_STATE    = 90      # Stan gry na stole
MSG_PLAYER_ACTION = 84      # Akcja gracza (np. siadanie)
MSG_PLAYER_LEAVE  = 85      # Gracz wstał / opuścił stół
MSG_SETTINGS      = 89      # Ustawienia stołu

# Kody zdarzeń, które są ignorowane (nie drukowane do stdout)
# Usuń kod z tej listy jeśli chcesz zobaczyć surowe dane.
IGNORE_CODES = {
    18,  # Opcje serwera
    20,  # Tekst globalny
    22,  # Aktualizacja profilu
    23,  # Lista graczy globalnie
    27,  # Lista stołów (raw)
    28,  # Status kontaktów
    30,  # Ustawienia puli
    31,  # Lista pokojów
    32,  # Lista aktywnych pokojów
    51,  # Tekst lokalizacyjny
    70,  # Aktualizacja gracza na stole
    72,  # Potwierdzenie join (odbijamy je inaczej)
    74,  # Zamknięcie stołu
    88,  # Status gry (raw)
}

# Domyślna gra i pokój (można nadpisać argumentami CLI --game i --room)
DEFAULT_GAME = 'kalambury'
DEFAULT_ROOM = '100'

# Interwał heartbeat w sekundach (ping serwera, by nie zerwać połączenia)
HEARTBEAT_INTERVAL = 30

# Maksymalny czas oczekiwania na odpowiedź serwera (s)
WS_TIMEOUT = 60

# ─── Protokół JSON ─────────────────────────────────────────────────────────────

def encode(codes: List[int], strings: Optional[List[str]] = None) -> str:
    """
    Koduje wiadomość do formatu JSON wymaganego przez Kurnik.pl.

    Format: {"i":[kod1,kod2,...],"s":["str1","str2",...]}
      - "i" (integers) — tablica liczb całkowitych (kody akcji + argumenty)
      - "s" (strings)  — opcjonalna tablica stringów (np. treść wiadomości)

    Przykład użycia:
      encode([81, 42], ["Hej!"])  → chat na stole 42
      encode([72, 5])             → dołącz do stołu 5
      encode([1])                 → ping
      encode([])                  → heartbeat (puste)

    Aby dodać nową akcję: wywołaj encode([KOD, arg1, arg2], ["tekst"])
    """
    out = '{"i":[' + ','.join(map(str, codes)) + ']'
    if strings:
        escaped = ['"{}"'.format(s.replace('\\', '\\\\').replace('"', '\\"')) for s in strings]
        out += ',"s":[' + ','.join(escaped) + ']'
    return out + '}'


def decode(raw: str) -> List[Dict[str, Any]]:
    """
    Dekoduje surową odpowiedź z WebSocket (może zawierać wiele JSON-ów rozdzielonych '\n').

    Zwraca listę słowników {'i': [...], 's': [...]}.
    Nieprawidłowe linie są pomijane (błąd JSON nie przerywa przetwarzania).

    Modyfikacja: jeśli serwer zacznie wysyłać inne formaty,
    dodaj obsługę tutaj przed blokiem json.loads().
    """
    results = []
    lines = raw.split('\n') if '\n' in raw else [raw]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            results.append({
                'i': obj.get('i', []),
                's': obj.get('s', [])
            })
        except json.JSONDecodeError as e:
            # Loguj błędy parsowania tylko w trybie debug
            pass
    return results


# ─── Sesja HTTP ────────────────────────────────────────────────────────────────

_session  = requests.Session()
_cookies  = ''           # Ciąg Cookie: używany w nagłówkach WS
_last_ver = '264'        # Wersja klienta kurnik (wyciągana z HTML)


def get_session(game: str, room: str) -> Dict[str, Any]:
    """
    Inicjalizuje sesję HTTP z Kurnik.pl.

    Wysyła POST na stronę gry, aby:
      1. Otrzymać ciasteczka sesji (kt=, ksession=)
      2. Wyekstrahować parametry połączenia z HTML:
           - window.ge  → ID geograficzny
           - window.ap  → ID aplikacji
           - tf         → ID typu gry (używane w pierwszej ramce WS)
           - k2ver      → wersja klienta JS

    Zwraca słownik: {'ge': str, 'ap': str, 'tf': int, 'ver': str}

    Jak modyfikować:
      - Aby zmienić grę wystarczy zmienić parametr `game` (np. 'szachy', 'warcaby').
      - Jeśli sesja zwraca SESSION_WARN (brak kt=), sprawdź czy Kurnik nie
        zmienił sposobu wydawania ciasteczek — może potrzebny nagłówek 'Sec-Fetch-Site'.
    """
    global _cookies, _last_ver

    # Ustaw ciasteczka przed requestem
    _session.cookies.update({
        'kguest': '1',     # tryb gościa
        'kbeta':  'gs',    # beta flag (wymagane przez serwer)
        'kroom':  room,    # numer pokoju
    })

    try:
        response = _session.post(
            f'https://www.kurnik.pl/{game}/',
            data='gmid=gs',
            headers={
                'User-Agent':   UA,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin':       'https://www.kurnik.pl',
                'Referer':      f'https://www.kurnik.pl/{game}/',
                'Sec-Fetch-Site': 'same-origin',
            },
            timeout=10,
            allow_redirects=True,
        )
        response.raise_for_status()
        body = response.text

        # Zbuduj ciąg Cookie dla nagłówków WebSocket
        cookie_parts = ['kguest=1', 'kbeta=gs', f'kroom={room}']
        for k, v in _session.cookies.items():
            if k not in ('kguest', 'kbeta', 'kroom'):
                cookie_parts.append(f'{k}={v}')
        _cookies = '; '.join(cookie_parts)

        # Wyekstrahuj parametry JS z HTML strony
        ge  = _extract(r'window\.ge\s*=\s*(\d+)',  body) or ''
        ap  = _extract(r'window\.ap\s*=\s*(\d+)',  body) or ''
        tf  = int(_extract(r'tf\s*:\s*(\d+)',       body) or '1751')
        ver = _extract(r'k2ver\s*=\s*(\d+)',        body) or '264'
        _last_ver = ver

        # Zwróć status sesji do launchera
        status = 'SESSION_OK' if 'kt=' in _cookies else 'SESSION_WARN'
        print(status, flush=True)
        return {'ge': ge, 'ap': ap, 'tf': tf, 'ver': ver}

    except requests.RequestException as e:
        print(f'[BŁĄD HTTP] {e}', flush=True)
        raise


def _extract(pattern: str, text: str) -> Optional[str]:
    """Pomocnicza: wyciąga pierwszą grupę regexpa z tekstu lub zwraca None."""
    m = re.search(pattern, text)
    return m.group(1) if m else None


# ─── Parsowanie stołów ─────────────────────────────────────────────────────────

def parse_tables(codes: List[int], strings: List[str]) -> List[Dict[str, Any]]:
    """
    Parsuje wiadomość MSG_TABLES (kod 71) do listy stołów.

    Format ramki (kody): [71, block_size, strings_per_table, id1, p1, p2, ..., id2, ...]
    Format ramki (stringi): [params_st1, players_st1, params_st2, players_st2, ...]

    Zwraca listę słowników:
      {'id': int, 'params': str, 'players': str}

    Jak modyfikować:
      - Jeśli serwer zmieni format (block_size lub str_per_table), zaktualizuj
        indeksy f i si poniżej.
      - Aby pobrać więcej pól z tablicy 'strings', zwiększ str_per_table
        i dodaj klucze do słownika.
    """
    tables = []
    if len(codes) < 3:
        return tables

    block_size    = codes[1]   # ile kodów na jeden stół
    str_per_table = codes[2]   # ile stringów na jeden stół
    f  = 3    # indeks w codes (od 3 zaczynają się dane stołów)
    si = 0    # indeks w strings

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
    """
    Formatuje listę stołów do protokołu stdout dla launchera.

    Format wyjściowy:
      TABLES_START <n>
      TABLE <id> | <params> | <players>
      ...
      TABLES_END

    Launcher.py parsuje te linie w Bot._handle_line().
    Aby dodać nowe pola stołu, zmodyfikuj zarówno tę funkcję
    jak i Bot._handle_line() w launcher.py.
    """
    if not tables:
        return 'TABLES_EMPTY'
    lines = [f'TABLES_START {len(tables)}']
    for t in tables:
        players = t['players'] or '(brak graczy)'
        lines.append(f"TABLE {t['id']} | {t['params']} | {players}")
    lines.append('TABLES_END')
    return '\n'.join(lines)


# ─── Parsowanie wydarzeń na stole ─────────────────────────────────────────────

def parse_player_event(codes: List[int], strings: List[str], event_type: str) -> Optional[str]:
    """
    Parsuje zdarzenia gracza (wejście/wyjście ze stołu).

    codes[1] — ID stołu
    strings[0] — nick gracza

    event_type: 'JOIN' lub 'LEAVE'

    Zwraca string do stdout: 'PLAYER_JOIN <table> <nick>' lub None.
    """
    if len(codes) < 2 or not strings:
        return None
    table_id = codes[1]
    nick = strings[0]
    if event_type == 'JOIN':
        return f'PLAYER_JOIN {table_id} {nick}'
    elif event_type == 'LEAVE':
        return f'PLAYER_LEAVE {table_id} {nick}'
    return None


def parse_chat_message(codes: List[int], strings: List[str]) -> Optional[str]:
    """
    Parsuje wiadomość czatu (kod MSG_CHAT = 81).

    codes[1] — ID stołu
    strings[0] — treść (format: 'nick: tekst')

    Zwraca string: 'CHAT <table_id> <treść>' lub None.
    """
    if len(codes) < 2 or not strings:
        return None
    table_id = codes[1]
    content  = strings[0]
    return f'CHAT {table_id} {content}'


def parse_word_hint(strings: List[str]) -> Optional[str]:
    """
    Wykrywa słowo do zgadnięcia w Kalamburach.

    Kalambury wysyłają slowo przez wiadomość czatu w formacie specjalnym
    lub przez osobne zdarzenie. Ta funkcja sprawdza czy treść to hint.

    Zwraca 'WORD <słowo>' lub None.

    Jak modyfikować:
      Zmień wyrażenie regularne, jeśli serwer zmieni format podpowiedzi.
    """
    for s in strings:
        # Format: "+ [słowo]" lub zawiera tylko kreski i litery (hint)
        m = re.match(r'^\+\s*\[(.+?)\]', s)
        if m:
            return f'WORD {m.group(1)}'
        # Alternatywny format: "_ _ _ _" (ukryte słowo)
        if re.match(r'^[_\s]+$', s) and len(s) > 2:
            return f'WORD_HIDDEN {s.strip()}'
    return None


# ─── Połączenie WebSocket ──────────────────────────────────────────────────────

async def connect_ws(
    game: str, room: str,
    ge: str, ap: str,
    tf: int, ver: str,
    initial_table: int,
) -> None:
    """
    Główna pętla połączenia WebSocket z Kurnik.pl.

    Kolejność działania:
      1. Próba połączenia z kolejnymi hostami WS (WS_HOSTS).
      2. Wysłanie ramki inicjalizacyjnej z parametrami sesji.
      3. Uruchomienie trzech równoległych tasków:
           - heartbeat()  — wysyła ping co HEARTBEAT_INTERVAL sekund
           - receive()    — odbiera i przetwarza ramki z serwera
           - read_stdin() — odczytuje komendy z stdin (od launchera)

    Komendy stdin:
      <liczba>     → /join <liczba>
      /join <id>   → zmiana stołu
      /table       → zwraca aktualny stół
      /quit        → rozłącza
      <tekst>      → chat na aktualny stół

    Jak dodać nową komendę:
      W sekcji read_stdin() dodaj blok `elif line == '/moja_komenda':`.
    """
    current_table = initial_table

    # Próbuj kolejne hosty WS
    ws = None
    last_error = None
    for uri in WS_HOSTS:
        print(f'[WS] Próbuję: {uri}', flush=True)
        try:
            # Używamy asyncio.timeout (Python 3.11+) lub czekamy na coroutine normalnie
            try:
                ws = await asyncio.wait_for(
                    websockets.connect(
                        uri,
                        extra_headers={
                            'User-Agent': UA,
                            'Origin':     'https://www.kurnik.pl',
                            'Cookie':     _cookies,
                        },
                        ping_interval=None,   # Obsługujemy ping ręcznie
                        close_timeout=5,
                    ),
                    timeout=10,
                )
            except asyncio.TimeoutError:
                print(f'[WS] Timeout dla {uri}', flush=True)
                ws = None
                continue

            print(f'[WS] Połączono: {uri}', flush=True)
            break
        except Exception as e:
            last_error = e
            print(f'[WS] Nieudane {uri}: {e}', flush=True)
            ws = None

    if ws is None:
        print(f'[BŁĄD WS] Nie można połączyć: {last_error}', flush=True)
        raise ConnectionError(str(last_error))

    print('CONNECTED', flush=True)

    try:
        # ── Ramka inicjalizacyjna ────────────────────────────────────────────
        # Pierwsza ramka musi zawierać dane sesji w formacie wymaganym przez serwer.
        # tf    — ID gry (np. 1751 dla Kalambury)
        # autoid — losowy ID sesji (symuluje localStorage)
        # ap, ge — parametry geograficzne wyciągnięte z HTML strony
        # ver    — wersja klienta JS (k2ver)
        autoid = str(int(abs(hash(datetime.now())) % (10 ** 18)))
        init_frame = encode([tf], [
            f'+{autoid}|{ap}|{ge}',           # format: '+autoid|ap|ge'
            'pl',                              # język
            'b',                               # beta flag
            '',                                # pokój startowy (pusty = default)
            UA,                                # User-Agent
            f'/{int(time.time() * 1000)}/1',  # timestamp/wersja
            'w',                               # typ klienta (web)
            '1920x1080 1',                     # rozdzielczość ekranu
            f'ref:https://www.kurnik.pl/{game}/',
            f'ver:{ver}',
        ])
        await ws.send(init_frame)

        # ── Heartbeat task ───────────────────────────────────────────────────
        async def heartbeat():
            """
            Co HEARTBEAT_INTERVAL sekund wysyła pustą ramkę, aby serwer
            nie zerwał połączenia z powodu braku aktywności.
            Co 3 cykle heartbeatu (90 sekund) żąda listy stołów.

            Aby zmienić interwał: zmodyfikuj stałą HEARTBEAT_INTERVAL.
            Aby wyłączyć: usuń ten task z asyncio.gather().
            """
            tick = 0
            try:
                while True:
                    await asyncio.sleep(HEARTBEAT_INTERVAL)
                    await ws.send('{"i":[]}')
                    # Co 3 cykle heartbeatu żądaj listy stołów (90 sekund przy HEARTBEAT_INTERVAL=30)
                    tick = (tick + 1) % 3
                    if tick == 0:
                        await ws.send(encode([MSG_TABLES]))
            except asyncio.CancelledError:
                pass

        # ── Receive task ─────────────────────────────────────────────────────
        async def receive():
            """
            Odbiera wszystkie ramki z WebSocket i konwertuje je na komunikaty stdout.

            Każda ramka to słownik {'i': [...], 's': [...]}.
            Na podstawie kodu codes[0] wybieramy odpowiednią akcję.

            Jak dodać obsługę nowego kodu:
              Dodaj blok `elif code == NOWY_KOD:` w pętli while i wypisz
              odpowiedni komunikat do stdout.
            """
            nonlocal current_table
            try:
                while True:
                    try:
                        raw_data = await asyncio.wait_for(ws.recv(), timeout=WS_TIMEOUT)
                    except asyncio.TimeoutError:
                        print('[WS] Timeout odbioru — rozłączam', flush=True)
                        break

                    text = raw_data if isinstance(raw_data, str) else raw_data.decode('utf-8')

                    for msg in decode(text):
                        codes   = msg['i']
                        strings = msg['s']

                        if not codes:
                            continue

                        code = codes[0]

                        # ── Ping: odpowiedz natychmiast ──────────────────────
                        if code == MSG_PING:
                            await ws.send(encode([MSG_PONG]))
                            continue

                        # ── Lista stołów ─────────────────────────────────────
                        if code == MSG_TABLES:
                            tables = parse_tables(codes, strings)
                            print(format_tables(tables), flush=True)
                            # Jeśli podano stół startowy — dołącz automatycznie
                            if current_table:
                                await ws.send(encode([MSG_JOIN_TAB, current_table]))
                                print(f'JOINED {current_table}', flush=True)
                            continue

                        # ── Pomiń ignorowane kody ────────────────────────────
                        if code in IGNORE_CODES:
                            continue

                        # ── Chat na stole ─────────────────────────────────────
                        if code == MSG_CHAT:
                            chat_out = parse_chat_message(codes, strings)
                            if chat_out:
                                print(f'MSG {chat_out}', flush=True)
                                # Sprawdź czy to podpowiedź słowa (Kalambury)
                                word_hint = parse_word_hint(strings)
                                if word_hint:
                                    print(word_hint, flush=True)
                            continue

                        # ── Dołączenie gracza do stołu ────────────────────────
                        # Kod 84 = gracz siada przy stole
                        if code == MSG_PLAYER_ACTION:
                            event = parse_player_event(codes, strings, 'JOIN')
                            if event:
                                print(event, flush=True)
                            continue

                        # ── Opuszczenie stołu przez gracza ────────────────────
                        # Kod 85 = gracz wstaje od stołu
                        if code == MSG_PLAYER_LEAVE:
                            event = parse_player_event(codes, strings, 'LEAVE')
                            if event:
                                print(event, flush=True)
                            continue

                        # ── Aktualizacja stołu (gracze, wyniki) ───────────────
                        # Kod 73 = otwarto/zmieniono stół
                        if code == MSG_TAB_OPEN:
                            if len(codes) > 1:
                                current_table = codes[1]
                                status_str = strings[0] if strings else ''
                                print(f'STATUS {code} {current_table} {status_str}', flush=True)
                            continue

                        # ── Stan gry na stole (90) ───────────────────────────
                        if code == MSG_GAME_STATE:
                            # Kod 90 zawiera informacje o stanie gry (rysowanie, zgadywanie itp.)
                            if len(codes) > 1:
                                game_state = codes[1]
                                # game_state: 0=czekanie, 1=rysowanie, 2=zgadywanie
                                hint = strings[0] if strings else ''
                                if game_state == 1 and hint:
                                    # Rysowanie: wyświetl wskazówkę
                                    print(f'HINT Rysuj: {hint}', flush=True)
                                elif game_state == 2 and hint:
                                    # Zgadywanie: wyświetl słowo do zgadnięcia
                                    print(f'GUESS Zgaduj: {hint}', flush=True)
                            continue

                        # ── Ruch rysunkowy (92) ──────────────────────────────
                        if code == MSG_TAB_DRAW:
                            # Kod 92 zawiera ruch rysunkowy (x, y, pressure itp.)
                            # Zwykle format: [92, type, x, y, ...]
                            if len(codes) > 3:
                                draw_type = codes[1]  # 0=start, 1=move, 2=end
                                x = codes[2]
                                y = codes[3]
                                print(f'DRAW {draw_type} {x} {y}', flush=True)
                            continue

                        # ── Pozostałe wiadomości ze stringami ─────────────────
                        if strings:
                            # Wypisz jako MSG jeśli jest tekst
                            txt = ' '.join(strings)
                          #  print(f'MSG {txt}', flush=True)
                        elif len(codes) > 1:
                            # Wypisz surowe kody (debug)
                            codes_str = ','.join(map(str, codes))
                            print(f'RAW [{code}] {codes_str}', flush=True)

            except asyncio.CancelledError:
                pass
            except websockets.exceptions.ConnectionClosed as e:
                print(f'[WS] Połączenie zamknięte: {e}', flush=True)
            except Exception as e:
                print(f'[BŁĄD RECV] {e}', flush=True)

        # ── Stdin task ───────────────────────────────────────────────────────
        async def read_stdin():
            """
            Odczytuje komendy ze stdin (wpisane przez użytkownika lub
            przekazane przez launcher.py przez subprocess.stdin).

            Parsuje komendy i wysyła odpowiednie ramki WebSocket.
            EOF na stdin = sygnał zakończenia (launcher zamknął pipe).

            Jak dodać nową komendę:
              Dodaj blok `elif line == '/nowa_komenda':` w pętli while
              i wyślij odpowiednią ramkę przez `await ws.send(encode(...))`.
            """
            nonlocal current_table
            loop = asyncio.get_event_loop()
            try:
                while True:
                    # run_in_executor — nie blokuje pętli asyncio
                    line = await loop.run_in_executor(None, sys.stdin.readline)
                    if not line:          # EOF — launcher zamknął pipe
                        print('[STDIN] EOF — kończę', flush=True)
                        break

                    line = line.strip()
                    if not line:
                        continue

                    # Skrót: sama liczba → /join <liczba>
                    if re.match(r'^\d+$', line):
                        line = f'/join {line}'

                    # ── Komendy ──────────────────────────────────────────────

                    if line.startswith('/join '):
                        # Zmień stół — wyślij JOIN_TAB
                        try:
                            tid = int(line[6:].strip())
                            current_table = tid
                            await ws.send(encode([MSG_JOIN_TAB, tid]))
                            print(f'__TABLE_CHANGED__{tid}', flush=True)
                            print(f'JOINED {tid}', flush=True)
                            # Poproś o listę stołów aby GUI się odświeżyła
                            await asyncio.sleep(0.1)
                            await ws.send(encode([MSG_TABLES]))
                        except ValueError:
                            print('ERR nieprawidłowy numer stołu', flush=True)

                    elif line == '/table':
                        # Zwróć aktualny stół
                        print(f'CURRENT_TABLE {current_table}', flush=True)

                    elif line == '/tables':
                        # Poproś serwer o odświeżenie listy stołów
                        await ws.send(encode([MSG_TABLES]))
                        print('Refreshing tables...', flush=True)

                    elif line.startswith('/ext '):
                        # Wyślij rozszerzony komunikat na aktualny stół
                        # Format: /ext <tekst>
                        text = line[5:].strip()
                        if text:
                            if current_table:
                                await ws.send(encode([MSG_CHAT, current_table], [text]))
                                print(f'EXT {current_table} {text}', flush=True)
                            else:
                                print('ERR brak stołu — użyj /join <ID> najpierw', flush=True)
                        else:
                           print('ERR format: /ext <tekst>', flush=True)

                    elif line in ('/quit', '/exit'):
                        # Zamknij połączenie
                        await ws.close()
                        return

                    elif current_table:
                        # Domyślnie: wyślij jako chat na aktualny stół
                        await ws.send(encode([MSG_CHAT, current_table], [line]))

                    else:
                        print('ERR brak stołu — użyj /join <ID>', flush=True)

            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f'[BŁĄD STDIN] {e}', flush=True)

        # ── Uruchom wszystkie taski równolegle ───────────────────────────────
        hb   = asyncio.create_task(heartbeat())
        recv = asyncio.create_task(receive())
        inp  = asyncio.create_task(read_stdin())

        try:
            # Czekaj aż receive() lub read_stdin() się zakończy
            done, pending = await asyncio.wait(
                [recv, inp],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            # Anuluj wszystkie pozostałe taski
            for task in (hb, recv, inp):
                task.cancel()
            try:
                await asyncio.gather(hb, recv, inp, return_exceptions=True)
            except Exception:
                pass
            try:
                await ws.close()
            except Exception:
                pass
    except websockets.exceptions.ConnectionClosed as e:
        print(f'[WS] Połączenie zamknięte: {e}', flush=True)
    except Exception as e:
        print(f'[BŁĄD] {e}', flush=True)
        raise


# ─── Argumenty CLI ────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """
    Parsuje argumenty linii komend.

    Argumenty:
      --game  <nazwa>   Gra na Kurnik.pl (domyślnie: kalambury)
                        Inne przykłady: szachy, warcaby, chinczyk
      --room  <numer>   Pokój (domyślnie: 100)
      --table <numer>   Stół startowy; 0 = tylko obserwator
      --debug           Włącz szczegółowe logowanie (RAW frames)

    Modyfikacja:
      Dodaj nowy argument przez p.add_argument() przed return p.parse_args().
    """
    p = argparse.ArgumentParser(
        description='Kurnik.pl WebSocket Bot',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument('--game',  default=DEFAULT_GAME,
                   help=f'Gra (default: {DEFAULT_GAME})')
    p.add_argument('--room',  default=DEFAULT_ROOM,
                   help=f'Pokój (default: {DEFAULT_ROOM})')
    p.add_argument('--table', type=int, default=0,
                   help='Stół do automatycznego dołączenia (0 = obserwator)')
    p.add_argument('--debug', action='store_true',
                   help='Włącz szczegółowe logowanie')
    return p.parse_args()


# ─── Punkt wejścia ────────────────────────────────────────────────────────────

async def main() -> None:
    """
    Główna funkcja asynchroniczna.

    Kolejność:
      1. Parsuj argumenty CLI.
      2. Inicjalizuj sesję HTTP (get_session).
      3. Połącz przez WebSocket (connect_ws).

    Modyfikacja:
      Dodaj tu własną logikę inicjalizacji (np. logowanie, wczytywanie
      słownika odpowiedzi) przed wywołaniem connect_ws().
    """
    args = parse_args()

    if args.debug:
        # W trybie debug nie ignoruj żadnych kodów
        IGNORE_CODES.clear()

    print(f'BOT_START game={args.game} room={args.room} table={args.table}', flush=True)

    try:
        sess = get_session(args.game, args.room)
        await connect_ws(
            game=args.game,
            room=args.room,
            ge=sess['ge'],
            ap=sess['ap'],
            tf=sess['tf'],
            ver=sess['ver'],
            initial_table=args.table,
        )
    except KeyboardInterrupt:
        print('[PRZERWANO]', flush=True)
    except Exception as err:
        print(f'[BŁĄD] {err}', flush=True)
        sys.exit(1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n[PRZERWANO]', flush=True)
        sys.exit(0)
