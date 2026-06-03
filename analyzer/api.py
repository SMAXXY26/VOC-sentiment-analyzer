import asyncio
import os
from collections import Counter
from typing import Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .main import analyze_single
from .schemas import FeedbackAnalysis

_API_KEY = os.getenv("API_KEY", "")
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_cors_origins = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()] or ["*"]

_EXEMPT_PATHS = {"/health", "/ready"}


async def _require_api_key(request: Request, x_api_key: str = Header(default="")):
    if _API_KEY and request.url.path not in _EXEMPT_PATHS and x_api_key != _API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


app = FastAPI(title="CX Semantic Analyzer API", dependencies=[Depends(_require_api_key)])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus scrape endpoint. Mounted as a sub-app so it bypasses the API-key
# dependency (Prometheus can't send the header); add "/metrics" to the exempt set
# for parity with /health and /ready.
from prometheus_client import make_asgi_app  # noqa: E402

_EXEMPT_PATHS.add("/metrics")
app.mount("/metrics", make_asgi_app())


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
    import os, httpx
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


@app.get("/analyses")
def list_analyses(limit: int = 50, offset: int = 0, q: Optional[str] = None):
    try:
        from vectordb.store import search
        from vectordb.client import get_client, ANALYSES_COLLECTION
        if q and q.strip():
            results = search(q.strip(), k=limit)
            return {"items": results, "total": len(results)}
        client = get_client()
        points, _ = client.scroll(
            collection_name=ANALYSES_COLLECTION,
            limit=limit,
            offset=offset,
            with_payload=True,
        )
        return {"items": [p.payload for p in points], "total": len(points)}
    except Exception as e:
        return {"items": [], "total": 0, "error": str(e)}


@app.get("/analyses/summary")
def analyses_summary():
    try:
        from vectordb.store import get_feature_history
        from vectordb.client import get_client, ANALYSES_COLLECTION
        client = get_client()
        all_points = []
        offset = None
        while True:
            batch, next_offset = client.scroll(
                collection_name=ANALYSES_COLLECTION,
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

        return {
            "total": len(all_points),
            "sentiment_distribution": dict(sentiments),
            "escalation_count": escalation_count,
            "churn_count": churn_count,
            "avg_intensity": round(sum(intensities) / len(intensities), 1) if intensities else 0,
            "top_categories": dict(categories.most_common(5)),
            "top_feature_requests": get_feature_history(k=20),
        }
    except Exception as e:
        return {"total": 0, "error": str(e)}


# ── Chatbot endpoints ──────────────────────────────────────────────────────────

class ChatStartRequest(BaseModel):
    customer_id: str = "guest"
    password: Optional[str] = None   # if provided, authenticate against EDBMS
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
    from .chatbot.agent import start_conversation, chat as agent_chat, get_quick_replies

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
    from .chatbot.agent import chat as agent_chat, get_quick_replies
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
        from vectordb.client import get_client, ANALYSES_COLLECTION
        from collections import Counter
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
    from analyzer.llm import get_healthy_endpoints, endpoint_count
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
        "ram_used_gb": round(mem.used / 1024 ** 3, 2),
        "ram_total_gb": round(mem.total / 1024 ** 3, 2),
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
        stats["gpu_used_mb"] = round(mem_info.used / 1024 ** 2)
        stats["gpu_total_mb"] = round(mem_info.total / 1024 ** 2)
        stats["gpu_util_percent"] = util.gpu
        pynvml.nvmlShutdown()
    except Exception:
        pass
    return stats
