"""
Supabase-backed data layer.

Set SUPABASE_URL and SUPABASE_KEY (the "anon" or "service_role" key from
Project Settings -> API) as environment variables to activate this. If
they're not set, every module in app/integrations/ falls back to its
in-memory mock automatically - the graph never breaks either way.

Run supabase_schema.sql in your Supabase project's SQL Editor first to
create the required tables (orders, inventory, refund_policy, email_decisions).
"""
import os
from datetime import datetime, timezone

_SUPABASE_URL = os.environ.get("SUPABASE_URL")
_SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_ENABLED = bool(_SUPABASE_URL and _SUPABASE_KEY)

_client = None
if SUPABASE_ENABLED:
    from supabase import create_client
    _client = create_client(_SUPABASE_URL, _SUPABASE_KEY)


def find_order(customer_email: str) -> dict | None:
    resp = _client.table("orders").select("*").eq("customer_email", customer_email.lower()).limit(1).execute()
    if not resp.data:
        return None
    row = resp.data[0]
    return {
        "id": row["id"],
        "total": float(row["total"]),
        "item": row["item"],
        "final_sale": row["final_sale"],
        "fulfilled_at": _parse_ts(row["fulfilled_at"]),
        "shipped": row["shipped"],
        "tracking": row.get("tracking_number"),
    }


def find_order_by_id(order_id: str) -> dict | None:
    resp = _client.table("orders").select("*").eq("id", order_id).limit(1).execute()
    if not resp.data:
        return None
    row = resp.data[0]
    return {
        "id": row["id"],
        "total": float(row["total"]),
        "item": row["item"],
        "final_sale": row["final_sale"],
        "fulfilled_at": _parse_ts(row["fulfilled_at"]),
        "shipped": row["shipped"],
        "tracking": row.get("tracking_number"),
    }


def lookup_policy(category: str, is_final_sale: bool = False, already_shipped: bool | None = None) -> dict:
    resp = _client.table("refund_policy").select("*").eq("category", category).execute()
    rows = resp.data or []

    for row in rows:
        condition = row["condition"]
        if category == "refund_request":
            if is_final_sale and condition == "final_sale item":
                return _policy_result(row)
            if not is_final_sale and condition == "standard item":
                return _policy_result(row)
        elif category == "cancellation":
            if already_shipped and condition == "already shipped":
                return _policy_result(row)
            if not already_shipped and condition == "not yet shipped":
                return _policy_result(row)
        elif category == "complaint":
            return _policy_result(row)

    return {
        "condition": None, "window_days": 0, "max_auto_refund_usd": 0,
        "notes": "No matching policy found - escalate.",
        "source_ref": "Supabase refund_policy (no match)",
    }


def _policy_result(row: dict) -> dict:
    return {
        "condition": row["condition"],
        "window_days": row["window_days"],
        "max_auto_refund_usd": float(row["max_auto_refund_usd"]),
        "notes": row["notes"],
        "source_ref": f"Supabase refund_policy, id={row['id']}",
    }


def mark_out_of_stock(product_name: str) -> None:
    _client.table("inventory").update({"in_stock": False, "updated_at": _now()}).eq("product_name", product_name).execute()
    print(f"[SUPABASE] Marked '{product_name}' as OUT OF STOCK")


def update_unit_cost(product_name: str, new_cost: float) -> None:
    _client.table("inventory").update({"unit_cost": new_cost, "updated_at": _now()}).eq("product_name", product_name).execute()
    print(f"[SUPABASE] '{product_name}' cost updated to ${new_cost}")


def update_tracking(order_id: str, tracking_number: str, status: str) -> None:
    _client.table("orders").update({"tracking_number": tracking_number, "shipped": True}).eq("id", order_id).execute()
    print(f"[SUPABASE] Order #{order_id} tracking updated: {tracking_number} ({status})")


def find_prior_decision(order_id: str, decision_type: str) -> dict | None:
    resp = (
        _client.table("email_decisions")
        .select("*")
        .eq("order_id", order_id)
        .eq("decision", decision_type)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def log_decision(record: dict) -> None:
    payload = {
        "email_id": record.get("email_id"),
        "inbox_source": record.get("inbox_source"),
        "sender": record.get("sender"),
        "sender_type": record.get("sender_type"),
        "category": record.get("category"),
        "decision": record.get("decision"),
        "reasoning": record.get("reasoning"),
        "source_used": record.get("source_used"),
        "human_response": record.get("human_response"),
        "order_id": record.get("order_id"),
    }
    _client.table("email_decisions").insert(payload).execute()
    print(f"[SUPABASE] Logged decision for email {record.get('email_id')}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
