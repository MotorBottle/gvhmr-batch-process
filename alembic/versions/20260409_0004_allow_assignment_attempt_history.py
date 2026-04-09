"""allow multiple assignment attempts per job

Revision ID: 20260409_0004
Revises: 20260326_0003
Create Date: 2026-04-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260409_0004"
down_revision = "20260326_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE job_assignments AS ja
        SET completed_at = COALESCE(ja.completed_at, COALESCE(j.finished_at, j.updated_at, CURRENT_TIMESTAMP))
        FROM jobs AS j
        WHERE ja.job_id = j.id
          AND ja.completed_at IS NULL
          AND j.status NOT IN ('scheduled', 'running')
        """
    )
    op.execute(
        """
        UPDATE jobs
        SET assigned_worker_id = NULL,
            assigned_gpu_slot = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'queued'
        """
    )

    op.drop_index(op.f("ix_job_assignments_job_id"), table_name="job_assignments")
    op.drop_constraint("job_assignments_job_id_key", "job_assignments", type_="unique")
    op.create_index(op.f("ix_job_assignments_job_id"), "job_assignments", ["job_id"], unique=False)
    op.create_index(
        "uq_job_assignments_active_job",
        "job_assignments",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("completed_at IS NULL"),
    )
    op.create_index(
        "uq_job_assignments_active_worker",
        "job_assignments",
        ["worker_id"],
        unique=True,
        postgresql_where=sa.text("completed_at IS NULL"),
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM job_assignments AS ja
        USING (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY job_id
                    ORDER BY assigned_at DESC, id DESC
                ) AS row_rank
            FROM job_assignments
        ) AS ranked
        WHERE ja.id = ranked.id
          AND ranked.row_rank > 1
        """
    )

    op.drop_index("uq_job_assignments_active_worker", table_name="job_assignments")
    op.drop_index("uq_job_assignments_active_job", table_name="job_assignments")
    op.drop_index(op.f("ix_job_assignments_job_id"), table_name="job_assignments")
    op.create_unique_constraint("job_assignments_job_id_key", "job_assignments", ["job_id"])
    op.create_index(op.f("ix_job_assignments_job_id"), "job_assignments", ["job_id"], unique=True)
