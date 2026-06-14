"""Slack incoming-webhook alert sender.

Posts a Block Kit message to a Slack incoming webhook via ``httpx``. The webhook
URL is the only credential; when it's unset the dispatcher never calls this.
"""

from __future__ import annotations

import logging

import httpx

from app.alerting.checker import (
    AlertEvaluation,
    alert_subject,
    format_pct,
)

logger = logging.getLogger(__name__)

#: Network timeout for the webhook POST (seconds).
DEFAULT_TIMEOUT_SECONDS = 10.0


def _truncate(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_payload(evaluation: AlertEvaluation) -> dict:
    """Build the Slack Block Kit JSON payload for an alert."""

    headline = alert_subject(evaluation)

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": _truncate(headline, 150), "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Project:*\n{evaluation.project_name}"},
                {"type": "mrkdwn", "text": f"*Brand:*\n{evaluation.brand_name}"},
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*Mention rate:*\n{format_pct(evaluation.old_rate)} → "
                        f"*{format_pct(evaluation.new_rate)}*"
                    ),
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Change:*\n{evaluation.arrow} {evaluation.delta_pp:+.0f}pp",
                },
            ],
        },
    ]

    if evaluation.top_changes:
        lines = [
            f"• _{_truncate(c.prompt_text)}_ — {format_pct(c.old_rate)} → "
            f"{format_pct(c.new_rate)} ({c.delta * 100:+.0f}pp)"
            for c in evaluation.top_changes
        ]
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Top changed prompts:*\n" + "\n".join(lines)},
            }
        )

    context_elements: list[dict] = []
    if evaluation.timestamp is not None:
        context_elements.append(
            {"type": "mrkdwn", "text": f"🕒 {evaluation.timestamp:%Y-%m-%d %H:%M UTC}"}
        )
    if evaluation.dashboard_url:
        context_elements.append(
            {"type": "mrkdwn", "text": f"<{evaluation.dashboard_url}|Open dashboard>"}
        )
    if context_elements:
        blocks.append({"type": "context", "elements": context_elements})

    # ``text`` is the notification fallback (and what shows in push previews).
    return {"text": headline, "blocks": blocks}


def send_slack(
    evaluation: AlertEvaluation,
    *,
    webhook_url: str,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """POST an alert to a Slack webhook. Returns ``True`` on a 2xx response.

    Never raises: network/HTTP errors are logged and reported as ``False`` so a
    failing channel can't break the snapshot run or the other channels.
    """

    payload = build_payload(evaluation)
    try:
        if client is not None:
            response = client.post(webhook_url, json=payload)
        else:
            response = httpx.post(webhook_url, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Slack alert failed: %s", exc)
        return False
    logger.info("Slack alert sent for project %s", evaluation.project_id)
    return True
