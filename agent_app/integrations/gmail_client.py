"""
Gmail ingestion + sending, using the Gmail API (OAuth2).

Setup (do this once):
1. Go to https://console.cloud.google.com/ -> create/select a project.
2. Enable the "Gmail API" (APIs & Services -> Library -> search Gmail API -> Enable).
3. Configure OAuth consent screen (APIs & Services -> OAuth consent screen).
   For personal testing, "External" + add your own Gmail as a test user is fine.
4. Create credentials -> OAuth client ID -> Application type: Desktop app.
   Download the JSON, save it as `credentials.json` in the project root.
5. Run this file directly the first time: `python -m app.integrations.gmail_client`
   It will open a browser window for you to log in and grant access, then
   save a `token.json` for future runs (no browser needed after that).

For TWO inboxes (orders@ and support@), you have two options:
  a) If both are aliases/delegates on the SAME Google account, one token
     covers both - just filter by the "to" header when reading.
  b) If they're separate Google accounts, run this OAuth flow once per
     account and keep two token files (e.g. token_orders.json,
     token_support.json), then instantiate two GmailClient objects.
"""
import os
import base64
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailClient:
    def __init__(self, credentials_path="credentials.json", token_path="token.json"):
        self.token_path = token_path
        self.credentials_path = credentials_path
        self.service = self._authenticate()

    def _authenticate(self):
        creds = None
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())
        return build("gmail", "v1", credentials=creds)

    def fetch_unread(self, inbox_source: str, max_results: int = 10) -> list[dict]:
        """Returns a list of EmailState-shaped dicts for unread messages."""
        results = self.service.users().messages().list(
            userId="me", q="is:unread", maxResults=max_results
        ).execute()
        messages = results.get("messages", [])

        emails = []
        for msg_ref in messages:
            msg = self.service.users().messages().get(
                userId="me", id=msg_ref["id"], format="full"
            ).execute()
            emails.append(self._parse_message(msg, inbox_source))
        return emails

    def _parse_message(self, msg: dict, inbox_source: str) -> dict:
        headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
        body = self._extract_body(msg["payload"])

        return {
            "email_id": msg["id"],
            "inbox_source": inbox_source,
            "sender": self._extract_email_address(headers.get("from", "")),
            "subject": headers.get("subject", "(no subject)"),
            "body": body,
            "attachments": [],  # extend: walk payload["parts"] for attachment parts
        }

    def _extract_body(self, payload: dict) -> str:
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part["body"].get("data", "")
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            # fallback: recurse into nested parts (multipart/alternative etc.)
            for part in payload["parts"]:
                if "parts" in part:
                    result = self._extract_body(part)
                    if result:
                        return result
        elif payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
        return ""

    def _extract_email_address(self, from_header: str) -> str:
        if "<" in from_header:
            return from_header.split("<")[1].rstrip(">").strip()
        return from_header.strip()

    def mark_as_read(self, message_id: str) -> None:
        self.service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    def send_reply(self, to: str, subject: str, body: str) -> None:
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject if subject.startswith("Re:") else f"Re: {subject}"
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        self.service.users().messages().send(userId="me", body={"raw": raw}).execute()


if __name__ == "__main__":
    # Run this file directly once to complete the OAuth flow and generate token.json
    client = GmailClient()
    print("Authenticated. Fetching up to 5 unread emails as a test...")
    for email in client.fetch_unread("test@inbox", max_results=5):
        print(f"- {email['subject']} (from {email['sender']})")
