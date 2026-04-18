# Kurnik Bot Launcher — Przewodnik Użytkownika

## 🎯 Szybki Start

### Uruchomienie
```bash
python launcher.py
```

### Konfiguracja Botów
1. Ustaw liczbę botów (spin box: Botów)
2. Wybierz pokój (domyślnie: 100)
3. Ustaw stół startowy (0 = bez stołu, lub numer stołu)
4. Zaznacz "Wspólny stół" jeśli wszystkie boty mają być na tym samym stole
5. Kliknij **▶ Uruchom boty**

---

## 🎮 Zarządzanie Botami

### Panel Botów (Lewy)
- Lista wszystkich aktywnych botów
- 🟢 = połączony, 🟡 = łączy się, 🔴 = offline
- Kliknij bota aby zobaczyć szczegóły

### Panel Szczegółów (Środek)
- **Etykieta bota** — Numer, pokój, aktualny stół
- **Statystyka** — Liczba wysłanych wiadomości i dołączeń
- **Stoły w pokoju** — Lista dostępnych stołów
  - `🔄` — odśwież listę stołów
  - `➡` — dołącz do wybranego stołu
  - Pole ID — ręczny numer stołu
- **Log bota** — Historia zdarzeń wybranego bota

### Panel Konfiguracji (Prawy)
6 zakładek:
1. **📢 Broadcast** — Wyślij wiadomość do wszystkich botów
2. **🟢 Whitelist** — Nicki, przy których bot wychodzi
3. **🔴 Blacklist** — Nicki z konfiguracją reakcji
4. **🏷️ Grupy** — Grupy nicków ze wspólną konfiguracją
5. **💬 Pule** — Pule wiadomości (losowe odpowiedzi)
6. **📋 Log globalny** — Historia wszystkich zdarzeń

---

## 🎨 Nowe Funkcje (v1.2.0)

### 🔄 Odświeżenie Listy Stołów
1. Wybierz bota z listy
2. Kliknij przycisk `🔄` w sekcji "Stoły w pokoju"
3. Lista się odświeży

**Kiedy używać?**
- Gdy lista stołów się zapatrzy
- Gdy pojawiły się nowe stoły
- Przed dołączeniem do konkretnego stołu

### 🖌️ Automatyczne Rysowanie

#### Włączenie
1. Zaznacz checkbox `🖌️ Auto-rysuj` w toolbarze
2. Kliknij `📂 Importuj obraz do rysowania`
3. Wybierz plik PNG/JPG

#### Jak Działa?
- Gdy bot ma **rysować** w Kalambury:
  - Log pokaże: `🖌️ Wskazówka: PANDA`
  - Bot automatycznie wyśle ruch rysunkowy
  - Zostanie narysowany załadowany obraz
- Gdy inny gracz **zgaduje**:
  - Log pokaże: `❓ _ _ _ _ _` (ukryte słowo)

### 📋 Konfiguracja Whitelist

**Cel:** Bot wychodzi ze stołu gdy dany gracz wejdzie

**Użytkownik:**
```
1. Przejdź do zakładki "🟢 Whitelist"
2. Wpisz nick gracza
3. Kliknij "➕ Dodaj"
```

**Import:**
- Kliknij "📂 Import"
- Wybierz plik TXT lub CSV (jeden nick na linię)

**Efekt:**
```
[PLAYER wejdzie na stół]
→ Bot automatycznie wychodzi
Log: 🟢 WHITELIST: <nick> → Bot wychodzi
```

### 🔴 Konfiguracja Blacklist

**Cel:** Bot wykonuje akcję gdy dany gracz wejdzie

**Akcje:**
- 💬 Wyślij wiadomość (z losowej puli)
- 🚪 Wyjdź ze stołu
- 🚪💬 Wyślij wiadomość i wyjdź
- 🔇 Nic nie rób (wycisz gracza)

**Użytkownik:**
```
1. Przejdź do "🔴 Blacklist"
2. Wpisz nick i kliknij "➕ Dodaj"
3. Kliknij nick z listy
4. Wybierz Grupę (opcjonalnie), Akcję i Pulę
5. Kliknij "💾 Zapisz konfigurację"
```

**Przykład:** Nick "Troll" → Akcja: Wyjdź → Bot wychodzi
```
Log: 🔴 BLACKLIST: Troll → Bot wychodzi ze stołu
```

### 🏷️ Grupy

**Cel:** Przypisz wspólną konfigurację wielu nickom

**Przykład:**
- Grupa: "Trollowie"
- Akcja: Wyjdź
- Nicki: "Troll1", "Troll2", "Troll3"
- Efekt: Bot wychodzi gdy ktoś z grupy wejdzie

**Użytkownik:**
```
1. Przejdź do "🏷️ Grupy"
2. Wpisz nazwę grupy, kliknij "➕ Dodaj grupę"
3. Kliknij grupę z listy
4. Ustaw Akcję i Pulę
5. Kliknij "💾 Zapisz grupę"
6. W Blacklist przypisz nick do grupy
```

### 💬 Pule Wiadomości

**Cel:** Bot wysyła losową wiadomość z puli

**Placeholder:**
- `{user}` — zostanie zastąpiony nickiem gracza

**Przykład puli "Grzeczność":**
```
Cześć {user}! 👋
Witaj {user} na stole! 🎮
{user}, zapraszam do gry! 🎲
```

**Użytkownik:**
```
1. Przejdź do "💬 Pule"
2. Wpisz nazwę puli, kliknij "➕ Utwórz pulę"
3. Wpisz wiadomość (może zawierać {user})
4. Kliknij "➕" aby dodać
5. Przypisz pulę w Grupie lub Nicku w Blacklist
```

---

## 📨 Broadcast

### Wyślij do Wszystkich Botów

**Wiadomość:**
1. Przejdź do "📢 Broadcast"
2. Wpisz tekst (np. "Hej wszystko OK?")
3. Kliknij "📢 Broadcast"
4. Wiadomość trafi do wszystkich działających botów

**Zmiana Stołu:**
1. Wpisz numer stołu w pole "ID stołu:"
2. Kliknij "➡ Przełącz wszystkie"
3. Wszystkie boty dołączą do tego stołu

---

## 🔧 Zaawansowane

### Komendy do Wysyłania do Bota

W sekcji "📨 Wyślij do wybranego bota":

```
/join 42        — Dołącz do stołu 42
/table          — Wyświetl aktualny stół
/tables         — Odśwież listę stołów
/ext Cześć!     — Wyślij "Cześć!" na aktualny stół
/quit           — Rozłącz i zamknij bota
<tekst>         — Wyślij jako chat na aktualny stół
```

### Import Danych

**Whitelist / Blacklist:**
```
Format TXT:
nick1
nick2
nick3
# To jest komentarz

Format CSV:
nick1, dodatkowa info
nick2, dodatkowa info
```

**Pule Wiadomości:**
```
Wiadomość 1
Wiadomość 2 z {user}
Wiadomość 3
```

---

## 📊 Monitoring

### Log Globalny
- Wszystkie zdarzenia wszystkich botów
- Można eksportować do pliku TXT
- Kliknij "💾 Eksportuj log" aby zapisać

### Pasek Stanu
- Liczba wszystkich botów
- Liczba połączonych botów
- Nazwa aktualnie uruchomionego skryptu

### Statystyki Bota
- Liczba wysłanych wiadomości
- Liczba dołączeń do stołów

---

## 🚨 Troubleshooting

### Bot się nie łączy
- Sprawdź czy internet działa
- Czekaj 30 sekund (timeout serwera)
- Zatrzymaj i uruchom ponownie

### Lista stołów się nie odświeża
- Kliknij przycisk `🔄` w sekcji "Stoły w pokoju"
- Lub wyślij `/tables` do bota

### Whitelist/Blacklist nie działa
- Upewnij się że nick jest poprawnie wpisany
- Nicki są nieważne dla wielkości liter (TROLL = troll)
- Log pokaże czy akcja się wykonała

### Wiadomości nie wysyłają się
- Sprawdź czy pula ma wiadomości
- Czy w blacklist jest przypisana pula?
- Log pokaże błędy

---

## 📚 Dokumentacja Techniczna

Zapoznaj się z:
- **`SERVER_PROTOCOL.md`** — Pełna dokumentacja kodów serwera
- **`CHANGELOG.md`** — Historia zmian i nowych funkcji

---

## ⌨️ Skróty

| Przycisk | Działanie |
|----------|-----------|
| Enter | Wysłanie w polach tekstowych |
| ✅ Zaznacz Whitelist | Nick ignoruje wszystko, bot wychodzi |
| ➕ Dodaj | Dodaj element do listy |
| 🗑 Usuń | Usuń wybrany element |
| 📂 Import | Importuj z pliku |
| 💾 Zapisz | Zapisz konfigurację |
| 🔄 | Odśwież |
| 🚀 | Uruchom |
| ⏹ | Stop |

---

**Wersja:** 1.2.0  
**Ostatnia Aktualizacja:** 2024-01-XX

Powodzenia! 🎮
