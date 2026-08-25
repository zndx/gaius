//! OpenAI Chat Completions façade over Engine/Complete.
//!
//! Grok's custom-model backend speaks this HTTP. We do not expose vLLM
//! `:8081` — the harness always goes through the lattice capability.

use std::sync::Arc;

use axum::{
    extract::State,
    http::StatusCode,
    response::{
        sse::{Event, KeepAlive, Sse},
        IntoResponse, Response,
    },
    Json,
};
use serde::Deserialize;
use serde_json::json;
use tokio_stream::StreamExt;

use crate::artifact::ArtifactBus;
use crate::ask_write;
use crate::engine::{CompleteExtras, CompleteOut, EngineError, Lattice};
use crate::brand::Brand;
use crate::pty::Sessions;
use std::path::PathBuf;
use std::sync::RwLock;

#[derive(Clone)]
pub struct AppState {
    pub lattice: Lattice,
    pub sessions: Arc<Sessions>,
    pub bind: String,
    pub brand: Arc<RwLock<Brand>>,
    pub settings_path: PathBuf,
    pub assets_dir: PathBuf,
    pub custom_dir: PathBuf,
    pub artifacts: ArtifactBus,
    pub ask_backend: Arc<RwLock<String>>,
    pub complete_watch: crate::ops::CompleteWatch,
}

#[derive(Debug, Default, Deserialize)]
pub struct ChatMessage {
    #[serde(default)]
    pub role: String,
    #[serde(default)]
    pub content: serde_json::Value,
    #[serde(default)]
    pub tool_calls: Option<serde_json::Value>,
    #[serde(default)]
    pub tool_call_id: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct ChatRequest {
    pub messages: Vec<ChatMessage>,
    pub max_tokens: Option<i32>,
    pub temperature: Option<f32>,
    pub stream: Option<bool>,
    pub model: Option<String>,
    /// Client hint: "thinking" when the turn looks like an Agenda write.
    #[serde(default)]
    pub escalate: Option<String>,
    /// Browser Clock (IANA timezone + resolved morning instants).
    #[serde(default)]
    pub clock: Option<serde_json::Value>,
    /// OpenAI tools[] from the Grok harness. Declared to Complete verbatim:
    /// the thinking endpoint runs an engine-level tool parser, so a turn with
    /// no tools[] has its <tool_call> markup eaten and comes back as bare
    /// reasoning — which is what ended Web Terminal turns after one step.
    #[serde(default)]
    pub tools: Option<serde_json::Value>,
    /// OpenAI tool_choice: "auto" | "required" | "none" | named-tool object.
    /// Absent = the engine default (auto whenever tools are declared).
    #[serde(default)]
    pub tool_choice: Option<serde_json::Value>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ParsedToolCall {
    pub name: String,
    pub arguments: serde_json::Value,
}

/// Last-word identity for Engine/Complete. Grok Build hardcodes
/// "released by xAI" in its prompt template; Qwen follows that and
/// claims to be Grok. This block is appended after the harness prompt.
pub const ENGINE_IDENTITY: &str = "\
You are Qwen3.8-27B served locally by Gaius Engine/Complete \
(zndx.engine.v1.Engine, capability=thinking). \
The Grok Build TUI is only the agent harness — not the model. \
You are not Grok and you are not built by xAI. \
When asked what model you are, answer Qwen/Qwen3.8-27B via Gaius Engine/Complete. \
Do not send the user to xAI websites or technical reports for your version.\n\
After a tool result, always write a user-visible answer. \
If the last tool result is a Gaius sitrep (ascii_format or \
GAIUS SITUATION REPORT), show that report. Do not call \
theta_sitrep again in the same turn.\n";

pub fn flatten_messages(messages: &[ChatMessage]) -> (String, String) {
    let mut system = Vec::new();
    let mut body = Vec::new();
    for m in messages {
        let text = rewrite_xai_identity(&message_text(&m.content));
        match m.role.as_str() {
            "system" | "developer" => {
                if !text.is_empty() {
                    system.push(text);
                }
            }
            "assistant" => {
                if text.is_empty() && m.tool_calls.is_none() {
                    continue;
                }
                let mut line = format!("Assistant: {text}");
                if let Some(calls) = m.tool_calls.as_ref() {
                    line.push_str(&format!("\nAssistant tool_calls: {calls}"));
                }
                body.push(line);
            }
            "tool" => {
                let id = m.tool_call_id.as_deref().unwrap_or("-");
                body.push(format!("Tool result ({id}): {text}"));
            }
            _ => {
                if !text.is_empty() {
                    body.push(format!("User: {text}"));
                }
            }
        }
    }
    let system = if system.is_empty() {
        ENGINE_IDENTITY.to_string()
    } else {
        format!("{}\n\n{ENGINE_IDENTITY}", system.join("\n\n"))
    };
    (system, body.join("\n\n"))
}

pub fn rewrite_xai_identity(text: &str) -> String {
    let mut s = text.to_string();
    s = s.replace(
        "You are Grok released by xAI.",
        ENGINE_IDENTITY.trim(),
    );
    s = s.replace("You are Grok, built by xAI.", ENGINE_IDENTITY.trim());
    s = s.replace("You are Grok built by xAI.", ENGINE_IDENTITY.trim());
    s = s.replace(
        "I am Grok, built by xAI.",
        "I am Qwen3.8-27B on Gaius Engine.",
    );
    s = s.replace(
        "I am Grok built by xAI.",
        "I am Qwen3.8-27B on Gaius Engine.",
    );
    s = s.replace(" released by xAI.", ".");
    s = s.replace(" built by xAI.", ".");
    s = s.replace(
        "Externally, refer to yourself uniformly as 'Grok'",
        "Externally, refer to yourself as Qwen3.8-27B on Gaius Engine",
    );
    s = s.replace(
        "direct them to the official website or technical report",
        "name Qwen/Qwen3.8-27B and Gaius Engine/Complete",
    );
    s
}

/// Pull Qwen XML / JSON `<tool_call>` blocks out of completion text so the
/// Grok harness sees OpenAI `tool_calls` instead of raw markup.
pub fn parse_qwen_tool_calls(text: &str) -> (String, Vec<ParsedToolCall>) {
    let mut calls = Vec::new();
    let mut out = String::new();
    let mut rest = text;
    while let Some(start) = rest.find("<tool_call>") {
        out.push_str(&rest[..start]);
        let after = &rest[start + "<tool_call>".len()..];
        match after.find("</tool_call>") {
            Some(end) => {
                if let Some(call) = parse_one_tool_call(after[..end].trim()) {
                    calls.push(normalize_tool_call(call));
                } else {
                    out.push_str(&rest[start..start + "<tool_call>".len() + end + "</tool_call>".len()]);
                }
                rest = &after[end + "</tool_call>".len()..];
            }
            None => {
                out.push_str(&rest[start..]);
                rest = "";
            }
        }
    }
    out.push_str(rest);
    let cleaned = out
        .lines()
        .map(str::trim_end)
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string();
    (cleaned, calls)
}

fn parse_one_tool_call(inner: &str) -> Option<ParsedToolCall> {
    let trimmed = inner.trim();
    if trimmed.starts_with('{') {
        let v: serde_json::Value = serde_json::from_str(trimmed).ok()?;
        let name = clean_tool_name(v.get("name")?.as_str()?);
        let arguments = v.get("arguments").cloned().unwrap_or(json!({}));
        return Some(ParsedToolCall { name, arguments });
    }
    let fn_tag = trimmed.find("<function=")?;
    let name_start = fn_tag + "<function=".len();
    let name_end = trimmed[name_start..].find('>')? + name_start;
    let name = clean_tool_name(&trimmed[name_start..name_end]);
    let body = &trimmed[name_end + 1..];
    let close = body.rfind("</function>").unwrap_or(body.len());
    let mut arguments = serde_json::Map::new();
    let mut src = &body[..close];
    while let Some(p) = src.find("<parameter=") {
        let ks = p + "<parameter=".len();
        let Some(ke) = src[ks..].find('>') else {
            break;
        };
        let key = src[ks..ks + ke].trim().to_string();
        let after = &src[ks + ke + 1..];
        let (val, nxt) = if let Some(end) = after.find("</parameter>") {
            (after[..end].to_string(), &after[end + "</parameter>".len()..])
        } else {
            break;
        };
        arguments.insert(key, json_param_value(&val));
        src = nxt;
    }
    if name.is_empty() {
        return None;
    }
    Some(ParsedToolCall {
        name,
        arguments: serde_json::Value::Object(arguments),
    })
}

fn json_param_value(raw: &str) -> serde_json::Value {
    let t = raw.trim();
    if let Ok(n) = t.parse::<i64>() {
        return json!(n);
    }
    if let Ok(n) = t.parse::<f64>() {
        return json!(n);
    }
    if t.eq_ignore_ascii_case("true") {
        return json!(true);
    }
    if t.eq_ignore_ascii_case("false") {
        return json!(false);
    }
    json!(t)
}

fn clean_tool_name(s: &str) -> String {
    s.chars().filter(|c| !c.is_whitespace()).collect()
}

fn alias_tool_name(name: &str) -> &str {
    match name {
        "list_files" | "ls" | "list_directory" | "listdir" => "list_dir",
        "sitrep" | "theta_sitrep" | "gaius_theta_sitrep" => "gaius__theta_sitrep",
        "ask_present" | "gaius_ask_present" | "present" => "gaius__ask_present",
        other => other,
    }
}

fn normalize_tool_call(mut call: ParsedToolCall) -> ParsedToolCall {
    call.name = alias_tool_name(&clean_tool_name(&call.name)).to_string();
    if let Some(obj) = call.arguments.as_object_mut() {
        for key in ["tool_name", "name", "tool"] {
            if let Some(v) = obj.get(key).and_then(|x| x.as_str()).map(str::to_string) {
                let cleaned = alias_tool_name(&clean_tool_name(&v)).to_string();
                obj.insert(key.to_string(), json!(cleaned));
            }
        }
        if call.name == "use_tool" {
            if !obj.contains_key("tool_name") {
                if let Some(n) = obj.get("name").or_else(|| obj.get("tool")).cloned() {
                    obj.insert("tool_name".into(), n);
                }
            }
            if let Some(inner) = obj.get("tool_input").cloned() {
                if let Some(s) = inner.as_str() {
                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(s) {
                        obj.insert("tool_input".into(), v);
                    }
                } else if let Some(map) = inner.as_object() {
                    if let Some(args) = map.get("arguments") {
                        let parsed = match args {
                            serde_json::Value::String(s) => {
                                serde_json::from_str(s).unwrap_or_else(|_| args.clone())
                            }
                            other => other.clone(),
                        };
                        if parsed.is_object() {
                            obj.insert("tool_input".into(), parsed);
                        }
                    }
                }
            }
            if !obj.contains_key("tool_input") {
                let mut inner = serde_json::Map::new();
                let keys: Vec<String> = obj.keys().cloned().collect();
                for k in keys {
                    if matches!(k.as_str(), "tool_name" | "name" | "tool") {
                        continue;
                    }
                    if let Some(v) = obj.remove(&k) {
                        inner.insert(k, v);
                    }
                }
                if !inner.is_empty() {
                    obj.insert("tool_input".into(), serde_json::Value::Object(inner));
                }
            }
            if let Some(tn) = obj
                .get("tool_name")
                .and_then(|v| v.as_str())
                .map(str::to_string)
            {
                if tn.starts_with("gaius__") {
                    let input = obj.get("tool_input").cloned().unwrap_or(json!({}));
                    let args = input
                        .get("arguments")
                        .filter(|v| v.is_object())
                        .cloned()
                        .unwrap_or(input);
                    call.name = tn;
                    call.arguments = if args.is_object() { args } else { json!({}) };
                    return call;
                }
            }
        }
        if call.name == "list_dir" && !obj.contains_key("target_directory") {
            if let Some(path) = obj.remove("path") {
                obj.insert("target_directory".into(), path);
            } else {
                obj.insert("target_directory".into(), json!("."));
            }
        }
    }
    call
}

fn tool_calls_json(calls: &[ParsedToolCall]) -> serde_json::Value {
    json!(calls
        .iter()
        .enumerate()
        .map(|(i, c)| {
            json!({
                "id": format!("gaius-call-{i}"),
                "type": "function",
                "function": {
                    "name": c.name,
                    "arguments": c.arguments.to_string(),
                }
            })
        })
        .collect::<Vec<_>>())
}

/// Rebuild the harness turns as an OpenAI `messages[]` for
/// `CompleteRequest.messages_json`, with `system` as the leading system turn.
///
/// `flatten_messages` collapses the transcript into one prompt string, and
/// `thinking_complete_prompt` then keeps only lines that begin with
/// "Assistant:" or "Tool result". That drops the `Assistant tool_calls:` line
/// outright and truncates every tool result to its first line — so a `ps aux`
/// or `read_file` result reached the model as a single fragment with no call
/// attached to it. The model could not tell the work had been done and
/// re-issued the same command, forever. Tool turns must reach the chat
/// template as their own turns.
pub fn harness_messages(messages: &[ChatMessage], system: &str) -> serde_json::Value {
    let mut out = vec![json!({"role": "system", "content": system})];
    for m in messages {
        match m.role.as_str() {
            // Already merged into `system` by flatten_messages.
            "system" | "developer" => {}
            "assistant" => {
                let text = rewrite_xai_identity(&message_text(&m.content));
                match m.tool_calls.as_ref() {
                    Some(calls) => out.push(json!({
                        "role": "assistant",
                        "content": text,
                        "tool_calls": calls,
                    })),
                    None if !text.trim().is_empty() => {
                        out.push(json!({"role": "assistant", "content": text}))
                    }
                    None => {}
                }
            }
            "tool" => {
                // vLLM pairs the result to its call by id; without one the
                // template cannot render a <tool_response> for it.
                let id = m.tool_call_id.as_deref().unwrap_or("").trim().to_string();
                if id.is_empty() {
                    continue;
                }
                out.push(json!({
                    "role": "tool",
                    "tool_call_id": id,
                    "content": message_text(&m.content),
                }));
            }
            _ => {
                let text = rewrite_xai_identity(&message_text(&m.content));
                if !text.trim().is_empty() {
                    out.push(json!({"role": "user", "content": text}));
                }
            }
        }
    }
    serde_json::Value::Array(out)
}

/// True when the transcript carries a tool turn — the case the flattened
/// prompt cannot represent.
pub fn has_tool_turns(messages: &[ChatMessage]) -> bool {
    messages
        .iter()
        .any(|m| m.role == "tool" || m.tool_calls.is_some())
}

/// Serialize the harness `tools[]` for `CompleteRequest.tools_json`.
/// Anything that is not a non-empty array is a text-only Complete.
pub fn tools_json(tools: Option<&serde_json::Value>) -> String {
    match tools.and_then(|v| v.as_array()) {
        Some(arr) if !arr.is_empty() => serde_json::Value::Array(arr.clone()).to_string(),
        _ => String::new(),
    }
}

/// Serialize `tool_choice` for `CompleteRequest.tool_choice`. A bare string
/// ("auto" / "required" / "none") passes through; a named-tool object is sent
/// as JSON. Absent leaves the engine default.
pub fn tool_choice_str(choice: Option<&serde_json::Value>) -> String {
    match choice {
        Some(serde_json::Value::String(s)) => s.trim().to_string(),
        Some(v @ serde_json::Value::Object(_)) => v.to_string(),
        _ => String::new(),
    }
}

fn stream_tool_deltas(calls: &[ParsedToolCall]) -> serde_json::Value {
    json!(calls
        .iter()
        .enumerate()
        .map(|(i, c)| {
            json!({
                "index": i,
                "id": format!("gaius-call-{i}"),
                "type": "function",
                "function": {
                    "name": c.name,
                    "arguments": c.arguments.to_string(),
                }
            })
        })
        .collect::<Vec<_>>())
}

/// Split Qwen/Qwen-style `<think>` blocks out of visible text.
pub fn peel_think(text: &str) -> (String, String) {
    let mut s = text.to_string();
    let mut thoughts = String::new();
    while let Some(start) = s.find("<think>") {
        if let Some(rel) = s[start..].find("</think>") {
            let body_start = start + "<think>".len();
            let body_end = start + rel;
            let end = body_end + "</think>".len();
            let body = s[body_start..body_end].trim();
            if !body.is_empty() {
                if !thoughts.is_empty() {
                    thoughts.push('\n');
                }
                thoughts.push_str(body);
            }
            s.replace_range(start..end, "");
        } else {
            let body = s[start + "<think>".len()..].trim();
            if !body.is_empty() {
                if !thoughts.is_empty() {
                    thoughts.push('\n');
                }
                thoughts.push_str(body);
            }
            s.replace_range(start.., "");
            break;
        }
    }
    (s.trim().to_string(), thoughts)
}

pub fn strip_think_tags(text: &str) -> String {
    peel_think(text).0
}

fn merge_reasoning(engine: &str, peeled: &str) -> String {
    match (engine.is_empty(), peeled.is_empty()) {
        (true, true) => String::new(),
        (false, true) => engine.to_string(),
        (true, false) => peeled.to_string(),
        (false, false) => format!("{engine}\n{peeled}"),
    }
}

/// Grok treats reasoning-only completions as ``no_visible_content``.
/// Promote the think trace (or a sitrep tool payload) so the turn is visible.
pub fn visible_completion(content: &str, reasoning: &str) -> String {
    let content = content.trim();
    if !content.is_empty() {
        return content.to_string();
    }
    strip_think_tags(reasoning)
}

fn message_text(content: &serde_json::Value) -> String {
    match content {
        serde_json::Value::Null => String::new(),
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Array(parts) => parts
            .iter()
            .filter_map(|p| {
                p.get("text")
                    .and_then(|t| t.as_str())
                    .map(str::to_string)
                    .or_else(|| p.as_str().map(str::to_string))
            })
            .collect::<Vec<_>>()
            .join(""),
        other => other.to_string(),
    }
}

fn openai_completion(
    stream: bool,
    model: &str,
    content: String,
    reasoning: &str,
    calls: &[ParsedToolCall],
    prompt_tokens: u32,
    completion_tokens: u32,
) -> Response {
    let created = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let id = format!("gaius-{created}");
    let usage = json!({
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    });
    let finish = if calls.is_empty() {
        "stop"
    } else {
        "tool_calls"
    };
    let reasoning = if reasoning.is_empty() {
        serde_json::Value::Null
    } else {
        serde_json::Value::String(reasoning.to_string())
    };
    if stream {
        let mut delta = json!({
            "role": "assistant",
            "content": content,
            "reasoning_content": reasoning,
        });
        if !calls.is_empty() {
            delta["tool_calls"] = stream_tool_deltas(calls);
        }
        let chunk = json!({
            "id": id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": finish
            }],
            "usage": usage,
        });
        let body = format!("data: {chunk}\n\ndata: [DONE]\n\n");
        (
            StatusCode::OK,
            [
                (axum::http::header::CONTENT_TYPE, "text/event-stream"),
                (axum::http::header::CACHE_CONTROL, "no-cache"),
            ],
            body,
        )
            .into_response()
    } else {
        Json(json!({
            "id": id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning,
                    "tool_calls": tool_calls_json(calls)
                },
                "finish_reason": finish
            }],
            "usage": usage,
        }))
        .into_response()
    }
}

fn ask_capability(state: &AppState, model: Option<&str>) -> String {
    match model {
        Some("ask") | Some("gaius-ask") => {
            let backend = state
                .ask_backend
                .read()
                .expect("ask backend lock")
                .clone();
            crate::brand::ask_complete_alias(&backend).to_string()
        }
        _ => state.lattice.capability().to_string(),
    }
}

/// OpenAI chunk envelope. Grok's sampler requires `id`, `created`, and `model`
/// on every `chat.completion.chunk` (`ChatCompletionChunk.id` is not optional).
#[derive(Clone)]
struct SseCtx {
    id: String,
    created: u64,
    model: String,
}

impl SseCtx {
    fn new(model: impl Into<String>) -> Self {
        let created = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        Self {
            id: format!("gaius-{created}"),
            created,
            model: model.into(),
        }
    }

    fn event(&self, delta: serde_json::Value, finish: Option<&str>) -> String {
        json!({
            "id": self.id,
            "object": "chat.completion.chunk",
            "created": self.created,
            "model": self.model,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": finish,
            }]
        })
        .to_string()
    }

    fn delta(
        &self,
        progress: Option<&str>,
        reasoning: Option<&str>,
        content: Option<&str>,
    ) -> String {
        let mut delta = json!({ "role": "assistant" });
        if let Some(p) = progress {
            delta["progress"] = json!(p);
        }
        if let Some(r) = reasoning {
            delta["reasoning_content"] = json!(r);
        }
        if let Some(c) = content {
            delta["content"] = json!(c);
        }
        self.event(delta, None)
    }

    fn status(&self, text: &str, phase: &str, seq: u32, elapsed_ms: u64) -> String {
        self.event(
            json!({
                "role": "assistant",
                "status": text,
                "phase": phase,
                "seq": seq,
                "elapsed_ms": elapsed_ms,
            }),
            None,
        )
    }

    fn agenda(&self, item: &serde_json::Value) -> String {
        self.event(json!({ "role": "assistant", "agenda": item }), None)
    }

    fn done(&self) -> String {
        self.event(json!({}), Some("stop"))
    }

    fn tool_calls(&self, calls: &[ParsedToolCall]) -> String {
        self.event(
            json!({
                "role": "assistant",
                "tool_calls": stream_tool_deltas(calls),
            }),
            Some("tool_calls"),
        )
    }
}

fn estimate_tokens(chars: usize) -> u32 {
    if chars == 0 {
        0
    } else {
        (chars / 4).max(1) as u32
    }
}

fn format_token_n(n: u32) -> String {
    if n >= 1_000_000 {
        format!("{:.1}M", f64::from(n) / 1_000_000.0)
    } else if n >= 1_000 {
        format!("{:.1}k", f64::from(n) / 1_000.0)
    } else {
        n.to_string()
    }
}

/// Metabot-shaped liveness line: phase + elapsed + token estimates.
fn heartbeat_text(
    phase: &str,
    elapsed_s: u32,
    pin: Option<u32>,
    pout: Option<u32>,
    thought: Option<u32>,
    estimated: bool,
) -> String {
    let tilde = if estimated { "~" } else { "" };
    let mut s = format!("Engine · {phase} · {elapsed_s}s");
    if pin.is_some() || pout.is_some() {
        s.push_str(&format!(
            " · {tilde}{} in / {tilde}{} out",
            format_token_n(pin.unwrap_or(0)),
            format_token_n(pout.unwrap_or(0))
        ));
        if let Some(t) = thought {
            if t > 0 {
                s.push_str(&format!(" / {tilde}{} thought", format_token_n(t)));
            }
        }
    }
    s
}

fn chunk_text(s: &str, n: usize) -> Vec<String> {
    if s.is_empty() {
        return Vec::new();
    }
    let mut out = Vec::new();
    let mut buf = String::new();
    for ch in s.chars() {
        buf.push(ch);
        if buf.chars().count() >= n {
            out.push(std::mem::take(&mut buf));
        }
    }
    if !buf.is_empty() {
        out.push(buf);
    }
    out
}

async fn complete_ticked(
    lattice: Lattice,
    tx: tokio::sync::mpsc::Sender<String>,
    cap: String,
    prompt: String,
    system: String,
    max_tokens: i32,
    temperature: f32,
    pin_est: u32,
    extras: CompleteExtras,
    ctx: SseCtx,
) -> Result<CompleteOut, EngineError> {
    let _ = tx
        .send(ctx.delta(Some(&format!("Complete {cap}…")), None, None))
        .await;
    let ticker = {
        let tx = tx.clone();
        let ctx = ctx.clone();
        tokio::spawn(async move {
            let t0 = std::time::Instant::now();
            let mut seq = 1u32;
            loop {
                tokio::time::sleep(std::time::Duration::from_millis(2500)).await;
                seq += 1;
                let elapsed = t0.elapsed();
                let line = ctx.status(
                    &heartbeat_text(
                        "thinking",
                        elapsed.as_secs() as u32,
                        Some(pin_est),
                        Some(0),
                        None,
                        true,
                    ),
                    "thinking",
                    seq,
                    elapsed.as_millis() as u64,
                );
                if tx.send(line).await.is_err() {
                    break;
                }
            }
        })
    };
    let result = lattice
        .complete_as(cap, prompt, system, max_tokens, temperature, extras)
        .await;
    ticker.abort();
    result
}

fn call_pairs(calls: &[ParsedToolCall]) -> Vec<(String, serde_json::Value)> {
    calls
        .iter()
        .map(|c| (c.name.clone(), c.arguments.clone()))
        .collect()
}

async fn emit_turn(
    tx: &tokio::sync::mpsc::Sender<String>,
    ctx: &SseCtx,
    out: &CompleteOut,
    pin_est: u32,
    reasoning: &str,
    content: &str,
    calls: &[ParsedToolCall],
) {
    let thought = estimate_tokens(reasoning.chars().count());
    let _ = tx
        .send(ctx.status(
            &heartbeat_text(
                "generating",
                0,
                Some(out.prompt_tokens.max(pin_est)),
                Some(out.completion_tokens),
                Some(thought),
                out.prompt_tokens == 0 && out.completion_tokens == 0,
            ),
            "generating",
            0,
            0,
        ))
        .await;
    if !calls.is_empty() {
        let _ = tx
            .send(ctx.delta(Some(&format!("Tools: {}", calls.len())), None, None))
            .await;
    }
    for piece in chunk_text(reasoning, 220) {
        let _ = tx.send(ctx.delta(None, Some(&piece), None)).await;
    }
    for piece in chunk_text(content, 120) {
        let _ = tx.send(ctx.delta(None, None, Some(&piece))).await;
    }
}

async fn apply_chart(
    tx: &tokio::sync::mpsc::Sender<String>,
    ctx: &SseCtx,
    artifacts: &ArtifactBus,
    spec: &serde_json::Value,
) {
    let symbol = spec
        .get("symbol")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_ascii_uppercase();
    if symbol.is_empty() {
        let _ = tx
            .send(ctx.delta(
                Some("Chart needs a ticker"),
                None,
                Some("ohlc needs a symbol.\n  Guru: #UI.00000008.NOBARS"),
            ))
            .await;
        return;
    }
    let from = spec
        .get("from_date")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let to = spec
        .get("to_date")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    let _ = tx
        .send(ctx.delta(Some(&format!("Fetching {symbol} EOD…")), None, None))
        .await;
    match crate::gaius::Gaius::from_env()
        .ask_present(
            spec.get("kind").and_then(|v| v.as_str()).unwrap_or("ohlc"),
            &symbol,
            spec.get("title").and_then(|v| v.as_str()).unwrap_or(""),
            &from,
            &to,
            "",
        )
        .await
    {
        Ok(item) => match artifacts.push(item) {
            Ok(_) => {
                let md = format!("Candles for **{symbol}** are in Ask.");
                let _ = tx
                    .send(ctx.delta(Some("Chart posted"), None, Some(&md)))
                    .await;
            }
            Err(e) => {
                let _ = tx
                    .send(ctx.delta(Some("Chart rejected"), None, Some(&e)))
                    .await;
            }
        },
        Err(e) => {
            // The chart is optional; say so, and keep the provider's text
            // clearly subordinate to whatever the turn already answered.
            let _ = tx
                .send(ctx.delta(
                    Some("Chart fetch failed"),
                    None,
                    Some(&format!("\n\n_Chart for {symbol} unavailable — {e}_\n")),
                ))
                .await;
        }
    }
}

async fn apply_and_confirm(
    tx: &tokio::sync::mpsc::Sender<String>,
    ctx: &SseCtx,
    spec: &serde_json::Value,
    clock: Option<&serde_json::Value>,
) {
    let title = spec
        .get("title")
        .and_then(|v| v.as_str())
        .unwrap_or("item");
    let _ = tx
        .send(ctx.delta(Some(&format!("Creating {title}…")), None, None))
        .await;
    match ask_write::apply_agenda_spec(spec, clock).await {
        Ok(created) => {
            let _ = tx.send(ctx.agenda(&created)).await;
            let md = ask_write::confirm_markdown(&created);
            let _ = tx
                .send(ctx.delta(Some("Booked on Agenda"), None, Some(&md)))
                .await;
        }
        Err(e) => {
            let _ = tx
                .send(ctx.delta(Some("Agenda write failed"), None, Some(&e)))
                .await;
        }
    }
}

async fn stream_complete(
    state: AppState,
    cap: String,
    prompt: String,
    system: String,
    max_tokens: i32,
    temperature: f32,
    escalate: Option<String>,
    clock: Option<serde_json::Value>,
    tools_json: String,
    tool_choice: String,
    turns: Vec<ChatMessage>,
) -> Response {
    let (tx, rx) = tokio::sync::mpsc::channel::<String>(32);
    // A structured turn sends the whole transcript, not the narrowed prompt;
    // estimate against what actually goes on the wire.
    let payload_chars = if turns.is_empty() {
        prompt.len()
    } else {
        turns
            .iter()
            .map(|m| message_text(&m.content).len())
            .sum::<usize>()
    };
    let pin_est = estimate_tokens(system.len() + payload_chars);
    tokio::spawn(async move {
        let client = if ask_write::is_small_ask(&cap) {
            "ask"
        } else {
            "terminal"
        };
        let intent = ask_write::thinking_complete_prompt(&prompt);
        let _inflight = state.complete_watch.guard(&cap, client, &intent);
        let ctx = SseCtx::new(cap.clone());
        let send = |s: String| {
            let tx = tx.clone();
            async move {
                let _ = tx.send(s).await;
            }
        };
        send(ctx.status("Consulting Engine…", "consulting", 0, 0)).await;

        let small = ask_write::is_small_ask(&cap);

        send(ctx.status(
            &heartbeat_text("thinking", 0, Some(pin_est), Some(0), None, true),
            "thinking",
            1,
            0,
        ))
        .await;

        let want_write = escalate.as_deref() == Some("thinking")
            || ask_write::looks_like_agenda_write(&prompt);
        let thinking_cap = state.lattice.capability().to_string();
        let thinking_busy = state.complete_watch.thinking_busy() && small;

        let clock_note = clock
            .as_ref()
            .map(|c| format!("\n\nClock JSON: {c}"))
            .unwrap_or_default();
        if thinking_busy && want_write {
            send(ctx.delta(
                Some("Thinking busy on Terminal — Ask stays here"),
                None,
                Some("Terminal thinking is occupied. I stay on Ask and will use live ops."),
            ))
            .await;
        }

        let mut first_system = if want_write && small {
            format!("{system}\n\n{}", ask_write::HANDOFF_ADDENDUM)
        } else if want_write {
            format!("{system}\n\n{}{clock_note}", ask_write::WRITE_ADDENDUM)
        } else {
            format!(
                "{system}\n\n{}",
                crate::gaius_slash::thinking_capability_card()
            )
        };
        if small {
            let backend = state.ask_backend.read().expect("ask lock").clone();
            let ask_cap = crate::brand::ask_complete_alias(&backend);
            let ops = crate::ops::snapshot(
                &state.sessions,
                &state.complete_watch,
                &backend,
                ask_cap,
            );
            first_system.push_str("\n\n## Live ops (JSON)\n");
            first_system.push_str(&ops.to_string());
            first_system.push_str(
                "\nAsk runs on its own capability. Answer questions about Terminal \
                 thinking from Live ops. Do not wait for thinking to finish.\n",
            );
        }
        let first_max = if want_write && small { 256 } else { max_tokens };

        let tz = clock
            .as_ref()
            .and_then(|c| c.get("timezone").and_then(|v| v.as_str()))
            .unwrap_or("")
            .to_string();
        let clock_json = clock
            .as_ref()
            .map(|c| c.to_string())
            .unwrap_or_default();
        // first_system is the system turn the engine will send; the harness
        // turns follow it verbatim so tool_calls keep their results.
        let messages_json = if turns.is_empty() {
            String::new()
        } else {
            harness_messages(&turns, &first_system).to_string()
        };
        let extras = CompleteExtras {
            timezone: tz.clone(),
            clock_json: clock_json.clone(),
            tools_json,
            tool_choice,
            messages_json,
        };
        let first = complete_ticked(
            state.lattice.clone(),
            tx.clone(),
            cap.clone(),
            intent.clone(),
            first_system.clone(),
            first_max,
            temperature,
            pin_est,
            extras.clone(),
            ctx.clone(),
        )
        .await;
        let first = match first {
            Err(e) if small && cap != thinking_cap => {
                send(ctx.delta(
                    Some(&format!("Ask light/medium not ready — using {thinking_cap}")),
                    None,
                    Some(&format!("{e}")),
                ))
                .await;
                complete_ticked(
                    state.lattice.clone(),
                    tx.clone(),
                    thinking_cap.clone(),
                    intent.clone(),
                    first_system,
                    first_max,
                    temperature,
                    pin_est,
                    extras.clone(),
                    ctx.clone(),
                )
                .await
            }
            other => other,
        };

        let first_out = match first {
            Err(e) => {
                let msg = format!(
                    "Engine/Complete failed ({cap} @ {tgt}).\n  Guru: #GR.00000003.NOCAP\n  {e}\n",
                    tgt = state.lattice.target()
                );
                send(ctx.status("Complete failed", "error", 0, 0)).await;
                send(ctx.delta(Some("Complete failed"), None, Some(&msg))).await;
                send(ctx.done()).await;
                send("[DONE]".into()).await;
                return;
            }
            Ok(out) => Some(out),
        };

        let mut should_escalate = false;
        if let Some(out) = first_out {
            let (parsed, calls) = parse_qwen_tool_calls(&out.text);
            if out.finish_reason == "tool_calls" && calls.is_empty() {
                tracing::warn!(
                    cap = %cap,
                    text_chars = out.text.len(),
                    "Complete finished on tool_calls but no <tool_call> survived — \
                     the turn ends with no call for the harness to run"
                );
            }
            let (stripped, peeled) = peel_think(&parsed);
            let reasoning = merge_reasoning(&out.reasoning, &peeled);
            let pairs = call_pairs(&calls);
            let spec = ask_write::parse_agenda_spec(&stripped, &pairs);
            let ohlc = ask_write::parse_ohlc_spec(&stripped, &pairs, &intent)
                .or_else(|| ask_write::parse_ohlc_spec(&parsed, &pairs, &intent));
            let handoff = ask_write::parse_handoff(&stripped)
                .or_else(|| ask_write::parse_handoff(&parsed));
            should_escalate = small
                && !thinking_busy
                && (want_write || handoff.is_some())
                && spec.is_none()
                && calls.is_empty();

            if !calls.is_empty() {
                emit_turn(&tx, &ctx, &out, pin_est, &reasoning, "", &calls).await;
                let _ = tx.send(ctx.tool_calls(&calls)).await;
                send("[DONE]".into()).await;
                return;
            }

            if let Some(h) = &handoff {
                let reason = h
                    .get("reason")
                    .and_then(|v| v.as_str())
                    .unwrap_or("agenda.write");
                send(ctx.delta(
                    Some(&format!("Handoff → thinking · {reason}")),
                    None,
                    None,
                ))
                .await;
            }

            if !should_escalate {
                // A chart or agenda write is a follow-up, not a replacement.
                // Emitting "" here dropped the answer the model had already
                // written — a sitrep vanished behind a failed SLB.PA chart,
                // leaving only the raw FMP 402 on screen.
                let aside = visible_completion(
                    &ask_write::strip_artifact_fences(&stripped),
                    &reasoning,
                );
                if let Some(ohlc) = ohlc {
                    emit_turn(&tx, &ctx, &out, pin_est, &reasoning, &aside, &calls).await;
                    apply_chart(&tx, &ctx, &state.artifacts, &ohlc).await;
                } else if let Some(spec) = spec {
                    emit_turn(&tx, &ctx, &out, pin_est, &reasoning, &aside, &calls).await;
                    apply_and_confirm(&tx, &ctx, &spec, clock.as_ref()).await;
                } else {
                    let content = visible_completion(&stripped, &reasoning);
                    emit_turn(&tx, &ctx, &out, pin_est, &reasoning, &content, &calls).await;
                    if content.is_empty() && reasoning.is_empty() {
                        send(ctx.delta(
                            Some("Complete returned an empty trace"),
                            None,
                            Some("(empty)"),
                        ))
                        .await;
                    }
                }
            }
        }

        if should_escalate {
            send(ctx.delta(
                Some(&format!("Escalating to {thinking_cap}…")),
                None,
                None,
            ))
            .await;
            let chart_prompt = intent.clone();
            let write_sys = format!("{system}\n\n{}{clock_note}", ask_write::WRITE_ADDENDUM);
            match complete_ticked(
                state.lattice.clone(),
                tx.clone(),
                thinking_cap,
                intent,
                write_sys,
                max_tokens,
                temperature,
                pin_est,
                extras,
                ctx.clone(),
            )
            .await
            {
                Ok(tout) => {
                    let (tparsed, tcalls) = parse_qwen_tool_calls(&tout.text);
                    let (tstripped, tpeeled) = peel_think(&tparsed);
                    let treason = merge_reasoning(&tout.reasoning, &tpeeled);
                    let tpairs = call_pairs(&tcalls);
                    let tspec = ask_write::parse_agenda_spec(&tstripped, &tpairs);
                    let tohlc = ask_write::parse_ohlc_spec(&tstripped, &tpairs, &chart_prompt)
                        .or_else(|| ask_write::parse_ohlc_spec(&tparsed, &tpairs, &chart_prompt));
                    emit_turn(&tx, &ctx, &tout, pin_est, &treason, "", &tcalls).await;
                    if let Some(ohlc) = tohlc {
                        apply_chart(&tx, &ctx, &state.artifacts, &ohlc).await;
                    } else if let Some(spec) = tspec {
                        apply_and_confirm(&tx, &ctx, &spec, clock.as_ref()).await;
                    } else {
                        let content = visible_completion(&tstripped, &treason);
                        if !content.is_empty() {
                            for piece in chunk_text(&content, 120) {
                                send(ctx.delta(None, None, Some(&piece))).await;
                            }
                        }
                        send(ctx.delta(
                            Some("No Agenda write emitted"),
                            None,
                            Some(ask_write::GURU_NOWRITE),
                        ))
                        .await;
                    }
                }
                Err(e) => {
                    let msg = format!(
                        "Engine/Complete failed (thinking @ {tgt}).\n  Guru: #GR.00000003.NOCAP\n  {e}\n",
                        tgt = state.lattice.target()
                    );
                    send(ctx.status("Complete failed", "error", 0, 0)).await;
                    send(ctx.delta(Some("Complete failed"), None, Some(&msg))).await;
                }
            }
        }

        send(ctx.done()).await;
        send("[DONE]".into()).await;
    });
    let stream = tokio_stream::wrappers::ReceiverStream::new(rx).map(|data| {
        Ok::<Event, std::convert::Infallible>(Event::default().data(data))
    });
    Sse::new(stream)
        .keep_alive(KeepAlive::new().interval(std::time::Duration::from_secs(8)))
        .into_response()
}

pub async fn chat_completions(
    State(state): State<AppState>,
    Json(req): Json<ChatRequest>,
) -> Response {
    let (mut system, prompt) = flatten_messages(&req.messages);
    let intent = ask_write::thinking_complete_prompt(&prompt);
    let max_tokens = req.max_tokens.unwrap_or(8192);
    let temperature = req.temperature.unwrap_or(0.2);
    let stream = req.stream.unwrap_or(false);
    let cap = ask_capability(&state, req.model.as_deref());
    let small = ask_write::is_small_ask(&cap);
    // Ask (1.7B / SAE) is served by endpoints launched without
    // --enable-auto-tool-choice and has no tool harness: it answers in
    // artifact fences. Only the Terminal capability declares tools[].
    //
    // These used to be dropped to keep the prompt small (ACP can attach ~180
    // MCP schemas). That is no longer optional: the thinking endpoint's
    // engine-level parser eats <tool_call> markup from an undeclared turn, so
    // dropping tools[] costs the whole tool channel. Grok Build reaches MCP
    // through search_tool/use_tool, so it declares ~24 built-ins, not the
    // server rosters. `tools_chars` below is the size to watch.
    let tools_json = if small {
        String::new()
    } else {
        tools_json(req.tools.as_ref())
    };
    let tool_choice = if tools_json.is_empty() {
        String::new()
    } else {
        tool_choice_str(req.tool_choice.as_ref())
    };
    // Ask has no tool harness, so its transcript flattens without loss. The
    // Terminal's does not: a tool turn only survives as its own message.
    let structured = !small && (has_tool_turns(&req.messages) || !tools_json.is_empty());
    tracing::info!(
        model = req.model.as_deref().unwrap_or("-"),
        system_chars = system.len(),
        prompt_chars = intent.len(),
        tools_chars = tools_json.len(),
        structured,
        // "-" when no tools are declared: tool_choice is meaningless there.
        tool_choice = %if tools_json.is_empty() {
            "-"
        } else if tool_choice.is_empty() {
            "auto"
        } else {
            &tool_choice
        },
        stream,
        "Engine/Complete façade"
    );
    let client = if small { "ask" } else { "terminal" };
    if !small {
        system.push_str("\n\n");
        system.push_str(&crate::gaius_slash::thinking_capability_card());
    }
    if stream {
        return stream_complete(
            state,
            cap,
            prompt,
            system,
            max_tokens,
            temperature,
            req.escalate.clone(),
            req.clock.clone(),
            tools_json,
            tool_choice,
            if structured { req.messages } else { Vec::new() },
        )
        .await;
    }
    let messages_json = if structured {
        harness_messages(&req.messages, &system).to_string()
    } else {
        String::new()
    };
    let _inflight = state.complete_watch.guard(&cap, client, &intent);
    match state
        .lattice
        .complete_as(
            cap,
            intent,
            system,
            max_tokens,
            temperature,
            CompleteExtras {
                timezone: req
                    .clock
                    .as_ref()
                    .and_then(|c| c.get("timezone").and_then(|v| v.as_str()))
                    .unwrap_or("")
                    .to_string(),
                clock_json: req
                    .clock
                    .as_ref()
                    .map(|c| c.to_string())
                    .unwrap_or_default(),
                tools_json,
                tool_choice,
                messages_json,
            },
        )
        .await
    {
        Ok(out) => {
            let (parsed, calls) = parse_qwen_tool_calls(&out.text);
            let (stripped, peeled) = peel_think(&parsed);
            let reasoning = merge_reasoning(&out.reasoning, &peeled);
            let content = visible_completion(&stripped, &reasoning);
            tracing::info!(
                engine_model = %out.model,
                tool_calls = calls.len(),
                finish_reason = %out.finish_reason,
                text_chars = parsed.len(),
                reasoning_chars = reasoning.len(),
                visible_chars = content.len(),
                "Engine/Complete ok"
            );
            openai_completion(
                stream,
                &out.model,
                content,
                &reasoning,
                &calls,
                out.prompt_tokens,
                out.completion_tokens,
            )
        }
        Err(e) => (
            StatusCode::BAD_GATEWAY,
            format!(
                "Engine/Complete failed ({cap} @ {tgt}).\n  Guru: #GR.00000003.NOCAP\n  {e}\n",
                cap = state.lattice.capability(),
                tgt = state.lattice.target()
            ),
        )
            .into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flatten_splits_system() {
        let msgs = vec![
            ChatMessage {
                role: "system".into(),
                content: serde_json::Value::String("be brief".into()),
                ..Default::default()
            },
            ChatMessage {
                role: "user".into(),
                content: serde_json::Value::String("hello".into()),
                ..Default::default()
            },
        ];
        let (sys, body) = flatten_messages(&msgs);
        assert!(sys.contains("be brief"));
        assert!(sys.contains("Qwen3.8-27B"));
        assert!(body.contains("User: hello"));
    }

    #[test]
    fn chunk_text_splits() {
        let bits = chunk_text("abcdefghij", 4);
        assert_eq!(bits, vec!["abcd", "efgh", "ij"]);
        assert!(chunk_text("", 8).is_empty());
    }

    #[test]
    fn heartbeat_text_matches_metabot_shape() {
        let line = heartbeat_text("thinking", 4, Some(1200), Some(0), None, true);
        assert_eq!(line, "Engine · thinking · 4s · ~1.2k in / ~0 out");
        let done = heartbeat_text("generating", 18, Some(1240), Some(400), Some(800), false);
        assert_eq!(
            done,
            "Engine · generating · 18s · 1.2k in / 400 out / 800 thought"
        );
        assert_eq!(estimate_tokens(0), 0);
        assert_eq!(estimate_tokens(9), 2);
    }

    #[test]
    fn sse_status_is_openai_chunk() {
        let ctx = SseCtx::new("thinking");
        let raw = ctx.status("Consulting Engine…", "consulting", 0, 0);
        let v: serde_json::Value = serde_json::from_str(&raw).unwrap();
        assert!(v["id"].as_str().unwrap().starts_with("gaius-"));
        assert_eq!(v["object"], "chat.completion.chunk");
        assert_eq!(v["model"], "thinking");
        assert!(v["created"].as_u64().is_some());
        let delta = &v["choices"][0]["delta"];
        assert_eq!(delta["status"], "Consulting Engine…");
        assert_eq!(delta["phase"], "consulting");
    }

    #[test]
    fn rewrite_strips_xai_identity() {
        let raw = "You are Grok released by xAI. You help write code.";
        let out = rewrite_xai_identity(raw);
        assert!(!out.contains("Grok released by xAI"));
        assert!(out.contains("Qwen3.8-27B"));
    }

    #[test]
    fn flatten_appends_engine_identity() {
        let msgs = vec![ChatMessage {
            role: "system".into(),
            content: serde_json::Value::String(
                "You are Grok released by xAI. Keep tools.".into(),
            ),
            ..Default::default()
        }];
        let (sys, _) = flatten_messages(&msgs);
        assert!(!sys.contains("released by xAI"));
        assert!(sys.contains("Gaius Engine/Complete"));
        assert!(sys.contains("Keep tools."));
    }

    #[test]
    fn parse_qwen_xml_function_blocks() {
        let raw = "\
Good morning! Let me check the workspace state.
<tool_call>
<function=list_files>
<parameter=path>.</parameter>
</function>
</tool_call>
<tool_call>
<function=read_file>
<parameter=limit>100</parameter>
<parameter=offset>1</parameter>
<parameter=path>README.md</parameter>
</function>
</tool_call>
";
        let (text, calls) = parse_qwen_tool_calls(raw);
        assert!(text.contains("Good morning"));
        assert!(!text.contains("<tool_call>"));
        assert_eq!(calls.len(), 2);
        assert_eq!(calls[0].name, "list_dir");
        assert_eq!(calls[0].arguments["target_directory"], ".");
        assert_eq!(calls[1].name, "read_file");
        assert_eq!(calls[1].arguments["path"], "README.md");
        assert_eq!(calls[1].arguments["limit"], 100);
    }

    #[test]
    fn parse_qwen_json_tool_call() {
        let raw = r#"<tool_call>
{"name": "read_file", "arguments": {"path": "README.md"}}
</tool_call>"#;
        let (text, calls) = parse_qwen_tool_calls(raw);
        assert!(text.is_empty());
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].name, "read_file");
        assert_eq!(calls[0].arguments["path"], "README.md");
    }

    #[test]
    fn sitrep_aliases_to_mcp() {
        let raw = r#"<tool_call>
<function=theta_sitrep>
<parameter=horizon>day</parameter>
</function>
</tool_call>"#;
        let (_, calls) = parse_qwen_tool_calls(raw);
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].name, "gaius__theta_sitrep");
        assert_eq!(calls[0].arguments["horizon"], "day");
    }

    #[test]
    fn strips_newlines_from_tool_names_and_use_tool() {
        let raw = "\
<tool_call>
<function=use_tool>
<parameter=tool_name>
gaius__theta_sitrep
</parameter>
<parameter=horizon>day</parameter>
</function>
</tool_call>
";
        let (_, calls) = parse_qwen_tool_calls(raw);
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].name, "gaius__theta_sitrep");
        assert_eq!(calls[0].arguments["horizon"], "day");
    }

    #[test]
    fn sse_tool_calls_finish_reason() {
        let ctx = SseCtx::new("thinking");
        let calls = [ParsedToolCall {
            name: "gaius__ask_present".into(),
            arguments: json!({"symbol": "SLB", "kind": "ohlc"}),
        }];
        let raw = ctx.tool_calls(&calls);
        let v: serde_json::Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(v["choices"][0]["finish_reason"], "tool_calls");
        assert_eq!(
            v["choices"][0]["delta"]["tool_calls"][0]["function"]["name"],
            "gaius__ask_present"
        );
    }

    #[test]
    fn unwraps_use_tool_ask_present() {
        let raw = r#"<tool_call>
{"name":"use_tool","arguments":{"tool_name":"gaius__ask_present","arguments":{"symbol":"SPCX","kind":"ohlc"}}}
</tool_call>"#;
        let (_, calls) = parse_qwen_tool_calls(raw);
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].name, "gaius__ask_present");
        assert_eq!(calls[0].arguments["symbol"], "SPCX");
    }

    #[test]
    fn peel_think_splits_trace() {
        let (vis, think) = peel_think("<think>plan</think>\npong");
        assert_eq!(vis, "pong");
        assert_eq!(think, "plan");
        assert_eq!(merge_reasoning("engine", "plan"), "engine\nplan");
    }

    #[test]
    fn visible_completion_promotes_reasoning() {
        assert_eq!(
            visible_completion("", "<think>hidden</think>\nHEALTHY, 6 GPUs"),
            "HEALTHY, 6 GPUs"
        );
        assert_eq!(visible_completion("shown", "ignored"), "shown");
        assert_eq!(visible_completion("  ", ""), "");
    }

    #[test]
    fn tools_json_forwards_harness_schemas() {
        let tools = json!([
            {"type": "function", "function": {"name": "run_terminal_command"}},
            {"type": "function", "function": {"name": "read_file"}}
        ]);
        let encoded = tools_json(Some(&tools));
        let back: serde_json::Value = serde_json::from_str(&encoded).unwrap();
        assert_eq!(back.as_array().unwrap().len(), 2);
        assert_eq!(back[0]["function"]["name"], "run_terminal_command");
    }

    #[test]
    fn tools_json_empty_for_text_only_complete() {
        assert_eq!(tools_json(None), "");
        assert_eq!(tools_json(Some(&json!([]))), "");
        assert_eq!(tools_json(Some(&json!("nonsense"))), "");
    }

    #[test]
    fn tool_choice_passes_auto_required_and_named() {
        assert_eq!(tool_choice_str(Some(&json!("auto"))), "auto");
        assert_eq!(tool_choice_str(Some(&json!("required"))), "required");
        assert_eq!(tool_choice_str(None), "");
        let named = json!({"type": "function", "function": {"name": "read_file"}});
        let s = tool_choice_str(Some(&named));
        let back: serde_json::Value = serde_json::from_str(&s).unwrap();
        assert_eq!(back["function"]["name"], "read_file");
    }

    /// The thinking endpoint's engine-level parser eats <tool_call> markup
    /// when the request declares no tools[], so a Terminal turn must always
    /// forward them. Ask has no tool harness and its endpoints lack the flag.
    #[test]
    fn ask_capability_never_declares_tools() {
        assert!(ask_write::is_small_ask("interpretable"));
        assert!(ask_write::is_small_ask("ask-sae"));
        assert!(!ask_write::is_small_ask("thinking"));
    }

    fn tool_loop_turns() -> Vec<ChatMessage> {
        vec![
            ChatMessage {
                role: "system".into(),
                content: json!("You are Grok released by xAI."),
                ..Default::default()
            },
            ChatMessage {
                role: "user".into(),
                content: json!("<user_query>\nwhat port is vllm on?\n</user_query>"),
                ..Default::default()
            },
            ChatMessage {
                role: "assistant".into(),
                content: json!(""),
                tool_calls: Some(json!([{
                    "id": "gaius-call-0",
                    "type": "function",
                    "function": {"name": "run_terminal_command",
                                 "arguments": "{\"command\": \"ps aux | grep vllm\"}"}
                }])),
                tool_call_id: None,
            },
            ChatMessage {
                role: "tool".into(),
                content: json!(
                    "rch 468868 vllm serve Qwen/Qwen3.8-27B --port 8081\n                     rch 473186 VLLM::EngineCore\n                     rch 474932 VLLM::Worker_TP0\n                     rch 474933 VLLM::Worker_TP1"
                ),
                tool_call_id: Some("gaius-call-0".into()),
                tool_calls: None,
            },
        ]
    }

    /// The loop this fixes: flattening keeps only lines that start with
    /// "Assistant:" or "Tool result", so a multi-line tool result lost every
    /// line but its first and the tool_calls line vanished entirely.
    #[test]
    fn flattening_truncates_multiline_tool_results() {
        let (_, body) = flatten_messages(&tool_loop_turns());
        let kept = ask_write::thinking_complete_prompt(&body);
        assert!(kept.contains("--port 8081"));
        // Everything after the first line of the result is gone.
        assert!(!kept.contains("VLLM::Worker_TP1"));
        assert!(!kept.contains("VLLM::EngineCore"));
        // And the model never learns which call produced it.
        assert!(!kept.contains("run_terminal_command"));
    }

    #[test]
    fn harness_messages_keeps_the_whole_tool_result() {
        let v = harness_messages(&tool_loop_turns(), "SYSTEM");
        let arr = v.as_array().unwrap();
        let roles: Vec<&str> = arr.iter().map(|m| m["role"].as_str().unwrap()).collect();
        assert_eq!(roles, vec!["system", "user", "assistant", "tool"]);
        assert_eq!(arr[0]["content"], "SYSTEM");

        let tool = &arr[3];
        let content = tool["content"].as_str().unwrap();
        for line in ["--port 8081", "VLLM::EngineCore", "VLLM::Worker_TP1"] {
            assert!(content.contains(line), "tool result lost {line}");
        }
        assert_eq!(tool["tool_call_id"], "gaius-call-0");

        // The call that produced it is paired, by id, as its own turn.
        let call = &arr[2]["tool_calls"][0];
        assert_eq!(call["id"], "gaius-call-0");
        assert_eq!(call["function"]["name"], "run_terminal_command");
    }

    #[test]
    fn harness_messages_drops_a_tool_turn_with_no_id() {
        let turns = vec![
            ChatMessage {
                role: "user".into(),
                content: json!("hi"),
                ..Default::default()
            },
            ChatMessage {
                role: "tool".into(),
                content: json!("orphan output"),
                tool_call_id: None,
                tool_calls: None,
            },
        ];
        let v = harness_messages(&turns, "S");
        let roles: Vec<&str> = v
            .as_array()
            .unwrap()
            .iter()
            .map(|m| m["role"].as_str().unwrap())
            .collect();
        assert_eq!(roles, vec!["system", "user"]);
    }

    #[test]
    fn has_tool_turns_detects_both_sides_of_a_call() {
        assert!(has_tool_turns(&tool_loop_turns()));
        assert!(!has_tool_turns(&[ChatMessage {
            role: "user".into(),
            content: json!("plain question"),
            ..Default::default()
        }]));
    }

    #[test]
    fn native_tool_calls_round_trip_as_markup() {
        // What VLLMController.qwen_tool_call_markup writes back into content.
        let raw = r#"<tool_call>{"name":"run_terminal_command","arguments":{"command":"ss -ltnp"}}</tool_call>"#;
        let (text, calls) = parse_qwen_tool_calls(raw);
        assert_eq!(text, "");
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].name, "run_terminal_command");
        assert_eq!(calls[0].arguments["command"], "ss -ltnp");
    }
}
