from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


class QueueStatus(str, enum.Enum):
    active = "active"
    paused = "paused"


class JobStatus(str, enum.Enum):
    queued = "queued"
    scheduled = "scheduled"
    claimed = "claimed"
    running = "running"
    completed = "completed"
    failed = "failed"
    dead_lettered = "dead_lettered"


class JobKind(str, enum.Enum):
    immediate = "immediate"
    delayed = "delayed"
    scheduled = "scheduled"
    recurring = "recurring"
    batch = "batch"


class RetryStrategy(str, enum.Enum):
    fixed = "fixed"
    linear = "linear"
    exponential = "exponential"


class ExecutionStatus(str, enum.Enum):
    claimed = "claimed"
    running = "running"
    completed = "completed"
    failed = "failed"


class WorkerStatus(str, enum.Enum):
    online = "online"
    draining = "draining"
    offline = "offline"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["OrganizationMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    projects: Mapped[list["Project"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    members: Mapped[list["OrganizationMember"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_org_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="owner")

    organization: Mapped[Organization] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship(back_populates="projects")
    queues: Mapped[list["Queue"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class RetryPolicy(Base):
    __tablename__ = "retry_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255))
    strategy: Mapped[RetryStrategy] = mapped_column(Enum(RetryStrategy), default=RetryStrategy.exponential)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    base_delay_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_delay_seconds: Mapped[int] = mapped_column(Integer, default=3600)

    queues: Mapped[list["Queue"]] = relationship(back_populates="retry_policy")


class Queue(Base):
    __tablename__ = "queues"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_project_queue"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    retry_policy_id: Mapped[str] = mapped_column(ForeignKey("retry_policies.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[QueueStatus] = mapped_column(Enum(QueueStatus), default=QueueStatus.active, index=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=0)
    shard_key: Mapped[str] = mapped_column(String(64), default="default", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="queues")
    retry_policy: Mapped[RetryPolicy] = relationship(back_populates="queues")
    jobs: Mapped[list["Job"]] = relationship(back_populates="queue", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_polling", "status", "run_at", "priority"),
        Index("ix_jobs_queue_status", "queue_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    queue_id: Mapped[str] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), index=True)
    kind: Mapped[JobKind] = mapped_column(Enum(JobKind), default=JobKind.immediate)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued, index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    cron_expression: Mapped[str] = mapped_column(String(128), default="")
    batch_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    dependency_job_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    locked_by_worker_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    queue: Mapped[Queue] = relationship(back_populates="jobs")
    executions: Mapped[list["JobExecution"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    logs: Mapped[list["JobLog"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobExecution(Base):
    __tablename__ = "job_executions"
    __table_args__ = (Index("ix_exec_job_started", "job_id", "started_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id", ondelete="SET NULL"), nullable=True, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[ExecutionStatus] = mapped_column(Enum(ExecutionStatus), default=ExecutionStatus.claimed)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    exit_code: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")

    job: Mapped[Job] = relationship(back_populates="executions")
    worker: Mapped["Worker"] = relationship(back_populates="executions")


class RetryHistory(Base):
    __tablename__ = "retry_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    strategy: Mapped[RetryStrategy] = mapped_column(Enum(RetryStrategy))
    delay_seconds: Mapped[int] = mapped_column(Integer)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    error: Mapped[str] = mapped_column(Text, default="")


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (Index("ix_workers_health", "status", "last_heartbeat_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[WorkerStatus] = mapped_column(Enum(WorkerStatus), default=WorkerStatus.online, index=True)
    capacity: Mapped[int] = mapped_column(Integer, default=4)
    active_jobs: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    executions: Mapped[list[JobExecution]] = relationship(back_populates="worker")
    heartbeats: Mapped[list["WorkerHeartbeat"]] = relationship(back_populates="worker", cascade="all, delete-orphan")


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    __table_args__ = (Index("ix_heartbeats_worker_created", "worker_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), index=True)
    active_jobs: Mapped[int] = mapped_column(Integer, default=0)
    capacity: Mapped[int] = mapped_column(Integer, default=4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    worker: Mapped[Worker] = relationship(back_populates="heartbeats")


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    job: Mapped[Job] = relationship(back_populates="logs")


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    schedule_type: Mapped[str] = mapped_column(String(32))
    cron_expression: Mapped[str] = mapped_column(String(128), default="")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")


class DeadLetterEntry(Base):
    __tablename__ = "dead_letter_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    queue_id: Mapped[str] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), index=True)
    failed_attempts: Mapped[int] = mapped_column(Integer)
    final_error: Mapped[str] = mapped_column(Text)
    failure_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
