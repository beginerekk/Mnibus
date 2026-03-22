#!/usr/bin/env python3
# ↑ Ta linia mówi systemowi operacyjnemu żeby uruchomił ten plik
#   za pomocą interpretera Pythona 3. Bez niej na Linuksie/Mac
#   plik nie wiedziałby jak go uruchomić. Na Windows nie ma znaczenia.

# -*- coding: utf-8 -*-
# ↑ Deklaracja kodowania pliku. Mówi Pythonowi że ten plik tekstowy
#   jest zapisany w UTF-8 (kodowanie obsługujące polskie znaki ąęśćźżółń).
#   Bez tego Python 2 miałby problemy. W Pythonie 3 to głównie konwencja.

# ==============================================================================
# CO ROBI TEN PLIK?
# ==============================================================================
# To jest "bot" — program który łączy się z serwisem kurnik.pl przez internet
# i podszywa się pod normalnego użytkownika grającego w Kalambury.
#
# Schemat działania:
#   1. Wysyłamy żądanie HTTP (jak przeglądarka) → dostajemy "przepustkę" (cookies)
#   2. Używamy tej przepustki żeby otworzyć połączenie WebSocket (WS)
#      WebSocket to jak otwarty kanał rozmowy: raz się połączysz i możesz
#      wysyłać/odbierać wiadomości w obie strony bez przerywania połączenia.
#   3. Przez ten kanał rozmawiamy z serwerem: dołączamy do pokoju/stołu,
#      wysyłamy wiadomości na czat, odbieramy co inni piszą.
#
# Ten plik jest uruchamiany przez launcher.py jako osobny proces (subprocess).
# Launcher zarządza wieloma takimi procesami jednocześnie.
# Komunikują się przez:
#   stdout (wyjście) → bot wypisuje dane → launcher je odczytuje
#   stdin  (wejście) → launcher wysyła komendy → bot je odczytuje

# ==============================================================================
# IMPORTY — "używamy zewnętrznych narzędzi"
# ==============================================================================
# Python ma wbudowane biblioteki (moduły) do różnych zadań.
# Żeby z nich skorzystać, trzeba je najpierw "zaimportować".
# To jak powiedzenie: "przynieś mi z półki narzędzie X, będę go używać".

import argparse
# ↑ Narzędzie do obsługi argumentów wiersza poleceń.
#   Dzięki niemu możemy uruchomić bota tak:
#     python kurnik-ws.py --room 200 --table 5
#   i program automatycznie odczyta te wartości.
#   Gdybyś chciał dodać nowy argument (np. --nick), tu byś to robił.

import asyncio
# ↑ Narzędzie do "asynchronicznego" programowania.
#   Wyobraź sobie kelnera w restauracji: zamiast stać i czekać aż kuchnia
#   przygotuje danie dla jednego klienta (blokowanie), idzie do następnego
#   stolika i przyjmuje zamówienia (asynchroniczność).
#   asyncio pozwala programowi "czekać" na dane z internetu
#   bez blokowania pozostałych zadań.
#   Funkcje z "async def" i "await" korzystają z asyncio.

import json
from pickle import INT
from shlex import join
# ↑ Narzędzie do pracy z formatem JSON.
#   JSON to format danych wyglądający tak: {"klucz": "wartość", "liczba": 42}
#   Serwer kurnik.pl wysyła dane właśnie w tym formacie.
#   json.loads(tekst)   → zamienia tekst JSON na słownik Pythona
#   json.dumps(słownik) → zamienia słownik Pythona na tekst JSON

import websockets
# ↑ Zewnętrzna biblioteka do obsługi WebSocket.
#   NIE jest wbudowana w Pythona — trzeba ją zainstalować:
#     pip install websockets
#   WebSocket to protokół internetowy pozwalający na dwukierunkową
#   komunikację w czasie rzeczywistym (inaczej niż zwykłe HTTP
#   gdzie musisz za każdym razem pytać od nowa).

import requests
# ↑ Zewnętrzna biblioteka do wysyłania żądań HTTP.
#   NIE jest wbudowana — pip install requests
#   Używamy jej do pierwszego kroku: zalogowania się na kurnik.pl
#   i pobrania "przepustki" (cookies) potrzebnej do WebSocket.
#   To jak wejście na stronę w przeglądarce, ale z poziomu kodu.

import re
# ↑ Narzędzie do "wyrażeń regularnych" (Regular Expressions).
#   Wyrażenia regularne to wzorce do wyszukiwania tekstu.
#   Przykład: wzorzec r'\d+' oznacza "jedna lub więcej cyfr".
#   Używamy re.search(wzorzec, tekst) żeby znaleźć wartości
#   w kodzie HTML strony kurnik.pl (np. numer wersji, ID sesji).

import sys
# ↑ Narzędzie dostępu do systemu operacyjnego.
#   Używamy go do:
#   sys.exit(kod)   → zakończ program (0 = sukces, 1 = błąd)
#   sys.stdin       → wejście standardowe (gdzie launcher pisze komendy)
#   sys.stdout      → wyjście standardowe (gdzie bot pisze odpowiedzi)
#   sys.platform    → nazwa systemu ('win32' na Windows, 'linux' na Linux)

import io
# ↑ Narzędzie do operacji wejścia/wyjścia.
#   Używamy tylko jednej rzeczy: io.TextIOWrapper
#   To "owijacz" który pozwala określić kodowanie strumienia tekstu.
#   Potrzebujemy go tylko na Windows do naprawienia problemu z UTF-8.

from datetime import datetime
# ↑ Import tylko klasy "datetime" z modułu "datetime".
#   Używamy jej do: datetime.now() → aktualna data i godzina
#   Potrzebujemy tego do wygenerowania unikalnego ID sesji
#   i znacznika czasu w pierwszej wiadomości autoryzacyjnej.

from typing import Dict, List, Any
# ↑ Import "podpowiedzi typów" — to tylko dla czytelności kodu.
#   Dict[str, Any] → słownik z kluczami str i dowolnymi wartościami
#   List[int]      → lista liczb całkowitych
#   Python ich nie wymaga, ale edytory kodu (np. VSCode) je rozumieją
#   i podpowiadają co dana funkcja przyjmuje i zwraca.
#   Gdybyś chciał je usunąć, program działałby tak samo.


# ==============================================================================
# SEKCJA 1 — NAPRAWIENIE KODOWANIA NA WINDOWS
# ==============================================================================
# PROBLEM: Windows domyślnie używa starszego kodowania tekstu (cp1250 lub cp852)
# które nie obsługuje dobrze wszystkich polskich znaków i emoji.
# Jeśli bota uruchomisz na Windows bez tej poprawki, możesz zobaczyć
# dziwne znaki zamiast "ą", "ę", "ś" albo program może się wysypać.
#
# ROZWIĄZANIE: Zamieniamy standardowe strumienie tekstu na wersje UTF-8.
# UTF-8 to kodowanie obsługujące wszystkie języki świata i emoji.
#
# Dlaczego tylko na win32? Na Linux i Mac domyślne kodowanie to już UTF-8,
# więc ta poprawka jest tam niepotrzebna.
#
# JAK EDYTOWAĆ: Tej sekcji nie musisz zmieniać. Jeśli masz problemy
# z kodowaniem na specyficznej wersji Windows, możesz zmienić
# 'utf-8' na inne kodowanie (np. 'cp1250'), ale nie polecamy tego.

if sys.platform == 'win32':
    # sys.platform == 'win32' → True tylko na Windows (nawet 64-bitowym)
    # Jeśli jesteśmy na Windows, zamieniamy strumienie:

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    # ↑ sys.stdout.buffer → surowy strumień bajtów (nie tekstu)
    #   io.TextIOWrapper(...)  → owijamy go żeby traktował bajty jako UTF-8
    #   errors='replace'       → jeśli natrafi na bajt którego nie umie
    #                            przetłumaczyć na UTF-8, wstaw '?' zamiast
    #                            rzucać błąd i zatrzymywać program

    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    # ↑ stderr to gdzie Python wypisuje komunikaty o błędach.
    #   Też musi być UTF-8 żeby komunikaty z polskimi znakami były czytelne.

    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
    # ↑ stdin to gdzie program odczytuje dane od launchera.
    #   Launcher może wysłać polskie znaki, więc stdin też musi być UTF-8.


# ==============================================================================
# SEKCJA 2 — STAŁE (WARTOŚCI KTÓRE SIĘ NIE ZMIENIAJĄ)
# ==============================================================================
# Stałe to zmienne które ustawiamy raz na początku i nie zmieniamy.
# Piszemy je WIELKIMI_LITERAMI żeby od razu było widać że to stałe.
# To jak "ustawienia" programu zebrane w jednym miejscu.
# JEŚLI CHCESZ COŚ ZMIENIĆ — zacznij od tej sekcji.

# ── User-Agent ────────────────────────────────────────────────────────────────
UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/122.0.0.0 Safari/537.36'
)
# ↑ "Wizytówka" którą wysyłamy serwerowi żeby myślał że jesteśmy
#   prawdziwą przeglądarką Chrome na Windows 10.
#   Serwer kurnik.pl sprawdza ten nagłówek. Bez niego może odrzucić połączenie.
#   Długi string jest podzielony na 3 linie dla czytelności — Python łączy
#   sąsiadujące stringi w nawiasach automatycznie w jeden.
#
#   JAK EDYTOWAĆ: Jeśli kurnik.pl zacznie blokować tę wizytówkę,
#   zmień numer wersji Chrome (122.0.0.0) na nowszy, np. 124.0.0.0.
#   Możesz też podmienić na User-Agent z Firefox lub Edge.
#   Aktualny UA swojej przeglądarki znajdziesz wpisując w Google:
#   "what is my user agent"


# ── Kody protokołu WebSocket kurnik.pl ───────────────────────────────────────
# Kurnik.pl ma własny protokół komunikacji przez WebSocket.
# Każda wiadomość to obiekt JSON z dwoma polami:
#   "i" (integers) → lista liczb, PIERWSZA to KOD określający typ wiadomości
#   "s" (strings)  → lista tekstów z danymi
#
# Przykład wiadomości od serwera:
#   {"i": [71, 1, 2, 3, 5, 7], "s": ["3+2", "Jan", "", "Anna"]}
#            ↑                           ↑
#        kod 71 = lista stołów        dane stołów
#
# NUMERY KODÓW odkryliśmy przez obserwację ruchu sieciowego w przeglądarce.
# Możesz to zrobić sam: w Chrome otwórz DevTools (F12) → zakładka "Network"
# → filtr "WS" → kliknij na połączenie WebSocket → zakładka "Messages"
# i obserwuj co serwer wysyła/odbiera.

PING = 1
# ↑ Kod "ping" — serwer wysyła co jakiś czas żeby sprawdzić czy żyjemy.
#   My musimy odpowiedzieć PONG (kod 2).
#   JAK EDYTOWAĆ: Nie zmieniaj — to stały kod protokołu kurnika.

TABLES = 71
# ↑ Kod "lista stołów" — serwer wysyła gdy dołączamy do pokoju.
#   Zawiera informacje o wszystkich stołach: ID, ustawienia, gracze.
#   JAK EDYTOWAĆ: Nie zmieniaj — to stały kod protokołu kurnika.

JOIN_TAB = 72
# ↑ Kod "dołącz do stołu" — MY wysyłamy żeby dołączyć do konkretnego stołu.
#   Format: {"i": [72, ID_stołu]}
#   JAK EDYTOWAĆ: Nie zmieniaj — to stały kod protokołu kurnika.

CHAT = 81
# ↑ Kod "wiadomość czatu" — używamy do wysyłania/odbierania wiadomości.
#   Format wysyłania: {"i": [81, ID_stołu], "s": ["treść wiadomości"]}
#   JAK EDYTOWAĆ: Nie zmieniaj — to stały kod protokołu kurnika.

SELFNAME = 31

# ── Kody do zignorowania ─────────────────────────────────────────────────────
IGNORE_CODES = {18, 20, 22, 23, 24, 25, 27, 28, 30, 32,
                51, 70, 72, 74, 88, 90, 92}
# ↑ Zbiór (set) kodów wiadomości które dostajemy od serwera ale które
#   nas nie interesują i chcemy je zignorować.
#
#   Dlaczego set {} a nie lista []?
#   Lista [18, 20, ...] → sprawdzenie "czy 72 jest na liście" wymaga
#                          przejrzenia całej listy od początku (wolno)
#   Zbiór {18, 20, ...} → sprawdzenie "czy 72 jest w zbiorze" jest
#                          natychmiastowe niezależnie od rozmiaru (szybko)
#
#   Co oznaczają te kody (odkryte przez obserwację ruchu):
#   18, 20, 22-25, 27-28 → aktualizacje informacji o graczach
#   30-32                → aktualizacje stanu pokoju/sali
#   51                   → informacje o grze
#   70, 74               → potwierdzenia związane z listą stołów
#   88, 90, 92           → różne powiadomienia systemowe
#
#   JAK EDYTOWAĆ:
#   Jeśli chcesz ZOBACZYĆ co serwer wysyła dla danego kodu (np. dla kodu 30),
#   usuń go z tego zbioru — w logu pojawią się wpisy "RAW [30] 30,5,1,0".
#   Jeśli odkryjesz znaczenie kodu i chcesz go obsłużyć, usuń go stąd
#   i dodaj obsługę w funkcji receive() w SEKCJI 6.


# ── Domyślne wartości ─────────────────────────────────────────────────────────
DEFAULT_GAME = 'kalambury'
# ↑ Nazwa gry używana w adresie URL: https://www.kurnik.pl/kalambury/
#   JAK EDYTOWAĆ: Zmień na inną grę z kurnik.pl.
#   Dostępne gry (nazwa w URL): szachy, warcaby, literaki, chinczyk,
#   go, backgammon, reversi, brydz, kierki, remik, hex, gomoku, bierki
#   UWAGA: Musisz zmienić też DEFAULT_GAME w launcher.py żeby było spójnie!

DEFAULT_ROOM = '100'
# ↑ Domyślny numer pokoju. Pokoje na kurnik.pl mają numery 100, 200, 300 itd.
#   JAK EDYTOWAĆ: Zmień na dowolny numer pokoju który istnieje na kurnik.pl.
#   Można też podać przez argument: python kurnik-ws.py --room 200


# ==============================================================================
# SEKCJA 3 — KODOWANIE I DEKODOWANIE WIADOMOŚCI
# ==============================================================================
# Te dwie funkcje to "tłumacze" między formatem który rozumie serwer
# a tym który rozumie Python.

def encode(codes: List[int], strings: List[str] = None) -> str:
    # ↑ Definicja funkcji "encode" (zakoduj/zbuduj wiadomość).
    #   Przyjmuje: codes   → lista liczb (np. [81, 5])
    #              strings → opcjonalna lista tekstów (np. ["cześć"])
    #              strings=None → domyślna wartość: jeśli nie podasz, strings=None
    #   Zwraca:   tekst JSON gotowy do wysłania przez WebSocket (-> str)
    #
    #   Dwukropki (codes: List[int]) to "podpowiedzi typów" — nieobowiązkowe,
    #   tylko dla czytelności. Python ich nie sprawdza w czasie działania.
    """
    Buduje wiadomość JSON do wysłania przez WebSocket.

    PRZYKŁADY UŻYCIA:
        encode([2])
        → '{"i":[2]}'
        Zastosowanie: odpowiedź PONG na ping serwera

        encode([72, 5])
        → '{"i":[72,5]}'
        Zastosowanie: dołącz do stołu numer 5

        encode([81, 5], ["Hej wszystkim!"])
        → '{"i":[81,5],"s":["Hej wszystkim!"]}'
        Zastosowanie: wyślij wiadomość czatu na stół numer 5

    JAK DODAĆ NOWY TYP WIADOMOŚCI:
        Znajdź kod wiadomości (obserwując ruch WS w przeglądarce)
        i użyj: await ws.send(encode([KOD, parametry], ["teksty"]))
    """

    # Buduj część "i" — lista liczb w formacie JSON
    # map(str, codes) → zamienia każdą liczbę na tekst: [81, 5] → ["81", "5"]
    # ','.join(...)   → łączy teksty przecinkami: "81,5"
    # Wynik: '{"i":[81,5]'
    out = '{"i":[' + ','.join(map(str, codes)) + ']'

    if strings:
        # Jeśli podano teksty (strings nie jest None i nie jest pustą listą)
        out += ',"s":["'

        # Dla każdego tekstu w strings przeprowadź "escaping" (ucieczkę znaków):
        # .replace('\\', '\\\\') → zmień \ na \\ (jeden backslash → dwa backslashe)
        # .replace('"', '\\"')   → zmień " na \" (cudzysłów → escaped cudzysłów)
        # To ważne! Gdybyś wysłał tekst z " bez escape, JSON byłby zepsuty.
        # Przykład: tekst 'piszę "cześć"' → 'piszę \\"cześć\\"'
        #
        # "for s in strings" → dla każdego tekstu s na liście strings
        # To jest "generator expression" — skrócony zapis pętli for
        # '","'.join([...]) → połącz przetworzone stringi separatorem ","
        out += '","'.join(
            s.replace('\\', '\\\\').replace('"', '\\"') for s in strings
        )
        out += '"]'
        # Zamknij tablicę stringów

    return out + '}'
    # Na końcu zamknij obiekt JSON klamrą "}"


def decode(raw: str) -> List[Dict[str, Any]]:
    # ↑ Funkcja "decode" (zdekoduj/odczytaj wiadomość od serwera).
    #   Przyjmuje: raw → surowy tekst odebrany z WebSocket (str)
    #   Zwraca:   lista słowników Python {'i': [...], 's': [...]}
    """
    Zamienia tekst JSON z WebSocketa na listę słowników Pythona.

    DLACZEGO LISTA a nie jeden słownik?
    Serwer może wysłać kilka wiadomości naraz, rozdzielonych znakiem nowej
    linii (\n). Np.:
        '{"i":[1]}\n{"i":[71,1,2,3],"s":["","Jan"]}'
    To są DWIE wiadomości. Musimy je obie przetworzyć.

    PRZYKŁAD:
        Wejście: '{"i":[81,3],"s":["Hej!"]}'
        Wyjście: [{'i': [81, 3], 's': ['Hej!']}]

    JAK EDYTOWAĆ: Tej funkcji raczej nie musisz zmieniać.
    Jeśli serwer zmieni format wiadomości, tutaj byś to naprawiał.
    """

    results = []  # lista na wyniki — na początku pusta

    # Sprawdź czy w tekście są znaki nowej linii (\n)
    # Jeśli tak → wiele wiadomości → podziel na linie i przetwórz każdą
    # Jeśli nie → jedna wiadomość → traktuj cały tekst jako jedną linię
    # raw.split('\n') → dzieli tekst po znakach nowej linii
    # Wynik np.: ['{"i":[1]}', '{"i":[71]}', ''] (ostatni element może być pusty)
    for line in (raw.split('\n') if '\n' in raw else [raw]):

        line = line.strip()
        # .strip() → usuwa białe znaki (spacje, \n, \r) z początku i końca
        # "  hello  " → "hello"

        if not line:
            continue
            # Jeśli linia jest pusta po strip(), pomiń ją i idź do następnej.
            # "continue" to słowo kluczowe: "przejdź do następnej iteracji pętli"

        try:
            # Spróbuj sparsować JSON
            o = json.loads(line)
            # json.loads → zamienia tekst JSON na słownik Pythona
            # '{"i":[1]}' → {'i': [1]}

            results.append({'i': o.get('i', []), 's': o.get('s', [])})
            # .get('i', []) → pobierz wartość klucza 'i', a jeśli nie istnieje zwróć []
            # To zabezpieczenie: niektóre wiadomości nie mają pola 's'
            # results.append → dodaj słownik na koniec listy results

        except json.JSONDecodeError:
            pass
            # Jeśli JSON jest zepsuty/nieprawidłowy, zignoruj linię.
            # "pass" → nic nie rób, idź dalej

    return results


# ==============================================================================
# SEKCJA 4 — SESJA HTTP (logowanie i pobieranie "przepustki")
# ==============================================================================
# Zanim możemy połączyć się przez WebSocket, musimy "zalogować się"
# na stronie kurnik.pl przez HTTP (jak przeglądarka). Serwer daje nam
# wtedy "cookies" — małe pliki z tokenami/identyfikatorami które
# potwierdzają że jesteśmy "zalogowanym" użytkownikiem.
#
# Bez tych cookies WebSocket zostałby odrzucony przez serwer.

_session = requests.Session()
# ↑ Tworzymy obiekt "sesji HTTP" — jest jak przeglądarka która
#   zapamiętuje cookies między żądaniami.
#   Podkreślnik na początku (_session) to konwencja Pythona:
#   "ta zmienna jest wewnętrzna, nie używaj jej z zewnątrz pliku".
#   Jest globalna bo używamy jej w funkcji get_session().

_cookies = ''
# ↑ Globalny string z cookies który będziemy wysyłać z każdym żądaniem WS.
#   Na początku pusty — wypełniamy go w get_session().
#   Przykładowa wartość po zalogowaniu:
#   'kguest=1; kbeta=gs; kroom=100; kt=abc123def456'
#   kt= to najważniejszy token autoryzacyjny.


def get_session(game: str, room: str) -> Dict[str, Any]:
    # ↑ Funkcja która "loguje bota" na kurnik.pl i zwraca parametry do WS.
    #   Przyjmuje: game → nazwa gry (np. 'kalambury')
    #              room → numer pokoju (np. '100')
    #   Zwraca:   słownik {'ge': ..., 'ap': ..., 'tf': ..., 'ver': ...}
    """
    Loguje bota na kurnik.pl i pobiera parametry potrzebne do WebSocket.

    KOLEJNOŚĆ DZIAŁAŃ:
        1. Ustawiamy "wstępne cookies" (mówimy serwerowi że jesteśmy gościem)
        2. Robimy POST na stronę gry (jak kliknięcie "Wejdź do gry" w przeglądarce)
        3. Serwer w odpowiedzi ustawia nowe cookies (w tym ważne kt=...)
        4. Z HTML strony wyciągamy 4 parametry: ge, ap, tf, ver
        5. Zwracamy je do main() które przekaże je do connect_ws()

    CO WYPISUJEMY NA STDOUT:
        'SESSION_OK'   → sesja udana (jest cookie kt=)
        'SESSION_WARN' → sesja niepewna (brak kt=, WS może nie zadziałać)

    JAK EDYTOWAĆ:
        Jeśli kurnik zmieni swoją stronę i przestaniesz dostawać ge/ap/tf/ver,
        otwórz kurnik.pl w przeglądarce, wejdź w DevTools (F12) → Sources
        i poszukaj zmiennych window.ge, window.ap, k2ver, tf w kodzie JS.
        Zaktualizuj wzorce regex w tej funkcji.
    """

    global _cookies
    # ↑ "global" mówi Pythonowi: "ta zmienna _cookies którą zaraz modyfikuję
    #   to ta GLOBALNA z góry pliku, nie twórz nowej lokalnej".
    #   Bez tego słowa Python stworzyłby nową lokalną zmienną _cookies
    #   wewnątrz tej funkcji i globalna zostałaby niezmieniona.

    # Krok 1: Ustaw wstępne cookies — symulują przeglądarkę wchodzącą jako gość
    _session.cookies.update({
        'kguest': '1',
        # ↑ Mówimy serwerowi że jesteśmy "gościem".
        #   Kurnik.pl pozwala grać bez konta — wystarczy być gościem.

        'kbeta':  'gs',
        # ↑ Wersja serwisu którą "używamy". 'gs' to standardowa wersja.

        'kroom':  room,
        # ↑ Numer pokoju do którego chcemy wejść (np. '100').
    })

    try:
        # Krok 2: Wyślij żądanie POST na stronę gry
        # POST to typ żądania HTTP — jak wypełnienie formularza i kliknięcie "Wyślij"
        response = _session.post(
            f'https://www.kurnik.pl/{game}/',
            # ↑ URL strony. f'...' to "f-string" — {game} zostanie zastąpione wartością.
            #   Wynik np.: 'https://www.kurnik.pl/kalambury/'

            data='gmid=gs',
            # ↑ Ciało żądania POST. To minimalne dane które serwer wymaga.
            #   JAK EDYTOWAĆ: Nie zmieniaj — to wymaganie serwera kurnika.

            headers={
                # Nagłówki HTTP — dodatkowe informacje o żądaniu
                'User-Agent':   UA,                             # nasza "wizytówka"
                'Content-Type': 'application/x-www-form-urlencoded',  # format danych POST
                'Origin':       'https://www.kurnik.pl',         # skąd pochodzi żądanie
                'Referer':      f'https://www.kurnik.pl/{game}/', # z jakiej strony "przyszliśmy"
            },
            timeout=10
            # ↑ Limit czasu w sekundach. Jeśli serwer nie odpowie przez 10s → błąd.
            #   JAK EDYTOWAĆ: Zwiększ jeśli masz wolne łącze (np. timeout=30).
        )
        body = response.text
        # ↑ response.text → treść HTML odpowiedzi jako string.
        #   To jest kod HTML strony kurnik.pl/kalambury/ — szukamy w nim parametrów.

        # Krok 3: Zbuduj string cookies z tego co serwer nam ustawił
        # Zaczynamy od znanych cookies które sami ustawiliśmy
        cookie_str = f'kguest=1; kbeta=gs; kroom={room}'
        for k, v in _session.cookies.items():
            # ↑ .items() → daje pary (klucz, wartość) ze słownika cookies.
            #   Przechodzimy przez wszystkie cookies które sesja zebrała.
            if k not in ('kguest', 'kbeta', 'kroom'):
                # Pomiń cookies które sami ustawiliśmy (żeby nie duplikować)
                cookie_str += f'; {k}={v}'
                # Dodaj każde nowe cookie: '; kt=abc123'
        _cookies = cookie_str
        # ↑ Zapisz gotowy string cookies globalnie.
        #   Będzie użyty w connect_ws() jako nagłówek 'Cookie'.
        #   Przykład: 'kguest=1; kbeta=gs; kroom=100; kt=xyzabc123'

        # Krok 4: Wyciągnij parametry z HTML strony za pomocą regex
        # "Regex" (wyrażenia regularne) to wzorce do wyszukiwania tekstu.
        # re.search(wzorzec, tekst) → szuka pierwszego dopasowania
        # Zwraca obiekt Match (jeśli znalazł) lub None (jeśli nie znalazł)

        ge = (re.search(r'window\.ge\s*=\s*(\d+)', body) or [None, ''])[1] or ''
        # ↑ Szuka w HTML wzorca: window.ge = LICZBA
        #   r'...' → "raw string" — backslash \ nie jest traktowany specjalnie
        #   window\.ge → dosłownie "window.ge"
        #               (. w regex = dowolny znak, więc \. = dosłowna kropka)
        #   \s*       → zero lub więcej białych znaków (spacji lub tabulatorów)
        #   =         → dosłownie znak równości
        #   (\d+)     → jedna lub więcej cyfr — TO jest to co chcemy pobrać
        #               nawiasy () tworzą "grupę przechwytującą"
        #
        #   "(re.search(...) or [None, ''])" → jeśli re.search zwróci None
        #   (nie znalazł wzorca), zamiast rzucać błąd, użyj listy [None, '']
        #   [1] → weź drugi element (indeks 1):
        #         - z obiektu Match: Match[1] = pierwsza grupa (nasze cyfry)
        #         - z listy [None, '']: drugi element = pusty string ''
        #   or '' → jeśli wynik to None, zwróć pusty string
        #
        #   ge to ID sesji/gracza który serwer przypisał nam.

        ap = (re.search(r'window\.ap\s*=\s*(\d+)', body) or [None, ''])[1] or ''
        # ↑ Analogicznie szuka: window.ap = LICZBA
        #   ap to dodatkowy parametr autoryzacji.

        tf_m = re.search(r'tf\s*:\s*(\d+)', body)
        # ↑ Szuka wzorca: tf : LICZBA
        #   Tym razem zapisujemy obiekt Match do tf_m żeby sprawdzić czy jest None
        tf = int(tf_m[1]) if tf_m else 1751
        # ↑ "wartość_A if warunek else wartość_B" to "wyrażenie warunkowe":
        #   Jeśli tf_m (Match) istnieje → int(tf_m[1]) = zamień cyfrę na int
        #   Jeśli tf_m jest None         → użyj 1751 jako wartości domyślnej
        #   tf to kod pierwszej ramki WebSocket używany przy autoryzacji.
        #   JAK EDYTOWAĆ: Jeśli 1751 przestanie działać, sprawdź aktualną wartość
        #   na stronie kurnik.pl w źródle strony i zaktualizuj fallback.

        ver_m = re.search(r'k2ver\s*=\s*(\d+)', body)
        ver = ver_m[1] if ver_m else '264'
        # ↑ Wersja klienta JavaScript. ver to string (nie int) bo tak jest używany.
        #   JAK EDYTOWAĆ: Jeśli '264' przestanie działać, sprawdź aktualną wartość.

        # Wypisz status sesji na stdout (launcher to odczyta i wyświetli)
        print('SESSION_OK' if 'kt=' in _cookies else 'SESSION_WARN', flush=True)
        # ↑ 'kt=' in _cookies → sprawdź czy w stringu cookies jest podciąg 'kt='
        #   kt= to token który serwer daje po poprawnym "zalogowaniu"
        #   Bez kt= WebSocket prawdopodobnie nie zadziała
        #   flush=True → wyślij natychmiast bez buforowania
        #   (buforowanie = Python zbiera dane i wysyła hurtem; flush wymusza
        #   natychmiastowe wysłanie, ważne bo launcher czeka na te dane)

        return {'ge': ge, 'ap': ap, 'tf': tf, 'ver': ver}
        # ↑ Zwróć słownik z czterema parametrami.
        #   main() przekaże je dalej do connect_ws().

    except Exception as e:
        # ↑ "Złap każdy błąd" — Exception to klasa bazowa wszystkich błędów.
        #   Jeśli cokolwiek pójdzie nie tak (brak internetu, timeout, itp.), wpadamy tu.
        print(f'[BŁĄD HTTP] {e}', flush=True)
        # ↑ {e} → tekst opisu błędu, np. "ConnectionError: Failed to connect"
        raise
        # ↑ "raise" bez argumentu → "rzuć błąd dalej" (propaguj go wyżej).
        #   Bez tego błąd zostałby "połknięty". Dzięki raise, main() go złapie
        #   i zakończy program z komunikatem błędu.


# ==============================================================================
# SEKCJA 5 — OBSŁUGA LISTY STOŁÓW
# ==============================================================================
# Kiedy bot dołącza do pokoju, serwer wysyła listę dostępnych stołów.
# parse_tables() odczytuje surowe dane → Python
# format_tables() zamienia Python → tekst dla launchera

def parse_tables(codes: List[int], strings: List[str]) -> List[Dict[str, Any]]:
    """
    Zamienia surowe dane ramki TABLES (kod 71) na czytelną listę stołów.

    FORMAT RAMKI OD SERWERA:
        Pole 'i': [71, block_size, str_per_table, id_stołu_0, id_stołu_1, ...]
        Pole 's': [params_0, gracze_0, params_1, gracze_1, ...]

        block_size    → krok w tablicy 'i' (zwykle 1)
        str_per_table → ile stringów opisuje jeden stół (zwykle 2)
        id_stołu_N    → numer ID stołu

    PRZYKŁAD:
        codes   = [71, 1, 2, 3, 5]   → stoły o ID 3 i 5
        strings = ['3+2', 'Jan', '', 'Anna']
        Wynik: [{'id':3, 'params':'3+2', 'players':'Jan'},
                {'id':5, 'params':'',    'players':'Anna'}]

    JAK EDYTOWAĆ:
        Jeśli chcesz dodać więcej pól (np. 'max_players'), musisz najpierw
        sprawdzić czy serwer je wysyła (obserwacja ruchu WS) i dodać tu odczyt.
    """
    tables = []
    # ↑ Lista na wyniki — na początku pusta.

    if len(codes) < 3:
        return tables
        # ↑ Zabezpieczenie: jeśli ramka zbyt krótka, zwróć pustą listę.

    block_size    = codes[1]   # krok w tablicy 'codes' (co ile elementów = jeden stół)
    str_per_table = codes[2]   # ile stringów opisuje jeden stół

    f  = 3   # indeks w 'codes' — startujemy od 3 (po [71, bs, spt])
    si = 0   # indeks w 'strings' — startujemy od 0

    while f < len(codes) and si < len(strings) - 1:
        # ↑ Pętla while — wykonuj dopóki:
        #   f < len(codes)         → nie wyszliśmy poza tablicę codes
        #   si < len(strings) - 1  → jest przynajmniej para stringów (params + gracze)

        tid = codes[f]   # ID aktualnego stołu
        if tid > 1:
            # ↑ Pomijamy ID 0 i 1 — to specjalne "stoły systemu", nie prawdziwe stoły.
            tables.append({
                'id':      tid,
                'params':  strings[si]     if si     < len(strings) else '',
                # ↑ Zabezpieczenie: jeśli string nie istnieje, zwróć ''
                'players': strings[si + 1] if si + 1 < len(strings) else '',
            })

        f  += block_size      # przesuń w 'codes' o block_size
        si += str_per_table   # przesuń w 'strings' o str_per_table

    return tables


def format_tables(tables: List[Dict[str, Any]]) -> str:
    """
    Zamienia listę stołów na tekst protokołu stdout który launcher rozumie.

    FORMAT WYJŚCIOWY (każda linia to osobna wiadomość dla launchera):
        TABLES_START 2      ← informuje że będą 2 stoły
        TABLE 3 | 3+2 | Jan ← stół ID=3, ustawienia=3+2, gracze=Jan
        TABLE 5 |     | Anna← stół ID=5, brak ustawień, gracze=Anna
        TABLES_END          ← koniec listy

    Launcher (w _handle_line()) rozpoznaje te prefiksy i reaguje odpowiednio.

    SEPARATOR ' | ':
        Używamy ' | ' bo jest mało prawdopodobny w nazwie gracza.
        Launcher parsuje: line.split(' | ', 2) → ['3', '3+2', 'Jan']

    JAK EDYTOWAĆ:
        Jeśli dodajesz pole w parse_tables(), dodaj kolumnę tu:
        TABLE id | params | players | nowe_pole
        Pamiętaj zaktualizować _handle_line() w launcher.py!
    """

    if not tables:
        return 'TABLES_EMPTY'
        # ↑ Brak stołów → specjalny token. Launcher wyświetli ostrzeżenie.

    lines = [f'TABLES_START {len(tables)}']
    # ↑ Pierwsza linia: ile stołów. len(tables) = długość listy.

    for t in tables:
        # ↑ Dla każdego stołu t (t to słownik {'id', 'params', 'players'})
        players = t['players'] or '(brak graczy)'
        # ↑ Pusty string → '(brak graczy)' (czytelniejsze w GUI)
        lines.append(f"TABLE {t['id']} | {t['params']} | {players}")

    lines.append('TABLES_END')

    return '\n'.join(lines)
    # ↑ '\n'.join(['a', 'b', 'c']) → 'a\nb\nc'
    #   Jeden print() wyśle to jako wieloliniowy tekst.


# ==============================================================================
# SEKCJA 6 — POŁĄCZENIE WEBSOCKET (GŁÓWNA LOGIKA BOTA)
# ==============================================================================
# To najważniejsza część programu. Tutaj bot:
# 1. Łączy się z serwerem przez WebSocket
# 2. Autoryzuje się (wysyła pierwszą ramkę z danymi sesji)
# 3. Nasłuchuje wiadomości od serwera
# 4. Odpowiada na komendy od launchera
# 5. Utrzymuje połączenie (heartbeat)
#
# WAŻNY KONCEPT: "async" i "await"
# Normalna funkcja: zatrzymuje cały program gdy czeka (np. na dane z sieci)
# Funkcja async:   "oddaje" kontrolę innemu zadaniu gdy czeka,
#                  a wraca gdy dane są gotowe.
# "await" przed wywołaniem = "poczekaj na wynik, ale nie blokuj innych zadań".
# Dzięki temu 3 zadania (heartbeat, receive, read_stdin) działają "jednocześnie"
# w jednym wątku — Python przełącza się między nimi gdy któreś czeka.

async def connect_ws(game: str, room: str, ge: str, ap: str,
                     tf: int, ver: str, initial_table: int) -> None:
    # ↑ "async def" → asynchroniczna funkcja. Musi być wywoływana z "await".
    #   -> None → ta funkcja nic nie zwraca
    """
    Główna pętla połączenia WebSocket.

    KOMENDY NA STDIN (od launchera):
        "5"          → /join 5 (sama liczba = dołącz do stołu)
        "/join 5"    → dołącz do stołu 5 (bez restartu bota!)
        "/table"     → wypisz numer aktualnego stołu
        "/quit"      → zakończ i wyjdź
        "cześć!"     → wyślij jako wiadomość czatu

    WYJŚCIE NA STDOUT (do launchera):
        CONNECTED, TABLES_START/TABLE/TABLES_END, JOINED N, MSG tekst, ERR ...

    JAK DODAĆ NOWĄ KOMENDĘ STDIN:
        W funkcji read_stdin() dodaj nowy elif:
            elif line.startswith('/moja_komenda '):
                dane = line[len('/moja_komenda '):]  # tekst po komendzie
                await ws.send(encode([KOD, ...], [dane]))
                print('MOJA_ODPOWIEDŹ ...', flush=True)
        Dodaj obsługę odpowiedzi w _handle_line() launchera.

    JAK DODAĆ OBSŁUGĘ NOWEGO KODU OD SERWERA:
        W funkcji receive() dodaj nowy blok:
            if code == NOWY_KOD:
                # przetworz msg['i'] i msg['s']
                print('NOWA_WIADOMOSC ...', flush=True)
                continue
        Usuń NOWY_KOD z IGNORE_CODES jeśli tam był.
        Dodaj stałą NOWY_KOD = X w SEKCJI 2.
    """

    current_table = initial_table
    # ↑ Zapamiętujemy aktualny stół. Modyfikowany przez nonlocal w zagnieżdżonych funkcjach.

    print(f'[WS] Łączę z pokojem #{room} ({game})...', flush=True)

    uri = 'wss://x.kurnik.pl:17003/ws/'
    # ↑ Adres WebSocket serwera kurnik.pl.
    #   'wss://' = WebSocket Secure (szyfrowane połączenie)
    #   JAK EDYTOWAĆ: Zaktualizuj jeśli kurnik zmieni adres.
    #   Aktualny adres: DevTools (F12) → Network → WS → nagłówek "Request URL"

    headers = {
        'User-Agent': UA,
        'Origin':     'https://www.kurnik.pl',
        'Cookie':     _cookies,
        # ↑ _cookies zawiera tokens z get_session(). Bez tego serwer odrzuci połączenie.
    }

    try:
        async with websockets.connect(uri, extra_headers=headers) as ws:
            # ↑ "async with" → otwórz połączenie WS asynchronicznie.
            #   "as ws" → połączenie dostępne jako zmienna 'ws'.
            #   Gdy blok się kończy (normalnie lub błędem), połączenie automatycznie zamknięte.

            print('CONNECTED', flush=True)
            # ↑ Launcher zobaczy 'CONNECTED' i zmieni ikonę bota na 🟢.

            # ── Wyślij ramkę autoryzacyjną ────────────────────────────────────
            # To PIERWSZA wiadomość po połączeniu. Serwer weryfikuje nasze dane.

            autoid = str(int(abs(hash(datetime.now())) % 10**18))
            # ↑ Generuj unikalny identyfikator sesji:
            #   datetime.now() → aktualna data i czas
            #   hash(...)      → zamień na liczbę (może być ujemna!)
            #   abs(...)       → wartość bezwzględna (zawsze >= 0)
            #   % 10**18       → ogranicz do max 18 cyfr (10^18 = miliard miliardów)
            #   int(...) → int, str(...) → string
            #   Wynik np.: '847392015847392015'

            await ws.send(encode([tf], [
                # ↑ Wyślij ramkę autoryzacyjną. 'tf' to kod pobrany ze strony HTML.
                f'+{autoid}|{ap}|{ge}',  # identyfikator sesji
                'pl',                     # język: 'pl' = polski (zmień na 'en' dla angielskiego)
                'b',                      # platforma: 'b' = browser
                '',                       # dodatkowe dane (puste, ale wymagane)
                UA,                       # User-Agent (musi zgadzać się z HTTP)
                f'/{int(datetime.now().timestamp() * 1000)}/1',  # timestamp w ms / nr połączenia
                'w',                      # typ: 'w' = web
                '1920x1080 1',            # rozdzielczość (serwer nie weryfikuje)
                f'ref:https://www.kurnik.pl/{game}/',  # referer
                f'ver:{ver}',             # wersja klienta JS
            ]))

            # ══════════════════════════════════════════════════════════════════
            # ZADANIE 1: HEARTBEAT (utrzymanie połączenia)
            # ══════════════════════════════════════════════════════════════════
            # Serwer rozłącza klientów którzy milczą przez ~60 sekund.
            # Co 30 sekund wysyłamy pusty ping żeby serwer wiedział że żyjemy.
            # To jak machanie ręką żeby ktoś nie myślał że zasnąłeś.
            #
            # JAK EDYTOWAĆ:
            # asyncio.sleep(30) → zmień 30 na mniejszą wartość (np. 15) jeśli
            # serwer rozłącza za szybko. Nie dawaj więcej niż ~50 sekund.

            async def heartbeat():
                # ↑ Zagnieżdżona funkcja async — ma dostęp do zmiennej 'ws' z zewnątrz.
                try:
                    while True:
                        # ↑ Nieskończona pętla — działa aż do anulowania taska.
                        await asyncio.sleep(30)
                        # ↑ Czekaj 30 sekund ASYNCHRONICZNIE.
                        #   Inne taski (receive, read_stdin) działają normalnie w tym czasie.
                        #   time.sleep(30) ZABLOKOWAŁOBY cały program!
                        await ws.send('{"i":[]}')
                        # ↑ Wyślij pusty ping. '{"i":[]}' = ramka bez kodu = ping.
                except asyncio.CancelledError:
                    pass
                    # ↑ Gdy task zostanie anulowany przez hb.cancel(),
                    #   asyncio rzuca CancelledError. Łapiemy go i kończymy cicho.

            # ══════════════════════════════════════════════════════════════════
            # ZADANIE 2: ODBIERANIE WIADOMOŚCI OD SERWERA
            # ══════════════════════════════════════════════════════════════════
            # Ta funkcja w kółko czeka na wiadomości od serwera i je przetwarza.
            # Każda wiadomość ma "kod" który mówi co to za wiadomość.
            #
            # JAK DODAĆ OBSŁUGĘ NOWEGO KODU:
            #   Dodaj blok "if code == TWÓJ_KOD:" po obsłudze TABLES.
            #   Pamiętaj o "continue" na końcu żeby nie przejść do obsługi ogólnej.

            async def receive():
                nonlocal current_table
                # ↑ "nonlocal" → zmienna current_table pochodzi z funkcji zewnętrznej
                #   (connect_ws), nie jest lokalna dla receive().
                #   Potrzebujemy go żeby wiedzieć do jakiego stołu auto-dołączyć.
                try:
                    while True:
                        data = await ws.recv()
                        # ↑ Czekaj asynchronicznie na wiadomość od serwera.
                        #   Gdy wiadomość przyjdzie, program kontynuuje.

                        # Ujednolicamy do stringa (WS może zwrócić str lub bytes)
                        raw = data if isinstance(data, str) else data.decode('utf-8')

                        for msg in decode(raw):
                            # ↑ decode() zwraca listę — może być kilka wiadomości naraz.
                            #   msg = {'i': [KOD, ...], 's': ['tekst', ...]}
                            code = msg['i'][0] if msg['i'] else None
                            code = msg['i'][0] if msg['i'] else None
                            # ↑ Pierwszy element listy 'i' = kod wiadomości.

                            # ── PING: odpowiedz natychmiast ────────────────────
                            if code == PING:
                                await ws.send('{"i":[2]}')  # PONG = kod 2
                                continue  # nie przetwarzaj dalej

                            # ── TABLES: lista stołów ──────────────────────────
                            if code == TABLES:
                                tables = parse_tables(msg['i'], msg['s'])
                                print(format_tables(tables), flush=True)
                                # ↑ Wyślij sformatowaną listę na stdout.
                                #   Launcher odczyta ją linijka po linijce w _handle_line().
                                if current_table:
                                    # ↑ Jeśli bot ma przypisany stół (nie 0),
                                    #   dołącz automatycznie po otrzymaniu listy.
                                    await ws.send(encode([JOIN_TAB, current_table]))
                                    print(f'JOINED {current_table}', flush=True)
                                continue

                            if code == SELFNAME:
                                nick = msg['s'][1] 
                                # ↑ Serwer informuje o naszym nicku (po zalogowaniu
                                print(f'NICK {msg["s"][1]}', flush=True)    
                               
                                continue

                            # ── Ignoruj nieinteresujące kody ──────────────────
                            if code in IGNORE_CODES:
                                continue

                            # ── Wiadomości tekstowe (chat, info o grze) ────────
                            if msg['s']:
                                # ↑ Jeśli wiadomość ma część 's' (nie pustą)
                                print (nick + ' ' + ' '.join(msg['s']), flush=True)
                                # ↑ Wyślij z prefixem 'MSG ' — launcher odezwie
                                #   prefix i wyświetli tylko treść.
                                # ' '.join(list) → łączy elementy listy spacjami
                            elif len(msg['i']) > 1:
                                # ↑ Ramka tylko z kodami (bez tekstów) — debug
                                codes_str = ','.join(map(str, msg['i']))
                                print(f'RAW [{code}] {codes_str}', flush=True)
                                # ↑ Przydatne do odkrywania co robią nieznane kody.

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f'[BŁĄD RECV] {e}', flush=True)

            # ══════════════════════════════════════════════════════════════════
            # ZADANIE 3: ODCZYT KOMEND OD LAUNCHERA (stdin)
            # ══════════════════════════════════════════════════════════════════
            # Launcher wysyła komendy przez "stdin" (standardowe wejście).
            # Każda linia tekstu = jedna komenda.
            #
            # PROBLEM: sys.stdin.readline() to "blokująca" operacja — program
            # stoi i czeka na linię. Inne taski by przestały działać.
            # ROZWIĄZANIE: run_in_executor uruchamia readline() w osobnym wątku,
            # a pętla async może działać normalnie.
            #
            # JAK DODAĆ NOWĄ KOMENDĘ (np. /whisper nick wiadomość):
            #   Dodaj przed blokiem "elif current_table:":
            #       elif line.startswith('/whisper '):
            #           parts = line[9:].split(' ', 1)  # ['nick', 'wiadomość']
            #           if len(parts) == 2:
            #               await ws.send(encode([KOD_WHISPER, ...], parts))
            #               print(f'WHISPER_SENT {parts[0]}', flush=True)

            async def read_stdin():
                nonlocal current_table
                # ↑ Modyfikujemy current_table przy /join — potrzebujemy nonlocal.
                loop = asyncio.get_event_loop()
                # ↑ Pobierz pętlę zdarzeń asyncio — potrzebna do run_in_executor.
                try:
                    while True:
                        line = await loop.run_in_executor(None, sys.stdin.readline)
                        # ↑ Uruchom blokujące readline() w osobnym wątku.
                        #   "await" → czekaj na wynik nie blokując pętli async.
                        #   Gdy launcher wyśle linię, wracamy tu z jej treścią.

                        if not line:
                            break
                            # ↑ '' (pusty string) z readline() = EOF.
                            #   EOF = launcher zamknął pipe stdin.
                            #   Czas się zakończyć.

                        line = line.strip()  # usuń \n i białe znaki z końca
                        if not line:
                            continue  # pusta linia → pomiń

                        # Konwersja: sama liczba (np. "5") → "/join 5"
                        # Skrót dla launchera który może wysłać samo ID stołu.
                        if re.match(r'^\d+$', line):
                            # ↑ r'^\d+$' = cały string to cyfry (od ^ do $)
                            line = f'/join {line}'

                        # ── Komenda: dołącz do stołu ──────────────────────────
                        if line.startswith('/join '):
                            try:
                                tid = int(line[6:].strip())
                                # ↑ line[6:] → wszystko po '/join ' (6 znaków)
                                #   int(...) → zamień na liczbę (błąd jeśli nie cyfry)
                                current_table = tid
                                await ws.send(encode([JOIN_TAB, tid]))
                                # ↑ Wyślij żądanie JOIN do serwera
                                print(f'JOINED {tid}', flush=True)
                                # ↑ Poinformuj launcher
                            except ValueError:
                                print('ERR nieprawidłowy numer stołu', flush=True)
                        # ── Komenda: zapytaj o aktualny stół ──────────────────
                        elif line == '/table':
                            print(f'CURRENT_TABLE {current_table}', flush=True)

                        # ── Komenda: zakończ ──────────────────────────────────
                        elif line in ('/quit', '/exit'):
                            await ws.close()  # zamknij WS
                            return            # zakończ funkcję

                        # ── Wyślij tekst jako wiadomość czatu ─────────────────
                        elif current_table:
                            # ↑ Tylko jeśli jesteśmy przy stole (current_table != 0)
                            await ws.send(encode(nick + ' ' +[CHAT, current_table], [line]))
                            # ↑ encode([81, id], ["tekst"]) → ramka czatu

                        # ── Brak stołu ────────────────────────────────────────
                        else:
                            print('ERR brak stołu, użyj /join ID', flush=True)

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f'[BŁĄD STDIN] {e}', flush=True)

            # ── Uruchom wszystkie trzy taski ──────────────────────────────────
            hb   = asyncio.create_task(heartbeat())
            recv = asyncio.create_task(receive())
            inp  = asyncio.create_task(read_stdin())
            # ↑ asyncio.create_task() → zaplanuj wykonanie funkcji async jako "task".
            #   Taski działają "równocześnie" — Python przełącza się między nimi
            #   przy każdym "await". To nie są prawdziwe wątki — to "korutyny".

            try:
                await asyncio.gather(recv, inp)
                # ↑ gather() → czekaj aż OBA taski (recv i inp) się zakończą.
                #   Heartbeat (hb) pominięty — działa w tle, anulujemy go w finally.
                #   gather() wraca gdy jeden z tasków się zakończy z błędem
                #   lub oba zakończą się normalnie.

            finally:
                # ↑ "finally" wykonuje się ZAWSZE — niezależnie czy był błąd.
                #   Gwarancja sprzątania.
                hb.cancel()    # zatrzymaj heartbeat
                recv.cancel()  # zatrzymaj odbieranie (może być w trakcie await ws.recv())
                inp.cancel()   # zatrzymaj czytanie stdin
                try:
                    await ws.close()  # zamknij połączenie WS
                except Exception:
                    pass  # może być już zamknięte — ignoruj błąd

    except Exception as e:
        print(f'[BŁĄD WS] {e}', flush=True)
        raise  # przekaż błąd do main()


# ==============================================================================
# SEKCJA 7 — PARSOWANIE ARGUMENTÓW I URUCHAMIANIE
# ==============================================================================

def parse_args() -> argparse.Namespace:
    """
    Czyta argumenty podane przy uruchamianiu programu z terminala.

    PRZYKŁADY:
        python kurnik-ws.py                          → domyślne wartości
        python kurnik-ws.py --room 200               → inny pokój
        python kurnik-ws.py --room 200 --table 5     → pokój + stół
        python kurnik-ws.py --game szachy --room 300 → inna gra

    JAK DODAĆ NOWY ARGUMENT (np. --nick Jan):
        p.add_argument('--nick', default='Bot', help='Nazwa gracza')
        Potem w main() odczytaj: nick = args.nick
        I przekaż do connect_ws() jako kolejny parametr.
    """
    p = argparse.ArgumentParser(description='Kurnik.pl bot CLI')
    # ↑ Tworzy parser. description pojawia się przy python kurnik-ws.py --help

    p.add_argument('--game', default=DEFAULT_GAME,
                   help=f'Gra (default: {DEFAULT_GAME})')
    # ↑ Argument --game. Jeśli nie podany, używa DEFAULT_GAME.

    p.add_argument('--room', default=DEFAULT_ROOM,
                   help=f'Pokój (default: {DEFAULT_ROOM})')

    p.add_argument('--table', type=int, default=0,
                   help='Stół do automatycznego dołączenia (0 = obserwator)')
    p.add_argument('--nick', type=str, default=SELFNAME, help='nazwa gracza')
    # ↑ type=int → automatycznie zamień podaną wartość na liczbę całkowitą.


    return p.parse_args()
    # ↑ Parsuj argumenty z sys.argv (lista argumentów z terminala).
    #   Zwraca obiekt z atrybutami: args.game, args.room, args.table


async def main() -> None:
    """
    Główna funkcja: inicjalizuje i uruchamia bota.

    KOLEJNOŚĆ:
        1. Wczytaj argumenty (--game, --room, --table)
        2. Wypisz BOT_START (launcher zobaczy w _handle_line)
        3. get_session() → zaloguj przez HTTP
        4. connect_ws() → połącz WebSocket i obsługuj do końca

    JAK DODAĆ AUTO-RESTART po rozłączeniu:
        Zamień wywołanie connect_ws() w pętlę:
            import time
            while True:
                try:
                    await connect_ws(...)
                except Exception:
                    print('RECONNECTING', flush=True)
                    await asyncio.sleep(5)  # czekaj 5s przed ponowną próbą
    """
    args  = parse_args()
    game  = args.game
    room  = args.room
    table = args.table
    nick - args.nick

    print(f'BOT_START game={game} room={room} table={table}', flush=True)
    # ↑ Launcher zobaczy 'BOT_START ...' i wyświetli 🚀 w logu.

    try:
        sess = get_session(game, room)
        # ↑ Zaloguj przez HTTP → zwraca {'ge', 'ap', 'tf', 'ver'}
        #   Przy okazji wypełnia globalną zmienną _cookies.

        await connect_ws(
            game, room,
            sess['ge'], sess['ap'], sess['tf'], sess['ver'],
            table
        )
        # ↑ Ta funkcja blokuje (czeka) aż połączenie się zerwie lub bot dostanie /quit.

    except Exception as err:
        print(f'[BŁĄD] {err}', flush=True)
        sys.exit(1)  # kod 1 = błąd (launcher to widzi)


# ==============================================================================
# PUNKT WEJŚCIA
# ==============================================================================
# Ten blok wykonuje się tylko gdy uruchamiasz plik BEZPOŚREDNIO:
#   python kurnik-ws.py
#
# NIE wykonuje się gdy plik jest importowany:
#   import kurnik_ws  (blok pominięty)

if __name__ == '__main__':
    try:
        asyncio.run(main())
        # ↑ Uruchom pętlę zdarzeń asyncio z funkcją main() jako punktem startowym.
        #   Blokuje program aż main() się zakończy.

    except KeyboardInterrupt:
        # ↑ Ctrl+C → wyjdź czysto bez długiego traceback
        print('\n[PRZERWANO]', flush=True)
        sys.exit(0)  # 0 = zakończono normalnie
