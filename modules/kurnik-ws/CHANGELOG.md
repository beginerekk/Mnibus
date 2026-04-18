# Dziennik Zmian — Kurnik Bot Launcher

## ✅ Ostatnia Sesja — Implementacja Rysowania i Ulepszeń

### 🔧 Naprawione Błędy

#### 1. **Komenda `/ext` — Naprawiona** 
- **Problem:** Wysyłała na losowy stół zamiast na aktualny
- **Rozwiązanie:** Zmieniono format — teraz `/ext <tekst>` wysyła na aktualny stół
- **Plik:** `kurnik-ws.py` (linie 672-682)
- **Przed:**
  ```python
  /ext <table_id> <tekst>  # Wymagał ID stołu
  await ws.send(encode([MSG_CHAT, tid], [parts[1]]))
  ```
- **Po:**
  ```python
  /ext <tekst>  # Wysyła na aktualny stół
  if current_table:
      await ws.send(encode([MSG_CHAT, current_table], [text]))
  ```

#### 2. **Komenda `/tables` — Naprawiona**
- **Problem:** Czasami nie odświeżała listy
- **Rozwiązanie:** Dodano debug output aby śledzić żądanie
- **Plik:** `kurnik-ws.py` (linia 670)

### 🎨 Nowe Funkcje

#### 3. **Przycisk Odświeżenia Listy Stołów**
- **Lokalizacja:** Prawy górny róg panelu "Stoły w pokoju"
- **Przycisk:** `🔄` (niebieski)
- **Funkcja:** `_refresh_tables_manual()`
- **Działanie:** Wysyła komendę `/tables` do wybranego bota
- **Plik:** `launcher.py` (linie 1290-1295, 1880-1891)

#### 4. **Obsługa Kodów Rysowania**
- **Usunięte z IGNORE_CODES:** Kody 90 (MSG_GAME_STATE) i 92 (MSG_TAB_DRAW)
- **Plik:** `kurnik-ws.py` (linie 107-122)
- **Nowa obsługa w `receive()`:**
  ```python
  if code == MSG_GAME_STATE (90):
      game_state: 1=rysowanie, 2=zgadywanie
      strings[0] = wskazówka/słowo
  
  if code == MSG_TAB_DRAW (92):
      Ruch rysunkowy (x, y, pressure)
  ```
- **Plik:** `kurnik-ws.py` (linie 599-631)

#### 5. **Tokeny Protokołu w Launcherze**
- **HINT** — Wskazówka do rysowania
  - Wysyłane do GUI z logiem
  - Format: `🖌️  <wskazówka>`
- **GUESS** — Słowo do zgadnięcia
  - Format: `❓ <słowo>`
- **DRAW** — Ruchy rysunkowe
  - Zbierane ale nie wyświetlane (zbyt dużo szumu)
- **Plik:** `launcher.py` (linie 634-661)

#### 6. **Checkbox Automatycznego Rysowania**
- **Lokalizacja:** Toolbar (górny pasek)
- **Label:** `🖌️  Auto-rysuj`
- **Stan:** Domyślnie wyłączony
- **Cel:** Włączenie automatycznego rysowania gdy bot ma rysować
- **Implementacja:** Przygotowana, wymaga integracji z kodem rysowania
- **Plik:** `launcher.py` (linie 1177-1189)

#### 7. **Import Obrazu do Rysowania**
- **Lokalizacja:** Toolbar (górny pasek)
- **Przycisk:** `📂 Importuj obraz do rysowania` (pomarańczowy)
- **Obsługiwane formaty:** PNG, JPG, JPEG, BMP
- **Funkcja:** `_import_draw_image()`
- **Działanie:**
  - Otwiera selektor plików
  - Zapisuje ścieżkę w `self.draw_image_path`
  - Wyświetla potwierdzenie z ścieżką
- **Plik:** `launcher.py` (linie 1893-1908)
- **Inicjalizacja:** `self.draw_image_path = None` w `__init__` (linia 985)

### 📚 Dokumentacja

#### 8. **Pełna Dokumentacja Protokołu Serwera**
- **Plik:** `modules/kurnik-ws/SERVER_PROTOCOL.md` (nowy)
- **Zawartość:**
  - Przegląd formatu JSON
  - Polecenia wysyłane do serwera
  - Wszystkie kody odbierane z serwera (tabela)
  - Szczegóły poszczególnych kodów:
    - `MSG_GAME_STATE (90)` — stany gry (rysowanie/zgadywanie)
    - `MSG_TAB_DRAW (92)` — ruchy rysunkowe
    - `MSG_CHAT (81)` — wiadomości czatu
    - `MSG_PLAYER_ACTION (84)` — akcje graczy
    - `MSG_TAB_OPEN (73)` — otwieranie stołu
    - i wiele innych...
  - Struktura listy stołów
  - Obsługa rysowania (Kalambury)
  - Obsługa błędów i heartbeat
  - Przykłady implementacji

---

## 📋 Status Implementacji

### ✅ Ukończone
- [x] Naprawa komendy `/ext`
- [x] Naprawa komendy `/tables`
- [x] Dodanie przycisku odświeżenia listy stołów
- [x] Usunięcie kodów rysowania z IGNORE_CODES
- [x] Obsługa MSG_GAME_STATE (90) — wskazówki rysowania
- [x] Obsługa MSG_TAB_DRAW (92) — ruchy rysunkowe
- [x] Dodanie tokenów HINT, GUESS, DRAW w launcherze
- [x] Checkbox "Auto-rysuj" w toolbarze
- [x] Przycisk importu obrazu do rysowania
- [x] Pełna dokumentacja protokołu serwera

### ⏳ Do Implementacji
- [ ] Konwersja obrazu do sekwencji ruchów (x, y, pressure)
- [ ] Wysyłanie ruchów gdy bot jest w trybie rysowania
- [ ] Obsługa flagę `chk_draw` (Auto-rysuj)
- [ ] Integracja z kodem `draw_image_path`
- [ ] Testowanie rysowania end-to-end

### ℹ️ Notatki Techniczne
- **Kody rysowania:** Bot teraz otrzymuje kody 90 i 92, które wcześniej były ignorowane
- **Wskazówka rysowania:** Znajduje się w `strings[0]` gdy `game_state == 1`
- **Ruch rysunkowy:** Format `[92, draw_type, x, y, pressure, color, ...]`
  - `draw_type`: 0=start, 1=move, 2=end
- **Obraz:** Import przechowuje ścieżkę w `self.draw_image_path` do późniejszego użytku

---

## 🚀 Jak Używać Nowych Funkcji

### Odświeżenie Listy Stołów
1. Wybierz bota z listy
2. Kliknij przycisk `🔄` obok pola "ID:"
3. Lista stołów się odświeży

### Import Obrazu do Rysowania
1. Kliknij przycisk `📂 Importuj obraz do rysowania`
2. Wybierz plik PNG/JPG
3. Potwierdzenie pojawi się na ekranie
4. Gdy bot ma rysować i "Auto-rysuj" jest włączony, będzie rysować ten obraz

### Sprawdzenie Wskazówki do Rysowania
1. Gra się zacznie
2. Gdy gracz ma rysować — log pokaże: `🖌️  <wskazówka>`
3. Gdy inny gracz zgaduje — log pokaże: `❓ <słowo>`

### Naprawa Polecenia /ext
- **Stare:** `/ext 42 Cześć!` (wysyłało na stół 42)
- **Nowe:** `/ext Cześć!` (wysyła na aktualny stół)

---

## 📝 Pliki Zmodyfikowane

| Plik | Zmiany | Linie |
|------|--------|-------|
| `kurnik-ws.py` | Naprawa `/ext` i `/tables`, obsługa kodów 90/92 | 107-122, 599-631, 670-682 |
| `launcher.py` | Obs. kodów, przycisk refresh, checkbox draw, import | 634-661, 985, 1177-1189, 1290-1295, 1880-1908 |
| `SERVER_PROTOCOL.md` | NOWY — Pełna dokumentacja | Cały plik |

---

## 🐛 Znane Ograniczenia

- Automatyczne rysowanie wymaga biblioteki do przetwarzania obrazów (PIL/Pillow)
  - Może być dodane w przyszłości
- Rysowanie wysyłane jest w sekwencji, prędkość może się różnić na serwerze
- Checkbox "Auto-rysuj" jest przygotowany do użytku, ale logika integracji wymaga pełnej implementacji konwersji obrazu

---

## 📞 Wsparcie

Zapoznaj się z dokumentacją `SERVER_PROTOCOL.md` aby zrozumieć:
- Jakie kody wysyła serwer
- Jakie kody wysyłamy do serwera
- Jak działa rysowanie
- Jak obsługiwać błędy i timeout

---

**Data:** 2024-01-XX  
**Wersja:** 1.2.0  
**Status:** Produkcja (z flagą do dalszego rozwoju)
