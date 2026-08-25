"""
Demo runner - simulates several inbound emails through the graph.

Run: python run_demo.py
"""
from dotenv import load_dotenv
load_dotenv()  # reads .env if present - sets SUPABASE_URL/KEY, OPENROUTER_API_KEY, etc.
               # before any app module checks os.environ, so this must run first.

from agent_app.graph.graph import graph
from langgraph.types import Command

SAMPLE_EMAILS = [
    # ---- support@ inbox: customer emails (existing flow) ----
    {
        "email_id": "e1",
        "inbox_source": "support@company.com",
        "sender": "jane@example.com",
        "subject": "Where is my order??",
        "body": "Hi, I ordered earbuds last week and haven't gotten a shipping update. What's the status?",
        "attachments": [],
    },
    {
        "email_id": "e2",
        "inbox_source": "support@company.com",
        "sender": "jane@example.com",
        "subject": "Refund please",
        "body": "These earbuds broke after 2 days, I want a refund.",
        "attachments": [],
    },
    {
        "email_id": "e3",
        "inbox_source": "support@company.com",
        "sender": "mike@example.com",
        "subject": "Refund request",
        "body": "I'd like a refund for my smart watch, it's not what I expected.",
        "attachments": [],
    },
    {
        "email_id": "e4",
        "inbox_source": "info@company.com",
        "sender": "spammer@junk.com",
        "subject": "50% off click here now!!!",
        "body": "Unsubscribe or click here to claim your winner prize.",
        "attachments": [],
    },

    # ---- orders@ inbox: mixed customer / supplier / carrier traffic ----
    {
        "email_id": "e5",
        "inbox_source": "orders@company.com",
        "sender": "supplier@cjdropshipping.com",
        "subject": "Stock Alert: Bluetooth Earbuds",
        "body": "Please be advised that Bluetooth Earbuds is now out of stock / backorder until further notice.",
        "attachments": [],
    },
    {
        "email_id": "e6",
        "inbox_source": "orders@company.com",
        "sender": "supplier@cjdropshipping.com",
        "subject": "Price Update Notice",
        "body": "Due to raw material costs, the unit price for Smart Watch will increase to $38.00 starting next month.",
        "attachments": [],
    },
    {
        "email_id": "e7",
        "inbox_source": "orders@company.com",
        "sender": "tracking@fedex.com",
        "subject": "Your package is out for delivery",
        "body": "Order #1001, tracking number TRK123456, is out for delivery today.",
        "attachments": [],
    },
    {
        "email_id": "e8",
        "inbox_source": "orders@company.com",
        "sender": "tracking@fedex.com",
        "subject": "Delivery Exception",
        "body": "We encountered a delivery exception for order #1002, tracking TRK987654: package damaged in transit.",
        "attachments": [],
    },

    # ---- New scenarios: duplicate detection + urgency override ----
    {
        "email_id": "e9",
        "inbox_source": "support@company.com",
        "sender": "jane@example.com",
        "subject": "Refund please - following up",
        "body": "Hi again, following up on my refund for the earbuds. Please process it.",
        "attachments": [],
    },
    {
        "email_id": "e10",
        "inbox_source": "support@company.com",
        "sender": "mike@example.com",
        "subject": "THIS IS UNACCEPTABLE",
        "body": "I am FURIOUS about this smart watch. If I don't get a refund I will file a chargeback and report this store to the BBB!!!",
        "attachments": [],
    },
]


def run_email(email: dict):
    config = {"configurable": {"thread_id": email["email_id"]}}
    print(f"\n{'='*70}\nPROCESSING: {email['email_id']} - {email['subject']}\n{'='*70}")

    result = graph.invoke(email, config)

    if "__interrupt__" in result:
        interrupt_info = result["__interrupt__"][0].value
        print(f"\n>> PAUSED for human input. Interrupt payload:\n{interrupt_info}\n")

        # --- Simulate a human answering in Slack ---
        simulated_human_reply = "Approved manually - go ahead and process a full refund."
        print(f">> Simulated human response: {simulated_human_reply}")

        result = graph.invoke(Command(resume=simulated_human_reply), config)

    print(f"\nFINAL STATE for {email['email_id']}: decision={result.get('decision')}, status={result.get('final_status')}")


if __name__ == "__main__":
    for email in SAMPLE_EMAILS:
        run_email(email)
