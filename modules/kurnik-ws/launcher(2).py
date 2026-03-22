#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py — GUI do zarządzania wieloma botami kurnik.pl

Architektura:
  - Klasa Bot   → reprezentuje jeden subprocess (kurnik-ws.py)
                  odczytuje jego stdout w osobnym wątku
                  wysyła komendy przez stdin
  - Klasa App   → okno Tkinter z trzema kolumnami:
                  [lista botów] [szczegóły wybranego] [broadcast + log globalny]
  - Pętla _tick → co 150ms odpytuje kolejki botów i aktualizuje GUI

Komunikacja launcher ↔ bot:
  stdout bota → _reader() w wątku → Queue → _tick() → GUI
  GUI → send()/join_table() → stdin bota
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
# scrolledtext — gotowy widget Text ze Scrollbarem
# messagebox   — okienka dialogowe (błąd, info, pytanie)
# filedialog   — okno wyboru pliku (eksport logów)

import subprocess   # uruchamianie procesów potomnych (kurnik-ws.py)
import threading    # wątek do odczytu stdout bota (nie blokuje GUI)
import queue        # bezpieczna kolejka między wątkiem odczytu a GUI
import sys          # sys.executable (ścieżka do Pythona), sys.platform
import io           # TextIOWrapper — nadpisanie kodowania na Windows
from datetime import datetime   # znaczniki czasu w logach
from pathlib  import Path       # ścieżki plików niezależne od systemu
from typing   import Dict, Any, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 1 — KODOWANIE UTF-8 NA WINDOWS
# ══════════════════════════════════════════════════════════════════════════════
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Domyślne wartości — muszą zgadzać się z DEFAULT_* w kurnik-ws.py
DEFAULT_GAME = 'kalambury'
DEFAULT_ROOM = '100'


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 2 — KLASA Bot
# Reprezentuje jeden uruchomiony proces bota.
# Każdy bot ma swój subprocess, wątek odczytu stdout i kolejkę wiadomości.
# ══════════════════════════════════════════════════════════════════════════════

class Bot:
    """Jedna instancja bota jako subprocess kurnik-ws.py."""

    def __init__(self, idx: int, room: str, table: int):
        """
        Parametry:
            idx   — unikalny numer bota (1, 2, 3, ...)
            room  — numer pokoju (np. '100')
            table — numer stołu do auto-dołączenia (0 = obserwator)
        """
        self.idx   = idx               # numer bota — używany w labelach i logach
        self.room  = room              # pokój do którego bot się łączy
        self.table = table             # aktualny stół (aktualizowany przez JOINED)
        self.proc: Optional[subprocess.Popen] = None  # obiekt procesu (po start())
        self.q:    queue.Queue = queue.Queue()         # kolejka wiadomości → GUI
        self.running   = False         # True gdy subprocess żyje
        self.connected = False         # True gdy bot wysłał CONNECTED
        self.lines:  List[str] = []    # historia wszystkich wiadomości (do wyświetlenia po kliknięciu)
        self.tables: List[Dict[str, Any]] = []  # ostatnia lista stołów z serwera

    # ── Uruchamianie ──────────────────────────────────────────────────────────

    def start(self, script: Path) -> bool:
        """
        Uruchamia subprocess kurnik-ws.py z odpowiednimi argumentami.

        Subprocess dostaje:
            --game kalambury    (zawsze, stała)
            --room <self.room>
            --table <self.table>  (tylko jeśli > 0)

        stdout i stderr subprocesu są przechwytywane przez pipe.
        stderr jest przekierowane do stdout (stderr=SUBPROCESS.STDOUT)
        żeby nie trzeba było obsługiwać dwóch oddzielnych strumieni.

        Po uruchomieniu startuje wątek _reader() który czyta stdout w tle.

        Zwraca True jeśli uruchomiono, False jeśli wystąpił błąd.
        """
        cmd = [
            sys.executable,      # ścieżka do interpretera Pythona (ten sam co launcher)
            str(script),         # ścieżka do kurnik-ws.py
            '--game', DEFAULT_GAME,
            '--room', self.room,
        ]
        if self.table:
            # Dodaj --table tylko gdy != 0 (0 = obserwator = nie dołączaj)
            cmd += ['--table', str(self.table)]

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,      # przechwytuj stdout do odczytu
                stderr=subprocess.STDOUT,    # stderr → do tego samego pipe co stdout
                stdin=subprocess.PIPE,       # pipe do wysyłania komend
                text=True,                   # odczyt/zapis jako stringi (nie bytes)
                encoding='utf-8',            # kodowanie UTF-8
                errors='replace',            # nieznane znaki → '?' zamiast wyjątku
                bufsize=1,                   # line-buffered (każda linia od razu dostępna)
            )
            self.running = True
            # Uruchom _reader() w wątku demona — zakończy się automatycznie z programem
            threading.Thread(target=self._reader, daemon=True).start()
            return True
        except Exception as e:
            # Umieść błąd w kolejce — GUI wyświetli go w logu
            self.q.put(f'[BŁĄD URUCHOMIENIA] {e}')
            return False

    # ── Wątek odczytu stdout ──────────────────────────────────────────────────

    def _reader(self):
        """
        Wątek tła — czyta stdout subprocesu linijka po linijce.

        Działa w pętli dopóki subprocess żyje (self.running = True).
        Każdą linię przekazuje do _handle_line() który ją interpretuje.

        Gdy subprocess zakończy działanie (for loop się wyczerpuje):
          - ustawia running = False, connected = False
          - wrzuca '__DEAD__' do kolejki → GUI usuwa bota z listy
        """
        try:
            # Iteracja po stdout — zatrzymuje się gdy proces zamknie pipe
            for raw in self.proc.stdout:
                if not self.running:
                    break            # stop() wywołane z zewnątrz
                line = raw.rstrip('\n')   # usuń znak nowej linii
                if not line:
                    continue         # puste linie ignoruj
                self._handle_line(line)
        except Exception:
            pass  # błąd odczytu — zakończ wątek cicho
        finally:
            # Niezależnie od przyczyny zakończenia — poinformuj GUI
            self.running   = False
            self.connected = False
            self.q.put('__DEAD__')   # specjalny sygnał do _tick()

    def _handle_line(self, line: str):
        """
        Interpretuje linię ze stdout bota.

        Rozpoznaje specjalne znaczniki protokołu i konwertuje je na:
          - zmiany stanu wewnętrznego bota (self.connected, self.table, self.tables)
          - wiadomości do GUI wrzucane do kolejki self.q

        Specjalne sygnały wewnętrzne (nie trafiają do logu wprost):
          '__DEAD__'   — bot zakończył działanie
          '__TABLES__' — lista stołów gotowa (odśwież GUI)

        Pozostałe wiadomości trafiają do self.q jako stringi
        i są wyświetlane w logu przez _tick().
        """
        # ── CONNECTED — bot nawiązał połączenie WS ────────────────────────────
        if line == 'CONNECTED':
            self.connected = True          # zmień ikonę na 🟢
            self.q.put('✅ Połączono')
            return

        # ── SESSION_OK — sesja HTTP z poprawnym tokenem kt= ──────────────────
        if line.startswith('SESSION_OK'):
            self.q.put('🔑 Sesja OK')
            return

        # ── SESSION_WARN — sesja bez kt= (może nie działać) ──────────────────
        if line.startswith('SESSION_WARN'):
            self.q.put('⚠️  Sesja bez kt=')
            return

        # ── TABLES_START — początek bloku listy stołów ────────────────────────
        # Wyczyść starą listę zanim zaczniemy zbierać nowe wiersze TABLE
        if line.startswith('TABLES_START'):
            self.tables = []
            return

        # ── TABLE id | params | players — jeden stół ─────────────────────────
        # Format: "TABLE 5 | 3+2 | Gracz1, Gracz2"
        # line[6:] odcina prefix "TABLE " (6 znaków)
        if line.startswith('TABLE '):
            parts = line[6:].split(' | ', 2)   # split na max 3 części
            if parts:
                try:
                    self.tables.append({
                        'id':      int(parts[0]),                          # ID stołu (liczba)
                        'params':  parts[1] if len(parts) > 1 else '',    # ustawienia stołu
                        'players': parts[2] if len(parts) > 2 else '',    # gracze przy stole
                    })
                except ValueError:
                    pass  # nieparsowalne ID — zignoruj ten stół
            return

        # ── TABLES_END — koniec bloku, lista gotowa ───────────────────────────
        # Wrzuć sygnał do kolejki → _tick() odświeży listę stołów w GUI
        if line == 'TABLES_END':
            self.q.put('__TABLES__')
            return

        # ── JOINED <id> — bot dołączył do stołu ──────────────────────────────
        if line.startswith('JOINED '):
            try:
                self.table = int(line[7:])   # line[7:] = numer za "JOINED "
            except ValueError:
                pass  # nie udało się sparsować — zostaw stary numer
            self.q.put(f'➡️  Stół {self.table}')
            return

        # ── TABLES_EMPTY — brak stołów w pokoju ──────────────────────────────
        if line == 'TABLES_EMPTY':
            self.q.put('⚠️  Brak stołów')
            return

        # ── CURRENT_TABLE <id> — odpowiedź na /table ─────────────────────────
        if line.startswith('CURRENT_TABLE '):
            self.q.put(f'📍 Stół: {line[14:]}')   # line[14:] = numer za "CURRENT_TABLE "
            return

        # ── MSG <tekst> — wiadomość z chatu/gry ──────────────────────────────
        # line[4:] odcina prefix "MSG " (4 znaki)
        if line.startswith('MSG '):
            self.q.put(line[4:])
            return

        # ── BOT_START — info o parametrach startu ────────────────────────────
        if line.startswith('BOT_START '):
            self.q.put(f'🚀 {line[10:]}')   # line[10:] = tekst za "BOT_START "
            return

        # ── Wszystko inne — wyświetl wprost (błędy, debug RAW, itp.) ─────────
        self.q.put(line)

    # ── Wysyłanie komend do bota ──────────────────────────────────────────────

    def send(self, text: str) -> bool:
        """
        Wysyła linię tekstu do stdin bota (+ '\n' na końcu).

        Używane do:
          - wysyłania wiadomości chatu
          - wysyłania komend (/join, /quit)

        Zwraca True jeśli udało się wysłać, False jeśli stdin jest zamknięty.
        """
        try:
            self.proc.stdin.write(text + '\n')   # dopisz \n — bot czyta readline()
            self.proc.stdin.flush()               # wymuś wysłanie (bez buforowania)
            return True
        except Exception:
            return False  # pipe zamknięty (bot martwy) — nie rzucaj wyjątku

    def join_table(self, tid: int) -> bool:
        """
        Przełącza bota na inny stół BEZ restartu subprocess.

        Wysyła komendę '/join <tid>' do stdin bota.
        Bot wyśle JOIN_TAB do serwera WS i odpowie 'JOINED <tid>' na stdout.
        self.table jest aktualizowane zarówno tutaj (optymistycznie) jak
        i przez _handle_line() gdy przyjdzie potwierdzenie JOINED.

        Parametry:
            tid — numer stołu docelowego

        Zwraca True jeśli komenda wysłana, False jeśli bot jest martwy.
        """
        if self.send(f'/join {tid}'):
            self.table = tid   # optymistyczna aktualizacja (przed potwierdzeniem)
            return True
        return False

    # ── Zatrzymanie ───────────────────────────────────────────────────────────

    def stop(self):
        """
        Zatrzymuje subprocess w sposób łagodny (graceful shutdown).

        Kolejność działań:
          1. Ustaw self.running = False (wątek _reader zakończy się)
          2. Wyślij /quit do stdin (bot zamknie WS i zakończy się sam)
          3. Wyślij SIGTERM (terminate()) jako backup
          4. Czekaj max 2 sekundy
          5. Jeśli nadal żyje — SIGKILL (kill())
        """
        self.running = False
        if self.proc:
            try:
                self.proc.stdin.write('/quit\n')   # poproś bota o zakończenie
                self.proc.stdin.flush()
            except Exception:
                pass  # stdin może być już zamknięty
            try:
                self.proc.terminate()          # SIGTERM — grzeczna prośba o zakończenie
                self.proc.wait(timeout=2)      # czekaj max 2 sekundy
            except Exception:
                try:
                    self.proc.kill()           # SIGKILL — wymuś zakończenie
                except Exception:
                    pass

    # ── Etykieta na liście botów ──────────────────────────────────────────────

    @property
    def label(self) -> str:
        """
        Generuje string wyświetlany na liście botów w GUI.

        Ikona statusu:
            🟢 — running=True  i connected=True  (bot połączony)
            🟡 — running=True  i connected=False (bot startuje/łączy się)
            🔴 — running=False                   (bot martwy)

        Format:
            🟢 Bot #01  R:100  T:5
            🟡 Bot #02  R:100  T:—
        """
        if self.running and self.connected:
            icon = '🟢'
        elif not self.running:
            icon = '🔴'
        else:
            icon = '🟡'    # running ale jeszcze nie connected
        return f'{icon} Bot #{self.idx:02d}  R:{self.room}  T:{self.table or "—"}'
        # :02d — formatuje liczbę z wiodącym zerem: 1→01, 10→10
        # self.table or "—" — jeśli stół = 0 (obserwator) wyświetl "—"


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 3 — KLASA App (główne okno GUI)
# ══════════════════════════════════════════════════════════════════════════════

class App:
    """
    Główna aplikacja GUI zbudowana w Tkinter/ttk.

    Struktura okna (trzy kolumny w PanedWindow):
        [1] Lista botów     — Listbox ze statusem każdego bota
        [2] Wybrany bot     — lista stołów, pole chat, log bota
        [3] Broadcast + log — wysyłanie do wszystkich, przełączanie stołów, log globalny
    """

    def __init__(self, root: tk.Tk):
        """
        Parametry:
            root — główne okno Tkinter (przekazane z bloku if __name__ == '__main__')
        """
        self.root = root
        self.root.title('🤖 Kurnik Bot Launcher')
        self.root.geometry('1500x850')           # szerokość x wysokość w pikselach
        self.root.configure(bg='#1e1e2e')        # ciemne tło (Catppuccin Mocha)

        # Ścieżka do skryptu bota — szuka kurnik-ws.py obok tego pliku
        self.script = Path(__file__).parent / 'kurnik-ws.py'

        self.bots:    Dict[int, Bot] = {}   # słownik: idx → obiekt Bot
        self.sel:     Optional[int]  = None # idx aktualnie wybranego bota (lub None)
        self._next_id = 1                   # licznik ID dla nowych botów (rośnie monotonicznie)

        self._build_ui()   # zbuduj wszystkie widgety
        self._tick()       # uruchom pętlę aktualizacji GUI (co 150ms)

    # ══════════════════════════════════════════════════════════════════════════
    # SEKCJA 3a — BUDOWANIE INTERFEJSU
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        """
        Buduje wszystkie widgety GUI.

        Hierarchia widgetów:
            root
            ├── cfg (LabelFrame) — panel konfiguracji na górze
            └── paned (PanedWindow) — trzy resizable panele
                ├── left  (LabelFrame) — lista botów + Listbox
                ├── mid   (LabelFrame) — szczegóły wybranego bota
                │   ├── tables_frame  — lista stołów + przycisk join
                │   ├── jf            — ręczny join po ID
                │   ├── bf            — pole chat dla jednego bota
                │   └── txt_bot       — log wybranego bota
                └── right (LabelFrame) — broadcast + log globalny
                    ├── bf2           — pole broadcast
                    ├── jba           — przełącz wszystkie boty na stół
                    └── txt_all       — zbiorczy log wszystkich botów
        """

        # ── Style ttk (motyw kolorystyczny) ──────────────────────────────────
        # ttk.Style pozwala nadpisać domyślne kolory widgetów ttk.
        # theme_use('clam') — bazowy motyw który wspiera customizację kolorów
        style = ttk.Style()
        style.theme_use('clam')
        # Tło i kolor tekstu dla poszczególnych typów widgetów
        style.configure('TLabelframe',       background='#1e1e2e', foreground='#cdd6f4')
        style.configure('TLabelframe.Label', background='#1e1e2e', foreground='#89b4fa',
                        font=('Segoe UI', 10, 'bold'))
        style.configure('TLabel',      background='#1e1e2e', foreground='#cdd6f4')
        style.configure('TButton',     background='#313244', foreground='#cdd6f4', padding=4)
        style.configure('TCheckbutton',background='#1e1e2e', foreground='#cdd6f4')
        style.configure('TEntry',      fieldbackground='#313244', foreground='#cdd6f4',
                        insertcolor='#cdd6f4')
        style.configure('TSpinbox',    fieldbackground='#313244', foreground='#cdd6f4')
        # Kolor przycisku po najechaniu myszą
        style.map('TButton', background=[('active', '#45475a')])

        # ── Panel konfiguracji (górny pasek) ──────────────────────────────────
        cfg = ttk.LabelFrame(self.root, text='⚙️  Konfiguracja', padding=8)
        cfg.pack(fill=tk.X, padx=10, pady=(10, 0))
        # fill=tk.X  → rozciągnij poziomo na całą szerokość okna
        # padx, pady → marginesy zewnętrzne

        # Liczba botów do uruchomienia
        ttk.Label(cfg, text='Botów:').grid(row=0, column=0, padx=4)
        self.v_count = tk.IntVar(value=2)   # tk.IntVar — zmienna powiązana z widgetem
        ttk.Spinbox(cfg, from_=1, to=50, textvariable=self.v_count, width=5).grid(
            row=0, column=1, padx=4)

        # Numer pokoju
        ttk.Label(cfg, text='Pokój:').grid(row=0, column=2, padx=4)
        self.v_room = tk.StringVar(value=DEFAULT_ROOM)
        ttk.Entry(cfg, textvariable=self.v_room, width=6).grid(row=0, column=3, padx=4)

        # Numer startowego stołu (0 = obserwator)
        ttk.Label(cfg, text='Stół (start):').grid(row=0, column=4, padx=4)
        self.v_table = tk.StringVar(value='0')
        ttk.Entry(cfg, textvariable=self.v_table, width=6).grid(row=0, column=5, padx=4)

        # Checkbox: wspólny stół dla wszystkich botów vs osobny (idx bota)
        self.v_shared = tk.BooleanVar(value=True)
        ttk.Checkbutton(cfg, text='Wspólny stół', variable=self.v_shared).grid(
            row=0, column=6, padx=8)

        # Przyciski sterowania
        ttk.Button(cfg, text='▶  Uruchom', command=self._run_bots).grid(row=0, column=7, padx=4)
        ttk.Button(cfg, text='⏹  Stop all', command=self._stop_all).grid(row=0, column=8, padx=4)
        ttk.Button(cfg, text='🗑  Wyczyść', command=self._clear_logs).grid(row=0, column=9, padx=4)
        ttk.Button(cfg, text='💾 Eksport',  command=self._export).grid(row=0, column=10, padx=4)

        # ── Główny układ: trzy panele obok siebie ────────────────────────────
        # PanedWindow pozwala użytkownikowi resize'ować panele przez przeciąganie
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        # fill=tk.BOTH + expand=True → wypełnij całą dostępną przestrzeń

        # ════════════════════════════════════════════════════════════════
        # PANEL LEWY — lista botów
        # ════════════════════════════════════════════════════════════════
        left = ttk.LabelFrame(paned, text='🤖 Boty', padding=5)
        paned.add(left, weight=1)   # weight=1 → proporcja przy resize (mniej miejsca)

        # Frame wewnętrzny żeby Listbox i Scrollbar były obok siebie
        sf = tk.Frame(left, bg='#1e1e2e')
        sf.pack(fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(sf)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # Listbox z listą botów — kliknięcie wywołuje _on_select_bot()
        self.bot_list = tk.Listbox(
            sf, yscrollcommand=sb.set,
            bg='#181825', fg='#cdd6f4',                    # kolory tła i tekstu
            selectbackground='#45475a', selectforeground='#cdd6f4',  # zaznaczenie
            font=('Courier New', 10),
            activestyle='none',    # bez podkreślenia przy hover
        )
        self.bot_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.bot_list.yview)   # połącz scrollbar z listbox

        # Zdarzenie kliknięcia na element listy → wybór bota
        self.bot_list.bind('<<ListboxSelect>>', self._on_select_bot)

        # ════════════════════════════════════════════════════════════════
        # PANEL ŚRODKOWY — szczegóły wybranego bota
        # ════════════════════════════════════════════════════════════════
        mid = ttk.LabelFrame(paned, text='💬 Wybrany bot', padding=5)
        paned.add(mid, weight=3)   # weight=3 → więcej miejsca niż panel lewy

        # Etykieta z info o wybranym bocie (aktualizowana przez _on_select_bot)
        self.lbl_bot = ttk.Label(mid, text='Wybierz bota z listy', foreground='#6c7086')
        self.lbl_bot.pack(anchor=tk.W, pady=(0, 4))
        # anchor=tk.W → wyrównaj do lewej

        # ── Lista stołów dostępnych w pokoju ─────────────────────────────────
        tables_frame = ttk.LabelFrame(mid, text='📋 Stoły w pokoju', padding=4)
        tables_frame.pack(fill=tk.X, pady=(0, 6))
        # fill=tk.X → rozciągnij poziomo, nie pionowo

        tf2 = tk.Frame(tables_frame, bg='#1e1e2e')
        tf2.pack(fill=tk.X)
        tsb = ttk.Scrollbar(tf2, orient=tk.VERTICAL)
        tsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Listbox ze stołami — wypełniany gdy bot odbierze TABLES_END
        self.table_list = tk.Listbox(
            tf2, yscrollcommand=tsb.set, height=6,   # wysokość = 6 wierszy
            bg='#181825', fg='#a6e3a1',              # zielony tekst = "stoły"
            selectbackground='#45475a', selectforeground='#cdd6f4',
            font=('Courier New', 9),
        )
        self.table_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tsb.config(command=self.table_list.yview)

        # Przycisk: dołącz wybranego bota do zaznaczonego stołu
        ttk.Button(
            tables_frame,
            text='➡  Dołącz do zaznaczonego stołu',
            command=self._join_selected_table
        ).pack(anchor=tk.W, pady=(4, 0))

        # ── Ręczny join po wpisaniu ID ────────────────────────────────────────
        jf = tk.Frame(mid, bg='#1e1e2e')
        jf.pack(fill=tk.X, pady=2)
        ttk.Label(jf, text='ID stołu:').pack(side=tk.LEFT, padx=(0, 4))
        self.v_join_id = tk.StringVar()   # pole tekstowe na ID stołu
        ttk.Entry(jf, textvariable=self.v_join_id, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(jf, text='➡ Dołącz', command=self._join_manual).pack(side=tk.LEFT)

        # ── Wysyłanie wiadomości do wybranego bota ────────────────────────────
        bf = ttk.LabelFrame(mid, text='📨 Wyślij do wybranego bota', padding=4)
        bf.pack(fill=tk.X, pady=4)
        ef = tk.Frame(bf, bg='#1e1e2e')
        ef.pack(fill=tk.X)

        # Pole tekstowe + Enter lub przycisk "Wyślij"
        self.ent_one = ttk.Entry(ef, font=('Segoe UI', 10))
        self.ent_one.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.ent_one.bind('<Return>', lambda _: self._send_one())  # Enter = wyślij
        ttk.Button(ef, text='Wyślij', command=self._send_one).pack(side=tk.LEFT)

        # ── Log wybranego bota ────────────────────────────────────────────────
        ttk.Label(mid, text='Log:').pack(anchor=tk.W)
        # ScrolledText = Text + Scrollbar w jednym widgecie
        # state=tk.DISABLED → tylko do odczytu (włączamy NORMAL tylko przy zapisie)
        self.txt_bot = scrolledtext.ScrolledText(
            mid, state=tk.DISABLED, height=12,
            bg='#181825', fg='#cdd6f4', insertbackground='#cdd6f4',
            font=('Courier New', 9),
        )
        self.txt_bot.pack(fill=tk.BOTH, expand=True)

        # ════════════════════════════════════════════════════════════════
        # PANEL PRAWY — broadcast do wszystkich + log globalny
        # ════════════════════════════════════════════════════════════════
        right = ttk.LabelFrame(paned, text='📢 Broadcast & Log', padding=5)
        paned.add(right, weight=3)   # taka sama waga jak panel środkowy

        # ── Broadcast tekstu do wszystkich botów ─────────────────────────────
        bf2 = ttk.LabelFrame(right, text='Wyślij do wszystkich botów', padding=4)
        bf2.pack(fill=tk.X, pady=(0, 6))
        ef2 = tk.Frame(bf2, bg='#1e1e2e')
        ef2.pack(fill=tk.X)
        self.ent_all = ttk.Entry(ef2, font=('Segoe UI', 10))
        self.ent_all.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.ent_all.bind('<Return>', lambda _: self._send_all())
        ttk.Button(ef2, text='📢 Broadcast', command=self._send_all).pack(side=tk.LEFT)

        # ── Przełącz WSZYSTKIE boty na jeden stół ────────────────────────────
        jba = ttk.LabelFrame(right, text='Przełącz wszystkie boty na stół', padding=4)
        jba.pack(fill=tk.X, pady=(0, 6))
        ef3 = tk.Frame(jba, bg='#1e1e2e')
        ef3.pack(fill=tk.X)
        self.v_join_all = tk.StringVar()   # pole na ID stołu docelowego
        ttk.Entry(ef3, textvariable=self.v_join_all, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(ef3, text='➡ Przełącz wszystkie', command=self._join_all).pack(side=tk.LEFT)

        # ── Zbiorczy log wszystkich botów ─────────────────────────────────────
        ttk.Label(right, text='Zbiorczy log:').pack(anchor=tk.W)
        self.txt_all = scrolledtext.ScrolledText(
            right, state=tk.DISABLED,
            bg='#181825', fg='#cdd6f4', insertbackground='#cdd6f4',
            font=('Courier New', 9),
        )
        self.txt_all.pack(fill=tk.BOTH, expand=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SEKCJA 3b — AKCJE (obsługa przycisków)
    # ══════════════════════════════════════════════════════════════════════════

    def _run_bots(self):
        """
        Uruchamia N botów według aktualnej konfiguracji z panelu górnego.

        Dla każdego bota:
          - tworzy obiekt Bot(idx, room, table)
          - wywołuje Bot.start(script_path)
          - dodaje do self.bots i do Listbox

        Jeśli 'Wspólny stół' = True  → wszystkie boty dołączają do tego samego stołu
        Jeśli 'Wspólny stół' = False → bot #1 → stół 1, bot #2 → stół 2, itd.
        """
        room = self.v_room.get().strip()
        if not room.isdigit():
            messagebox.showerror('Błąd', 'Numer pokoju musi być liczbą')
            return

        count  = self.v_count.get()       # liczba botów z Spinbox
        shared = self.v_shared.get()      # True/False z Checkbutton

        try:
            # Stół startowy — 0 jeśli pole puste
            base_table = int(self.v_table.get()) if self.v_table.get().strip() else 0
        except ValueError:
            messagebox.showerror('Błąd', 'Numer stołu musi być liczbą (0 = obserwator)')
            return

        for _ in range(count):
            idx = self._next_id   # unikalny numer dla tego bota

            # Ustal stół: wspólny → base_table, osobny → numer bota
            table = base_table if shared else idx

            bot = Bot(idx, room, table)
            if bot.start(self.script):
                self.bots[idx] = bot
                # Dodaj wpis do Listbox (na końcu)
                self.bot_list.insert(tk.END, bot.label)
                self._log_all(f'🚀 Uruchomiono Bot #{idx:02d}  R:{room}  T:{table or "—"}')
            else:
                self._log_all(f'❌ Nie udało się uruchomić Bot #{idx:02d}')

            self._next_id += 1   # następny bot dostanie wyższy numer

    def _stop_all(self):
        """
        Zatrzymuje wszystkie działające boty i czyści listę.
        Resetuje licznik ID do 1 (nowe boty zaczną od Bot #01).
        """
        for bot in list(self.bots.values()):
            bot.stop()           # wyślij /quit i terminate()
        self.bots.clear()        # wyczyść słownik botów
        self.bot_list.delete(0, tk.END)   # wyczyść Listbox
        self.sel = None          # odznacz wybrany bot
        self._next_id = 1        # zresetuj licznik
        self._log_all('⏹  Wszystkie boty zatrzymane')
        self._refresh_table_list([])   # wyczyść listę stołów

    def _on_select_bot(self, _event=None):
        """
        Wywoływana przez Listbox przy kliknięciu na bota.

        Mapuje indeks wiersza Listbox na idx bota w self.bots.
        (Listbox ma indeksy 0,1,2... a boty mają idx 1,2,3...)

        Aktualizuje:
          - self.sel       → idx wybranego bota
          - self.lbl_bot   → etykieta z info o bocie
          - self.txt_bot   → log wybranego bota
          - self.table_list → lista stołów tego bota
        """
        sel = self.bot_list.curselection()   # tupla z indeksami zaznaczonych wierszy
        if not sel:
            return

        # Mapuj indeks Listbox → klucz w self.bots (zachowując kolejność)
        ids = list(self.bots.keys())   # lista idx botów w kolejności dodania
        if sel[0] >= len(ids):
            return  # indeks poza zakresem (bot mógł zostać usunięty)

        self.sel = ids[sel[0]]   # zapisz idx wybranego bota
        bot = self.bots[self.sel]

        # Aktualizuj etykietę nagłówka środkowego panelu
        self.lbl_bot.config(
            text=f'Bot #{self.sel:02d}  |  Pokój: {bot.room}  |  Stół: {bot.table or "—"}',
            foreground='#89b4fa'
        )
        self._refresh_bot_log(self.sel)       # załaduj historię logu
        self._refresh_table_list(bot.tables)  # załaduj listę stołów

    def _refresh_table_list(self, tables: List[Dict]):
        """
        Odświeża Listbox ze stołami.

        Parametry:
            tables — lista słowników {'id', 'params', 'players'}
                     (z Bot.tables, które wypełnia _handle_line())

        Format wyświetlanego wiersza:
            ID:   5  3+2                   👥 Gracz1, Gracz2
        """
        self.table_list.delete(0, tk.END)   # wyczyść stare wpisy
        for t in tables:
            players = t['players'] or '(brak graczy)'
            # :>4  → wyrównaj ID do prawej (max 4 znaki)
            # :<20 → wyrównaj params do lewej (max 20 znaków)
            self.table_list.insert(tk.END,
                f"ID:{t['id']:>4}  {t['params']:<20}  👥 {players}")

    def _join_selected_table(self):
        """
        Dołącza wybranego bota do stołu zaznaczonego na liście stołów.

        Wymaga:
          - self.sel        → wybrany bot (kliknięty na liście botów)
          - zaznaczony wiersz w self.table_list

        Indeks zaznaczonego wiersza odpowiada bezpośrednio indeksowi
        w Bot.tables[] (obie listy są synchronizowane przez _refresh_table_list).
        """
        if self.sel is None or self.sel not in self.bots:
            return
        sel = self.table_list.curselection()
        if not sel:
            messagebox.showinfo('Info', 'Zaznacz stół na liście')
            return

        bot = self.bots[self.sel]
        table_entry = bot.tables[sel[0]]   # słownik stołu z indeksu zaznaczenia
        tid = table_entry['id']
        bot.join_table(tid)                # wyślij /join <tid> przez stdin
        self._log_all(f'➡️  Bot #{self.sel} → stół {tid}')

    def _join_manual(self):
        """
        Dołącza wybranego bota do stołu wpisanego ręcznie w polu 'ID stołu'.
        Używane gdy stół nie jest na liście (np. nowy stół, specjalny numer).
        """
        if self.sel is None or self.sel not in self.bots:
            return
        raw = self.v_join_id.get().strip()
        if not raw.isdigit():
            messagebox.showerror('Błąd', 'Podaj numer stołu')
            return
        tid = int(raw)
        self.bots[self.sel].join_table(tid)
        self._log_all(f'➡️  Bot #{self.sel} → stół {tid}')

    def _join_all(self):
        """
        Przełącza WSZYSTKIE aktywne boty na stół wpisany w polu 'Przełącz wszystkie'.

        Wywołuje join_table() na każdym bocie.
        Liczy ile botów udało się przełączyć (send() zwróciło True).
        """
        raw = self.v_join_all.get().strip()
        if not raw.isdigit():
            messagebox.showerror('Błąd', 'Podaj numer stołu')
            return
        tid = int(raw)
        # sum() z generatorem — zlicza True (=1) z join_table()
        cnt = sum(1 for b in self.bots.values() if b.join_table(tid))
        self._log_all(f'➡️  Przełączono {cnt} botów → stół {tid}')

    def _send_one(self):
        """
        Wysyła wiadomość z pola 'Wyślij do wybranego bota' do aktywnego bota.

        Po wysłaniu:
          - czyści pole tekstowe
          - loguje do globalnego logu i logu bota
        """
        if self.sel is None or self.sel not in self.bots:
            return
        msg = self.ent_one.get().strip()
        if msg:
            if self.bots[self.sel].send(msg):
                self.ent_one.delete(0, tk.END)   # wyczyść pole po wysłaniu
                self._log_all(f'Bot #{self.sel} ➜ {msg}')
                self._append_bot_log(f'➜ {msg}')  # pokaż też w logu bota

    def _send_all(self):
        """
        Wysyła wiadomość broadcast do WSZYSTKICH aktywnych botów.

        Każdy bot dostaje tę samą wiadomość przez stdin.
        Loguje ile botów faktycznie ją odebrało.
        """
        msg = self.ent_all.get().strip()
        if msg and self.bots:
            cnt = sum(1 for b in self.bots.values() if b.send(msg))
            self.ent_all.delete(0, tk.END)
            self._log_all(f'📢 BROADCAST ({cnt}): {msg}')

    # ══════════════════════════════════════════════════════════════════════════
    # SEKCJA 3c — LOGOWANIE (zapis do widgetów Text)
    # ══════════════════════════════════════════════════════════════════════════

    def _log_all(self, msg: str):
        """
        Dopisuje wiadomość do zbiorczego logu (prawy panel).

        Pattern Tkinter dla readonly Text:
            config(state=NORMAL)    → odblokuj do zapisu
            insert(END, tekst)      → dopisz na końcu
            see(END)                → przewiń do końca (autoscroll)
            config(state=DISABLED)  → zablokuj z powrotem
        """
        ts = datetime.now().strftime('%H:%M:%S')   # znacznik czasu HH:MM:SS
        self.txt_all.config(state=tk.NORMAL)
        self.txt_all.insert(tk.END, f'[{ts}] {msg}\n')
        self.txt_all.see(tk.END)
        self.txt_all.config(state=tk.DISABLED)

    def _append_bot_log(self, msg: str):
        """
        Dopisuje wiadomość do logu wybranego bota (środkowy panel).
        Używany zarówno przez _tick() (wiadomości przychodzące)
        jak i przez _send_one() (wiadomości wychodzące z '➜').
        """
        ts = datetime.now().strftime('%H:%M:%S')
        self.txt_bot.config(state=tk.NORMAL)
        self.txt_bot.insert(tk.END, f'[{ts}] {msg}\n')
        self.txt_bot.see(tk.END)
        self.txt_bot.config(state=tk.DISABLED)

    def _refresh_bot_log(self, idx: int):
        """
        Zastępuje zawartość logu bota pełną historią (Bot.lines[]).

        Wywoływany przy kliknięciu na bota — załadowuje całą historię
        która mogła się zebrać zanim ten bot był wybrany.
        """
        self.txt_bot.config(state=tk.NORMAL)
        self.txt_bot.delete('1.0', tk.END)   # wyczyść wszystko od linii 1, znaku 0
        for line in self.bots[idx].lines:
            self.txt_bot.insert(tk.END, line + '\n')
        self.txt_bot.see(tk.END)
        self.txt_bot.config(state=tk.DISABLED)

    def _clear_logs(self):
        """Czyści oba logi (bot i globalny) — przycisk '🗑 Wyczyść'."""
        for w in (self.txt_bot, self.txt_all):
            w.config(state=tk.NORMAL)
            w.delete('1.0', tk.END)
            w.config(state=tk.DISABLED)

    def _export(self):
        """
        Eksportuje zbiorczy log do pliku tekstowego.
        Otwiera systemowe okno dialogowe wyboru ścieżki zapisu.
        """
        fp = filedialog.asksaveasfilename(
            defaultextension='.txt',
            filetypes=[('Tekst', '*.txt'), ('Wszystkie', '*.*')]
        )
        if fp:   # użytkownik wybrał plik (nie kliknął Anuluj)
            try:
                with open(fp, 'w', encoding='utf-8') as f:
                    f.write(f'Kurnik.pl Bot Export\nData: {datetime.now()}\n')
                    f.write(f'Boty: {len(self.bots)}\n\n')
                    f.write(self.txt_all.get('1.0', tk.END))   # pobierz cały tekst
                messagebox.showinfo('OK', f'Zapisano: {fp}')
            except Exception as e:
                messagebox.showerror('Błąd', str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # SEKCJA 3d — PĘTLA AKTUALIZACJI GUI (_tick)
    # ══════════════════════════════════════════════════════════════════════════

    def _tick(self):
        """
        Pętla aktualizacji GUI — wywoływana co 150ms przez root.after().

        Tkinter nie jest thread-safe — nie można modyfikować widgetów
        z wątków w tle. Zamiast tego:
          1. Wątki (_reader) wrzucają dane do Queue (thread-safe)
          2. _tick() w głównym wątku odczytuje Queue i aktualizuje GUI

        W każdym wywołaniu:
          1. Dla każdego bota opróżnij jego kolejkę (bot.q)
          2. Obsłuż specjalne sygnały: __DEAD__, __TABLES__
          3. Dopisz zwykłe wiadomości do logów
          4. Usuń martwe boty z self.bots i przebuduj Listbox
          5. Odśwież etykiety (ikony statusu mogły się zmienić)
          6. Zaplanuj następne wywołanie za 150ms
        """
        dead_bots = []   # lista idx botów do usunięcia po iteracji
        ids = list(self.bots.keys())   # kopia kluczy (nie modyfikuj dict w trakcie iteracji)

        for idx in ids:
            bot = self.bots.get(idx)
            if not bot:
                continue  # bot mógł zniknąć między iteracjami

            # Opróżnij kolejkę tego bota (wszystkie wiadomości od ostatniego tick)
            while True:
                try:
                    msg = bot.q.get_nowait()   # pobierz bez czekania (non-blocking)
                except queue.Empty:
                    break  # kolejka pusta — przejdź do następnego bota

                # ── Sygnał: bot zakończył działanie ──────────────────────────
                if msg == '__DEAD__':
                    dead_bots.append(idx)
                    break  # reszta kolejki nieistotna

                # ── Sygnał: lista stołów gotowa ──────────────────────────────
                if msg == '__TABLES__':
                    # Odśwież GUI tylko jeśli ten bot jest aktualnie wybrany
                    if self.sel == idx:
                        self._refresh_table_list(bot.tables)
                    self._log_all(f'Bot #{idx}: 📋 {len(bot.tables)} stołów')
                    continue  # nie dopisuj '__TABLES__' do logu

                # ── Zwykła wiadomość — zapisz i wyświetl ─────────────────────
                bot.lines.append(msg)                # do historii (dla _refresh_bot_log)
                self._log_all(f'Bot #{idx}: {msg}')  # do logu globalnego
                if self.sel == idx:
                    self._append_bot_log(msg)         # do logu bota (jeśli wybrany)

        # ── Usuń martwe boty ──────────────────────────────────────────────────
        if dead_bots:
            for idx in dead_bots:
                self._log_all(f'💀 Bot #{idx} zakończył działanie')
                self.bots.pop(idx, None)   # pop z None = nie rzucaj błędu jeśli brak
            self._rebuild_bot_list()       # przebuduj Listbox bez martwych botów

        # ── Odśwież etykiety w Listbox (ikony statusu 🟢/🟡/🔴) ──────────────
        self._refresh_bot_labels()

        # Zaplanuj następne wywołanie za 150ms (nie blokuje GUI)
        self.root.after(150, self._tick)

    def _rebuild_bot_list(self):
        """
        Przebudowuje Listbox od zera na podstawie self.bots.
        Wywoływany po usunięciu martwego bota żeby nie było "dziur" w liście.
        """
        self.bot_list.delete(0, tk.END)
        for bot in self.bots.values():
            self.bot_list.insert(tk.END, bot.label)

    def _refresh_bot_labels(self):
        """
        Aktualizuje etykiety istniejących wierszy Listbox in-place.

        Zamiast przebudowywać całą listę (co deselektuje zaznaczenie),
        nadpisujemy każdy wiersz nową etykietą.

        Metoda: delete(i) + insert(i, nowa_etykieta) = zamiana wiersza.
        Używamy try/except tk.TclError na wypadek race condition
        (bot usunięty przez _rebuild_bot_list w tej samej iteracji _tick).
        """
        for i, bot in enumerate(self.bots.values()):
            try:
                self.bot_list.delete(i)           # usuń stary wiersz
                self.bot_list.insert(i, bot.label) # wstaw zaktualizowany
            except tk.TclError:
                break  # listbox zmienił rozmiar — bezpieczne wyjście


# ══════════════════════════════════════════════════════════════════════════════
# SEKCJA 4 — PUNKT WEJŚCIA
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    root = tk.Tk()         # utwórz główne okno Tkinter
    app = App(root)        # zbuduj aplikację (inicjalizuje UI i pętlę _tick)
    root.mainloop()        # uruchom pętlę zdarzeń Tkinter (blokuje do zamknięcia okna)
