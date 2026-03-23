#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py — Kurnik.pl Bot Launcher
Zarządza botami, white/blacklistą, grupami i pulami wiadomości.

Pliki konfiguracyjne (obok launcher.py):
  whitelist.txt  — jeden nick na linię
  blacklist.json — nicki z przypisaniem do grupy i własną konfiguracją
  groups.json    — grupy z konfiguracją akcji i przypisaną pulą
  pools.json     — pule wiadomości (nazwa + lista wiadomości)
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import subprocess, threading, queue, sys, io, csv, json, random
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

DEFAULT_GAME = 'kalambury'
DEFAULT_ROOM = '100'

CONFIG_DIR     = Path(__file__).parent
PATH_WHITELIST = CONFIG_DIR / 'whitelist.txt'
PATH_BLACKLIST = CONFIG_DIR / 'blacklist.json'
PATH_GROUPS    = CONFIG_DIR / 'groups.json'
PATH_POOLS     = CONFIG_DIR / 'pools.json'

# Dostępne akcje dla blacklisty: klucz → (etykieta GUI, opis)
ACTIONS = {
    'send_msg':  ('💬 Wyślij wiadomość',           'Bot wysyła losową wiadomość z przypisanej puli.'),
    'leave':     ('🚪 Wyjdź ze stołu',             'Bot wychodzi ze stołu gdy gracz wchodzi.'),
    'leave_msg': ('🚪💬 Wyjdź + wyślij wiadomość', 'Bot wysyła wiadomość, a następnie wychodzi ze stołu.'),
    'nothing':   ('🔇 Nic nie rób',                'Nick jest na liście, ale bot nie reaguje (wyciszony).'),
}
ACTION_KEYS   = list(ACTIONS.keys())
ACTION_LABELS = [v[0] for v in ACTIONS.values()]


# ══════════════════════════════════════════════════════════════════════════════
# ConfigManager
# ══════════════════════════════════════════════════════════════════════════════

class ConfigManager:
    """
    Przechowuje i zarządza konfiguracją.
    Każda zmiana automatycznie zapisuje odpowiedni plik.

    Priorytety reakcji (od najwyższego):
      1. Nick ma własną akcję → użyj jej
      2. Nick należy do grupy → użyj konfiguracji grupy
      3. Brak → nic nie rób
    """

    def __init__(self):
        self.whitelist: Set[str]       = set()
        self.blacklist: Dict[str, Dict] = {}
        self.groups:    Dict[str, Dict] = {}
        self.pools:     Dict[str, List[str]] = {'domyślna': ['Nie gram z tobą, {user}.']}
        self._load_all()

    def _load_all(self):
        self._load_whitelist()
        self._load_blacklist()
        self._load_groups()
        self._load_pools()

    def _load_whitelist(self):
        if PATH_WHITELIST.exists():
            try:
                for line in PATH_WHITELIST.read_text(encoding='utf-8').splitlines():
                    n = line.strip()
                    if n and not n.startswith('#'):
                        self.whitelist.add(n.lower())
            except Exception:
                pass

    def _load_blacklist(self):
        if PATH_BLACKLIST.exists():
            try:
                d = json.loads(PATH_BLACKLIST.read_text(encoding='utf-8'))
                if isinstance(d, dict):
                    self.blacklist = d
            except Exception:
                pass

    def _load_groups(self):
        if PATH_GROUPS.exists():
            try:
                d = json.loads(PATH_GROUPS.read_text(encoding='utf-8'))
                if isinstance(d, dict):
                    self.groups = d
            except Exception:
                pass

    def _load_pools(self):
        if PATH_POOLS.exists():
            try:
                d = json.loads(PATH_POOLS.read_text(encoding='utf-8'))
                if isinstance(d, dict):
                    self.pools = d
            except Exception:
                pass

    # ── Zapis ─────────────────────────────────────────────────────────────────

    def save_whitelist(self):
        try:
            PATH_WHITELIST.write_text('\n'.join(sorted(self.whitelist)) + '\n', encoding='utf-8')
        except Exception as e:
            print(f'[ZAPIS whitelist] {e}')

    def save_blacklist(self):
        try:
            PATH_BLACKLIST.write_text(json.dumps(self.blacklist, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            print(f'[ZAPIS blacklist] {e}')

    def save_groups(self):
        try:
            PATH_GROUPS.write_text(json.dumps(self.groups, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            print(f'[ZAPIS groups] {e}')

    def save_pools(self):
        try:
            PATH_POOLS.write_text(json.dumps(self.pools, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            print(f'[ZAPIS pools] {e}')

    # ── Whitelist ──────────────────────────────────────────────────────────────

    def wl_add(self, name: str):
        self.whitelist.add(name.strip().lower()); self.save_whitelist()

    def wl_remove(self, name: str):
        self.whitelist.discard(name.strip().lower()); self.save_whitelist()

    def wl_clear(self):
        self.whitelist.clear(); self.save_whitelist()

    def wl_import(self, filepath: str) -> int:
        names = _parse_name_file(filepath)
        before = len(self.whitelist)
        for n in names:
            self.whitelist.add(n.lower())
        self.save_whitelist()
        return len(self.whitelist) - before

    def is_whitelisted(self, name: str) -> bool:
        return name.strip().lower() in self.whitelist

    # ── Blacklist ──────────────────────────────────────────────────────────────

    def bl_add(self, name: str, group=None, action=None, pool=None):
        key = name.strip().lower()
        self.blacklist[key] = {'display': name.strip(), 'group': group, 'action': action, 'pool': pool}
        self.save_blacklist()

    def bl_remove(self, name: str):
        self.blacklist.pop(name.strip().lower(), None); self.save_blacklist()

    def bl_clear(self):
        self.blacklist.clear(); self.save_blacklist()

    def bl_import(self, filepath: str) -> int:
        names = _parse_name_file(filepath)
        before = len(self.blacklist)
        for n in names:
            key = n.lower()
            if key not in self.blacklist:
                self.blacklist[key] = {'display': n, 'group': None, 'action': None, 'pool': None}
        self.save_blacklist()
        return len(self.blacklist) - before

    def bl_update(self, name: str, group=None, action=None, pool=None):
        key = name.strip().lower()
        if key in self.blacklist:
            self.blacklist[key].update({'group': group, 'action': action, 'pool': pool})
            self.save_blacklist()

    def is_blacklisted(self, name: str) -> bool:
        return name.strip().lower() in self.blacklist

    def get_bl_config(self, name: str) -> Dict:
        """Zwraca skuteczną konfigurację wg priorytetów (nick > grupa > brak)."""
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

    # ── Groups ─────────────────────────────────────────────────────────────────

    def group_add(self, name: str, action='send_msg', pool=None, desc=''):
        self.groups[name] = {'action': action, 'pool': pool, 'desc': desc}; self.save_groups()

    def group_remove(self, name: str):
        self.groups.pop(name, None)
        for e in self.blacklist.values():
            if e.get('group') == name:
                e['group'] = None
        self.save_groups(); self.save_blacklist()

    def group_update(self, name: str, action: str, pool=None, desc=''):
        if name in self.groups:
            self.groups[name] = {'action': action, 'pool': pool, 'desc': desc}
            self.save_groups()

    # ── Pools ──────────────────────────────────────────────────────────────────

    def pool_create(self, name: str):
        if name not in self.pools:
            self.pools[name] = []; self.save_pools()

    def pool_delete(self, name: str):
        self.pools.pop(name, None)
        for e in self.blacklist.values():
            if e.get('pool') == name:
                e['pool'] = None
        for g in self.groups.values():
            if g.get('pool') == name:
                g['pool'] = None
        self.save_pools(); self.save_blacklist(); self.save_groups()

    def pool_add_msg(self, pool: str, msg: str):
        if pool in self.pools:
            self.pools[pool].append(msg); self.save_pools()

    def pool_remove_msg(self, pool: str, idx: int):
        if pool in self.pools and 0 <= idx < len(self.pools[pool]):
            self.pools[pool].pop(idx); self.save_pools()

    def pool_import(self, pool: str, filepath: str) -> int:
        msgs = _parse_name_file(filepath)
        before = len(self.pools.get(pool, []))
        if pool not in self.pools:
            self.pools[pool] = []
        self.pools[pool].extend(msgs)
        self.save_pools()
        return len(self.pools[pool]) - before

    def pool_get_random(self, pool: str, username: str) -> Optional[str]:
        msgs = self.pools.get(pool, []) or self.pools.get('domyślna', [])
        if not msgs:
            return None
        return random.choice(msgs).replace('{user}', username)

    def pool_names(self) -> List[str]:
        return list(self.pools.keys())


def _parse_name_file(filepath: str) -> List[str]:
    result = []
    path = Path(filepath)
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
# Bot
# ══════════════════════════════════════════════════════════════════════════════

class Bot:
    def __init__(self, idx: int, room: str, table: int):
        self.idx = idx; self.room = room; self.table = table
        self.proc: Optional[subprocess.Popen] = None
        self.q: queue.Queue = queue.Queue()
        self.running = False; self.connected = False
        self.lines: List[str] = []
        self.tables: List[Dict[str, Any]] = []

    def start(self, script: Path) -> bool:
        cmd = [sys.executable, str(script), '--game', DEFAULT_GAME, '--room', self.room]
        if self.table:
            cmd += ['--table', str(self.table)]
        try:
            self.proc = subprocess.Popen(cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE, text=True, encoding='utf-8',
                errors='replace', bufsize=1)
            self.running = True
            threading.Thread(target=self._reader, daemon=True).start()
            return True
        except Exception as e:
            self.q.put(f'[BŁĄD URUCHOMIENIA] {e}'); return False

    def _reader(self):
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
            self.running = False; self.connected = False
            self.q.put('__DEAD__')

    def _handle_line(self, line: str):
        if line == 'CONNECTED':
            self.connected = True; self.q.put('✅ Połączono'); return
        if line.startswith('SESSION_OK'):
            self.q.put('🔑 Sesja OK'); return
        if line.startswith('SESSION_WARN'):
            self.q.put('⚠️  Sesja bez kt='); return
        if line.startswith('TABLES_START'):
            self.tables = []; return
        if line.startswith('TABLE '):
            parts = line[6:].split(' | ', 2)
            if parts:
                try:
                    self.tables.append({'id': int(parts[0]),
                        'params': parts[1] if len(parts) > 1 else '',
                        'players': parts[2] if len(parts) > 2 else ''})
                except ValueError:
                    pass
            return
        if line == 'TABLES_END':
            self.q.put('__TABLES__'); return
        if line.startswith('JOINED '):
            try:
                self.table = int(line[7:])
            except ValueError:
                pass
            self.q.put(f'➡️  Stół {self.table}'); return
        if line == 'TABLES_EMPTY':
            self.q.put('⚠️  Brak stołów'); return
        if line.startswith('CURRENT_TABLE '):
            self.q.put(f'📍 Stół: {line[14:]}'); return
        if line.startswith('MSG '):
            self.q.put(line[4:]); return
        if line.startswith('BOT_START '):
            self.q.put(f'🚀 {line[10:]}'); return
        if line.startswith('EXT '):
            parts = line[4:].split(maxsplit=1)
            self.q.put(f'📤 → stół {parts[0]}: {parts[1]}' if len(parts) == 2 else line); return
        if line.startswith('PLAYER_JOIN '):
            self.q.put(f'__PLAYER_JOIN__{line[12:]}'); return
        self.q.put(line)

    def send(self, text: str) -> bool:
        try:
            self.proc.stdin.write(text + '\n'); self.proc.stdin.flush(); return True
        except Exception:
            return False

    def join_table(self, tid: int) -> bool:
        if self.send(f'/join {tid}'):
            self.table = tid; return True
        return False

    def leave_table(self) -> bool:
        if self.send('/join 0'):
            self.table = 0; return True
        return False

    def stop(self):
        self.running = False
        if self.proc:
            try:
                self.proc.stdin.write('/quit\n'); self.proc.stdin.flush()
            except Exception:
                pass
            try:
                self.proc.terminate(); self.proc.wait(timeout=2)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass

    @property
    def label(self) -> str:
        icon = '🟢' if (self.running and self.connected) else ('🔴' if not self.running else '🟡')
        return f'{icon} Bot #{self.idx:02d}  R:{self.room}  T:{self.table or "—"}'


# ══════════════════════════════════════════════════════════════════════════════
# App
# ══════════════════════════════════════════════════════════════════════════════

class App:
    C = {
        'bg': '#1e1e2e', 'bg2': '#181825', 'bg3': '#313244', 'bg4': '#45475a',
        'fg': '#cdd6f4', 'fg2': '#6c7086',
        'blue': '#89b4fa', 'green': '#a6e3a1', 'red': '#f38ba8',
        'yellow': '#f9e2af', 'purple': '#cba6f7', 'teal': '#94e2d5',
        'border': '#45475a',
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('🤖 Kurnik Bot Launcher')
        self.root.geometry('1700x950')
        self.root.configure(bg=self.C['bg'])
        self.root.minsize(1300, 700)
        self.script = Path(__file__).parent / 'kurnik-ws.py'
        self.bots: Dict[int, Bot] = {}
        self.sel: Optional[int] = None
        self._next_id = 1
        self.cfg = ConfigManager()
        self._apply_styles()
        self._build_ui()
        self._tick()

    def _apply_styles(self):
        s = ttk.Style(); s.theme_use('clam'); C = self.C
        s.configure('.', background=C['bg'], foreground=C['fg'], font=('Segoe UI', 10))
        s.configure('TLabelframe', background=C['bg'], relief='flat', borderwidth=1, bordercolor=C['border'])
        s.configure('TLabelframe.Label', background=C['bg'], foreground=C['blue'], font=('Segoe UI', 10, 'bold'))
        s.configure('TLabel', background=C['bg'], foreground=C['fg'])
        s.configure('TButton', background=C['bg3'], foreground=C['fg'], padding=(8, 4), relief='flat', borderwidth=0)
        s.map('TButton', background=[('active', C['bg4']), ('pressed', C['border'])])
        s.configure('Accent.TButton', background=C['blue'], foreground=C['bg'], font=('Segoe UI', 10, 'bold'), padding=(10, 5))
        s.map('Accent.TButton', background=[('active', '#7aa2f7')])
        s.configure('Danger.TButton', background=C['red'], foreground=C['bg'], padding=(8, 4))
        s.map('Danger.TButton', background=[('active', '#e06c8a')])
        s.configure('TCheckbutton', background=C['bg'], foreground=C['fg'])
        s.configure('TEntry', fieldbackground=C['bg3'], foreground=C['fg'], insertcolor=C['fg'], borderwidth=1, relief='flat')
        s.configure('TSpinbox', fieldbackground=C['bg3'], foreground=C['fg'], borderwidth=1, relief='flat')
        s.configure('TCombobox', fieldbackground=C['bg3'], foreground=C['fg'], selectbackground=C['bg4'], selectforeground=C['fg'])
        s.map('TCombobox', fieldbackground=[('readonly', C['bg3'])])
        s.configure('TNotebook', background=C['bg'], tabmargins=[0, 0, 0, 0], borderwidth=0)
        s.configure('TNotebook.Tab', background=C['bg3'], foreground=C['fg2'], padding=(12, 6), borderwidth=0)
        s.map('TNotebook.Tab', background=[('selected', C['bg4'])], foreground=[('selected', C['fg'])])
        s.configure('TPanedwindow', background=C['border'])
        s.configure('TScrollbar', background=C['bg3'], troughcolor=C['bg2'], borderwidth=0, arrowsize=12)

    def _build_ui(self):
        C = self.C

        # ── Górny pasek ────────────────────────────────────────────────────────
        top = tk.Frame(self.root, bg=C['bg'], pady=10)
        top.pack(fill=tk.X, padx=14)

        left = tk.Frame(top, bg=C['bg'])
        left.pack(side=tk.LEFT)

        def field(parent, label, var, width=6):
            f = tk.Frame(parent, bg=C['bg'])
            f.pack(side=tk.LEFT, padx=(0, 14))
            tk.Label(f, text=label, bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9)).pack(anchor=tk.W)
            ttk.Entry(f, textvariable=var, width=width).pack()

        def spin(parent, label, var, lo, hi):
            f = tk.Frame(parent, bg=C['bg'])
            f.pack(side=tk.LEFT, padx=(0, 14))
            tk.Label(f, text=label, bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9)).pack(anchor=tk.W)
            ttk.Spinbox(f, from_=lo, to=hi, textvariable=var, width=5).pack()

        self.v_count  = tk.IntVar(value=2)
        self.v_room   = tk.StringVar(value=DEFAULT_ROOM)
        self.v_table  = tk.StringVar(value='0')
        self.v_shared = tk.BooleanVar(value=True)

        spin(left, 'Liczba botów', self.v_count, 1, 50)
        field(left, 'Pokój', self.v_room)
        field(left, 'Stół startowy', self.v_table)
        cb_f = tk.Frame(left, bg=C['bg']); cb_f.pack(side=tk.LEFT, padx=(0, 14))
        tk.Label(cb_f, text=' ', bg=C['bg']).pack()
        ttk.Checkbutton(cb_f, text='Wspólny stół', variable=self.v_shared).pack()

        right = tk.Frame(top, bg=C['bg'])
        right.pack(side=tk.RIGHT)
        ttk.Button(right, text='▶  Uruchom boty',    command=self._run_bots,  style='Accent.TButton').pack(side=tk.LEFT, padx=3)
        ttk.Button(right, text='⏹  Stop wszystkich', command=self._stop_all).pack(side=tk.LEFT, padx=3)
        ttk.Button(right, text='🗑  Wyczyść logi',   command=self._clear_logs).pack(side=tk.LEFT, padx=3)
        ttk.Button(right, text='💾  Eksport logów',  command=self._export).pack(side=tk.LEFT, padx=3)

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=14)

        # ── Główny obszar ──────────────────────────────────────────────────────
        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        p1 = ttk.LabelFrame(main, text='🤖  Boty', padding=8)
        main.add(p1, weight=1)
        self._build_bots_panel(p1)

        p2 = ttk.LabelFrame(main, text='💬  Wybrany bot', padding=8)
        main.add(p2, weight=3)
        self._build_selected_bot_panel(p2)

        p3 = ttk.LabelFrame(main, text='⚙️  Konfiguracja', padding=8)
        main.add(p3, weight=4)
        self._build_config_panel(p3)

    # ── Panele ────────────────────────────────────────────────────────────────

    def _build_bots_panel(self, p):
        C = self.C
        f = tk.Frame(p, bg=C['bg']); f.pack(fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(f); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.bot_list = tk.Listbox(f, yscrollcommand=sb.set,
            bg=C['bg2'], fg=C['fg'], selectbackground=C['bg4'], selectforeground=C['fg'],
            font=('Consolas', 10), activestyle='none', borderwidth=0, highlightthickness=0)
        self.bot_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.bot_list.yview)
        self.bot_list.bind('<<ListboxSelect>>', self._on_select_bot)

    def _build_selected_bot_panel(self, p):
        C = self.C
        self.lbl_bot = tk.Label(p, text='Wybierz bota z listy',
            bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 10, 'italic'))
        self.lbl_bot.pack(anchor=tk.W, pady=(0, 8))

        tf = ttk.LabelFrame(p, text='📋  Stoły w pokoju', padding=6)
        tf.pack(fill=tk.X, pady=(0, 8))
        inner = tk.Frame(tf, bg=C['bg']); inner.pack(fill=tk.X)
        tsb = ttk.Scrollbar(inner, orient=tk.VERTICAL); tsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.table_list = tk.Listbox(inner, yscrollcommand=tsb.set, height=5,
            bg=C['bg2'], fg=C['teal'], selectbackground=C['bg4'], selectforeground=C['fg'],
            font=('Consolas', 9), activestyle='none', borderwidth=0, highlightthickness=0)
        self.table_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tsb.config(command=self.table_list.yview)
        br = tk.Frame(tf, bg=C['bg']); br.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(br, text='➡  Dołącz do zaznaczonego', command=self._join_selected_table).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(br, text='ID:', bg=C['bg'], fg=C['fg2']).pack(side=tk.LEFT, padx=(0, 4))
        self.v_join_id = tk.StringVar()
        ttk.Entry(br, textvariable=self.v_join_id, width=5).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(br, text='➡', command=self._join_manual).pack(side=tk.LEFT)

        mf = ttk.LabelFrame(p, text='📨  Wyślij do wybranego bota', padding=6)
        mf.pack(fill=tk.X, pady=(0, 8))
        row = tk.Frame(mf, bg=C['bg']); row.pack(fill=tk.X)
        self.ent_one = ttk.Entry(row, font=('Segoe UI', 10))
        self.ent_one.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.ent_one.bind('<Return>', lambda _: self._send_one())
        ttk.Button(row, text='Wyślij', command=self._send_one).pack(side=tk.LEFT)

        tk.Label(p, text='Log bota:', bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9)).pack(anchor=tk.W)
        self.txt_bot = scrolledtext.ScrolledText(p, state=tk.DISABLED, height=10,
            bg=C['bg2'], fg=C['teal'], insertbackground=C['fg'],
            font=('Consolas', 9), borderwidth=0, relief='flat')
        self.txt_bot.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

    def _build_config_panel(self, p):
        nb = ttk.Notebook(p); nb.pack(fill=tk.BOTH, expand=True)
        tabs = [
            ('📢  Broadcast',       self._build_tab_broadcast),
            ('🟢  Whitelist',       self._build_tab_whitelist),
            ('🔴  Blacklist',       self._build_tab_blacklist),
            ('🏷️  Grupy',           self._build_tab_groups),
            ('💬  Pule wiadomości', self._build_tab_pools),
            ('📋  Log globalny',    self._build_tab_log),
        ]
        for title, builder in tabs:
            f = tk.Frame(nb, bg=self.C['bg'], padx=8, pady=8)
            nb.add(f, text=title)
            builder(f)

    # ── Zakładka Broadcast ────────────────────────────────────────────────────

    def _build_tab_broadcast(self, p):
        C = self.C
        f1 = ttk.LabelFrame(p, text='Wyślij wiadomość do wszystkich botów', padding=8)
        f1.pack(fill=tk.X, pady=(0, 10))
        r1 = tk.Frame(f1, bg=C['bg']); r1.pack(fill=tk.X)
        self.ent_all = ttk.Entry(r1, font=('Segoe UI', 10))
        self.ent_all.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.ent_all.bind('<Return>', lambda _: self._send_all())
        ttk.Button(r1, text='📢 Broadcast', command=self._send_all, style='Accent.TButton').pack(side=tk.LEFT)

        f2 = ttk.LabelFrame(p, text='Przełącz wszystkie boty na stół', padding=8)
        f2.pack(fill=tk.X)
        r2 = tk.Frame(f2, bg=C['bg']); r2.pack(fill=tk.X)
        tk.Label(r2, text='ID stołu:', bg=C['bg'], fg=C['fg2']).pack(side=tk.LEFT, padx=(0, 6))
        self.v_join_all = tk.StringVar()
        ttk.Entry(r2, textvariable=self.v_join_all, width=8).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(r2, text='➡  Przełącz wszystkie', command=self._join_all).pack(side=tk.LEFT)

    # ── Zakładka Whitelist ────────────────────────────────────────────────────

    def _build_tab_whitelist(self, p):
        C = self.C
        tk.Label(p, text='Gdy gracz z whitelist wejdzie na stół — boty automatycznie wychodzą.',
            bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9, 'italic')).pack(anchor=tk.W, pady=(0, 8))

        tb = tk.Frame(p, bg=C['bg']); tb.pack(fill=tk.X, pady=(0, 6))
        self.v_wl_entry = tk.StringVar()
        ttk.Entry(tb, textvariable=self.v_wl_entry, width=22, font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tb, text='➕ Dodaj',    command=self._wl_add).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text='➖ Usuń',     command=self._wl_remove).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text='📂 TXT/CSV',  command=self._wl_load_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text='🗑 Wyczyść',  command=self._wl_clear, style='Danger.TButton').pack(side=tk.LEFT, padx=2)

        self.lbl_wl_count = tk.Label(p, text='0 wpisów', bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9))
        self.lbl_wl_count.pack(anchor=tk.E)

        lf = tk.Frame(p, bg=C['bg']); lf.pack(fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(lf); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.wl_listbox = tk.Listbox(lf, yscrollcommand=sb.set,
            bg=C['bg2'], fg=C['green'], selectbackground=C['bg4'], selectforeground=C['fg'],
            font=('Consolas', 10), activestyle='none', borderwidth=0, highlightthickness=0)
        self.wl_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.wl_listbox.yview)
        self._wl_refresh()

    # ── Zakładka Blacklist ────────────────────────────────────────────────────

    def _build_tab_blacklist(self, p):
        C = self.C
        tk.Label(p, text='Konfiguracja reakcji na graczy. Priorytet: własna akcja > grupa > brak reakcji.',
            bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9, 'italic')).pack(anchor=tk.W, pady=(0, 8))

        tb = tk.Frame(p, bg=C['bg']); tb.pack(fill=tk.X, pady=(0, 4))
        self.v_bl_entry = tk.StringVar()
        ttk.Entry(tb, textvariable=self.v_bl_entry, width=18, font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tb, text='➕ Dodaj',    command=self._bl_add).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text='📂 TXT/CSV',  command=self._bl_load_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text='🗑 Wyczyść',  command=self._bl_clear, style='Danger.TButton').pack(side=tk.LEFT, padx=2)

        self.lbl_bl_count = tk.Label(p, text='0 wpisów', bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9))
        self.lbl_bl_count.pack(anchor=tk.E)

        paned = ttk.PanedWindow(p, orient=tk.HORIZONTAL); paned.pack(fill=tk.BOTH, expand=True)

        # Lista nicków
        lf = tk.Frame(paned, bg=C['bg']); paned.add(lf, weight=2)
        sb = ttk.Scrollbar(lf); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.bl_listbox = tk.Listbox(lf, yscrollcommand=sb.set,
            bg=C['bg2'], fg=C['red'], selectbackground=C['bg4'], selectforeground=C['fg'],
            font=('Consolas', 10), activestyle='none', borderwidth=0, highlightthickness=0)
        self.bl_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.bl_listbox.yview)
        self.bl_listbox.bind('<<ListboxSelect>>', self._bl_on_select)

        # Edytor
        ef_outer = tk.Frame(paned, bg=C['bg']); paned.add(ef_outer, weight=3)
        self.lbl_bl_selected = tk.Label(ef_outer, text='← Wybierz nick aby skonfigurować',
            bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9, 'italic'))
        self.lbl_bl_selected.pack(anchor=tk.W, pady=(0, 6))

        ef = ttk.LabelFrame(ef_outer, text='Konfiguracja reakcji', padding=8)
        ef.pack(fill=tk.X, pady=(0, 8))

        def cfg_row(parent, label, var, cb_ref_name, values):
            r = tk.Frame(parent, bg=C['bg']); r.pack(fill=tk.X, pady=3)
            tk.Label(r, text=label, bg=C['bg'], fg=C['fg2'], width=16, anchor=tk.W).pack(side=tk.LEFT)
            cb = ttk.Combobox(r, textvariable=var, state='readonly', width=28)
            cb['values'] = values; cb.pack(side=tk.LEFT)
            setattr(self, cb_ref_name, cb)

        self.v_bl_group  = tk.StringVar()
        self.v_bl_action = tk.StringVar()
        self.v_bl_pool   = tk.StringVar()
        cfg_row(ef, 'Grupa:', self.v_bl_group, 'cb_bl_group', self._combo_groups())
        cfg_row(ef, 'Własna akcja:', self.v_bl_action, 'cb_bl_action',
                ['(brak — użyj grupy)'] + ACTION_LABELS)

        self.lbl_bl_action_desc = tk.Label(ef, text='', bg=C['bg'], fg=C['fg2'],
            font=('Segoe UI', 8, 'italic'), wraplength=300, justify=tk.LEFT)
        self.lbl_bl_action_desc.pack(anchor=tk.W, pady=(2, 4))
        self.v_bl_action.trace_add('write', self._bl_action_desc_update)

        cfg_row(ef, 'Własna pula:', self.v_bl_pool, 'cb_bl_pool', self._combo_pools())

        btn_row = tk.Frame(ef, bg=C['bg']); btn_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_row, text='💾 Zapisz konfigurację', command=self._bl_save_config,
                   style='Accent.TButton').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text='🗑 Usuń nick', command=self._bl_remove_selected,
                   style='Danger.TButton').pack(side=tk.LEFT)

        self._bl_refresh()

    # ── Zakładka Grupy ────────────────────────────────────────────────────────

    def _build_tab_groups(self, p):
        C = self.C
        tk.Label(p, text='Grupy pozwalają przypisać wspólną konfigurację wielu nickom naraz.',
            bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9, 'italic')).pack(anchor=tk.W, pady=(0, 8))

        tb = tk.Frame(p, bg=C['bg']); tb.pack(fill=tk.X, pady=(0, 6))
        tk.Label(tb, text='Nazwa grupy:', bg=C['bg'], fg=C['fg2']).pack(side=tk.LEFT, padx=(0, 4))
        self.v_gr_name = tk.StringVar()
        ttk.Entry(tb, textvariable=self.v_gr_name, width=18).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tb, text='➕ Utwórz grupę', command=self._gr_add).pack(side=tk.LEFT)

        paned = ttk.PanedWindow(p, orient=tk.HORIZONTAL); paned.pack(fill=tk.BOTH, expand=True)

        lf = tk.Frame(paned, bg=C['bg']); paned.add(lf, weight=1)
        sb = ttk.Scrollbar(lf); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.gr_listbox = tk.Listbox(lf, yscrollcommand=sb.set,
            bg=C['bg2'], fg=C['yellow'], selectbackground=C['bg4'], selectforeground=C['fg'],
            font=('Consolas', 10), activestyle='none', borderwidth=0, highlightthickness=0)
        self.gr_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.gr_listbox.yview)
        self.gr_listbox.bind('<<ListboxSelect>>', self._gr_on_select)

        ef_outer = tk.Frame(paned, bg=C['bg']); paned.add(ef_outer, weight=3)
        self.lbl_gr_selected = tk.Label(ef_outer, text='← Wybierz grupę aby edytować',
            bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9, 'italic'))
        self.lbl_gr_selected.pack(anchor=tk.W, pady=(0, 6))

        ef = ttk.LabelFrame(ef_outer, text='Konfiguracja grupy', padding=8)
        ef.pack(fill=tk.X, pady=(0, 8))

        def gr_row(parent, label, var, width=30):
            r = tk.Frame(parent, bg=C['bg']); r.pack(fill=tk.X, pady=3)
            tk.Label(r, text=label, bg=C['bg'], fg=C['fg2'], width=18, anchor=tk.W).pack(side=tk.LEFT)
            ttk.Entry(r, textvariable=var, width=width).pack(side=tk.LEFT)

        self.v_gr_desc   = tk.StringVar()
        self.v_gr_action = tk.StringVar()
        self.v_gr_pool   = tk.StringVar()
        gr_row(ef, 'Opis (opcjonalny):', self.v_gr_desc)

        ra = tk.Frame(ef, bg=C['bg']); ra.pack(fill=tk.X, pady=3)
        tk.Label(ra, text='Akcja:', bg=C['bg'], fg=C['fg2'], width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.cb_gr_action = ttk.Combobox(ra, textvariable=self.v_gr_action, state='readonly', width=30)
        self.cb_gr_action['values'] = ACTION_LABELS; self.cb_gr_action.pack(side=tk.LEFT)
        self.lbl_gr_action_desc = tk.Label(ef, text='', bg=C['bg'], fg=C['fg2'],
            font=('Segoe UI', 8, 'italic'), wraplength=300, justify=tk.LEFT)
        self.lbl_gr_action_desc.pack(anchor=tk.W, pady=(2, 4))
        self.v_gr_action.trace_add('write', self._gr_action_desc_update)

        rp = tk.Frame(ef, bg=C['bg']); rp.pack(fill=tk.X, pady=3)
        tk.Label(rp, text='Pula wiadomości:', bg=C['bg'], fg=C['fg2'], width=18, anchor=tk.W).pack(side=tk.LEFT)
        self.cb_gr_pool = ttk.Combobox(rp, textvariable=self.v_gr_pool, state='readonly', width=22)
        self.cb_gr_pool['values'] = self._combo_pools(); self.cb_gr_pool.pack(side=tk.LEFT)

        btn_row = tk.Frame(ef, bg=C['bg']); btn_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_row, text='💾 Zapisz grupę', command=self._gr_save,
                   style='Accent.TButton').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text='🗑 Usuń grupę', command=self._gr_remove,
                   style='Danger.TButton').pack(side=tk.LEFT)

        mf = ttk.LabelFrame(ef_outer, text='Nicki w tej grupie', padding=6)
        mf.pack(fill=tk.BOTH, expand=True)
        self.gr_members_list = tk.Listbox(mf, bg=C['bg2'], fg=C['fg'],
            font=('Consolas', 9), height=6, activestyle='none',
            borderwidth=0, highlightthickness=0)
        self.gr_members_list.pack(fill=tk.BOTH, expand=True)

        self._gr_refresh()

    # ── Zakładka Pule wiadomości ──────────────────────────────────────────────

    def _build_tab_pools(self, p):
        C = self.C
        tk.Label(p, text='Bot losowo wybiera wiadomość z puli. Użyj {user} jako placeholder dla nicku gracza.',
            bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9, 'italic'), wraplength=600, justify=tk.LEFT
            ).pack(anchor=tk.W, pady=(0, 8))

        paned = ttk.PanedWindow(p, orient=tk.HORIZONTAL); paned.pack(fill=tk.BOTH, expand=True)

        lf = tk.Frame(paned, bg=C['bg']); paned.add(lf, weight=1)
        tb = tk.Frame(lf, bg=C['bg']); tb.pack(fill=tk.X, pady=(0, 4))
        self.v_pool_name = tk.StringVar()
        ttk.Entry(tb, textvariable=self.v_pool_name, width=14).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tb, text='➕', command=self._pool_create).pack(side=tk.LEFT, padx=1)
        ttk.Button(tb, text='🗑', command=self._pool_delete, style='Danger.TButton').pack(side=tk.LEFT, padx=1)

        psb = ttk.Scrollbar(lf); psb.pack(side=tk.RIGHT, fill=tk.Y)
        self.pool_listbox = tk.Listbox(lf, yscrollcommand=psb.set,
            bg=C['bg2'], fg=C['purple'], selectbackground=C['bg4'], selectforeground=C['fg'],
            font=('Consolas', 10), activestyle='none', borderwidth=0, highlightthickness=0)
        self.pool_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        psb.config(command=self.pool_listbox.yview)
        self.pool_listbox.bind('<<ListboxSelect>>', self._pool_on_select)

        rf = tk.Frame(paned, bg=C['bg']); paned.add(rf, weight=3)
        self.lbl_pool_selected = tk.Label(rf, text='← Wybierz pulę aby edytować',
            bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 9, 'italic'))
        self.lbl_pool_selected.pack(anchor=tk.W, pady=(0, 6))

        act_tb = tk.Frame(rf, bg=C['bg']); act_tb.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(act_tb, text='📂 Importuj TXT/CSV', command=self._pool_import).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(act_tb, text='➖ Usuń zaznaczoną', command=self._pool_remove_msg).pack(side=tk.LEFT)

        add_row = tk.Frame(rf, bg=C['bg']); add_row.pack(fill=tk.X, pady=(0, 4))
        self.v_pool_msg = tk.StringVar()
        ttk.Entry(add_row, textvariable=self.v_pool_msg, font=('Segoe UI', 10)).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(add_row, text='➕ Dodaj wiadomość', command=self._pool_add_msg).pack(side=tk.LEFT)

        mlf = tk.Frame(rf, bg=C['bg']); mlf.pack(fill=tk.BOTH, expand=True)
        msb = ttk.Scrollbar(mlf); msb.pack(side=tk.RIGHT, fill=tk.Y)
        self.msg_listbox = tk.Listbox(mlf, yscrollcommand=msb.set,
            bg=C['bg2'], fg=C['fg'], selectbackground=C['bg4'], selectforeground=C['fg'],
            font=('Consolas', 9), activestyle='none', borderwidth=0, highlightthickness=0)
        self.msg_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        msb.config(command=self.msg_listbox.yview)

        self.lbl_pool_count = tk.Label(rf, text='', bg=C['bg'], fg=C['fg2'], font=('Segoe UI', 8))
        self.lbl_pool_count.pack(anchor=tk.E, pady=(2, 0))

        self._pool_refresh()

    # ── Zakładka Log globalny ─────────────────────────────────────────────────

    def _build_tab_log(self, p):
        C = self.C
        self.txt_all = scrolledtext.ScrolledText(p, state=tk.DISABLED,
            bg=C['bg2'], fg=C['fg'], insertbackground=C['fg'],
            font=('Consolas', 9), borderwidth=0, relief='flat')
        self.txt_all.pack(fill=tk.BOTH, expand=True)

    # ── Pomocniki combobox ────────────────────────────────────────────────────

    def _combo_pools(self)  -> List[str]: return ['(brak)'] + self.cfg.pool_names()
    def _combo_groups(self) -> List[str]: return ['(brak)'] + list(self.cfg.groups.keys())

    def _refresh_combos(self):
        pools  = self._combo_pools()
        groups = self._combo_groups()
        for cb in (self.cb_bl_pool, self.cb_gr_pool):
            cb['values'] = pools
        self.cb_bl_group['values'] = groups

    # ══════════════════════════════════════════════════════════════════════════
    # AKCJE BOTÓW
    # ══════════════════════════════════════════════════════════════════════════

    def _run_bots(self):
        room = self.v_room.get().strip()
        if not room.isdigit():
            messagebox.showerror('Błąd', 'Numer pokoju musi być liczbą'); return
        try:
            base_table = int(self.v_table.get()) if self.v_table.get().strip() else 0
        except ValueError:
            messagebox.showerror('Błąd', 'Numer stołu musi być liczbą'); return
        count = self.v_count.get(); shared = self.v_shared.get()
        for _ in range(count):
            idx   = self._next_id
            table = base_table if shared else idx
            bot   = Bot(idx, room, table)
            if bot.start(self.script):
                self.bots[idx] = bot
                self.bot_list.insert(tk.END, bot.label)
                self._log(f'🚀 Uruchomiono Bot #{idx:02d}  R:{room}  T:{table or "—"}')
            else:
                self._log(f'❌ Nie udało się uruchomić Bot #{idx:02d}')
            self._next_id += 1

    def _stop_all(self):
        for bot in list(self.bots.values()): bot.stop()
        self.bots.clear(); self.bot_list.delete(0, tk.END)
        self.sel = None; self._next_id = 1
        self._log('⏹  Wszystkie boty zatrzymane')
        self._refresh_table_list([])

    def _on_select_bot(self, _=None):
        sel = self.bot_list.curselection()
        if not sel: return
        ids = list(self.bots.keys())
        if sel[0] >= len(ids): return
        self.sel = ids[sel[0]]; bot = self.bots[self.sel]
        self.lbl_bot.config(
            text=f'Bot #{self.sel:02d}   Pokój: {bot.room}   Stół: {bot.table or "—"}',
            fg=self.C['blue'])
        self._refresh_bot_log(self.sel)
        self._refresh_table_list(bot.tables)

    def _refresh_table_list(self, tables):
        self.table_list.delete(0, tk.END)
        for t in tables:
            self.table_list.insert(tk.END,
                f"ID:{t['id']:>4}  {t['params']:<18}  👥 {t['players'] or '(brak graczy)'}")

    def _join_selected_table(self):
        if self.sel is None or self.sel not in self.bots: return
        sel = self.table_list.curselection()
        if not sel: messagebox.showinfo('Info', 'Zaznacz stół na liście'); return
        tid = self.bots[self.sel].tables[sel[0]]['id']
        self.bots[self.sel].join_table(tid); self._log(f'➡️  Bot #{self.sel} → stół {tid}')

    def _join_manual(self):
        if self.sel is None or self.sel not in self.bots: return
        raw = self.v_join_id.get().strip()
        if not raw.isdigit(): messagebox.showerror('Błąd', 'Podaj numer stołu'); return
        self.bots[self.sel].join_table(int(raw)); self._log(f'➡️  Bot #{self.sel} → stół {raw}')

    def _join_all(self):
        raw = self.v_join_all.get().strip()
        if not raw.isdigit(): messagebox.showerror('Błąd', 'Podaj numer stołu'); return
        tid = int(raw)
        cnt = sum(1 for b in self.bots.values() if b.join_table(tid))
        self._log(f'➡️  Przełączono {cnt} botów → stół {tid}')

    def _send_one(self):
        if self.sel is None or self.sel not in self.bots: return
        msg = self.ent_one.get().strip()
        if msg and self.bots[self.sel].send(msg):
            self.ent_one.delete(0, tk.END)
            self._log(f'Bot #{self.sel} ➜ {msg}'); self._append_bot_log(f'➜ {msg}')

    def _send_all(self):
        msg = self.ent_all.get().strip()
        if msg and self.bots:
            cnt = sum(1 for b in self.bots.values() if b.send(msg))
            self.ent_all.delete(0, tk.END); self._log(f'📢 BROADCAST ({cnt}): {msg}')

    # ══════════════════════════════════════════════════════════════════════════
    # WHITELIST
    # ══════════════════════════════════════════════════════════════════════════

    def _wl_add(self):
        name = self.v_wl_entry.get().strip()
        if not name: return
        self.cfg.wl_add(name); self.v_wl_entry.set('')
        self._wl_refresh(); self._log(f'🟢 Whitelist +{name}')

    def _wl_remove(self):
        sel = self.wl_listbox.curselection()
        if not sel: return
        name = self.wl_listbox.get(sel[0])
        self.cfg.wl_remove(name); self._wl_refresh(); self._log(f'🟢 Whitelist −{name}')

    def _wl_load_file(self):
        fp = filedialog.askopenfilename(title='Whitelist — wybierz plik',
            filetypes=[('TXT / CSV', '*.txt *.csv'), ('Wszystkie', '*.*')])
        if not fp: return
        try:
            added = self.cfg.wl_import(fp); self._wl_refresh()
            self._log(f'🟢 Whitelist: +{added} z {Path(fp).name}')
        except RuntimeError as e:
            messagebox.showerror('Błąd', str(e))

    def _wl_clear(self):
        if not messagebox.askyesno('Whitelist', 'Wyczyścić całą whitelist?'): return
        self.cfg.wl_clear(); self._wl_refresh(); self._log('🟢 Whitelist wyczyszczona')

    def _wl_refresh(self):
        self.wl_listbox.delete(0, tk.END)
        for n in sorted(self.cfg.whitelist): self.wl_listbox.insert(tk.END, n)
        self.lbl_wl_count.config(text=f'{len(self.cfg.whitelist)} wpisów')

    # ══════════════════════════════════════════════════════════════════════════
    # BLACKLIST
    # ══════════════════════════════════════════════════════════════════════════

    def _bl_add(self):
        name = self.v_bl_entry.get().strip()
        if not name: return
        self.cfg.bl_add(name); self.v_bl_entry.set('')
        self._bl_refresh(); self._log(f'🔴 Blacklist +{name}')

    def _bl_load_file(self):
        fp = filedialog.askopenfilename(title='Blacklist — wybierz plik',
            filetypes=[('TXT / CSV', '*.txt *.csv'), ('Wszystkie', '*.*')])
        if not fp: return
        try:
            added = self.cfg.bl_import(fp); self._bl_refresh()
            self._log(f'🔴 Blacklist: +{added} z {Path(fp).name}')
        except RuntimeError as e:
            messagebox.showerror('Błąd', str(e))

    def _bl_clear(self):
        if not messagebox.askyesno('Blacklist', 'Wyczyścić całą blacklist?'): return
        self.cfg.bl_clear(); self._bl_refresh(); self._log('🔴 Blacklist wyczyszczona')

    def _bl_on_select(self, _=None):
        sel = self.bl_listbox.curselection()
        if not sel: return
        raw   = self.bl_listbox.get(sel[0])
        nick  = raw.split('  [')[0].strip()
        key   = nick.lower()
        entry = self.cfg.blacklist.get(key, {})
        self.lbl_bl_selected.config(text=f'Konfiguracja dla: {nick}', fg=self.C['red'])
        self.cb_bl_group['values']  = self._combo_groups()
        self.cb_bl_pool['values']   = self._combo_pools()
        self.v_bl_group.set(entry.get('group') or '(brak)')
        a = entry.get('action')
        self.v_bl_action.set(ACTIONS[a][0] if a in ACTIONS else '(brak — użyj grupy)')
        self.v_bl_pool.set(entry.get('pool') or '(brak)')

    def _bl_save_config(self):
        sel = self.bl_listbox.curselection()
        if not sel: messagebox.showinfo('Info', 'Wybierz nick z listy'); return
        nick   = self.bl_listbox.get(sel[0]).split('  [')[0].strip()
        group  = self.v_bl_group.get();  group  = None if group  == '(brak)' else group
        pool   = self.v_bl_pool.get();   pool   = None if pool   == '(brak)' else pool
        al     = self.v_bl_action.get()
        action = next((k for k, (l, _) in ACTIONS.items() if l == al), None)
        self.cfg.bl_update(nick, group=group, action=action, pool=pool)
        self._bl_refresh(); self._log(f'🔴 Zapisano konfigurację dla {nick}')

    def _bl_remove_selected(self):
        sel = self.bl_listbox.curselection()
        if not sel: return
        nick = self.bl_listbox.get(sel[0]).split('  [')[0].strip()
        self.cfg.bl_remove(nick); self._bl_refresh()
        self.lbl_bl_selected.config(text='← Wybierz nick aby skonfigurować', fg=self.C['fg2'])
        self._log(f'🔴 Blacklist −{nick}')

    def _bl_action_desc_update(self, *_):
        lbl = self.v_bl_action.get()
        desc = next((d for k, (l, d) in ACTIONS.items() if l == lbl), 'Użyta zostanie konfiguracja grupy lub brak reakcji.')
        self.lbl_bl_action_desc.config(text=f'ℹ️  {desc}')

    def _bl_refresh(self):
        self.bl_listbox.delete(0, tk.END)
        for key, entry in sorted(self.cfg.blacklist.items()):
            display = entry.get('display', key)
            a = entry.get('action'); g = entry.get('group')
            tag = f'  [{ACTIONS[a][0]}]' if a else (f'  [grupa: {g}]' if g else '')
            self.bl_listbox.insert(tk.END, f'{display}{tag}')
        self.lbl_bl_count.config(text=f'{len(self.cfg.blacklist)} wpisów')

    # ══════════════════════════════════════════════════════════════════════════
    # GRUPY
    # ══════════════════════════════════════════════════════════════════════════

    def _gr_add(self):
        name = self.v_gr_name.get().strip()
        if not name: return
        if name in self.cfg.groups: messagebox.showwarning('Grupy', f'Grupa "{name}" już istnieje'); return
        self.cfg.group_add(name); self.v_gr_name.set('')
        self._gr_refresh(); self._refresh_combos(); self._log(f'🏷️  Utworzono grupę: {name}')

    def _gr_on_select(self, _=None):
        sel = self.gr_listbox.curselection()
        if not sel: return
        name = self.gr_listbox.get(sel[0]).split('  [')[0].strip()
        g    = self.cfg.groups.get(name, {})
        self.lbl_gr_selected.config(text=f'Edytujesz grupę: {name}', fg=self.C['yellow'])
        self.v_gr_desc.set(g.get('desc', ''))
        a = g.get('action', 'send_msg')
        self.v_gr_action.set(ACTIONS.get(a, (ACTION_LABELS[0],))[0])
        self.cb_gr_pool['values'] = self._combo_pools()
        self.v_gr_pool.set(g.get('pool') or '(brak)')
        self.gr_members_list.delete(0, tk.END)
        for key, entry in self.cfg.blacklist.items():
            if entry.get('group') == name:
                self.gr_members_list.insert(tk.END, entry.get('display', key))

    def _gr_save(self):
        sel = self.gr_listbox.curselection()
        if not sel: messagebox.showinfo('Info', 'Wybierz grupę z listy'); return
        name   = self.gr_listbox.get(sel[0]).split('  [')[0].strip()
        al     = self.v_gr_action.get()
        action = next((k for k, (l, _) in ACTIONS.items() if l == al), ACTION_KEYS[0])
        pool   = self.v_gr_pool.get(); pool = None if pool == '(brak)' else pool
        self.cfg.group_update(name, action=action, pool=pool, desc=self.v_gr_desc.get())
        self._gr_refresh(); self._log(f'🏷️  Zapisano grupę: {name}')

    def _gr_remove(self):
        sel = self.gr_listbox.curselection()
        if not sel: return
        name = self.gr_listbox.get(sel[0]).split('  [')[0].strip()
        if not messagebox.askyesno('Grupy', f'Usunąć grupę "{name}"?\nNicki stracą przypisanie.'): return
        self.cfg.group_remove(name); self._gr_refresh(); self._refresh_combos(); self._bl_refresh()
        self.lbl_gr_selected.config(text='← Wybierz grupę aby edytować', fg=self.C['fg2'])
        self._log(f'🏷️  Usunięto grupę: {name}')

    def _gr_action_desc_update(self, *_):
        lbl  = self.v_gr_action.get()
        desc = next((d for k, (l, d) in ACTIONS.items() if l == lbl), '')
        self.lbl_gr_action_desc.config(text=f'ℹ️  {desc}' if desc else '')

    def _gr_refresh(self):
        self.gr_listbox.delete(0, tk.END)
        for name, g in sorted(self.cfg.groups.items()):
            a    = g.get('action', '')
            lbl  = ACTIONS.get(a, ('?',))[0]
            desc = g.get('desc', '')
            self.gr_listbox.insert(tk.END, f'{name}  [{lbl}]' + (f'  {desc}' if desc else ''))

    # ══════════════════════════════════════════════════════════════════════════
    # PULE WIADOMOŚCI
    # ══════════════════════════════════════════════════════════════════════════

    @property
    def _selected_pool(self) -> Optional[str]:
        sel = self.pool_listbox.curselection()
        return self.pool_listbox.get(sel[0]).rsplit('  (', 1)[0] if sel else None

    def _pool_create(self):
        name = self.v_pool_name.get().strip()
        if not name: return
        if name in self.cfg.pools: messagebox.showwarning('Pule', f'Pula "{name}" już istnieje'); return
        self.cfg.pool_create(name); self.v_pool_name.set('')
        self._pool_refresh(); self._refresh_combos(); self._log(f'💬 Utworzono pulę: {name}')

    def _pool_delete(self):
        name = self._selected_pool
        if not name: return
        if not messagebox.askyesno('Pule', f'Usunąć pulę "{name}"?'): return
        self.cfg.pool_delete(name)
        self._pool_refresh(); self._refresh_combos(); self._gr_refresh(); self._bl_refresh()
        self.lbl_pool_selected.config(text='← Wybierz pulę aby edytować', fg=self.C['fg2'])
        self._log(f'💬 Usunięto pulę: {name}')

    def _pool_on_select(self, _=None):
        name = self._selected_pool
        if not name: return
        self.lbl_pool_selected.config(text=f'Edytujesz pulę: {name}', fg=self.C['purple'])
        self._pool_refresh_msgs(name)

    def _pool_add_msg(self):
        name = self._selected_pool
        if not name: messagebox.showinfo('Info', 'Wybierz pulę z listy'); return
        msg = self.v_pool_msg.get().strip()
        if not msg: return
        self.cfg.pool_add_msg(name, msg); self.v_pool_msg.set('')
        self._pool_refresh_msgs(name); self._pool_refresh()
        self._log(f'💬 Dodano wiadomość do puli "{name}"')

    def _pool_remove_msg(self):
        name = self._selected_pool
        if not name: return
        sel = self.msg_listbox.curselection()
        if not sel: return
        self.cfg.pool_remove_msg(name, sel[0])
        self._pool_refresh_msgs(name); self._pool_refresh()

    def _pool_import(self):
        name = self._selected_pool
        if not name: messagebox.showinfo('Info', 'Wybierz pulę z listy'); return
        fp = filedialog.askopenfilename(title=f'Importuj wiadomości do puli "{name}"',
            filetypes=[('TXT / CSV', '*.txt *.csv'), ('Wszystkie', '*.*')])
        if not fp: return
        try:
            added = self.cfg.pool_import(name, fp)
            self._pool_refresh_msgs(name); self._pool_refresh()
            self._log(f'💬 Pula "{name}": +{added} wiadomości z {Path(fp).name}')
        except RuntimeError as e:
            messagebox.showerror('Błąd', str(e))

    def _pool_refresh(self):
        self.pool_listbox.delete(0, tk.END)
        for name in self.cfg.pool_names():
            self.pool_listbox.insert(tk.END, f'{name}  ({len(self.cfg.pools[name])})')

    def _pool_refresh_msgs(self, pool_name: str):
        self.msg_listbox.delete(0, tk.END)
        msgs = self.cfg.pools.get(pool_name, [])
        for i, msg in enumerate(msgs):
            self.msg_listbox.insert(tk.END, f'{i+1:3}.  {msg}')
        self.lbl_pool_count.config(text=f'{len(msgs)} wiadomości')

    # ══════════════════════════════════════════════════════════════════════════
    # REAKCJA NA PLAYER_JOIN
    # ══════════════════════════════════════════════════════════════════════════

    def _handle_player_join(self, bot: Bot, payload: str):
        parts = payload.split(maxsplit=1)
        if len(parts) < 2: return
        try:
            table_id = int(parts[0])
        except ValueError:
            return
        username = parts[1].strip()
        if table_id != bot.table: return   # inny stół — nie nasz bot

        if self.cfg.is_whitelisted(username):
            bot.leave_table()
            self._log(f'🟢 WHITELIST: {username} → Bot #{bot.idx} wychodzi ze stołu {table_id}')
            return

        if self.cfg.is_blacklisted(username):
            conf   = self.cfg.get_bl_config(username)
            action = conf['action']
            pool   = conf['pool'] or 'domyślna'
            msg    = self.cfg.pool_get_random(pool, username)
            if action == 'send_msg':
                if msg: bot.send(msg)
                self._log(f'🔴 BLACKLIST: {username} → Bot #{bot.idx} wysyła wiadomość')
            elif action == 'leave':
                bot.leave_table()
                self._log(f'🔴 BLACKLIST: {username} → Bot #{bot.idx} wychodzi ze stołu')
            elif action == 'leave_msg':
                if msg: bot.send(msg)
                bot.leave_table()
                self._log(f'🔴 BLACKLIST: {username} → Bot #{bot.idx} wysyła wiadomość i wychodzi')
            elif action == 'nothing':
                self._log(f'🔴 BLACKLIST: {username} — brak reakcji (wyciszony)')

    # ══════════════════════════════════════════════════════════════════════════
    # LOGOWANIE
    # ══════════════════════════════════════════════════════════════════════════

    def _log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.txt_all.config(state=tk.NORMAL)
        self.txt_all.insert(tk.END, f'[{ts}] {msg}\n')
        self.txt_all.see(tk.END)
        self.txt_all.config(state=tk.DISABLED)

    def _append_bot_log(self, msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.txt_bot.config(state=tk.NORMAL)
        self.txt_bot.insert(tk.END, f'[{ts}] {msg}\n')
        self.txt_bot.see(tk.END)
        self.txt_bot.config(state=tk.DISABLED)

    def _refresh_bot_log(self, idx: int):
        self.txt_bot.config(state=tk.NORMAL)
        self.txt_bot.delete('1.0', tk.END)
        for line in self.bots[idx].lines:
            self.txt_bot.insert(tk.END, line + '\n')
        self.txt_bot.see(tk.END)
        self.txt_bot.config(state=tk.DISABLED)

    def _clear_logs(self):
        for w in (self.txt_bot, self.txt_all):
            w.config(state=tk.NORMAL); w.delete('1.0', tk.END); w.config(state=tk.DISABLED)

    def _export(self):
        fp = filedialog.asksaveasfilename(defaultextension='.txt',
            filetypes=[('Tekst', '*.txt'), ('Wszystkie', '*.*')])
        if fp:
            try:
                with open(fp, 'w', encoding='utf-8') as f:
                    f.write(f'Kurnik.pl Bot Export\nData: {datetime.now()}\n\n')
                    f.write(self.txt_all.get('1.0', tk.END))
                messagebox.showinfo('OK', f'Zapisano: {fp}')
            except Exception as e:
                messagebox.showerror('Błąd', str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # PĘTLA AKTUALIZACJI
    # ══════════════════════════════════════════════════════════════════════════

    def _tick(self):
        for idx in list(self.bots.keys()):
            bot = self.bots.get(idx)
            if not bot: continue
            while True:
                try:
                    msg = bot.q.get_nowait()
                except queue.Empty:
                    break
                if msg == '__DEAD__':
                    self._log(f'💀 Bot #{idx} zakończył działanie')
                    self.bots.pop(idx, None); self._rebuild_bot_list(); break
                if msg == '__TABLES__':
                    if self.sel == idx: self._refresh_table_list(bot.tables)
                    self._log(f'Bot #{idx}: 📋 {len(bot.tables)} stołów'); continue
                if msg.startswith('__PLAYER_JOIN__'):
                    self._handle_player_join(bot, msg[15:]); continue
                bot.lines.append(msg)
                self._log(f'Bot #{idx}: {msg}')
                if self.sel == idx: self._append_bot_log(msg)

        self._refresh_bot_labels()
        self.root.after(150, self._tick)

    def _rebuild_bot_list(self):
        self.bot_list.delete(0, tk.END)
        for bot in self.bots.values(): self.bot_list.insert(tk.END, bot.label)

    def _refresh_bot_labels(self):
        for i, bot in enumerate(self.bots.values()):
            try:
                self.bot_list.delete(i); self.bot_list.insert(i, bot.label)
            except tk.TclError:
                break


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
