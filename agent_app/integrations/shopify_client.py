"""
Order lookup.

Uses Supabase if SUPABASE_URL/SUPABASE_KEY are set (see supabase_store.py
and supabase_schema.sql), otherwise falls back to an in-memory mock table
so the graph is fully runnable without any external service.
"""
from datetime import datetime, timedelta
from agent_app.integrations import supabase_store

# Fake "database" of orders, keyed by customer email - used only when
# Supabase isn't configured.
_MOCK_ORDERS = {
    "jane@example.com": {
        "id": "1001",
        "total": 24.99,
        "item": "Bluetooth Earbuds",
        "final_sale": False,
        "fulfilled_at": datetime.now() - timedelta(days=12),
        "shipped": True,
        "tracking": "TRK123456",
    },
    "mike@example.com": {
        "id": "1002",
        "total": 89.00,
        "item": "Smart Watch",
        "final_sale": False,
        "fulfilled_at": datetime.now() - timedelta(days=40),
        "shipped": True,
        "tracking": "TRK987654",
    },
    "amy@example.com": {
        "id": "1003",
        "total": 15.50,
        "item": "Phone Case",
        "final_sale": False,
        "fulfilled_at": None,          # not yet shipped
        "shipped": False,
        "tracking": None,
    },
}


def find_order(sender_email: str, body: str) -> dict | None:
    """Look up an order by customer email. Tries an order-number match in
    the body first (more reliable when a customer references it directly),
    then falls back to matching by sender email."""
    if supabase_store.SUPABASE_ENABLED:
        order_id = _extract_order_id(body)
        if order_id:
            order = supabase_store.find_order_by_id(order_id)
            if order:
                return order
        return supabase_store.find_order(sender_email)

    order_id = _extract_order_id(body)
    if order_id:
        for order in _MOCK_ORDERS.values():
            if order["id"] == order_id:
                return order
    return _MOCK_ORDERS.get(sender_email.lower())


def _extract_order_id(body: str) -> str | None:
    import re
    match = re.search(r"order\s*#?(\d{3,})", body, re.IGNORECASE)
    return match.group(1) if match else None

