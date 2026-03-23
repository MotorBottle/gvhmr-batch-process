"""add use_dpvo to jobs

Revision ID: 20260323_0002
Revises: 20260320_0001
Create Date: 2026-03-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260323_0002"
down_revision = "20260320_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("use_dpvo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("jobs", "use_dpvo", server_default=None)


def downgrade() -> None:
    op.drop_column("jobs", "use_dpvo")
