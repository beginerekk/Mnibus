#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py — Kurnik.pl Bot Launcher (Qt6 GUI)
================================================
Zarządza wieloma botami kurnik-ws.py przez subprocess + stdin/stdout.

Pliki konfiguracyjne (obok launcher.py):
  whitelist.txt  — jeden nick na linię (gracze, przy których bot wychodzi)
  blacklist.json — nicki z przypisaniem do grupy i własną konfiguracją
  groups.json    — grupy z konfiguracją akcji i przypisaną pulą
  pools.json     — pule wiadomości (nazwa + lista wiadomości)

Wymagania:
  pip install PyQt6

Uruchamianie:
  python launcher.py

Jak modyfikować:
  - DEFAULT_GAME / DEFAULT_ROOM — zmień domyślną grę i pokój
  - ACTIONS — dodaj własne akcje dla blacklisty
  - Klasa Bot — logika zarządzania pojedynczym procesem
  - Klasa ConfigManager — logika konfiguracji (wczytyj/zapisuj)
  - Klasa MainWindow — cały interfejs graficzny Qt6
"""

import sys
import io
import json
import csv
import random
import queue
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

# ─── UTF-8 na Windows ─────────────────────────────────────────────────────────
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ─── Import Qt6 ───────────────────────────────────────────────────────────────
try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
        QTabWidget, QSplitter, QFrame, QSpinBox, QCheckBox, QComboBox,
        QGroupBox, QScrollArea, QSizePolicy, QDialog, QDialogButtonBox,
        QFileDialog, QMessageBox, QProgressBar, QStatusBar, QToolBar,
        QFormLayout, QGridLayout, QAbstractItemView,
    )
    from PyQt6.QtCore import (
        Qt, QTimer, QThread, pyqtSignal, QSize, QSettings,
    )
    from PyQt6.QtGui import (
        QColor, QPalette, QFont, QIcon, QTextCursor, QAction,
        QFontMetrics,
    )
except ImportError:
    print('BŁĄD: Brak PyQt6. Zainstaluj: pip install PyQt6')
    sys.exit(1)

# ─── Stałe ────────────────────────────────────────────────────────────────────

DEFAULT_GAME = 'kalambury'
DEFAULT_ROOM = '100'

CONFIG_DIR     = Path(__file__).parent
PATH_WHITELIST = CONFIG_DIR / 'whitelist.txt'
PATH_BLACKLIST = CONFIG_DIR / 'blacklist.json'
PATH_GROUPS    = CONFIG_DIR / 'groups.json'
PATH_POOLS     = CONFIG_DIR / 'pools.json'

# ─── Dostępne akcje dla blacklisty ────────────────────────────────────────────
# Klucz → (etykieta GUI, opis)
# Aby dodać nową akcję: dodaj tu wpis i obsłuż ją w MainWindow._handle_player_join()
ACTIONS = {
    'send_msg':  ('💬 Wyślij wiadomość',           'Bot wysyła losową wiadomość z przypisanej puli.'),
    'leave':     ('🚪 Wyjdź ze stołu',             'Bot wychodzi ze stołu gdy gracz wchodzi.'),
    'leave_msg': ('🚪💬 Wyjdź + wyślij wiadomość', 'Bot wysyła wiadomość, a następnie wychodzi ze stołu.'),
    'nothing':   ('🔇 Nic nie rób',                'Nick jest na liście, ale bot nie reaguje (wyciszony).'),
}
ACTION_KEYS   = list(ACTIONS.keys())
ACTION_LABELS = [v[0] for v in ACTIONS.values()]

# ─── Paleta kolorów (Catppuccin Mocha) ────────────────────────────────────────
# Aby zmienić motyw: zmodyfikuj wartości hex poniżej lub dodaj nową stałą COLORS_LIGHT.
COLORS = {
    'bg':      '#1e1e2e',   # Tło główne
    'bg2':     '#181825',   # Tło paneli
    'bg3':     '#313244',   # Tło elementów
    'bg4':     '#45475a',   # Tło aktywnych elementów
    'fg':      '#cdd6f4',   # Tekst główny
    'fg2':     '#6c7086',   # Tekst drugorzędny
    'blue':    '#89b4fa',   # Akcent niebieski
    'green':   '#a6e3a1',   # Zielony (whitelist, OK)
    'red':     '#f38ba8',   # Czerwony (blacklist, błąd)
    'yellow':  '#f9e2af',   # Żółty (ostrzeżenie)
    'purple':  '#cba6f7',   # Fioletowy (grupy)
    'teal':    '#94e2d5',   # Turkusowy (stoły)
    'surface': '#313244',   # Powierzchnia kart
    'border':  '#45475a',   # Obramowania
    'peach':   '#fab387',   # Pomarańczowy (akcje)
}


# ══════════════════════════════════════════════════════════════════════════════
# ConfigManager — zarządzanie plikami konfiguracyjnymi
# ══════════════════════════════════════════════════════════════════════════════

class ConfigManager:
    """
    Wczytuje i zapisuje konfigurację z/do plików JSON/TXT.

    Priorytety reakcji (od najwyższego):
      1. Nick ma własną akcję → użyj jej
      2. Nick należy do grupy → użyj konfiguracji grupy
      3. Brak → nic nie rób

    Pliki:
      whitelist.txt  — jeden nick na linię, linie z # są komentarzem
      blacklist.json — {nick: {display, group, action, pool}}
      groups.json    — {nazwa: {action, pool, desc}}
      pools.json     — {nazwa: [wiadomość1, wiadomość2, ...]}

    Jak modyfikować:
      Dodaj nową metodę load_*/save_* jeśli chcesz obsługiwać nowy plik.
    """

    def __init__(self):
        self.whitelist: Set[str]            = set()
        self.blacklist: Dict[str, Dict]     = {}
        self.groups:    Dict[str, Dict]     = {}
        self.pools:     Dict[str, List[str]] = {'domyślna': ['Nie gram z tobą, {user}.']}
        self._load_all()

    def _load_all(self):
        """Wczytuje wszystkie pliki konfiguracyjne."""
        self._load_whitelist()
        self._load_blacklist()
        self._load_groups()
        self._load_pools()

    # ── Wczytywanie ───────────────────────────────────────────────────────────

    def _load_whitelist(self):
        """Wczytuje whitelist.txt — jeden nick na linię, # = komentarz."""
        if PATH_WHITELIST.exists():
            try:
                for line in PATH_WHITELIST.read_text(encoding='utf-8').splitlines():
                    n = line.strip()
                    if n and not n.startswith('#'):
                        self.whitelist.add(n.lower())
            except Exception:
                pass

    def _load_blacklist(self):
        """Wczytuje blacklist.json — słownik nicków z konfiguracją."""
        if PATH_BLACKLIST.exists():
            try:
                d = json.loads(PATH_BLACKLIST.read_text(encoding='utf-8'))
                if isinstance(d, dict):
                    self.blacklist = d
            except Exception:
                pass

    def _load_groups(self):
        """Wczytuje groups.json — słownik grup z akcją i pulą."""
        if PATH_GROUPS.exists():
            try:
                d = json.loads(PATH_GROUPS.read_text(encoding='utf-8'))
                if isinstance(d, dict):
                    self.groups = d
            except Exception:
                pass

    def _load_pools(self):
        """Wczytuje pools.json — słownik pul z listami wiadomości."""
        if PATH_POOLS.exists():
            try:
                d = json.loads(PATH_POOLS.read_text(encoding='utf-8'))
                if isinstance(d, dict):
                    self.pools = d
            except Exception:
                pass

    # ── Zapis ─────────────────────────────────────────────────────────────────

    def save_whitelist(self):
        """Zapisuje whitelist.txt (nicki posortowane alfabetycznie)."""
        try:
            PATH_WHITELIST.write_text(
                '\n'.join(sorted(self.whitelist)) + '\n', encoding='utf-8'
            )
        except Exception as e:
            print(f'[ZAPIS whitelist] {e}')

    def save_blacklist(self):
        """Zapisuje blacklist.json z wcięciami (czytelny format)."""
        try:
            PATH_BLACKLIST.write_text(
                json.dumps(self.blacklist, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except Exception as e:
            print(f'[ZAPIS blacklist] {e}')

    def save_groups(self):
        """Zapisuje groups.json."""
        try:
            PATH_GROUPS.write_text(
                json.dumps(self.groups, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except Exception as e:
            print(f'[ZAPIS groups] {e}')

    def save_pools(self):
        """Zapisuje pools.json."""
        try:
            PATH_POOLS.write_text(
                json.dumps(self.pools, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except Exception as e:
            print(f'[ZAPIS pools] {e}')

    # ── Whitelist ─────────────────────────────────────────────────────────────

    def wl_add(self, name: str):
        """Dodaje nick do whitelist i zapisuje plik."""
        self.whitelist.add(name.strip().lower())
        self.save_whitelist()

    def wl_remove(self, name: str):
        """Usuwa nick z whitelist (bez błędu jeśli nie istnieje)."""
        self.whitelist.discard(name.strip().lower())
        self.save_whitelist()

    def wl_clear(self):
        """Czyści całą whitelist."""
        self.whitelist.clear()
        self.save_whitelist()

    def wl_import(self, filepath: str) -> int:
        """Importuje nicki z pliku TXT/CSV. Zwraca liczbę dodanych."""
        names  = _parse_name_file(filepath)
        before = len(self.whitelist)
        for n in names:
            self.whitelist.add(n.lower())
        self.save_whitelist()
        return len(self.whitelist) - before

    def is_whitelisted(self, name: str) -> bool:
        """Sprawdza czy nick jest na whiteliście (bez uwzględnienia wielkości liter)."""
        return name.strip().lower() in self.whitelist

    # ── Blacklist ─────────────────────────────────────────────────────────────

    def bl_add(self, name: str, group=None, action=None, pool=None):
        """Dodaje nick do blacklist z opcjonalną konfiguracją."""
        key = name.strip().lower()
        self.blacklist[key] = {
            'display': name.strip(),
            'group':   group,
            'action':  action,
            'pool':    pool,
        }
        self.save_blacklist()

    def bl_remove(self, name: str):
        """Usuwa nick z blacklist."""
        self.blacklist.pop(name.strip().lower(), None)
        self.save_blacklist()

    def bl_clear(self):
        """Czyści całą blacklist."""
        self.blacklist.clear()
        self.save_blacklist()

    def bl_import(self, filepath: str) -> int:
        """Importuje nicki z pliku TXT/CSV do blacklist."""
        names  = _parse_name_file(filepath)
        before = len(self.blacklist)
        for n in names:
            key = n.lower()
            if key not in self.blacklist:
                self.blacklist[key] = {
                    'display': n, 'group': None, 'action': None, 'pool': None
                }
        self.save_blacklist()
        return len(self.blacklist) - before

    def bl_update(self, name: str, group=None, action=None, pool=None):
        """Aktualizuje konfigurację istniejącego nicka w blacklist."""
        key = name.strip().lower()
        if key in self.blacklist:
            self.blacklist[key].update({'group': group, 'action': action, 'pool': pool})
            self.save_blacklist()

    def is_blacklisted(self, name: str) -> bool:
        """Sprawdza czy nick jest na blackliście."""
        return name.strip().lower() in self.blacklist

    def get_bl_config(self, name: str) -> Dict:
        """
        Zwraca skuteczną konfigurację wg priorytetów:
          1. Własna akcja nicka
          2. Akcja grupy do której należy
          3. Domyślnie: 'nothing'
        """
        entry  = self.blacklist.get(name.strip().lower(), {})
        action = entry.get('action')
        pool   = entry.get('pool')
        if not action:
            g = entry.get('group')
            if g and g in self.groups:
                action = self.groups[g].get('action', 'nothing')
                if not pool:
                    pool = self.groups[g].get('pool')
        return {'action': action or 'nothing', 'pool': pool}

    # ── Grupy ─────────────────────────────────────────────────────────────────

    def group_add(self, name: str, action='send_msg', pool=None, desc=''):
        """Tworzy nową grupę z akcją i pulą."""
        self.groups[name] = {'action': action, 'pool': pool, 'desc': desc}
        self.save_groups()

    def group_remove(self, name: str):
        """Usuwa grupę i odłącza przypisanych nicków (ustawiają group=None)."""
        self.groups.pop(name, None)
        for e in self.blacklist.values():
            if e.get('group') == name:
                e['group'] = None
        self.save_groups()
        self.save_blacklist()

    def group_update(self, name: str, action: str, pool=None, desc=''):
        """Aktualizuje konfigurację grupy."""
        if name in self.groups:
            self.groups[name] = {'action': action, 'pool': pool, 'desc': desc}
            self.save_groups()

    # ── Pule wiadomości ───────────────────────────────────────────────────────

    def pool_create(self, name: str):
        """Tworzy nową (pustą) pulę wiadomości."""
        if name not in self.pools:
            self.pools[name] = []
            self.save_pools()

    def pool_delete(self, name: str):
        """Usuwa pulę i odłącza ją od nicków/grup."""
        self.pools.pop(name, None)
        for e in self.blacklist.values():
            if e.get('pool') == name:
                e['pool'] = None
        for g in self.groups.values():
            if g.get('pool') == name:
                g['pool'] = None
        self.save_pools()
        self.save_blacklist()
        self.save_groups()

    def pool_add_msg(self, pool: str, msg: str):
        """Dodaje wiadomość do puli."""
        if pool in self.pools:
            self.pools[pool].append(msg)
            self.save_pools()

    def pool_remove_msg(self, pool: str, idx: int):
        """Usuwa wiadomość z puli po indeksie."""
        if pool in self.pools and 0 <= idx < len(self.pools[pool]):
            self.pools[pool].pop(idx)
            self.save_pools()

    def pool_import(self, pool: str, filepath: str) -> int:
        """Importuje wiadomości z pliku TXT/CSV do puli."""
        msgs   = _parse_name_file(filepath)
        before = len(self.pools.get(pool, []))
        if pool not in self.pools:
            self.pools[pool] = []
        self.pools[pool].extend(msgs)
        self.save_pools()
        return len(self.pools[pool]) - before

    def pool_get_random(self, pool: str, username: str) -> Optional[str]:
        """
        Zwraca losową wiadomość z puli.
        Zastępuje {user} w wiadomości nazwą gracza.
        Fallback: pula 'domyślna' jeśli wybrana jest pusta.
        """
        msgs = self.pools.get(pool, []) or self.pools.get('domyślna', [])
        if not msgs:
            return None
        return random.choice(msgs).replace('{user}', username)

    def pool_names(self) -> List[str]:
        """Zwraca listę nazw wszystkich pul."""
        return list(self.pools.keys())


def _parse_name_file(filepath: str) -> List[str]:
    """
    Wczytuje listę nicków/wiadomości z pliku TXT lub CSV.

    TXT: jeden wpis na linię, linie z # są pomijane.
    CSV: pierwsza kolumna każdego wiersza, linie z # są pomijane.

    Rzuca RuntimeError jeśli plik jest niedostępny.
    """
    result = []
    path   = Path(filepath)
    try:
        if path.suffix.lower() == '.csv':
            with open(path, newline='', encoding='utf-8-sig') as f:
                for row in csv.reader(f):
                    if row:
                        v = row[0].strip()
                        if v and not v.startswith('#'):
                            result.append(v)
        else:
            with open(path, encoding='utf-8-sig') as f:
                for line in f:
                    v = line.strip()
                    if v and not v.startswith('#'):
                        result.append(v)
    except Exception as e:
        raise RuntimeError(f'Błąd odczytu {path.name}: {e}')
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Bot — reprezentuje jeden proces kurnik-ws.py
# ══════════════════════════════════════════════════════════════════════════════

class Bot:
    """
    Zarządza jednym procesem subprocess kurnik-ws.py.

    Wątki:
      - Główny wątek: start(), stop(), send(), join_table() itd.
      - Wątek _reader: czyta stdout subprocess i wkłada do kolejki q.
      - MainWindow._tick(): odczytuje kolejkę q co 150ms i aktualizuje GUI.

    Kolejka q — specjalne tokeny:
      '__DEAD__'           — proces zakończył działanie
      '__TABLES__'         — odebrano aktualną listę stołów (bot.tables gotowe)
      '__TABLE_UPDATED__<id>' — stół bota zmienił się na <id>
      '__PLAYER_JOIN__<data>' — gracz wszedł na stół bota

    Jak modyfikować:
      - Dodaj nowe tokeny do _handle_line() i obsłuż je w MainWindow._tick().
      - Rozszerz stop() jeśli subprocess wymaga innych sygnałów zakończenia.
    """

    def __init__(self, idx: int, room: str, table: int):
        self.idx:       int   = idx
        self.room:      str   = room
        self.table:     int   = table
        self.proc:      Optional[subprocess.Popen] = None
        self.q:         queue.Queue = queue.Queue()
        self.running:   bool  = False
        self.connected: bool  = False
        self.lines:     List[str]            = []   # Historia logów bota
        self.tables:    List[Dict[str, Any]] = []   # Aktualna lista stołów
        self._stats = {'msgs': 0, 'joins': 0}       # Statystyki sesji

    def start(self, script: Path) -> bool:
        """
        Uruchamia subprocess kurnik-ws.py z odpowiednimi parametrami.

        Parametry CLI przekazywane do kurnik-ws.py:
          --game, --room, --table

        Aby przekazać dodatkowe parametry: rozszerz listę cmd.
        """
        cmd = [sys.executable, str(script),
               '--game', DEFAULT_GAME,
               '--room', self.room]
        if self.table:
            cmd += ['--table', str(self.table)]

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,   # Błędy trafiają do stdout
                stdin=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,                  # Line-buffered (konieczne dla realtime)
            )
            self.running = True
            # Wątek daemon: kończy się automatycznie gdy główny wątek się skończy
            threading.Thread(target=self._reader, daemon=True).start()
            return True
        except Exception as e:
            self.q.put(f'[BŁĄD URUCHOMIENIA] {e}')
            return False

    def _reader(self):
        """
        Wątek: czyta linie z stdout subprocess i wkłada do kolejki q.
        Działa do śmierci procesu lub ustawienia self.running=False.
        Na końcu wkłada '__DEAD__' aby poinformować GUI.
        """
        try:
            for raw in self.proc.stdout:
                if not self.running:
                    break
                line = raw.rstrip('\n')
                if line:
                    self._handle_line(line)
        except Exception:
            pass
        finally:
            self.running   = False
            self.connected = False
            self.q.put('__DEAD__')

    def _handle_line(self, line: str):
        """
        Przetwarza jedną linię stdout z kurnik-ws.py.

        Mapuje tokeny protokołu na wewnętrzne zdarzenia kolejki.
        Aby obsłużyć nowy token z kurnik-ws.py: dodaj blok if/elif tu.

        Specjalne tokeny w kolejce:
          __DEAD__           — proces zakończył działanie
          __TABLES__         — odebrano listę stołów
          __PLAYER_JOIN__X   — gracz X wszedł na stół
          __PLAYER_LEAVE__X  — gracz X opuścił stół
        """
        if line == 'CONNECTED':
            self.connected = True
            self.q.put('✅ Połączono')
            return

        if line.startswith('SESSION_OK'):
            self.q.put('🔑 Sesja OK')
            return

        if line.startswith('SESSION_WARN'):
            self.q.put('⚠️  Sesja bez kt= (niezalogowany)')
            return

        # ── Parsowanie listy stołów ──────────────────────────────────────────
        if line.startswith('TABLES_START'):
            self.tables = []
            return

        if line.startswith('TABLE '):
            parts = line[6:].split(' | ', 2)
            if parts:
                try:
                    self.tables.append({
                        'id':      int(parts[0]),
                        'params':  parts[1] if len(parts) > 1 else '',
                        'players': parts[2] if len(parts) > 2 else '',
                    })
                except ValueError:
                    pass
            return

        if line == 'TABLES_END':
            self.q.put('__TABLES__')
            return

        if line == 'TABLES_EMPTY':
            self.q.put('⚠️  Brak stołów w pokoju')
            return

        # ── Status stołu bota ────────────────────────────────────────────────
        if line.startswith('JOINED '):
            try:
                new_table = int(line[7:])
                self.table = new_table
                self._stats['joins'] += 1
                self.q.put(f'__TABLE_UPDATED__{new_table}')
            except ValueError:
                pass
            self.q.put(f'➡️  Stół {self.table}')
            return

        if line.startswith('CURRENT_TABLE '):
            self.q.put(f'📍 Aktualny stół: {line[14:]}')
            return

        # ── Wiadomości ───────────────────────────────────────────────────────
        if line.startswith('MSG '):
            self._stats['msgs'] += 1
            self.q.put(line[4:])
            return

        # ── Czat na stole ────────────────────────────────────────────────────
        if line.startswith('CHAT '):
            self._stats['msgs'] += 1
            self.q.put(f'💬 {line[5:]}')
            return

        # ── Zdarzenia graczy ─────────────────────────────────────────────────
        if line.startswith('PLAYER_JOIN '):
            self.q.put(f'__PLAYER_JOIN__{line[12:]}')
            return

        if line.startswith('PLAYER_LEAVE '):
            self.q.put(f'__PLAYER_LEAVE__{line[13:]}')
            return

        # ── Słowo do zgadnięcia (Kalambury) ──────────────────────────────────
        if line.startswith('WORD '):
            self.q.put(f'🔤 Słowo: {line[5:]}')
            return

        if line.startswith('WORD_HIDDEN '):
            self.q.put(f'❓ Ukryte: {line[12:]}')
            return

        # ── Status startu ────────────────────────────────────────────────────
        if line.startswith('BOT_START '):
            self.q.put(f'🚀 {line[10:]}')
            return

        # ── EXT — komunikat z tabeli ─────────────────────────────────────────
        if line.startswith('EXT '):
            parts = line[4:].split(maxsplit=1)
            if len(parts) == 2:
                self.q.put(f'📤 → stół {parts[0]}: {parts[1]}')
            return

        # ── Wskazówka do rysowania (Kalambury) ─────────────────────────────────
        if line.startswith('HINT '):
            self.q.put(f'🖌️  {line[5:]}')
            return

        # ── Słowo do zgadnięcia (Kalambury - zgadywanie) ───────────────────────
        if line.startswith('GUESS '):
            self.q.put(f'❓ {line[6:]}')
            return

        # ── Ruch rysunkowy (Kalambury - dane rysunku) ──────────────────────────
        if line.startswith('DRAW '):
            # Opcjonalnie: możemy ignorować surowe dane rysunku
            # lub zebrać je do automatycznego rysowania
            parts = line[5:].split(maxsplit=2)
            if len(parts) >= 2:
                draw_type = parts[0]  # 0=start, 1=move, 2=end
                # Nie wypisujemy każdego ruchu - zbyt dużo szumu
                # self.q.put(f'🖍️  Rysowanie...')
            return

        # ── Pozostałe linie ───────────────────────────────────────────────────
        self.q.put(line)

    def send(self, text: str) -> bool:
        """
        Wysyła tekst do stdin subprocess (komenda lub wiadomość chat).
        Zwraca True jeśli udało się wysłać, False jeśli proces nie żyje.
        """
        try:
            self.proc.stdin.write(text + '\n')
            self.proc.stdin.flush()
            return True
        except Exception:
            return False

    def join_table(self, tid: int) -> bool:
        """Wysyła komendę /join <tid> do bota."""
        if self.send(f'/join {tid}'):
            self.table = tid
            return True
        return False

    def leave_table(self) -> bool:
        """Wysyła /join 0 (opuszczenie stołu bez zamykania bota)."""
        if self.send('/join 0'):
            self.table = 0
            return True
        return False

    def stop(self):
        """
        Łagodnie zatrzymuje subprocess:
          1. Wysyła /quit do stdin
          2. Terminuje proces
          3. Jeśli nie odpowie w 2s — kill()
        """
        self.running = False
        if self.proc:
            try:
                self.proc.stdin.write('/quit\n')
                self.proc.stdin.flush()
            except Exception:
                pass
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

    @property
    def label(self) -> str:
        """
        Etykieta bota wyświetlana na liście.
        🟢 = połączony, 🟡 = łączy się, 🔴 = offline
        """
        if self.running and self.connected:
            icon = '🟢'
        elif self.running:
            icon = '🟡'
        else:
            icon = '🔴'
        table_str = str(self.table) if self.table else '—'
        return f'{icon} Bot #{self.idx:02d}  R:{self.room}  T:{table_str}'

    @property
    def stats_label(self) -> str:
        """Krótki opis statystyk sesji bota."""
        return f"wiad: {self._stats['msgs']}  joinów: {self._stats['joins']}"


# ══════════════════════════════════════════════════════════════════════════════
# Pomocnicze widżety Qt6
# ══════════════════════════════════════════════════════════════════════════════

def styled_button(text: str, color: str = None, min_w: int = None) -> QPushButton:
    """
    Tworzy przycisk z ciemnym motywem i opcjonalnym kolorem akcentu.

    color: hex kolor tła (np. COLORS['blue'])
    min_w: minimalna szerokość w pikselach
    """
    btn = QPushButton(text)
    bg  = color or COLORS['bg3']
    fg  = COLORS['bg'] if color else COLORS['fg']
    hover_bg = _lighten(bg, 20) if color else COLORS['bg4']
    btn.setStyleSheet(f"""
        QPushButton {{
            background: {bg};
            color: {fg};
            border: none;
            border-radius: 6px;
            padding: 6px 14px;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background: {hover_bg};
        }}
        QPushButton:pressed {{
            background: {COLORS['border']};
        }}
        QPushButton:disabled {{
            background: {COLORS['bg3']};
            color: {COLORS['fg2']};
        }}
    """)
    if min_w:
        btn.setMinimumWidth(min_w)
    return btn


def _lighten(hex_color: str, amount: int) -> str:
    """Rozjaśnia kolor hex o podaną wartość (0–255)."""
    try:
        c = QColor(hex_color)
        r = min(255, c.red()   + amount)
        g = min(255, c.green() + amount)
        b = min(255, c.blue()  + amount)
        return f'#{r:02x}{g:02x}{b:02x}'
    except Exception:
        return hex_color


def styled_label(text: str, color: str = None, bold: bool = False,
                 size: int = 13, italic: bool = False) -> QLabel:
    """Tworzy etykietę z motywem ciemnym i opcjonalnym formatowaniem."""
    lbl = QLabel(text)
    fg  = color or COLORS['fg']
    lbl.setStyleSheet(
        f'color: {fg}; font-size: {size}px;'
        + (' font-weight: bold;' if bold else '')
        + (' font-style: italic;' if italic else '')
    )
    return lbl


def styled_input(placeholder: str = '', width: int = None) -> QLineEdit:
    """Tworzy pole tekstowe z ciemnym motywem."""
    inp = QLineEdit()
    inp.setPlaceholderText(placeholder)
    inp.setStyleSheet(f"""
        QLineEdit {{
            background: {COLORS['bg3']};
            color: {COLORS['fg']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 5px 10px;
            font-size: 13px;
        }}
        QLineEdit:focus {{
            border-color: {COLORS['blue']};
        }}
    """)
    if width:
        inp.setFixedWidth(width)
    return inp


def styled_list() -> QListWidget:
    """Tworzy listę z ciemnym motywem."""
    lst = QListWidget()
    lst.setStyleSheet(f"""
        QListWidget {{
            background: {COLORS['bg2']};
            color: {COLORS['fg']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            font-family: Consolas, monospace;
            font-size: 12px;
        }}
        QListWidget::item:selected {{
            background: {COLORS['bg4']};
            color: {COLORS['fg']};
        }}
        QListWidget::item:hover {{
            background: {COLORS['bg3']};
        }}
        QScrollBar:vertical {{
            background: {COLORS['bg2']};
            width: 8px;
        }}
        QScrollBar::handle:vertical {{
            background: {COLORS['bg4']};
            border-radius: 4px;
        }}
    """)
    return lst


def styled_log() -> QTextEdit:
    """Tworzy pole tekstowe tylko do odczytu (log) z ciemnym motywem."""
    txt = QTextEdit()
    txt.setReadOnly(True)
    txt.setStyleSheet(f"""
        QTextEdit {{
            background: {COLORS['bg2']};
            color: {COLORS['teal']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            font-family: Consolas, monospace;
            font-size: 12px;
            padding: 4px;
        }}
        QScrollBar:vertical {{
            background: {COLORS['bg2']};
            width: 8px;
        }}
        QScrollBar::handle:vertical {{
            background: {COLORS['bg4']};
            border-radius: 4px;
        }}
    """)
    return txt


def styled_combo(items: List[str] = None) -> QComboBox:
    """Tworzy combobox z ciemnym motywem."""
    cb = QComboBox()
    cb.setStyleSheet(f"""
        QComboBox {{
            background: {COLORS['bg3']};
            color: {COLORS['fg']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 4px 8px;
            font-size: 13px;
        }}
        QComboBox:focus {{ border-color: {COLORS['blue']}; }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox QAbstractItemView {{
            background: {COLORS['bg3']};
            color: {COLORS['fg']};
            selection-background-color: {COLORS['bg4']};
        }}
    """)
    if items:
        cb.addItems(items)
    return cb


def group_box(title: str) -> QGroupBox:
    """Tworzy grupę (ramkę z tytułem) w ciemnym motywie."""
    gb = QGroupBox(title)
    gb.setStyleSheet(f"""
        QGroupBox {{
            color: {COLORS['blue']};
            border: 1px solid {COLORS['border']};
            border-radius: 8px;
            margin-top: 10px;
            font-weight: bold;
            font-size: 13px;
            padding-top: 8px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 6px;
            left: 10px;
        }}
    """)
    return gb


def separator() -> QFrame:
    """Tworzy poziomą linię separatora."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f'color: {COLORS["border"]};')
    return line


def append_log(log_widget: QTextEdit, text: str, color: str = None):
    """
    Dodaje wiersz do loga z znacznikiem czasu.
    Automatycznie przewija na dół.
    color: hex kolor tekstu (None = domyślny teal)
    """
    ts = datetime.now().strftime('%H:%M:%S')
    c  = color or COLORS['teal']
    log_widget.append(
        f'<span style="color:{COLORS["fg2"]}">[{ts}]</span> '
        f'<span style="color:{c}">{text}</span>'
    )
    log_widget.moveCursor(QTextCursor.MoveOperation.End)


# ══════════════════════════════════════════════════════════════════════════════
# MainWindow — główne okno aplikacji
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    """
    Główne okno aplikacji Qt6.

    Struktura paneli:
      ┌──────────────────────────────────────────────────────┐
      │  Toolbar: ustawienia + przyciski akcji               │
      ├──────────┬──────────────────┬────────────────────────┤
      │  Boty    │  Wybrany bot     │  Konfiguracja          │
      │  (lista) │  (stoły, log)    │  (zakładki)            │
      └──────────┴──────────────────┴────────────────────────┘
      │  Status bar                                          │
      └──────────────────────────────────────────────────────┘

    Jak modyfikować:
      - Dodaj nową zakładkę w _build_config_tabs().
      - Rozszerz _tick() aby obsłużyć nowe tokeny z kolejki bota.
      - Dodaj nowe przyciski w _build_toolbar().
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle('🤖 Kurnik Bot Launcher')
        self.resize(1750, 950)
        self.setMinimumSize(1200, 700)

        # Stan aplikacji
        self.bots:    Dict[int, Bot] = {}    # idx → Bot
        self.sel:     Optional[int]  = None  # Wybrany bot (idx)
        self._next_id = 1                    # Licznik ID botów
        self.cfg      = ConfigManager()
        self.script   = Path(__file__).parent / 'kurnik-ws.py'
        self.draw_image_path = None           # Ścieżka do obrazu do rysowania

        # Zastosuj globalny styl
        self._apply_global_style()
        self._build_ui()

        # Timer aktualizacji GUI — co 150ms sprawdza kolejki botów
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(150)

    def _apply_global_style(self):
        """
        Ustawia globalną paletę kolorów i arkusz stylów Qt6.

        Aby zmienić motyw: zmodyfikuj słownik COLORS na górze pliku.
        Tutaj zmień globalny stylesheet jeśli chcesz dostosować wygląd
        elementów których nie obejmuje indywidualne stylowanie.
        """
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {COLORS['bg']};
                color: {COLORS['fg']};
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
            }}
            QTabWidget::pane {{
                background: {COLORS['bg']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background: {COLORS['bg3']};
                color: {COLORS['fg2']};
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border: none;
            }}
            QTabBar::tab:selected {{
                background: {COLORS['bg4']};
                color: {COLORS['fg']};
                font-weight: bold;
            }}
            QTabBar::tab:hover {{
                background: {COLORS['bg4']};
                color: {COLORS['fg']};
            }}
            QSplitter::handle {{
                background: {COLORS['border']};
                width: 2px;
            }}
            QStatusBar {{
                background: {COLORS['bg2']};
                color: {COLORS['fg2']};
                border-top: 1px solid {COLORS['border']};
            }}
            QToolBar {{
                background: {COLORS['bg2']};
                border-bottom: 1px solid {COLORS['border']};
                spacing: 6px;
                padding: 6px;
            }}
            QScrollBar:vertical {{
                background: {COLORS['bg2']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['bg4']};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar:horizontal {{
                background: {COLORS['bg2']};
                height: 8px;
            }}
            QScrollBar::handle:horizontal {{
                background: {COLORS['bg4']};
                border-radius: 4px;
            }}
            QMessageBox {{
                background: {COLORS['bg3']};
            }}
            QMessageBox QLabel {{
                color: {COLORS['fg']};
            }}
            QFileDialog {{
                background: {COLORS['bg']};
                color: {COLORS['fg']};
            }}
        """)

    # ── Budowanie UI ──────────────────────────────────────────────────────────

    def _build_ui(self):
        """Buduje cały interfejs: toolbar + panele + statusbar."""
        self._build_toolbar()
        self._build_statusbar()

        # Centralny widget z splitterem poziomym
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter)

        # Panel 1: Lista botów
        bots_panel = self._build_bots_panel()
        splitter.addWidget(bots_panel)

        # Panel 2: Wybrany bot (stoły, log, send)
        bot_panel = self._build_bot_panel()
        splitter.addWidget(bot_panel)

        # Panel 3: Konfiguracja (zakładki)
        cfg_panel = self._build_config_panel()
        splitter.addWidget(cfg_panel)

        # Proporcje szerokości paneli (1:2:3)
        splitter.setSizes([250, 450, 650])

    def _build_toolbar(self):
        """
        Buduje pasek narzędzi na górze okna.

        Elementy:
          - Liczba botów (SpinBox)
          - Pokój (LineEdit)
          - Stół startowy (LineEdit)
          - Checkbox "Wspólny stół"
          - Przyciski: Uruchom, Stop wszystkich, Wyczyść, Eksport

        Jak dodać nowy element: dodaj widget do toolbar przez toolbar.addWidget().
        """
        toolbar = QToolBar('Sterowanie')
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(toolbar)

        def label(text):
            lbl = QLabel(f'  {text}')
            lbl.setStyleSheet(f'color: {COLORS["fg2"]}; font-size: 12px;')
            return lbl

        # Liczba botów
        toolbar.addWidget(label('Botów:'))
        self.spin_count = QSpinBox()
        self.spin_count.setRange(1, 50)
        self.spin_count.setValue(2)
        self.spin_count.setFixedWidth(60)
        self.spin_count.setStyleSheet(f"""
            QSpinBox {{
                background: {COLORS['bg3']};
                color: {COLORS['fg']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 3px 6px;
            }}
        """)
        toolbar.addWidget(self.spin_count)

        toolbar.addSeparator()

        # Pokój
        toolbar.addWidget(label('Pokój:'))
        self.inp_room = styled_input(DEFAULT_ROOM, width=60)
        self.inp_room.setText(DEFAULT_ROOM)
        toolbar.addWidget(self.inp_room)

        toolbar.addSeparator()

        # Stół startowy
        toolbar.addWidget(label('Stół startowy:'))
        self.inp_table = styled_input('0', width=60)
        self.inp_table.setText('0')
        toolbar.addWidget(self.inp_table)

        toolbar.addSeparator()

        # Checkbox wspólny stół
        self.chk_shared = QCheckBox('Wspólny stół')
        self.chk_shared.setChecked(True)
        self.chk_shared.setStyleSheet(f'color: {COLORS["fg"]}; font-size: 13px;')
        toolbar.addWidget(self.chk_shared)

        toolbar.addSeparator()

        # Checkbox automatyczne rysowanie
        self.chk_draw = QCheckBox('🖌️  Auto-rysuj')
        self.chk_draw.setChecked(False)
        self.chk_draw.setToolTip('Gdy bot wykryje, że ma rysować — automatycznie importuje obraz')
        self.chk_draw.setStyleSheet(f'color: {COLORS["fg"]}; font-size: 13px;')
        toolbar.addWidget(self.chk_draw)

        # Przycisk importu obrazu do rysowania
        btn_import_draw = styled_button('📂 Importuj obraz do rysowania', COLORS['peach'])
        btn_import_draw.setToolTip('Załaduj obraz PNG/JPG który będzie rysowany automatycznie')
        btn_import_draw.clicked.connect(self._import_draw_image)
        toolbar.addWidget(btn_import_draw)

        toolbar.addSeparator()

        # ── Przyciski akcji ───────────────────────────────────────────────────
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        btn_run  = styled_button('▶  Uruchom boty', COLORS['blue'])
        btn_stop = styled_button('⏹  Stop wszystkich')
        btn_clr  = styled_button('🗑  Wyczyść logi')
        btn_exp  = styled_button('💾  Eksport logów')

        btn_run.clicked.connect(self._run_bots)
        btn_stop.clicked.connect(self._stop_all)
        btn_clr.clicked.connect(self._clear_logs)
        btn_exp.clicked.connect(self._export_logs)

        for btn in (btn_run, btn_stop, btn_clr, btn_exp):
            toolbar.addWidget(btn)

        toolbar.addWidget(QLabel('  '))

    def _build_statusbar(self):
        """Buduje pasek stanu na dole okna (informacje o liczbie botów)."""
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.setStyleSheet(f'color: {COLORS["fg2"]}; font-size: 12px;')
        self._update_status()

    def _update_status(self):
        """Aktualizuje tekst paska stanu."""
        total    = len(self.bots)
        running  = sum(1 for b in self.bots.values() if b.running and b.connected)
        self.status.showMessage(
            f'Botów: {total}  |  Połączonych: {running}  |  '
            f'Script: {self.script.name}'
        )

    # ── Panel: Lista botów ────────────────────────────────────────────────────

    def _build_bots_panel(self) -> QWidget:
        """
        Lewy panel z listą aktywnych botów.

        Lista wyświetla etykietę każdego bota (ikona + numer + pokój + stół).
        Kliknięcie na bota zaznacza go i pokazuje szczegóły w środkowym panelu.
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = styled_label('🤖  Boty', COLORS['blue'], bold=True, size=14)
        layout.addWidget(title)

        self.bot_list = styled_list()
        self.bot_list.setFont(QFont('Consolas', 11))
        self.bot_list.currentRowChanged.connect(self._on_select_bot)
        layout.addWidget(self.bot_list)

        # Przycisk zatrzymania wybranego bota
        btn_stop_one = styled_button('⏹ Zatrzymaj wybranego', COLORS['red'])
        btn_stop_one.clicked.connect(self._stop_selected)
        layout.addWidget(btn_stop_one)

        return panel

    # ── Panel: Wybrany bot ────────────────────────────────────────────────────

    def _build_bot_panel(self) -> QWidget:
        """
        Środkowy panel szczegółów wybranego bota.

        Elementy:
          - Nagłówek z etykietą bota i statystykami
          - Lista stołów dostępnych w pokoju
          - Pola do dołączenia do stołu (ręcznie lub z listy)
          - Pole do wysyłania wiadomości przez bota
          - Log aktywności bota
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Nagłówek
        self.lbl_bot = styled_label('← Wybierz bota z listy', COLORS['fg2'], italic=True)
        layout.addWidget(self.lbl_bot)

        self.lbl_bot_stats = styled_label('', COLORS['fg2'], size=11)
        layout.addWidget(self.lbl_bot_stats)

        layout.addWidget(separator())

        # ── Stoły ────────────────────────────────────────────────────────────
        tables_gb = group_box('📋  Stoły w pokoju')
        tables_layout = QVBoxLayout(tables_gb)

        self.table_list = styled_list()
        self.table_list.setFixedHeight(120)
        self.table_list.setFont(QFont('Consolas', 10))
        tables_layout.addWidget(self.table_list)

        join_row = QHBoxLayout()
        btn_join_sel = styled_button('➡ Dołącz zaznaczony')
        btn_join_sel.clicked.connect(self._join_selected_table)
        join_row.addWidget(btn_join_sel)

        join_row.addWidget(styled_label('ID:'))
        self.inp_join_id = styled_input('np. 42', width=70)
        join_row.addWidget(self.inp_join_id)

        btn_join_manual = styled_button('➡', min_w=40)
        btn_join_manual.clicked.connect(self._join_manual)
        join_row.addWidget(btn_join_manual)

        btn_refresh_tables = styled_button('🔄', COLORS['blue'], min_w=40)
        btn_refresh_tables.setToolTip('Odśwież listę stołów')
        btn_refresh_tables.clicked.connect(self._refresh_tables_manual)
        join_row.addWidget(btn_refresh_tables)

        join_row.addStretch()
        tables_layout.addLayout(join_row)

        layout.addWidget(tables_gb)

        # ── Wyślij do bota ────────────────────────────────────────────────────
        send_gb = group_box('📨  Wyślij do wybranego bota')
        send_layout = QHBoxLayout(send_gb)
        self.inp_send_one = styled_input('wiadomość lub komenda (np. /join 5)')
        self.inp_send_one.returnPressed.connect(self._send_one)
        send_layout.addWidget(self.inp_send_one)
        btn_send_one = styled_button('Wyślij', COLORS['blue'])
        btn_send_one.clicked.connect(self._send_one)
        send_layout.addWidget(btn_send_one)
        layout.addWidget(send_gb)

        # ── Log bota ──────────────────────────────────────────────────────────
        layout.addWidget(styled_label('Log bota:', COLORS['fg2'], size=12))
        self.log_bot = styled_log()
        layout.addWidget(self.log_bot)

        return panel

    # ── Panel: Konfiguracja (zakładki) ────────────────────────────────────────

    def _build_config_panel(self) -> QWidget:
        """
        Prawy panel z zakładkami konfiguracyjnymi.

        Zakładki:
          📢 Broadcast    — wyślij do wszystkich botów
          🟢 Whitelist    — gracze przy których bot wychodzi
          🔴 Blacklist    — gracze z konfiguracją reakcji
          🏷️ Grupy        — grupy nicków ze wspólną konfiguracją
          💬 Pule         — pule wiadomości
          📋 Log globalny — historia wszystkich zdarzeń

        Jak dodać nową zakładkę:
          1. Utwórz metodę _build_tab_NAZWA(parent)
          2. Dodaj tuple do listy tabs poniżej
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        tabs_def = [
            ('📢  Broadcast',       self._build_tab_broadcast),
            ('🟢  Whitelist',       self._build_tab_whitelist),
            ('🔴  Blacklist',       self._build_tab_blacklist),
            ('🏷️  Grupy',           self._build_tab_groups),
            ('💬  Pule',            self._build_tab_pools),
            ('📋  Log globalny',    self._build_tab_log),
        ]
        for title, builder in tabs_def:
            tab = QWidget()
            tab.setStyleSheet(f'background: {COLORS["bg"]};')
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(8, 8, 8, 8)
            builder(tab_layout)
            self.tabs.addTab(tab, title)

        return panel

    # ── Zakładka: Broadcast ───────────────────────────────────────────────────

    def _build_tab_broadcast(self, layout: QVBoxLayout):
        """
        Zakładka do wysyłania wiadomości do wszystkich botów naraz.

        Broadcast: wyślij tę samą wiadomość/komendę do wszystkich aktywnych botów.
        Zmiana stołu: przenieś wszystkie boty na wskazany stół jednocześnie.
        """
        # Wyślij do wszystkich
        gb1 = group_box('Wyślij wiadomość do wszystkich botów')
        row1 = QHBoxLayout(gb1)
        self.inp_broadcast = styled_input('wiadomość lub komenda...')
        self.inp_broadcast.returnPressed.connect(self._send_all)
        row1.addWidget(self.inp_broadcast)
        btn_bc = styled_button('📢 Broadcast', COLORS['peach'])
        btn_bc.clicked.connect(self._send_all)
        row1.addWidget(btn_bc)
        layout.addWidget(gb1)

        # Przełącz stół
        gb2 = group_box('Przełącz wszystkie boty na stół')
        row2 = QHBoxLayout(gb2)
        row2.addWidget(styled_label('ID stołu:'))
        self.inp_join_all = styled_input('np. 42', width=80)
        row2.addWidget(self.inp_join_all)
        btn_ja = styled_button('➡  Przełącz wszystkie', COLORS['blue'])
        btn_ja.clicked.connect(self._join_all)
        row2.addWidget(btn_ja)
        row2.addStretch()
        layout.addWidget(gb2)

        layout.addStretch()

    # ── Zakładka: Whitelist ───────────────────────────────────────────────────

    def _build_tab_whitelist(self, layout: QVBoxLayout):
        """
        Zarządzanie whitelistą.

        Gdy gracz z whitelist wejdzie na stół — bot automatycznie wychodzi.
        Nicki są przechowywane małymi literami (case-insensitive).
        """
        layout.addWidget(styled_label(
            'Gdy gracz z whitelist wejdzie na stół — boty automatycznie wychodzą.',
            COLORS['fg2'], italic=True, size=12
        ))

        # Pasek narzędzi
        row = QHBoxLayout()
        self.inp_wl = styled_input('nick gracza...')
        self.inp_wl.returnPressed.connect(self._wl_add)
        row.addWidget(self.inp_wl)
        row.addWidget(styled_button('➕ Dodaj',   COLORS['green'], min_w=90))
        row.addWidget(styled_button('➖ Usuń',    COLORS['red'],   min_w=90))
        row.addWidget(styled_button('📂 Import',  min_w=90))
        row.addWidget(styled_button('🗑 Wyczyść', COLORS['red'],   min_w=90))
        layout.addLayout(row)

        # Podłącz przyciski
        btns = row  # zapamiętaj layout żeby pobrać widżety
        # Pobieramy przyciski przez layout — prostszy sposób:
        self._wl_btns = {
            'add':    row.itemAt(1).widget(),
            'remove': row.itemAt(2).widget(),
            'import': row.itemAt(3).widget(),
            'clear':  row.itemAt(4).widget(),
        }
        self._wl_btns['add'].clicked.connect(self._wl_add)
        self._wl_btns['remove'].clicked.connect(self._wl_remove)
        self._wl_btns['import'].clicked.connect(self._wl_import)
        self._wl_btns['clear'].clicked.connect(self._wl_clear)

        # Licznik
        self.lbl_wl_count = styled_label('0 wpisów', COLORS['fg2'], size=12)
        layout.addWidget(self.lbl_wl_count)

        # Lista
        self.wl_list = styled_list()
        self.wl_list.setFont(QFont('Consolas', 11))
        self.wl_list.setStyleSheet(self.wl_list.styleSheet().replace(
            COLORS['teal'], COLORS['green']
        ))
        layout.addWidget(self.wl_list)
        self._wl_refresh()

    # ── Zakładka: Blacklist ───────────────────────────────────────────────────

    def _build_tab_blacklist(self, layout: QVBoxLayout):
        """
        Zarządzanie blacklistą z konfiguracją reakcji.

        Każdy nick może mieć:
          - Grupę (dziedziczy akcję i pulę z grupy)
          - Własną akcję (nadpisuje grupę)
          - Własną pulę wiadomości

        Edytor po prawej stronie pojawia się po kliknięciu nicka na liście.
        """
        layout.addWidget(styled_label(
            'Konfiguracja reakcji na graczy. Priorytet: własna akcja > grupa > brak reakcji.',
            COLORS['fg2'], italic=True, size=12
        ))

        # Pasek dodawania
        row = QHBoxLayout()
        self.inp_bl = styled_input('nick gracza...')
        self.inp_bl.returnPressed.connect(self._bl_add)
        row.addWidget(self.inp_bl)
        btn_bl_add  = styled_button('➕ Dodaj',   COLORS['red'],  min_w=90)
        btn_bl_imp  = styled_button('📂 Import',              min_w=90)
        btn_bl_clr  = styled_button('🗑 Wyczyść', COLORS['red'], min_w=90)
        btn_bl_add.clicked.connect(self._bl_add)
        btn_bl_imp.clicked.connect(self._bl_import)
        btn_bl_clr.clicked.connect(self._bl_clear)
        row.addWidget(btn_bl_add)
        row.addWidget(btn_bl_imp)
        row.addWidget(btn_bl_clr)
        layout.addLayout(row)

        # Licznik
        self.lbl_bl_count = styled_label('0 wpisów', COLORS['fg2'], size=12)
        layout.addWidget(self.lbl_bl_count)

        # Splitter: lista | edytor
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Lista nicków
        self.bl_list = styled_list()
        self.bl_list.setFont(QFont('Consolas', 11))
        self.bl_list.setStyleSheet(self.bl_list.styleSheet().replace(
            COLORS['teal'], COLORS['red']
        ))
        self.bl_list.currentItemChanged.connect(self._bl_on_select)
        splitter.addWidget(self.bl_list)

        # Edytor konfiguracji
        editor = QWidget()
        editor.setStyleSheet(f'background: {COLORS["bg"]};')
        ed_layout = QVBoxLayout(editor)

        self.lbl_bl_selected = styled_label(
            '← Kliknij nick aby skonfigurować', COLORS['fg2'], italic=True
        )
        ed_layout.addWidget(self.lbl_bl_selected)

        gb_cfg = group_box('Konfiguracja reakcji')
        form = QFormLayout(gb_cfg)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cb_bl_group  = styled_combo(['(brak)'] + list(self.cfg.groups.keys()))
        self.cb_bl_action = styled_combo(['(brak — użyj grupy)'] + ACTION_LABELS)
        self.cb_bl_pool   = styled_combo(['(brak)'] + self.cfg.pool_names())

        form.addRow(styled_label('Grupa:', COLORS['fg2']),         self.cb_bl_group)
        form.addRow(styled_label('Własna akcja:', COLORS['fg2']),  self.cb_bl_action)
        form.addRow(styled_label('Własna pula:', COLORS['fg2']),   self.cb_bl_pool)

        self.lbl_bl_action_desc = styled_label('', COLORS['fg2'], italic=True, size=11)
        self.lbl_bl_action_desc.setWordWrap(True)
        form.addRow('', self.lbl_bl_action_desc)
        self.cb_bl_action.currentIndexChanged.connect(self._bl_action_desc_update)

        ed_layout.addWidget(gb_cfg)

        btn_row = QHBoxLayout()
        btn_bl_save   = styled_button('💾 Zapisz konfigurację', COLORS['blue'])
        btn_bl_remove = styled_button('🗑 Usuń nick',            COLORS['red'])
        btn_bl_save.clicked.connect(self._bl_save_config)
        btn_bl_remove.clicked.connect(self._bl_remove_selected)
        btn_row.addWidget(btn_bl_save)
        btn_row.addWidget(btn_bl_remove)
        btn_row.addStretch()
        ed_layout.addLayout(btn_row)
        ed_layout.addStretch()

        splitter.addWidget(editor)
        splitter.setSizes([200, 350])
        layout.addWidget(splitter)

        self._bl_refresh()

    # ── Zakładka: Grupy ───────────────────────────────────────────────────────

    def _build_tab_groups(self, layout: QVBoxLayout):
        """
        Zarządzanie grupami nicków.

        Grupy pozwalają przypisać wspólną konfigurację wielu nickom naraz.
        Edytor pojawia się po kliknięciu grupy na liście.
        """
        layout.addWidget(styled_label(
            'Grupy pozwalają przypisać wspólną konfigurację wielu nickom naraz.',
            COLORS['fg2'], italic=True, size=12
        ))

        # Dodawanie grupy
        row = QHBoxLayout()
        self.inp_gr_name = styled_input('nazwa grupy...')
        row.addWidget(self.inp_gr_name)
        btn_gr_add = styled_button('➕ Dodaj grupę', COLORS['purple'], min_w=120)
        btn_gr_add.clicked.connect(self._gr_add)
        row.addWidget(btn_gr_add)
        layout.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Lista grup
        self.gr_list = styled_list()
        self.gr_list.setStyleSheet(self.gr_list.styleSheet().replace(
            COLORS['teal'], COLORS['purple']
        ))
        self.gr_list.currentItemChanged.connect(self._gr_on_select)
        splitter.addWidget(self.gr_list)

        # Edytor grupy
        editor = QWidget()
        editor.setStyleSheet(f'background: {COLORS["bg"]};')
        ed_layout = QVBoxLayout(editor)

        self.lbl_gr_selected = styled_label(
            '← Kliknij grupę aby skonfigurować', COLORS['fg2'], italic=True
        )
        ed_layout.addWidget(self.lbl_gr_selected)

        gb_cfg = group_box('Konfiguracja grupy')
        form = QFormLayout(gb_cfg)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cb_gr_action = styled_combo(ACTION_LABELS)
        self.cb_gr_pool   = styled_combo(['(brak)'] + self.cfg.pool_names())
        self.inp_gr_desc  = styled_input('opis grupy...')

        form.addRow(styled_label('Akcja grupy:', COLORS['fg2']), self.cb_gr_action)
        form.addRow(styled_label('Pula:', COLORS['fg2']),        self.cb_gr_pool)
        form.addRow(styled_label('Opis:', COLORS['fg2']),        self.inp_gr_desc)
        ed_layout.addWidget(gb_cfg)

        btn_row = QHBoxLayout()
        btn_gr_save   = styled_button('💾 Zapisz grupę',  COLORS['blue'])
        btn_gr_delete = styled_button('🗑 Usuń grupę',    COLORS['red'])
        btn_gr_save.clicked.connect(self._gr_save)
        btn_gr_delete.clicked.connect(self._gr_delete)
        btn_row.addWidget(btn_gr_save)
        btn_row.addWidget(btn_gr_delete)
        btn_row.addStretch()
        ed_layout.addLayout(btn_row)
        ed_layout.addStretch()

        splitter.addWidget(editor)
        splitter.setSizes([200, 350])
        layout.addWidget(splitter)

        self._gr_refresh()

    # ── Zakładka: Pule wiadomości ─────────────────────────────────────────────

    def _build_tab_pools(self, layout: QVBoxLayout):
        """
        Zarządzanie pulami wiadomości.

        Pula to lista wiadomości, z których bot losowo wybiera jedną
        gdy wymagana jest akcja 'send_msg' lub 'leave_msg'.

        Placeholder {user} w wiadomości jest zastępowany nickiem gracza.
        """
        layout.addWidget(styled_label(
            'Pule wiadomości — bot losuje wiadomość gdy wykonuje akcję. {user} = nick gracza.',
            COLORS['fg2'], italic=True, size=12
        ))

        # Tworzenie puli
        row = QHBoxLayout()
        self.inp_pool_name = styled_input('nazwa puli...')
        row.addWidget(self.inp_pool_name)
        btn_pool_new = styled_button('➕ Utwórz pulę', COLORS['blue'])
        btn_pool_new.clicked.connect(self._pool_create)
        row.addWidget(btn_pool_new)
        layout.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Lista pul
        pool_left = QWidget()
        pool_left_layout = QVBoxLayout(pool_left)
        pool_left_layout.setContentsMargins(0, 0, 0, 0)

        pool_left_layout.addWidget(styled_label('Pule:', COLORS['fg2'], size=12))
        self.pool_list = styled_list()
        self.pool_list.setStyleSheet(self.pool_list.styleSheet().replace(
            COLORS['teal'], COLORS['peach']
        ))
        self.pool_list.currentItemChanged.connect(self._pool_on_select)
        pool_left_layout.addWidget(self.pool_list)

        btn_pool_del = styled_button('🗑 Usuń pulę', COLORS['red'])
        btn_pool_del.clicked.connect(self._pool_delete)
        pool_left_layout.addWidget(btn_pool_del)
        splitter.addWidget(pool_left)

        # Edytor wiadomości puli
        pool_right = QWidget()
        pool_right_layout = QVBoxLayout(pool_right)
        pool_right_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_pool_selected = styled_label(
            '← Kliknij pulę aby edytować', COLORS['fg2'], italic=True
        )
        pool_right_layout.addWidget(self.lbl_pool_selected)

        pool_right_layout.addWidget(styled_label('Wiadomości:', COLORS['fg2'], size=12))
        self.msg_list = styled_list()
        pool_right_layout.addWidget(self.msg_list)

        self.lbl_pool_count = styled_label('0 wiadomości', COLORS['fg2'], size=11)
        pool_right_layout.addWidget(self.lbl_pool_count)

        # Dodawanie wiadomości
        msg_row = QHBoxLayout()
        self.inp_pool_msg = styled_input('nowa wiadomość... ({user} = nick gracza)')
        self.inp_pool_msg.returnPressed.connect(self._pool_add_msg)
        msg_row.addWidget(self.inp_pool_msg)
        btn_msg_add = styled_button('➕', COLORS['green'], min_w=40)
        btn_msg_add.clicked.connect(self._pool_add_msg)
        btn_msg_del = styled_button('🗑', COLORS['red'],   min_w=40)
        btn_msg_del.clicked.connect(self._pool_remove_msg)
        btn_msg_imp = styled_button('📂 Import', min_w=80)
        btn_msg_imp.clicked.connect(self._pool_import)
        msg_row.addWidget(btn_msg_add)
        msg_row.addWidget(btn_msg_del)
        msg_row.addWidget(btn_msg_imp)
        pool_right_layout.addLayout(msg_row)

        splitter.addWidget(pool_right)
        splitter.setSizes([180, 400])
        layout.addWidget(splitter)

        self._pool_refresh()

    # ── Zakładka: Log globalny ────────────────────────────────────────────────

    def _build_tab_log(self, layout: QVBoxLayout):
        """
        Zakładka z globalnym logiem wszystkich zdarzeń ze wszystkich botów.
        """
        btn_row = QHBoxLayout()
        btn_clr = styled_button('🗑 Wyczyść log')
        btn_exp = styled_button('💾 Eksportuj log')
        btn_clr.clicked.connect(self._clear_logs)
        btn_exp.clicked.connect(self._export_logs)
        btn_row.addWidget(btn_clr)
        btn_row.addWidget(btn_exp)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.log_all = styled_log()
        self.log_all.setStyleSheet(self.log_all.styleSheet().replace(
            COLORS['teal'], COLORS['fg']
        ))
        layout.addWidget(self.log_all)

    # ══════════════════════════════════════════════════════════════════════════
    # Akcje: Boty
    # ══════════════════════════════════════════════════════════════════════════

    def _run_bots(self):
        """
        Uruchamia N nowych botów (N = spin_count).

        Jeśli 'Wspólny stół' jest zaznaczony, wszystkie boty dostają
        ten sam stół startowy. W przeciwnym razie każdy bot startuje bez stołu.

        Jak modyfikować:
          Aby uruchomić boty z różnymi pokojami lub grami, zmodyfikuj
          parametry przekazywane do Bot() i Bot.start().
        """
        if not self.script.exists():
            QMessageBox.critical(self, 'Błąd', f'Nie znaleziono: {self.script}')
            return

        count = self.spin_count.value()
        room  = self.inp_room.text().strip() or DEFAULT_ROOM
        try:
            table = int(self.inp_table.text().strip() or '0')
        except ValueError:
            table = 0
        shared = self.chk_shared.isChecked()

        for _ in range(count):
            idx  = self._next_id
            self._next_id += 1
            t    = table if shared else 0
            bot  = Bot(idx, room, t)
            if bot.start(self.script):
                self.bots[idx] = bot
                self._log(f'🤖 Bot #{idx:02d} uruchomiony (R:{room} T:{t or "—"})')
            else:
                self._log(f'❌ Bot #{idx:02d} nie uruchomiony')

        self._rebuild_bot_list()
        self._update_status()

    def _stop_all(self):
        """Zatrzymuje wszystkie aktywne boty."""
        for bot in list(self.bots.values()):
            bot.stop()
        self._log('⏹ Zatrzymano wszystkie boty')

    def _stop_selected(self):
        """Zatrzymuje wybranego bota."""
        bot = self._get_selected_bot()
        if bot:
            bot.stop()
            self._log(f'⏹ Bot #{bot.idx} zatrzymany')

    def _on_select_bot(self, row: int):
        """Obsługa zaznaczenia bota na liście — aktualizuje środkowy panel."""
        keys = list(self.bots.keys())
        if 0 <= row < len(keys):
            self.sel = keys[row]
            bot = self.bots[self.sel]
            self.lbl_bot.setText(bot.label)
            self.lbl_bot_stats.setText(bot.stats_label)
            self._refresh_table_list(bot.tables)
            self._refresh_bot_log(self.sel)
        else:
            self.sel = None
            self.lbl_bot.setText('← Wybierz bota z listy')
            self.lbl_bot_stats.setText('')

    def _get_selected_bot(self) -> Optional[Bot]:
        """Zwraca wybranego bota lub None."""
        if self.sel is not None:
            return self.bots.get(self.sel)
        return None

    def _rebuild_bot_list(self):
        """Przebudowuje listę botów od zera."""
        self.bot_list.clear()
        for bot in self.bots.values():
            item = QListWidgetItem(bot.label)
            if bot.running and bot.connected:
                item.setForeground(QColor(COLORS['green']))
            elif bot.running:
                item.setForeground(QColor(COLORS['yellow']))
            else:
                item.setForeground(QColor(COLORS['red']))
            self.bot_list.addItem(item)

    def _refresh_bot_labels(self):
        """Aktualizuje etykiety botów na liście (bez przebudowy)."""
        for i, bot in enumerate(self.bots.values()):
            item = self.bot_list.item(i)
            if item:
                item.setText(bot.label)
                if bot.running and bot.connected:
                    item.setForeground(QColor(COLORS['green']))
                elif bot.running:
                    item.setForeground(QColor(COLORS['yellow']))
                else:
                    item.setForeground(QColor(COLORS['red']))

    # ── Stoły ─────────────────────────────────────────────────────────────────

    def _refresh_table_list(self, tables: List[Dict[str, Any]]):
        """Aktualizuje listę stołów w środkowym panelu."""
        self.table_list.clear()
        for t in tables:
            players = t['players'] or '(brak graczy)'
            item = QListWidgetItem(f"#{t['id']:4d}  {players}")
            item.setData(Qt.ItemDataRole.UserRole, t['id'])
            self.table_list.addItem(item)

    def _join_selected_table(self):
        """Dołącza wybranego bota do zaznaczonego stołu z listy."""
        bot  = self._get_selected_bot()
        item = self.table_list.currentItem()
        if bot and item:
            tid = item.data(Qt.ItemDataRole.UserRole)
            bot.join_table(tid)
            self._log(f'Bot #{bot.idx}: ➡️ stół {tid}')

    def _join_manual(self):
        """Dołącza wybranego bota do stołu wpisanego ręcznie."""
        bot = self._get_selected_bot()
        if not bot:
            return
        try:
            tid = int(self.inp_join_id.text().strip())
            bot.join_table(tid)
            self.inp_join_id.clear()
            self._log(f'Bot #{bot.idx}: ➡️ stół {tid}')
        except ValueError:
            QMessageBox.warning(self, 'Błąd', 'Nieprawidłowy numer stołu')

    def _join_all(self):
        """Przełącza wszystkie boty na podany stół."""
        try:
            tid = int(self.inp_join_all.text().strip())
        except ValueError:
            QMessageBox.warning(self, 'Błąd', 'Nieprawidłowy numer stołu')
            return
        for bot in self.bots.values():
            if bot.running:
                bot.join_table(tid)
        self._log(f'📡 Broadcast join → stół {tid}')

    def _refresh_tables_manual(self):
        """Wysyła żądanie odświeżenia listy stołów do wybranego bota."""
        bot = self._get_selected_bot()
        if bot and bot.running:
            bot.send('/tables')
            self._log(f'Bot #{bot.idx}: 🔄 Żądanie listy stołów')
        else:
            QMessageBox.information(self, 'Info', 'Wybierz aktywnego bota')

    def _import_draw_image(self):
        """Importuje obraz do rysowania (PNG/JPG)."""
        fp, _ = QFileDialog.getOpenFileName(
            self, 'Importuj obraz do rysowania',
            str(CONFIG_DIR), 'Obrazy (*.png *.jpg *.jpeg *.bmp);;Wszystkie (*.*)'
        )
        if fp:
            try:
                # Zapisz ścieżkę obrazu w konfiguracji
                # Będzie używana gdy bot ma rysować
                self.draw_image_path = fp
                self._log(f'🖼️  Załadowany obraz: {Path(fp).name}')
                QMessageBox.information(self, 'OK', f'Obraz załadowany.\nPath: {fp}\n\nKiedy bot ma rysować, będzie automatycznie rysował ten obraz (jeśli Auto-rysuj jest włączony)')
            except Exception as e:
                QMessageBox.critical(self, 'Błąd', f'Nie można załadować: {e}')

    # ── Wysyłanie ──────────────────────────────────────────────────────────────

    def _send_one(self):
        """Wysyła wiadomość/komendę do wybranego bota."""
        bot  = self._get_selected_bot()
        text = self.inp_send_one.text().strip()
        if bot and text:
            bot.send(text)
            self.inp_send_one.clear()
            self._log(f'Bot #{bot.idx}: 📤 {text}')

    def _send_all(self):
        """Wysyła broadcast do wszystkich aktywnych botów."""
        text = self.inp_broadcast.text().strip()
        if not text:
            return
        sent = 0
        for bot in self.bots.values():
            if bot.running:
                bot.send(text)
                sent += 1
        self.inp_broadcast.clear()
        self._log(f'📢 Broadcast ({sent} botów): {text}')

    # ══════════════════════════════════════════════════════════════════════════
    # Akcje: Whitelist
    # ══════════════════════════════════════════════════════════════════════════

    def _wl_add(self):
        name = self.inp_wl.text().strip()
        if not name:
            return
        self.cfg.wl_add(name)
        self.inp_wl.clear()
        self._wl_refresh()
        self._log(f'🟢 WL: dodano {name}')

    def _wl_remove(self):
        item = self.wl_list.currentItem()
        if item:
            name = item.text()
            self.cfg.wl_remove(name)
            self._wl_refresh()
            self._log(f'🟢 WL: usunięto {name}')

    def _wl_import(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, 'Importuj whitelist',
            str(CONFIG_DIR), 'TXT / CSV (*.txt *.csv);;Wszystkie (*.*)'
        )
        if fp:
            try:
                added = self.cfg.wl_import(fp)
                self._wl_refresh()
                self._log(f'🟢 WL: +{added} z {Path(fp).name}')
            except RuntimeError as e:
                QMessageBox.critical(self, 'Błąd', str(e))

    def _wl_clear(self):
        if QMessageBox.question(
            self, 'Potwierdź', 'Wyczyścić całą whitelist?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.cfg.wl_clear()
            self._wl_refresh()
            self._log('🟢 WL: wyczyszczono')

    def _wl_refresh(self):
        """Odświeża listę whitelist w GUI."""
        self.wl_list.clear()
        for name in sorted(self.cfg.whitelist):
            item = QListWidgetItem(name)
            item.setForeground(QColor(COLORS['green']))
            self.wl_list.addItem(item)
        self.lbl_wl_count.setText(f'{len(self.cfg.whitelist)} wpisów')

    # ══════════════════════════════════════════════════════════════════════════
    # Akcje: Blacklist
    # ══════════════════════════════════════════════════════════════════════════

    def _bl_add(self):
        name = self.inp_bl.text().strip()
        if not name:
            return
        self.cfg.bl_add(name)
        self.inp_bl.clear()
        self._bl_refresh()
        self._log(f'🔴 BL: dodano {name}')

    def _bl_remove_selected(self):
        item = self.bl_list.currentItem()
        if item:
            name = item.data(Qt.ItemDataRole.UserRole) or item.text()
            self.cfg.bl_remove(name)
            self._bl_refresh()
            self._log(f'🔴 BL: usunięto {name}')

    def _bl_import(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, 'Importuj blacklist',
            str(CONFIG_DIR), 'TXT / CSV (*.txt *.csv);;Wszystkie (*.*)'
        )
        if fp:
            try:
                added = self.cfg.bl_import(fp)
                self._bl_refresh()
                self._log(f'🔴 BL: +{added} z {Path(fp).name}')
            except RuntimeError as e:
                QMessageBox.critical(self, 'Błąd', str(e))

    def _bl_clear(self):
        if QMessageBox.question(
            self, 'Potwierdź', 'Wyczyścić całą blacklist?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.cfg.bl_clear()
            self._bl_refresh()
            self._log('🔴 BL: wyczyszczono')

    def _bl_on_select(self, current, previous):
        """Ładuje konfigurację wybranego nicka do edytora."""
        if not current:
            return
        name = current.data(Qt.ItemDataRole.UserRole) or current.text()
        entry = self.cfg.blacklist.get(name.lower(), {})

        # Załaduj grupę
        group = entry.get('group') or ''
        idx   = self.cb_bl_group.findText(group) if group else 0
        self.cb_bl_group.setCurrentIndex(max(0, idx))

        # Załaduj akcję
        action = entry.get('action')
        if action and action in ACTION_KEYS:
            self.cb_bl_action.setCurrentIndex(ACTION_KEYS.index(action) + 1)
        else:
            self.cb_bl_action.setCurrentIndex(0)

        # Załaduj pulę
        pool = entry.get('pool') or ''
        pidx = self.cb_bl_pool.findText(pool) if pool else 0
        self.cb_bl_pool.setCurrentIndex(max(0, pidx))

        self.lbl_bl_selected.setText(f'Edytujesz: {name}')
        self.lbl_bl_selected.setStyleSheet(f'color: {COLORS["purple"]}; font-weight: bold;')

    def _bl_save_config(self):
        """Zapisuje konfigurację wybranego nicka z edytora."""
        item = self.bl_list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole) or item.text()

        group_val  = self.cb_bl_group.currentText()
        action_idx = self.cb_bl_action.currentIndex()
        pool_val   = self.cb_bl_pool.currentText()

        group  = None if group_val == '(brak)'             else group_val
        action = None if action_idx == 0                   else ACTION_KEYS[action_idx - 1]
        pool   = None if pool_val in ('(brak)', '')        else pool_val

        self.cfg.bl_update(name, group=group, action=action, pool=pool)
        self._bl_refresh()
        self._log(f'🔴 BL: zapisano konfigurację dla {name}')

    def _bl_action_desc_update(self):
        """Aktualizuje opis akcji pod comboboxem."""
        idx = self.cb_bl_action.currentIndex()
        if idx == 0:
            self.lbl_bl_action_desc.setText('')
        else:
            key  = ACTION_KEYS[idx - 1]
            desc = ACTIONS[key][1]
            self.lbl_bl_action_desc.setText(desc)

    def _bl_refresh(self):
        """Odświeża listę blacklist w GUI."""
        self.bl_list.clear()
        for key, entry in self.cfg.blacklist.items():
            display = entry.get('display', key)
            action  = entry.get('action') or entry.get('group') or '—'
            text    = f'{display}  [{action}]'
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setForeground(QColor(COLORS['red']))
            self.bl_list.addItem(item)
        self.lbl_bl_count.setText(f'{len(self.cfg.blacklist)} wpisów')
        # Odśwież combobox grup
        self._refresh_combos()

    def _refresh_combos(self):
        """Odświeża listy rozwijane (grupy, pule) we wszystkich zakładkach."""
        groups = ['(brak)'] + list(self.cfg.groups.keys())
        pools  = ['(brak)'] + self.cfg.pool_names()

        for cb, items in [(self.cb_bl_group, groups), (self.cb_bl_pool, pools)]:
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(items)
            idx = cb.findText(cur)
            cb.setCurrentIndex(max(0, idx))
            cb.blockSignals(False)

        # Grupy w edytorze grup
        pools_only = ['(brak)'] + self.cfg.pool_names()
        for cb in [self.cb_bl_pool]:
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(pools_only)
            idx = cb.findText(cur)
            cb.setCurrentIndex(max(0, idx))
            cb.blockSignals(False)

    # ══════════════════════════════════════════════════════════════════════════
    # Akcje: Grupy
    # ══════════════════════════════════════════════════════════════════════════

    def _gr_add(self):
        name = self.inp_gr_name.text().strip()
        if not name:
            return
        if name in self.cfg.groups:
            QMessageBox.warning(self, 'Grupy', f'Grupa "{name}" już istnieje')
            return
        self.cfg.group_add(name)
        self.inp_gr_name.clear()
        self._gr_refresh()
        self._refresh_combos()
        self._log(f'🏷️ Grupy: dodano "{name}"')

    def _gr_on_select(self, current, previous):
        """Ładuje konfigurację wybranej grupy do edytora."""
        if not current:
            return
        name  = current.text().split('  [')[0]
        entry = self.cfg.groups.get(name, {})

        action = entry.get('action', 'send_msg')
        if action in ACTION_KEYS:
            self.cb_gr_action.setCurrentIndex(ACTION_KEYS.index(action))

        pool = entry.get('pool') or ''
        pidx = self.cb_gr_pool.findText(pool) if pool else 0
        self.cb_gr_pool.setCurrentIndex(max(0, pidx))

        self.inp_gr_desc.setText(entry.get('desc', ''))
        self.lbl_gr_selected.setText(f'Edytujesz grupę: {name}')
        self.lbl_gr_selected.setStyleSheet(f'color: {COLORS["purple"]}; font-weight: bold;')

    def _gr_save(self):
        """Zapisuje konfigurację wybranej grupy."""
        item = self.gr_list.currentItem()
        if not item:
            return
        name       = item.text().split('  [')[0]
        action_idx = self.cb_gr_action.currentIndex()
        action     = ACTION_KEYS[action_idx] if 0 <= action_idx < len(ACTION_KEYS) else 'nothing'
        pool_val   = self.cb_gr_pool.currentText()
        pool       = None if pool_val == '(brak)' else pool_val
        desc       = self.inp_gr_desc.text().strip()

        self.cfg.group_update(name, action=action, pool=pool, desc=desc)
        self._gr_refresh()
        self._log(f'🏷️ Grupy: zapisano "{name}"')

    def _gr_delete(self):
        """Usuwa wybraną grupę i odłącza przypisane nicki."""
        item = self.gr_list.currentItem()
        if not item:
            return
        name = item.text().split('  [')[0]
        if QMessageBox.question(
            self, 'Potwierdź', f'Usunąć grupę "{name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.cfg.group_remove(name)
            self._gr_refresh()
            self._bl_refresh()
            self._refresh_combos()
            self._log(f'🏷️ Grupy: usunięto "{name}"')

    def _gr_refresh(self):
        """Odświeża listę grup w GUI."""
        self.gr_list.clear()
        for name, entry in self.cfg.groups.items():
            action = entry.get('action', '—')
            item = QListWidgetItem(f'{name}  [{action}]')
            item.setForeground(QColor(COLORS['purple']))
            self.gr_list.addItem(item)

    # ══════════════════════════════════════════════════════════════════════════
    # Akcje: Pule wiadomości
    # ══════════════════════════════════════════════════════════════════════════

    def _selected_pool_name(self) -> Optional[str]:
        """Zwraca nazwę aktualnie wybranej puli lub None."""
        item = self.pool_list.currentItem()
        if item:
            return item.text().rsplit('  (', 1)[0]
        return None

    def _pool_create(self):
        name = self.inp_pool_name.text().strip()
        if not name:
            return
        if name in self.cfg.pools:
            QMessageBox.warning(self, 'Pule', f'Pula "{name}" już istnieje')
            return
        self.cfg.pool_create(name)
        self.inp_pool_name.clear()
        self._pool_refresh()
        self._refresh_combos()
        self._log(f'💬 Pule: utworzono "{name}"')

    def _pool_delete(self):
        name = self._selected_pool_name()
        if not name:
            return
        if QMessageBox.question(
            self, 'Potwierdź', f'Usunąć pulę "{name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.cfg.pool_delete(name)
            self._pool_refresh()
            self._refresh_combos()
            self._gr_refresh()
            self._bl_refresh()
            self._log(f'💬 Pule: usunięto "{name}"')

    def _pool_on_select(self, current, previous):
        """Ładuje wiadomości wybranej puli do listy."""
        if not current:
            return
        name = current.text().rsplit('  (', 1)[0]
        self.lbl_pool_selected.setText(f'Edytujesz pulę: {name}')
        self.lbl_pool_selected.setStyleSheet(f'color: {COLORS["peach"]}; font-weight: bold;')
        self._pool_refresh_msgs(name)

    def _pool_add_msg(self):
        name = self._selected_pool_name()
        if not name:
            QMessageBox.information(self, 'Info', 'Wybierz pulę z listy')
            return
        msg = self.inp_pool_msg.text().strip()
        if not msg:
            return
        self.cfg.pool_add_msg(name, msg)
        self.inp_pool_msg.clear()
        self._pool_refresh_msgs(name)
        self._pool_refresh()
        self._log(f'💬 Pule: dodano wiadomość do "{name}"')

    def _pool_remove_msg(self):
        name = self._selected_pool_name()
        if not name:
            return
        item = self.msg_list.currentItem()
        if item:
            idx = self.msg_list.row(item)
            self.cfg.pool_remove_msg(name, idx)
            self._pool_refresh_msgs(name)
            self._pool_refresh()

    def _pool_import(self):
        name = self._selected_pool_name()
        if not name:
            QMessageBox.information(self, 'Info', 'Wybierz pulę z listy')
            return
        fp, _ = QFileDialog.getOpenFileName(
            self, f'Importuj wiadomości do puli "{name}"',
            str(CONFIG_DIR), 'TXT / CSV (*.txt *.csv);;Wszystkie (*.*)'
        )
        if fp:
            try:
                added = self.cfg.pool_import(name, fp)
                self._pool_refresh_msgs(name)
                self._pool_refresh()
                self._log(f'💬 Pule: +{added} wiadomości w "{name}"')
            except RuntimeError as e:
                QMessageBox.critical(self, 'Błąd', str(e))

    def _pool_refresh(self):
        """Odświeża listę pul."""
        cur = self._selected_pool_name()
        self.pool_list.clear()
        for name in self.cfg.pool_names():
            count = len(self.cfg.pools[name])
            item  = QListWidgetItem(f'{name}  ({count})')
            item.setForeground(QColor(COLORS['peach']))
            self.pool_list.addItem(item)
        if cur:
            items = self.pool_list.findItems(cur, Qt.MatchFlag.MatchStartsWith)
            if items:
                self.pool_list.setCurrentItem(items[0])

    def _pool_refresh_msgs(self, pool_name: str):
        """Odświeża listę wiadomości wybranej puli."""
        self.msg_list.clear()
        msgs = self.cfg.pools.get(pool_name, [])
        for i, msg in enumerate(msgs):
            item = QListWidgetItem(f'{i+1:3}. {msg}')
            self.msg_list.addItem(item)
        self.lbl_pool_count.setText(f'{len(msgs)} wiadomości')

    # ══════════════════════════════════════════════════════════════════════════
    # Obsługa zdarzeń graczy
    # ══════════════════════════════════════════════════════════════════════════

    def _handle_player_join(self, bot: Bot, payload: str):
        """
        Reaguje na wejście gracza na stół bota.

        payload format: '<table_id> <nick>'

        Priorytety:
          1. Nick na whitelist → bot wychodzi ze stołu
          2. Nick na blacklist → wykonaj skonfigurowaną akcję
          3. Brak → nic

        Jak modyfikować:
          Dodaj nowy blok elif dla nowych akcji zdefiniowanych w ACTIONS.
        """
        parts = payload.split(maxsplit=1)
        if len(parts) < 2:
            return
        try:
            table_id = int(parts[0])
        except ValueError:
            return
        username = parts[1].strip()

        if table_id != bot.table:
            return  # Zdarzenie dotyczy innego stołu

        # ── Whitelist (najwyższy priorytet) ───────────────────────────────────
        if self.cfg.is_whitelisted(username):
            bot.leave_table()
            self._log(
                f'🟢 WHITELIST: <b style="color:{COLORS["green"]}">{username}</b>'
                f' → Bot #{bot.idx} wychodzi ze stołu {table_id}',
                color=COLORS['green']
            )
            return

        # ── Blacklist ─────────────────────────────────────────────────────────
        if self.cfg.is_blacklisted(username):
            conf   = self.cfg.get_bl_config(username)
            action = conf['action']
            pool   = conf['pool'] or 'domyślna'
            msg    = self.cfg.pool_get_random(pool, username)

            if action == 'send_msg':
                if msg:
                    bot.send(msg)
                self._log(
                    f'🔴 BLACKLIST: {username} → Bot #{bot.idx} wysyła wiadomość',
                    color=COLORS['red']
                )

            elif action == 'leave':
                bot.leave_table()
                self._log(
                    f'🔴 BLACKLIST: {username} → Bot #{bot.idx} wychodzi ze stołu',
                    color=COLORS['red']
                )

            elif action == 'leave_msg':
                if msg:
                    bot.send(msg)
                bot.leave_table()
                self._log(
                    f'🔴 BLACKLIST: {username} → Bot #{bot.idx} wyśle wiadomość i wychodzi',
                    color=COLORS['red']
                )

            elif action == 'nothing':
                self._log(
                    f'🔴 BLACKLIST: {username} — brak reakcji (wyciszony)',
                    color=COLORS['fg2']
                )

    # ══════════════════════════════════════════════════════════════════════════
    # Logowanie
    # ══════════════════════════════════════════════════════════════════════════

    def _log(self, msg: str, color: str = None):
        """Dodaje wpis do globalnego logu (zakładka 'Log globalny')."""
        append_log(self.log_all, msg, color)

    def _append_bot_log(self, msg: str):
        """Dodaje wpis do logu wybranego bota (środkowy panel)."""
        append_log(self.log_bot, msg)

    def _refresh_bot_log(self, idx: int):
        """Ładuje całą historię wybranego bota do logu."""
        self.log_bot.clear()
        bot = self.bots.get(idx)
        if bot:
            for line in bot.lines[-500:]:  # Max 500 ostatnich wierszy
                append_log(self.log_bot, line)

    def _clear_logs(self):
        """Czyści oba logi."""
        self.log_all.clear()
        self.log_bot.clear()

    def _export_logs(self):
        """Eksportuje globalny log do pliku TXT."""
        fp, _ = QFileDialog.getSaveFileName(
            self, 'Eksportuj log',
            str(CONFIG_DIR / 'kurnik_log.txt'),
            'Tekst (*.txt);;Wszystkie (*.*)'
        )
        if fp:
            try:
                content = self.log_all.toPlainText()
                with open(fp, 'w', encoding='utf-8') as f:
                    f.write(f'Kurnik.pl Bot Export\nData: {datetime.now()}\n\n')
                    f.write(content)
                QMessageBox.information(self, 'OK', f'Zapisano: {fp}')
            except Exception as e:
                QMessageBox.critical(self, 'Błąd', str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # Pętla aktualizacji GUI — wywoływana co 150ms przez QTimer
    # ══════════════════════════════════════════════════════════════════════════

    def _tick(self):
        """
        Główna pętla aktualizacji GUI.

        Co 150ms:
          1. Dla każdego bota pobiera wszystkie wpisy z kolejki q.
          2. Obsługuje specjalne tokeny (__DEAD__, __TABLES__, __PLAYER_JOIN__).
          3. Zwykłe wiadomości dodaje do logów i historii bota.
          4. Odświeża etykiety botów na liście.
          5. Aktualizuje pasek stanu.

        Jak dodać nowy token:
          Dodaj blok `elif msg.startswith('__NOWY_TOKEN__'):` i obsłuż akcję.
        """
        changed = False

        for idx in list(self.bots.keys()):
            bot = self.bots.get(idx)
            if not bot:
                continue

            while True:
                try:
                    msg = bot.q.get_nowait()
                except queue.Empty:
                    break

                # ── Bot zakończył działanie ───────────────────────────────────
                if msg == '__DEAD__':
                    self._log(f'💀 Bot #{idx} zakończył działanie', color=COLORS['red'])
                    self.bots.pop(idx, None)
                    self._rebuild_bot_list()
                    changed = True
                    if self.sel == idx:
                        self.sel = None
                    break

                # ── Odebrano listę stołów ─────────────────────────────────────
                if msg == '__TABLES__':
                    old_table = bot.table
                    if self.sel == idx:
                        self._refresh_table_list(bot.tables)
                    self._log(f'Bot #{idx}: 📋 {len(bot.tables)} stołów (current table: {old_table})')
                    # Nie ustawiaj changed=True dla samej listy stołów
                    continue

                # ── Stół bota zmienił się ─────────────────────────────────────
                if msg.startswith('__TABLE_UPDATED__'):
                    try:
                        table_id = int(msg[17:])
                        old_table = bot.table
                        # Tylko zmień tabelę jeśli faktycznie się zmieniła
                        if bot.table != table_id:
                            self._log(f'DEBUG: Bot #{idx} zmiana stołu {old_table} → {table_id}', color=COLORS['yellow'])
                            bot.table = table_id
                            changed = True
                        else:
                            self._log(f'DEBUG: Bot #{idx} __TABLE_UPDATED__{table_id} ale już na tym stole', color=COLORS['fg2'])
                    except ValueError:
                        pass
                    continue

                # ── Gracz wszedł na stół ──────────────────────────────────────
                if msg.startswith('__PLAYER_JOIN__'):
                    self._handle_player_join(bot, msg[15:])
                    continue

                # ── Gracz opuścił stół ────────────────────────────────────────
                if msg.startswith('__PLAYER_LEAVE__'):
                    parts = msg[16:].split(maxsplit=1)
                    if len(parts) == 2:
                        self._log(
                            f'Bot #{idx}: 🚪 {parts[1]} opuścił stół {parts[0]}',
                            color=COLORS['fg2']
                        )
                    continue

                # ── Zwykła wiadomość ──────────────────────────────────────────
                bot.lines.append(msg)
                if len(bot.lines) > 1000:
                    bot.lines = bot.lines[-500:]  # Przytnij historię

                self._log(f'Bot #{idx}: {msg}')
                if self.sel == idx:
                    self._append_bot_log(msg)

        # Odśwież etykiety i status
        self._refresh_bot_labels()
        if changed:
            self._update_status()
        # (status jest odświeżany co kilka sekund przez _update_status_tick)

    def closeEvent(self, event):
        """Przy zamknięciu okna zatrzymuje wszystkie boty."""
        self._stop_all()
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
# Punkt wejścia
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """
    Uruchamia aplikację Qt6.

    Modyfikacja:
      Aby zmienić ikonę aplikacji: odkomentuj setWindowIcon() i podaj ścieżkę.
      Aby dodać obsługę argumentów CLI: użyj argparse przed QApplication.
    """
    app = QApplication(sys.argv)
    app.setApplicationName('Kurnik Bot Launcher')
    app.setOrganizationName('KurnikBot')
    # app.setWindowIcon(QIcon('icon.png'))  # Opcjonalna ikona

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
