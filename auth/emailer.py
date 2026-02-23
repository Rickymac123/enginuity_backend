# auth/emailer.py

import os
import smtplib
from email.message import EmailMessage


SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
MAIL_FROM = os.getenv("MAIL_FROM", SMTP_USER)


def send_email(to_email: str, subject: str, html: str) -> None:
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS or not MAIL_FROM:
        raise RuntimeError("SMTP not configured correctly.")

    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.set_content("Your email client does not support HTML.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"❌ Email send failed: {e}")
        raise