"""
Company refund/return policy source.

Uses Supabase's refund_policy table if configured, otherwise reads the
local Excel file - either way this is what gives the agent's decisions a
citable "source" instead of relying on the LLM's general knowledge.
"""
import openpyxl
import os
from agent_app.integrations import supabase_store

_XLSX_PATH = os.path.join(os.path.dirname(__file__), "..", "mock_data", "refund_policy.xlsx")


def lookup_policy(category: str, is_final_sale: bool = False, already_shipped: bool | None = None) -> dict:
    if supabase_store.SUPABASE_ENABLED:
        return supabase_store.lookup_policy(category, is_final_sale, already_shipped)
    return _lookup_from_excel(category, is_final_sale, already_shipped)


def _lookup_from_excel(category: str, is_final_sale: bool, already_shipped: bool | None) -> dict:
    wb = openpyxl.load_workbook(_XLSX_PATH)
    ws = wb["refund_policy"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    # columns: category, condition, window_days, max_auto_refund_usd, notes

    for i, row in enumerate(rows, start=2):
        cat, condition, window_days, max_refund, notes = row

        if cat != category:
            continue

        if category == "refund_request":
            if is_final_sale and condition == "final_sale item":
                return _make_result(condition, window_days, max_refund, notes, i)
            if not is_final_sale and condition == "standard item":
                return _make_result(condition, window_days, max_refund, notes, i)

        elif category == "cancellation":
            if already_shipped and condition == "already shipped":
                return _make_result(condition, window_days, max_refund, notes, i)
            if not already_shipped and condition == "not yet shipped":
                return _make_result(condition, window_days, max_refund, notes, i)

        elif category == "complaint":
            return _make_result(condition, window_days, max_refund, notes, i)

    return {
        "condition": None, "window_days": 0, "max_auto_refund_usd": 0,
        "notes": "No matching policy found - escalate.",
        "source_ref": "refund_policy.xlsx (no match)",
    }


def _make_result(condition, window_days, max_refund, notes, row_num):
    return {
        "condition": condition,
        "window_days": window_days,
        "max_auto_refund_usd": max_refund,
        "notes": notes,
        "source_ref": f"refund_policy.xlsx, row {row_num}",
    }
