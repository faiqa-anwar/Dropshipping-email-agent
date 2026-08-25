"""
Live runner - polls your real Gmail inbox(es) and runs each unread email
through the graph. Run repeatedly on a schedule (cron, Task Scheduler, or
a simple while-loop with a sleep) for continuous processing.

SETUP FIRST:
1. Follow the setup steps at the top of app/integrations/gmail_client.py
   to create credentials.json and generate a token.
2. If orders@ and support@ are on the SAME Google account (aliases),
   you only need one token - see the ONE_ACCOUNT section below.
3. If they're separate Google accounts, run the OAuth flow once per
   account (rename the resulting token.json each time) and use the
   TWO_ACCOUNTS section instead.

Run: python run_live.py
"""
from dotenv import load_dotenv
load_dotenv()

from agent_app.graph.graph import build_graph
from agent_app.integrations.gmail_client import GmailClient
from agent_app.integrations import notify_clients
from langgraph.types import Command
from langgraph.checkpoint.sqlite import SqliteSaver

# ---- Pick ONE of the two setups below ----

# --- ONE_ACCOUNT: both inboxes are aliases/labels on one Gmail account ---
gmail = GmailClient(credentials_path="credentials.json", token_path="token.json")
INBOXES = {
    "support@company.com": gmail,
    "orders@company.com": gmail,
}

# --- TWO_ACCOUNTS: separate Google accounts, uncomment and adjust ---
# gmail_support = GmailClient(credentials_path="credentials.json", token_path="token_support.json")
# gmail_orders = GmailClient(credentials_path="credentials.json", token_path="token_orders.json")
# INBOXES = {
#     "support@company.com": gmail_support,
#     "orders@company.com": gmail_orders,
# }

for inbox_source, client in INBOXES.items():
    notify_clients.register_gmail_client(inbox_source, client)


def process_inbox(graph, inbox_source: str, client: GmailClient):
    emails = client.fetch_unread(inbox_source, max_results=10)
    print(f"\n{inbox_source}: {len(emails)} unread email(s)")

    for email in emails:
        config = {"configurable": {"thread_id": email["email_id"]}}
        print(f"\nProcessing: {email['subject']} (from {email['sender']})")

        result = graph.invoke(email, config)

        if "__interrupt__" in result:
            # Left paused intentionally - a human resolves this via Slack,
            # then a separate resume step (see resume_escalation below)
            # continues the graph. Don't mark as read yet since it's not
            # done processing.
            print(">> Escalated - waiting on human response, left as unread.")
            continue

        # Fully handled (auto_reply / auto_refund / ignore) - mark as read
        client.mark_as_read(email["email_id"])
        print(f">> Done: {result.get('decision')}")


def resume_escalation(graph, email_id: str, human_response: str):
    """Call this once a human has responded (e.g. typed a reply in Slack).
    thread_id must match the original email_id so LangGraph resumes the
    correct paused run."""
    config = {"configurable": {"thread_id": email_id}}
    result = graph.invoke(Command(resume=human_response), config)
    print(f"Resumed {email_id}: {result.get('final_status')}")
    return result


if __name__ == "__main__":
    # Persistent checkpointer - so a paused escalation from a previous run
    # of this script is still there next time you run it (e.g. via cron).
    with SqliteSaver.from_conn_string("dropship_agent.db") as checkpointer:
        graph = build_graph(checkpointer)
        for inbox_source, client in INBOXES.items():
            process_inbox(graph, inbox_source, client)
