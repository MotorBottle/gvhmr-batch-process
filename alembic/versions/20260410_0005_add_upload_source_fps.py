"""add upload source fps

Revision ID: 20260410_0005
Revises: 20260409_0004
Create Date: 2026-04-10 11:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260410_0005"
down_revision = "20260409_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("uploads", sa.Column("source_fps", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("uploads", "source_fps")
