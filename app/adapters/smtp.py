from __future__ import annotations

import smtplib
from collections.abc import Mapping
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
from typing import TypedDict

from fastapi import status

import app.settings
from app.constants.gamemodes import GameMode
from app.logging import Ansi
from app.logging import log
from app.state import services


async def send_html_email(to_address: str, subject: str, body: str) -> bool:
    if app.settings.DEBUG:
        log(f"Sending email to {to_address} with subject {subject}", Ansi.LMAGENTA)

    message = MIMEMultipart()
    message["From"] = f"osu!Peru <{app.settings.SMTP_EMAIL}>"
    message["To"] = f"<{to_address}>"
    message["Subject"] = subject
    message.attach(MIMEText(body, "html"))

    try:
        smtp = smtplib.SMTP(
            app.settings.SMTP_SERVER_HOST,
            app.settings.SMTP_SERVER_PORT,
        )
        smtp.ehlo()
        smtp.starttls()
        smtp.login(app.settings.SMTP_EMAIL, app.settings.SMTP_PASSWORD)
        smtp.sendmail(app.settings.SMTP_EMAIL, to_address, message.as_string())
        smtp.close()
    except Exception as e:
        log(f"Failed to send email to {to_address}: {e}", Ansi.LRED)
        return False

    return True
