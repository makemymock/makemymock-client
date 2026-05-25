import logging
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import aiosmtplib
import httpx
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


# ---------------------------------------------------------------------------
# Public entrypoint — picks the transport based on which credentials are set.
# ---------------------------------------------------------------------------

async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> None:
    """Send an HTML email.

    Transport selection:
      - If `BREVO_API_KEY` is set, route over Brevo's HTTPS REST API (port
        443). Most cloud hosts block outbound port 587 to fight spam, so
        SMTP fails with a connect timeout from Railway/Render/Heroku/etc.
      - Otherwise fall back to direct SMTP via aiosmtplib (works locally
        where outbound 587 is open).
    """
    if settings.BREVO_API_KEY:
        await _send_via_brevo(to_email, subject, html_body, text_body)
    else:
        await _send_via_smtp(to_email, subject, html_body, text_body)


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


# ---------------------------------------------------------------------------
# Brevo HTTPS transport
# ---------------------------------------------------------------------------

_BREVO_URL = "https://api.brevo.com/v3/smtp/email"


async def _send_via_brevo(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None,
) -> None:
    payload: dict[str, Any] = {
        "sender": {
            "email": settings.SMTP_EMAIL,    # must be verified in Brevo
            "name": settings.SMTP_FROM_NAME,
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
    }
    if text_body:
        payload["textContent"] = text_body

    headers = {
        "api-key": settings.BREVO_API_KEY,
        "accept": "application/json",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(_BREVO_URL, headers=headers, json=payload)
        if response.status_code >= 400:
            logger.error(
                "Brevo rejected email to %s (status=%s body=%s)",
                to_email, response.status_code, response.text,
            )
            response.raise_for_status()
        logger.info("Email sent to %s via Brevo (subject=%s)", to_email, subject)
    except Exception as exc:
        logger.exception("Failed to send Brevo email to %s: %s", to_email, exc)
        raise


# ---------------------------------------------------------------------------
# SMTP transport (local-dev fallback)
# ---------------------------------------------------------------------------

async def _send_via_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None,
) -> None:
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
        logger.info("Email sent to %s via SMTP (subject=%s)", to_email, subject)
    except Exception as exc:
        logger.exception("Failed to send SMTP email to %s: %s", to_email, exc)
        raise
