#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  launcher.py — graficzny menedżer botów Kurnik.pl                          ║
# ║                                                                              ║
# ║  CO ROBI TEN PLIK:                                                           ║
# ║  Uruchamia okno graficzne (GUI) w którym możesz:                            ║
# ║    • odpalić wiele botów naraz (każdy bot = osobny proces kurnik-ws.py)     ║
# ║    • zobaczyć co każdy bot dostaje/wysyła                                   ║
# ║    • przełączać boty między stołami bez ich restartowania                   ║
# ║    • wysłać wiadomość do jednego lub wszystkich botów                       ║
# ║                                                                              ║
# ║  JAK TO DZIAŁA W SKRÓCIE:                                                   ║
# ║  1. Klikasz "Uruchom" → launcher odpala N kopii kurnik-ws.py               ║
# ║  2. Każda kopia (bot) to osobny "process" — jak otwarcie N okienek          ║
# ║     terminala z tym samym programem, tyle że niewidocznych                  ║
# ║  3. Launcher "rozmawia" z każdym botem przez dwa kanały tekstowe:           ║
# ║     STDIN  = launcher pisze komendy → bot je czyta (np. "/join 5")         ║
# ║     STDOUT = bot pisze odpowiedzi  → launcher je czyta (np. "CONNECTED")   ║
# ║  4. GUI odświeża się co 150ms — sprawdza czy boty coś nowego napisały      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


# ══════════════════════════════════════════════════════════════════════════════
# BLOK IMPORTÓW — ładowanie bibliotek których używamy
#
# Biblioteki to gotowe zestawy funkcji napisanych przez innych programistów.
# Zamiast pisać od zera np. kod do rysowania okienek, importujemy tkinter.
# ══════════════════════════════════════════════════════════════════════════════
from pickle import LIST
import tkinter as tk
# tkinter = standardowa biblioteka Pythona do tworzenia okien graficznych (GUI).
# Działa na Windows, Mac i Linux bez instalowania czegokolwiek.
# "as tk" = skrót — zamiast pisać "tkinter.Label" piszemy "tk.Label"

from tkinter import ttk, scrolledtext, messagebox, filedialog
# Importujemy konkretne moduły z tkinter:
#   ttk          = "themed tkinter" — ładniejsze widgety niż klasyczne
#                  np. ttk.Button wygląda nowocześniej niż tk.Button
#   scrolledtext = gotowy widget tekstowy z paskiem przewijania
#                  (zamiast ręcznie składać Text + Scrollbar)
#   messagebox   = okienka dialogowe: showerror(), showinfo(), askyesno()
#   filedialog   = systemowe okno wyboru pliku (do eksportu logów)

import subprocess
# subprocess = uruchamianie zewnętrznych programów z Pythona.
# Używamy go żeby odpalić kurnik-ws.py jako osobny process.
# Pozwala też czytać co ten process wypisuje (stdout) i pisać do niego (stdin).
# Wyobraź sobie że subprocess.Popen() to jak "otwarcie nowego okna terminala
# i uruchomienie w nim programu, ale po cichu, w tle".

import threading
# threading = uruchamianie kodu "równolegle" w tym samym programie.
# Problem: odczyt stdout bota (readline()) BLOKUJE program — czeka aż coś przyjdzie.
# Rozwiązanie: uruchamiamy odczyt w osobnym "wątku" (thread) — to jak drugi
# tor kolejowy obok głównego. Wątek czeka sobie na dane, a GUI działa normalnie.
# WAŻNE: Tkinter NIE jest "thread-safe" — nie można modyfikować GUI z wątku!
#        Dlatego wątek tylko wrzuca dane do Queue, a GUI czyta z Queue w _tick().

import queue
# queue = kolejka danych bezpieczna dla wielu wątków (thread-safe).
# Działa jak kolejka w sklepie: wątek odczytu "wkłada" wiadomości (put()),
# a główny wątek GUI "wyjmuje" je (get_nowait()) co 150ms w _tick().
# Bez queue wątki mogłyby nadpisywać dane jednocześnie → błędy.

import sys
# sys = dostęp do interpretera Pythona i systemu operacyjnego.
# Używamy:
#   sys.executable = ścieżka do uruchomionego Pythona (np. "C:\Python312\python.exe")
#                    dzięki temu bot uruchamia się tym samym Pythonem co launcher
#   sys.platform   = "win32" na Windows, "linux" na Linux, "darwin" na Mac
#   sys.stdout/stderr = strumienie wyjścia (do nadpisania kodowania na Windows)

import io
# io = obsługa strumieni wejścia/wyjścia.
# Używamy io.TextIOWrapper żeby "opakować" stdout/stderr w warstwę UTF-8.
# Potrzebne tylko na Windows gdzie domyślne kodowanie to cp1250 (psuje polskie znaki).

from datetime import datetime
# datetime = data i czas.
# Używamy datetime.now() żeby dodać znacznik czasu [HH:MM:SS] do każdego wpisu w logu.
# Przykład: datetime.now().strftime('%H:%M:%S') → "14:35:22"

from pathlib import Path
# Path = nowoczesny sposób pracy ze ścieżkami plików.
# Działa identycznie na Windows (\) i Linux (/) bez ręcznego zamieniania slashy.
# Przykład: Path(__file__).parent / 'kurnik-ws.py'
#           = katalog gdzie leży ten plik + "kurnik-ws.py"
#           Na Windows: "C:\boty\kurnik-ws.py"
#           Na Linux:   "/home/user/boty/kurnik-ws.py"

from typing import Dict, Any, List, Optional
# typing = podpowiedzi typów — mówią Pythonowi (i nam) jakiego typu są zmienne.
# Nie są wymagane do działania programu — są jak dokumentacja wbudowana w kod.
#   Dict[int, Bot]    = słownik gdzie klucze to liczby całkowite, wartości to obiekty Bot
#   List[str]         = lista stringów (tekstów)
#   Optional[int]     = liczba całkowita LUB None (brak wartości)
#   Any               = dowolny typ


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 1 — NAPRAWIENIE KODOWANIA NA WINDOWS
#
# PROBLEM: Windows domyślnie używa kodowania "cp1250" dla polskich znaków.
# Gdy launcher wypisuje "ą ę ó ż" przez print(), Windows może to zepsuć.
# ROZWIĄZANIE: Zamieniamy stdout i stderr na wersję UTF-8.
#
# sys.platform == 'win32' → sprawdza czy działamy na Windows.
# Ten blok NIE wykonuje się na Linux/Mac (są już domyślnie UTF-8).
#
# KIEDY EDYTOWAĆ: Nigdy — chyba że chcesz zmienić zachowanie błędnych znaków.
#   errors='replace' = zamiast błędu wstaw '?' gdy znak jest nieznany
#   errors='ignore'  = po prostu pomiń nieznany znak
#   errors='strict'  = rzuć wyjątek (domyślne, niepożądane tutaj)
# ══════════════════════════════════════════════════════════════════════════════

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ══════════════════════════════════════════════════════════════════════════════
# STAŁE GLOBALNE
#
# Stałe to wartości które się nie zmieniają podczas działania programu.
# Piszemy je WIELKIMI_LITERAMI — to konwencja Pythona (nie wymóg języka).
# Definiujemy je tutaj, na górze pliku, żeby łatwo je znaleźć i zmienić.
#
# KIEDY EDYTOWAĆ:
#   DEFAULT_GAME → jeśli chcesz żeby launcher domyślnie łączył z inną grą
#   DEFAULT_ROOM → jeśli chcesz inny domyślny pokój niż 100
#
# WAŻNE: Te wartości MUSZĄ zgadzać się z DEFAULT_* w kurnik-ws.py!
#        Jeśli zmienisz tu, zmień też tam.
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_GAME = 'kalambury'
# Nazwa gry używana w URL: kurnik.pl/kalambury/
# Możliwe wartości: 'kalambury', 'szachy', 'warcaby', 'literaki' itd.
# Ta wartość jest przekazywana do kurnik-ws.py przez argument --game

DEFAULT_ROOM = '100'
# Numer pokoju jako tekst (string), nie liczba — bo trafia do argumentu --room
# Domyślnie pokój 100 (główny pokój kalambury na kurnik.pl)


# ══════════════════════════════════════════════════════════════════════════════
# ██████████████████████████████████████████████████████████████████████████████
# KLASA Bot
# ██████████████████████████████████████████████████████████████████████████████
#
# CO TO JEST KLASA?
# Klasa to "przepis" na tworzenie obiektów. Obiekt to paczka danych + funkcji
# które na tych danych działają. Myśl o klasie Bot jak o formularzu:
# każdy nowy bot wypełnia ten formularz swoimi danymi (pokój, stół, numer).
#
# KAŻDY obiekt Bot reprezentuje JEDNEGO uruchomionego bota:
#   - przechowuje dane bota (numer, pokój, stół, status)
#   - zarządza jego procesem (subprocess kurnik-ws.py)
#   - ma wątek który czyta co bot wypisuje na stdout
#   - ma kolejkę do przekazywania tych danych do GUI
#
# TWORZENIE BOTA: bot = Bot(idx=1, room='100', table=5)
# URUCHOMIENIE:   bot.start(Path('kurnik-ws.py'))
# ZATRZYMANIE:    bot.stop()
# WYSŁANIE:       bot.send('/join 3')
# ██████████████████████████████████████████████████████████████████████████████
# ══════════════════════════════════════════════════════════════════════════════

class Bot:

    # ──────────────────────────────────────────────────────────────────────────
    # __init__ = KONSTRUKTOR — wywołuje się automatycznie przy Bot(idx, room, table)
    # To "inicjalizacja" — ustawiamy wszystkie zmienne bota na wartości startowe.
    # "self" = referencja do tego konkretnego obiektu (jak "ja" w zdaniu)
    #
    # Parametry które dostajemy przy tworzeniu:
    #   idx   = unikalny numer bota (1, 2, 3...) — nigdy się nie zmienia
    #   room  = numer pokoju jako string (np. '100')
    #   table = numer stołu do auto-dołączenia (0 = tylko obserwuj)
    # ──────────────────────────────────────────────────────────────────────────
    def __init__(self, idx: int, room: str, table: int, nick: str):

        self.idx = idx
        # Numer porządkowy bota. Używany wszędzie: w etykiecie listy ("Bot #01"),
        # w logach ("Bot #3: Połączono"), jako klucz w słowniku self.bots w App.
        # Nigdy się nie zmienia po utworzeniu — to "imię" bota.

        self.nick:  List[str] = [msg['i'][31], msg['1']]

        self.room = room
        # Numer pokoju kurnik.pl jako string (np. '100').
        # Przekazywany do kurnik-ws.py przez argument --room.
        # Wyświetlany w etykiecie: "R:100"

        self.table = table
        # AKTUALNY numer stołu przy którym siedzi bot.
        # Zaczyna od wartości startowej (0 = obserwator).
        # ZMIENIA SIĘ gdy bot dostanie potwierdzenie "JOINED X" — patrz _handle_line().
        # Wyświetlany w etykiecie: "T:5" lub "T:—" gdy 0.

        self.proc: Optional[subprocess.Popen] = None
        # Obiekt procesu — wypełniany przez start(), początkowo None (brak procesu).
        # subprocess.Popen to "uchwyt" do uruchomionego procesu kurnik-ws.py.
        # Przez self.proc możemy:
        #   - pisać do procesu: self.proc.stdin.write(...)
        #   - czytać z procesu: self.proc.stdout.readline()
        #   - zabić proces:     self.proc.terminate() lub self.proc.kill()
        # Optional[...] = może być None (przed start()) lub Popen (po start())

        self.q: queue.Queue = queue.Queue()
        # Kolejka wiadomości od bota do GUI.
        # Wątek _reader() wkłada tu wiadomości: self.q.put("tekst")
        # Główna pętla _tick() w App wyjmuje je: self.q.get_nowait()
        # Kolejka jest THREAD-SAFE — wiele wątków może z niej korzystać bez błędów.
        # Każdy bot ma SWOJĄ kolejkę — nie mieszają się ze sobą.

        self.running = False
        # Czy subprocess bota aktualnie działa?
        # False = bot nie jest uruchomiony (przed start() lub po stop()/śmierci)
        # True  = bot działa (po start(), przed stop())
        # Używane przez _reader() żeby wiedzieć kiedy skończyć czytanie.
        # Zmieniane na True w start(), na False w stop() i w _reader() finally.

        self.connected = False
        # Czy bot nawiązał połączenie WebSocket z kurnik.pl?
        # False = bot startuje, łączy się przez HTTP, jeszcze nie połączony
        # True  = bot otrzymał potwierdzenie WS i wysłał "CONNECTED" na stdout
        # Wpływa na kolor ikony w liście: 🟡 (running=True, connected=False)
        #                                 🟢 (running=True, connected=True)

        self.lines: List[str] = []
        # Historia WSZYSTKICH wiadomości od tego bota — lista stringów.
        # Każda nowa wiadomość jest DOPISYWANA na koniec przez _tick().
        # Używana gdy klikasz na bota w liście — _refresh_bot_log() ładuje
        # całą historię do widgetu tekstowego, żebyś zobaczył co było wcześniej.
        # UWAGA: Lista rośnie w nieskończoność — jeśli boty działają długo,
        #        możesz chcieć ograniczyć jej rozmiar np. do ostatnich 1000 linii:
        #        if len(self.lines) > 1000: self.lines = self.lines[-1000:]

        self.tables: List[Dict[str, Any]] = []
        # Ostatnia lista stołów otrzymana z serwera kurnik.pl przez tego bota.
        # Wypełniana fragmentami przez _handle_line() gdy przychodzą linie:
        #   "TABLES_START" → czyścimy: self.tables = []
        #   "TABLE 5 | 3+2 | Gracz1" → dopisujemy słownik do listy
        #   "TABLES_END" → lista gotowa, sygnalizujemy GUI przez kolejkę
        # Każdy element listy to słownik: {'id': 5, 'params': '3+2', 'players': 'Gracz1'}
        # Wyświetlana w GUI w widgecie table_list (zielona lista stołów).


    # ──────────────────────────────────────────────────────────────────────────
    # METODA start() — uruchamia subprocess kurnik-ws.py
    #
    # CO ROBI:
    #   1. Buduje listę argumentów komendy (jak wpisanie w terminalu)
    #   2. Uruchamia kurnik-ws.py jako osobny process (subprocess.Popen)
    #   3. Tworzy wątek który czyta stdout tego procesu (_reader)
    #
    # PARAMETRY:
    #   script = ścieżka do pliku kurnik-ws.py (obiekt Path)
    #
    # ZWRACA:
    #   True  = udało się uruchomić
    #   False = błąd (np. nie znaleziono pliku, brak uprawnień)
    #
    # KIEDY EDYTOWAĆ:
    #   → chcesz dodać nowy argument do kurnik-ws.py? Dopisz do listy cmd[]
    #   → chcesz zmienić domyślną grę? Zmień DEFAULT_GAME na górze pliku
    # ──────────────────────────────────────────────────────────────────────────
    def start(self, script: Path) -> bool:

        # Budujemy komendę jak gdybyś wpisał ją w terminalu.
        # sys.executable = pełna ścieżka do Pythona który teraz działa
        #   np. "C:\Python312\python.exe" lub "/usr/bin/python3"
        # Dzięki temu bot zawsze uruchamia się tym samym Pythonem co launcher —
        # nie musisz martwić się że masz kilka wersji Pythona zainstalowanych.
        cmd = [
            sys.executable,        # np. "python3" lub "C:\Python312\python.exe"
            str(script),           # np. "/home/user/boty/kurnik-ws.py"
            '--game', DEFAULT_GAME, # → kurnik-ws.py dostaje: --game kalambury
            '--room', self.room,    # → kurnik-ws.py dostaje: --room 100
        ]

        # Dodaj argument --table TYLKO jeśli stół != 0
        # (0 oznacza "obserwator" — nie dołączaj do żadnego stołu automatycznie)
        if self.table:
            cmd += ['--table', str(self.table)]
            # str(self.table) bo argumenty muszą być stringami, nie liczbami

        # Efekt końcowy cmd może wyglądać np. tak:
        # ["python3", "kurnik-ws.py", "--game", "kalambury", "--room", "100", "--table", "5"]
        # co odpowiada wpisaniu w terminalu:
        # python3 kurnik-ws.py --game kalambury --room 100 --table 5

        try:
            self.proc = subprocess.Popen(
                cmd,                        # lista argumentów komendy
                stdout=subprocess.PIPE,
                # PIPE = "rura" — zamiast pokazywać stdout bota w oknie terminala,
                # przekieruj go do wewnętrznego bufora który możemy czytać przez
                # self.proc.stdout.readline(). Bez tego nie widzielibyśmy co bot pisze.

                stderr=subprocess.STDOUT,
                # Przekieruj też stderr (błędy) do tego samego PIPE co stdout.
                # Dzięki temu błędy Pythona (np. "ImportError: No module named websockets")
                # też trafiają do naszego logu, a nie gdzieś w próżnię.
                # Alternatywa: stderr=subprocess.PIPE — osobna rura dla błędów.

                stdin=subprocess.PIPE,
                # PIPE dla wejścia — pozwala nam PISAĆ do bota przez self.proc.stdin.
                # Bez tego nie moglibyśmy wysyłać komend (/join, /quit, tekst chatu).

                text=True,
                # Tryb tekstowy — dane są automatycznie kodowane/dekodowane jako stringi.
                # Bez tego dostalibyśmy bytes (np. b"CONNECTED\n") zamiast str ("CONNECTED\n").

                encoding='utf-8',
                # Kodowanie UTF-8 dla polskich znaków.
                # Musi zgadzać się z kodowaniem w kurnik-ws.py.

                errors='replace',
                # Co zrobić gdy napotkamy bajt którego nie można zdekodować jako UTF-8?
                # 'replace' = wstaw znak '?' — bezpieczne, nie rzuca wyjątku.

                bufsize=1,
                # Rozmiar bufora: 1 = "line-buffered" = każda linia jest dostępna
                # natychmiast po jej wypisaniu przez bota (bez czekania na zapełnienie bufora).
                # Bez tego musiałbyś czekać aż bot wypiszę np. 4096 bajtów zanim cokolwiek zobaczysz.
            )

            self.running = True
            # Bot działa — zapamiętaj to żeby _reader() wiedział że ma czytać.

            threading.Thread(target=self._reader, daemon=True).start()
            # Utwórz i uruchom wątek który będzie czytał stdout bota.
            # target=self._reader = funkcja która ma się wykonać w wątku
            # daemon=True = "wątek demon" — zakończy się automatycznie gdy główny
            #               program (GUI) się zamknie. Bez daemon=True program
            #               mógłby wisieć po zamknięciu okna, czekając na wątek.

            return True  # sukces

        except Exception as e:
            # Coś poszło nie tak (np. brak pliku kurnik-ws.py, brak Pythona w PATH).
            # Zamiast crashować, wrzucamy błąd do kolejki — GUI go wyświetli w logu.
            self.q.put(f'[BŁĄD URUCHOMIENIA] {e}')
            return False  # porażka


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _reader() — wątek który czyta stdout bota w tle
    #
    # WAŻNE: Ta metoda działa w osobnym WĄTKU (uruchomionym przez start()).
    #        NIE MODYFIKUJE GUI bezpośrednio — tylko wrzuca do kolejki self.q.
    #        To kluczowy punkt: wątek → kolejka → _tick() → GUI.
    #
    # CO ROBI:
    #   1. Czyta stdout bota linia po linii (blokująca pętla for)
    #   2. Każdą linię przekazuje do _handle_line() do interpretacji
    #   3. Gdy stdout się zamknie (bot umarł) → informuje GUI przez kolejkę
    #
    # KIEDY EDYTOWAĆ:
    #   → Zazwyczaj nigdy — logika interpretacji jest w _handle_line()
    #   → Jeśli chcesz logować surowy stdout do pliku, dodaj tu zapis do pliku
    # ──────────────────────────────────────────────────────────────────────────
    def _reader(self):
        try:
            for raw in self.proc.stdout:
                # "for raw in self.proc.stdout" = czytaj linie jedna po jednej.
                # BLOKUJE się i czeka gdy brak nowych danych — dlatego potrzebujemy wątku.
                # Pętla kończy się automatycznie gdy bot zamknie swój stdout
                # (czyli gdy process kurnik-ws.py zakończy działanie).

                if not self.running:
                    break
                # Sprawdź czy ktoś zewnętrznie nie kazał nam się zatrzymać.
                # stop() ustawia self.running = False — wtedy wychodzimy z pętli.
                # Bez tego sprawdzenia wątek mógłby czytać "zombie process".

                line = raw.rstrip('\n')
                # Usuń znak nowej linii z końca.
                # readline() i iteracja po stdout zawsze zwracają linię Z "\n" na końcu.
                # Przykład: "CONNECTED\n" → "CONNECTED"
                # rstrip('\n') = usuń '\n' tylko z PRAWEJ strony (nie z lewej).

                if not line:
                    continue
                # Pomiń puste linie (np. gdy bot wypisał samą "\n").

                self._handle_line(line)
                # Przekaż linię do interpretacji. _handle_line() zdecyduje
                # co z nią zrobić (zmienić stan bota, wrzucić do kolejki, etc.).

        except Exception:
            pass
            # Błąd odczytu (np. process już nie istnieje, pipe zamknięty).
            # Łapiemy wszystko i ignorujemy — i tak idziemy do finally.

        finally:
            # Ten blok wykonuje się ZAWSZE — niezależnie czy wyszliśmy przez break,
            # przez wyczerpanie pętli, czy przez wyjątek.
            # "finally" gwarantuje sprzątanie nawet przy błędach.

            self.running = False
            # Bot już nie działa — zaktualizuj status.
            # _tick() zauważy zmianę i zaktualizuje ikonę na 🔴.

            self.connected = False
            # Bot nie jest też połączony — serwer WS na pewno to odnotował.

            self.q.put('__DEAD__')
            # Wyślij specjalny sygnał do GUI że bot umarł.
            # _tick() go złapie, usunie bota z self.bots i przebuduje listę.
            # Podwójne podkreślenia __ to konwencja dla "sygnałów wewnętrznych"
            # które nie są zwykłymi wiadomościami do wyświetlenia.


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _handle_line() — interpretuje jedną linię ze stdout bota
    #
    # To "tłumacz" między surowym tekstem bota a stanem GUI.
    # Każda linia którą bot wypisuje na stdout trafia tutaj.
    #
    # PROTOKÓŁ KOMUNIKACJI (co bot pisze → co my robimy):
    #   "CONNECTED"          → self.connected = True, ikona zmienia się na 🟢
    #   "SESSION_OK"         → wiadomość do logu: "🔑 Sesja OK"
    #   "SESSION_WARN"       → wiadomość do logu: "⚠️ Sesja bez kt="
    #   "TABLES_START"       → czyść self.tables, zaraz przyjdą nowe stoły
    #   "TABLE 5 | 3+2 | X"  → dopisz stół do self.tables
    #   "TABLES_END"         → lista stołów kompletna, odśwież GUI
    #   "JOINED 5"           → self.table = 5 (bot zmienił stół)
    #   "TABLES_EMPTY"       → brak stołów w pokoju
    #   "CURRENT_TABLE 5"    → odpowiedź na /table — pokaż w logu
    #   "MSG cześć"          → wiadomość z czatu — pokaż "cześć" w logu
    #   "BOT_START ..."      → info o parametrach startu — pokaż w logu
    #   cokolwiek innego     → pokaż wprost w logu (błędy, debug, etc.)
    #
    # KIEDY EDYTOWAĆ:
    #   → chcesz reagować na nowy typ wiadomości z bota?
    #     Dodaj nowy blok "if line.startswith('NOWY_TYP'):" na końcu tej metody
    #   → chcesz zmienić co jest wyświetlane? Zmień self.q.put('nowy tekst')
    # ──────────────────────────────────────────────────────────────────────────
    def _handle_line(self, line: str):

        # ── "CONNECTED" — bot nawiązał połączenie WebSocket ───────────────────
        # kurnik-ws.py wypisuje dokładnie "CONNECTED" (bez niczego więcej)
        # gdy websockets.connect() zakończy handshake z serwerem.
        if line == 'CONNECTED':
            self.connected = True
            # Teraz _tick() + _refresh_bot_labels() zmienią ikonę na 🟢.
            self.q.put('✅ Połączono')
            # Wrzuć czytelną wiadomość do logu GUI.
            return
            # return = wyjdź z funkcji natychmiast — ta linia jest obsłużona.

        # ── "SESSION_OK" — sesja HTTP zadziałała poprawnie ───────────────────
        # kurnik-ws.py wypisuje to gdy w cookies jest "kt=" (token sesji).
        # Oznacza że serwer nas rozpoznał i możemy połączyć WebSocket.
        if line.startswith('SESSION_OK'):
            # startswith() zamiast == bo nie wiemy czy bot nie dopisze czegoś po
            self.q.put('🔑 Sesja OK')
            return

        # ── "SESSION_WARN" — sesja bez tokenu kt= ────────────────────────────
        # Sesja istnieje, ale może nie działać poprawnie (brak tokenu).
        # Bot spróbuje połączyć WebSocket, ale może dostać odmowę.
        if line.startswith('SESSION_WARN'):
            self.q.put('⚠️  Sesja bez kt=')
            return

        # ── "TABLES_START" — zaczyna się blok listy stołów ───────────────────
        # kurnik-ws.py wysyła najpierw tę linię, potem po jednej linii "TABLE ...",
        # a na końcu "TABLES_END". Musimy czyścić starą listę tutaj, a nie
        # przy TABLES_END, żeby nie było momentu gdy lista jest pusta.
        if line.startswith('TABLES_START'):
            self.tables = []
            # Wyczyść poprzednią listę stołów — zaraz przyjdą nowe.
            # Nie wrzucamy nic do kolejki — GUI nie musi na to reagować.
            return

        # ── "TABLE 5 | 3+2 | Gracz1, Gracz2" — jeden stół ───────────────────
        # Format: "TABLE <id> | <params> | <players>"
        # Przykłady:
        #   "TABLE 3 | 5+3 | Kowalski, Nowak"
        #   "TABLE 7 | bez limitu | "  (brak graczy)
        if line.startswith('TABLE '):
            parts = line[6:].split(' | ', 2)
            # line[6:] = odetnij pierwsze 6 znaków ("TABLE "), zostaw resztę
            # Przykład: "TABLE 5 | 3+2 | Gracz1"[6:] → "5 | 3+2 | Gracz1"
            # .split(' | ', 2) = podziel na maks. 3 części po separatorze ' | '
            # Wynik: ['5', '3+2', 'Gracz1']
            # Maks. 2 podziały żeby graczy z " | " w nazwie nie rozciąć.

            if parts:
                # parts nie jest pusta (split zawsze zwraca co najmniej 1 element)
                try:
                    self.tables.append({
                        'id':      int(parts[0]),
                        # parts[0] = "5" → int("5") = 5
                        # MOŻE rzucić ValueError jeśli parts[0] nie jest liczbą
                        # (dlatego jesteśmy w bloku try)

                        'params':  parts[1] if len(parts) > 1 else '',
                        # parts[1] = "3+2" lub puste jeśli nie ma parametrów
                        # if len(parts) > 1 = zabezpieczenie gdyby split dał tylko 1 element

                        'players': parts[2] if len(parts) > 2 else '',
                        # parts[2] = "Gracz1, Gracz2" lub puste jeśli brak graczy
                    })
                except ValueError:
                    pass
                    # ID stołu nie było liczbą — zignoruj ten stół.
                    # Lepiej pominąć jeden stół niż crashować.
            return

        # ── "TABLES_END" — lista stołów kompletna ────────────────────────────
        # self.tables jest teraz wypełniona wszystkimi stołami.
        # Wysyłamy specjalny sygnał do GUI żeby odświeżyło listę stołów.
        if line == 'TABLES_END':
            self.q.put('__TABLES__')
            # __TABLES__ = sygnał wewnętrzny (nie wyświetlany jako tekst).
            # _tick() w App obsłuży go specjalnie: wywoła _refresh_table_list().
            return

        # ── "JOINED 5" — bot dołączył do stołu numer 5 ───────────────────────
        # Wysyłane przez kurnik-ws.py po tym jak serwer potwierdził JOIN_TAB.
        # To jest "twarde" potwierdzenie — wcześniej join_table() ustawiło
        # self.table optymistycznie, teraz to oficjalne potwierdzenie.
        if line.startswith('JOINED '):
            try:
                self.table = int(line[7:])
                # line[7:] = odetnij "JOINED " (7 znaków), zostaw numer
                # Przykład: "JOINED 5"[7:] → "5" → int("5") → 5
            except ValueError:
                pass
                # Nie udało się sparsować numeru — zostaw stary self.table.
            self.q.put(f'➡️  Stół {self.table}')
            # Wrzuć wiadomość do logu z aktualnym numerem stołu.
            return

        # ── "TABLES_EMPTY" — brak stołów w pokoju ────────────────────────────
        # kurnik.pl odesłał listę stołów, ale była pusta.
        if line == 'TABLES_EMPTY':
            self.q.put('⚠️  Brak stołów')
            return

        # ── "CURRENT_TABLE 5" — odpowiedź na komendę /table ──────────────────
        # Gdy launcher wysyła "/table" do bota, bot odpowiada tym komunikatem.
        # Aktualnie nie wysyłamy /table z GUI, ale bot może to obsłużyć ręcznie.
        if line.startswith('CURRENT_TABLE '):
            self.q.put(f'📍 Stół: {line[14:]}')
            # line[14:] = odetnij "CURRENT_TABLE " (14 znaków), zostaw numer
            return

        # ── "MSG cześć" — wiadomość z czatu lub stanu gry ────────────────────
        # kurnik-ws.py dodaje prefix "MSG " do wiadomości z serwera kurnik.
        # Tutaj go odcinamy żeby w logu było czyste "cześć" a nie "MSG cześć".
        if line.startswith('MSG '):
            self.q.put(line[4:])
            # line[4:] = odetnij pierwsze 4 znaki ("MSG "), zostaw resztę
            # Przykład: "MSG cześć wszystkim"[4:] → "cześć wszystkim"
            return

        # ── "BOT_START game=kalambury room=100 table=5" ───────────────────────
        # Pierwsza linia którą bot wypisuje po uruchomieniu.
        # Zawiera potwierdzenie parametrów z jakimi go uruchomiono.
        if line.startswith('BOT_START '):
            self.q.put(f'🚀 {line[10:]}')
            # line[10:] = odetnij "BOT_START " (10 znaków)
            # Przykład: "🚀 game=kalambury room=100 table=5"
            return

        # ── Wszystko inne — pokaż wprost ─────────────────────────────────────
        # Linia nie pasuje do żadnego ze znanych wzorców.
        # Może to być: błąd Pythona, linia debugowa RAW [...], [BŁĄD WS], itp.
        # Wyświetlamy ją bez modyfikacji żeby nic nie zgubiło się po cichu.
        self.q.put(line)


    # ──────────────────────────────────────────────────────────────────────────
    # METODA send() — wysyła tekst do stdin bota
    #
    # To jak wpisanie tekstu w terminalu w którym działa bot.
    # Bot czyta stdin przez sys.stdin.readline() w kurnik-ws.py.
    #
    # PARAMETRY:
    #   text = tekst do wysłania (bez "\n" — dodajemy go sami)
    #
    # ZWRACA:
    #   True  = wysłano pomyślnie
    #   False = błąd (bot martwy, pipe zamknięty)
    #
    # PRZYKŁADY UŻYCIA:
    #   bot.send('/join 5')      → bot dołączy do stołu 5
    #   bot.send('cześć!')       → bot wyśle "cześć!" na czacie
    #   bot.send('/quit')        → bot się rozłączy
    #
    # KIEDY EDYTOWAĆ:
    #   → Prawie nigdy. To bardzo prosta funkcja.
    #   → Jeśli chcesz logować wysyłane komendy, dodaj print() przed write().
    # ──────────────────────────────────────────────────────────────────────────
    def send(self, text: str) -> bool:
        try:
            self.proc.stdin.write(text + '\n')
            # Dpisz "\n" (nowa linia) na końcu — bot czyta przez readline()
            # które zwraca tekst DO znaku "\n". Bez "\n" readline() czekałoby w nieskończoność.

            self.proc.stdin.flush()
            # Wymuś natychmiastowe wysłanie danych.
            # Bez flush() Python mógłby trzymać dane w buforze i wysłać je
            # dopiero gdy bufor się zapełni — powodując opóźnienia lub "ciszę".
            # flush() = "wyślij teraz, nie czekaj na więcej danych"

            return True

        except Exception:
            return False
            # Najczęstszy powód błędu: self.proc jest None (bot nie wystartował)
            # lub stdin pipe jest zamknięty (bot umarł).
            # Nie rzucamy wyjątku — zwracamy False żeby wywołujący mógł obsłużyć błąd.


    # ──────────────────────────────────────────────────────────────────────────
    # METODA join_table() — przełącza bota na inny stół BEZ restartu
    #
    # To "wygodna nakładka" na send() — zamiast ręcznie pisać send('/join 5'),
    # wywołujesz join_table(5) co jest bardziej czytelne.
    #
    # PARAMETRY:
    #   tid = numer stołu docelowego (np. 5)
    #
    # ZWRACA:
    #   True  = komenda wysłana (bot ją przetworzy)
    #   False = nie udało się wysłać (bot martwy)
    #
    # JAK TO DZIAŁA:
    #   1. Wysyłamy "/join 5" do stdin bota
    #   2. Bot w kurnik-ws.py odbiera to w read_stdin()
    #   3. Bot wysyła do serwera WS ramkę JOIN_TAB
    #   4. Serwer potwierdza → bot wypisuje "JOINED 5" na stdout
    #   5. _handle_line() odbiera "JOINED 5" → self.table = 5
    #
    # OPTYMISTYCZNA AKTUALIZACJA:
    #   Ustawiamy self.table = tid ZANIM dostaniemy potwierdzenie.
    #   Czyli zakładamy że join się uda. Jeśli się nie uda, bot nie wyśle
    #   "JOINED" a self.table pozostanie z błędną wartością do następnego join.
    #   To kompromis: szybka aktualizacja GUI vs ryzyko chwilowo błędnego stanu.
    # ──────────────────────────────────────────────────────────────────────────
    def join_table(self, tid: int) -> bool:
        if self.send(f'/join {tid}'):
            # f'/join {tid}' = f-string = tekst z wstawioną wartością zmiennej
            # np. gdy tid=5: '/join 5'
            self.table = tid
            # Optymistyczna aktualizacja — zaktualizuj TERAZ zanim przyjdzie potwierdzenie.
            # GUI od razu pokaże nowy numer stołu w etykiecie i logu.
            return True
        return False


    # ──────────────────────────────────────────────────────────────────────────
    # METODA stop() — zatrzymuje subprocess w sposób łagodny
    #
    # STRATEGIA "graceful shutdown" (łagodne wyłączanie):
    #   Próbujemy najpierw grzecznie poprosić bota o zakończenie (/quit),
    #   potem używamy sygnału systemowego (terminate = SIGTERM),
    #   a na końcu siłowego zabicia (kill = SIGKILL) jeśli nic innego nie działa.
    #
    # KIEDY EDYTOWAĆ:
    #   → Chcesz zmienić czas oczekiwania? Zmień timeout=2 na inną wartość (sekundy).
    #   → Chcesz wykonać coś przed zabiciem bota (np. zapis stanu)?
    #     Dodaj kod przed self.proc.terminate()
    # ──────────────────────────────────────────────────────────────────────────
    def stop(self):
        self.running = False
        # Ustaw od razu — wątek _reader() zauważy to i wyjdzie z pętli.
        # Bez tego _reader() mógłby próbować czytać z już martwego procesu.

        if self.proc:
            # Upewnij się że mamy uchwyt do procesu (proc != None).

            try:
                self.proc.stdin.write('/quit\n')
                self.proc.stdin.flush()
                # KROK 1: Wyślij /quit do bota.
                # Bot w kurnik-ws.py obsłuży to w read_stdin(): zamknie WS, wyjdzie z pętli.
                # To "prośba" — bot może ją obsłużyć i zakończyć się elegancko.
            except Exception:
                pass
                # stdin może być już zamknięty (bot zdechł samoczynnie). Ignoruj.

            try:
                self.proc.terminate()
                # KROK 2: Wyślij sygnał SIGTERM (zakończ się proszę).
                # Na Windows: wysyła TerminateProcess() API call.
                # Na Linux/Mac: wysyła sygnał SIGTERM (można go przechwycić).
                # Daje procesowi szansę na sprzątanie przed wyjściem.

                self.proc.wait(timeout=2)
                # KROK 3: Poczekaj maks. 2 sekundy aż process naprawdę się skończy.
                # Jeśli skończy się wcześniej — wait() wróci od razu.
                # Jeśli nie skończy się w 2 sekundy → rzuca subprocess.TimeoutExpired
                # → wpadamy do except → kill()

            except Exception:
                try:
                    self.proc.kill()
                    # KROK 4 (ostateczność): SIGKILL — natychmiastowe zabicie.
                    # Process nie może tego przechwycić ani zignorować.
                    # Używamy tylko gdy terminate() nie zadziałało.
                    # Na Windows: TerminateProcess() z kodem wyjścia 1.
                    # Na Linux: kill -9
                except Exception:
                    pass
                    # Nawet kill() może się nie udać (np. process już nie istnieje).
                    # W tym przypadku po prostu odpuszczamy.


    # ──────────────────────────────────────────────────────────────────────────
    # WŁAŚCIWOŚĆ label — generuje etykietę wyświetlaną na liście botów
    #
    # @property = "właściwość" — dostęp jak do zmiennej, ale oblicza wartość.
    # Zamiast bot.label() (wywołanie funkcji) piszemy bot.label (jak zmienna).
    # Wartość jest obliczana NA ŻĄDANIE przy każdym odczycie — zawsze aktualna.
    #
    # FORMAT ETYKIETY:
    #   "🟢 Bot #01  R:100  T:5"   (połączony, stół 5)
    #   "🟡 Bot #02  R:100  T:—"   (startuje, brak stołu)
    #   "🔴 Bot #03  R:100  T:2"   (martwy, ostatni znany stół 2)
    #
    # IKONY STATUSU:
    #   🟢 running=True  + connected=True  = połączony z serwerem
    #   🟡 running=True  + connected=False = uruchomiony, ale jeszcze się łączy
    #   🔴 running=False                   = process nie działa
    #
    # KIEDY EDYTOWAĆ:
    #   → Chcesz dodać więcej info w etykiecie? Rozszerz f-string na końcu.
    #   → Chcesz inne ikony? Zmień '🟢', '🟡', '🔴' na inne emoji lub tekst.
    # ──────────────────────────────────────────────────────────────────────────
    @property
    def label(self) -> str:
        if self.running and self.connected:
            icon = '🟢'   # Działa i połączony
        elif not self.running:
            icon = '🔴'   # Nie działa (martwy lub jeszcze nie uruchomiony)
        else:
            icon = '🟡'   # Działa ale nie połączony (startuje, loguje się)

        return f'{icon} Bot #{self.idx:02d} N:{self.nick}  R:{self.room}  T:{self.table or "—"}'
        # f-string = tekst z wbudowanymi wyrażeniami w {}
        # {self.idx:02d}   = numer z wiodącym zerem: 1→"01", 10→"10"
        #                    :02d = format liczby całkowitej, min. 2 cyfry, uzupełniaj zerami
        # {self.table or "—"} = jeśli self.table == 0 (falsy), wyświetl "—"
        #                        jeśli self.table == 5 (truthy), wyświetl "5"


# ══════════════════════════════════════════════════════════════════════════════
# ██████████████████████████████████████████████████████████████████████████████
# KLASA App
# ██████████████████████████████████████████████████████████████████████████████
#
# CO TO JEST:
# App = główna aplikacja GUI. Jeden obiekt App = jedno okno programu.
# Zarządza wszystkimi botami i całym interfejsem użytkownika.
#
# STRUKTURA OKNA (trzy kolumny):
#
#  ┌──────────────────────────────────────────────────────────────────────────┐
#  │  ⚙️ Konfiguracja: [Botów: 2] [Pokój: 100] [Stół: 0] [▶ Uruchom] ...    │
#  ├────────────────┬──────────────────────────┬──────────────────────────────┤
#  │ 🤖 Boty        │ 💬 Wybrany bot           │ 📢 Broadcast & Log           │
#  │                │                           │                              │
#  │ 🟢 Bot #01 R:  │ 📋 Stoły w pokoju        │ Wyślij do wszystkich:        │
#  │ 🟡 Bot #02 R:  │  ID: 3  3+2  👥 Gracz1   │ [pole tekstowe] [📢 Broad.] │
#  │ 🔴 Bot #03 R:  │  ID: 7       👥 (brak)   │                              │
#  │                │ [➡ Dołącz]               │ Przełącz wszystkie na stół:  │
#  │                │                           │ [pole] [➡ Przełącz]         │
#  │                │ ID stołu: [  ] [➡ Dołącz]│                              │
#  │                │                           │ Zbiorczy log:                │
#  │                │ 📨 Wyślij do wybranego:   │ [14:35] Bot #1: ✅ Połączono │
#  │                │ [pole tekstowe] [Wyślij]  │ [14:35] Bot #2: 🔑 Sesja OK │
#  │                │                           │ ...                          │
#  │                │ Log:                      │                              │
#  │                │ [14:35] ✅ Połączono       │                              │
#  │                │ ...                       │                              │
#  └────────────────┴──────────────────────────┴──────────────────────────────┘
#
# DANE PRZECHOWYWANE W App:
#   self.bots     = słownik {1: Bot, 2: Bot, 3: Bot, ...} — wszystkie boty
#   self.sel      = numer bota aktualnie wybranego kliknięciem
#   self._next_id = licznik dla nowych botów (zawsze rośnie, nie powtarza się)
#   self.script   = ścieżka do kurnik-ws.py
#
# KIEDY EDYTOWAĆ:
#   → Chcesz zmienić rozmiar okna? Zmień '1500x850' w __init__
#   → Chcesz zmienić kolory? Zmień kolory hex w _build_ui() / style.configure()
#   → Chcesz dodać nowy przycisk? Dodaj ttk.Button w _build_ui() + nową metodę
# ██████████████████████████████████████████████████████████████████████████████
# ══════════════════════════════════════════════════════════════════════════════

class App:

    # ──────────────────────────────────────────────────────────────────────────
    # __init__ — inicjalizacja aplikacji
    # Wywoływana raz przy tworzeniu: app = App(root)
    #
    # PARAMETRY:
    #   root = główne okno Tkinter (tk.Tk()) — "kontener" dla całego GUI
    # ──────────────────────────────────────────────────────────────────────────
    def __init__(self, root: tk.Tk):
        self.root = root
        # Zapisz referencję do głównego okna — używamy go wszędzie (root.after, root.configure).

        self.root.title('🤖 Kurnik Bot Launcher')
        # Tekst wyświetlany na pasku tytułu okna (w górze okna).
        # ZMIANA: Możesz wpisać cokolwiek chcesz.

        self.root.geometry('1500x850')
        # Rozmiar okna w pikselach: szerokość x wysokość.
        # 1500x850 = szerokie okno dla trzech kolumn.
        # ZMIANA: np. '1200x700' dla mniejszego ekranu.
        # Możesz też dodać '+100+100' żeby ustawić pozycję: '1500x850+100+100'

        self.root.configure(bg='#1e1e2e')
        # Kolor tła głównego okna (hex).
        # #1e1e2e = bardzo ciemny fioletowo-szary (paleta Catppuccin Mocha).
        # ZMIANA: '#ffffff' = białe, '#2b2b2b' = ciemnoszare, '#f0f0f0' = jasnoszare

        self.script = Path(__file__).parent / 'kurnik-ws.py'
        # Ścieżka do skryptu bota.
        # Path(__file__) = ścieżka do TEGO pliku (launcher.py)
        # .parent = katalog nadrzędny (katalog gdzie leży launcher.py)
        # / 'kurnik-ws.py' = dołącz nazwę pliku (operator / dla Path)
        # Zakłada że kurnik-ws.py jest w TYM SAMYM katalogu co launcher.py.
        # ZMIANA: Jeśli bot jest gdzie indziej: Path('/inna/ścieżka/kurnik-ws.py')

        self.bots: Dict[int, Bot] = {}
        # Słownik wszystkich aktywnych botów.
        # Klucz (int) = numer bota (idx), Wartość = obiekt Bot
        # Przykład po uruchomieniu 3 botów: {1: Bot, 2: Bot, 3: Bot}
        # Po śmierci bota #2: {1: Bot, 3: Bot} (luka w numerach jest OK)
        # Dostęp: self.bots[2] = Bot #2
        self.nick: LIST [Str. nick] = []

        self.sel: Optional[int] = None
        # Który bot jest aktualnie WYBRANY (kliknięty) na liście?
        # None = nikt nie jest wybrany (na starcie lub po stop_all)
        # Liczba = idx wybranego bota (np. 2 = Bot #02 jest wybrany)
        # Używane do decydowania do którego bota wysłać wiadomość w _send_one()

        self._next_id = 1
        # Licznik dla nowych botów. Rośnie monotonicznie — nigdy się nie cofa.
        # Dlaczego nie cofamy do 1 po usunięciu bota? Żeby unikać zamieszania:
        # jeśli Bot #1 umarł i tworzymy nowego, nowy dostaje #2 (nie #1 ponownie).
        # _stop_all() resetuje go do 1 bo wtedy wszystkie boty są usunięte.

        self._build_ui()
        # Zbuduj wszystkie widgety (przyciski, listy, pola tekstowe).
        # Ta metoda tworzy i umieszcza wszystkie elementy interfejsu.
        # Musi być wywołana PRZED _tick() bo _tick() odwołuje się do widgetów.

        self._tick()
        # Uruchom pętlę aktualizacji GUI.
        # _tick() wywołuje siebie samo co 150ms przez root.after().
        # Od teraz GUI będzie automatycznie odświeżać się w tle.


    # ══════════════════════════════════════════════════════════════════════════
    # METODA _build_ui() — buduje cały interfejs graficzny
    #
    # CO ROBI:
    #   Tworzy i rozmieszcza WSZYSTKIE widgety (elementy GUI):
    #   przyciski, listy, pola tekstowe, etykiety, panele.
    #
    # STRUKTURA:
    #   1. Ustawia kolory (ttk.Style)
    #   2. Tworzy górny panel konfiguracji (LabelFrame cfg)
    #   3. Tworzy trzy kolumny w PanedWindow (left, mid, right)
    #
    # JAK DODAĆ NOWY WIDGET:
    #   1. Znajdź odpowiedni panel (cfg/left/mid/right)
    #   2. Utwórz widget np: btn = ttk.Button(panel, text='Kliknij', command=self.moja_metoda)
    #   3. Umieść go: btn.pack(...) lub btn.grid(row=X, column=Y)
    #   4. Jeśli potrzebujesz do niego dostępu później: self.moj_button = btn
    #
    # UKŁADY (pack vs grid):
    #   pack()  = automatyczne układanie w pionie/poziomie. Proste.
    #   grid()  = siatka wierszy i kolumn. Precyzyjne. Używamy w panelu cfg.
    #   Nie mieszaj pack i grid w TYM SAMYM kontenerze — błąd Tkinter!
    # ══════════════════════════════════════════════════════════════════════════
    def _build_ui(self):

        # ── KOLORY I STYLE ────────────────────────────────────────────────────
        # ttk.Style = obiekt który pozwala zmieniać wygląd widgetów ttk.*
        # Działa jak CSS w HTML — zamiast ustawiać kolor każdego przycisku osobno,
        # ustawiamy raz dla wszystkich przycisków 'TButton'.
        #
        # DOSTĘPNE NAZWY STYLI:
        #   'TLabelframe'       = ramka z tytułem (ttk.LabelFrame)
        #   'TLabelframe.Label' = sam tytuł ramki
        #   'TLabel'            = etykieta (ttk.Label)
        #   'TButton'           = przycisk (ttk.Button)
        #   'TCheckbutton'      = checkbox (ttk.Checkbutton)
        #   'TEntry'            = pole tekstowe (ttk.Entry)
        #   'TSpinbox'          = pole z przyciskami +/- (ttk.Spinbox)
        #
        # KOLORY (format hex #RRGGBB):
        #   #1e1e2e = bardzo ciemny (tło okna)
        #   #181825 = jeszcze ciemniejszy (tło list i logów)
        #   #313244 = ciemnoszary (tło przycisków)
        #   #45475a = ciemnoszary jaśniejszy (hover przycisku, zaznaczenie)
        #   #cdd6f4 = jasnoniebieski (główny tekst)
        #   #89b4fa = jasnoniebieski akcentowy (tytuły ramek)
        #   #a6e3a1 = jasnozielony (tekst stołów)
        #   #6c7086 = szary (pomocniczy, nieaktywny)
        #
        # ZMIANA MOTYWU KOLORYSTYCZNEGO:
        #   Zamień wszystkie wartości hex na swoje. Możesz użyć dowolnego generatora
        #   palet kolorów (np. coolors.co). Pamiętaj o kontraście tekst/tło!

        style = ttk.Style()
        style.theme_use('clam')
        # 'clam' = motyw bazowy który POZWALA na zmianę kolorów.
        # Inne motywy ('default', 'vista', 'winnative') ignorują część ustawień configure().
        # Zawsze używaj 'clam' jeśli chcesz pełną kontrolę nad kolorami.

        style.configure('TLabelframe',
                         background='#1e1e2e',   # tło ramki
                         foreground='#cdd6f4')   # kolor obramowania
        style.configure('TLabelframe.Label',
                         background='#1e1e2e',   # tło za tytułem ramki
                         foreground='#89b4fa',   # kolor tytułu (niebieski)
                         font=('Segoe UI', 10, 'bold'))  # czcionka tytułu
        style.configure('TLabel',
                         background='#1e1e2e',   # tło etykiety
                         foreground='#cdd6f4')   # kolor tekstu
        style.configure('TButton',
                         background='#313244',   # tło przycisku
                         foreground='#cdd6f4',   # kolor tekstu przycisku
                         padding=4)              # wewnętrzny margines (piksele)
        style.configure('TCheckbutton',
                         background='#1e1e2e',
                         foreground='#cdd6f4')
        style.configure('TEntry',
                         fieldbackground='#313244',  # tło pola tekstowego
                         foreground='#cdd6f4',       # kolor wpisywanego tekstu
                         insertcolor='#cdd6f4')      # kolor kursora tekstowego
        style.configure('TSpinbox',
                         fieldbackground='#313244',
                         foreground='#cdd6f4')
        style.map('TButton',
                  background=[('active', '#45475a')])
        # style.map = styl DYNAMICZNY — zmienia się w zależności od stanu.
        # ('active', '#45475a') = gdy mysz jest nad przyciskiem → ciemniejszy kolor
        # Możesz dodać więcej: ('pressed', '#color') dla wciśniętego przycisku.


        # ══════════════════════════════════════════════════════════════════════
        # PANEL KONFIGURACJI — górny pasek z ustawieniami
        #
        # LabelFrame = ramka z tytułem. Wizualnie grupuje powiązane widgety.
        # Używamy grid() do precyzyjnego układu w siatce kolumn.
        #
        # SIATKA KOLUMN (row=0):
        # [0]Botów: [1]SpinBox [2]Pokój: [3]Entry [4]Stół(start): [5]Entry
        # [6]Checkbox [7]▶Uruchom [8]⏹Stop [9]🗑Wyczyść [10]💾Eksport
        # ══════════════════════════════════════════════════════════════════════

        cfg = ttk.LabelFrame(self.root, text='⚙️  Konfiguracja', padding=8)
        cfg.pack(fill=tk.X, padx=10, pady=(10, 0))
        # fill=tk.X  = rozciągnij poziomo do pełnej szerokości okna
        # padx=10    = margines lewy i prawy 10 pikseli
        # pady=(10,0)= margines górny 10px, dolny 0px

        ttk.Label(cfg, text='Botów:').grid(row=0, column=0, padx=4)
        # ttk.Label = napis (nie można go edytować). Wyświetla 'Botów:'
        # .grid(row=0, column=0) = umieść w wierszu 0, kolumnie 0 siatki

        self.v_count = tk.IntVar(value=2)
        # tk.IntVar = zmienna przechowująca LICZBĘ CAŁKOWITĄ, powiązana z widgetem.
        # Gdy użytkownik zmieni wartość w Spinbox, self.v_count automatycznie się aktualizuje.
        # Odczyt: self.v_count.get() → zwraca int (np. 2)
        # Ustawienie: self.v_count.set(5) → zmienia wartość w Spinbox na 5
        # value=2 = wartość domyślna

        ttk.Spinbox(cfg, from_=1, to=50, textvariable=self.v_count, width=5).grid(
            row=0, column=1, padx=4)
        # ttk.Spinbox = pole z przyciskami + i - do zmiany liczby
        # from_=1  = minimalna wartość (nie można zejść poniżej 1)
        # to=50    = maksymalna wartość (nie można przekroczyć 50)
        # textvariable=self.v_count = powiąż z IntVar (dwukierunkowe)
        # width=5  = szerokość pola w znakach (nie pikselach)
        # ZMIANA: Chcesz max 100 botów? Zmień to=100

        ttk.Label(cfg, text='Pokój:').grid(row=0, column=2, padx=4)

        self.v_room = tk.StringVar(value=DEFAULT_ROOM)
        # tk.StringVar = zmienna przechowująca TEXT, powiązana z widgetem.
        # value=DEFAULT_ROOM = domyślnie '100' (ze stałej na górze pliku)
        # Odczyt: self.v_room.get() → '100' (jako string, nie int!)

        ttk.Entry(cfg, textvariable=self.v_room, width=6).grid(row=0, column=3, padx=4)
        # ttk.Entry = jednoliniowe pole tekstowe do wpisywania
        # width=6 = szerokość 6 znaków (wystarczy dla "100", "200" itp.)

        ttk.Label(cfg, text='Stół (start):').grid(row=0, column=4, padx=4)

        self.v_table = tk.StringVar(value='0')
        # '0' = domyślnie obserwator (nie dołączaj do żadnego stołu automatycznie)
        # Jeśli użytkownik wpisze np. '5', wszystkie nowe boty automatycznie dołączą do stołu 5.

        ttk.Entry(cfg, textvariable=self.v_table, width=6).grid(row=0, column=5, padx=4)

        self.v_shared = tk.BooleanVar(value=True)
        # tk.BooleanVar = zmienna True/False powiązana z Checkbutton
        # value=True = domyślnie checkbox jest ZAZNACZONY (wspólny stół)
        # Gdy True:  wszystkie boty → ten sam stół (wpisany w polu "Stół (start)")
        # Gdy False: bot #1 → stół 1, bot #2 → stół 2, bot #3 → stół 3, itp.

        ttk.Checkbutton(cfg, text='Wspólny stół', variable=self.v_shared).grid(
            row=0, column=6, padx=8)
        # ttk.Checkbutton = pole do zaznaczenia (☑ lub ☐)
        # Kliknięcie automatycznie zmienia self.v_shared między True i False.

        ttk.Button(cfg, text='▶  Uruchom', command=self._run_bots).grid(row=0, column=7, padx=4)
        # ttk.Button = klikalny przycisk
        # command=self._run_bots = gdy kliknięty, wywołaj metodę _run_bots()
        # Strzałka ▶ to zwykły symbol Unicode — możesz go zmienić na cokolwiek.

        ttk.Button(cfg, text='⏹  Stop all', command=self._stop_all).grid(row=0, column=8, padx=4)
        # Zatrzymuje WSZYSTKIE boty naraz.

        ttk.Button(cfg, text='🗑  Wyczyść', command=self._clear_logs).grid(row=0, column=9, padx=4)
        # Czyści oba pola logów (nie zatrzymuje botów, tylko czyści wyświetlane logi).

        ttk.Button(cfg, text='💾 Eksport', command=self._export).grid(row=0, column=10, padx=4)
        # Eksportuje zbiorczy log do pliku .txt


        # ══════════════════════════════════════════════════════════════════════
        # GŁÓWNY UKŁAD — trzy kolumny obok siebie (PanedWindow)
        #
        # PanedWindow = kontener który dzieli przestrzeń na "pane" (panele).
        # orient=tk.HORIZONTAL = panele są obok siebie (poziomo).
        # Użytkownik może PRZECIĄGAĆ linie podziału żeby resize'ować panele.
        #
        # Każdy panel dodajemy przez paned.add(panel, weight=X).
        # weight=1 = "normalny" rozmiar
        # weight=3 = "trzy razy szerszy" niż weight=1
        # Suma wag: 1 + 3 + 3 = 7 → lewa kolumna = 1/7 szerokości, środek = 3/7, prawa = 3/7
        # ══════════════════════════════════════════════════════════════════════

        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        # fill=tk.BOTH = rozciągnij poziomo I pionowo
        # expand=True  = zajmij całą dostępną przestrzeń (rośnie gdy okno jest powiększane)


        # ══════════════════════════════════════════════════════════════════════
        # PANEL LEWY — lista botów
        # Zawiera tylko jeden widget: Listbox ze scrollbarem.
        # Kliknięcie na element listy wywołuje _on_select_bot().
        # ══════════════════════════════════════════════════════════════════════

        left = ttk.LabelFrame(paned, text='🤖 Boty', padding=5)
        paned.add(left, weight=1)
        # weight=1 = wąski panel — lista botów nie potrzebuje dużo miejsca

        sf = tk.Frame(left, bg='#1e1e2e')
        sf.pack(fill=tk.BOTH, expand=True)
        # Wewnętrzny Frame żeby Listbox i Scrollbar były obok siebie.
        # Dlaczego Frame? Listbox i Scrollbar muszą być w tym samym kontenerze
        # żeby scrollbar "wiedział" do którego Listbox należy.

        sb = ttk.Scrollbar(sf)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        # Scrollbar po PRAWEJ stronie, wypełniający całą wysokość (fill=tk.Y)

        self.bot_list = tk.Listbox(
            sf,
            yscrollcommand=sb.set,
            # Połącz Listbox ze Scrollbarem: gdy scrollujesz listę, scrollbar się przesuwa.
            # sb.set = funkcja którą Listbox wywołuje żeby poinformować scrollbar o pozycji.

            bg='#181825',              # tło listy
            fg='#cdd6f4',              # kolor tekstu wierszy
            selectbackground='#45475a', # tło zaznaczonego wiersza
            selectforeground='#cdd6f4', # tekst zaznaczonego wiersza
            font=('Courier New', 10),
            # Courier New = czcionka o stałej szerokości (monospace).
            # Wszystkie znaki mają tę samą szerokość → ikony i tekst ładnie się wyrównują.
            # Rozmiar 10 = dość mały, mieści dużo botów.
            # ZMIANA: ('Consolas', 11) lub ('Courier', 10) lub ('Arial', 11)

            activestyle='none',
            # Domyślnie Tkinter podkreśla element nad którym jest mysz (hover).
            # 'none' = wyłącz to podkreślenie — wygląda czyściej.
        )
        self.bot_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.bot_list.yview)
        # Połącz Scrollbar z Listbox w drugą stronę:
        # gdy przeciągasz scrollbar → lista się przesuwa (yview).

        self.bot_list.bind('<<ListboxSelect>>', self._on_select_bot)
        # bind() = "nasłuchuj na zdarzenie i wywołaj funkcję gdy zajdzie"
        # '<<ListboxSelect>>' = wirtualne zdarzenie Tkinter: kliknięcie na element listy
        # self._on_select_bot = funkcja wywoływana przy kliknięciu
        # Alternatywy: '<Button-1>' (pojedyncze kliknięcie), '<Double-Button-1>' (podwójne)


        # ══════════════════════════════════════════════════════════════════════
        # PANEL ŚRODKOWY — szczegóły wybranego bota
        # ══════════════════════════════════════════════════════════════════════

        mid = ttk.LabelFrame(paned, text='💬 Wybrany bot', padding=5)
        paned.add(mid, weight=3)
        # weight=3 = trzy razy szerszy niż lewa kolumna

        self.lbl_bot = ttk.Label(mid, text='Wybierz bota z listy', foreground='#6c7086')
        self.lbl_bot.pack(anchor=tk.W, pady=(0, 4))
        # Etykieta z info o wybranym bocie.
        # Domyślnie szary tekst "Wybierz bota z listy" — zmienia się po kliknięciu.
        # anchor=tk.W = wyrównaj do lewej (W = West)
        # Aktualizowana przez _on_select_bot() gdy klikniesz bota.

        # ── Ramka z listą stołów ──────────────────────────────────────────────
        # Wyświetla stoły które serwer kurnik.pl wysłał dla wybranego bota.
        tables_frame = ttk.LabelFrame(mid, text='📋 Stoły w pokoju', padding=4)
        tables_frame.pack(fill=tk.X, pady=(0, 6))
        # fill=tk.X = rozciągnij poziomo ALE nie pionowo (lista stołów jest stała wysokość)

        tf2 = tk.Frame(tables_frame, bg='#1e1e2e')
        tf2.pack(fill=tk.X)
        tsb = ttk.Scrollbar(tf2, orient=tk.VERTICAL)
        tsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.table_list = tk.Listbox(
            tf2,
            yscrollcommand=tsb.set,
            height=6,
            # height=6 = lista ma zawsze 6 wierszy wysokości (nie rozciąga się).
            # ZMIANA: większa liczba = więcej stołów widocznych bez scrollowania.

            bg='#181825',
            fg='#a6e3a1',
            # Zielony kolor tekstu dla stołów — wizualnie odróżnia od listy botów.
            # ZMIANA: '#89b4fa' = niebieski, '#cdd6f4' = biały, '#f38ba8' = czerwony

            selectbackground='#45475a',
            selectforeground='#cdd6f4',
            font=('Courier New', 9),
            # Rozmiar 9 = mniejszy żeby więcej informacji mieściło się w wierszu
        )
        self.table_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tsb.config(command=self.table_list.yview)

        ttk.Button(
            tables_frame,
            text='➡  Dołącz do zaznaczonego stołu',
            command=self._join_selected_table
        ).pack(anchor=tk.W, pady=(4, 0))
        # Przycisk: zaznacz stół na liście powyżej, potem kliknij ten przycisk.
        # Wywołuje _join_selected_table() która odczytuje zaznaczenie z table_list.

        # ── Ręczny JOIN po wpisaniu ID ────────────────────────────────────────
        # Gdy stołu nie ma na liście (np. właśnie powstał), możesz wpisać numer ręcznie.
        jf = tk.Frame(mid, bg='#1e1e2e')
        jf.pack(fill=tk.X, pady=2)
        ttk.Label(jf, text='ID stołu:').pack(side=tk.LEFT, padx=(0, 4))
        # side=tk.LEFT = układaj widgety poziomo (od lewej do prawej)

        self.v_join_id = tk.StringVar()
        # Puste pole na numer stołu — użytkownik wpisze ID ręcznie.

        ttk.Entry(jf, textvariable=self.v_join_id, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(jf, text='➡ Dołącz', command=self._join_manual).pack(side=tk.LEFT)

        # ── Wysyłanie wiadomości do wybranego bota ────────────────────────────
        bf = ttk.LabelFrame(mid, text='📨 Wyślij do wybranego bota', padding=4)
        bf.pack(fill=tk.X, pady=4)
        ef = tk.Frame(bf, bg='#1e1e2e')
        ef.pack(fill=tk.X)

        self.ent_one = ttk.Entry(ef, font=('Segoe UI', 10))
        # Pole tekstowe do wpisania wiadomości lub komendy dla konkretnego bota.
        # Akceptuje tekst chatu ("/join 5", "cześć", "/quit" itp.)

        self.ent_one.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        # fill=tk.X + expand=True = pole rozciąga się żeby wypełnić dostępną szerokość

        self.ent_one.bind('<Return>', lambda _: self._send_one())
        # '<Return>' = naciśnięcie klawisza Enter.
        # lambda _ = anonimowa funkcja która ignoruje argument zdarzenia (_)
        #            i wywołuje _send_one().
        # Dzięki temu możesz wysłać wiadomość przez Enter bez klikania przycisku.

        ttk.Button(ef, text='Wyślij', command=self._send_one).pack(side=tk.LEFT)

        ttk.Label(mid, text='Log:').pack(anchor=tk.W)

        self.txt_bot = scrolledtext.ScrolledText(
            mid,
            state=tk.DISABLED,
            # DISABLED = pole tylko do odczytu (użytkownik nie może pisać).
            # Włączamy NORMAL tymczasowo gdy chcemy dopisać tekst, potem z powrotem DISABLED.
            # To standardowy pattern Tkinter dla logów: DISABLED zapobiega przypadkowej edycji.

            height=12,
            # Wysokość w wierszach tekstu. 12 = ok. 12 linii widocznych naraz.
            # ZMIANA: Większa liczba = więcej logu widocznego bez scrollowania.

            bg='#181825',
            fg='#cdd6f4',
            insertbackground='#cdd6f4',
            # insertbackground = kolor kursora tekstowego (miga gdy wpisujesz).
            # Tu bez znaczenia bo DISABLED, ale dobrze ustawić na wypadek NORMAL.

            font=('Courier New', 9),
        )
        self.txt_bot.pack(fill=tk.BOTH, expand=True)
        # fill=tk.BOTH + expand=True = log wypełnia całą pozostałą przestrzeń panelu


        # ══════════════════════════════════════════════════════════════════════
        # PANEL PRAWY — broadcast do wszystkich + zbiorczy log
        # ══════════════════════════════════════════════════════════════════════

        right = ttk.LabelFrame(paned, text='📢 Broadcast & Log', padding=5)
        paned.add(right, weight=3)
        # weight=3 = taka sama szerokość jak panel środkowy

        # ── Broadcast wiadomości do WSZYSTKICH botów ──────────────────────────
        bf2 = ttk.LabelFrame(right, text='Wyślij do wszystkich botów', padding=4)
        bf2.pack(fill=tk.X, pady=(0, 6))
        ef2 = tk.Frame(bf2, bg='#1e1e2e')
        ef2.pack(fill=tk.X)

        self.ent_all = ttk.Entry(ef2, font=('Segoe UI', 10))
        # Pole do wpisania wiadomości którą chcesz wysłać DO KAŻDEGO bota.
        # Np. jeśli wpiszesz "cześć!" i klikniesz 📢 Broadcast,
        # KAŻDY aktywny bot wyśle "cześć!" na swoim stole.

        self.ent_all.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.ent_all.bind('<Return>', lambda _: self._send_all())
        ttk.Button(ef2, text='📢 Broadcast', command=self._send_all).pack(side=tk.LEFT)

        # ── Przełącz WSZYSTKIE boty na jeden stół ────────────────────────────
        jba = ttk.LabelFrame(right, text='Przełącz wszystkie boty na stół', padding=4)
        jba.pack(fill=tk.X, pady=(0, 6))
        ef3 = tk.Frame(jba, bg='#1e1e2e')
        ef3.pack(fill=tk.X)

        self.v_join_all = tk.StringVar()
        # Pole na numer stołu docelowego dla wszystkich botów.
        # Gdy wpiszesz "7" i klikniesz przycisk, KAŻDY bot dostanie komendę "/join 7".

        ttk.Entry(ef3, textvariable=self.v_join_all, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(ef3, text='➡ Przełącz wszystkie', command=self._join_all).pack(side=tk.LEFT)

        # ── Zbiorczy log WSZYSTKICH botów ─────────────────────────────────────
        ttk.Label(right, text='Zbiorczy log:').pack(anchor=tk.W)

        self.txt_all = scrolledtext.ScrolledText(
            right,
            state=tk.DISABLED,
            bg='#181825',
            fg='#cdd6f4',
            insertbackground='#cdd6f4',
            font=('Courier New', 9),
        )
        self.txt_all.pack(fill=tk.BOTH, expand=True)
        # Ten log pokazuje wiadomości od WSZYSTKICH botów, prefixowane numerem bota:
        # "[14:35:22] Bot #1: ✅ Połączono"
        # "[14:35:23] Bot #2: 🔑 Sesja OK"
        # Pełna historia sesji — przydatna do debugowania i eksportu.


    # ══════════════════════════════════════════════════════════════════════════
    # AKCJE — metody wywoływane przez przyciski i interakcje GUI
    # ══════════════════════════════════════════════════════════════════════════

    # ──────────────────────────────────────────────────────────────────────────
    # METODA _run_bots() — uruchamia N botów
    # Wywoływana przez przycisk "▶ Uruchom"
    #
    # CO ROBI KROK PO KROKU:
    #   1. Odczytuje ustawienia z pól konfiguracji (pokój, liczba, stół)
    #   2. Waliduje dane (czy pokój to liczba?)
    #   3. Dla każdego bota: tworzy obiekt Bot, uruchamia go, dodaje do słownika i listy
    #
    # KIEDY EDYTOWAĆ:
    #   → Chcesz żeby każdy bot dostawał inny pokój? Zmień logikę ustalania 'room'.
    #   → Chcesz żeby boty startowały z opóźnieniem? Dodaj time.sleep(0.5) w pętli for.
    #   → Chcesz limit botów? Dodaj: if len(self.bots) >= 10: messagebox.showerror(...)
    # ──────────────────────────────────────────────────────────────────────────
    def _run_bots(self):
        room = self.v_room.get().strip()
        # .get() = odczytaj aktualną wartość z StringVar
        # .strip() = usuń spacje z początku i końca (np. jeśli user wpisał " 100 ")

        if not room.isdigit():
            # .isdigit() = sprawdza czy string zawiera TYLKO cyfry
            # "100" → True, "abc" → False, "10.5" → False, "" → False
            messagebox.showerror('Błąd', 'Numer pokoju musi być liczbą')
            # Pokaż okno dialogowe z błędem. Zatrzymuje wykonanie przez return poniżej.
            return
            # Wyjdź z metody — nie uruchamiaj botów jeśli pokój jest nieprawidłowy.

        count  = self.v_count.get()
        # .get() na IntVar zwraca int (np. 2), nie string.
        # Liczba botów do uruchomienia.

        shared = self.v_shared.get()
        # .get() na BooleanVar zwraca bool (True lub False).
        # True = wszystkie boty → ten sam stół, False = każdy bot → inny stół.

        try:
            base_table = int(self.v_table.get()) if self.v_table.get().strip() else 0
            # Jeśli pole "Stół (start)" nie jest puste → sparsuj jako int.
            # Jeśli jest puste → ustaw 0 (obserwator).
            # int() rzuci ValueError jeśli wpisano np. "abc" → lapie except poniżej.
        except ValueError:
            messagebox.showerror('Błąd', 'Numer stołu musi być liczbą (0 = obserwator)')
            return

        for _ in range(count):
            # Pętla uruchamia się 'count' razy.
            # _ = "nie interesuje mnie numer iteracji" (konwencja Pythona)

            idx = self._next_id
            # Przypisz następny wolny numer. Po użyciu inkrementujemy licznik.
            

            if shared:
                table = base_table
                # Wszyscy boty → ten sam stół (np. 5)
            else:
                table = idx
                # Bot #1 → stół 1, Bot #2 → stół 2, itp.
                # Przydatne gdy chcesz mieć boty na różnych stołach.

            bot = Bot(idx, self.nick, room, table)
            # Utwórz nowy obiekt Bot. To jeszcze nie uruchamia procesu!

            if bot.start(self.script):
                # start() uruchamia subprocess i wątek odczytu.
                # Zwraca True jeśli się udało.

                self.bots[idx] = bot
                # Dodaj do słownika aktywnych botów.
                # Klucz = idx (np. 3), wartość = obiekt Bot.

                self.nick str[{'i': [31], 's': ['1']}] = nick


                self.bot_list.insert(tk.END, bot.label)
                # Dodaj wpis na końcu (tk.END) listy botów w GUI.
                # bot.label generuje tekst np. "🟡 Bot #03  R:100  T:5"

                self._log_all(f'🚀 Uruchomiono Bot #{idx:02d} N:{nick} R:{room}  T:{table or "—"}')
                # Dopisz do zbiorczego logu informację o uruchomieniu.
            else:
                self._log_all(f'❌ Nie udało się uruchomić Bot #{idx:02d}')
                # Jeśli start() zwróciło False — zaloguj błąd.

            self._next_id += 1
            # Inkrementuj licznik dla następnego bota.
            # Wykonuje się ZAWSZE (nawet jeśli start() się nie udało)
            # żeby numery były unikalne.


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _stop_all() — zatrzymuje wszystkie boty
    # Wywoływana przez przycisk "⏹ Stop all"
    # ──────────────────────────────────────────────────────────────────────────
    def _stop_all(self):
        for bot in list(self.bots.values()):
            # list(...) = skopiuj wartości słownika do listy PRZED iteracją.
            # Dlaczego? Bo wewnątrz pętli modyfikujemy self.bots (przez clear()).
            # Modyfikacja słownika w trakcie iteracji po nim = błąd RuntimeError.
            # Kopiując do listy, iterujemy po KOPII — bezpiecznie.
            bot.stop()
            # Wyślij /quit, terminate(), ewentualnie kill().

        self.bots.clear()
        # Usuń wszystkie wpisy ze słownika botów.
        # Obiekty Bot zostaną zniszczone przez garbage collector.

        self.bot_list.delete(0, tk.END)
        # Wyczyść Listbox od pierwszego (0) do ostatniego elementu (tk.END).

        self.sel = None
        # Odznacz wybrany bot (żaden nie jest wybrany).

        self._next_id = 1
        # Zresetuj licznik — następne boty zaczną od #01.
        # Bezpieczne bo wszystkie stare boty są usunięte.

        self._log_all('⏹  Wszystkie boty zatrzymane')
        self._refresh_table_list([])
        # Wyczyść listę stołów ([] = pusta lista).


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _on_select_bot() — reaguje na kliknięcie bota na liście
    # Wywoływana automatycznie przez binding '<<ListboxSelect>>'
    #
    # PROBLEM DO ROZWIĄZANIA:
    # Listbox ma indeksy 0,1,2... (zwykłe pozycje na liście).
    # Boty mają idx 1,3,5... (mogą być "dziury" po martwych botach).
    # Musimy zmapować "pozycję na liście" → "idx bota".
    #
    # ROZWIĄZANIE:
    # list(self.bots.keys()) = lista idx botów w kolejności dodania
    # np. jeśli mamy boty #1, #3, #5: [1, 3, 5]
    # Kliknięcie pozycji 1 (drugi element) → ids[1] = 3 → Bot #3
    # ──────────────────────────────────────────────────────────────────────────
    def _on_select_bot(self, _event=None):
        # _event = obiekt zdarzenia Tkinter (nie używamy go, ale musi być parametrem).
        # Konwencja: _ lub _event oznacza "ignoruję ten parametr".

        sel = self.bot_list.curselection()
        # curselection() = tupla z indeksami zaznaczonych wierszy.
        # Przykład gdy zaznaczony drugi wiersz: (1,)
        # Gdy nic niezaznaczone: ()
        if not sel:
            return
            # Nic nie zaznaczone (zdarza się np. przy programowym odznaczeniu).

        ids = list(self.bots.keys())
        # Konwertuj klucze słownika na listę żeby móc indeksować przez [].
        # Słownik w Pythonie 3.7+ zachowuje kolejność wstawiania.
        # Przykład: {1: Bot, 3: Bot, 5: Bot} → [1, 3, 5]

        if sel[0] >= len(ids):
            return
            # Zabezpieczenie: kliknięto pozycję która już nie istnieje
            # (bot mógł umrzeć między kliknięciem a obsługą zdarzenia).

        self.sel = ids[sel[0]]
        # sel[0] = indeks zaznaczonego wiersza (np. 1)
        # ids[1] = idx bota na tej pozycji (np. 3)
        # self.sel = 3 → "Bot #3 jest wybrany"

        bot = self.bots[self.sel]
        # Pobierz obiekt Bot dla wybranego idx.

        self.lbl_bot.config(
            text=f'Bot #{self.sel:02d}  |  Pokój: {bot.room}  |  Stół: {bot.table or "—"}',
            foreground='#89b4fa'
            # Zmień kolor na niebieski (aktywny) z szarego (nieaktywny).
        )
        # Zaktualizuj etykietę nagłówka środkowego panelu z danymi wybranego bota.

        self._refresh_bot_log(self.sel)
        # Załaduj CAŁĄ historię wiadomości tego bota do pola txt_bot.

        self._refresh_table_list(bot.tables)
        # Załaduj ostatnią listę stołów tego bota do table_list.


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _refresh_table_list() — odświeża listę stołów w GUI
    #
    # Wywoływana gdy:
    #   - klikasz nowego bota na liście (_on_select_bot)
    #   - bot dostaje aktualizację stołów z serwera (_tick → __TABLES__)
    #   - stop_all() czyści wszystko
    #
    # PARAMETRY:
    #   tables = lista słowników [{'id': int, 'params': str, 'players': str}, ...]
    #            Pusta lista [] = wyczyść listę stołów w GUI
    # ──────────────────────────────────────────────────────────────────────────
    def _refresh_table_list(self, tables: List[Dict]):
        self.table_list.delete(0, tk.END)
        # Wyczyść wszystkie stare wpisy w Listbox stołów.

        for t in tables:
            players = t['players'] or '(brak graczy)'
            # t['players'] może być '' (pusty string) = falsy → wyświetl "(brak graczy)"
            # Jeśli niepuste = np. "Kowalski, Nowak" → wyświetl to.

            self.table_list.insert(tk.END,
                f"ID:{t['id']:>4}  {t['params']:<20}  👥 {players}")
            # Format wyświetlanego wiersza. Przykłady:
            # "ID:   3  3+2                   👥 Kowalski, Nowak"
            # "ID:  15  bez limitu            👥 (brak graczy)"
            #
            # {:>4}  = wyrównaj liczbę do PRAWEJ, min. 4 znaki (spacje z lewej)
            #          3 → "   3", 15 → "  15", 100 → " 100"
            # {:<20} = wyrównaj tekst do LEWEJ, min. 20 znaków (spacje z prawej)
            #          "3+2" → "3+2                 "
            # Dzięki temu kolumny są wyrównane (monospace font).
            #
            # ZMIANA: Chcesz inny format? Modyfikuj f-string.
            # Chcesz inną szerokość kolumn? Zmień liczby w {:>4} i {:<20}.


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _join_selected_table() — dołącza wybranego bota do zaznaczonego stołu
    # Wywoływana przez przycisk "➡ Dołącz do zaznaczonego stołu"
    #
    # WYMAGA:
    #   1. Wybranego bota na liście botów (self.sel != None)
    #   2. Zaznaczonego wiersza na liście stołów (table_list.curselection())
    # ──────────────────────────────────────────────────────────────────────────
    def _join_selected_table(self):
        if self.sel is None or self.sel not in self.bots:
            return
            # Brak wybranego bota → nic nie rób.
            # self.sel not in self.bots = bot mógł umrzeć po zaznaczeniu go.

        sel = self.table_list.curselection()
        if not sel:
            messagebox.showinfo('Info', 'Zaznacz stół na liście')
            # Użytkownik nie zaznaczył żadnego stołu — pokaż podpowiedź.
            return

        bot = self.bots[self.sel]
        # Pobierz obiekt wybranego bota.

        table_entry = bot.tables[sel[0]]
        # bot.tables = lista słowników stołów (wypełniana przez _handle_line)
        # sel[0] = indeks zaznaczonego wiersza w table_list
        # KLUCZOWE: indeks w table_list ODPOWIADA indeksowi w bot.tables
        # bo obie listy są synchronizowane przez _refresh_table_list().
        # Przykład: zaznaczony wiersz 2 → bot.tables[2] = {'id': 7, 'params': '3+2', ...}

        tid = table_entry['id']
        # Wyciągnij ID stołu ze słownika (np. 7).

        bot.join_table(tid)
        # Wyślij /join 7 do bota przez stdin.

        self._log_all(f'➡️  Bot #{self.sel} → stół {tid}')
        # Zaloguj akcję w zbiorczym logu.


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _join_manual() — dołącza wybranego bota do stołu wpisanego ręcznie
    # Wywoływana przez przycisk "➡ Dołącz" obok pola "ID stołu:"
    #
    # UŻYCIE: Gdy stołu nie ma na liście (np. właśnie powstał nowy stół).
    # ──────────────────────────────────────────────────────────────────────────
    def _join_manual(self):
        if self.sel is None or self.sel not in self.bots:
            return

        raw = self.v_join_id.get().strip()
        # Odczytaj tekst z pola "ID stołu:" i usuń białe znaki.

        if not raw.isdigit():
            messagebox.showerror('Błąd', 'Podaj numer stołu')
            return
            # Użytkownik wpisał coś co nie jest liczbą.

        tid = int(raw)
        # Skonwertuj string na int (walidacja wyżej gwarantuje że to cyfry).

        self.bots[self.sel].join_table(tid)
        # Wyślij /join do wybranego bota.

        self._log_all(f'➡️  Bot #{self.sel} → stół {tid}')


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _join_all() — przełącza WSZYSTKIE boty na jeden stół
    # Wywoływana przez przycisk "➡ Przełącz wszystkie"
    #
    # To "operacja masowa" — jeden klik zmienia stół wszystkim aktywnym botom.
    # Przydatne gdy chcesz zebrać wszystkich botów przy jednym stole.
    # ──────────────────────────────────────────────────────────────────────────
    def _join_all(self):
        raw = self.v_join_all.get().strip()
        # Odczytaj numer stołu z pola "Przełącz wszystkie boty na stół".

        if not raw.isdigit():
            messagebox.showerror('Błąd', 'Podaj numer stołu')
            return

        tid = int(raw)

        cnt = sum(1 for b in self.bots.values() if b.join_table(tid))
        # Wyrażenie generatorowe: dla każdego bota wywołaj join_table(tid).
        # join_table() zwraca True (=1) jeśli wysłano, False (=0) jeśli bot martwy.
        # sum() zsumuje True jako 1 → cnt = liczba botów które faktycznie dostały komendę.
        # Przykład: 5 botów, 1 martwy → cnt = 4.

        self._log_all(f'➡️  Przełączono {cnt} botów → stół {tid}')


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _send_one() — wysyła wiadomość do wybranego bota
    # Wywoływana przez przycisk "Wyślij" lub klawisz Enter w polu ent_one
    # ──────────────────────────────────────────────────────────────────────────
    def _send_one(self):
        if self.sel is None or self.sel not in self.bots:
            return

        msg = self.ent_one.get().strip()
        # Odczytaj tekst z pola "Wyślij do wybranego bota".

        if msg:
            # Wysyłaj tylko jeśli pole nie jest puste.
            if self.bots[self.sel].send(msg):
                # send() wysyła msg do stdin bota i zwraca True jeśli się udało.

                self.ent_one.delete(0, tk.END)
                # Wyczyść pole po wysłaniu (od znaku 0 do końca).
                # Użytkownik może od razu wpisać kolejną wiadomość.

                self._log_all(f'Bot #{self.sel} ➜ {msg}')
                # Zaloguj wysłaną wiadomość w zbiorczym logu z strzałką ➜.

                self._append_bot_log(f'➜ {msg}')
                # Zaloguj też w logu konkretnego bota (widocznym w środkowym panelu).
                # Dzięki temu widzisz zarówno co bot dostał jak i co wysłałeś.


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _send_all() — wysyła tę samą wiadomość do WSZYSTKICH botów (broadcast)
    # Wywoływana przez przycisk "📢 Broadcast" lub Enter w polu ent_all
    # ──────────────────────────────────────────────────────────────────────────
    def _send_all(self):
        msg = self.ent_all.get().strip()

        if msg and self.bots:
            # Wysyłaj tylko jeśli wiadomość niepusta I są jakieś boty.

            cnt = sum(1 for b in self.bots.values() if b.send(msg))
            # Wyślij do każdego bota i policz ile faktycznie dostało wiadomość.

            self.ent_all.delete(0, tk.END)
            # Wyczyść pole po wysłaniu.

            self._log_all(f'📢 BROADCAST ({cnt}): {msg}')
            # Zaloguj broadcast z informacją ile botów dostało wiadomość.


    # ══════════════════════════════════════════════════════════════════════════
    # METODY LOGOWANIA — dopisują tekst do widgetów ScrolledText
    #
    # DLACZEGO TAK SKOMPLIKOWANE? (NORMAL → insert → DISABLED)
    # ScrolledText ma stan DISABLED = "tylko do odczytu".
    # Gdy próbujemy insert() na DISABLED widget → cichy błąd, nic się nie dopisuje.
    # Musimy na chwilę przełączyć na NORMAL, dopisać, potem z powrotem DISABLED.
    # To standardowy pattern Tkinter dla logów — zapamiętaj go.
    # ══════════════════════════════════════════════════════════════════════════

    # ──────────────────────────────────────────────────────────────────────────
    # METODA _log_all() — dopisuje do zbiorczego logu (prawy panel)
    # ──────────────────────────────────────────────────────────────────────────
    def _log_all(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        # Aktualny czas w formacie GG:MM:SS.
        # Przykład: "14:35:22"
        # ZMIANA: '%H:%M:%S.%f' = z milisekundami: "14:35:22.123456"
        #         '%d.%m %H:%M' = z datą: "22.03 14:35"

        self.txt_all.config(state=tk.NORMAL)
        # Odblokuj do zapisu.

        self.txt_all.insert(tk.END, f'[{ts}] {msg}\n')
        # Dopisz na końcu (tk.END).
        # f'[{ts}] {msg}\n' = np. "[14:35:22] Bot #1: ✅ Połączono\n"
        # '\n' = nowa linia na końcu (każda wiadomość w osobnym wierszu).

        self.txt_all.see(tk.END)
        # Przewiń do końca żeby nowy wpis był widoczny (autoscroll).
        # Bez tego log scrollowałby do góry po każdym dopisaniu.

        self.txt_all.config(state=tk.DISABLED)
        # Zablokuj z powrotem.

    # ──────────────────────────────────────────────────────────────────────────
    # METODA _append_bot_log() — dopisuje do logu wybranego bota (środkowy panel)
    # Działa identycznie jak _log_all ale na txt_bot.
    # ──────────────────────────────────────────────────────────────────────────
    def _append_bot_log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.txt_bot.config(state=tk.NORMAL)
        self.txt_bot.insert(tk.END, f'[{ts}] {msg}\n')
        self.txt_bot.see(tk.END)
        self.txt_bot.config(state=tk.DISABLED)

    # ──────────────────────────────────────────────────────────────────────────
    # METODA _refresh_bot_log() — ZASTĘPUJE zawartość logu bota całą historią
    # Wywoływana gdy klikasz na bota — ładuje wszystko co napisał od początku.
    #
    # Różnica od _append_bot_log:
    #   _append_bot_log = DOPISUJE jedną wiadomość na koniec (używana na bieżąco)
    #   _refresh_bot_log = ZASTĘPUJE całą zawartość historią (używana przy przełączaniu)
    # ──────────────────────────────────────────────────────────────────────────
    def _refresh_bot_log(self, idx: int):
        self.txt_bot.config(state=tk.NORMAL)

        self.txt_bot.delete('1.0', tk.END)
        # Usuń CAŁĄ zawartość od początku do końca.
        # '1.0' = pozycja: linia 1, znak 0 (od samego początku)
        # tk.END = do samego końca
        # Tkinter używa "linia.znak" jako pozycji, nie prostego indeksu.

        for line in self.bots[idx].lines:
            self.txt_bot.insert(tk.END, line + '\n')
        # Wstaw każdą linię z historii bota.
        # bot.lines = lista wszystkich wiadomości zebranych od startu bota.

        self.txt_bot.see(tk.END)
        self.txt_bot.config(state=tk.DISABLED)

    # ──────────────────────────────────────────────────────────────────────────
    # METODA _clear_logs() — czyści oba pola logów
    # Wywoływana przez przycisk "🗑 Wyczyść"
    # NIE zatrzymuje botów — tylko czyści wyświetlane logi.
    # NIE czyści bot.lines[] — historia jest zachowana w pamięci.
    # ──────────────────────────────────────────────────────────────────────────
    def _clear_logs(self):
        for w in (self.txt_bot, self.txt_all):
            # Iteruj przez oba widgety logów w jednej pętli.
            w.config(state=tk.NORMAL)
            w.delete('1.0', tk.END)
            w.config(state=tk.DISABLED)

    # ──────────────────────────────────────────────────────────────────────────
    # METODA _export() — eksportuje zbiorczy log do pliku .txt
    # Wywoływana przez przycisk "💾 Eksport"
    # ──────────────────────────────────────────────────────────────────────────
    def _export(self):
        fp = filedialog.asksaveasfilename(
            defaultextension='.txt',
            # Domyślne rozszerzenie — dodawane automatycznie jeśli user nie wpisze.

            filetypes=[('Tekst', '*.txt'), ('Wszystkie', '*.*')]
            # Lista typów plików w dialogu wyboru. Format: ('opis', 'wzorzec')
            # ZMIANA: Możesz dodać ('CSV', '*.csv') jeśli chcesz eksport CSV.
        )
        # filedialog.asksaveasfilename() = systemowe okno "Zapisz jako".
        # Zwraca wybraną ścieżkę jako string, lub '' jeśli user kliknął Anuluj.

        if fp:
            # Tylko jeśli user wybrał plik (nie kliknął Anuluj).
            try:
                with open(fp, 'w', encoding='utf-8') as f:
                    # Otwórz plik do zapisu ('w') z UTF-8.
                    # 'with' = automatycznie zamknie plik nawet przy błędzie.

                    f.write(f'Kurnik.pl Bot Export\nData: {datetime.now()}\n')
                    f.write(f'Boty: {len(self.bots)}\n\n')
                    # Nagłówek z datą i liczbą aktywnych botów.

                    f.write(self.txt_all.get('1.0', tk.END))
                    # txt_all.get('1.0', tk.END) = pobierz CAŁY tekst z logu.
                    # '1.0' = od początku, tk.END = do końca.

                messagebox.showinfo('OK', f'Zapisano: {fp}')
                # Pokaż okno sukcesu ze ścieżką zapisanego pliku.

            except Exception as e:
                messagebox.showerror('Błąd', str(e))
                # Pokaż błąd jeśli zapis się nie powiódł (np. brak uprawnień).


    # ══════════════════════════════════════════════════════════════════════════
    # METODA _tick() — SERCE GUI: pętla aktualizacji co 150ms
    #
    # TO NAJWAŻNIEJSZA METODA W App. Rozumiejąc ją, rozumiesz jak działa GUI.
    #
    # DLACZEGO JEST POTRZEBNA?
    # Tkinter działa w JEDNYM wątku (głównym).
    # Wątki botów (_reader) NIE MOGĄ modyfikować GUI bezpośrednio.
    # (Byłoby to jak dwie osoby jednocześnie piszące w jednym dokumencie → chaos)
    #
    # WZORZEC PRODUCENT-KONSUMENT:
    #   _reader() = "producent" → wrzuca dane do Queue (kolejka jako bufor)
    #   _tick()   = "konsument" → odczytuje z Queue i aktualizuje GUI
    #   Queue     = thread-safe "skrzynka odbiorcza" między nimi
    #
    # JAK DZIAŁA PĘTLA:
    #   _tick() jest wywoływana co 150ms przez root.after(150, self._tick).
    #   NIE jest prawdziwą pętlą while True — każde wywołanie planuje NASTĘPNE.
    #   To "kooperacyjna pętla" — oddaje kontrolę Tkinter między wywołaniami.
    #   Dzięki temu GUI pozostaje responsywne (można klikać przyciski, resize itp.)
    #
    # KIEDY EDYTOWAĆ:
    #   → Chcesz szybsze odświeżanie? Zmień 150 na np. 50 (ms). Uwaga: więcej CPU.
    #   → Chcesz wolniejsze? Zmień na 500. Logi będą z opóźnieniem.
    #   → Chcesz nowy typ sygnału (np. '__STATUS__')? Dodaj blok if msg == '__STATUS__':
    # ══════════════════════════════════════════════════════════════════════════
    def _tick(self):
        dead_bots = []
        # Lista botów które umarły w tej iteracji.
        # Nie usuwamy ich od razu (w środku pętli for) bo modyfikowanie
        # iterowanego słownika = błąd. Zbieramy idx, usuwamy PO pętli.

        ids = list(self.bots.keys())
        # Kopia kluczy słownika jako lista.
        # Dlaczego kopia? Bo jeśli bot umrze w tej iteracji i _rebuild_bot_list()
        # zmodyfikuje self.bots, moglibyśmy dostać RuntimeError "dictionary changed size".

        for idx in ids:
            bot = self.bots.get(idx)
            # .get() zamiast self.bots[idx] = bezpieczne, zwraca None zamiast KeyError
            # jeśli bot zniknął między pobraniem ids a tą linią.

            if not bot:
                continue
                # Bot zniknął (race condition) → pomiń.

            while True:
                # Opróżnij CAŁĄ kolejkę tego bota w jednej iteracji _tick().
                # Bez while True odczytalibyśmy tylko jedną wiadomość na 150ms
                # co przy dużym ruchu powodowałoby zapełnienie kolejki.

                try:
                    msg = bot.q.get_nowait()
                    # get_nowait() = pobierz element BEZ CZEKANIA.
                    # Jeśli kolejka pusta → rzuca queue.Empty → break.
                    # Alternatywa: bot.q.get(timeout=0.01) = czekaj 10ms — NIEPOŻĄDANE
                    # bo blokowałoby GUI.

                except queue.Empty:
                    break
                    # Kolejka pusta → wyjdź z while True, przejdź do następnego bota.

                # ── Sygnał specjalny: bot umarł ──────────────────────────────
                if msg == '__DEAD__':
                    dead_bots.append(idx)
                    # Zapamiętaj do usunięcia po pętli.
                    break
                    # Przestań czytać kolejkę tego bota — może zawierać
                    # stare wiadomości, ale bot jest martwy więc nie ma sensu.

                # ── Sygnał specjalny: aktualizacja listy stołów ───────────────
                if msg == '__TABLES__':
                    if self.sel == idx:
                        self._refresh_table_list(bot.tables)
                        # Odśwież listę stołów w GUI TYLKO gdy ten bot jest wybrany.
                        # Gdybyśmy zawsze odświeżali, kliknięcie innego bota zmieniałoby
                        # wyświetlane stoły na stoły poprzedniego bota.
                    self._log_all(f'Bot #{idx}: 📋 {len(bot.tables)} stołów')
                    # Zaloguj że otrzymano listę stołów z informacją ile jest stołów.
                    continue
                    # continue = wróć na początek while True (nie wykonuj kodu poniżej).

                # ── Zwykła wiadomość — zapisz i wyświetl ─────────────────────
                bot.lines.append(msg)
                # Dopisz do historii tego bota (do zobaczenia gdy klikniesz go na liście).

                self._log_all(f'Bot #{idx}: {msg}')
                # Dopisz do zbiorczego logu (prawy panel) z prefiksem numeru bota.

                if self.sel == idx:
                    self._append_bot_log(msg)
                    # Dopisz do logu WYBRANEGO bota (środkowy panel) TYLKO gdy jest wybrany.
                    # Gdy klikniesz innego bota, _refresh_bot_log() załaduje jego historię.

        # ── Usuń martwe boty ──────────────────────────────────────────────────
        if dead_bots:
            # Tylko jeśli są jakieś martwe boty do usunięcia.
            for idx in dead_bots:
                self._log_all(f'💀 Bot #{idx} zakończył działanie')
                self.bots.pop(idx, None)
                # .pop(idx, None) = usuń klucz idx ze słownika.
                # Drugi argument None = jeśli klucz nie istnieje, nie rzucaj KeyError.

            self._rebuild_bot_list()
            # Przebuduj Listbox od zera bez martwych botów.
            # Robimy to POZA pętlą (po usunięciu wszystkich martwych) dla wydajności.

        # ── Odśwież ikony statusu na liście botów ─────────────────────────────
        self._refresh_bot_labels()
        # Aktualizuj ikony 🟢/🟡/🔴 co 150ms — zmieniają się gdy bot zmienia status.

        self.root.after(150, self._tick)
        # ZAPLANUJ NASTĘPNE WYWOŁANIE za 150 milisekund.
        # root.after(ms, funkcja) = wywołaj funkcję po ms milisekundach.
        # To nie jest rekurencja w klasycznym sensie — Tkinter zarządza harmonogramem.
        # Nie zapełnia stosu wywołań bo każde wywołanie _tick() KOŃCZY się przed następnym.
        # ZMIANA: 150 → 50 dla szybszego odświeżania, → 500 dla wolniejszego.


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _rebuild_bot_list() — przebudowuje Listbox od zera
    # Wywoływana po śmierci bota żeby usunąć go z listy.
    #
    # DLACZEGO PRZEBUDOWUJEMY CAŁKOWICIE zamiast usunąć jeden wiersz?
    # Listbox.delete(i) usuwa element o indeksie i.
    # Po usunięciu indeksy pozostałych elementów się PRZESUWAJĄ.
    # To powoduje problemy z mapowaniem "indeks Listbox → idx bota".
    # Przebudowa od zera jest prostsza i bezpieczniejsza.
    # ──────────────────────────────────────────────────────────────────────────
    def _rebuild_bot_list(self):
        self.bot_list.delete(0, tk.END)
        # Wyczyść całą listę.

        for bot in self.bots.values():
            self.bot_list.insert(tk.END, bot.label)
        # Wstaw od nowa tylko żyjące boty.
        # Kolejność jest zachowana bo słownik w Python 3.7+ jest ordered.


    # ──────────────────────────────────────────────────────────────────────────
    # METODA _refresh_bot_labels() — aktualizuje etykiety na liście in-place
    # Wywoływana co 150ms przez _tick() żeby ikony 🟢/🟡/🔴 były aktualne.
    #
    # DLACZEGO IN-PLACE zamiast przebudowy?
    # Przebudowa (_rebuild_bot_list) KASUJE zaznaczenie w Listbox.
    # Gdybyśmy przebudowywali co 150ms, nie dałoby się utrzymać zaznaczenia.
    # In-place update: delete(i) + insert(i, nowy_tekst) = zamiana JEDNEGO wiersza.
    # Zaznaczenie (selection) pozostaje nienaruszone.
    # ──────────────────────────────────────────────────────────────────────────
    def _refresh_bot_labels(self):
        for i, bot in enumerate(self.bots.values()):
            # enumerate() = iteracja z indeksem: i=0,1,2... bot=Bot,Bot,Bot...
            try:
                self.bot_list.delete(i)
                # Usuń wiersz na pozycji i.

                self.bot_list.insert(i, bot.label)
                # Wstaw zaktualizowaną etykietę NA TĘ SAMĄ pozycję i.
                # Efekt: wiersz "🟡 Bot #01..." zmienia się na "🟢 Bot #01..."

            except tk.TclError:
                break
                # TclError = błąd wewnętrzny Tkinter.
                # Może wystąpić gdy Listbox ma mniej wierszy niż oczekujemy
                # (np. bot umarł a _rebuild_bot_list jeszcze nie wykonał się w tej iteracji).
                # Bezpieczne wyjście zamiast crashu.


# ══════════════════════════════════════════════════════════════════════════════
# PUNKT WEJŚCIA PROGRAMU
#
# Ten blok wykonuje się TYLKO gdy plik jest uruchamiany bezpośrednio:
#   python launcher.py
#
# NIE wykonuje się gdy jest importowany:
#   import launcher  ← __name__ == 'launcher', nie '__main__'
#
# To standardowa konwencja Python. Dzięki temu plik można importować
# (np. żeby przetestować klasę Bot) bez uruchamiania całego GUI.
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    root = tk.Tk()
    # Utwórz główne okno Tkinter.
    # tk.Tk() = "pień" całej aplikacji GUI. Jeden na program.
    # Wszystkie inne widgety są "dziećmi" tego okna (bezpośrednio lub pośrednio).

    app = App(root)
    # Utwórz aplikację: zbuduj GUI, uruchom pętlę _tick.
    # Zmienna app musi istnieć żeby obiekt App nie został zniszczony przez garbage collector.

    root.mainloop()
    # Uruchom pętlę zdarzeń Tkinter.
    # mainloop() BLOKUJE — program "zawiesza się" tutaj i czeka na zdarzenia GUI.
    # Zdarzenie = kliknięcie, wpisanie tekstu, resize okna, root.after() itp.
    # Wychodzi z mainloop() (i kończy program) gdy użytkownik zamknie okno (X).
