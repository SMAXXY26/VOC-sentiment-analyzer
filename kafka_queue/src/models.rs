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
    /// Producer-side model routing hint: "big" (Qwen-7B) or "small" (1.5B draft).
    /// Optional + defaulted so it's backward-compatible — jobs written by an older
    /// producer deserialize as None and the analyzer falls back to its default model.
    /// No SCHEMA_VERSION bump needed (the consumer would otherwise DLT old jobs).
    #[serde(default)]
    pub target_model: Option<String>,
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

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_unix_now_reasonable() {
        let ts = unix_now();
        assert!(ts > 1_700_000_000, "timestamp predates 2023");
        assert!(ts < 2_000_000_000, "timestamp is implausibly far in future");
    }

    #[test]
    fn test_schema_version_default() {
        assert_eq!(default_schema_version(), SCHEMA_VERSION);
        assert_eq!(SCHEMA_VERSION, 1);
    }

    #[test]
    fn test_analysis_job_roundtrip() {
        let job = AnalysisJob {
            schema_version: SCHEMA_VERSION,
            feedback_id: "abc-123".into(),
            payload: FeedbackPayload {
                id: "abc-123".into(),
                text: "Great service".into(),
                source: "nps".into(),
                rating: Some(4.5),
                submitted_at: Some("2024-01-01T00:00:00Z".into()),
                metadata: json!({"region": "us-east"}),
            },
            enqueued_at: 1_700_000_000,
            target_model: Some("big".into()),
        };

        let serialized = serde_json::to_string(&job).unwrap();
        let got: AnalysisJob = serde_json::from_str(&serialized).unwrap();
        assert_eq!(got.target_model.as_deref(), Some("big"));

        assert_eq!(got.feedback_id, "abc-123");
        assert_eq!(got.schema_version, SCHEMA_VERSION);
        assert_eq!(got.payload.text, "Great service");
        assert_eq!(got.payload.rating, Some(4.5));
        assert_eq!(got.payload.metadata["region"], "us-east");
    }

    #[test]
    fn test_analysis_job_optional_fields_absent() {
        // schema_version absent in JSON — default must kick in
        let raw = r#"{
            "feedback_id": "xyz",
            "payload": {
                "id": "xyz",
                "text": "ok",
                "source": "csv",
                "rating": null,
                "submitted_at": null
            },
            "enqueued_at": 0
        }"#;

        let job: AnalysisJob = serde_json::from_str(raw).unwrap();
        assert_eq!(job.schema_version, SCHEMA_VERSION);
        assert!(job.payload.rating.is_none());
        assert!(job.payload.submitted_at.is_none());
    }

    #[test]
    fn test_dead_letter_message_roundtrip() {
        let dlt = DeadLetterMessage {
            feedback_id: "fail-1".into(),
            reason: "http_status_503".into(),
            original_payload: r#"{"text":"hello"}"#.into(),
            failed_at: 1_700_000_000,
        };

        let serialized = serde_json::to_string(&dlt).unwrap();
        let got: DeadLetterMessage = serde_json::from_str(&serialized).unwrap();

        assert_eq!(got.feedback_id, "fail-1");
        assert_eq!(got.reason, "http_status_503");
        assert_eq!(got.failed_at, 1_700_000_000);
    }

    #[test]
    fn test_analysis_result_roundtrip() {
        let result = AnalysisResult {
            schema_version: SCHEMA_VERSION,
            feedback_id: "r-1".into(),
            source: "typeform".into(),
            result: json!({"sentiment": "positive", "score": 0.9}),
            analyzed_at: 1_700_000_001,
        };

        let serialized = serde_json::to_string(&result).unwrap();
        let got: AnalysisResult = serde_json::from_str(&serialized).unwrap();

        assert_eq!(got.source, "typeform");
        assert_eq!(got.result["sentiment"], "positive");
        assert_eq!(got.analyzed_at, 1_700_000_001);
    }
}
