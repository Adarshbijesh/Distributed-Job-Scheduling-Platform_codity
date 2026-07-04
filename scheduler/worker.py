from __future__ import annotations

import argparse
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

from .database import Base, engine, session_scope
from .models import Job, WorkerStatus
from .services import (
    claim_next_job,
    complete_execution,
    fail_execution,
    heartbeat,
    json_loads,
    mark_worker,
    recover_stale_claims,
    register_worker,
    simulate_job,
    start_execution,
)

shutdown = threading.Event()


def install_signal_handlers() -> None:
    def handle_signal(signum, frame):
        shutdown.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)


def execute_job(job_id: str, execution_id: str) -> None:
    started = time.perf_counter()
    try:
        with session_scope() as db:
            start_execution(db, job_id, execution_id)
            payload = json_loads(db.get(Job, job_id).payload)
        duration_ms = int(payload.get("duration_ms", 500))
        time.sleep(max(duration_ms, 25) / 1000)
        simulate_job(payload)
        with session_scope() as db:
            complete_execution(db, job_id, execution_id, int((time.perf_counter() - started) * 1000))
    except Exception as exc:
        with session_scope() as db:
            fail_execution(db, job_id, execution_id, int((time.perf_counter() - started) * 1000), str(exc))


def run_worker(worker_name: str, concurrency: int, poll_interval: float) -> None:
    Base.metadata.create_all(bind=engine)
    install_signal_handlers()
    with session_scope() as db:
        worker = register_worker(db, worker_name, concurrency)
        worker_id = worker.id

    active = set()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        while not shutdown.is_set():
            active = {future for future in active if not future.done()}
            claimed = []
            with session_scope() as db:
                recover_stale_claims(db)
                heartbeat(db, worker_id, len(active), concurrency)
                slots_available = concurrency - len(active)
                while slots_available > 0:
                    worker = register_worker(db, worker_name, concurrency)
                    job, execution = claim_next_job(db, worker)
                    if not job or not execution:
                        break
                    claimed.append((job.id, execution.id))
                    slots_available -= 1
            for job_id, execution_id in claimed:
                active.add(executor.submit(execute_job, job_id, execution_id))
            time.sleep(poll_interval)

        with session_scope() as db:
            mark_worker(db, worker_id, WorkerStatus.draining)
        wait(active, timeout=30)
        with session_scope() as db:
            heartbeat(db, worker_id, 0, concurrency)
            mark_worker(db, worker_id, WorkerStatus.offline)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a job scheduler worker")
    parser.add_argument("--worker-name", default="local-worker")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args()
    run_worker(args.worker_name, args.concurrency, args.poll_interval)


if __name__ == "__main__":
    main()
