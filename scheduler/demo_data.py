from __future__ import annotations

import json
from datetime import timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_password
from .models import (
    DeadLetterEntry,
    ExecutionStatus,
    Job,
    JobExecution,
    JobKind,
    JobLog,
    JobStatus,
    Organization,
    OrganizationMember,
    Project,
    Queue,
    QueueStatus,
    RetryPolicy,
    RetryStrategy,
    User,
    Worker,
    WorkerHeartbeat,
    WorkerStatus,
    utcnow,
)
from .schemas import JobCreate
from .services import create_job, sync_worker_active_jobs


def seed_demo(db: Session) -> None:
    user = db.scalar(select(User).where(User.email == "demo@example.com"))
    if not user:
        user = User(email="demo@example.com", password_hash=hash_password("demo1234"), full_name="Demo User")
        org = Organization(name="Acme Operations")
        db.add_all([user, org])
        db.flush()
        db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
        project = Project(organization_id=org.id, name="Payments Platform", description="Background jobs for payment operations")
        db.add(project)
        db.flush()
    else:
        membership = user.memberships[0]
        org = db.get(Organization, membership.organization_id)
        project = db.scalar(select(Project).where(Project.organization_id == org.id))
        if not project:
            project = Project(organization_id=org.id, name="Payments Platform", description="Background jobs for payment operations")
            db.add(project)
            db.flush()

    queues = _ensure_queues(db, project)
    _ensure_workers(db)
    if db.scalar(select(Job).where(Job.queue_id.in_([q.id for q in queues.values()]))) is None:
        _seed_jobs(db, queues)
    elif db.scalar(select(Job).where(Job.batch_key == "demo-rich-batch")) is None:
        _seed_jobs(db, queues, light=True)
    _ensure_status_mix(db, queues)
    _ensure_paused_backlog(db, queues)
    sync_worker_active_jobs(db)


def _ensure_queues(db: Session, project: Project) -> dict[str, Queue]:
    specs = [
        ("critical-payments", 10, 3, RetryStrategy.exponential),
        ("reports", 1, 2, RetryStrategy.exponential),
        ("email-notifications", 4, 6, RetryStrategy.fixed),
        ("media-processing", 3, 2, RetryStrategy.linear),
        ("webhooks", 7, 4, RetryStrategy.exponential),
    ]
    queues: dict[str, Queue] = {}
    for name, priority, concurrency, strategy in specs:
        queue = db.scalar(select(Queue).where(Queue.project_id == project.id, Queue.name == name))
        if not queue:
            policy = RetryPolicy(
                name=f"{name} retry policy",
                strategy=strategy,
                max_attempts=4,
                base_delay_seconds=15,
                max_delay_seconds=300,
            )
            db.add(policy)
            db.flush()
            queue = Queue(
                project_id=project.id,
                retry_policy_id=policy.id,
                name=name,
                priority=priority,
                concurrency_limit=concurrency,
                rate_limit_per_minute=120 if name == "webhooks" else 0,
                shard_key=name.split("-")[0],
            )
            db.add(queue)
            db.flush()
        queues[name] = queue
    return queues


def _ensure_workers(db: Session) -> None:
    now = utcnow()
    specs = [
        ("worker-ash", WorkerStatus.online, 8, now),
        ("worker-birch", WorkerStatus.online, 6, now - timedelta(seconds=8)),
        ("worker-cedar", WorkerStatus.draining, 4, now - timedelta(seconds=22)),
        ("worker-delta", WorkerStatus.offline, 4, now - timedelta(minutes=18)),
    ]
    for name, status, capacity, heartbeat_at in specs:
        worker = db.scalar(select(Worker).where(Worker.name == name))
        if not worker:
            worker = Worker(name=name)
            db.add(worker)
            db.flush()
        worker.status = status
        worker.capacity = capacity
        worker.last_heartbeat_at = heartbeat_at
        db.add(WorkerHeartbeat(worker_id=worker.id, active_jobs=0, capacity=capacity, created_at=heartbeat_at))


def _seed_jobs(db: Session, queues: dict[str, Queue], light: bool = False) -> None:
    now = utcnow()
    samples = [
        ("critical-payments", JobKind.immediate, JobStatus.queued, {"task": "capture-payment", "amount": 124.5}, 10),
        ("critical-payments", JobKind.immediate, JobStatus.running, {"task": "fraud-screen", "customer": "cus_1024"}, 9),
        ("critical-payments", JobKind.delayed, JobStatus.scheduled, {"task": "settlement-check"}, 8),
        ("webhooks", JobKind.immediate, JobStatus.queued, {"task": "deliver-webhook", "endpoint": "/stripe"}, 7),
        ("webhooks", JobKind.immediate, JobStatus.completed, {"task": "deliver-webhook", "endpoint": "/github"}, 5),
        ("webhooks", JobKind.immediate, JobStatus.dead_lettered, {"task": "deliver-webhook", "endpoint": "/legacy-crm"}, 5),
        ("email-notifications", JobKind.batch, JobStatus.queued, {"task": "send-welcome-email"}, 3),
        ("email-notifications", JobKind.batch, JobStatus.completed, {"task": "send-invoice-email"}, 3),
        ("media-processing", JobKind.immediate, JobStatus.running, {"task": "transcode-video", "duration_ms": 2200}, 4),
        ("media-processing", JobKind.scheduled, JobStatus.scheduled, {"task": "thumbnail-refresh"}, 2),
        ("reports", JobKind.recurring, JobStatus.scheduled, {"task": "daily-revenue-report"}, 1),
        ("reports", JobKind.immediate, JobStatus.completed, {"task": "export-csv"}, 1),
    ]
    if light:
        samples = samples[:8]

    worker_ash = db.scalar(select(Worker).where(Worker.name == "worker-ash"))
    worker_birch = db.scalar(select(Worker).where(Worker.name == "worker-birch"))
    demo_workers = [w for w in (worker_ash, worker_birch) if w]

    for index, (queue_name, kind, status, payload, priority) in enumerate(samples):
        queue = queues[queue_name]
        job = create_job(
            db,
            queue,
            JobCreate(
                kind=kind,
                payload=payload,
                priority=priority,
                delay_seconds=0 if status != JobStatus.scheduled else 900 + index * 60,
                batch_key="demo-rich-batch" if kind == JobKind.batch else "",
                cron_expression="*/15 * * * *" if kind == JobKind.recurring else "",
            ),
            "demo-rich-batch" if kind == JobKind.batch else "",
        )
        job.status = status
        job.created_at = now - timedelta(minutes=60 - index * 4)
        job.run_at = now + timedelta(minutes=15 + index) if status == JobStatus.scheduled else now - timedelta(minutes=index)
        if status in {JobStatus.running, JobStatus.claimed}:
            job.claimed_at = now - timedelta(seconds=45 + index)
            job.started_at = now - timedelta(seconds=30 + index)
            job.locked_at = job.claimed_at
            worker = demo_workers[index % len(demo_workers)] if demo_workers else None
            job.locked_by_worker_id = worker.id if worker else ""
        if status == JobStatus.completed:
            job.attempts = 1
            job.completed_at = now - timedelta(minutes=index)
            _add_execution(db, job, ExecutionStatus.completed, 1, 520 + index * 110)
        elif status == JobStatus.running:
            job.attempts = 1
            _add_execution(db, job, ExecutionStatus.running, 1, 0)
        elif status == JobStatus.dead_lettered:
            job.attempts = job.max_attempts
            job.failed_at = now - timedelta(minutes=index)
            _add_execution(db, job, ExecutionStatus.failed, job.max_attempts, 1800, "HTTP 410 from downstream endpoint")
            db.add(
                DeadLetterEntry(
                    job_id=job.id,
                    queue_id=job.queue_id,
                    failed_attempts=job.attempts,
                    final_error="HTTP 410 from downstream endpoint",
                    failure_summary="likely non-retryable downstream configuration issue; endpoint returned HTTP 410",
                )
            )
        db.add(JobLog(job_id=job.id, level="info", message=f"demo payload: {json.dumps(payload)}"))


def _add_execution(
    db: Session,
    job: Job,
    status: ExecutionStatus,
    attempt: int,
    duration_ms: int,
    error: str = "",
) -> None:
    worker = db.scalar(select(Worker).where(Worker.status == WorkerStatus.online))
    execution = JobExecution(
        job_id=job.id,
        worker_id=worker.id if worker else None,
        attempt_number=attempt,
        status=status,
        started_at=utcnow() - timedelta(seconds=90),
        finished_at=None if status == ExecutionStatus.running else utcnow() - timedelta(seconds=60),
        duration_ms=duration_ms,
        exit_code=1 if error else 0,
        error=error,
    )
    db.add(execution)


def _ensure_status_mix(db: Session, queues: dict[str, Queue]) -> None:
    now = utcnow()
    worker_ash = db.scalar(select(Worker).where(Worker.name == "worker-ash"))
    worker_birch = db.scalar(select(Worker).where(Worker.name == "worker-birch"))
    active_count = db.scalar(select(Job).where(Job.batch_key == "demo-active-showcase").limit(1))
    if active_count:
        jobs = db.scalars(select(Job).where(Job.batch_key == "demo-active-showcase")).all()
        for job in jobs:
            payload = json.loads(job.payload)
            if payload.get("task") == "render-preview":
                job.status = JobStatus.running
                job.attempts = max(job.attempts, 1)
                job.claimed_at = now - timedelta(seconds=35)
                job.started_at = now - timedelta(seconds=25)
                job.locked_at = now - timedelta(seconds=35)
                job.locked_by_worker_id = worker_ash.id if worker_ash else ""
            elif payload.get("task") == "send-campaign":
                job.status = JobStatus.running
                job.attempts = max(job.attempts, 1)
                job.claimed_at = now - timedelta(seconds=35)
                job.started_at = now - timedelta(seconds=25)
                job.locked_at = now - timedelta(seconds=35)
                job.locked_by_worker_id = worker_birch.id if worker_birch else ""
            elif payload.get("task") == "quarterly-board-pack":
                job.status = JobStatus.scheduled
                job.run_at = now + timedelta(minutes=45)
        return

    showcase = [
        ("critical-payments", JobStatus.queued, {"task": "authorize-payment", "amount": 89.99}, 10),
        ("webhooks", JobStatus.queued, {"task": "deliver-webhook", "endpoint": "/shopify"}, 7),
        ("media-processing", JobStatus.running, {"task": "render-preview", "duration_ms": 12000}, 4),
        ("email-notifications", JobStatus.running, {"task": "send-campaign", "segment": "trial-users"}, 3),
        ("reports", JobStatus.scheduled, {"task": "quarterly-board-pack"}, 1),
    ]
    for index, (queue_name, status, payload, priority) in enumerate(showcase):
        running_worker = worker_ash if payload.get("task") == "render-preview" else worker_birch
        job = Job(
            queue_id=queues[queue_name].id,
            kind=JobKind.immediate if status != JobStatus.scheduled else JobKind.scheduled,
            status=status,
            payload=json.dumps(payload),
            priority=priority,
            run_at=now + timedelta(minutes=30) if status == JobStatus.scheduled else now,
            batch_key="demo-active-showcase",
            attempts=1 if status == JobStatus.running else 0,
            max_attempts=4,
            created_at=now - timedelta(minutes=8 - index),
            claimed_at=now - timedelta(seconds=50) if status == JobStatus.running else None,
            started_at=now - timedelta(seconds=35) if status == JobStatus.running else None,
            locked_at=now - timedelta(seconds=50) if status == JobStatus.running else None,
            locked_by_worker_id=running_worker.id if running_worker and status == JobStatus.running else "",
        )
        db.add(job)
        db.flush()
        db.add(JobLog(job_id=job.id, level="info", message=f"showcase job seeded: {payload['task']}"))
        if status == JobStatus.running:
            db.add(
                JobExecution(
                    job_id=job.id,
                    worker_id=running_worker.id if running_worker else None,
                    attempt_number=1,
                    status=ExecutionStatus.running,
                    started_at=job.started_at,
                    duration_ms=0,
                )
            )


def _ensure_paused_backlog(db: Session, queues: dict[str, Queue]) -> None:
    queue = queues["email-notifications"]
    queue.status = QueueStatus.paused
    if db.scalar(select(Job).where(Job.batch_key == "demo-paused-backlog").limit(1)):
        return
    now = utcnow()
    for index, task in enumerate(["send-password-reset", "send-weekly-digest", "send-renewal-reminder"]):
        db.add(
            Job(
                queue_id=queue.id,
                kind=JobKind.batch,
                status=JobStatus.queued,
                payload=json.dumps({"task": task, "template": f"tpl_{index + 1}"}),
                priority=3,
                run_at=now,
                batch_key="demo-paused-backlog",
                max_attempts=4,
                created_at=now - timedelta(minutes=index + 2),
            )
        )
