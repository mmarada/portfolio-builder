"""
SMTP email sender as fallback when Gmail OAuth is not configured.
"""
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, html_body: str, text_body: str = "") -> bool:
    if not SMTP_USER or not SMTP_PASSWORD:
        log.error("SMTP credentials not configured")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [to], msg.as_string())

        log.info("SMTP email sent to %s: %s", to, subject)
        return True
    except Exception as e:
        log.error("SMTP send error: %s", e)
        return False
