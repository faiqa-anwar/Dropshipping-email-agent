from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
# For production, swap InMemorySaver for a persistent one, e.g.:
# from langgraph.checkpoint.sqlite import SqliteSaver
# checkpointer = SqliteSaver.from_conn_string("dropship_agent.db")

from agent_app.graph.state import EmailState
from agent_app.graph import nodes


def route_after_sender_type(state: EmailState) -> str:
    """Top-level triage: send each sender type down its own path."""
    sender_type = state.get("sender_type")
    if sender_type == "spam":
        return "decide"  # decide() handles spam -> "ignore"
    if sender_type == "supplier":
        return "classify_supplier_email"
    if sender_type == "carrier":
        return "classify_carrier_email"
    return "classify_email"  # customer (default/fallback)


def route_after_classify(state: EmailState) -> str:
    """Spam/ignored categories skip straight to logging - no need to fetch
    order data or spend more LLM calls on them."""
    if state["category"] == "spam":
        return "decide"  # decide() handles spam -> "ignore" without needing order/policy lookups
    return "fetch_context"


def route_after_decision(state: EmailState) -> str:
    if state["decision"] == "escalate":
        return "escalate_to_human"
    if state["decision"] == "ignore":
        return "send_and_log"
    return "draft_reply"


def route_after_supplier_or_carrier(state: EmailState) -> str:
    """Supplier/carrier handlers set 'decision' directly (auto_reply=logged-only
    or escalate) - no draft_reply/refund logic applies to them."""
    if state["decision"] == "escalate":
        return "escalate_to_human"
    return "send_and_log"


def build_graph(checkpointer=None):
    """checkpointer defaults to InMemorySaver (fine for a single-process demo
    run). For run_live.py, pass a persistent SqliteSaver instead so paused
    escalations survive between separate script invocations (e.g. cron)."""
    builder = StateGraph(EmailState)

    builder.add_node("identify_sender_type", nodes.identify_sender_type)
    builder.add_node("classify_email", nodes.classify_email)
    builder.add_node("fetch_context", nodes.fetch_context)
    builder.add_node("assess_urgency", nodes.assess_urgency)
    builder.add_node("check_duplicate", nodes.check_duplicate)
    builder.add_node("decide", nodes.decide)
    builder.add_node("draft_reply", nodes.draft_reply)
    builder.add_node("escalate_to_human", nodes.escalate_to_human)
    builder.add_node("send_and_log", nodes.send_and_log)

    builder.add_node("classify_supplier_email", nodes.classify_supplier_email)
    builder.add_node("handle_supplier_email", nodes.handle_supplier_email)
    builder.add_node("classify_carrier_email", nodes.classify_carrier_email)
    builder.add_node("handle_carrier_email", nodes.handle_carrier_email)

    builder.add_edge(START, "identify_sender_type")
    builder.add_conditional_edges("identify_sender_type", route_after_sender_type)

    # customer path (existing)
    builder.add_conditional_edges("classify_email", route_after_classify)
    builder.add_edge("fetch_context", "assess_urgency")
    builder.add_edge("assess_urgency", "check_duplicate")
    builder.add_edge("check_duplicate", "decide")
    builder.add_conditional_edges("decide", route_after_decision)
    builder.add_edge("draft_reply", "send_and_log")
    builder.add_edge("escalate_to_human", "send_and_log")

    # supplier path
    builder.add_edge("classify_supplier_email", "handle_supplier_email")
    builder.add_conditional_edges("handle_supplier_email", route_after_supplier_or_carrier)

    # carrier path
    builder.add_edge("classify_carrier_email", "handle_carrier_email")
    builder.add_conditional_edges("handle_carrier_email", route_after_supplier_or_carrier)

    builder.add_edge("send_and_log", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())


graph = build_graph()
