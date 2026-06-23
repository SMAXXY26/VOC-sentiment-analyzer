"""Customer support chatbot agent.

The chatbot runs EXCLUSIVELY on the draft 1.5B (the 7B is reserved for the analyzer).
Because the draft server can't do LLM tool-calling, there is no ReAct loop: each turn
resolves the relevant EDBMS data + any requested action deterministically in Python
(see context_router.build_context), injects it as a CONTEXT block, and makes a single
draft-model call to phrase the reply.

SOC (start_conversation): authenticates customer via EDBMS, creates session.
chat():                   builds CONTEXT (Python-side tools), one draft-model call.
EOC (end_conversation):   stores conversation summary to Qdrant, cleans up session.

Token budget (max_model_len=1024):
  system ~110 | context ≤400 chars | history ≤250 | response ≤130
"""

from __future__ import annotations

import os
import time
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .cascade_llm import get_draft_llm
from .context_router import build_context
from .memory import ConversationMemory

# Retained for config/back-compat (and asserted by tests). The draft-only chatbot
# makes a single model call per turn, so there is no tool-loop to bound, but keeping
# the knob avoids breaking deployments that set CHATBOT_RECURSION_LIMIT.
_RECURSION_LIMIT = int(os.getenv("CHATBOT_RECURSION_LIMIT", "8"))

_SYSTEM = (
    "You are a friendly, empathetic customer support assistant. "
    "A CONTEXT section may give the customer's relevant orders, an FAQ answer, and any "
    "actions already completed on their behalf. Use ONLY the CONTEXT for order/account "
    "facts — never invent order numbers, prices, or statuses. "
    "If the CONTEXT shows an action was done (refund, complaint, escalation), confirm it warmly. "
    "If the needed info isn't in the CONTEXT, say you'll look into it and offer a human agent. "
    "Keep responses under 3 sentences."
)

_INITIAL_QUICK_REPLIES = [
    "Show my recent orders",
    "I have a product issue",
    "Request a refund",
    "Track my delivery",
    "Account information",
]


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
    """Process one user turn on the draft model.

    Pipeline: resolve EDBMS context + actions in Python → build a single prompt
    (one merged system message + history) → one draft-model call. No tool-calling.
    """
    if session_id not in _sessions:
        session_id = start_conversation()

    session = _sessions[session_id]
    memory: ConversationMemory = session["memory"]
    customer: dict = session.get("customer", {})
    session["ts"] = time.time()

    memory.add("user", user_message)

    # Python-side "tools": fetch this customer's relevant data / perform actions.
    context = build_context(user_message, customer)

    # One merged system message — the draft's minimal chat template is happier with a
    # single system block than several. Carries the account/earlier summary + CONTEXT.
    sys_parts = [_SYSTEM]
    if memory.summary:
        sys_parts.append("ACCOUNT/EARLIER: " + memory.summary)
    if context:
        sys_parts.append("CONTEXT: " + context)

    messages = [SystemMessage(content="\n".join(sys_parts))]
    for m in memory.messages:  # already includes the just-added user turn
        messages.append(HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content))

    try:
        llm = get_draft_llm(temperature=0.3).bind(max_tokens=130)
        reply = str(llm.invoke(messages).content).strip() or "I'm sorry, I couldn't process that. Please try again."
    except Exception:
        reply = "I'm having trouble reaching the assistant right now. Let me connect you with a human agent who can help."

    memory.add("assistant", reply)
    return reply


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
