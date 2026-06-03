//! Dead-letter drain / redrive tool.
//!
//! feedback.failed used to be write-only — messages landed there and nobody ever read
//! them, so a burst of failures was a silent black hole. This binary gives the DLT a
//! reader:
//!
//!   - default (observe): drain feedback.failed, log every message and tally by reason,
//!     then exit. Turns the black hole into something you can actually see.
//!   - --redrive: additionally re-publish *transient* failures (exhausted_retries,
//!     publish_failed, serialize_failed) back to feedback.raw for reprocessing.
//!     Permanent failures (unknown_schema_version, decode) are never auto-replayed —
//!     they'd just fail again — only logged so an operator can inspect them.
//!
//! Drain-and-exit by design: it's meant to run as a CronJob (k8s/dlt-replay/), so a
//! message that fails again only gets another chance on the next run — no tight loop.
//! Pairs with the DLT alert rules in monitoring/alerts.yml.

use std::time::Duration;

use rdkafka::{
    consumer::{CommitMode, Consumer, StreamConsumer},
    producer::{FutureProducer, FutureRecord},
    ClientConfig, Message,
};
use tracing::{info, warn};

use feedback_gateway::models::{AnalysisJob, DeadLetterMessage};

/// Failure reasons safe to retry (infra blips), vs permanent (bad data).
fn is_transient(reason: &str) -> bool {
    reason.starts_with("exhausted_retries")
        || reason.starts_with("publish_failed")
        || reason.starts_with("serialize_failed")
}

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(std::env::var("RUST_LOG").unwrap_or_else(|_| "info".into()))
        .init();

    let redrive = std::env::args().any(|a| a == "--redrive")
        || std::env::var("REDRIVE").map(|v| v == "1").unwrap_or(false);
    let idle_secs: u64 = std::env::var("DLT_IDLE_TIMEOUT_SECS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(5);

    let brokers = std::env::var("KAFKA_BROKERS").unwrap_or_else(|_| "localhost:9092".into());
    let failed_topic =
        std::env::var("KAFKA_FAILED_TOPIC").unwrap_or_else(|_| "feedback.failed".into());
    let raw_topic = std::env::var("KAFKA_RAW_TOPIC").unwrap_or_else(|_| "feedback.raw".into());
    let group_id = std::env::var("DLT_GROUP_ID").unwrap_or_else(|_| "dlt-replay".into());

    let consumer: StreamConsumer = ClientConfig::new()
        .set("bootstrap.servers", &brokers)
        .set("group.id", &group_id)
        .set("enable.auto.commit", "false")
        .set("auto.offset.reset", "earliest")
        .create()
        .expect("Failed to create DLT consumer");
    consumer
        .subscribe(&[&failed_topic])
        .expect("Failed to subscribe to DLT");

    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", &brokers)
        .set("message.timeout.ms", "5000")
        .create()
        .expect("Failed to create redrive producer");

    info!(
        topic = %failed_topic, redrive, idle_secs,
        "DLT drain started (exits after {idle_secs}s idle)"
    );

    let (mut seen, mut redriven, mut skipped) = (0u64, 0u64, 0u64);

    loop {
        match tokio::time::timeout(Duration::from_secs(idle_secs), consumer.recv()).await {
            Err(_) => {
                info!("No more DLT messages — draining complete");
                break;
            }
            Ok(Err(e)) => {
                warn!("DLT receive error: {e}");
                break;
            }
            Ok(Ok(msg)) => {
                seen += 1;
                let payload = msg.payload_view::<str>().and_then(|r| r.ok()).unwrap_or("");
                let dlt: Option<DeadLetterMessage> = serde_json::from_str(payload).ok();

                match dlt {
                    None => {
                        warn!("Undecodable DLT envelope — skipping");
                        skipped += 1;
                    }
                    Some(d) => {
                        if redrive && is_transient(&d.reason) {
                            // Re-publish the original job so it flows through analysis again.
                            if serde_json::from_str::<AnalysisJob>(&d.original_payload).is_ok() {
                                let _ = producer
                                    .send(
                                        FutureRecord::to(&raw_topic)
                                            .key(&d.feedback_id)
                                            .payload(&d.original_payload),
                                        Duration::from_secs(5),
                                    )
                                    .await;
                                redriven += 1;
                                info!(feedback_id = %d.feedback_id, reason = %d.reason, "Redriven → feedback.raw");
                            } else {
                                warn!(feedback_id = %d.feedback_id, "Original payload not a valid job — skipping");
                                skipped += 1;
                            }
                        } else {
                            // Observe-only, or a permanent failure we won't auto-replay.
                            info!(feedback_id = %d.feedback_id, reason = %d.reason, transient = is_transient(&d.reason), "DLT message");
                            skipped += 1;
                        }
                    }
                }
                consumer.commit_message(&msg, CommitMode::Async).ok();
            }
        }
    }

    info!(seen, redriven, skipped, "DLT drain summary");
}

#[cfg(test)]
mod tests {
    use super::is_transient;

    #[test]
    fn transient_reasons_are_retryable() {
        assert!(is_transient("exhausted_retries"));
        assert!(is_transient("publish_failed: broker down"));
        assert!(is_transient("serialize_failed: ..."));
    }

    #[test]
    fn permanent_reasons_are_not_retried() {
        assert!(!is_transient("unknown_schema_version"));
        assert!(!is_transient("decode_error"));
        assert!(!is_transient("something_else"));
    }
}
