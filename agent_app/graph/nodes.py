from langgraph.types import interrupt

from agent_app.graph.state import EmailState
from agent_app.integrations import shopify_client, policy_source, llm, notify_clients, inventory_store, dedup_check


def identify_sender_type(state: EmailState) -> dict:
    """Step 0 (orders@ especially mixes these together): figure out if this
    is a customer, a supplier, a shipping carrier, or spam before deciding
    which downstream flow to use."""
    result = llm.identify_sender_type(state["sender"], state["subject"], state["body"])
    return {"sender_type": result["sender_type"], "sender_type_confidence": result["confidence"]}


def classify_supplier_email(state: EmailState) -> dict:
    result = llm.classify_supplier_email(state["subject"], state["body"])
    return {"supplier_category": result["supplier_category"]}


def handle_supplier_email(state: EmailState) -> dict:
    """Supplier emails are mostly auto-processed data updates, not replies -
    stock/price changes feed straight into inventory so customer-facing
    order-status answers stay accurate."""
    category = state.get("supplier_category")
    body = state["body"]

    # naive product-name extraction for the mock - in production the
    # supplier's email/API would include a proper SKU/product ID
    product = _extract_product_name(body)

    if category == "stock_alert" and product:
        inventory_store.mark_out_of_stock(product)
        return {"decision": "auto_reply", "reasoning": f"Stock alert processed - '{product}' marked out of stock.", "final_status": "completed"}

    if category == "price_change" and product:
        new_cost = _extract_price(body)
        if new_cost:
            inventory_store.update_unit_cost(product, new_cost)
        return {"decision": "auto_reply", "reasoning": f"Price change logged for '{product}'.", "final_status": "completed"}

    if category in ("order_confirmation", "invoice"):
        return {"decision": "auto_reply", "reasoning": f"Supplier {category} logged, no action needed.", "final_status": "completed"}

    # shipping_delay or anything ambiguous -> human should see it, since it
    # may need proactive customer communication
    return {"decision": "escalate", "reasoning": f"Supplier email category '{category}' needs human review."}


def classify_carrier_email(state: EmailState) -> dict:
    result = llm.classify_carrier_email(state["subject"], state["body"])
    return {"carrier_category": result["carrier_category"]}


def handle_carrier_email(state: EmailState) -> dict:
    """Carrier emails sync tracking status back onto the order record.
    Delivery exceptions (damaged/lost) are the one case that needs a human,
    since that usually means proactively contacting the customer."""
    category = state.get("carrier_category")
    tracking = _extract_tracking_number(state["body"])
    order_id = _extract_order_id(state["body"]) or "unknown"

    if category in ("tracking_update", "delivery_confirmation"):
        inventory_store.update_tracking(order_id, tracking or "n/a", category)
        return {"decision": "auto_reply", "reasoning": f"Carrier {category} synced to order #{order_id}.", "final_status": "completed"}

    # delivery_exception (damaged/lost/failed) -> escalate, customer likely
    # needs proactive outreach and possibly a refund/replacement
    return {"decision": "escalate", "reasoning": f"Delivery exception on order #{order_id} - needs proactive customer outreach."}


def _extract_product_name(body: str) -> str | None:
    for name in ("Bluetooth Earbuds", "Smart Watch", "Phone Case"):
        if name.lower() in body.lower():
            return name
    return None


def _extract_price(body: str) -> float | None:
    import re
    match = re.search(r"\$(\d+\.?\d*)", body)
    return float(match.group(1)) if match else None


def _extract_tracking_number(body: str) -> str | None:
    import re
    match = re.search(r"\b(TRK\w+|\d{10,})\b", body)
    return match.group(1) if match else None


def _extract_order_id(body: str) -> str | None:
    import re
    match = re.search(r"order\s*#?(\d+)", body, re.IGNORECASE)
    return match.group(1) if match else None


def classify_email(state: EmailState) -> dict:
    """Step 1: figure out what kind of email this is."""
    result = llm.classify(state["subject"], state["body"])
    return {"category": result["category"], "confidence": result["confidence"]}


def fetch_context(state: EmailState) -> dict:
    """Step 2: pull grounding data - the order record and the policy row
    that applies. This is what lets every later decision cite a real source
    instead of the LLM guessing."""
    order = shopify_client.find_order(state["sender"], state["body"])

    order_source = None
    if order:
        from agent_app.integrations import supabase_store
        order_source = f"Supabase orders table, order #{order['id']}" if supabase_store.SUPABASE_ENABLED \
            else f"mock order data, order #{order['id']}"

    is_final_sale = bool(order and order.get("final_sale"))
    already_shipped = bool(order and order.get("shipped"))

    policy = policy_source.lookup_policy(
        category=state["category"],
        is_final_sale=is_final_sale,
        already_shipped=already_shipped,
    )

    policy_summary = f"{policy['notes']} (window: {policy['window_days']}d, max auto: ${policy['max_auto_refund_usd']})"

    # order_status/general_inquiry decisions are grounded in the order lookup
    # itself, not the refund policy - cite whichever one is actually relevant.
    if state["category"] in ("order_status", "general_inquiry"):
        source_used = order_source or "no matching order found"
    else:
        source_used = policy["source_ref"]

    return {
        "order_data": order,
        "policy_context": policy_summary,
        "source_used": source_used,
    }


def assess_urgency(state: EmailState) -> dict:
    """Step 2b: detect anger, legal/chargeback threats, or urgent distress.
    This runs regardless of category/confidence - decide() checks it FIRST,
    before any auto-approval rule, since an angry or threatening customer
    should always reach a human even if their refund would otherwise
    qualify for auto-approval."""
    result = llm.assess_urgency(state["subject"], state["body"])
    return {"is_urgent": result["is_urgent"], "urgency_reason": result.get("reason")}


def check_duplicate(state: EmailState) -> dict:
    """Step 2c: has this order already had an auto_refund approved? Prevents
    double-refunding a customer who emails twice about the same issue."""
    order = state.get("order_data")
    if not order or state.get("category") not in ("refund_request", "cancellation"):
        return {"is_duplicate": False, "duplicate_reason": None}

    decision_type = "auto_refund" if state["category"] == "refund_request" else "auto_reply"
    prior = dedup_check.already_auto_approved(order["id"], decision_type)

    if prior:
        return {
            "is_duplicate": True,
            "duplicate_reason": f"Order #{order['id']} already had a '{decision_type}' decision "
                                 f"(email {prior.get('email_id')}) - possible duplicate request.",
        }
    return {"is_duplicate": False, "duplicate_reason": None}


def decide(state: EmailState) -> dict:
    """Step 3: rule-based decision using the fetched order + policy data.
    Deliberately NOT left entirely to the LLM - refund approval logic is
    explicit and auditable."""
    category = state.get("category")  # None when routed here directly from
                                        # identify_sender_type (top-level spam)
    order = state.get("order_data")
    confidence = state.get("confidence", 0)

    if category is None:
        return {"decision": "ignore", "reasoning": "Classified as spam at sender-type triage."}

    # --- Overrides checked FIRST, before any normal rule/policy logic ---
    if state.get("is_urgent"):
        return {
            "decision": "escalate",
            "reasoning": f"Escalated regardless of policy match: {state.get('urgency_reason')}",
        }

    if state.get("is_duplicate"):
        return {
            "decision": "escalate",
            "reasoning": f"Escalated - possible duplicate request: {state.get('duplicate_reason')}",
        }

    # No order found at all -> can't safely automate anything order-related
    if category in ("refund_request", "cancellation", "complaint") and not order:
        return {
            "decision": "escalate",
            "reasoning": "No matching order found for this customer - needs manual lookup.",
        }

    if category == "spam":
        return {"decision": "ignore", "reasoning": "Classified as spam/newsletter."}

    if category == "order_status":
        if order and confidence >= 0.75:
            return {"decision": "auto_reply", "reasoning": "Order found, high-confidence order-status query."}
        return {"decision": "escalate", "reasoning": "Low confidence or missing order data for status query."}

    if category in ("refund_request", "cancellation", "complaint"):
        policy = policy_source.lookup_policy(
            category=category,
            is_final_sale=bool(order.get("final_sale")),
            already_shipped=bool(order.get("shipped")),
        )
        within_window = policy["window_days"] >= _days_since(order.get("fulfilled_at"))
        under_threshold = order["total"] <= policy["max_auto_refund_usd"]

        if within_window and under_threshold:
            reasoning = (
                f"Auto-approved: order #{order['id']} (${order['total']}), "
                f"{_days_since(order.get('fulfilled_at'))} days since fulfillment, "
                f"within {policy['window_days']}-day window, "
                f"under ${policy['max_auto_refund_usd']} auto-approval threshold. "
                f"Source: {policy['source_ref']}."
            )
            decision = "auto_refund" if category != "cancellation" else "auto_reply"
            return {"decision": decision, "reasoning": reasoning}

        reasoning = (
            f"Escalated: order #{order['id']} (${order['total']}) does not meet auto-approval "
            f"rules ({policy['notes']}). Source: {policy['source_ref']}."
        )
        return {"decision": "escalate", "reasoning": reasoning}

    # general_inquiry and anything unmatched
    if confidence >= 0.75:
        return {"decision": "auto_reply", "reasoning": "General inquiry, high classification confidence."}
    return {"decision": "escalate", "reasoning": "General inquiry with low confidence."}


def draft_reply(state: EmailState) -> dict:
    """Step 4a: generate the actual reply text for auto_reply / auto_refund."""
    context = f"Order: {state.get('order_data')}\nPolicy: {state.get('policy_context')}\nReasoning: {state.get('reasoning')}"
    instruction = "Write a short, friendly customer service email reply based on the context below."
    reply = llm.generate_reply(context, instruction)
    return {"draft_reply": reply}


def escalate_to_human(state: EmailState) -> dict:
    """Step 4b: notify a human via Slack and PAUSE the graph until they respond.
    This is the core human-in-the-loop mechanic."""
    category = state.get("category") or state.get("supplier_category") or state.get("carrier_category")

    notify_clients.post_to_slack(
        channel="#support-escalations",
        text=(
            f"Email needs review (id={state['email_id']})\n"
            f"From: {state['sender']}\n"
            f"Category: {category}\n"
            f"Reasoning: {state.get('reasoning')}\n"
            f"Source: {state.get('source_used')}\n"
            f"Original: {state['body'][:300]}"
        ),
    )

    # Graph pauses here. Whatever value is passed to Command(resume=...)
    # when the graph is re-invoked becomes the return value of interrupt().
    human_response = interrupt({
        "email_id": state["email_id"],
        "category": category,
        "reasoning": state.get("reasoning"),
        "body": state["body"],
    })

    return {"human_response": human_response, "final_status": "resolved_by_human"}


def send_and_log(state: EmailState) -> dict:
    """Step 5: deliver the outcome and write the audit record. Always runs last."""
    if state["decision"] in ("auto_reply", "auto_refund") and state.get("draft_reply"):
        notify_clients.send_email(
            state["sender"], f"Re: {state['subject']}", state["draft_reply"],
            inbox_source=state.get("inbox_source"),
        )

    if state["decision"] == "auto_refund" and state.get("order_data"):
        print(f"[SHOPIFY] Issuing refund for order #{state['order_data']['id']}")

    record = {
        "email_id": state["email_id"],
        "inbox_source": state.get("inbox_source"),
        "sender": state["sender"],
        "sender_type": state.get("sender_type"),
        "category": state.get("category") or state.get("supplier_category") or state.get("carrier_category"),
        "decision": state.get("decision"),
        "reasoning": state.get("reasoning"),
        "source_used": state.get("source_used"),
        "human_response": state.get("human_response"),
        "order_id": (state.get("order_data") or {}).get("id"),
    }
    notify_clients.log_decision(record)

    return {"final_status": state.get("final_status") or "completed"}


def _days_since(dt) -> int:
    if dt is None:
        return 0
    from datetime import datetime
    return (datetime.now() - dt).days
