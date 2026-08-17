//! Locate the oss-grok-build harness and write a session GROK_HOME
//! that aims inference at this process's Engine/Complete façade.

use std::path::PathBuf;

pub fn grok_bin() -> Result<PathBuf, String> {
    if let Ok(p) = std::env::var("GAIUS_GROK_BIN") {
        let pb = PathBuf::from(p);
        if pb.is_file() {
            return Ok(pb);
        }
        return Err(format!(
            "GAIUS_GROK_BIN is not a file: {}\n  Guru: #UI.00000001.NOGROK",
            pb.display()
        ));
    }
    if let Ok(p) = which("grok") {
        return Ok(p);
    }
    let pager = repo_root().join("external/oss-grok-build/target/release/xai-grok-pager");
    if pager.is_file() {
        return Ok(pager);
    }
    Err(
        "grok harness not found (PATH `grok` or external/oss-grok-build release).\n\
         Guru: #UI.00000001.NOGROK\n\
         Try: export GAIUS_GROK_BIN=$(command -v grok)"
            .into(),
    )
}

pub fn repo_root() -> PathBuf {
    if let Ok(p) = std::env::var("DEVENV_ROOT") {
        return PathBuf::from(p);
    }
    let here = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    here.join("../../../..")
        .canonicalize()
        .unwrap_or(here.join("../../../.."))
}

pub fn write_session_home(session_id: &str, listen_host: &str) -> Result<PathBuf, String> {
    let home = repo_root()
        .join("build/dev/.gaius-ui-grok")
        .join(session_id);
    std::fs::create_dir_all(&home).map_err(|e| e.to_string())?;
    let base = format!("http://{listen_host}/v1");
    let repo = repo_root();
    let workspace = write_session_workspace(session_id)?;
    let mcp_py = mcp_python(&repo)?;
    let toml = format!(
        r#"
[models]
default = "gaius-thinking"
max_retries = 2

[agent]
system_prompt_label = "Qwen3.8-27B on Gaius Engine"

[model.gaius-thinking]
model = "thinking"
base_url = "{base}"
name = "Gaius thinking (Engine/Complete)"
api_key = "gaius"
api_backend = "chat_completions"
context_window = 262144
max_completion_tokens = 8192
max_retries = 2
system_prompt_label = "Qwen3.8-27B on Gaius Engine"

[ui]
default_selected_permission = "always_allow_all_sessions"
screen_mode = "fullscreen"

[features]
telemetry = false
remote_fetch = false

[marketplace]
official_marketplace_auto_installed = false
default_skills_installs_purged = true

[mcp_servers.gaius]
command = "{mcp_py}"
args = ["-m", "gaius.mcp_server"]
env = {{ PYTHONDONTWRITEBYTECODE = "1", PYTHONUNBUFFERED = "1" }}
enabled = true
startup_timeout_sec = 45

[mcp_servers.cybersec]
enabled = false
"#,
        base = base,
        mcp_py = mcp_py.display(),
    );
    std::fs::write(home.join("config.toml"), toml).map_err(|e| e.to_string())?;
    std::fs::write(
        home.join("pager.toml"),
        "[terminal]\nalt_screen = \"always\"\n",
    )
    .map_err(|e| e.to_string())?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    // Trust the session workspace only — never the Gaius checkout.
    let trust = format!(
        "[folders.{ws:?}]\ntrusted = true\ndecided_at = {now}\n",
        ws = workspace.display(),
    );
    std::fs::write(home.join("trusted_folders.toml"), trust).map_err(|e| e.to_string())?;
    Ok(home)
}

/// Per-session working tree. Not the Gaius checkout. Host stand-in for
/// the in-browser OPFS a grok-wasm module will own.
pub fn write_session_workspace(session_id: &str) -> Result<PathBuf, String> {
    let ws = repo_root()
        .join("build/dev/.gaius-ui-ws")
        .join(session_id);
    std::fs::create_dir_all(&ws).map_err(|e| e.to_string())?;
    let readme = ws.join("README.md");
    if !readme.is_file() {
        std::fs::write(
            &readme,
            "# Gaius web session workspace\n\n\
             This directory is the harness working tree for one browser \
             session. It is not the Gaius checkout.\n\n\
             Sitrep is not here. Use `/sitrep` or MCP `gaius__theta_sitrep` \
             (horizon: day|week|quarter|open). Knowledge of Gaius lives on \
             the engine.\n",
        )
        .map_err(|e| e.to_string())?;
    }
    seed_gaius_commands(&ws)?;
    if !ws.join(".git").exists() {
        let st = std::process::Command::new("git")
            .args(["init", "--quiet"])
            .current_dir(&ws)
            .status()
            .map_err(|e| format!("git init workspace: {e}"))?;
        if !st.success() {
            return Err(format!("git init workspace exited {st}"));
        }
    }
    Ok(ws)
}

fn seed_gaius_commands(ws: &PathBuf) -> Result<(), String> {
    let cmd_dir = ws.join(".grok/commands");
    std::fs::create_dir_all(&cmd_dir).map_err(|e| e.to_string())?;
    for cmd in crate::gaius_slash::GAIUS_SLASH {
        std::fs::write(
            cmd_dir.join(format!("{}.md", cmd.name)),
            crate::gaius_slash::command_markdown(cmd),
        )
        .map_err(|e| e.to_string())?;
    }
    std::fs::write(ws.join("AGENTS.md"), crate::gaius_slash::agents_md())
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Linux `--sandbox workspace` re-execs via `bwrap`. Missing binary is
/// fail-fast: grok will not start with the deny list unenforced.
pub fn bwrap_bin() -> Result<PathBuf, String> {
    if let Ok(p) = std::env::var("GAIUS_BWRAP") {
        let pb = PathBuf::from(p);
        if pb.is_file() {
            return Ok(pb);
        }
        return Err(format!(
            "GAIUS_BWRAP is not a file: {}\n  Guru: #UI.00000002.NOBWRAP",
            pb.display()
        ));
    }
    if let Ok(p) = which("bwrap") {
        return Ok(p);
    }
    let profile = repo_root().join(".devenv/profile/bin/bwrap");
    if profile.is_file() {
        return Ok(profile);
    }
    Err(
        "bubblewrap (bwrap) not found — grok --sandbox workspace cannot enforce its deny list.\n\
         Guru: #UI.00000002.NOBWRAP\n\
         Try: re-enter the devenv shell (devenv.nix packages.bubblewrap)\n\
         Or:  apt install -y bubblewrap"
            .into(),
    )
}

fn mcp_python(repo: &PathBuf) -> Result<PathBuf, String> {
    let venv = repo.join(".devenv/state/venv/bin/python");
    if venv.is_file() {
        return Ok(venv);
    }
    Err(format!(
        "Gaius MCP python missing: {}\n  Guru: #UI.00000003.NOMCPPY\n  Try: uv sync (devenv venv)",
        venv.display()
    ))
}

fn which(name: &str) -> Result<PathBuf, ()> {
    let paths = std::env::var_os("PATH").ok_or(())?;
    for dir in std::env::split_paths(&paths) {
        let cand = dir.join(name);
        if cand.is_file() {
            return Ok(cand);
        }
    }
    Err(())
}

pub fn listen_loopback(bind: &str) -> String {
    // Grok runs on the host and must reach this process. 0.0.0.0 is not a dest.
    if let Some(port) = bind.rsplit(':').next() {
        format!("127.0.0.1:{port}")
    } else {
        "127.0.0.1:9890".into()
    }
}
