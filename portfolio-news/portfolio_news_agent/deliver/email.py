"""SMTP delivery of the brief as a multipart HTML+text email."""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import Config

log = logging.getLogger(__name__)


def send(cfg: Config, subject: str, html_body: str, text_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg.email_from
    msg["To"] = cfg.email_to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as server:
        server.starttls()
        server.login(cfg.smtp_username, cfg.smtp_password)
        server.send_message(msg)
    log.info("email sent to %s", cfg.email_to)
