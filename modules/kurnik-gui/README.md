# kurnik-gui

Desktopowy klient Kurnik.pl oparty na Electron.

## Wymagania

- Node.js 18+
- npm

## Instalacja

```bash
npm install
```

> `ws` masz już zainstalowane z poprzedniego `npm install ws`.
> Polecenie powyżej doinstaluje tylko `electron` (~90 MB, jednorazowo).

## Uruchomienie

```bash
npm start
```

## Struktura

```
kurnik-gui/
├── main.js          ← Electron main process (cała logika WS/HTTP)
├── preload.js       ← bezpieczny bridge IPC
├── renderer/
│   └── index.html   ← GUI (HTML/CSS/JS)
└── package.json
```

## Jak działa

1. `main.js` przejmuje całą logikę z oryginalnego `kurnik-ws.js`
   - HTTP POST do kurnik.pl → uzyskanie sesji (cookies, ge, ap, tf, ver)
   - WebSocket do `wss://x.kurnik.pl:17003/ws/`
   - heartbeat co 30s
2. `preload.js` wystawia API `window.kurnik` do renderera przez contextBridge
3. `renderer/index.html` to GUI — ekran połączenia, lista stołów, okno czatu

## Komendy czatu

- `/join <ID>` — dołącz do stołu o podanym ID
- Wpisz tekst i naciśnij Enter / kliknij WYŚLIJ — wyślij wiadomość
