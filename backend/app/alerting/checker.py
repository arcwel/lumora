"""Threshold-comparison logic for mention-rate alerts.

The checker is pure read-side analysis: given a freshly-completed snapshot run,
it finds the previous completed run for the same project, pools each into an
overall mention rate, and decides whether the change clears the configured
threshold. It also surfaces the individual prompts that moved the most so alert
messages can point at *what* changed, not just the headline number.

Nothing here sends anything — :mod:`app.alerting.dispatcher` owns side effects.
The :class:`AlertEvaluation` it returns carries every field the channel
formatters need (rates, delta, direction, top movers, timestamp, dashboard
link), keeping message rendering decoupled from the comparison logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.aggregate import (
    GroupStat,
    aggregate_run,
    completed_runs,
    overall_mention_rate,
)
from app.models.project import Project
from app.models.snapshot import SnapshotRun

#: How many top-moving prompts to include in an alert message.
DEFAULT_TOP_CHANGES = 3


@dataclass(slots=True)
class PromptChange:
    """One prompt's mention-rate movement between the previous and current run."""

    prompt_id: int
    prompt_text: str
    old_rate: float | None
    new_rate: float

    @property
    def delta(self) -> float:
        """Change in mention rate; treats a brand-new prompt as a rise from 0."""

        return self.new_rate - (self.old_rate or 0.0)

    @property
    def abs_delta(self) -> float:
        return abs(self.delta)


@dataclass(slots=True)
class AlertEvaluation:
    """The result of comparing one run against its predecessor.

    Self-contained so channel formatters never need to touch the database:
    every display field (rates, delta, direction, top movers, timestamp,
    dashboard link) lives here.
    """

    project_id: int
    project_name: str
    brand_name: str
    current_run_id: int
    previous_run_id: int | None
    old_rate: float | None
    new_rate: float
    threshold: float
    timestamp: datetime | None
    dashboard_url: str | None = None
    top_changes: list[PromptChange] = field(default_factory=list)

    @property
    def delta(self) -> float:
        """Signed change in overall mention rate (new − old)."""

        return self.new_rate - (self.old_rate or 0.0)

    @property
    def delta_pp(self) -> float:
        """Signed change expressed in percentage points."""

        return self.delta * 100.0

    @property
    def is_increase(self) -> bool:
        return self.delta >= 0

    @property
    def direction(self) -> str:
        return "up" if self.is_increase else "down"

    @property
    def arrow(self) -> str:
        return "📈" if self.is_increase else "📉"

    @property
    def has_baseline(self) -> bool:
        """``True`` when there is a previous run to compare against."""

        return self.previous_run_id is not None and self.old_rate is not None

    @property
    def breached(self) -> bool:
        """Whether the change meets/exceeds the threshold and is worth alerting.

        Requires a baseline run — the very first run for a project has nothing
        to compare against and never alerts.
        """

        if not self.has_baseline:
            return False
        # Small epsilon so exact-boundary moves (e.g. 60%→50% = 10pp) count as
        # "at least the threshold" despite binary float rounding.
        return abs(self.delta) >= self.threshold - 1e-9


def format_pct(rate: float | None) -> str:
    """Render a 0–1 rate as a whole-percent string; ``None`` → an em dash."""

    return "—" if rate is None else f"{rate * 100:.0f}%"


def format_delta_pp(evaluation: "AlertEvaluation") -> str:
    """Signed percentage-point delta, e.g. ``+12pp`` or ``-23pp``."""

    sign = "+" if evaluation.delta >= 0 else "-"
    return f"{sign}{abs(evaluation.delta_pp):.0f}pp"


def alert_subject(evaluation: "AlertEvaluation") -> str:
    """One-line headline shared across channels (and the email subject)."""

    verb = "rose" if evaluation.is_increase else "dropped"
    return (
        f"{evaluation.arrow} {evaluation.brand_name} AI mention rate {verb} "
        f"{format_delta_pp(evaluation)} "
        f"({format_pct(evaluation.old_rate)} → {format_pct(evaluation.new_rate)})"
    )


def _per_prompt_rates(stats: list[GroupStat]) -> dict[int, tuple[str, float]]:
    """Pool per-(prompt, model) stats into one mention rate per prompt id."""

    totals: dict[int, list[int]] = {}
    texts: dict[int, str] = {}
    for stat in stats:
        runs, mentions = totals.setdefault(stat.prompt_id, [0, 0])
        totals[stat.prompt_id] = [runs + stat.total_runs, mentions + stat.mentions]
        texts.setdefault(stat.prompt_id, stat.prompt_text)
    return {
        pid: (texts[pid], (mentions / runs if runs else 0.0))
        for pid, (runs, mentions) in totals.items()
    }


def _top_prompt_changes(
    current: list[GroupStat],
    previous: list[GroupStat],
    *,
    limit: int = DEFAULT_TOP_CHANGES,
) -> list[PromptChange]:
    """Rank prompts by absolute mention-rate movement, largest first.

    Prompts present this run but not last are treated as a rise from 0. Prompts
    that didn't move at all are dropped so the list shows only real changes.
    """

    cur = _per_prompt_rates(current)
    prev = _per_prompt_rates(previous)

    changes: list[PromptChange] = []
    for pid, (text, new_rate) in cur.items():
        old = prev.get(pid)
        old_rate = old[1] if old is not None else None
        change = PromptChange(
            prompt_id=pid,
            prompt_text=text,
            old_rate=old_rate,
            new_rate=new_rate,
        )
        if change.abs_delta > 0:
            changes.append(change)

    changes.sort(key=lambda c: c.abs_delta, reverse=True)
    return changes[:limit]


def _dashboard_url(base_url: str | None, project_id: int) -> str | None:
    """Build a deep link to a project's analytics view, if ``base_url`` is set."""

    if not base_url:
        return None
    return f"{base_url.rstrip('/')}/projects/{project_id}/view"


def evaluate_run(
    session: Session,
    project_id: int,
    run_id: int,
    *,
    threshold: float,
    base_url: str | None = None,
    top_changes: int = DEFAULT_TOP_CHANGES,
) -> AlertEvaluation | None:
    """Compare ``run_id`` against the project's prior completed run.

    Returns an :class:`AlertEvaluation` describing the movement (whose
    ``breached`` property tells the dispatcher whether to send), or ``None`` if
    the project or run can't be found. A run with no prior completed run yields
    an evaluation with ``has_baseline=False`` (so ``breached`` is ``False``).
    """

    project = session.get(Project, project_id)
    current = session.get(SnapshotRun, run_id)
    if project is None or current is None:
        return None

    # Most-recent-first walk over completed runs to find the one before this.
    history = completed_runs(session, project_id)
    previous: SnapshotRun | None = None
    for run in reversed(history):  # newest → oldest
        if run.id < run_id:
            previous = run
            break

    current_stats = aggregate_run(session, run_id)
    new_rate = overall_mention_rate(current_stats) or 0.0

    old_rate: float | None = None
    movers: list[PromptChange] = []
    if previous is not None:
        previous_stats = aggregate_run(session, previous.id)
        old_rate = overall_mention_rate(previous_stats)
        movers = _top_prompt_changes(
            current_stats, previous_stats, limit=top_changes
        )

    return AlertEvaluation(
        project_id=project.id,
        project_name=project.name,
        brand_name=project.brand_name,
        current_run_id=run_id,
        previous_run_id=previous.id if previous is not None else None,
        old_rate=old_rate,
        new_rate=new_rate,
        threshold=threshold,
        timestamp=current.completed_at or current.started_at,
        dashboard_url=_dashboard_url(base_url, project.id),
        top_changes=movers,
    )
