"""Deterministic, Python-side 'tool' routing for the draft-only chatbot.

The 1.5B draft model is served by a minimal transformers server that cannot do
LLM tool-calling. So instead of a ReAct loop where the model decides which tool to
call, we resolve the relevant EDBMS data — and perform any clearly-requested action
— here in code, then hand the model a compact CONTEXT block to phrase a reply from.

This keeps real order/refund/escalation handling working on a weak model, and it's
deterministic (no cross-customer leakage, no hallucinated order numbers): the model
only ever sees this customer's own rows, fetched by user_id.
"""

from __future__ import annotations

import re

from .edbms import create_ticket, get_recent_purchases
from .tools import _FAQ

# Keyword sets for routing. Kept small and lowercase; matched against the message.
_ORDER_KW = {
    "order",
    "orders",
    "delivery",
    "deliver",
    "delivered",
    "track",
    "tracking",
    "status",
    "package",
    "parcel",
    "shipment",
    "shipping",
    "bought",
    "buy",
    "purchase",
    "purchased",
    "received",
    "arrive",
    "arrived",
    "where",
}
_ISSUE_KW = {
    "damaged",
    "broken",
    "defective",
    "faulty",
    "wrong",
    "missing",
    "late",
    "quality",
    "stopped",
    "cracked",
    "leaking",
}
_COMPLAINT_KW = {"complaint", "complain", "damaged", "broken", "defective", "wrong", "missing", "faulty"}
_ESCALATE_KW = {
    "human",
    "agent",
    "representative",
    "manager",
    "supervisor",
    "escalate",
    "escalation",
    "legal",
    "lawsuit",
    "sue",
}

_MAX_CONTEXT = 400  # char cap — keeps the prompt within the draft's small budget


def _fmt_orders(orders: list[dict]) -> str:
    out = []
    for o in orders[:3]:
        issue = f" [issue: {o['issue']}]" if o.get("issue") else ""
        out.append(f"{o['order_ref']} {o['product']} ({o['status']}){issue} ${o['amount']:.2f}")
    return "; ".join(out)


def build_context(user_message: str, customer: dict) -> str:
    """Resolve the EDBMS facts + actions relevant to this turn, as a CONTEXT string.

    Returns "" when there's nothing to add (e.g. anonymous session or small talk),
    in which case the model just chats from the system prompt + history.
    """
    uid = customer.get("id")
    if not uid:
        return ""

    text = user_message.lower()
    words = set(re.findall(r"[a-z']+", text))
    parts: list[str] = []

    # 1. Relevant purchase history — keyword-filtered to the mentioned product/issue.
    if words & _ORDER_KW or words & _ISSUE_KW:
        orders = get_recent_purchases(uid, keywords=user_message)
        parts.append("Recent orders: " + _fmt_orders(orders) if orders else "No matching recent orders found.")

    # 2. One FAQ snippet for a recognised topic (one is enough for the token budget).
    for key, ans in _FAQ.items():
        if key.replace("_", " ") in text or key in words:
            parts.append(f"FAQ[{key}]: {ans}")
            break

    # 3. Actions (mutations) — performed on clear intent, result fed back for the
    #    model to confirm. Refund takes precedence over a generic complaint.
    if "refund" in words or "reimburse" in words:
        ref = create_ticket(uid, "refund")
        parts.append(f"ACTION done: refund request {ref} filed (3-5 business days to original payment).")
    elif words & _COMPLAINT_KW:
        ref = create_ticket(uid, "complaint")
        parts.append(f"ACTION done: complaint ticket {ref} logged (team reviews within 1 hour).")

    if words & _ESCALATE_KW:
        ref = create_ticket(uid, "escalation:urgent")
        parts.append(f"ACTION done: escalated to a human agent (ticket {ref}); contact within 30 min.")

    return " | ".join(parts)[:_MAX_CONTEXT]
