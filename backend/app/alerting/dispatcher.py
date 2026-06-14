"""Orchestrates threshold checking and fan-out across notification channels.

:func:`dispatch_alert` is the single entry point the runner calls after a
snapshot completes. It evaluates the mention-rate change and, when the threshold
is breached, sends to every *configured* channel (Slack, email, Telegram).
Unconfigured channels are skipped silently; a failure in one channel is logged
and never propagates, so alerting can never fail a snapshot run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.alerting.checker import AlertEvaluation, evaluate_run
from app.alerting.email import EmailConfig, send_email
from app.alerting.slack import send_slack
from app.alerting.telegram import send_telegram
from app.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DispatchResult:
    """Outcome of a dispatch attempt, for logging/CLI feedback and tests."""

    evaluation: AlertEvaluation | None
    #: Channels that were configured and attempted (regardless of success).
    attempted: list[str] = field(default_factory=list)
    #: Channels that reported a successful send.
    sent: list[str] = field(default_factory=list)

    @property
    def triggered(self) -> bool:
        """Whether the threshold was breached (an alert was warranted)."""

        return self.evaluation is not None and self.evaluation.breached


def _email_config(settings: Settings) -> EmailConfig | None:
    """Build an :class:`EmailConfig` if the required SMTP fields are present."""

    if not (settings.smtp_host and settings.alert_email_from and settings.alert_email_to):
        return None
    return EmailConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        sender=settings.alert_email_from,
        recipient=settings.alert_email_to,
        username=settings.smtp_user,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
    )


def dispatch_alert(
    session: Session,
    project_id: int,
    run_id: int,
    *,
    settings: Settings | None = None,
) -> DispatchResult:
    """Evaluate a finished run and notify every configured channel on a breach.

    Safe to call unconditionally after any completed run: returns early (with an
    empty :class:`DispatchResult`) when there's no baseline or the change is
    below threshold. Each channel send is isolated so one failure can't suppress
    the others or disturb the caller.
    """

    settings = settings or default_settings

    evaluation = evaluate_run(
        session,
        project_id,
        run_id,
        threshold=settings.alert_threshold,
        base_url=settings.base_url,
    )
    result = DispatchResult(evaluation=evaluation)

    if evaluation is None or not evaluation.breached:
        return result

    logger.info(
        "Mention-rate threshold breached for project %s (run %s): %.0f%% -> %.0f%% (%+.0fpp)",
        project_id,
        run_id,
        (evaluation.old_rate or 0.0) * 100,
        evaluation.new_rate * 100,
        evaluation.delta_pp,
    )

    if settings.slack_webhook_url:
        result.attempted.append("slack")
        if send_slack(evaluation, webhook_url=settings.slack_webhook_url):
            result.sent.append("slack")

    email_config = _email_config(settings)
    if email_config is not None:
        result.attempted.append("email")
        if send_email(evaluation, config=email_config):
            result.sent.append("email")

    if settings.telegram_bot_token and settings.telegram_chat_id:
        result.attempted.append("telegram")
        if send_telegram(
            evaluation,
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
        ):
            result.sent.append("telegram")

    if not result.attempted:
        logger.info(
            "Alert threshold breached for project %s but no channels are configured",
            project_id,
        )

    return result
