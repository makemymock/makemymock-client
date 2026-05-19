import logging
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config.settings import settings

logger = logging.getLogger(__name__)

# Jinja2 env pointing at the authentication module's email_templates folder.
_TEMPLATE_DIR = (
    Path(__file__).resolve().parent.parent
    / "modules"
    / "authentication"
    / "email_templates"
)
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)


def render_template(template_name: str, context: dict[str, Any]) -> str:
    template = _jinja_env.get_template(template_name)
    return template.render(**context)


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> None:
    """Send an HTML email via SMTP using STARTTLS by default."""
    message = EmailMessage()
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_EMAIL}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text_body or "This email requires an HTML-capable client.")
    message.add_alternative(html_body, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_EMAIL,
            password=settings.SMTP_PASSWORD,
            start_tls=settings.SMTP_USE_TLS,
            timeout=15,
        )
        logger.info("Email sent to %s (subject=%s)", to_email, subject)
    except Exception as exc:
        # Don't leak SMTP errors to the API caller; log and re-raise as generic.
        logger.exception("Failed to send email to %s: %s", to_email, exc)
        raise


async def send_otp_email(to_email: str, username: str, otp_code: str) -> None:
    html = render_template(
        "otp.html",
        {
            "username": username,
            "otp_code": otp_code,
            "expiry_minutes": settings.OTP_EXPIRY_MINUTES,
            "app_name": settings.APP_NAME,
        },
    )
    text = (
        f"Hi {username},\n\n"
        f"Your {settings.APP_NAME} verification code is: {otp_code}\n"
        f"This code expires in {settings.OTP_EXPIRY_MINUTES} minutes.\n"
    )
    await send_email(
        to_email=to_email,
        subject=f"Your {settings.APP_NAME} verification code",
        html_body=html,
        text_body=text,
    )
