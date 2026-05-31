"""
Order and ticket store backed by Qdrant.

Collections:
  customer_orders  — order records, queried by customer_id payload filter
  support_tickets  — complaint / refund / escalation tickets
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

ORDERS_COLLECTION = "customer_orders"
TICKETS_COLLECTION = "support_tickets"

_DEMO_ORDERS = [
    {
        "order_id": "ORD-1001",
        "customer_id": "demo_customer",
        "restaurant": "Burger Palace",
        "items": ["Double Cheeseburger", "Fries", "Coke"],
        "status": "delivered",
        "total": 18.50,
        "placed_at": time.time() - 7200,
        "delivered_at": time.time() - 6000,
        "delivery_address": "123 Main St",
        "estimated_delivery": None,
    },
    {
        "order_id": "ORD-1002",
        "customer_id": "demo_customer",
        "restaurant": "Pizza Express",
        "items": ["Margherita Pizza", "Garlic Bread"],
        "status": "in_transit",
        "total": 24.00,
        "placed_at": time.time() - 1800,
        "delivered_at": None,
        "delivery_address": "123 Main St",
        "estimated_delivery": "15–20 min",
    },
    {
        "order_id": "ORD-1003",
        "customer_id": "demo_customer",
        "restaurant": "Sushi World",
        "items": ["Salmon Roll", "Miso Soup"],
        "status": "preparing",
        "total": 31.00,
        "placed_at": time.time() - 600,
        "delivered_at": None,
        "delivery_address": "123 Main St",
        "estimated_delivery": "30–40 min",
    },
]


def _ensure_collection(collection: str):
    from qdrant_client.models import Distance, VectorParams
    from vectordb.client import get_client
    from vectordb.embedder import VECTOR_SIZE
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    if collection not in existing:
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
    return client


def seed_demo_orders() -> None:
    """Seed demo orders for development. Safe to call multiple times."""
    try:
        from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue
        from vectordb.embedder import embed
        client = _ensure_collection(ORDERS_COLLECTION)
        for order in _DEMO_ORDERS:
            # Skip if already seeded
            existing, _ = client.scroll(
                collection_name=ORDERS_COLLECTION,
                scroll_filter=Filter(must=[
                    FieldCondition(key="order_id", match=MatchValue(value=order["order_id"]))
                ]),
                limit=1,
            )
            if existing:
                continue
            desc = f"Order {order['order_id']} from {order['restaurant']}: {', '.join(order['items'])}"
            client.upsert(
                collection_name=ORDERS_COLLECTION,
                points=[PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embed(desc),
                    payload=order,
                )],
            )
    except Exception:
        pass


def get_customer_orders(customer_id: str, limit: int = 5) -> list[dict]:
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        client = _ensure_collection(ORDERS_COLLECTION)
        points, _ = client.scroll(
            collection_name=ORDERS_COLLECTION,
            scroll_filter=Filter(must=[
                FieldCondition(key="customer_id", match=MatchValue(value=customer_id))
            ]),
            limit=limit,
            with_payload=True,
        )
        return [p.payload for p in points]
    except Exception:
        return []


def get_order_by_id(order_id: str) -> Optional[dict]:
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        client = _ensure_collection(ORDERS_COLLECTION)
        points, _ = client.scroll(
            collection_name=ORDERS_COLLECTION,
            scroll_filter=Filter(must=[
                FieldCondition(key="order_id", match=MatchValue(value=order_id))
            ]),
            limit=1,
            with_payload=True,
        )
        return points[0].payload if points else None
    except Exception:
        return None


def create_ticket(
    customer_id: str,
    ticket_type: str,
    description: str,
    order_id: Optional[str] = None,
    priority: str = "normal",
) -> str:
    """Create a support ticket. Returns the ticket_id."""
    ticket_id = f"TKT-{str(uuid.uuid4())[:8].upper()}"
    try:
        from qdrant_client.models import PointStruct
        from vectordb.embedder import embed
        client = _ensure_collection(TICKETS_COLLECTION)
        payload = {
            "ticket_id": ticket_id,
            "customer_id": customer_id,
            "order_id": order_id,
            "type": ticket_type,
            "description": description,
            "status": "open",
            "priority": priority,
            "created_at": time.time(),
        }
        client.upsert(
            collection_name=TICKETS_COLLECTION,
            points=[PointStruct(
                id=str(uuid.uuid4()),
                vector=embed(f"{ticket_type}: {description}"[:200]),
                payload=payload,
            )],
        )
    except Exception:
        pass
    return ticket_id
