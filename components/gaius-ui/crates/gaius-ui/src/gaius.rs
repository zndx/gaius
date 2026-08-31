//! GaiusService client — CognitionSurface (federation attention).

use std::time::Duration;

use serde::Serialize;
use thiserror::Error;
use tonic::transport::Channel;

pub mod pb {
    tonic::include_proto!("gaius.engine");
}

use pb::{
    gaius_service_client::GaiusServiceClient, AgendaCheck, AgendaCreateRequest,
    AgendaGetRequest, AgendaListRequest, AgendaUpdateRequest, CognitionSurfaceRequest,
    CognitionWaterfallRequest,
    SummaryForkRequest, SummaryGetRequest, SummaryHopRequest, SummaryIndexRequest,
    SummaryScheduleTriggerRequest, SummarySchedulesRequest,
    FederationSurfacesRequest, FederationCognitionRequest, AskPresentRequest,
    CognitionCorpusRequest, CognitionCorpusItem, CognitionTraceRequest,
    FederationContributionsRequest,
    EnsureEndpointResponse, StartEndpointRequest, StopEndpointRequest,
    SignalsTelemetryRequest, DiscoverSurfaceRequest,
};

fn surface_title(project: &str) -> String {
    match project.trim().to_ascii_lowercase().as_str() {
        "gaius" => "Gaius".into(),
        "signals" => "Signals".into(),
        "aegir" => "Ægir".into(),
        "atelier" => "Atelier".into(),
        "" => "Peer".into(),
        other => other
            .replace('-', " ")
            .replace('_', " ")
            .split_whitespace()
            .map(|w| {
                let mut c = w.chars();
                match c.next() {
                    None => String::new(),
                    Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
                }
            })
            .collect::<Vec<_>>()
            .join(" "),
    }
}

#[derive(Debug, Error)]
pub enum GaiusError {
    #[error("connect {0}")]
    Connect(#[from] tonic::transport::Error),
    #[error("rpc {0}")]
    Rpc(#[from] tonic::Status),
    #[error("{0}")]
    Message(String),
}

#[derive(Clone)]
pub struct Gaius {
    target: String,
}

impl Gaius {
    pub fn from_env() -> Self {
        Self {
            target: std::env::var("GAIUS_ENGINE_TARGET")
                .unwrap_or_else(|_| "127.0.0.1:50051".into()),
        }
    }

    pub async fn ensure_endpoint(&self, name: String) -> Result<EnsureEndpointResponse, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .ensure_endpoint(StartEndpointRequest {
                endpoint_name: name,
            })
            .await?
            .into_inner();
        if !r.message.is_empty() && !r.healthy && r.status == "error" {
            return Err(GaiusError::Message(r.message));
        }
        Ok(r)
    }

    pub async fn discover_surface(
        &self,
        window: String,
        query: String,
        breakdown: String,
        limit: i32,
    ) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.discover_client().await?;
        let r = c
            .discover_surface(DiscoverSurfaceRequest {
                window: if window.is_empty() {
                    "12h".into()
                } else {
                    window
                },
                query,
                breakdown: if breakdown.is_empty() {
                    "source".into()
                } else {
                    breakdown
                },
                limit: if limit <= 0 { 50 } else { limit },
                cursor: String::new(),
                feature_pins: vec![],
                from_ts: String::new(),
                to_ts: String::new(),
            })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        let buckets: Vec<serde_json::Value> = r
            .buckets
            .into_iter()
            .map(|b| {
                serde_json::json!({
                    "t": b.t,
                    "n": b.n,
                    "breakdown_key": b.breakdown_key,
                    "salience": b.salience,
                    "watts": b.watts,
                    "util": b.util,
                    "salience_ma": b.salience_ma,
                    "watts_ma": b.watts_ma,
                    "util_ma": b.util_ma,
                })
            })
            .collect();
        let docs: Vec<serde_json::Value> = r
            .docs
            .into_iter()
            .map(|d| {
                serde_json::json!({
                    "id": d.id,
                    "stream": d.stream,
                    "source": d.source,
                    "ts": d.ts,
                    "title": d.title,
                    "body": d.body,
                    "source_id": d.source_id,
                    "url": d.url,
                })
            })
            .collect();
        let facets: Vec<serde_json::Value> = r
            .facets
            .into_iter()
            .map(|f| {
                serde_json::json!({
                    "key": f.key,
                    "kind": f.kind,
                    "count": f.count,
                    "salience": f.salience,
                    "label": f.label,
                })
            })
            .collect();
        let ep = r.next_episode;
        let st = r.status;
        Ok(serde_json::json!({
            "window": r.window,
            "query": r.query,
            "interval": r.interval,
            "scraped_at": r.scraped_at,
            "total": r.total,
            "last_salience_at": r.last_salience_at,
            "clock": r.clock,
            "next_episode": ep.map(|e| serde_json::json!({
                "kind": e.kind,
                "at": e.at,
                "eta_s": e.eta_s,
                "label": e.label,
            })),
            "status": st.map(|s| serde_json::json!({
                "updating": s.updating,
                "workflows": s.workflows,
                "waiting_at": s.waiting_at,
                "watts": s.watts,
                "watts_live": s.watts_live,
                "articles": s.articles,
                "projects": s.projects,
                "thoughts": s.thoughts,
                "terms_skos": s.terms_skos,
                "terms_cites": s.terms_cites,
                "agenda_min": s.agenda_min,
                "agenda_max": s.agenda_max,
                "agenda_std": s.agenda_std,
                "salience_peak": s.salience_peak,
                "cognition_tokens": s.cognition_tokens,
            })),
            "buckets": buckets,
            "docs": docs,
            "facets": facets,
        }))
    }

    pub async fn signals_telemetry(&self) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .signals_telemetry(SignalsTelemetryRequest {})
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        let gpus: Vec<serde_json::Value> = r
            .gpus
            .into_iter()
            .map(|g| {
                serde_json::json!({
                    "index": g.index,
                    "uuid": g.uuid,
                    "model": g.model,
                    "power_w": g.power_w,
                    "util": g.util,
                    "memory_used_mib": g.memory_used_mib,
                    "memory_free_mib": g.memory_free_mib,
                    "energy_mj": g.energy_mj,
                    "temp_c": g.temp_c,
                })
            })
            .collect();
        Ok(serde_json::json!({
            "source_url": r.source_url,
            "scraped_at": r.scraped_at,
            "total_w": r.total_w,
            "parked_w": r.parked_w,
            "inferring_w": r.inferring_w,
            "gpus": gpus,
        }))
    }

    pub async fn stop_endpoint(&self, name: String) -> Result<(), GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .stop_endpoint(StopEndpointRequest {
                endpoint_name: name,
                force: false,
            })
            .await?
            .into_inner();
        if !r.success && !r.message.is_empty() {
            return Err(GaiusError::Message(r.message));
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn cognition_surface(
        &self,
        window_days: i32,
        thought_limit: i32,
        stream: String,
        window: String,
        bucket: String,
        from_ms: i64,
        to_ms: i64,
    ) -> Result<CognitionSurfaceJson, GaiusError> {
        let endpoint = format!("http://{}", self.target.trim());
        let ch = Channel::from_shared(endpoint)
            .map_err(|e| GaiusError::Message(e.to_string()))?
            .connect()
            .await?;
        let mut c = GaiusServiceClient::new(ch);
        let r = c
            .cognition_surface(CognitionSurfaceRequest {
                window_days,
                thought_limit,
                stream,
                window,
                bucket,
                from_ms,
                to_ms,
            })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(CognitionSurfaceJson::from(r))
    }

    pub async fn cognition_thought(
        &self,
        id: String,
    ) -> Result<CognitionThoughtJson, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .cognition_thought(pb::CognitionThoughtRequest { id })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(CognitionThoughtJson {
            thought: r.thought.map(thought_detail_json),
            chain: r.chain.into_iter().map(thought_detail_json).collect(),
        })
    }

    /// Held-open cognition event stream mapped to JSON values (SSE bridge).
    pub async fn subscribe_cognition(
        &self,
    ) -> Result<impl tokio_stream::Stream<Item = serde_json::Value> + Send, GaiusError>
    {
        use tokio_stream::StreamExt;

        let mut c = self.client().await?;
        let stream = c
            .subscribe_cognition(pb::CognitionStreamRequest {
                buffer_size: 100,
                event_types: Vec::new(),
            })
            .await?
            .into_inner();
        Ok(stream.filter_map(|item| item.ok().map(|ev| cognition_event_value(&ev))))
    }

    pub async fn cognition_waterfall(
        &self,
        window_s: i32,
    ) -> Result<CognitionWaterfallJson, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .cognition_waterfall(CognitionWaterfallRequest { window_s })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(CognitionWaterfallJson {
            epoch_unix_ms: r.epoch_unix_ms,
            n_channels: r.n_channels,
            n_times: r.n_times,
            channel_names: r.channel_names,
            matrix: r.matrix,
            driver: r.driver,
            hn_tokens: r.hn_tokens,
            fmp_tokens: r.fmp_tokens,
            bokeh_json: r.bokeh_json,
        })
    }

    async fn client(&self) -> Result<GaiusServiceClient<Channel>, GaiusError> {
        let endpoint = format!("http://{}", self.target.trim());
        let ch = Channel::from_shared(endpoint)
            .map_err(|e| GaiusError::Message(e.to_string()))?
            .connect()
            .await?;
        Ok(GaiusServiceClient::new(ch))
    }

    async fn discover_client(&self) -> Result<GaiusServiceClient<Channel>, GaiusError> {
        let endpoint = format!("http://{}", self.target.trim());
        // Generous outer net (progress doctrine): the engine's own 110s
        // outer net governs; this only bounds a dead engine. Varnish owns
        // interactivity for the discover surface. Chain: servicer 110s <
        // varnish first_byte 120s < here 130s < proxy reqwest 150s.
        let ch = Channel::from_shared(endpoint)
            .map_err(|e| GaiusError::Message(e.to_string()))?
            .connect_timeout(Duration::from_secs(2))
            .timeout(Duration::from_secs(130))
            .connect()
            .await?;
        Ok(GaiusServiceClient::new(ch))
    }

    pub async fn agenda_list(
        &self,
        window_days: i32,
        kind: String,
        tag: String,
        origin: String,
        timezone: String,
    ) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .agenda_list(AgendaListRequest {
                window_days,
                kind,
                tag,
                origin,
                timezone,
            })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({
            "items": r.items.into_iter().map(card_json).collect::<Vec<_>>(),
        }))
    }

    pub async fn agenda_get(&self, path: String) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .agenda_get(AgendaGetRequest { path })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({ "item": card_json(r.item.unwrap_or_default()) }))
    }

    pub async fn agenda_create(
        &self,
        kind: String,
        title: String,
        body: String,
        starts: String,
        ends: String,
        tags: Vec<String>,
        pin: bool,
        intent: String,
        with_whom: String,
        timezone: String,
    ) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .agenda_create(AgendaCreateRequest {
                kind,
                title,
                body,
                starts,
                ends,
                tags,
                pin,
                intent,
                with_whom,
                timezone,
            })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({ "item": card_json(r.item.unwrap_or_default()) }))
    }

    pub async fn agenda_update(
        &self,
        path: String,
        title: String,
        body: String,
        starts: String,
        ends: String,
        tags: Vec<String>,
        pin: Option<bool>,
        checks: Option<Vec<(bool, String)>>,
    ) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let mut req = AgendaUpdateRequest {
            path,
            title,
            body,
            starts,
            ends,
            tags,
            pin: pin.unwrap_or(false),
            has_pin: pin.is_some(),
            checks: vec![],
            has_checks: checks.is_some(),
            intent: String::new(),
            has_intent: false,
            with_whom: String::new(),
            has_with: false,
            timezone: String::new(),
            has_timezone: false,
        };
        if let Some(chs) = checks {
            req.checks = chs
                .into_iter()
                .map(|(done, text)| AgendaCheck { done, text })
                .collect();
        }
        let r = c.agenda_update(req).await?.into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({ "item": card_json(r.item.unwrap_or_default()) }))
    }

    pub async fn ask_present(
        &self,
        kind: &str,
        symbol: &str,
        title: &str,
        from_date: &str,
        to_date: &str,
        payload_json: &str,
    ) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .ask_present(AskPresentRequest {
                kind: kind.to_string(),
                symbol: symbol.to_string(),
                title: title.to_string(),
                from_date: from_date.to_string(),
                to_date: to_date.to_string(),
                payload_json: payload_json.to_string(),
            })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        serde_json::from_str(&r.artifact_json).map_err(|e| GaiusError::Message(e.to_string()))
    }

    fn corpus_item_json(i: CognitionCorpusItem) -> serde_json::Value {
        serde_json::json!({
            "id": i.id,
            "flow_name": i.flow_name,
            "step_name": i.step_name,
            "run_id": i.run_id,
            "subject": i.subject,
            "technique": i.technique,
            "model_name": i.model_name,
            "decision": i.decision,
            "confidence": i.confidence,
            "input_tokens": i.input_tokens,
            "output_tokens": i.output_tokens,
            "latency_ms": i.latency_ms,
            "generated_at_ms": i.generated_at_ms,
            "product_id": i.product_id,
            "has_layers": i.has_layers,
            "layer_count": i.layer_count,
        })
    }

    pub async fn cognition_corpus(
        &self,
        limit: i32,
        window_days: i32,
        flow: String,
    ) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .cognition_corpus(CognitionCorpusRequest {
                limit,
                window_days,
                flow,
            })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({
            "total": r.total,
            "items": r.items.into_iter().map(Self::corpus_item_json).collect::<Vec<_>>(),
        }))
    }

    pub async fn cognition_trace(&self, id: String) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .cognition_trace(CognitionTraceRequest { id })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({
            "item": r.item.map(Self::corpus_item_json),
            "prompt": r.prompt,
            "reasoning_trace": r.reasoning_trace,
            "output": r.output,
            "layers": r
                .layers
                .into_iter()
                .map(|l| {
                    serde_json::json!({
                        "layer": l.layer,
                        "producer": l.producer,
                        "tokens": l.tokens,
                        "text": l.text,
                    })
                })
                .collect::<Vec<_>>(),
        }))
    }

    pub async fn federation_contributions(&self) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .federation_contributions(FederationContributionsRequest {})
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({
            "items": r
                .items
                .into_iter()
                .map(|i| {
                    serde_json::json!({
                        "project": i.project,
                        "interval": i.interval,
                        "range_start_ms": i.range_start_ms,
                        "range_end_ms": i.range_end_ms,
                        "buckets": i
                            .buckets
                            .into_iter()
                            .map(|b| {
                                serde_json::json!({
                                    "start_ms": b.start_ms,
                                    "end_ms": b.end_ms,
                                })
                            })
                            .collect::<Vec<_>>(),
                        "items": i
                            .items
                            .into_iter()
                            .map(|it| {
                                serde_json::json!({
                                    "group": it.group,
                                    "id": it.id,
                                    "system": it.system,
                                    "total": it.total,
                                    "series": it.series,
                                    "peer": it.peer,
                                })
                            })
                            .collect::<Vec<_>>(),
                    })
                })
                .collect::<Vec<_>>(),
        }))
    }

    pub async fn federation_cognition(&self) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .federation_cognition(FederationCognitionRequest {})
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({
            "items": r
                .items
                .into_iter()
                .map(|i| {
                    serde_json::json!({
                        "project": i.project,
                        "unit": i.unit,
                        "running": i.running,
                        "thoughts": i.thoughts,
                        "cycles": i.cycles,
                        "last_cycle_ms": i.last_cycle_ms,
                        "interval": i.interval,
                        "range_start_ms": i.range_start_ms,
                        "range_end_ms": i.range_end_ms,
                        "buckets": i
                            .buckets
                            .into_iter()
                            .map(|b| {
                                serde_json::json!({
                                    "start_ms": b.start_ms,
                                    "end_ms": b.end_ms,
                                    "thoughts": b.thoughts,
                                    "cycles": b.cycles,
                                })
                            })
                            .collect::<Vec<_>>(),
                        "streams": i
                            .stream_counts
                            .into_iter()
                            .map(|s| {
                                serde_json::json!({ "id": s.id, "thoughts": s.thoughts })
                            })
                            .collect::<Vec<_>>(),
                    })
                })
                .collect::<Vec<_>>(),
        }))
    }

    pub async fn federation_surfaces(&self) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .federation_surfaces(FederationSurfacesRequest {})
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({
            "items": r
                .items
                .into_iter()
                .map(|i| {
                    serde_json::json!({
                        "project": i.project,
                        "title": surface_title(&i.project),
                        "engine_target": i.engine_target,
                        "primary_ui": i.primary_ui,
                    })
                })
                .collect::<Vec<_>>(),
        }))
    }

    pub async fn summary_index(
        &self,
        section: String,
        lens: String,
        week: String,
        limit: i32,
    ) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .summary_index(SummaryIndexRequest {
                section,
                lens,
                week,
                limit,
            })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({
            "week": r.week,
            "landing_id": r.landing_id,
            "seed": summary_note_json(r.seed.unwrap_or_default()),
            "items": r.items.into_iter().map(summary_note_json).collect::<Vec<_>>(),
        }))
    }

    pub async fn summary_get(
        &self,
        id: String,
        section: String,
        lens: String,
        week: String,
    ) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .summary_get(SummaryGetRequest {
                id,
                section,
                lens,
                week,
            })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(summary_note_json(r.note.unwrap_or_default()))
    }

    pub async fn summary_hop(
        &self,
        from_id: String,
        target: String,
        section: String,
        lens: String,
        week: String,
    ) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .summary_hop(SummaryHopRequest {
                from_id,
                target,
                section,
                lens,
                week,
            })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        let mut v = summary_note_json(r.note.unwrap_or_default());
        if let serde_json::Value::Object(ref mut m) = v {
            m.insert("resolved_id".into(), serde_json::json!(r.resolved_id));
        }
        Ok(v)
    }

    pub async fn summary_fork(
        &self,
        id: String,
        origin_project: String,
    ) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .summary_fork(SummaryForkRequest { id, origin_project })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(summary_note_json(r.note.unwrap_or_default()))
    }

    pub async fn summary_schedules(&self) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .summary_schedules(SummarySchedulesRequest {})
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({
            "items": r.items.into_iter().map(|i| serde_json::json!({
                "id": i.id,
                "cron": i.cron,
                "task_type": i.task_type,
                "source": i.source,
                "enabled": i.enabled,
                "triggerable": i.triggerable,
                "cadence": i.cadence,
            })).collect::<Vec<_>>(),
        }))
    }

    pub async fn summary_trigger(&self, id: String) -> Result<serde_json::Value, GaiusError> {
        let mut c = self.client().await?;
        let r = c
            .summary_schedule_trigger(SummaryScheduleTriggerRequest { id })
            .await?
            .into_inner();
        if !r.error.is_empty() {
            return Err(GaiusError::Message(r.error));
        }
        Ok(serde_json::json!({
            "task_id": r.task_id,
            "task_type": r.task_type,
        }))
    }
}

fn summary_note_json(n: pb::SummaryNote) -> serde_json::Value {
    serde_json::json!({
        "id": n.id,
        "title": n.title,
        "body": n.body,
        "section": n.section,
        "lens": n.lens,
        "week": n.week,
        "mtime_ms": n.mtime_ms,
        "links": n.links,
        "origin_project": n.origin_project,
        "origin_id": n.origin_id,
        "excerpt": n.excerpt,
        "virtual": n.r#virtual,
    })
}

fn card_json(c: pb::AgendaCard) -> serde_json::Value {
    serde_json::json!({
        "path": c.path,
        "kind": c.kind,
        "title": c.title,
        "body": c.body,
        "excerpt": c.excerpt,
        "prev": c.prev,
        "next": c.next,
        "starts": c.starts,
        "ends": c.ends,
        "tags": c.tags,
        "pin": c.pin,
        "checks": c.checks.into_iter().map(|ch| serde_json::json!({"done": ch.done, "text": ch.text})).collect::<Vec<_>>(),
        "created_ms": c.created_ms,
        "intent": c.intent,
        "with": c.with_whom,
        "calendar_url": c.calendar_url,
        "timezone": c.timezone,
    })
}

#[derive(Serialize)]
pub struct CognitionSurfaceJson {
    pub running: bool,
    pub cycles_completed: i32,
    pub cycles_in_window: i32,
    pub last_cycle_timestamp_ms: i64,
    pub current_task: String,
    pub thoughts: i32,
    pub streams: i32,
    pub active_days: i32,
    pub thoughts_per_cycle: f32,
    pub concentration_stream: String,
    pub concentration_pct: f32,
    pub reserve_tokens: i32,
    pub project: String,
    pub unit: String,
    pub recent: Vec<ThoughtJson>,
    pub top: Vec<ThoughtJson>,
    pub days: Vec<DayJson>,
    pub hours: Vec<HourJson>,
    pub stream_counts: Vec<StreamJson>,
    pub buckets: Vec<BucketJson>,
    pub interval: String,
    pub range_start_ms: i64,
    pub range_end_ms: i64,
    pub effective_end_ms: i64,
    pub bucket_seconds: i32,
    pub contributions: Vec<ContributionJson>,
}

#[derive(Serialize)]
pub struct ContributionJson {
    pub group: String,
    pub id: String,
    pub system: String,
    pub total: i32,
    pub series: Vec<i32>,
    pub peer: String,
}

#[derive(Serialize)]
pub struct BucketJson {
    pub start_ms: i64,
    pub end_ms: i64,
    pub thoughts: i32,
    pub cycles: i32,
    pub tokens: i64,
    pub salience_max: f32,
}

#[derive(Serialize)]
pub struct ThoughtJson {
    pub id: String,
    pub thought_type: String,
    pub title: String,
    pub summary: String,
    pub salience: f32,
    pub generation: i32,
    pub timestamp_ms: i64,
    pub note_path: String,
}

#[derive(Serialize)]
pub struct DayJson {
    pub date: String,
    pub thoughts: i32,
    pub cycles: i32,
}

#[derive(Serialize)]
pub struct HourJson {
    pub weekday: i32,
    pub hour: i32,
    pub thoughts: i32,
}

#[derive(Serialize)]
pub struct StreamJson {
    pub id: String,
    pub thoughts: i32,
}

#[derive(Serialize)]
pub struct CognitionWaterfallJson {
    pub epoch_unix_ms: i64,
    pub n_channels: i32,
    pub n_times: i32,
    pub channel_names: Vec<String>,
    pub matrix: Vec<f32>,
    pub driver: String,
    pub hn_tokens: i32,
    pub fmp_tokens: i32,
    pub bokeh_json: String,
}

impl From<pb::CognitionSurfaceResponse> for CognitionSurfaceJson {
    fn from(r: pb::CognitionSurfaceResponse) -> Self {
        Self {
            running: r.running,
            cycles_completed: r.cycles_completed,
            cycles_in_window: r.cycles_in_window,
            last_cycle_timestamp_ms: r.last_cycle_timestamp_ms,
            current_task: r.current_task,
            thoughts: r.thoughts,
            streams: r.streams,
            active_days: r.active_days,
            thoughts_per_cycle: r.thoughts_per_cycle,
            concentration_stream: r.concentration_stream,
            concentration_pct: r.concentration_pct,
            reserve_tokens: r.reserve_tokens,
            project: r.project,
            unit: r.unit,
            recent: r.recent.into_iter().map(ThoughtJson::from).collect(),
            top: r.top.into_iter().map(ThoughtJson::from).collect(),
            days: r
                .days
                .into_iter()
                .map(|d| DayJson {
                    date: d.date,
                    thoughts: d.thoughts,
                    cycles: d.cycles,
                })
                .collect(),
            hours: r
                .hours
                .into_iter()
                .map(|h| HourJson {
                    weekday: h.weekday,
                    hour: h.hour,
                    thoughts: h.thoughts,
                })
                .collect(),
            stream_counts: r
                .stream_counts
                .into_iter()
                .map(|s| StreamJson {
                    id: s.id,
                    thoughts: s.thoughts,
                })
                .collect(),
            buckets: r
                .buckets
                .into_iter()
                .map(|b| BucketJson {
                    start_ms: b.start_ms,
                    end_ms: b.end_ms,
                    thoughts: b.thoughts,
                    cycles: b.cycles,
                    tokens: b.tokens,
                    salience_max: b.salience_max,
                })
                .collect(),
            interval: r.interval,
            range_start_ms: r.range_start_ms,
            range_end_ms: r.range_end_ms,
            effective_end_ms: r.effective_end_ms,
            bucket_seconds: r.bucket_seconds,
            contributions: r
                .contributions
                .into_iter()
                .map(|c| ContributionJson {
                    group: c.group,
                    id: c.id,
                    system: c.system,
                    total: c.total,
                    series: c.series,
                    peer: c.peer,
                })
                .collect(),
        }
    }
}

impl From<pb::ThoughtMessage> for ThoughtJson {
    fn from(t: pb::ThoughtMessage) -> Self {
        Self {
            id: t.id,
            thought_type: t.thought_type,
            title: t.title,
            summary: t.summary,
            salience: t.salience,
            generation: t.generation,
            timestamp_ms: t.timestamp_ms,
            note_path: t.note_path,
        }
    }
}

#[derive(Serialize)]
pub struct CognitionThoughtJson {
    pub thought: Option<serde_json::Value>,
    pub chain: Vec<serde_json::Value>,
}

fn thought_detail_json(d: pb::CognitionThoughtDetail) -> serde_json::Value {
    serde_json::json!({
        "id": d.id,
        "thought_type": d.thought_type,
        "title": d.title,
        "summary": d.summary,
        "content": d.content,
        "salience": d.salience,
        "confidence": d.confidence,
        "novelty": d.novelty,
        "generation": d.generation,
        "timestamp_ms": d.timestamp_ms,
        "note_path": d.note_path,
        "status": d.status,
        "generator_model": d.generator_model,
        "tokens_used": d.tokens_used,
        "domains": d.domains,
        "thought_chain_id": d.thought_chain_id,
        "predecessor_id": d.predecessor_id,
    })
}

fn cognition_event_value(ev: &pb::CognitionEvent) -> serde_json::Value {
    let kind = pb::cognition_event::Type::try_from(ev.r#type)
        .map(|t| format!("{t:?}").to_lowercase())
        .unwrap_or_else(|_| "unknown".to_string());
    serde_json::json!({
        "type": kind,
        "timestamp_ms": ev.timestamp_ms,
        "thought_id": ev.thought_id,
        "thought_type": ev.thought_type,
        "title": ev.title,
        "summary": ev.summary,
        "salience": ev.salience,
        "generation": ev.generation,
        "cycle_id": ev.cycle_id,
        "thoughts_in_cycle": ev.thoughts_in_cycle,
        "error": ev.error,
    })
}
