/// HTTP gateway — accepts feedback, publishes to Kafka, exposes Prometheus metrics.
use std::sync::Arc;
use std::time::Duration;

use axum::{
    extract::State,
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use metrics::{counter, gauge, histogram};
use metrics_exporter_prometheus::PrometheusBuilder;
use rdkafka::{
    producer::{FutureProducer, FutureRecord},
    ClientConfig,
};
use tokio::sync::RwLock;
use tower::limit::ConcurrencyLimitLayer;
use tower_http::{limit::RequestBodyLimitLayer, trace::TraceLayer};
use tracing::{info, warn};
use uuid::Uuid;

use feedback_gateway::models::{
    unix_now, AnalysisJob, FeedbackPayload, QueueResponse, SCHEMA_VERSION,
};

mod routing {
    //! Cheap keyword pre-tag — a zero-latency, zero-dependency HINT attached at the
    //! gateway so the Kafka message carries a default tier. It is NOT the authority:
    //! the analyzer makes the real decision with a 1.5B model-based router
    //! (analyzer/routing.py::resolve_model_tier), which reads intent rather than
    //! surface words (e.g. "I'm fine, just want to cancel" → complex, no trigger word).
    //! This keyword set mirrors analyzer/chatbot/cascade_llm.py::_COMPLEX_SIGNALS and is
    //! kept in sync by tests/test_hardening.py::test_classifier_keyword_parity. The
    //! analyzer falls back to this same logic only when the draft model is unavailable.

    /// Keywords signalling the query likely needs the full 7B model's reasoning.
    const COMPLEX_SIGNALS: &[&str] = &[
        "why",
        "explain",
        "issue",
        "complaint",
        "escalate",
        "broken",
        "damaged",
        "refund",
        "wrong",
        "missing",
        "urgent",
        "angry",
        "terrible",
        "worst",
        "disappointed",
        "frustrated",
        "lost",
        "never",
        "impossible",
        "unacceptable",
        "legal",
        "manager",
        "lawsuit",
        "charged",
        "overcharged",
        "fraud",
    ];

    /// "big" for complex/emotional or long text, "small" otherwise.
    pub fn classify(text: &str) -> &'static str {
        let lower = text.to_lowercase();
        let words: Vec<&str> = lower.split_whitespace().collect();
        let has_signal = words.iter().any(|w| COMPLEX_SIGNALS.contains(w));
        if words.len() > 20 || has_signal {
            "big"
        } else {
            "small"
        }
    }
}

/// Health snapshot of the inference fleet, refreshed by a background task.
#[derive(Clone, Default)]
struct FleetHealth {
    analyzer_ok: bool,
    big_ok: bool,   // Qwen-7B vLLM endpoint
    small_ok: bool, // 1.5B draft endpoint
    checked_at: u64,
}

struct AppState {
    producer: FutureProducer,
    topic: String,
    health: Arc<RwLock<FleetHealth>>,
    /// If the classifier picks "small" but the draft endpoint is down, fall back to "big".
    draft_configured: bool,
}

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(std::env::var("RUST_LOG").unwrap_or_else(|_| "info".into()))
        .init();

    let metrics_addr = std::env::var("METRICS_ADDR").unwrap_or_else(|_| "0.0.0.0:9001".into());
    let metrics_addr: std::net::SocketAddr = metrics_addr.parse().unwrap();
    PrometheusBuilder::new()
        .with_http_listener(metrics_addr)
        .install()
        .expect("Failed to install Prometheus recorder");

    info!("Prometheus metrics on http://{metrics_addr}/metrics");

    let brokers = std::env::var("KAFKA_BROKERS").unwrap_or_else(|_| "localhost:9092".into());
    let topic = std::env::var("KAFKA_RAW_TOPIC").unwrap_or_else(|_| "feedback.raw".into());
    let bind = std::env::var("PRODUCER_ADDR").unwrap_or_else(|_| "0.0.0.0:3001".into());
    // Concurrency limit — caps simultaneous in-flight requests to prevent Kafka topic DoS.
    // tower::RateLimitLayer is not Clone-safe with axum; ConcurrencyLimitLayer uses Arc<Semaphore>.
    let max_in_flight: usize = std::env::var("MAX_IN_FLIGHT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(100);

    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", &brokers)
        .set("message.timeout.ms", "5000")
        .set("queue.buffering.max.ms", "10")
        .set("queue.buffering.max.messages", "100000")
        .set("compression.type", "lz4")
        .create()
        .expect("Failed to create Kafka producer");

    info!("Producer connected to Kafka at {brokers}");

    // Inference-fleet health checks (HTTP probes — no k8s API / RBAC needed).
    let analyzer_health = std::env::var("ANALYZER_HEALTH_URL")
        .unwrap_or_else(|_| "http://analyzer:8080/ready".into());
    let big_health =
        std::env::var("VLLM_HEALTH_URL").unwrap_or_else(|_| "http://vllm:8000/health".into());
    let draft_url = std::env::var("DRAFT_LLM_URL").unwrap_or_default();
    let draft_configured = !draft_url.trim().is_empty();
    let small_health = if draft_configured {
        Some(format!(
            "{}/health",
            draft_url.trim_end_matches('/').trim_end_matches("/v1")
        ))
    } else {
        None
    };

    let health = Arc::new(RwLock::new(FleetHealth::default()));
    spawn_health_checker(
        Arc::clone(&health),
        analyzer_health,
        big_health,
        small_health,
    );

    let state = Arc::new(AppState {
        producer,
        topic,
        health,
        draft_configured,
    });

    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/fleet", get(fleet_handler))
        .route("/feedback", post(submit_feedback))
        .route("/feedback/batch", post(submit_batch))
        .layer(TraceLayer::new_for_http())
        .layer(RequestBodyLimitLayer::new(1024 * 1024))
        // Rate limit: configurable RPS (default 100 req/s) — prevents Kafka topic DoS
        .layer(ConcurrencyLimitLayer::new(max_in_flight))
        .with_state(state);

    let listener = tokio::net::TcpListener::bind(&bind).await.unwrap();
    info!("Producer HTTP server listening on {bind} (max in-flight: {max_in_flight})");

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .unwrap();

    info!("Producer shutdown complete");
}

/// Resolves on SIGTERM or SIGINT — axum drains in-flight requests automatically.
async fn shutdown_signal() {
    use tokio::signal::unix::{signal, SignalKind};
    let mut sigterm = signal(SignalKind::terminate()).expect("Failed to register SIGTERM handler");
    let mut sigint = signal(SignalKind::interrupt()).expect("Failed to register SIGINT handler");
    tokio::select! {
        _ = sigterm.recv() => info!("SIGTERM received"),
        _ = sigint.recv() => info!("SIGINT received"),
    }
}

async fn health_handler() -> Json<serde_json::Value> {
    Json(serde_json::json!({"status": "ok"}))
}

/// Report the last fleet-health snapshot (analyzer + both inference endpoints).
async fn fleet_handler(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let h = state.health.read().await;
    Json(serde_json::json!({
        "analyzer_ok": h.analyzer_ok,
        "big_ok":      h.big_ok,
        "small_ok":    h.small_ok,
        "checked_at":  h.checked_at,
    }))
}

/// Pick the target model for a piece of text, applying a health-aware fallback:
/// "small" downgrades to "big" when the draft endpoint is absent or unhealthy.
async fn choose_model(state: &AppState, text: &str) -> &'static str {
    let mut model = routing::classify(text);
    if model == "small" {
        let small_up = state.draft_configured && state.health.read().await.small_ok;
        if !small_up {
            model = "big";
            counter!("producer_model_fallback_total", "from" => "small", "to" => "big")
                .increment(1);
        }
    }
    counter!("producer_model_routed_total", "model" => model).increment(1);
    model
}

/// Background task: probe analyzer + inference endpoints every 5s and update the
/// shared FleetHealth snapshot + Prometheus gauges. Never panics — a down endpoint
/// just flips its flag to false.
fn spawn_health_checker(
    health: Arc<RwLock<FleetHealth>>,
    analyzer_url: String,
    big_url: String,
    small_url: Option<String>,
) {
    tokio::spawn(async move {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .expect("failed to build health-check client");

        async fn probe(client: &reqwest::Client, url: &str) -> bool {
            matches!(client.get(url).send().await, Ok(r) if r.status().is_success())
        }

        loop {
            let analyzer_ok = probe(&client, &analyzer_url).await;
            let big_ok = probe(&client, &big_url).await;
            let small_ok = match &small_url {
                Some(u) => probe(&client, u).await,
                None => false,
            };

            gauge!("producer_fleet_healthy", "component" => "analyzer")
                .set(analyzer_ok as i32 as f64);
            gauge!("producer_fleet_healthy", "component" => "big").set(big_ok as i32 as f64);
            gauge!("producer_fleet_healthy", "component" => "small").set(small_ok as i32 as f64);

            if !big_ok {
                warn!("Big (Qwen-7B) inference endpoint is unhealthy");
            }

            {
                let mut h = health.write().await;
                h.analyzer_ok = analyzer_ok;
                h.big_ok = big_ok;
                h.small_ok = small_ok;
                h.checked_at = unix_now();
            }

            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    });
}

async fn submit_feedback(
    State(state): State<Arc<AppState>>,
    Json(mut payload): Json<FeedbackPayload>,
) -> Result<Json<QueueResponse>, (StatusCode, String)> {
    let start = std::time::Instant::now();
    counter!("producer_requests_total", "endpoint" => "single").increment(1);

    if payload.text.trim().is_empty() {
        counter!("producer_errors_total", "reason" => "empty_text").increment(1);
        return Err((StatusCode::BAD_REQUEST, "text field is required".into()));
    }

    if payload.id.is_empty() {
        payload.id = Uuid::new_v4().to_string();
    }

    let feedback_id = payload.id.clone();
    let target_model = choose_model(&state, &payload.text).await;
    let job = AnalysisJob {
        schema_version: SCHEMA_VERSION,
        feedback_id: feedback_id.clone(),
        payload,
        enqueued_at: unix_now(),
        target_model: Some(target_model.to_string()),
    };

    publish(&state, &job).await.inspect_err(|_| {
        counter!("producer_errors_total", "reason" => "kafka_publish").increment(1);
    })?;

    counter!("producer_feedback_queued_total").increment(1);
    histogram!("producer_publish_duration_seconds").record(start.elapsed().as_secs_f64());

    info!(feedback_id = %feedback_id, "Queued feedback");
    Ok(Json(QueueResponse {
        status: "queued".into(),
        feedback_id,
        message: "Feedback accepted for analysis".into(),
    }))
}

async fn submit_batch(
    State(state): State<Arc<AppState>>,
    Json(payloads): Json<Vec<FeedbackPayload>>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let start = std::time::Instant::now();
    counter!("producer_requests_total", "endpoint" => "batch").increment(1);

    if payloads.is_empty() {
        counter!("producer_errors_total", "reason" => "empty_batch").increment(1);
        return Err((StatusCode::BAD_REQUEST, "batch cannot be empty".into()));
    }
    if payloads.len() > 500 {
        counter!("producer_errors_total", "reason" => "batch_too_large").increment(1);
        return Err((StatusCode::BAD_REQUEST, "batch limit is 500 items".into()));
    }

    let batch_size = payloads.len();
    let mut ids = Vec::with_capacity(batch_size);

    for mut payload in payloads {
        if payload.id.is_empty() {
            payload.id = Uuid::new_v4().to_string();
        }
        let feedback_id = payload.id.clone();
        let target_model = choose_model(&state, &payload.text).await;
        let job = AnalysisJob {
            schema_version: SCHEMA_VERSION,
            feedback_id: feedback_id.clone(),
            payload,
            enqueued_at: unix_now(),
            target_model: Some(target_model.to_string()),
        };
        publish(&state, &job).await.inspect_err(|_| {
            counter!("producer_errors_total", "reason" => "kafka_publish").increment(1);
        })?;
        ids.push(feedback_id);
    }

    counter!("producer_feedback_queued_total").increment(batch_size as u64);
    histogram!("producer_batch_size").record(batch_size as f64);
    histogram!("producer_publish_duration_seconds").record(start.elapsed().as_secs_f64());

    info!(count = ids.len(), "Queued feedback batch");
    Ok(Json(serde_json::json!({
        "status": "queued",
        "count": ids.len(),
        "feedback_ids": ids,
    })))
}

async fn publish(state: &AppState, job: &AnalysisJob) -> Result<(), (StatusCode, String)> {
    // Don't panic the request handler if serialization ever fails — surface a 500.
    let value = serde_json::to_string(job).map_err(|e| {
        counter!("producer_errors_total", "reason" => "serialize").increment(1);
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("failed to serialize job: {e}"),
        )
    })?;
    state
        .producer
        .send(
            FutureRecord::to(&state.topic)
                .key(&job.feedback_id)
                .payload(&value),
            Duration::from_secs(5),
        )
        .await
        .map_err(|(e, _)| {
            (
                StatusCode::SERVICE_UNAVAILABLE,
                format!("Kafka publish failed: {e}"),
            )
        })?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::routing::classify;

    #[test]
    fn short_neutral_text_routes_small() {
        assert_eq!(classify("great service thanks"), "small");
    }

    #[test]
    fn complex_signal_routes_big() {
        assert_eq!(classify("I want a refund now"), "big");
        assert_eq!(classify("this is unacceptable"), "big");
    }

    #[test]
    fn long_text_routes_big_even_without_signal() {
        let long = "word ".repeat(25);
        assert_eq!(classify(&long), "big");
    }

    #[test]
    fn classification_is_case_insensitive() {
        assert_eq!(classify("REFUND please"), "big");
    }
}
