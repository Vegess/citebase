"""A small durable job queue on Postgres. No Redis.

Claiming uses SELECT ... FOR UPDATE SKIP LOCKED: a worker locks one queued
row and other workers skip past it instead of waiting, so two workers never
run the same job. (On SQLite, used for tests and local dev, SQLAlchemy drops
the FOR UPDATE clause; a single in-process worker is assumed there.)

Failures retry with backoff up to max_attempts. A job left `running` by a
crashed process is requeued once its lock is older than STALE_AFTER.

The worker wakes immediately when work is enqueued and otherwise polls
rarely, so an idle app does not keep the Neon database awake.
"""
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.models import Job

logger = logging.getLogger("app.services.jobs")

STALE_AFTER = timedelta(minutes=10)
IDLE_POLL_SECONDS = 15 * 60
BACKOFF = [timedelta(seconds=10), timedelta(seconds=60), timedelta(minutes=5)]


@dataclass
class Handler:
    run: Callable[[Session, dict], None]
    # Called in a fresh transaction after `run` raised. `final` is True when no
    # retries remain. Must leave domain state consistent (e.g. mark doc failed).
    on_error: Callable[[Session, dict, Exception, bool], None] | None = None
    # Payload keys to drop once the job finishes, so bulky input (extracted
    # document text) does not sit in the jobs table forever.
    scrub_keys: tuple[str, ...] = ()


HANDLERS: dict[str, Handler] = {}
_wake = threading.Event()


def register(kind: str, handler: Handler) -> None:
    HANDLERS[kind] = handler


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def enqueue(db: Session, kind: str, payload: dict) -> Job:
    """Add a job inside the caller's transaction: it becomes visible to workers
    only if the caller commits, so a rolled-back upload never leaves a job."""
    if kind not in HANDLERS:
        raise ValueError(f"No handler registered for job kind {kind!r}")
    job = Job(kind=kind, payload=json.dumps(payload))
    db.add(job)
    db.flush()
    return job


def wake_worker() -> None:
    _wake.set()


def claim_next(db: Session) -> Job | None:
    job = db.scalar(
        select(Job)
        .where(Job.status == "queued", Job.run_after <= _now())
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        db.rollback()
        return None
    job.status = "running"
    job.locked_at = _now()
    job.attempts += 1
    db.commit()
    return job


def requeue_stale(db: Session) -> int:
    result = db.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < _now() - STALE_AFTER)
        .values(status="queued", locked_at=None, run_after=_now())
    )
    db.commit()
    if result.rowcount:
        logger.warning("Requeued %s stale job(s)", result.rowcount)
    return result.rowcount


def _scrub(payload: dict, keys: tuple[str, ...]) -> str:
    return json.dumps({k: v for k, v in payload.items() if k not in keys})


def run_job(job_id: str) -> str:
    """Execute one claimed job. Returns the job's final status for this attempt."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        handler = HANDLERS[job.kind]
        payload = json.loads(job.payload)
        attempts, max_attempts = job.attempts, job.max_attempts
        try:
            handler.run(db, payload)
            job = db.get(Job, job_id)
            job.status = "done"
            job.finished_at = _now()
            job.last_error = None
            job.payload = _scrub(payload, handler.scrub_keys)
            db.commit()
            return "done"
        except Exception as exc:  # noqa: BLE001 — every failure is recorded, never swallowed
            db.rollback()
            final = attempts >= max_attempts
            logger.exception("Job %s (%s) failed on attempt %s/%s", job_id, job.kind, attempts, max_attempts)
            if handler.on_error:
                try:
                    handler.on_error(db, payload, exc, final)
                    db.commit()
                except Exception:  # noqa: BLE001
                    db.rollback()
                    logger.exception("on_error handler failed for job %s", job_id)
            job = db.get(Job, job_id)
            job.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            job.locked_at = None
            if final:
                job.status = "failed"
                job.finished_at = _now()
                job.payload = _scrub(payload, handler.scrub_keys)
            else:
                job.status = "queued"
                job.run_after = _now() + BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]
            db.commit()
            return job.status


def drain(max_jobs: int = 100) -> int:
    """Run ready jobs until none are left. Used by the worker and in inline mode."""
    done = 0
    while done < max_jobs:
        with SessionLocal() as db:
            job = claim_next(db)
            job_id = job.id if job else None
        if job_id is None:
            break
        run_job(job_id)
        done += 1
    return done


def _seconds_until_next_job() -> float:
    with SessionLocal() as db:
        next_at = db.scalar(
            select(Job.run_after).where(Job.status == "queued").order_by(Job.run_after).limit(1)
        )
    if next_at is None:
        return IDLE_POLL_SECONDS
    return max(1.0, min(IDLE_POLL_SECONDS, (_utc(next_at) - _now()).total_seconds()))


class Worker(threading.Thread):
    def __init__(self):
        super().__init__(name="citebase-worker", daemon=True)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        _wake.set()

    def run(self) -> None:
        logger.info("Job worker started")
        while not self._stop_event.is_set():
            try:
                with SessionLocal() as db:
                    requeue_stale(db)
                drain()
                timeout = _seconds_until_next_job()
            except Exception:  # noqa: BLE001 — a DB blip must not kill the worker thread
                logger.exception("Job worker loop error; retrying in 30s")
                timeout = 30
            _wake.wait(timeout)
            _wake.clear()
        logger.info("Job worker stopped")
