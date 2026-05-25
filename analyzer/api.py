import asyncio
from collections import Counter
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .main import analyze_single
from .schemas import FeedbackAnalysis

app = FastAPI(title="CX Semantic Analyzer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    text: str
    feedback_id: Optional[str] = None


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
    return await asyncio.to_thread(analyze_single, req.text, req.feedback_id)


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
