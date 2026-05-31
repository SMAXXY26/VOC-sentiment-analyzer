"""
Agentic review workflow.

A LangGraph ReAct agent that autonomously:
  1. Fetches the current review queue (low-confidence items)
  2. Checks for semantic drift alerts
  3. Summarises recent escalations
  4. Produces a structured ReviewReport with prioritised action items

The agent is triggered via POST /review/run and runs to completion (no streaming).
Reports are stored in the `review_reports` Qdrant collection.

Tools available to the agent:
  - fetch_review_queue  : get pending low-confidence items
  - fetch_drift_status  : run / fetch latest drift snapshot
  - fetch_escalations   : recent high/critical risk items
  - summarise_findings  : LLM call to synthesise a final report paragraph

The final output is a ReviewReport Pydantic model serialised to JSON.
"""
from __future__ import annotations

import time
import uuid
from functools import lru_cache
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from analyzer.llm import get_llm

# ── Pydantic report schema ────────────────────────────────────────────────────

class ReviewReport(BaseModel):
    generated_at: float = Field(default_factory=time.time)
    pending_reviews: int = 0
    drift_detected: bool = False
    escalation_count: int = 0
    summary: str = ""
    action_items: list[str] = Field(default_factory=list)
    risk_level: str = "low"   # low | medium | high | critical


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def fetch_review_queue() -> str:
    """Fetch items in the active learning review queue that need human attention."""
    try:
        from analyzer.active_learning import get_queue
        items = get_queue(limit=20)
        if not items:
            return "Review queue is empty."
        lines = [
            f"- [{i.get('pipeline_confidence', '?'):.2f}] {i.get('summary','')[:100]} "
            f"(category={i.get('current_category','?')}, sentiment={i.get('current_sentiment','?')})"
            for i in items[:10]
        ]
        return f"{len(items)} pending items:\n" + "\n".join(lines)
    except Exception as e:
        return f"error: {e}"


@tool
def fetch_drift_status() -> str:
    """Check semantic drift — whether recent feedback topics or sentiment have shifted from baseline."""
    try:
        from analyzer.drift import compute_drift
        r = compute_drift()
        if "error" in r:
            return r["error"]
        alerts = []
        if r.get("centroid_alert"):
            alerts.append(f"topic drift (cosine distance={r['centroid_distance']:.3f})")
        if r.get("sentiment_alert"):
            alerts.append(f"sentiment shift ({r['sentiment_shift']*100:.1f}pp more negative)")
        if r.get("category_alert"):
            alerts.append(f"category distribution shift (KL={r['category_kl']:.3f})")
        if not alerts:
            return f"No drift detected. Recent={r['recent_n']} items, baseline={r['baseline_n']} items."
        return "DRIFT DETECTED: " + "; ".join(alerts)
    except Exception as e:
        return f"error: {e}"


@tool
def fetch_escalations() -> str:
    """Fetch recent high/critical risk escalations from the feedback database."""
    try:
        from vectordb.store import get_escalation_precedents
        items = get_escalation_precedents(k=10)
        if not items:
            return "No escalated feedback found."
        lines = [
            f"- [{i.get('risk_level','?')}] {i.get('summary','')[:100]} → {i.get('suggested_action','')[:80]}"
            for i in items[:8]
        ]
        return f"{len(items)} escalated items:\n" + "\n".join(lines)
    except Exception as e:
        return f"error: {e}"


REVIEW_TOOLS = [fetch_review_queue, fetch_drift_status, fetch_escalations]

_SYSTEM = (
    "You are a CX review agent. Use all three tools once, then write a concise structured report. "
    "Format your final response as JSON with keys: summary (str), action_items (list[str]), "
    "risk_level (low|medium|high|critical). Be specific and actionable."
)

# ── Graph ─────────────────────────────────────────────────────────────────────

def _merge(a: list, b: list) -> list:
    return a + b


class ReviewState(TypedDict):
    messages: Annotated[list[BaseMessage], _merge]


@lru_cache(maxsize=1)
def _get_review_graph():
    llm = get_llm(temperature=0.2).bind_tools(REVIEW_TOOLS).bind(max_tokens=300)
    tool_node = ToolNode(REVIEW_TOOLS)

    def agent_node(state: ReviewState) -> dict:
        return {"messages": [llm.invoke(state["messages"])]}

    def should_continue(state: ReviewState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    g = StateGraph(ReviewState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tool_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


# ── Report storage ────────────────────────────────────────────────────────────

_REPORTS_COLLECTION = "review_reports"


def _ensure_reports_collection(client) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if _REPORTS_COLLECTION not in existing:
        from qdrant_client.models import VectorParams, Distance
        from vectordb.embedder import VECTOR_SIZE
        client.create_collection(
            collection_name=_REPORTS_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def _store_report(report: ReviewReport) -> None:
    try:
        from qdrant_client.models import PointStruct
        from vectordb.client import get_client
        from vectordb.embedder import embed
        client = get_client()
        _ensure_reports_collection(client)
        client.upsert(
            collection_name=_REPORTS_COLLECTION,
            points=[PointStruct(
                id=str(uuid.uuid4()),
                vector=embed(report.summary or "review report"),
                payload=report.model_dump(),
            )],
        )
    except Exception:
        pass


# ── Public API ─────────────────────────────────────────────────────────────────

def run_review() -> ReviewReport:
    """
    Trigger the agentic review workflow.
    Calls all three tools, synthesises findings, stores report, returns ReviewReport.
    """
    graph = _get_review_graph()
    result = graph.invoke({
        "messages": [SystemMessage(content=_SYSTEM)]
    })

    # Extract final AI response
    raw = ""
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            raw = msg.content or ""
            break

    # Parse JSON from agent output
    report = ReviewReport()
    try:
        import json, re
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            report = ReviewReport(
                summary=parsed.get("summary", raw[:300]),
                action_items=parsed.get("action_items", []),
                risk_level=parsed.get("risk_level", "low"),
            )
        else:
            report.summary = raw[:400]
    except Exception:
        report.summary = raw[:400]

    _store_report(report)
    return report


def get_reports(limit: int = 20) -> list[dict]:
    """Fetch stored review reports, newest first."""
    try:
        from vectordb.client import get_client
        client = get_client()
        _ensure_reports_collection(client)
        results, _ = client.scroll(
            collection_name=_REPORTS_COLLECTION,
            limit=limit,
            with_payload=True,
        )
        payloads = [p.payload for p in results]
        payloads.sort(key=lambda p: p.get("generated_at", 0), reverse=True)
        return payloads
    except Exception:
        return []
