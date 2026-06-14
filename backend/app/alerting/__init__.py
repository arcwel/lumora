"""Threshold-change alerting across Slack, email, and Telegram.

After a snapshot run completes the runner calls :func:`dispatch_alert`, which
compares the run's overall mention rate against the previous completed run and,
when the change clears the configured threshold, fans the alert out to every
configured notification channel. Channels with missing credentials are skipped
silently, so alerting is fully opt-in per channel.
"""

from __future__ import annotations

from app.alerting.checker import (
    AlertEvaluation,
    PromptChange,
    evaluate_run,
)
from app.alerting.dispatcher import DispatchResult, dispatch_alert

__all__ = [
    "AlertEvaluation",
    "PromptChange",
    "evaluate_run",
    "DispatchResult",
    "dispatch_alert",
]
