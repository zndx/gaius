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

/// Real directory for PTY GROK_HOME / workspace. Never under `build/dev`
/// (that path is a symlink onto RAID; grok sandbox write-deny refuses it).
pub fn session_state_root() -> Result<PathBuf, String> {
    if let Ok(p) = std::env::var("GAIUS_UI_STATE") {
        let pb = PathBuf::from(p.trim());
        let pb = if pb.is_absolute() {
            pb
        } else {
            repo_root().join(pb)
        };
        return ensure_real_dir(pb);
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    let base = std::env::var("XDG_STATE_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(home).join(".local/state"));
    ensure_real_dir(base.join("gaius-ui"))
}

fn ensure_real_dir(p: PathBuf) -> Result<PathBuf, String> {
    std::fs::create_dir_all(&p).map_err(|e| {
        format!(
            "cannot create gaius-ui state {}: {e}\n  Guru: #UI.00000010.GROKHOME",
            p.display()
        )
    })?;
    let canon = p.canonicalize().map_err(|e| {
        format!(
            "cannot resolve gaius-ui state {}: {e}\n  Guru: #UI.00000010.GROKHOME",
            p.display()
        )
    })?;
    let mut walk = canon.clone();
    loop {
        let meta = std::fs::symlink_metadata(&walk).map_err(|e| e.to_string())?;
        if meta.file_type().is_symlink() {
            return Err(format!(
                "GROK_HOME cannot sit under a symlink ({})\n  Guru: #UI.00000010.GROKHOME\n  Try: export GAIUS_UI_STATE=$HOME/.local/state/gaius-ui",
                walk.display()
            ));
        }
        if !walk.pop() {
            break;
        }
    }
    Ok(canon)
}

pub fn write_session_home(session_id: &str, listen_host: &str) -> Result<PathBuf, String> {
    let home = session_state_root()?.join("grok").join(session_id);
    std::fs::create_dir_all(&home).map_err(|e| e.to_string())?;
    let home = home.canonicalize().map_err(|e| e.to_string())?;
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
args = ["-m", "gaius.mcp_terminal"]
env = {{ PYTHONDONTWRITEBYTECODE = "1", PYTHONUNBUFFERED = "1" }}
enabled = true
startup_timeout_sec = 45

disabled_mcp_servers = ["cybersec"]
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
    let ws = session_state_root()?.join("ws").join(session_id);
    std::fs::create_dir_all(&ws).map_err(|e| e.to_string())?;
    let ws = ws.canonicalize().map_err(|e| e.to_string())?;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn session_state_is_not_under_build_dev_symlink() {
        let tmp = std::env::temp_dir().join(format!(
            "gaius-ui-state-{}",
            std::process::id()
        ));
        std::env::set_var("GAIUS_UI_STATE", &tmp);
        let root = session_state_root().expect("state root");
        let s = root.to_string_lossy();
        assert!(
            !s.contains("/build/dev/"),
            "GROK_HOME must not sit under the KB symlink: {s}"
        );
        let home = write_session_home("test-session", "127.0.0.1:9890").expect("home");
        assert!(home.join("config.toml").is_file());
        assert!(!home.to_string_lossy().contains("/build/dev/"));
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
