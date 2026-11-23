"""Background job queue with progress and cancellation."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

logger = logging.getLogger("volumax.jobs")


class JobState(Enum):
    PENDING = auto()
    RUNNING = auto()
    PAUSED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class Job:
    id: str
    name: str
    fn: Callable[..., Any]
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    state: JobState = JobState.PENDING
    progress: int = 0  # 0-100
    message: str = ""
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    _cancel_flag: bool = field(default=False, repr=False)
    _pause_flag: bool = field(default=False, repr=False)

    def request_cancel(self) -> None:
        self._cancel_flag = True

    def request_pause(self) -> None:
        self._pause_flag = True

    def request_resume(self) -> None:
        self._pause_flag = False

    def is_cancelled(self) -> bool:
        return self._cancel_flag

    def is_paused(self) -> bool:
        return self._pause_flag


class JobQueue:
    """Simple sequential background job runner."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._wake = threading.Event()
        self._stop = False
        self._listeners: list[Callable[[Job], None]] = []

    def add_listener(self, cb: Callable[[Job], None]) -> None:
        self._listeners.append(cb)

    def _notify(self, job: Job) -> None:
        for cb in self._listeners:
            try:
                cb(job)
            except Exception:
                logger.exception("Job listener error")

    def submit(
        self,
        name: str,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Job:
        job = Job(
            id=str(uuid.uuid4())[:8],
            name=name,
            fn=fn,
            args=args,
            kwargs=kwargs,
        )
        with self._lock:
            self._jobs[job.id] = job
        self._ensure_worker()
        self._wake.set()
        self._notify(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job and job.state in (JobState.PENDING, JobState.RUNNING, JobState.PAUSED):
            job.request_cancel()
            if job.state == JobState.PENDING:
                job.state = JobState.CANCELLED
                job.finished_at = time.time()
                self._notify(job)
            return True
        return False

    def _ensure_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop = False
        self._worker = threading.Thread(target=self._run_loop, daemon=True, name="JobQueue")
        self._worker.start()

    def _run_loop(self) -> None:
        while not self._stop:
            job = self._next_pending()
            if job is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            self._execute(job)

    def _next_pending(self) -> Job | None:
        with self._lock:
            for j in self._jobs.values():
                if j.state == JobState.PENDING:
                    return j
        return None

    def _execute(self, job: Job) -> None:
        job.state = JobState.RUNNING
        job.started_at = time.time()
        job.message = "Running…"
        self._notify(job)

        def progress_cb(pct: int, msg: str = "") -> None:
            job.progress = max(0, min(100, pct))
            if msg:
                job.message = msg
            self._notify(job)

        # Inject helpers if the callable accepts them
        kwargs = dict(job.kwargs)
        if "progress" not in kwargs:
            kwargs["progress"] = progress_cb
        if "cancel" not in kwargs:
            kwargs["cancel"] = job.is_cancelled

        try:
            while job.is_paused() and not job.is_cancelled():
                time.sleep(0.2)

            if job.is_cancelled():
                job.state = JobState.CANCELLED
                job.message = "Cancelled"
            else:
                result = job.fn(*job.args, **kwargs)
                if job.is_cancelled():
                    job.state = JobState.CANCELLED
                    job.message = "Cancelled"
                else:
                    job.result = result
                    job.state = JobState.COMPLETED
                    job.progress = 100
                    job.message = "Completed"
        except Exception as exc:
            logger.exception("Job %s failed", job.id)
            job.state = JobState.FAILED
            job.error = str(exc)
            job.message = f"Failed: {exc}"
        finally:
            job.finished_at = time.time()
            self._notify(job)

    def shutdown(self) -> None:
        self._stop = True
        self._wake.set()
        if self._worker:
            self._worker.join(timeout=5)


# Application-wide queue
_queue: JobQueue | None = None


def get_job_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue()
    return _queue
