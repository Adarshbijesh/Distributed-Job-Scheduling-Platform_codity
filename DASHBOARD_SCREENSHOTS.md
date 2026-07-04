# Dashboard Visual Guide - Screenshots & Descriptions

## Live Dashboard Access

The dashboard is accessible at: **http://127.0.0.1:8000**

Login with demo credentials:

- Email: `demo@example.com`
- Password: `demo1234`

---

## 1. Overview Dashboard

**URL**: `http://127.0.0.1:8000/` (default view)

### Metrics Cards (Top Section)

```
┌──────────────────────────────────────────────────────────────┐
│  📦 QUEUED          🔄 RUNNING        ✅ COMPLETED      ☠️ DEAD LETTER  │
│      0                  2                 13                    1          │
│  waiting to run    currently executing  last 15m: 10     2 workers online   │
└──────────────────────────────────────────────────────────────┘
```

### Queue Health Panel

Shows all 5 queues with:

- Queue name with priority (P1-P10)
- Concurrency settings (slots used/limit)
- Status badge (active/paused)
- Pause/Resume button

**Queues visible:**

- webhooks (P7, 0/4 slots, active)
- media-processing (P3, 1/2 slots, active)
- email-notifications (P4, 1/6 slots, active)
- reports (P1, 0/2 slots, active)
- critical-payments (P10, 0/3 slots, active)

### Workers Panel

Shows all 5 workers with:

- Worker name
- Active jobs / Total capacity with load %
- Status indicator (online/stale/draining/offline)
- Last heartbeat timestamp

**Workers visible:**

- worker-ash: 1/8 active · 13% load · stale · 5h ago
- worker-birch: 1/6 active · 17% load · stale · 5h ago
- worker-cedar: 0/4 active · 0% load · draining · 5h ago
- local-worker: 0/4 active · 0% load · offline · 5h ago
- worker-delta: 0/4 active · 0% load · offline · 5h ago

### UI Features

- **User display**: "demo@example.com" in top right
- **Refresh button**: Manual data refresh (↻)
- **Live polling indicator**: "Live polling every 5s" with green dot
- **Organization**: "Acme Operations" shown in sidebar
- **Dark theme**: Blue sidebar, dark gray background, color-coded status

---

## 2. Queues Management View

**Navigation**: Click "📦 Queues" in left sidebar

### Page Header

```
Queues
Manage queue priorities, concurrency limits and pause/resume
```

### Queue Cards

Each queue shows:

- **Name**: Queue identifier
- **Project**: Parent project UUID
- **Rate Limit**: Per-minute rate limit (if configured)
- **Status**: Active/Paused badge
- **Priority**: P{1-10} level
- **Concurrency**: Current capacity limit
- **Controls**: Pause/Resume button

### Full Queue List

1. **webhooks**
   - Project: 26136a14
   - Rate limit: 120/min
   - Status: active (green)
   - Priority: P7
   - Concurrency: 4

2. **media-processing**
   - Project: 26136a14
   - Rate limit: None
   - Status: active (green)
   - Priority: P3
   - Concurrency: 2

3. **email-notifications**
   - Project: 26136a14
   - Rate limit: None
   - Status: active (green)
   - Priority: P4
   - Concurrency: 6

4. **reports**
   - Project: 26136a14
   - Rate limit: None
   - Status: active (green)
   - Priority: P1
   - Concurrency: 2

5. **critical-payments**
   - Project: 26136a14
   - Rate limit: None
   - Status: active (green)
   - Priority: P10
   - Concurrency: 3

### Features

- "+ New Job" button to submit jobs to any queue
- Each queue has independent pause/resume control
- Visual priority ordering (P10 highest, P1 lowest)

---

## 3. Jobs List View

**Navigation**: Click "🔧 Jobs" in left sidebar

### Page Header

```
Jobs
Paginated view of all jobs with status and execution history
```

### Job Table

Each job row displays:

- **Job ID** (first 8 chars visible)
- **Queue** + timestamp (e.g., "email-notifications · 5h ago")
- **Status** (color-coded):
  - Green: completed ✓
  - Blue: running ⟳
  - Yellow: scheduled ⏱
  - Red: dead lettered ✗
- **Kind**: Job type (immediate, batch, scheduled, delayed, recurring)
- **Attempts**: Current/Max (e.g., 1/4)
- **Inspector**: "Inspect →" button for details

### Sample Jobs Visible

**Completed Jobs:**

- 842900e7 | email-notifications · 5h ago | completed | batch | 1/4
- 8c587476 | email-notifications · 5h ago | completed | batch | 1/4
- c49b5169 | email-notifications · 5h ago | completed | batch | 1/4
- 19c58492 | webhooks · 5h ago | completed | immediate | 1/4
- ec6fb805 | critical-payments · 5h ago | completed | immediate | 1/4
- 1b1410be | reports · 5h ago | completed | immediate | 1/4

**Running Jobs:**

- a4f620e8 | email-notifications · 5h ago | running | immediate | 1/4
- 2abf3978 | media-processing · 5h ago | running | immediate | 2/4

**Scheduled Jobs:**

- bd9bafd6 | reports · 5h ago | scheduled | scheduled | 0/4
- e48f899c | media-processing · 6h ago | scheduled | scheduled | 0/4
- 53f0be4f | reports · 5h ago | scheduled | recurring | 0/4

**Dead Lettered:**

- 889359e7 | webhooks · 6h ago | dead lettered | immediate | 4/4

### Pagination

- Default: 50 jobs per page
- Shows "Showing 20 of 20 jobs" indicator
- Scrollable job list

### Inspector Feature

Click "Inspect →" on any job to see:

- Full payload JSON
- Execution history with worker assignment
- Job logs with timestamps
- Dead letter details (if failed)
- Retry history

---

## 4. Workers Status View

**Navigation**: Click "🖥️ Workers" in left sidebar

### Page Header

```
Workers
Monitor worker heartbeats, capacity, and active job counts
```

### Worker Cards

Each worker displays:

- **Name**: Worker identifier
- **Active/Capacity**: e.g., "1 active / 8 capacity · 13% load"
- **Status Badge**:
  - Green: online (actively working)
  - Red: stale (no heartbeat 45s+)
  - Orange: draining (graceful shutdown)
  - Gray: offline (disconnected)
- **Max Concurrency**: Worker's capacity limit
- **Last Heartbeat**: Timestamp (e.g., "5h ago")

### Full Worker Pool

1. **worker-ash**
   - Status: stale
   - Load: 1 active / 8 capacity · 13% load
   - Concurrency: 8
   - Heartbeat: 5h ago

2. **worker-birch**
   - Status: stale
   - Load: 1 active / 6 capacity · 17% load
   - Concurrency: 6
   - Heartbeat: 5h ago

3. **worker-cedar**
   - Status: draining
   - Load: 0 active / 4 capacity · 0% load
   - Concurrency: 4
   - Heartbeat: 5h ago

4. **local-worker**
   - Status: offline
   - Load: 0 active / 4 capacity · 0% load
   - Concurrency: 4
   - Heartbeat: 5h ago

5. **worker-delta**
   - Status: offline
   - Load: 0 active / 4 capacity · 0% load
   - Concurrency: 4
   - Heartbeat: 5h ago

### Health Indicators

- **Online**: Worker actively polling and accepting jobs
- **Stale**: Worker hasn't sent heartbeat for 45+ seconds
- **Draining**: Worker in graceful shutdown, rejecting new jobs
- **Offline**: Worker disconnected or crashed

---

## 5. Real-Time Updates

### Auto-Refresh

- **Interval**: 5 seconds
- **Indicator**: Green dot next to "Live polling every 5s"
- **No page reload**: Smooth updates via Fetch API

### Endpoints Polled

```
GET /api/metrics           (every 5s)
GET /api/queues            (every 5s)
GET /api/workers           (every 5s)
GET /api/jobs?limit=50     (every 5s)
```

### Manual Refresh

- **Refresh Button**: ↻ in top right corner
- **Purpose**: Force immediate data update
- **Result**: All sections refresh instantly

---

## 6. Navigation & Layout

### Sidebar Navigation

```
⚡ JobScheduler
  Distributed queues

NAVIGATION
├─ 📊 Overview      (main metrics dashboard)
├─ 📦 Queues        (queue configuration)
├─ 🔧 Jobs          (job list & inspector)
├─ 🖥️ Workers        (worker status)
└─ 📋 Logs          (future: job logs)

STATUS
├─ Live polling every 5s ✓
└─ Acme Operations     (current org)
```

### Color Coding

**Status Indicators:**

- 🟢 Green: active, online, completed, healthy
- 🔴 Red: offline, stale, dead lettered, failed
- 🟠 Orange: paused, draining, warning
- 🔵 Blue: running, in progress

**Background:**

- Dark navy sidebar
- Dark gray main content area
- High contrast for readability

---

## 7. Key Features Demonstrated

### ✅ Multi-Tenancy

- User authenticated to specific organization
- Data scoped to organization membership
- Projects and queues isolated per org

### ✅ Real-Time Monitoring

- 5-second polling for live updates
- No page reload needed
- Smooth metric transitions

### ✅ Queue Management

- Pause/resume controls visible and functional
- Priority-based ordering (P1-P10)
- Concurrency limits displayed

### ✅ Job Lifecycle

- Job status transitions tracked
- Attempt counting for retries
- Failed jobs in dead letter queue

### ✅ Worker Health

- Heartbeat timestamp tracking
- Status transitions (online → stale → offline)
- Load percentage calculation
- Capacity management

### ✅ Dark Theme UI

- Professional dashboard appearance
- Emoji icons for quick scanning
- Status badges with clear semantics
- Responsive layout

---

## 8. How to Interact with Dashboard

### Navigation

1. Click sidebar buttons to switch views
2. Use Refresh button for manual updates
3. Scroll to see more items in paginated lists

### Job Inspection

1. Navigate to Jobs tab
2. Find job in list
3. Click "Inspect →" button
4. View full details including:
   - Payload JSON
   - Execution history
   - Worker assignment
   - Logs
   - Dead letter info

### Queue Control

1. Navigate to Queues tab
2. Find queue
3. Click "Pause" to stop new jobs
4. Click "Resume" to accept jobs again

### Worker Monitoring

1. Navigate to Workers tab
2. Watch for status changes
3. Monitor load percentage and active jobs
4. Check heartbeat timestamps for health

---

## Summary

The dashboard provides a **complete real-time view** of the distributed job scheduler with:

- System-wide metrics (queued, running, completed, failed)
- Queue configuration and control
- Job execution tracking and inspection
- Worker health monitoring
- Live polling updates every 5 seconds
- Multi-tenant isolation
- Professional dark theme UI
- Responsive design

Perfect for monitoring and managing background job workloads in production.
