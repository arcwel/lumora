"""add n_runs/error, project cron_schedule, answer run_index

Adds the columns introduced for N=3 variance runs, multi-provider snapshots,
and per-project cron scheduling.

Revision ID: 8f2a1c4b9d30
Revises: 51801cd4dc45
Create Date: 2026-06-12 20:10:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f2a1c4b9d30"
down_revision: str | None = "51801cd4dc45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cron_schedule", sa.String(length=128), nullable=True))

    with op.batch_alter_table("snapshot_runs", schema=None) as batch_op:
        # Widen provider_model to hold a comma-separated multi-provider list.
        batch_op.alter_column(
            "provider_model",
            existing_type=sa.String(length=128),
            type_=sa.String(length=512),
            existing_nullable=True,
        )
        batch_op.add_column(
            sa.Column("n_runs", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("error", sa.Text(), nullable=True))

    with op.batch_alter_table("answers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("run_index", sa.Integer(), nullable=False, server_default="1")
        )


def downgrade() -> None:
    with op.batch_alter_table("answers", schema=None) as batch_op:
        batch_op.drop_column("run_index")

    with op.batch_alter_table("snapshot_runs", schema=None) as batch_op:
        batch_op.drop_column("error")
        batch_op.drop_column("n_runs")
        batch_op.alter_column(
            "provider_model",
            existing_type=sa.String(length=512),
            type_=sa.String(length=128),
            existing_nullable=True,
        )

    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_column("cron_schedule")
