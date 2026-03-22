#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot_manager.py — Rdzeń zarządzający botami Kurnik (bez GUI).
Importowany przez telegram_bot.py jako moduł.
"""

import subprocess, threading, queue, sys, io, asyncio, logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

log = logging.getLogger(__name__)

DEFAULT_GAME = 'kalambury'

# Ścieżka do skryptu bota Kurnik — musi być w tym samym folderze
KURNIK_SCRIPT = Path(__file__).parent / 'kurnik-ws.py'


# ══════════════════════════════════════════════════════════════════════════════
# Klasa pojedynczego bota
# ══════════════════════════════════════════════════════════════════════════════

class Bot:
    def __init__(self, idx: int, room: str, table: int):
        self.idx   = idx        # numer bota (unikalny)
        self.room  = room       # numer pokoju na Kurniku
        self.table = table      # numer stołu (0 = brak)
        self.proc: Optional[subprocess.Popen] = None
        self.q: queue.Queue = queue.Queue()   # kolejka komunikatów z procesu
        self.running   = False  # czy proces żyje
        self.connected = False  # czy połączony z Kurnikiem
        self.lines: List[str] = []  # historia logów tego bota

    # ── Uruchomienie ───────────────────────────────────────────────────────────

    def start(self, script: Path = KURNIK_SCRIPT) -> bool:
        """Uruchamia podproces kurnik-ws.py z odpowiednimi argumentami."""
        cmd = [sys.executable, str(script), '--game', DEFAULT_GAME, '--room', self.room]
        if self.table:
            cmd += ['--table', str(self.table)]   # podaj stół jeśli podano
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
            )
            self.running = True
            # Osobny wątek czyta stdout procesu — nie blokuje event loop
            threading.Thread(target=self._reader, daemon=True).start()
            return True
        except Exception as e:
            self.q.put(f'[BŁĄD URUCHOMIENIA] {e}')
            return False

    # ── Czytanie stdout procesu ────────────────────────────────────────────────

    def _reader(self):
        """Wątek czytający stdout kurnik-ws.py linijka po linijce."""
        try:
            for raw in self.proc.stdout:
                if not self.running:
                    break
                line = raw.rstrip('\n')
                if line:
                    self._handle_line(line)   # parsuj i wrzuć do kolejki
        except Exception:
            pass
        finally:
            # Proces zakończył działanie
            self.running   = False
            self.connected = False
            self.q.put('__DEAD__')   # sygnał dla BotManagera

    def _handle_line(self, line: str):
        """Parsuje linię z procesu i wrzuca czytelny komunikat do kolejki."""
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
        if line.startswith('EXT '):
            parts = line[4:].split(maxsplit=1)
            self.q.put(f'📤 → stół {parts[0]}: {parts[1]}' if len(parts) == 2 else line)
            return
        if line.startswith('PLAYER_JOIN '):
            self.q.put(f'__PLAYER_JOIN__{line[12:]}')
            return
        self.q.put(line)   # nieznana linia — przepuść bez zmian

    # ── Komunikacja z procesem ─────────────────────────────────────────────────

    def send(self, text: str) -> bool:
        """Wysyła komendę do stdin procesu kurnik-ws.py."""
        try:
            self.proc.stdin.write(text + '\n')
            self.proc.stdin.flush()
            return True
        except Exception:
            return False

    def join_table(self, tid: int) -> bool:
        """Każe botowi dołączyć do stołu o podanym ID."""
        if self.send(f'/join {tid}'):
            self.table = tid
            return True
        return False

    def leave_table(self) -> bool:
        """Każe botowi wyjść ze stołu."""
        if self.send('/join 0'):
            self.table = 0
            return True
        return False

    def stop(self):
        """Zatrzymuje bota — najpierw graceful (/quit), potem kill."""
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
        """Zwraca czytelny opis bota z ikoną statusu."""
        if self.running and self.connected:
            icon = '🟢'
        elif not self.running:
            icon = '🔴'
        else:
            icon = '🟡'   # running ale jeszcze nie connected
        return f'{icon} Bot #{self.idx:02d}  Pokój:{self.room}  Stół:{self.table or "—"}'


# ══════════════════════════════════════════════════════════════════════════════
# Menedżer botów — główna klasa używana przez telegram_bot.py
# ══════════════════════════════════════════════════════════════════════════════

class BotManager:
    """
    Zarządza instancjami botów Kurnik.
    Używany przez telegram_bot.py jako silnik.

    Użycie:
        manager = BotManager()
        manager.set_log_callback(async_fn)   # opcjonalnie: callback do Telegrama
        manager.start_bots(count=3, room='100', table=5)
        manager.broadcast('Hej!')
        manager.stop_all()
    """

    def __init__(self):
        self.bots: Dict[int, Bot] = {}   # słownik idx → Bot
        self._next_id = 1                # licznik ID botów
        self._lock = threading.Lock()    # mutex dla operacji na bots

        # Callback wywoływany przy każdym logu bota.
        # Ustaw przez set_log_callback() jeśli chcesz dostawać logi na Telegram.
        self._log_cb: Optional[Callable[[str], Any]] = None

        # Uruchom wątek który opróżnia kolejki wszystkich botów
        threading.Thread(target=self._pump_loop, daemon=True).start()

    # ── Konfiguracja callbacku ─────────────────────────────────────────────────

    def set_log_callback(self, cb: Callable[[str], Any]):
        """
        Ustaw funkcję wywoływaną przy każdym zdarzeniu bota.
        Może być coroutine (async) albo zwykła funkcja.
        Przykład: manager.set_log_callback(send_to_telegram)
        """
        self._log_cb = cb

    def _emit(self, msg: str):
        """Loguje wewnętrznie i wywołuje callback jeśli ustawiony."""
        log.info(msg)
        if self._log_cb:
            try:
                result = self._log_cb(msg)
                # Jeśli callback jest coroutine, uruchom go w event loop
                if asyncio.iscoroutine(result):
                    asyncio.run_coroutine_threadsafe(
                        result,
                        asyncio.get_event_loop(),
                    )
            except Exception as e:
                log.warning(f'Log callback error: {e}')

    # ── Wątek pompujący kolejki ────────────────────────────────────────────────

    def _pump_loop(self):
        """
        Działa w tle — co 100ms opróżnia kolejki wszystkich botów.
        Przetwarza komunikaty: logi, śmierć bota, dołączenie gracza.
        """
        import time
        while True:
            with self._lock:
                dead = []
                for idx, bot in self.bots.items():
                    while True:
                        try:
                            msg = bot.q.get_nowait()
                        except queue.Empty:
                            break

                        if msg == '__DEAD__':
                            self._emit(f'💀 Bot #{idx} zakończył działanie')
                            dead.append(idx)
                            break

                        if msg == '__TABLES__':
                            self._emit(f'Bot #{idx}: 📋 {len(bot.tables)} stołów')
                            continue

                        if msg.startswith('__PLAYER_JOIN__'):
                            # Tutaj możesz podpiąć logikę white/blacklisty
                            self._emit(f'Bot #{idx}: 👤 gracz dołączył → {msg[15:]}')
                            continue

                        # Zwykły log — zapamiętaj i wyślij
                        bot.lines.append(msg)
                        self._emit(f'Bot #{idx}: {msg}')

                for idx in dead:
                    self.bots.pop(idx, None)

            time.sleep(0.1)   # 100ms przerwa żeby nie palić CPU

    # ── Publiczne API ──────────────────────────────────────────────────────────

    def start_bots(self, count: int, room: str, table: int = 0) -> List[int]:
        """
        Uruchamia `count` botów w pokoju `room`, opcjonalnie na stole `table`.
        Zwraca listę ID uruchomionych botów.

        Przykład: start_bots(3, '100', table=5)
        """
        if not KURNIK_SCRIPT.exists():
            raise FileNotFoundError(
                f'Nie znaleziono kurnik-ws.py w: {KURNIK_SCRIPT}\n'
                'Umieść kurnik-ws.py w tym samym folderze co bot_manager.py'
            )

        started = []
        with self._lock:
            for _ in range(count):
                idx = self._next_id
                self._next_id += 1
                bot = Bot(idx=idx, room=room, table=table)
                if bot.start():
                    self.bots[idx] = bot
                    started.append(idx)
                    self._emit(f'🚀 Uruchomiono Bot #{idx} | pokój={room} stół={table or "auto"}')
                else:
                    self._emit(f'❌ Nie udało się uruchomić Bot #{idx}')
        return started

    def stop_bot(self, idx: int) -> bool:
        """
        Zatrzymuje bota o podanym numerze.
        Zwraca True jeśli bot istniał, False jeśli nie.
        """
        with self._lock:
            bot = self.bots.get(idx)
            if not bot:
                return False
            bot.stop()
            self.bots.pop(idx, None)
            self._emit(f'⏹  Bot #{idx} zatrzymany')
            return True

    def stop_all(self) -> int:
        """
        Zatrzymuje wszystkie boty.
        Zwraca liczbę zatrzymanych botów.
        """
        with self._lock:
            count = len(self.bots)
            for bot in self.bots.values():
                bot.stop()
            self.bots.clear()
            self._emit(f'⏹  Zatrzymano wszystkich botów ({count})')
            return count

    def broadcast(self, text: str) -> int:
        """
        Wysyła wiadomość text do wszystkich aktywnych botów.
        Zwraca liczbę botów którym wysłano.
        """
        sent = 0
        with self._lock:
            for bot in self.bots.values():
                if bot.running and bot.send(text):
                    sent += 1
        self._emit(f'📢 Broadcast do {sent} botów: {text}')
        return sent

    def send_to_bot(self, idx: int, text: str) -> bool:
        """Wysyła wiadomość do konkretnego bota."""
        with self._lock:
            bot = self.bots.get(idx)
            if not bot or not bot.running:
                return False
            return bot.send(text)

    def status(self) -> List[str]:
        """
        Zwraca listę czytelnych opisów wszystkich botów.
        Pusty list = brak aktywnych botów.
        """
        with self._lock:
            if not self.bots:
                return []
            return [bot.label for bot in self.bots.values()]

    def get_logs(self, idx: int, last: int = 10) -> List[str]:
        """Zwraca ostatnie `last` linii logów bota o podanym ID."""
        with self._lock:
            bot = self.bots.get(idx)
            if not bot:
                return []
            return bot.lines[-last:]
