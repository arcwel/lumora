"""Telegram Bot API alert sender.

Sends an HTML-formatted message via the Bot API ``sendMessage`` endpoint using
``httpx``. Requires a bot token and a target chat id; the dispatcher skips this
channel when either is unset.
"""

from __future__ import annotations

import html
import logging

import httpx

from app.alerting.checker import (
    AlertEvaluation,
    alert_subject,
    format_pct,
)

logger = logging.getLogger(__name__)

#: Network timeout for the Bot API call (seconds).
DEFAULT_TIMEOUT_SECONDS = 10.0

API_BASE = "https://api.telegram.org"


def _esc(text: str) -> str:
    """Escape text for Telegram's HTML parse mode."""

    return html.escape(text, quote=False)


def _truncate(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_message(evaluation: AlertEvaluation) -> str:
    """Build the HTML message body for a Telegram alert."""

    lines = [
        f"<b>{_esc(alert_subject(evaluation))}</b>",
        "",
        f"<b>Project:</b> {_esc(evaluation.project_name)} "
        f"(brand: {_esc(evaluation.brand_name)})",
        f"<b>Mention rate:</b> {format_pct(evaluation.old_rate)} → "
        f"<b>{format_pct(evaluation.new_rate)}</b> "
        f"({evaluation.arrow} {evaluation.delta_pp:+.0f}pp)",
    ]

    if evaluation.top_changes:
        lines.append("")
        lines.append("<b>Top changed prompts:</b>")
        for change in evaluation.top_changes:
            lines.append(
                f"• <i>{_esc(_truncate(change.prompt_text))}</i> — "
                f"{format_pct(change.old_rate)} → {format_pct(change.new_rate)} "
                f"({change.delta * 100:+.0f}pp)"
            )

    if evaluation.timestamp is not None:
        lines.append("")
        lines.append(f"🕒 {evaluation.timestamp:%Y-%m-%d %H:%M UTC}")
    if evaluation.dashboard_url:
        lines.append(f'<a href="{_esc(evaluation.dashboard_url)}">Open dashboard</a>')

    return "\n".join(lines)


def send_telegram(
    evaluation: AlertEvaluation,
    *,
    bot_token: str,
    chat_id: str,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Send an alert via the Telegram Bot API. Returns ``True`` on success.

    Never raises: errors are logged and reported as ``False`` so a misconfigured
    bot can't break the run or the other channels.
    """

    url = f"{API_BASE}/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": build_message(evaluation),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        if client is not None:
            response = client.post(url, json=payload)
        else:
            response = httpx.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Telegram alert failed: %s", exc)
        return False
    logger.info("Telegram alert sent for project %s", evaluation.project_id)
    return True
