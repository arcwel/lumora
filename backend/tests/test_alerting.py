"""Tests for threshold-change alerting.

Exercises the pure comparison logic in :mod:`app.alerting.checker` and the
fan-out decisions in :mod:`app.alerting.dispatcher`. All network/SMTP sending is
mocked — no real Slack/Telegram/email calls are made.
"""

from __future__ import annotations

import pytest

from app.alerting.checker import alert_subject, evaluate_run, format_delta_pp
from app.alerting.dispatcher import dispatch_alert
from app.config import Settings
from app.models.answer import Answer
from app.models.score import Score, Sentiment
from app.models.snapshot import SnapshotRun, SnapshotStatus


def _make_run(session, project, per_prompt):
    """Create a COMPLETED run. ``per_prompt`` maps a prompt index → (n, mentions).

    For each listed prompt, ``n`` answers are created with the first
    ``mentions`` of them scored as brand-mentioned.
    """

    run = SnapshotRun(
        project_id=project.id, status=SnapshotStatus.COMPLETED, n_runs=3
    )
    session.add(run)
    session.commit()
    for prompt_idx, (n, mentions) in per_prompt.items():
        prompt = project.prompts[prompt_idx]
        for i in range(1, n + 1):
            ans = Answer(
                snapshot_run_id=run.id,
                prompt_id=prompt.id,
                provider="openai",
                model="gpt-4o-mini",
                raw_response=f"answer {i}",
                run_index=i,
            )
            session.add(ans)
            session.commit()
            mentioned = i <= mentions
            session.add(
                Score(
                    answer_id=ans.id,
                    brand_mentioned=mentioned,
                    mention_position=1 if mentioned else None,
                    sentiment=Sentiment.POSITIVE if mentioned else None,
                    cited_sources=[],
                    judge_model="judge",
                    judge_prompt_hash="h",
                )
            )
    session.commit()
    return run


# --- checker -------------------------------------------------------------


def test_first_run_has_no_baseline(db_session, project):
    run = _make_run(db_session, project, {0: (3, 3)})
    ev = evaluate_run(db_session, project.id, run.id, threshold=0.10)
    assert ev is not None
    assert ev.has_baseline is False
    assert ev.breached is False
    assert ev.previous_run_id is None


def test_decrease_above_threshold_breaches(db_session, project):
    _make_run(db_session, project, {0: (3, 3), 1: (3, 3)})  # 100%
    cur = _make_run(db_session, project, {0: (3, 0), 1: (3, 0)})  # 0%
    ev = evaluate_run(db_session, project.id, cur.id, threshold=0.10)
    assert ev.old_rate == 1.0
    assert ev.new_rate == 0.0
    assert ev.breached is True
    assert ev.is_increase is False
    assert ev.direction == "down"
    assert ev.arrow == "📉"
    assert round(ev.delta_pp) == -100


def test_increase_above_threshold_breaches(db_session, project):
    _make_run(db_session, project, {0: (3, 0), 1: (3, 0)})  # 0%
    cur = _make_run(db_session, project, {0: (3, 3), 1: (3, 3)})  # 100%
    ev = evaluate_run(db_session, project.id, cur.id, threshold=0.10)
    assert ev.breached is True
    assert ev.is_increase is True
    assert ev.direction == "up"
    assert ev.arrow == "📈"


def test_small_change_below_threshold_does_not_breach(db_session, project):
    # 6/6 = 100% then 5/6 ≈ 83% → ~17pp... pick values under threshold instead.
    _make_run(db_session, project, {0: (10, 6)})  # 60%
    cur = _make_run(db_session, project, {0: (10, 5)})  # 50%, delta -10pp
    ev = evaluate_run(db_session, project.id, cur.id, threshold=0.15)
    assert ev.has_baseline is True
    assert ev.breached is False


def test_threshold_boundary_is_inclusive(db_session, project):
    _make_run(db_session, project, {0: (10, 6)})  # 60%
    cur = _make_run(db_session, project, {0: (10, 5)})  # 50%, delta exactly -10pp
    ev = evaluate_run(db_session, project.id, cur.id, threshold=0.10)
    assert round(ev.delta_pp) == -10
    assert ev.breached is True


def test_top_changed_prompts_ranked_by_movement(db_session, project):
    # prompt0 stays flat (100%→100%); prompt1 collapses (100%→0%).
    _make_run(db_session, project, {0: (3, 3), 1: (3, 3)})
    cur = _make_run(db_session, project, {0: (3, 3), 1: (3, 0)})
    ev = evaluate_run(db_session, project.id, cur.id, threshold=0.10)
    assert ev.breached is True
    # Only the prompt that actually moved is reported.
    assert len(ev.top_changes) == 1
    top = ev.top_changes[0]
    assert top.prompt_id == project.prompts[1].id
    assert top.old_rate == 1.0
    assert top.new_rate == 0.0


def test_dashboard_url_built_from_base_url(db_session, project):
    _make_run(db_session, project, {0: (3, 0)})
    cur = _make_run(db_session, project, {0: (3, 3)})
    ev = evaluate_run(
        db_session,
        project.id,
        cur.id,
        threshold=0.10,
        base_url="https://lumora.example.com/",
    )
    assert ev.dashboard_url == f"https://lumora.example.com/projects/{project.id}/view"


def test_subject_and_delta_formatting(db_session, project):
    _make_run(db_session, project, {0: (3, 0)})
    cur = _make_run(db_session, project, {0: (3, 3)})
    ev = evaluate_run(db_session, project.id, cur.id, threshold=0.10)
    assert format_delta_pp(ev) == "+100pp"
    subject = alert_subject(ev)
    assert "rose" in subject
    assert "0% → 100%" in subject


def test_evaluate_run_missing_returns_none(db_session, project):
    assert evaluate_run(db_session, 999, 999, threshold=0.10) is None


# --- dispatcher ----------------------------------------------------------


def _spy_sends(monkeypatch):
    """Patch the three channel senders to record calls instead of sending."""

    calls: dict[str, list] = {"slack": [], "email": [], "telegram": []}

    def fake_slack(ev, **kw):
        calls["slack"].append((ev, kw))
        return True

    def fake_email(ev, **kw):
        calls["email"].append((ev, kw))
        return True

    def fake_telegram(ev, **kw):
        calls["telegram"].append((ev, kw))
        return True

    monkeypatch.setattr("app.alerting.dispatcher.send_slack", fake_slack)
    monkeypatch.setattr("app.alerting.dispatcher.send_email", fake_email)
    monkeypatch.setattr("app.alerting.dispatcher.send_telegram", fake_telegram)
    return calls


def test_dispatch_skips_when_no_channels_configured(db_session, project, monkeypatch):
    calls = _spy_sends(monkeypatch)
    _make_run(db_session, project, {0: (3, 0)})
    cur = _make_run(db_session, project, {0: (3, 3)})  # breaches
    settings = Settings(alert_threshold=0.10)  # no channel creds
    result = dispatch_alert(db_session, project.id, cur.id, settings=settings)
    assert result.triggered is True
    assert result.attempted == []
    assert all(not v for v in calls.values())


def test_dispatch_sends_to_all_configured_channels(db_session, project, monkeypatch):
    calls = _spy_sends(monkeypatch)
    _make_run(db_session, project, {0: (3, 0)})
    cur = _make_run(db_session, project, {0: (3, 3)})  # breaches
    settings = Settings(
        alert_threshold=0.10,
        slack_webhook_url="https://hooks.slack.com/services/x",
        smtp_host="smtp.example.com",
        alert_email_from="from@example.com",
        alert_email_to="to@example.com",
        telegram_bot_token="123:abc",
        telegram_chat_id="42",
    )
    result = dispatch_alert(db_session, project.id, cur.id, settings=settings)
    assert set(result.attempted) == {"slack", "email", "telegram"}
    assert set(result.sent) == {"slack", "email", "telegram"}
    assert len(calls["slack"]) == 1
    assert len(calls["email"]) == 1
    assert len(calls["telegram"]) == 1


def test_dispatch_does_not_send_when_not_breached(db_session, project, monkeypatch):
    calls = _spy_sends(monkeypatch)
    _make_run(db_session, project, {0: (10, 6)})  # 60%
    cur = _make_run(db_session, project, {0: (10, 5)})  # 50%, -10pp
    settings = Settings(
        alert_threshold=0.20,  # 10pp move doesn't clear 20pp threshold
        slack_webhook_url="https://hooks.slack.com/services/x",
    )
    result = dispatch_alert(db_session, project.id, cur.id, settings=settings)
    assert result.triggered is False
    assert result.attempted == []
    assert calls["slack"] == []


def test_dispatch_partial_email_config_skips_email(db_session, project, monkeypatch):
    calls = _spy_sends(monkeypatch)
    _make_run(db_session, project, {0: (3, 0)})
    cur = _make_run(db_session, project, {0: (3, 3)})
    settings = Settings(
        alert_threshold=0.10,
        smtp_host="smtp.example.com",  # missing from/to addresses
    )
    result = dispatch_alert(db_session, project.id, cur.id, settings=settings)
    assert "email" not in result.attempted
    assert calls["email"] == []


def test_dispatch_first_run_is_noop(db_session, project, monkeypatch):
    calls = _spy_sends(monkeypatch)
    run = _make_run(db_session, project, {0: (3, 3)})  # only run, no baseline
    settings = Settings(
        alert_threshold=0.10,
        slack_webhook_url="https://hooks.slack.com/services/x",
    )
    result = dispatch_alert(db_session, project.id, run.id, settings=settings)
    assert result.triggered is False
    assert calls["slack"] == []


def test_channel_failure_isolated(db_session, project, monkeypatch):
    """A failing channel is reported but doesn't suppress the others."""

    calls = _spy_sends(monkeypatch)

    def failing_slack(ev, **kw):
        calls["slack"].append((ev, kw))
        return False  # reports failure, doesn't raise

    monkeypatch.setattr("app.alerting.dispatcher.send_slack", failing_slack)
    _make_run(db_session, project, {0: (3, 0)})
    cur = _make_run(db_session, project, {0: (3, 3)})
    settings = Settings(
        alert_threshold=0.10,
        slack_webhook_url="https://hooks.slack.com/services/x",
        telegram_bot_token="123:abc",
        telegram_chat_id="42",
    )
    result = dispatch_alert(db_session, project.id, cur.id, settings=settings)
    assert set(result.attempted) == {"slack", "telegram"}
    assert "slack" not in result.sent
    assert "telegram" in result.sent
