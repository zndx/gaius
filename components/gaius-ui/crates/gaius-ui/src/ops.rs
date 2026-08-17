//! Live operational snapshot for Ask: inflight Complete, Terminal
//! screen, grok-debug tail. Ask answers *about* thinking from this,
//! on its own capability — it does not wait for thinking to finish.

use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::pty::Sessions;

#[derive(Clone, Debug)]
pub struct Inflight {
    pub id: u64,
    pub cap: String,
    pub client: String,
    pub started_ms: u64,
    pub prompt_preview: String,
}

#[derive(Clone, Default)]
pub struct CompleteWatch {
    inner: Arc<Mutex<Inner>>,
}

#[derive(Default)]
struct Inner {
    next_id: u64,
    items: Vec<Inflight>,
}

impl CompleteWatch {
    pub fn begin(&self, cap: impl Into<String>, client: impl Into<String>, prompt: &str) -> u64 {
        let mut g = self.inner.lock().expect("complete watch");
        g.next_id += 1;
        let id = g.next_id;
        g.items.push(Inflight {
            id,
            cap: cap.into(),
            client: client.into(),
            started_ms: now_ms(),
            prompt_preview: preview(prompt, 240),
        });
        id
    }

    pub fn guard(
        &self,
        cap: impl Into<String>,
        client: impl Into<String>,
        prompt: &str,
    ) -> WatchGuard {
        WatchGuard {
            watch: self.clone(),
            id: self.begin(cap, client, prompt),
        }
    }

    pub fn end(&self, id: u64) {
        let mut g = self.inner.lock().expect("complete watch");
        g.items.retain(|i| i.id != id);
    }

    pub fn thinking_busy(&self) -> bool {
        self.inner
            .lock()
            .expect("complete watch")
            .items
            .iter()
            .any(|i| i.cap == "thinking" || i.client == "terminal")
    }

    pub fn snapshot(&self) -> Value {
        let now = now_ms();
        let items: Vec<Value> = self
            .inner
            .lock()
            .expect("complete watch")
            .items
            .iter()
            .map(|i| {
                json!({
                    "id": i.id,
                    "cap": i.cap,
                    "client": i.client,
                    "elapsed_s": now.saturating_sub(i.started_ms) / 1000,
                    "prompt_preview": i.prompt_preview,
                })
            })
            .collect();
        json!(items)
    }
}

pub struct WatchGuard {
    watch: CompleteWatch,
    id: u64,
}

impl Drop for WatchGuard {
    fn drop(&mut self) {
        self.watch.end(self.id);
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn preview(s: &str, n: usize) -> String {
    let t = s.split_whitespace().collect::<Vec<_>>().join(" ");
    if t.chars().count() <= n {
        return t;
    }
    t.chars().take(n).collect::<String>() + "…"
}

pub fn parse_debug_tail(raw: &str) -> Value {
    let lines: Vec<&str> = raw.lines().rev().take(80).collect();
    let mut last_prompt = String::new();
    let mut last_tools: Vec<String> = Vec::new();
    let mut last_stop = String::new();
    let mut has_tool_call = false;
    for line in lines.iter().rev() {
        if let Some(idx) = line.find("\"text\":\"") {
            if last_prompt.is_empty() && line.contains("session/prompt") {
                let rest = &line[idx + 8..];
                if let Some(end) = rest.find('"') {
                    last_prompt = rest[..end].replace("\\n", " ");
                }
            }
        }
        if line.contains("gaius__") {
            for part in line.split(|c: char| !c.is_ascii_alphanumeric() && c != '_') {
                if part.starts_with("gaius__") && !last_tools.iter().any(|t| t == part) {
                    last_tools.push(part.to_string());
                }
            }
        }
        if line.contains("has_tool_call=true") {
            has_tool_call = true;
        }
        if line.contains("stop_reason=") && last_stop.is_empty() {
            if let Some(i) = line.find("stop_reason=\"") {
                let rest = &line[i + 13..];
                last_stop = rest.split('"').next().unwrap_or("").to_string();
            } else if let Some(i) = line.find("stop_reason=") {
                last_stop = line[i + 12..]
                    .split(|c: char| c == ' ' || c == '}' || c == ',')
                    .next()
                    .unwrap_or("")
                    .to_string();
            }
        }
    }
    let tail: Vec<String> = raw
        .lines()
        .rev()
        .filter(|l| {
            l.contains("session/prompt")
                || l.contains("has_tool_call")
                || l.contains("gaius__")
                || l.contains("Engine/Complete")
                || l.contains("stop_reason")
                || l.contains("ERROR")
                || l.contains("WARN")
        })
        .take(24)
        .map(|l| preview(l, 220))
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    json!({
        "last_prompt": last_prompt,
        "last_tools": last_tools,
        "last_stop": last_stop,
        "has_tool_call": has_tool_call,
        "tail": tail,
    })
}

pub fn read_debug_file(path: &Path) -> String {
    let Ok(bytes) = std::fs::read(path) else {
        return String::new();
    };
    let start = bytes.len().saturating_sub(48 * 1024);
    String::from_utf8_lossy(&bytes[start..]).into_owned()
}

pub fn snapshot(sessions: &Sessions, watch: &CompleteWatch, ask_backend: &str, ask_cap: &str) -> Value {
    json!({
        "ask_backend": ask_backend,
        "ask_capability": ask_cap,
        "thinking_busy": watch.thinking_busy(),
        "complete": watch.snapshot(),
        "terminal": sessions.ops_snapshot(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn watch_tracks_thinking() {
        let w = CompleteWatch::default();
        assert!(!w.thinking_busy());
        let id = w.begin("thinking", "terminal", "chart $SLB");
        assert!(w.thinking_busy());
        w.end(id);
        assert!(!w.thinking_busy());
    }

    #[test]
    fn debug_tail_extracts_prompt_and_tools() {
        let raw = r#"
2026-08-17T15:21:18Z sending session/prompt {"prompt":[{"type":"text","text":"Generate a 30 day performance shart for $SLB"}]}
2026-08-17T15:21:05Z Registered MCP tool 'gaius__ask_present' from server 'gaius'
2026-08-17T15:21:31Z stop_reason="stop" response.has_tool_call=false
"#;
        let v = parse_debug_tail(raw);
        assert!(v["last_prompt"].as_str().unwrap().contains("SLB"));
        assert!(v["last_tools"]
            .as_array()
            .unwrap()
            .iter()
            .any(|t| t.as_str() == Some("gaius__ask_present")));
        assert_eq!(v["last_stop"], "stop");
    }
}
