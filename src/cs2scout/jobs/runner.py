"""Background jobs (design §5.6 concurrency rule, ADR-005).

- One job per entry at a time; a second request fails with CONFLICT_JOB_RUNNING.
- One parse at a time across the app (``parse_slot``): speed is not a goal (D5) and it caps
  memory at one parse.
- Cancel is cooperative: jobs check ``ctx.cancel`` and pass it to the parse child, which is
  killed immediately.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from cs2scout.store.library import Library

log = logging.getLogger(__name__)


class JobConflict(Exception):
    pass


class JobCancelled(Exception):
    pass


@dataclass
class JobContext:
    job_id: str
    library: Library
    parse_slot: threading.Lock
    cancel: threading.Event = field(default_factory=threading.Event)

    def progress(self, **values) -> None:
        self.library.update_job(self.job_id, progress=values)

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise JobCancelled


class JobRunner:
    def __init__(self, library: Library, workers: int = 4) -> None:
        self.library = library
        self.parse_slot = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cs2scout-job")
        self._lock = threading.Lock()
        self._busy_entries: set[int] = set()
        self._contexts: dict[str, JobContext] = {}

    def submit(self, kind: str, fn: Callable[[JobContext], dict], *, entry_id: int | None = None
               ) -> str:  # fmt: skip
        with self._lock:
            if entry_id is not None and entry_id in self._busy_entries:
                raise JobConflict(f"entry {entry_id} already has a running job")
            if entry_id is not None:
                self._busy_entries.add(entry_id)
            job_id = uuid.uuid4().hex
            ctx = JobContext(job_id, self.library, self.parse_slot)
            self._contexts[job_id] = ctx
        self.library.create_job(job_id, kind, entry_id)
        self._pool.submit(self._run, ctx, fn, entry_id)
        return job_id

    def cancel(self, job_id: str) -> bool:
        ctx = self._contexts.get(job_id)
        if ctx is None:
            return False
        ctx.cancel.set()
        return True

    def busy(self, entry_id: int) -> bool:
        with self._lock:
            return entry_id in self._busy_entries

    def shutdown(self) -> None:
        for ctx in list(self._contexts.values()):
            ctx.cancel.set()
        self._pool.shutdown(wait=True, cancel_futures=True)

    def _run(self, ctx: JobContext, fn: Callable[[JobContext], dict], entry_id: int | None) -> None:
        self.library.update_job(ctx.job_id, state="running")
        try:
            result = fn(ctx)
        except JobCancelled:
            self.library.update_job(ctx.job_id, state="cancelled")
        except Exception as exc:
            log.exception("job %s failed", ctx.job_id)
            self.library.update_job(
                ctx.job_id, state="failed", error=f"{type(exc).__name__}: {exc}"
            )
        else:
            state = "cancelled" if ctx.cancel.is_set() else "done"
            self.library.update_job(ctx.job_id, state=state, result=result)
        finally:
            with self._lock:
                self._busy_entries.discard(entry_id)
                self._contexts.pop(ctx.job_id, None)
