from fastapi_mail import ConnectionConfig, FastMail, MessageSchema
from pydantic import EmailStr
from typing import List

conf = ConnectionConfig(
    MAIL_USERNAME="no-reply@yourdomain.com",
    MAIL_PASSWORD="YOUR_IONOS_PASSWORD",
    MAIL_FROM="no-reply@yourdomain.com",
    MAIL_PORT=587,
    MAIL_SERVER="smtp.ionos.co.uk",
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
)

fastmail = FastMail(conf)

async def send_email(
    subject: str,
    recipients: List[EmailStr],
    body: str,
):
    message = MessageSchema(
        subject=subject,
        recipients=recipients,
        body=body,
        subtype="html",
    )
    await fastmail.send_message(message)