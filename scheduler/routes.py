from __future__ import annotations

from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import create_access_token, current_user, hash_password, verify_password
from .database import get_db
from .models import (
    DeadLetterEntry,
    Job,
    JobExecution,
    JobLog,
    JobStatus,
    Organization,
    OrganizationMember,
    Project,
    Queue,
    QueueStatus,
    RetryPolicy,
    User,
    Worker,
    WorkerStatus,
    utcnow,
)
from .schemas import BatchJobCreate, JobCreate, LoginRequest, ProjectCreate, QueueCreate, QueueUpdate, RegisterRequest
from .services import (
    create_job,
    queue_active_count,
    queue_stats,
    require_entity,
    serialize_job,
    serialize_queue,
    worker_active_job_counts,
)

router = APIRouter(prefix="/api")


@router.post("/auth/register")
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == req.email)):
        raise HTTPException(status_code=409, detail={"error": "email_exists", "message": "Email already registered"})
    user = User(email=req.email, password_hash=hash_password(req.password), full_name=req.full_name)
    org = Organization(name=req.organization_name)
    db.add_all([user, org])
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    project = Project(organization_id=org.id, name="Default Project", description="Seed project")
    db.add(project)
    db.commit()
    return {"user_id": user.id, "organization_id": org.id, "project_id": project.id}


@router.post("/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == req.email))
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail={"error": "bad_credentials", "message": "Invalid email or password"})
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "full_name": user.full_name}


@router.get("/projects")
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    org_ids = [m.organization_id for m in user.memberships]
    projects = db.scalars(select(Project).where(Project.organization_id.in_(org_ids)).order_by(Project.created_at.desc())).all()
    return [{"id": p.id, "organization_id": p.organization_id, "name": p.name, "description": p.description} for p in projects]


@router.post("/projects")
def add_project(req: ProjectCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    org_id = req.organization_id or (user.memberships[0].organization_id if user.memberships else None)
    if not org_id:
        raise HTTPException(status_code=400, detail={"error": "missing_org", "message": "No organization available"})
    if org_id not in [m.organization_id for m in user.memberships]:
        raise HTTPException(status_code=403, detail={"error": "forbidden", "message": "Not a member of organization"})
    project = Project(organization_id=org_id, name=req.name, description=req.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"id": project.id, "organization_id": project.organization_id, "name": project.name, "description": project.description}


@router.get("/queues")
def list_queues(project_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Queue).join(Project).join(OrganizationMember, OrganizationMember.organization_id == Project.organization_id)
    stmt = stmt.where(OrganizationMember.user_id == user.id)
    if project_id:
        stmt = stmt.where(Queue.project_id == project_id)
    queues = db.scalars(stmt.order_by(Queue.created_at.desc())).all()
    return [
        {**serialize_queue(q), "active_slots": queue_active_count(db, q.id)}
        for q in queues
    ]


@router.post("/projects/{project_id}/queues")
def add_queue(project_id: str, req: QueueCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = require_entity(db.get(Project, project_id), "project")
    if project.organization_id not in [m.organization_id for m in user.memberships]:
        raise HTTPException(status_code=403, detail={"error": "forbidden", "message": "Not a project member"})
    policy = RetryPolicy(
        name=f"{req.name} retry policy",
        strategy=req.retry_strategy,
        max_attempts=req.max_attempts,
        base_delay_seconds=req.base_delay_seconds,
        max_delay_seconds=req.max_delay_seconds,
    )
    db.add(policy)
    db.flush()
    queue = Queue(
        project_id=project.id,
        retry_policy_id=policy.id,
        name=req.name,
        priority=req.priority,
        concurrency_limit=req.concurrency_limit,
        rate_limit_per_minute=req.rate_limit_per_minute,
        shard_key=req.shard_key,
    )
    db.add(queue)
    db.commit()
    db.refresh(queue)
    return serialize_queue(queue)


@router.patch("/queues/{queue_id}")
def update_queue(queue_id: str, req: QueueUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    queue = require_entity(db.get(Queue, queue_id), "queue")
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(queue, field, value)
    db.commit()
    db.refresh(queue)
    return serialize_queue(queue)


@router.post("/queues/{queue_id}/pause")
def pause_queue(queue_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    queue = require_entity(db.get(Queue, queue_id), "queue")
    queue.status = QueueStatus.paused
    db.commit()
    return serialize_queue(queue)


@router.post("/queues/{queue_id}/resume")
def resume_queue(queue_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    queue = require_entity(db.get(Queue, queue_id), "queue")
    queue.status = QueueStatus.active
    db.commit()
    return serialize_queue(queue)


@router.get("/queues/{queue_id}/stats")
def get_queue_stats(queue_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_entity(db.get(Queue, queue_id), "queue")
    return queue_stats(db, queue_id)


@router.post("/queues/{queue_id}/jobs")
def add_job(queue_id: str, req: JobCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    queue = require_entity(db.get(Queue, queue_id), "queue")
    job = create_job(db, queue, req)
    db.commit()
    db.refresh(job)
    return serialize_job(job)


@router.post("/queues/{queue_id}/jobs/batch")
def add_batch(queue_id: str, req: BatchJobCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    queue = require_entity(db.get(Queue, queue_id), "queue")
    jobs = [create_job(db, queue, item.model_copy(update={"kind": item.kind, "batch_key": req.batch_key}), req.batch_key) for item in req.jobs]
    db.commit()
    return {"batch_key": req.batch_key, "jobs": [serialize_job(j) for j in jobs]}


@router.get("/jobs")
def list_jobs(
    status: JobStatus | None = None,
    queue_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Job)
        .join(Queue)
        .join(Project, Project.id == Queue.project_id)
        .join(OrganizationMember, OrganizationMember.organization_id == Project.organization_id)
        .where(OrganizationMember.user_id == user.id)
    )
    count_stmt = (
        select(func.count(Job.id))
        .join(Queue)
        .join(Project, Project.id == Queue.project_id)
        .join(OrganizationMember, OrganizationMember.organization_id == Project.organization_id)
        .where(OrganizationMember.user_id == user.id)
    )
    if status:
        stmt = stmt.where(Job.status == status)
        count_stmt = count_stmt.where(Job.status == status)
    if queue_id:
        stmt = stmt.where(Job.queue_id == queue_id)
        count_stmt = count_stmt.where(Job.queue_id == queue_id)
    total = db.scalar(count_stmt) or 0
    jobs = db.scalars(stmt.order_by(Job.created_at.desc()).limit(limit).offset(offset)).all()
    return {"items": [serialize_job(j, include_payload=False) for j in jobs], "total": total, "limit": limit, "offset": offset}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = require_entity(db.get(Job, job_id), "job")
    executions = db.scalars(select(JobExecution).where(JobExecution.job_id == job.id).order_by(JobExecution.started_at.desc())).all()
    logs = db.scalars(select(JobLog).where(JobLog.job_id == job.id).order_by(JobLog.created_at.desc()).limit(100)).all()
    dlq = db.scalar(select(DeadLetterEntry).where(DeadLetterEntry.job_id == job.id))
    return {
        **serialize_job(job),
        "executions": [
            {
                "id": e.id,
                "worker_id": e.worker_id,
                "attempt_number": e.attempt_number,
                "status": e.status.value,
                "duration_ms": e.duration_ms,
                "error": e.error,
            }
            for e in executions
        ],
        "logs": [{"level": l.level, "message": l.message, "created_at": l.created_at.isoformat()} for l in logs],
        "dead_letter": {
            "final_error": dlq.final_error,
            "failure_summary": dlq.failure_summary,
            "created_at": dlq.created_at.isoformat(),
        }
        if dlq
        else None,
    }


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = require_entity(db.get(Job, job_id), "job")
    if job.status not in {JobStatus.failed, JobStatus.dead_lettered}:
        raise HTTPException(status_code=400, detail={"error": "invalid_state", "message": "Only failed or DLQ jobs can be retried"})
    job.status = JobStatus.queued
    job.run_at = utcnow()
    job.locked_by_worker_id = ""
    job.locked_at = None
    job.failed_at = None
    job.attempts = 0
    # Remove dead letter entry so the job is no longer flagged as DLQ after retry
    dlq = db.scalar(select(DeadLetterEntry).where(DeadLetterEntry.job_id == job.id))
    if dlq:
        db.delete(dlq)
    db.commit()
    return serialize_job(job)


@router.get("/workers")
def list_workers(user: User = Depends(current_user), db: Session = Depends(get_db)):
    workers = db.scalars(select(Worker).order_by(Worker.last_heartbeat_at.desc())).all()
    active_by_worker = worker_active_job_counts(db)
    now = utcnow()
    result = []
    for w in workers:
        try:
            # Normalize to UTC-aware regardless of what SQLite returns
            hb = w.last_heartbeat_at
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
            is_stale = (now - hb) > timedelta(seconds=45) and w.status == WorkerStatus.online
            status_val = "stale" if is_stale else w.status.value
        except Exception:
            status_val = w.status.value
        result.append({
            "id": w.id,
            "name": w.name,
            "status": status_val,
            "capacity": w.capacity,
            "active_jobs": active_by_worker.get(w.id, 0),
            "last_heartbeat_at": w.last_heartbeat_at.isoformat(),
        })
    return result


@router.get("/metrics")
def metrics(user: User = Depends(current_user), db: Session = Depends(get_db)):
    statuses = dict(db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status)).all())
    workers = dict(db.execute(select(Worker.status, func.count(Worker.id)).group_by(Worker.status)).all())
    recent_completed = db.scalar(
        select(func.count(Job.id)).where(Job.status == JobStatus.completed, Job.completed_at >= utcnow() - timedelta(minutes=15))
    ) or 0
    return {
        "jobs": {key.value if hasattr(key, "value") else str(key): value for key, value in statuses.items()},
        "workers": {key.value if hasattr(key, "value") else str(key): value for key, value in workers.items()},
        "completed_last_15m": recent_completed,
    }
