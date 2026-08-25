"""
Shared state for the email-handling graph.

Every node reads from this state and returns ONLY the fields it wants to
update. LangGraph merges the returned dict into the overall state after
each node runs.
"""
from typing import TypedDict, Optional, List, Literal


class EmailState(TypedDict, total=False):
    # ---- Input (set when the graph is first invoked) ----
    email_id: str
    inbox_source: str          # "orders@company.com" / "support@company.com"
    sender: str
    subject: str
    body: str
    attachments: List[str]

    # ---- Set by identify_sender_type node (NEW - runs first) ----
    sender_type: Optional[Literal["customer", "supplier", "carrier", "spam"]]
    sender_type_confidence: float

    # ---- Set by classify_email node (customer emails only) ----
    category: Optional[str]        # order_status | refund_request | complaint | cancellation | spam | general_inquiry
    confidence: float

    # ---- Set by classify_supplier_email node (supplier emails only) ----
    supplier_category: Optional[str]   # stock_alert | price_change | order_confirmation | invoice | other

    # ---- Set by classify_carrier_email node (carrier emails only) ----
    carrier_category: Optional[str]    # tracking_update | delivery_exception | delivery_confirmation

    # ---- Set by fetch_context node (customer path) ----
    order_data: Optional[dict]
    policy_context: Optional[str]
    source_used: Optional[str]     # human-readable citation, e.g. "refund_policy.xlsx row 4"

    # ---- Set by assess_urgency node (NEW - customer path, runs before decide) ----
    is_urgent: bool
    urgency_reason: Optional[str]

    # ---- Set by check_duplicate node (NEW - customer path, runs before decide) ----
    is_duplicate: bool
    duplicate_reason: Optional[str]

    # ---- Set by decide node (customer path) ----
    decision: Optional[Literal["auto_reply", "auto_refund", "escalate", "ignore"]]
    reasoning: Optional[str]

    # ---- Set by draft_reply node ----
    draft_reply: Optional[str]

    # ---- Set by escalate_to_human node ----
    human_response: Optional[str]

    # ---- Set by send_and_log node ----
    final_status: Optional[str]
