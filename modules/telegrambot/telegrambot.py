#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_bot.py — Starter bota Telegram
Biblioteka: python-telegram-bot v20+  (pip install python-telegram-bot[job-queue])

Funkcje:
  ✅ Komendy (/start, /help, /info)
  ✅ Reakcja na słowa kluczowe
  ✅ Przyciski inline (menu)
  ✅ Automatyczne wiadomości co X sekund (JobQueue)
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# ── Konfiguracja ───────────────────────────────────────────────────────────────

TOKEN = "8656639154:AAEW8YMvOAeMQ1TRAhdoh3dPBfsqI3KQubY"   # Token od @BotFather

class PierwszyOK(logging.Filter):
    def __init__(self):
        super().__init__()
        self.pokazany = False

    def filter(self, record):
        if "HTTP/1.1 200 OK" in record.getMessage():
            if not self.pokazany:
                self.pokazany = True
                return True   # przepuść pierwszy raz
            return False      # blokuj kolejne
        return True           # wszystko inne przepuść normalnie

# Podepnij filtr pod logger httpx
httpx_logger = logging.getLogger("httpx")
httpx_logger.addFilter(PierwszyOK())


# Włącz logowanie (zobaczysz błędy w konsoli)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)


# ══════════════════════════════════════════════════════════════════════════════
# KOMENDY
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wywoływana gdy użytkownik napisze /start"""
    imie = update.effective_user.first_name
    await update.message.reply_text(
        f"Cześć, {imie}! 👋\n"
        "Jestem botem. Oto co umiem:\n\n"
        "/help — lista komend\n"
        "/menu — pokaż przyciski\n"
        "/info — informacje o bocie"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wywoływana gdy użytkownik napisze /help"""
    await update.message.reply_text(
        "📋 *Lista komend:*\n\n"
        "/start — powitanie\n"
        "/help — ta lista\n"
        "/menu — interaktywne menu\n"
        "/info — informacje\n\n"
        "Możesz też napisać: *hej*, *pomoc* lub *cześć*",
        parse_mode="Markdown",
    )


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wywoływana gdy użytkownik napisze /info"""
    await update.message.reply_text(
        "🤖 *Informacje o bocie*\n\n"
        "Wersja: 1.0\n"
        "Biblioteka: python-telegram-bot v20+\n"
        "Status: działa ✅",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════════════════════════════════════
# PRZYCISKI INLINE (menu)
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wysyła wiadomość z przyciskami inline"""

    # Definiujesz przyciski jako listę list (każda lista = rząd przycisków)
    klawiatura = [
        [
            InlineKeyboardButton("🐔 O Kurniku",   callback_data="kurnik"),
            InlineKeyboardButton("📊 Statystyki",   callback_data="statsy"),
        ],
        [
            InlineKeyboardButton("⚙️ Ustawienia",  callback_data="ustawienia"),
            InlineKeyboardButton("❓ Pomoc",        callback_data="pomoc"),
        ],
        [
            InlineKeyboardButton("🌐 Kurnik.pl",   url="https://kurnik.pl"),
        ],
    ]
    markup = InlineKeyboardMarkup(klawiatura)

    await update.message.reply_text(
        "Wybierz opcję z menu:",
        reply_markup=markup,
    )


async def on_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Wywoływana gdy użytkownik kliknie dowolny przycisk inline.
    update.callback_query.data zawiera wartość 'callback_data' przycisku.
    """
    query = update.callback_query
    await query.answer()   # WAŻNE: zawsze odpowiedz na callback, żeby zniknął "spinner"

    data = query.data

    if data == "kurnik":
        tekst = "🐔 Kurnik.pl to polska platforma gier online!"
    elif data == "statsy":
        tekst = "📊 Statystyki:\nBotów aktywnych: 3\nWiadomości wysłanych: 42"
    elif data == "ustawienia":
        tekst = "⚙️ Ustawienia nie są jeszcze dostępne."
    elif data == "pomoc":
        tekst = "❓ Napisz /help żeby zobaczyć listę komend."
    else:
        tekst = f"Kliknąłeś: {data}"

    # Edytuje oryginalną wiadomość zamiast wysyłać nową
    await query.edit_message_text(tekst)


# ══════════════════════════════════════════════════════════════════════════════
# REAKCJA NA SŁOWA KLUCZOWE
# ══════════════════════════════════════════════════════════════════════════════

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Wywoływana dla każdej zwykłej wiadomości (nie komendy).
    Sprawdzamy słowa kluczowe i odpowiadamy.
    """
    tekst = update.message.text.lower()

    if any(slowo in tekst for slowo in ["hej", "cześć", "siema", "witaj", "hello"]):
        imie = update.effective_user.first_name
        await update.message.reply_text(f"Hej, {imie}! 👋 Napisz /menu żeby zobaczyć opcje.")

    elif any(slowo in tekst for slowo in ["pomoc", "help", "co umiesz"]):
        await update.message.reply_text("Napisz /help żeby zobaczyć co potrafię!")

    elif "kurnik" in tekst:
        await update.message.reply_text("🐔 Chcesz coś wiedzieć o Kurniku? Napisz /info")

    else:
        # Odpowiedź domyślna — możesz ją usunąć jeśli bot ma milczeć
        await update.message.reply_text(
            f"Napisałeś: \"{update.message.text}\"\n"
            "Nie rozumiem tego. Spróbuj /help"
        )


# ══════════════════════════════════════════════════════════════════════════════
# AUTOMATYCZNE WIADOMOŚCI (JobQueue)
# ══════════════════════════════════════════════════════════════════════════════

async def auto_wiadomosc(context: ContextTypes.DEFAULT_TYPE):
    """
    Ta funkcja jest wywoływana automatycznie co X sekund przez JobQueue.
    context.job.data zawiera dane przekazane przy tworzeniu joba.
    """
    chat_id = context.job.data
    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ Automatyczna wiadomość od bota!"
    )


async def cmd_start_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /autostart — uruchamia automatyczne wiadomości co 30 sekund.
    W prawdziwym bocie możesz usunąć tę komendę i uruchamiać joba
    w innym miejscu (np. przy starcie bota).
    """
    chat_id = update.effective_chat.id

    # Usuń poprzedni job dla tego chatu (jeśli istniał)
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in jobs:
        job.schedule_removal()

    # Utwórz nowy job: co 30 sekund, pierwszy raz po 10 sekundach
    context.job_queue.run_repeating(
        callback=auto_wiadomosc,
        interval=30,        # co ile sekund (można też podać timedelta)
        first=10,           # pierwsze uruchomienie po ilu sekundach
        data=chat_id,       # dane dostępne w context.job.data
        name=str(chat_id),  # nazwa joba (używamy do usuwania)
    )
    await update.message.reply_text("✅ Automatyczne wiadomości włączone (co 30 sek)")


async def cmd_stop_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/autostop — wyłącza automatyczne wiadomości"""
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in jobs:
        job.schedule_removal()
    await update.message.reply_text("⛔ Automatyczne wiadomości wyłączone")


# ══════════════════════════════════════════════════════════════════════════════
# URUCHOMIENIE BOTA
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # Zbuduj aplikację
    app = Application.builder().token(TOKEN).build()

    # Zarejestruj handlery komend
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("info",       cmd_info))
    app.add_handler(CommandHandler("menu",       cmd_menu))
    app.add_handler(CommandHandler("autostart",  cmd_start_auto))
    app.add_handler(CommandHandler("autostop",   cmd_stop_auto))

    # Zarejestruj handler przycisków inline
    app.add_handler(CallbackQueryHandler(on_button_click))

    # Zarejestruj handler wiadomości tekstowych (MUSI być ostatni!)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    # Uruchom polling (bot czeka na wiadomości)
    print("Bot uruchomiony. Zatrzymaj przez Ctrl+C")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
