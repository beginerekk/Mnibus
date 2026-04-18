# 🤖 Kurnik Bot Launcher — Wersja 1.2.0

Zaawansowany manager botów dla Kurnik.pl z obsługą automatycznego rysowania (Kalambury), konfiguracją whitelist/blacklist, grupami graczy i pulami wiadomości.

---

## ✨ Co Nowego w v1.2.0?

### 🔧 Naprawione Komendy
- ✅ **`/ext`** — Teraz wysyła na aktualny stół (zamiast wymagać ID)
- ✅ **`/tables`** — Odświeża listę stołów (z debug output)

### 🎨 Nowe Funkcje
- 🔄 **Przycisk Odświeżenia Stołów** — Ręczne odświeżenie listy
- 🖌️ **Obsługa Rysowania (Kalambury)**
  - Kody `MSG_GAME_STATE (90)` i `MSG_TAB_DRAW (92)` już przetwarzane
  - Wskazówki rysowania wyświetlane w logu
  - Słowa do zgadnięcia wyświetlane w logu
- ✅ **Checkbox "Auto-rysuj"** w toolbarze
- 📂 **Import Obrazu do Rysowania** — PNG/JPG
- 📚 **Pełna Dokumentacja Protokołu** — `SERVER_PROTOCOL.md`

---

## 📖 Dokumentacja

### 📘 Plik Przewodnika
**`GUIDE.md`** — Kompletny przewodnik użytkownika z przykładami

### 🔐 Protokół Serwera
**`SERVER_PROTOCOL.md`** — Dokumentacja wszystkich kodów serwera:
- MSG_PING, MSG_PONG — Heartbeat
- MSG_TABLES, MSG_JOIN_TAB — Zarządzanie stołami
- MSG_CHAT, MSG_PLAYER_ACTION — Komunikacja
- MSG_GAME_STATE, MSG_TAB_DRAW — Rysowanie w Kalambury
- I wiele więcej...

### 📋 Historia Zmian
**`CHANGELOG.md`** — Pełna historia wszystkich zmian i implementacji

---

## 🚀 Szybki Start

### 1. Instalacja
```bash
pip install PyQt6 websockets requests
```

### 2. Uruchomienie
```bash
python launcher.py
```

### 3. Konfiguracja Botów
```
1. Ustaw liczbę botów (np. 5)
2. Wybierz pokój (domyślnie: 100)
3. Kliknij "▶ Uruchom boty"
```

### 4. Zarządzanie
```
- Kliknij bota aby zobaczyć szczegóły
- Kliknij stół aby dołączyć
- Kliknij "🔄" aby odświeżyć listę stołów
```

---

## 🎯 Główne Funkcjonalności

### 🟢 Whitelist
Bot automatycznie wychodzi ze stołu gdy gracz z whitelist wejdzie.

```python
# Użytkownik
1. Przejdź do "🟢 Whitelist"
2. Dodaj nick gracza
3. Bot wychodzi gdy gracz wejdzie
```

### 🔴 Blacklist
Bot wykonuje akcję gdy gracz z blacklist wejdzie.

```python
# Akcje dostępne
- 💬 Wyślij wiadomość z puli
- 🚪 Wyjdź ze stołu
- 🚪💬 Wyślij + wyjdź
- 🔇 Nic nie rób
```

### 🏷️ Grupy
Przypisz wspólną konfigurację wielu nickom.

```python
# Przykład
Grupa: "Trollowie"
  Akcja: Wyjdź
  Nicki: ["Troll1", "Troll2", "Troll3"]
```

### 💬 Pule Wiadomości
Losowe wiadomości z placeholerem `{user}`.

```python
# Przykład puli
"Cześć {user}! 👋"
"Witaj {user} na stole! 🎮"
"{user}, zapraszam do gry! 🎲"
```

### 🖌️ Rysowanie (Kalambury)
```python
# Nowe: Bot może rysować automatycznie
1. Zaznacz "🖌️ Auto-rysuj" w toolbarze
2. Importuj obraz (📂 Importuj obraz do rysowania)
3. Gdy bot ma rysować — załadowany obraz zostanie narysowany
```

---

## 📊 Architektura

### Struktura Katalogów
```
modules/kurnik-ws/
├── launcher.py              # Qt6 GUI manager botów
├── kurnik-ws.py             # WebSocket bot (subprocess)
├── SERVER_PROTOCOL.md       # Dokumentacja protokołu serwera ✨ NOWY
├── CHANGELOG.md             # Historia zmian ✨ NOWY
├── GUIDE.md                 # Przewodnik użytkownika ✨ NOWY
├── whitelist.txt            # Lista nicków (auto-exit)
├── blacklist.json           # Konfiguracja nicków
├── groups.json              # Grupy nicków
└── pools.json               # Pule wiadomości
```

### Komunikacja Bot ↔ GUI
```
launcher.py (Qt6 GUI)
    ↓
subprocess (kurnik-ws.py)
    ↕ stdin/stdout
    ↕ kolejka (queue.Queue)
    ↓
WebSocket (Kurnik.pl)
```

### Tokeny Protokołu
```
Wysyłane:
  CONNECTED               — Bot połączony
  JOINED <id>            — Bot dołączył do stołu
  MSG <tekst>            — Wiadomość
  
HINT <wskazówka>         — Do rysowania ✨ NOWY
GUESS <słowo>            — Słowo do zgadnięcia ✨ NOWY
DRAW <type> <x> <y>      — Ruch rysunkowy ✨ NOWY
  
PLAYER_JOIN <id> <nick>  — Gracz wejdzie
PLAYER_LEAVE <id> <nick> — Gracz wyjdzie
```

---

## 🔌 Polecenia do Botów

W sekcji "📨 Wyślij do wybranego bota":

| Komenda | Efekt |
|---------|-------|
| `/join 42` | Dołącz do stołu 42 |
| `/table` | Wyświetl aktualny stół |
| `/tables` | Odśwież listę stołów |
| `/ext Tekst` | Wyślij na aktualny stół |
| `/quit` | Zamknij bota |
| `Tekst` | Chat na aktualny stół |

---

## 🎮 Workflow: Konfiguracja Rysowania

```python
# 1. Przygotowanie obrazu
1. Kliknij "📂 Importuj obraz do rysowania"
2. Wybierz PNG lub JPG
3. Ścieżka zostanie zapisana

# 2. Włączenie automatycznego rysowania
1. Zaznacz checkbox "🖌️ Auto-rysuj" w toolbarze
2. Skopiuj bota do Kalambury

# 3. Uruchomienie
1. Bot dołącza do gry
2. Gdy ma RYSOWAĆ:
   - Log pokaże: "🖌️ Rysuj: PANDA"
   - Obraz zostanie narysowany (jeśli Auto-rysuj ON)
3. Gdy inny gracz ZGADUJE:
   - Log pokaże: "❓ _ _ _ _ _"
```

---

## 🔍 Monitoring i Debugging

### Log Globalny
```
- Wszystkie zdarzenia wszystkich botów
- Eksport do TXT: Kliknij "💾 Eksportuj log"
```

### Log Bota
```
- Historia zdarzeń wybranego bota
- Aktualizuje się co 150ms
- Max 500 ostatnich wiadomości
```

### Status Bar
```
Botów: 5 | Połączonych: 4 | Script: kurnik-ws.py
```

---

## 📝 Formaty Plików

### whitelist.txt
```
gracz1
gracz2
# komentarz
gracz3
```

### blacklist.json
```json
{
  "gracz1": {
    "display": "Gracz1",
    "group": "trollowie",
    "action": "leave",
    "pool": null
  }
}
```

### groups.json
```json
{
  "trollowie": {
    "action": "leave",
    "pool": null,
    "desc": "Automatycznie wychodź"
  },
  "gracze": {
    "action": "send_msg",
    "pool": "pozdrowienia",
    "desc": "Wyślij losową wiadomość"
  }
}
```

### pools.json
```json
{
  "pozdrowienia": [
    "Cześć {user}! 👋",
    "Witaj {user}! 🎮"
  ],
  "pożegnania": [
    "Pa {user}! 👋",
    "Do zobaczenia {user}! 🎯"
  ]
}
```

---

## 🐛 Znane Ograniczenia

1. **Rysowanie** — Wymaga implementacji konwersji obrazu do sekwencji ruchów
2. **Performance** — Przy 50+ botach GUI może być wolne
3. **WebSocket Timeout** — 60 sekund bez odpowiedzi = rozłączenie

---

## 🛠️ Rozszerzeń & Plany

### Do Zrobienia
- [ ] Konwersja obrazu PNG/JPG → sekwencja ruchów
- [ ] Wysyłanie ruchów rysunkowych do serwera
- [ ] Obsługa koloru w rysowaniu
- [ ] Cache obrazów dla szybszego rysowania
- [ ] Statystyka: procent poprawnych rysunków

### Przyszłe Featuresy
- [ ] GUI do edycji ścieżek rysowania
- [ ] Zapis/wczytanie sekwencji ruchów
- [ ] WebUI zamiast Qt (dla linuxu bez X11)
- [ ] Automatyczne testowanie (unit tests)

---

## 📞 Wsparcie

1. **Czytaj `GUIDE.md`** — Pełny przewodnik użytkownika
2. **Czytaj `SERVER_PROTOCOL.md`** — Dokumentacja protokołu
3. **Czytaj `CHANGELOG.md`** — Historia zmian
4. **Sprawdź logi** — Log globalny zawiera całą historię

---

## 🔄 Zmany od Poprzedniej Wersji

### v1.1.0 → v1.2.0

| Feature | Status |
|---------|--------|
| `/ext` naprawa | ✅ Gotowe |
| `/tables` naprawa | ✅ Gotowe |
| Przycisk odświeżenia stołów | ✅ Gotowe |
| Obsługa MSG_GAME_STATE (90) | ✅ Gotowe |
| Obsługa MSG_TAB_DRAW (92) | ✅ Gotowe |
| Checkbox "Auto-rysuj" | ✅ Gotowe |
| Import obrazu | ✅ Gotowe |
| Dokumentacja protokołu | ✅ Gotowe |
| Konwersja obrazu → ruchy | ⏳ Planowane |
| Wysyłanie ruchów rysunkowych | ⏳ Planowane |

---

## 📜 Licencja

Projekt Kurnik Bot Launcher — Publiczne użytkownie na własne ryzyko.

---

## 👨‍💻 Autor

Maintainer: GitHub Copilot  
Ostatnia aktualizacja: 2024-01-XX  
Wersja: **1.2.0**

---

**Zapraszam do używania i zgłaszania uwag! 🎮✨**
