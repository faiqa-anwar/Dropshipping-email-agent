"""
Slack + email delivery.

Email sending uses real Gmail if a GmailClient has been registered via
register_gmail_client() (see run_live.py) - otherwise it just prints,
which is what keeps run_demo.py working with zero setup.

Slack still prints for now; swap post_to_slack for
slack_sdk.WebClient(token=...).chat_postMessage(channel=..., text=...)
when you're ready to wire it up for real.
"""

_gmail_clients: dict = {}   # inbox_source -> GmailClient instance


def register_gmail_client(inbox_source: str, client) -> None:
    """Call this once per inbox at startup (see run_live.py) to make
    send_email actually deliver through that inbox's Gmail account."""
    _gmail_clients[inbox_source] = client


def post_to_slack(channel: str, text: str) -> None:
    print(f"\n[SLACK -> {channel}]\n{text}\n")


def send_email(to: str, subject: str, body: str, inbox_source: str | None = None) -> None:
    client = _gmail_clients.get(inbox_source) if inbox_source else None
    if client:
        client.send_reply(to, subject, body)
        print(f"[GMAIL] Sent real reply to {to} via {inbox_source}")
        return
    print(f"\n[EMAIL -> {to}] Subject: {subject}\n{body}\n")


def log_decision(record: dict) -> None:
    """Audit log. Writes to Supabase's email_decisions table if configured,
    otherwise prints and mirrors into the in-memory dedup log."""
    from agent_app.integrations import supabase_store, dedup_check
    if supabase_store.SUPABASE_ENABLED:
        supabase_store.log_decision(record)
        return
    dedup_check.record_for_dedup_check(record)
    import json
    print(f"\n[AUDIT LOG] {json.dumps(record, default=str, indent=2)}\n")
