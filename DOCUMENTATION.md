# Distributed Job Scheduling Platform - Technical Documentation

## System Architecture

The system is a production-inspired background job scheduler built with **FastAPI**, **SQLAlchemy**, and **SQLite**. It provides enterprise-grade features for managing distributed job execution across multiple workers with full observability and recovery mechanisms.

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI REST API                         │
│  (/api/auth, /api/projects, /api/queues, /api/jobs, ...)   │
└─────────────────────────────────────────────────────────────┘
         ↓                              ↓
┌──────────────────────┐    ┌──────────────────────┐
│  Web Dashboard UI    │    │  Python Worker CLI   │
│  (React/Vanilla JS)  │    │  (Concurrent Executor)
└──────────────────────┘    └──────────────────────┘
         ↓                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    SQLite Database                          │
│  (Organizations, Users, Projects, Queues, Jobs, Workers)   │
└─────────────────────────────────────────────────────────────┘
```

### Key Responsibilities

- **API Layer** (`scheduler/routes.py`): Handles authentication, CRUD operations, and job lifecycle management
- **Service Layer** (`scheduler/services.py`): Business logic for job claiming, retry strategy, queue concurrency enforcement
- **Data Layer** (`scheduler/models.py`): SQLAlchemy ORM definitions with proper relationships and indexing
- **Worker** (`scheduler/worker.py`): Polling-based job executor with heartbeat mechanism and graceful shutdown
- **Frontend** (`scheduler/static/`): Real-time dashboard with live polling every 5 seconds

---

## Database Design

### Normalized Relational Schema

The database is organized around **tenancy**, **queue ownership**, **job state**, and **immutable execution history**.

```sql
-- Core Tenancy
users (id, email, password_hash, full_name, created_at)
organizations (id, name, created_at)
organization_members (id, organization_id, user_id, role)

-- Project & Queue Management
projects (id, organization_id, name, description, created_at)
retry_policies (id, name, strategy, max_attempts, base_delay, max_delay)
queues (id, project_id, retry_policy_id, name, priority, concurrency_limit,
        status, rate_limit_per_minute, shard_key, created_at)

-- Job Lifecycle & Execution
jobs (id, queue_id, kind, status, payload, priority, run_at, cron_expression,
      batch_key, dependency_job_id, attempts, max_attempts, locked_by_worker_id,
      locked_at, created_at, claimed_at, started_at, completed_at, failed_at)
job_executions (id, job_id, worker_id, attempt_number, status, started_at,
                finished_at, duration_ms, exit_code, error)
retry_history (id, job_id, attempt_number, strategy, delay_seconds,
               scheduled_at, next_run_at, error)

-- Worker & Observability
workers (id, name, status, capacity, active_jobs, started_at, last_heartbeat_at)
worker_heartbeats (id, worker_id, active_jobs, capacity, created_at)
job_logs (id, job_id, execution_id, level, message, created_at)

-- Terminal States
scheduled_jobs (id, job_id, schedule_type, cron_expression, next_run_at, timezone)
dead_letter_entries (id, job_id, queue_id, failed_attempts, final_error,
                     failure_summary, created_at)
```

### Key Indexes for Performance

| Index                                      | Purpose                              |
| ------------------------------------------ | ------------------------------------ |
| `jobs(status, run_at, priority)`           | Scheduler polling optimization       |
| `jobs(queue_id, status)`                   | Dashboard filtering and queue health |
| `job_executions(job_id, started_at)`       | Job detail page queries              |
| `workers(status, last_heartbeat_at)`       | Worker health checks                 |
| `worker_heartbeats(worker_id, created_at)` | Worker timeline queries              |

### Constraints & Relationships

- **Foreign Keys**: Enforce tenancy ownership (`organization → projects → queues → jobs`)
- **Cascading Deletes**: Preserve referential integrity for owned resources
- **Unique Constraints**: `users(email)`, `workers(name)`, `queues(project_id, name)`, `organization_members(organization_id, user_id)`
- **UUID Primary Keys**: All entities use UUID strings for API-safe identifiers

---

## Backend Engineering

### Technology Stack

- **Framework**: FastAPI 0.115.6 with Uvicorn
- **ORM**: SQLAlchemy 2.0.36 with async support
- **Database**: SQLite 3 (local) / PostgreSQL-compatible (production)
- **Authentication**: JWT (python-jose) with bcrypt password hashing
- **Validation**: Pydantic v2 for request/response schemas
- **Async**: Python asyncio with lifespan context managers

### Authentication & Authorization

```python
# JWT Token Flow
1. POST /api/auth/register → Create user + organization
2. POST /api/auth/login → Issue JWT token
3. Bearer token in Authorization header for all protected routes
4. Tokens expire after 12 hours (configurable)
```

**Role-Based Access Control**:

- `owner`: Full access to organization and projects
- Extended schema supports role-based queue/job permissions (future)

### Startup & Seed Data

On application startup:

1. Create all database tables via SQLAlchemy metadata
2. Run demo data seeding if no existing data
3. Creates demo user (`demo@example.com:demo1234`) with sample queues and jobs
4. Seeded workers with varying status (online/stale/draining/offline)

### Error Handling

- Global exception handler returns consistent JSON error responses
- HTTP status codes: 400 (validation), 401 (auth), 403 (permission), 404 (not found), 500 (server error)
- Error details include `error` code and `message` for client parsing

---

## Reliability & Concurrency

### Job State Machine

```
┌─────────┐
│ queued  │ ← Initial state for immediate jobs
└────┬────┘
     ↓
┌─────────────┐
│ scheduled   │ ← Delayed/recurring jobs waiting for run_at
└────┬────────┘
     ↓
┌─────────────┐
│ claimed     │ ← Worker atomically claims and increments attempts
└────┬────────┘
     ↓
┌─────────────┐
│ running     │ ← Job currently executing
└────┬────────┘
     ├─→ completed (success) ✓
     ├─→ scheduled (retry) ↻
     └─→ dead_lettered (terminal failure) ✗
```

### Atomic Job Claiming

Workers claim jobs atomically within a database transaction to prevent duplicate execution:

```python
# Pseudo-code: Atomic claim with status guard
UPDATE jobs
  SET status = 'claimed', locked_by_worker_id = ?, locked_at = NOW()
  WHERE id = ? AND status = 'queued' AND run_at <= NOW()
RETURNING *
```

**Key safeguards**:

- Only `queued` jobs can transition to `claimed`
- Concurrency limit enforced by counting active jobs per queue
- Dependency checking prevents dependent jobs from running early
- Stale claims (no heartbeat for 120s) are recovered and requeued

### Retry Strategy

Three configurable strategies per queue:

| Strategy        | Formula                      | Use Case                                     |
| --------------- | ---------------------------- | -------------------------------------------- |
| **Fixed**       | delay = base                 | Simple fixed backoff (e.g., retry every 30s) |
| **Linear**      | delay = base × attempt       | Gradually increase wait time                 |
| **Exponential** | delay = base × 2^(attempt-1) | Avoid thundering herd                        |

Max delay capped to prevent infinite backoff (default 3600s).

### Worker Heartbeats

Workers emit heartbeats every polling interval with:

- Active job count
- Total capacity
- Timestamp

Health detection: Workers marked `stale` if last heartbeat > 45 seconds old and status = `online`.

### Graceful Shutdown

On SIGINT/SIGTERM:

1. Worker transitions to `draining` state (rejects new claims)
2. Waits up to 30s for in-flight jobs to complete
3. Transitions to `offline` state
4. Final heartbeat confirms shutdown

---

## Frontend & UX

### Technology Stack

- **HTML/CSS/JavaScript**: Vanilla (no build step)
- **Styling**: Custom CSS with dark theme
- **Real-time Updates**: Fetch API polling every 5 seconds
- **State Management**: Client-side (no persistence needed)

### Dashboard Sections

#### 1. **Overview** (Home)

- Key metrics: Queued, Running, Completed, Dead Letter counts
- 15-minute window for recent completion rate
- Queue health panel with pause/resume controls
- Worker status panel with load percentages

#### 2. **Queues**

- Full list of queues in current organization
- Queue configuration: priority, concurrency limit, rate limit
- Active slot utilization (e.g., 2/4)
- Pause/resume controls
- Link to create new jobs in each queue

#### 3. **Jobs**

- Paginated job list (default 50, max 200 per page)
- Filters: status, queue, created time
- Job details: ID, queue, status, kind, attempt count
- Inspector view: full payload, execution history, logs, dead letter details

#### 4. **Workers**

- Active worker list with status indicators
- Metrics: capacity, active job count, load percentage
- Last heartbeat timestamp
- Worker health: online, stale, draining, offline

#### 5. **Logs** (Future)

- Append-only job logs
- Filter by job, execution, level (info/warning/error)
- Export/download capability

### Live Polling

Frontend polls key endpoints every 5 seconds:

- `GET /api/metrics` → Job/worker counts
- `GET /api/queues` → Queue status
- `GET /api/workers` → Worker health
- `GET /api/jobs?limit=50` → Recent job activity

Smooth updates without full page refresh.

---

## API Design

### Authentication

```http
POST /api/auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepass123",
  "full_name": "John Doe",
  "organization_name": "Acme Corp"
}

Response 200:
{
  "user_id": "uuid",
  "organization_id": "uuid",
  "project_id": "uuid"
}
```

```http
POST /api/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepass123"
}

Response 200:
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer"
}
```

### Project Management

```http
GET /api/projects
Authorization: Bearer <token>

Response 200:
[
  {
    "id": "proj-uuid",
    "organization_id": "org-uuid",
    "name": "Payments Platform",
    "description": "Background jobs for payment operations"
  }
]
```

### Queue Operations

```http
POST /api/projects/{project_id}/queues
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "critical-payments",
  "priority": 10,
  "concurrency_limit": 3,
  "retry_strategy": "exponential",
  "max_attempts": 4,
  "base_delay_seconds": 30,
  "max_delay_seconds": 3600,
  "rate_limit_per_minute": 0,
  "shard_key": "default"
}

Response 201:
{
  "id": "queue-uuid",
  "project_id": "proj-uuid",
  "name": "critical-payments",
  "status": "active",
  "retry_policy": {
    "strategy": "exponential",
    "max_attempts": 4,
    "base_delay_seconds": 30,
    "max_delay_seconds": 3600
  }
}
```

### Job Submission

```http
POST /api/queues/{queue_id}/jobs
Authorization: Bearer <token>
Content-Type: application/json

{
  "kind": "immediate",
  "payload": {"task": "process_payment", "amount": 99.99},
  "priority": 5,
  "delay_seconds": 0,
  "max_attempts": 3
}

Response 201:
{
  "id": "job-uuid",
  "queue_id": "queue-uuid",
  "kind": "immediate",
  "status": "queued",
  "payload": {"task": "process_payment", "amount": 99.99},
  "priority": 5,
  "attempts": 0,
  "created_at": "2026-07-04T10:30:00Z"
}
```

### Batch Job Submission

```http
POST /api/queues/{queue_id}/jobs/batch
Authorization: Bearer <token>
Content-Type: application/json

{
  "batch_key": "daily-email-campaign-20260704",
  "jobs": [
    {"kind": "immediate", "payload": {"recipient": "user1@example.com"}},
    {"kind": "immediate", "payload": {"recipient": "user2@example.com"}},
    {"kind": "immediate", "payload": {"recipient": "user3@example.com"}}
  ]
}

Response 201:
{
  "batch_key": "daily-email-campaign-20260704",
  "jobs": [...]
}
```

### Metrics & Observability

```http
GET /api/metrics
Authorization: Bearer <token>

Response 200:
{
  "jobs": {
    "queued": 12,
    "running": 3,
    "completed": 2847,
    "failed": 14,
    "dead_lettered": 2
  },
  "workers": {
    "online": 4,
    "stale": 1,
    "draining": 0,
    "offline": 2
  },
  "completed_last_15m": 143
}
```

### Complete API Endpoints

| Method | Endpoint                      | Purpose                    |
| ------ | ----------------------------- | -------------------------- |
| POST   | `/api/auth/register`          | Create new user            |
| POST   | `/api/auth/login`             | Authenticate and get token |
| GET    | `/api/me`                     | Get current user           |
| GET    | `/api/projects`               | List projects              |
| POST   | `/api/projects`               | Create project             |
| GET    | `/api/queues`                 | List queues                |
| POST   | `/api/projects/{id}/queues`   | Create queue               |
| PATCH  | `/api/queues/{id}`            | Update queue config        |
| POST   | `/api/queues/{id}/pause`      | Pause queue                |
| POST   | `/api/queues/{id}/resume`     | Resume queue               |
| GET    | `/api/queues/{id}/stats`      | Queue statistics           |
| POST   | `/api/queues/{id}/jobs`       | Submit single job          |
| POST   | `/api/queues/{id}/jobs/batch` | Submit batch               |
| GET    | `/api/jobs`                   | List jobs (paginated)      |
| GET    | `/api/jobs/{id}`              | Get job details + history  |
| POST   | `/api/jobs/{id}/retry`        | Retry failed job           |
| GET    | `/api/workers`                | List workers               |
| GET    | `/api/metrics`                | System metrics             |

---

## Documentation

### Running Locally

#### Setup

```powershell
# Create virtual environment
python -m venv .venv

# Activate
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

#### Start API Server

```powershell
uvicorn scheduler.main:app --reload --port 8000
```

Server runs at `http://127.0.0.1:8000`

#### Start Worker

```powershell
python -m scheduler.worker --worker-name local-worker --concurrency 4
```

Worker options:

- `--worker-name`: Unique worker identifier
- `--concurrency`: Max parallel jobs (default 4)
- `--poll-interval`: Polling frequency in seconds (default 1.0)

#### Demo Credentials

- Email: `demo@example.com`
- Password: `demo1234`

### Project Structure

```
codity_ai/
├── scheduler/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + startup
│   ├── routes.py            # REST API endpoints
│   ├── services.py          # Business logic
│   ├── models.py            # SQLAlchemy ORM
│   ├── schemas.py           # Pydantic schemas
│   ├── database.py          # DB connection & session
│   ├── auth.py              # JWT & password hashing
│   ├── worker.py            # Job execution worker
│   ├── demo_data.py         # Seed data
│   └── static/
│       ├── index.html       # Dashboard UI
│       ├── app.js           # Client logic
│       └── styles.css       # Styling
├── tests/
│   ├── smoke_test.py        # Manual smoke test
│   └── test_api.py          # Pytest regression test
├── requirements.txt         # Python dependencies
└── README.md               # Quick start
```

### Configuration

Key settings in `scheduler/auth.py`:

- `SECRET_KEY`: Change in production (currently `dev-secret-change-me`)
- `ALGORITHM`: JWT signing algorithm (HS256)
- `ACCESS_TOKEN_EXPIRE_MINUTES`: Token lifetime (default 12h)

Database URL in `scheduler/database.py`:

- `DATABASE_URL = "sqlite:///./scheduler.db"` (local)
- Supports PostgreSQL: `postgresql://user:pass@host/dbname`

---

## Testing

### Test Coverage

#### Regression Test Suite

**File**: `tests/test_api.py`

```python
def test_smoke_login_and_metrics() -> None:
    """End-to-end test: login → queues → jobs → metrics"""
    with TestClient(app) as client:
        # Login with demo user
        login = client.post("/api/auth/login", json={
            "email": "demo@example.com",
            "password": "demo1234"
        })
        assert login.status_code == 200

        # Fetch queues
        queues = client.get("/api/queues", headers=headers)
        assert queues.status_code == 200
        assert len(queues.json()) >= 1

        # Fetch jobs
        jobs = client.get("/api/jobs", headers=headers)
        assert jobs.status_code == 200

        # Fetch metrics
        metrics = client.get("/api/metrics", headers=headers)
        assert metrics.status_code == 200
```

**Run tests**:

```powershell
python -m pytest -v
```

#### Manual Smoke Test

**File**: `tests/smoke_test.py`

Validates core flows:

1. User login succeeds
2. Queues list returns 5+ queues
3. Jobs list returns results
4. Metrics endpoint returns valid JSON

Run with:

```powershell
python tests/smoke_test.py
```

### Test Scenarios (Future)

- [ ] Job claiming under concurrency limit
- [ ] Retry strategy exponential backoff
- [ ] Worker graceful shutdown
- [ ] Stale claim recovery
- [ ] Dependency job ordering
- [ ] Batch job creation
- [ ] Queue pause/resume behavior
- [ ] Dead letter queue movement
- [ ] Authentication token validation
- [ ] Role-based access control

### CI/CD Integration

Tests should run on:

1. Every commit (pre-push hook)
2. Pull request validation
3. Pre-deployment to staging/production

Example GitHub Actions workflow:

```yaml
- name: Run tests
  run: python -m pytest -v --tb=short
```

---

## Performance Considerations

### Scalability Notes

#### Local SQLite

- Suitable for development and small deployments
- Single-file database, no server overhead
- Limited to single-writer concurrency

#### PostgreSQL Migration

- Horizontal scaling with connection pooling
- Full ACID transaction support
- Use `SELECT ... FOR UPDATE SKIP LOCKED` for job claiming
- Partition `job_executions` and `job_logs` by time

### Optimization Strategies

| Concern                  | Strategy                                                              |
| ------------------------ | --------------------------------------------------------------------- |
| Job payload size         | Cap at 1MB, move large blobs to S3/object storage                     |
| Execution log growth     | Archive logs older than 30 days, keep hot data indexed                |
| Worker heartbeat history | Retain 5-minute window, `workers.last_heartbeat_at` is primary        |
| Retry scheduling         | Pre-compute `jobs.run_at` once per failure, avoid runtime calculation |
| High-volume queues       | Shard by `queue.shard_key`, run workers against subsets               |
| Connection pooling       | Use `sqlalchemy.pool.QueuePool` with min/max size                     |

### Monitoring & Observability

Recommended integrations:

- **Metrics**: Prometheus endpoint at `/metrics` (future)
- **Logging**: Structured JSON logs to ELK/Datadog
- **Tracing**: OpenTelemetry instrumentation on job lifecycle
- **Alerting**: Threshold-based alerts on dead letter rate, worker offline count

---

## Summary

This distributed job scheduler provides a **production-ready foundation** for reliable background job processing. Key strengths:

✅ **Atomic job claiming** prevents duplicate execution  
✅ **Multi-worker scaling** with heartbeat health detection  
✅ **Flexible retry strategies** (fixed, linear, exponential)  
✅ **Full audit trail** with immutable execution records  
✅ **Real-time dashboard** with live metrics polling  
✅ **Role-aware multi-tenancy** for organizational isolation  
✅ **Graceful degradation** under failure (stale claim recovery)  
✅ **Database-agnostic** (SQLite → PostgreSQL migration path)

## Ready for deployment in production environments with appropriate scaling, monitoring, and security hardening.

## Dashboard Screenshots

The following screenshots showcase the real-time dashboard UI in action:

### Overview Dashboard

The main dashboard displays system-wide metrics at a glance:

- **Queued**: 0 jobs waiting to run
- **Running**: 2 jobs currently executing
- **Completed**: 13 jobs with 10 in the last 15 minutes
- **Dead Letter**: 1 job in terminal failure state
- **Queue Health**: All 5 queues with status and slot utilization
- **Workers**: 5 workers with varying status (online, stale, draining, offline)
- **Live polling**: Updates every 5 seconds with green indicator

Key features visible:

- Navigation sidebar with all views (Overview, Queues, Jobs, Workers, Logs)
- User authentication display (demo@example.com)
- Refresh button for manual updates
- Color-coded status indicators (green=active, orange=paused, red=offline)

![Overview Dashboard](dashboard-overview.png)

### Queues Management

Dedicated view for queue management and configuration:

- **Queue List**: All 5 project queues with full details
- **Priority**: P1-P10 priority levels for scheduling preference
- **Concurrency**: Concurrency limits per queue (2-6 slots)
- **Status**: Active/Paused toggle with visual indicators
- **Controls**: Individual pause/resume buttons per queue
- **Rate Limits**: Webhook queue has 120/min rate limit configured
- **Project Association**: Shows parent project UUID for multi-tenancy

Visible queues:

1. **webhooks** (P7, 4 slots, rate-limited)
2. **media-processing** (P3, 2 slots)
3. **email-notifications** (P4, 6 slots)
4. **reports** (P1, 2 slots)
5. **critical-payments** (P10, 3 slots - highest priority)

![Queues Management](dashboard-queues.png)

### Jobs List & Monitoring

Real-time job execution tracking and history:

- **Job ID**: Unique identifier for each job (first 8 chars visible)
- **Queue**: Associated queue and timestamp (e.g., "email-notifications · 5h ago")
- **Status**: Color-coded indicators
  - **Green** (completed): Successfully executed
  - **Blue** (running): Currently executing on a worker
  - **Yellow** (scheduled): Waiting for scheduled time
  - **Red** (dead lettered): Terminal failure
- **Kind**: Job type (immediate, batch, scheduled, delayed, recurring)
- **Attempts**: Current attempt vs max (e.g., 1/4 attempts)
- **Inspector**: Clickable "Inspect →" to view full job details, payload, execution history, and logs

Sample jobs visible:

- Batch email notifications (completed)
- Scheduled reports job
- Running media processing with retry count
- Dead lettered webhook delivery
- Immediate payment processing jobs

![Jobs List](dashboard-jobs.png)

### Workers Status

Worker health and capacity monitoring:

- **Worker Name**: Unique identifier (worker-ash, worker-birch, etc.)
- **Status**: Visual indicator badges
  - **Online** (green): Active and accepting jobs
  - **Stale** (red): No heartbeat for 45+ seconds
  - **Draining** (orange): Graceful shutdown in progress
  - **Offline** (red): Not connected
- **Load**: Active/capacity and percentage (e.g., 1 active / 8 capacity · 13% load)
- **Concurrency**: Max jobs the worker can handle simultaneously
- **Last Heartbeat**: Time since last health check (e.g., "5h ago")

Worker pool visible:

1. **worker-ash**: 1/8 active, 13% load, stale status
2. **worker-birch**: 1/6 active, 17% load, stale status
3. **worker-cedar**: 0/4 active, 0% load, draining
4. **local-worker**: 0/4 active, 0% load, offline
5. **worker-delta**: 0/4 active, 0% load, offline

![Workers Status](dashboard-workers.png)

---

## Integration & Usage

All screenshots depict the dashboard running on `http://127.0.0.1:8000` with:

- **Authentication**: Logged in as demo@example.com (demo credentials)
- **Organization**: "Acme Operations" (demo tenant)
- **Seed Data**: Demo data automatically populated on first startup
- **Real-time Updates**: 5-second polling interval for live metrics
- **Responsive Design**: Dark theme optimized for monitoring

To view the live dashboard:

1. Start the API server: `uvicorn scheduler.main:app --reload --port 8000`
2. Open browser: `http://127.0.0.1:8000`
3. Login with `demo@example.com:demo1234`
4. Navigate between tabs to explore different views
