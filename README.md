# Distributed Job Scheduling Platform

Production-inspired background job scheduler with authentication, projects, queues, atomic job claiming, retries, dead letter queue support, worker heartbeats, execution logs, and a responsive dashboard.

## Run Locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn scheduler.main:app --reload --port 8000
```

In another terminal:

```powershell
python -m scheduler.worker --worker-name local-worker --concurrency 4
```

Open `http://127.0.0.1:8000`.

The API seeds a demo organization, user, project, queues, and jobs on startup.

Demo credentials:

- Email: `demo@example.com`
- Password: `demo1234`

## Architecture

- `scheduler/main.py`: FastAPI app, startup migration/seed, static dashboard.
- `scheduler/models.py`: normalized relational schema.
- `scheduler/routes.py`: authenticated REST APIs with pagination/filtering.
- `scheduler/services.py`: scheduling, queue state, retry strategy, atomic claim logic.
- `scheduler/worker.py`: polling worker with heartbeats, concurrent execution, graceful shutdown.
- `scheduler/static`: dashboard UI with live polling.

## Database Design

The relational schema is normalized around tenancy, queue ownership, job state, and immutable execution history.

### Tables

- `users`: user identity and password hash. Primary key `id`; unique `email`.
- `organizations`: tenant boundary. Primary key `id`.
- `organization_members`: many-to-many membership between users and organizations with `role`. Composite uniqueness on `(organization_id, user_id)`.
- `projects`: belongs to an organization and owns queues. Indexed by `organization_id`.
- `retry_policies`: reusable retry behavior with strategy (`fixed`, `linear`, `exponential`), max attempts, base delay, and max delay.
- `queues`: belongs to a project and retry policy. Stores priority, concurrency limit, paused state, and rate limit metadata. Indexed by `(project_id, name)`.
- `jobs`: core state machine. Stores queue, type, status, payload, schedule time, cron expression, attempts, priority, batch key, worker assignment, and lifecycle timestamps.
- `job_executions`: immutable attempt records with worker assignment, timing, duration, status, exit code, and error text.
- `retry_history`: retry decisions per failed attempt, including delay strategy and next run time.
- `workers`: registered worker processes with status, capacity, and timestamps.
- `worker_heartbeats`: heartbeat history for observability and liveness.
- `job_logs`: append-only structured logs per job and execution.
- `scheduled_jobs`: durable records for delayed, scheduled, and recurring jobs.
- `dead_letter_entries`: terminal failures preserving final error, attempts, and source job.

### Keys, Indexes, and Constraints

- All entity tables use string UUID primary keys for API-safe identifiers.
- Foreign keys preserve ownership and auditability. Cascades are used for tenant-owned resources (`organization -> projects -> queues -> jobs`) and execution/log children. Dead letter entries cascade with jobs because they are derived records.
- Important indexes:
  - `jobs(status, run_at, priority)` accelerates scheduler and worker polling.
  - `jobs(queue_id, status)` accelerates dashboard filtering and queue health.
  - `job_executions(job_id, started_at)` accelerates job detail pages.
  - `workers(status, last_heartbeat_at)` accelerates health checks.
  - `worker_heartbeats(worker_id, created_at)` supports worker timelines.
- Queue concurrency is enforced at claim time by counting active jobs per queue inside a transaction before updating a candidate job.
- The local implementation uses SQLite transactions and conditional updates. In PostgreSQL, the same pattern should use `SELECT ... FOR UPDATE SKIP LOCKED` or an `UPDATE ... FROM (...) RETURNING` claim query.

### Performance Considerations

- Job payloads are JSON text for portability; high-volume deployments should cap payload size and move large blobs to object storage.
- Execution logs are append-only and should be partitioned or archived by time in production.
- Worker heartbeat history can be retained for a short window while `workers.last_heartbeat_at` remains the hot health field.
- Retry scheduling is computed once per failure and stored in `retry_history` and `jobs.run_at` to keep polling cheap.
- For very high volume, shard queues by project or queue id and run workers against shard subsets.

## REST API Overview

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/projects`
- `POST /api/projects`
- `GET /api/queues`
- `POST /api/projects/{project_id}/queues`
- `PATCH /api/queues/{queue_id}`
- `POST /api/queues/{queue_id}/pause`
- `POST /api/queues/{queue_id}/resume`
- `GET /api/queues/{queue_id}/stats`
- `POST /api/queues/{queue_id}/jobs`
- `POST /api/queues/{queue_id}/jobs/batch`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/retry`
- `GET /api/workers`
- `GET /api/metrics`

## Reliability Features

- Atomic claim with status guard prevents duplicate execution.
- Workers heartbeat while running and mark themselves draining on shutdown.
- Jobs move through `queued`, `scheduled`, `claimed`, `running`, `completed`, `failed`, and `dead_lettered`.
- Retry strategies: fixed delay, linear backoff, and exponential backoff.
- Dead letter entries are created after permanent failure.
- Execution records and logs are append-only for auditability.
- Job handlers should be idempotent; the sample worker simulates execution while preserving hooks for real dispatch.

## Bonus Features Included

- Role-aware organization membership schema.
- Queue rate limit fields in schema and API.
- Workflow dependency field on jobs.
- Queue sharding field.
- Polling-based live dashboard updates.
- AI failure summary placeholder generated from failure context.
