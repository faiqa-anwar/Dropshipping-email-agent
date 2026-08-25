"""
Inventory + tracking store.

Uses Supabase's inventory/orders tables if configured, otherwise an
in-memory dict. Either way, callers (nodes.py) use the same functions.
"""
from agent_app.integrations import supabase_store

_INVENTORY = {
    "Bluetooth Earbuds": {"in_stock": True, "unit_cost": 8.50},
    "Smart Watch": {"in_stock": True, "unit_cost": 32.00},
    "Phone Case": {"in_stock": True, "unit_cost": 2.10},
}


def mark_out_of_stock(product_name: str) -> None:
    if supabase_store.SUPABASE_ENABLED:
        supabase_store.mark_out_of_stock(product_name)
        return
    if product_name in _INVENTORY:
        _INVENTORY[product_name]["in_stock"] = False
    print(f"[INVENTORY] Marked '{product_name}' as OUT OF STOCK")


def update_unit_cost(product_name: str, new_cost: float) -> None:
    if supabase_store.SUPABASE_ENABLED:
        supabase_store.update_unit_cost(product_name, new_cost)
        return
    if product_name in _INVENTORY:
        old = _INVENTORY[product_name]["unit_cost"]
        _INVENTORY[product_name]["unit_cost"] = new_cost
        print(f"[INVENTORY] '{product_name}' cost updated: ${old} -> ${new_cost}")


def update_tracking(order_id: str, tracking_number: str, status: str) -> None:
    if supabase_store.SUPABASE_ENABLED:
        supabase_store.update_tracking(order_id, tracking_number, status)
        return
    print(f"[SHOPIFY] Order #{order_id} tracking updated: {tracking_number} ({status})")
