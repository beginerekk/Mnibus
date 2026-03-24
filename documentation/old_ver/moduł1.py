#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_bot.py — Pilot Telegram do sterowania botami Kurnik.
Wymaga: pip install python-telegram-bot[job-queue]

Pliki w tym samym folderze:
  bot_manager.py  — silnik botów Kurnik
  kurnik-ws.py    — właściwy skrypt bota Kurnik

Komendy:
  /start              — logowanie hasłem
  /start_bots 3 100 5 — uruchom 3 boty, pokój 100, stół 5
  /start_bots 2 100   — uruchom 2 boty, pokój 100, stół auto
  /stop_bot 3         — zatrzymaj bota nr 3
  /stop_all           — zatrzymaj wszystkie
  /status             — lista aktywnych botów
  /logi 2             — ostatnie 10 logów bota nr 2
  /wsio Hej wszystkim — broadcast do wszystkich botów
"""

import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from bot_manager import BotManager   # import silnika zarządzającego botami (oddzielna logika biznesowa)

# ── Konfiguracja ───────────────────────────────────────────────────────────────

TOKEN  = "8656639154:AAEW8YMvOAeMQ1TRAhdoh3dPBfsqI3KQubY"  # token API Telegram — identyfikuje Twojego bota
HASLO  = "siusiak"     # proste hasło do autoryzacji użytkownika (zabezpieczenie przed obcymi)
room = 100
# ── Logging ────────────────────────────────────────────────────────────────────

# Konfiguracja globalnego logowania — ustawia format i poziom logów
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)

class PierwszyOK(logging.Filter):
    # Ten filtr ogranicza spam w logach HTTP — przepuszcza tylko pierwszy "200 OK"
    def __init__(self):
        super().__init__()
        self.pokazany = False  # flaga czy pierwszy OK już był pokazany

    def filter(self, record):
        # Jeśli log zawiera "200 OK"
        if "HTTP/1.1 200 OK" in record.getMessage():
            if not self.pokazany:
                self.pokazany = True
                return True    # przepuść tylko pierwszy raz
            return False       # blokuj kolejne żeby nie spamować
        return True            # wszystkie inne logi przepuszczaj normalnie

# Dodanie filtra do bibliotek HTTP używanych przez telegram-bot
logging.getLogger("httpx").addFilter(PierwszyOK())
logging.getLogger("httpcore").setLevel(logging.WARNING)  # wyciszenie mniej ważnych logów

log = logging.getLogger(__name__)  # logger dla tego pliku

# ── Globalny stan ──────────────────────────────────────────────────────────────

manager = BotManager()           # jeden centralny manager zarządzający wszystkimi botami
# trzymanie go globalnie pozwala współdzielić stan między komendami

autoryzowani: set[int] = set()   # zbiór ID czatów (użytkowników), którzy się zalogowali


# ══════════════════════════════════════════════════════════════════════════════
# Dekorator autoryzacji
# ══════════════════════════════════════════════════════════════════════════════

def wymaga_auth(fn):
    """
    Dekorator — opakowuje funkcję (handler komendy).
    Sprawdza czy użytkownik jest zalogowany.
    Jeśli nie — blokuje dostęp.

    Dlaczego dekorator?
    → żeby nie powtarzać tego samego kodu w każdej komendzie.
    """
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id  # unikalne ID użytkownika/czatu
        if chat_id not in autoryzowani:
            # jeśli nie ma dostępu — informujemy użytkownika
            await update.message.reply_text(
                "🔒 Brak dostępu.\nWpisz /start i podaj hasło."
            )
            return
        return await fn(update, context)  # jeśli OK — wykonaj oryginalną funkcję
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# Logowanie
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — punkt wejścia do bota.

    Obsługuje 2 scenariusze:
    1. /start hasło  → logowanie natychmiastowe
    2. /start        → prośba o podanie hasła
    """
    chat_id = update.effective_chat.id

    # Jeśli użytkownik już zalogowany — nie rób nic więcej
    if chat_id in autoryzowani:
        await update.message.reply_text(
            "✅ Już jesteś zalogowany!\n"
            "Wpisz /help żeby zobaczyć komendy."
        )
        return

    # Pobranie argumentów wpisanych po komendzie
    args = context.args
    if args:
        # jeśli podano hasło — porównaj z zapisanym
        if args[0] == HASLO:
            autoryzowani.add(chat_id)  # zapamiętaj użytkownika
            await update.message.reply_text(
                "✅ Zalogowano pomyślnie!\n\n"
                "Wpisz /help żeby zobaczyć dostępne komendy."
            )
        else:
            await update.message.reply_text("❌ Złe hasło. Spróbuj ponownie.")
        return

    # jeśli nie podano hasła — poinstruuj użytkownika
    await update.message.reply_text(
        "🔐 Witaj! Podaj hasło aby uzyskać dostęp:\n"
        "Napisz: /start <hasło>"
    )


async def cmd_wyloguj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /wyloguj — usuwa użytkownika z listy autoryzowanych
    Dzięki temu traci dostęp do komend chronionych
    """
    chat_id = update.effective_chat.id
    autoryzowani.discard(chat_id)  # discard nie rzuca błędu jeśli element nie istnieje
    await update.message.reply_text("👋 Wylogowano.")


# ══════════════════════════════════════════════════════════════════════════════
# Komendy botów Kurnik
# ══════════════════════════════════════════════════════════════════════════════

@wymaga_auth
async def cmd_start_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Uruchamia określoną liczbę botów.

    Dlaczego tutaj walidacja?
    → żeby nie wysyłać błędnych danych do BotManagera
    → chroni przed crashami i złymi inputami
    """
    args = context.args

    # sprawdzenie minimalnej liczby argumentów
    if len(args) < 2:
        await update.message.reply_text(
            "❗ Użycie: /start_bots <liczba> <pokój> [stół]\n"
            "Przykład: /start_bots 3 100 5"
        )
        return

    try:
        count = int(args[0])   # ile botów uruchomić
      #  room  = args[1]        # pokój (string — bo może mieć różne formaty)
        table = int(args[2]) if len(args) >= 3 else 0   # opcjonalny numer stołu
    except ValueError:
        await update.message.reply_text("❗ Liczba botów i stół muszą być liczbami całkowitymi.")
        return

    # ograniczenie bezpieczeństwa — żeby nie odpalić np. 1000 botów
    if count < 1 or count > 50:
        await update.message.reply_text("❗ Liczba botów musi być między 1 a 50.")
        return

    # informacja dla użytkownika (UX)
    await update.message.reply_text(
        f"⏳ Uruchamiam {count} bot{'y' if count in (2,3,4) else 'ów'} "
        f"w pokoju {room}"
        f"{f', stół {table}' if table else ', stół auto'}..."
    )

    try:
        # delegacja do managera — logika uruchamiania jest poza tym plikiem
        ids = manager.start_bots(count=count, room=room, table=table)
        await update.message.reply_text(
            f"✅ Uruchomiono {len(ids)} botów.\n"
            f"ID: {', '.join(f'#{i}' for i in ids)}\n\n"
            f"Użyj /status żeby sprawdzić stan."
        )
    except FileNotFoundError as e:
        # obsługa błędu np. brak pliku bota
        await update.message.reply_text(f"❌ Błąd: {e}")


@wymaga_auth
async def cmd_stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zatrzymuje jednego bota po ID"""
    args = context.args
    if not args:
        await update.message.reply_text("❗ Użycie: /stop_bot <id>\nPrzykład: /stop_bot 3")
        return

    try:
        idx = int(args[0])
    except ValueError:
        await update.message.reply_text("❗ ID musi być liczbą.")
        return

    # wywołanie managera
    if manager.stop_bot(idx):
        await update.message.reply_text(f"⏹  Bot #{idx} zatrzymany.")
    else:
        await update.message.reply_text(f"❗ Bot #{idx} nie istnieje lub już jest zatrzymany.")


@wymaga_auth
async def cmd_stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zatrzymuje wszystkie boty — szybkie czyszczenie"""
    count = manager.stop_all()
    if count:
        await update.message.reply_text(f"⏹  Zatrzymano {count} botów.")
    else:
        await update.message.reply_text("ℹ️ Brak aktywnych botów.")


@wymaga_auth
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zwraca listę aktywnych botów"""
    lines = manager.status()
    if not lines:
        await update.message.reply_text("ℹ️ Brak aktywnych botów.\nUżyj /start_bots żeby uruchomić.")
        return
    tekst = "📊 *Aktywne boty:*\n\n" + "\n".join(lines)
    await update.message.reply_text(tekst, parse_mode="Markdown")


@wymaga_auth
async def cmd_logi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zwraca ostatnie logi konkretnego bota"""
    args = context.args
    if not args:
        await update.message.reply_text("❗ Użycie: /logi <id>\nPrzykład: /logi 2")
        return

    try:
        idx = int(args[0])
    except ValueError:
        await update.message.reply_text("❗ ID musi być liczbą.")
        return

    lines = manager.get_logs(idx, last=10)
    if not lines:
        await update.message.reply_text(f"❗ Bot #{idx} nie istnieje lub nie ma logów.")
        return

    tekst = f"📋 *Logi Bot #{idx} (ostatnie {len(lines)}):*\n\n"
    tekst += "\n".join(f"`{l}`" for l in lines)
    await update.message.reply_text(tekst, parse_mode="Markdown")


@wymaga_auth
async def cmd_wsio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wysyła wiadomość do wszystkich botów"""
    if not context.args:
        await update.message.reply_text(
            "❗ Użycie: /wsio <wiadomość>\n"
            "Przykład: /wsio Hej wszystkim!"
        )
        return

    # składanie wiadomości z argumentów
    wiadomosc = " ".join(context.args)
    sent = manager.broadcast(wiadomosc)

    if sent:
        await update.message.reply_text(
            f"📢 Wysłano do {sent} bot{'a' if sent == 1 else 'ów'}:\n_{wiadomosc}_",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "ℹ️ Brak aktywnych botów do wysłania.\nUżyj /start_bots żeby uruchomić."
        )


@wymaga_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wyświetla pomoc — lista komend"""
    await update.message.reply_text(
        "🤖 *Komendy Kurnik Bot Launcher*\n\n"
        "*Zarządzanie botami:*\n"
        "`/start_bots <liczba botów> <numer stołu>`   — 3 boty, stół 100\n"
        "`/stop_bot 3`         — zatrzymaj bota nr 3\n"
        "`/stop_all`           — zatrzymaj wszystkie\n\n"
        "*Informacje:*\n"
        "`/status`             — lista aktywnych botów\n"
        "`/logi 2`             — ostatnie logi bota nr 2\n\n"
        "*Komunikacja:*\n"
        "`/wsio <tekst>`       — broadcast do wszystkich botów\n\n"
        "*Konto:*\n"
        "`/wyloguj`            — wyloguj się",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════════════════════════════════════
# Uruchomienie
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # Tworzenie aplikacji Telegram (główna pętla zdarzeń)
    app = Application.builder().token(TOKEN).build()

    # Rejestracja handlerów — przypisanie komend do funkcji
    # Najpierw komendy bez autoryzacji
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("wyloguj",  cmd_wyloguj))

    # Komendy wymagające logowania
    app.add_handler(CommandHandler("start_bots", cmd_start_bots))
    app.add_handler(CommandHandler("stop_bot",   cmd_stop_bot))
    app.add_handler(CommandHandler("stop_all",   cmd_stop_all))
    app.add_handler(CommandHandler("status",     cmd_status))
    app.add_handler(CommandHandler("logi",       cmd_logi))
    app.add_handler(CommandHandler("wsio",       cmd_wsio))
    app.add_handler(CommandHandler("help",       cmd_help))

    # Handler dla zwykłych wiadomości (nie-komend)
    # Dlaczego na końcu?
    # → żeby nie przechwycił komend wcześniej
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        lambda u, c: u.message.reply_text("Wpisz /help żeby zobaczyć dostępne komendy.")
    ))

    log.info("Bot uruchomiony. Zatrzymaj przez Ctrl+C")

    # Start pętli polling — bot nasłuchuje wiadomości
    # drop_pending_updates=True → ignoruje stare wiadomości po restarcie
    app.run_polling(drop_pending_updates=True)


# Standardowy entrypoint Pythona
# Dzięki temu plik można też importować bez uruchamiania bota
if __name__ == "__main__":
    main()
