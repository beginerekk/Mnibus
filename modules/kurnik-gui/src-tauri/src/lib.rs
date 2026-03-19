// src-tauri/src/lib.rs
use dashmap::DashMap;
use futures_util::{SinkExt, StreamExt};
use once_cell::sync::Lazy;
use reqwest::{cookie::Jar, Client};
use serde::{Deserialize, Serialize};
use std::sync::{atomic::{AtomicU32, Ordering}, Arc};
use tauri::{AppHandle, Emitter, Manager};
use tokio::sync::mpsc;
use tokio_tungstenite::{connect_async_tls_with_config, tungstenite::Message};

// ─── typy publiczne ───────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Table {
    pub id:      u32,
    pub params:  String,
    pub players: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChatMsg {
    pub bot_id: u32,
    pub code:   u32,
    pub text:   String,
}

#[derive(Debug, Clone, Serialize)]
pub struct BotStatus {
    pub bot_id:  u32,
    pub game:    String,
    pub room:    String,
    pub table:   Option<u32>,
    pub online:  bool,
}

// ─── globalna mapa botów ──────────────────────────────────────────────────────
// bot_id → Sender do wątku WS
static BOTS: Lazy<DashMap<u32, mpsc::Sender<BotCmd>>> = Lazy::new(DashMap::new);
static NEXT_ID: AtomicU32 = AtomicU32::new(1);

enum BotCmd {
    JoinTable(u32),
    Chat(u32, String),
    Disconnect,
}

// ─── protokół kurnik ─────────────────────────────────────────────────────────
const UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
                  (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";
const PING: u32     = 1;
const PONG: u32     = 2;
const TABLES: u32   = 71;
const JOIN_TAB: u32 = 72;
const CHAT: u32     = 81;

// Kody do zignorowania
fn should_ignore(code: u32) -> bool {
    matches!(code, 18|20|22|23|24|25|27|28|30|31|32|51|70|72|74|88|90|92)
}

/// Koduje ramkę WS {"i":[...],"s":[...]}
fn encode(codes: &[u32], strings: &[&str]) -> String {
    let mut out = String::with_capacity(64);
    out.push_str("{\"i\":[");
    for (i, c) in codes.iter().enumerate() {
        if i > 0 { out.push(','); }
        out.push_str(&c.to_string());
    }
    out.push(']');
    if !strings.is_empty() {
        out.push_str(",\"s\":[");
        for (i, s) in strings.iter().enumerate() {
            if i > 0 { out.push(','); }
            out.push('"');
            for ch in s.chars() {
                match ch {
                    '\\' => out.push_str("\\\\"),
                    '"'  => out.push_str("\\\""),
                    _    => out.push(ch),
                }
            }
            out.push('"');
        }
        out.push(']');
    }
    out.push('}');
    out
}

#[derive(Deserialize)]
struct Frame {
    #[serde(default)] i: Vec<serde_json::Value>,
    #[serde(default)] s: Vec<String>,
}

fn parse_frames(raw: &str) -> Vec<Frame> {
    let mut out = Vec::new();
    // szybka ścieżka: brak '\n'
    if !raw.contains('\n') {
        if let Ok(f) = serde_json::from_str(raw) { out.push(f); }
        return out;
    }
    for line in raw.split('\n') {
        if line.is_empty() { continue; }
        if let Ok(f) = serde_json::from_str(line) { out.push(f); }
    }
    out
}

fn frame_code(f: &Frame) -> Option<u32> {
    f.i.first()?.as_u64().map(|v| v as u32)
}

fn parse_tables(f: &Frame) -> Vec<Table> {
    let codes: Vec<u32> = f.i.iter()
        .filter_map(|v| v.as_u64().map(|n| n as u32))
        .collect();
    if codes.len() < 3 { return vec![]; }
    let d  = codes[1] as usize;
    let m  = codes[2] as usize;
    let mut tables = Vec::new();
    let mut fi  = 3usize;
    let mut si  = 0usize;
    while fi < codes.len() && si + 1 < f.s.len() {
        let id = codes[fi];
        if id > 1 {
            tables.push(Table {
                id,
                params:  f.s[si].clone(),
                players: f.s.get(si + 1).cloned().unwrap_or_default(),
            });
        }
        fi += d;
        si += m;
    }
    tables
}

// ─── sesja HTTP ───────────────────────────────────────────────────────────────
struct Session {
    cookies: Arc<Jar>,
    ge: String,
    ap: String,
    tf: u32,
    ver: String,
}

async fn get_session(game: &str, room: &str) -> anyhow::Result<Session> {
    let jar = Arc::new(Jar::default());
    let base = format!("https://www.kurnik.pl/{game}/");
    let client = Client::builder()
        .user_agent(UA)
        .cookie_provider(jar.clone())
        .use_rustls_tls()
        .build()?;

    // ustaw cookie kroom przed requestem
    let url = base.parse::<reqwest::Url>()?;
    jar.add_cookie_str(&format!("kguest=1; kbeta=gs; kroom={room}"), &url);

    let body = client
        .post(&base)
        .header("Content-Type", "application/x-www-form-urlencoded")
        .header("Origin", "https://www.kurnik.pl")
        .header("Referer", &base)
        .body("gmid=gs")
        .send()
        .await?
        .text()
        .await?;

    let ge  = regex_val(&body, r"window\.ge\s*=\s*(\d+)").unwrap_or_default();
    let ap  = regex_val(&body, r"window\.ap\s*=\s*(\d+)").unwrap_or_default();
    let tf  = regex_val(&body, r"tf\s*:\s*(\d+)").unwrap_or("1751".into())
                .parse::<u32>().unwrap_or(1751);
    let ver = regex_val(&body, r"k2ver\s*=\s*(\d+)").unwrap_or("264".into());

    Ok(Session { cookies: jar, ge, ap, tf, ver })
}

fn regex_val(body: &str, pat: &str) -> Option<String> {
    let re = regex::Regex::new(pat).ok()?;
    re.captures(body)?.get(1).map(|m| m.as_str().to_string())
}

// ─── wątek bota ───────────────────────────────────────────────────────────────
async fn bot_task(
    bot_id: u32,
    game:   String,
    room:   String,
    app:    AppHandle,
    mut rx: mpsc::Receiver<BotCmd>,
) {
    // sesja
    let sess = match get_session(&game, &room).await {
        Ok(s)  => s,
        Err(e) => {
            let _ = app.emit("bot-error", format!("Bot {bot_id}: sesja błąd: {e}"));
            return;
        }
    };

    // buduj cookie string dla WS
    let cookie_str = {
        use std::fmt::Write;
        let url = format!("https://www.kurnik.pl/{game}/").parse::<reqwest::Url>().unwrap();
        let mut s = String::new();
        for c in sess.cookies.cookies(&url).iter() {
            if !s.is_empty() { s.push_str("; "); }
            write!(s, "{}", c.to_str().unwrap_or("")).ok();
        }
        s
    };

    // połączenie WS
    let req = tokio_tungstenite::tungstenite::http::Request::builder()
        .uri("wss://x.kurnik.pl:17003/ws/")
        .header("User-Agent", UA)
        .header("Origin", "https://www.kurnik.pl")
        .header("Cookie", &cookie_str)
        .body(())
        .unwrap();

    let (ws_stream, _) = match connect_async_tls_with_config(req, None, false, None).await {
        Ok(v)  => v,
        Err(e) => {
            let _ = app.emit("bot-error", format!("Bot {bot_id}: WS błąd: {e}"));
            return;
        }
    };

    let (mut sink, mut stream) = ws_stream.split();

    // handshake
    let autoid = rand_id();
    let ts     = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH).unwrap().as_millis();
    let handshake = encode(&[sess.tf], &[
        &format!("+{autoid}|{}|{}", sess.ap, sess.ge),
        "pl", "b", "", UA,
        &format!("/{ts}/1"), "w", "1920x1080 1",
        &format!("ref:https://www.kurnik.pl/{game}/"),
        &format!("ver:{}", sess.ver),
    ]);
    let _ = sink.send(Message::Text(handshake.into())).await;

    // emituj status online
    let _ = app.emit("bot-status", BotStatus {
        bot_id, game: game.clone(), room: room.clone(), table: None, online: true,
    });

    let mut current_table: Option<u32> = None;

    // heartbeat co 30s
    let mut hb = tokio::time::interval(std::time::Duration::from_secs(30));
    hb.tick().await; // skip first immediate tick

    loop {
        tokio::select! {
            // wiadomość z GUI → WS
            cmd = rx.recv() => {
                match cmd {
                    None | Some(BotCmd::Disconnect) => { let _ = sink.close().await; break; }
                    Some(BotCmd::JoinTable(id)) => {
                        current_table = Some(id);
                        let msg = encode(&[JOIN_TAB, id], &[]);
                        let _ = sink.send(Message::Text(msg.into())).await;
                        let _ = app.emit("bot-status", BotStatus {
                            bot_id, game: game.clone(), room: room.clone(),
                            table: current_table, online: true,
                        });
                    }
                    Some(BotCmd::Chat(table, text)) => {
                        let msg = encode(&[CHAT, table], &[&text]);
                        let _ = sink.send(Message::Text(msg.into())).await;
                    }
                }
            }

            // wiadomość z serwera
            msg = stream.next() => {
                match msg {
                    None | Some(Err(_)) => break,
                    Some(Ok(Message::Text(raw))) => {
                        for frame in parse_frames(&raw) {
                            let code = match frame_code(&frame) { Some(c) => c, None => continue };

                            if code == PING {
                                let _ = sink.send(Message::Text(encode(&[PONG], &[]).into())).await;
                                continue;
                            }

                            if code == TABLES {
                                let tables = parse_tables(&frame);
                                let _ = app.emit("bot-tables", (bot_id, tables));
                                continue;
                            }

                            if should_ignore(code) { continue; }

                            // wiadomość czatu / zdarzenia
                            if !frame.s.is_empty() {
                                let _ = app.emit("bot-msg", ChatMsg {
                                    bot_id,
                                    code,
                                    text: frame.s.join(" "),
                                });
                            }
                        }
                    }
                    Some(Ok(Message::Close(_))) => break,
                    _ => {}
                }
            }

            // heartbeat
            _ = hb.tick() => {
                let _ = sink.send(Message::Text("{\"i\":[]}".to_string().into())).await;
            }
        }
    }

    // bot offline
    let _ = app.emit("bot-status", BotStatus {
        bot_id, game, room, table: None, online: false,
    });
    BOTS.remove(&bot_id);
}

fn rand_id() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let t = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    t as u64 ^ (t >> 32) as u64
}

// ─── komendy Tauri (wywoływane z JS) ─────────────────────────────────────────

#[tauri::command]
async fn start_bot(
    game:  String,
    room:  String,
    app:   AppHandle,
) -> Result<u32, String> {
    let bot_id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    let (tx, rx) = mpsc::channel::<BotCmd>(32);
    BOTS.insert(bot_id, tx);

    let app2 = app.clone();
    tokio::spawn(async move {
        bot_task(bot_id, game, room, app2, rx).await;
    });

    Ok(bot_id)
}

#[tauri::command]
async fn stop_bot(bot_id: u32) -> Result<(), String> {
    if let Some((_, tx)) = BOTS.remove(&bot_id) {
        let _ = tx.send(BotCmd::Disconnect).await;
    }
    Ok(())
}

#[tauri::command]
async fn join_table(bot_id: u32, table_id: u32) -> Result<(), String> {
    if let Some(tx) = BOTS.get(&bot_id) {
        tx.send(BotCmd::JoinTable(table_id)).await
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn send_chat(bot_id: u32, table_id: u32, text: String) -> Result<(), String> {
    if let Some(tx) = BOTS.get(&bot_id) {
        tx.send(BotCmd::Chat(table_id, text)).await
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn list_bots() -> Vec<u32> {
    BOTS.iter().map(|e| *e.key()).collect()
}

// ─── entry point ─────────────────────────────────────────────────────────────
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            start_bot,
            stop_bot,
            join_table,
            send_chat,
            list_bots,
        ])
        .run(tauri::generate_context!())
        .expect("error running app");
}
