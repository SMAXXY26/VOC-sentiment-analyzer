/// HTTP gateway — accepts feedback, publishes to Kafka, exposes Prometheus metrics.
use std::sync::Arc;
use std::time::Duration;

use axum::{
    extract::State,
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use metrics::{counter, histogram};
use metrics_exporter_prometheus::PrometheusBuilder;
use rdkafka::{
    producer::{FutureProducer, FutureRecord},
    ClientConfig,
};
use tower::limit::ConcurrencyLimitLayer;
use tower_http::{limit::RequestBodyLimitLayer, trace::TraceLayer};
use tracing::info;
use uuid::Uuid;

use feedback_gateway::models::{unix_now, AnalysisJob, FeedbackPayload, QueueResponse, SCHEMA_VERSION};

struct AppState {
    producer: FutureProducer,
    topic: String,
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

    let state = Arc::new(AppState { producer, topic });

    let app = Router::new()
        .route("/health", get(health))
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

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({"status": "ok"}))
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
    let job = AnalysisJob {
        schema_version: SCHEMA_VERSION,
        feedback_id: feedback_id.clone(),
        payload,
        enqueued_at: unix_now(),
    };

    publish(&state, &job).await.map_err(|e| {
        counter!("producer_errors_total", "reason" => "kafka_publish").increment(1);
        e
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
        let job = AnalysisJob {
            schema_version: SCHEMA_VERSION,
            feedback_id: feedback_id.clone(),
            payload,
            enqueued_at: unix_now(),
        };
        publish(&state, &job).await.map_err(|e| {
            counter!("producer_errors_total", "reason" => "kafka_publish").increment(1);
            e
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
    let value = serde_json::to_string(job).unwrap();
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
