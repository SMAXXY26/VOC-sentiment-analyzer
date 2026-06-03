"""Customer support chatbot agent.

Graph:
    START → agent_node → should_continue ─┬→ tools_node → agent_node (loop)
                                           └→ END

SOC (start_conversation): authenticates customer via EDBMS, creates session.
chat():                   routes query to draft (1.5B) or target (7B) LLM,
                          runs one user turn with tool access.
EOC (end_conversation):   stores conversation summary to Qdrant, cleans up session.

Token budget (max_model_len=1024):
  system ~70 | tools ~220 | history ≤250 | tool results ≤280 chars | response ≤170
"""

from __future__ import annotations

import os
import time
import uuid
from functools import lru_cache
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from .cascade_llm import get_chat_llm
from .memory import ConversationMemory
from .tools import _CURRENT_CUSTOMER, TOOLS, reset_tool_budget

# Cap on agent_node↔tools loop iterations per turn. LangGraph counts each node hop,
# so N covers roughly N/2 tool rounds — enough for a multi-tool answer, but it stops
# a model that loops forever calling tools. Configurable via env.
_RECURSION_LIMIT = int(os.getenv("CHATBOT_RECURSION_LIMIT", "8"))

_SYSTEM = (
    "You are a helpful, empathetic customer support assistant. "
    "You have access to the customer's purchase history and account details via tools. "
    "When a customer mentions a product issue, call lookup_purchase_context with keywords first. "
    "For general questions use get_faq_answer. For anything you can't find, try web_search. "
    "Never guess order details — always call a tool first. "
    "When you cannot resolve an issue, call escalate_to_human. "
    "Be concise and friendly. Keep responses under 3 sentences."
)

_INITIAL_QUICK_REPLIES = [
    "Show my recent orders",
    "I have a product issue",
    "Request a refund",
    "Track my delivery",
    "Account information",
]


# ── LangGraph state ────────────────────────────────────────────────────────────


def _merge_messages(a: list, b: list) -> list:
    return a + b


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], _merge_messages]


# ── Graph ──────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _get_graph():
    """Build the ReAct graph once. LLM is selected dynamically inside agent_node."""
    tool_node = ToolNode(TOOLS)

    def agent_node(state: AgentState) -> dict:
        # Find last human message to classify query complexity for model routing
        last_user = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                last_user = str(msg.content)
                break
        llm = get_chat_llm(last_user, temperature=0.3).bind_tools(TOOLS).bind(max_tokens=170)
        return {"messages": [llm.invoke(state["messages"])]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tool_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


# ── Session store ──────────────────────────────────────────────────────────────

_sessions: dict[str, dict] = {}
_SESSION_TTL = 3600


def _evict_expired() -> None:
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s["ts"] > _SESSION_TTL]
    for sid in expired:
        del _sessions[sid]


# ── SOC ────────────────────────────────────────────────────────────────────────


def start_conversation(customer: dict | str = "guest") -> str:
    """SOC — create a new session. Accepts either an authenticated customer dict
    (from edbms.authenticate) or a plain customer_id string for anonymous sessions.
    """
    _evict_expired()
    session_id = str(uuid.uuid4())
    memory = ConversationMemory()

    if isinstance(customer, str):
        customer_dict = {"id": None, "username": customer, "name": customer, "tier": "guest"}
    else:
        customer_dict = customer

    # Pre-load a short context summary so first response has account info
    try:
        if customer_dict.get("id"):
            from .edbms import get_recent_purchases

            orders = get_recent_purchases(customer_dict["id"])
            if orders:
                recent = "; ".join(
                    f"{o['order_ref']} {o['product']} ({o['status']})" + (f" [{o['issue']}]" if o.get("issue") else "")
                    for o in orders[:3]
                )
                memory.summary = f"Customer {customer_dict['name']} ({customer_dict['tier']}). Recent: {recent}"
    except Exception:
        pass

    _sessions[session_id] = {
        "memory": memory,
        "customer": customer_dict,
        "ts": time.time(),
    }
    return session_id


def get_quick_replies(session_id: str) -> list[str]:
    if session_id not in _sessions:
        return _INITIAL_QUICK_REPLIES
    memory: ConversationMemory = _sessions[session_id]["memory"]
    return _INITIAL_QUICK_REPLIES if memory.turn_count() == 0 else []


# ── Chat ───────────────────────────────────────────────────────────────────────


def chat(session_id: str, user_message: str) -> str:
    """Process one user turn. Sets _CURRENT_CUSTOMER for the duration of the call."""
    if session_id not in _sessions:
        session_id = start_conversation()

    session = _sessions[session_id]
    memory: ConversationMemory = session["memory"]
    customer: dict = session.get("customer", {})
    session["ts"] = time.time()

    token = _CURRENT_CUSTOMER.set(customer)
    reset_tool_budget()  # fresh per-turn tool-call budget (caps web_search etc.)
    try:
        memory.add("user", user_message)
        messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM)]
        messages += memory.to_langchain_messages()

        # recursion_limit bounds the agent↔tools loop; on overrun LangGraph raises
        # GraphRecursionError, which we turn into a graceful escalation message.
        try:
            result = _get_graph().invoke(
                {"messages": messages},
                config={"recursion_limit": _RECURSION_LIMIT},
            )
            reply = "I'm sorry, I couldn't process that. Please try again."
            for msg in reversed(result["messages"]):
                if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                    reply = str(msg.content) or reply
                    break
        except Exception:
            reply = (
                "I'm having trouble resolving this automatically. Let me connect you with a human agent who can help."
            )

        memory.add("assistant", reply)
        return reply
    finally:
        _CURRENT_CUSTOMER.reset(token)


# ── EOC ────────────────────────────────────────────────────────────────────────

_CHAT_COLLECTION = "chat_sessions"


def _ensure_chat_collection(client) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if _CHAT_COLLECTION not in existing:
        from qdrant_client.models import Distance, VectorParams

        from vectordb.embedder import VECTOR_SIZE

        client.create_collection(
            collection_name=_CHAT_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def end_conversation(session_id: str) -> str:
    if session_id not in _sessions:
        return "session not found"

    session = _sessions[session_id]
    memory: ConversationMemory = session["memory"]
    customer: dict = session.get("customer", {})
    summary = memory.for_storage()

    try:
        from qdrant_client.models import PointStruct

        from vectordb.client import get_client
        from vectordb.embedder import embed

        client = get_client()
        _ensure_chat_collection(client)
        client.upsert(
            collection_name=_CHAT_COLLECTION,
            points=[
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embed(summary),
                    payload={
                        "session_id": session_id,
                        "customer_id": customer.get("username", "guest"),
                        "summary": summary,
                        "turn_count": memory.turn_count(),
                        "ended_at": time.time(),
                    },
                )
            ],
        )
    except Exception:
        pass

    del _sessions[session_id]
    return summary


# ── Introspection ──────────────────────────────────────────────────────────────


def get_history(session_id: str) -> list[dict] | None:
    if session_id not in _sessions:
        return None
    memory: ConversationMemory = _sessions[session_id]["memory"]
    return [{"role": m.role, "content": m.content} for m in memory.messages]
