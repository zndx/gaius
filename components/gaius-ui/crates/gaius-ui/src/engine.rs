//! Lattice `zndx.engine.v1.Engine/Complete` — capability, not a model URL.

use thiserror::Error;
use tonic::transport::Channel;

pub mod pb {
    pub mod engine {
        pub mod v1 {
            tonic::include_proto!("zndx.engine.v1");
        }
    }
}

use pb::engine::v1::{engine_client::EngineClient, CompleteRequest};

#[derive(Debug, Error)]
pub enum EngineError {
    #[error("connect {0}")]
    Connect(#[from] tonic::transport::Error),
    #[error("rpc {0}")]
    Rpc(#[from] tonic::Status),
    #[error("{0}")]
    Message(String),
}

#[derive(Clone)]
pub struct Lattice {
    target: String,
    capability: String,
}

impl Lattice {
    pub fn from_env() -> Self {
        Self {
            target: std::env::var("GAIUS_ENGINE_TARGET")
                .unwrap_or_else(|_| "127.0.0.1:50051".into()),
            capability: std::env::var("GAIUS_THINKING_CAPABILITY")
                .unwrap_or_else(|_| "thinking".into()),
        }
    }

    pub fn target(&self) -> &str {
        &self.target
    }

    pub fn capability(&self) -> &str {
        &self.capability
    }

    pub async fn complete(
        &self,
        prompt: String,
        system_prompt: String,
        max_tokens: i32,
        temperature: f32,
    ) -> Result<CompleteOut, EngineError> {
        self.complete_as(
            self.capability.clone(),
            prompt,
            system_prompt,
            max_tokens,
            temperature,
            String::new(),
            String::new(),
        )
        .await
    }

    pub async fn complete_as(
        &self,
        capability: String,
        prompt: String,
        system_prompt: String,
        max_tokens: i32,
        temperature: f32,
        timezone: String,
        clock_json: String,
    ) -> Result<CompleteOut, EngineError> {
        let endpoint = format!("http://{}", self.target.trim());
        let ch = Channel::from_shared(endpoint)
            .map_err(|e| EngineError::Message(e.to_string()))?
            .connect()
            .await?;
        let mut c = EngineClient::new(ch);
        let r = c
            .complete(CompleteRequest {
                capability,
                prompt,
                system_prompt,
                max_tokens,
                temperature,
                json_schema: String::new(),
                timezone,
                clock_json,
            })
            .await?
            .into_inner();
        Ok(CompleteOut {
            text: r.text,
            reasoning: r.reasoning_content,
            model: r.model,
            prompt_tokens: r.prompt_tokens.max(0) as u32,
            completion_tokens: r.completion_tokens.max(0) as u32,
        })
    }
}

pub struct CompleteOut {
    pub text: String,
    pub reasoning: String,
    pub model: String,
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
}
