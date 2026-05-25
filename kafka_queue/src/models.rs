use serde::{Deserialize, Serialize};

pub const SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FeedbackPayload {
    pub id: String,
    pub text: String,
    pub source: String,
    pub rating: Option<f32>,
    pub submitted_at: Option<String>, // client-supplied, kept as string
    #[serde(default)]
    pub metadata: serde_json::Value,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AnalysisJob {
    /// Bumped when the schema changes — consumer rejects unknown versions to DLT.
    #[serde(default = "default_schema_version")]
    pub schema_version: u32,
    pub feedback_id: String,
    pub payload: FeedbackPayload,
    pub enqueued_at: u64, // epoch seconds
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AnalysisResult {
    pub schema_version: u32,
    pub feedback_id: String,
    pub source: String,
    pub result: serde_json::Value,
    pub analyzed_at: u64, // epoch seconds
}

#[derive(Debug, Serialize, Deserialize)]
pub struct QueueResponse {
    pub status: String,
    pub feedback_id: String,
    pub message: String,
}

/// Envelope sent to the dead-letter topic (feedback.failed).
#[derive(Debug, Serialize, Deserialize)]
pub struct DeadLetterMessage {
    pub feedback_id: String,
    pub reason: String,
    pub original_payload: String,
    pub failed_at: u64, // epoch seconds
}

fn default_schema_version() -> u32 {
    SCHEMA_VERSION
}

pub fn unix_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs()
}
