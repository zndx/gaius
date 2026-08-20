//! gaius-ui — TUI-parity board service (Axum + Askama + Keiretsu).
//!
//! Terminal: ghostty-web WASM (VT) ↔ PTY ↔ oss-grok-build harness.
//! Grok's model HTTP is this process's `/v1`, which is Engine/Complete.

mod artifact;
mod ask_write;
mod brand;
mod engine;
mod gaius;
mod gaius_slash;
mod grok;
mod openai;
mod ops;
mod pty;

use askama::Template;
use axum::{
    extract::{DefaultBodyLimit, Multipart, Query, State},
    response::{Html, IntoResponse, Json, Redirect},
    routing::{get, post},
    Form, Router,
};
use std::sync::{Arc, RwLock};
use serde::{Deserialize, Serialize};
use std::{net::SocketAddr, path::PathBuf};
use tower_http::{cors::CorsLayer, services::ServeDir, trace::TraceLayer};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

const RESERVE: u32 = 65_536;

#[derive(Template)]
#[template(path = "discover.html")]
struct DiscoverPage {
    title: String,
    active: String,
    mode: String,
    asset_v: String,
    brand_id: String,
    logo_href: String,
    logo_alt: String,
}

#[derive(Template)]
#[template(path = "board.html")]
struct BoardPage {
    title: String,
    active: String,
    mode: String,
    asset_v: String,
    brand_id: String,
    logo_href: String,
    logo_alt: String,
    reserve: u32,
    kappa: String,
    tenuki: String,
}

#[derive(Template)]
#[template(path = "agenda.html")]
struct AgendaPage {
    title: String,
    active: String,
    mode: String,
    asset_v: String,
    brand_id: String,
    logo_href: String,
    logo_alt: String,
}

#[derive(Template)]
#[template(path = "cognition.html")]
struct CognitionPage {
    title: String,
    active: String,
    mode: String,
    asset_v: String,
    brand_id: String,
    logo_href: String,
    logo_alt: String,
}

#[derive(Template)]
#[template(path = "summary.html")]
struct SummaryPage {
    title: String,
    active: String,
    mode: String,
    asset_v: String,
    brand_id: String,
    logo_href: String,
    logo_alt: String,
}

#[derive(Template)]
#[template(path = "terminal.html")]
struct TerminalPage {
    title: String,
    active: String,
    mode: String,
    asset_v: String,
    brand_id: String,
    logo_href: String,
    logo_alt: String,
}

#[derive(Template)]
#[template(path = "settings.html")]
struct SettingsPage {
    title: String,
    active: String,
    mode: String,
    asset_v: String,
    brand_id: String,
    logo_href: String,
    logo_alt: String,
    brands: Vec<brand::BrandOption>,
    selected_brand: String,
    ask_backend: String,
    saved_msg: Option<String>,
}

#[derive(Serialize)]
struct BoardJson {
    cursor: [u8; 2],
    kappa: Option<f64>,
    tenuki_target: Option<[u8; 2]>,
    tenuki_visited: Vec<[u8; 2]>,
    curvature: Option<Vec<Vec<f64>>>,
    cognition: CognitionJson,
}

#[derive(Serialize)]
struct CognitionJson {
    purpose: &'static str,
    reserve: u32,
    r#where: String,
    doing: String,
    decide: String,
}

struct ChromeBits {
    mode: String,
    asset_v: String,
    brand_id: String,
    logo_href: String,
    logo_alt: String,
}

fn chrome_bits(state: &openai::AppState) -> ChromeBits {
    let b = state.brand.read().expect("brand lock");
    ChromeBits {
        mode: "dark".into(),
        asset_v: std::env::var("GAIUS_UI_ASSET_V").unwrap_or_else(|_| "0.3.11-chart-once".into()),
        brand_id: b.id.clone(),
        logo_href: b.logo_href.clone(),
        logo_alt: b.logo_alt.clone(),
    }
}

async fn discover(State(state): State<openai::AppState>) -> impl IntoResponse {
    let c = chrome_bits(&state);
    Html(
        DiscoverPage {
            title: "Discover".into(),
            active: "discover".into(),
            mode: c.mode,
            asset_v: c.asset_v,
            brand_id: c.brand_id,
            logo_href: c.logo_href,
            logo_alt: c.logo_alt,
        }
        .render()
        .unwrap_or_else(|e| format!("template error: {e}")),
    )
}

async fn discover_api(Query(q): Query<DiscoverQuery>) -> impl IntoResponse {
    match gaius::Gaius::from_env()
        .discover_surface(
            q.window.unwrap_or_default(),
            q.query.unwrap_or_default(),
            q.breakdown.unwrap_or_default(),
            q.limit.unwrap_or(50),
        )
        .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => summary_err(e),
    }
}

#[derive(Deserialize)]
struct DiscoverQuery {
    window: Option<String>,
    query: Option<String>,
    breakdown: Option<String>,
    limit: Option<i32>,
}

async fn board(State(state): State<openai::AppState>) -> impl IntoResponse {
    let c = chrome_bits(&state);
    Html(
        BoardPage {
            title: "Board".into(),
            active: "board".into(),
            mode: c.mode,
            asset_v: c.asset_v,
            brand_id: c.brand_id,
            logo_href: c.logo_href,
            logo_alt: c.logo_alt,
            reserve: RESERVE,
            kappa: "—".into(),
            tenuki: "—".into(),
        }
        .render()
        .unwrap_or_else(|e| format!("template error: {e}")),
    )
}

async fn agenda(State(state): State<openai::AppState>) -> impl IntoResponse {
    let c = chrome_bits(&state);
    Html(
        AgendaPage {
            title: "Agenda".into(),
            active: "agenda".into(),
            mode: c.mode,
            asset_v: c.asset_v,
            brand_id: c.brand_id,
            logo_href: c.logo_href,
            logo_alt: c.logo_alt,
        }
        .render()
        .unwrap_or_else(|e| format!("template error: {e}")),
    )
}

#[derive(Deserialize)]
struct AgendaQuery {
    window_days: Option<i32>,
    kind: Option<String>,
    tag: Option<String>,
    path: Option<String>,
    origin: Option<String>,
    timezone: Option<String>,
}

#[derive(Deserialize)]
struct AgendaWrite {
    kind: Option<String>,
    title: Option<String>,
    body: Option<String>,
    starts: Option<String>,
    ends: Option<String>,
    tags: Option<Vec<String>>,
    pin: Option<bool>,
    path: Option<String>,
    checks: Option<Vec<AgendaCheckIn>>,
    intent: Option<String>,
    r#with: Option<String>,
    timezone: Option<String>,
}

#[derive(Deserialize)]
struct AgendaCheckIn {
    done: Option<bool>,
    text: Option<String>,
}

#[derive(Deserialize)]
struct ArtifactQuery {
    since: Option<u64>,
}

async fn ask_artifacts(
    State(state): State<openai::AppState>,
    Query(q): Query<ArtifactQuery>,
) -> impl IntoResponse {
    let (gen, items) = state.artifacts.since(q.since.unwrap_or(0));
    Json(serde_json::json!({ "gen": gen, "items": items }))
}

async fn ask_artifacts_clear(State(state): State<openai::AppState>) -> impl IntoResponse {
    let gen = state.artifacts.clear();
    Json(serde_json::json!({ "gen": gen, "items": [] }))
}

async fn ask_artifact_post(
    State(state): State<openai::AppState>,
    axum::Json(body): axum::Json<serde_json::Value>,
) -> impl IntoResponse {
    match state.artifacts.push(body) {
        Ok(item) => Json(serde_json::json!({ "item": item })).into_response(),
        Err(e) => (
            axum::http::StatusCode::BAD_REQUEST,
            format!("{e}\n"),
        )
            .into_response(),
    }
}

fn agenda_err(e: gaius::GaiusError) -> axum::response::Response {
    (
        axum::http::StatusCode::SERVICE_UNAVAILABLE,
        format!("{e}\n"),
    )
        .into_response()
}

async fn agenda_api(Query(q): Query<AgendaQuery>) -> impl IntoResponse {
    if let Some(path) = q.path.filter(|p| !p.is_empty()) {
        return match gaius::Gaius::from_env().agenda_get(path).await {
            Ok(v) => Json(v).into_response(),
            Err(e) => agenda_err(e),
        };
    }
    match gaius::Gaius::from_env()
        .agenda_list(
            q.window_days.unwrap_or(14),
            q.kind.unwrap_or_default(),
            q.tag.unwrap_or_default(),
            q.origin.unwrap_or_default(),
            q.timezone.unwrap_or_default(),
        )
        .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => agenda_err(e),
    }
}

async fn agenda_create(axum::Json(body): axum::Json<AgendaWrite>) -> impl IntoResponse {
    match gaius::Gaius::from_env()
        .agenda_create(
            body.kind.unwrap_or_else(|| "note".into()),
            body.title.unwrap_or_default(),
            body.body.unwrap_or_default(),
            body.starts.unwrap_or_default(),
            body.ends.unwrap_or_default(),
            body.tags.unwrap_or_default(),
            body.pin.unwrap_or(false),
            body.intent.unwrap_or_default(),
            body.r#with.unwrap_or_default(),
            body.timezone.unwrap_or_default(),
        )
        .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => agenda_err(e),
    }
}

async fn agenda_update(axum::Json(body): axum::Json<AgendaWrite>) -> impl IntoResponse {
    let path = body.path.unwrap_or_default();
    let checks = body.checks.map(|cs| {
        cs.into_iter()
            .map(|c| (c.done.unwrap_or(false), c.text.unwrap_or_default()))
            .collect()
    });
    match gaius::Gaius::from_env()
        .agenda_update(
            path,
            body.title.unwrap_or_default(),
            body.body.unwrap_or_default(),
            body.starts.unwrap_or_default(),
            body.ends.unwrap_or_default(),
            body.tags.unwrap_or_default(),
            body.pin,
            checks,
        )
        .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => agenda_err(e),
    }
}

async fn summary_page(State(state): State<openai::AppState>) -> impl IntoResponse {
    let c = chrome_bits(&state);
    Html(
        SummaryPage {
            title: "Summary".into(),
            active: "summary".into(),
            mode: c.mode,
            asset_v: c.asset_v,
            brand_id: c.brand_id,
            logo_href: c.logo_href,
            logo_alt: c.logo_alt,
        }
        .render()
        .unwrap_or_else(|e| format!("template error: {e}")),
    )
}

#[derive(Deserialize)]
struct SummaryQuery {
    section: Option<String>,
    lens: Option<String>,
    week: Option<String>,
    id: Option<String>,
}

#[derive(Deserialize)]
struct SummaryHopBody {
    from_id: Option<String>,
    target: Option<String>,
    section: Option<String>,
    lens: Option<String>,
    week: Option<String>,
}

#[derive(Deserialize)]
struct SummaryForkBody {
    id: Option<String>,
    origin_project: Option<String>,
}

fn summary_err(e: gaius::GaiusError) -> axum::response::Response {
    (
        axum::http::StatusCode::SERVICE_UNAVAILABLE,
        format!("{e}\n"),
    )
        .into_response()
}

async fn watts_api() -> impl IntoResponse {
    match gaius::Gaius::from_env().signals_telemetry().await {
        Ok(v) => Json(v).into_response(),
        Err(e) => summary_err(e),
    }
}

async fn ops_api(State(state): State<openai::AppState>) -> impl IntoResponse {
    let backend = state.ask_backend.read().expect("ask lock").clone();
    let cap = crate::brand::ask_complete_alias(&backend);
    Json(crate::ops::snapshot(
        &state.sessions,
        &state.complete_watch,
        &backend,
        cap,
    ))
}

async fn federation_surfaces_api() -> impl IntoResponse {
    match gaius::Gaius::from_env().federation_surfaces().await {
        Ok(v) => Json(v).into_response(),
        Err(e) => summary_err(e),
    }
}

async fn summary_index_api(Query(q): Query<SummaryQuery>) -> impl IntoResponse {
    match gaius::Gaius::from_env()
        .summary_index(
            q.section.unwrap_or_default(),
            q.lens.unwrap_or_default(),
            q.week.unwrap_or_default(),
            48,
        )
        .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => summary_err(e),
    }
}

async fn summary_note_api(Query(q): Query<SummaryQuery>) -> impl IntoResponse {
    match gaius::Gaius::from_env()
        .summary_get(
            q.id.unwrap_or_default(),
            q.section.unwrap_or_default(),
            q.lens.unwrap_or_default(),
            q.week.unwrap_or_default(),
        )
        .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => summary_err(e),
    }
}

async fn summary_hop_api(Json(body): Json<SummaryHopBody>) -> impl IntoResponse {
    match gaius::Gaius::from_env()
        .summary_hop(
            body.from_id.unwrap_or_default(),
            body.target.unwrap_or_default(),
            body.section.unwrap_or_default(),
            body.lens.unwrap_or_default(),
            body.week.unwrap_or_default(),
        )
        .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => summary_err(e),
    }
}

async fn summary_schedules_api() -> impl IntoResponse {
    match gaius::Gaius::from_env().summary_schedules().await {
        Ok(v) => Json(v).into_response(),
        Err(e) => summary_err(e),
    }
}

#[derive(Deserialize)]
struct SummaryTriggerBody {
    id: Option<String>,
}

async fn summary_trigger_api(Json(body): Json<SummaryTriggerBody>) -> impl IntoResponse {
    match gaius::Gaius::from_env()
        .summary_trigger(body.id.unwrap_or_default())
        .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => summary_err(e),
    }
}

async fn summary_fork_api(Json(body): Json<SummaryForkBody>) -> impl IntoResponse {
    match gaius::Gaius::from_env()
        .summary_fork(
            body.id.unwrap_or_default(),
            body.origin_project.unwrap_or_default(),
        )
        .await
    {
        Ok(v) => Json(v).into_response(),
        Err(e) => summary_err(e),
    }
}

async fn cognition(State(state): State<openai::AppState>) -> impl IntoResponse {
    let c = chrome_bits(&state);
    Html(
        CognitionPage {
            title: "Cognition".into(),
            active: "cognition".into(),
            mode: c.mode,
            asset_v: c.asset_v,
            brand_id: c.brand_id,
            logo_href: c.logo_href,
            logo_alt: c.logo_alt,
        }
        .render()
        .unwrap_or_else(|e| format!("template error: {e}")),
    )
}

#[derive(Deserialize)]
struct CognitionQuery {
    window_days: Option<i32>,
    stream: Option<String>,
}

async fn cognition_api(Query(q): Query<CognitionQuery>) -> impl IntoResponse {
    let window_days = q.window_days.unwrap_or(365);
    let stream = q.stream.unwrap_or_default();
    match gaius::Gaius::from_env()
        .cognition_surface(window_days, 80, stream)
        .await
    {
        Ok(snap) => Json(snap).into_response(),
        Err(e) => (
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            format!("{e}\n"),
        )
            .into_response(),
    }
}

async fn terminal(State(state): State<openai::AppState>) -> impl IntoResponse {
    let c = chrome_bits(&state);
    Html(
        TerminalPage {
            title: "Terminal".into(),
            active: "terminal".into(),
            mode: c.mode,
            asset_v: c.asset_v,
            brand_id: c.brand_id,
            logo_href: c.logo_href,
            logo_alt: c.logo_alt,
        }
        .render()
        .unwrap_or_else(|e| format!("template error: {e}")),
    )
}

#[derive(Deserialize)]
struct SettingsQuery {
    saved: Option<String>,
    error: Option<String>,
}

#[derive(Deserialize)]
struct BrandForm {
    brand_id: String,
}

fn settings_html(state: &openai::AppState, saved_msg: Option<String>) -> String {
    let c = chrome_bits(state);
    let brands = brand::list_brand_packs(&state.assets_dir, &state.custom_dir);
    SettingsPage {
        title: "Settings".into(),
        active: "settings".into(),
        mode: c.mode,
        asset_v: c.asset_v,
        brand_id: c.brand_id.clone(),
        logo_href: c.logo_href,
        logo_alt: c.logo_alt,
        selected_brand: c.brand_id,
        ask_backend: state.ask_backend.read().expect("ask lock").clone(),
        brands,
        saved_msg,
    }
    .render()
    .unwrap_or_else(|e| format!("template error: {e}"))
}

async fn settings(
    State(state): State<openai::AppState>,
    Query(q): Query<SettingsQuery>,
) -> impl IntoResponse {
    let saved_msg = if let Some(err) = q.error.filter(|s| !s.is_empty()) {
        Some(err)
    } else if q.saved.is_some() {
        Some(format!(
            "Branding applied ({}). All clients use this pack.",
            state.brand.read().expect("brand lock").id
        ))
    } else {
        None
    };
    Html(settings_html(&state, saved_msg))
}

async fn post_settings_brand(
    State(state): State<openai::AppState>,
    Form(form): Form<BrandForm>,
) -> impl IntoResponse {
    let id = form.brand_id.trim();
    match brand::load_brand_id(&state.assets_dir, &state.custom_dir, id) {
        Ok(b) if b.id == brand::BRAND_CUSTOM && !b.has_logo => Redirect::to(
            "/settings?error=Custom%20pack%20is%20empty.%20Upload%20a%20.tgz%20first.%20Guru:%20%23UI.00000004.BRANDPACK",
        )
        .into_response(),
        Ok(b) => {
            let deploy = brand::DeploySettings {
                brand_id: b.id.clone(),
                ask_backend: state.ask_backend.read().expect("ask lock").clone(),
            };
            if let Err(e) = deploy.save(&state.settings_path) {
                return Html(settings_html(&state, Some(e.to_string()))).into_response();
            }
            *state.brand.write().expect("brand lock") = b;
            Redirect::to("/settings?saved=1").into_response()
        }
        Err(e) => Html(settings_html(&state, Some(e.to_string()))).into_response(),
    }
}

async fn post_settings_brand_upload(
    State(state): State<openai::AppState>,
    mut multipart: Multipart,
) -> impl IntoResponse {
    let mut bytes: Option<bytes::Bytes> = None;
    while let Ok(Some(field)) = multipart.next_field().await {
        if field.name() == Some("pack") {
            match field.bytes().await {
                Ok(b) => bytes = Some(b),
                Err(e) => {
                    return Html(settings_html(
                        &state,
                        Some(format!("upload read failed: {e}\n  Guru: #UI.00000005.BRANDTGZ")),
                    ))
                    .into_response();
                }
            }
        }
    }
    let Some(bytes) = bytes else {
        return Html(settings_html(
            &state,
            Some("no pack file in upload.\n  Guru: #UI.00000005.BRANDTGZ".into()),
        ))
        .into_response();
    };
    match brand::ingest_tgz(&bytes, &state.custom_dir) {
        Ok(b) => {
            let deploy = brand::DeploySettings {
                brand_id: b.id.clone(),
                ask_backend: state.ask_backend.read().expect("ask lock").clone(),
            };
            let _ = deploy.save(&state.settings_path);
            *state.brand.write().expect("brand lock") = b;
            Redirect::to("/settings?saved=1").into_response()
        }
        Err(e) => Html(settings_html(&state, Some(e.to_string()))).into_response(),
    }
}

#[derive(Deserialize)]
struct AskForm {
    ask_backend: String,
}

async fn apply_ask_endpoints(backend: &str) -> Result<String, String> {
    let g = gaius::Gaius::from_env();
    match backend {
        brand::ASK_SAE_9B => {
            let _ = g.stop_endpoint("clt".into()).await;
            let _ = g.stop_endpoint("interpretable".into()).await;
            let _ = g.stop_endpoint("interpretable-b".into()).await;
            g.ensure_endpoint("ask-sae".into())
                .await
                .map_err(|e| e.to_string())?;
            Ok("Ask → medium: Qwen3.5-9B-Base + SAE (TP=2 on GPU 4–5). Thinking 0–3 untouched.".into())
        }
        brand::ASK_CLT_PAIR | "clt" | "interpretable" => {
            let _ = g.stop_endpoint("ask-sae".into()).await;
            let _ = g.stop_endpoint("clt".into()).await;
            g.ensure_endpoint("interpretable".into())
                .await
                .map_err(|e| e.to_string())?;
            g.ensure_endpoint("interpretable-b".into())
                .await
                .map_err(|e| e.to_string())?;
            Ok("Ask → light: 2× Qwen3-1.7B (one whole GPU each, 4 and 5).".into())
        }
        other => Err(format!(
            "unknown ask backend {other}.\n  Guru: #UI.00000009.ASKBACKEND"
        )),
    }
}

async fn post_settings_ask(
    State(state): State<openai::AppState>,
    Form(form): Form<AskForm>,
) -> impl IntoResponse {
    let backend = form.ask_backend.trim();
    let normalized = match backend {
        brand::ASK_SAE_9B => brand::ASK_SAE_9B,
        brand::ASK_CLT_PAIR => brand::ASK_CLT_PAIR,
        _ => {
            return Html(settings_html(
                &state,
                Some(format!(
                    "unknown ask backend {backend}.\n  Guru: #UI.00000009.ASKBACKEND"
                )),
            ))
            .into_response();
        }
    };
    let deploy = brand::DeploySettings {
        brand_id: state.brand.read().expect("brand lock").id.clone(),
        ask_backend: normalized.into(),
    };
    if let Err(e) = deploy.save(&state.settings_path) {
        return Html(settings_html(&state, Some(e.to_string()))).into_response();
    }
    *state.ask_backend.write().expect("ask lock") = normalized.into();
    let msg = match apply_ask_endpoints(normalized).await {
        Ok(m) => m,
        Err(e) => format!("Saved {normalized}; endpoint start: {e}"),
    };
    Html(settings_html(&state, Some(msg))).into_response()
}

#[derive(serde::Deserialize)]
struct BoardFile {
    n_documents: Option<u32>,
    n_iceberg: Option<u32>,
    cells_occupied: Option<u32>,
    projection_method: Option<String>,
    iceberg_coverage: Option<f64>,
    allocations: Option<Vec<Vec<i32>>>,
}

fn board_json_path() -> PathBuf {
    std::env::var("GAIUS_BOARD_JSON")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("build/dev/.board.json"))
}

async fn board_api() -> impl IntoResponse {
    let path = board_json_path();
    let raw = match std::fs::read_to_string(&path) {
        Ok(s) => s,
        Err(_) => {
            return (
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                format!(
                    "board snapshot missing: {}\n  Try: uv run gaius-cli --cmd \"/board refresh\" --format json\n",
                    path.display()
                ),
            )
                .into_response();
        }
    };
    let file: BoardFile = match serde_json::from_str(&raw) {
        Ok(f) => f,
        Err(e) => {
            return (
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                format!("board snapshot unreadable: {e}\n"),
            )
                .into_response();
        }
    };
    let allocations = file.allocations.unwrap_or_default();
    let curvature = if allocations.len() == 19 {
        Some(
            allocations
                .iter()
                .map(|row| {
                    row.iter()
                        .map(|v| (*v as f64) / 100.0)
                        .collect::<Vec<_>>()
                })
                .collect(),
        )
    } else {
        None
    };
    Json(BoardJson {
        cursor: [9, 9],
        kappa: None,
        tenuki_target: None,
        tenuki_visited: vec![],
        curvature,
        cognition: CognitionJson {
            purpose: "one-next-question",
            reserve: RESERVE,
            r#where: format!(
                "docs={} iced={} cells={}",
                file.n_documents.unwrap_or(0),
                file.n_iceberg.unwrap_or(0),
                file.cells_occupied.unwrap_or(0)
            ),
            doing: file
                .projection_method
                .unwrap_or_else(|| "kb_topology".into()),
            decide: format!(
                "iceberg coverage {}",
                file.iceberg_coverage.unwrap_or(0.0)
            ),
        },
    })
    .into_response()
}

async fn healthz() -> &'static str {
    "ok\n"
}

async fn list_models() -> impl IntoResponse {
    Json(serde_json::json!({
        "object": "list",
        "data": [{
            "id": "thinking",
            "object": "model",
            "owned_by": "gaius"
        }, {
            "id": "gaius-thinking",
            "object": "model",
            "owned_by": "gaius"
        }]
    }))
}

fn assets_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../assets")
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "gaius_ui=info,tower_http=info".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    let bind: SocketAddr = std::env::var("GAIUS_UI_BIND")
        .unwrap_or_else(|_| "0.0.0.0:9890".into())
        .parse()?;
    let assets = assets_dir();
    if !assets.is_dir() {
        anyhow::bail!(
            "gaius-ui assets missing at {} — checkout components/gaius-ui/assets",
            assets.display()
        );
    }

    let custom = brand::custom_dir();
    let deploy = brand::DeploySettings::load_or_bootstrap();
    let brand_live = match brand::load_brand_id(&assets, &custom, &deploy.brand_id) {
        Ok(b) if b.id == brand::BRAND_CUSTOM && !b.has_logo => {
            brand::load_brand_id(&assets, &custom, brand::BRAND_WEATHERSHIP)?
        }
        Ok(b) => b,
        Err(_) if deploy.brand_id == brand::BRAND_CUSTOM => {
            brand::load_brand_id(&assets, &custom, brand::BRAND_WEATHERSHIP)?
        }
        Err(e) => anyhow::bail!("{e}"),
    };
    tracing::info!(brand = %brand_live.id, "logo pack");

    let state = openai::AppState {
        lattice: engine::Lattice::from_env(),
        sessions: Arc::new(pty::Sessions::new()),
        bind: bind.to_string(),
        brand: Arc::new(RwLock::new(brand_live)),
        settings_path: brand::DeploySettings::config_path(),
        assets_dir: assets.clone(),
        custom_dir: custom.clone(),
        artifacts: artifact::ArtifactBus::default(),
        ask_backend: Arc::new(RwLock::new(deploy.ask_backend.clone())),
        complete_watch: crate::ops::CompleteWatch::default(),
    };
    tracing::info!(
        "lattice {} capability={}",
        state.lattice.target(),
        state.lattice.capability()
    );
    {
        let backend = deploy.ask_backend.clone();
        tokio::spawn(async move {
            match apply_ask_endpoints(&backend).await {
                Ok(m) => tracing::info!(backend = %backend, "{m}"),
                Err(e) => tracing::warn!(backend = %backend, error = %e, "ask endpoints at boot"),
            }
        });
    }

    let custom_serve = if custom.is_dir() {
        custom
    } else {
        assets.join("brand/custom")
    };
    let app = Router::new()
        .route("/", get(discover))
        .route("/lab/board", get(board))
        .route("/api/gaius/v1/discover", get(discover_api))
        .route("/agenda", get(agenda))
        .route("/api/gaius/v1/agenda", get(agenda_api).post(agenda_create))
        .route("/api/gaius/v1/agenda/update", post(agenda_update))
        .route("/cognition", get(cognition))
        .route("/summary", get(summary_page))
        .route("/api/gaius/v1/summary", get(summary_index_api))
        .route("/api/gaius/v1/summary/note", get(summary_note_api))
        .route("/api/gaius/v1/summary/hop", post(summary_hop_api))
        .route("/api/gaius/v1/summary/fork", post(summary_fork_api))
        .route("/api/gaius/v1/summary/schedules", get(summary_schedules_api))
        .route("/api/gaius/v1/summary/trigger", post(summary_trigger_api))
        .route("/terminal", get(terminal))
        .route("/settings", get(settings))
        .route("/settings/brand", post(post_settings_brand))
        .route("/settings/brand/upload", post(post_settings_brand_upload))
        .route("/settings/ask", post(post_settings_ask))
        .route("/ws/terminal/{id}", get(pty::terminal_ws))
        .route("/v1/chat/completions", post(openai::chat_completions))
        .route("/v1/models", get(list_models))
        .route("/api/gaius/v1/board", get(board_api))
        .route("/api/gaius/v1/cognition", get(cognition_api))
        .route("/api/gaius/v1/ops", get(ops_api))
        .route("/api/gaius/v1/watts", get(watts_api))
        .route("/api/gaius/v1/federation/surfaces", get(federation_surfaces_api))
        .route(
            "/api/gaius/v1/ask/artifacts",
            get(ask_artifacts)
                .post(ask_artifact_post)
                .delete(ask_artifacts_clear),
        )
        .route("/healthz", get(healthz))
        .nest_service("/assets/brand/custom", ServeDir::new(custom_serve))
        .nest_service("/assets", ServeDir::new(assets))
        .layer(DefaultBodyLimit::max(8 * 1024 * 1024))
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    tracing::info!("gaius-ui listening on http://{bind}");
    let listener = tokio::net::TcpListener::bind(bind).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
