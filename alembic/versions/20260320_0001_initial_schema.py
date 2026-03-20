"""initial schema

Revision ID: 20260320_0001
Revises:
Create Date: 2026-03-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260320_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_uploads_sha256"), "uploads", ["sha256"], unique=False)

    op.create_table(
        "batches",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_batches_status"), "batches", ["status"], unique=False)

    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("node_name", sa.String(length=255), nullable=False),
        sa.Column("gpu_slot", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("running_job_id", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_worker_heartbeats_last_heartbeat_at"), "worker_heartbeats", ["last_heartbeat_at"], unique=False)
    op.create_index(op.f("ix_worker_heartbeats_running_job_id"), "worker_heartbeats", ["running_job_id"], unique=False)
    op.create_index(op.f("ix_worker_heartbeats_status"), "worker_heartbeats", ["status"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("batch_id", sa.String(length=32), nullable=True),
        sa.Column("upload_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("static_camera", sa.Boolean(), nullable=False),
        sa.Column("video_render", sa.Boolean(), nullable=False),
        sa.Column("video_type", sa.String(length=255), nullable=False),
        sa.Column("f_mm", sa.Integer(), nullable=True),
        sa.Column("assigned_worker_id", sa.String(length=64), nullable=True),
        sa.Column("assigned_gpu_slot", sa.Integer(), nullable=True),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_worker_id"], ["worker_heartbeats.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"]),
        sa.ForeignKeyConstraint(["upload_id"], ["uploads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_assigned_worker_id"), "jobs", ["assigned_worker_id"], unique=False)
    op.create_index(op.f("ix_jobs_batch_id"), "jobs", ["batch_id"], unique=False)
    op.create_index(op.f("ix_jobs_priority"), "jobs", ["priority"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index(op.f("ix_jobs_upload_id"), "jobs", ["upload_id"], unique=False)

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_artifacts_job_id"), "artifacts", ["job_id"], unique=False)

    op.create_table(
        "job_assignments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["worker_id"], ["worker_heartbeats.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index(op.f("ix_job_assignments_job_id"), "job_assignments", ["job_id"], unique=True)
    op.create_index(op.f("ix_job_assignments_worker_id"), "job_assignments", ["worker_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_assignments_worker_id"), table_name="job_assignments")
    op.drop_index(op.f("ix_job_assignments_job_id"), table_name="job_assignments")
    op.drop_table("job_assignments")
    op.drop_index(op.f("ix_artifacts_job_id"), table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index(op.f("ix_jobs_upload_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_priority"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_batch_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_assigned_worker_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_worker_heartbeats_status"), table_name="worker_heartbeats")
    op.drop_index(op.f("ix_worker_heartbeats_running_job_id"), table_name="worker_heartbeats")
    op.drop_index(op.f("ix_worker_heartbeats_last_heartbeat_at"), table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
    op.drop_index(op.f("ix_batches_status"), table_name="batches")
    op.drop_table("batches")
    op.drop_index(op.f("ix_uploads_sha256"), table_name="uploads")
    op.drop_table("uploads")
