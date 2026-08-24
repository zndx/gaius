//! Gaius slash commands for the Grok `/` autocomplete menu.
//!
//! Grok discovers user-invocable commands from `<cwd>/.grok/commands/*.md`.
//! Each file is a skill: the stem is `/name`. Bodies must call Gaius MCP
//! (`gaius__…`); they must not invent engine state in the session workspace.

pub struct SlashCmd {
    pub name: &'static str,
    pub hint: &'static str,
    pub description: &'static str,
    pub mcp: &'static str,
    pub extra: &'static str,
}

/// CLI/TUI-shaped surface that has a real MCP tool. Not the full 180-tool
/// MCP dump — that would drown the `/` menu.
pub const GAIUS_SLASH: &[SlashCmd] = &[
    SlashCmd {
        name: "agenda",
        hint: "cards|create|list",
        description: "Agenda: executive letters, shared lists, catch-ups with a colleague.",
        mcp: "gaius__agenda_list",
        extra: "Call gaius__agenda_list or gaius__agenda_create. intent=brief (letter/memo, natural-register prose) | reminder (shared suggestions, list) | session (catch-up; discussion headlines in the description; needs starts). Do not invent filings or write engine state into this workspace.",
    },
    SlashCmd {
        name: "sitrep",
        hint: "day|week|quarter|open",
        description: "Gaius situational report. Use for sitrep, morning briefing, or /sitrep.",
        mcp: "gaius__theta_sitrep",
        extra: "Pass horizon (default day). Summarize ascii_format. Do not read this workspace for sitrep.",
    },
    SlashCmd {
        name: "thoughts",
        hint: "[n]",
        description: "Active Gaius cognition thoughts. Use for /thoughts or what are you thinking.",
        mcp: "gaius__get_recent_thoughts",
        extra: "Call gaius__get_recent_thoughts. If the user passed a number after /thoughts, set limit to that number (default 10). Only call gaius__trigger_cognition if they ask to think / run a cycle.",
    },
    SlashCmd {
        name: "research",
        hint: "<topic>",
        description: "Deep research a topic via the engine. Use for /research <topic>.",
        mcp: "gaius__research_topic",
        extra: "Call gaius__research_topic only for open web/KB synthesis. Not for FMP fundamentals (employees, filings, quotes). Those are gaius__fmp_search / gaius__fmp_employees / gaius__fmp_news / gaius__ask_present.",
    },
    SlashCmd {
        name: "search",
        hint: "<query>",
        description: "Search the Gaius knowledge base. Use for /search.",
        mcp: "gaius__search_kb",
        extra: "Call gaius__search_kb. For vector search use gaius__semantic_search.",
    },
    SlashCmd {
        name: "health",
        hint: "[status|check]",
        description: "Health observer status and checks. Use for /health.",
        mcp: "gaius__health_observer_status",
        extra: "status → gaius__health_observer_status. check → gaius__health_observer_check. `/health fix` is CLI/TUI only (uv run gaius-cli --cmd \"/health fix <svc>\"); MCP has no fix tool.",
    },
    SlashCmd {
        name: "gpu",
        hint: "[status|health]",
        description: "GPU orchestrator and endpoint status. Use for /gpu.",
        mcp: "gaius__orchestrator_status",
        extra: "Call gaius__orchestrator_status. For sensors, gaius__gpu_health.",
    },
    SlashCmd {
        name: "objectives",
        hint: "",
        description: "Tracked verification objectives. Use for /objectives.",
        mcp: "gaius__list_objectives",
        extra: "Call gaius__list_objectives and summarize.",
    },
    SlashCmd {
        name: "consolidate",
        hint: "[slice] [--max N]",
        description: "Theta consolidation cycle. Use for /consolidate.",
        mcp: "gaius__theta_consolidate",
        extra: "Call gaius__theta_consolidate. stats → gaius__theta_consolidation_stats.",
    },
    SlashCmd {
        name: "evolve",
        hint: "[status]",
        description: "Evolution daemon status. Use for /evolve.",
        mcp: "gaius__evolution_status",
        extra: "Call gaius__evolution_status. Do not trigger evolution unless the user asks.",
    },
    SlashCmd {
        name: "prospects",
        hint: "[status]",
        description: "Prospects product status. Use for /prospects.",
        mcp: "gaius__prospects_status",
        extra: "Call gaius__prospects_status.",
    },
    SlashCmd {
        name: "swarm",
        hint: "<domain>",
        description: "Run a swarm analysis via the engine. Use for /swarm.",
        mcp: "gaius__run_swarm",
        extra: "Call gaius__run_swarm with the user's domain/context.",
    },
    SlashCmd {
        name: "ask",
        hint: "<question>",
        description: "Ask the thinking capability. Use for /ask.",
        mcp: "gaius__ask_reasoning",
        extra: "Call gaius__ask_reasoning with the user's question. This is Engine/Complete, not workspace files.",
    },
    SlashCmd {
        name: "news",
        hint: "[stock|general]",
        description: "Latest FMP headlines. Use when headlines would inform the answer.",
        mcp: "gaius__fmp_news",
        extra: "kind=stock or general. optional symbol if the user already named a ticker. Do not invent symbols.",
    },
    SlashCmd {
        name: "employees",
        hint: "<symbol>",
        description: "FMP historical employee counts by SEC period.",
        mcp: "gaius__fmp_employees",
        extra: "symbol from fmp_search or the user. Do not invent a ticker.",
    },
    SlashCmd {
        name: "ticker",
        hint: "<company>",
        description: "FMP name to ticker search. You choose among listings.",
        mcp: "gaius__fmp_search",
        extra: "query is the company or fragment from the user. You pick among results. Do not invent a ticker.",
    },
    SlashCmd {
        name: "chart",
        hint: "<symbol>",
        description: "OHLC chart in the Ask panel. Use for /chart <ticker>.",
        mcp: "gaius__ask_present",
        extra: "Call gaius__ask_present exactly once. symbol is the ticker from the user message after /chart or $. Never substitute a ticker that is not in the user message. Do not invent bars. Do not wrap it in use_tool. If posted=true, stop: the chart is in Ask. Do not call the tool again. Do not print the fence.",
    },
    SlashCmd {
        name: "kb",
        hint: "[list|read <path>|search <q>]",
        description: "Knowledge-base operations. Use for /kb.",
        mcp: "gaius__list_kb",
        extra: "list → gaius__list_kb. read → gaius__read_kb. search → gaius__search_kb. Paths are engine KB paths, not this workspace.",
    },
    SlashCmd {
        name: "explain",
        hint: "[pos]",
        description: "Explain a board position. Use for /explain.",
        mcp: "gaius__explain_grid_position",
        extra: "Call gaius__explain_grid_position.",
    },
    SlashCmd {
        name: "metabase",
        hint: "[status|dashboards]",
        description: "Metabase federation status. Use for /metabase.",
        mcp: "gaius__metabase_status",
        extra: "Call gaius__metabase_status. dashboards → gaius__metabase_list_dashboards.",
    },
];

pub fn command_markdown(cmd: &SlashCmd) -> String {
    format!(
        "---\n\
         name: {name}\n\
         description: {desc}\n\
         argument-hint: {hint}\n\
         user-invocable: true\n\
         ---\n\n\
         # /{name}\n\n\
         Call the Gaius MCP tool `{mcp}`.\n\
         {extra}\n\
         Do not invent engine state or write it into this workspace.\n",
        name = cmd.name,
        desc = cmd.description,
        hint = cmd.hint,
        mcp = cmd.mcp,
        extra = cmd.extra,
    )
}

/// Compact option space for thinking Complete. Not the full slash catalog.
/// Schema only — no example tickers. Qwen chooses FMP; we do not detect names.
pub fn thinking_capability_card() -> String {
    String::from(
        "You are Qwen3.8-27B on Gaius Engine/Complete. Terminal prose is high-priority.\n\
         FMP is at hand. You search and pick listings. Do not invent OHLC bars or employee counts.\n\
         A candlestick in Ask is a normal follow-up when headlines or a company come up — you decide.\n\
         Emit <tool_call>{\"name\":\"gaius__…\",\"arguments\":{}}</tool_call>\n\
         - gaius__fmp_search: company or fragment → tickers (once; then pick a symbol)\n\
         - gaius__fmp_news: latest headlines; kind=stock|general; optional symbol\n\
         - gaius__fmp_employees: historical employee counts by SEC period; symbol required\n\
         - gaius__ask_present: OHLC in Ask; symbol + optional from_date/to_date\n\
         - gaius__theta_sitrep: situational report; horizon=day|week|quarter|open\n\
         - gaius__orchestrator_status: GPU / thinking health\n\
         - gaius__prospects_status: FMP product / buffer\n\
         - gaius__agenda_list: calendar cards\n\
         - gaius__get_recent_thoughts: cognition thoughts\n\
         Do not call gaius__research_topic for fundamentals, employees, quotes, or filings.\n",
    )
}

pub fn agents_md() -> &'static str {
    "# Web session workspace\n\n\
     This is not the Gaius checkout.\n\n\
     Gaius slash commands (`/sitrep`, `/thoughts`, `/research`, `/health`, \
     `/gpu`, …) live in `.grok/commands/` so they appear in Grok's `/` menu. \
     Each one calls a Gaius MCP tool. Knowledge of Gaius lives on the engine.\n\n\
     `/agenda` lists and creates cards via `gaius__agenda_list` / \
     `gaius__agenda_create`. A brief is a letter or memo for an \
     executive (natural-register prose). A list (intent reminder) \
     is shared suggestions between agents and operators. A session \
     is a catch-up with a colleague; discussion headlines go in the \
     calendar description. Sessions need `starts`. That is not Synth's \
     Deluge gesture FSM.\n"
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn catalog_has_sitrep_not_agenda() {
        let names: Vec<&str> = GAIUS_SLASH.iter().map(|c| c.name).collect();
        assert!(names.contains(&"sitrep"));
        assert!(names.contains(&"thoughts"));
        assert!(names.contains(&"gpu"));
        assert!(names.contains(&"agenda"));
        assert!(names.contains(&"chart"));
    }

    #[test]
    fn catalog_has_no_example_tickers() {
        let banned = ["NVDA", "AAPL", "SLB", "SPCX", "MSFT", "TSLA"];
        for cmd in GAIUS_SLASH {
            let blob = format!("{} {} {}", cmd.description, cmd.extra, cmd.hint);
            for t in banned {
                assert!(
                    !blob.contains(t),
                    "/{} skill copy contains example ticker {}",
                    cmd.name,
                    t
                );
            }
        }
        let md = agents_md();
        for t in banned {
            assert!(!md.contains(t), "AGENTS.md contains example ticker {t}");
        }
        let card = thinking_capability_card();
        assert!(card.contains("gaius__ask_present"));
        assert!(card.contains("gaius__fmp_news"));
        assert!(card.contains("gaius__fmp_search"));
        assert!(card.contains("gaius__fmp_employees"));
        assert!(card.contains("Do not call gaius__research_topic"));
        assert!(card.len() < 4000, "capability card too large: {}", card.len());
        for t in banned {
            assert!(!card.contains(t), "capability card contains example ticker {t}");
        }
    }

    #[test]
    fn sitrep_markdown_names_mcp() {
        let sitrep = GAIUS_SLASH.iter().find(|c| c.name == "sitrep").unwrap();
        let md = command_markdown(sitrep);
        assert!(md.contains("gaius__theta_sitrep"));
        assert!(md.contains("user-invocable: true"));
        assert!(md.contains("argument-hint: day|week|quarter|open"));
    }
}