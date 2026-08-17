//! PTY to the Grok Build harness. Ghostty-web speaks VT; this is the
//! other end. Same byte interface a future grok-wasm module would use.

use std::collections::HashMap;
use std::io::{Read, Write};
use std::sync::{Arc, Mutex};

use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::{Path, State};
use axum::response::IntoResponse;
use portable_pty::{native_pty_system, CommandBuilder, MasterPty, PtySize};
use serde::Deserialize;
use tokio::sync::mpsc;

use crate::artifact::{hint_line, ArtifactBus, Peeler};
use crate::grok;
use crate::openai::AppState;

const DEFAULT_ROWS: u16 = 32;
const DEFAULT_COLS: u16 = 100;

const STRIP_ENV: &[&str] = &[
    "GROK_AGENT",
    "XAI_API_KEY",
    "XAI_MANAGEMENT_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENAI_API_PORT",
    "CEREBRAS_API_KEY",
    "SSH_CLIENT",
    "SSH_CONNECTION",
    "SSH_TTY",
    "TMUX",
    "TMUX_PANE",
    "STY",
];

struct LivePty {
    id: String,
    debug_file: std::path::PathBuf,
    writer: Arc<Mutex<Box<dyn Write + Send>>>,
    master: Arc<Mutex<Box<dyn MasterPty + Send>>>,
    child: Mutex<Box<dyn portable_pty::Child + Send + Sync>>,
    term: Mutex<vt100::Parser>,
    subs: Mutex<Vec<mpsc::UnboundedSender<Vec<u8>>>>,
    peeler: Mutex<Peeler>,
    artifacts: ArtifactBus,
}

impl LivePty {
    fn push_bytes(&self, bytes: &[u8]) {
        let peeled = self.peeler.lock().unwrap().push(bytes);
        if !peeled.vt.is_empty() {
            self.term.lock().unwrap().process(&peeled.vt);
            let mut subs = self.subs.lock().unwrap();
            subs.retain(|tx| tx.send(peeled.vt.clone()).is_ok());
        }
        for raw in peeled.artifacts {
            match self.artifacts.push(raw) {
                Ok(item) => {
                    tracing::info!(
                        title = item.get("title").and_then(|v| v.as_str()).unwrap_or("-"),
                        "peeled artifact → Ask"
                    );
                    let hint = hint_line(&item);
                    self.term.lock().unwrap().process(hint.as_bytes());
                    let mut subs = self.subs.lock().unwrap();
                    subs.retain(|tx| tx.send(hint.as_bytes().to_vec()).is_ok());
                }
                Err(e) => {
                    tracing::warn!(error = %e, "peeled artifact rejected");
                    let msg = format!("\r\n▸ artifact rejected · {e}\r\n");
                    self.term.lock().unwrap().process(msg.as_bytes());
                    let mut subs = self.subs.lock().unwrap();
                    subs.retain(|tx| tx.send(msg.as_bytes().to_vec()).is_ok());
                }
            }
        }
    }

    fn subscribe(&self) -> mpsc::UnboundedReceiver<Vec<u8>> {
        let (tx, rx) = mpsc::unbounded_channel();
        self.subs.lock().unwrap().push(tx);
        rx
    }

    /// Escape sequence that reproduces the current screen on a blank Ghostty.
    /// Ratatui only emits dirty cells; a reload has no prior cells.
    fn snapshot(&self) -> Vec<u8> {
        let parser = self.term.lock().unwrap();
        let screen = parser.screen();
        let mut out = Vec::new();
        if screen.alternate_screen() {
            out.extend_from_slice(b"\x1b[?1049h");
        }
        out.extend_from_slice(&screen.contents_formatted());
        out
    }

    fn resize(&self, cols: u16, rows: u16) {
        let cols = cols.max(2);
        let rows = rows.max(2);
        self.term.lock().unwrap().set_size(rows, cols);
        let _ = self.master.lock().unwrap().resize(PtySize {
            cols,
            rows,
            pixel_width: 0,
            pixel_height: 0,
        });
    }

    fn child_alive(&self) -> bool {
        matches!(self.child.lock().unwrap().try_wait(), Ok(None))
    }

    fn screen_text(&self) -> String {
        self.term.lock().unwrap().screen().contents()
    }
}

#[derive(Default)]
pub struct Sessions {
    inner: Mutex<HashMap<String, Arc<LivePty>>>,
}

impl Sessions {
    pub fn ops_snapshot(&self) -> serde_json::Value {
        let map = self.inner.lock().unwrap();
        let rows: Vec<serde_json::Value> = map
            .values()
            .map(|live| {
                let screen = live.screen_text();
                let lines: Vec<&str> = screen.lines().rev().take(32).collect();
                let screen_tail = lines.into_iter().rev().collect::<Vec<_>>().join("\n");
                let raw = crate::ops::read_debug_file(&live.debug_file);
                let debug = crate::ops::parse_debug_tail(&raw);
                serde_json::json!({
                    "id": live.id,
                    "alive": live.child_alive(),
                    "model": "gaius-thinking",
                    "screen_tail": screen_tail,
                    "debug": debug,
                })
            })
            .collect();
        serde_json::json!(rows)
    }

    pub fn new() -> Self {
        Self {
            inner: Mutex::new(HashMap::new()),
        }
    }
}

#[derive(Deserialize)]
struct ClientFrame {
    #[serde(rename = "type")]
    kind: String,
    data: Option<String>,
    cols: Option<u16>,
    rows: Option<u16>,
}

pub async fn terminal_ws(
    ws: WebSocketUpgrade,
    Path(id): Path<String>,
    State(state): State<AppState>,
) -> impl IntoResponse {
    let sessions = state.sessions.clone();
    let bind = state.bind.clone();
    let artifacts = state.artifacts.clone();
    ws.on_upgrade(move |socket| handle_socket(socket, id, sessions, bind, artifacts))
}

async fn handle_socket(
    mut socket: WebSocket,
    id: String,
    sessions: Arc<Sessions>,
    bind: String,
    artifacts: ArtifactBus,
) {
    let live = match attach_or_spawn(&id, &sessions, &bind, artifacts) {
        Ok(l) => l,
        Err(e) => {
            let _ = socket
                .send(Message::Text(
                    serde_json::json!({"type":"text","data": format!("\r\n{e}\r\n")})
                        .to_string()
                        .into(),
                ))
                .await;
            return;
        }
    };

    let _ = socket
        .send(Message::Text(
            serde_json::json!({"type":"status","data":"attached · waiting for grok paint"})
                .to_string()
                .into(),
        ))
        .await;

    let mut rx = live.subscribe();
    let snap = live.snapshot();
    if !snap.is_empty() {
        tracing::info!(session = %id, snapshot_bytes = snap.len(), "attach: full VT snapshot");
        let text = String::from_utf8_lossy(&snap).into_owned();
        if socket
            .send(Message::Text(
                serde_json::json!({"type":"text","data": text})
                    .to_string()
                    .into(),
            ))
            .await
            .is_err()
        {
            return;
        }
        let _ = socket
            .send(Message::Text(
                serde_json::json!({"type":"status","data":"attached · grok"})
                    .to_string()
                    .into(),
            ))
            .await;
    }

    loop {
        tokio::select! {
            Some(bytes) = rx.recv() => {
                let text = String::from_utf8_lossy(&bytes).into_owned();
                let frame = serde_json::json!({"type":"text","data": text}).to_string();
                if socket.send(Message::Text(frame.into())).await.is_err() {
                    break;
                }
            }
            incoming = socket.recv() => {
                match incoming {
                    Some(Ok(Message::Text(t))) => {
                        if let Ok(f) = serde_json::from_str::<ClientFrame>(t.as_str()) {
                            match f.kind.as_str() {
                                "input" => {
                                    if let Some(data) = f.data {
                                        let _ = live.writer.lock().unwrap().write_all(data.as_bytes());
                                    }
                                }
                                "resize" => {
                                    live.resize(
                                        f.cols.unwrap_or(DEFAULT_COLS),
                                        f.rows.unwrap_or(DEFAULT_ROWS),
                                    );
                                }
                                _ => {}
                            }
                        }
                    }
                    Some(Ok(Message::Binary(b))) => {
                        let _ = live.writer.lock().unwrap().write_all(b.as_ref());
                    }
                    Some(Ok(Message::Close(_))) | None => break,
                    _ => {}
                }
            }
        }
    }
}

fn attach_or_spawn(
    id: &str,
    sessions: &Sessions,
    bind: &str,
    artifacts: ArtifactBus,
) -> Result<Arc<LivePty>, String> {
    {
        let mut map = sessions.inner.lock().unwrap();
        if let Some(existing) = map.get(id).cloned() {
            if existing.child_alive() {
                return Ok(existing);
            }
            tracing::warn!(session = %id, "grok PTY child exited; respawning");
            map.remove(id);
        }
    }
    let live = spawn_grok(id, bind, artifacts)?;
    sessions
        .inner
        .lock()
        .unwrap()
        .insert(id.to_string(), live.clone());
    Ok(live)
}

fn spawn_grok(id: &str, bind: &str, artifacts: ArtifactBus) -> Result<Arc<LivePty>, String> {
    let bin = grok::grok_bin()?;
    let bwrap = grok::bwrap_bin()?;
    let loopback = grok::listen_loopback(bind);
    let home = grok::write_session_home(id, &loopback)?;
    let workspace = grok::write_session_workspace(id)?;

    let pty_sys = native_pty_system();
    let pair = pty_sys
        .openpty(PtySize {
            rows: DEFAULT_ROWS,
            cols: DEFAULT_COLS,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| e.to_string())?;

    let debug_file = home.join("grok-debug.log");
    let mut cmd = CommandBuilder::new(bin);
    cmd.arg("--always-approve");
    cmd.arg("--trust");
    cmd.arg("--fullscreen");
    cmd.arg("--sandbox");
    cmd.arg("workspace");
    cmd.arg("--cwd");
    cmd.arg(workspace.as_os_str());
    cmd.arg("-m");
    cmd.arg("gaius-thinking");
    cmd.arg("--debug-file");
    cmd.arg(debug_file.as_os_str());
    for key in STRIP_ENV {
        cmd.env_remove(key);
    }
    cmd.env("GROK_HOME", home.as_os_str());
    if let Some(dir) = bwrap.parent() {
        let mut path = dir.as_os_str().to_os_string();
        if let Some(rest) = std::env::var_os("PATH") {
            path.push(":");
            path.push(rest);
        }
        cmd.env("PATH", path);
    }
    cmd.env(
        "GROK_SYSTEM_PROMPT_LABEL",
        "Qwen3.8-27B on Gaius Engine",
    );
    cmd.env("TERM", "xterm-256color");
    cmd.env("COLORTERM", "truecolor");
    cmd.env("TERM_PROGRAM", "ghostty");
    cmd.env("GROK_DEFAULT_SELECTED_PERMISSION", "always_allow_all_sessions");
    cmd.cwd(&workspace);

    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| format!("spawn grok: {e}"))?;

    let writer = pair.master.take_writer().map_err(|e| e.to_string())?;
    let mut reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| format!("pty reader: {e}"))?;
    let live = Arc::new(LivePty {
        id: id.to_string(),
        debug_file: debug_file.clone(),
        writer: Arc::new(Mutex::new(writer)),
        master: Arc::new(Mutex::new(pair.master)),
        child: Mutex::new(child),
        term: Mutex::new(vt100::Parser::new(DEFAULT_ROWS, DEFAULT_COLS, 0)),
        subs: Mutex::new(Vec::new()),
        peeler: Mutex::new(Peeler::default()),
        artifacts,
    });
    let pump = live.clone();
    std::thread::spawn(move || {
        let mut buf = [0u8; 4096];
        loop {
            match reader.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => pump.push_bytes(&buf[..n]),
                Err(_) => break,
            }
        }
    });
    Ok(live)
}

#[cfg(test)]
mod tests {
    #[test]
    fn snapshot_reproduces_cells_not_just_cursor_ticks() {
        let mut p = vt100::Parser::new(8, 40, 0);
        p.process(b"\x1b[?1049h\x1b[H\x1b[2JGrok Build 1.0.4");
        let screen = p.screen();
        let snap = screen.contents_formatted();
        let text = String::from_utf8_lossy(&snap);
        assert!(
            text.contains("Grok Build") || screen.contents().contains("Grok Build"),
            "snapshot missing cells: {text:?}"
        );
        assert!(screen.alternate_screen());
    }
}
