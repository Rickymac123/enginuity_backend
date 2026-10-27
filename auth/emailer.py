"""Transactional mail: Microsoft Graph app authentication or TLS SMTP."""
import os
import ssl
import smtplib
from email.message import EmailMessage
from urllib.parse import quote
import httpx


def send_email(to_email: str, subject: str, html: str) -> None:
    provider = os.getenv("MAIL_PROVIDER", "smtp")
    sender = os.getenv("MAIL_FROM") or os.getenv("SMTP_USER")
    if not sender:
        raise RuntimeError("MAIL_FROM is required")
    if provider == "microsoft_graph":
        tenant = os.getenv("MS_TENANT_ID")
        client_id = os.getenv("MS_CLIENT_ID")
        client_secret = os.getenv("MS_CLIENT_SECRET")
        if not all((tenant, client_id, client_secret)):
            raise RuntimeError("Microsoft Graph mail credentials are incomplete")
        with httpx.Client(timeout=10) as client:
            token = client.post(f"https://login.microsoftonline.com/{quote(tenant, safe='')}/oauth2/v2.0/token", data={
                "client_id": client_id, "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
            })
            if token.status_code != 200:
                raise RuntimeError(f"Microsoft mail authentication failed ({token.status_code})")
            response = client.post(f"https://graph.microsoft.com/v1.0/users/{quote(sender, safe='')}/sendMail",
                headers={"Authorization": f"Bearer {token.json()['access_token']}"}, json={"message": {
                    "subject": subject, "body": {"contentType": "HTML", "content": html},
                    "toRecipients": [{"emailAddress": {"address": to_email}}],
                }})
            if response.status_code != 202:
                raise RuntimeError(f"Microsoft mail submission failed ({response.status_code})")
        return
    if provider != "smtp":
        raise RuntimeError("Unsupported MAIL_PROVIDER")
    host, user, password = (os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"))
    if not all((host, user, password)):
        raise RuntimeError("SMTP credentials are incomplete")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, to_email, subject
    msg.set_content("Please view the HTML version of this ContractPros email for the requested link.")
    msg.add_alternative(html, subtype="html")
    port = int(os.getenv("SMTP_PORT", "587"))
    transport = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with transport(host, port, timeout=10) as server:
        if port != 465:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
        server.login(user, password)
        server.send_message(msg)
