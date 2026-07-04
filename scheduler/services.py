from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .models import (
    DeadLetterEntry,
    ExecutionStatus,
    Job,
    JobExecution,
    JobKind,
    JobLog,
    JobStatus,
    Queue,
    QueueStatus,
    RetryHistory,
    RetryPolicy,
    RetryStrategy,
    ScheduledJob,
    Worker,
    WorkerHeartbeat,
    WorkerStatus,
    utcnow,
)
from .schemas import JobCreate


def json_loads(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {"value": value}
    except json.JSONDecodeError:
        return {}


def serialize_job(job: Job, include_payload: bool = True) -> dict[str, Any]:
    data = {
        "id": job.id,
        "queue_id": job.queue_id,
        "kind": job.kind.value,
        "status": job.status.value,
        "priority": job.priority,
        "run_at": job.run_at.isoformat() if job.run_at else None,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "locked_by_worker_id": job.locked_by_worker_id,
        "created_at": job.created_at.isoformat(),
        "claimed_at": job.claimed_at.isoformat() if job.claimed_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "failed_at": job.failed_at.isoformat() if job.failed_at else None,
        "batch_key": job.batch_key,
        "dependency_job_id": job.dependency_job_id,
    }
    if include_payload:
        data["payload"] = json_loads(job.payload)
    return data


def serialize_queue(queue: Queue) -> dict[str, Any]:
    return {
        "id": queue.id,
        "project_id": queue.project_id,
        "name": queue.name,
        "priority": queue.priority,
        "concurrency_limit": queue.concurrency_limit,
        "status": queue.status.value,
        "rate_limit_per_minute": queue.rate_limit_per_minute,
        "shard_key": queue.shard_key,
        "retry_policy": {
            "strategy": queue.retry_policy.strategy.value,
            "max_attempts": queue.retry_policy.max_attempts,
            "base_delay_seconds": queue.retry_policy.base_delay_seconds,
            "max_delay_seconds": queue.retry_policy.max_delay_seconds,
        },
    }


def job_run_time(req: JobCreate) -> datetime:
    now = utcnow()
    if req.run_at:
        return req.run_at.astimezone(timezone.utc) if req.run_at.tzinfo else req.run_at.replace(tzinfo=timezone.utc)
    if req.delay_seconds:
        return now + timedelta(seconds=req.delay_seconds)
    return now


def create_job(db: Session, queue: Queue, req: JobCreate, batch_key: str = "") -> Job:
    run_at = job_run_time(req)
    status = JobStatus.queued if run_at <= utcnow() else JobStatus.scheduled
    job = Job(
        queue_id=queue.id,
        kind=req.kind,
        status=status,
        payload=json.dumps(req.payload),
        priority=req.priority,
        run_at=run_at,
        cron_expression=req.cron_expression,
        batch_key=batch_key or req.batch_key,
        dependency_job_id=req.dependency_job_id,
        max_attempts=req.max_attempts or queue.retry_policy.max_attempts,
    )
    db.add(job)
    db.flush()
    if req.kind in {JobKind.delayed, JobKind.scheduled, JobKind.recurring} or run_at > utcnow():
        db.add(
            ScheduledJob(
                job_id=job.id,
                schedule_type=req.kind.value,
                cron_expression=req.cron_expression,
                next_run_at=run_at,
            )
        )
    add_log(db, job.id, "info", f"job created as {job.status.value}")
    return job


def promote_due_jobs(db: Session) -> int:
    now = utcnow()
    jobs = db.scalars(
        select(Job).where(Job.status == JobStatus.scheduled, Job.run_at <= now).limit(200)
    ).all()
    for job in jobs:
        job.status = JobStatus.queued
        add_log(db, job.id, "info", "scheduled job promoted to queued")
    return len(jobs)


def recover_stale_claims(db: Session, older_than_seconds: int = 120) -> int:
    cutoff = utcnow() - timedelta(seconds=older_than_seconds)
    jobs = db.scalars(
        select(Job).where(
            Job.status.in_([JobStatus.claimed, JobStatus.running]),
            or_(Job.locked_at.is_(None), Job.locked_at <= cutoff),
        )
    ).all()
    for job in jobs:
        job.status = JobStatus.queued
        job.locked_by_worker_id = ""
        job.locked_at = None
        add_log(db, job.id, "warning", "stale claim recovered and requeued")
    return len(jobs)


def dependency_satisfied(db: Session, job: Job) -> bool:
    if not job.dependency_job_id:
        return True
    parent = db.get(Job, job.dependency_job_id)
    return bool(parent and parent.status == JobStatus.completed)


def queue_active_count(db: Session, queue_id: str) -> int:
    return db.scalar(
        select(func.count(Job.id)).where(
            Job.queue_id == queue_id,
            Job.status.in_([JobStatus.claimed, JobStatus.running]),
        )
    ) or 0


def worker_active_job_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(Job.locked_by_worker_id, func.count(Job.id)).where(
            Job.status.in_([JobStatus.claimed, JobStatus.running]),
            Job.locked_by_worker_id != "",
        ).group_by(Job.locked_by_worker_id)
    ).all()
    return {worker_id: count for worker_id, count in rows}


def sync_worker_active_jobs(db: Session) -> None:
    counts = worker_active_job_counts(db)
    for worker in db.scalars(select(Worker)).all():
        worker.active_jobs = counts.get(worker.id, 0)


def claim_next_job(db: Session, worker: Worker) -> tuple[Job | None, JobExecution | None]:
    promote_due_jobs(db)
    candidates = db.scalars(
        select(Job)
        .join(Queue)
        .where(
            Job.status == JobStatus.queued,
            Job.run_at <= utcnow(),
            Queue.status == QueueStatus.active,
        )
        .order_by(Job.priority.desc(), Queue.priority.desc(), Job.run_at.asc(), Job.created_at.asc())
        .limit(25)
    ).all()
    for job in candidates:
        if not dependency_satisfied(db, job):
            continue
        if queue_active_count(db, job.queue_id) >= job.queue.concurrency_limit:
            continue
        updated = (
            db.query(Job)
            .filter(Job.id == job.id, Job.status == JobStatus.queued)
            .update(
                {
                    "status": JobStatus.claimed,
                    "locked_by_worker_id": worker.id,
                    "locked_at": utcnow(),
                    "claimed_at": utcnow(),
                    "attempts": Job.attempts + 1,
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            continue
        db.flush()
        db.refresh(job)
        execution = JobExecution(
            job_id=job.id,
            worker_id=worker.id,
            attempt_number=job.attempts,
            status=ExecutionStatus.claimed,
        )
        db.add(execution)
        db.flush()
        add_log(db, job.id, "info", f"claimed by worker {worker.name}")
        return job, execution
    return None, None


def start_execution(db: Session, job_id: str, execution_id: str) -> None:
    now = utcnow()
    job = db.get(Job, job_id)
    execution = db.get(JobExecution, execution_id)
    if not job or not execution:
        raise RuntimeError("job or execution missing")
    job.status = JobStatus.running
    job.started_at = now
    execution.status = ExecutionStatus.running
    execution.started_at = now
    add_log(db, job.id, "info", "execution started", execution.id)


def complete_execution(db: Session, job_id: str, execution_id: str, duration_ms: int) -> None:
    now = utcnow()
    job = db.get(Job, job_id)
    execution = db.get(JobExecution, execution_id)
    if not job or not execution:
        raise RuntimeError("job or execution missing")
    job.status = JobStatus.completed
    job.completed_at = now
    job.locked_by_worker_id = ""
    job.locked_at = None
    execution.status = ExecutionStatus.completed
    execution.finished_at = now
    execution.duration_ms = duration_ms
    add_log(db, job.id, "info", "execution completed", execution.id)


def retry_delay(policy: RetryPolicy, attempt_number: int) -> int:
    base = policy.base_delay_seconds
    if policy.strategy == RetryStrategy.fixed:
        delay = base
    elif policy.strategy == RetryStrategy.linear:
        delay = base * attempt_number
    else:
        delay = base * (2 ** max(attempt_number - 1, 0))
    return min(delay, policy.max_delay_seconds)


def summarize_failure(error: str, attempts: int) -> str:
    hint = "permanent failure after retry budget was exhausted"
    if "timeout" in error.lower():
        hint = "likely timeout or downstream availability issue"
    if "validation" in error.lower():
        hint = "likely non-retryable payload validation issue"
    return f"{hint}; final attempt {attempts}: {error[:240]}"


def fail_execution(db: Session, job_id: str, execution_id: str, duration_ms: int, error: str) -> None:
    now = utcnow()
    job = db.get(Job, job_id)
    execution = db.get(JobExecution, execution_id)
    if not job or not execution:
        raise RuntimeError("job or execution missing")
    execution.status = ExecutionStatus.failed
    execution.finished_at = now
    execution.duration_ms = duration_ms
    execution.exit_code = 1
    execution.error = error
    policy = job.queue.retry_policy
    if job.attempts < job.max_attempts:
        delay = retry_delay(policy, job.attempts)
        next_run_at = now + timedelta(seconds=delay)
        job.status = JobStatus.scheduled
        job.run_at = next_run_at
        job.failed_at = now
        job.locked_by_worker_id = ""
        job.locked_at = None
        db.add(
            RetryHistory(
                job_id=job.id,
                attempt_number=job.attempts,
                strategy=policy.strategy,
                delay_seconds=delay,
                next_run_at=next_run_at,
                error=error,
            )
        )
        add_log(db, job.id, "warning", f"execution failed; retry scheduled in {delay}s", execution.id)
        return
    job.status = JobStatus.dead_lettered
    job.failed_at = now
    job.locked_by_worker_id = ""
    job.locked_at = None
    db.add(
        DeadLetterEntry(
            job_id=job.id,
            queue_id=job.queue_id,
            failed_attempts=job.attempts,
            final_error=error,
            failure_summary=summarize_failure(error, job.attempts),
        )
    )
    add_log(db, job.id, "error", "job moved to dead letter queue", execution.id)


def add_log(db: Session, job_id: str, level: str, message: str, execution_id: str = "") -> None:
    db.add(JobLog(job_id=job_id, execution_id=execution_id, level=level, message=message))


def register_worker(db: Session, name: str, capacity: int) -> Worker:
    worker = db.scalar(select(Worker).where(Worker.name == name))
    if worker:
        worker.status = WorkerStatus.online
        worker.capacity = capacity
        worker.last_heartbeat_at = utcnow()
        return worker
    worker = Worker(name=name, capacity=capacity)
    db.add(worker)
    db.flush()
    return worker


def heartbeat(db: Session, worker_id: str, active_jobs: int, capacity: int) -> None:
    worker = db.get(Worker, worker_id)
    if not worker:
        return
    worker.active_jobs = active_jobs
    worker.capacity = capacity
    worker.last_heartbeat_at = utcnow()
    db.add(WorkerHeartbeat(worker_id=worker_id, active_jobs=active_jobs, capacity=capacity))


def mark_worker(db: Session, worker_id: str, status: WorkerStatus) -> None:
    worker = db.get(Worker, worker_id)
    if worker:
        worker.status = status
        worker.last_heartbeat_at = utcnow()


def simulate_job(payload: dict[str, Any]) -> None:
    if payload.get("fail"):
        raise RuntimeError(str(payload.get("error", "simulated failure")))
    failure_rate = float(payload.get("failure_rate", 0))
    if failure_rate and random.random() < failure_rate:
        raise RuntimeError("simulated intermittent failure")


def require_entity(entity: Any, name: str) -> Any:
    if not entity:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"{name} not found"})
    return entity


def queue_stats(db: Session, queue_id: str) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(Job.status, func.count(Job.id)).where(Job.queue_id == queue_id).group_by(Job.status)
        ).all()
    )
    completed = counts.get(JobStatus.completed, 0)
    failed = counts.get(JobStatus.dead_lettered, 0) + counts.get(JobStatus.failed, 0)
    durations = db.scalars(
        select(JobExecution.duration_ms).join(Job).where(Job.queue_id == queue_id, JobExecution.duration_ms > 0)
    ).all()
    avg_ms = round(sum(durations) / len(durations), 2) if durations else 0
    return {
        "queue_id": queue_id,
        "counts": {status.value if hasattr(status, "value") else str(status): count for status, count in counts.items()},
        "completed": completed,
        "failed": failed,
        "avg_duration_ms": avg_ms,
        "throughput_total": completed,
    }
