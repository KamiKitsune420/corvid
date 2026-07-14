from __future__ import annotations

import threading

from corvid.app.jobs import JobContext, JobQueue, JobStatus
from corvid.errors import JobCancelled


def test_job_returns_result() -> None:
    queue = JobQueue(max_workers=2)
    try:
        handle = queue.submit("double", lambda ctx: 21 * 2)
        assert handle.result(timeout=5) == 42
        assert handle.status == JobStatus.SUCCEEDED
    finally:
        queue.shutdown()


def test_progress_callback_is_invoked() -> None:
    queue = JobQueue(max_workers=1)
    reports: list[tuple[float, str]] = []

    def work(ctx: JobContext) -> str:
        ctx.progress(0.5, "halfway")
        ctx.progress(1.0, "done")
        return "ok"

    try:
        handle = queue.submit("work", work, on_progress=lambda f, m: reports.append((f, m)))
        assert handle.result(timeout=5) == "ok"
    finally:
        queue.shutdown()
    assert reports == [(0.5, "halfway"), (1.0, "done")]


def test_cooperative_cancellation() -> None:
    queue = JobQueue(max_workers=1)
    started = threading.Event()

    def work(ctx: JobContext) -> str:
        started.set()
        for _ in range(1000):
            ctx.raise_if_cancelled()
            if ctx.token.wait(0.01):
                ctx.raise_if_cancelled()
        return "finished"

    try:
        handle = queue.submit("loop", work)
        assert started.wait(timeout=5)
        handle.cancel()
        handle.wait(timeout=5)
        assert handle.status == JobStatus.CANCELLED
        try:
            handle.result()
        except JobCancelled:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected JobCancelled")
    finally:
        queue.shutdown()


def test_failed_job_reports_failure() -> None:
    queue = JobQueue(max_workers=1)

    def boom(ctx: JobContext) -> None:
        raise ValueError("nope")

    try:
        handle = queue.submit("boom", boom)
        handle.wait(timeout=5)
        assert handle.status == JobStatus.FAILED
    finally:
        queue.shutdown()
