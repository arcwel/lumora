"""Lumora command-line interface.

Operate Lumora without the web dashboard: initialize the database, manage
projects and prompts, trigger snapshot runs, inspect results, set cron
schedules, and export to CSV. Installed as the ``lumora`` console script (see
``[project.scripts]`` in ``pyproject.toml``).
"""

from __future__ import annotations

import sys

import click
from sqlalchemy import select

from app.aggregate import aggregate_run, latest_run
from app.config import settings
from app.db import SessionLocal, init_db
from app.exporter import export_project_csv
from app.models.project import Project
from app.models.prompt import Prompt
from app.scheduler.runner import run_snapshot_for_project, schedule_project


def _csv_option(value: str | None) -> list[str]:
    """Parse a comma-separated CLI option into a clean list of strings."""

    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _get_project_or_exit(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise click.ClickException(f"Project {project_id} not found.")
    return project


@click.group()
@click.version_option(package_name="lumora", message="%(prog)s %(version)s")
def cli() -> None:
    """Lumora — track how your brand appears in AI assistant answers."""


# --- init ------------------------------------------------------------------
@cli.command()
def init() -> None:
    """Initialize the database (create all tables)."""

    init_db()
    click.echo(f"Database initialized at {settings.database_url}")


# --- project ---------------------------------------------------------------
@cli.group()
def project() -> None:
    """Manage projects (brands being monitored)."""


@project.command("create")
@click.option("--name", required=True, help="Human-friendly project name.")
@click.option("--brand", "brand_name", required=True, help="The brand to track.")
@click.option("--aliases", default="", help="Comma-separated brand aliases.")
@click.option("--competitors", default="", help="Comma-separated competitor names.")
@click.option("--budget", "monthly_token_budget", type=int, default=None,
              help="Optional monthly token budget.")
def project_create(
    name: str,
    brand_name: str,
    aliases: str,
    competitors: str,
    monthly_token_budget: int | None,
) -> None:
    """Create a new project."""

    with SessionLocal() as session:
        proj = Project(
            name=name,
            brand_name=brand_name,
            aliases=_csv_option(aliases),
            competitors=_csv_option(competitors),
            monthly_token_budget=monthly_token_budget,
        )
        session.add(proj)
        session.commit()
        click.echo(f"Created project #{proj.id}: {proj.name} (brand: {proj.brand_name})")


@project.command("list")
def project_list() -> None:
    """List all projects."""

    with SessionLocal() as session:
        projects = session.scalars(select(Project).order_by(Project.id)).all()
        if not projects:
            click.echo("No projects yet. Create one with: lumora project create ...")
            return
        click.echo(f"{'ID':>3}  {'ACTIVE':<6}  {'BRAND':<24}  {'CRON':<14}  NAME")
        for p in projects:
            click.echo(
                f"{p.id:>3}  {'yes' if p.is_active else 'no':<6}  "
                f"{p.brand_name[:24]:<24}  {(p.cron_schedule or '-'):<14}  {p.name}"
            )


# --- prompt ----------------------------------------------------------------
@cli.group()
def prompt() -> None:
    """Manage prompts within a project."""


@prompt.command("add")
@click.option("--project-id", required=True, type=int)
@click.option("--text", required=True, help="The prompt text to ask AI assistants.")
@click.option("--category", default=None, help="Optional category label.")
def prompt_add(project_id: int, text: str, category: str | None) -> None:
    """Add a prompt to a project."""

    with SessionLocal() as session:
        _get_project_or_exit(session, project_id)
        pr = Prompt(project_id=project_id, text=text, category=category)
        session.add(pr)
        session.commit()
        click.echo(f"Added prompt #{pr.id} to project {project_id}.")


@prompt.command("list")
@click.option("--project-id", required=True, type=int)
def prompt_list(project_id: int) -> None:
    """List prompts for a project."""

    with SessionLocal() as session:
        _get_project_or_exit(session, project_id)
        prompts = session.scalars(
            select(Prompt).where(Prompt.project_id == project_id).order_by(Prompt.id)
        ).all()
        if not prompts:
            click.echo("No prompts yet. Add one with: lumora prompt add ...")
            return
        for p in prompts:
            flag = "" if p.is_active else " [inactive]"
            cat = f" ({p.category})" if p.category else ""
            click.echo(f"#{p.id}{cat}{flag}: {p.text}")


# --- run -------------------------------------------------------------------
@cli.command()
@click.option("--project-id", type=int, default=None, help="Project to run a snapshot for.")
@click.option("--all", "run_all", is_flag=True, help="Run all active projects.")
@click.option("--runs", type=int, default=None, help="Variance passes per prompt (default 3).")
def run(project_id: int | None, run_all: bool, runs: int | None) -> None:
    """Trigger an on-demand snapshot run."""

    if run_all == (project_id is not None):
        raise click.ClickException("Provide exactly one of --project-id or --all.")

    with SessionLocal() as session:
        if run_all:
            ids = list(
                session.scalars(
                    select(Project.id).where(Project.is_active.is_(True)).order_by(Project.id)
                ).all()
            )
            if not ids:
                click.echo("No active projects to run.")
                return
        else:
            _get_project_or_exit(session, project_id)  # type: ignore[arg-type]
            ids = [project_id]  # type: ignore[list-item]

    for pid in ids:
        click.echo(f"\n=== Project {pid} ===")
        run_snapshot_for_project(pid, runs_per_prompt=runs, progress=click.echo)


# --- status ----------------------------------------------------------------
@cli.command()
@click.option("--project-id", required=True, type=int)
def status(project_id: int) -> None:
    """Show the latest snapshot results for a project."""

    with SessionLocal() as session:
        project = _get_project_or_exit(session, project_id)
        snap = latest_run(session, project_id)
        if snap is None:
            click.echo(
                f"No snapshot runs yet for project {project_id}. "
                f"Try: lumora run --project-id {project_id}"
            )
            return

        started = snap.started_at.isoformat() if snap.started_at else "n/a"
        click.echo(f"Project {project_id}: {project.name} (brand: {project.brand_name})")
        click.echo(
            f"Latest run #{snap.id} · status={snap.status.value} · "
            f"started={started} · models={snap.provider_model or '-'} · N={snap.n_runs}"
        )
        if snap.error:
            click.echo(f"  error: {snap.error}")

        stats = aggregate_run(session, snap.id)
        if not stats:
            click.echo("  (no answers recorded)")
            return

        click.echo("")
        click.echo(f"  {'PROMPT':<8} {'MODEL':<28} {'MENTION RATE':<14} {'AVG POS':<8} SENTIMENT")
        for s in stats:
            rate = f"{s.mentions}/{s.total_runs} ({s.mention_rate * 100:.0f}%)"
            pos = f"{s.avg_position:.1f}" if s.avg_position is not None else "-"
            sent = ",".join(sorted(set(s.sentiments))) if s.sentiments else "-"
            click.echo(f"  #{s.prompt_id:<7} {s.model[:28]:<28} {rate:<14} {pos:<8} {sent}")


# --- export ----------------------------------------------------------------
@cli.command()
@click.option("--project-id", required=True, type=int)
@click.option("--format", "fmt", type=click.Choice(["csv"]), default="csv")
@click.option("--output", "-o", type=click.Path(dir_okay=False, writable=True), default=None,
              help="Write to a file instead of stdout.")
def export(project_id: int, fmt: str, output: str | None) -> None:
    """Export a project's results (one row per answer)."""

    with SessionLocal() as session:
        _get_project_or_exit(session, project_id)
        data = export_project_csv(session, project_id)

    if output:
        with open(output, "w", newline="", encoding="utf-8") as fh:
            fh.write(data)
        click.echo(f"Wrote {output}")
    else:
        click.echo(data, nl=False)


# --- schedule --------------------------------------------------------------
@cli.command()
@click.option("--project-id", required=True, type=int)
@click.option("--cron", required=True, help='Cron expression, e.g. "0 9 * * 1" (Mondays 09:00).')
def schedule(project_id: int, cron: str) -> None:
    """Set a project's recurring cron schedule."""

    with SessionLocal() as session:
        _get_project_or_exit(session, project_id)
    try:
        schedule_project(project_id, cron)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Scheduled project {project_id} with cron {cron!r}. "
        "It will run when the app's scheduler is active."
    )


def main() -> None:  # pragma: no cover - console-script entry point
    """Console-script entry point."""

    cli()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(cli())
