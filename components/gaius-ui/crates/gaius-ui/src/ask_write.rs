//! Ask write path: small model hands off, thinking fills a constrained
//! Agenda create/update, façade executes Engine AgendaCreate.

use serde_json::{json, Value};

use crate::gaius::Gaius;

pub const GURU_NOWRITE: &str = "\
Thinking did not emit an Agenda write.\n\
  Guru: #AG.00000008.NOWRITE\n\
  Emit :::gaius-artifact {type:agenda, action:create, …} or use Agenda +.";

pub const HANDOFF_ADDENDUM: &str = "\
The user wants to create or change an Agenda item.\n\
Do not invent times. Do not write the card yourself.\n\
Reply with ONLY this fence (no essay):\n\
:::gaius-handoff\n\
{\"to\":\"thinking\",\"task\":\"agenda.write\",\"reason\":\"calendar write\"}\n\
:::";

pub const TOOL_LOOP_ADDENDUM: &str = "\
You are in a tool loop. To use a Gaius MCP tool, emit exactly:\n\
<tool_call>\n\
{\"name\":\"gaius__ask_present\",\"arguments\":{\"symbol\":\"TICKER\",\"kind\":\"ohlc\"}}\n\
</tool_call>\n\
Replace TICKER with the symbol from the user message. Call the tool.\n\
Rich Ask surfaces: kind=ohlc (symbol), kind=table (rows JSON array of objects), \
kind=links (rows JSON [{href,title}]), kind=markdown (body).\n\
After a tool result, write a short user-visible answer.";

pub const CHART_HINT: &str = "\
For a stock candlestick, emit :::gaius-artifact {\"type\":\"ohlc\",\"symbol\":\"TICKER\"} \
or call gaius__ask_present. Do not invent OHLC bars.";

pub const CHART_ADDENDUM: &str = "\
The user wants a stock candlestick (OHLC) in the Ask panel.\n\
Do not invent bars. Do not draw ASCII candles.\n\
Emit exactly one fence (symbol only):\n\
:::gaius-artifact\n\
{\"type\":\"ohlc\",\"symbol\":\"TICKER\"}\n\
:::\n\
Replace TICKER with the symbol from the user message. Never use a ticker that is not in that message. Optional from/to as from_date/to_date (YYYY-MM-DD).";

pub const WRITE_ADDENDUM: &str = "\
You are filling one Agenda write. Clock is the browser timezone (not the server).\n\
Copy Clock tokens or Clock ISO verbatim. tomorrow morning = Clock.tomorrow_morning\n\
(or the token tomorrow_morning). Session default is 30 minutes.\n\
Do not emit 09:00Z unless Clock.timezone is UTC.\n\
kind = note|list|event. A timed slot is kind=event.\n\
intent = brief|reminder|session. Working through a topic WITH the agents is session\n\
(requires starts). session defaults with=agents.\n\
Emit exactly one fence and a one-line confirmation. No calendar fiction, no <think> dump.\n\
:::gaius-artifact\n\
{\"type\":\"agenda\",\"action\":\"create\",\"kind\":\"event\",\"intent\":\"session\",\"title\":\"…\",\
\"starts\":\"tomorrow_morning\",\"ends\":\"tomorrow_morning_end\",\"with\":\"agents\",\"body\":\"…\",\"tags\":[]}\n\
:::";

pub fn is_small_ask(cap: &str) -> bool {
    matches!(cap, "interpretable" | "interpretable-b" | "ask-sae" | "ask")
}

pub fn looks_like_chart(prompt: &str) -> bool {
    let q = user_intent_text(prompt);
    let t = q.to_ascii_lowercase();
    // Bare "chart" matches YK/queue prose. "stock chart" is user intent.
    if t.contains("/chart")
        || t.contains("candlestick")
        || t.contains("ohlc")
        || t.contains("shart")
        || t.contains("stock chart")
        || t.contains("price chart")
        || t.contains("performance chart")
        || t.contains("chart for")
    {
        return true;
    }
    ticker_in(q).is_some()
        && (t.contains("stock")
            || t.contains("price")
            || t.contains("quote")
            || t.contains("candle")
            || t.contains("performance")
            || q.contains('$'))
}

/// Grok wraps the turn in user_info / user_query. Chart intent lives there.
pub fn user_intent_text(prompt: &str) -> &str {
    if let Some(start) = prompt.find("<user_query>") {
        let rest = &prompt[start + "<user_query>".len()..];
        if let Some(end) = rest.find("</user_query>") {
            let inner = rest[..end].trim();
            if !inner.is_empty() {
                return inner;
            }
        }
    }
    if let Some(idx) = prompt.rfind("User: ") {
        let chunk = prompt[idx + 6..].trim();
        if chunk.len() < 400 {
            return chunk;
        }
        for line in chunk.lines().map(str::trim).rev() {
            if line.is_empty() || line.starts_with('<') {
                continue;
            }
            if (8..400).contains(&line.len()) {
                return line;
            }
        }
    }
    prompt
}

/// Ticker or company name to send to AskPresent (engine resolves names).
pub fn chart_symbol_query(prompt: &str) -> Option<String> {
    let q = user_intent_text(prompt);
    if q.contains("/chart") || q.contains('$') {
        if let Some(t) = ticker_in(q) {
            return Some(t);
        }
    }
    let lower = q.to_ascii_lowercase();
    for sep in [" for ", " of "] {
        if let Some(i) = lower.rfind(sep) {
            let rest = q[i + sep.len()..].trim();
            let name: String = rest
                .chars()
                .take_while(|c| c.is_alphanumeric() || *c == ' ' || *c == '.')
                .collect();
            let name = name.trim().trim_end_matches('.');
            if name.len() >= 2 && !is_infra_ticker(name) {
                return Some(name.to_string());
            }
        }
    }
    ticker_in(q)
}

pub fn is_infra_ticker(symbol: &str) -> bool {
    TICKER_SKIP_GREEDY.contains(&symbol.trim().to_ascii_uppercase().as_str())
}

const TICKER_SKIP: &[&str] = &[
    "OHLC", "CHART", "STOCK", "CANDLE", "PRICE", "QUOTE", "SHOW", "THE",
    "FOR", "AND", "ASK", "LAST", "DAYS", "WEEK", "PLEASE",
];

/// Only skipped on the greedy whole-prompt scan. `/chart ROOT` and `$ROOT` still work.
const TICKER_SKIP_GREEDY: &[&str] = &[
    "ROOT", "HTML", "HTTP", "JSON", "GPU", "GPUS", "CLI", "TUI", "UTC",
    "ISO", "SQL", "API", "MCP", "SAE", "CLT", "SKOS", "YK", "GAIUS",
    "QUEUE", "PAGE", "FOCUS", "CLOCK", "BOARD", "GRID",
];

pub fn ticker_in(prompt: &str) -> Option<String> {
    if let Some(rest) = prompt.split_once("/chart").map(|(_, r)| r) {
        if let Some(t) = token_ticker(rest, false) {
            return Some(t);
        }
    }
    if let Some(pos) = prompt.find('$') {
        if let Some(t) = token_ticker(&prompt[pos + 1..], false) {
            return Some(t);
        }
    }
    token_ticker(prompt, true)
}

fn token_ticker(s: &str, greedy: bool) -> Option<String> {
    for tok in s.split(|c: char| !c.is_ascii_alphanumeric()) {
        let t = tok.trim();
        if !(2..=5).contains(&t.len()) || !t.chars().all(|c| c.is_ascii_alphabetic()) {
            continue;
        }
        let up = t.to_ascii_uppercase();
        if TICKER_SKIP.contains(&up.as_str()) {
            continue;
        }
        if greedy && TICKER_SKIP_GREEDY.contains(&up.as_str()) {
            continue;
        }
        return Some(up);
    }
    None
}

pub fn looks_like_agenda_write(prompt: &str) -> bool {
    let t = prompt.to_ascii_lowercase();
    let verbs = [
        "create",
        "schedule",
        "book",
        "add ",
        "put ",
        "update",
        "move ",
        "reschedule",
        "rename",
        "make an",
        "make a ",
    ];
    let nouns = [
        "event",
        "session",
        "reminder",
        "agenda",
        "meeting",
        "calendar",
        "brief",
    ];
    verbs.iter().any(|v| t.contains(v)) && nouns.iter().any(|n| t.contains(n))
}

fn fence_body<'a>(text: &'a str, open: &str) -> Option<&'a str> {
    let start = text.find(open)?;
    let after = text.get(start + open.len()..)?;
    let end = after.find(":::")?;
    Some(after[..end].trim())
}

pub fn parse_handoff(text: &str) -> Option<Value> {
    let raw = fence_body(text, ":::gaius-handoff")?;
    let v: Value = serde_json::from_str(raw).ok()?;
    let to = v.get("to").and_then(|x| x.as_str()).unwrap_or("");
    if to == "thinking" || v.get("task").and_then(|x| x.as_str()) == Some("agenda.write") {
        Some(v)
    } else {
        None
    }
}

fn spec_from_value(v: Value) -> Option<Value> {
    let typ = v
        .get("type")
        .or_else(|| v.get("kind"))
        .and_then(|x| x.as_str())
        .unwrap_or("");
    let action = v.get("action").and_then(|x| x.as_str()).unwrap_or("create");
    if typ == "ohlc" {
        return None;
    }
    if typ == "agenda" || action == "create" || action == "update" {
        if v.get("title").and_then(|x| x.as_str()).unwrap_or("").trim().is_empty()
            && action != "update"
        {
            return None;
        }
        let mut out = v;
        if out.get("type").is_none() {
            out["type"] = json!("agenda");
        }
        if out.get("action").is_none() {
            out["action"] = json!("create");
        }
        return Some(out);
    }
    None
}

pub fn parse_ohlc_spec(text: &str, calls: &[(String, Value)], prompt: &str) -> Option<Value> {
    if let Some(raw) = fence_body(text, ":::gaius-artifact") {
        if let Ok(v) = serde_json::from_str::<Value>(raw) {
            let typ = v
                .get("type")
                .or_else(|| v.get("kind"))
                .and_then(|x| x.as_str())
                .unwrap_or("");
            if typ == "ohlc" {
                let sym = v
                    .get("symbol")
                    .and_then(|s| s.as_str())
                    .unwrap_or("")
                    .trim();
                if is_infra_ticker(sym)
                    && !prompt.contains("/chart")
                    && !prompt.contains('$')
                {
                    return None;
                }
                if sym.is_empty()
                    && v.get("bars").and_then(|b| b.as_array()).map(|a| !a.is_empty())
                        != Some(true)
                {
                    // fall through to ticker
                } else {
                    return Some(v);
                }
            }
        }
    }
    for (name, args) in calls {
        if name == "gaius__ask_present" || name == "ask_present" {
            let mut out = args.clone();
            out["type"] = json!("ohlc");
            if out.get("symbol").and_then(|s| s.as_str()).unwrap_or("").trim().is_empty() {
                if let Some(t) = ticker_in(prompt) {
                    out["symbol"] = json!(t);
                }
            }
            if out.get("symbol").and_then(|s| s.as_str()).unwrap_or("").trim().is_empty() {
                continue;
            }
            return Some(out);
        }
    }
    let intent = user_intent_text(prompt);
    if looks_like_chart(intent) || looks_like_chart(prompt) {
        if let Some(t) = chart_symbol_query(prompt) {
            if is_infra_ticker(&t) && !intent.contains("/chart") && !intent.contains('$') {
                return None;
            }
            let mut out = json!({"type": "ohlc", "symbol": t});
            if let Some((from, to)) = window_from_prompt(intent) {
                out["from_date"] = json!(from);
                out["to_date"] = json!(to);
            }
            return Some(out);
        }
    }
    None
}

fn window_from_prompt(prompt: &str) -> Option<(String, String)> {
    let t = prompt.to_ascii_lowercase();
    let days = if t.contains("30 day") || t.contains("30-day") || t.contains("last month") {
        30u64
    } else if t.contains("90 day") || t.contains("90-day") {
        90
    } else if t.contains("7 day") || t.contains("7-day") || t.contains("last week") {
        7
    } else {
        return None;
    };
    Some((days_ago_iso(days), days_ago_iso(0)))
}

fn days_ago_iso(days: u64) -> String {
    days_ago_ymd(days)
}

pub fn days_ago_ymd(days: u64) -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs().saturating_sub(days * 86400))
        .unwrap_or(0);
    unix_ymd(secs)
}

pub fn unix_ymd(secs: u64) -> String {
    let z = (secs / 86400) as i64 + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{y:04}-{m:02}-{d:02}")
}

pub fn parse_agenda_spec(text: &str, calls: &[(String, Value)]) -> Option<Value> {
    if let Some(raw) = fence_body(text, ":::gaius-artifact") {
        if let Ok(v) = serde_json::from_str::<Value>(raw) {
            if let Some(spec) = spec_from_value(v) {
                return Some(spec);
            }
        }
    }
    if let Some(start) = text.find('{') {
        if let Some(end) = text.rfind('}') {
            if end > start {
                if let Ok(v) = serde_json::from_str::<Value>(&text[start..=end]) {
                    if let Some(spec) = spec_from_value(v) {
                        return Some(spec);
                    }
                }
            }
        }
    }
    for (name, arguments) in calls {
        if matches!(
            name.as_str(),
            "gaius__agenda_create" | "agenda_create" | "gaius_agenda_create"
        ) {
            let mut args = arguments.clone();
            args["action"] = json!("create");
            args["type"] = json!("agenda");
            if let Some(spec) = spec_from_value(args) {
                return Some(spec);
            }
        }
        if matches!(
            name.as_str(),
            "gaius__agenda_update" | "agenda_update" | "gaius_agenda_update"
        ) {
            let mut args = arguments.clone();
            args["action"] = json!("update");
            args["type"] = json!("agenda");
            return Some(args);
        }
    }
    None
}

fn tags_of(spec: &Value) -> Vec<String> {
    match spec.get("tags") {
        Some(Value::Array(a)) => a
            .iter()
            .filter_map(|v| v.as_str().map(|s| s.trim().to_string()))
            .filter(|s| !s.is_empty())
            .collect(),
        Some(Value::String(s)) => s
            .split(',')
            .map(|t| t.trim().to_string())
            .filter(|t| !t.is_empty())
            .collect(),
        _ => vec![],
    }
}

fn s(spec: &Value, key: &str) -> String {
    spec.get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_string()
}

pub fn clock_is_utc(clock: &Value) -> bool {
    let tz = clock
        .get("timezone")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    tz.is_empty()
        || tz.eq_ignore_ascii_case("utc")
        || tz.eq_ignore_ascii_case("etc/utc")
        || tz.eq_ignore_ascii_case("zulu")
}

pub fn resolve_when(raw: &str, clock: &Value) -> String {
    let t = raw.trim();
    if t.is_empty() {
        return String::new();
    }
    if let Some(v) = clock.get(t).and_then(|x| x.as_str()) {
        if !v.is_empty() {
            return v.to_string();
        }
    }
    t.to_string()
}

fn utc_nine_on_day(iso: &str, day: &str) -> bool {
    if day.is_empty() || !iso.starts_with(day) || !iso.contains("T09:00") {
        return false;
    }
    iso.contains('Z') || iso.contains("+00:00")
}

/// Resolve Clock tokens and replace invented 09:00Z mornings when the
/// browser is not UTC (MDT 09:00 is 15:00Z, not 09:00Z).
pub fn coerce_to_clock(starts: &str, ends: &str, clock: &Value) -> (String, String) {
    let mut starts = resolve_when(starts, clock);
    let mut ends = resolve_when(ends, clock);
    if clock_is_utc(clock) {
        return (starts, ends);
    }
    let pairs = [
        (
            "tomorrow",
            "tomorrow_morning",
            "tomorrow_morning_end",
        ),
        ("today", "today_morning", "today_morning_end"),
    ];
    for (day_key, start_key, end_key) in pairs {
        let day = clock.get(day_key).and_then(|v| v.as_str()).unwrap_or("");
        let morning = clock.get(start_key).and_then(|v| v.as_str()).unwrap_or("");
        let morning_end = clock.get(end_key).and_then(|v| v.as_str()).unwrap_or("");
        if day.is_empty() || morning.is_empty() {
            continue;
        }
        if utc_nine_on_day(&starts, day) {
            starts = morning.to_string();
            if ends.is_empty() || utc_nine_on_day(&ends, day) || ends.contains("T09:30")
            {
                if !morning_end.is_empty() {
                    ends = morning_end.to_string();
                }
            }
        }
    }
    (starts, ends)
}

pub async fn apply_agenda_spec(spec: &Value, clock: Option<&Value>) -> Result<Value, String> {
    let action = s(spec, "action");
    let g = Gaius::from_env();
    match action.as_str() {
        "update" => {
            let path = s(spec, "path");
            if path.is_empty() {
                return Err(
                    "Agenda update needs path.\n  Guru: #AG.00000003.BADPATH".into(),
                );
            }
            let (starts, ends) = match clock {
                Some(c) => coerce_to_clock(&s(spec, "starts"), &s(spec, "ends"), c),
                None => (s(spec, "starts"), s(spec, "ends")),
            };
            g.agenda_update(
                path,
                s(spec, "title"),
                s(spec, "body"),
                starts,
                ends,
                tags_of(spec),
                spec.get("pin").and_then(|v| v.as_bool()),
                None,
            )
            .await
            .map_err(|e| e.to_string())
        }
        _ => {
            let title = s(spec, "title");
            if title.is_empty() {
                return Err(GURU_NOWRITE.into());
            }
            let kind = {
                let k = s(spec, "kind");
                if k.is_empty() || k == "agenda" {
                    "event".into()
                } else {
                    k
                }
            };
            let with = {
                let w = s(spec, "with");
                if w.is_empty() {
                    s(spec, "with_whom")
                } else {
                    w
                }
            };
            let (starts, ends) = match clock {
                Some(c) => coerce_to_clock(&s(spec, "starts"), &s(spec, "ends"), c),
                None => (s(spec, "starts"), s(spec, "ends")),
            };
            let tz = {
                let t = s(spec, "timezone");
                if !t.is_empty() {
                    t
                } else {
                    clock
                        .and_then(|c| c.get("timezone").and_then(|v| v.as_str()))
                        .unwrap_or("")
                        .to_string()
                }
            };
            g.agenda_create(
                kind,
                title,
                s(spec, "body"),
                starts,
                ends,
                tags_of(spec),
                spec.get("pin").and_then(|v| v.as_bool()).unwrap_or(false),
                s(spec, "intent"),
                with,
                tz,
            )
            .await
            .map_err(|e| e.to_string())
        }
    }
}

pub fn confirm_markdown(created: &Value) -> String {
    let item = created.get("item").unwrap_or(created);
    let title = item.get("title").and_then(|v| v.as_str()).unwrap_or("item");
    let intent = item.get("intent").and_then(|v| v.as_str()).unwrap_or("");
    let starts = item.get("starts").and_then(|v| v.as_str()).unwrap_or("");
    let ends = item.get("ends").and_then(|v| v.as_str()).unwrap_or("");
    let with = item.get("with").and_then(|v| v.as_str()).unwrap_or("");
    let path = item.get("path").and_then(|v| v.as_str()).unwrap_or("");
    let when = if starts.is_empty() {
        String::new()
    } else if ends.is_empty() {
        starts.to_string()
    } else {
        format!("{starts} – {ends}")
    };
    format!(
        "Booked **{title}**\n\n- intent: {intent}\n- when: {when}\n- with: {with}\n- path: `{path}`\n"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn write_detector_hits_create_event() {
        assert!(looks_like_agenda_write(
            "Can you create an event for tomorrow morning titled: Review Prospects"
        ));
        assert!(!looks_like_agenda_write("what is on today's agenda?"));
    }

    #[test]
    fn handoff_fence_parses() {
        let raw = ":::gaius-handoff\n{\"to\":\"thinking\",\"task\":\"agenda.write\",\"reason\":\"create\"}\n:::";
        let v = parse_handoff(raw).expect("handoff");
        assert_eq!(v["to"], "thinking");
    }

    #[test]
    fn artifact_fence_parses() {
        let raw = r#"ok
:::gaius-artifact
{"type":"agenda","action":"create","kind":"event","intent":"session","title":"Review Prospects","starts":"2026-08-17T13:00:00Z"}
:::
"#;
        let spec = parse_agenda_spec(raw, &[]).expect("spec");
        assert_eq!(spec["title"], "Review Prospects");
        assert_eq!(spec["intent"], "session");
    }

    #[test]
    fn tool_call_becomes_spec() {
        let calls = vec![(
            "gaius__agenda_create".into(),
            json!({
                "title": "Review Prospects",
                "kind": "event",
                "intent": "session",
                "starts": "2026-08-17T13:00:00Z",
            }),
        )];
        let spec = parse_agenda_spec("", &calls).expect("spec");
        assert_eq!(spec["title"], "Review Prospects");
    }

    #[test]
    fn ohlc_is_not_an_agenda_write() {
        let raw = r#":::gaius-artifact
{"type":"ohlc","title":"SPCX","bars":[{"t":"2026-08-01","o":1,"h":2,"l":0.5,"c":1.5}]}
:::"#;
        assert!(parse_agenda_spec(raw, &[]).is_none());
    }

    #[test]
    fn chart_intent_and_ticker() {
        assert!(looks_like_chart("show NVDA candlestick"));
        assert!(looks_like_chart("/chart AAPL"));
        assert!(looks_like_chart("let's see a 30 day stock chart for Disney"));
        let disney = parse_ohlc_spec("", &[], "let's see a 30 day stock chart for Disney")
            .expect("disney");
        assert_eq!(disney["symbol"], "Disney");
        assert!(disney.get("from_date").is_some());
        let wrapped = "User: <user_info> OS Version: linux\n<user_query>\nlet's see a 30 day stock chart for Disney\n</user_query>";
        assert_eq!(
            user_intent_text(wrapped),
            "let's see a 30 day stock chart for Disney"
        );
        let w = parse_ohlc_spec("", &[], wrapped).expect("wrapped disney");
        assert_eq!(w["symbol"], "Disney");
        assert!(looks_like_chart("Generate a 30 day performance shart for $SLB"));
        let slb = parse_ohlc_spec("", &[], "Generate a 30 day performance shart for $SLB")
            .expect("slb");
        assert_eq!(slb["symbol"], "SLB");
        assert!(slb.get("from_date").is_some());
        let agenda = parse_ohlc_spec(
            "",
            &[],
            "can you create a chart on 30 days of stock performance for $SLB",
        )
        .expect("agenda slb");
        assert_eq!(agenda["symbol"], "SLB");
        assert_eq!(ticker_in("/chart NVDA last 90 days").as_deref(), Some("NVDA"));
        assert_eq!(ticker_in("chart $SPCX").as_deref(), Some("SPCX"));
        assert_eq!(ticker_in("show NVDA candlestick").as_deref(), Some("NVDA"));
        assert!(ticker_in("root.gaius queue chart").is_none());
        assert!(!looks_like_chart("root.gaius queue chart"));
        assert!(is_infra_ticker("ROOT"));
        assert!(parse_ohlc_spec("", &[], "root.gaius queue chart").is_none());
        assert!(
            parse_ohlc_spec(
                r#":::gaius-artifact
{"type":"ohlc","symbol":"ROOT"}
:::"#,
                &[],
                "looking at root.internal.inference.extract",
            )
            .is_none()
        );
        assert_eq!(ticker_in("/chart ROOT").as_deref(), Some("ROOT"));
        assert_eq!(ticker_in("$ROOT").as_deref(), Some("ROOT"));
        let spec = parse_ohlc_spec(
            r#":::gaius-artifact
{"type":"ohlc","symbol":"MSFT"}
:::"#,
            &[],
            "chart please",
        )
        .expect("ohlc");
        assert_eq!(spec["symbol"], "MSFT");
        let from_tool = parse_ohlc_spec(
            "",
            &[(
                "gaius__ask_present".into(),
                json!({"symbol": "NVDA", "kind": "ohlc"}),
            )],
            "chart",
        )
        .expect("tool");
        assert_eq!(from_tool["symbol"], "NVDA");
    }

    #[test]
    fn prompt_addenda_have_no_example_tickers() {
        let blob = format!(
            "{TOOL_LOOP_ADDENDUM}\n{CHART_HINT}\n{CHART_ADDENDUM}\n{HANDOFF_ADDENDUM}"
        );
        for t in ["NVDA", "AAPL", "SLB", "SPCX", "MSFT", "TSLA"] {
            assert!(!blob.contains(t), "prompt addendum contains example ticker {t}");
        }
    }

    #[test]
    fn small_caps() {
        assert!(is_small_ask("interpretable"));
        assert!(is_small_ask("ask-sae"));
        assert!(!is_small_ask("thinking"));
    }

    #[test]
    fn clock_tokens_resolve() {
        let clock = json!({
            "timezone": "America/Denver",
            "tomorrow": "2026-08-17",
            "tomorrow_morning": "2026-08-17T15:00:00.000Z",
            "tomorrow_morning_end": "2026-08-17T15:30:00.000Z",
        });
        assert_eq!(
            resolve_when("tomorrow_morning", &clock),
            "2026-08-17T15:00:00.000Z"
        );
        let (st, en) = coerce_to_clock(
            "2026-08-17T09:00:00Z",
            "2026-08-17T09:30:00+00:00",
            &clock,
        );
        assert_eq!(st, "2026-08-17T15:00:00.000Z");
        assert_eq!(en, "2026-08-17T15:30:00.000Z");
    }

    #[test]
    fn utc_clock_keeps_nine() {
        let clock = json!({
            "timezone": "UTC",
            "tomorrow": "2026-08-17",
            "tomorrow_morning": "2026-08-17T09:00:00.000Z",
            "tomorrow_morning_end": "2026-08-17T09:30:00.000Z",
        });
        let (st, _) = coerce_to_clock("2026-08-17T09:00:00Z", "", &clock);
        assert_eq!(st, "2026-08-17T09:00:00Z");
    }

    #[test]
    fn mdt_offset_nine_is_not_utc_nine() {
        let clock = json!({
            "timezone": "America/Denver",
            "tomorrow": "2026-08-17",
            "tomorrow_morning": "2026-08-17T15:00:00.000Z",
        });
        let (st, _) = coerce_to_clock("2026-08-17T09:00:00-06:00", "", &clock);
        assert_eq!(st, "2026-08-17T09:00:00-06:00");
    }
}
