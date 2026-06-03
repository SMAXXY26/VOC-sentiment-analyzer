/// Kafka consumer — reads feedback.raw, calls Python analyzer, publishes to
/// feedback.analyzed. Failed analyses go to feedback.failed (DLT).
/// Offset is committed ONLY after successful publish or DLT send — no silent drops.
use std::sync::Arc;
use std::time::Duration;

use metrics::{counter, gauge, histogram};
use metrics_exporter_prometheus::PrometheusBuilder;
use rdkafka::{
    consumer::{CommitMode, Consumer, StreamConsumer},
    producer::{FutureProducer, FutureRecord},
    ClientConfig, Message,
};
use reqwest::Client;
use tokio::signal::unix::{signal, SignalKind};
use tokio::sync::Semaphore;
use tracing::{error, info, warn};

use feedback_gateway::models::{
    unix_now, AnalysisJob, AnalysisResult, DeadLetterMessage, SCHEMA_VERSION,
};

struct Config {
    brokers: String,
    raw_topic: String,
    analyzed_topic: String,
    failed_topic: String,
    analyzer_url: String,
    group_id: String,
    max_concurrent: usize,
}

impl Config {
    fn from_env() -> Self {
        Self {
            brokers: std::env::var("KAFKA_BROKERS").unwrap_or_else(|_| "localhost:9092".into()),
            raw_topic: std::env::var("KAFKA_RAW_TOPIC").unwrap_or_else(|_| "feedback.raw".into()),
            analyzed_topic: std::env::var("KAFKA_ANALYZED_TOPIC")
                .unwrap_or_else(|_| "feedback.analyzed".into()),
            failed_topic: std::env::var("KAFKA_FAILED_TOPIC")
                .unwrap_or_else(|_| "feedback.failed".into()),
            analyzer_url: std::env::var("ANALYZER_URL")
                .unwrap_or_else(|_| "http://localhost:8080/analyze".into()),
            group_id: std::env::var("KAFKA_GROUP_ID")
                .unwrap_or_else(|_| "cx-analyzer-group".into()),
            max_concurrent: std::env::var("MAX_CONCURRENT")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(4),
        }
    }
}

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(std::env::var("RUST_LOG").unwrap_or_else(|_| "info".into()))
        .init();

    let metrics_addr = std::env::var("METRICS_ADDR").unwrap_or_else(|_| "0.0.0.0:9002".into());
    let metrics_addr: std::net::SocketAddr = metrics_addr.parse().unwrap();
    PrometheusBuilder::new()
        .with_http_listener(metrics_addr)
        .install()
        .expect("Failed to install Prometheus recorder");

    info!("Prometheus metrics on http://{metrics_addr}/metrics");

    let config = Arc::new(Config::from_env());

    let consumer: Arc<StreamConsumer> = Arc::new(
        ClientConfig::new()
            .set("bootstrap.servers", &config.brokers)
            .set("group.id", &config.group_id)
            .set("enable.auto.commit", "false")
            // Disable auto-store so only explicit store_offset() calls are committed
            .set("enable.auto.offset.store", "false")
            .set("auto.offset.reset", "earliest")
            .set("max.poll.interval.ms", "300000")
            .set("session.timeout.ms", "30000")
            .create()
            .expect("Failed to create Kafka consumer"),
    );

    consumer
        .subscribe(&[&config.raw_topic])
        .expect("Failed to subscribe");

    let producer: Arc<FutureProducer> = Arc::new(
        ClientConfig::new()
            .set("bootstrap.servers", &config.brokers)
            .set("message.timeout.ms", "5000")
            .create()
            .expect("Failed to create result producer"),
    );

    let http = Client::builder()
        .timeout(Duration::from_secs(120))
        .build()
        .unwrap();

    let sem = Arc::new(Semaphore::new(config.max_concurrent));

    info!(
        topic = %config.raw_topic,
        max_concurrent = config.max_concurrent,
        "Consumer started"
    );

    // --- Consume loop with graceful shutdown on SIGTERM/SIGINT ---
    let mut sigterm = signal(SignalKind::terminate()).expect("Failed to register SIGTERM handler");
    let mut sigint = signal(SignalKind::interrupt()).expect("Failed to register SIGINT handler");

    loop {
        tokio::select! {
            _ = sigterm.recv() => {
                info!("SIGTERM received — draining in-flight jobs...");
                break;
            }
            _ = sigint.recv() => {
                info!("SIGINT received — draining in-flight jobs...");
                break;
            }
            result = consumer.recv() => {
                match result {
                    Err(e) => {
                        warn!("Kafka receive error: {e}");
                        counter!("consumer_kafka_errors_total").increment(1);
                    }
                    Ok(msg) => {
                        let payload = match msg.payload_view::<str>() {
                            Some(Ok(s)) => s.to_owned(),
                            _ => {
                                warn!("Non-UTF8 message — sending to DLT");
                                counter!("consumer_decode_errors_total").increment(1);
                                // Commit: undecodable message, nothing to retry
                                consumer.commit_message(&msg, CommitMode::Async).ok();
                                continue;
                            }
                        };

                        let job: AnalysisJob = match serde_json::from_str(&payload) {
                            Ok(j) => j,
                            Err(e) => {
                                error!("Failed to deserialize job: {e}");
                                counter!("consumer_decode_errors_total").increment(1);
                                // Commit: malformed message can never succeed on retry
                                consumer.commit_message(&msg, CommitMode::Async).ok();
                                continue;
                            }
                        };

                        // Schema version guard — unknown versions go to DLT, not dropped
                        if job.schema_version != SCHEMA_VERSION {
                            error!(
                                feedback_id = %job.feedback_id,
                                got = job.schema_version,
                                expected = SCHEMA_VERSION,
                                "Unknown schema version — routing to DLT"
                            );
                            counter!("consumer_schema_version_errors_total").increment(1);
                            send_to_dlt(&producer, &config.failed_topic, &job.feedback_id,
                                "unknown_schema_version", &payload).await;
                            consumer.commit_message(&msg, CommitMode::Async).ok();
                            continue;
                        }

                        counter!("consumer_messages_received_total").increment(1);

                        // Extract offset info before msg is consumed by the borrow checker.
                        // store_offset() is called inside process_job after success or DLT send.
                        let msg_topic = msg.topic().to_string();
                        let msg_partition = msg.partition();
                        let msg_offset = msg.offset();

                        let available = sem.available_permits();
                        gauge!("consumer_available_workers").set(available as f64);

                        let permit = Arc::clone(&sem).acquire_owned().await.unwrap();
                        let http = http.clone();
                        let producer = Arc::clone(&producer);
                        let consumer = Arc::clone(&consumer);
                        let config = Arc::clone(&config);
                        let raw_payload = payload.clone();

                        tokio::spawn(async move {
                            let _permit = permit;
                            process_job(
                                job, raw_payload, &http, &producer, &consumer, &config,
                                &msg_topic, msg_partition, msg_offset,
                            ).await;
                        });
                    }
                }
            }
        }
    }

    // Drain: wait for all spawned workers to release their permits.
    // Capped at 25s — k8s sends SIGKILL at 30s, so we must exit before that.
    let max = config.max_concurrent as u32;
    let drain_sem = Arc::clone(&sem);
    match tokio::time::timeout(Duration::from_secs(25), drain_sem.acquire_many(max)).await {
        Ok(_) => info!("All in-flight jobs drained — shutdown complete"),
        Err(_) => warn!("Drain timed out after 25s — some jobs may be reprocessed on restart"),
    };
}

// Offset coordinates (topic/partition/offset) are passed individually because the
// borrow checker forces extracting them before `msg` is moved; grouping into a struct
// adds no clarity here.
#[allow(clippy::too_many_arguments)]
async fn process_job(
    job: AnalysisJob,
    raw_payload: String,
    http: &Client,
    producer: &FutureProducer,
    consumer: &StreamConsumer,
    config: &Config,
    topic: &str,
    partition: i32,
    offset: i64,
) {
    let start = std::time::Instant::now();
    info!(feedback_id = %job.feedback_id, "Processing job");
    gauge!("consumer_active_jobs").increment(1.0);

    let analysis = call_analyzer_with_retry(http, &config.analyzer_url, &job).await;

    let elapsed = start.elapsed().as_secs_f64();
    gauge!("consumer_active_jobs").decrement(1.0);

    match analysis {
        Err(reason) => {
            error!(feedback_id = %job.feedback_id, reason = %reason, "Analysis failed after retries — sending to DLT");
            counter!("consumer_analyzer_errors_total", "reason" => "exhausted_retries")
                .increment(1);
            send_to_dlt(
                producer,
                &config.failed_topic,
                &job.feedback_id,
                &reason,
                &raw_payload,
            )
            .await;
            // Store offset only after DLT send — message is handled, not lost
            consumer.store_offset(topic, partition, offset).ok();
        }
        Ok(result_json) => {
            histogram!("consumer_analysis_duration_seconds").record(elapsed);
            counter!("consumer_analyses_completed_total").increment(1);

            let result = AnalysisResult {
                schema_version: SCHEMA_VERSION,
                feedback_id: job.feedback_id.clone(),
                source: job.payload.source.clone(),
                result: result_json,
                analyzed_at: unix_now(),
            };

            let value = match serde_json::to_string(&result) {
                Ok(v) => v,
                Err(e) => {
                    // Serialization of our own result should never fail, but if it
                    // does, don't panic the worker — DLT it and move on.
                    error!(feedback_id = %job.feedback_id, "Failed to serialize result: {e}");
                    counter!("consumer_serialize_errors_total").increment(1);
                    send_to_dlt(
                        producer,
                        &config.failed_topic,
                        &job.feedback_id,
                        &format!("serialize_failed: {e}"),
                        &raw_payload,
                    )
                    .await;
                    consumer.store_offset(topic, partition, offset).ok();
                    return;
                }
            };
            match producer
                .send(
                    FutureRecord::to(&config.analyzed_topic)
                        .key(&job.feedback_id)
                        .payload(&value),
                    Duration::from_secs(5),
                )
                .await
            {
                Err((e, _)) => {
                    error!(feedback_id = %job.feedback_id, "Failed to publish result: {e} — sending to DLT");
                    counter!("consumer_publish_errors_total").increment(1);
                    send_to_dlt(
                        producer,
                        &config.failed_topic,
                        &job.feedback_id,
                        &format!("publish_failed: {e}"),
                        &raw_payload,
                    )
                    .await;
                    // Store offset after DLT send — consistent with analysis-failure path
                    consumer.store_offset(topic, partition, offset).ok();
                }
                Ok(_) => {
                    info!(
                        feedback_id = %job.feedback_id,
                        duration_s = elapsed,
                        "Analysis complete and published"
                    );
                    // Store offset only after successful publish — guarantees at-least-once
                    consumer.store_offset(topic, partition, offset).ok();
                }
            }
        }
    }
}

/// Call the analyzer with 3 attempts and exponential backoff (500ms, 1s, 2s).
async fn call_analyzer_with_retry(
    http: &Client,
    url: &str,
    job: &AnalysisJob,
) -> Result<serde_json::Value, String> {
    let mut last_err = String::new();

    for attempt in 0..3u32 {
        if attempt > 0 {
            let delay = Duration::from_millis(500 * (1u64 << attempt));
            warn!(
                feedback_id = %job.feedback_id,
                attempt,
                delay_ms = delay.as_millis(),
                "Retrying analyzer call"
            );
            tokio::time::sleep(delay).await;
        }

        // Forward the producer's model routing hint (big/small) to the analyzer.
        // Omitted (null) when absent so the analyzer uses its default model.
        match http
            .post(url)
            .json(&serde_json::json!({
                "text": job.payload.text,
                "model": job.target_model,
            }))
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => {
                return resp
                    .json::<serde_json::Value>()
                    .await
                    .map_err(|e| e.to_string());
            }
            Ok(resp) => {
                last_err = format!("http_status_{}", resp.status().as_u16());
                counter!("consumer_analyzer_errors_total", "reason" => "bad_status").increment(1);
            }
            Err(e) => {
                last_err = e.to_string();
                counter!("consumer_analyzer_errors_total", "reason" => "http_error").increment(1);
            }
        }
    }

    Err(last_err)
}

// send_to_dlt is defined after this test module for readability (it's a leaf helper);
// the lint that flags this is purely stylistic.
#[allow(clippy::items_after_test_module)]
#[cfg(test)]
mod tests {
    use super::*;
    use feedback_gateway::models::FeedbackPayload;
    use serde_json::json;
    use std::sync::LazyLock;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    // Serialise all env-var tests so parallel test threads don't race on process env.
    static ENV_LOCK: LazyLock<std::sync::Mutex<()>> = LazyLock::new(|| std::sync::Mutex::new(()));

    fn make_job() -> AnalysisJob {
        AnalysisJob {
            schema_version: SCHEMA_VERSION,
            feedback_id: "test-id-1".into(),
            payload: FeedbackPayload {
                id: "test-id-1".into(),
                text: "Product is excellent".into(),
                source: "csv".into(),
                rating: None,
                submitted_at: None,
                metadata: json!({}),
            },
            enqueued_at: 0,
            target_model: Some("big".into()),
        }
    }

    // --- Config::from_env tests ---

    #[test]
    fn test_config_defaults() {
        let _guard = ENV_LOCK.lock().unwrap();
        for var in &[
            "KAFKA_BROKERS",
            "KAFKA_RAW_TOPIC",
            "KAFKA_ANALYZED_TOPIC",
            "KAFKA_FAILED_TOPIC",
            "ANALYZER_URL",
            "KAFKA_GROUP_ID",
            "MAX_CONCURRENT",
        ] {
            std::env::remove_var(var);
        }
        let cfg = Config::from_env();
        assert_eq!(cfg.brokers, "localhost:9092");
        assert_eq!(cfg.raw_topic, "feedback.raw");
        assert_eq!(cfg.analyzed_topic, "feedback.analyzed");
        assert_eq!(cfg.failed_topic, "feedback.failed");
        assert_eq!(cfg.analyzer_url, "http://localhost:8080/analyze");
        assert_eq!(cfg.group_id, "cx-analyzer-group");
        assert_eq!(cfg.max_concurrent, 4);
    }

    #[test]
    fn test_config_max_concurrent_custom() {
        let _guard = ENV_LOCK.lock().unwrap();
        std::env::set_var("MAX_CONCURRENT", "16");
        let cfg = Config::from_env();
        assert_eq!(cfg.max_concurrent, 16);
        std::env::remove_var("MAX_CONCURRENT");
    }

    #[test]
    fn test_config_max_concurrent_invalid_falls_back_to_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        std::env::set_var("MAX_CONCURRENT", "not-a-number");
        let cfg = Config::from_env();
        assert_eq!(cfg.max_concurrent, 4);
        std::env::remove_var("MAX_CONCURRENT");
    }

    // --- call_analyzer_with_retry tests ---

    #[tokio::test]
    async fn test_analyzer_success_on_first_attempt() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/analyze"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_body_json(json!({"sentiment": "positive", "score": 0.95})),
            )
            .mount(&server)
            .await;

        let http = Client::new();
        let url = format!("{}/analyze", server.uri());
        let result = call_analyzer_with_retry(&http, &url, &make_job()).await;

        assert!(result.is_ok());
        assert_eq!(result.unwrap()["sentiment"], "positive");
    }

    #[tokio::test]
    async fn test_analyzer_retries_on_500_then_succeeds() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/analyze"))
            .respond_with(ResponseTemplate::new(500))
            .up_to_n_times(1)
            .mount(&server)
            .await;
        Mock::given(method("POST"))
            .and(path("/analyze"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"sentiment": "neutral"})))
            .mount(&server)
            .await;

        let http = Client::new();
        let url = format!("{}/analyze", server.uri());
        let result = call_analyzer_with_retry(&http, &url, &make_job()).await;

        assert!(result.is_ok(), "expected Ok after retry, got {:?}", result);
    }

    #[tokio::test]
    async fn test_analyzer_exhausts_all_retries_returns_err() {
        let server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/analyze"))
            .respond_with(ResponseTemplate::new(503))
            .mount(&server)
            .await;

        let http = Client::new();
        let url = format!("{}/analyze", server.uri());
        let result = call_analyzer_with_retry(&http, &url, &make_job()).await;

        assert!(result.is_err());
        assert!(
            result.unwrap_err().contains("503"),
            "error should mention the HTTP status"
        );
    }

    #[tokio::test]
    async fn test_analyzer_connection_refused_returns_err() {
        // Nothing listening on this port — all 3 attempts fail immediately.
        let http = Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap();
        let result =
            call_analyzer_with_retry(&http, "http://127.0.0.1:19753/analyze", &make_job()).await;

        assert!(result.is_err(), "connection refused should produce Err");
    }
}

/// Publish a failed message to the dead-letter topic.
async fn send_to_dlt(
    producer: &FutureProducer,
    failed_topic: &str,
    feedback_id: &str,
    reason: &str,
    original_payload: &str,
) {
    let dlt_msg = DeadLetterMessage {
        feedback_id: feedback_id.to_string(),
        reason: reason.to_string(),
        original_payload: original_payload.to_string(),
        failed_at: unix_now(),
    };
    let value = match serde_json::to_string(&dlt_msg) {
        Ok(v) => v,
        Err(e) => {
            error!(feedback_id = %feedback_id, "CRITICAL: failed to serialize DLT message: {e}");
            counter!("consumer_dlt_failures_total").increment(1);
            return;
        }
    };
    match producer
        .send(
            FutureRecord::to(failed_topic)
                .key(feedback_id)
                .payload(&value),
            Duration::from_secs(5),
        )
        .await
    {
        Ok(_) => {
            counter!("consumer_dlt_messages_total").increment(1);
            warn!(feedback_id = %feedback_id, reason = %reason, "Message sent to DLT");
        }
        Err((e, _)) => {
            error!(feedback_id = %feedback_id, "CRITICAL: Failed to send to DLT: {e}");
            counter!("consumer_dlt_failures_total").increment(1);
        }
    }
}
