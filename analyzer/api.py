import asyncio
import os
import re
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .main import analyze_single
from .schemas import FeedbackAnalysis

_API_KEY = os.getenv("API_KEY", "")
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_cors_origins = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()] or ["*"]

# Auth is enforced when a service API key is configured, or AUTH_REQUIRED is set
# (so dashboard-token-only deployments can require login without a shared key).
_AUTH_ENABLED = bool(_API_KEY) or os.getenv("AUTH_REQUIRED", "").lower() in ("1", "true", "yes")

_EXEMPT_PATHS = {"/health", "/ready", "/auth/login"}

# Common English stopwords + filler terms, excluded from the dashboard word cloud
# so it surfaces meaningful feedback vocabulary rather than "the", "and", etc.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
_STOPWORDS = frozenset(
    """
a an and the of to in is it for on with this that was were be been being have has had
do does did but or if so as at by from we you they he she them his her our your my me
i not no yes can will just get got would could should there here what when which who how
am are isnt arent dont doesnt didnt im ive id ill us about into out up down over under
than then too very really also more most some any all only even much many lot really
""".split()
)


def _tokenize_words(text: str) -> list[str]:
    """Lowercased content words from a blob of feedback text, stopwords removed."""
    return [w for w in (m.group(0).lower() for m in _WORD_RE.finditer(text)) if w not in _STOPWORDS]


async def _require_api_key(
    request: Request,
    x_api_key: str = Header(default=""),
    authorization: str = Header(default=""),
):
    """Allow the request if auth is disabled, the path is exempt, the static service
    key matches, OR a valid dashboard bearer token is presented."""
    if not _AUTH_ENABLED or request.url.path in _EXEMPT_PATHS:
        return
    if _API_KEY and x_api_key == _API_KEY:
        return
    if authorization.startswith("Bearer "):
        from .auth import verify_token

        if verify_token(authorization[7:]):
            return
    raise HTTPException(status_code=401, detail="Authentication required")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Drain the Kafka store-retry topic in the background so analyses that failed to
    # reach Qdrant (while it was down) get persisted once it recovers. No-op unless
    # KAFKA_BROKERS is set and kafka-python is installed.
    try:
        from .store_retry import start_retry_consumer

        start_retry_consumer()
    except Exception:
        pass
    yield


app = FastAPI(
    title="CX Semantic Analyzer API",
    dependencies=[Depends(_require_api_key)],
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus scrape endpoint. Served as an explicit route (not app.mount, which
# would make the real path "/metrics/" and answer "/metrics" with a 307 redirect —
# Prometheus doesn't follow redirects on scrape, so it would silently get nothing).
# Exempt from the API-key dependency so Prometheus can scrape without a header.
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # noqa: E402

_EXEMPT_PATHS.add("/metrics")


@app.get("/metrics")
def metrics():
    from fastapi import Response

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ── Dashboard auth ───────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
async def auth_login(req: LoginRequest):
    """Verify operator credentials (SQLite) and issue a signed bearer token."""
    from .auth import issue_token, verify_credentials

    user = await asyncio.to_thread(verify_credentials, req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {**issue_token(user["username"]), "role": user["role"]}


@app.get("/auth/me")
async def auth_me(authorization: str = Header(default="")):
    """Validate the current bearer token (used by the dashboard to check its session)."""
    from .auth import verify_token

    username = verify_token(authorization[7:]) if authorization.startswith("Bearer ") else None
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": username}


class AnalyzeRequest(BaseModel):
    text: str
    feedback_id: Optional[str] = None
    model: Optional[str] = None  # producer routing hint: "big" | "small"


@app.get("/health")
def health():
    """Liveness probe — always 200 if the process is alive."""
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """Readiness probe — checks Qdrant and vLLM are reachable.
    Returns 503 if any dependency is down so k8s stops routing traffic.
    """
    import os

    import httpx

    checks: dict = {}
    healthy = True

    # Probe Qdrant
    try:
        from vectordb.client import get_client

        await asyncio.to_thread(get_client().get_collections)
        checks["qdrant"] = "ok"
    except Exception as e:
        checks["qdrant"] = f"error: {e}"
        healthy = False

    # Probe vLLM
    try:
        base = os.getenv("VLLM_BASE_URL", "http://vllm:8000/v1").removesuffix("/v1")
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{base}/health", timeout=2.0)
        checks["vllm"] = "ok" if r.status_code == 200 else f"error: http {r.status_code}"
        if r.status_code != 200:
            healthy = False
    except Exception as e:
        checks["vllm"] = f"error: {e}"
        healthy = False

    status_code = 200 if healthy else 503
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if healthy else "degraded", **checks},
    )


@app.post("/analyze", response_model=FeedbackAnalysis)
async def analyze(req: AnalyzeRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    # Run CPU-bound pipeline in a thread so the async event loop isn't blocked
    return await asyncio.to_thread(analyze_single, req.text, req.feedback_id, req.model)


# Seed/backfill data is tagged with this payload `source` and hidden from the dashboard
# views (/analyses, /analyses/summary) while still feeding dedup/RAG/clustering/drift.
SEED_SOURCE = os.getenv("SEED_SOURCE", "hf_seed")


def _exclude_seed_filter():
    """A Qdrant scroll filter that drops seed-tagged points (None if seeding disabled)."""
    if not SEED_SOURCE:
        return None
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(must_not=[FieldCondition(key="source", match=MatchValue(value=SEED_SOURCE))])


# Higher = more urgent. Items are sorted by this descending so escalations and
# high-risk/churn feedback surface first in the dashboard list.
_RISK_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def _priority_key(item: dict):
    risk = _RISK_RANK.get(str(item.get("risk_level", "")).lower(), 0)
    return (risk, 1 if item.get("escalate") else 0, 1 if item.get("churn_risk") else 0)


def _by_priority(items: list[dict]) -> list[dict]:
    """Sort highest-priority first; stable, so semantic/scroll order breaks ties."""
    return sorted(items, key=_priority_key, reverse=True)


def _analyses_filter(
    category: Optional[str] = None,
    sentiment: Optional[str] = None,
    risk_level: Optional[str] = None,
    escalate: Optional[bool] = None,
    churn_risk: Optional[bool] = None,
):
    """Build a Qdrant filter combining the search-bar payload filters (AND) with the
    seed-exclusion rule. Returns None when nothing needs filtering."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    must = []
    if category:
        must.append(FieldCondition(key="category", match=MatchValue(value=category)))
    if sentiment:
        must.append(FieldCondition(key="sentiment", match=MatchValue(value=sentiment)))
    if risk_level:
        must.append(FieldCondition(key="risk_level", match=MatchValue(value=risk_level)))
    if escalate is not None:
        must.append(FieldCondition(key="escalate", match=MatchValue(value=escalate)))
    if churn_risk is not None:
        must.append(FieldCondition(key="churn_risk", match=MatchValue(value=churn_risk)))

    must_not = []
    if SEED_SOURCE:
        must_not.append(FieldCondition(key="source", match=MatchValue(value=SEED_SOURCE)))

    if not must and not must_not:
        return None
    return Filter(must=must or None, must_not=must_not or None)


@app.get("/analyses")
def list_analyses(
    limit: int = 50,
    offset: int = 0,
    q: Optional[str] = None,
    category: Optional[str] = None,
    sentiment: Optional[str] = None,
    risk_level: Optional[str] = None,
    escalate: Optional[bool] = None,
    churn_risk: Optional[bool] = None,
):
    try:
        from vectordb.client import ANALYSES_COLLECTION, get_client
        from vectordb.store import search

        qfilter = _analyses_filter(category, sentiment, risk_level, escalate, churn_risk)

        if q and q.strip():
            # Filters (incl. seed-exclusion) applied server-side so they don't consume
            # the top-k slots (filtering after the search left real results starved).
            results = search(q.strip(), k=limit, query_filter=qfilter)
            return {"items": _by_priority(results), "total": len(results)}
        client = get_client()
        points, _ = client.scroll(
            collection_name=ANALYSES_COLLECTION,
            scroll_filter=qfilter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )
        items = _by_priority([p.payload for p in points])
        return {"items": items, "total": len(items)}
    except Exception as e:
        return {"items": [], "total": 0, "error": str(e)}


@app.get("/analyses/summary")
def analyses_summary():
    try:
        from vectordb.client import ANALYSES_COLLECTION, get_client

        client = get_client()
        all_points = []
        offset = None
        seed_filter = _exclude_seed_filter()
        while True:
            batch, next_offset = client.scroll(
                collection_name=ANALYSES_COLLECTION,
                scroll_filter=seed_filter,
                limit=250,
                offset=offset,
                with_payload=True,
            )
            all_points.extend(batch)
            if next_offset is None:
                break
            offset = next_offset

        sentiments = Counter(p.payload.get("sentiment") for p in all_points)
        categories = Counter(p.payload.get("category") for p in all_points)
        intensities = [p.payload.get("intensity", 0) for p in all_points if p.payload.get("intensity")]
        escalation_count = sum(1 for p in all_points if p.payload.get("escalate"))
        churn_count = sum(1 for p in all_points if p.payload.get("churn_risk"))

        # Customer Satisfaction / Experience indices — average the per-item percentages.
        # Older points without these fields are simply excluded from the mean.
        csi_scores = [p.payload["csi_score"] for p in all_points if p.payload.get("csi_score") is not None]
        cxi_scores = [p.payload["cxi_score"] for p in all_points if p.payload.get("cxi_score") is not None]

        # Aggregate feature requests from the SAME filtered points (not a separate
        # unfiltered scan) so seed-derived features don't leak onto the dashboard.
        feature_counts: Counter = Counter()
        for p in all_points:
            for feat in p.payload.get("feature_requests") or []:
                feature_counts[feat] += 1

        # Feedback volume per calendar day (UTC), bucketed from the stored_at epoch.
        # Points predating the stored_at field are simply skipped. Returned sorted
        # by date ascending so the dashboard bar chart reads left-to-right.
        day_counts: Counter = Counter()
        for p in all_points:
            ts = p.payload.get("stored_at")
            if ts is None:
                continue
            day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            day_counts[day] += 1
        daily_counts = {d: day_counts[d] for d in sorted(day_counts)}

        # Word-frequency cloud — tokenize the actual feedback text (falling back to
        # the summary) so the cloud shows the most-used words across all feedback.
        word_counts: Counter = Counter()
        for p in all_points:
            text = p.payload.get("raw_text") or p.payload.get("summary") or ""
            word_counts.update(_tokenize_words(text))

        return {
            "total": len(all_points),
            "sentiment_distribution": dict(sentiments),
            "escalation_count": escalation_count,
            "churn_count": churn_count,
            "avg_intensity": round(sum(intensities) / len(intensities), 1) if intensities else 0,
            "avg_csi": round(sum(csi_scores) / len(csi_scores), 1) if csi_scores else 0,
            "avg_cxi": round(sum(cxi_scores) / len(cxi_scores), 1) if cxi_scores else 0,
            "top_categories": dict(categories.most_common(5)),
            "top_feature_requests": [f for f, _ in feature_counts.most_common(20)],
            # phrase -> frequency (kept for the feature-request list/badges)
            "feature_request_counts": dict(feature_counts.most_common(40)),
            # word -> frequency, for the word cloud (most-used words across feedback)
            "word_frequencies": dict(word_counts.most_common(60)),
            # "YYYY-MM-DD" -> count, for the date-wise volume bar chart
            "daily_counts": daily_counts,
        }
    except Exception as e:
        return {"total": 0, "error": str(e)}


# ── Chatbot endpoints ──────────────────────────────────────────────────────────


class ChatStartRequest(BaseModel):
    customer_id: str = "guest"
    password: Optional[str] = None  # if provided, authenticate against EDBMS
    message: Optional[str] = None


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    quick_replies: list[str] = []
    customer_name: Optional[str] = None
    customer_tier: Optional[str] = None


@app.post("/chat", response_model=ChatResponse)
async def chat_start(req: ChatStartRequest):
    """SOC: start a new support session. Authenticates against EDBMS if password is provided."""
    from .chatbot.agent import chat as agent_chat
    from .chatbot.agent import get_quick_replies, start_conversation

    customer: dict | str = req.customer_id
    if req.password:
        from .chatbot.edbms import authenticate

        result = await asyncio.to_thread(authenticate, req.customer_id, req.password)
        if result is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Invalid username or password")
        customer = result

    session_id = await asyncio.to_thread(start_conversation, customer)
    reply = ""
    if req.message and req.message.strip():
        reply = await asyncio.to_thread(agent_chat, session_id, req.message.strip())
    quick_replies = await asyncio.to_thread(get_quick_replies, session_id)

    cust_dict = customer if isinstance(customer, dict) else {}
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        quick_replies=quick_replies,
        customer_name=cust_dict.get("name"),
        customer_tier=cust_dict.get("tier"),
    )


@app.post("/chat/{session_id}", response_model=ChatResponse)
async def chat_continue(session_id: str, req: ChatRequest):
    """Continue an existing support session."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    from .chatbot.agent import chat as agent_chat
    from .chatbot.agent import get_quick_replies

    reply = await asyncio.to_thread(agent_chat, session_id, req.message.strip())
    quick_replies = await asyncio.to_thread(get_quick_replies, session_id)
    return ChatResponse(session_id=session_id, reply=reply, quick_replies=quick_replies)


@app.delete("/chat/{session_id}")
async def chat_end(session_id: str):
    """EOC: end the session, summarise and store to Qdrant."""
    from .chatbot.agent import end_conversation

    summary = await asyncio.to_thread(end_conversation, session_id)
    return {"session_id": session_id, "summary": summary}


@app.get("/chat/{session_id}/history")
async def chat_history(session_id: str):
    """Return the message history for an active session."""
    from .chatbot.agent import get_history

    history = get_history(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="session not found or expired")
    return {"session_id": session_id, "messages": history}


# ── Embedding / vector search ──────────────────────────────────────────────────


@app.get("/search")
async def embedding_search(
    q: str,
    k: int = 10,
    category: Optional[str] = None,
    sentiment: Optional[str] = None,
    risk_level: Optional[str] = None,
    escalate: Optional[bool] = None,
    churn_risk: Optional[bool] = None,
    min_intensity: Optional[int] = None,
):
    """Filtered semantic search over stored feedback embeddings."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required")
    from vectordb.retrieval import filtered_search

    return await asyncio.to_thread(
        filtered_search, q, k, category, sentiment, risk_level, escalate, churn_risk, min_intensity
    )


# ── Topic clustering ───────────────────────────────────────────────────────────


@app.post("/cluster")
async def cluster_topics(n_clusters: Optional[int] = None):
    """
    Run KMeans topic clustering over all stored feedback embeddings.
    Auto-selects k via silhouette score if n_clusters is omitted.
    Writes cluster_id + cluster_label back to each Qdrant point.
    """
    from analyzer.clustering import run_clustering

    return await asyncio.to_thread(run_clustering, n_clusters)


@app.get("/clusters")
async def get_clusters():
    """Return cluster labels from the most recent clustering run (reads from Qdrant payloads)."""
    try:
        from vectordb.client import ANALYSES_COLLECTION, get_client

        client = get_client()
        results, _ = client.scroll(
            collection_name=ANALYSES_COLLECTION,
            limit=5000,
            with_payload=True,
        )
        labelled = [p.payload for p in results if p.payload.get("cluster_id") is not None]
        if not labelled:
            return {"clusters": [], "note": "No clustering run yet — POST /cluster to run."}
        by_cluster: dict = {}
        for p in labelled:
            cid = p["cluster_id"]
            if cid not in by_cluster:
                by_cluster[cid] = {"id": cid, "label": p.get("cluster_label", ""), "size": 0}
            by_cluster[cid]["size"] += 1
        clusters = sorted(by_cluster.values(), key=lambda c: c["size"], reverse=True)
        return {"clusters": clusters, "total_labelled": len(labelled)}
    except Exception as e:
        return {"clusters": [], "error": str(e)}


# ── Semantic drift ─────────────────────────────────────────────────────────────


@app.get("/drift")
async def drift_report(recent_days: int = 7, baseline_days: int = 30):
    """Compute semantic drift between recent and baseline feedback windows."""
    from analyzer.drift import compute_drift

    return await asyncio.to_thread(compute_drift, recent_days, baseline_days)


@app.get("/drift/history")
async def drift_history(limit: int = 30):
    """Fetch stored drift snapshots, newest first."""
    from analyzer.drift import get_drift_history

    return await asyncio.to_thread(get_drift_history, limit)


# ── Active learning / review queue ────────────────────────────────────────────


@app.get("/review/queue")
async def review_queue(limit: int = 50):
    """Get pending low-confidence items sorted by confidence ascending (least confident first)."""
    from analyzer.active_learning import get_queue

    return await asyncio.to_thread(get_queue, limit)


@app.get("/review/stats")
async def review_stats():
    """Count of pending / reviewed / skipped items in the review queue."""
    from analyzer.active_learning import queue_stats

    return await asyncio.to_thread(queue_stats)


class CorrectionRequest(BaseModel):
    corrected_category: Optional[str] = None
    corrected_subcategory: Optional[str] = None
    corrected_sentiment: Optional[str] = None
    reviewer_note: str = ""


@app.post("/review/{feedback_id}")
async def submit_correction(feedback_id: str, req: CorrectionRequest):
    """
    Submit a human correction for a queued item.
    Updates the stored analysis and adds the corrected item to few_shot_examples.
    """
    from analyzer.active_learning import submit_correction as _submit

    return await asyncio.to_thread(
        _submit,
        feedback_id,
        req.corrected_category,
        req.corrected_subcategory,
        req.corrected_sentiment,
        req.reviewer_note,
    )


# ── Agentic review workflow ────────────────────────────────────────────────────


@app.post("/review/run")
async def run_review_agent():
    """
    Trigger the agentic review workflow. The agent fetches queue, drift, and escalations,
    then synthesises a ReviewReport with action items and risk level.
    """
    from analyzer.review_agent import run_review

    report = await asyncio.to_thread(run_review)
    return report.model_dump()


@app.get("/review/reports")
async def get_review_reports(limit: int = 20):
    """Fetch stored agentic review reports, newest first."""
    from analyzer.review_agent import get_reports

    return await asyncio.to_thread(get_reports, limit)


# ── Distributed inference status ──────────────────────────────────────────────


@app.get("/inference/endpoints")
async def inference_endpoints():
    """Health-check all configured vLLM inference endpoints."""
    from analyzer.llm import endpoint_count, get_healthy_endpoints

    return {
        "endpoint_count": endpoint_count(),
        "endpoints": await asyncio.to_thread(get_healthy_endpoints),
    }


# ── System stats ───────────────────────────────────────────────────────────────


@app.get("/system")
def system_stats():
    import psutil

    mem = psutil.virtual_memory()
    stats = {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "ram_used_gb": round(mem.used / 1024**3, 2),
        "ram_total_gb": round(mem.total / 1024**3, 2),
        "ram_percent": mem.percent,
        "gpu_used_mb": None,
        "gpu_total_mb": None,
        "gpu_util_percent": None,
    }
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        stats["gpu_used_mb"] = round(mem_info.used / 1024**2)
        stats["gpu_total_mb"] = round(mem_info.total / 1024**2)
        stats["gpu_util_percent"] = util.gpu
        pynvml.nvmlShutdown()
    except Exception:
        pass
    return stats
