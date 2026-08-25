"""
Thin LLM wrapper.

Supports three modes, in priority order:
  1. OpenRouter  - if OPENROUTER_API_KEY is set (recommended, works with
     any model OpenRouter hosts - claude, gpt-4o, llama, etc.)
  2. OpenAI      - if OPENAI_API_KEY is set instead
  3. Mock        - keyword-based fallback, no key needed at all

Swap _mock_classify / _mock_generate for real prompts once you're ready;
the call sites in nodes.py don't need to change either way.
"""
import os
import json

_OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY")
_OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
_USE_REAL_LLM = bool(_OPENROUTER_KEY or _OPENAI_KEY)

if _USE_REAL_LLM:
    from langchain_openai import ChatOpenAI

    if _OPENROUTER_KEY:
        # OpenRouter exposes an OpenAI-compatible API - just point base_url
        # at it and pass the OpenRouter key as the api_key.
        # Model names are prefixed with the provider, e.g. "openai/gpt-4o-mini",
        # "anthropic/claude-3.5-haiku", "meta-llama/llama-3.1-8b-instruct".
        _model_name = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
        _llm = ChatOpenAI(
            model=_model_name,
            temperature=0,
            api_key=_OPENROUTER_KEY,
            base_url="https://openrouter.ai/api/v1",
        )
    else:
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=_OPENAI_KEY)


def identify_sender_type(sender: str, subject: str, body: str) -> dict:
    """First triage step: is this from a customer, a supplier, a shipping
    carrier, or spam? Needed because orders@ receives all of these mixed
    together, and each needs completely different downstream handling."""
    if _USE_REAL_LLM:
        prompt = f"""Determine who sent this email: customer, supplier, carrier (shipping/logistics company), or spam.
Clues: suppliers usually discuss stock/inventory/pricing/purchase orders with the STORE.
Carriers send tracking/delivery notifications, often auto-generated.
Customers ask about their own order, refunds, or complaints.
Sender: {sender}
Subject: {subject}
Body: {body}
Respond with ONLY valid JSON: {{"sender_type": "...", "confidence": 0.0}}"""
        resp = _llm.invoke(prompt).content
        return json.loads(_strip_json_fences(resp))
    return _mock_identify_sender_type(sender, subject, body)


def classify_supplier_email(subject: str, body: str) -> dict:
    if _USE_REAL_LLM:
        prompt = f"""Classify this supplier email into exactly one category:
stock_alert, price_change, order_confirmation, invoice, shipping_delay, other.
Subject: {subject}
Body: {body}
Respond with ONLY valid JSON: {{"supplier_category": "...", "confidence": 0.0}}"""
        resp = _llm.invoke(prompt).content
        return json.loads(_strip_json_fences(resp))
    return _mock_classify_supplier(subject, body)


def classify_carrier_email(subject: str, body: str) -> dict:
    if _USE_REAL_LLM:
        prompt = f"""Classify this shipping carrier email into exactly one category:
tracking_update, delivery_exception, delivery_confirmation, other.

Important distinctions:
- "delivery_confirmation" means the package has ALREADY been delivered
  (e.g. "delivered", "successfully delivered", "left at door").
- "tracking_update" means the package is still in transit or moving toward
  delivery but NOT yet delivered (e.g. "in transit", "out for delivery",
  "arriving today", "shipped").
- "delivery_exception" means something went wrong (damaged, lost, delayed,
  failed delivery attempt).
Do not classify "out for delivery" as delivery_confirmation - it is not yet delivered.

Subject: {subject}
Body: {body}
Respond with ONLY valid JSON: {{"carrier_category": "...", "confidence": 0.0}}"""
        resp = _llm.invoke(prompt).content
        return json.loads(_strip_json_fences(resp))
    return _mock_classify_carrier(subject, body)


def assess_urgency(subject: str, body: str) -> dict:
    """Detects anger, legal/chargeback threats, or urgent distress that
    should force human escalation regardless of category confidence or
    policy match."""
    if _USE_REAL_LLM:
        prompt = f"""Does this customer email show anger, a legal/chargeback/dispute
threat, or urgent distress that should be escalated to a human regardless
of normal policy rules?
Subject: {subject}
Body: {body}
Respond with ONLY valid JSON: {{"is_urgent": true/false, "reason": "..."}}"""
        resp = _llm.invoke(prompt).content
        return json.loads(_strip_json_fences(resp))
    return _mock_assess_urgency(subject, body)


def classify(subject: str, body: str) -> dict:
    if _USE_REAL_LLM:
        prompt = f"""Classify this customer email into exactly one category:
order_status, refund_request, complaint, cancellation, spam, general_inquiry.
Also give a confidence score 0-1.
Subject: {subject}
Body: {body}
Respond with ONLY valid JSON: {{"category": "...", "confidence": 0.0}}"""
        resp = _llm.invoke(prompt).content
        return json.loads(_strip_json_fences(resp))
    return _mock_classify(subject, body)


def _strip_json_fences(text: str) -> str:
    """Some models wrap JSON in ```json ... ``` even when told not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def generate_reply(context: str, instruction: str) -> str:
    if _USE_REAL_LLM:
        prompt = f"{instruction}\n\nContext:\n{context}"
        return _llm.invoke(prompt).content
    return _mock_generate_reply(context, instruction)


# ---------------- mock fallbacks (no API key needed) ----------------

def _mock_classify(subject: str, body: str) -> dict:
    text = (subject + " " + body).lower()
    if any(w in text for w in ["refund", "money back", "return"]):
        return {"category": "refund_request", "confidence": 0.9}
    if any(w in text for w in ["cancel"]):
        return {"category": "cancellation", "confidence": 0.9}
    if any(w in text for w in ["broken", "damaged", "wrong item", "not working"]):
        return {"category": "complaint", "confidence": 0.85}
    if any(w in text for w in ["where is my order", "tracking", "shipped", "status"]):
        return {"category": "order_status", "confidence": 0.9}
    if any(w in text for w in ["unsubscribe", "% off", "winner", "click here"]):
        return {"category": "spam", "confidence": 0.95}
    return {"category": "general_inquiry", "confidence": 0.6}


def _mock_generate_reply(context: str, instruction: str) -> str:
    return f"[Auto-drafted reply based on: {instruction}]\n\n{context}"


def _mock_identify_sender_type(sender: str, subject: str, body: str) -> dict:
    text = (subject + " " + body).lower()
    domain = sender.split("@")[-1].lower() if "@" in sender else ""

    if any(w in text for w in ["unsubscribe", "% off", "winner", "click here"]):
        return {"sender_type": "spam", "confidence": 0.9}
    if any(d in domain for d in ["fedex", "ups", "dhl", "usps", "aftership", "17track"]):
        return {"sender_type": "carrier", "confidence": 0.95}
    if any(w in text for w in ["tracking number", "package", "out for delivery", "delivered", "delivery exception"]):
        return {"sender_type": "carrier", "confidence": 0.8}
    if any(d in domain for d in ["supplier", "cjdropshipping", "aliexpress", "spocket", "wholesale"]):
        return {"sender_type": "supplier", "confidence": 0.9}
    if any(w in text for w in ["stock", "inventory", "purchase order", "unit price", "moq", "restock"]):
        return {"sender_type": "supplier", "confidence": 0.8}
    return {"sender_type": "customer", "confidence": 0.7}


def _mock_classify_supplier(subject: str, body: str) -> dict:
    text = (subject + " " + body).lower()
    if any(w in text for w in ["out of stock", "sold out", "no longer available", "backorder"]):
        return {"supplier_category": "stock_alert", "confidence": 0.9}
    if any(w in text for w in ["price increase", "new price", "price change", "cost update", "will increase", "unit price"]):
        return {"supplier_category": "price_change", "confidence": 0.9}
    if any(w in text for w in ["invoice", "payment due", "bill"]):
        return {"supplier_category": "invoice", "confidence": 0.85}
    if any(w in text for w in ["order confirmed", "order received", "processing your order"]):
        return {"supplier_category": "order_confirmation", "confidence": 0.9}
    if any(w in text for w in ["delay", "backlog", "processing time"]):
        return {"supplier_category": "shipping_delay", "confidence": 0.85}
    return {"supplier_category": "other", "confidence": 0.5}


def _mock_classify_carrier(subject: str, body: str) -> dict:
    text = (subject + " " + body).lower()
    if any(w in text for w in ["exception", "delayed", "damaged in transit", "failed delivery", "lost"]):
        return {"carrier_category": "delivery_exception", "confidence": 0.9}
    if any(w in text for w in ["delivered", "successfully delivered"]):
        return {"carrier_category": "delivery_confirmation", "confidence": 0.9}
    if any(w in text for w in ["in transit", "out for delivery", "tracking update", "shipped"]):
        return {"carrier_category": "tracking_update", "confidence": 0.85}
    return {"carrier_category": "other", "confidence": 0.5}


def _mock_assess_urgency(subject: str, body: str) -> dict:
    text = (subject + " " + body).lower()

    legal_signals = ["lawyer", "attorney", "chargeback", "dispute", "sue", "lawsuit",
                      "fraud", "bbb", "better business bureau", "fraudulent", "scam", "report you"]
    anger_signals = ["furious", "unacceptable", "disgusted", "ridiculous", "worst",
                      "never again", "terrible service", "outraged", "disgraceful"]

    for w in legal_signals:
        if w in text:
            return {"is_urgent": True, "reason": f"Legal/dispute threat detected ('{w}')."}

    for w in anger_signals:
        if w in text:
            return {"is_urgent": True, "reason": f"Strong negative sentiment detected ('{w}')."}

    # crude all-caps / exclamation heuristic as a lightweight anger signal
    exclamations = body.count("!")
    caps_words = sum(1 for w in body.split() if len(w) > 3 and w.isupper())
    if exclamations >= 3 or caps_words >= 2:
        return {"is_urgent": True, "reason": "Excessive caps/exclamation marks suggest heightened emotion."}

    return {"is_urgent": False, "reason": None}
