//! Ask-panel artifacts. Terminal prose stays on the PTY; structured
//! payloads are peeled here and rendered in the Ask rail.
//!
//! Markers (either is enough):
//!   :::gaius-artifact
//!   { ... json ... }
//!   :::
//!
//!   OSC: ESC ] 1337 ; GaiusArtifact= <base64> BEL

use std::collections::{HashSet, VecDeque};
use std::sync::{Arc, Mutex};

use serde_json::{json, Value};
use uuid::Uuid;

pub const FENCE_OPEN: &str = ":::gaius-artifact";
pub const OSC_HEAD: &str = "\x1b]1337;GaiusArtifact=";
pub const GURU_BAD: &str = "#UI.00000007.BADARTIFACT";
pub const GURU_NOBARS: &str = "#UI.00000008.NOBARS";

const MAX_ITEMS: usize = 32;

#[derive(Clone, Default)]
pub struct ArtifactBus {
    inner: Arc<Mutex<Store>>,
}

#[derive(Default)]
struct Store {
    gen: u64,
    items: VecDeque<Value>,
    ids: HashSet<String>,
}

impl ArtifactBus {
    pub fn push(&self, mut item: Value) -> Result<Value, String> {
        item = coerce(item);
        validate(&item)?;
        if item.get("id").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
            item["id"] = json!(Uuid::new_v4().to_string());
        }
        let id = item["id"].as_str().unwrap_or("").to_string();
        let mut st = self.inner.lock().map_err(|e| e.to_string())?;
        if st.ids.contains(&id) {
            return Ok(item);
        }
        if let Some(key) = ohlc_symbol(&item) {
            if let Some(pos) = st.items.iter().position(|i| ohlc_symbol(i).as_deref() == Some(&key))
            {
                let old = &st.items[pos];
                if old.get("bars") == item.get("bars") {
                    return Ok(old.clone());
                }
                let keep_id = old.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                if !keep_id.is_empty() {
                    item["id"] = json!(keep_id.clone());
                }
                st.gen += 1;
                item["gen"] = json!(st.gen);
                st.items[pos] = item.clone();
                return Ok(item);
            }
        }
        st.ids.insert(id);
        st.gen += 1;
        item["gen"] = json!(st.gen);
        st.items.push_back(item.clone());
        while st.items.len() > MAX_ITEMS {
            if let Some(old) = st.items.pop_front() {
                if let Some(oid) = old.get("id").and_then(|v| v.as_str()) {
                    st.ids.remove(oid);
                }
            }
        }
        Ok(item)
    }

    pub fn since(&self, gen: u64) -> (u64, Vec<Value>) {
        let st = self.inner.lock().expect("artifact lock");
        let items = st
            .items
            .iter()
            .filter(|i| i.get("gen").and_then(|g| g.as_u64()).unwrap_or(0) > gen)
            .cloned()
            .collect();
        (st.gen, items)
    }

    pub fn clear(&self) -> u64 {
        let mut st = self.inner.lock().expect("artifact lock");
        st.items.clear();
        st.ids.clear();
        st.gen += 1;
        st.gen
    }
}

fn ohlc_symbol(item: &Value) -> Option<String> {
    let kind = item
        .get("type")
        .and_then(|v| v.as_str())
        .or_else(|| item.get("kind").and_then(|v| v.as_str()))
        .unwrap_or("");
    if !kind.eq_ignore_ascii_case("ohlc") {
        return None;
    }
    let s = item
        .get("symbol")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_ascii_uppercase();
    if s.is_empty() {
        None
    } else {
        Some(s)
    }
}

pub fn coerce(mut item: Value) -> Value {
    if item.get("type").and_then(|v| v.as_str()).unwrap_or("").is_empty() {
        if let Some(k) = item.get("kind").cloned() {
            item["type"] = k;
        }
    }
    if let Some(bars) = item.get_mut("bars").and_then(|v| v.as_array_mut()) {
        for b in bars {
            if let Some(t) = b.get("t").and_then(|v| v.as_str()) {
                let compact: String = t.chars().filter(|c| !c.is_whitespace()).collect();
                b["t"] = json!(compact);
            }
        }
    }
    item
}

pub fn validate(item: &Value) -> Result<(), String> {
    let kind = item
        .get("type")
        .and_then(|v| v.as_str())
        .or_else(|| item.get("kind").and_then(|v| v.as_str()))
        .unwrap_or("")
        .trim();
    if kind.is_empty() {
        return Err(format!("artifact type required.\n  Guru: {GURU_BAD}"));
    }
    match kind {
        "ohlc" => {
            let bars = item.get("bars").and_then(|v| v.as_array());
            if bars.map(|b| b.is_empty()).unwrap_or(true) {
                return Err(format!(
                    "ohlc artifact needs a non-empty bars array.\n  Guru: {GURU_NOBARS}"
                ));
            }
            for (i, b) in bars.unwrap().iter().enumerate() {
                for k in ["t", "o", "h", "l", "c"] {
                    if b.get(k).is_none() {
                        return Err(format!(
                            "bars[{i}] missing {k}.\n  Guru: {GURU_BAD}"
                        ));
                    }
                }
            }
            Ok(())
        }
        "markdown" | "table" | "links" => Ok(()),
        _ => Err(format!(
            "artifact type must be ohlc, markdown, or table.\n  Guru: {GURU_BAD}"
        )),
    }
}

pub struct PeelOut {
    pub vt: Vec<u8>,
    pub artifacts: Vec<Value>,
}

#[derive(Default)]
pub struct Peeler {
    buf: String,
}

impl Peeler {
    pub fn push(&mut self, bytes: &[u8]) -> PeelOut {
        self.buf.push_str(&String::from_utf8_lossy(bytes));
        let mut vt = String::new();
        let mut artifacts = Vec::new();
        loop {
            if let Some(i) = self.buf.find(OSC_HEAD) {
                vt.push_str(&self.buf[..i]);
                self.buf.replace_range(..i, "");
                match take_osc(&self.buf) {
                    Take::Done { artifact, rest } => {
                        if let Some(a) = artifact {
                            artifacts.push(a);
                        }
                        self.buf = rest;
                        continue;
                    }
                    Take::Incomplete => break,
                }
            }
            if let Some(i) = self.buf.find(FENCE_OPEN) {
                vt.push_str(&self.buf[..i]);
                self.buf.replace_range(..i, "");
                match take_fence(&self.buf) {
                    Take::Done { artifact, rest } => {
                        if let Some(a) = artifact {
                            artifacts.push(a);
                        }
                        self.buf = rest;
                        continue;
                    }
                    Take::Incomplete => break,
                }
            }
            let hold = hold_suffix(&self.buf);
            let emit = self.buf.len().saturating_sub(hold);
            vt.push_str(&self.buf[..emit]);
            self.buf.replace_range(..emit, "");
            break;
        }
        PeelOut {
            vt: vt.into_bytes(),
            artifacts,
        }
    }
}

enum Take {
    Done {
        artifact: Option<Value>,
        rest: String,
    },
    Incomplete,
}

fn take_fence(buf: &str) -> Take {
    if !buf.starts_with(FENCE_OPEN) {
        return Take::Incomplete;
    }
    let after = &buf[FENCE_OPEN.len()..];
    let after = after.strip_prefix('\r').unwrap_or(after);
    if !after.starts_with('\n') {
        if after.is_empty() {
            return Take::Incomplete;
        }
        // not a real fence — drop the marker so we do not stall
        return Take::Done {
            artifact: None,
            rest: after.to_string(),
        };
    }
    let body = &after[1..];
    // close is a line that is exactly :::
    let mut pos = 0;
    while let Some(rel) = body[pos..].find("\n:::") {
        let abs = pos + rel;
        let after_close = &body[abs + 4..];
        let end_ok = after_close.is_empty()
            || after_close.starts_with('\n')
            || after_close.starts_with('\r');
        if end_ok {
            let json_txt = body[..abs].trim();
            let rest = after_close
                .strip_prefix('\r')
                .unwrap_or(after_close)
                .strip_prefix('\n')
                .unwrap_or(after_close)
                .to_string();
            let artifact = parse_payload(json_txt);
            return Take::Done { artifact, rest };
        }
        pos = abs + 4;
    }
    Take::Incomplete
}

fn take_osc(buf: &str) -> Take {
    if !buf.starts_with(OSC_HEAD) {
        return Take::Incomplete;
    }
    let rest = &buf[OSC_HEAD.len()..];
    let (payload, tail) = if let Some(i) = rest.find('\u{7}') {
        (&rest[..i], &rest[i + 1..])
    } else if let Some(i) = rest.find("\x1b\\") {
        (&rest[..i], &rest[i + 2..])
    } else {
        return Take::Incomplete;
    };
    let decoded = b64_decode(payload.trim());
    let artifact = decoded
        .as_deref()
        .and_then(|b| std::str::from_utf8(b).ok())
        .and_then(parse_payload);
    Take::Done {
        artifact,
        rest: tail.to_string(),
    }
}

fn parse_payload(txt: &str) -> Option<Value> {
    if let Ok(v) = serde_json::from_str::<Value>(txt) {
        if v.is_object() {
            return Some(coerce(v));
        }
    }
    let compact: String = txt.chars().filter(|c| !c.is_whitespace()).collect();
    serde_json::from_str::<Value>(&compact)
        .ok()
        .filter(|v| v.is_object())
        .map(coerce)
}

fn hold_suffix(buf: &str) -> usize {
    let candidates = [FENCE_OPEN, OSC_HEAD, "\x1b]1337;", "\x1b]", "\x1b", ":::gaius", ":::", "::", ":"];
    for c in candidates {
        if buf.ends_with(c) {
            return c.len();
        }
        // prefix of a marker at the end
        for n in 1..c.len() {
            if buf.ends_with(&c[..n]) {
                return n;
            }
        }
    }
    0
}

fn b64_decode(s: &str) -> Option<Vec<u8>> {
    let s: String = s.chars().filter(|c| !c.is_whitespace()).collect();
    if s.is_empty() || s.len() % 4 == 1 {
        return None;
    }
    fn val(c: u8) -> Option<u8> {
        match c {
            b'A'..=b'Z' => Some(c - b'A'),
            b'a'..=b'z' => Some(c - b'a' + 26),
            b'0'..=b'9' => Some(c - b'0' + 52),
            b'+' | b'-' => Some(62),
            b'/' | b'_' => Some(63),
            b'=' => Some(0),
            _ => None,
        }
    }
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(s.len() / 4 * 3);
    let mut i = 0;
    while i < bytes.len() {
        let chunk = [
            *bytes.get(i).unwrap_or(&b'='),
            *bytes.get(i + 1).unwrap_or(&b'='),
            *bytes.get(i + 2).unwrap_or(&b'='),
            *bytes.get(i + 3).unwrap_or(&b'='),
        ];
        let a = val(chunk[0])?;
        let b = val(chunk[1])?;
        let c = val(chunk[2])?;
        let d = val(chunk[3])?;
        out.push((a << 2) | (b >> 4));
        if chunk[2] != b'=' {
            out.push((b << 4) | (c >> 2));
        }
        if chunk[3] != b'=' {
            out.push((c << 6) | d);
        }
        i += 4;
    }
    Some(out)
}

pub fn hint_line(item: &Value) -> String {
    let title = item
        .get("title")
        .and_then(|v| v.as_str())
        .or_else(|| item.get("symbol").and_then(|v| v.as_str()))
        .unwrap_or("artifact");
    format!("\r\n▸ {title} · Ask panel\r\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ohlc() -> Value {
        json!({
            "type": "ohlc",
            "title": "NVDA",
            "symbol": "NVDA",
            "bars": [
                {"t":"2026-08-14","o":180.0,"h":182.0,"l":179.0,"c":181.0},
                {"t":"2026-08-15","o":181.0,"h":184.0,"l":180.5,"c":183.4}
            ]
        })
    }

    #[test]
    #[test]
    fn ohlc_same_symbol_does_not_stack() {
        let bus = ArtifactBus::default();
        let a = ohlc();
        let mut b = ohlc();
        b["id"] = json!("other-id");
        bus.push(a).unwrap();
        bus.push(b).unwrap();
        let (_gen, items) = bus.since(0);
        assert_eq!(items.len(), 1, "{items:?}");
        assert_eq!(items[0]["symbol"], "NVDA");
    }

    #[test]
    fn peel_fence_drops_json_from_vt() {
        let mut p = Peeler::default();
        let raw = format!("hello\n{FENCE_OPEN}\n{}\n:::\nworld", ohlc());
        let out = p.push(raw.as_bytes());
        let vt = String::from_utf8_lossy(&out.vt);
        assert!(vt.contains("hello"), "{vt:?}");
        assert!(vt.contains("world"), "{vt:?}");
        assert!(!vt.contains("183.4"), "json leaked: {vt:?}");
        assert_eq!(out.artifacts.len(), 1);
        assert_eq!(out.artifacts[0]["symbol"], "NVDA");
    }

    #[test]
    fn peel_spans_chunks() {
        let mut p = Peeler::default();
        let raw = format!("{FENCE_OPEN}\n{}\n:::\n", ohlc());
        let mid = raw.len() / 2;
        let a = p.push(&raw.as_bytes()[..mid]);
        assert!(a.artifacts.is_empty());
        let b = p.push(&raw.as_bytes()[mid..]);
        assert_eq!(b.artifacts.len(), 1);
        assert!(String::from_utf8_lossy(&b.vt).is_empty() || !String::from_utf8_lossy(&b.vt).contains("183.4"));
    }

    #[test]
    fn peel_osc_base64() {
        let mut p = Peeler::default();
        let json = ohlc().to_string();
        let b64 = b64_encode(json.as_bytes());
        let raw = format!("pre{OSC_HEAD}{b64}\u{7}post");
        let out = p.push(raw.as_bytes());
        let vt = String::from_utf8_lossy(&out.vt);
        assert_eq!(vt, "prepost");
        assert_eq!(out.artifacts.len(), 1);
        assert_eq!(out.artifacts[0]["title"], "NVDA");
    }

    #[test]
    fn peel_accepts_kind_and_wrapped_dates() {
        let mut p = Peeler::default();
        let raw = "Tool result: :::gaius-artifact\n{\"kind\":\"ohlc\",\"title\":\"SPCX\",\"bars\":[{\"t\":\"2026-08-\\n03\",\"o\":1,\"h\":2,\"l\":0.5,\"c\":1.5}]}\n:::\n";
        let out = p.push(raw.as_bytes());
        assert_eq!(out.artifacts.len(), 1);
        assert_eq!(out.artifacts[0]["type"], "ohlc");
        assert_eq!(out.artifacts[0]["bars"][0]["t"], "2026-08-03");
        let vt = String::from_utf8_lossy(&out.vt);
        assert!(!vt.contains("184.2"));
    }

    #[test]
    fn validate_rejects_empty_ohlc() {
        let err = validate(&json!({"type":"ohlc","bars":[]})).unwrap_err();
        assert!(err.contains("00000008"), "{err}");
    }

    #[test]
    fn bus_dedupes_id() {
        let bus = ArtifactBus::default();
        let mut a = ohlc();
        a["id"] = json!("same");
        bus.push(a.clone()).unwrap();
        bus.push(a).unwrap();
        let (gen, items) = bus.since(0);
        assert_eq!(gen, 1);
        assert_eq!(items.len(), 1);
        let g2 = bus.clear();
        assert!(g2 > gen);
        let (_, empty) = bus.since(0);
        assert!(empty.is_empty());
    }

    fn b64_encode(bytes: &[u8]) -> String {
        const T: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        let mut out = String::new();
        let mut i = 0;
        while i < bytes.len() {
            let b0 = bytes[i];
            let b1 = if i + 1 < bytes.len() { bytes[i + 1] } else { 0 };
            let b2 = if i + 2 < bytes.len() { bytes[i + 2] } else { 0 };
            out.push(T[(b0 >> 2) as usize] as char);
            out.push(T[(((b0 & 3) << 4) | (b1 >> 4)) as usize] as char);
            if i + 1 < bytes.len() {
                out.push(T[(((b1 & 15) << 2) | (b2 >> 6)) as usize] as char);
            } else {
                out.push('=');
            }
            if i + 2 < bytes.len() {
                out.push(T[(b2 & 63) as usize] as char);
            } else {
                out.push('=');
            }
            i += 3;
        }
        out
    }
}
