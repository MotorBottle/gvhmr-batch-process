"""add retry metadata to jobs

Revision ID: 20260326_0003
Revises: 20260323_0002
Create Date: 2026-03-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260326_0003"
down_revision = "20260323_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "jobs",
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "jobs",
        sa.Column("failure_category", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_jobs_failure_category"), "jobs", ["failure_category"], unique=False)
    op.create_index(op.f("ix_jobs_next_retry_at"), "jobs", ["next_retry_at"], unique=False)
    op.alter_column("jobs", "retry_count", server_default=None)
    op.alter_column("jobs", "max_retries", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_next_retry_at"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_failure_category"), table_name="jobs")
    op.drop_column("jobs", "next_retry_at")
    op.drop_column("jobs", "failure_category")
    op.drop_column("jobs", "max_retries")
    op.drop_column("jobs", "retry_count")
