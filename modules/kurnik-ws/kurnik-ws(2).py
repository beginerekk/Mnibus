#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kurnik-ws.py — bot/klient CLI dla kurnik.pl
Uruchamiany jako subprocess przez launcher.py lub samodzielnie z terminala.
Domyślna gra: kalambury, domyślny pokój: 100.

Komunikacja z launcherem odbywa się przez:
  - stdout  → bot wysyła ustrukturyzowane komunikaty (CONNECTED, MSG, JOINED…)
  - stdin   → launcher wysyła komendy (/join ID, tekst chatu, /quit)
"""

import argparse        # parsowanie argumentów wiersza poleceń (--game, --room, --table)
import asyncio         # pętla zdarzeń i współbieżność (async/await)
import json            # dekodowanie ramek JSON z WebSocketa
import websockets      # biblioteka WebSocket (pip install websockets)
import requests        # sesja HTTP do pobrania cookies (pip install requests)
import re              # wyrażenia regularne — wyciąganie ge/ap/tf/ver ze strony
import sys             # sys.exit, sys.stdin/stdout/stderr
import io              # TextIOWrapper — nadpisanie kodowania na Windows
from datetime          import datetime         # znacznik czasu w autoid i heartbeat
from typing            import Dict, List, Any  # podpowiedzi typów


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 1 — KODOWANIE UTF-8 NA WINDOWS
# Na Windows domyślne kodowanie konsoli to cp1250/cp852, co psuje polskie znaki.
# Nadpisujemy stdin/stdout/stderr na UTF-8 zanim cokolwiek wydrukujemy.
# errors='replace' → zamiast wyjątku przy nieznanym znaku wstawia '?'
# ══════════════════════════════════════════════════════════════════════════════
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    sys.stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding='utf-8', errors='replace')


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 2 — STAŁE GLOBALNE
# ══════════════════════════════════════════════════════════════════════════════

# User-Agent udający przeglądarkę Chrome — serwer kurnik.pl go sprawdza
UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/122.0.0.0 Safari/537.36'
)

# ── Kody wiadomości protokołu WebSocket kurnik.pl ─────────────────────────────
# Każda ramka WS to JSON: {"i": [kod, ...], "s": ["string1", ...]}
# Pole "i" (integers) zawiera kody liczbowe, "s" (strings) zawiera teksty.

PING     = 1    # serwer pyta czy żyjemy → odpowiadamy {"i":[2]} (PONG)
TABLES   = 71   # serwer wysyła listę stołów w pokoju
JOIN_TAB = 72   # my wysyłamy żądanie dołączenia do stołu
CHAT     = 81   # wysyłanie/odbieranie wiadomości czatu

# Zbiór kodów które ignorujemy (nie wyświetlamy, nie przetwarzamy).
# set zamiast list → sprawdzanie "czy jest w zbiorze" działa w O(1).
# Kody dotyczą m.in.: aktualizacji gracza (18,20,22-25,27-28), stanu pokoju
# (30-32), informacji o grze (51), duplikatów JOIN (72,74), itp.
IGNORE_CODES = {18, 20, 22, 23, 24, 25, 27, 28, 30, 31, 32,
                51, 70, 72, 74, 88, 90, 92}

# Wartości domyślne — można nadpisać przez argumenty CLI (--game, --room)
DEFAULT_GAME = 'kalambury'   # nazwa gry w URL: kurnik.pl/kalambury/
DEFAULT_ROOM = '100'         # numer pokoju


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 3 — PROTOKÓŁ WS: KODOWANIE I DEKODOWANIE RAMEK
# ══════════════════════════════════════════════════════════════════════════════

def encode(codes: List[int], strings: List[str] = None) -> str:
    """
    Buduje ramkę JSON do wysłania przez WebSocket.

    Format wyjściowy:
        {"i":[kod1,kod2,...]}
        {"i":[kod1,...],"s":["string1","string2",...]}

    Parametry:
        codes   — lista liczb całkowitych (kody operacji i parametry)
        strings — opcjonalna lista stringów (np. treść chatu, dane autoryzacji)

    Przykład:
        encode([81, 5], ["cześć"])
        → '{"i":[81,5],"s":["cześć"]}'
    """
    # Buduj część "i" (integers)
    out = '{"i":[' + ','.join(map(str, codes)) + ']'

    if strings:
        # Dodaj część "s" (strings) — każdy string musi mieć escaped \ i "
        out += ',"s":["'
        out += '","'.join(
            s.replace('\\', '\\\\').replace('"', '\\"') for s in strings
        )
        out += '"]'

    return out + '}'


def decode(raw: str) -> List[Dict[str, Any]]:
    """
    Parsuje surowy tekst odebrany z WebSocketa na listę słowników.

    Serwer może wysłać jedną lub wiele ramek JSON rozdzielonych '\\n'.
    Każda ramka to słownik: {'i': [...], 's': [...]}.

    Parametry:
        raw — surowy string z WebSocketa

    Zwraca:
        listę słowników, np. [{'i': [71, 2, 2, 3, 4], 's': ['', 'Gracz1']}]
    """
    results = []

    # Dziel po '\n' jeśli jest ich więcej (wiele ramek w jednym recv()),
    # w przeciwnym razie traktuj cały string jako jedną ramkę
    for line in (raw.split('\n') if '\n' in raw else [raw]):
        line = line.strip()
        if not line:
            continue  # pomijaj puste linie
        try:
            o = json.loads(line)
            # Zabezpiecz się na wypadek brakujących pól — zwróć puste listy
            results.append({'i': o.get('i', []), 's': o.get('s', [])})
        except json.JSONDecodeError:
            pass  # zepsute ramki ignoruj cicho

    return results


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 4 — SESJA HTTP (pobieranie cookies i parametrów strony)
# ══════════════════════════════════════════════════════════════════════════════

# Globalny obiekt sesji HTTP — przechowuje cookies między żądaniami
_session = requests.Session()

# Globalny string cookies — używany potem w nagłówkach WebSocket
_cookies = ''


def get_session(game: str, room: str) -> Dict[str, Any]:
    """
    Loguje się do kurnik.pl przez HTTP i wyciąga parametry potrzebne do WS.

    Kurnik wymaga aktywnej sesji HTTP (cookies) zanim WebSocket zostanie
    zaakceptowany. Ta funkcja:
      1. Ustawia wstępne cookies (kguest, kbeta, kroom)
      2. Robi POST na stronę gry (to inicjuje sesję po stronie serwera)
      3. Wyciąga z HTML parametry: ge, ap, tf, ver
      4. Buduje string cookies do użycia w nagłówku WS

    Parametry:
        game — nazwa gry (np. 'kalambury')
        room — numer pokoju (np. '100')

    Zwraca słownik:
        {'ge': str, 'ap': str, 'tf': int, 'ver': str}

    Wypisuje na stdout:
        'SESSION_OK'   — gdy w cookies jest 'kt=' (poprawna sesja)
        'SESSION_WARN' — gdy brak 'kt=' (sesja może nie działać)
    """
    global _cookies

    # Wstępne cookies — symulują przeglądarkę wchodzącą do gry jako gość
    _session.cookies.update({
        'kguest': '1',    # tryb gościa
        'kbeta':  'gs',   # wersja beta (wymagane przez serwer)
        'kroom':  room,   # numer pokoju do którego się łączymy
    })

    try:
        # POST na stronę gry — serwer w odpowiedzi ustawia cookies sesji (kt=...)
        # data='gmid=gs' to minimalne ciało żądania wymagane przez serwer
        response = _session.post(
            f'https://www.kurnik.pl/{game}/',
            data='gmid=gs',
            headers={
                'User-Agent':   UA,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin':       'https://www.kurnik.pl',
                'Referer':      f'https://www.kurnik.pl/{game}/',
            },
            timeout=10  # czekaj max 10 sekund na odpowiedź
        )
        body = response.text  # HTML strony — zawiera window.ge, window.ap itd.

        # ── Buduj string cookies z tego co serwer nam ustawił ─────────────────
        # Zaczynamy od znanych wartości, potem dopisujemy co sesja dostała
        cookie_str = f'kguest=1; kbeta=gs; kroom={room}'
        for k, v in _session.cookies.items():
            if k not in ('kguest', 'kbeta', 'kroom'):  # nie duplikuj znanych
                cookie_str += f'; {k}={v}'
        _cookies = cookie_str  # zapisz globalnie — używane w connect_ws()

        # ── Wyciągnij parametry z HTML za pomocą regex ────────────────────────

        # ge — ID gracza/sesji (window.ge = 12345)
        # Wzorzec: 'window.ge' + opcjonalne spacje + '=' + opcjonalne spacje + cyfry
        ge = (re.search(r'window\.ge\s*=\s*(\d+)', body) or [None, ''])[1] or ''

        # ap — dodatkowy parametr autoryzacji (window.ap = 67890)
        ap = (re.search(r'window\.ap\s*=\s*(\d+)', body) or [None, ''])[1] or ''

        # tf — "token frame" — kod pierwszej ramki WS autoryzacyjnej (tf: 1751)
        # Jest w HTML jako element obiektu konfiguracji JS: {tf: 1751, ...}
        tf_m = re.search(r'tf\s*:\s*(\d+)', body)
        tf   = int(tf_m[1]) if tf_m else 1751   # fallback = 1751 gdy nie znaleziono

        # ver — wersja klienta JS (k2ver = 264) — wysyłana w ramce autoryzacyjnej
        ver_m = re.search(r'k2ver\s*=\s*(\d+)', body)
        ver   = ver_m[1] if ver_m else '264'     # fallback = '264' gdy nie znaleziono

        # Wypisz status — launcher to przeczyta i wyświetli użytkownikowi
        print('SESSION_OK' if 'kt=' in _cookies else 'SESSION_WARN', flush=True)

        return {'ge': ge, 'ap': ap, 'tf': tf, 'ver': ver}

    except Exception as e:
        print(f'[BŁĄD HTTP] {e}', flush=True)
        raise  # przebij wyjątek wyżej — main() go złapie i zakończy program


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 5 — PARSOWANIE I FORMATOWANIE LISTY STOŁÓW
# ══════════════════════════════════════════════════════════════════════════════

def parse_tables(codes: List[int], strings: List[str]) -> List[Dict[str, Any]]:
    """
    Parsuje wiadomość TABLES (kod 71) na listę słowników stołów.

    Format ramki TABLES:
        i = [71, block_size, str_per_table, id_stołu_0, id_stołu_1, ...]
        s = [params_0, players_0, params_1, players_1, ...]

    Gdzie:
        block_size    — co ile elementów w 'i' jest jeden stół (zwykle 1)
        str_per_table — ile stringów z 's' należy do jednego stołu (zwykle 2)
        id_stołu      — unikalny numer stołu (pomijamy id <= 1, to "stół lobby")
        params        — ustawienia stołu (np. "3+2", "bez limitu")
        players       — lista graczy przy stole jako string

    Parametry:
        codes   — lista liczb z pola 'i' ramki
        strings — lista stringów z pola 's' ramki

    Zwraca listę słowników:
        [{'id': int, 'params': str, 'players': str}, ...]
    """
    tables = []
    if len(codes) < 3:
        return tables  # za krótka ramka — brak nagłówka, zwróć pustą listę

    block_size    = codes[1]   # krok iteracji po tablicy 'i'
    str_per_table = codes[2]   # krok iteracji po tablicy 's'

    f  = 3   # indeks w 'codes' — startujemy od pozycji 3 (po [71, bs, spt])
    si = 0   # indeks w 'strings' — startujemy od 0

    while f < len(codes) and si < len(strings) - 1:
        tid = codes[f]    # ID stołu z bieżącej pozycji
        if tid > 1:       # pomijaj "stół 0" i "stół 1" (to nie są prawdziwe stoły)
            tables.append({
                'id':      tid,
                'params':  strings[si]     if si     < len(strings) else '',
                'players': strings[si + 1] if si + 1 < len(strings) else '',
            })
        f  += block_size      # przejdź do następnego bloku w 'i'
        si += str_per_table   # przejdź do następnego bloku w 's'

    return tables


def format_tables(tables: List[Dict[str, Any]]) -> str:
    """
    Serializuje listę stołów do formatu tekstowego wysyłanego na stdout.

    Launcher odczytuje ten format linijka po linijce w _handle_line().
    Format jest celowo prosty — oddzielone ' | ' żeby łatwo parsować split().

    Format wyjściowy (wieloliniowy string):
        TABLES_START <liczba_stołów>
        TABLE <id> | <params> | <players>
        TABLE <id> | <params> | <players>
        ...
        TABLES_END

    Jeśli brak stołów: zwraca 'TABLES_EMPTY'

    Przykład wyjścia:
        TABLES_START 2
        TABLE 3 | 3+2 | Gracz1, Gracz2
        TABLE 7 |      | (brak graczy)
        TABLES_END
    """
    if not tables:
        return 'TABLES_EMPTY'

    lines = [f'TABLES_START {len(tables)}']
    for t in tables:
        players = t['players'] or '(brak graczy)'  # puste pole → czytelny komunikat
        lines.append(f"TABLE {t['id']} | {t['params']} | {players}")
    lines.append('TABLES_END')

    return '\n'.join(lines)  # jeden print() wyśle cały blok naraz


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 6 — POŁĄCZENIE WEBSOCKET I GŁÓWNA LOGIKA BOTA
# ══════════════════════════════════════════════════════════════════════════════

async def connect_ws(game: str, room: str, ge: str, ap: str,
                     tf: int, ver: str, initial_table: int) -> None:
    """
    Nawiązuje połączenie WebSocket z kurnik.pl i obsługuje komunikację.

    Trzy współbieżne zadania (asyncio.Task):
        heartbeat()   — co 30s wysyła pusty ping żeby serwer nie rozłączył
        receive()     — odbiera ramki WS i przekazuje je na stdout launchera
        read_stdin()  — czyta komendy od launchera (stdin) i wysyła na WS

    Komendy stdin (launcher → bot):
        <liczba>      → traktowane jako /join <liczba>
        /join <id>    → dołącz do stołu (wysyła JOIN_TAB, bez restartu bota)
        /table        → wypisz aktualny stół (CURRENT_TABLE <id>)
        /quit /exit   → zamknij połączenie i zakończ
        <inny tekst>  → wyślij jako wiadomość chatu na aktualny stół

    Odpowiedzi stdout (bot → launcher):
        CONNECTED               — nawiązano połączenie WS
        SESSION_OK/SESSION_WARN — wynik autoryzacji HTTP
        TABLES_START N          — start bloku listy stołów
        TABLE id | p | g        — jeden stół
        TABLES_END              — koniec bloku listy stołów
        JOINED <id>             — potwierdzenie zmiany stołu
        MSG <tekst>             — wiadomość z chatu/gry
        RAW [kod] kody          — surowa ramka do debugowania

    Parametry:
        game          — nazwa gry (np. 'kalambury')
        room          — numer pokoju (np. '100')
        ge            — ID sesji wyciągnięty ze strony HTML
        ap            — parametr autoryzacji ze strony HTML
        tf            — kod pierwszej ramki autoryzacyjnej (np. 1751)
        ver           — wersja klienta (np. '264')
        initial_table — stół do auto-dołączenia przy starcie (0 = obserwator)
    """
    current_table = initial_table  # aktywny stół — modyfikowany przez nonlocal

    print(f'[WS] Łączę z pokojem #{room} ({game})...', flush=True)

    uri = 'wss://x.kurnik.pl:17003/ws/'  # adres serwera WebSocket kurnik.pl

    # Nagłówki HTTP dołączane do handshake WebSocket
    headers = {
        'User-Agent': UA,
        'Origin':     'https://www.kurnik.pl',
        'Cookie':     _cookies,   # cookies z get_session() — klucz autoryzacji
    }

    try:
        # 'async with' otwiera połączenie i automatycznie je zamknie przy wyjściu
        async with websockets.connect(uri, extra_headers=headers) as ws:
            print('CONNECTED', flush=True)  # launcher zmieni status bota na 🟢

            # ── Wyślij ramkę autoryzacyjną ────────────────────────────────────
            # autoid = unikalny identyfikator sesji generowany z hash czasu
            # abs() bo hash() może być ujemny, % 10**18 ogranicza do 18 cyfr
            autoid = str(int(abs(hash(datetime.now())) % 10**18))

            # Pierwsza ramka używa kodu 'tf' pobranego ze strony HTML.
            # Strings opisują sesję — serwer weryfikuje ge, ap, język, platformę.
            await ws.send(encode([tf], [
                f'+{autoid}|{ap}|{ge}',              # unikalny ID | auth param | session ID
                'pl',                                 # język interfejsu (polski)
                'b',                                  # platforma: 'b' = browser
                '',                                   # pole opcjonalne (puste)
                UA,                                   # User-Agent — musi pasować do sesji HTTP
                f'/{int(datetime.now().timestamp() * 1000)}/1',  # timestamp w ms / numer połączenia
                'w',                                  # typ: 'w' = websocket
                '1920x1080 1',                        # rozdzielczość (może być dowolna)
                f'ref:https://www.kurnik.pl/{game}/', # skąd przyszliśmy (referer)
                f'ver:{ver}',                         # wersja klienta JS
            ]))

            # ══════════════════════════════════════════════════════════════════
            # ZADANIE 1: HEARTBEAT
            # Co 30 sekund wysyłaj pusty ping {"i":[]}.
            # Bez tego serwer po ~60s uzna bota za martwego i rozłączy.
            # ══════════════════════════════════════════════════════════════════
            async def heartbeat():
                try:
                    while True:
                        await asyncio.sleep(30)       # czekaj 30 sekund (nie blokuje)
                        await ws.send('{"i":[]}')     # wyślij pusty ping do serwera
                except asyncio.CancelledError:
                    pass  # zadanie anulowane przez finally — wyjdź cicho

            # ══════════════════════════════════════════════════════════════════
            # ZADANIE 2: ODBIERANIE WIADOMOŚCI Z WEBSOCKET
            # Czyta wszystkie ramki przychodzące z serwera.
            # Każdą interpretuje wg pierwszego kodu w polu 'i'.
            # ══════════════════════════════════════════════════════════════════
            async def receive():
                nonlocal current_table  # odczytujemy current_table (join auto)
                try:
                    while True:
                        data = await ws.recv()  # czekaj na następną ramkę (async)
                        # Ramka może być bytes lub str — ujednolicamy do str UTF-8
                        raw = data if isinstance(data, str) else data.decode('utf-8')

                        # decode() zwraca listę (serwer może wysłać kilka ramek naraz)
                        for msg in decode(raw):
                            code = msg['i'][0] if msg['i'] else None  # pierwszy kod = typ wiadomości

                            # ── PING (kod 1): serwer sprawdza czy żyjemy ──────
                            if code == PING:
                                await ws.send('{"i":[2]}')  # PONG = kod 2
                                continue

                            # ── TABLES (kod 71): lista stołów ─────────────────
                            if code == TABLES:
                                tables = parse_tables(msg['i'], msg['s'])
                                # Wyślij sformatowaną listę na stdout → launcher ją sparsuje
                                print(format_tables(tables), flush=True)
                                # Jeśli bot ma przypisany stół (--table N) → dołącz automatycznie
                                if current_table:
                                    await ws.send(encode([JOIN_TAB, current_table]))
                                    print(f'JOINED {current_table}', flush=True)
                                continue

                            # ── Kody do zignorowania ──────────────────────────
                            if code in IGNORE_CODES:
                                continue  # nie wyświetlaj, nie loguj

                            # ── Pozostałe wiadomości ──────────────────────────
                            if msg['s']:
                                # Wiadomość tekstowa (chat, info o grze, itp.)
                                # Prefix 'MSG ' → launcher wyświetli bez tego prefixu
                                print('MSG ' + ' '.join(msg['s']), flush=True)
                            elif len(msg['i']) > 1:
                                # Ramka tylko z kodami, bez stringów — przydatne do debug
                                codes_str = ','.join(map(str, msg['i']))
                                print(f'RAW [{code}] {codes_str}', flush=True)

                except asyncio.CancelledError:
                    pass  # anulowane — wyjdź cicho
                except Exception as e:
                    print(f'[BŁĄD RECV] {e}', flush=True)

            # ══════════════════════════════════════════════════════════════════
            # ZADANIE 3: ODCZYT STDIN (komendy od launchera)
            # readline() jest funkcją blokującą (czeka na dane z pipe'a).
            # Używamy run_in_executor() żeby uruchomić ją w osobnym wątku
            # i nie blokować pętli asyncio — inne taski działają normalnie.
            # ══════════════════════════════════════════════════════════════════
            async def read_stdin():
                nonlocal current_table  # modyfikujemy aktualny stół
                loop = asyncio.get_event_loop()
                try:
                    while True:
                        # Uruchom blokujące readline() w puli wątków (ThreadPoolExecutor)
                        line = await loop.run_in_executor(None, sys.stdin.readline)
                        if not line:
                            # readline() zwróciło '' = EOF (launcher zamknął stdin pipe)
                            break
                        line = line.strip()    # usuń whitespace i \n
                        if not line:
                            continue  # pusta linia — nic nie rób

                        # Sama liczba (np. "5") → traktuj jak "/join 5"
                        # Skrót dla launchera — nie musi wysyłać pełnej komendy
                        if re.match(r'^\d+$', line):
                            line = f'/join {line}'

                        # ── /join <id> — zmień stół BEZ restartu bota ─────────
                        if line.startswith('/join '):
                            try:
                                tid = int(line[6:].strip())    # wyciągnij ID po '/join '
                                current_table = tid             # zapamiętaj nowy stół
                                await ws.send(encode([JOIN_TAB, tid]))   # wyślij do serwera
                                print(f'JOINED {tid}', flush=True)       # potwierdź launcherowi
                            except ValueError:
                                print('ERR nieprawidłowy numer stołu', flush=True)

                        # ── /table — zapytaj o aktualny stół ─────────────────
                        elif line == '/table':
                            print(f'CURRENT_TABLE {current_table}', flush=True)

                        # ── /quit lub /exit — zakończ gracefully ──────────────
                        elif line in ('/quit', '/exit'):
                            await ws.close()   # zamknij WS zanim wyjdziemy
                            return             # zakończ tę funkcję

                        # ── zwykły tekst — wyślij jako chat ───────────────────
                        elif current_table:
                            # encode([CHAT=81, id_stołu], [treść]) → ramka WS
                            await ws.send(encode([CHAT, current_table], [line]))

                        # ── brak wybranego stołu — błąd ───────────────────────
                        else:
                            print('ERR brak stołu, użyj /join ID', flush=True)

                except asyncio.CancelledError:
                    pass  # anulowane przez finally — wyjdź cicho
                except Exception as e:
                    print(f'[BŁĄD STDIN] {e}', flush=True)

            # ── Utwórz i uruchom wszystkie trzy taski współbieżnie ───────────
            hb   = asyncio.create_task(heartbeat())    # task heartbeat (tło)
            recv = asyncio.create_task(receive())      # task odbierania WS
            inp  = asyncio.create_task(read_stdin())   # task odczytu stdin

            try:
                # gather() czeka aż OBA główne taski (recv i inp) zakończą się.
                # Heartbeat działa w tle — anulujemy go dopiero w finally.
                await asyncio.gather(recv, inp)
            finally:
                # Sprzątanie niezależnie od przyczyny wyjścia (błąd, /quit, EOF)
                hb.cancel()    # zatrzymaj heartbeat
                recv.cancel()  # zatrzymaj odbieranie (może być w toku)
                inp.cancel()   # zatrzymaj czytanie stdin
                try:
                    await ws.close()  # zamknij połączenie WS
                except Exception:
                    pass  # może być już zamknięte — ignoruj

    except Exception as e:
        print(f'[BŁĄD WS] {e}', flush=True)
        raise  # przebij do main() który wypisze błąd i wywoła sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 7 — PARSOWANIE ARGUMENTÓW I PUNKT WEJŚCIA
# ══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    """
    Parsuje argumenty wiersza poleceń.

    Dostępne argumenty:
        --game  NAZWA   gra (default: kalambury) — nazwa w URL kurnik.pl
        --room  NUMER   pokój (default: 100)
        --table NUMER   stół do auto-dołączenia (default: 0 = obserwator)

    Launcher wywołuje bota np.:
        python kurnik-ws.py --game kalambury --room 100 --table 5
    """
    p = argparse.ArgumentParser(description='Kurnik.pl bot CLI')
    p.add_argument('--game',  default=DEFAULT_GAME,
                   help=f'Gra (default: {DEFAULT_GAME})')
    p.add_argument('--room',  default=DEFAULT_ROOM,
                   help=f'Pokój (default: {DEFAULT_ROOM})')
    p.add_argument('--table', type=int, default=0,
                   help='Stół do automatycznego dołączenia (0 = obserwator)')
    return p.parse_args()


async def main() -> None:
    """
    Główna funkcja async — inicjalizuje wszystko i wchodzi w pętlę WS.

    Kolejność działań:
        1. Sparsuj argumenty CLI
        2. Wypisz BOT_START (launcher to odczyta)
        3. Pobierz sesję HTTP → cookies + parametry ge/ap/tf/ver
        4. Połącz WebSocket i obsługuj komunikację do zakończenia
    """
    args  = parse_args()
    game  = args.game
    room  = args.room
    table = args.table

    # Informuj launcher o parametrach startu (wyświetlone w logu jako 🚀)
    print(f'BOT_START game={game} room={room} table={table}', flush=True)

    try:
        sess = get_session(game, room)   # krok 3: HTTP → cookies + parametry
        await connect_ws(                # krok 4: WS → główna pętla
            game, room,
            sess['ge'], sess['ap'], sess['tf'], sess['ver'],
            table
        )
    except Exception as err:
        print(f'[BŁĄD] {err}', flush=True)
        sys.exit(1)   # niezerowy kod wyjścia sygnalizuje błąd


# ── Punkt wejścia programu ────────────────────────────────────────────────────
# Uruchamia się tylko gdy plik jest wywołany bezpośrednio:
#   python kurnik-ws.py
# Nie uruchamia się gdy plik jest importowany jako moduł (import kurnik_ws).
if __name__ == '__main__':
    try:
        asyncio.run(main())   # uruchom pętlę zdarzeń asyncio z funkcją main()
    except KeyboardInterrupt:
        # Ctrl+C w terminalu — wyjdź elegancko bez długiego traceback
        print('\n[PRZERWANO]', flush=True)
        sys.exit(0)
