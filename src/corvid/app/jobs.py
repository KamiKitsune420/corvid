"""Background job queue with cooperative cancellation and progress reporting.

Long-running work (folder sync, sending, importing) runs off the UI thread. Each
job receives a :class:`JobContext` exposing a cancellation token and a progress
callback. Cancellation is cooperative: jobs must check ``ctx.raise_if_cancelled()``
(or ``ctx.cancelled``) at safe points.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum

from ..errors import JobCancelled
from ..ids import new_id

log = logging.getLogger("corvid.jobs")

ProgressCallback = Callable[[float, str], None]


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CancellationToken:
    """A thread-safe one-shot cancellation flag."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise JobCancelled()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancelled or timeout; returns True if cancelled."""
        return self._event.wait(timeout)


@dataclass(slots=True)
class JobContext:
    """Passed to every job function as its single argument."""

    token: CancellationToken
    _progress_cb: ProgressCallback | None = None

    @property
    def cancelled(self) -> bool:
        return self.token.cancelled

    def raise_if_cancelled(self) -> None:
        self.token.raise_if_cancelled()

    def progress(self, fraction: float, message: str = "") -> None:
        """Report progress in [0.0, 1.0]. Never raises if no listener is attached."""
        if self._progress_cb is not None:
            self._progress_cb(max(0.0, min(1.0, fraction)), message)


@dataclass(slots=True)
class JobHandle[T]:
    """A reference to a submitted job. Returned by :meth:`JobQueue.submit`."""

    id: str
    name: str
    token: CancellationToken
    future: Future[T]
    _running: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        """Request cancellation. Cancels outright if not yet started."""
        self.token.cancel()
        self.future.cancel()  # no-op if already running

    @property
    def status(self) -> JobStatus:
        if self.future.cancelled():
            return JobStatus.CANCELLED
        if not self.future.done():
            return JobStatus.RUNNING if self._running.is_set() else JobStatus.PENDING
        exc = self.future.exception()
        if exc is None:
            return JobStatus.SUCCEEDED
        return JobStatus.CANCELLED if isinstance(exc, JobCancelled) else JobStatus.FAILED

    def result(self, timeout: float | None = None) -> T:
        """Block for the result. Re-raises the job's exception, if any."""
        return self.future.result(timeout)

    def wait(self, timeout: float | None = None) -> bool:
        """Block until done; returns True if finished within the timeout."""
        try:
            self.future.result(timeout)
        except Exception:  # noqa: BLE001 - we only care that it finished
            pass
        return self.future.done()


class JobQueue:
    """A thread-pool-backed queue of cancellable background jobs."""

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers), thread_name_prefix="corvid-job"
        )
        self._handles: dict[str, JobHandle[object]] = {}
        self._lock = threading.Lock()
        self._closed = False

    def submit[T](
        self,
        name: str,
        func: Callable[[JobContext], T],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> JobHandle[T]:
        """Schedule ``func`` to run on a worker thread."""
        if self._closed:
            raise RuntimeError("JobQueue is shut down; cannot submit new jobs.")

        token = CancellationToken()
        ctx = JobContext(token=token, _progress_cb=on_progress)
        running = threading.Event()

        def runner() -> T:
            running.set()
            token.raise_if_cancelled()  # may have been cancelled while queued
            log.debug("job started", extra={"fields": {"job": name}})
            return func(ctx)

        future: Future[T] = self._executor.submit(runner)
        handle = JobHandle(
            id=new_id("job_"), name=name, token=token, future=future, _running=running
        )

        def _on_done(_f: Future[T]) -> None:
            log.debug(
                "job finished", extra={"fields": {"job": name, "status": handle.status.value}}
            )
            with self._lock:
                self._handles.pop(handle.id, None)

        future.add_done_callback(_on_done)
        with self._lock:
            self._handles[handle.id] = handle  # type: ignore[assignment]
        return handle

    def active(self) -> list[JobHandle[object]]:
        with self._lock:
            return list(self._handles.values())

    def cancel_all(self) -> None:
        for handle in self.active():
            handle.cancel()

    def shutdown(self, *, wait: bool = True, cancel: bool = True) -> None:
        """Stop accepting jobs and tear down the worker pool."""
        if self._closed:
            return
        self._closed = True
        if cancel:
            self.cancel_all()
        self._executor.shutdown(wait=wait, cancel_futures=cancel)
