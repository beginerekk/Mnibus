# Protokół Serwera Kurnik.pl

## Przegląd

Komunikacja z serwerem Kurnik.pl odbywa się przez WebSocket z użyciem formatu JSON:

```json
{"i":[kod1, kod2, ...], "s":["string1", "string2", ...]}
```

- **`i` (integers)** — tablica kodów akcji i argumentów
- **`s` (strings)** — opcjonalna tablica tekstów (np. treść wiadomości)

## Przesyłanie Danych do Serwera

### Żądanie Listy Stołów
```python
encode([MSG_TABLES])  # [71]
```
Serwer odpowiadał będzie z listą stołów w pokoju.

### Dołączenie do Stołu
```python
encode([MSG_JOIN_TAB, table_id])  # [72, 42]
```
- `table_id` — numer stołu do którego się dołączamy

### Wysłanie Wiadomości Chat
```python
encode([MSG_CHAT, table_id], ["wiadomość"])  # [81, 42], ["Cześć!"]
```
- `table_id` — numer stołu
- `"wiadomość"` — treść wiadomości

### Odpowiedź na Ping
```python
encode([MSG_PONG])  # [2]
```

---

## Kody Odbierane z Serwera

### Heartbeat
| Kod | Nazwa | Format | Opis |
|-----|-------|--------|------|
| 1 | `MSG_PING` | `[1]` | Serwer pinguje — klient musi odpowiedzieć kodem 2 |
| 2 | `MSG_PONG` | `[2]` | Odpowiedź na ping (wysyłamy my) |

### Zarządzanie Stołami
| Kod | Nazwa | Format | Opis |
|-----|-------|--------|------|
| 70 | `MSG_TAB_UPDATE` | `[70, table_id, ...]` | Aktualizacja danych stołu (gracze, wyniki) |
| 71 | `MSG_TABLES` | `[71, ...]` + strings | Lista stołów w pokoju |
| 72 | `MSG_JOIN_TAB` | `[72, table_id]` | Potwierdzenie dołączenia do stołu |
| 73 | `MSG_TAB_OPEN` | `[73, table_id, status]` | Stół otwarty/zmieniono pokój |
| 74 | `MSG_TAB_CLOSE` | `[74, table_id]` | Stół zamknięty |

### Komunikacja Graczy
| Kod | Nazwa | Format | Opis |
|-----|-------|--------|------|
| 81 | `MSG_CHAT` | `[81, table_id, ...]` + strings | Wiadomość czatu na stole |
| 84 | `MSG_PLAYER_ACTION` | `[84, table_id, player_id, action]` | Akcja gracza (siadanie, wstawanie) |
| 85 | `MSG_PLAYER_LEAVE` | `[85, table_id, player_id]` | Gracz opuścił stół |

### Gra (Kalambury)
| Kod | Nazwa | Format | Opis |
|-----|-------|--------|------|
| 88 | `MSG_TAB_STATUS` | `[88, table_id, status]` | Status gry na stole |
| 89 | `MSG_SETTINGS` | `[89, table_id, ...]` + strings | Ustawienia stołu |
| 90 | `MSG_GAME_STATE` | `[90, game_state, ...]` + strings | Stan gry na stole |
| 91 | `MSG_TAB_HISTORY` | `[91, ...]` | Historia ruchów (rysowania) |
| 92 | `MSG_TAB_DRAW` | `[92, draw_type, x, y, ...]` | Ruch rysunkowy |

### Pozostałe Kody (Zwykle Ignorowane)
| Kod | Opis |
|-----|------|
| 18 | Opcje serwera |
| 20 | Tekst globalny |
| 22 | Aktualizacja profilu |
| 23 | Lista graczy globalnie |
| 27 | Lista stołów (raw) |
| 28 | Status kontaktów |
| 30 | Ustawienia puli |
| 31 | Lista pokojów |
| 32 | Lista aktywnych pokojów |
| 51 | Tekst lokalizacyjny |

---

## Szczegóły Kodów

### MSG_GAME_STATE (90) — Stan Gry

Wysyłany gdy zmienia się stan gry na stole (faza rysowania, zgadywania itp.).

**Format:**
```
[90, game_state] + ["wskazówka" lub "słowo"]
```

**game_state wartości:**
- `0` — czekanie / pusta faza
- `1` — **rysowanie** — gracz rysuje, drugi zgaduje
  - strings[0] = wskazówka do rysowania (słowo do narysowania)
- `2` — **zgadywanie** — gracz zgaduje słowo
  - strings[0] = ukryte słowo (np. "_ _ _ _ _ _")

**Przykład:**
```json
{"i":[90,1],"s":["PANDA"]}           // Rysuj: PANDA
{"i":[90,2],"s":["_ _ _ _ _"]}       // Zgaduj: 5-literowe słowo
```

### MSG_TAB_DRAW (92) — Ruch Rysunkowy

Wysyłany gdy ktoś rysuje na stole.

**Format:**
```
[92, draw_type, x, y, pressure, color, ...]
```

**draw_type wartości:**
- `0` — początek linii (ponieś pióro)
- `1` — rysowanie (ciąg lini)
- `2` — koniec linii (opuść pióro)

**Parametry:**
- `x, y` — współrzędne punktu
- `pressure` — siła nacisku (0-1.0)
- `color` — kod koloru

**Przykład:**
```json
{"i":[92,1,100,150,0.8,0]}          // Rysuj punkt (100,150) z naciskiem 0.8
```

### MSG_CHAT (81) — Wiadomość Czatu

**Format:**
```
[81, table_id] + ["nick: wiadomość"]
```

**Przykład:**
```json
{"i":[81,42],"s":["Player123: Hej wszystkim!"]}
```

### MSG_PLAYER_ACTION (84) — Akcja Gracza

**Format:**
```
[84, table_id, player_id, action_code]
```

**action_code:**
- `1` — gracz siedzi przy stole
- `2` — gracz wstał od stołu

### MSG_TAB_OPEN (73) — Stół Otwarty

Wysyłany gdy gracz otwiera/zmienia stół.

**Format:**
```
[73, table_id, status] + [status_string]
```

**Przykład:**
```json
{"i":[73,42,0],"s":["Kalambury · Pokój 100"]}
```

---

## Struktura Listy Stołów (MSG_TABLES = 71)

Odpowiedź serwera zawiera listę wszystkich stołów w pokoju.

**Format:**
```
[71] + ["ID | parametry | gracze", "ID | parametry | gracze", ...]
```

**Przykład:**
```json
{
  "i": [71],
  "s": [
    "42 | Kalambury · 2/4 · RO=0 | Alice, Bob",
    "43 | Kalambury · 1/4 · RO=0 | Charlie",
    "44 | Kalambury · 4/4 · RO=1 | Diana, Eve, Frank, Grace"
  ]
}
```

**Opis parametrów:**
- `ID` — numer stołu
- `2/4` — liczba graczy / maksymalnie
- `RO=0` — RO=0 (gra możliwa), RO=1 (gra trwa, nie można dołączyć)
- Ostatnia część — lista nicków graczy

---

## Obsługa Rysowania (Kalambury)

Aby automatycznie rysować:

1. **Czekaj na kod 90** (MSG_GAME_STATE) z `game_state = 1`
2. **Odczytaj wskazówkę** z strings[0]
3. **Zkonwertuj obraz** do sekwencji ruchów (x, y, pressure)
4. **Wyślij ruchy** jako kody 92 (MSG_TAB_DRAW)

Przykład sekwencji:
```python
await ws.send(encode([92, 0, 100, 150, 0.5, 0]))  # Start
await ws.send(encode([92, 1, 101, 151, 0.5, 0]))  # Move
await ws.send(encode([92, 1, 102, 152, 0.5, 0]))  # Move
await ws.send(encode([92, 2, 102, 152, 0.5, 0]))  # End
```

---

## Błędy i Obsługa Połączenia

### Timeout
- **Przyczyna:** Brak odpowiedzi z serwera przez 60 sekund
- **Działanie:** Bot rozłącza się i próbuje ponownie

### Zamknięcie Połączenia
- **Przyczyna:** Serwer zamkną połączenie (timeout na serwerze, czasami login wygasł)
- **Działanie:** Wyświetl błąd, próbuj ponownie

### Heartbeat
- **Interwał:** 30 sekund
- **Wysyłane:** `{"i":[]}`
- **Cel:** Utrzymanie połączenia z serwerem

---

## Implementacja Bota

```python
# Kodowanie
msg = encode([MSG_CHAT, 42], ["Cześć!"])
await ws.send(msg)

# Dekodowanie
for frame in decode(raw_data):
    codes = frame['i']
    strings = frame['s']
    if codes[0] == MSG_TABLES:
        print(f"Dostałem {len(strings)} stołów")
```

---

## Referencje

- Pliki źródłowe: `kurnik-ws.py`, `launcher.py`
- Protokół JSON: `encode()` i `decode()` funkcje
- Heartbeat: Co 30 sekund, tabele co 90 sekund
