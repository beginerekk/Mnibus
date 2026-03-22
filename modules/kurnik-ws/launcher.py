#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bot Launcher GUI — zarządza wieloma instancjami bota Kurnik.pl"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import subprocess, threading, queue, sys, io
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

# ─── UTF-8 dla Windows ────────────────────────────────────────────────────────
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

DEFAULT_GAME = 'kalambury'
DEFAULT_ROOM = '100'


# ─── Bot ─────────────────────────────────────────────────────────────────────

class Bot:
    """Jedna instancja bota jako subprocess."""

    def __init__(self, idx: int, room: str, table: int):
        self.idx   = idx
        self.room  = room
        self.table = table          # aktualny stół (mutowalny)
        self.proc: Optional[subprocess.Popen] = None
        self.q:    queue.Queue = queue.Queue()
        self.running = False
        self.lines:  List[str] = []
        self.tables: List[Dict[str, Any]] = []   # ostatnia lista stołów z serwera
        self.connected = False

    # ── uruchomienie ──────────────────────────────────────────────────────────
    def start(self, script: Path) -> bool:
        cmd = [
            sys.executable, str(script),
            '--game', DEFAULT_GAME,
            '--room', self.room,
        ]
        if self.table:
            cmd += ['--table', str(self.table)]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,   # stderr → stdout
                stdin=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
            self.running = True
            threading.Thread(target=self._reader, daemon=True).start()
            return True
        except Exception as e:
            self.q.put(f'[BŁĄD URUCHOMIENIA] {e}')
            return False

    # ── wątek odczytu stdout ──────────────────────────────────────────────────
    def _reader(self):
        try:
            for raw in self.proc.stdout:
                if not self.running:
                    break
                line = raw.rstrip('\n')
                if not line:
                    continue
                self._handle_line(line)
        except Exception:
            pass
        finally:
            self.running = False
            self.connected = False
            self.q.put('__DEAD__')

    def _handle_line(self, line: str):
        """Interpretuje specjalne znaczniki protokołu stdout bota."""
        if line == 'CONNECTED':
            self.connected = True
            self.q.put('✅ Połączono')
            return
        if line.startswith('SESSION_OK'):
            self.q.put('🔑 Sesja OK')
            return
        if line.startswith('SESSION_WARN'):
            self.q.put('⚠️  Sesja bez kt=')
            return
        if line.startswith('TABLES_START'):
            self.tables = []
            return
        if line.startswith('TABLE '):
            # TABLE <id> | <params> | <players>
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
            self.q.put('__TABLES__')    # sygnał do GUI: odśwież listę stołów
            return
        if line.startswith('JOINED '):
            try:
                self.table = int(line[7:])
            except ValueError:
                pass
            self.q.put(f'➡️  Stół {self.table}')
            return
        if line == 'TABLES_EMPTY':
            self.q.put('⚠️  Brak stołów')
            return
        if line.startswith('CURRENT_TABLE '):
            self.q.put(f'📍 Stół: {line[14:]}')
            return
        if line.startswith('MSG '):
            self.q.put(line[4:])
            return
        if line.startswith('BOT_START '):
            self.q.put(f'🚀 {line[10:]}')
            return
        # wszystko inne wyświetl wprost
        self.q.put(line)

    # ── wysyłanie stdin ───────────────────────────────────────────────────────
    def send(self, text: str) -> bool:
        try:
            self.proc.stdin.write(text + '\n')
            self.proc.stdin.flush()
            return True
        except Exception:
            return False

    def join_table(self, tid: int) -> bool:
        """Przełącz stół bez restartu."""
        if self.send(f'/join {tid}'):
            self.table = tid
            return True
        return False

    # ── zatrzymanie ───────────────────────────────────────────────────────────
    def stop(self):
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
        status = '🟢' if (self.running and self.connected) else ('🔴' if not self.running else '🟡')
        return f'{status} Bot #{self.idx:02d}  R:{self.room}  T:{self.table or "—"}'


# ─── Aplikacja GUI ────────────────────────────────────────────────────────────

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('🤖 Kurnik Bot Launcher')
        self.root.geometry('1500x850')
        self.root.configure(bg='#1e1e2e')

        self.script = Path(__file__).parent / 'kurnik-ws.py'
        self.bots:   Dict[int, Bot] = {}
        self.sel:    Optional[int]  = None
        self._next_id = 1

        self._build_ui()
        self._tick()

    # ── budowa UI ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TLabelframe',       background='#1e1e2e', foreground='#cdd6f4')
        style.configure('TLabelframe.Label', background='#1e1e2e', foreground='#89b4fa', font=('Segoe UI', 10, 'bold'))
        style.configure('TLabel',  background='#1e1e2e', foreground='#cdd6f4')
        style.configure('TButton', background='#313244', foreground='#cdd6f4', padding=4)
        style.configure('TCheckbutton', background='#1e1e2e', foreground='#cdd6f4')
        style.configure('TEntry',  fieldbackground='#313244', foreground='#cdd6f4', insertcolor='#cdd6f4')
        style.configure('TSpinbox', fieldbackground='#313244', foreground='#cdd6f4')
        style.map('TButton', background=[('active', '#45475a')])

        # ── panel konfiguracji ────────────────────────────────────────────────
        cfg = ttk.LabelFrame(self.root, text='⚙️  Konfiguracja', padding=8)
        cfg.pack(fill=tk.X, padx=10, pady=(10, 0))

        ttk.Label(cfg, text='Botów:').grid(row=0, column=0, padx=4)
        self.v_count = tk.IntVar(value=2)
        ttk.Spinbox(cfg, from_=1, to=50, textvariable=self.v_count, width=5).grid(row=0, column=1, padx=4)

        ttk.Label(cfg, text='Pokój:').grid(row=0, column=2, padx=4)
        self.v_room = tk.StringVar(value=DEFAULT_ROOM)
        ttk.Entry(cfg, textvariable=self.v_room, width=6).grid(row=0, column=3, padx=4)

        ttk.Label(cfg, text='Stół (start):').grid(row=0, column=4, padx=4)
        self.v_table = tk.StringVar(value='0')
        ttk.Entry(cfg, textvariable=self.v_table, width=6).grid(row=0, column=5, padx=4)

        self.v_shared = tk.BooleanVar(value=True)
        ttk.Checkbutton(cfg, text='Wspólny stół', variable=self.v_shared).grid(row=0, column=6, padx=8)

        ttk.Button(cfg, text='▶  Uruchom', command=self._run_bots).grid(row=0, column=7, padx=4)
        ttk.Button(cfg, text='⏹  Stop all', command=self._stop_all).grid(row=0, column=8, padx=4)
        ttk.Button(cfg, text='🗑  Wyczyść', command=self._clear_logs).grid(row=0, column=9, padx=4)
        ttk.Button(cfg, text='💾 Eksport',  command=self._export).grid(row=0, column=10, padx=4)

        # ── główny panel ──────────────────────────────────────────────────────
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        # Lewa kolumna — lista botów
        left = ttk.LabelFrame(paned, text='🤖 Boty', padding=5)
        paned.add(left, weight=1)

        sf = tk.Frame(left, bg='#1e1e2e')
        sf.pack(fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(sf)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.bot_list = tk.Listbox(
            sf, yscrollcommand=sb.set,
            bg='#181825', fg='#cdd6f4',
            selectbackground='#45475a', selectforeground='#cdd6f4',
            font=('Courier New', 10), activestyle='none',
        )
        self.bot_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.bot_list.yview)
        self.bot_list.bind('<<ListboxSelect>>', self._on_select_bot)

        # Środkowa kolumna — szczegóły wybranego bota
        mid = ttk.LabelFrame(paned, text='💬 Wybrany bot', padding=5)
        paned.add(mid, weight=3)

        self.lbl_bot = ttk.Label(mid, text='Wybierz bota z listy', foreground='#6c7086')
        self.lbl_bot.pack(anchor=tk.W, pady=(0, 4))

        # Lista stołów wybranego bota
        tables_frame = ttk.LabelFrame(mid, text='📋 Stoły w pokoju', padding=4)
        tables_frame.pack(fill=tk.X, pady=(0, 6))

        tf2 = tk.Frame(tables_frame, bg='#1e1e2e')
        tf2.pack(fill=tk.X)
        tsb = ttk.Scrollbar(tf2, orient=tk.VERTICAL)
        tsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.table_list = tk.Listbox(
            tf2, yscrollcommand=tsb.set, height=6,
            bg='#181825', fg='#a6e3a1',
            selectbackground='#45475a', selectforeground='#cdd6f4',
            font=('Courier New', 9),
        )
        self.table_list.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tsb.config(command=self.table_list.yview)

        btn_join = ttk.Button(tables_frame, text='➡  Dołącz do zaznaczonego stołu',
                              command=self._join_selected_table)
        btn_join.pack(anchor=tk.W, pady=(4, 0))

        # Ręczny /join
        jf = tk.Frame(mid, bg='#1e1e2e')
        jf.pack(fill=tk.X, pady=2)
        ttk.Label(jf, text='ID stołu:').pack(side=tk.LEFT, padx=(0, 4))
        self.v_join_id = tk.StringVar()
        ttk.Entry(jf, textvariable=self.v_join_id, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(jf, text='➡ Dołącz', command=self._join_manual).pack(side=tk.LEFT)

        # Broadcast do wybranego bota
        bf = ttk.LabelFrame(mid, text='📨 Wyślij do wybranego bota', padding=4)
        bf.pack(fill=tk.X, pady=4)
        ef = tk.Frame(bf, bg='#1e1e2e')
        ef.pack(fill=tk.X)
        self.ent_one = ttk.Entry(ef, font=('Segoe UI', 10))
        self.ent_one.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.ent_one.bind('<Return>', lambda _: self._send_one())
        ttk.Button(ef, text='Wyślij', command=self._send_one).pack(side=tk.LEFT)

        # Log wybranego bota
        ttk.Label(mid, text='Log:').pack(anchor=tk.W)
        self.txt_bot = scrolledtext.ScrolledText(
            mid, state=tk.DISABLED, height=12,
            bg='#181825', fg='#cdd6f4', insertbackground='#cdd6f4',
            font=('Courier New', 9),
        )
        self.txt_bot.pack(fill=tk.BOTH, expand=True)

        # Prawa kolumna — broadcast + zbiorczy log
        right = ttk.LabelFrame(paned, text='📢 Broadcast & Log', padding=5)
        paned.add(right, weight=3)

        bf2 = ttk.LabelFrame(right, text='Wyślij do wszystkich botów', padding=4)
        bf2.pack(fill=tk.X, pady=(0, 6))
        ef2 = tk.Frame(bf2, bg='#1e1e2e')
        ef2.pack(fill=tk.X)
        self.ent_all = ttk.Entry(ef2, font=('Segoe UI', 10))
        self.ent_all.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.ent_all.bind('<Return>', lambda _: self._send_all())
        ttk.Button(ef2, text='📢 Broadcast', command=self._send_all).pack(side=tk.LEFT)

        # Broadcast /join do wszystkich
        jba = ttk.LabelFrame(right, text='Przełącz wszystkie boty na stół', padding=4)
        jba.pack(fill=tk.X, pady=(0, 6))
        ef3 = tk.Frame(jba, bg='#1e1e2e')
        ef3.pack(fill=tk.X)
        self.v_join_all = tk.StringVar()
        ttk.Entry(ef3, textvariable=self.v_join_all, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(ef3, text='➡ Przełącz wszystkie', command=self._join_all).pack(side=tk.LEFT)

        ttk.Label(right, text='Zbiorczy log:').pack(anchor=tk.W)
        self.txt_all = scrolledtext.ScrolledText(
            right, state=tk.DISABLED,
            bg='#181825', fg='#cdd6f4', insertbackground='#cdd6f4',
            font=('Courier New', 9),
        )
        self.txt_all.pack(fill=tk.BOTH, expand=True)

    # ── akcje ─────────────────────────────────────────────────────────────────
    def _run_bots(self):
        room = self.v_room.get().strip()
        if not room.isdigit():
            messagebox.showerror('Błąd', 'Numer pokoju musi być liczbą')
            return
        count  = self.v_count.get()
        shared = self.v_shared.get()
        try:
            base_table = int(self.v_table.get()) if self.v_table.get().strip() else 0
        except ValueError:
            messagebox.showerror('Błąd', 'Numer stołu musi być liczbą (0 = obserwator)')
            return

        for _ in range(count):
            idx   = self._next_id
            table = base_table if shared else idx
            bot   = Bot(idx, room, table)
            if bot.start(self.script):
                self.bots[idx] = bot
                self.bot_list.insert(tk.END, bot.label)
                self._log_all(f'🚀 Uruchomiono Bot #{idx:02d}  R:{room}  T:{table or "—"}')
            else:
                self._log_all(f'❌ Nie udało się uruchomić Bot #{idx:02d}')
            self._next_id += 1

    def _stop_all(self):
        for bot in list(self.bots.values()):
            bot.stop()
        self.bots.clear()
        self.bot_list.delete(0, tk.END)
        self.sel = None
        self._next_id = 1
        self._log_all('⏹  Wszystkie boty zatrzymane')
        self._refresh_table_list([])

    def _on_select_bot(self, _event=None):
        sel = self.bot_list.curselection()
        if not sel:
            return
        # mapuj indeks Listbox → id bota (zachowujemy kolejność wstawiania)
        ids = list(self.bots.keys())
        if sel[0] >= len(ids):
            return
        self.sel = ids[sel[0]]
        bot = self.bots[self.sel]
        self.lbl_bot.config(
            text=f'Bot #{self.sel:02d}  |  Pokój: {bot.room}  |  Stół: {bot.table or "—"}',
            foreground='#89b4fa'
        )
        self._refresh_bot_log(self.sel)
        self._refresh_table_list(bot.tables)

    def _refresh_table_list(self, tables: List[Dict]):
        self.table_list.delete(0, tk.END)
        for t in tables:
            players = t['players'] or '(brak graczy)'
            self.table_list.insert(tk.END, f"ID:{t['id']:>4}  {t['params']:<20}  👥 {players}")

    def _join_selected_table(self):
        """Dołącz wybranego bota do stołu zaznaczonego na liście stołów."""
        if self.sel is None or self.sel not in self.bots:
            return
        sel = self.table_list.curselection()
        if not sel:
            messagebox.showinfo('Info', 'Zaznacz stół na liście')
            return
        bot = self.bots[self.sel]
        table_entry = bot.tables[sel[0]]
        tid = table_entry['id']
        bot.join_table(tid)
        self._log_all(f'➡️  Bot #{self.sel} → stół {tid}')

    def _join_manual(self):
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
        raw = self.v_join_all.get().strip()
        if not raw.isdigit():
            messagebox.showerror('Błąd', 'Podaj numer stołu')
            return
        tid = int(raw)
        cnt = sum(1 for b in self.bots.values() if b.join_table(tid))
        self._log_all(f'➡️  Przełączono {cnt} botów → stół {tid}')

    def _send_one(self):
        if self.sel is None or self.sel not in self.bots:
            return
        msg = self.ent_one.get().strip()
        if msg:
            if self.bots[self.sel].send(msg):
                self.ent_one.delete(0, tk.END)
                self._log_all(f'Bot #{self.sel} ➜ {msg}')
                self._append_bot_log(f'➜ {msg}')

    def _send_all(self):
        msg = self.ent_all.get().strip()
        if msg and self.bots:
            cnt = sum(1 for b in self.bots.values() if b.send(msg))
            self.ent_all.delete(0, tk.END)
            self._log_all(f'📢 BROADCAST ({cnt}): {msg}')

    # ── logowanie ─────────────────────────────────────────────────────────────
    def _log_all(self, msg: str):
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
            w.config(state=tk.NORMAL)
            w.delete('1.0', tk.END)
            w.config(state=tk.DISABLED)

    def _export(self):
        fp = filedialog.asksaveasfilename(defaultextension='.txt',
                                          filetypes=[('Tekst', '*.txt'), ('Wszystkie', '*.*')])
        if fp:
            try:
                with open(fp, 'w', encoding='utf-8') as f:
                    f.write(f'Kurnik.pl Bot Export\nData: {datetime.now()}\n')
                    f.write(f'Boty: {len(self.bots)}\n\n')
                    f.write(self.txt_all.get('1.0', tk.END))
                messagebox.showinfo('OK', f'Zapisano: {fp}')
            except Exception as e:
                messagebox.showerror('Błąd', str(e))

    # ── pętla aktualizacji ────────────────────────────────────────────────────
    def _tick(self):
        dead_bots = []
        ids = list(self.bots.keys())

        for idx in ids:
            bot = self.bots.get(idx)
            if not bot:
                continue
            while True:
                try:
                    msg = bot.q.get_nowait()
                except queue.Empty:
                    break

                if msg == '__DEAD__':
                    dead_bots.append(idx)
                    break

                if msg == '__TABLES__':
                    # odśwież listę stołów jeśli ten bot jest wybrany
                    if self.sel == idx:
                        self._refresh_table_list(bot.tables)
                    self._log_all(f'Bot #{idx}: 📋 {len(bot.tables)} stołów')
                    continue

                bot.lines.append(msg)
                self._log_all(f'Bot #{idx}: {msg}')
                if self.sel == idx:
                    self._append_bot_log(msg)

        # usuń martwe boty i odśwież listę
        if dead_bots:
            for idx in dead_bots:
                self._log_all(f'💀 Bot #{idx} zakończył działanie')
                self.bots.pop(idx, None)
            self._rebuild_bot_list()

        # odśwież etykiety (kolory statusu)
        self._refresh_bot_labels()

        self.root.after(150, self._tick)

    def _rebuild_bot_list(self):
        self.bot_list.delete(0, tk.END)
        for bot in self.bots.values():
            self.bot_list.insert(tk.END, bot.label)

    def _refresh_bot_labels(self):
        ids = list(self.bots.keys())
        for i, bot in enumerate(self.bots.values()):
            try:
                self.bot_list.delete(i)
                self.bot_list.insert(i, bot.label)
            except tk.TclError:
                break


# ─── start ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    root = tk.Tk()
    app = App(root)
    root.mainloop()
