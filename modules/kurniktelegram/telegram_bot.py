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
from bot_manager import BotManager   # nasz silnik bez GUI

# ── Konfiguracja ───────────────────────────────────────────────────────────────

TOKEN  = "8656639154:AAEW8YMvOAeMQ1TRAhdoh3dPBfsqI3KQubY"
HASLO  = "siusiak"     # hasło do logowania przez /start

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)

class PierwszyOK(logging.Filter):
    def __init__(self):
        super().__init__()
        self.pokazany = False

    def filter(self, record):
        if "HTTP/1.1 200 OK" in record.getMessage():
            if not self.pokazany:
                self.pokazany = True
                return True    # przepuść tylko pierwszy raz
            return False       # blokuj kolejne
        return True            # wszystko inne przepuść normalnie

logging.getLogger("httpx").addFilter(PierwszyOK())
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

# ── Globalny stan ──────────────────────────────────────────────────────────────

manager = BotManager()           # jeden manager dla całej aplikacji
autoryzowani: set[int] = set()   # zbiór chat_id które podały poprawne hasło


# ══════════════════════════════════════════════════════════════════════════════
# Dekorator autoryzacji
# ══════════════════════════════════════════════════════════════════════════════

def wymaga_auth(fn):
    """
    Dekorator — opakuj nim każdy handler który ma być chroniony hasłem.
    Jeśli użytkownik nie jest zalogowany, dostanie komunikat o braku dostępu.
    """
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if chat_id not in autoryzowani:
            await update.message.reply_text(
                "🔒 Brak dostępu.\nWpisz /start i podaj hasło."
            )
            return
        return await fn(update, context)
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# Logowanie
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — punkt wejścia.
    Jeśli podano hasło jako argument (/start mojhaslo), od razu sprawdź.
    Jeśli bez argumentu, poproś o hasło.
    """
    chat_id = update.effective_chat.id

    # Jeśli już zalogowany
    if chat_id in autoryzowani:
        await update.message.reply_text(
            "✅ Już jesteś zalogowany!\n"
            "Wpisz /help żeby zobaczyć komendy."
        )
        return

    # Sprawdź czy hasło podano jako argument: /start moje_haslo
    args = context.args
    if args:
        if args[0] == HASLO:
            autoryzowani.add(chat_id)
            await update.message.reply_text(
                "✅ Zalogowano pomyślnie!\n\n"
                "Wpisz /help żeby zobaczyć dostępne komendy."
            )
        else:
            await update.message.reply_text("❌ Złe hasło. Spróbuj ponownie.")
        return

    # Brak argumentu — poproś o hasło
    await update.message.reply_text(
        "🔐 Witaj! Podaj hasło aby uzyskać dostęp:\n"
        "Napisz: /start <hasło>"
    )


async def cmd_wyloguj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wyloguj — usuwa chat_id z autoryzowanych"""
    chat_id = update.effective_chat.id
    autoryzowani.discard(chat_id)
    await update.message.reply_text("👋 Wylogowano.")


# ══════════════════════════════════════════════════════════════════════════════
# Komendy botów Kurnik
# ══════════════════════════════════════════════════════════════════════════════

@wymaga_auth
async def cmd_start_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start_bots <liczba> <pokój> [stół]

    Przykłady:
      /start_bots 3 100      — 3 boty, pokój 100, stół auto
      /start_bots 2 100 5    — 2 boty, pokój 100, stół 5
    """
    args = context.args

    # Walidacja argumentów
    if len(args) < 2:
        await update.message.reply_text(
            "❗ Użycie: /start_bots <liczba> <pokój> [stół]\n"
            "Przykład: /start_bots 3 100 5"
        )
        return

    try:
        count = int(args[0])   # liczba botów
        room  = args[1]        # numer pokoju (string)
        table = int(args[2]) if len(args) >= 3 else 0   # stół (opcjonalny)
    except ValueError:
        await update.message.reply_text("❗ Liczba botów i stół muszą być liczbami całkowitymi.")
        return

    if count < 1 or count > 50:
        await update.message.reply_text("❗ Liczba botów musi być między 1 a 50.")
        return

    await update.message.reply_text(
        f"⏳ Uruchamiam {count} bot{'y' if count in (2,3,4) else 'ów'} "
        f"w pokoju {room}"
        f"{f', stół {table}' if table else ', stół auto'}..."
    )

    try:
        ids = manager.start_bots(count=count, room=room, table=table)
        await update.message.reply_text(
            f"✅ Uruchomiono {len(ids)} botów.\n"
            f"ID: {', '.join(f'#{i}' for i in ids)}\n\n"
            f"Użyj /status żeby sprawdzić stan."
        )
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ Błąd: {e}")


@wymaga_auth
async def cmd_stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stop_bot <id>
    Przykład: /stop_bot 3
    """
    args = context.args
    if not args:
        await update.message.reply_text("❗ Użycie: /stop_bot <id>\nPrzykład: /stop_bot 3")
        return

    try:
        idx = int(args[0])
    except ValueError:
        await update.message.reply_text("❗ ID musi być liczbą.")
        return

    if manager.stop_bot(idx):
        await update.message.reply_text(f"⏹  Bot #{idx} zatrzymany.")
    else:
        await update.message.reply_text(f"❗ Bot #{idx} nie istnieje lub już jest zatrzymany.")


@wymaga_auth
async def cmd_stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stop_all — zatrzymuje wszystkie boty"""
    count = manager.stop_all()
    if count:
        await update.message.reply_text(f"⏹  Zatrzymano {count} botów.")
    else:
        await update.message.reply_text("ℹ️ Brak aktywnych botów.")


@wymaga_auth
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status — lista wszystkich aktywnych botów"""
    lines = manager.status()
    if not lines:
        await update.message.reply_text("ℹ️ Brak aktywnych botów.\nUżyj /start_bots żeby uruchomić.")
        return
    tekst = "📊 *Aktywne boty:*\n\n" + "\n".join(lines)
    await update.message.reply_text(tekst, parse_mode="Markdown")


@wymaga_auth
async def cmd_logi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /logi <id> — ostatnie 10 logów wybranego bota
    Przykład: /logi 2
    """
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
    """
    /wsio <wiadomość> — wysyła wiadomość do WSZYSTKICH aktywnych botów
    Przykład: /wsio Hej, dobry wieczór!
    """
    if not context.args:
        await update.message.reply_text(
            "❗ Użycie: /wsio <wiadomość>\n"
            "Przykład: /wsio Hej wszystkim!"
        )
        return

    # Sklej wszystkie argumenty z powrotem w jedną wiadomość
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
    """/help — lista wszystkich komend"""
    await update.message.reply_text(
        "🤖 *Komendy Kurnik Bot Launcher*\n\n"
        "*Zarządzanie botami:*\n"
        "`/start_bots 3 100`   — 3 boty, pokój 100\n"
        "`/start_bots 2 100 5` — 2 boty, pokój 100, stół 5\n"
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
# Callback logów → Telegram (opcjonalne powiadomienia)
# ══════════════════════════════════════════════════════════════════════════════

# Jeśli chcesz dostawać logi botów na Telegram, odkomentuj poniższy blok
# i ustaw CHAT_ID_DO_LOGOW na swój chat_id (możesz go poznać pisząc /start).
#
# CHAT_ID_DO_LOGOW = 123456789
#
# async def wyslij_log(bot_app, msg: str):
#     await bot_app.bot.send_message(chat_id=CHAT_ID_DO_LOGOW, text=msg)
#
# Po zbudowaniu app:
# manager.set_log_callback(lambda msg: wyslij_log(app, msg))


# ══════════════════════════════════════════════════════════════════════════════
# Uruchomienie
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(TOKEN).build()

    # Komendy autoryzacji (dostępne bez logowania)
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("wyloguj",  cmd_wyloguj))

    # Komendy chronione hasłem
    app.add_handler(CommandHandler("start_bots", cmd_start_bots))
    app.add_handler(CommandHandler("stop_bot",   cmd_stop_bot))
    app.add_handler(CommandHandler("stop_all",   cmd_stop_all))
    app.add_handler(CommandHandler("status",     cmd_status))
    app.add_handler(CommandHandler("logi",       cmd_logi))
    app.add_handler(CommandHandler("wsio",       cmd_wsio))
    app.add_handler(CommandHandler("help",       cmd_help))

    # Ignoruj zwykłe wiadomości tekstowe (nie komendy)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        lambda u, c: u.message.reply_text("Wpisz /help żeby zobaczyć dostępne komendy.")
    ))

    log.info("Bot uruchomiony. Zatrzymaj przez Ctrl+C")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
