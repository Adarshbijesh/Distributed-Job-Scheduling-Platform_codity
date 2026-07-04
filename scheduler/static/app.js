// ── State ──────────────────────────────────────────────────────────────────
const state = {
  token: localStorage.getItem("schedulerToken"),
  queues: [],
  jobs: [],
  workers: [],
  metrics: {},
  selectedJobId: null,
  currentView: "overview",
};

// ── API helper ──────────────────────────────────────────────────────────────
async function api(path, options = {}) {
  if (!state.token) await login();
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${state.token}`,
      ...(options.headers || {}),
    },
  });
  if (response.status === 401) {
    localStorage.removeItem("schedulerToken");
    state.token = null;
    await login();
    return api(path, options);
  }
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function login() {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: "demo@example.com", password: "demo1234" }),
  });
  const data = await response.json();
  state.token = data.access_token;
  localStorage.setItem("schedulerToken", state.token);
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function pill(value) {
  return `<span class="pill ${value}">${value.replace("_", " ")}</span>`;
}

function short(id) {
  return id ? id.slice(0, 8) : "—";
}

function relativeTime(isoStr) {
  if (!isoStr) return "—";
  const diff = Date.now() - new Date(isoStr).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

function formatDuration(ms) {
  if (!ms || ms === 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function statusIcon(status) {
  const icons = {
    queued: "⏳", scheduled: "🕐", claimed: "🔒", running: "⚡",
    completed: "✅", failed: "❌", dead_lettered: "💀",
    online: "🟢", draining: "🟡", offline: "🔴", stale: "🟠", active: "🟢", paused: "⏸",
  };
  return icons[status] || "•";
}

function emptyState(icon, message) {
  return `<div class="empty-state"><div class="empty-icon">${icon}</div><p>${message}</p></div>`;
}

// ── Data loading ─────────────────────────────────────────────────────────────
async function load() {
  try {
    const statusVal = document.querySelector("#statusFilter")?.value || "";
    const queueVal  = document.querySelector("#queueFilter")?.value  || "";
    let jobUrl = `/api/jobs?limit=50`;
    if (statusVal) jobUrl += `&status=${statusVal}`;
    if (queueVal)  jobUrl += `&queue_id=${queueVal}`;

    const [metricsRes, queuesRes, workersRes, jobsRes] = await Promise.allSettled([
      api("/api/metrics"),
      api("/api/queues"),
      api("/api/workers"),
      api(jobUrl),
    ]);

    const metrics = metricsRes.status  === "fulfilled" ? metricsRes.value  : {};
    const queues  = queuesRes.status   === "fulfilled" ? queuesRes.value   : [];
    const workers = workersRes.status  === "fulfilled" ? workersRes.value  : [];
    const jobs    = jobsRes.status     === "fulfilled" ? jobsRes.value     : { items: [], total: 0 };

    if (workersRes.status === "rejected") {
      console.warn("Workers API error:", workersRes.reason);
    }

    state.metrics = metrics;
    state.queues  = queues;
    state.workers = workers;
    state.jobs    = jobs.items;

    renderMetrics(metrics);
    renderQueueOverview(queues);
    renderWorkerOverview(workers);
    renderQueuesTable(queues);
    renderWorkers(workers);
    renderJobs(jobs);
    renderSelectors(queues);
  } catch (err) {
    console.error("Load error:", err);
  }
}

// ── Metrics ─────────────────────────────────────────────────────────────────
function renderMetrics(data) {
  const j = data.jobs || {};
  const w = data.workers || {};
  const onlineWorkers = (w.online || 0);
  const cards = [
    { label: "Queued",      value: j.queued || 0,       sub: "waiting to run",        color: "blue"   },
    { label: "Running",     value: (j.running||0)+(j.claimed||0), sub: "currently executing", color: "green" },
    { label: "Completed",   value: j.completed || 0,    sub: `last 15m: ${data.completed_last_15m||0}`, color: "yellow" },
    { label: "Dead Letter", value: j.dead_lettered || 0, sub: `${onlineWorkers} workers online`, color: "red" },
  ];
  document.querySelector("#metrics").innerHTML = cards.map((c, i) => `
    <div class="metric">
      <div class="metric-label">${c.label}</div>
      <strong>${c.value}</strong>
      <div class="metric-sub">${c.sub}</div>
    </div>
  `).join("");
}

// ── Queue Overview (sidebar panel) ──────────────────────────────────────────
function renderQueueOverview(queues) {
  document.querySelector("#queueCount").textContent = queues.length;
  if (!queues.length) {
    document.querySelector("#queueHealth").innerHTML = emptyState("📦", "No queues found");
    return;
  }
  document.querySelector("#queueHealth").innerHTML = queues.map(q => `
    <div class="row queue-row">
      <div>
        <div class="row-name">${q.name}</div>
        <div class="row-sub">Priority ${q.priority} · Concurrency ${q.concurrency_limit}</div>
      </div>
      ${pill(q.status)}
      <span class="mono">${q.active_slots ?? 0}/${q.concurrency_limit} slots</span>
      <button class="btn ${q.status === 'paused' ? 'btn-warn' : ''}"
        data-action="${q.status === 'paused' ? 'resume' : 'pause'}" data-id="${q.id}">
        ${q.status === 'paused' ? '▶ Resume' : '⏸ Pause'}
      </button>
    </div>
  `).join("");
}

// ── Worker Overview (sidebar panel) ─────────────────────────────────────────
function renderWorkerOverview(workers) {
  document.querySelector("#workerCount").textContent = workers.length;
  if (!workers.length) {
    document.querySelector("#workerHealth").innerHTML = emptyState("🖥️", "No workers registered");
    return;
  }
  document.querySelector("#workerHealth").innerHTML = workers.map(w => {
    const pct = w.capacity > 0 ? Math.round((w.active_jobs / w.capacity) * 100) : 0;
    return `
    <div class="row worker">
      <div>
        <div class="row-name">${w.name}</div>
        <div class="capacity-bar"><div class="capacity-fill" style="width:${pct}%"></div></div>
        <div class="row-sub">${w.active_jobs}/${w.capacity} active · ${pct}% load</div>
      </div>
      ${pill(w.status)}
      <span class="mono" style="font-size:11px;">${relativeTime(w.last_heartbeat_at)}</span>
    </div>
  `}).join("");
}

// ── Queues Table (full page) ─────────────────────────────────────────────────
function renderQueuesTable(queues) {
  if (!queues.length) {
    document.querySelector("#queuesTable").innerHTML = emptyState("📦", "No queues yet");
    return;
  }
  document.querySelector("#queuesTable").innerHTML = queues.map(q => `
    <div class="row queue-row">
      <div>
        <div class="row-name">${q.name}</div>
        <div class="row-sub">${q.project_id ? `Project: ${short(q.project_id)}` : ''} · Rate limit: ${q.rate_limit_per_minute > 0 ? q.rate_limit_per_minute + '/min' : 'None'}</div>
      </div>
      ${pill(q.status)}
      <div>
        <div style="font-weight:600;">P${q.priority}</div>
        <div class="row-sub">priority</div>
      </div>
      <div>
        <div style="font-weight:600;">${q.concurrency_limit}</div>
        <div class="row-sub">concurrency</div>
      </div>
      <button class="btn ${q.status === 'paused' ? 'btn-warn' : ''}"
        data-action="${q.status === 'paused' ? 'resume' : 'pause'}" data-id="${q.id}">
        ${q.status === 'paused' ? '▶ Resume' : '⏸ Pause'}
      </button>
    </div>
  `).join("");
}

// ── Workers Table (full page) ─────────────────────────────────────────────────
function renderWorkers(workers) {
  if (!workers.length) {
    document.querySelector("#workersTable").innerHTML = emptyState("🖥️", "No workers registered");
    return;
  }
  document.querySelector("#workersTable").innerHTML = workers.map(w => {
    const pct = w.capacity > 0 ? Math.round((w.active_jobs / w.capacity) * 100) : 0;
    return `
    <div class="row worker">
      <div>
        <div class="row-name">${w.name}</div>
        <div class="capacity-bar" style="max-width:180px;"><div class="capacity-fill" style="width:${pct}%"></div></div>
        <div class="row-sub">${w.active_jobs} active / ${w.capacity} capacity · ${pct}% load</div>
      </div>
      ${pill(w.status)}
      <div>
        <div style="font-weight:600;">${w.capacity}</div>
        <div class="row-sub">max concurrency</div>
      </div>
      <div>
        <div class="mono">${relativeTime(w.last_heartbeat_at)}</div>
        <div class="row-sub">last heartbeat</div>
      </div>
    </div>
  `}).join("");
}

// ── Jobs Table ────────────────────────────────────────────────────────────────
function renderJobs(data) {
  const jobs = data.items || [];
  const total = data.total || 0;
  if (!jobs.length) {
    document.querySelector("#jobsTable").innerHTML = emptyState("🔧", "No jobs match this filter");
    return;
  }
  const queueMap = {};
  state.queues.forEach(q => queueMap[q.id] = q.name);

  document.querySelector("#jobsTable").innerHTML = `
    <div style="color:var(--text-2);font-size:12px;padding:0 4px;margin-bottom:4px;">
      Showing ${jobs.length} of ${total} jobs
    </div>
  ` + jobs.map(j => `
    <div class="row job">
      <div>
        <div class="row-name mono">${short(j.id)}</div>
        <div class="row-sub">${queueMap[j.queue_id] || short(j.queue_id)} · ${relativeTime(j.created_at)}</div>
      </div>
      ${pill(j.status)}
      <div>
        <span class="mono" style="font-size:12px;">${j.kind}</span>
      </div>
      <div>
        <div style="font-weight:600;">${j.attempts}/${j.max_attempts}</div>
        <div class="row-sub">attempts</div>
      </div>
      <button class="btn" data-job="${j.id}">Inspect →</button>
    </div>
  `).join("");
}

// ── Job Detail ────────────────────────────────────────────────────────────────
async function inspectJob(jobId) {
  state.selectedJobId = jobId;
  const job = await api(`/api/jobs/${jobId}`);
  const queueMap = {};
  state.queues.forEach(q => queueMap[q.id] = q.name);

  document.querySelector("#jobDetailCard").style.display = "block";
  document.querySelector("#jobDetail").innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px;">
      <div class="detail-field">
        <label>Job ID</label>
        <p class="mono">${short(job.id)}</p>
      </div>
      <div class="detail-field">
        <label>Status</label>
        <p>${pill(job.status)}</p>
      </div>
      <div class="detail-field">
        <label>Kind</label>
        <p class="mono">${job.kind}</p>
      </div>
      <div class="detail-field">
        <label>Queue</label>
        <p>${queueMap[job.queue_id] || short(job.queue_id)}</p>
      </div>
      <div class="detail-field">
        <label>Attempts</label>
        <p>${job.attempts} / ${job.max_attempts}</p>
      </div>
      <div class="detail-field">
        <label>Priority</label>
        <p>${job.priority}</p>
      </div>
      <div class="detail-field">
        <label>Created</label>
        <p>${relativeTime(job.created_at)}</p>
      </div>
      <div class="detail-field">
        <label>Run At</label>
        <p>${relativeTime(job.run_at)}</p>
      </div>
      <div class="detail-field">
        <label>Completed</label>
        <p>${relativeTime(job.completed_at)}</p>
      </div>
    </div>

    <details style="margin-bottom:16px;">
      <summary style="cursor:pointer;color:var(--text-2);font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;">
        Payload
      </summary>
      <pre style="margin-top:10px;padding:12px;background:#0a0f1a;border:1px solid var(--border);border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:12px;color:#94c5f8;overflow:auto;">${JSON.stringify(typeof job.payload === 'string' ? JSON.parse(job.payload || '{}') : (job.payload || {}), null, 2)}</pre>
    </details>

    ${job.dead_letter ? `
      <div style="background:var(--red-bg);border:1px solid var(--red);border-radius:8px;padding:14px;margin-bottom:16px;">
        <div style="font-weight:700;color:var(--red);margin-bottom:6px;">💀 Dead Letter Entry</div>
        <div style="font-size:13px;color:var(--text);">${job.dead_letter.failure_summary}</div>
        <div class="mono" style="font-size:11px;color:var(--text-2);margin-top:4px;">${job.dead_letter.final_error}</div>
      </div>
    ` : ''}

    <div style="font-size:13px;font-weight:600;margin-bottom:10px;">Executions (${job.executions.length})</div>
    <div class="table" style="margin-bottom:20px;">
      ${job.executions.length ? job.executions.map(e => `
        <div class="row job">
          <div class="mono">${short(e.id)}</div>
          ${pill(e.status)}
          <span>Attempt ${e.attempt_number}</span>
          <span>${formatDuration(e.duration_ms)}</span>
          <span class="mono" style="font-size:11px;color:var(--red);">${e.error || ''}</span>
        </div>
      `).join('') : emptyState('📋', 'No executions yet')}
    </div>

    <div style="font-size:13px;font-weight:600;margin-bottom:10px;">Logs (${job.logs.length})</div>
    <div class="logs">
      ${job.logs.length ? job.logs.map(l => `
        <div class="logline">
          <span class="log-time">${new Date(l.created_at).toLocaleTimeString()}</span>
          <span class="log-level ${l.level}">${l.level}</span>
          <span class="log-msg">${l.message}</span>
        </div>
      `).join('') : emptyState('📋', 'No logs yet')}
    </div>

    ${job.status === 'dead_lettered' || job.status === 'failed' ? `
      <div style="margin-top:20px;display:flex;justify-content:flex-end;">
        <button class="btn btn-danger" data-retry="${job.id}">🔄 Retry Job</button>
      </div>
    ` : ''}
  `;

  // Also update logs panel
  document.querySelector("#logsPanel").innerHTML = job.logs.length
    ? job.logs.map(l => `
        <div class="logline">
          <span class="log-time">${new Date(l.created_at).toLocaleTimeString()}</span>
          <span class="log-level ${l.level}">${l.level}</span>
          <span class="log-msg">job <strong>${short(job.id)}</strong> — ${l.message}</span>
        </div>
      `).join('')
    : emptyState('📋', 'Select a job to see its logs here.');

  document.querySelector("#jobDetailCard").scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Selectors ─────────────────────────────────────────────────────────────────
function renderSelectors(queues) {
  const options = queues.map(q => `<option value="${q.id}">${q.name}</option>`).join("");
  document.querySelector("#jobQueue").innerHTML = options;

  const filterOptions = `<option value="">All queues</option>` +
    queues.map(q => `<option value="${q.id}">${q.name}</option>`).join("");
  document.querySelector("#queueFilter").innerHTML = filterOptions;
}

// ── Navigation ────────────────────────────────────────────────────────────────
const pageTitles = {
  overview: ["Overview", "Real-time distributed queue health and execution monitoring"],
  queues:   ["Queues",   "Manage queue priorities, concurrency limits and pause/resume"],
  jobs:     ["Job Explorer", "Browse, filter, and inspect individual job executions"],
  workers:  ["Workers",  "Monitor worker heartbeats, capacity, and active job counts"],
  logs:     ["Execution Logs", "Recent job execution log lines across all queues"],
};

function switchView(view) {
  document.querySelectorAll(".nav").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".view").forEach(el => el.classList.remove("active"));
  document.querySelector(`#nav-${view}`)?.classList.add("active");
  document.querySelector(`#${view}`)?.classList.add("active");
  const [title, sub] = pageTitles[view] || ["Dashboard", ""];
  document.querySelector("#pageTitle").textContent = title;
  document.querySelector("#subtitle").textContent = sub;
  state.currentView = view;
}

// ── Events ────────────────────────────────────────────────────────────────────
document.addEventListener("click", async (event) => {
  // Navigation
  const nav = event.target.closest(".nav[data-view]");
  if (nav) { switchView(nav.dataset.view); return; }

  // Queue pause/resume
  const action = event.target.dataset.action;
  if (action && event.target.dataset.id) {
    event.target.disabled = true;
    try {
      await api(`/api/queues/${event.target.dataset.id}/${action}`, { method: "POST" });
      await load();
    } finally {
      event.target.disabled = false;
    }
    return;
  }

  // Job inspect
  if (event.target.dataset.job) {
    await inspectJob(event.target.dataset.job);
    return;
  }

  // Job retry
  if (event.target.dataset.retry) {
    event.target.disabled = true;
    try {
      await api(`/api/jobs/${event.target.dataset.retry}/retry`, { method: "POST" });
      await load();
      await inspectJob(event.target.dataset.retry);
    } finally {
      event.target.disabled = false;
    }
    return;
  }

  // Create job dialog
  if (event.target.id === "createJobBtn" || event.target.id === "createJobBtn2") {
    document.querySelector("#jobDialog").showModal();
    return;
  }

  // Close detail
  if (event.target.id === "closeDetail") {
    document.querySelector("#jobDetailCard").style.display = "none";
    state.selectedJobId = null;
    return;
  }

  // Cancel dialog
  if (event.target.id === "cancelJob") {
    document.querySelector("#jobDialog").close();
    return;
  }
});

document.querySelector("#refreshBtn").addEventListener("click", load);
document.querySelector("#statusFilter").addEventListener("change", load);
document.querySelector("#queueFilter").addEventListener("change", load);

document.querySelector("#submitJob").addEventListener("click", async () => {
  const payloadRaw = document.querySelector("#jobPayload").value;
  let payload;
  try { payload = JSON.parse(payloadRaw); }
  catch { alert("Invalid JSON payload"); return; }

  const btn = document.querySelector("#submitJob");
  btn.disabled = true;
  btn.textContent = "Creating…";
  try {
    await api(`/api/queues/${document.querySelector("#jobQueue").value}/jobs`, {
      method: "POST",
      body: JSON.stringify({
        kind: document.querySelector("#jobKind").value,
        payload,
        delay_seconds: Number(document.querySelector("#jobDelay").value || 0),
      }),
    });
    document.querySelector("#jobDialog").close();
    await load();
  } catch(e) {
    alert("Failed to create job: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Create Job";
  }
});

// ── Logs empty state ─────────────────────────────────────────────────────────
document.querySelector("#logsPanel").innerHTML = emptyState("📋", "Select a job from the Jobs view to see its execution logs here.");

// ── Init ─────────────────────────────────────────────────────────────────────
load();
setInterval(load, 5000);
