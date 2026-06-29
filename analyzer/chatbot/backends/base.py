"""Pluggable customer-data backend for the chatbot.

The chatbot needs only four operations against whatever customer system you point
it at: authenticate a login, fetch account info, fetch recent orders, and open a
support ticket. This module defines that contract (`CustomerBackend`) plus the
backend-agnostic logic (order rollup + keyword filtering), so each concrete
adapter stays tiny — it only implements the data primitives.

Add a new database by subclassing `CustomerBackend`, implementing the four
primitives, and selecting it from config (see `config.py` and
`config/chatbot_db.example.yaml`).

Normalized shapes the rest of the chatbot relies on:
  customer  : {"id", "username", "name", "email", "tier"}
  account   : {"name", "email", "tier", "join_date", "total_orders", "active_orders"}
  order row : {"order_ref", "product", "category", "status", "issue",
               "amount", "order_date", "delivery_date"}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

# Order statuses that count as "not yet delivered" / on the way. Used for the
# account rollup and (in context_router) for surfacing live orders first.
ACTIVE_STATUSES = {"processing", "in_transit", "out_for_delivery"}

# Query/filler words ignored when keyword-filtering orders, so generic phrasings
# ("what is the status of my order?") fall through to "show recent orders" instead
# of spuriously matching a product/category substring. Product/issue words (shoes,
# damaged, late, missing…) are deliberately NOT here so they still filter.
_STOPWORDS = {
    "what", "when", "where", "which", "status", "order", "orders", "mine", "have",
    "with", "will", "your", "about", "please", "want", "need", "tell", "show",
    "give", "could", "would", "there", "here", "from", "like", "just", "also",
    "some", "this", "that", "they", "them", "does", "recent", "latest", "update",
}  # fmt: skip


def keyword_filter(rows: list[dict], keywords: str) -> list[dict]:
    """Filter normalized order rows by meaningful tokens in `keywords`.

    Drops stopwords and short tokens; when nothing meaningful matches, returns the
    rows unchanged (so generic status questions still surface recent/active orders).
    """
    if not (keywords and keywords.strip()):
        return rows
    kws = {k.lower() for k in keywords.split() if len(k) >= 4 and k.lower() not in _STOPWORDS}
    if not kws:
        return rows
    filtered = [
        r
        for r in rows
        if any(
            kw in (r.get("product") or "").lower()
            or kw in (r.get("category") or "").lower()
            or kw in (r.get("status") or "").lower()
            or kw in (r.get("issue") or "").lower()
            for kw in kws
        )
    ]
    return filtered or rows


class CustomerBackend(ABC):
    """Contract the chatbot depends on.

    Concrete adapters implement the abstract primitives; this base supplies
    `get_account_info` (profile + order rollup) and `get_recent_purchases`
    (keyword filtering) so every backend behaves identically above the data layer.
    """

    @abstractmethod
    def authenticate(self, username: str, password: str) -> Optional[dict]:
        """Return the customer dict (without secrets) on valid credentials, else None."""

    @abstractmethod
    def get_customer(self, username: str) -> Optional[dict]:
        """Look up a customer by username (no password check), or None."""

    @abstractmethod
    def _fetch_account(self, user_id) -> Optional[dict]:
        """Raw account fields {name, email, tier, join_date} for user_id, or None."""

    @abstractmethod
    def _fetch_recent(self, user_id) -> list[dict]:
        """Normalized order rows for user_id, newest first (already capped)."""

    @abstractmethod
    def create_ticket(self, user_id, ticket_type: str, purchase_id=None) -> str:
        """Open a support ticket and return its reference id."""

    # ── backend-agnostic, shared by all adapters ──────────────────────────────

    def get_account_info(self, user_id) -> dict:
        acct = self._fetch_account(user_id)
        if not acct:
            return {}
        orders = self._fetch_recent(user_id)
        acct = dict(acct)
        acct["total_orders"] = len(orders)
        acct["active_orders"] = sum(1 for o in orders if o.get("status") in ACTIVE_STATUSES)
        return acct

    def get_recent_purchases(self, user_id, keywords: str = "") -> list[dict]:
        return keyword_filter(self._fetch_recent(user_id), keywords)
