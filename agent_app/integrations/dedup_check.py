"""
Duplicate-request detection.

Before auto-approving a refund/cancellation, check whether we already
auto-approved one for the same order_id. Without this, a customer emailing
twice about the same issue (common - people follow up when anxious) could
trigger two separate refunds.

Uses Supabase's email_decisions table if configured, otherwise an
in-memory list that mirrors what notify_clients.log_decision writes in
mock mode.
"""
from agent_app.integrations import supabase_store

# Mirrors mock-mode audit log entries so duplicate checks work without Supabase
_MOCK_DECISION_LOG: list[dict] = []


def record_for_dedup_check(record: dict) -> None:
    """Called by notify_clients.log_decision in mock mode so later duplicate
    checks have something to look at. No-op when Supabase is enabled, since
    Supabase's own table is queried directly instead."""
    if not supabase_store.SUPABASE_ENABLED:
        _MOCK_DECISION_LOG.append(record)


def already_auto_approved(order_id: str, decision_type: str = "auto_refund") -> dict | None:
    """Returns the prior matching decision record if one exists, else None."""
    if not order_id:
        return None

    if supabase_store.SUPABASE_ENABLED:
        return supabase_store.find_prior_decision(order_id, decision_type)

    for record in _MOCK_DECISION_LOG:
        if record.get("order_id") == order_id and record.get("decision") == decision_type:
            return record
    return None
