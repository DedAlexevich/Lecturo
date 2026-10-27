import asyncio
import logging
import smtplib
from email.message import EmailMessage
from urllib.parse import urlsplit

from app.core.config import get_settings

logger = logging.getLogger(__name__)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def mask_email(address: str) -> str:
    name, _, domain = address.rpartition("@")
    if not name:
        return "***"
    return f"{name[0]}***@{domain}"


def is_local_public_url() -> bool:
    host = urlsplit(get_settings().public_url).hostname or ""
    return host in LOCAL_HOSTS or host.endswith(".localhost")


def deliver(message: EmailMessage) -> None:
    settings = get_settings()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            login_and_send(smtp, message)
        return
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        login_and_send(smtp, message)


def login_and_send(smtp: smtplib.SMTP, message: EmailMessage) -> None:
    settings = get_settings()
    if settings.smtp_user:
        smtp.login(settings.smtp_user, settings.smtp_password)
    smtp.send_message(message)


async def deliver_mail(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        if is_local_public_url():
            logger.info("Письмо для %s: %s\n%s", to, subject, body)
        else:
            logger.info("Письмо для %s: %s", mask_email(to), subject)
        return
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    await asyncio.to_thread(deliver, message)


async def send_mail(to: str, subject: str, body: str) -> None:
    try:
        await deliver_mail(to, subject, body)
    except Exception:
        logger.exception("Не удалось отправить письмо для %s", mask_email(to))


async def send_verification_mail(to: str, token: str) -> None:
    link = f"{get_settings().public_url.rstrip('/')}/verify-email?token={token}"
    await send_mail(
        to,
        "Подтверждение почты в Lecturo",
        f"Чтобы подтвердить почту, перейдите по ссылке:\n{link}\n\n"
        "Ссылка действует 24 часа. Если вы не регистрировались, просто проигнорируйте письмо.",
    )


async def send_password_reset_mail(to: str, token: str) -> None:
    link = f"{get_settings().public_url.rstrip('/')}/reset-password?token={token}"
    await send_mail(
        to,
        "Сброс пароля в Lecturo",
        f"Чтобы задать новый пароль, перейдите по ссылке:\n{link}\n\n"
        "Ссылка действует 1 час. Если вы не запрашивали сброс, просто проигнорируйте письмо.",
    )
