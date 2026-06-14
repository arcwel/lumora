"""SMTP email alert sender.

Builds an HTML (with plain-text fallback) summary and sends it over SMTP using
the stdlib :mod:`smtplib`. Requires an SMTP host plus from/to addresses; the
dispatcher skips this channel when any are unset. Auth (``SMTP_USER`` /
``SMTP_PASSWORD``) is optional for relays that don't require it.
"""

from __future__ import annotations

import html
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.alerting.checker import (
    AlertEvaluation,
    alert_subject,
    format_pct,
)

logger = logging.getLogger(__name__)

#: SMTP connection timeout (seconds).
DEFAULT_TIMEOUT_SECONDS = 15.0


@dataclass(slots=True)
class EmailConfig:
    """SMTP connection + addressing settings for outbound alert email."""

    host: str
    port: int
    sender: str
    recipient: str
    username: str | None = None
    password: str | None = None
    use_tls: bool = True


def _truncate(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_text_body(evaluation: AlertEvaluation) -> str:
    """Plain-text fallback body."""

    lines = [
        alert_subject(evaluation),
        "",
        f"Project: {evaluation.project_name} (brand: {evaluation.brand_name})",
        f"Mention rate: {format_pct(evaluation.old_rate)} -> "
        f"{format_pct(evaluation.new_rate)} ({evaluation.delta_pp:+.0f}pp)",
    ]
    if evaluation.top_changes:
        lines.append("")
        lines.append("Top changed prompts:")
        for change in evaluation.top_changes:
            lines.append(
                f"  - {_truncate(change.prompt_text)}: "
                f"{format_pct(change.old_rate)} -> {format_pct(change.new_rate)} "
                f"({change.delta * 100:+.0f}pp)"
            )
    if evaluation.timestamp is not None:
        lines.append("")
        lines.append(f"Run completed: {evaluation.timestamp:%Y-%m-%d %H:%M UTC}")
    if evaluation.dashboard_url:
        lines.append(f"Dashboard: {evaluation.dashboard_url}")
    return "\n".join(lines)


def build_html_body(evaluation: AlertEvaluation) -> str:
    """HTML summary body."""

    def esc(text: str) -> str:
        return html.escape(text, quote=True)

    rows = ""
    if evaluation.top_changes:
        items = "".join(
            f"<li><em>{esc(_truncate(c.prompt_text))}</em> — "
            f"{format_pct(c.old_rate)} &rarr; {format_pct(c.new_rate)} "
            f"({c.delta * 100:+.0f}pp)</li>"
            for c in evaluation.top_changes
        )
        rows = f"<p><strong>Top changed prompts:</strong></p><ul>{items}</ul>"

    footer_parts = []
    if evaluation.timestamp is not None:
        footer_parts.append(f"Run completed {evaluation.timestamp:%Y-%m-%d %H:%M UTC}")
    if evaluation.dashboard_url:
        footer_parts.append(
            f'<a href="{esc(evaluation.dashboard_url)}">Open dashboard</a>'
        )
    footer = (
        f'<p style="color:#666;font-size:12px">{" · ".join(footer_parts)}</p>'
        if footer_parts
        else ""
    )

    return f"""\
<html><body style="font-family:system-ui,Arial,sans-serif;color:#1a1a1a">
  <h2 style="margin-bottom:4px">{evaluation.arrow} {esc(evaluation.brand_name)} AI mention rate {evaluation.direction}</h2>
  <p><strong>{esc(evaluation.project_name)}</strong></p>
  <p style="font-size:18px">
    {format_pct(evaluation.old_rate)} &rarr;
    <strong>{format_pct(evaluation.new_rate)}</strong>
    <span style="color:{'#1a7f37' if evaluation.is_increase else '#cf222e'}">
      ({evaluation.delta_pp:+.0f}pp)
    </span>
  </p>
  {rows}
  {footer}
</body></html>"""


def build_message(evaluation: AlertEvaluation, config: EmailConfig) -> EmailMessage:
    """Assemble a multipart (text + HTML) :class:`EmailMessage`."""

    message = EmailMessage()
    message["Subject"] = alert_subject(evaluation)
    message["From"] = config.sender
    message["To"] = config.recipient
    message.set_content(build_text_body(evaluation))
    message.add_alternative(build_html_body(evaluation), subtype="html")
    return message


def send_email(
    evaluation: AlertEvaluation,
    *,
    config: EmailConfig,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Send an alert email over SMTP. Returns ``True`` on success.

    Never raises: SMTP/connection errors are logged and reported as ``False`` so
    a mail outage can't break the run or the other channels. ``smtp_use_tls``
    upgrades the connection with STARTTLS; auth is attempted only when both a
    username and password are supplied.
    """

    message = build_message(evaluation, config)
    try:
        with smtplib.SMTP(config.host, config.port, timeout=timeout) as server:
            if config.use_tls:
                server.starttls()
            if config.username and config.password:
                server.login(config.username, config.password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("Email alert failed: %s", exc)
        return False
    logger.info("Email alert sent for project %s", evaluation.project_id)
    return True
