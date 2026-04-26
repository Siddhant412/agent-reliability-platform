from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class SupportToolError(Exception):
    """Raised when a deterministic support tool cannot complete."""


@dataclass(frozen=True)
class SupportToolMetadata:
    name: str
    description: str
    is_mutating: bool
    risk_level: str


TOOL_METADATA: dict[str, SupportToolMetadata] = {
    "kb_search": SupportToolMetadata(
        name="kb_search",
        description="Search support knowledge-base articles.",
        is_mutating=False,
        risk_level="low",
    ),
    "get_customer_profile": SupportToolMetadata(
        name="get_customer_profile",
        description="Fetch a customer profile by customer ID.",
        is_mutating=False,
        risk_level="low",
    ),
    "get_order": SupportToolMetadata(
        name="get_order",
        description="Fetch the latest order for a customer or a specific order ID.",
        is_mutating=False,
        risk_level="low",
    ),
}


CUSTOMERS: dict[str, dict[str, Any]] = {
    "C-500": {
        "customer_id": "C-500",
        "name": "Avery Stone",
        "email": "avery.stone@example.com",
        "tier": "gold",
        "account_status": "active",
    },
    "C-200": {
        "customer_id": "C-200",
        "name": "Riley Chen",
        "email": "riley.chen@example.com",
        "tier": "standard",
        "account_status": "active",
    },
}


ORDERS: dict[str, dict[str, Any]] = {
    "O-900": {
        "order_id": "O-900",
        "customer_id": "C-500",
        "status": "delivered",
        "total_usd": 149.0,
        "payment_status": "paid",
        "items": ["Noise-cancelling headset"],
    },
    "O-901": {
        "order_id": "O-901",
        "customer_id": "C-200",
        "status": "processing",
        "total_usd": 49.0,
        "payment_status": "paid",
        "items": ["USB-C hub"],
    },
}


KB_ARTICLES: list[dict[str, Any]] = [
    {
        "article_id": "KB-100",
        "title": "Handling duplicate charges",
        "summary": "Verify payment history, reassure the customer, and prepare a refund if duplicate capture is confirmed.",
        "tags": ["billing", "refund", "duplicate charge"],
    },
    {
        "article_id": "KB-200",
        "title": "Order status investigation",
        "summary": "Check latest order status, carrier events, and whether escalation is needed.",
        "tags": ["order", "shipping"],
    },
    {
        "article_id": "KB-300",
        "title": "Customer reply quality",
        "summary": "Use concise empathy, explain next steps, and avoid promising actions that require approval.",
        "tags": ["reply", "quality"],
    },
]


def kb_search(*, query: str) -> dict[str, Any]:
    if query == "__force_tool_failure__":
        raise SupportToolError("forced support demo tool failure")

    normalized_query = query.lower()
    matches = [
        article
        for article in KB_ARTICLES
        if any(tag in normalized_query for tag in article["tags"])
        or any(word in article["title"].lower() for word in normalized_query.split())
    ]
    if not matches:
        matches = [KB_ARTICLES[-1]]
    return {"query": query, "articles": matches[:3]}


def get_customer_profile(*, customer_id: str) -> dict[str, Any]:
    return CUSTOMERS.get(
        customer_id,
        {
            "customer_id": customer_id,
            "name": "Unknown Customer",
            "email": None,
            "tier": "standard",
            "account_status": "unknown",
        },
    )


def get_order(*, customer_id: str | None = None, order_id: str | None = None) -> dict[str, Any]:
    if order_id is not None:
        order = ORDERS.get(order_id)
        if order is None:
            return {"order_id": order_id, "status": "not_found"}
        return order

    for order in ORDERS.values():
        if order["customer_id"] == customer_id:
            return order
    return {"customer_id": customer_id, "status": "not_found"}


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "kb_search":
        return kb_search(query=str(args.get("query", "")))
    if name == "get_customer_profile":
        return get_customer_profile(customer_id=str(args.get("customer_id", "")))
    if name == "get_order":
        return get_order(
            customer_id=args.get("customer_id"),
            order_id=args.get("order_id"),
        )
    raise SupportToolError(f"unknown support demo tool: {name}")

