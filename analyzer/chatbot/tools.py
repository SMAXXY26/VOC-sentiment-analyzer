"""Customer-facing support tools for the chatbot agent.

Tools are customer-aware via _CURRENT_CUSTOMER ContextVar (set by agent.chat()
before each graph invocation). Prevents cross-customer data access even if the
LLM hallucinates a different customer_id.

Tool outputs are kept ≤280 chars to stay within the 1024-token vLLM budget.
"""

from __future__ import annotations

import functools
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextvars import ContextVar

from langchain_core.tools import tool

_CURRENT_CUSTOMER: ContextVar[dict] = ContextVar("current_customer", default={})

# ── Tool guards: per-turn call budget + per-call timeout ────────────────────────
# Two failure modes this prevents:
#   1. A runaway agent calling an expensive/external tool (web_search) repeatedly,
#      burning the token budget and latency. Capped per conversation turn.
#   2. A tool hanging indefinitely (DuckDuckGo has no built-in timeout), wedging the
#      whole chat request. Each tool body runs with a hard wall-clock timeout.

_TOOL_CALLS: ContextVar[dict] = ContextVar("tool_calls", default={})

TOOL_TIMEOUT_SECONDS = float(os.getenv("TOOL_TIMEOUT_SECONDS", "8"))
WEB_SEARCH_MAX_CALLS = int(os.getenv("WEB_SEARCH_MAX_CALLS", "1"))

# Daemon pool so a hung tool thread never blocks process exit.
_TOOL_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool")


def reset_tool_budget() -> None:
    """Start a fresh per-turn call budget. Called by agent.chat() each turn."""
    _TOOL_CALLS.set({})


def _guarded(max_calls: int | None = None, timeout: float | None = None):
    """Wrap a tool function with a per-turn call cap and a wall-clock timeout.

    Applied *under* @tool so functools.wraps preserves the name/signature/docstring
    that LangChain reads to build the tool schema.
    """

    def decorator(fn):
        limit = timeout if timeout is not None else TOOL_TIMEOUT_SECONDS

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            calls = _TOOL_CALLS.get()
            used = calls.get(fn.__name__, 0)
            if max_calls is not None and used >= max_calls:
                return (
                    f"(Skipped: '{fn.__name__}' already used {used}× this turn — answer from what you already have.)"
                )[:280]
            calls[fn.__name__] = used + 1

            # ContextVars don't propagate into pool threads automatically, so copy
            # the current context (carries _CURRENT_CUSTOMER) into the worker.
            import contextvars

            ctx = contextvars.copy_context()
            future = _TOOL_POOL.submit(ctx.run, fn, *args, **kwargs)
            try:
                return future.result(timeout=limit)
            except FutureTimeout:
                return f"(Tool '{fn.__name__}' timed out after {limit:.0f}s — try rephrasing.)"[:280]
            except Exception as exc:
                return f"(Tool '{fn.__name__}' error: {exc})"[:280]

        return wrapper

    return decorator


_FAQ: dict[str, str] = {
    "cancel": "Orders can be cancelled within 2 minutes of placing. Go to Orders → Cancel Order.",
    "refund": "Refunds take 3–5 business days to your original payment method.",
    "delivery_time": "Standard delivery: 30–45 min. Express: 15–20 min.",
    "contact": "Urgent? Call 1-800-SUPPORT or email support@example.com.",
    "track": "Track in real-time under Orders → Track Order.",
    "payment": "We accept cards, UPI, wallets, and cash on delivery.",
    "missing_item": "Report a missing item within 24 hours for a full refund or re-delivery.",
    "late_delivery": "If your order is very late, we can refund the delivery fee or offer a coupon.",
}


def _customer() -> dict:
    return _CURRENT_CUSTOMER.get()


def _uid() -> int | None:
    return _customer().get("id")


# ── EDBMS-backed tools ─────────────────────────────────────────────────────────


@tool
@_guarded()
def get_account_info() -> str:
    """Get the current customer's account details: membership tier, join date, email."""
    uid = _uid()
    if not uid:
        return "Session error: customer not identified."
    from .edbms import get_account_info as _get

    info = _get(uid)
    if not info:
        return "No account info found."
    return f"Name: {info.get('name')} | Tier: {info.get('tier')} | Member since: {info.get('join_date')} | Email: {info.get('email')}"


@tool
@_guarded()
def get_my_orders() -> str:
    """Get the customer's recent purchase history with status and any reported issues."""
    uid = _uid()
    if not uid:
        return "Session error: customer not identified."
    from .edbms import get_recent_purchases

    orders = get_recent_purchases(uid)
    if not orders:
        return "No recent purchases found."
    lines = []
    for o in orders[:5]:
        issue_str = f" [ISSUE: {o['issue']}]" if o.get("issue") else ""
        lines.append(f"{o['order_ref']} {o['product']} {o['status']}{issue_str} ${o['amount']:.2f}")
    return "; ".join(lines)[:280]


@tool
@_guarded()
def lookup_purchase_context(keywords: str) -> str:
    """Search the customer's recent purchases for context about a specific product or issue.
    Use when the customer mentions a product name, delivery problem, or issue type.
    keywords: space-separated terms like 'headphones damaged' or 'shoes missing'"""
    uid = _uid()
    if not uid:
        return "Session error: customer not identified."
    from .edbms import get_recent_purchases

    orders = get_recent_purchases(uid, keywords=keywords)
    if not orders:
        return f"No purchases found matching '{keywords}'."
    lines = []
    for o in orders[:3]:
        issue_str = f" — Issue: {o['issue']}" if o.get("issue") else ""
        ddate = f" Delivered:{o['delivery_date']}" if o.get("delivery_date") else ""
        lines.append(f"{o['order_ref']} {o['product']} ({o['status']}){ddate}{issue_str} ${o['amount']:.2f}")
    return " | ".join(lines)[:280]


@tool
@_guarded()
def log_complaint(order_ref: str, complaint_type: str, description: str) -> str:
    """Log a complaint for a purchase.
    complaint_type: wrong_item | missing_item | quality | late_delivery | damaged | other"""
    uid = _uid()
    if not uid:
        return "Session error."
    from .edbms import create_ticket

    ticket_id = create_ticket(uid, f"complaint:{complaint_type}")
    return (
        f"Complaint logged (ticket {ticket_id}) for order {order_ref}. "
        "Our team reviews within 1 hour. You'll receive a resolution notification."
    )[:280]


@tool
@_guarded()
def request_refund(order_ref: str, reason: str) -> str:
    """Request a refund for a purchase. Provide the order reference and reason."""
    uid = _uid()
    if not uid:
        return "Session error."
    from .edbms import create_ticket

    ticket_id = create_ticket(uid, "refund")
    return (
        f"Refund request submitted (ticket {ticket_id}) for order {order_ref}. "
        "Refunds process in 3–5 business days to your original payment method."
    )[:280]


@tool
@_guarded()
def escalate_to_human(order_ref: str, reason: str) -> str:
    """Escalate to a human support agent when you cannot resolve the issue yourself."""
    uid = _uid()
    if not uid:
        return "Session error."
    from .edbms import create_ticket

    ticket_id = create_ticket(uid, "escalation:urgent")
    return (
        f"Case escalated to our support team (ticket {ticket_id}). "
        "A human agent will contact you within 30 minutes via the app or email."
    )[:280]


@tool
@_guarded()
def get_faq_answer(topic: str) -> str:
    """Answer common questions. Topics: cancel, refund, delivery_time, contact, track, payment, missing_item, late_delivery"""
    topic = topic.lower().strip()
    for key in _FAQ:
        if key in topic or topic in key:
            return _FAQ[key]
    return f"Available topics: {', '.join(_FAQ.keys())}"


@tool
@_guarded(max_calls=WEB_SEARCH_MAX_CALLS)
def web_search(query: str) -> str:
    """Search the web for product information, company policies, or general questions.
    Use for questions about products, shipping policies, or anything not in the FAQ."""
    try:
        from langchain_community.tools import DuckDuckGoSearchRun

        result = DuckDuckGoSearchRun().run(query)
        return result[:280]
    except Exception as exc:
        return f"Web search unavailable: {exc}"[:280]


TOOLS = [
    get_account_info,
    get_my_orders,
    lookup_purchase_context,
    log_complaint,
    request_refund,
    escalate_to_human,
    get_faq_answer,
    web_search,
]
