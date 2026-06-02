//! Intelligent vLLM inference router.
//!
//! Replaces the analyzer's dumb client-side round-robin (analyzer/llm.py) with a
//! load-aware reverse proxy. It scrapes each backend's Prometheus `/metrics`
//! (`vllm:num_requests_running` + `vllm:num_requests_waiting`) and forwards each
//! request to the least-loaded *healthy* backend, so a slow/queued GPU stops
//! receiving traffic instead of getting its fair 1/N share regardless of load.
//!
//! The analyzer points VLLM_BASE_URL at this router; the request/response bodies
//! (including SSE streams) are proxied through unchanged.
//!
//! Env:
//!   VLLM_ENDPOINTS   comma-separated backend base URLs (with or without /v1)
//!   ROUTER_ADDR      proxy listen addr (default 0.0.0.0:8100)
//!   METRICS_ADDR     router's own Prometheus endpoint (default 0.0.0.0:9003)
//!   SCRAPE_INTERVAL_MS  backend metric poll interval (default 1000)

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use axum::{
    body::Body,
    extract::State,
    http::{HeaderMap, Method, StatusCode, Uri},
    response::Response,
    routing::get,
    Json, Router,
};
use futures_util::StreamExt;
use metrics::{counter, gauge};
use metrics_exporter_prometheus::PrometheusBuilder;
use tokio::sync::RwLock;
use tracing::{info, warn};

/// Live load snapshot for one backend.
#[derive(Clone, Copy)]
struct Load {
    running: f64,
    waiting: f64,
    healthy: bool,
    /// Exponentially-weighted moving average of (running + waiting).
    ewma: f64,
}

impl Default for Load {
    fn default() -> Self {
        Load {
            running: 0.0,
            waiting: 0.0,
            healthy: false,
            ewma: f64::MAX, // unknown backends sort last until first scrape
        }
    }
}

struct AppState {
    /// Backend base URLs, normalised to end with `/v1`.
    backends: Vec<String>,
    loads: RwLock<Vec<Load>>,
    rr: AtomicUsize, // round-robin fallback cursor when no load data
    client: reqwest::Client,
}

#[tokio::main]
async fn main() {
    dotenvy::dotenv().ok();
    tracing_subscriber::fmt()
        .with_env_filter(std::env::var("RUST_LOG").unwrap_or_else(|_| "info".into()))
        .init();

    let metrics_addr = std::env::var("METRICS_ADDR").unwrap_or_else(|_| "0.0.0.0:9003".into());
    let metrics_addr: std::net::SocketAddr = metrics_addr.parse().unwrap();
    PrometheusBuilder::new()
        .with_http_listener(metrics_addr)
        .install()
        .expect("Failed to install Prometheus recorder");
    info!("Router metrics on http://{metrics_addr}/metrics");

    let backends = parse_endpoints(&std::env::var("VLLM_ENDPOINTS").unwrap_or_default());
    if backends.is_empty() {
        panic!("VLLM_ENDPOINTS must list at least one backend URL");
    }
    info!(count = backends.len(), "Router backends: {:?}", backends);

    let loads = vec![Load::default(); backends.len()];
    let state = Arc::new(AppState {
        backends,
        loads: RwLock::new(loads),
        rr: AtomicUsize::new(0),
        client: reqwest::Client::builder()
            .timeout(Duration::from_secs(300))
            .build()
            .unwrap(),
    });

    spawn_scraper(Arc::clone(&state));

    let bind = std::env::var("ROUTER_ADDR").unwrap_or_else(|_| "0.0.0.0:8100".into());
    let app = Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/fleet", get(fleet_handler))
        .fallback(proxy_handler)
        .with_state(state);

    let listener = tokio::net::TcpListener::bind(&bind).await.unwrap();
    info!("Router proxy listening on {bind}");
    axum::serve(listener, app).await.unwrap();
}

/// Normalise a comma-separated endpoint list to backend bases ending in `/v1`.
fn parse_endpoints(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(|s| {
            let base = s.trim_end_matches('/');
            if base.ends_with("/v1") {
                base.to_string()
            } else {
                format!("{base}/v1")
            }
        })
        .collect()
}

/// Sum every Prometheus sample whose series name equals `name` (ignores labels).
fn sum_metric(body: &str, name: &str) -> Option<f64> {
    let mut total = 0.0;
    let mut found = false;
    for line in body.lines() {
        if line.starts_with('#') {
            continue;
        }
        if let Some(rest) = line.strip_prefix(name) {
            // Guard against prefix collisions (e.g. foo vs foo_bar): the char after
            // the name must start a label block or the value separator.
            if rest.starts_with('{') || rest.starts_with(' ') {
                if let Some(tok) = line.split_whitespace().last() {
                    if let Ok(v) = tok.parse::<f64>() {
                        total += v;
                        found = true;
                    }
                }
            }
        }
    }
    if found {
        Some(total)
    } else {
        None
    }
}

/// Pick the least-loaded healthy backend. Falls back to round-robin across all
/// backends when no backend is healthy/scraped yet, so the proxy never wedges.
fn pick_backend(loads: &[Load], rr: &AtomicUsize) -> usize {
    let best = loads
        .iter()
        .enumerate()
        .filter(|(_, l)| l.healthy)
        .min_by(|(_, a), (_, b)| a.ewma.total_cmp(&b.ewma))
        .map(|(i, _)| i);

    best.unwrap_or_else(|| rr.fetch_add(1, Ordering::Relaxed) % loads.len().max(1))
}

fn spawn_scraper(state: Arc<AppState>) {
    let interval_ms: u64 = std::env::var("SCRAPE_INTERVAL_MS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(1000);

    tokio::spawn(async move {
        let probe = reqwest::Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap();

        loop {
            for (i, base) in state.backends.iter().enumerate() {
                // /metrics lives at the server root, not under /v1.
                let root = base.trim_end_matches("/v1");
                let url = format!("{root}/metrics");

                let (running, waiting, healthy) = match probe.get(&url).send().await {
                    Ok(r) if r.status().is_success() => {
                        let body = r.text().await.unwrap_or_default();
                        let run = sum_metric(&body, "vllm:num_requests_running").unwrap_or(0.0);
                        let wait = sum_metric(&body, "vllm:num_requests_waiting").unwrap_or(0.0);
                        (run, wait, true)
                    }
                    _ => (0.0, 0.0, false),
                };

                let mut loads = state.loads.write().await;
                let l = &mut loads[i];
                l.running = running;
                l.waiting = waiting;
                l.healthy = healthy;
                let current = running + waiting;
                l.ewma = if l.ewma == f64::MAX {
                    current
                } else {
                    0.5 * current + 0.5 * l.ewma
                };
                if !healthy {
                    l.ewma = f64::MAX;
                    warn!(backend = %base, "vLLM backend unhealthy");
                }

                let labels = [("backend", base.clone())];
                gauge!("router_backend_running", &labels).set(running);
                gauge!("router_backend_waiting", &labels).set(waiting);
                gauge!("router_backend_healthy", &labels).set(healthy as i32 as f64);
            }

            tokio::time::sleep(Duration::from_millis(interval_ms)).await;
        }
    });
}

async fn fleet_handler(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let loads = state.loads.read().await;
    let backends: Vec<_> = state
        .backends
        .iter()
        .zip(loads.iter())
        .map(|(url, l)| {
            serde_json::json!({
                "endpoint": url,
                "running":  l.running,
                "waiting":  l.waiting,
                "healthy":  l.healthy,
                "ewma":     if l.ewma == f64::MAX { serde_json::Value::Null } else { l.ewma.into() },
            })
        })
        .collect();
    Json(serde_json::json!({ "backend_count": state.backends.len(), "backends": backends }))
}

/// Reverse-proxy any non-control request to the chosen backend, streaming the
/// response body back (so SSE token streams pass through unbuffered).
async fn proxy_handler(
    State(state): State<Arc<AppState>>,
    method: Method,
    uri: Uri,
    headers: HeaderMap,
    body: Body,
) -> Response {
    let idx = {
        let loads = state.loads.read().await;
        pick_backend(&loads, &state.rr)
    };
    let backend = &state.backends[idx];
    counter!("router_requests_routed_total", "backend" => backend.clone()).increment(1);

    // The analyzer/chatbot call paths like /v1/chat/completions; backends already
    // carry the /v1 base, so strip a leading /v1 from the incoming path to avoid /v1/v1.
    let path = uri.path();
    let path = path.strip_prefix("/v1").unwrap_or(path);
    let query = uri.query().map(|q| format!("?{q}")).unwrap_or_default();
    let target = format!("{backend}{path}{query}");

    let body_bytes = match axum::body::to_bytes(body, 16 * 1024 * 1024).await {
        Ok(b) => b,
        Err(_) => return error_response(StatusCode::BAD_REQUEST, "failed to read request body"),
    };

    let mut fwd_headers = headers.clone();
    fwd_headers.remove(axum::http::header::HOST);
    fwd_headers.remove(axum::http::header::CONTENT_LENGTH);

    let upstream = state
        .client
        .request(method, &target)
        .headers(fwd_headers)
        .body(body_bytes)
        .send()
        .await;

    match upstream {
        Ok(resp) => {
            let status = resp.status();
            let resp_headers = resp.headers().clone();
            let stream = resp
                .bytes_stream()
                .map(|chunk| chunk.map_err(std::io::Error::other));
            let mut builder = Response::builder().status(status);
            for (k, v) in resp_headers.iter() {
                // Hop-by-hop transfer-encoding would conflict with axum's framing.
                if k != axum::http::header::TRANSFER_ENCODING {
                    builder = builder.header(k, v);
                }
            }
            builder.body(Body::from_stream(stream)).unwrap()
        }
        Err(e) => {
            counter!("router_upstream_errors_total", "backend" => backend.clone()).increment(1);
            warn!(backend = %backend, "upstream error: {e}");
            error_response(
                StatusCode::BAD_GATEWAY,
                "upstream inference backend unreachable",
            )
        }
    }
}

fn error_response(status: StatusCode, msg: &str) -> Response {
    Response::builder()
        .status(status)
        .body(Body::from(msg.to_string()))
        .unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_endpoints_normalises_v1() {
        let eps = parse_endpoints("http://a:8000, http://b:8000/v1 ,");
        assert_eq!(eps, vec!["http://a:8000/v1", "http://b:8000/v1"]);
    }

    #[test]
    fn sum_metric_sums_label_series_and_ignores_comments() {
        let body = "# HELP foo\nvllm:num_requests_running{model=\"x\"} 2.0\nvllm:num_requests_running{model=\"y\"} 3.0\n";
        assert_eq!(sum_metric(body, "vllm:num_requests_running"), Some(5.0));
        assert_eq!(sum_metric(body, "vllm:num_requests_waiting"), None);
    }

    #[test]
    fn sum_metric_guards_prefix_collision() {
        let body = "vllm:num_requests_running_total 9\nvllm:num_requests_running 1\n";
        // Only the exact series counts, not the _total variant.
        assert_eq!(sum_metric(body, "vllm:num_requests_running"), Some(1.0));
    }

    #[test]
    fn pick_prefers_least_loaded_healthy() {
        let rr = AtomicUsize::new(0);
        let loads = vec![
            Load {
                running: 5.0,
                waiting: 1.0,
                healthy: true,
                ewma: 6.0,
            },
            Load {
                running: 1.0,
                waiting: 0.0,
                healthy: true,
                ewma: 1.0,
            },
            Load {
                running: 0.0,
                waiting: 0.0,
                healthy: false,
                ewma: 0.0,
            },
        ];
        assert_eq!(pick_backend(&loads, &rr), 1);
    }

    #[test]
    fn pick_falls_back_to_round_robin_when_none_healthy() {
        let rr = AtomicUsize::new(0);
        let loads = vec![Load::default(), Load::default()];
        let a = pick_backend(&loads, &rr);
        let b = pick_backend(&loads, &rr);
        assert_ne!(a, b); // round-robin advances
    }
}
