"""
Gmail API sender + draft creator.
Requires credentials.json from Google Cloud Console.
Run `python email_service/gmail_sender.py --auth` once to complete OAuth flow.
"""
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]

_service = None


def _get_service():
    global _service
    if _service:
        return _service

    creds = None
    if Path(GMAIL_TOKEN_FILE).exists():
        creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(GMAIL_CREDENTIALS_FILE).exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {GMAIL_CREDENTIALS_FILE}.\n"
                    "Download from Google Cloud Console > APIs & Services > Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GMAIL_CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(GMAIL_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    _service = build("gmail", "v1", credentials=creds)
    return _service


def _build_message(to: str, subject: str, html_body: str, text_body: str = "") -> dict:
    msg = MIMEMultipart("alternative")
    msg["to"] = to
    msg["subject"] = subject
    if text_body:
        msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}


def send_email(to: str, subject: str, html_body: str, text_body: str = "") -> bool:
    """Send email immediately. Returns True on success."""
    try:
        service = _get_service()
        message = _build_message(to, subject, html_body, text_body)
        service.users().messages().send(userId="me", body=message).execute()
        log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as e:
        log.error("Gmail send error: %s", e)
        return False


def create_draft(to: str, subject: str, html_body: str, text_body: str = "") -> str:
    """
    Create a Gmail draft (not sent). Returns draft ID.
    User can review and send from Gmail inbox.
    """
    try:
        service = _get_service()
        message = _build_message(to, subject, html_body, text_body)
        draft_body = {"message": message}
        result = service.users().drafts().create(userId="me", body=draft_body).execute()
        draft_id = result.get("id", "")
        log.info("Gmail draft created: %s | subject: %s", draft_id, subject)
        return draft_id
    except Exception as e:
        log.error("Gmail draft creation error: %s", e)
        return ""


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth", action="store_true", help="Complete Gmail OAuth flow")
    args = parser.parse_args()
    if args.auth:
        _get_service()
        print("Gmail authentication successful. token.json saved.")
